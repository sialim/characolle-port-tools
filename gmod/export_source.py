"""Prepare a CharaColle scene and export its GMod mesh groups with Source Tools."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

import bpy
import bmesh
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
        edit_bone.length = max(((inverse @ source.matrix_world).to_3x3()
                                @ (source_bone.tail_local - source_bone.head_local)).length, 0.000001)
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
            raise RuntimeError(f"Missing requested body armature for layer {canonical_layer}")
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


def attach_recovered_head(manifest: dict) -> list[str]:
    if not manifest.get("scene", {}).get("recovered_from_compiled"):
        return []
    objects = [bpy.data.objects[entry["name"]] for entry in manifest["head_objects"]]
    armatures = {modifier.object for obj in objects for modifier in obj.modifiers
                 if modifier.type == "ARMATURE" and modifier.object}
    if len(armatures) != 1:
        raise ValueError("Recovered head must use one armature")
    armature = armatures.pop()
    if "o01_J_Head" not in armature.data.bones:
        raise ValueError("Recovered head attachment bone is missing")
    body_root = armature.data.bones["o01_J_Head"]
    while body_root.parent:
        body_root = body_root.parent
    roots = set()
    for obj in objects:
        used = {group.group for vertex in obj.data.vertices for group in vertex.groups if group.weight > 0}
        for index in used:
            bone = armature.data.bones.get(obj.vertex_groups[index].name)
            if bone is None:
                continue
            while bone.parent:
                bone = bone.parent
            if bone != body_root:
                roots.add(bone.name)
    if not roots:
        return []
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="EDIT")
    for name in sorted(roots):
        bone = armature.data.edit_bones[name]
        matrix = bone.matrix.copy()
        bone.parent = armature.data.edit_bones["o01_J_Head"]
        bone.use_connect = False
        bone.matrix = matrix
    bpy.ops.object.mode_set(mode="OBJECT")
    return sorted(roots)


def restore_weighted_deformers(manifest: dict, armature: bpy.types.Object) -> list[dict]:
    entries = list(manifest.get("base_objects", []))
    entries.extend(mesh for entry in manifest.get("bodygroups", [])
                   for mesh in (entry.get("meshes") or [entry["mesh"]]))
    restored = []
    bone_names = set(armature.data.bones.keys())
    for name in dict.fromkeys(entry["name"] for entry in entries):
        obj = bpy.data.objects[name]
        if obj.type != "MESH" or any(modifier.type == "ARMATURE" for modifier in obj.modifiers):
            continue
        used = [{obj.vertex_groups[link.group].name for link in vertex.groups
                 if link.weight > 0 and obj.vertex_groups[link.group].name in bone_names}
                for vertex in obj.data.vertices]
        weighted_bones = set().union(*used) if used else set()
        if not weighted_bones:
            continue
        if obj.parent == armature and obj.parent_type == "BONE" and weighted_bones == {obj.parent_bone}:
            continue
        if any(not bones for bones in used):
            raise ValueError(f"Cannot restore partial skin weights on {obj.name}")
        graph = bpy.context.evaluated_depsgraph_get()
        evaluated = obj.evaluated_get(graph)
        before = [evaluated.matrix_world @ vertex.co for vertex in evaluated.data.vertices]
        world = obj.matrix_world.copy()
        obj.parent = armature
        obj.parent_type = "OBJECT"
        obj.parent_bone = ""
        obj.matrix_world = world
        modifier = obj.modifiers.new(name="CHARACOLLE_EXPORT_SKIN", type="ARMATURE")
        modifier.object = armature
        bpy.context.view_layer.update()
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        after = [evaluated.matrix_world @ vertex.co for vertex in evaluated.data.vertices]
        if len(before) != len(after):
            raise ValueError(f"Restoring skin changes vertex count on {obj.name}")
        error = max(((a - b).length for a, b in zip(before, after)), default=0.0)
        extent = max((max(v[i] for v in before) - min(v[i] for v in before) for i in range(3)), default=0.0)
        if error > max(extent * 0.0001, 1e-7):
            raise ValueError(f"Restoring skin changes fitted geometry on {obj.name}: {error:g}")
        restored.append({"mesh": obj.name, "bones": sorted(weighted_bones),
                         "maximum_geometry_error": error})
    return restored


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


def simplify_mantle_bones(keep_bones: list[str] | None = None) -> dict:
    """Keep the cape attached to the torso without exceeding Source's bone limit."""
    if keep_bones is not None and (not isinstance(keep_bones, list)
                                   or any(not isinstance(name, str) for name in keep_bones)):
        raise ValueError("mantle_keep_bones must be a list of bone names")
    canonical = bpy.data.objects.get(bpy.context.scene.get("characolle_shared_body_rig", ""))
    if canonical is None:
        return {"removed_mantle_bones": 0, "simplified_mantle_meshes": 0}
    bones = {bone.name for bone in canonical.data.bones}
    mantle_names = {name for name in bones if "mant" in name.casefold()}
    keep = set(keep_bones or [])
    if keep - mantle_names:
        raise ValueError(f"Unknown retained mantle bones: {sorted(keep - mantle_names)}")
    removed = mantle_names - keep
    if keep and len(bones) - len(removed) > 256:
        raise ValueError("Retained mantle bones exceed the 256-bone export budget")
    if not mantle_names:
        return {"removed_mantle_bones": 0, "simplified_mantle_meshes": 0}
    fallback = next((name for name in ("o01_J_Spin04", "o01_J_Spin03", "o01_J_Spin01") if name in bones), None)
    if fallback is None:
        raise RuntimeError("Could not find a torso fallback bone for the mantle export")

    replacements = {}
    for name in removed:
        parent = canonical.data.bones[name].parent
        while parent is not None and parent.name in removed:
            parent = parent.parent
        replacements[name] = parent.name if parent is not None and parent.name in keep else fallback
    simplified = 0
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        mantle_groups = [group for group in obj.vertex_groups if group.name in removed]
        if not mantle_groups:
            continue
        targets = {group.index: replacements[group.name] for group in mantle_groups}
        target_groups = {name: obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name)
                         for name in set(targets.values())}
        target_indices = {group.index: name for name, group in target_groups.items()}
        for vertex in obj.data.vertices:
            weights = {}
            changed = False
            for link in vertex.groups:
                name = targets.get(link.group) or target_indices.get(link.group)
                if name is not None:
                    weights[name] = weights.get(name, 0.0) + link.weight
                    changed |= link.group in targets
            if changed:
                for name, weight in weights.items():
                    target_groups[name].add([vertex.index], weight, "REPLACE")
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
    return {"removed_mantle_bones": len(removed), "simplified_mantle_meshes": simplified,
            "mantle_fallback": fallback, "retained_mantle_bones": sorted(keep)}


