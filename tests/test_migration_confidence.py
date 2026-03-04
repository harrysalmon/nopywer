"""
Classification: RESOURCE-INDEPENDENT

These tests use synthetic in-memory fixtures only.
They do not require QGIS project files, spreadsheets, or inventory files.
"""

import math
import unittest

import networkx as nx
import numpy as np

try:
    from tests.module_loader import import_nopywer_module, install_fake_qgis
except ModuleNotFoundError:
    from module_loader import import_nopywer_module, install_fake_qgis


install_fake_qgis()

cumulate_current_mod = import_nopywer_module("cumulate_current")
compute_voltage_drop_mod = import_nopywer_module("compute_voltage_drop")
graph_model_mod = import_nopywer_module("graph_model")
optimization_tools_mod = import_nopywer_module("optimization_tools")


class MigrationConfidenceTests(unittest.TestCase):
    def test_cumulate_current_graph_contract(self):
        G = nx.DiGraph()
        G.add_node("generator", power=np.array([0.0, 0.0, 0.0]), cum_power=np.array([0.0, 0.0, 0.0]))
        G.add_node("a", power=np.array([900.0, 0.0, 0.0]), cum_power=np.array([0.0, 0.0, 0.0]))
        G.add_node("b", power=np.array([0.0, 450.0, 0.0]), cum_power=np.array([0.0, 0.0, 0.0]))
        G.add_edge("generator", "a", current=[])
        G.add_edge("a", "b", current=[])

        G = cumulate_current_mod.cumulate_current(G, V0=230.0, PF=0.9)

        np.testing.assert_allclose(G.nodes["b"]["cum_power"], [0.0, 450.0, 0.0], rtol=0, atol=1e-9)
        np.testing.assert_allclose(G.nodes["a"]["cum_power"], [900.0, 450.0, 0.0], rtol=0, atol=1e-9)
        np.testing.assert_allclose(
            G.nodes["generator"]["cum_power"], [900.0, 450.0, 0.0], rtol=0, atol=1e-9
        )
        np.testing.assert_allclose(
            G.edges["a", "b"]["current"], np.array([0.0, 450.0, 0.0]) / 230.0 / 0.9, rtol=0, atol=1e-9
        )
        np.testing.assert_allclose(
            G.edges["generator", "a"]["current"],
            np.array([900.0, 450.0, 0.0]) / 230.0 / 0.9,
            rtol=0,
            atol=1e-9,
        )

    def test_compute_voltage_drop_graph_contract(self):
        G = nx.DiGraph()
        G.add_node("generator", voltage=0.0, vdrop_percent=0.0)
        G.add_node("a", voltage=0.0, vdrop_percent=0.0)
        G.add_node("b", voltage=0.0, vdrop_percent=0.0)
        G.add_edge("generator", "a", resistance=0.5, current=[2.0, 1.0, 0.0], vdrop_volts=0.0)
        G.add_edge("a", "b", resistance=1.0, current=[3.0, 0.0, 0.0], vdrop_volts=0.0)

        G = compute_voltage_drop_mod.compute_voltage_drop(G)

        vdrop_ref = math.sqrt(3) * 230.0
        expected_v_a = 230.0 - 0.5 * 2.0
        expected_v_b = expected_v_a - 1.0 * 3.0

        self.assertAlmostEqual(G.edges["generator", "a"]["vdrop_volts"], 1.0, places=9)
        self.assertAlmostEqual(G.edges["a", "b"]["vdrop_volts"], 3.0, places=9)
        self.assertAlmostEqual(G.nodes["a"]["voltage"], expected_v_a, places=9)
        self.assertAlmostEqual(G.nodes["b"]["voltage"], expected_v_b, places=9)
        self.assertAlmostEqual(G.nodes["a"]["vdrop_percent"], 100.0 * (230.0 - expected_v_a) / vdrop_ref)
        self.assertAlmostEqual(G.nodes["b"]["vdrop_percent"], 100.0 * (230.0 - expected_v_b) / vdrop_ref)

    def test_graph_depth_and_bfs_contract(self):
        G = nx.DiGraph()
        G.add_edges_from([("generator", "a"), ("a", "b"), ("a", "c"), ("c", "d")])

        dlist = graph_model_mod.depth_list_from_graph(G, root="generator")
        bfs = graph_model_mod.bfs_order(G, root="generator")

        self.assertEqual(dlist[0], ["generator"])
        self.assertEqual(set(dlist[1]), {"a"})
        self.assertEqual(set(dlist[2]), {"b", "c"})
        self.assertEqual(set(dlist[3]), {"d"})
        self.assertEqual(bfs[0], "generator")
        self.assertEqual(set(bfs), {"generator", "a", "b", "c", "d"})

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
