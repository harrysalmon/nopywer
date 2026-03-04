"""
Classification: RESOURCE-FILE-DEPENDENT

Required resources:
- tests/resources/user_parameters.yaml
- tests/resources/project_file.qgs
- tests/resources/power.gpkg
- tests/resources/power_balance.ods
- tests/resources/norg_power_inventory.ods

This module runs against the real project/model to validate end-to-end
topology and optimization contracts on actual data.
"""

import contextlib
import hashlib
import os
import sys
import tempfile
import unittest
from collections import defaultdict, deque
from pathlib import Path

import numpy as np
import yaml


TEST_ROOT = Path(__file__).resolve().parent
RESOURCES_DIR = TEST_ROOT / "resources"
RESOURCE_USER_PARAMETERS = RESOURCES_DIR / "user_parameters.yaml"
RESOURCE_PROJECT_FILE = RESOURCES_DIR / "project_file.qgs"
RESOURCE_POWER_GPKG = RESOURCES_DIR / "power.gpkg"
RESOURCE_POWER_BALANCE = RESOURCES_DIR / "power_balance.ods"
RESOURCE_INVENTORY = RESOURCES_DIR / "norg_power_inventory.ods"


@contextlib.contextmanager
def temp_cwd():
    prev = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        os.chdir(td)
        try:
            yield td
        finally:
            os.chdir(prev)


class RealProjectContractTests(unittest.TestCase):
    EXPECTED_OPT_OBJECTIVE = 928.356579737996
    EXPECTED_OPT_SIGNATURE_SHA256 = (
        "d6f6702fbb4cd44476b8d4672b04587efe15c33e971cc423d977599dac7ba39d"
    )

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

        # Earlier unit tests install a lightweight "fake qgis" stub into sys.modules.
        # Remove it here so integration imports resolve against the real QGIS package.
        qgis_mod = sys.modules.get("qgis")
        if (qgis_mod is not None) and (not hasattr(qgis_mod, "__path__")):
            for mod_name in list(sys.modules.keys()):
                if (mod_name == "qgis") or mod_name.startswith("qgis."):
                    del sys.modules[mod_name]

        nopywer_mod = sys.modules.get("nopywer")
        if nopywer_mod is not None:
            module_file = getattr(nopywer_mod, "__file__", None)
            if module_file is None:
                for mod_name in list(sys.modules.keys()):
                    if (mod_name == "nopywer") or mod_name.startswith("nopywer."):
                        del sys.modules[mod_name]

        required = [
            RESOURCE_USER_PARAMETERS,
            RESOURCE_PROJECT_FILE,
            RESOURCE_POWER_GPKG,
            RESOURCE_POWER_BALANCE,
            RESOURCE_INVENTORY,
        ]
        missing = [str(p) for p in required if not p.is_file()]
        if missing:
            raise unittest.SkipTest(f"Missing resource links/files: {missing}")

        with open(RESOURCE_USER_PARAMETERS, "r") as f:
            raw_params = yaml.safe_load(f)

        params = dict(raw_params)
        project_cfg = Path(params["project_file"])
        if not project_cfg.is_absolute():
            project_cfg = (RESOURCES_DIR / project_cfg).resolve()
        params["project_file"] = str(project_cfg)

        if project_cfg != RESOURCE_PROJECT_FILE.resolve():
            raise unittest.SkipTest(
                "Resource config mismatch: project_file in tests/resources/user_parameters.yaml "
                f"does not resolve to {RESOURCE_PROJECT_FILE.resolve()}"
            )

        try:
            import main as main_module
            import nopywer as npw
        except Exception as exc:
            raise unittest.SkipTest(f"Runtime not available for integration test: {exc}")

        original_get_user_parameters = main_module.npw.get_user_parameters
        main_module.npw.get_user_parameters = lambda: params
        try:
            grid, _, _ = main_module.main()
        finally:
            main_module.npw.get_user_parameters = original_get_user_parameters

        with temp_cwd():
            nodes, edges = npw.qgis2list(grid)
        optim_edges = npw.find_optimal_layout(nodes, edges)

        canon = sorted((u, v, round(float(d), 6)) for u, v, d in optim_edges)
        sig = "|".join(f"{u}>{v}:{d:.6f}" for u, v, d in canon)

        cls.grid = grid
        cls.nodes = nodes
        cls.edges = edges
        cls.optim_edges = optim_edges
        cls.optim_objective = float(sum(d for _, _, d in optim_edges))
        cls.optim_signature_sha256 = hashlib.sha256(sig.encode()).hexdigest()

    def test_real_main_contracts(self):
        self.assertIn("generator", self.grid.nodes)
        total_power = float(np.sum(self.grid.nodes["generator"]["cum_power"]))
        self.assertGreater(total_power, 80_000.0)
        self.assertLess(total_power, 100_000.0)

    def test_real_qgis2list_contracts(self):
        n = len(self.nodes)
        self.assertGreaterEqual(n, 30)
        self.assertEqual(len(self.edges), n * (n - 1))
        self.assertTrue(all(src != dst for src, dst, _ in self.edges))
        for src, dst, dist in self.edges:
            self.assertIn(src, self.nodes)
            self.assertIn(dst, self.nodes)
            self.assertGreaterEqual(dist, 0.0)

    def test_real_optimization_contracts(self):
        n = len(self.nodes)
        self.assertEqual(len(self.optim_edges), n - 1)

        incoming = {name: 0 for name in self.nodes}
        adj = defaultdict(list)
        total_cost = 0.0
        for src, dst, dist in self.optim_edges:
            self.assertNotEqual(src, dst)
            incoming[dst] += 1
            adj[src].append(dst)
            total_cost += float(dist)

        self.assertEqual(incoming["generator"], 0)
        for name in self.nodes:
            if name != "generator":
                self.assertEqual(incoming[name], 1)

        visited = set()
        queue = deque(["generator"])
        while queue:
            u = queue.popleft()
            if u in visited:
                continue
            visited.add(u)
            queue.extend(adj[u])

        self.assertEqual(visited, set(self.nodes.keys()))
        self.assertGreater(total_cost, 0.0)
        self.assertLess(total_cost, 2_000.0)
        self.assertAlmostEqual(total_cost, self.EXPECTED_OPT_OBJECTIVE, places=9)
        self.assertEqual(self.optim_signature_sha256, self.EXPECTED_OPT_SIGNATURE_SHA256)


if __name__ == "__main__":
    unittest.main()
