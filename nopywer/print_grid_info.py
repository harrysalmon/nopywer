"""Console reporting for a graph-based electrical analysis run."""

import numpy as np

from .get_constant_parameters import get_constant_parameters
from .graph_model import depth_list_from_graph

try:
    import networkx as nx
except Exception as exc:  # pragma: no cover - dependency import guard
    nx = None
    _NETWORKX_ERROR = exc
else:
    _NETWORKX_ERROR = None


def print_grid_info(G, phase_balance, has_no_phase, root: str = "generator"):
    """Print summary metrics and per-node state from graph attributes.

    Args:
        G: Directed runtime graph containing per-node/edge analysis attributes.
        phase_balance: Phase imbalance percentage at the generator.
        has_no_phase: Spreadsheet row names missing explicit phase allocation.
        root: Root source node for traversal, typically ``generator``.
    """
    if nx is None:
        raise ImportError(f"networkx is required for print_grid_info: {_NETWORKX_ERROR}")
    if not isinstance(G, nx.Graph):
        raise TypeError("print_grid_info expects a NetworkX graph")

    constants = get_constant_parameters()
    V0 = constants["V0"]
    PF = constants["PF"]
    dlist = depth_list_from_graph(G, root=root)

    print("\n === info about the grid === \n")

    total_cum = np.array(G.nodes[root]["cum_power"], dtype=float)
    print(
        f"total power: {1e-3 * np.sum(total_cum):.0f}kW \t {np.round(1e-3 * total_cum, 1)}kW "
        + f"/ {np.round(total_cum / PF / V0)}A"
    )

    phase_flag = " <<<<<<<<<<" if phase_balance > 5 else ""
    print(f"phase balance: {np.round(phase_balance, 1)} % {phase_flag}")

    for deep in range(len(dlist)):
        print(f"\t deepness {deep}")
        for load in dlist[deep]:
            node = G.nodes[load]
            pwr_per_phase = np.round(1e-3 * np.array(node["cum_power"]), 1).tolist()
            pwr_total = 1e-3 * np.sum(node["cum_power"])
            vdrop = float(node.get("vdrop_percent", 0.0))
            vdrop_flag = " <<<<<<<<<<" if vdrop > 5 else ""
            print(
                f"\t\t {load:20} cum_power={pwr_per_phase}kW, total {pwr_total:5.1f}kW, vdrop {vdrop:.1f}% {vdrop_flag} "
            )

    print("\nLoads not connected to a cable:")
    for load in G.nodes():
        if load == root:
            continue
        needs_power = bool(np.double(np.array(G.nodes[load]["power"]) > 0).sum())
        if (G.in_degree(load) == 0) and needs_power:
            print(f"\t{load}")

    print(
        f"\nlist of loads on the spreadsheet that don't have a phase assigned: \n\t{has_no_phase} \n "
    )

    print("total power on other grids: ")
    subgrid_dict = {"tot": 0.0, "msg": ""}
    subgrid = {"red": subgrid_dict.copy(), "yellow": subgrid_dict.copy()}
    for load in G.nodes():
        phase = G.nodes[load].get("phase", None)
        if phase == "U":
            g = "red"
        elif phase == "Y":
            g = "yellow"
        else:
            g = None

        if g is not None:
            subgrid[g]["tot"] += np.array(G.nodes[load]["power"], dtype=float)
            subgrid[g]["msg"] += f"\t\t {load} ({G.nodes[load]['power']}W) \n"

    for subgrid_name, subgrid_val in subgrid.items():
        if isinstance(subgrid_val["tot"], float):
            tot = subgrid_val["tot"]
        elif len(subgrid_val["tot"]) > 1:
            tot = sum(subgrid_val["tot"])
        else:
            tot = subgrid_val["tot"]

        print(f"\t {subgrid_name} grid: {tot / 1e3:.1f}kW / {tot / V0:.1f}A")
        print(subgrid_val["msg"])
