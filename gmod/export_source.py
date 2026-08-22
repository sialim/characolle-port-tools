"""Prepare a CharaColle scene and export its GMod mesh groups with Source Tools."""

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
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-tools", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--material-path", required=True)
    parser.add_argument("--format", choices=("DMX", "SMD"), default="DMX")
    parser.add_argument("--max-influences", type=int, default=3)
    parser.add_argument("--keep-mantle-bones", action="store_true")
    parser.add_argument("--canonical-layer", choices=("00", "01", "02", "03", "04"))
    return parser.parse_args(argv)


def register_source_tools(path: Path) -> None:
    sys.path.insert(0, str(path))
    import io_scene_valvesource

    io_scene_valvesource.register()


def copy_bones(canonical: bpy.types.Object, source: bpy.types.Object) -> int:
    missing = set(bone.name for bone in source.data.bones) - set(bone.name for bone in canonical.data.bones)
    if not missing:
        return 0
    bpy.ops.object.mode_set(mode="OBJECT") if bpy.context.object and bpy.context.object.mode != "OBJECT" else None
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    canonical.select_set(True)
    bpy.context.view_layer.objects.active = canonical
    inverse = canonical.matrix_world.inverted()
    bpy.ops.object.mode_set(mode="EDIT")
    copied: set[str] = set()

    def copy_one(name: str) -> None:
        if name in copied or canonical.data.edit_bones.get(name):
            copied.add(name)
            return
        source_bone = source.data.bones[name]
        if source_bone.parent and source_bone.parent.name not in canonical.data.edit_bones:
            copy_one(source_bone.parent.name)
        edit_bone = canonical.data.edit_bones.new(name)
        edit_bone.matrix = inverse @ source.matrix_world @ source_bone.matrix_local
        edit_bone.use_connect = False
        edit_bone.use_deform = source_bone.use_deform
        if source_bone.parent:
            edit_bone.parent = canonical.data.edit_bones.get(source_bone.parent.name)
        copied.add(name)

    for name in sorted(missing):
        copy_one(name)
    bpy.ops.object.mode_set(mode="OBJECT")
    return len(missing)


def unhide_object_collection(obj: bpy.types.Object) -> None:
    obj.hide_set(False)
    obj.hide_viewport = False

    def visit(layer: bpy.types.LayerCollection) -> None:
        if layer.collection in obj.users_collection:
            layer.hide_viewport = False
            layer.exclude = False
        for child in layer.children:
            visit(child)

    for layer in bpy.context.view_layer.layer_collection.children:
        visit(layer)


def prepare_single_armature(canonical_layer: str | None = None) -> dict:
    canonical = None
    if canonical_layer:
        canonical = next(
            (
                obj
                for obj in bpy.data.objects
                if obj.type == "ARMATURE" and obj.name.startswith(f"BODY_{canonical_layer}__")
            ),
            None,
        )
    if canonical is None:
        canonical = bpy.data.objects.get(bpy.context.scene.get("characolle_shared_body_rig", ""))
    if canonical is None:
        preferred = bpy.context.scene.get("characolle_canonical_body_layer", "02")
        canonical = next(
            (
                obj
                for obj in bpy.data.objects
                if obj.type == "ARMATURE" and obj.name.startswith(f"BODY_{preferred}__")
            ),
            None,
        )
    if canonical is None:
        canonical = next(
            (
                obj
                for obj in bpy.data.objects
                if obj.type == "ARMATURE" and obj.name.startswith(("BODY_03__", "BODY_02__"))
            ),
            None,
        )
    if canonical is None:
        raise RuntimeError("Could not find the shared body armature")
    unhide_object_collection(canonical)
    old_armatures = {obj for obj in bpy.data.objects if obj.type == "ARMATURE" and obj != canonical}
    copied_bones = sum(copy_bones(canonical, source) for source in old_armatures)
    canonical_bones = {bone.name for bone in canonical.data.bones}
    rebound = 0
    for obj in list(bpy.data.objects):
        old_parent = obj.parent in old_armatures
        old_modifiers = [modifier for modifier in obj.modifiers if modifier.type == "ARMATURE" and modifier.object in old_armatures]
        if not old_parent and not old_modifiers:
            continue
        world = obj.matrix_world.copy()
        if obj.type == "MESH":
            for modifier in old_modifiers:
                modifier.object = canonical
            if not any(modifier.type == "ARMATURE" and modifier.object == canonical for modifier in obj.modifiers):
                matching = [group.name for group in obj.vertex_groups if group.name in canonical_bones]
                if matching:
                    modifier = obj.modifiers.new(name="CHARACOLLE_EXPORT_RIG", type="ARMATURE")
                    modifier.object = canonical
            if old_parent:
                obj.parent = canonical
                obj.parent_type = "OBJECT"
                obj.matrix_world = world
            rebound += 1
        elif old_parent:
            parent_bone = obj.parent_bone if obj.parent_type == "BONE" else ""
            obj.parent = canonical
            if parent_bone and parent_bone in canonical_bones:
                obj.parent_type = "BONE"
                obj.parent_bone = parent_bone
            else:
                obj.parent_type = "OBJECT"
            obj.matrix_world = world

    for armature in old_armatures:
        bpy.data.objects.remove(armature, do_unlink=True)
    return {"armature": canonical.name, "copied_bones": copied_bones, "rebound_objects": rebound, "removed_armatures": len(old_armatures)}


