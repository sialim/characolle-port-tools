import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


GMOD = Path(__file__).resolve().parents[1] / "gmod"
sys.path.insert(0, str(GMOD))
from build_gmod import material_entries, source_texture_stem
from bundle_manifest import bundle


class QcGenerationTests(unittest.TestCase):
    def generate(self, count, *extra, flexes=None, attachments=None, defaults=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        groups = [{"name": f"piece_{i}"} for i in range(count)]
        for group, visible in zip(groups, defaults or []):
            group["default_visible"] = visible
        (root / "manifest.json").write_text(json.dumps({"character": "Fixture", "bodygroups": groups}))
        if flexes is not None:
            (root / "flexes.json").write_text(json.dumps(flexes))
        if attachments is not None:
            (root / "attachments.json").write_text(json.dumps(attachments))
        for name in ["base.dmx", "head.dmx", *[f"bg_{g['name']}.dmx" for g in groups]]:
            (root / name).touch()
        result = subprocess.run([sys.executable, str(GMOD / "generate_qc.py"), "--manifest", str(root / "manifest.json"),
                                 "--export", str(root), "--output", str(root / "model.qc"),
                                 "--material-path", "models/fixture", *extra], capture_output=True, text=True)
        return result, root / "model.qc"

    def test_rejects_overflow_before_writing_qc(self):
        result, qc = self.generate(32)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("32-bit", result.stderr)
        self.assertFalse(qc.exists())

    def test_largest_safe_binary_table_and_clothed_default(self):
        result, qc = self.generate(31, "--outfit-visible")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('studio "bg_piece_0.dmx"\n    blank', qc.read_text())

    def test_distinct_layer_materials_keep_exported_names(self):
        manifest = {"base_objects": [{"materials": [{"name": "BODY_02__skin", "images": ["base"]}]}],
                    "bodygroups": [{"mesh": {"materials": [{"name": "BODY_00__skin", "images": ["outfit"]}]}}]}
        entries = material_entries(manifest)
        self.assertEqual(set(entries), {"body_02__skin", "body_00__skin"})
        self.assertNotEqual(entries["body_02__skin"]["images"], entries["body_00__skin"]["images"])

    def test_alternative_can_start_hidden_in_clothed_build(self):
        result, qc = self.generate(2, "--outfit-visible", defaults=[True, False])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('studio "bg_piece_0.dmx"\n    blank', qc.read_text())
        self.assertIn('blank\n    studio "bg_piece_1.dmx"', qc.read_text())

    def test_explicit_visibility_overrides_hidden_global_default(self):
        result, qc = self.generate(1, defaults=[True])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('studio "bg_piece_0.dmx"\n    blank', qc.read_text())

    def test_invalid_visibility_does_not_silently_enable_a_variant(self):
        result, qc = self.generate(1, "--outfit-visible", defaults=["false"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('must be a boolean', result.stderr)
        self.assertFalse(qc.exists())

    def test_head_compiles_facial_rules_and_linked_lashes(self):
        result, qc = self.generate(1, flexes=["MeBaseToji", "NamidaBacetoji", "KuchiAkiA"])
        self.assertEqual(result.returncode, 0, result.stderr)
        text = qc.read_text()
        self.assertIn('$model "head" "head.dmx" {\n', text)
        self.assertIn('%KuchiAkiA = KuchiAkiA', text)
        self.assertIn('%NamidaBacetoji = NamidaBacetoji + MeBaseToji', text)
        self.assertIn('    noautodmxrules\n', text)
        self.assertIn('flexcontroller phoneme range 0 1 "MeBaseToji"', text)

    def test_pupil_submeshes_share_one_controller(self):
        result, qc = self.generate(0, flexes=["PupilSmall", "PupilSmalleyeL1", "PupilSmalleyeR0"])
        self.assertEqual(result.returncode, 0, result.stderr)
        text = qc.read_text()
        self.assertEqual(text.count("flexcontroller "), 1)
        self.assertIn('%PupilSmalleyeL1 = PupilSmall', text)
        self.assertIn('%PupilSmalleyeR0 = PupilSmall', text)

    def test_eye_attachment_keeps_origin_and_rotation(self):
        data = {"eye_position": [0, -2, 53], "attachments": [{"name": "eyes", "bone": "head",
                "position": [1, 2, 3], "rotation": [-90, -90, 0]}]}
        result, qc = self.generate(0, attachments=data)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('$eyeposition -2 0 53', qc.read_text())
        self.assertIn('$attachment "eyes" "head" 1 2 3 rotate -90 -90 0', qc.read_text())

    def test_bundling_preserves_geometry_and_all_materials(self):
        meshes = [{"name": f"BODY_00__P_dou_{i}", "materials": [{"name": f"torso_{i}"}]} for i in range(12)]
        source = {"bodygroups": [{"name": f"00_p_dou_{i}", "layer": "00", "mesh": mesh} for i, mesh in enumerate(meshes)]}
        result = bundle(source, ["P_dou"])
        self.assertEqual(len(result["bodygroups"]), 1)
        self.assertEqual(result["bodygroups"][0]["meshes"], meshes)
        self.assertEqual(set(material_entries(result)), {f"torso_{i}" for i in range(12)})
        self.assertEqual(len(source["bodygroups"]), 12)

    def test_texture_names_cannot_be_interpreted_as_extensions(self):
        self.assertEqual(source_texture_stem("skin.bmp"), "skin")
        dotted = source_texture_stem("c00_01_10._kacyu.bmp")
        self.assertNotIn(".", dotted)
        self.assertNotEqual(dotted, source_texture_stem("c00_01_10__kacyu.bmp"))

    def test_outfit_fitting_is_explicit_and_preserves_shared_body(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = {"character": "Fixture", "scene": {"base_body_layer": "02"},
                      "base_objects": [{"name": "BODY_02__P_body_0"}],
                      "bodygroups": [{"name": name, "layer": "01", "mesh": {"name": name}}
                                     for name in ["shirt", "duplicate_skin"]]}
            (root / "source.json").write_text(json.dumps(source))
            command = [sys.executable, str(GMOD / "split_manifest.py"), "--input", str(root / "source.json"),
                       "--output", str(root / "outfit.json"), "--layer", "01",
                       "--exclude-mesh", "duplicate_skin", "--clearance-mesh", "shirt",
                       "--clearance-face-iterations", "8", "--clearance-subdivide", "1"]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            outfit = json.loads((root / "outfit.json").read_text())
            self.assertEqual(outfit["base_objects"], source["base_objects"])
            self.assertEqual([group["name"] for group in outfit["bodygroups"]], ["shirt"])
            self.assertEqual(outfit["outfit_clearance"]["meshes"], ["shirt"])
            self.assertEqual(outfit["outfit_clearance"]["face_iterations"], 8)
            self.assertEqual(outfit["outfit_clearance"]["subdivide"], 1)
            result = subprocess.run([*command, "--clearance-mesh", "missing"], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing", result.stderr)


if __name__ == "__main__":
    unittest.main()
