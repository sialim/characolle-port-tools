"""Create an outfit-specific manifest from a unified CharaColle scene manifest."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--layer", required=True)
    parser.add_argument("--base-layer")
    parser.add_argument("--model-name")
    return parser.parse_args()


def is_base_mesh(name: str) -> bool:
    mesh_name = name.split("__", 1)[-1].casefold()
    return mesh_name.startswith("p_body") or mesh_name.startswith("p_nip")


def main() -> None:
    args = parse_args()
    source = json.loads(args.input.read_text(encoding="utf-8"))
    scene = dict(source.get("scene", {}))
    base_layer = args.base_layer or scene.get("base_body_layer", "02")
    layer = args.layer

    if base_layer == scene.get("base_body_layer", "") and source.get("base_objects"):
        base_objects = list(source["base_objects"])
    else:
        base_objects = [
            entry["mesh"]
            for entry in source.get("bodygroups", [])
            if entry.get("layer") == base_layer and is_base_mesh(entry["mesh"]["name"])
        ]
    if not base_objects:
        raise RuntimeError(f"Could not find base meshes for layer {base_layer}")

    base_names = {entry["name"] for entry in base_objects}
    outfit_groups = [
        entry
        for entry in source.get("bodygroups", [])
        if entry.get("layer") == layer and entry["mesh"]["name"] not in base_names
    ]
    scene.update({
        "outfit_layer": layer,
        "base_body_layer": base_layer,
        "base_replaced_by_variant": False,
    })
    result = {
        "format": source.get("format", 1),
        "character": source["character"],
        "model_name": args.model_name or f"characolle/{source['character'].lower()}_{layer}",
        "source_blend": source.get("source_blend", ""),
        "material_path": source.get("material_path", ""),
        "scene": scene,
        "armature": source.get("armature", {}),
        "base_objects": base_objects,
        "head_objects": list(source.get("head_objects", [])),
        "bodygroups": outfit_groups,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote layer {layer} manifest with {len(outfit_groups)} bodygroups: {args.output}")


if __name__ == "__main__":
    main()
