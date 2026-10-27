"""Recover editable outfit geometry from a preserved Source MDL family.

Run in Blender's background mode. SourceIO remains an external dependency.
The generated scene and manifest need material and in-game review before release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import bpy


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--sourceio', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--character', required=True)
    parser.add_argument('--model-name', required=True)
    parser.add_argument('--material-index', type=Path)
    parser.add_argument('--texture-root', type=Path)
    parser.add_argument('--mesh-prefix', help='Original character prefix, such as c03_02')
    parser.add_argument('--morph-source', type=Path, help='Original head XA for recovering linked face-part controls')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    if args.output.exists():
        raise FileExistsError(f'Inspect the existing recovery before replacing it: {args.output}')
    source = args.input.resolve()
    companions = [source, source.with_suffix('.vvd'), source.with_suffix('.dx90.vtx')]
    hashes = {p.name: digest(p) for p in companions}
    os.environ['NO_BPY'] = '1'
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(args.sourceio.resolve().parent))
    from SourceIO.blender_bindings.models import import_model
    from SourceIO.blender_bindings.models.common import put_into_collections
    from SourceIO.blender_bindings.operators.import_settings_base import ModelOptions
    from SourceIO.library.shared.content_manager import ContentManager
    from SourceIO.library.utils import FileBuffer
    from SourceIO.library.utils.tiny_path import TinyPath
    from scene_manifest import mesh_entry

    bpy.ops.wm.read_factory_settings(use_empty=True)
    options = ModelOptions.default()
    options.scale = 1.0
    options.import_textures = False
    options.create_flex_drivers = False
    options.generate_wrinkle_map_node_group = False
    options.bodygroup_vis_switches = False
    with FileBuffer(TinyPath(str(source))) as buffer:
        container = import_model(TinyPath(str(source)), buffer, ContentManager(), options)
    put_into_collections(container, source.stem, bodygroup_grouping=True)
    if container.armature is None:
        raise RuntimeError('Recovery requires a skinned model')
    if not {'body', 'head'}.issubset(container.bodygroups):
        raise RuntimeError('Expected separate body and head groups')
    bpy.context.scene['characolle_shared_body_rig'] = container.armature.name
    records = json.loads(args.material_index.read_text(encoding='utf-8')) if args.material_index else {}
    missing = []
    for material in bpy.data.materials:
        original = material.name.replace('\\', '/').rsplit('/', 1)[-1]
        material.name = original
        material['recovered_source_material'] = original
        match = re.match(r'BODY_(\d\d)__(.+)', original)
        layer, name = match.groups() if match else (None, original)
        suffix = f'_{layer}_00' if layer is not None else '_10'
        candidates = [r for r in records.values() if Path(r['path']).stem == f'{args.mesh_prefix}{suffix}']
        matches = [m for r in candidates for m in r['materials'] if m['name'].casefold() == name.casefold()]
        texture = next((t for m in matches for t in m['textures'] if t and '_sell_' not in t.lower() and '_sel_' not in t.lower()), None)
        paths = list(args.texture_root.rglob(texture)) if texture and args.texture_root else []
        paths = [p for p in paths if p.parent.name == f'{args.mesh_prefix}{suffix}']
        if len(paths) != 1:
            missing.append(original)
            continue
        material.use_nodes = True
        shader = material.node_tree.nodes.get('Principled BSDF')
        image = bpy.data.images.load(str(paths[0].resolve()), check_existing=True)
        node = material.node_tree.nodes.new('ShaderNodeTexImage')
        node.image = image
        material.node_tree.links.new(node.outputs['Color'], shader.inputs['Base Color'])
        if paths[0].suffix.lower() == '.tga':
            material.node_tree.links.new(node.outputs['Alpha'], shader.inputs['Alpha'])
        shader.inputs['Roughness'].default_value = 0.8

    objects = []
    base, head, bodygroups = [], [], []
    for group, members in container.bodygroups.items():
        members = [o for o in members if o is not None]
        for obj in members:
            obj.name = 'P_face' if group == 'head' else 'RECOVERED_' + re.sub(r'[^A-Za-z0-9_]', '_', group)
            if obj.data.shape_keys:
                obj.data.shape_keys.key_blocks[0].name = 'Basis'
            obj['characolle_source'] = str(source)
            if not obj.data.uv_layers or not obj.data.polygons:
                raise RuntimeError(f'Missing geometry or UVs: {obj.name}')
            bad_weights = sum(abs(sum(g.weight for g in v.groups) - 1.0) > 0.002 for v in obj.data.vertices)
            if bad_weights:
                raise RuntimeError(f'{obj.name}: {bad_weights} vertices have invalid weight sums')
            if group == 'body':
                base.append(mesh_entry(obj))
            elif group == 'head':
                head.append(mesh_entry(obj))
            else:
                bodygroups.append({'name': group, 'default': True, 'mesh': mesh_entry(obj), 'objects': [obj.name]})
            keys = obj.data.shape_keys.key_blocks if obj.data.shape_keys else []
            objects.append({'name': obj.name, 'vertices': len(obj.data.vertices), 'triangles': len(obj.data.polygons),
                            'shape_keys': [k.name for k in keys], 'uv_layers': len(obj.data.uv_layers),
                            'weighted_vertices': len(obj.data.vertices) - bad_weights})
    if not base or not head or not bodygroups:
        raise RuntimeError('The recovered model is not a clothed outfit family')
    if any(digest(p) != hashes[p.name] for p in companions):
        raise RuntimeError('Preserved compiled files changed during import')
    args.output.mkdir(parents=True)
    blend = args.output / (source.stem + '.blend')
    manifest = {'format': 1, 'character': args.character, 'model_name': args.model_name,
                'source_blend': str(blend.resolve()), 'base_objects': base, 'head_objects': head,
                'bodygroups': bodygroups, 'scene': {'recovered_from_compiled': True}}
    if args.morph_source:
        from recover_flex_aliases import aliases_from_xa
        manifest['flex_aliases'] = aliases_from_xa(args.morph_source, [key for obj in head for key in obj['shape_keys']])
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    report = {'source': str(source), 'source_sha256': hashes, 'objects': objects,
              'bones': len(container.armature.data.bones), 'missing_materials': missing,
              'stage': 'recovered_needs_review', 'in_game_verified': False,
              'original_blender_scene_recovered': False,
              'sourceio_revision': subprocess.check_output(['git', '-C', str(args.sourceio), 'rev-parse', 'HEAD'], text=True).strip()
              if (args.sourceio / '.git').exists() else None}
    (args.output / 'recovery.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    bpy.ops.wm.save_as_mainfile(filepath=str(blend.resolve()))
    print(f'Recovered {len(objects)} objects, {len(bodygroups)} outfit groups; {len(missing)} materials unresolved')


if __name__ == '__main__':
    main()
