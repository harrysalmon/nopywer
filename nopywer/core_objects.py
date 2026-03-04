"""Domain containers for import-time node/cable data.

Historical TODOs preserved from the previous property-heavy implementation:
- check attribute values for each field (now done in ``__post_init__``)
- add helper strings for easier debugging/printing (partially covered by ``__str__``)
"""

from dataclasses import dataclass, field
from numbers import Real
from typing import Any, ClassVar

import numpy as np
from qgis.core import QgsPointXY


PhaseType = int | str | list[int] | None


def _validate_phase(value: Any, *, where: str) -> None:
    if value is None:
        return
    if isinstance(value, int):
        return
    if isinstance(value, str):
        return
    if isinstance(value, list) and all(isinstance(v, int) for v in value):
        return
    raise TypeError(f"{where} must be int | str | list[int] | None, got {type(value)}")


def _as_phase_vector(value: Any, *, where: str) -> np.ndarray:
    out = np.array(value, dtype=float)
    if out.shape != (3,):
        raise ValueError(f"{where} must be a 3-phase vector, got shape {out.shape}")
    return out


@dataclass(slots=True)
class Cable:
    """Import-time cable container used before edge attributes are built on the graph."""

    length: float
    area: float
    plugs_and_sockets: float
    nodes: list[str] = field(default_factory=list)
    current: list[float] = field(default_factory=list)
    phase: PhaseType = None
    vdrop_volts: float = 0.0
    coordinates: list[QgsPointXY] = field(default_factory=list)
    layer_name: str = ""
    id: int = -1

    rho: ClassVar[float] = 1 / 26  # [ohm / (m*mm2)] for copper

    def __post_init__(self) -> None:
        if (not isinstance(self.length, Real)) or isinstance(self.length, bool):
            raise TypeError(f"length must be numeric, got {type(self.length)}")
        if float(self.length) <= 0:
            raise ValueError("length must be > 0")
        self.length = float(self.length)

        if (not isinstance(self.area, Real)) or isinstance(self.area, bool):
            raise TypeError(f"area must be numeric, got {type(self.area)}")
        if float(self.area) <= 0:
            raise ValueError("area must be > 0")
        self.area = float(self.area)

        if (not isinstance(self.plugs_and_sockets, Real)) or isinstance(
            self.plugs_and_sockets, bool
        ):
            raise TypeError(
                f"plugs_and_sockets must be numeric, got {type(self.plugs_and_sockets)}"
            )
        self.plugs_and_sockets = float(self.plugs_and_sockets)

        if not isinstance(self.nodes, list):
            raise TypeError(f"nodes must be a list, got {type(self.nodes)}")
        if not isinstance(self.current, list):
            raise TypeError(f"current must be a list, got {type(self.current)}")
        if not isinstance(self.coordinates, list):
            raise TypeError(f"coordinates must be a list, got {type(self.coordinates)}")
        if (self.layer_name is not None) and (not isinstance(self.layer_name, str)):
            raise TypeError(f"layer_name must be a str, got {type(self.layer_name)}")
        if (self.id is not None) and (not isinstance(self.id, int)):
            raise TypeError(f"id must be an int, got {type(self.id)}")
        _validate_phase(self.phase, where="cable.phase")

        if (not isinstance(self.vdrop_volts, Real)) or isinstance(self.vdrop_volts, bool):
            raise TypeError(f"vdrop_volts must be numeric, got {type(self.vdrop_volts)}")
        self.vdrop_volts = float(self.vdrop_volts)

    @property
    def r(self) -> float:
        """Cable resistance in Ohms."""
        return self.rho * self.length / self.area

    def __str__(self) -> str:
        return (
            f"Cable {self.id + 1} from layer {self.layer_name}, "
            f"between {self.nodes}. Length {self.length:.1f}m."
        )


@dataclass(slots=True)
class Node:
    """Import-time node container used before node attributes are built on the graph."""

    name: str
    parent: str | None = None
    children: dict = field(default_factory=dict)
    deepness: int | None = None
    cable: dict = field(default_factory=dict)
    cables: list = field(default_factory=list)
    power: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=float))
    phase: PhaseType = None
    cum_power: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=float))
    distro: dict = field(default_factory=lambda: dict.fromkeys(["in", "out"]))
    distro_chosen: dict | str = field(default_factory=lambda: dict.fromkeys(["in", "out"]))
    coordinates: QgsPointXY | None = None
    voltage: float = 0.0
    vdrop_percent: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise TypeError(f"name must be str, got {type(self.name)}")
        if (self.parent is not None) and (not isinstance(self.parent, str)):
            raise TypeError(f"parent must be str | None, got {type(self.parent)}")
        if not isinstance(self.children, dict):
            raise TypeError(f"children must be dict, got {type(self.children)}")
        if (self.deepness is not None) and (not isinstance(self.deepness, int)):
            raise TypeError(f"deepness must be int | None, got {type(self.deepness)}")
        if not isinstance(self.cable, dict):
            raise TypeError(f"cable must be dict, got {type(self.cable)}")
        if not isinstance(self.cables, list):
            raise TypeError(f"cables must be list, got {type(self.cables)}")

        _validate_phase(self.phase, where="node.phase")
        self.power = _as_phase_vector(self.power, where="node.power")
        self.cum_power = _as_phase_vector(self.cum_power, where="node.cum_power")

        if not isinstance(self.distro, dict):
            raise TypeError(f"distro must be dict, got {type(self.distro)}")
        if not isinstance(self.distro_chosen, (dict, str)):
            raise TypeError(
                f"distro_chosen must be dict | str, got {type(self.distro_chosen)}"
            )
        if (self.coordinates is not None) and (not isinstance(self.coordinates, QgsPointXY)):
            raise TypeError(f"coordinates must be QgsPointXY | None, got {type(self.coordinates)}")
        if (not isinstance(self.voltage, Real)) or isinstance(self.voltage, bool):
            raise TypeError(f"voltage must be numeric, got {type(self.voltage)}")
        if (not isinstance(self.vdrop_percent, Real)) or isinstance(
            self.vdrop_percent, bool
        ):
            raise TypeError(
                f"vdrop_percent must be numeric, got {type(self.vdrop_percent)}"
            )
        self.voltage = float(self.voltage)
        self.vdrop_percent = float(self.vdrop_percent)
