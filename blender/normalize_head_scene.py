"""Normalize a CharaColle head scene for Blender inspection and export."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import bpy


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def base_image_name(name: str) -> str:
    name = re.sub(r"\.\d{3}$", "", name)
    return name.casefold()


def image_index() -> dict[str, bpy.types.Image]:
    result: dict[str, bpy.types.Image] = {}
    for image in bpy.data.images:
        result.setdefault(base_image_name(image.name), image)
    return result


def suffix_image(images: dict[str, bpy.types.Image], *suffixes: str) -> bpy.types.Image | None:
    for suffix in suffixes:
        suffix = suffix.casefold()
        for name, image in images.items():
            if name.endswith(suffix):
                return image
    return None


def choose_texture(material_name: str, images: dict[str, bpy.types.Image]) -> bpy.types.Image | None:
    name = material_name.casefold()
    if "namida" in name:
        return suffix_image(images, "_namida.tga")
    elif "hoho" in name:
        return suffix_image(images, "_hoho.tga")
    elif "face_pa_tu" in name or "medama" in name or "mehikari" in name:
        return suffix_image(images, "_eyes.bmp")
    elif "mimi" in name:
        return suffix_image(images, "_mimi.bmp", "_hair.bmp")
    elif "suzu" in name:
        return suffix_image(images, "_suzu.bmp", "_hair.bmp")
    elif "hair" in name or "inumimi" in name:
        return suffix_image(images, "_hair.bmp")
    elif "bousi" in name:
        return suffix_image(images, "_bousi.bmp", "_hair.bmp")
    elif "face" in name or "mimi" in name:
        return suffix_image(images, "_skin.bmp")
    else:
        return None


def set_surface_mode(material: bpy.types.Material, transparent: bool) -> None:
    if hasattr(material, "surface_render_method"):
        material.surface_render_method = "DITHERED" if transparent else "DITHERED"
    elif hasattr(material, "blend_method"):
        material.blend_method = "BLEND" if transparent else "OPAQUE"


def rebuild_materials() -> int:
    images = image_index()
    updated = 0
    for material in bpy.data.materials:
        texture = choose_texture(material.name, images)
        if texture is None:
            continue

        material.use_nodes = True
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        nodes.clear()

        output = nodes.new("ShaderNodeOutputMaterial")
        output.location = (320, 0)
        shader = nodes.new("ShaderNodeBsdfPrincipled")
        shader.location = (0, 0)
        shader.inputs["Roughness"].default_value = 0.72
        shader.inputs["Specular IOR Level"].default_value = 0.25

        color = nodes.new("ShaderNodeTexImage")
        color.name = "CharaColle Color"
        color.label = texture.name
        color.location = (-320, 80)
        color.image = texture
        texture.colorspace_settings.name = "sRGB"
        links.new(color.outputs["Color"], shader.inputs["Base Color"])

        transparent = "namida" in material.name.casefold() or "hoho" in material.name.casefold()
        if transparent and "Alpha" in color.outputs and "Alpha" in shader.inputs:
            links.new(color.outputs["Alpha"], shader.inputs["Alpha"])
            set_surface_mode(material, True)
        else:
            set_surface_mode(material, False)

        links.new(shader.outputs["BSDF"], output.inputs["Surface"])
        material.diffuse_color = (1.0, 1.0, 1.0, 1.0)
        updated += 1
    return updated


def move_to_collection(obj: bpy.types.Object, collection: bpy.types.Collection) -> None:
    if collection.objects.get(obj.name) is None:
        collection.objects.link(obj)
    for old_collection in list(obj.users_collection):
        if old_collection != collection:
            old_collection.objects.unlink(obj)


def normalize_names() -> None:
    for root_name in ("P_face", "P_namida"):
        root = bpy.data.objects.get(root_name)
        mesh = bpy.data.objects.get(root_name + "_0")
        if root is not None and root.type == "EMPTY":
            root.name = root_name + "_Root"
        if mesh is not None and mesh.type == "MESH":
            mesh.name = root_name


def organize_scene() -> None:
    normalize_names()
    mesh_collection = bpy.data.collections.get("CHARACTER_HEAD") or bpy.data.collections.new("CHARACTER_HEAD")
    rig_collection = bpy.data.collections.get("HEAD_RIG") or bpy.data.collections.new("HEAD_RIG")
    if mesh_collection.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(mesh_collection)
    if rig_collection.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(rig_collection)

    for obj in list(bpy.data.objects):
        if obj.type == "MESH":
            move_to_collection(obj, mesh_collection)
        elif obj.type in {"ARMATURE", "EMPTY"}:
            move_to_collection(obj, rig_collection)

    for obj_name in ("P_face", "P_namida"):
        obj = bpy.data.objects.get(obj_name)
        if obj is not None:
            obj["characolle_role"] = "face" if obj_name == "P_face" else "eyelash_and_tear_overlay"

    bpy.context.scene["characolle_scene_layout"] = "head_meshes_and_rig_collections"


def main() -> None:
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(args.input))
    organize_scene()
    updated = rebuild_materials()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output))
    print(f"Normalized head scene; rebuilt {updated} material(s); saved {args.output}")


if __name__ == "__main__":
    main()
