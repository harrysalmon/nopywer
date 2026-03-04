"""Graph traversal helpers for the runtime NetworkX model.

Legacy note:
- this module previously carried dict/Node/Cable conversion adapters between
  old and new representations. Those adapters were removed to keep a strict
  graph-first runtime contract.
"""

from __future__ import annotations

try:
    import networkx as nx
except Exception as exc:
    nx = None
    _NETWORKX_ERROR = exc
else:
    _NETWORKX_ERROR = None


def _require_networkx() -> None:
    if nx is None:
        raise ImportError(f"networkx is required for graph operations: {_NETWORKX_ERROR}")


def depth_list_from_graph(G, root: str = "generator") -> list[list[str]]:
    """Return nodes grouped by BFS depth from ``root``."""
    _require_networkx()
    if root not in G:
        return []

    depth_map = dict(nx.single_source_shortest_path_length(G, root))
    if not depth_map:
        return []

    dmax = max(depth_map.values())
    dlist = [[] for _ in range(dmax + 1)]
    for node, depth in depth_map.items():
        dlist[depth].append(node)
    return dlist


def bfs_order(G, root: str = "generator") -> list[str]:
    """Return node names in BFS order from ``root``."""
    _require_networkx()
    if root not in G:
        return []
    return list(nx.bfs_tree(G, root).nodes())