def temporary_collection(name: str, objects: list[bpy.types.Object]) -> bpy.types.Collection:
    existing = bpy.data.collections.get(name)
    if existing is not None:
        existing.name = name + "__source"
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


def clearance_pass(manifest: dict, settings: dict) -> dict:
    distance = float(settings["distance"])
    maximum = float(settings["max_correction"])
    iterations = int(settings.get("face_iterations", 0))
    subdivisions = int(settings.get("subdivide", 0))
    if (not 0 < distance <= 0.5 or not distance <= maximum <= 2
            or not 0 <= iterations <= 16 or subdivisions not in (0, 1)):
        raise ValueError("Invalid garment distance, correction limit or sampling iterations")
    height_fade = settings.get("height_fade")
    if height_fade is not None:
        if (not isinstance(height_fade, (list, tuple)) or len(height_fade) != 2
                or not all(isinstance(value, (int, float)) and math.isfinite(value)
                           for value in height_fade)
                or height_fade[0] >= height_fade[1]):
            raise ValueError("Clearance height_fade requires two increasing finite Source heights")
    entries = [mesh for group in manifest.get("bodygroups", [])
               for mesh in (group.get("meshes") or [group["mesh"]])]
    available = {entry["name"] for entry in entries}
    names = list(dict.fromkeys(settings["meshes"]))
    references = list(dict.fromkeys(settings.get("reference_meshes", [])))
    if (set(names) | set(references)) - available:
        raise ValueError("Clearance can only use selected outfit meshes")
    if set(names) & set(references):
        raise ValueError("An outfit mesh cannot be its own clearance reference")
    vertex_counts = {}
    for name in names:
        obj = bpy.data.objects[name]
        vertex_counts[name] = len(obj.data.vertices)
        if subdivisions:
            if obj.data.shape_keys:
                raise ValueError(f"Clearance subdivision cannot discard garment shape keys: {name}")
            if len(obj.data.vertices) * 4 > 60000:
                raise ValueError(f"Clearance subdivision would exceed the export vertex budget: {name}")
            geometry = bmesh.new()
            geometry.from_mesh(obj.data)
            bmesh.ops.subdivide_edges(geometry, edges=list(geometry.edges), cuts=1, use_grid_fill=True)
            geometry.to_mesh(obj.data)
            geometry.free()
            obj.data.update()
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()

    def surface(object_names):
        points, faces = [], []
        for name in object_names:
            obj = bpy.data.objects[name].evaluated_get(graph)
            start = len(points)
            points.extend(obj.matrix_world @ vertex.co for vertex in obj.data.vertices)
            faces.extend(tuple(start + index for index in face.vertices) for face in obj.data.polygons)
        return BVHTree.FromPolygons(points, faces)

    surfaces = [surface([entry["name"] for entry in manifest["base_objects"]])]
    surfaces.extend(surface([name]) for name in references)

    def query(collider, point):
        nearest, normal, index, separation = collider.find_nearest(point, maximum + distance)
        if nearest is not None and collider is not surfaces[0] and settings.get("orient_references"):
            body_point, body_normal, _, _ = surfaces[0].find_nearest(nearest, maximum + distance)
            if body_point is not None and normal.dot(body_normal) < 0:
                normal = -normal
        return nearest, normal, index, separation

    def contact(point, facing=None, only_base=False):
        result = Vector((0, 0, 0))
        selected = None
        for collider in surfaces[:1] if only_base else surfaces:
            nearest, normal, _, separation = query(collider, point)
            if nearest is None:
                continue
            signed = (point - nearest).dot(normal)
            if facing is not None:
                alignment = normal.dot(facing)
                if settings.get("sample_backfaces"):
                    alignment = abs(alignment)
                if alignment < 0.2 or abs(signed) < separation * 0.8:
                    continue
            correction = distance - signed
            if correction > result.length and correction > 0.00001:
                result = normal * correction
                selected = collider
        return result, selected

    report = {}
    for name in names:
        obj = bpy.data.objects[name]
        evaluated = obj.evaluated_get(graph)
        basis = obj.data.shape_keys.key_blocks[0].data if obj.data.shape_keys else obj.data.vertices
        if len(evaluated.data.vertices) != len(basis):
            raise ValueError(f"Clearance requires unchanged vertex topology: {name}")
        original = [obj.matrix_world @ vertex.co for vertex in basis]
        if any((evaluated.matrix_world @ evaluated.data.vertices[i].co - point).length > 0.0001
               for i, point in enumerate(original)):
            raise ValueError(f"Clearance requires an unposed outfit: {name}")
        points = [point.copy() for point in original]
        limited = set()
        protected = set()

        def move(proposals):
            moved = 0
            for index, delta in proposals.items():
                if delta.length <= 0.00001:
                    continue
                candidate = points[index] + delta
                nearest, normal, _, _ = query(surfaces[0], candidate)
                if nearest is not None:
                    before, before_normal, _, _ = query(surfaces[0], points[index])
                    before_signed = (points[index] - before).dot(before_normal) if before is not None else 0
                    if (candidate - nearest).dot(normal) < min(0, before_signed) - 0.002:
                        protected.add(index)
                        continue
                if (candidate - original[index]).length > maximum:
                    limited.add(index)
                    continue
                points[index] = candidate
                moved += 1
            return moved

        move({index: contact(point, only_base=True)[0] for index, point in enumerate(points)})
        move({index: contact(point)[0] for index, point in enumerate(points)})

        def face_samples():
            edge_normals = {}
            for face in obj.data.polygons:
                indices = tuple(face.vertices)
                normal = (points[indices[1]] - points[indices[0]]).cross(
                    points[indices[2]] - points[indices[0]]).normalized()
                yield indices, normal
                for a, b in zip(indices, indices[1:] + indices[:1]):
                    edge = tuple(sorted((a, b)))
                    edge_normals[edge] = edge_normals.get(edge, Vector((0, 0, 0))) + normal
            for edge, normal in edge_normals.items():
                yield edge, normal.normalized()

        completed = 0
        for iteration in range(iterations):
            proposals = {}
            for indices, normal in face_samples():
                center = sum((points[index] for index in indices), Vector((0, 0, 0))) / len(indices)
                delta, collider = contact(center, normal)
                if delta.length < 0.001:
                    continue
                directions = []
                for index in indices:
                    nearest, outward, _, _ = query(collider, points[index])
                    if nearest is not None:
                        alignment = outward.dot(delta.normalized())
                        if alignment > 0.15:
                            directions.append((index, outward, alignment))
                for index, outward, alignment in directions:
                    amount = min(0.15, delta.length * 0.65 * len(indices) / len(directions) / alignment)
                    proposal = outward * amount
                    if index not in proposals or proposal.length > proposals[index].length:
                        proposals[index] = proposal
            completed = iteration + 1
            if not move(proposals):
                break
            move({index: contact(point)[0] for index, point in enumerate(points)})
        faded = 0
        if height_fade is not None:
            for index, point in enumerate(original):
                weight = max(0.0, min(1.0, (point.z - height_fade[0]) /
                                     (height_fade[1] - height_fade[0])))
                weight = weight * weight * (3 - 2 * weight)
                if weight < 1 and (points[index] - point).length > 0.00001:
                    faded += 1
                    points[index] = point + (points[index] - point) * weight
        unresolved = 0
        if iterations:
            for indices, normal in face_samples():
                center = sum((points[index] for index in indices), Vector((0, 0, 0))) / len(indices)
                if contact(center, normal)[0].length > distance + 0.002:
                    unresolved += 1
        inverse = obj.matrix_world.inverted().to_3x3()
        changes = {i: inverse @ (point - original[i]) for i, point in enumerate(points)
                   if (point - original[i]).length > 0.00001}
        coordinates = ([key.data for key in obj.data.shape_keys.key_blocks]
                       if obj.data.shape_keys else [obj.data.vertices])
        for data in coordinates:
            for index, delta in changes.items():
                data[index].co += delta
        obj.data.update()
        report[name] = {"moved_vertices": len(changes), "limited_vertices": len(limited),
                        "maximum_correction": max(((points[i] - original[i]).length for i in changes), default=0),
                        "face_iterations": completed, "unresolved_samples": unresolved,
                        "vertices_before": vertex_counts[name], "vertices_after": len(basis),
                        "height_faded_vertices": faded,
                        "protected_vertices": len(protected)}
    bpy.context.view_layer.update()
    return {"distance": distance, "max_correction": maximum,
            "reference_meshes": references, "height_fade": height_fade, "meshes": report}


