"""Rebuild a recovered outfit head from original FBX/XA without changing fitted clothing."""
import argparse
import bpy
import hashlib
import json
import re
import sys
from pathlib import Path
from mathutils import Matrix
repo = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(repo / 'blender'), str(repo / 'tools'), str(repo / 'gmod')]
from import_xa_morphs import find_clip_mesh, add_clip_shape_keys
from xa_morph_extract import parse_xa
from add_eye_controls import add_eye_controls
from export_source import clean_shape_names, prepare_single_armature
from scene_manifest import mesh_entry

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--head-fbx', type=Path, required=True)
    parser.add_argument('--head-xa', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-scale', type=float, default=400)
    parser.add_argument('--model-name')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    if not 0 < args.source_scale < 100000:
        raise ValueError('Invalid original-to-recovered coordinate scale')
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(output)
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    if not manifest.get('scene', {}).get('recovered_from_compiled') or not manifest.get('bodygroups'):
        raise ValueError('Expected a recovered clothed outfit manifest')
    name = re.sub(r'[^A-Za-z0-9_]+', '_', manifest['character'])
    source = Path(manifest['source_blend']).resolve()
    fbx = args.head_fbx.resolve()
    xa = args.head_xa.resolve()
    bpy.ops.wm.open_mainfile(filepath=str(source))
    for entry in manifest['head_objects']:
        bpy.data.objects.remove(bpy.data.objects[entry['name']], do_unlink=True)
    bodyrig = bpy.data.objects[bpy.context.scene['characolle_shared_body_rig']]
    bodyobjects = [bpy.data.objects[e['name']] for e in manifest['base_objects']]
    bodyobjects += [bpy.data.objects[e['mesh']['name']] for e in manifest['bodygroups']]
    before = {o.name: [list(v.co) for v in o.data.vertices] for o in bodyobjects}
    used = set()
    for obj in bodyobjects:
        used.update((obj.vertex_groups[g.group].name for v in obj.data.vertices for g in v.groups if g.weight > 0))
    used.update(['o01_J_Head', 'o01_J_Neck', 'o01_J_Hip', 'o01_J_Spin01', 'o01_J_Spin04'])
    for side in ('L', 'R'):
        used.update((f'o01_J_{joint}_{side}' for joint in ('Arm01', 'Hiji01', 'Hand', 'Naka01', 'UpLeg01', 'Hiza', 'Foot01', 'Toes')))
    keep = set()
    for n in used:
        bone = bodyrig.data.bones.get(n)
        while bone:
            keep.add(bone.name)
            bone = bone.parent
    bpy.ops.object.select_all(action='DESELECT')
    bodyrig.select_set(True)
    bpy.context.view_layer.objects.active = bodyrig
    bpy.ops.object.mode_set(mode='EDIT')
    removed = []
    for bone in list(bodyrig.data.edit_bones):
        if bone.name not in keep:
            removed.append(bone.name)
            bodyrig.data.edit_bones.remove(bone)
    bpy.ops.object.mode_set(mode='OBJECT')
    old = set(bpy.data.objects)
    materials = {m.name: m for m in bpy.data.materials}
    bpy.ops.import_scene.fbx(filepath=str(fbx), automatic_bone_orientation=False)
    imported = set(bpy.data.objects) - old
    data = parse_xa(xa.read_bytes())[1]
    key_map = {}
    targets = {}
    for clip in data['clips']:
        target = find_clip_mesh(clip['mesh'], data, clip['name'])
        add_clip_shape_keys(target, data, clip['name'])
        targets[clip['name']] = target
        for ref in clip['keyframes']:
            key_map[clip['name'], ref['name']] = target.data.shape_keys.key_blocks[clip['name'] + '__' + ref['name']]
    eyes = add_eye_controls()
    for obj in imported:
        if obj.type != 'MESH':
            continue
        for i, mat in enumerate(obj.data.materials):
            plain = re.sub('\\.\\d{3}$', '', mat.name)
            if plain in materials:
                obj.data.materials[i] = materials[plain]
        if obj.name.startswith('P_face_'):
            obj.name = 'REPAIR_faceparts' if any(('face_pa_tu' in m.name for m in obj.data.materials)) else 'REPAIR_face'
    roots = [o for o in imported if o.parent not in imported]
    for obj in roots:
        obj.matrix_world = Matrix.Scale(args.source_scale, 4) @ obj.matrix_world
    bpy.context.view_layer.update()
    headrig = next((o for o in imported if o.type == 'ARMATURE'))
    matrix = headrig.matrix_world.copy()
    headrig.parent = bodyrig
    headrig.parent_type = 'BONE'
    headrig.parent_bone = 'o01_J_Head'
    headrig.matrix_world = matrix
    headmesh_names = sorted((o.name for o in imported if o.type == 'MESH'))
    staging = prepare_single_armature()
    clean_shape_names()
    aliases = {}
    clips = {c['name']: c for c in data['clips']}
    for target_clip, source_clip in [('Parts_top', 'Face_top'), ('Parts_bottom', 'Face_bottom')]:
        if target_clip not in clips:
            continue
        target, sourceclip = (clips[target_clip], clips[source_clip])
        assert len(target['keyframes']) == len(sourceclip['keyframes'])
        for t, s in zip(target['keyframes'], sourceclip['keyframes']):
            k = key_map[target_clip, t['name']].name
            v = key_map[source_clip, s['name']].name
            if k in aliases and aliases[k] != v:
                raise ValueError('Ambiguous Parts link ' + k)
            aliases[k] = v
    for target, source_name in [('namida_toji', 'bace_toji'), ('namida_einkL', 'Wink_L_toji'), ('namida_einkR', 'Wink_R_toji')]:
        if ('namida', target) in key_map and ('Face_top', source_name) in key_map:
            aliases[key_map['namida', target].name] = key_map['Face_top', source_name].name
    headmeshes = [bpy.data.objects[n] for n in headmesh_names]
    for obj in bodyobjects:
        assert before[obj.name] == [list(v.co) for v in obj.data.vertices], 'Fitted clothing changed'
    manifest['head_objects'] = [mesh_entry(o) for o in headmeshes]
    manifest['flex_aliases'] = aliases
    manifest['model_name'] = args.model_name or 'characolle/' + name.lower() + '_uniform_repaired'
    if len(bodyrig.data.bones) > 256:
        raise ValueError('Rebuilt skeleton exceeds Source bone limit')
    output.mkdir(parents=True)
    blend = output / (name + '_repaired.blend')
    manifest['source_blend'] = str(blend)
    manifest['repair_sources'] = {'fbx': str(fbx), 'xa': str(xa), 'sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (fbx, xa)}}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    report = {'stage': 'head_rebuilt_needs_validation', 'original_scene': str(source), 'body_outfit_vertices_unchanged': True, 'removed_unused_bones': removed, 'new_eye_bones': eyes, 'staging': staging, 'head_objects': [o.name for o in headmeshes], 'flex_aliases': aliases, 'bone_count': len(bodyrig.data.bones)}
    (output / 'repair.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    print('Rebuilt', name, 'head; preserved fitted body/outfit, bones', report['bone_count'])
if __name__ == '__main__':
    main()
