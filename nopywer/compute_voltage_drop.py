"""Forward voltage-drop sweep on the graph runtime model."""

from numbers import Real

import networkx as nx
import numpy as np

from .get_constant_parameters import get_constant_parameters

# vdrop threshold in %, above which a warning is printed
THRESHOLD_PERCENT = 5
CONSTANTS = get_constant_parameters()
V0 = CONSTANTS["V0"]
VDROP_REF = np.sqrt(3) * V0
VDROP_COEF = 1


def _validate_voltage_drop_inputs(G: nx.DiGraph, root: str):
    """Validate graph shape and required edge attributes once, upfront."""
    if not isinstance(G, nx.DiGraph):
        raise TypeError("compute_voltage_drop expects a networkx.DiGraph")
    if root not in G:
        raise KeyError(f"root node '{root}' is missing from graph")

    bfs_edges = list(nx.bfs_edges(G, root))
    for parent, load in bfs_edges:
        edge = G.edges[parent, load]
        resistance = edge.get("resistance", None)
        if (resistance is None) or isinstance(resistance, bool) or (
            not isinstance(resistance, Real)
        ):
            raise KeyError(
                f"edge ({parent}, {load}) must define numeric 'resistance'"
            )

        current = edge.get("current", None)
        if (current is None) or (not isinstance(current, (list, tuple, np.ndarray))):
            raise KeyError(
                f"edge ({parent}, {load}) must define non-empty numeric 'current'"
            )
        if len(current) == 0:
            raise ValueError(f"edge ({parent}, {load}) has empty 'current'")
        if any(isinstance(v, bool) or (not isinstance(v, Real)) for v in current):
            raise TypeError(f"edge ({parent}, {load}) has non-numeric 'current'")

    return bfs_edges


def compute_voltage_drop(G: nx.DiGraph, root: str = "generator") -> nx.DiGraph:
    """Compute per-edge voltage drop and per-node voltage on the graph.

    Args:
        G: Directed graph with edge attributes:
            - ``resistance``: real scalar
            - ``current``: non-empty sequence of real values
        root: Root source node for traversal, typically ``generator``.

    Returns:
        The same graph instance with updated ``edge['vdrop_volts']``,
        ``node['voltage']``, and ``node['vdrop_percent']`` attributes.
    """
    bfs_edges = _validate_voltage_drop_inputs(G, root)

    for node in G.nodes():
        G.nodes[node]["voltage"] = float(0.0)
        G.nodes[node]["vdrop_percent"] = float(0.0)

    G.nodes[root]["voltage"] = float(V0)
    G.nodes[root]["vdrop_percent"] = 0.0

    for parent, load in bfs_edges:
        edge = G.edges[parent, load]
        resistance = edge["resistance"]
        current = edge["current"]
        max_current = np.max(current)

        edge["vdrop_volts"] = VDROP_COEF * resistance * max_current

        G.nodes[load]["voltage"] = G.nodes[parent]["voltage"] - edge["vdrop_volts"]
        G.nodes[load]["vdrop_percent"] = (
            100 * (V0 - G.nodes[load]["voltage"]) / VDROP_REF
        )

        if G.nodes[load]["vdrop_percent"] > THRESHOLD_PERCENT:
            print(f"\t /!\\ vdrop of {G.nodes[load]['vdrop_percent']:.1f} percent at {load}")

    return G
