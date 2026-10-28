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
toggleable collection. The body material rebuild preserves both the primary
texture and the game's secondary sell/tint texture as an available mask node.
Those maps are selection masks rather than extra light, so they are not wired
to Emission by default. The current Kud files contain:

```text
c02_01_00_00.xx  school uniform
c02_01_01_00.xx  pajama/private outfit, including P_pantu
c02_01_02_00.xx  swimsuit/base-body layer, including P_body and P_bura
```

`tools/xx_mesh_names.py` lists the mesh frames and material texture slots in
an `.xx` file. Keep outfit layers separate until the shared skeleton and
GMod bodygroup assignments are finalized.

The organized Blender scene keeps the permanent base pieces in `BODY_BASE`
and leaves outfit geometry in `BODY_LAYER_00`, `BODY_LAYER_01`, and
`BODY_LAYER_02`. This avoids carrying duplicate body vertices into the final
bodygroup setup; clothing can be fitted against `BODY_BASE` and then cleaned
as separate release meshes.

Patched packages may add `BODY_LAYER_03` and `BODY_LAYER_04`. These are
alternate full-body surfaces rather than clothing-only layers, so the
organizer hides `BODY_BASE` when either variant is selected to prevent
overlapping body surfaces.

Eye controls and the pupil approximation can be added after the full body
scene is organized:

```text
blender --background --python blender/add_eye_controls.py -- --input C:\blends\Kud_full_body_layers.blend --output C:\blends\Kud_full_body_layers_eye_controls.blend
```

This creates `eye_L` and `eye_R` bones on the head armature and parents the
existing `P_eye_L` and `P_eye_R` hierarchies to them. Each eye mesh also gets
a `Pupil_Small` key. Since the original pupil is painted into the eye texture,
that key is a front-cap geometry approximation rather than a separate iris
morph. `blender/restore_hair_overlays.py` can restore the original
`*_hair_sel_00.bmp` or `*_hair_sell_00.bmp` material overlay when a cleaned
scene needs it; the normalizer preserves that map as an unconnected mask.

To put the head and outfit layers on one usable skeleton, run the body-rig
unifier after the eye-control step:

```text
blender --background --python blender/unify_body_rig.py -- --input C:\blends\Kud_full_body_layers_eye_controls.blend --output C:\blends\Kud_full_body_layers_unified.blend --canonical-layer 02
```

The selected canonical body layer becomes `SHARED_BODY_RIG`, outfit armature modifiers are
reassigned to it, missing outfit-specific bones are copied into it, and the
head armature is parented to `o01_J_Head`. The original outfit rigs are kept
in a hidden `SOURCE_BODY_RIGS` collection.

The unifier also detects source-parented meshes that still have valid vertex
groups but no armature modifier, such as skirt panels and tail pieces, and
rebounds them to the shared rig automatically.

The final scene therefore has two active armatures by design. Select the
canonical `BODY_##__SCENE_ROOT` in `SHARED_BODY_RIG` and enter Pose Mode for body
controls such as `o01_J_Neck` and `o01_J_Head`. Select `o_N_kao_all` in
`HEAD_RIG` and enter Pose Mode for face controls, including `eye_L` and
`eye_R`; the face armature is parented to the body rig's `o01_J_Head` bone.
Meshes with valid vertex groups but no imported armature modifier can be
rebound with `blender/attach_skinned_mesh.py`; this is used for the tail and
variant body overlay meshes in the supplied scenes.

6. Test the imported face keys in Blender. Preserve the original skeleton in
   a source collection and create a separate Source/GMod-ready collection.
7. Clean the rig and materials in Blender.
8. Export to SMD/DMX or PMX according to the intended GMod path. For native
   GMod face posing, the Blender shape keys must become Source flexes during
   the final export/compile stage; shape keys by themselves do not create
   faceposing controls in GMod.

## Automated GMod build

The `gmod` scripts keep the Blender scene as the source of truth and create a
repeatable Source export:

1. `gmod/scene_manifest.py` records the shared armature, materials, flexes,
   base meshes, head meshes, and one bodygroup entry per outfit mesh.
