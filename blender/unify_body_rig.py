"""Unify outfit armatures and attach the head rig to the shared body rig."""

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
    parser.add_argument("--canonical-layer", choices=("00", "01", "02", "03", "04"), default="02")
    return parser.parse_args(argv)


def body_rigs() -> dict[str, bpy.types.Object]:
    result: dict[str, bpy.types.Object] = {}
    for obj in bpy.data.objects:
        if obj.type != "ARMATURE":
            continue
        match = re.match(r"BODY_(\d\d)__SCENE_ROOT", obj.name)
        if match:
            result[match.group(1)] = obj
    return result


def link_only(obj: bpy.types.Object, collection: bpy.types.Collection) -> None:
    if collection.objects.get(obj.name) is None:
        collection.objects.link(obj)
    for old in list(obj.users_collection):
        if old != collection:
            old.objects.unlink(obj)


def copy_missing_bones(canonical: bpy.types.Object, source: bpy.types.Object) -> int:
    missing = set(bone.name for bone in source.data.bones) - set(bone.name for bone in canonical.data.bones)
    if not missing:
        return 0

    inverse = canonical.matrix_world.inverted()
    bpy.context.view_layer.objects.active = canonical
    canonical.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    copied: set[str] = set()

    def copy_bone(name: str) -> None:
        if name in copied or canonical.data.edit_bones.get(name):
            copied.add(name)
            return
        source_bone = source.data.bones[name]
        if source_bone.parent and source_bone.parent.name not in canonical.data.edit_bones:
            copy_bone(source_bone.parent.name)
        edit_bone = canonical.data.edit_bones.new(name)
        edit_bone.matrix = inverse @ source.matrix_world @ source_bone.matrix_local
        edit_bone.use_connect = False
        edit_bone.use_deform = source_bone.use_deform
        if source_bone.parent:
            edit_bone.parent = canonical.data.edit_bones.get(source_bone.parent.name)
        copied.add(name)

    for name in sorted(missing):
        copy_bone(name)
    bpy.ops.object.mode_set(mode="OBJECT")
    return len(missing)


def reassign_body_meshes(canonical: bpy.types.Object, rigs: set[bpy.types.Object]) -> int:
    updated = 0
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        modifiers = [modifier for modifier in obj.modifiers if modifier.type == "ARMATURE" and modifier.object in rigs]
        if not modifiers:
            continue
        world = obj.matrix_world.copy()
        for modifier in modifiers:
            modifier.object = canonical
        if obj.parent in rigs:
            obj.parent = canonical
            obj.parent_type = "OBJECT"
            obj.matrix_world = world
        updated += 1
    return updated


def reassign_weighted_parented_meshes(canonical: bpy.types.Object, rigs: set[bpy.types.Object]) -> int:
    canonical_bones = {bone.name for bone in canonical.data.bones}
    updated = 0
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.parent not in rigs or obj.parent == canonical:
            continue
        if any(modifier.type == "ARMATURE" for modifier in obj.modifiers):
            continue
        matching = [group.name for group in obj.vertex_groups if group.name in canonical_bones]
        if not matching:
            continue
        world = obj.matrix_world.copy()
        obj.parent = canonical
        obj.parent_type = "OBJECT"
        obj.matrix_world = world
        modifier = obj.modifiers.new(name="CHARACOLLE_SHARED_RIG", type="ARMATURE")
        modifier.object = canonical
        obj["characolle_shared_armature"] = canonical.name
        obj["characolle_matching_bone_groups"] = len(matching)
        updated += 1
    return updated


def attach_head(canonical: bpy.types.Object) -> None:
    head = bpy.data.objects.get("o_N_kao_all")
    if head is None or head.type != "ARMATURE":
        raise RuntimeError("Could not find the head armature o_N_kao_all")
    if canonical.data.bones.get("o01_J_Head") is None:
        raise RuntimeError("The shared body armature has no o01_J_Head bone")
    world = head.matrix_world.copy()
    head.parent = canonical
    head.parent_type = "BONE"
    head.parent_bone = "o01_J_Head"
    head.matrix_world = world
    head["characolle_body_rig"] = canonical.name
    head["characolle_head_parent_bone"] = "o01_J_Head"


def main() -> None:
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(args.input))
    rigs = body_rigs()
    canonical = rigs.get(args.canonical_layer)
    if canonical is None:
        raise RuntimeError(f"Could not find the canonical body rig for layer {args.canonical_layer}")

    copied = sum(copy_missing_bones(canonical, source) for layer, source in rigs.items() if source != canonical)
    updated = reassign_body_meshes(canonical, set(rigs.values()))
    weighted = reassign_weighted_parented_meshes(canonical, set(rigs.values()))

    shared = bpy.data.collections.get("SHARED_BODY_RIG") or bpy.data.collections.new("SHARED_BODY_RIG")
    if shared.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(shared)
    root = canonical.parent
    world = canonical.matrix_world.copy()
    canonical.parent = None
    canonical.matrix_world = world
    link_only(canonical, shared)
    shared.hide_viewport = False
    shared.hide_render = False
    view = bpy.context.view_layer.layer_collection.children.get(shared.name)
    if view is not None:
        view.hide_viewport = False

    source_collection = bpy.data.collections.get("SOURCE_BODY_RIGS") or bpy.data.collections.new("SOURCE_BODY_RIGS")
    if source_collection.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(source_collection)
    for layer, source in rigs.items():
        if source == canonical:
            continue
        source.hide_viewport = True
        source.hide_render = True
        link_only(source, source_collection)
        if source.parent is not None and source.parent.type == "EMPTY":
            source.parent.hide_viewport = True
            source.parent.hide_render = True
            link_only(source.parent, source_collection)
    source_collection.hide_viewport = True
    source_collection.hide_render = True
    source_view = bpy.context.view_layer.layer_collection.children.get(source_collection.name)
    if source_view is not None:
        source_view.hide_viewport = True

    attach_head(canonical)
    canonical["characolle_role"] = "shared_body_rig"
    bpy.context.scene["characolle_canonical_body_layer"] = args.canonical_layer
    bpy.context.scene["characolle_shared_body_rig"] = canonical.name
    bpy.context.scene["characolle_head_parent_bone"] = "o01_J_Head"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output))
    print(
        f"Copied {copied} outfit bones, reassigned {updated} skinned mesh(es), "
        f"rebound {weighted} weighted mesh(es), and attached the head; saved {args.output}"
    )


if __name__ == "__main__":
    main()
