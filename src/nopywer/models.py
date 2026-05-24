import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

import numpy as np

from .constants import PF, RHO_COPPER, V0

logger = logging.getLogger(__name__)


def normalise_phase_legs(phase: object, *, node_name: str = "<unnamed>") -> list[int]:
    """Canonical list of leg indices a `phase` field places a load on.

    The single rule used everywhere a load's `phase` field is read:
    `io.load_geojson`, `pp_interop._powerflow_3ph._phase_split` /
    `to_pandapower_3ph`, and `pp_interop.phases._common._fixed_leg_seed`.
    Centralising the rule prevents the three sites from drifting and
    gives one place to log when the input is non-canonical.

    Returns the legs the load occupies, as a list of `int` in 1-3:

      - `1` / `2` / `3` → `[that int]`
      - `[1, 2]` and any non-empty list with at least one valid leg →
        the list filtered to valid ints in 1-3.
      - `None`, a legacy `"U"` / `"Y"` string, an out-of-range int
        (`0`, `4`, `-1`), or a list with no valid legs → `[]`,
        meaning "balanced — spread evenly across all three legs".

    Non-canonical inputs (strings, out-of-range ints, lists with no
    valid legs) emit a `WARNING` naming `node_name` and the value, so
    operators see that the value was coerced rather than honoured.

    Args:
        phase: the raw `phase` field, in any of its forms.
        node_name: name of the node, used only for the warning
            message. Defaults to `"<unnamed>"` for the rare callers
            that don't have a name to hand (e.g. unit tests of the
            helper itself).

    Returns:
        A new list of valid leg indices in 1-3, possibly empty.
    """
    # bool is a subclass of int in Python — exclude it before the int check
    # so `phase=True` doesn't quietly mean "leg 1".
    if isinstance(phase, bool):
        logger.warning(
            "Node %r has phase=%r (a bool, not an int leg index); treating "
            "as unphased (balanced across L1/L2/L3). Valid phase forms are: "
            "int 1/2/3 for a single leg, list like [1, 2] for a multi-phase "
            "load, or None for an unphased / balanced load.",
            node_name,
            phase,
        )
        return []
    if isinstance(phase, int):
        if 1 <= phase <= 3:
            return [phase]
        logger.warning(
            "Node %r has phase=%r outside the valid range 1-3; treating as "
            "unphased (balanced across L1/L2/L3). Valid phase forms are: "
            "int 1/2/3 for a single leg, list like [1, 2] for a multi-phase "
            "load, or None for an unphased / balanced load.",
            node_name,
            phase,
        )
        return []
    if isinstance(phase, list):
        valid = [p for p in phase if isinstance(p, int) and not isinstance(p, bool) and 1 <= p <= 3]
        if valid:
            return valid
        if phase:
            logger.warning(
                "Node %r has phase=%r with no valid legs (every element must "
                "be an int in 1-3); treating as unphased (balanced across "
                "L1/L2/L3).",
                node_name,
                phase,
            )
        return []
    if isinstance(phase, str):
        logger.warning(
            "Node %r carries legacy string phase marker %r; treating as "
            "unphased (balanced across L1/L2/L3). These markers ('U'/'Y') "
            "named sub-grids in older fixtures and have no electrical "
            "meaning — for runpp_3ph the load is routed to the balanced "
            "pp.load table, not net.asymmetric_load. Strip the marker from "
            "the fixture once the sub-grid reporting it came from is no "
            "longer needed; replace it with an int leg (1/2/3) or list "
            "([1, 2]) if you want the load on a specific leg.",
            node_name,
            phase,
        )
        return []
    return []


@dataclass
class PowerNode:
    name: str
    lon: float
    lat: float
    power_watts: float = 0.0
    is_generator: bool = False
    phase: int | str | list | None = None

    parent: str | None = None
    children: dict[str, str] = field(default_factory=dict)
    deepness: int | None = None

    cum_power: np.ndarray = field(default_factory=lambda: np.zeros(3))
    power_per_phase: np.ndarray = field(default_factory=lambda: np.zeros(3))
    voltage: float = 0.0
    vdrop_percent: float = 0.0
    i_sc_ka: float = 0.0

    cable_to_parent: str | None = None

    distro: dict = field(default_factory=lambda: {"in": None, "out": {}})
    distro_chosen: dict | str = field(default_factory=lambda: {"in": None, "out": {}})

    def __setattr__(self, name, value):
        if name == "voltage":
            value = round(value, 1)
        elif name == "vdrop_percent":
            value = round(value, 2)
        elif name == "i_sc_ka":
            value = round(float(value), 4)
        super().__setattr__(name, value)

    def to_geojson(self) -> dict:
        properties = {
            "name": self.name,
            "type": "generator" if self.is_generator else "load",
            "power_watts": round(float(self.power_per_phase.sum()), 1),
            "cum_power_watts": round(float(self.cum_power.sum()), 1),
            "voltage": self.voltage,
            "vdrop_percent": self.vdrop_percent,
            "i_sc_ka": self.i_sc_ka,
            "distro": self.distro,
        }
        # Omit `phase` when unset so unphased exports stay clean; emit it
        # whenever a planner (manual or `pp_interop.phases`) has assigned
        # one, so the choice round-trips through load_geojson.
        if self.phase is not None:
            properties["phase"] = self.phase
        return {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [self.lon, self.lat],
            },
            "properties": properties,
        }


