"""Audit shape keys in an existing Blender file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True, help="Blender file to inspect")
    parser.add_argument("--output", type=Path, required=True, help="JSON report path")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(args.input))
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
        blocks = [
            {
                "index": index,
                "name": block.name,
                "value": block.value,
                "min": block.slider_min,
                "max": block.slider_max,
                "is_basis": index == 0,
            }
            for index, block in enumerate(keys.key_blocks)
        ]
        total += len(blocks)
        non_basis += max(0, len(blocks) - 1)
        objects.append({"object": obj.name, "mesh": obj.data.name, "shape_keys": blocks})
    report = {
        "file": str(args.input),
        "mesh_objects_with_shape_keys": len(objects),
        "total_shape_keys_including_basis": total,
        "face_pose_shape_keys_excluding_basis": non_basis,
        "objects": objects,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Found {non_basis} face-pose shape key(s) across "
        f"{len(objects)} mesh object(s); wrote {args.output}"
    )


if __name__ == "__main__":
    main()
