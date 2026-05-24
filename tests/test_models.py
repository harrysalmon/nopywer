"""Tests for the core data model in `nopywer.models`.

Covers:
- `pick_cable_for` — picks the smallest cable tier that can carry the
  power, dispatching on the subclass `num_phases` / `max_current_a`
  ClassVars.
- `Cable.to_geojson` and the Cable subclass hierarchy — the
  subclass IS the cable type, and `to_geojson` reads its `num_phases`
  ClassVar (not any per-instance override).
- `PowerNode.to_geojson` — round-trip semantics for the polymorphic
  `phase` field (omitted when None, emitted in any other form).
- `PowerGrid` construction invariants — exactly one generator.
- Field rounding side-effects on `__setattr__`.
- `normalise_phase_legs` — the single source-of-truth helper for
  what each `phase` value means; pinned across every input form so
  the three call sites in `io.load_geojson`,
  `pp_interop._powerflow_3ph` and `pp_interop.phases._common` cannot
  drift.
"""

import logging

import numpy as np
import pytest

from nopywer.models import (
    Cable,
    Cable16A,
    Cable32A,
    Cable63A,
    Cable125A,
    PowerGrid,
    PowerNode,
    normalise_phase_legs,
    pick_cable_for,
)


@pytest.mark.parametrize(
    "power_watts, expected_cls",
    [
        (0, Cable16A),
        (1000, Cable16A),
        (3312, Cable16A),
        (3313, Cable32A),
        (10_000, Cable32A),
        (19_872, Cable32A),
        (19_873, Cable63A),
        (39_123, Cable63A),
        (39_124, Cable125A),
        (77_625, Cable125A),
        (100_000, Cable125A),
    ],
)
def test_pick_cable_for(power_watts, expected_cls):
    assert pick_cable_for(power_watts) is expected_cls


def test_cable_to_geojson():
    cable = Cable32A(
        id="c1",
        length_m=25.5,
        from_node="gen",
        to_node="load_a",
        from_coords=(2.35, 48.85),
        to_coords=(2.36, 48.86),
        current_per_phase=[10.5, 10.5, 10.5],
        vdrop_volts=1.23,
    )
    gj = cable.to_geojson()

    assert gj["type"] == "Feature"
    assert gj["geometry"]["type"] == "LineString"
    assert gj["geometry"]["coordinates"] == [[2.35, 48.85], [2.36, 48.86]]

    props = gj["properties"]
    assert props["id"] == "c1"
    assert props["nodes"] == ["gen", "load_a"]
    assert props["from"] == "gen"
    assert props["to"] == "load_a"
    assert props["length_m"] == 25.5
    assert props["area_mm2"] == 6.0
    assert props["plugs_and_sockets_a"] == 32.0
    assert props["number_of_phases"] == 3
    assert props["cable_type"] == "3P 32A — 6.0mm²"
    assert props["current_a"] == 10.5
    assert props["cum_power_kw"] == 6.52
    assert props["vdrop_volts"] == 1.23


def test_cable_to_geojson_uses_subclass_phase_count():
    """The cable subclass dictates the exported phase count.

    Cable types are a closed catalogue: a Cable16A is always 1-phase, a
    Cable32A always 3-phase, etc. Per-instance phase overrides are not
    representable — that's the whole point of the subclass-as-type
    design. This test pins that `to_geojson` reads `num_phases` from
    the class, not from any instance attribute.
    """
    cable = Cable63A(id="c1", length_m=10.0, current_per_phase=[10.0, 10.0, 10.0])
    props = cable.to_geojson()["properties"]

    assert props["number_of_phases"] == 3
    assert props["cable_type"] == "3P 63A — 16.0mm²"
    # 10 A * 230 V * 0.9 PF * 3 phases = 6.21 kW
    assert props["cum_power_kw"] == 6.21


def test_power_node_to_geojson():
    node = PowerNode(
        name="bar_south",
        lon=2.35,
        lat=48.85,
        power_watts=3000.0,
        power_per_phase=np.array([1000.0, 1000.0, 1000.0]),
        cum_power=np.array([2000.0, 2000.0, 2000.0]),
        voltage=228.5,
        vdrop_percent=1.75,
        distro={"in": "3P 32A", "out": {"1P 16A": 2}},
    )
    gj = node.to_geojson()

    assert gj["type"] == "Feature"
    assert gj["geometry"]["type"] == "Point"
    assert gj["geometry"]["coordinates"] == [2.35, 48.85]

    props = gj["properties"]
    assert props["name"] == "bar_south"
    assert props["type"] == "load"
    assert props["power_watts"] == 3000.0
    assert props["cum_power_watts"] == 6000.0
    assert props["voltage"] == 228.5
    assert props["vdrop_percent"] == 1.75
    assert props["distro"] == {"in": "3P 32A", "out": {"1P 16A": 2}}
    # phase is None on this node and is intentionally omitted from the
    # export, not emitted as `"phase": null`.
    assert "phase" not in props