2. `gmod/export_source.py` consolidates the armatures, rebinds weighted meshes,
   limits vertex influences, exports DMX files, and renames flexes for Source.
   Exports default to 61.2 Source units tall, a 15% reduction from the previous
   72-unit target. Override this with `--target-height`. This flattens mesh and rig
   transforms, preserves nested eye attachments, and checks sampled
   evaluated vertices before exporting. Keep QC scale at its default for these
   normalized exports; an additional `$scale 400` would multiply the height again.
   Mantle cloth bones are reduced to a torso-bound export representation because
   Source models have a 256-bone limit; the Blender scene is not modified.
   To retain cape pose controls, set a root-level `mantle_keep_bones` list in the
   manifest with the exact source bone names. Removed cape weights merge into
   the nearest retained ancestor, or the torso when none survives. Retained
   bones keep their rest transforms and attach through the surviving chain.
   Choose a reduced set that keeps the export skeleton within 256 bones.
   This preserves manual posing controls; it does not add cloth simulation.
   The manifest's `canonical_body_layer` takes priority over the saved scene
   default. `--canonical-layer` overrides it explicitly. A requested layer must
   exist; the exporter stops instead of silently falling back to another rig.
3. `gmod/generate_qc.py` creates a QC with the base, head, and individual
   bodygroups. Outfit entries start blank so they can be enabled independently.
   Pass `--outfit-visible` for an outfit model that starts fully dressed. The
   generator rejects bodygroup tables that overflow signed 32-bit storage.
   The head uses a `$model` block with explicit facial rules from `flexes.json`.
   Exporting it only as a bodygroup can leave named sliders without executable
   rules in GMod. Matching eyelash morphs follow the face expression controls.
   Face-parts meshes with the same ordered expression list follow the main face
   through `flex_aliases.json`, while retaining their separate adjustment sliders.
   The block declares controllers explicitly and disables automatic DMX rules;
   otherwise StudioMDL appends rules that overwrite those links. Pupil submeshes
   share one `PupilSmall` slider.
4. `gmod/build_gmod.py` converts referenced textures with VTFCmd, writes VMTs,
   runs StudioMDL, collects the compiled files, and creates a GMA package.
   Before packaging, `gmod/validate_model.py` checks the compiled height,
   bodygroup bases, companion-file checksums, and packaged VMT/VTF references.
   It rejects facial controllers with no compiled flex rules and repeated rules
   that overwrite the same target.
   This is an offline check; successful validation still requires an in-game
   rendering and posing test. Ragdoll builds also check the PHY checksum and
   require between 1 and 32 physics solids.

Pass `--physics` to both the exporter and QC generator to create a ragdoll.
The exporter builds sixteen convex collision hulls for the pelvis, torso, head,
arms, hands, legs, and feet. Each hull has one rigid bone assignment; the generated
`physics.json` records the joint limits and mass for review. Elbows and knees use
hinge limits chosen from the source bone orientation. Hair and outfit bones follow
their existing parents. This is a starting collision rig; unusual outfits may need
hull or joint-limit adjustments after an in-game test. Source Blender files retain
their original size and fitted geometry.

For outfits with too many independent parts, `gmod/bundle_manifest.py` combines
related material submeshes into one bodygroup. Run it on an outfit-specific manifest,
for example `--prefix P_dou` for the torso garment. Each member mesh, its weights,
and its materials are exported together; no geometry is joined or discarded. This
keeps the other garment toggles separate and brings large outfits below the limit.
The exporter also adds eye controls in staging when the original head rig and eye
markers are present but eye bones have not yet been created.
When both eye bones are available, it adds an `eye_controls` parent aligned for
the bone-based Eye Poser and writes a head-local `eyes` attachment. Neutral mesh
positions are checked before exporting. The QC includes the attachment and eye
center; the build validator checks that the attachment survived compilation and
that the compiled eye center matches the export. These changes affect export
staging only. Verify selection and both movement axes with the installed Eye
Poser, since tool variants can use different bone conventions.
Materials that need visible back faces, such as wing membranes, can set
`characolle_two_sided` on the Blender material or `two_sided` in its manifest
entry. The texture builder emits `$nocull 1` for those materials.

