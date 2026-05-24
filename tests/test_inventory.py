"""Tests for the cable / distro inventory matchers.

Every test in this module fabricates its own one- or two-row ODS file
on the fly via `_write_ods`. There is no real inventory shipped in the
repo; each test ships exactly the rows it needs to exercise one
matching path, so the inventory contents are visible inline.
"""

from pathlib import Path

import pandas as pd

from nopywer.inventory import (
    choose_cables,
    choose_distros,
)
from nopywer.models import Cable32A, Cable63A, PowerNode


def _write_ods(path: Path, sheet_name: str, data: pd.DataFrame) -> None:
    """Write a synthetic inventory sheet for a single test to consume."""
    with pd.ExcelWriter(path, engine="odf") as writer:
        data.to_excel(writer, sheet_name=sheet_name, index=False)


def test_choose_cables_in_inventory_nominal_case(tmp_path, caplog):
    inventory_file = tmp_path / "cables_inventory.ods"
    _write_ods(
        inventory_file,
        "cables",
        pd.DataFrame(
            [
                {
                    "number of phases": 3,
                    "plugs&sockets [A]": 32.0,
                    "section [mm2]": 6.0,
                    "quantity": 1,
                    "length [m]": 11.0,  # algo is only happy if inventory has a lil bit more
                }
            ]
        ),
    )

    cables = {
        "c1": Cable32A(
            id="c1",
            length_m=10.0,
            from_node="generator",
            to_node="load_a",
        )
    }

    caplog.set_level("INFO", logger="nopywer.inventory")
    choose_cables(str(inventory_file), cables)

    assert "Reading cables inventory" in caplog.text
    assert "generator-load_a" not in caplog.text


def test_choose_cables_picks_phase_count_from_subclass(tmp_path, caplog):
    """`choose_cables` reads `num_phases` from the cable subclass.

    A Cable63A in the grid must match a 3-phase entry in the inventory.
    Cable types are a closed catalogue — a 63 A cable is always 3-phase
    — so this test exists to pin that the inventory matcher uses the
    subclass's `num_phases` ClassVar, not any per-instance override.
    """
    inventory_file = tmp_path / "cables_inventory.ods"
    _write_ods(
        inventory_file,
        "cables",
        pd.DataFrame(
            [
                {
                    "number of phases": 3,
                    "plugs&sockets [A]": 63.0,
                    "section [mm2]": 16.0,
                    "quantity": 1,
                    "length [m]": 11.0,
                }
            ]
        ),
    )

    cables = {
        "c1": Cable63A(
            id="c1",
            length_m=10.0,
            from_node="generator",
            to_node="load_a",
        )
    }

    caplog.set_level("INFO", logger="nopywer.inventory")
    choose_cables(str(inventory_file), cables)

    assert "generator-load_a" not in caplog.text


def test_choose_distros_in_inventory_nominal_case(tmp_path):
    inventory_file = tmp_path / "distros_inventory.ods"
    _write_ods(
        inventory_file,
        "distros",
        pd.DataFrame(
            [
                {
                    "input - type": "3P",
                    "input - current [A]": 63.0,
                    "3P output - current [A]": 32.0,
                    "3P output - quantity": 1.0,
                    "3P 2nd output - current [A]": None,
                    "3P 2nd output - quantity": None,
                    "1P output - current [A]": None,
                    "1P output - quantity": None,
                    "how many distros": 1,
                }
            ]
        ),
    )

    grid = {
        "load_a": PowerNode(
            name="load_a",
            lon=0.0,
            lat=0.0,
            distro={"in": "3P 63A", "out": {"3P 32A": 1}},
        )
    }

    updated_grid = choose_distros(str(inventory_file), grid)

    assert updated_grid["load_a"].distro_chosen == {
        "in": "3P - 63A",
        "out": ["3P - 32A (x1)"],
    }
