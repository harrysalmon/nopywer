"""
Classification: RESOURCE-INDEPENDENT

These tests validate graph-first representation contracts using synthetic
fixtures only. No external QGIS data files are required.
"""

import contextlib
import os
import tempfile
import unittest

import networkx as nx
import numpy as np

try:
    from tests.module_loader import import_nopywer_module, install_fake_qgis
except ModuleNotFoundError:
    from module_loader import import_nopywer_module, install_fake_qgis


install_fake_qgis()

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


def build_graph():
    G = nx.DiGraph()
    for name, spec in _base_cases().items():
        x, y = spec["xy"]
        G.add_node(
            name,
            power=np.array(spec["power"], dtype=float),
            cum_power=np.array(spec["cum_power"], dtype=float),
            coordinates=QgsPointXY(x, y),
            x=float(x),
            y=float(y),
        )
    return G


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


def expected_nodes():
    out = {}
    for name, spec in _base_cases().items():
        x, y = spec["xy"]
        out[name] = {
            "power": tuple(np.array(spec["power"], dtype=float).round(9)),
            "cum_power": tuple(np.array(spec["cum_power"], dtype=float).round(9)),
            "x": round(float(x), 9),
            "y": round(float(y), 9),
        }
    return out


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
    def test_qgis2list_graph_contract(self):
        with temp_cwd():
            nodes, edges = optimization_tools_mod.qgis2list(build_graph())

        self.assertEqual(canonical_nodes(nodes), expected_nodes())
        n = len(nodes)
        self.assertEqual(len(edges), n * (n - 1))
        self.assertTrue(all(src != dst for src, dst, _ in edges))
        self.assertTrue(all(float(d) >= 0.0 for _, _, d in edges))

    def test_qgis2list_rejects_non_graph_input(self):
        with self.assertRaises(TypeError):
            optimization_tools_mod.qgis2list({"generator": {}})

    def test_optimization_contract_on_graph_derived_nodes(self):
        with temp_cwd():
            nodes, edges = optimization_tools_mod.qgis2list(build_graph())

        edges_final = optimization_tools_mod.find_optimal_layout(nodes, edges)
        assert_arborescence(self, nodes, edges_final)
        cost = sum(d for _, _, d in edges_final)
        self.assertAlmostEqual(cost, 3.0, places=9)


if __name__ == "__main__":
    unittest.main()