def apply_outfit_clearance(manifest: dict) -> dict:
    settings = manifest.get("outfit_clearance")
    if not settings:
        return {}
    report = clearance_pass(manifest, settings)
    if settings.get("layers"):
        report["layers"] = [clearance_pass(manifest, layer) for layer in settings["layers"]]
    return report


def export_collection(collection: bpy.types.Collection, output: Path, material_path: str, export_format: str) -> None:
    scene = bpy.context.scene
    scene.vs.export_path = str(output)
    scene.vs.export_format = export_format
    scene.vs.material_path = material_path
    scene.vs.smd_format = "SOURCE"
    scene.vs.up_axis = "Z"
    renamed = []
    for obj in collection.objects:
        if obj.type != "MESH":
            continue
        bones = {bone.name for modifier in obj.modifiers if modifier.type == "ARMATURE" and modifier.object
                 for bone in modifier.object.data.bones}
        if obj.name in bones:
            original = obj.name
            obj.name = "CC_EXPORT_" + obj.name
            renamed.append((obj.name, original))
    try:
        bpy.ops.export_scene.smd(collection=collection.name, export_scene=False)
    finally:
        for temporary, original in renamed:
            obj = bpy.data.objects.get(temporary)
            if obj is not None:
                obj.name = original
    suffix = ".dmx" if export_format == "DMX" else ".smd"
    if not (output / (collection.name + suffix)).is_file():
        raise RuntimeError(f"Source Tools did not write the requested mesh: {collection.name + suffix}")


