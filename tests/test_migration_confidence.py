"""
Classification: RESOURCE-INDEPENDENT

These tests use synthetic in-memory fixtures only.
They do not require QGIS project files, spreadsheets, or inventory files.
"""

import math
import unittest

import numpy as np

try:
    from tests.module_loader import import_nopywer_module, install_fake_qgis
except ModuleNotFoundError:
    from module_loader import import_nopywer_module, install_fake_qgis


install_fake_qgis()

cumulate_current_mod = import_nopywer_module("cumulate_current")
compute_voltage_drop_mod = import_nopywer_module("compute_voltage_drop")
get_children_mod = import_nopywer_module("get_children")
optimization_tools_mod = import_nopywer_module("optimization_tools")


class DummyCable:
    def __init__(self, *, nodes=None, r=0.0, current=None):
        self.nodes = list(nodes or [])
        self.r = float(r)
        self.current = list(current or [])
        self.vdrop_volts = 0.0


class DummyNode:
    def __init__(self, name, *, parent=None, power=None, cable=None):
        self.name = name
        self.parent = parent
        self.children = {}
        self.deepness = None
        self.cables = []
        self.cable = cable or {}
        self.power = np.array(power if power is not None else [0.0, 0.0, 0.0], dtype=float)
        self.cum_power = np.array([0.0, 0.0, 0.0], dtype=float)
        self.voltage = 0.0
        self.vdrop_percent = 0.0


