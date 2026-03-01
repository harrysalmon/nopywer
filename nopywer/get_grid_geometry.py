"""Build graph geometry from QGIS layers.

This module reads load and cable features from QGIS layers, infers cable-to-load
connectivity, and constructs a directed NetworkX graph rooted at ``generator``.

In the graph:
- Nodes represent loads/junctions/generator with coordinates and electrical attrs.
- Edges represent physical cables with GIS metadata and electrical attrs.

Disconnected loads remain in the graph as isolated nodes. Cables not connected on
both ends are reported and excluded from the directed tree topology.
"""

# This code is intented to find which load is connected to which cable
#
# It uses the class QgsDistanceArea and its methods:
#   - measureLength (argin: geometry)
#   - measureLine (args in : list of points)
#
# Documentation of the class:
# https://qgis.org/pyqgis/3.22/core/QgsDistanceArea.html#qgis.core.QgsDistanceArea
#
# Tutorial: "Santa claus is a workaholic and needs a summer break," in:
# https://docs.qgis.org/3.22/en/docs/pyqgis_developer_cookbook/geometry.html
#
# notes on structures: TODO: move this into a class !
#
# - nodes_dict=grid: dict(). each node is a key. each node is itself a dictonnary.
#   nodes_dict['someLoad'] has the following keys:
#       - _cable: a list of cables. Each cable in the list is described as a dictionnary with keys 'layer' and 'id'
#           exemple: nodes_dict['generator']['cable'][0]
#
#       - children: dictionary. One kid = one key.
#           each kid is itself a dict. eg: grid['generator']['children']['Werkhaus'].keys() ---> dict_keys(['cable'])
#       - parent: a str
#       - cable = cable to parent
#       - load = [watts] on all 3 phases ?
#       - cumulated load = [ on the 3 phases ---> a list ?]
#       - etc.
#
# - cables_dict['cable_layer_name'][cable_idx]  = dict() with the following keys:
#        - nodes: list(c). Each item of the list contains node(s) names connected to this cable
#

# imports
from qgis.core import QgsDistanceArea, QgsUnitTypes, QgsFeature
from .get_layer import get_layer
from .get_coordinates import get_coordinates
from .core_objects import Cable, Node
import traceback
import logging
import numpy as np

try:
    import networkx as nx
except Exception:
    nx = None

thres = 5  # [meters] threshold to detect cable and load connection
verbose = 0


def get_load_name(load: QgsFeature) -> str:
    """Normalize and return the load name from a QGIS feature."""
    verbose = 0

    load_name = load.attribute("name")
    assert isinstance(load_name, str), (
        "this should be a string containing the name of the load"
    )

    load_name = load_name.lower()
    load_name = load_name.replace(
        "\n", " "
    )  # in case of some names on the map have a \n
    load_name = load_name.replace("  ", " ")  # avoid double blanks

    if verbose:
        attrs = (
            load.attributes()
        )  # attrs is a list. It contains all the attribute values of this feature
        print("\n\t load's ID: ", load.id())
        print("\t load's attributes: ", attrs)

    return load_name


def get_cables_info(project, cables_layers_list, extra_cable_length) -> dict:
    """Extract cable objects from configured QGIS cable layers."""

    cables_dict = {}

    for cable_layer_name in cables_layers_list:
        cable_layer = get_layer(project, cable_layer_name)
        cables_dict[cable_layer_name] = [None] * len(cable_layer)

        # --- check cable CRS to measure distances
        # tips to mesure distance https://gis.stackexchange.com/questions/347802/calculating-elipsoidal-length-of-line-in-pyqgis
        assert project.crs() == cable_layer.crs(), (
            f"project CRS ({project.crs()}) does not match layer {cable_layer_name}'s CRS ({cable_layer.crs()}), stg is weird... "
        )

        qgsDist = QgsDistanceArea()

        # https://gis.stackexchange.com/questions/57745/how-to-get-crs-of-a-raster-layer-in-pyqgis
        qgsDist.setSourceCrs(cable_layer.crs(), project.transformContext())

        # on ellipsoids:
        #   - set global settings on qgis: https://gis.stackexchange.com/questions/341997/how-to-set-global-setting-ellipsoid-in-qgis
        #   - crs for ellipsoid measurements: https://gis.stackexchange.com/questions/376703/crs-for-ellipsoid-measurements

        # check that units are meters
        # https://gis.stackexchange.com/questions/341455/how-to-display-the-correct-unit-of-measure-in-pyqgis
        units_in_meters = QgsUnitTypes.toString(qgsDist.lengthUnits()) == "meters"
        if not units_in_meters:
            print(
                f'in layer "{cable_layer_name}", qgsDist.lengthUnits()): {QgsUnitTypes.toString(qgsDist.lengthUnits())}'
            )
            raise ValueError("distance units should be meters")

        # --- get info from each cable of the current cable layer
        for cable_idx, cable_qgis in enumerate(cable_layer.getFeatures()):
            cable_length = qgsDist.measureLength(cable_qgis.geometry())
            assert cable_length > 0, (
                f"in layer '{cable_layer}', cable_qgis {cable_idx + 1} has length = 0m. It should be deleted"
            )

            try:
                # check attributes before getting them ?
                cable_nopywer = Cable(
                    length=cable_length + extra_cable_length,
                    area=cable_qgis.attribute("area"),
                    plugs_and_sockets=cable_qgis.attribute(r"plugs&sockets"),
                )
                cable_nopywer.coordinates = get_coordinates(cable_qgis)
                cable_nopywer.layer_name = cable_layer_name
                cable_nopywer.id = cable_idx

            except Exception as error:
                raise ValueError(
                    f"There is a problem with the cable number {cable_idx + 1} of layer {cable_layer_name}: \n{repr(error)}"
                )

            cables_dict[cable_layer_name][cable_idx] = cable_nopywer

    return cables_dict


