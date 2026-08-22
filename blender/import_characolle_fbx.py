"""Import CharaColle FBX exports into Blender and relink extracted textures.

Run from Blender, for example:

    blender --background --python import_characolle_fbx.py -- \
        --input C:\\exports\\Kud \
        --textures C:\\path\\to\\characters\\Kud \
        --output C:\\blends\\characolle_kud.blend

This script assumes SB3Utility has already produced FBX files. It deliberately
does not attempt to parse proprietary .pp/.xx files inside Blender.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True, help="FBX file or directory")
    parser.add_argument("--textures", type=Path, help="Directory containing extracted textures")
    parser.add_argument("--output", type=Path, required=True, help="Output .blend path")
    parser.add_argument(
        "--shape-key-report",
        type=Path,
        help="Optional JSON report describing imported shape keys",
    )
    parser.add_argument("--scale", type=float, default=1.0)
    return parser.parse_args(argv)


def input_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.rglob("*.fbx"), key=lambda item: item.name.lower())


def image_index(root: Path | None) -> dict[str, Path]:
    if not root or not root.exists():
        return {}
    return {
        path.name.casefold(): path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".bmp", ".tga", ".png", ".jpg", ".dds"}
    }


def relink_materials(images: dict[str, Path]) -> int:
    linked = 0
    for material in bpy.data.materials:
        if not material.use_nodes:
            material.use_nodes = True
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        shader = next((node for node in nodes if node.type == "BSDF_PRINCIPLED"), None)
        if shader is None:
            continue
        candidates = [material.name, material.name.replace(" ", "_")]
        texture_path = next(
            (images.get(candidate.casefold()) for candidate in candidates if images.get(candidate.casefold())),
            None,
        )
        if texture_path is None:
            continue
        image = bpy.data.images.load(str(texture_path), check_existing=True)
        texture = nodes.new("ShaderNodeTexImage")
        texture.image = image
        links.new(texture.outputs["Color"], shader.inputs["Base Color"])
        if "Alpha" in texture.outputs and "Alpha" in shader.inputs:
            links.new(texture.outputs["Alpha"], shader.inputs["Alpha"])
        linked += 1
    return linked


def import_file(path: Path, scale: float) -> None:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(path), automatic_bone_orientation=False)
    imported = set(bpy.data.objects) - before
    for obj in imported:
        obj["characolle_source"] = str(path)
        obj.scale *= scale


def shape_key_report() -> dict:
    objects = []
    total = 0
    non_basis = 0
    for obj in sorted(
        (item for item in bpy.data.objects if item.type == "MESH"),
        key=lambda item: item.name.casefold(),
    ):
        keys = obj.data.shape_keys
        if keys is None:
            continue
        blocks = []
        for index, block in enumerate(keys.key_blocks):
            blocks.append(
                {
                    "index": index,
                    "name": block.name,
                    "value": block.value,
                    "min": block.slider_min,
                    "max": block.slider_max,
                    "is_basis": index == 0,
                }
            )
        total += len(blocks)
        non_basis += max(0, len(blocks) - 1)
        objects.append(
            {
                "object": obj.name,
                "mesh": obj.data.name,
                "source": obj.get("characolle_source", ""),
                "shape_keys": blocks,
            }
        )
    return {
        "mesh_objects_with_shape_keys": len(objects),
        "total_shape_keys_including_basis": total,
        "face_pose_shape_keys_excluding_basis": non_basis,
        "objects": objects,
    }


def main() -> None:
    args = parse_args()
    files = input_files(args.input)
    if not files:
        raise SystemExit(f"No FBX files found under {args.input}")
    for path in files:
        import_file(path, args.scale)
    images = image_index(args.textures)
    linked = relink_materials(images)
    shape_keys = shape_key_report()
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene["characolle_import_count"] = len(files)
    scene["characolle_texture_links"] = linked
    scene["characolle_mesh_objects_with_shape_keys"] = shape_keys["mesh_objects_with_shape_keys"]
    scene["characolle_face_pose_shape_keys"] = shape_keys["face_pose_shape_keys_excluding_basis"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output))
    if args.shape_key_report:
        args.shape_key_report.parent.mkdir(parents=True, exist_ok=True)
        args.shape_key_report.write_text(json.dumps(shape_keys, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Imported {len(files)} FBX file(s); relinked {linked} material(s); "
        f"found {shape_keys['face_pose_shape_keys_excluding_basis']} face-pose shape key(s); "
        f"saved {args.output}"
    )


if __name__ == "__main__":
    main()
