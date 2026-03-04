import numpy as np
import os
import pickle
from pprint import pprint
import pulp
from qgis.core import QgsDistanceArea
from nopywer.minimum_spanning_tree2 import minimum_spanning_tree

try:
    import networkx as nx
    _HAS_NETWORKX = True
    _NETWORKX_ERROR = None
except Exception as nx_exc:
    nx = None
    _HAS_NETWORKX = False
    _NETWORKX_ERROR = nx_exc

try:
    import matplotlib.pyplot as plt
    _HAS_MATPLOTLIB = True
    _MATPLOTLIB_ERROR = None
except Exception as mpl_exc:
    plt = None
    _HAS_MATPLOTLIB = False
    _MATPLOTLIB_ERROR = mpl_exc

_HAS_PLOT_STACK = _HAS_NETWORKX and _HAS_MATPLOTLIB
if _HAS_PLOT_STACK:
    _PLOT_STACK_ERROR = None
else:
    _PLOT_STACK_ERROR = _MATPLOTLIB_ERROR or _NETWORKX_ERROR


def _is_graph(obj) -> bool:
    return (nx is not None) and isinstance(obj, nx.Graph)


def _extract_xy(node):
    if isinstance(node, dict):
        if ("x" in node) and ("y" in node):
            return node["x"], node["y"]
        coord = node.get("coordinates", None)
        if coord is not None:
            return coord.x(), coord.y()
        return None, None

    coord = getattr(node, "coordinates", None)
    if coord is not None:
        return coord.x(), coord.y()
    return None, None


def _matplotlib_can_show():
    if not _HAS_MATPLOTLIB:
        return False

    backend = str(plt.get_backend()).lower()
    if "inline" in backend:
        return False

    non_interactive_suffixes = ("agg", "pdf", "ps", "svg", "template", "cairo")
    return not backend.endswith(non_interactive_suffixes)


def phase_assignment_greedy(grid: dict):
    """
    each item has the foloowing:
    - 'power' (or 'cum_power')
            - name
            - ....
    """
    phases = [{"total_load": 0}, {"total_load": 0}, {"total_load": 0}]

    loads_unsorted = {key: value["power"].sum() for key, value in grid.items()}
    loads = dict(sorted(loads_unsorted.items(), key=lambda x: x[1], reverse=True))
    for key, value in loads.items():
        assigned_phase = min(range(len(phases)), key=lambda i: phases[i]["total_load"])
        # grid[key]['assigned_phase'] = assigned_phase
        phases[assigned_phase]["total_load"] += value
        print(f"{key}: {value:.0f}W, phase {assigned_phase}")

    print(f"\ntotal on phases: {phases}")
    phase_balance = 100 * np.std(
        grid["generator"]["cum_power"] / np.mean(grid["generator"]["cum_power"])
    )
    print(f"balance : {phase_balance:.1f}%")

    return loads


def qgis2list(grid):
    """this functions:
    - takes the 'grid' object from QGIS,
    - compute two new objects:
            - 'nodes': very similar to 'grid' but:
                    - with only necessary info for optim
                    - without QGIS objects, so it can be saved as a pickle

            - edges: all possible connections between two loads
                    note that it could be smarter, eg consider user input:
                    (ban some connections, compute distances from possible
                    layout on the map rather than direct distance, ...)

    Saving the nodes and edges as pickles allows to run the optimization stuff
    without having to rerun everything.

    Legacy note:
    - this function previously accepted multiple input representations
      (dict/Node/graph). It is now graph-only to avoid implicit conversions.
    """

    if not _is_graph(grid):
        raise TypeError("qgis2list expects a NetworkX graph as input")

    # define all possible edges
    edges = []  # list of ('source', 'dest', distance)
    nodes = {}
    qgsDist = QgsDistanceArea()
    node_items = list(grid.nodes(data=True))

    for src_name, source in node_items:
        src_coord = source.get("coordinates", None)
        src_x, src_y = source.get("x", None), source.get("y", None)
        nodes[src_name] = {
            "power": source.get("power"),
            "cum_power": source.get("cum_power"),
            "x": src_x,
            "y": src_y,
        }

        for dst_name, dest in node_items:
            if src_name == dst_name:
                continue

            dst_coord = dest.get("coordinates", None)
            if (src_coord is not None) and (dst_coord is not None):
                dist = qgsDist.measureLine(src_coord, dst_coord)
            else:
                src_x = nodes[src_name]["x"]
                src_y = nodes[src_name]["y"]
                dst_x = dest.get("x")
                dst_y = dest.get("y")
                if None in (src_x, src_y, dst_x, dst_y):
                    raise ValueError(
                        f"missing coordinates for edge distance computation between '{src_name}' and '{dst_name}'"
                    )
                dx = float(src_x - dst_x)
                dy = float(src_y - dst_y)
                dist = (dx * dx + dy * dy) ** 0.5

            edges.append((src_name, dst_name, dist))

    with open("grid.pkl", "wb") as f:
        pickle.dump([nodes, edges], f)

    return nodes, edges


