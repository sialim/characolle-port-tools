import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'gmod'))
from export_source import restore_weighted_deformers

bpy.ops.wm.read_factory_settings(use_empty=True)
data=bpy.data.armatures.new('Rig')
rig=bpy.data.objects.new('Rig',data)
bpy.context.collection.objects.link(rig)
bpy.context.view_layer.objects.active=rig
rig.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
root=data.edit_bones.new('root'); root.head=(0,0,0); root.tail=(0,0,1)
finger=data.edit_bones.new('finger'); finger.head=(1,0,0); finger.tail=(1,0,1); finger.parent=root
bpy.ops.object.mode_set(mode='OBJECT')

def mesh(name, weights=True, partial=False):
    data=bpy.data.meshes.new(name)
    data.from_pydata([(1,0,0),(1.1,0,0),(1,0,.1)],[],[(0,1,2)])
    obj=bpy.data.objects.new(name,data)
    bpy.context.collection.objects.link(obj)
    obj.parent=rig
    obj.parent_type='BONE';obj.parent_bone='root'
    obj.matrix_world.identity()
    if weights: obj.vertex_groups.new(name='finger').add([0] if partial else [0,1,2],1,'REPLACE')
    bpy.context.view_layer.update()
    return obj

skin=mesh('nails')
head=mesh('eye')
rigid=mesh('rigid',False)
rigid.vertex_groups.new(name='root').add([0,1,2],1,'REPLACE')
manifest={'base_objects':[{'name':skin.name},{'name':rigid.name}], 'head_objects':[{'name':head.name}]}
result=restore_weighted_deformers(manifest,rig)
assert [entry['mesh'] for entry in result]==['nails']
assert not head.modifiers and head.parent_type=='BONE'
assert not rigid.modifiers and rigid.parent_type=='BONE'
assert restore_weighted_deformers(manifest,rig)==[]
graph=bpy.context.evaluated_depsgraph_get()
before=[skin.evaluated_get(graph).matrix_world @ v.co for v in skin.evaluated_get(graph).data.vertices]
rig.pose.bones['finger'].location.x=.5
bpy.context.view_layer.update()
graph=bpy.context.evaluated_depsgraph_get()
after=[skin.evaluated_get(graph).matrix_world @ v.co for v in skin.evaluated_get(graph).data.vertices]
assert all(abs((a-b).length-.5)<1e-5 for a,b in zip(after,before))
rig.pose.bones['finger'].location.x=0
partial=mesh('partial',partial=True)
try: restore_weighted_deformers({'base_objects':[{'name':partial.name}]},rig)
except ValueError as error: assert 'partial skin weights' in str(error)
else: raise AssertionError('Partial weights must not silently fall back to the root')
changed=mesh('changed_fit')
rig.pose.bones['finger'].location.x=.5
bpy.context.view_layer.update()
try: restore_weighted_deformers({'base_objects':[{'name':changed.name}]},rig)
except ValueError as error: assert 'changes fitted geometry' in str(error)
else: raise AssertionError('A changed fitted pose must stop the export')
print('Weighted deformer restoration, rigid/head preservation, idempotence and pose checks passed')
