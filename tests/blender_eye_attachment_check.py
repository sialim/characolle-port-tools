"""Check attachment placement and Source angle order under a rotated head bone."""

import math
import sys
from pathlib import Path

import bpy
from mathutils import Euler, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'gmod'))
from export_source import eye_attachments, prepare_eye_control_frame

bpy.ops.wm.read_factory_settings(use_empty=True)
data = bpy.data.armatures.new('rig')
rig = bpy.data.objects.new('rig', data)
bpy.context.scene.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig
rig.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
head = data.edit_bones.new('o01_J_Head')
head.head, head.tail = (0, 0, 2), (1, 0.3, 2)
for name, x in [('eye_L', -0.1), ('eye_R', 0.1)]:
    bone = data.edit_bones.new(name)
    bone.head, bone.tail, bone.parent = (x, -0.2, 2.3), (x, -0.3, 2.3), head
bpy.ops.object.mode_set(mode='OBJECT')
mesh = bpy.data.meshes.new('body')
mesh.from_pydata([(-0.1, -0.2, 2.3), (-0.05, -0.2, 2.3), (-0.1, -0.2, 2.35)], [], [(0, 1, 2)])
obj = bpy.data.objects.new('body', mesh)
bpy.context.scene.collection.objects.link(obj)
obj.modifiers.new('skin', 'ARMATURE').object = rig
obj.vertex_groups.new(name='eye_L').add([0, 1, 2], 1, 'REPLACE')
manifest = {'base_objects': [{'name': obj.name}], 'head_objects': [{'name': obj.name}]}
frame = prepare_eye_control_frame(manifest)
assert frame['maximum_geometry_error'] < 0.00001
assert data.bones['eye_L'].parent.name == 'eye_controls'
axes = data.bones['eye_controls'].matrix_local.to_3x3()
for source, expected in [((1, 0, 0), (0, 0, 1)), ((0, 1, 0), (0, 1, 0)), ((0, 0, 1), (-1, 0, 0))]:
    assert (axes @ Vector(source) - Vector(expected)).length < 0.00001
result = eye_attachments(manifest)
attachment = result['attachments'][0]
matrix = data.bones['o01_J_Head'].matrix_local
center = matrix @ Vector(attachment['position'])
assert (center - Vector((0, -0.2, 2.3))).length < 0.00001
pitch, yaw, roll = [math.radians(value) for value in attachment['rotation']]
orientation = matrix.to_3x3() @ Euler((roll, pitch, yaw), 'XYZ').to_matrix()
assert (orientation @ Vector((1, 0, 0)) - Vector((0, -1, 0))).length < 0.00001
assert (orientation @ Vector((0, 0, 1)) - Vector((0, 0, 1))).length < 0.00001
print('Eye attachment center, forward/up axes and Source angle order pass')