For small intersections with the shared body, `gmod/split_manifest.py` accepts
repeated `--clearance-mesh` arguments with exact outfit object names. The default
clearance is 0.06 Source units, with a 1-unit correction limit. The exporter moves
only those garment vertices away from the body surface, preserves relative shape
keys, and records moved and limited vertices in its report. This operates on the
export copy and requires an unposed outfit. Final height stays at the requested
value. Check the result in game; this does not replace fitting large differences.
`--exclude-mesh` can omit confirmed duplicate outfit parts. Some base bodies omit
lower legs or hands, so retain those outfit skin parts unless coverage is verified.

Long garment faces can cross the body even when their vertices have clearance.
`--clearance-subdivide 1` adds one subdivision level to explicitly selected
garments, interpolating UVs and weights. It rejects meshes with shape keys rather
than discarding them. `--clearance-face-iterations 8` can also check face centers
and edge midpoints, with all movement still bounded by the correction limit.
New weights are reduced to Source's influence limit before export.

An outfit manifest can add ordered `layers` inside `outfit_clearance` to separate
an outer collar from an inner shirt. Each layer accepts `meshes`,
`reference_meshes`, `distance`, `max_correction`, `subdivide`, and `face_iterations`.
Optional `orient_references: true` aligns reference normals with the nearby body;
`sample_backfaces: true` includes reversed garment faces in sampling. Layers retain
the base body as a protected surface. Reports include unresolved samples and
vertices stopped by the movement or body-protection limits. Inspect those cases
in game before treating the outfit as finished.

VTFCmd can return success without writing a texture when the source dimensions
are unsupported. The builder checks each output and, when needed, retries at the
nearest power-of-two size. Original images are kept unchanged.

Example Kud commands:

```text
blender --background --python gmod/scene_manifest.py -- --input C:\blends\Kud.blend --output C:\work\Kud_manifest.json --character Kud
blender --background --python gmod/export_source.py -- --input C:\blends\Kud.blend --manifest C:\work\Kud_manifest.json --source-tools C:\tools\blender_source_tools_3.4.3 --output C:\work\Kud_export --report C:\work\Kud_export_report.json --material-path models/characolle/kud --format DMX --physics
python gmod/generate_qc.py --manifest C:\work\Kud_manifest.json --export C:\work\Kud_export --output C:\work\Kud_export\Kud.qc --material-path models/characolle/kud --outfit-visible --physics
python gmod/build_gmod.py --manifest C:\work\Kud_manifest.json --qc C:\work\Kud_export\Kud.qc --gmod F:\SteamLibrary\steamapps\common\GarrysMod --vtfcmd C:\tools\VTFCmd.exe --textures C:\exports\Kud --textures C:\exports\Kud\head_textures --addon C:\work\characolle_kud --package C:\work\characolle_kud.gma
```

### Recovering missing outfit scenes

