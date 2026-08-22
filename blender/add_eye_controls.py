"""Add eye control bones and pupil controls to a CharaColle scene."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def world_bounds(obj: bpy.types.Object) -> tuple[Vector, Vector]:
    points = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
    return (
        Vector((min(point.x for point in points), min(point.y for point in points), min(point.z for point in points))),
        Vector((max(point.x for point in points), max(point.y for point in points), max(point.z for point in points))),
    )


def add_front_cap_key(obj: bpy.types.Object) -> bool:
    if obj.type != "MESH" or not obj.data.vertices:
        return False
    if obj.data.shape_keys and obj.data.shape_keys.key_blocks.get("Pupil_Small"):
        return False

    minimum, maximum = world_bounds(obj)
    center = (minimum + maximum) * 0.5
    radius_y = max((maximum.y - minimum.y) * 0.5, 1e-7)
    inverse = obj.matrix_world.inverted()
    basis = obj.shape_key_add(name="Basis") if obj.data.shape_keys is None else obj.data.shape_keys.key_blocks[0]
    key = obj.shape_key_add(name="Pupil_Small")

    for vertex, basis_vertex, key_vertex in zip(obj.data.vertices, basis.data, key.data):
        point = obj.matrix_world @ basis_vertex.co
        frontness = (center.y - point.y) / radius_y
        influence = max(0.0, min(1.0, (frontness - 0.10) / 0.90))
        influence = influence * influence * (3.0 - 2.0 * influence)
        target = point.copy()
        target.x = center.x + (point.x - center.x) * (1.0 - 0.28 * influence)
        target.z = center.z + (point.z - center.z) * (1.0 - 0.28 * influence)
        key_vertex.co = inverse @ target

    key.value = 0.0
    obj["characolle_pupil_control"] = "Pupil_Small uses a front-cap geometry approximation because the pupil is texture-painted."
    return True


def make_bone(armature: bpy.types.Object, name: str, world_head: Vector, parent_name: str | None) -> None:
    armature_space = armature.matrix_world.inverted()
    head = armature_space @ world_head
    front = armature_space.to_3x3() @ Vector((0.0, -0.003, 0.0))
    if front.length == 0:
        front = Vector((0.0, 0.0, 0.003))
    front.normalize()

    edit_bone = armature.data.edit_bones.get(name) or armature.data.edit_bones.new(name)
    edit_bone.head = head
    edit_bone.tail = head + front * 0.004
    edit_bone.use_connect = False
    if parent_name and armature.data.edit_bones.get(parent_name):
        edit_bone.parent = armature.data.edit_bones[parent_name]


def parent_eye_root(obj: bpy.types.Object, armature: bpy.types.Object, bone_name: str) -> None:
    world = obj.matrix_world.copy()
    obj.parent = armature
    obj.parent_type = "BONE"
    obj.parent_bone = bone_name
    obj.matrix_world = world
    obj["characolle_eye_control_bone"] = bone_name


def add_eye_controls() -> int:
    armature = bpy.data.objects.get("o_N_kao_all")
    if armature is None or armature.type != "ARMATURE":
        raise RuntimeError("Could not find the head armature o_N_kao_all")

    source_names = {"eye_L": "o_N_eye_L", "eye_R": "o_N_eye_R"}
    parent_name = "o01_J_coa" if armature.data.bones.get("o01_J_coa") else None
    locations: dict[str, Vector] = {}
    for bone_name, source_name in source_names.items():
        source = bpy.data.objects.get(source_name)
        if source is None:
            raise RuntimeError(f"Could not find eye marker {source_name}")
        locations[bone_name] = source.matrix_world.translation.copy()

    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for bone_name, location in locations.items():
        make_bone(armature, bone_name, location, parent_name)
    bpy.ops.object.mode_set(mode="POSE")
    for bone_name in source_names:
        armature.pose.bones[bone_name]["characolle_role"] = "eye_pose_control"
    bpy.ops.object.mode_set(mode="OBJECT")

    for side in source_names:
        bone_name = side
        root = bpy.data.objects.get("P_" + side)
        if root is None:
            raise RuntimeError(f"Could not find eye root P_{side}")
        parent_eye_root(root, armature, bone_name)
        for suffix in ("_0", "_1", "_2"):
            eye_mesh = bpy.data.objects.get("P_" + side + suffix)
            if eye_mesh is not None:
                add_front_cap_key(eye_mesh)

    armature["characolle_eye_bones"] = "eye_L,eye_R"
    armature["characolle_eye_bone_parent"] = parent_name or ""
    return 2


def main() -> None:
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(args.input))
    count = add_eye_controls()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output))
    print(f"Added {count} eye control bones and pupil controls; saved {args.output}")


if __name__ == "__main__":
    main()
