"""Run with Blender --background --factory-startup --python-exit-code 1 --python this_file."""
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'blender'))
from rebuild_recovered_wings import match_materials


original = bpy.data.materials.new('o01_m_hane')
outfit = bpy.data.materials.new('BODY_01__hane_o01_m_hane')
assert match_materials([original], [outfit]) == [outfit]

a = bpy.data.materials.new('wing_a')
b = bpy.data.materials.new('wing_b')
recovered_a = bpy.data.materials.new('BODY_01__wing_a')
recovered_b = bpy.data.materials.new('BODY_01__wing_b')
assert match_materials([a, b], [recovered_b, recovered_a]) == [recovered_a, recovered_b]

for imported, recovered in [([a], [recovered_a, recovered_b]),
                            ([a, a], [recovered_a, recovered_b]),
                            ([a, b], [recovered_a, recovered_a]),
                            ([None], [recovered_a])]:
    try:
        match_materials(imported, recovered)
    except ValueError:
        pass
    else:
        raise AssertionError('Accepted missing, ambiguous or incompatible material slots')
print('Wing material fixtures passed: outfit alias, slot order and four rejection cases')
