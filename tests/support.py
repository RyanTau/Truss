"""Load pure integration modules without installing HA or model dependencies."""
import importlib
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "truss_engine"))
package = types.ModuleType("truss_test")
package.__path__ = [str(ROOT / "custom_components/truss")]
sys.modules.setdefault("truss_test", package)


def integration(name):
    return importlib.import_module("truss_test." + name)
