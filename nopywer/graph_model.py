from __future__ import annotations

from copy import deepcopy
from typing import Any

import numpy as np

try:
    import networkx as nx
except Exception as exc:
    nx = None
    _NETWORKX_ERROR = exc
else:
    _NETWORKX_ERROR = None


def _require_networkx():
    if nx is None:
        raise ImportError(f"networkx is required for graph operations: {_NETWORKX_ERROR}")


def _is_mapping(obj: Any) -> bool:
    return isinstance(obj, dict)


def _get_attr(obj: Any, key: str, default=None):
    if _is_mapping(obj):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _set_attr(obj: Any, key: str, value):
    if _is_mapping(obj):
        obj[key] = value
    else:
        setattr(obj, key, value)


def _as_phase_vector(value) -> np.ndarray:
    if isinstance(value, np.ndarray):
        return value.astype(float)
    if value is None:
        return np.array([0.0, 0.0, 0.0], dtype=float)
    return np.array(value, dtype=float)


def _edge_waypoints(cable) -> list[tuple[float, float]]:
    out = []
    coords = _get_attr(cable, "coordinates", []) or []
    for p in coords:
        if p is None:
            continue
        try:
            out.append((float(p.x()), float(p.y())))
        except Exception:
            pass
    return out


def build_graph_from_legacy(grid: dict, cables_dict: dict, root: str = "generator"):
    """Build a DiGraph from legacy nopywer Node/Cable containers."""
    _require_networkx()
    G = nx.DiGraph()

    # Add every node first so disconnected loads are still represented.
    for name, node in grid.items():
        coord = _get_attr(node, "coordinates", None)
        x = None
        y = None
        if coord is not None:
            try:
                x = float(coord.x())
                y = float(coord.y())
            except Exception:
                x = None
                y = None

        power = _as_phase_vector(_get_attr(node, "power", None))
        cum_power = _as_phase_vector(_get_attr(node, "cum_power", None))
        voltage = _get_attr(node, "voltage", 0.0)
        vdrop_percent = _get_attr(node, "vdrop_percent", 0.0)

        G.add_node(
            name,
            node_type="generator" if name == root else "load",
            coordinates=coord,
            x=x,
            y=y,
            power=power,
            cum_power=cum_power,
            phase=_get_attr(node, "phase", None),
            voltage=float(0.0 if voltage is None else voltage),
            vdrop_percent=float(0.0 if vdrop_percent is None else vdrop_percent),
            distro=deepcopy(_get_attr(node, "distro", {"in": None, "out": {}})),
            distro_chosen=deepcopy(_get_attr(node, "distro_chosen", {"in": None, "out": None})),
        )

    # Tree-oriented edges are encoded by each node's "cable to parent" reference.
    for child_name, child in grid.items():
        if child_name == root:
            continue

        parent = _get_attr(child, "parent", None)
        if parent in (None, ""):
            continue

        cable_ref = _get_attr(child, "cable", {}) or {}
        layer = cable_ref.get("layer", None)
        idx = cable_ref.get("idx", None)
        if layer is None or idx is None:
            continue
        if layer not in cables_dict:
            continue
        if not (0 <= idx < len(cables_dict[layer])):
            continue

        cable = cables_dict[layer][idx]
        resistance = _get_attr(cable, "r", 0.0)
        vdrop_volts = _get_attr(cable, "vdrop_volts", 0.0)
        edge_phase = _get_attr(cable, "phase", None)
        edge_current = list(_get_attr(cable, "current", []) or [])

        G.add_edge(
            parent,
            child_name,
            layer_name=layer,
            feature_id=idx,
            cable_ref={"layer": layer, "idx": idx},
            length=float(_get_attr(cable, "length", 0.0)),
            area=float(_get_attr(cable, "area", 0.0)),
            resistance=float(0.0 if resistance is None else resistance),
            plugs_and_sockets=_get_attr(cable, "plugs_and_sockets", None),
            phase=edge_phase,
            current=edge_current,
            vdrop_volts=float(0.0 if vdrop_volts is None else vdrop_volts),
            waypoints=_edge_waypoints(cable),
        )

    return G


def depth_list_from_graph(G, root: str = "generator") -> list[list[str]]:
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
    _require_networkx()
    if root not in G:
        return []
    return list(nx.bfs_tree(G, root).nodes())


def sync_legacy_from_graph(
    G, grid: dict, cables_dict: dict, root: str = "generator"
) -> tuple[dict, dict, list[list[str]]]:
    """Push graph attributes back into legacy Node/Cable objects for old modules."""
    _require_networkx()

    for name in grid:
        if name not in G.nodes:
            continue
        nd = G.nodes[name]
        _set_attr(grid[name], "power", _as_phase_vector(nd.get("power", None)))
        _set_attr(grid[name], "cum_power", _as_phase_vector(nd.get("cum_power", None)))
        _set_attr(grid[name], "phase", nd.get("phase", None))
        _set_attr(grid[name], "voltage", float(nd.get("voltage", 0.0)))
        _set_attr(grid[name], "vdrop_percent", float(nd.get("vdrop_percent", 0.0)))
        _set_attr(grid[name], "distro", deepcopy(nd.get("distro", {"in": None, "out": {}})))
        _set_attr(
            grid[name],
            "distro_chosen",
            deepcopy(nd.get("distro_chosen", {"in": None, "out": None})),
        )
        _set_attr(grid[name], "children", {})
        _set_attr(grid[name], "parent", None)
        _set_attr(grid[name], "deepness", None)
        _set_attr(grid[name], "cable", {})

    for parent, child, edge_data in G.edges(data=True):
        if parent in grid and child in grid:
            child_ref = {
                "layer": edge_data.get("layer_name"),
                "idx": edge_data.get("feature_id"),
            }
            _set_attr(grid[child], "parent", parent)
            _set_attr(grid[child], "cable", child_ref)
            children = _get_attr(grid[parent], "children", {})
            children[child] = {"cable": child_ref}
            _set_attr(grid[parent], "children", children)

    if root in grid:
        _set_attr(grid[root], "parent", "")

    depth_map = (
        dict(nx.single_source_shortest_path_length(G, root)) if root in G else {}
    )
    for name, depth in depth_map.items():
        if name in grid:
            _set_attr(grid[name], "deepness", int(depth))

    for parent, child, edge_data in G.edges(data=True):
        layer = edge_data.get("layer_name", None)
        idx = edge_data.get("feature_id", None)
        if layer is None or idx is None:
            continue
        if layer not in cables_dict:
            continue
        if not (0 <= idx < len(cables_dict[layer])):
            continue
        cable = cables_dict[layer][idx]
        _set_attr(cable, "phase", edge_data.get("phase", None))
        _set_attr(cable, "current", list(edge_data.get("current", []) or []))
        _set_attr(cable, "vdrop_volts", float(edge_data.get("vdrop_volts", 0.0)))

    return grid, cables_dict, depth_list_from_graph(G, root=root)
