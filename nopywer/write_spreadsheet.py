"""Spreadsheet writer for graph-based analysis outputs."""

import numpy as np
import pandas as pd

try:
    import networkx as nx
except Exception as exc:  # pragma: no cover - dependency import guard
    nx = None
    _NETWORKX_ERROR = exc
else:
    _NETWORKX_ERROR = None


def write_spreadsheet(G, sh) -> None:
    """Write cumulated power columns and grouped tabs from graph attributes.

    Args:
        G: Directed runtime graph with per-node ``cum_power`` and edge metadata.
        sh: Original phase-balance spreadsheet DataFrame.
    """
    if nx is None:
        raise ImportError(f"networkx is required for write_spreadsheet: {_NETWORKX_ERROR}")
    if not isinstance(G, nx.Graph):
        raise TypeError("write_spreadsheet expects a NetworkX graph")

    print("write_spreadsheet...")

    # Drop unnamed columns from spreadsheet import.
    sh = sh.loc[:, ~sh.columns.str.contains("^Unnamed")]

    # Keep only relevant fields and normalize column names for output report.
    sh = sh.drop(columns=["Arrive", "Depart", "daytime power [W]", "nighttime power [W]"])
    sh = sh.rename(
        columns={
            "worstcase power [W]": "power [W]",
            "which phase(1, 2, 3, T, U or Y)": "phase",
        }
    )

    # Drop rows without active power demand.
    sh = sh[sh["power [W]"] != 0]

    for l in range(3):
        sh[f"cumulated power L{l + 1} [kW]"] = "NA"

    for load_on_map in G.nodes():
        idx = [load_on_map in name_on_sheet.lower() for name_on_sheet in sh["Project"]]
        cum = np.array(G.nodes[load_on_map]["cum_power"], dtype=float)
        for l in range(3):
            sh.loc[idx, f"cumulated power L{l + 1} [kW]"] = 1e-3 * cum[l]

        has_parent = G.in_degree(load_on_map) > 0
        if (not any(idx)) and has_parent:
            tmp_dict = {
                "Project": load_on_map,
                "power [W]": 0,
                "current [A]": 0,
                "phase": "NA",
            }
            for l in range(3):
                tmp_dict[f"cumulated power L{l + 1} [kW]"] = 1e-3 * cum[l]
            sh = pd.concat([sh, pd.DataFrame(tmp_dict, index=[0])], ignore_index=True)

    sh["Project"] = [str(i).lower() for i in sh["Project"]]
    sh = sh.sort_values("Project")

    norg_loads = []
    for idx, load_on_sheet in enumerate(sh["Project"]):
        is_on_map = [
            load_on_map for load_on_map in G.nodes() if load_on_map in load_on_sheet.lower()
        ]
        if len(is_on_map) == 1:
            load_on_map = is_on_map[0]
        elif len(is_on_map) > 1:
            load_on_map = [name for name in is_on_map if name == load_on_sheet][0]
        else:
            load_on_map = None

        if (load_on_map is not None) and (G.in_degree(load_on_map) > 0):
            parent = list(G.predecessors(load_on_map))[0]
            cable_layer = G.edges[parent, load_on_map].get("layer_name", "")
            if "norg" in cable_layer:
                norg_loads.append(idx)

    other_loads = [i for j, i in enumerate(range(len(sh))) if j not in norg_loads]
    df_norg = sh.iloc[norg_loads, :]
    df_others = sh.iloc[other_loads, :]

    with pd.ExcelWriter("output.ods") as writer:
        sh.to_excel(writer, sheet_name="all", index=False)
        df_norg.to_excel(writer, sheet_name="norg", index=False)
        df_others.to_excel(writer, sheet_name="other", index=False)
