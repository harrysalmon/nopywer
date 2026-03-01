"""Backward power sweep on the graph runtime model.

This module computes per-node cumulated downstream power and per-edge phase
currents directly on a directed NetworkX graph.
"""

import numpy as np

from .graph_model import bfs_order

try:
    import networkx as nx
except Exception as exc:  # pragma: no cover - dependency import guard
    nx = None
    _NETWORKX_ERROR = exc
else:
    _NETWORKX_ERROR = None


def cumulate_current(G, V0: float, PF: float, root: str = "generator"):
    """Compute cumulated power and cable current on graph attributes.

    Args:
        G: Directed graph where node attribute ``power`` stores 3-phase load
            power and edge attributes receive ``current``.
        V0: Nominal voltage used to convert power into current.
        PF: Power factor used to convert power into current.
        root: Root source node for traversal, typically ``generator``.

    Returns:
        The same graph instance with updated ``node['cum_power']`` and
        ``edge['current']`` attributes.
    """
    if nx is None:
        raise ImportError(f"networkx is required for cumulate_current: {_NETWORKX_ERROR}")
    if not isinstance(G, nx.Graph):
        raise TypeError("cumulate_current expects a NetworkX graph")
    if root not in G:
        return G

    order = bfs_order(G, root=root)
    for node in order:
        G.nodes[node]["cum_power"] = np.array(
            G.nodes[node].get("power", [0.0, 0.0, 0.0]), dtype=float
        )

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