@dataclass
class Cable:
    id: str
    length_m: float
    area_mm2: float = 2.5
    plugs_and_sockets_a: float = 16.0
    phase: int | str | list | None = None

    from_node: str = ""
    to_node: str = ""
    from_coords: tuple[float, float] = (0.0, 0.0)
    to_coords: tuple[float, float] = (0.0, 0.0)

    current_per_phase: list[float] = field(default_factory=list)
    vdrop_volts: float = 0.0

    def __setattr__(self, name, value):
        if name == "current_per_phase" and isinstance(value, list):
            value = [round(c, 2) for c in value]
        elif name == "length_m":
            value = round(value, 1)
        elif name == "vdrop_volts":
            value = round(value, 2)
        super().__setattr__(name, value)

    tier_cost: ClassVar[float] = 1.0
    num_phases: ClassVar[int] = 1
    max_current_a: ClassVar[int] = 16

    @property
    def resistance(self) -> float:
        return RHO_COPPER * self.length_m / self.area_mm2

    def to_geojson(self) -> dict:
        max_current = max(self.current_per_phase) if self.current_per_phase else 0.0
        num_phases = type(self).num_phases
        cum_power_w = max_current * V0 * PF * num_phases
        cable_type = f"{num_phases}P {self.plugs_and_sockets_a:.0f}A — {self.area_mm2}mm²"
        return {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [list(self.from_coords), list(self.to_coords)],
            },
            "properties": {
                "id": self.id,
                "nodes": [self.from_node, self.to_node],
                "from": self.from_node,
                "to": self.to_node,
                "length_m": self.length_m,
                "area_mm2": self.area_mm2,
                "plugs_and_sockets_a": self.plugs_and_sockets_a,
                "number_of_phases": num_phases,
                "cable_type": cable_type,
                "current_a": round(max_current, 1),
                "cum_power_kw": round(cum_power_w / 1000, 2),
                "vdrop_volts": self.vdrop_volts,
            },
        }


# tier costs are approximative but not completely off
# A 32A cable costs about 3 times more per meter than a 16A cable, and so on.
@dataclass
class Cable16A(Cable):
    tier_cost: ClassVar[float] = 1.0
    num_phases: ClassVar[int] = 1
    max_current_a: ClassVar[int] = 16


@dataclass
class Cable32A(Cable):
    tier_cost: ClassVar[float] = 3.0
    num_phases: ClassVar[int] = 3
    max_current_a: ClassVar[int] = 32
    area_mm2: float = 6.0
    plugs_and_sockets_a: float = 32.0


@dataclass
class Cable63A(Cable):
    tier_cost: ClassVar[float] = 8.0
    num_phases: ClassVar[int] = 3
    max_current_a: ClassVar[int] = 63
    area_mm2: float = 16.0
    plugs_and_sockets_a: float = 63.0


@dataclass
class Cable125A(Cable):
    tier_cost: ClassVar[float] = 20.0
    num_phases: ClassVar[int] = 3
    max_current_a: ClassVar[int] = 125
    area_mm2: float = 35.0
    plugs_and_sockets_a: float = 125.0


_CABLE_TYPES: list[type[Cable]] = [Cable16A, Cable32A, Cable63A, Cable125A]


def pick_cable_for(power_watts: float) -> type[Cable]:
    """Pick the smallest cable type that can handle the given power.

    Each type is checked with: I = P / (num_phases x V0 x PF)
    """
    for cable_cls in _CABLE_TYPES:
        if power_watts / (cable_cls.num_phases * V0 * PF) <= cable_cls.max_current_a:
            return cable_cls
    return _CABLE_TYPES[-1]


@dataclass
class PowerGrid:
    nodes: dict[str, PowerNode]
    cables: dict[str, Cable]
    generator: PowerNode = field(init=False, repr=False)
    tree: list[list[str]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        generators = [node for node in self.nodes.values() if node.is_generator]
        if not generators:
            raise ValueError("At least one generator is required")
        if len(generators) > 1:
            raise ValueError("Only one generator is supported for now")
        self.generator = generators[0]

    @classmethod
    def from_geojson(cls, source: str | Path | dict) -> "PowerGrid":
        from .io import load_geojson

        nodes, cables = load_geojson(source)
        return cls(nodes=nodes, cables=cables)

    def to_geojson(self) -> dict:
        features = [cable.to_geojson() for cable in self.cables.values()]
        features += [node.to_geojson() for node in self.nodes.values()]
        return {"type": "FeatureCollection", "features": features}
