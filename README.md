# CharaColle! Key Blender/GMod Port

Tooling and notes for moving the CharaColle! Key characters into Blender and
then into Garry's Mod.

The repository does not contain the original game archive, `.pp` packages,
extracted meshes, textures, or compiled model releases. Keep those in a
private local workspace and point the scripts at them when needed.

## Character package map

| Character | Package | Main body meshes | Head/hair meshes |
| --- | --- | --- | --- |
| Kud | `cc02_00_00_00` | `c02_01_00_00.xx`, `c02_01_01_00.xx`, `c02_01_02_00.xx` | `c02_01_10.xx`, `c02_01_11.xx` |
| Rin | `cc02_00_01_00` | `c02_02_00_00.xx`, `c02_02_01_00.xx`, `c02_02_02_00.xx` | `c02_02_10.xx`, `c02_02_11.xx` |

Each character package also has `.xa` animation/facial data, bone lists,
accessory `.xx` files, and extracted texture/previews.

## Workflow

1. Extract the game's `.pp` packages with a CharaColle-compatible extractor.
2. Open the relevant `.xx` files in SB3Utility and export a geometry-only FBX.
   The CharaColle XA morph exporter can fail on valid facial clips, so do not
   rely on the combined XA-to-FBX export for face posing.
3. Run `tools/xa_morph_extract.py` against the matching `.xa` file. It reads
   the morph index sets, keyframes, clips, and references without modifying
   the source game files.
4. Run `blender/import_xa_morphs.py` to import the geometry-only FBX and apply
   the extracted XA positions as Blender shape keys.
5. Run `tools/catalog_extraction.py` to produce a machine-readable inventory.
6. Run `blender/import_characolle_fbx.py` inside Blender to import FBX files,
   relink extracted textures, normalize scene units, and save a `.blend`.
   The importer records the number of non-basis shape keys and can write a
   JSON report with `--shape-key-report`.

Example:

```text
blender --background --python blender/import_characolle_fbx.py -- --input C:\exports\Kud --textures C:\path\to\Kud --output C:\blends\Kud.blend --shape-key-report C:\blends\Kud.shape_keys.json
```

An existing `.blend` can be checked later with
`blender/audit_shape_keys.py`.

Morph conversion example:

```text
python tools/xa_morph_extract.py --input C:\exports\Kud\c02_01_10.xa --output C:\exports\Kud\c02_01_10.morphs.json
blender --background --python blender/import_xa_morphs.py -- --input C:\exports\Kud\Kud_head.fbx --morph-json C:\exports\Kud\c02_01_10.morphs.json --textures C:\exports\Kud\textures --output C:\blends\Kud_head_with_morphs.blend
blender --background --python blender/link_face_pose_keys.py -- --input C:\blends\Kud_head_with_morphs.blend --output C:\blends\Kud_head_with_morphs.blend
```

To make the imported head easier to inspect in Blender, normalize the FBX
parent/mesh names and rebuild the material texture nodes:

```text
blender --background --python blender/normalize_head_scene.py -- --input C:\blends\Kud_head_with_morphs.blend --output C:\blends\Kud_head_with_morphs_fixed.blend
```

This produces `P_face` and `P_namida` mesh objects in the `CHARACTER_HEAD`
collection. Their original FBX empty parents are retained in `HEAD_RIG`.

The face-pose linker drives matching `P_namida` tear/eyelash keys from the
corresponding `P_face` expression keys without merging the two skinned meshes.

Body and outfit exports can be appended with `blender/append_body_fbx.py`.
Run `blender/organize_body_layers.py` afterward to put each outfit in its own
toggleable collection. The current Kud files contain:

```text
c02_01_00_00.xx  school uniform
c02_01_01_00.xx  pajama/private outfit, including P_pantu
c02_01_02_00.xx  swimsuit/base-body layer, including P_body and P_bura
```

`tools/xx_mesh_names.py` lists the mesh frames and material texture slots in
an `.xx` file. Keep outfit layers separate until the shared skeleton and
GMod bodygroup assignments are finalized.

6. Test the imported face keys in Blender. Preserve the original skeleton in
   a source collection and create a separate Source/GMod-ready collection.
7. Clean the rig and materials in Blender.
8. Export to SMD/DMX or PMX according to the intended GMod path. For native
   GMod face posing, the Blender shape keys must become Source flexes during
   the final export/compile stage; shape keys by themselves do not create
   faceposing controls in GMod.

## First export targets

Start with one outfit per character:

```text
Kud: cc02_00_00_00/c02_01_00_00.xx + c02_01_10.xx
Rin: cc02_00_01_00/c02_02_00_00.xx + c02_02_10.xx
```

Then add alternate outfit/body files and the second head/hair variant.
Shared dance animations can be retargeted after the static skeleton and
materials are verified.

Do not commit the original copyrighted assets or a rehosted game archive.
