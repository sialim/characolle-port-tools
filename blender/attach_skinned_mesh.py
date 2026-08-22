"""Attach selected CharaColle meshes to a shared armature."""

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
    parser.add_argument("--armature", required=True)
    parser.add_argument("--mesh", action="append", required=True)
    return parser.parse_args(argv)


def attach_mesh(obj: bpy.types.Object, armature: bpy.types.Object) -> int:
    if obj.type != "MESH":
        raise RuntimeError(f"{obj.name} is not a mesh")

    matching_groups = sum(1 for group in obj.vertex_groups if armature.data.bones.get(group.name))
    world = obj.matrix_world.copy()
    obj.parent = armature
    obj.parent_type = "OBJECT"
    obj.matrix_world = world

    modifier = next((item for item in obj.modifiers if item.type == "ARMATURE"), None)
    if modifier is None:
        modifier = obj.modifiers.new(name="CHARACOLLE_SHARED_RIG", type="ARMATURE")
    modifier.object = armature
    obj["characolle_shared_armature"] = armature.name
    obj["characolle_matching_bone_groups"] = matching_groups
    return matching_groups


def main() -> None:
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(args.input))
    armature = bpy.data.objects.get(args.armature)
    if armature is None or armature.type != "ARMATURE":
        raise RuntimeError(f"Could not find armature {args.armature}")

    for name in args.mesh:
        obj = bpy.data.objects.get(name)
        if obj is None:
            raise RuntimeError(f"Could not find mesh {name}")
        matching = attach_mesh(obj, armature)
        if matching == 0:
            raise RuntimeError(f"{name} has no vertex groups matching {args.armature}")
        print(f"Attached {name} to {args.armature} using {matching} matching bone group(s)")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output))
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
