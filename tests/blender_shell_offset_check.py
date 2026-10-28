"""Check seam continuity, Source-unit distances and relative garment keys."""
import importlib.util
from pathlib import Path
import bpy

spec = importlib.util.spec_from_file_location(
    "export_source", Path(__file__).resolve().parents[1] / "gmod/export_source.py")
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)
bpy.ops.wm.read_factory_settings(use_empty=True)
mesh = bpy.data.meshes.new("glove")
mesh.from_pydata([(0, 0, 0), (0, 1, 0), (0, 1, 1), (0, 0, 1),
                  (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
                 [], [(0, 1, 2, 3), (4, 5, 6, 7)])
glove = bpy.data.objects.new("glove", mesh)
bpy.context.collection.objects.link(glove)
glove.scale = (2, 3, 4)
basis = glove.shape_key_add(name="Basis")
fold = glove.shape_key_add(name="Fold")
fold.data[1].co.y += .02
fold.value = 0
bpy.context.view_layer.update()
before = [glove.matrix_world @ vertex.co for vertex in basis.data]
manifest = {"bodygroups": [{"mesh": {"name": "glove"}}],
            "outfit_shell_offset": {"meshes": ["glove"], "distance": .04}}
report = exporter.apply_outfit_shell_offset(manifest)
after = [glove.matrix_world @ vertex.co for vertex in basis.data]
assert all(abs((a - b).length - .04) < 1e-6 for a, b in zip(after, before))
assert (after[0] - after[4]).length < 1e-6
assert (after[1] - after[7]).length < 1e-6
assert abs((fold.data[1].co - basis.data[1].co).y - .02) < 1e-6
assert report["meshes"]["glove"]["moved_vertices"] == 8
assert abs(report["meshes"]["glove"]["maximum_correction"] - .04) < 1e-6
fold.value = 1
bpy.context.view_layer.update()
try:
    exporter.apply_outfit_shell_offset(manifest)
except ValueError as error:
    assert "unposed" in str(error)
else:
    raise AssertionError("A posed garment was accepted")
fold.value = 0
for distance in (0, -.04, .26, float("nan")):
    manifest["outfit_shell_offset"]["distance"] = distance
    try:
        exporter.apply_outfit_shell_offset(manifest)
    except ValueError:
        pass
    else:
        raise AssertionError("An invalid shell distance was accepted")
manifest["outfit_shell_offset"].update(distance=.04, meshes=["body"])
try:
    exporter.apply_outfit_shell_offset(manifest)
except ValueError as error:
    assert "selected outfit" in str(error)
else:
    raise AssertionError("A body mesh was accepted as clothing")
assert exporter.apply_outfit_shell_offset({}) == {}
print("PASS: smooth garment seams, world-space offset distance, relative keys and input guards")