def find_optimal_layout(grid, edges):
    # Define the problem
    prob = pulp.LpProblem("grid_layout", pulp.LpMinimize)

    # Create variables
    edges_conn = {
        (u, v): pulp.LpVariable(f"{u}_{v}", lowBound=0, upBound=1, cat="Integer")
        for u, v, _ in edges
    }  # [bool] used or not
    nodes = dict.fromkeys(grid.keys())
    for node in grid.keys():
        nodes[node] = {
            "n_in": None,  # pulp.LpVariable(f"{node}_{'n_in'}", lowBound=0, upBound=1, cat='Integer'),
            "n_out": None,
            "parent": "",
            "children": [],  # pas besoi de ca si j'utilise bien edges_conn ?
            "power": np.sum(grid[node]["power"]),
            "cum_power": pulp.LpVariable(
                f"cum_power_{node}", lowBound=0, cat="Continuous"
            ),
        }

    # Objective function
    print("\t creating objective function")
    prob += pulp.lpSum(edges_conn[e[0], e[1]] * e[2] for e in edges)  # minimize length

    # Constraints
    for n in nodes:
        # 'n_in' and 'n_out' are LpVariables (because sum of 'edges_conn')
        # https://stackoverflow.com/questions/72762330/how-can-i-add-interaction-of-two-variables-as-a-constraint-in-pulp
        n_out = pulp.lpSum([edges_conn[src, dst] for src, dst, _ in edges if src == n])
        n_in = pulp.lpSum([edges_conn[src, dst] for src, dst, _ in edges if dst == n])
        grid[n]["n_out"] = n_out
        grid[n]["n_in"] = n_in
        if n == "generator":
            prob += n_in == 0
            prob += n_out >= 1
            prob += nodes[n]["cum_power"] == sum(
                [load["power"] for _, load in nodes.items()]
            )  # all must be connected to generator

        else:
            prob += (
                n_in == 1
            )  # all nodes must be have 1 incoming cable, except generator (0)

            # constraint (attempt): check power flow constraint at one node
            # outgoing = [(src, dst) for src, dst in edges_conn if src == n] # connections going from n to its children
            # outgoing_power = pulp.lpSum(nodes[dst]['cum_power'] for src, dst in outgoing)
            # incoming = [(src, dst) for src, dst in edges_conn if dst == node]
            # ingoing_power = pulp.lpSum(nodes[dst]['cum_power'] for src, dst in incoming)
            # prob += (nodes[n]['cum_power'] == pulp.lpSum([nodes[n]['power'], outgoing_power]))

        # constraint (attempt): cum_power of each node is the sum of children's cum_power
        # children_power = pulp.lpSum([edges_conn[src,dst]*nodes[dst]['cum_power'] for src, dst, _ in edges if src==n])
        # children_power = pulp.lpSum([nodes[dst]['cum_power'] for src, dst, _ in edges if (src==n) and (edges_conn[src,dst])])
        # prob += (nodes[n]['cum_power'] == pulp.lpSum([nodes[n]['power'], children_power]))

        # outgoing = [(src, dst) for src, dst in edges_conn if src == n] # connections going from n to its children
        # outgoing_power = pulp.lpSum(nodes[dst]['cum_power'] for src, dst in outgoing)
        # # prob += (nodes[n]['cum_power'] == pulp.lpSum([nodes[n]['power'], outgoing_power]))
        # cp = pulp.LpConstraint(e=nodes[n]['cum_power'], sense=pulp.LpConstraintEQ, name=f'cum_power_{n}', rhs=outgoing_power)
        # prob.add(cp)

    for e in edges:
        prob.add(
            pulp.LpConstraint(
                e=edges_conn[e[0], e[1]] + edges_conn[e[1], e[0]],
                sense=pulp.LpConstraintLE,
                name=f"no_dbl_co_between_{e[0]}-{e[1]}",
                rhs=1,
            )
        )

        # la ligne ci dessous marche po car 'children' est mal géré, mais je devrais pouvoir utiser edges_conn
        # (qui inclu le sens sc->dst?)
        # prob += nodes[node]['cum_power'] == (nodes[node]['power'] + sum([child['cum_power'] for child in nodes[node]['children']]))

    # "all are connected to the generator" or "the generator is the source" constraint
    # could be:
    # - the cum_power of the generator must be the sum of all power:
    # -> implies to be able to compute cumulated power (ie store [children] info)
    #
    # - recursive: if node not 'generator', 'generator' must be foundable in the 'in' of 'in' parents...
    #
    # 	- the cumulated power of each node must be it's own power + the sum of the cum_power of its children
    # cf tentative d'implémentaton ci dessus, mais besoin de mieux gérer 'children' (and/or use edges_conn)
    #
    # - tsp: (n_edges) == (n_nodes-1) 	to connect all nodes together
    prob += pulp.lpSum(edges_conn) == (len(nodes) - 1)
    # - https://github.com/AlexBrou/Minimum-Spanning-Tree-with-Linear-Programming/blob/master/main.py

    """
	# constraints (attempt)
	for node in G.nodes():
		if node in ['source', 'sink']:
			continue
		incoming = [(u, v) for u, v in edges_conn if v == node]
		outgoing = [(u, v) for u, v in edges_conn if u == node]
		prob += pulp.lpSum(edges_conn[u, v] for u, v in incoming) == pulp.lpSum(edges_conn[u, v] for u, v in outgoing)
	"""

    # flow conservation constraint from https://medium.com/@bpuppim/solving-the-traveling-salesman-problem-using-pulp-f2f1aaf179fd
    vars_f = pulp.LpVariable.dicts("Flow", (nodes, nodes), 0, None, pulp.LpInteger)
    n = len(nodes) - 1
    for d in nodes:
        for a in nodes:
            if d != a:
                prob += vars_f[d][a] <= n * edges_conn[d, a]

    # Constraints are added to ensure flow is balanced for non-starting cities, allowing them to be visited exactly once.
    for o in nodes:
        if o != "generator":
            prob += (
                pulp.lpSum([vars_f[a][o] - vars_f[o][a] for a in nodes]) == 1,
                f"Flow_balance_{o}",
            )

    # Solve the problem
    print("\t solving problem")
    prob.solve()

    # print the result
    print(f"prob status: {pulp.LpStatus[prob.status]}")
    edges_final = []
    if pulp.LpStatus[prob.status] != "Infeasible":
        print(f"\nObjective Value: {pulp.value(prob.objective)} \n")
        print("connections:")
        for u, v in edges_conn:
            if pulp.value(edges_conn[u, v]):
                print(f"\t{u} connected to {v}")

        print("\nloads info:")
        for n in nodes:
            print(f"\t{n} cum_power = {pulp.value(nodes[n]['cum_power'])}")

        # too verbose:
        # print("\nOptimal Result:")
        # for variable in prob.variables():
        # 	if variable.varValue:
        # 		print (variable.name, "=", variable.varValue)

        # constraints = prob.constraints
        # for name in constraints.keys():
        # 	value = constraints.get(name).value()
        # 	slack = constraints.get(name).slack
        # 	print(f'constraint {name} has value: {value:0.2e} and slack: {slack:0.2e}')

        edges_final = [
            (e[0], e[1], e[2]) for e in edges if pulp.value(edges_conn[e[0], e[1]])
        ]

        if _HAS_PLOT_STACK:
            # Define the graph
            G = nx.DiGraph()
            G.add_weighted_edges_from(edges_final)

            # Plot the graph
            pos = {name: (node["x"], node["y"]) for name, node in grid.items()}
            colormap = ["red" if node == "generator" else "green" for node in G.nodes()]
            nx.draw(
                G,
                pos,
                with_labels=True,
                node_color=colormap,
                node_size=100,
                arrows=True,
                horizontalalignment="left",
                font_size=8,
            )
            labels = {
                (e[0], e[1]): f"{e[2]:.0f}m"
                for e in edges
                if pulp.value(edges_conn[e[0], e[1]])
            }
            nx.draw_networkx_edge_labels(G, pos, edge_labels=labels)
            if _matplotlib_can_show():
                plt.show()
            else:
                print(
                    "plot generated; skipping plt.show() on non-interactive matplotlib backend"
                )
        else:
            print(f"plotting disabled: {_PLOT_STACK_ERROR}")

    return edges_final


