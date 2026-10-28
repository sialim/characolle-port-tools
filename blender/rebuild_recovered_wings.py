"""Restore recovered wing geometry and pivots from the original evaluated FBX pose."""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import bpy
from mathutils import Matrix

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gmod"))
from scene_manifest import mesh_entry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--wings-fbx", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-scale", type=float, default=400)
    parser.add_argument("--model-name")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(output)
    if not 0 < args.source_scale < 100000:
        raise ValueError("Invalid original-to-recovered coordinate scale")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not manifest.get("scene", {}).get("recovered_from_compiled"):
        raise ValueError("Expected a recovered outfit manifest")
    source, fbx = Path(manifest["source_blend"]).resolve(), args.wings_fbx.resolve()
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    bpy.ops.wm.open_mainfile(filepath=str(source))
    rig = bpy.data.objects[bpy.context.scene["characolle_shared_body_rig"]]
    groups = [g for g in manifest["bodygroups"] if re.search(r"_p_hane_[01]$", g["name"])]
    if len(groups) != 2:
        raise ValueError("Expected the two original P_hane wing submeshes")
    old_wings = {bpy.data.objects[g["mesh"]["name"]] for g in groups}
    materials = {re.sub(r"^BODY_\d\d__", "", mat.name): mat
                 for obj in old_wings for mat in obj.data.materials}
    other = [obj for obj in bpy.data.objects if obj.type == "MESH" and obj not in old_wings]
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    before = {obj.name: [obj.evaluated_get(graph).matrix_world @ v.co
                        for v in obj.evaluated_get(graph).data.vertices] for obj in other}
    original = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(fbx), automatic_bone_orientation=False)
    imported = set(bpy.data.objects) - original
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    wings = sorted([obj for obj in imported if obj.type == "MESH"], key=lambda obj: obj.name)
    if {obj.name for obj in wings} != {"P_hane_0", "P_hane_1"}:
        raise ValueError("FBX must contain only the original wing meshes")
    source_rigs = [obj for obj in imported if obj.type == "ARMATURE"]
    if len(source_rigs) != 1:
        raise ValueError("Expected one original wing armature")
    source_rig = source_rigs[0]
    scale = Matrix.Scale(args.source_scale, 4)
    points = {obj: [scale @ obj.evaluated_get(graph).matrix_world @ v.co
                    for v in obj.evaluated_get(graph).data.vertices] for obj in wings}
    used = {obj.vertex_groups[g.group].name for obj in wings
            for vertex in obj.data.vertices for g in vertex.groups if g.weight > 0}
    if not all(name.startswith("J_hane") or name == "P_hane" for name in used):
        raise ValueError("Unexpected non-wing weights in the original wing meshes")
    for obj in other:
        active = {obj.vertex_groups[g.group].name for vertex in obj.data.vertices
                  for g in vertex.groups if g.weight > 0}
        if active & used:
            raise ValueError(f"Wing bone is also used by another mesh: {obj.name}")
    transform = scale @ source_rig.matrix_world
    bone_data = {name: (transform @ source_rig.pose.bones[name].matrix,
                       (transform.to_3x3() @ (source_rig.pose.bones[name].tail
                                             - source_rig.pose.bones[name].head)).length,
                       source_rig.data.bones[name].parent.name
                       if source_rig.data.bones[name].parent else "o01_J_Spin04")
                 for name in used}
    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    for name, (matrix, length, _) in bone_data.items():
        bone = rig.data.edit_bones.get(name) or rig.data.edit_bones.new(name)
        bone.use_connect = False
        bone.matrix = rig.matrix_world.inverted() @ matrix
        bone.length = max(length, 0.001)
    for name, (_, _, parent) in bone_data.items():
        rig.data.edit_bones[name].parent = rig.data.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    for name in used:
        rig.pose.bones[name].matrix_basis = Matrix.Identity(4)
    replacements = {}
    for obj in wings:
        original_name = obj.name
        if len(points[obj]) != len(obj.data.vertices):
            raise ValueError("Evaluated wings changed vertex topology")
        obj.parent = None
        obj.matrix_world = Matrix.Identity(4)
        for modifier in list(obj.modifiers):
            obj.modifiers.remove(modifier)
        for vertex, point in zip(obj.data.vertices, points[obj]):
            vertex.co = point
        for index, material in enumerate(obj.data.materials):
            name = re.sub(r"\.\d{3}$", "", material.name)
            obj.data.materials[index] = materials[name]
            materials[name]["characolle_two_sided"] = True
        for group in list(obj.vertex_groups):
            if group.name not in used:
                obj.vertex_groups.remove(group)
        obj.modifiers.new("Armature", "ARMATURE").object = rig
        obj.name = "REPAIRED_" + original_name
        replacements[original_name.casefold()] = obj
    for obj in old_wings | (imported - set(wings)):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    def error(objects, expected):
        if any(len(obj.evaluated_get(graph).data.vertices) != len(expected[obj]) for obj in objects):
            raise ValueError("Repair changed mesh vertex counts")
        return max((obj.evaluated_get(graph).matrix_world @ vertex.co - point).length
                   for obj in objects for vertex, point in
                   zip(obj.evaluated_get(graph).data.vertices, expected[obj]))
    other_error = error(other, {obj: before[obj.name] for obj in other})
    wing_error = error(wings, points)
    if other_error > 0.001 or wing_error > 0.001:
        raise ValueError(f"Unexpected geometry change: other={other_error}, wings={wing_error}")
    for group in groups:
        obj = replacements[re.sub(r"^\d\d_", "", group["name"])]
        group["mesh"], group["objects"] = mesh_entry(obj), [obj.name]
    if len(rig.data.bones) > 256:
        raise ValueError("Rebuilt skeleton exceeds the Source bone limit")
    output.mkdir(parents=True)
    character = re.sub(r"[^A-Za-z0-9_]+", "_", manifest["character"])
    blend = output / (character + "_wings_repaired.blend")
    manifest["source_blend"] = str(blend)
    manifest["model_name"] = args.model_name or f"characolle/{character.lower()}_uniform_wings_repaired"
    repair = manifest.setdefault("repair_sources", {})
    repair["wings_fbx"] = str(fbx)
    repair.setdefault("sha256", {})[fbx.name] = hashlib.sha256(fbx.read_bytes()).hexdigest()
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    report = {"source": str(source), "source_sha256": source_hash,
              "other_mesh_maximum_error": other_error, "evaluated_wing_error": wing_error,
              "wing_bones": sorted(used), "bone_count": len(rig.data.bones)}
    (output / "wing_repair.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
        raise RuntimeError("Original recovered scene changed during repair")
    print("Restored evaluated wings and pivots; other geometry error", other_error)


if __name__ == "__main__":
    main()