def prune_weights(max_influences: int) -> int:
    changed = 0
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        modifiers = [modifier for modifier in obj.modifiers if modifier.type == "ARMATURE" and modifier.object]
        if not modifiers:
            continue
        bone_names = {bone.name for bone in modifiers[0].object.data.bones}
        for vertex in obj.data.vertices:
            links = [(group.group, group.weight) for group in vertex.groups if obj.vertex_groups[group.group].name in bone_names]
            if len(links) <= max_influences:
                continue
            links.sort(key=lambda item: item[1], reverse=True)
            keep = links[:max_influences]
            keep_ids = {group_id for group_id, _ in keep}
            total = sum(weight for _, weight in keep)
            for group_id, _ in links[max_influences:]:
                obj.vertex_groups[group_id].remove([vertex.index])
            if total > 0:
                for group_id, weight in keep:
                    obj.vertex_groups[group_id].add([vertex.index], weight / total, "REPLACE")
            changed += 1
    return changed


def clean_shape_names() -> int:
    changed = 0
    used_names: set[str] = set()
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.data.shape_keys is None:
            continue
        for key in obj.data.shape_keys.key_blocks:
            if key.name == "Basis":
                continue
            original = key.name
            tail = original.rsplit("__", 1)[-1]
            parts = re.findall(r"[A-Za-z0-9]+", tail)
            cleaned = "".join(part[:1].upper() + part[1:] for part in parts)
            if not cleaned:
                cleaned = "Flex"
            if cleaned in used_names:
                suffix = re.sub(r"^P_", "", obj.name, flags=re.IGNORECASE)
                suffix = re.sub(r"[^A-Za-z0-9]+", "", suffix)
                cleaned = f"{cleaned}{suffix or 'Mesh'}"
                serial = 2
                candidate = cleaned
                while candidate in used_names:
                    candidate = f"{cleaned}{serial}"
                    serial += 1
                cleaned = candidate
            if cleaned != original:
                key.name = cleaned
                changed += 1
            used_names.add(cleaned)
    return changed


