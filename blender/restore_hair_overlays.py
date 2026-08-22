"""Restore the original CharaColle hair selection overlay in Blender materials."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--texture-dir", type=Path, required=True)
    return parser.parse_args(argv)


def image_for_material(material: bpy.types.Material, texture_dir: Path) -> bpy.types.Image | None:
    name = material.name.casefold()
    if "hair" not in name and "inumimi" not in name:
        return None
    matches = sorted(texture_dir.glob("*_hair_sel_00.bmp")) + sorted(texture_dir.glob("*_hair_sell_00.bmp"))
    if not matches:
        return None
    image = bpy.data.images.get(matches[0].name) or bpy.data.images.load(str(matches[0]), check_existing=True)
    image.pack()
    return image


def restore(texture_dir: Path) -> int:
    updated = 0
    for material in bpy.data.materials:
        overlay = image_for_material(material, texture_dir)
        if overlay is None:
            continue
        material.use_nodes = True
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        shader = next((node for node in nodes if node.type == "BSDF_PRINCIPLED"), None)
        if shader is None or "Emission Color" not in shader.inputs:
            continue
        old = nodes.get("CharaColle Hair Overlay")
        if old is not None:
            nodes.remove(old)
        texture = nodes.new("ShaderNodeTexImage")
        texture.name = "CharaColle Hair Overlay"
        texture.label = overlay.name
        texture.location = (-320, -120)
        texture.image = overlay
        overlay.colorspace_settings.name = "sRGB"
        for link in list(shader.inputs["Emission Color"].links):
            links.remove(link)
        links.new(texture.outputs["Color"], shader.inputs["Emission Color"])
        if "Emission Strength" in shader.inputs:
            shader.inputs["Emission Strength"].default_value = 1.0
        updated += 1
    return updated


def main() -> None:
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(args.input))
    updated = restore(args.texture_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output))
    print(f"Restored hair overlays on {updated} material(s); saved {args.output}")


if __name__ == "__main__":
    main()
