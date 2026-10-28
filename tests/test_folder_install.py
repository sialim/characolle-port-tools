import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gmod"))
from install_verified_addons import approved_models, catalog_script, merge_assets


class FolderInstallTests(unittest.TestCase):
    def test_catalog_does_not_depend_on_package_autoruns(self):
        inventory = {"main": [{"model": "models/characolle/kud.mdl"}],
                     "previews": [{"model": "models/characolle/rin.mdl"}]}
        script = catalog_script(inventory)
        self.assertIn("list.Set('CharaColleModels'", script)
        self.assertNotIn("list.Get(", script)
        self.assertIn("file.Exists(model,'GAME')", script)
        self.assertIn("models/characolle/kud.mdl", script)
        self.assertIn("models/characolle/rin.mdl", script)

    def test_checks_package_identity_and_rejects_duplicates(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "model.gma"
            package.write_bytes(b"fixture")
            item = {"model": "models/characolle/kud.mdl", "package": str(package),
                    "sha256": hashlib.sha256(b"fixture").hexdigest()}
            self.assertEqual(len(approved_models({"main": [item], "previews": []})), 1)
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                approved_models({"main": [item], "previews": [item]})
            package.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                approved_models({"main": [item], "previews": []})

    def test_conflicting_shared_material_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, output = Path(temporary) / "source", Path(temporary) / "output"
            material = source / "materials/models/cloth.vmt"
            material.parent.mkdir(parents=True)
            material.write_bytes(b"first")
            merge_assets(source, output)
            material.write_bytes(b"second")
            with self.assertRaisesRegex(ValueError, "Conflicting"):
                merge_assets(source, output)
            self.assertEqual((output / "materials/models/cloth.vmt").read_bytes(), b"first")


if __name__ == "__main__":
    unittest.main()