def get_loads_info(project, loads_layers_list) -> dict:
    """Extract load nodes from configured QGIS load layers."""
    if verbose:
        print("get_loads_info:")

    nodes_dict = {}
    for load_layer_name in loads_layers_list:
        load_layer = get_layer(project, load_layer_name)
        if verbose:
            print(f"loads layer = {load_layer}")

        field = "name"
        assert field in load_layer.fields().names(), (
            f'layer "{load_layer_name}" does not have a field "{field}"'
        )

        for load in load_layer.getFeatures():
            load_name = get_load_name(load)
            if verbose:
                print(f"\t load {load_name}")

            # init a Node for that node
            nodes_dict[load_name] = Node(name=load_name)

            try:
                load_pos = get_coordinates(load)
                nodes_dict[load_name].coordinates = load_pos

            except Exception:  # https://stackoverflow.com/questions/4990718/how-can-i-write-a-try-except-block-that-catches-all-exceptions/4992124#4992124
                print(
                    f'\t there is a problem with load "{load_name}" in "{load_layer_name}" layer:'
                )
                logging.error(traceback.format_exc())  # Logs the error appropriately.

    return nodes_dict


def is_load_connected(cable, load, qgsDist):
    """Return True when a load is within threshold distance of a cable end."""
    verbose = 0

    elist = [
        qgsDist.measureLine(load.coordinates, extrem) for extrem in cable.coordinates
    ]

    dmin = min(elist)
    is_load_connected = dmin <= thres
    if is_load_connected and verbose:
        print(
            f'\t\t in cable layer "{cable._layer_name}", cable {cable._id} is connected to "{load.name}"'
        )

    return is_load_connected


def find_connections(
    project, loads_layers_list, cables_layers_list, extra_cable_length, thres
) -> tuple[dict, dict]:
    """Match load nodes to nearby cables and return node/cable lookup dictionaries."""
    verbose = 0
    qgsDist = QgsDistanceArea()
    cables_dict = get_cables_info(project, cables_layers_list, extra_cable_length)
    nodes_dict = get_loads_info(project, loads_layers_list)

    # find connections : for each node, loop through all cables until you find close enough to the load
    for load in nodes_dict.values():
        for cable_layer in cables_dict.values():
            for cable in cable_layer:
                if is_load_connected(cable, load, qgsDist):
                    cables_dict[cable._layer_name][cable._id].nodes.append(load.name)
                    load.cables.append({"layer": cable._layer_name, "idx": cable._id})

        if verbose:
            if is_load_connected == 0:
                print(f"\t{load.name} is NOT connected")

            else:
                print(f"\t{load.name} is connected to {len(load.cables)} cable(s)")

    cables_list_str = "list of cables:\n"
    cables_not_connected = ""
    for cable_layer in cables_dict.values():
        for cable in cable_layer:
            cables_list_str += f"\t {cable}\n"
            if len(cable.nodes) < 2:
                cables_not_connected += f"\t{cable}\n"

    if len(cables_not_connected) > 0:
        print(
            f"\nthe following cables are not connected on both ends: \n{cables_not_connected}"
        )

    if verbose:
        print(cables_list_str)

    return nodes_dict, cables_dict