def prepare_eye_control_frame(manifest: dict) -> dict:
    armatures = {modifier.object for entry in manifest["base_objects"]
                 for modifier in bpy.data.objects[entry["name"]].modifiers
                 if modifier.type == "ARMATURE" and modifier.object}
    if len(armatures) != 1:
        return {}
    armature = armatures.pop()
    if not all(name in armature.data.bones for name in ("eye_L", "eye_R", "o01_J_Head")):
        return {}
    center = armature.matrix_world @ ((armature.data.bones["eye_L"].head_local
                                      + armature.data.bones["eye_R"].head_local) * 0.5)
    meshes = [bpy.data.objects[entry["name"]] for entry in manifest["head_objects"]]
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    samples = {obj.name: [(i, obj.evaluated_get(graph).matrix_world @ obj.evaluated_get(graph).data.vertices[i].co)
                         for i in range(0, len(obj.data.vertices), max(1, len(obj.data.vertices) // 32))]
               for obj in meshes}
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="EDIT")
    bones = armature.data.edit_bones
    saved = {name: (bones[name].matrix.copy(), bones[name].length) for name in ("eye_L", "eye_R")}
    frame = bones.get("eye_controls") or bones.new("eye_controls")
    frame.parent = bones["o01_J_Head"]
    frame.use_connect = False
    inverse = armature.matrix_world.inverted()
    frame.head = inverse @ center
    frame.tail = inverse @ (center + Vector((0, 0.1, 0)))
    frame.align_roll(inverse.to_3x3() @ Vector((-1, 0, 0)))
    for name, (matrix, length) in saved.items():
        bones[name].parent = frame
        bones[name].use_connect = False
        bones[name].matrix = matrix
        bones[name].length = length
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    error = max((obj.evaluated_get(graph).matrix_world @ obj.evaluated_get(graph).data.vertices[i].co - point).length
                for obj in meshes for i, point in samples[obj.name])
    if error > 0.01:
        raise RuntimeError(f"Eye control frame changed the neutral head geometry: {error}")
    return {"bone": "eye_controls", "maximum_geometry_error": error}


def eye_attachments(manifest: dict) -> dict | None:
    armatures = {modifier.object for entry in manifest["base_objects"]
                 for modifier in bpy.data.objects[entry["name"]].modifiers
                 if modifier.type == "ARMATURE" and modifier.object}
    if len(armatures) != 1:
        return None
    armature = armatures.pop()
    bones = armature.data.bones
    if not all(name in bones for name in ("eye_L", "eye_R", "o01_J_Head")):
        return None
    center = armature.matrix_world @ ((bones["eye_L"].head_local + bones["eye_R"].head_local) * 0.5)
    head = armature.matrix_world @ bones["o01_J_Head"].matrix_local
    local_position = head.inverted() @ center
    forward = Matrix(((0, 1, 0), (-1, 0, 0), (0, 0, 1)))
    local_rotation = head.to_3x3().inverted() @ forward
    euler = local_rotation.to_euler("XYZ")
    angles = [math.degrees(euler.y), math.degrees(euler.z), math.degrees(euler.x)]
    return {"eye_position": list(center), "attachments": [{"name": "eyes", "bone": "o01_J_Head",
            "position": list(local_position), "rotation": angles}]}


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
    canonical_layer = args.canonical_layer or manifest.get("scene", {}).get("canonical_body_layer")
    if canonical_layer is not None and canonical_layer not in {"00", "01", "02", "03", "04"}:
        raise ValueError(f"Invalid manifest canonical body layer: {canonical_layer}")
    staging = prepare_single_armature(canonical_layer)
    staging["restored_weighted_deformers"] = restore_weighted_deformers(manifest, bpy.data.objects[staging["armature"]])
    staging["recovered_head_roots_attached"] = attach_recovered_head(manifest)
    staging["eye_controls_added"] = eye_controls_added
    if not args.keep_mantle_bones:
        staging.update(simplify_mantle_bones(manifest.get("mantle_keep_bones")))
    staging["pruned_vertices"] = prune_weights(args.max_influences)
    staging["renamed_shape_keys"] = clean_shape_names()
    if args.target_height is not None:
        staging["coordinate_normalization"] = normalize_export_transforms(manifest, args.target_height)
    elif manifest.get("outfit_clearance"):
        raise ValueError("Outfit clearance requires normalized Source units")
    staging["outfit_clearance"] = apply_outfit_clearance(manifest)
    if staging["outfit_clearance"]:
        staging["post_clearance_pruned_vertices"] = prune_weights(args.max_influences)
        staging["post_clearance_normalization"] = normalize_export_transforms(manifest, args.target_height)
    args.output.mkdir(parents=True, exist_ok=True)
    staging["eye_control_frame"] = prepare_eye_control_frame(manifest)
    attachments = eye_attachments(manifest)
    if attachments is not None:
        (args.output / "attachments.json").write_text(json.dumps(attachments, indent=2), encoding="utf-8")
    head_flexes = [key.name for entry in manifest.get("head_objects", [])
                   if bpy.data.objects[entry["name"]].data.shape_keys
                   for key in bpy.data.objects[entry["name"]].data.shape_keys.key_blocks if key.name != "Basis"]
    (args.output / "flexes.json").write_text(json.dumps(head_flexes, indent=2), encoding="utf-8")
    face = bpy.data.objects.get("P_face")
    aliases = dict(manifest.get("flex_aliases", {}))
    if any(target not in head_flexes or source not in head_flexes for target, source in aliases.items()):
        raise ValueError("Manifest facial links reference absent exported shape keys")
    if face and face.type == "MESH" and face.data.shape_keys:
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
