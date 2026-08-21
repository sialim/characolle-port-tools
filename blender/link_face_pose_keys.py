"""Drive eyelash and tear morphs from matching face expression keys."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy


FACE_TO_NAMIDA = {
    "Face_top__me_base_toji": "namida__namida_bacetoji",
    "Face_top__me_base": "namida__namida_bace",
    "Face_top__me_winL": "namida__namidaL",
    "Face_top__me_winR": "namida__namidaR",
    "Face_top__me_ten": "namida__namidaten",
    "Face_top__me_niko": "namida__namidanik",
}


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(args.input))
    face = bpy.data.objects.get("P_face_0")
    namida = bpy.data.objects.get("P_namida_0")
    if face is None or namida is None or face.data.shape_keys is None or namida.data.shape_keys is None:
        raise RuntimeError("Expected P_face_0 and P_namida_0 shape-key meshes")

    face_keys = face.data.shape_keys.key_blocks
    namida_keys = namida.data.shape_keys.key_blocks
    linked = []
    for face_name, namida_name in FACE_TO_NAMIDA.items():
        if face_name not in face_keys or namida_name not in namida_keys:
            continue
        target = namida_keys[namida_name]
        target.value = 0.0
        try:
            target.driver_remove("value")
        except TypeError:
            pass
        fcurve = target.driver_add("value")
        driver = fcurve.driver
        driver.type = "AVERAGE"
        variable = driver.variables.new()
        variable.name = "face_pose"
        variable.type = "SINGLE_PROP"
        variable.targets[0].id = face
        variable.targets[0].data_path = f'data.shape_keys.key_blocks["{face_name}"].value'
        linked.append({"face": face_name, "namida": namida_name})

    namida["characolle_face_pose_links"] = linked
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output))
    print(f"Linked {len(linked)} namida pose driver(s); saved {args.output}")


if __name__ == "__main__":
    main()
