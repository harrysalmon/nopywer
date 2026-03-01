import numpy as np

from .graph_model import bfs_order

try:
    import networkx as nx
except Exception:
    nx = None


def _is_graph(obj) -> bool:
    return (nx is not None) and isinstance(obj, nx.Graph)


def cumulate_current_graph(G, V0, PF, root: str = "generator"):
    """Backward sweep directly on graph node/edge attributes."""
    if root not in G:
        return G

    order = bfs_order(G, root=root)
    for node in order:
        G.nodes[node]["cum_power"] = np.array(G.nodes[node].get("power", [0.0, 0.0, 0.0]), dtype=float)

    for parent, child in G.edges():
        G.edges[parent, child]["current"] = []

    for load in reversed(order):
        parents = list(G.predecessors(load))
        if not parents:
            continue
        parent = parents[0]

        G.nodes[parent]["cum_power"] = np.array(
            G.nodes[parent]["cum_power"], dtype=float
        ) + np.array(G.nodes[load]["cum_power"], dtype=float)

        G.edges[parent, load]["current"] = list(
            np.array(G.nodes[load]["cum_power"], dtype=float) / V0 / PF
        )

    return G


def cumulate_current(grid, cables_dict=None, dlist=None, V0=None, PF=None):
    if _is_graph(grid):
        return cumulate_current_graph(grid, V0=V0, PF=PF)

    verbose = 0
    if verbose:
        print("\ncumulate_current.py:")

    for deepness in range(len(dlist) - 1, 0, -1):
        if verbose:
            print(f"\tdeepness: {deepness}")

        loads = dlist[deepness]
        for load in loads:
            parent = grid[load].parent

            # compute cumulated power for the load and its parent...
            grid[load].cum_power += grid[load].power  # ... at load
            grid[parent].cum_power += grid[load].cum_power  # ... and at parent

            # add info to cables_dict
            cable = cables_dict[grid[load].cable["layer"]][grid[load].cable["idx"]]

            # store current TODO: constant power or constant voltage ?
            cable.current = list(grid[load].cum_power / V0 / PF)

            if verbose:
                print(
                    f"\t\t{load} cumulated power: {np.array2string(1e-3 * grid[load].cum_power, precision=1, floatmode='fixed')}kW"
                )

    if verbose:
        load = "generator"
        print(
            f"\t{load} cumulated power: {np.array2string(1e-3 * grid[load]['cum_power'], precision=1, floatmode='fixed')}kW"
        )

    return grid, cables_dict
