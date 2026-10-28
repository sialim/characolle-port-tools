"""Run in Blender to verify reduced cape chains preserve weights and rest geometry."""
import importlib.util
from pathlib import Path

import bpy

spec = importlib.util.spec_from_file_location(
    "export_source", Path(__file__).resolve().parents[1] / "gmod/export_source.py")
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)
bpy.ops.wm.read_factory_settings(use_empty=True)
armature = bpy.data.armatures.new("rig")
rig = bpy.data.objects.new("rig", armature)
bpy.context.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig
rig.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
names = ["o01_J_Spin04", "mant01", "mant02", "mant03", "mant04", "tassel"]
for i, name in enumerate(names):
    bone = armature.edit_bones.new(name)
    bone.head = (0, 0, i)
    bone.tail = (0, 0, i + 1)
    if i:
        bone.parent = armature.edit_bones[names[i - 1]]
bpy.ops.object.mode_set(mode="OBJECT")
bpy.context.scene["characolle_shared_body_rig"] = rig.name
mesh = bpy.data.meshes.new("cape")
mesh.from_pydata([(0, 1, 1), (0, 1, 3), (1, 1, 3)], [], [(0, 1, 2)])
cape = bpy.data.objects.new("cape", mesh)
bpy.context.collection.objects.link(cape)
for name in names:
    cape.vertex_groups.new(name=name)
for index, weights in enumerate(({"mant01": .2, "mant02": .3, "mant03": .5},
                                  {"mant04": .6, "mant03": .4},
                                  {"tassel": .3, "mant03": .4, "mant02": .3})):
    for name, weight in weights.items():
        cape.vertex_groups[name].add([index], weight, "REPLACE")
modifier = cape.modifiers.new("Armature", "ARMATURE")
modifier.object = rig
bpy.context.view_layer.update()
graph = bpy.context.evaluated_depsgraph_get()
before = [vertex.co.copy() for vertex in cape.evaluated_get(graph).data.vertices]
matrices = {bone.name: bone.matrix_local.copy() for bone in armature.bones}
report = exporter.simplify_mantle_bones(["mant02", "mant04"])
assert report["removed_mantle_bones"] == 2
assert report["retained_mantle_bones"] == ["mant02", "mant04"]
assert armature.bones["mant02"].parent.name == "o01_J_Spin04"
assert armature.bones["mant04"].parent.name == "mant02"
assert armature.bones["tassel"].parent.name == "mant04"
for bone in armature.bones:
    assert max(abs(a - b) for row_a, row_b in zip(bone.matrix_local, matrices[bone.name])
               for a, b in zip(row_a, row_b)) < 1e-6
expected = [{"o01_J_Spin04": .2, "mant02": .8}, {"mant02": .4, "mant04": .6},
            {"mant02": .7, "tassel": .3}]
for vertex, weights in zip(mesh.vertices, expected):
    actual = {cape.vertex_groups[group.group].name: group.weight for group in vertex.groups}
    assert actual.keys() == weights.keys()
    assert all(abs(actual[name] - weight) < 1e-6 for name, weight in weights.items())
bpy.context.view_layer.update()
assert all((vertex.co - point).length < 1e-6
           for vertex, point in zip(cape.evaluated_get(graph).data.vertices, before))
for invalid in (["missing_mant"], "mant02", [12]):
    try:
        exporter.simplify_mantle_bones(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid retained cape bones were accepted")
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode="EDIT")
for i in range(253):
    bone = armature.edit_bones.new(f"spare_{i}")
    bone.head = (1, 0, i)
    bone.tail = (1, 0, i + 1)
bpy.ops.object.mode_set(mode="OBJECT")
try:
    exporter.simplify_mantle_bones(["mant02", "mant04"])
except ValueError as error:
    assert "256-bone" in str(error)
else:
    raise AssertionError("An oversized retained skeleton was accepted")
bpy.ops.object.mode_set(mode="EDIT")
for bone in list(armature.edit_bones):
    if bone.name.startswith("spare_"):
        armature.edit_bones.remove(bone)
bpy.ops.object.mode_set(mode="OBJECT")
report = exporter.simplify_mantle_bones()
assert report["removed_mantle_bones"] == 2
assert all("mant" not in group.name for group in cape.vertex_groups)
assert armature.bones["tassel"].parent.name == "o01_J_Spin04"
print("PASS: reduced cape chains, merged weights, unchanged rest geometry and default fallback")
