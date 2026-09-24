import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


APP_PATH = Path(__file__).with_name("app.py")
sys.path.insert(0, str(APP_PATH.parent))
SPEC = importlib.util.spec_from_file_location("finanzplanung_app_under_test", APP_PATH)
assert SPEC and SPEC.loader
finanz_app = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = finanz_app
SPEC.loader.exec_module(finanz_app)


class FinanzPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.original_paths = (
            finanz_app.DATA_DIR,
            finanz_app.SHARE_DIR,
            finanz_app.DATA_PATH,
            finanz_app.SHARE_PATH,
        )
        finanz_app.DATA_DIR = root / "data"
        finanz_app.SHARE_DIR = root / "share" / "Finanzen"
        finanz_app.DATA_PATH = finanz_app.DATA_DIR / "finanzplanung-data.json"
        finanz_app.SHARE_PATH = finanz_app.SHARE_DIR / "finanzplanung-data.json"

    def tearDown(self) -> None:
        (
            finanz_app.DATA_DIR,
            finanz_app.SHARE_DIR,
            finanz_app.DATA_PATH,
            finanz_app.SHARE_PATH,
        ) = self.original_paths
        self.temp_dir.cleanup()

    def test_legacy_share_data_is_migrated_before_it_is_used(self) -> None:
        legacy = finanz_app.deep_default_data()
        legacy["categories"] = ["Wohnen", "Legacy"]
        finanz_app.SHARE_DIR.mkdir(parents=True)
        finanz_app.SHARE_PATH.write_text(json.dumps(legacy), encoding="utf-8")

        loaded = finanz_app.load_data()

        self.assertIn("Legacy", loaded["categories"])
        self.assertTrue(finanz_app.DATA_PATH.exists())
        self.assertEqual(loaded, json.loads(finanz_app.DATA_PATH.read_text(encoding="utf-8")))

    def test_save_keeps_protected_data_when_share_mirror_is_unavailable(self) -> None:
        data = copy.deepcopy(finanz_app.deep_default_data())
        data["categories"] = ["Wohnen", "Gesichert"]

        finanz_app.save_data(data)

        stored = json.loads(finanz_app.DATA_PATH.read_text(encoding="utf-8"))
        self.assertIn("Gesichert", stored["categories"])
        self.assertTrue((finanz_app.DATA_DIR / "backups").exists())
        self.assertFalse(finanz_app.SHARE_PATH.exists())

    def test_data_copy_remains_authoritative_over_old_share_copy(self) -> None:
        protected = finanz_app.deep_default_data()
        protected["categories"] = ["Wohnen", "Aktuell"]
        old_share = finanz_app.deep_default_data()
        old_share["categories"] = ["Wohnen", "Alt"]
        finanz_app.DATA_DIR.mkdir(parents=True)
        finanz_app.SHARE_DIR.mkdir(parents=True)
        finanz_app.DATA_PATH.write_text(json.dumps(protected), encoding="utf-8")
        finanz_app.SHARE_PATH.write_text(json.dumps(old_share), encoding="utf-8")

        loaded = finanz_app.load_data()

        self.assertIn("Aktuell", loaded["categories"])
        self.assertNotIn("Alt", loaded["categories"])


if __name__ == "__main__":
    unittest.main()
