"""Check recovered head attachment without changing its fitted rest geometry."""

import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'gmod'))
from export_source import attach_recovered_head, temporary_collection

bpy.ops.wm.read_factory_settings(use_empty=True)
data = bpy.data.armatures.new('rig')
rig = bpy.data.objects.new('rig', data)
bpy.context.scene.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig
rig.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
root = data.edit_bones.new('o01_N_Zentai')
root.head, root.tail = (0, 0, 0), (0, 0, 1)
head = data.edit_bones.new('o01_J_Head')
head.head, head.tail, head.parent = (0, 0, 2), (0, 1, 2), root
frame = data.edit_bones.new('P_face')
frame.head, frame.tail = (0, 0, 2), (0, 1, 2)
bpy.ops.object.mode_set(mode='OBJECT')
mesh = bpy.data.meshes.new('face')
mesh.from_pydata([(1, 0, 2), (2, 0, 2), (1, 0, 3)], [], [(0, 1, 2)])
obj = bpy.data.objects.new('face', mesh)
bpy.context.scene.collection.objects.link(obj)
obj.vertex_groups.new(name='P_face').add([0, 1, 2], 1, 'REPLACE')
obj.modifiers.new('skin', 'ARMATURE').object = rig
manifest = {'scene': {'recovered_from_compiled': True}, 'head_objects': [{'name': obj.name}]}

def points():
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    return [evaluated.matrix_world @ v.co for v in evaluated.data.vertices]

before = points()
assert attach_recovered_head(manifest) == ['P_face']
assert max((a-b).length for a, b in zip(before, points())) < 0.00001
assert data.bones['P_face'].parent.name == 'o01_J_Head'
rig.pose.bones['o01_J_Head'].rotation_mode = 'XYZ'
rig.pose.bones['o01_J_Head'].rotation_euler.y = 0.5
after = points()
pivot = Vector((0, 0, 2))
orientation = data.bones['o01_J_Head'].matrix_local.to_3x3()
rotation = orientation @ Matrix.Rotation(0.5, 3, 'Y') @ orientation.inverted()
expected = [pivot + rotation @ (p-pivot) for p in before]
assert max((a-b).length for a, b in zip(after, expected)) < 0.00001
assert attach_recovered_head(manifest) == []
source = bpy.data.collections.new('head')
bpy.context.scene.collection.children.link(source)
source.objects.link(obj)
export = temporary_collection('head', [obj])
assert export.name == 'head' and obj.name in source.objects and obj.name in export.objects
print('Recovered head rest fit, rotation inheritance and collection collision checks passed')