def _build_graph_from_connections(
    nodes_dict: dict, cables_dict: dict, root: str = "generator"
):
    """Build directed tree-like graph from connection dictionaries.

    The underlying undirected connectivity graph is validated for cycles in the
    connected component containing ``root``. Directed edges are then oriented by
    BFS traversal from the root.
    """
    if nx is None:
        raise ImportError("networkx is required to build graph geometry")

    G = nx.DiGraph()
    U = nx.Graph()

    for name, node in nodes_dict.items():
        coord = node.coordinates
        x = float(coord.x()) if coord is not None else None
        y = float(coord.y()) if coord is not None else None
        G.add_node(
            name,
            node_type="generator" if name == root else "load",
            coordinates=coord,
            x=x,
            y=y,
            power=np.array(node.power, dtype=float),
            cum_power=np.array(node.cum_power, dtype=float),
            phase=node.phase,
            voltage=0.0,
            vdrop_percent=0.0,
            distro={"in": None, "out": {}},
            distro_chosen={"in": None, "out": None},
        )
        U.add_node(name)

    for cable_layer_name, cable_layer in cables_dict.items():
        for cable_idx, cable in enumerate(cable_layer):
            cable_nodes = list(dict.fromkeys(cable.nodes))
            if len(cable_nodes) < 2:
                continue
            if len(cable_nodes) > 2:
                raise ValueError(
                    f"cable {cable_layer_name}:{cable_idx} is connected to more than two nodes: {cable_nodes}"
                )

            src, dst = cable_nodes
            if U.has_edge(src, dst):
                raise ValueError(
                    f"multiple cables between nodes '{src}' and '{dst}' are not supported in DiGraph mode"
                )

            U.add_edge(
                src,
                dst,
                layer_name=cable_layer_name,
                feature_id=cable_idx,
                cable_ref={"layer": cable_layer_name, "idx": cable_idx},
                length=float(cable.length),
                area=float(cable.area),
                resistance=float(cable.r),
                plugs_and_sockets=cable.plugs_and_sockets,
                phase=cable.phase,
                current=list(cable.current),
                vdrop_volts=float(getattr(cable, "vdrop_volts", 0.0)),
                waypoints=[
                    (float(p.x()), float(p.y()))
                    for p in (cable.coordinates or [])
                    if p is not None
                ],
            )

    if root not in G:
        raise ValueError(f"root node '{root}' is missing from loads layers")

    if root in U:
        connected = nx.node_connected_component(U, root)
        connected_graph = U.subgraph(connected).copy()
        if connected_graph.number_of_edges() > 0 and (not nx.is_tree(connected_graph)):
            raise ValueError(
                "There is an infinite loop on the map. Make sure to display all cable layers and fix."
            )

        for parent, child in nx.bfs_edges(U, root):
            attrs = dict(U.get_edge_data(parent, child))
            G.add_edge(parent, child, **attrs)

    return G


def compute_distro_requirements(G):
    """Compute incoming/outgoing distro requirements for each graph node.

    This should run after ``inspect_cable_layers`` so edge plug/socket ratings are
    populated.
    """
    if (nx is None) or (not isinstance(G, nx.Graph)):
        raise TypeError("compute_distro_requirements expects a NetworkX graph")

    verbose = 0
    print("\ncompute_distro_requirements...")
    for load_name in G.nodes:
        distro = {"in": None, "out": {}}

        if verbose:
            print(f"\n\t\t {load_name}:")

        if load_name == "generator":
            distro["in"] = "3P 125A"
        else:
            parents = list(G.predecessors(load_name))
            if parents:
                parent = parents[0]
                edge = G.edges[parent, load_name]
                layer_name = edge.get("layer_name", "")
                if "3phases" in layer_name:
                    ph = "3P"
                elif "1phase" in layer_name:
                    ph = "1P"
                else:
                    ph = "?"
                    print("\t\t\t can't figure out if this cable is 3P or 1P")

                if edge.get("plugs_and_sockets", None) is None:
                    raise ValueError(
                        "cable2parent.plugs_and_sockets is None, run inspect_cable_layer?"
                    )
                distro["in"] = f"{ph} {edge['plugs_and_sockets']}A"

        for _, child in G.out_edges(load_name):
            edge = G.edges[load_name, child]
            layer_name = edge.get("layer_name", "")
            if "3phases" in layer_name:
                ph = "3P"
            elif "1phase" in layer_name:
                ph = "1P"
            else:
                ph = "?"
                print("\t\t\t can't figure out if this cable is 3P or 1P")

            rating = f"{edge.get('plugs_and_sockets', '?')}A"
            desc = f"{ph} {rating}"
            if desc not in distro["out"]:
                distro["out"][desc] = 1
            else:
                distro["out"][desc] += 1

        if verbose:
            print(f"\t\t\t in: {distro['in']}")
            print("\t\t\t out: ")
            for desc in distro["out"].keys():
                print(f"\t\t\t\t {desc}: {distro['out'][desc]}")

        G.nodes[load_name]["distro"] = distro

    return G


def get_grid_geometry(project, param: dict):
    """Read QGIS layers and return the canonical directed grid graph."""
    verbose = 0
    if verbose:
        print("get grid geometry: \nfind_connections")

    loads_layers_list = param["loads_layers_list"]
    cables_layers_list = param["cables_layers_list"]

    # 1. find connections between loads and cables (find what load is plugged into what cable, and vice-versa)
    nodes_dict, cables_dict = find_connections(
        project,
        loads_layers_list,
        cables_layers_list,
        param["extra_cable_length"],
        thres,
    )

    # 2. build directed topology graph rooted at generator.
    G = _build_graph_from_connections(nodes_dict, cables_dict, root="generator")
    return G