def test_power_node_to_geojson_emits_phase_when_set():
    """Phase is emitted whenever it is non-None, in any form it can take.

    What: an int phase, a multi-phase list, and a legacy string marker
    all appear in the exported properties; only `phase=None` is
    omitted.

    Why it matters: this is the round-trip contract for
    `pp_interop.phases`. A planner assigns `phase` on the grid via
    `apply_assignment`; that choice has to survive a `to_geojson`
    → `load_geojson` cycle, otherwise committing a plan to a fixture
    silently loses it.
    """
    int_phase = PowerNode(name="a", lon=0, lat=0, phase=2)
    list_phase = PowerNode(name="b", lon=0, lat=0, phase=[1, 2])
    str_phase = PowerNode(name="c", lon=0, lat=0, phase="U")

    assert int_phase.to_geojson()["properties"]["phase"] == 2
    assert list_phase.to_geojson()["properties"]["phase"] == [1, 2]
    assert str_phase.to_geojson()["properties"]["phase"] == "U"


def test_generator_node_to_geojson():
    node = PowerNode(name="generator", lon=0.0, lat=0.0, is_generator=True)
    assert node.to_geojson()["properties"]["type"] == "generator"


def test_power_grid_resolves_generator_once():
    generator = PowerNode(name="generator", lon=0.0, lat=0.0, is_generator=True)
    load = PowerNode(name="load_a", lon=1.0, lat=1.0)

    grid = PowerGrid(nodes={"generator": generator, "load_a": load}, cables={})

    assert grid.generator is generator


def test_power_grid_to_geojson_includes_nodes_and_cables():
    generator = PowerNode(name="generator", lon=0.0, lat=0.0, is_generator=True)
    load = PowerNode(name="load_a", lon=1.0, lat=1.0)
    cable = Cable(id="c1", length_m=10.0, from_node="generator", to_node="load_a")

    grid = PowerGrid(
        nodes={"generator": generator, "load_a": load},
        cables={"c1": cable},
    )

    geojson = grid.to_geojson()

    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) == 3


def test_cable_rounds_on_set():
    cable = Cable(id="c", length_m=12.3456)
    assert cable.length_m == 12.3

    cable.vdrop_volts = 1.23456
    assert cable.vdrop_volts == 1.23

    cable.current_per_phase = [10.556, 10.556, 10.556]
    assert cable.current_per_phase == [10.56, 10.56, 10.56]


def test_power_node_rounds_on_set():
    node = PowerNode(name="n", lon=0.0, lat=0.0, voltage=228.777)
    assert node.voltage == 228.8

    node.vdrop_percent = 1.23456
    assert node.vdrop_percent == 1.23


# --- normalise_phase_legs ----------------------------------------------------


@pytest.mark.parametrize(
    "phase, expected",
    [
        # canonical single-leg forms
        (1, [1]),
        (2, [2]),
        (3, [3]),
        # canonical multi-leg form — listed legs preserved in order
        ([1, 2], [1, 2]),
        ([1, 2, 3], [1, 2, 3]),
        ([3, 1], [3, 1]),
        # canonical balanced sentinel
        (None, []),
    ],
)
def test_normalise_phase_legs_canonical_forms_pass_through(phase, expected, caplog):
    """Every canonical `phase` form returns its documented leg list with no warning.

    What: ints 1/2/3 wrap into single-element lists; lists of valid
    leg indices pass through with their order preserved (the order is
    not semantically meaningful but is preserved for stable hashing /
    diffing); `None` returns the empty list (balanced).

    Why it matters: these are the only forms a fixture author or
    planner is expected to write. Any one of them firing a WARNING
    would mean the helper had become noisy for normal data, which
    would erode the signal value of the warning channel for the
    actually-non-canonical cases below.
    """
    caplog.set_level(logging.WARNING, logger="nopywer.models")
    assert normalise_phase_legs(phase) == expected
    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []


@pytest.mark.parametrize(
    "phase",
    [0, 4, -1, 5, 100],
)
def test_normalise_phase_legs_out_of_range_int_coerces_to_balanced_with_warning(phase, caplog):
    """An int outside 1-3 is coerced to balanced and surfaces a WARNING.

    What: a `phase` value like `0`, `4`, or `-1` returns `[]` (meaning
    "balanced — spread evenly across L1/L2/L3") and emits a
    `WARNING`-level record naming the node and the offending value.

    Why it matters: before this helper existed, an out-of-range int
    silently fell through to a balanced split inside `_phase_split`
    and `_fixed_leg_seed` — but in `to_pandapower_3ph` it would land
    in `net.asymmetric_load` with three equal P's, mislabelling a
    balanced load as asymmetric. Routing that decision through the
    helper means the coercion is visible (the warning) and consistent
    (the empty list always means balanced everywhere it is consumed).
    """
    caplog.set_level(logging.WARNING, logger="nopywer.models")
    assert normalise_phase_legs(phase, node_name="bad_node") == []
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "bad_node" in warnings[0].getMessage()
    assert str(phase) in warnings[0].getMessage()


