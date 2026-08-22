"""Build a Source/GMod export manifest from a CharaColle Blender scene."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import bpy


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--character", required=True)
    return parser.parse_args(argv)


def slug(value: str) -> str:
    value = re.sub(r"^BODY_\d\d__", "", value)
    value = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_").lower()
    return value or "mesh"


def image_entry(image: bpy.types.Image) -> dict:
    return {
        "name": image.name,
        "filepath": bpy.path.abspath(image.filepath) if image.filepath else "",
        "packed": image.packed_file is not None,
        "size": list(image.size),
    }


def material_entry(material: bpy.types.Material | None) -> dict | None:
    if material is None:
        return None
    images = []
    for node in material.node_tree.nodes if material.use_nodes else []:
        if node.type == "TEX_IMAGE" and node.image is not None:
            images.append(image_entry(node.image))
    return {
        "name": material.name,
        "images": images,
        "base_texture": material.get("characolle_base_texture", ""),
        "overlay_texture": material.get("characolle_overlay_texture", ""),
    }


def mesh_entry(obj: bpy.types.Object) -> dict:
    modifiers = []
    for modifier in obj.modifiers:
        if modifier.type != "ARMATURE":
            continue
        modifiers.append({"type": "ARMATURE", "object": modifier.object.name if modifier.object else ""})
    shape_keys = []
    if obj.data.shape_keys is not None:
        shape_keys = [key.name for key in obj.data.shape_keys.key_blocks if key.name != "Basis"]
    return {
        "name": obj.name,
        "mesh_data": obj.data.name,
        "vertex_count": len(obj.data.vertices),
        "polygon_count": len(obj.data.polygons),
        "materials": [entry for entry in (material_entry(material) for material in obj.data.materials) if entry],
        "shape_keys": shape_keys,
        "armature_modifiers": modifiers,
        "parent": obj.parent.name if obj.parent else "",
        "parent_bone": obj.parent_bone if obj.parent_type == "BONE" else "",
        "vertex_groups": [group.name for group in obj.vertex_groups],
        "bodygroup_candidate": bool(obj.get("characolle_bodygroup_candidate")),
        "source": obj.get("characolle_source", ""),
    }


def collection_meshes(collection: bpy.types.Collection) -> list[dict]:
    return [mesh_entry(obj) for obj in sorted(collection.objects, key=lambda item: item.name.casefold()) if obj.type == "MESH"]


def main() -> None:
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(args.input))
    armature = bpy.data.objects.get(bpy.context.scene.get("characolle_shared_body_rig", ""))
    if armature is None:
        preferred = bpy.context.scene.get("characolle_canonical_body_layer", "02")
        armature = next(
            (
                obj
                for obj in bpy.data.objects
                if obj.type == "ARMATURE" and obj.name.startswith(f"BODY_{preferred}__")
            ),
            None,
        )
    if armature is None:
        armature = next(
            (
                obj
                for obj in bpy.data.objects
                if obj.type == "ARMATURE" and obj.name.startswith(("BODY_03__", "BODY_02__"))
            ),
            None,
        )
    if armature is None:
        raise RuntimeError("Could not find the shared body armature")

    base = bpy.data.collections.get("BODY_BASE")
    head = bpy.data.collections.get("CHARACTER_HEAD")
    bodygroups = []
    for collection in sorted(bpy.data.collections, key=lambda item: item.name.casefold()):
        match = re.fullmatch(r"BODY_LAYER_(\d\d)", collection.name)
        if not match:
            continue
        layer = match.group(1)
        meshes = collection_meshes(collection)
        for mesh in meshes:
            bodygroups.append({
                "name": f"{layer}_{slug(mesh['name'])}",
                "layer": layer,
                "collection": collection.name,
                "objects": [mesh["name"]],
                "default": layer == bpy.context.scene.get("characolle_visible_body_layer", "02"),
                "mesh": mesh,
            })

    head_meshes = collection_meshes(head) if head is not None else []
    base_meshes = collection_meshes(base) if base is not None else []
    bones = []
    for bone in armature.data.bones:
        bones.append({
            "name": bone.name,
            "parent": bone.parent.name if bone.parent else "",
            "deform": bone.use_deform,
        })

    manifest = {
        "format": 1,
        "character": args.character,
        "source_blend": str(args.input),
        "scene": {
            "visible_body_layer": bpy.context.scene.get("characolle_visible_body_layer", "02"),
            "base_body_layer": bpy.context.scene.get("characolle_base_body_layer", "02"),
            "canonical_body_layer": bpy.context.scene.get("characolle_canonical_body_layer", "02"),
            "base_replaced_by_variant": bool(bpy.context.scene.get("characolle_base_body_replaced", False)),
        },
        "armature": {"object": armature.name, "bones": bones},
        "base_objects": base_meshes,
        "head_objects": head_meshes,
        "bodygroups": bodygroups,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(bodygroups)} bodygroup entries, {len(base_meshes)} base mesh entries, and {len(head_meshes)} head mesh entries to {args.output}")


if __name__ == "__main__":
    main()
