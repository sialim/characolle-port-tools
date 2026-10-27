import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


GMOD = Path(__file__).resolve().parents[1] / "gmod"
sys.path.insert(0, str(GMOD))
from build_gmod import material_entries


class QcGenerationTests(unittest.TestCase):
    def generate(self, count, *extra, flexes=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        groups = [{"name": f"piece_{i}"} for i in range(count)]
        (root / "manifest.json").write_text(json.dumps({"character": "Fixture", "bodygroups": groups}))
        if flexes is not None:
            (root / "flexes.json").write_text(json.dumps(flexes))
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

    def test_head_compiles_facial_rules_and_linked_lashes(self):
        result, qc = self.generate(1, flexes=["MeBaseToji", "NamidaBacetoji", "KuchiAkiA"])
        self.assertEqual(result.returncode, 0, result.stderr)
        text = qc.read_text()
        self.assertIn('$model "head" "head.dmx" {\n', text)
        self.assertIn('%KuchiAkiA = KuchiAkiA', text)
        self.assertIn('%NamidaBacetoji = NamidaBacetoji + MeBaseToji', text)


if __name__ == "__main__":
    unittest.main()
