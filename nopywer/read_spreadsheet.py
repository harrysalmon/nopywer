"""Spreadsheet ingestion for the graph runtime model.

This module reads the phase-balance spreadsheet and writes power/phase
attributes directly onto graph nodes and incoming edges.
"""

import os

import numpy as np
import pandas as pd

try:
    import networkx as nx
except Exception as exc:  # pragma: no cover - dependency import guard
    nx = None
    _NETWORKX_ERROR = exc
else:
    _NETWORKX_ERROR = None


def _load_sheet(project_path: str, sparam: dict) -> pd.DataFrame:
    """Load and validate the phase-balance spreadsheet."""
    headers = {
        "name": "Project",
        "phase": "which phase(1, 2, 3, T, U or Y)",
        "power": "worstcase power [W]",
    }
    sh = pd.read_excel(
        os.path.join(project_path, sparam["name"]),
        sheet_name=sparam["sheet"],
        skiprows=sparam["skiprows"],
        engine="odf",
    )

    for key in headers.values():
        assert key in sh.keys(), (
            f'key "{key}" is not on the spreadsheet. The following keys were found: {sh.keys()}'
        )

    return sh


def _parse_phase(phase, has_no_phase: list, name_on_sheet: str):
    """Parse spreadsheet phase values into canonical runtime forms."""
    if isinstance(phase, int):
        phase_parsed = phase
    elif isinstance(phase, str):
        if len(phase) == 1:
            phase_parsed = phase
            if phase == "X":
                has_no_phase.append(name_on_sheet)
        else:
            phase_parsed = list(map(int, phase.split(",")))
    elif phase == float("nan"):
        has_no_phase.append(name_on_sheet)
        phase_parsed = phase
    else:
        raise ValueError(f"{name_on_sheet} has a wrong phase assigned: {phase}")

    return phase_parsed


def read_spreadsheet(project_path: str, G, sparam: dict):
    """Read load phase/power assignments and populate graph attributes.

    Args:
        project_path: Folder containing the spreadsheet file.
        G: Directed runtime graph whose nodes are map loads.
        sparam: Spreadsheet configuration from ``user_parameters.yaml``.

    Returns:
        Tuple ``(G, has_no_phase, sh)`` where ``G`` has updated ``power`` and
        ``phase`` attributes, ``has_no_phase`` lists rows without phase, and
        ``sh`` is the loaded spreadsheet DataFrame.
    """
    if nx is None:
        raise ImportError(f"networkx is required for read_spreadsheet: {_NETWORKX_ERROR}")
    if not isinstance(G, nx.Graph):
        raise TypeError("read_spreadsheet expects a NetworkX graph")

    verbose = 0
    headers = {
        "name": "Project",
        "phase": "which phase(1, 2, 3, T, U or Y)",
        "power": "worstcase power [W]",
    }

    print("\nReading spreadsheet")
    sh = _load_sheet(project_path, sparam)

    loads_on_map = list(G.nodes())
    loads_on_sheet = list(sh[headers["name"]])
    missing_on_sheet = []
    missing_on_map = []
    has_no_phase = []

    for idx, _ in reversed(list(enumerate(loads_on_sheet))):
        if not isinstance(loads_on_sheet[idx], str):
            loads_on_sheet.pop(idx)

    for load in loads_on_map:
        G.nodes[load]["power"] = np.array([0.0, 0.0, 0.0], dtype=float)
        idx = []
        name_on_map = load.lower().strip()

        for row, x in enumerate(loads_on_sheet):
            name_on_sheet = x.lower().strip()
            is_on_map = (name_on_map in name_on_sheet) and (name_on_map != "generator")
            if not is_on_map:
                continue

            idx.append(row)
            phase = sh[headers["phase"]][row]
            pwr = np.double(sh[headers["power"]][row])
            assert pwr != np.nan, f"load {name_on_sheet} has no power indicated"
            if verbose:
                print(
                    f"\t'{name_on_sheet}' draws {pwr}W on phase {phase} ('{load}' on the map)"
                )

            if pwr > 0:
                phase_parsed = _parse_phase(phase, has_no_phase, name_on_sheet)
                G.nodes[load]["phase"] = phase_parsed

                parents = list(G.predecessors(load))
                if parents:
                    parent = parents[0]
                    G.edges[parent, load]["phase"] = phase_parsed

                if isinstance(phase_parsed, int):
                    G.nodes[load]["power"][phase_parsed - 1] += pwr
                elif isinstance(phase_parsed, list):
                    G.nodes[load]["power"][[p - 1 for p in phase_parsed]] += pwr / len(
                        phase_parsed
                    )
                elif isinstance(phase_parsed, str):
                    if phase == "T":
                        G.nodes[load]["power"] += pwr / 3
            elif pwr == 0:
                if verbose:
                    print(f"'{load}' doesn't draw power but let's keep it anyway :) ")
            else:
                raise ValueError(f'Unable to read "{name_on_sheet}" power usage')

        if (len(idx) == 0) and (load != "generator"):
            missing_on_sheet.append(name_on_map)

    for name_on_sheet in loads_on_sheet:
        idx_on_map = [
            idx
            for idx, name_on_map in enumerate(loads_on_map)
            if name_on_map in name_on_sheet.lower()
        ]
        if len(idx_on_map) == 0:
            missing_on_map.append(name_on_sheet)

    print("\n!!! you should not go any further if some loads on the map are not on spreadsheet:")
    print(f"\t on map but missing on spreadsheet: \n\t {missing_on_sheet}")
    print(f"\n\t on spreadsheet but missing on map: \n\t {missing_on_map}")
    print(
        f"\n list of loads on the spreadsheet that don't have a phase assigned: \n\t {has_no_phase} \n "
    )

    return G, has_no_phase, sh
