"""Prepare a CharaColle scene and export its GMod mesh groups with Source Tools."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-tools", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--material-path", required=True)
    parser.add_argument("--format", choices=("DMX", "SMD"), default="DMX")
    parser.add_argument("--max-influences", type=int, default=3)
    parser.add_argument("--keep-mantle-bones", action="store_true")
    parser.add_argument("--canonical-layer", choices=("00", "01", "02", "03", "04"))
    parser.add_argument("--target-height", type=float, default=61.2, help="Export height in Source units (72 units reduced by 15%%)")
    parser.add_argument("--physics", action="store_true", help="Export a jointed collision skeleton")
    return parser.parse_args(argv)


def register_source_tools(path: Path) -> None:
    sys.path.insert(0, str(path))
    import io_scene_valvesource

    io_scene_valvesource.register()


def copy_bones(canonical: bpy.types.Object, source: bpy.types.Object) -> int:
    missing = set(bone.name for bone in source.data.bones) - set(bone.name for bone in canonical.data.bones)
    if not missing:
        return 0
    bpy.ops.object.mode_set(mode="OBJECT") if bpy.context.object and bpy.context.object.mode != "OBJECT" else None
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    canonical.select_set(True)
    bpy.context.view_layer.objects.active = canonical
    inverse = canonical.matrix_world.inverted()
    bpy.ops.object.mode_set(mode="EDIT")
    copied: set[str] = set()

    def copy_one(name: str) -> None:
        if name in copied or canonical.data.edit_bones.get(name):
            copied.add(name)
            return
        source_bone = source.data.bones[name]
        if source_bone.parent and source_bone.parent.name not in canonical.data.edit_bones:
            copy_one(source_bone.parent.name)
        edit_bone = canonical.data.edit_bones.new(name)
        edit_bone.matrix = inverse @ source.matrix_world @ source_bone.matrix_local
        edit_bone.use_connect = False
        edit_bone.use_deform = source_bone.use_deform
        if source_bone.parent:
            edit_bone.parent = canonical.data.edit_bones.get(source_bone.parent.name)
        elif source.parent is not None and source.parent.type == "ARMATURE" and source.parent_type == "BONE":
            edit_bone.parent = canonical.data.edit_bones.get(source.parent_bone)
        copied.add(name)

    for name in sorted(missing):
        copy_one(name)
    bpy.ops.object.mode_set(mode="OBJECT")
    return len(missing)


def unhide_object_collection(obj: bpy.types.Object) -> None:
    obj.hide_set(False)
    obj.hide_viewport = False

    def visit(layer: bpy.types.LayerCollection) -> None:
        if layer.collection in obj.users_collection:
            layer.hide_viewport = False
            layer.exclude = False
        for child in layer.children:
            visit(child)

    for layer in bpy.context.view_layer.layer_collection.children:
        visit(layer)


def prepare_single_armature(canonical_layer: str | None = None) -> dict:
    canonical = None
    if canonical_layer:
        canonical = next(
            (
                obj
                for obj in bpy.data.objects
                if obj.type == "ARMATURE" and obj.name.startswith(f"BODY_{canonical_layer}__")
            ),
            None,
        )
    if canonical is None:
        canonical = bpy.data.objects.get(bpy.context.scene.get("characolle_shared_body_rig", ""))
    if canonical is None:
        preferred = bpy.context.scene.get("characolle_canonical_body_layer", "02")
        canonical = next(
            (
                obj
                for obj in bpy.data.objects
                if obj.type == "ARMATURE" and obj.name.startswith(f"BODY_{preferred}__")
            ),
            None,
        )
    if canonical is None:
        canonical = next(
            (
                obj
                for obj in bpy.data.objects
                if obj.type == "ARMATURE" and obj.name.startswith(("BODY_03__", "BODY_02__"))
            ),
            None,
        )
    if canonical is None:
        raise RuntimeError("Could not find the shared body armature")
    unhide_object_collection(canonical)
    old_armatures = {obj for obj in bpy.data.objects if obj.type == "ARMATURE" and obj != canonical}
    copied_bones = sum(copy_bones(canonical, source) for source in old_armatures)
    canonical_bones = {bone.name for bone in canonical.data.bones}
    inherited_attachments = {
        source: source.parent_bone for source in old_armatures
        if source.parent in (old_armatures | {canonical}) and source.parent_type == "BONE"
        and source.parent_bone in canonical_bones
    }
    rebound = 0
    restored_attachments = 0
    for obj in list(bpy.data.objects):
        old_parent = obj.parent in old_armatures
        parent_bone = obj.parent_bone if obj.parent_type == "BONE" else inherited_attachments.get(obj.parent, "")
        old_modifiers = [modifier for modifier in obj.modifiers if modifier.type == "ARMATURE" and modifier.object in old_armatures]
        if not old_parent and not old_modifiers:
            continue
        world = obj.matrix_world.copy()
        if obj.type == "MESH":
            for modifier in old_modifiers:
                modifier.object = canonical
            if not any(modifier.type == "ARMATURE" and modifier.object == canonical for modifier in obj.modifiers):
                matching = [group.name for group in obj.vertex_groups if group.name in canonical_bones]
                if matching:
                    modifier = obj.modifiers.new(name="CHARACOLLE_EXPORT_RIG", type="ARMATURE")
                    modifier.object = canonical
            if old_parent:
                obj.parent = canonical
                if parent_bone in canonical_bones and not any(modifier.type == "ARMATURE" for modifier in obj.modifiers):
                    obj.parent_type = "BONE"
                    obj.parent_bone = parent_bone
                    restored_attachments += 1
                else:
                    obj.parent_type = "OBJECT"
                obj.matrix_world = world
            rebound += 1
        elif old_parent:
            obj.parent = canonical
            if parent_bone and parent_bone in canonical_bones:
                obj.parent_type = "BONE"
                obj.parent_bone = parent_bone
                restored_attachments += 1
            else:
                obj.parent_type = "OBJECT"
            obj.matrix_world = world

    for armature in old_armatures:
        bpy.data.objects.remove(armature, do_unlink=True)
    bpy.context.view_layer.update()
    return {"armature": canonical.name, "copied_bones": copied_bones, "rebound_objects": rebound,
            "removed_armatures": len(old_armatures), "restored_rigid_attachments": restored_attachments}


def prune_weights(max_influences: int) -> int:
    changed = 0
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        modifiers = [modifier for modifier in obj.modifiers if modifier.type == "ARMATURE" and modifier.object]
        if not modifiers:
            continue
        bone_names = {bone.name for bone in modifiers[0].object.data.bones}
        for vertex in obj.data.vertices:
            links = [(group.group, group.weight) for group in vertex.groups if obj.vertex_groups[group.group].name in bone_names]
            if len(links) <= max_influences:
                continue
            links.sort(key=lambda item: item[1], reverse=True)
            keep = links[:max_influences]
            keep_ids = {group_id for group_id, _ in keep}
            total = sum(weight for _, weight in keep)
            for group_id, _ in links[max_influences:]:
                obj.vertex_groups[group_id].remove([vertex.index])
            if total > 0:
                for group_id, weight in keep:
                    obj.vertex_groups[group_id].add([vertex.index], weight / total, "REPLACE")
            changed += 1
    return changed


def clean_shape_names() -> int:
    changed = 0
    used_names: set[str] = set()
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.data.shape_keys is None:
            continue
        for key in obj.data.shape_keys.key_blocks:
            if key.name == "Basis":
                continue
            original = key.name
            tail = original.rsplit("__", 1)[-1]
            parts = re.findall(r"[A-Za-z0-9]+", tail)
            cleaned = "".join(part[:1].upper() + part[1:] for part in parts)
            if not cleaned:
                cleaned = "Flex"
            if cleaned in used_names:
                suffix = re.sub(r"^P_", "", obj.name, flags=re.IGNORECASE)
                suffix = re.sub(r"[^A-Za-z0-9]+", "", suffix)
                cleaned = f"{cleaned}{suffix or 'Mesh'}"
                serial = 2
                candidate = cleaned
                while candidate in used_names:
                    candidate = f"{cleaned}{serial}"
                    serial += 1
                cleaned = candidate
            if cleaned != original:
                key.name = cleaned
                changed += 1
            used_names.add(cleaned)
    return changed


def simplify_mantle_bones() -> dict:
    """Keep the cape attached to the torso without exceeding Source's bone limit."""
    canonical = bpy.data.objects.get(bpy.context.scene.get("characolle_shared_body_rig", ""))
    if canonical is None:
        return {"removed_mantle_bones": 0, "simplified_mantle_meshes": 0}
    bones = {bone.name for bone in canonical.data.bones}
    mantle_names = {name for name in bones if "mant" in name.casefold()}
    if not mantle_names:
        return {"removed_mantle_bones": 0, "simplified_mantle_meshes": 0}
    fallback = next((name for name in ("o01_J_Spin04", "o01_J_Spin03", "o01_J_Spin01") if name in bones), None)
    if fallback is None:
        raise RuntimeError("Could not find a torso fallback bone for the mantle export")

    simplified = 0
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        mantle_groups = [group for group in obj.vertex_groups if group.name in mantle_names]
        if not mantle_groups:
            continue
        fallback_group = obj.vertex_groups.get(fallback) or obj.vertex_groups.new(name=fallback)
        mantle_indices = {group.index for group in mantle_groups}
        for vertex in obj.data.vertices:
            mantle_weight = 0.0
            fallback_weight = 0.0
            for link in vertex.groups:
                if link.group in mantle_indices:
                    mantle_weight += link.weight
                elif link.group == fallback_group.index:
                    fallback_weight = link.weight
            if mantle_weight:
                fallback_group.add([vertex.index], fallback_weight + mantle_weight, "REPLACE")
        for group in mantle_groups:
            obj.vertex_groups.remove(group)
        simplified += 1

    bpy.ops.object.mode_set(mode="OBJECT") if bpy.context.object and bpy.context.object.mode != "OBJECT" else None
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    canonical.select_set(True)
    bpy.context.view_layer.objects.active = canonical
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = canonical.data.edit_bones
    removed = set(mantle_names)
    for edit_bone in list(edit_bones):
        if edit_bone.name not in removed:
            continue
        for child in list(edit_bone.children):
            parent = edit_bone.parent
            while parent is not None and parent.name in removed:
                parent = parent.parent
            world = child.matrix.copy()
            child.parent = parent
            child.matrix = world
    for name in sorted(removed):
        edit_bone = edit_bones.get(name)
        if edit_bone is not None:
            edit_bones.remove(edit_bone)
    bpy.ops.object.mode_set(mode="OBJECT")
    return {"removed_mantle_bones": len(removed), "simplified_mantle_meshes": simplified, "mantle_fallback": fallback}


