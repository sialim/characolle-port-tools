"""Import an FBX mesh and apply extracted XA morphs as Blender shape keys."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True, help="Base FBX file")
    parser.add_argument("--morph-json", type=Path, required=True, help="Output from xa_morph_extract.py")
    parser.add_argument("--output", type=Path, required=True, help="Output Blender file")
    parser.add_argument("--mesh", action="append", help="XX mesh name; repeat for multiple meshes")
    parser.add_argument("--clip", action="append", help="Morph clip name; repeat for multiple clips")
    parser.add_argument("--scale", type=float, default=1.0)
    return parser.parse_args(argv)


def find_mesh(mesh_name: str) -> bpy.types.Object:
    candidates = [
        obj
        for obj in bpy.data.objects
        if obj.type == "MESH" and (obj.name == mesh_name or obj.name.startswith(mesh_name + "_"))
    ]
    if not candidates:
        raise RuntimeError(f"Could not find imported mesh for {mesh_name}")
    candidates.sort(key=lambda obj: (len(obj.data.vertices), obj.name))
    return candidates[-1]


def add_clip_shape_keys(obj: bpy.types.Object, data: dict, clip_name: str) -> int:
    index_sets = {item["name"]: item for item in data["index_sets"]}
    keyframes = {item["name"]: item for item in data["keyframes"]}
    clip = next((item for item in data["clips"] if item["name"] == clip_name), None)
    if clip is None:
        raise RuntimeError(f"Morph clip not found: {clip_name}")
    index_set = index_sets.get(clip_name)
    if index_set is None:
        raise RuntimeError(f"Morph index set not found: {clip_name}")

    if len(obj.data.vertices) <= max(index_set["mesh_indices"], default=-1):
        raise RuntimeError(
            f"{obj.name} has {len(obj.data.vertices)} vertices but {clip_name} "
            f"references vertex {max(index_set['mesh_indices'])}"
        )

    if obj.data.shape_keys is None:
        obj.shape_key_add(name="Basis", from_mix=False)

    seen: set[str] = set()
    created = 0
    for ref in clip["keyframes"]:
        keyframe_name = ref["name"]
        if keyframe_name in seen:
            continue
        seen.add(keyframe_name)
        keyframe = keyframes.get(keyframe_name)
        if keyframe is None:
            raise RuntimeError(f"Morph keyframe not found: {keyframe_name}")
        if max(index_set["morph_indices"], default=-1) >= len(keyframe["positions"]):
            raise RuntimeError(
                f"{clip_name}/{keyframe_name} has {len(keyframe['positions'])} positions "
                f"but references {max(index_set['morph_indices'])}"
            )

        shape = obj.shape_key_add(name=f"{clip_name}__{keyframe_name}", from_mix=False)
        for mesh_index, morph_index in zip(index_set["mesh_indices"], index_set["morph_indices"]):
            shape.data[mesh_index].co = keyframe["positions"][morph_index]
        created += 1
    return created


def main() -> None:
    args = parse_args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(args.input), automatic_bone_orientation=False)
    data = json.loads(args.morph_json.read_text(encoding="utf-8"))
    mesh_names = args.mesh or sorted({clip["mesh"] for clip in data["clips"]})
    created = 0
    processed = []
    for mesh_name in mesh_names:
        target = find_mesh(mesh_name)
        if args.scale != 1.0:
            target.scale *= args.scale
        clips = [
            clip["name"]
            for clip in data["clips"]
            if clip["mesh"] == mesh_name and (not args.clip or clip["name"] in args.clip)
        ]
        for clip in clips:
            created += add_clip_shape_keys(target, data, clip)
        target["characolle_morph_source"] = str(args.morph_json)
        target["characolle_morph_clips"] = clips
        processed.extend(f"{mesh_name}:{clip}" for clip in clips)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output))
    print(f"Added {created} shape keys across {len(processed)} clip export(s); saved {args.output}")


if __name__ == "__main__":
    main()
