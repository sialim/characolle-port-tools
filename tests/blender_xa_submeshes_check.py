"""Check XA routing when face and face parts share one XX frame name."""

import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'blender'))
from import_xa_morphs import find_clip_mesh, add_clip_shape_keys

for reverse in (False, True):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    targets = {}
    for count, suffix in ((8, int(reverse)), (5, int(not reverse))):
        mesh = bpy.data.meshes.new('mesh')
        mesh.from_pydata([(i, 0, 0) for i in range(count)], [], [])
        obj = bpy.data.objects.new('P_face_' + str(suffix), mesh)
        bpy.context.scene.collection.objects.link(obj)
        targets[count] = obj
    data = {'clips': [], 'index_sets': [], 'keyframes': []}
    for clip, count in [('Face_top', 8), ('Parts_top', 5)]:
        key = clip + '_closed'
        positions = [[i, 0, 0] for i in range(count)]
        positions[1] = [1, 0, 0.25]
        data['clips'].append({'name': clip, 'mesh': 'P_face', 'keyframes': [{'name': key}]})
        data['index_sets'].append({'name': clip, 'mesh_indices': [1], 'morph_indices': [1]})
        data['keyframes'].append({'name': key, 'positions': positions})
        selected = find_clip_mesh('P_face', data, clip)
        assert selected == targets[count]
        add_clip_shape_keys(selected, data, clip)
        assert abs(selected.data.shape_keys.key_blocks[-1].data[1].co.z - 0.25) < 0.00001
    assert len(targets[8].data.shape_keys.key_blocks) == 2
    assert len(targets[5].data.shape_keys.key_blocks) == 2
print('XA face/parts routing passes in either FBX submesh order')
