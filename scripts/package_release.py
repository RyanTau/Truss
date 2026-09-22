"""Create a manual HA integration zip without caches, models, or credentials."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


def package():
    destination = ROOT / "dist" / "truss-manual-install.zip"
    destination.parent.mkdir(exist_ok=True)
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted((ROOT / "custom_components/truss").rglob("*")):
            if path.is_file() and path.suffix in (".py", ".json", ".png") and "__pycache__" not in path.parts:
                archive.write(path, path.relative_to(ROOT).as_posix())
    print(destination)


if __name__ == "__main__":
    package()
