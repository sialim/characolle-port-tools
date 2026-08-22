"""Append CharaColle body and outfit FBX exports to an existing head scene."""

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
    parser.add_argument("--fbx", type=Path, action="append", required=True)
    parser.add_argument("--material-json", type=Path, required=True)
    parser.add_argument("--textures", type=Path, required=True)
    parser.add_argument("--body-prefix", default="c02_01", help="Source body prefix, such as c02_01 or c02_02")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def collection(name: str) -> bpy.types.Collection:
    result = bpy.data.collections.get(name)
    if result is None:
        result = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(result)
    return result


def move_to_collection(obj: bpy.types.Object, target: bpy.types.Collection) -> None:
    if target.objects.get(obj.name) is None:
        target.objects.link(obj)
    for source in list(obj.users_collection):
        if source != target:
            source.objects.unlink(obj)


def image_index(root: Path) -> dict[str, bpy.types.Image]:
    result = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".bmp", ".tga", ".png", ".jpg", ".dds"}:
            continue
        image = bpy.data.images.load(str(path), check_existing=True)
        image.pack()
        result[path.name.casefold()] = image
    return result


def original_material_name(name: str) -> str:
    return re.sub(r"\.\d{3}$", "", name)


def set_transparency(material: bpy.types.Material, enabled: bool) -> None:
    if hasattr(material, "surface_render_method"):
        material.surface_render_method = "DITHERED"
    elif hasattr(material, "blend_method"):
        material.blend_method = "BLEND" if enabled else "OPAQUE"


def rebuild_material(material: bpy.types.Material, source: dict, images: dict[str, bpy.types.Image]) -> bool:
    slots = source.get("textures", [])
    diffuse_name = next((name for name in slots if name), "")
    image = images.get(diffuse_name.casefold())
    if image is None:
        return False

    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (320, 0)
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.location = (0, 0)
    shader.inputs["Roughness"].default_value = 0.78
    shader.inputs["Specular IOR Level"].default_value = 0.2
    texture = nodes.new("ShaderNodeTexImage")
    texture.name = "CharaColle Color"
    texture.label = image.name
    texture.location = (-320, 80)
    texture.image = image
    image.colorspace_settings.name = "sRGB"
    links.new(texture.outputs["Color"], shader.inputs["Base Color"])

    transparent = image.channels == 4 and ("nip" in diffuse_name.casefold() or "pantu" in material.name.casefold())
    if transparent and "Alpha" in texture.outputs and "Alpha" in shader.inputs:
        links.new(texture.outputs["Alpha"], shader.inputs["Alpha"])
    set_transparency(material, transparent)
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    material.diffuse_color = (1.0, 1.0, 1.0, 1.0)
    return True


def source_for_fbx(fbx: Path, material_data: dict, body_prefix: str) -> dict:
    match = re.search(r"body_(\d\d)_", fbx.stem)
    if not match:
        raise RuntimeError(f"Could not determine body layer from {fbx.name}")
    key = f"{body_prefix}_{match.group(1)}_00.xx"
    for path, data in material_data.items():
        if path.casefold().endswith(key.casefold()):
            return data
    raise RuntimeError(f"No material data found for {key}")


def main() -> None:
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(args.input))
    material_data = json.loads(args.material_json.read_text(encoding="utf-8"))
    images = image_index(args.textures)
    body_collection = collection("CHARACTER_BODY")
    rig_collection = collection("BODY_RIG")
    updated_materials = 0
    imported_meshes = []

    for fbx in sorted(args.fbx, key=lambda item: item.name.casefold()):
        source = source_for_fbx(fbx, material_data, args.body_prefix)
        source_materials = {item["name"]: item for item in source["materials"]}
        before = set(bpy.data.objects)
        bpy.ops.import_scene.fbx(filepath=str(fbx), automatic_bone_orientation=False)
        imported = set(bpy.data.objects) - before
        layer = fbx.stem.split("body_")[-1].split("_")[0]
        for obj in imported:
            obj["characolle_source"] = str(fbx)
            obj["characolle_body_layer"] = layer
            obj.name = f"BODY_{layer}__{obj.name}"
            if obj.type == "MESH":
                move_to_collection(obj, body_collection)
                imported_meshes.append(obj)
                for material in obj.data.materials:
                    if material is None:
                        continue
                    original = original_material_name(material.name)
                    mapping = source_materials.get(original)
                    if mapping is not None:
                        material.name = f"BODY_{layer}__{original}"
                        if rebuild_material(material, mapping, images):
                            updated_materials += 1
            else:
                move_to_collection(obj, rig_collection)

    body_collection["characolle_role"] = "body_and_outfits"
    for obj in imported_meshes:
        obj["characolle_bodygroup_candidate"] = obj.name.casefold().find("pantu") >= 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output))
    print(
        f"Appended {len(imported_meshes)} body mesh object(s); rebuilt {updated_materials} material(s); "
        f"saved {args.output}"
    )


if __name__ == "__main__":
    main()