def temporary_collection(name: str, objects: list[bpy.types.Object]) -> bpy.types.Collection:
    collection = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(collection)
    for obj in objects:
        collection.objects.link(obj)
    return collection


def normalize_export_transforms(manifest: dict, target_height: float) -> dict:
    if not 0 < target_height < 1000:
        raise ValueError("Target height must be between 0 and 1000 Source units")
    entries = list(manifest.get("base_objects", [])) + list(manifest.get("head_objects", []))
    entries.extend(mesh for entry in manifest.get("bodygroups", []) for mesh in (entry.get("meshes") or [entry["mesh"]]))
    objects = [bpy.data.objects[name] for name in dict.fromkeys(entry["name"] for entry in entries)]
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    points = [
        obj.evaluated_get(graph).matrix_world @ vertex.co
        for obj in objects
        for vertex in obj.evaluated_get(graph).data.vertices
    ]
    bottom, top = min(point.z for point in points), max(point.z for point in points)
    height = top - bottom
    if height <= 0:
        raise RuntimeError("The reference body and head have no measurable height")
    factor = target_height / height
    transform = Matrix.Scale(factor, 4) @ Matrix.Translation((0, 0, -bottom))
    reference_samples = {
        obj.name: [(index, transform @ obj.evaluated_get(graph).matrix_world @ obj.evaluated_get(graph).data.vertices[index].co)
                   for index in range(0, len(obj.data.vertices), max(1, len(obj.data.vertices) // 32))]
        for obj in objects
    }
    armatures = {modifier.object for obj in objects for modifier in obj.modifiers
                 if modifier.type == "ARMATURE" and modifier.object is not None}
    if len(armatures) != 1:
        raise RuntimeError(f"Expected one export armature, found {len(armatures)}")
    armature = next(iter(armatures))
    matrices = {obj: obj.matrix_world.copy() for obj in objects + [armature]}

    def rigid_parent_bone(obj):
        current = obj
        while current.parent is not None:
            if current.parent == armature and current.parent_type == "BONE":
                return current.parent_bone
            current = current.parent
        return None

    rigid_attachments = {}
    for obj in objects:
        bone = rigid_parent_bone(obj)
        if bone and not any(modifier.type == "ARMATURE" for modifier in obj.modifiers):
            rigid_attachments[obj] = bone
    head_names = {entry["name"] for entry in manifest.get("head_objects", [])}
    detached_head_meshes = [obj.name for obj in objects if obj.name in head_names
                            and obj not in rigid_attachments
                            and not any(modifier.type == "ARMATURE" for modifier in obj.modifiers)]
    if detached_head_meshes:
        raise RuntimeError(f"Head meshes have no bone attachment: {detached_head_meshes}")
    for obj in objects:
        obj.data = obj.data.copy()
        obj.data.transform(transform @ matrices[obj], shape_keys=True)
        obj.parent = None
        obj.matrix_world = Matrix.Identity(4)
        obj.data.update()
    armature.data = armature.data.copy()
    armature_transform = transform @ matrices[armature]
    scales = armature_transform.to_scale()
    if max(scales) - min(scales) > max(scales) * 0.0001:
        raise RuntimeError("Normalize the armature's non-uniform scale before exporting")
    armature.data.transform(armature_transform)
    pose_translation_scale = scales.x
    for bone in armature.pose.bones:
        bone.location *= pose_translation_scale
    armature.parent = None
    armature.matrix_world = Matrix.Identity(4)
    bpy.context.view_layer.update()
    for obj, bone in rigid_attachments.items():
        obj.parent = armature
        obj.parent_type = "BONE"
        obj.parent_bone = bone
    bpy.context.view_layer.update()
    for obj in rigid_attachments:
        obj.matrix_world = Matrix.Identity(4)
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    errors = {obj.name: max(
        (obj.evaluated_get(graph).matrix_world @ obj.evaluated_get(graph).data.vertices[index].co - expected).length
        for index, expected in reference_samples[obj.name]) for obj in objects}
    maximum_error = max(errors.values())
    if maximum_error > 0.01:
        largest = sorted(errors.items(), key=lambda entry: entry[1], reverse=True)[:5]
        raise RuntimeError(f"Normalizing transforms changed the fitted geometry: {largest}")
    return {"reference_height_before": height, "target_height": target_height,
            "coordinate_scale": factor, "reference_ground_before": bottom,
            "normalized_meshes": len(objects), "maximum_geometry_error": maximum_error}


def apply_outfit_clearance(manifest: dict) -> dict:
    settings = manifest.get("outfit_clearance")
    if not settings:
        return {}
    distance = float(settings["distance"])
    maximum = float(settings["max_correction"])
    if not 0 < distance <= 0.5 or not distance <= maximum <= 2:
        raise ValueError("Outfit clearance must be 0–0.5 units with a correction limit up to 2 units")
    entries = [mesh for group in manifest.get("bodygroups", [])
               for mesh in (group.get("meshes") or [group["mesh"]])]
    available = {entry["name"] for entry in entries}
    names = list(dict.fromkeys(settings["meshes"]))
    if set(names) - available:
        raise ValueError("Clearance can only affect selected outfit meshes")
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    points, faces = [], []
    for entry in manifest["base_objects"]:
        obj = bpy.data.objects[entry["name"]].evaluated_get(graph)
        start = len(points)
        points.extend(obj.matrix_world @ vertex.co for vertex in obj.data.vertices)
        faces.extend(tuple(start + index for index in face.vertices) for face in obj.data.polygons)
    surface = BVHTree.FromPolygons(points, faces)
    report = {}
    for name in names:
        obj = bpy.data.objects[name]
        evaluated = obj.evaluated_get(graph)
        if len(evaluated.data.vertices) != len(obj.data.vertices):
            raise ValueError(f"Clearance requires unchanged vertex topology: {name}")
        inverse = obj.matrix_world.inverted().to_3x3()
        changes, limited = {}, 0
        basis = obj.data.shape_keys.key_blocks[0].data if obj.data.shape_keys else obj.data.vertices
        for index, vertex in enumerate(basis):
            point = obj.matrix_world @ vertex.co
            if (evaluated.matrix_world @ evaluated.data.vertices[index].co - point).length > 0.0001:
                raise ValueError(f"Clearance requires an unposed outfit: {name}")
            nearest, normal, _, _ = surface.find_nearest(point, maximum + distance)
            if nearest is None:
                continue
            signed = (point - nearest).dot(normal)
            correction = distance - signed
            if correction <= 0.00001:
                continue
            if correction > maximum:
                limited += 1
                continue
            changes[index] = inverse @ (normal * correction)
        coordinates = ([key.data for key in obj.data.shape_keys.key_blocks]
                       if obj.data.shape_keys else [obj.data.vertices])
        for data in coordinates:
            for index, delta in changes.items():
                data[index].co += delta
        obj.data.update()
        report[name] = {"moved_vertices": len(changes), "limited_vertices": limited,
                        "maximum_correction": max((delta.length for delta in changes.values()), default=0)}
    bpy.context.view_layer.update()
    return {"distance": distance, "max_correction": maximum, "meshes": report}


def export_collection(collection: bpy.types.Collection, output: Path, material_path: str, export_format: str) -> None:
    scene = bpy.context.scene
    scene.vs.export_path = str(output)
    scene.vs.export_format = export_format
    scene.vs.material_path = material_path
    scene.vs.smd_format = "SOURCE"
    scene.vs.up_axis = "Z"
    bpy.ops.export_scene.smd(collection=collection.name, export_scene=False)


def create_physics(manifest: dict, output: Path, height: float) -> bpy.types.Object:
    """Build sixteen separate convex hulls, each rigidly weighted to one body joint."""
    armature = next(mod.object for entry in manifest["base_objects"]
                    for mod in bpy.data.objects[entry["name"]].modifiers if mod.type == "ARMATURE")
    bones = armature.data.bones
    unit = height / 61.2
    vertices, faces, assignments, joints = [], [], [], []
    box_faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                 (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]

    def position(name):
        return armature.matrix_world @ bones[name].head_local

    def hull(name, start, end, width, depth, limits):
        direction = end - start
        if direction.length < 0.01:
            raise RuntimeError(f"Zero length collision segment: {name}")
        axis = direction.normalized()
        reference = Vector((0, 1, 0)) if abs(axis.y) < 0.9 else Vector((1, 0, 0))
        across = axis.cross(reference).normalized() * width * unit
        forward = axis.cross(across).normalized() * depth * unit
        offset = len(vertices)
        for center in (start, end):
            vertices.extend([center-across-forward, center+across-forward,
                             center+across+forward, center-across+forward])
        faces.extend(tuple(offset+i for i in face) for face in box_faces)
        assignments.append((name, list(range(offset, offset+8))))
        joints.append({"bone": name, "limits": limits, "start": list(start), "end": list(end)})

    def segment(name, child, width, depth, limits):
        start, end = position(name), position(child)
        delta = end-start
        hull(name, start+delta*0.08, end-delta*0.08, width, depth, limits)

    def hinge_limits(name, world_axis):
        local_axis = bones[name].matrix_local.to_3x3().inverted() @ Vector(world_axis)
        hinge = max(range(3), key=lambda index: abs(local_axis[index]))
        return [(-125, 125) if index == hinge else (-8, 8) for index in range(3)]

    moderate = [(-25, 25), (-25, 25), (-25, 25)]
    hip = position("o01_J_Hip")
    pelvis = (position("o01_J_UpLeg01_L") + position("o01_J_UpLeg01_R"))*0.5
    hull("o01_J_Hip", pelvis-Vector((0, 0, 1.2*unit)), hip+Vector((0, 0, unit)), 3.6, 2.3, moderate)
    segment("o01_J_Spin01", "o01_J_Spin04", 3.0, 2.0, moderate)
    segment("o01_J_Spin04", "o01_J_Neck", 3.5, 2.0, moderate)
    head = position("o01_J_Head")
    hull("o01_J_Head", head+Vector((0, 0, 0.4*unit)), head+Vector((0, 0, 7*unit)),
         3.4, 3.0, [(-45, 45), (-35, 35), (-50, 50)])
    for side in ("L", "R"):
        segment(f"o01_J_Arm01_{side}", f"o01_J_Hiji01_{side}", 1.2, 1.2, [(-80, 80)]*3)
        segment(f"o01_J_Hiji01_{side}", f"o01_J_Hand_{side}", 0.95, 0.95,
                hinge_limits(f"o01_J_Hiji01_{side}", (0, 0, 1)))
        hand = position(f"o01_J_Hand_{side}")
        finger = position(f"o01_J_Naka01_{side}")
        hull(f"o01_J_Hand_{side}", hand, hand+(finger-hand)*1.7, 0.8, 0.5, [(-35, 35)]*3)
        segment(f"o01_J_UpLeg01_{side}", f"o01_J_Hiza_{side}", 1.8, 1.9, [(-65, 65)]*3)
        segment(f"o01_J_Hiza_{side}", f"o01_J_Foot01_{side}", 1.3, 1.3,
                hinge_limits(f"o01_J_Hiza_{side}", (1, 0, 0)))
        segment(f"o01_J_Foot01_{side}", f"o01_J_Toes_{side}", 1.25, 1.1, [(-30, 30)]*3)
    mesh = bpy.data.meshes.new("physics")
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(bpy.data.materials.new("physics"))
    mesh.update()
    obj = bpy.data.objects.new("physics", mesh)
    bpy.context.scene.collection.objects.link(obj)
    for name, indices in assignments:
        obj.vertex_groups.new(name=name).add(indices, 1.0, "REPLACE")
    modifier = obj.modifiers.new("Armature", "ARMATURE")
    modifier.object = armature
    profile = {"rootbone": "o01_J_Hip", "mass": 45, "hulls": joints}
    (output / "physics.json").write_text(json.dumps(profile, indent=2), encoding="utf-8")
    return obj


def main() -> None:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    register_source_tools(args.source_tools)
    bpy.ops.wm.open_mainfile(filepath=str(args.input))
    eye_controls_added = 0
    head_rig = bpy.data.objects.get("o_N_kao_all")
    if (head_rig is not None and head_rig.type == "ARMATURE"
            and not all(name in head_rig.data.bones for name in ("eye_L", "eye_R"))
            and all(bpy.data.objects.get(name) is not None for name in ("o_N_eye_L", "o_N_eye_R"))):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))
        from add_eye_controls import add_eye_controls
        eye_controls_added = add_eye_controls()
    staging = prepare_single_armature(args.canonical_layer)
    staging["eye_controls_added"] = eye_controls_added
    if not args.keep_mantle_bones:
        staging.update(simplify_mantle_bones())
    staging["pruned_vertices"] = prune_weights(args.max_influences)
    staging["renamed_shape_keys"] = clean_shape_names()
    if args.target_height is not None:
        staging["coordinate_normalization"] = normalize_export_transforms(manifest, args.target_height)
    elif manifest.get("outfit_clearance"):
        raise ValueError("Outfit clearance requires normalized Source units")
    staging["outfit_clearance"] = apply_outfit_clearance(manifest)
    if staging["outfit_clearance"]:
        staging["post_clearance_normalization"] = normalize_export_transforms(manifest, args.target_height)
    args.output.mkdir(parents=True, exist_ok=True)
    head_flexes = [key.name for entry in manifest.get("head_objects", [])
                   if bpy.data.objects[entry["name"]].data.shape_keys
                   for key in bpy.data.objects[entry["name"]].data.shape_keys.key_blocks if key.name != "Basis"]
    (args.output / "flexes.json").write_text(json.dumps(head_flexes, indent=2), encoding="utf-8")
    face = bpy.data.objects.get("P_face")
    aliases = {}
    if face and face.data.shape_keys:
        face_keys = list(face.data.shape_keys.key_blocks)[1:]
        for entry in manifest.get("head_objects", []):
            obj = bpy.data.objects[entry["name"]]
            if obj.name.startswith("P_faceparts") and obj.data.shape_keys:
                keys = list(obj.data.shape_keys.key_blocks)[1:]
                if len(keys) != len(face_keys):
                    raise RuntimeError("Face and face-parts expression lists have different lengths")
                aliases.update({target.name: source.name for source, target in zip(face_keys, keys)})
    (args.output / "flex_aliases.json").write_text(json.dumps(aliases, indent=2), encoding="utf-8")
    exported = []

    def objects_from(entries: list[dict]) -> list[bpy.types.Object]:
        result = []
        for entry in entries:
            obj = bpy.data.objects.get(entry["name"])
            if obj is None:
                raise RuntimeError(f"Manifest object is missing from scene: {entry['name']}")
            result.append(obj)
        return result

    groups = [("base", manifest.get("base_objects", [])), ("head", manifest.get("head_objects", []))]
    groups.extend((f"bg_{entry['name']}", entry.get("meshes") or [entry["mesh"]]) for entry in manifest.get("bodygroups", []))
    for name, entries in groups:
        objects = objects_from(entries)
        collection = temporary_collection(name, objects)
        export_collection(collection, args.output, args.material_path, args.format)
        exported.append(name + (".dmx" if args.format == "DMX" else ".smd"))

    if args.physics:
        physics = create_physics(manifest, args.output, args.target_height)
        collection = temporary_collection("physics", [physics])
        export_collection(collection, args.output, args.material_path, args.format)
        exported.append("physics.dmx" if args.format == "DMX" else "physics.smd")

    report = {"character": manifest["character"], "format": args.format, "exported": exported, "staging": staging}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Exported {len(exported)} Source files to {args.output}")


if __name__ == "__main__":
    main()