def export_layout_pyvis(grid, edges_final, output_html="outputs/optimal_layout.html"):
    try:
        from pyvis.network import Network
    except Exception as exc:
        print(f"pyvis export disabled: {exc}")
        return None

    if not edges_final:
        print("pyvis export skipped: no edges")
        return None

    output_folder = os.path.dirname(output_html)
    if output_folder:
        os.makedirs(output_folder, exist_ok=True)

    coords = {name: _extract_xy(node) for name, node in grid.items()}
    all_coords_available = all(x is not None and y is not None for x, y in coords.values())

    if all_coords_available:
        xs = [x for x, _ in coords.values()]
        ys = [y for _, y in coords.values()]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        x_span = max(x_max - x_min, 1e-9)
        y_span = max(y_max - y_min, 1e-9)

    net = Network(height="900px", width="100%", directed=True, cdn_resources="remote")

    for name, node in grid.items():
        color = "#d62728" if name == "generator" else "#2ca02c"
        node_args = {"label": name, "title": name, "color": color}

        if all_coords_available:
            x, y = coords[name]
            node_args["x"] = int(((x - x_min) / x_span - 0.5) * 1600)
            node_args["y"] = int((0.5 - (y - y_min) / y_span) * 1000)
            node_args["physics"] = False

        net.add_node(name, **node_args)

    for src, dst, dist in edges_final:
        net.add_edge(src, dst, label=f"{dist:.0f}m", title=f"{dist:.1f} m")

    if not all_coords_available:
        net.toggle_physics(True)

    net.write_html(output_html, open_browser=False, notebook=False)
    print(f"wrote pyvis layout: {output_html}")
    return output_html


def find_min_spanning_tree(grid, edges):
    """
        shape data like this
            edges_with_cost = [
        ["A", "D", 4],
        ["A", "B", 1],
        ...
            ["C", "F", 5],
    ]
    """
    print("\n-------------------------------------------\n")
    print(f"number of possible edges: {len(edges)}")
    print(f"number of nodes: {len(grid)}")

    edges_with_cost = []
    for e in edges:
        edges_with_cost.append([e[0], e[1], e[2]])
        # if len(edges_with_cost)>10: # 30 is already too big
        # 	break

    pprint(minimum_spanning_tree(edges_with_cost))
    return None


if __name__ == "__main__":
    with open("grid.pkl", "rb") as f:
        nodes, edges = pickle.load(f)

    find_optimal_layout(nodes, edges)
