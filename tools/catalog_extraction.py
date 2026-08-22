"""Catalog extracted CharaColle packages without copying copyrighted assets.

Example:
    python catalog_extraction.py \
        --root C:\\path\\to\\all_pp \
        --output C:\\path\\to\\characolle_manifest.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


CHARACTERS = {
    "kud": {
        "display_name": "Kud",
        "package": "cc02_00_00_00",
        "preview_names": ["クド制服.png", "クド水着.png", "クド私服.png"],
        "body_prefix": "c02_01_",
    },
    "rin": {
        "display_name": "Rin",
        "package": "cc02_00_01_00",
        "preview_names": ["鈴制服.png", "鈴水着.png", "鈴私服.png"],
        "body_prefix": "c02_02_",
    },
}


def files_in(path: Path) -> list[Path]:
    return sorted((item for item in path.rglob("*") if item.is_file()), key=lambda p: p.name.lower())


def classify(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".xx":
        return "mesh_or_object"
    if suffix == ".xa":
        return "animation"
    if suffix in {".bmp", ".tga", ".png", ".jpg", ".dds"}:
        return "texture_or_preview"
    if suffix in {".lst", ".kys", ".kcol", ".neck", ".eyes", ".tty"}:
        return "character_metadata"
    if suffix in {".wav", ".ogg", ".mp3"}:
        return "audio"
    return "other"


def package_record(root: Path, package_dir: Path) -> dict[str, object]:
    package_files = files_in(package_dir)
    by_type: dict[str, list[str]] = {}
    for path in package_files:
        by_type.setdefault(classify(path), []).append(path.relative_to(package_dir).as_posix())
    return {
        "name": package_dir.name,
        "path": package_dir.relative_to(root).as_posix(),
        "file_count": len(package_files),
        "by_type": by_type,
    }


def character_record(root: Path, spec: dict[str, object]) -> dict[str, object]:
    package_name = str(spec["package"])
    package_dir = root / package_name
    files = files_in(package_dir) if package_dir.is_dir() else []
    prefix = str(spec["body_prefix"])
    relevant = [path for path in files if path.name.startswith(prefix)]
    return {
        "display_name": spec["display_name"],
        "package": package_name,
        "package_path": package_dir.relative_to(root).as_posix() if package_dir.exists() else None,
        "preview_names": [name for name in spec["preview_names"] if (package_dir / name).exists()],
        "meshes": [path.relative_to(package_dir).as_posix() for path in relevant if path.suffix.lower() == ".xx"],
        "animations": [path.relative_to(package_dir).as_posix() for path in relevant if path.suffix.lower() == ".xa"],
        "textures": [path.relative_to(package_dir).as_posix() for path in relevant if path.suffix.lower() in {".bmp", ".tga", ".png", ".dds"}],
        "metadata": [path.relative_to(package_dir).as_posix() for path in relevant if path.suffix.lower() not in {".xx", ".xa", ".bmp", ".tga", ".png", ".dds"}],
    }


def build_manifest(root: Path) -> dict[str, object]:
    package_dirs = sorted(
        (path for path in root.iterdir() if path.is_dir() and path.name.startswith("cc02_")),
        key=lambda path: path.name,
    )
    return {
        "schema": 1,
        "source_root": root.name,
        "packages": [package_record(root, path) for path in package_dirs],
        "characters": {name: character_record(root, spec) for name, spec in CHARACTERS.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True, help="Extracted all_pp directory")
    parser.add_argument("--output", type=Path, required=True, help="Manifest JSON path")
    args = parser.parse_args()
    manifest = build_manifest(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Catalogued {len(manifest['packages'])} packages and {len(manifest['characters'])} characters")


if __name__ == "__main__":
    main()
