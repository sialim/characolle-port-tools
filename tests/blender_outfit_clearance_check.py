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

mesh = bpy.data.meshes.new("outer")
mesh.from_pydata([(1.04, -.2, -.2), (1.04, .2, -.2),
                  (1.04, .2, .2), (1.04, -.2, .2)], [], [(0, 1, 2, 3)])
outer = bpy.data.objects.new("outer", mesh)
bpy.context.collection.objects.link(outer)
uv = mesh.uv_layers.new(name="UVMap")
for loop in mesh.loops:
    point = mesh.vertices[loop.vertex_index].co
    uv.data[loop.index].uv = ((point.y + .2) / .4, (point.z + .2) / .4)
outer.vertex_groups.new(name="left").add([0, 3], 1, "REPLACE")
outer.vertex_groups.new(name="right").add([1, 2], 1, "REPLACE")
layered = {"base_objects": [{"name": "body"}],
           "bodygroups": [{"mesh": {"name": name}} for name in ["shirt", "outer"]],
           "outfit_clearance": {"meshes": [], "distance": .06, "max_correction": .5,
                                "layers": [{"meshes": ["outer"], "reference_meshes": ["shirt"],
                                            "distance": .03, "max_correction": .5, "subdivide": 1}]}}
exporter.apply_outfit_clearance(layered)
assert all(abs(vertex.co.x - 1.09) < 1e-5 for vertex in outer.data.vertices)
assert all(abs(vertex.co.x - 1.06) < 1e-5 for vertex in basis.data)
assert len(outer.data.vertices) == 9
center_vertex = next(vertex for vertex in outer.data.vertices if abs(vertex.co.y) + abs(vertex.co.z) < 1e-5)
assert all(abs(group.weight - .5) < 1e-5 for group in center_vertex.groups)
assert len(center_vertex.groups) == 2
assert len(outer.data.uv_layers) == 1
assert any((item.uv.x - .5)**2 + (item.uv.y - .5)**2 < 1e-8 for item in outer.data.uv_layers[0].data)
shirt.data.flip_normals()
shirt.data.update()
for vertex in outer.data.vertices:
    vertex.co.x = 1.04
layered["outfit_clearance"]["layers"][0].update(subdivide=0, orient_references=True)
exporter.apply_outfit_clearance(layered)
assert all(abs(vertex.co.x - 1.09) < 1e-5 for vertex in outer.data.vertices)
layered["outfit_clearance"]["layers"][0]["reference_meshes"] = ["outer"]
try:
    exporter.apply_outfit_clearance(layered)
except ValueError as error:
    assert "own clearance reference" in str(error)
else:
    raise AssertionError("Self-referencing garment layers must be rejected")

round_mesh = bpy.data.meshes.new("round_body")
geometry = bmesh.new()
bmesh.ops.create_uvsphere(geometry, u_segments=32, v_segments=16, radius=1)
geometry.to_mesh(round_mesh)
geometry.free()
round_body = bpy.data.objects.new("round_body", round_mesh)
bpy.context.collection.objects.link(round_body)
mesh = bpy.data.meshes.new("corner")
mesh.from_pydata([(.8, .7, 0), (.8, -.35, .6062), (.8, -.35, -.6062)], [], [(0, 1, 2)])
corner = bpy.data.objects.new("corner", mesh)
bpy.context.collection.objects.link(corner)
corner_basis = corner.shape_key_add(name="Basis")
corner_fold = corner.shape_key_add(name="Fold")
corner_fold.data[0].co.z += .02
corner_fold.value = 0
sampled = {"base_objects": [{"name": "round_body"}], "bodygroups": [{"mesh": {"name": "corner"}}],
           "outfit_clearance": {"meshes": ["corner"], "distance": .06,
                                "max_correction": 1.5, "face_iterations": 16}}
report = exporter.apply_outfit_clearance(sampled)
center = sum((vertex.co for vertex in corner_basis.data), corner_basis.data[0].co * 0) / 3
assert center.x >= .99, center
assert report["meshes"]["corner"]["unresolved_samples"] == 0
assert abs((corner_fold.data[0].co - corner_basis.data[0].co).z - .02) < 1e-5
sampled["outfit_clearance"]["subdivide"] = 1
try:
    exporter.apply_outfit_clearance(sampled)
except ValueError as error:
    assert "cannot discard garment shape keys" in str(error)
else:
    raise AssertionError("Garment shape keys must survive or subdivision must stop")

# Oversized corrections remain unchanged for manual review.
for data in (basis.data, key.data):
    for vertex in data:
        vertex.co.x = .88
bpy.context.view_layer.update()
manifest["outfit_clearance"]["max_correction"] = .1
report = exporter.apply_outfit_clearance(manifest)
assert report["meshes"]["shirt"]["limited_vertices"] == 4
assert all(abs(vertex.co.x - .88) < 1e-5 for vertex in basis.data)

mesh = bpy.data.meshes.new("boot")
mesh.from_pydata([(.98, y, z) for z in (-.2, 0, .2) for y in (-.2, .2)],
                 [], [(0, 1, 3, 2), (2, 3, 5, 4)])
boot = bpy.data.objects.new("boot", mesh)
bpy.context.collection.objects.link(boot)
boot_basis = boot.shape_key_add(name="Basis")
boot_fold = boot.shape_key_add(name="Fold")
boot_fold.data[0].co.z += .02
boot_fold.value = 0
faded = {"base_objects": [{"name": "body"}], "bodygroups": [{"mesh": {"name": "boot"}}],
         "outfit_clearance": {"meshes": ["boot"], "distance": .06, "max_correction": .5,
                              "height_fade": [-.2, .2]}}
report = exporter.apply_outfit_clearance(faded)
for index, expected in enumerate((.98, .98, 1.02, 1.02, 1.06, 1.06)):
    assert abs(boot_basis.data[index].co.x - expected) < 1e-5
assert report["meshes"]["boot"]["height_faded_vertices"] == 4
assert abs((boot_fold.data[0].co - boot_basis.data[0].co).z - .02) < 1e-5
assert all((vertex.co - point).length == 0 for vertex, point in zip(body.data.vertices, original))
for invalid in ([1, 1], [2, 1], [0, float("nan")], [0], "0,1"):
    faded["outfit_clearance"]["height_fade"] = invalid
    try:
        exporter.apply_outfit_clearance(faded)
    except ValueError as error:
        assert "height_fade" in str(error)
    else:
        raise AssertionError(f"Invalid clearance height fade was accepted: {invalid}")
print("PASS: bounded garment and layer clearance, face samples, shape keys and unchanged shared body")

