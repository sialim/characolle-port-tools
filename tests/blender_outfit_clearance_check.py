"""Run in Blender background mode to check clothing clearance and shape keys."""

import importlib.util
from pathlib import Path

import bmesh
import bpy


spec = importlib.util.spec_from_file_location(
    "export_source", Path(__file__).resolve().parents[1] / "gmod/export_source.py")
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)
bpy.ops.wm.read_factory_settings(use_empty=True)

mesh = bpy.data.meshes.new("body")
geometry = bmesh.new()
bmesh.ops.create_cube(geometry, size=2)
geometry.to_mesh(mesh)
geometry.free()
body = bpy.data.objects.new("body", mesh)
bpy.context.collection.objects.link(body)

mesh = bpy.data.meshes.new("shirt")
mesh.from_pydata([(0.98, -.2, -.2), (0.98, .2, -.2),
                  (0.98, .2, .2), (0.98, -.2, .2)], [], [(0, 1, 2, 3)])
shirt = bpy.data.objects.new("shirt", mesh)
bpy.context.collection.objects.link(shirt)
shirt.shape_key_add(name="Basis")
key = shirt.shape_key_add(name="Fold")
key.data[0].co.z += .02
key.value = 0
original = [vertex.co.copy() for vertex in body.data.vertices]
manifest = {
    "base_objects": [{"name": "body"}],
    "bodygroups": [{"mesh": {"name": "shirt"}}],
    "outfit_clearance": {"meshes": ["shirt"], "distance": .06, "max_correction": .5},
}
report = exporter.apply_outfit_clearance(manifest)
assert report["meshes"]["shirt"]["moved_vertices"] == 4
assert report["meshes"]["shirt"]["limited_vertices"] == 0
basis = shirt.data.shape_keys.key_blocks["Basis"]
assert all(abs(vertex.co.x - 1.06) < 1e-5 for vertex in basis.data)
assert abs((key.data[0].co - basis.data[0].co).z - .02) < 1e-5
assert all((vertex.co - point).length == 0 for vertex, point in zip(body.data.vertices, original))
assert exporter.apply_outfit_clearance({"base_objects": []}) == {}

# Oversized corrections remain unchanged for manual review.
for data in (basis.data, key.data):
    for vertex in data:
        vertex.co.x = .88
bpy.context.view_layer.update()
manifest["outfit_clearance"]["max_correction"] = .1
report = exporter.apply_outfit_clearance(manifest)
assert report["meshes"]["shirt"]["limited_vertices"] == 4
assert all(abs(vertex.co.x - .88) < 1e-5 for vertex in basis.data)
print("PASS: bounded garment clearance, shape keys, unchanged shared body and opt-in behavior")