class MigrationConfidenceTests(unittest.TestCase):
    def test_get_children_builds_tree_and_deepness(self):
        cables = {
            "L": [
                DummyCable(nodes=["generator", "a"]),
                DummyCable(nodes=["a", "b"]),
            ]
        }
        grid = {
            "generator": DummyNode("generator", parent=None),
            "a": DummyNode("a", parent=None),
            "b": DummyNode("b", parent=None),
        }
        grid["generator"].cables = [{"layer": "L", "idx": 0}]
        grid["a"].cables = [{"layer": "L", "idx": 0}, {"layer": "L", "idx": 1}]
        grid["b"].cables = [{"layer": "L", "idx": 1}]

        grid, _ = get_children_mod.get_children("generator", grid, cables)

        self.assertEqual(grid["generator"].deepness, 0)
        self.assertEqual(grid["a"].deepness, 1)
        self.assertEqual(grid["b"].deepness, 2)
        self.assertEqual(grid["a"].parent, "generator")
        self.assertEqual(grid["b"].parent, "a")
        self.assertEqual(set(grid["generator"].children.keys()), {"a"})
        self.assertEqual(set(grid["a"].children.keys()), {"b"})
        self.assertEqual(grid["a"].children["b"]["cable"]["idx"], 1)

    def test_get_children_detects_preexisting_children_as_loop(self):
        cables = {"L": [DummyCable(nodes=["generator", "a"])]}
        grid = {
            "generator": DummyNode("generator", parent=None),
            "a": DummyNode("a", parent=None),
        }
        grid["generator"].cables = [{"layer": "L", "idx": 0}]
        grid["a"].cables = [{"layer": "L", "idx": 0}]
        grid["generator"].children = {"a": {"cable": {"layer": "L", "idx": 0}}}

        with self.assertRaises(ValueError) as ctx:
            get_children_mod.get_children("generator", grid, cables)

        self.assertIn("infinite loop", str(ctx.exception).lower())

    def test_cumulate_current_preserves_numeric_balance(self):
        cables = {"L": [DummyCable(), DummyCable()]}
        grid = {
            "generator": DummyNode("generator", power=[0, 0, 0]),
            "a": DummyNode(
                "a",
                parent="generator",
                power=[900.0, 0.0, 0.0],
                cable={"layer": "L", "idx": 0},
            ),
            "b": DummyNode(
                "b",
                parent="a",
                power=[0.0, 450.0, 0.0],
                cable={"layer": "L", "idx": 1},
            ),
        }
        dlist = [["generator"], ["a"], ["b"]]

        grid, cables = cumulate_current_mod.cumulate_current(
            grid=grid, cables_dict=cables, dlist=dlist, V0=230.0, PF=0.9
        )

        np.testing.assert_allclose(grid["b"].cum_power, [0.0, 450.0, 0.0], rtol=0, atol=1e-9)
        np.testing.assert_allclose(grid["a"].cum_power, [900.0, 450.0, 0.0], rtol=0, atol=1e-9)
        np.testing.assert_allclose(
            grid["generator"].cum_power, [900.0, 450.0, 0.0], rtol=0, atol=1e-9
        )
        np.testing.assert_allclose(
            cables["L"][1].current, np.array([0.0, 450.0, 0.0]) / 230.0 / 0.9, rtol=0, atol=1e-9
        )
        np.testing.assert_allclose(
            cables["L"][0].current, np.array([900.0, 450.0, 0.0]) / 230.0 / 0.9, rtol=0, atol=1e-9
        )

    def test_compute_voltage_drop_matches_reference_formula(self):
        cables = {
            "L": [
                DummyCable(r=0.5, current=[2.0, 1.0, 0.0]),
                DummyCable(r=1.0, current=[3.0, 0.0, 0.0]),
            ]
        }
        grid = {
            "generator": DummyNode("generator", parent=None),
            "a": DummyNode("a", parent="generator", cable={"layer": "L", "idx": 0}),
            "b": DummyNode("b", parent="a", cable={"layer": "L", "idx": 1}),
        }
        grid["generator"].children = {"a": {"cable": {"layer": "L", "idx": 0}}}
        grid["a"].children = {"b": {"cable": {"layer": "L", "idx": 1}}}

        grid, cables = compute_voltage_drop_mod.compute_voltage_drop(grid, cables)

        vdrop_ref = math.sqrt(3) * 230.0
        expected_v_a = 230.0 - 0.5 * 2.0
        expected_v_b = expected_v_a - 1.0 * 3.0

        self.assertAlmostEqual(cables["L"][0].vdrop_volts, 1.0, places=9)
        self.assertAlmostEqual(cables["L"][1].vdrop_volts, 3.0, places=9)
        self.assertAlmostEqual(grid["a"].voltage, expected_v_a, places=9)
        self.assertAlmostEqual(grid["b"].voltage, expected_v_b, places=9)
        self.assertAlmostEqual(grid["a"].vdrop_percent, 100.0 * (230.0 - expected_v_a) / vdrop_ref)
        self.assertAlmostEqual(grid["b"].vdrop_percent, 100.0 * (230.0 - expected_v_b) / vdrop_ref)

    def test_find_optimal_layout_enforces_tree_constraints_on_toy_graph(self):
        nodes = {
            "A": {"power": 10.0, "cum_power": None, "x": 1.0, "y": 1.0},
            "B": {"power": 20.0, "cum_power": None, "x": 0.0, "y": 1.0},
            "C": {"power": 30.0, "cum_power": None, "x": 1.0, "y": 0.0},
            "generator": {"power": 0.0, "cum_power": None, "x": 0.0, "y": 0.0},
        }

        edges = []
        for src in nodes:
            for dst in nodes:
                if src != dst:
                    dist = (nodes[src]["x"] - nodes[dst]["x"]) ** 2 + (
                        nodes[src]["y"] - nodes[dst]["y"]
                    ) ** 2
                    edges.append((src, dst, dist))

        edges_final = optimization_tools_mod.find_optimal_layout(nodes, edges)

        self.assertEqual(len(edges_final), len(nodes) - 1)
        incoming = {n: 0 for n in nodes}
        for src, dst, _ in edges_final:
            incoming[dst] += 1
            self.assertNotEqual(src, dst)

        self.assertEqual(incoming["generator"], 0)
        for node_name in nodes:
            if node_name != "generator":
                self.assertEqual(incoming[node_name], 1)

        total_cost = sum(dist for _, _, dist in edges_final)
        self.assertAlmostEqual(total_cost, 3.0, places=9)


if __name__ == "__main__":
    unittest.main()
