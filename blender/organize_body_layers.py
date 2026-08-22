"""Separate imported CharaColle outfit layers into toggleable collections."""

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
    parser.add_argument("--visible-layer", choices=("00", "01", "02"), default="02")
    return parser.parse_args(argv)


def get_collection(name: str) -> bpy.types.Collection:
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


def main() -> None:
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(args.input))
    layers = {layer: get_collection(f"BODY_LAYER_{layer}") for layer in ("00", "01", "02")}
    rigs = {layer: get_collection(f"BODY_RIG_{layer}") for layer in ("00", "01", "02")}
    candidates = get_collection("GMOD_BODYGROUP_CANDIDATES")
    candidates.hide_viewport = False
    candidates.hide_render = False

    for layer, target in layers.items():
        target.hide_viewport = False
        target.hide_render = False
        layer_view = bpy.context.view_layer.layer_collection.children.get(target.name)
        if layer_view is not None:
            layer_view.hide_viewport = layer != args.visible_layer
        target["characolle_outfit_layer"] = layer
    for layer, target in rigs.items():
        target.hide_viewport = False
        target.hide_render = False
        layer_view = bpy.context.view_layer.layer_collection.children.get(target.name)
        if layer_view is not None:
            layer_view.hide_viewport = layer != args.visible_layer

    candidate_view = bpy.context.view_layer.layer_collection.children.get(candidates.name)
    if candidate_view is not None:
        candidate_view.hide_viewport = True

    for obj in list(bpy.data.objects):
        match = re.match(r"BODY_(\d\d)__", obj.name)
        if not match:
            continue
        layer = match.group(1)
        target = layers[layer] if obj.type == "MESH" else rigs[layer]
        move_to_collection(obj, target)
        if obj.type == "MESH" and obj.get("characolle_bodygroup_candidate"):
            if candidates.objects.get(obj.name) is None:
                candidates.objects.link(obj)

    candidates["characolle_role"] = "candidate_bodygroups"
    bpy.context.scene["characolle_visible_body_layer"] = args.visible_layer
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output))
    print(f"Organized body layers; visible layer {args.visible_layer}; saved {args.output}")


if __name__ == "__main__":
    main()