`gmod/recover_compiled.py` can recover an outfit from a preserved MDL, VVD and
DX90 VTX family using an external [SourceIO checkout](https://github.com/REDxEYE/SourceIO)
in a directory named `SourceIO`. It creates a new Blender scene and export
manifest with the compiled meshes, UVs, weights and surviving facial targets.
It records source hashes and the importer revision, and refuses to overwrite an
existing recovery. The original Blender collections, editable modifiers and
uncompiled morphs cannot be reconstructed from these files.

Original XX files can restore texture references and embedded images:

```text
python tools/xx_mesh_names.py C:\extracted\c03_02_00_00.xx C:\extracted\c03_02_02_00.xx C:\extracted\c03_02_10.xx --output C:\work\materials.json --textures-output C:\work\textures
blender --background --python gmod/recover_compiled.py -- --input C:\backup\ameri_layer_00.mdl --sourceio C:\tools\SourceIO --output C:\work\ameri_recovered --character Ameri --model-name characolle/ameri_recovered --material-index C:\work\materials.json --texture-root C:\work\textures --mesh-prefix c03_02 --morph-source C:\extracted\c03_02_10.xa
```

The XX extractor restores BMP signatures, keeps original image bytes otherwise,
rejects unsafe names, and refuses to overwrite different images. Recovery reports
unresolved materials. Check those before building. Matching `Parts_top` and
`Parts_bottom` XA expression slots restore face-part links through the manifest's
`flex_aliases`; conflicting slots are rejected. Source Tools export collections
receive exact filenames even when imported collections already use those names.
The export stage also avoids mesh/bone name collisions and attaches detached
weighted head roots to `o01_J_Head`, retaining the fitted rest geometry. Damaged
geometry already present in an old compiled model still needs source repair.

Pass the matching original head XA to `gmod/generate_qc.py --morph-source` to
restore linked meshes from the source expression slots. This includes the
`mayuge` mesh used for both eyebrows and eyelashes on Key heads. Its closed-eye
target must follow the face target; moving only the eyelid can hide the lashes.
The generated rules retain the separate mesh controls for manual adjustments.
Mismatched slot times and conflicting links stop generation.

Export also restores missing armature modifiers on weighted body and outfit
submeshes. A mesh parented to the root bone can otherwise export as a rigid part
despite retaining fingertip or other skin weights, causing it to drift during
ragdoll poses. Restoration preserves the fitted geometry and leaves intentional
rigid attachments and head eye-bone parenting intact. Partial weights or a change
to fitted geometry stop the export for inspection.

Recovered scenes retain compiled coordinates until the normal export stage
normalizes them to 61.2 units. Build a new clothed preview path and inspect it in
game before replacing any working package. Recovery and compilation alone do
not verify appearance, facial posing or physics.

If an old compiled head or its facial targets are damaged,
`blender/rebuild_recovered_head.py` replaces the head from an original SB3 FBX
and matching XA while retaining the recovered body and outfit vertices. It
adds eye bones and the existing pupil approximation, restores face-part links,
and writes a new scene, manifest and source-hash receipt. Use `--manifest`,
`--head-fbx`, `--head-xa` and a new `--output` directory. The default
`--source-scale 400` matches these preserved compiled families; verify the
coordinate relationship before using it on another export.

For Ameri's recovered wings, `blender/rebuild_recovered_wings.py` takes
`--manifest`, `--wings-fbx` and a new `--output` directory. Export only the two
original `P_hane` submeshes to that FBX. The tool bakes their evaluated pose and
restores wing pivots from the posed rig; raw FBX coordinates can place the wings
above the head. Other mesh positions must remain unchanged. It retains the
separate wing bodygroups, marks their materials as two-sided, and writes a new
scene, manifest and source-hash receipt. The default source scale is 400.

XA morphs are assigned by the reference vertex count for each clip. Face and
face-parts can share the XX frame name `P_face` while occupying different FBX
submeshes, sometimes in reverse order. Assigning both to the largest mesh
deforms the face. Ambiguous or inconsistent counts now stop the import. Bone
copies also retain their transformed lengths so small head rigs survive export
normalization without shifting skinned hair.

The compiled model should be visually checked in GMod for bodygroup
combinations, eye-bone posing, flex names, and texture coverage. The generated
addon contains only build output; source game packages and extracted assets stay
outside the repository.

An individual bodygroup can set `"default_visible": false` in its manifest to
start hidden even with `--outfit-visible`. This preserves separate controls for
overlapping alternatives, such as Mashiro's brown and white tails, without
drawing both surfaces by default. Omit the field to use the command-line default.

Mashiro's two clothed outfit builds retain six manual tail controls,
`o01_J_sippo_01` through `o01_J_sippo_06`. The first control attaches to
`o01_J_Kosi02`; the remaining controls form a chain. Rotate the first control to
swing the whole tail, or later controls to bend its tip. Check the rendered skin
and reset the angles afterward; the tail root, hips and head should stay in place.
Tail physics requires a separate setup.

With brown tail A exported first and white tail B set to `default_visible: false`,
bodygroup values A=0/B=0 show brown and A=1/B=1 show white. The group names start
with `00_p_sippo_` or `01_p_sippo_`, depending on the outfit. Keep one variant
visible at a time to avoid coincident surfaces flickering.

Outfits can also contain skin that duplicates the chosen shared body. Keep those
pieces in optional groups that start hidden while retaining the shared body and
clothing. If a skin piece shares a bundled group with clothing, move it into an
appended group so existing group indices stay stable.

Use material-isolation views in game to distinguish duplicate skin from the
shared body clipping through a garment. Clearance can improve a sleeve while
distorting detailed fingerless gloves. Review the per-mesh `unresolved_samples`
and `protected_vertices` in the export report, then inspect the rendered shape;
compilation alone does not establish a good fit.

Thin fabric can disappear from its reverse side while attached trim remains
visible. Compare the same pose with a two-sided material before changing bone
weights. Set `"two_sided": true` on that material's manifest record to emit
`$nocull 1`, or set the Blender material custom property `characolle_two_sided`
before generating the manifest. Check both sides again after the ragdoll falls;
this fixes missing reverse faces, while stiff cloth and intersections still need
their own pose or geometry adjustments.

For nearly coincident fabric and skin, a small shell offset can preserve a
garment's contours better than closest-surface clearance. Set a root-level
`"outfit_shell_offset": {"meshes": ["exact_outfit_object"], "distance": 0.04}` in
the manifest. Distances use normalized Source units and must be within `(0, .25]`.
The exporter averages normals at coincident garment vertices to keep seams
together, preserves relative shape keys, and records moved vertices and maximum
correction. Inspect both sides and bent poses; this does not resolve deep
intersections or correct reversed garment normals.

For boots whose feet already fit, a clearance pass can set `"height_fade": [6, 9]`
in its manifest settings. Corrections stay zero below the first Source height and
fade smoothly to full strength at the second. Apply the same fade to associated
trim layers. The report records `height_faded_vertices` and counts unresolved
samples after fading; inspect the transition and any intentionally uncorrected
areas. Original scenes and relative shape keys remain unchanged.

`gmod/lua/inspect_model.lua` provides a read-only client-side snapshot of a loaded
entity's materials, bodygroups, flex weights, eye bones and `eyes` attachment.
Copy it to `garrysmod/lua/characolle_inspect_model.lua`, then use it from a client
Lua script while looking at the model:

```lua
local inspect = include('characolle_inspect_model.lua')
local report = inspect(LocalPlayer():GetEyeTrace().Entity)
print(util.TableToJSON(report, true))
```

Eye positions use evaluated bone matrices. The report also records the position
getter separately because some loaded rigs return the entity origin from it.
The eye-center error should be near zero with neutral eye offsets; posed eyes
deliberately move away from the fixed attachment. Inspect the rendered result
alongside the snapshot.

`gmod/lua/render_model.lua` draws one live entity into a render target and saves
a PNG plus a JSON receipt under `garrysmod/data/characolle_port_checks`. It runs
inside GMod without desktop input or moving the player's camera. Copy it to
`garrysmod/lua/characolle_render_model.lua` and request a render from client Lua:

```lua
local entity = Entity(123) -- Use the owned test entity's actual index.
entity:SetupBones()
local target = entity:GetBoneMatrix(entity:LookupBone('o01_J_Head')):GetTranslation()
include('characolle_render_model.lua')(entity, {
    name = 'head_' .. os.time(),
    origin = target + entity:GetAngles():Forward() * 38,
    target = target,
    inspect = include('characolle_inspect_model.lua')
})
```

The game can remain unfocused. Keep it running and unpaused; if no render frame
arrives within twenty seconds, the receipt reports a failure. Use a new output
name for each capture. The helper restores the entity's draw flag, omits desktop
overlays, and renders only the requested model against a plain background.
These images verify the live model's appearance and pose. They do not show map
collisions; inspect ragdoll motion and joint measurements separately in the world.

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
