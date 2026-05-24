"""Tests for the diagnostic logging emitted by `nopywer.io.load_geojson`.

The loader is the project's front door for fixture data and silently
coerces a number of borderline inputs (unknown property keys, legacy
string phase markers). This module pins the warnings/diagnostics that
surface those coercions so they cannot regress to silent behaviour.
"""

import logging

from nopywer.io import load_geojson


def _point_feature(name: str, **extra_props) -> dict:
    """A minimal valid Point feature with whatever extra properties given."""
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
        "properties": {"name": name, "power": 1000.0, **extra_props},
    }


def _line_feature(**props) -> dict:
    """A minimal valid LineString feature with whatever properties given."""
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[0.0, 0.0], [0.001, 0.0]]},
        "properties": props,
    }


def _fc(*features: dict) -> dict:
    return {"type": "FeatureCollection", "features": list(features)}


def test_legacy_string_phase_marker_logs_a_warning(caplog):
    """A node whose `phase` is a string ("U"/"Y") triggers a WARNING.

    What: loading a Point feature with `phase: "U"` produces a
    `logging.WARNING` naming the node and the marker, and the load
    still succeeds with the load spread evenly across L1/L2/L3.

    Why it matters: `"U"` / `"Y"` are legacy sub-grid reporting
    markers with no electrical meaning. They look phase-like in the
    GeoJSON and slip through silently otherwise, which is misleading
    when reading a `runpp_3ph` result. The warning is the operator's
    only signal that the marker propagated as far as the loader.
    """
    caplog.set_level(logging.WARNING, logger="nopywer.io")
    nodes, _ = load_geojson(_fc(_point_feature("stage_left", phase="U")))

    # behaviour: still loads, treated as unphased
    assert nodes["stage_left"].phase == "U"
    assert nodes["stage_left"].power_per_phase.tolist() == [1000.0 / 3] * 3

    # diagnostic: a single warning naming the node and the marker
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "stage_left" in warnings[0].getMessage()
    assert "'U'" in warnings[0].getMessage()


def test_int_phase_emits_no_warning(caplog):
    """A well-formed integer phase does not trigger the legacy-marker warning.

    What: loading a Point feature with `phase: 2` produces no
    `WARNING`-level log records.

    Why it matters: the warning would lose meaning if it fired for
    normal data. This test pins it as legacy-marker-specific.
    """
    caplog.set_level(logging.WARNING, logger="nopywer.io")
    load_geojson(_fc(_point_feature("ok", phase=2)))
    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []


def test_unknown_property_key_logs_a_debug_diagnostic(caplog):
    """An unrecognised property key surfaces at DEBUG level.

    What: loading a Point feature with a property key not in the
    known set (here, the typo `powr` for `power`) produces a
    `logging.DEBUG` record naming the feature and the unknown key.

    Why it matters: `load_geojson` silently ignores unknown keys —
    a typo for a known key (`powr` instead of `power`) would
    otherwise load with the default value and never get flagged.
    DEBUG (not WARNING) because legitimate exports also carry keys
    we don't read; this is a "if you suspect a typo, turn on DEBUG"
    aid, not a noisy default.
    """
    caplog.set_level(logging.DEBUG, logger="nopywer.io")
    load_geojson(_fc(_point_feature("typo_stage", powr=2000.0)))

    debug_records = [
        r for r in caplog.records if r.levelno == logging.DEBUG and "powr" in r.getMessage()
    ]
    assert len(debug_records) == 1
    assert "typo_stage" in debug_records[0].getMessage()


def test_recognised_export_keys_do_not_log(caplog):
    """Computed fields from a round-tripped nopywer export are silent.

    What: loading a Point feature with the full set of computed
    export keys (`voltage`, `vdrop_percent`, `cum_power_watts`,
    `distro`, ...) produces no DEBUG-level records about unknown
    keys.

    Why it matters: round-tripping an export back into the loader
    is the canonical workflow (see doc 11). If the loader warned on
    every computed field, the DEBUG channel would be useless noise
    every time someone reloads their own previous output.
    """
    caplog.set_level(logging.DEBUG, logger="nopywer.io")
    load_geojson(
        _fc(
            _point_feature(
                "exported",
                voltage=228.5,
                vdrop_percent=1.75,
                cum_power_watts=3000.0,
                distro={"in": "3P 32A", "out": {}},
                i_sc_ka=2.5,
                type="load",
            )
        )
    )
    unknown_debugs = [
        r
        for r in caplog.records
        if r.levelno == logging.DEBUG and "not used by load_geojson" in r.getMessage()
    ]
    assert unknown_debugs == []


def test_load_geojson_picks_cable_subclass_from_plugs_and_sockets():
    """`plugs_and_sockets_a` dispatches to the right Cable subclass.

    What: a LineString with `plugs_and_sockets_a=63.0` loads as a
    `Cable63A`, whose `num_phases` ClassVar is 3.

    Why it matters: cable types are a closed catalogue (16/32/63/125 A).
    The loader's job is to pick the right subclass from JSON content,
    not to instantiate a base `Cable` with arbitrary per-instance
    fields. This pins the dispatch table.
    """
    from nopywer.models import Cable63A

    _, cables = load_geojson(
        _fc(
            _line_feature(
                plugs_and_sockets_a=63.0,
                area_mm2=16.0,
                length_m=10.0,
            )
        )
    )

    assert isinstance(cables["cable_0"], Cable63A)
    assert cables["cable_0"].num_phases == 3


def test_load_geojson_warns_when_explicit_phase_count_disagrees_with_subclass(caplog):
    """A fixture phase count that disagrees with the subclass triggers a WARNING.

    What: a LineString with `plugs_and_sockets_a=63.0` and
    `number_of_phases=1` (an impossible combination — 63 A is always
    3-phase) loads as a `Cable63A` (the subclass wins) and emits a
    `WARNING` naming the cable and the disagreement.

    Why it matters: round-tripped exports may carry an explicit
    `number_of_phases`; if a hand-edited fixture sets it to something
    impossible, silently ignoring it would mask the error. The warning
    is the operator's signal that the fixture is internally
    inconsistent.
    """
    from nopywer.models import Cable63A

    caplog.set_level(logging.WARNING, logger="nopywer.io")
    _, cables = load_geojson(
        _fc(
            _line_feature(
                plugs_and_sockets_a=63.0,
                area_mm2=16.0,
                length_m=10.0,
                number_of_phases=1,
            )
        )
    )

    assert isinstance(cables["cable_0"], Cable63A)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "cable_0" in warnings[0].getMessage()
    assert "number_of_phases=1" in warnings[0].getMessage()


def test_load_geojson_warns_on_unknown_plugs_and_sockets_rating(caplog):
    """An unknown plugs-and-sockets rating falls back to Cable16A with a WARNING.

    What: a LineString with `plugs_and_sockets_a=20.0` (not in the
    closed catalogue 16/32/63/125) loads as a `Cable16A` and emits a
    `WARNING` naming the cable and the unrecognised rating.

    Why it matters: catalogues are closed by intent, but legacy or
    hand-authored fixtures may carry odd values. Falling back instead
    of raising lets the loader keep working; the warning makes the
    coercion visible.
    """
    from nopywer.models import Cable16A

    caplog.set_level(logging.WARNING, logger="nopywer.io")
    _, cables = load_geojson(
        _fc(
            _line_feature(
                plugs_and_sockets_a=20.0,
                area_mm2=4.0,
                length_m=10.0,
            )
        )
    )

    assert isinstance(cables["cable_0"], Cable16A)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "cable_0" in warnings[0].getMessage()
    assert "20" in warnings[0].getMessage()
