"""Run with Blender in background mode to check inherited head attachments."""

import importlib.util
from pathlib import Path

import bpy
from mathutils import Matrix


spec = importlib.util.spec_from_file_location("export_source", Path(__file__).resolve().parents[1] / "gmod/export_source.py")
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


def armature(name, bone_names):
    obj = bpy.data.objects.new(name, bpy.data.armatures.new(name))
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for index, name in enumerate(bone_names):
        bone = obj.data.edit_bones.new(name)
        bone.head = (0, 0, index)
        bone.tail = (0, 0, index + 0.5)
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


bpy.ops.wm.read_factory_settings(use_empty=True)
body = armature("BODY_02__SCENE_ROOT", ["body_root", "head"])
head = armature("head_source", ["face_root", "eye_L"])
head.parent = body
head.parent_type = "BONE"
head.parent_bone = "head"
head.matrix_world = Matrix.Translation((0, 0, 2))
holder = bpy.data.objects.new("face_holder", None)
bpy.context.scene.collection.objects.link(holder)
holder.parent = head
holder.matrix_world = Matrix.Translation((0.2, 0.3, 2.5))
eye_holder = bpy.data.objects.new("eye_holder", None)
bpy.context.scene.collection.objects.link(eye_holder)
eye_holder.parent = head
eye_holder.parent_type = "BONE"
eye_holder.parent_bone = "eye_L"
eye_holder.matrix_world = Matrix.Translation((0.4, 0.3, 2.6))
bpy.context.view_layer.update()
expected = {obj.name: obj.matrix_world.copy() for obj in (holder, eye_holder)}

report = exporter.prepare_single_armature("02")
assert holder.parent == body and holder.parent_type == "BONE" and holder.parent_bone == "head"
assert eye_holder.parent == body and eye_holder.parent_type == "BONE" and eye_holder.parent_bone == "eye_L"
assert body.data.bones["face_root"].parent.name == "head"
for obj in (holder, eye_holder):
    error = max(abs(obj.matrix_world[row][col] - expected[obj.name][row][col]) for row in range(4) for col in range(4))
    assert error < 0.00001, (obj.name, error)
assert report["restored_rigid_attachments"] == 2
print("PASS: inherited face and explicit eye attachments retain their bones and transforms")
