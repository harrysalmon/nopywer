"""
Classification: RESOURCE-INDEPENDENT

These tests validate representation invariants (dict vs Node) using synthetic
fixtures only. No external QGIS data files are required.
"""

import contextlib
import os
import tempfile
import unittest

import numpy as np

try:
    from tests.module_loader import import_nopywer_module, install_fake_qgis
except ModuleNotFoundError:
    from module_loader import import_nopywer_module, install_fake_qgis


install_fake_qgis()

core_objects_mod = import_nopywer_module("core_objects")
optimization_tools_mod = import_nopywer_module("optimization_tools")
from qgis.core import QgsPointXY


@contextlib.contextmanager
def temp_cwd():
    prev = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        os.chdir(td)
        try:
            yield td
        finally:
            os.chdir(prev)


def _base_cases():
    return {
        "generator": {"power": [0.0, 0.0, 0.0], "cum_power": [0.0, 0.0, 0.0], "xy": (0.0, 0.0)},
        "a": {"power": [300.0, 0.0, 0.0], "cum_power": [300.0, 0.0, 0.0], "xy": (1.0, 0.0)},
        "b": {"power": [0.0, 600.0, 0.0], "cum_power": [0.0, 600.0, 0.0], "xy": (0.0, 1.0)},
        "c": {"power": [0.0, 0.0, 900.0], "cum_power": [0.0, 0.0, 900.0], "xy": (1.0, 1.0)},
    }


def build_dict_grid():
    grid = {}
    for name, spec in _base_cases().items():
        x, y = spec["xy"]
        grid[name] = {
            "power": np.array(spec["power"], dtype=float),
            "cum_power": np.array(spec["cum_power"], dtype=float),
            "coordinates": QgsPointXY(x, y),
        }
    return grid


def build_node_grid():
    Node = core_objects_mod.Node
    grid = {}
    for name, spec in _base_cases().items():
        x, y = spec["xy"]
        node = Node(name=name)
        node.power = np.array(spec["power"], dtype=float)
        node.cum_power = np.array(spec["cum_power"], dtype=float)
        node.coordinates = QgsPointXY(x, y)
        grid[name] = node
    return grid


def canonical_nodes(nodes):
    out = {}
    for name, node in nodes.items():
        out[name] = {
            "power": tuple(np.array(node["power"], dtype=float).round(9)),
            "cum_power": tuple(np.array(node["cum_power"], dtype=float).round(9)),
            "x": round(float(node["x"]), 9),
            "y": round(float(node["y"]), 9),
        }
    return out


def canonical_edges(edges):
    return sorted((u, v, round(float(d), 9)) for u, v, d in edges)


def assert_arborescence(testcase, nodes, edges_final):
    testcase.assertEqual(len(edges_final), len(nodes) - 1)
    incoming = {n: 0 for n in nodes}
    for src, dst, _ in edges_final:
        testcase.assertNotEqual(src, dst)
        testcase.assertIn(src, nodes)
        testcase.assertIn(dst, nodes)
        incoming[dst] += 1

    testcase.assertEqual(incoming["generator"], 0)
    for node_name in nodes:
        if node_name != "generator":
            testcase.assertEqual(incoming[node_name], 1)


class RepresentationContractTests(unittest.TestCase):
    def test_qgis2list_is_representation_invariant(self):
        with temp_cwd():
            n_dict, e_dict = optimization_tools_mod.qgis2list(build_dict_grid())
            n_node, e_node = optimization_tools_mod.qgis2list(build_node_grid())

        self.assertEqual(canonical_nodes(n_dict), canonical_nodes(n_node))
        self.assertEqual(canonical_edges(e_dict), canonical_edges(e_node))

        n = len(n_dict)
        self.assertEqual(len(e_dict), n * (n - 1))
        self.assertTrue(all(src != dst for src, dst, _ in e_dict))

    def test_optimization_contract_is_representation_invariant(self):
        with temp_cwd():
            n_dict, e_dict = optimization_tools_mod.qgis2list(build_dict_grid())
            n_node, e_node = optimization_tools_mod.qgis2list(build_node_grid())

        edges_final_dict = optimization_tools_mod.find_optimal_layout(n_dict, e_dict)
        edges_final_node = optimization_tools_mod.find_optimal_layout(n_node, e_node)

        assert_arborescence(self, n_dict, edges_final_dict)
        assert_arborescence(self, n_node, edges_final_node)

        cost_dict = sum(d for _, _, d in edges_final_dict)
        cost_node = sum(d for _, _, d in edges_final_node)
        self.assertAlmostEqual(cost_dict, cost_node, places=9)


if __name__ == "__main__":
    unittest.main()