def simplify_mantle_bones() -> dict:
    """Keep the cape attached to the torso without exceeding Source's bone limit."""
    canonical = bpy.data.objects.get(bpy.context.scene.get("characolle_shared_body_rig", ""))
    if canonical is None:
        return {"removed_mantle_bones": 0, "simplified_mantle_meshes": 0}
    bones = {bone.name for bone in canonical.data.bones}
    mantle_names = {name for name in bones if "mant" in name.casefold()}
    if not mantle_names:
        return {"removed_mantle_bones": 0, "simplified_mantle_meshes": 0}
    fallback = next((name for name in ("o01_J_Spin04", "o01_J_Spin03", "o01_J_Spin01") if name in bones), None)
    if fallback is None:
        raise RuntimeError("Could not find a torso fallback bone for the mantle export")

    simplified = 0
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        mantle_groups = [group for group in obj.vertex_groups if group.name in mantle_names]
        if not mantle_groups:
            continue
        fallback_group = obj.vertex_groups.get(fallback) or obj.vertex_groups.new(name=fallback)
        mantle_indices = {group.index for group in mantle_groups}
        for vertex in obj.data.vertices:
            mantle_weight = 0.0
            fallback_weight = 0.0
            for link in vertex.groups:
                if link.group in mantle_indices:
                    mantle_weight += link.weight
                elif link.group == fallback_group.index:
                    fallback_weight = link.weight
            if mantle_weight:
                fallback_group.add([vertex.index], fallback_weight + mantle_weight, "REPLACE")
        for group in mantle_groups:
            obj.vertex_groups.remove(group)
        simplified += 1

    bpy.ops.object.mode_set(mode="OBJECT") if bpy.context.object and bpy.context.object.mode != "OBJECT" else None
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    canonical.select_set(True)
    bpy.context.view_layer.objects.active = canonical
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = canonical.data.edit_bones
    removed = set(mantle_names)
    for edit_bone in list(edit_bones):
        if edit_bone.name not in removed:
            continue
        for child in list(edit_bone.children):
            parent = edit_bone.parent
            while parent is not None and parent.name in removed:
                parent = parent.parent
            world = child.matrix.copy()
            child.parent = parent
            child.matrix = world
    for name in sorted(removed):
        edit_bone = edit_bones.get(name)
        if edit_bone is not None:
            edit_bones.remove(edit_bone)
    bpy.ops.object.mode_set(mode="OBJECT")
    return {"removed_mantle_bones": len(removed), "simplified_mantle_meshes": simplified, "mantle_fallback": fallback}


def temporary_collection(name: str, objects: list[bpy.types.Object]) -> bpy.types.Collection:
    collection = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(collection)
    for obj in objects:
        collection.objects.link(obj)
    return collection


def export_collection(collection: bpy.types.Collection, output: Path, material_path: str, export_format: str) -> None:
    scene = bpy.context.scene
    scene.vs.export_path = str(output)
    scene.vs.export_format = export_format
    scene.vs.material_path = material_path
    scene.vs.smd_format = "SOURCE"
    scene.vs.up_axis = "Z"
    bpy.ops.export_scene.smd(collection=collection.name, export_scene=False)


def main() -> None:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    register_source_tools(args.source_tools)
    bpy.ops.wm.open_mainfile(filepath=str(args.input))
    staging = prepare_single_armature(args.canonical_layer)
    if not args.keep_mantle_bones:
        staging.update(simplify_mantle_bones())
    staging["pruned_vertices"] = prune_weights(args.max_influences)
    staging["renamed_shape_keys"] = clean_shape_names()
    args.output.mkdir(parents=True, exist_ok=True)
    exported = []

    def objects_from(entries: list[dict]) -> list[bpy.types.Object]:
        result = []
        for entry in entries:
            obj = bpy.data.objects.get(entry["name"])
            if obj is None:
                raise RuntimeError(f"Manifest object is missing from scene: {entry['name']}")
            result.append(obj)
        return result

    groups = [("base", manifest.get("base_objects", [])), ("head", manifest.get("head_objects", []))]
    groups.extend((f"bg_{entry['name']}", [entry["mesh"]]) for entry in manifest.get("bodygroups", []))
    for name, entries in groups:
        objects = objects_from(entries)
        collection = temporary_collection(name, objects)
        export_collection(collection, args.output, args.material_path, args.format)
        exported.append(name + (".dmx" if args.format == "DMX" else ".smd"))

    report = {"character": manifest["character"], "format": args.format, "exported": exported, "staging": staging}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Exported {len(exported)} Source files to {args.output}")


if __name__ == "__main__":
    main()
