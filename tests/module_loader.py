import importlib
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def install_fake_qgis() -> None:
    """Provide a minimal qgis.core surface for unit tests outside QGIS."""
    if "qgis.core" in sys.modules:
        return

    qgis_mod = types.ModuleType("qgis")
    core_mod = types.ModuleType("qgis.core")

    class QgsPointXY:
        def __init__(self, x=0.0, y=0.0):
            self._x = x
            self._y = y

        def x(self):
            return self._x

        def y(self):
            return self._y

    class QgsDistanceArea:
        def measureLine(self, p1, p2):
            dx = p1.x() - p2.x()
            dy = p1.y() - p2.y()
            return (dx**2 + dy**2) ** 0.5

    core_mod.QgsPointXY = QgsPointXY
    core_mod.QgsDistanceArea = QgsDistanceArea

    qgis_mod.core = core_mod
    sys.modules["qgis"] = qgis_mod
    sys.modules["qgis.core"] = core_mod


def import_nopywer_module(module_name: str):
    """Import nopywer submodules without executing nopywer/__init__.py."""
    if "nopywer" not in sys.modules:
        pkg = types.ModuleType("nopywer")
        pkg.__path__ = [str(ROOT / "nopywer")]
        sys.modules["nopywer"] = pkg

    return importlib.import_module(f"nopywer.{module_name}")