@pytest.mark.parametrize(
    "phase, expected",
    [
        ([1, 5], [1]),  # mixed: valid leg + invalid leg
        ([2, 0, 3], [2, 3]),  # invalid in the middle
        ([3, 4, 5, 1], [3, 1]),  # multiple invalids surrounded by valids
    ],
)
def test_normalise_phase_legs_list_silently_filters_invalid_when_some_valid_legs_remain(
    phase, expected, caplog
):
    """A list with mixed valid / invalid legs keeps the valid ones, silently.

    What: a list like `[1, 5]` returns `[1]` and emits no WARNING.

    Why it matters: a multi-phase load that happens to carry a stray
    out-of-range int in its phase list is best treated as "use the
    valid legs the operator clearly meant", not "silently fall back to
    balanced just because one element was wrong". Warning here would
    be noise — the load's actual leg placement isn't ambiguous. The
    fully-malformed case is covered by the test below.
    """
    caplog.set_level(logging.WARNING, logger="nopywer.models")
    assert normalise_phase_legs(phase) == expected
    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []


@pytest.mark.parametrize(
    "phase",
    [[5, 9], [0], [-1, 100], ["x", "y"], [None]],
)
def test_normalise_phase_legs_list_with_no_valid_legs_coerces_to_balanced_with_warning(
    phase, caplog
):
    """A non-empty list with no valid legs coerces to balanced with a WARNING.

    What: a list like `[5, 9]` or `["x", "y"]` returns `[]` and emits
    a `WARNING` naming the node and the list.

    Why it matters: an entirely malformed list is genuinely ambiguous
    — the operator intended *some* per-leg placement but every element
    is unusable. Falling back to balanced is the only safe default;
    the warning makes the silent fallback visible so a fixture author
    can fix the typo. Contrast with the mixed-valid case above, which
    is unambiguous and stays silent.
    """
    caplog.set_level(logging.WARNING, logger="nopywer.models")
    assert normalise_phase_legs(phase, node_name="malformed") == []
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "malformed" in warnings[0].getMessage()


def test_normalise_phase_legs_empty_list_is_balanced_no_warning(caplog):
    """An empty list is the same as `None` — balanced, with no WARNING.

    What: `phase=[]` returns `[]` and emits no warning.

    Why it matters: an empty list is the natural representation of
    "no legs selected, but the field exists" — e.g. a planner that
    cleared the assignment. It is not malformed (no values to be
    wrong), so it should be silent. This pins that the helper does
    not warn on this shape.
    """
    caplog.set_level(logging.WARNING, logger="nopywer.models")
    assert normalise_phase_legs([]) == []
    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []


@pytest.mark.parametrize("marker", ["U", "Y", "u", "y"])
def test_normalise_phase_legs_legacy_string_marker_coerces_to_balanced_with_warning(marker, caplog):
    """A legacy `"U"` / `"Y"` string marker coerces to balanced with a WARNING.

    What: `phase="U"` (or `"Y"`, case-sensitive in older fixtures)
    returns `[]` and emits a `WARNING` that names the node, the
    marker, and the migration guidance (replace with an int leg or
    list, or strip once sub-grid reporting is no longer needed).

    Why it matters: these are legacy sub-grid reporting markers with
    no electrical meaning. Without the warning they would silently
    behave like an unphased load while still looking phase-like in
    the fixture — confusing when reading a `runpp_3ph` result. The
    warning is the operator's signal that the marker propagated as
    far as the model layer.
    """
    caplog.set_level(logging.WARNING, logger="nopywer.models")
    assert normalise_phase_legs(marker, node_name="stage_left") == []
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "stage_left" in warnings[0].getMessage()
    assert repr(marker) in warnings[0].getMessage()


@pytest.mark.parametrize("phase", [True, False])
def test_normalise_phase_legs_bool_coerces_to_balanced_with_warning(phase, caplog):
    """A bool `phase` is coerced to balanced (not treated as 0/1) with a WARNING.

    What: `phase=True` (or `False`) returns `[]` and emits a WARNING.

    Why it matters: `bool` is a subclass of `int` in Python, so a
    naive `isinstance(phase, int)` check would have `True` quietly
    mean "leg 1" and `False` mean "leg 0" (an out-of-range coercion
    again). The helper short-circuits on `bool` first to avoid that
    foot-gun. This test pins that decision against a future refactor
    that re-orders the type checks.
    """
    caplog.set_level(logging.WARNING, logger="nopywer.models")
    assert normalise_phase_legs(phase, node_name="bool_node") == []
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "bool_node" in warnings[0].getMessage()


def test_normalise_phase_legs_default_node_name_in_warning(caplog):
    """When called without `node_name`, the warning uses a placeholder.

    What: `normalise_phase_legs("U")` (no `node_name=`) still emits a
    WARNING and the placeholder `"<unnamed>"` appears in the message.

    Why it matters: the helper is callable in isolation (unit tests
    parametrise across every form). Forgetting to pass `node_name`
    must not crash or emit a silent warning — it must still be
    traceable. The placeholder makes the omission obvious to a log
    reader.
    """
    caplog.set_level(logging.WARNING, logger="nopywer.models")
    assert normalise_phase_legs("U") == []
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "<unnamed>" in warnings[0].getMessage()
