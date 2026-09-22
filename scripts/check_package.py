"""Offline structural checks; no claim of runtime HA validation."""
import ast
import json
import struct
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for folder in ("custom_components", "truss_engine", "scripts", "tests"):
    for path in (ROOT / folder).rglob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
for path in (ROOT / "custom_components").rglob("*.json"):
    json.loads(path.read_text(encoding="utf-8"))
manifest = json.loads((ROOT / "custom_components/truss/manifest.json").read_text())
assert manifest["domain"] == "truss" and manifest["config_flow"]
assert json.loads((ROOT / "custom_components/truss/strings.json").read_text()) == json.loads((ROOT / "custom_components/truss/translations/en.json").read_text())
for required in ("hacs.json", "repository.yaml", "truss_engine/config.yaml", "truss_engine/Dockerfile", "README.md"):
    assert (ROOT / required).is_file(), required
if "YOUR_GITHUB_OWNER" in manifest["documentation"]:
    print("Publication pending: run scripts/set_repository.py with the real GitHub URL.")
print("Python syntax, JSON, translations, and package layout passed.")
for name, size in (("icon.png", 256), ("truss_engine/icon.png", 128), ("truss_engine/logo.png", 256)):
    data = (ROOT / name).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", data[16:24]) == (size, size), name
for path in (ROOT / "custom_components/truss/brand").glob("*.png"):
    size = 512 if "@2x" in path.name else 256
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", data[16:24]) == (size, size), path
    assert data[25] == 6, "Brand PNG must preserve RGBA transparency"
assert (ROOT / "icon.png").read_bytes() == (ROOT / "custom_components/truss/brand/icon.png").read_bytes()
print("Brand PNG dimensions and alpha format passed.")
