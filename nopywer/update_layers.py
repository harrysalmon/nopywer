from qgis.core import edit, QgsProject, QgsFeature
from .get_layer import get_layer
from .get_grid_geometry import get_load_name
from qgis.PyQt.QtCore import QVariant
from qgis.core import QgsField
import numpy as np

try:
    import networkx as nx
except Exception:
    nx = None

# based on https://gis.stackexchange.com/questions/428973/writing-list-as-attribute-field-in-pyqgis


def set_attribute(feature: QgsFeature, field: str, value: str):
    if field not in feature.fields().names():
        raise ValueError(
            f'The feature "{feature["name"]}" does not have a field "{field}"'
        )
    feature.setAttribute(field, f"{value}")
    return None


def update_1phase_layers(G, project: QgsProject):
    if (nx is None) or (not isinstance(G, nx.Graph)):
        raise TypeError("update_1phase_layers expects a NetworkX graph")
    print("\nupdating 1-phase layers with phase label...")
    edge_lookup = {
        (d.get("layer_name"), d.get("feature_id")): d for _, _, d in G.edges(data=True)
    }
    one_phase_layers = sorted(
        {
            d.get("layer_name")
            for _, _, d in G.edges(data=True)
            if "1phase" in str(d.get("layer_name"))
        }
    )

    for cable_layer_name in one_phase_layers:
        cable_layer = get_layer(project, cable_layer_name)
        if not cable_layer.isEditable():
            with edit(cable_layer):
                for i, cable in enumerate(list(cable_layer.getFeatures())):
                    edge = edge_lookup.get((cable_layer_name, i), None)
                    if edge is None:
                        continue
                    phase = edge.get("phase", None)
                    if phase is None:
                        phase = 0
                    if phase == "T":
                        raise ValueError(
                            f'cable idx {i} cannot be on phase "{phase}" because it is in a single phase layer.'
                        )
                    set_attribute(cable, "phase", f"{phase}")
                    cable_layer.updateFeature(cable)
        else:
            raise ValueError(
                f'Layer "{cable_layer_name}" cannot be edited by nopywer '
                "because it is already in edit mode in QGIS. Please untoggle edit mode."
            )

    return None


def update_load_layers(G, loads_layers_list: list, project: QgsProject):
    if (nx is None) or (not isinstance(G, nx.Graph)):
        raise TypeError("update_load_layers expects a NetworkX graph")
    print("\nupdating load layers with power usage and cumulated power...")
    for load_layer_name in loads_layers_list:
        layer = get_layer(project, load_layer_name)

        # Ensure 'distro assigned' field exists
        distro_field = "distro assigned"
        if distro_field not in layer.fields().names():
            layer.dataProvider().addAttributes(
                [QgsField(distro_field, QVariant.String)]
            )
            layer.updateFields()

        if not layer.isEditable():
            with edit(layer):
                for load in list(layer.getFeatures()):
                    load_name = get_load_name(load)
                    if load_name in G.nodes:
                        set_attribute(
                            load,
                            "power",
                            f"{1e-3 * np.array(G.nodes[load_name]['power'], dtype=float).sum()}",
                        )
                        set_attribute(
                            load,
                            "cum_power",
                            f"{1e-3 * np.array(G.nodes[load_name]['cum_power'], dtype=float).sum()}",
                        )
                        distro_value = G.nodes[load_name].get("distro_chosen", None)
                        load.setAttribute(distro_field, str(distro_value))
                        layer.updateFeature(load)

        else:
            raise ValueError(
                f'Layer "{load_name}" cannot be edited by nopywer '
                "because it is already in edit mode in QGIS. Please untoggle edit mode."
            )

    return None
