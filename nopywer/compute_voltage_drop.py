"""Forward voltage-drop sweep on the graph runtime model."""

import numpy as np

from .get_constant_parameters import get_constant_parameters

try:
    import networkx as nx
except Exception as exc:  # pragma: no cover - dependency import guard
    nx = None
    _NETWORKX_ERROR = exc
else:
    _NETWORKX_ERROR = None

# vdrop threshold in %, above which a warning is printed
THRESHOLD_PERCENT = 5
CONSTANTS = get_constant_parameters()
V0 = CONSTANTS["V0"]
VDROP_REF = np.sqrt(3) * V0
VDROP_COEF = 1


def compute_voltage_drop(G, root: str = "generator"):
    """Compute per-edge voltage drop and per-node voltage on the graph.

    Args:
        G: Directed graph with ``edge['resistance']`` and ``edge['current']``.
        root: Root source node for traversal, typically ``generator``.

    Returns:
        The same graph instance with updated ``edge['vdrop_volts']``,
        ``node['voltage']``, and ``node['vdrop_percent']`` attributes.
    """
    if nx is None:
        raise ImportError(
            f"networkx is required for compute_voltage_drop: {_NETWORKX_ERROR}"
        )
    if not isinstance(G, nx.Graph):
        raise TypeError("compute_voltage_drop expects a NetworkX graph")
    if root not in G:
        return G

    for node in G.nodes():
        G.nodes[node]["voltage"] = float(0.0)
        G.nodes[node]["vdrop_percent"] = float(0.0)

    G.nodes[root]["voltage"] = float(V0)
    G.nodes[root]["vdrop_percent"] = 0.0

    for parent, load in nx.bfs_edges(G, root):
        edge = G.edges[parent, load]
        resistance = float(edge.get("resistance", 0.0))
        current = edge.get("current", []) or []
        max_current = float(np.max(current)) if len(current) > 0 else 0.0
        edge["vdrop_volts"] = float(VDROP_COEF * resistance * max_current)

        G.nodes[load]["voltage"] = float(G.nodes[parent]["voltage"] - edge["vdrop_volts"])
        G.nodes[load]["vdrop_percent"] = float(
            100 * (V0 - G.nodes[load]["voltage"]) / VDROP_REF
        )

        if G.nodes[load]["vdrop_percent"] > THRESHOLD_PERCENT:
            print(f"\t /!\\ vdrop of {G.nodes[load]['vdrop_percent']:.1f} percent at {load}")

    return G
