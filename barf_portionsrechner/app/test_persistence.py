import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent))
import app as barf_app  # noqa: E402


class BarfPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.original_paths = (
            barf_app.DATA_DIR,
            barf_app.SHARE_DIR,
            barf_app.DATA_CONFIG_PATH,
            barf_app.SHARE_CONFIG_PATH,
            barf_app.DATA_VACATION_CONFIG_PATH,
            barf_app.SHARE_VACATION_CONFIG_PATH,
        )
        barf_app.DATA_DIR = root / "data"
        barf_app.SHARE_DIR = root / "share" / "Barf"
        barf_app.DATA_CONFIG_PATH = barf_app.DATA_DIR / "barf-portionsrechner-config.json"
        barf_app.SHARE_CONFIG_PATH = barf_app.SHARE_DIR / "barf-portionsrechner-config.json"
        barf_app.DATA_VACATION_CONFIG_PATH = barf_app.DATA_DIR / "barf-portionsrechner-urlaubsmodus-config.json"
        barf_app.SHARE_VACATION_CONFIG_PATH = barf_app.SHARE_DIR / "barf-portionsrechner-urlaubsmodus-config.json"

    def tearDown(self) -> None:
        (
            barf_app.DATA_DIR,
            barf_app.SHARE_DIR,
            barf_app.DATA_CONFIG_PATH,
            barf_app.SHARE_CONFIG_PATH,
            barf_app.DATA_VACATION_CONFIG_PATH,
            barf_app.SHARE_VACATION_CONFIG_PATH,
        ) = self.original_paths
        self.temp_dir.cleanup()

    def test_legacy_share_config_is_migrated_to_protected_data(self) -> None:
        legacy = copy.deepcopy(barf_app.DEFAULT_DOGS)
        legacy["dog_one"]["name"] = "Fienchen"
        legacy["dog_one"]["default_days"] = 14
        barf_app.SHARE_DIR.mkdir(parents=True)
        barf_app.SHARE_CONFIG_PATH.write_text(json.dumps(legacy), encoding="utf-8")

        loaded, message = barf_app.load_dogs_config()

        self.assertEqual("Fienchen", loaded["dog_one"]["name"])
        self.assertEqual(14, loaded["dog_one"]["default_days"])
        self.assertTrue(barf_app.DATA_CONFIG_PATH.exists())
        self.assertIn("geschützten App-Speicher", message)

    def test_save_always_writes_protected_data_before_share_copy(self) -> None:
        dogs = copy.deepcopy(barf_app.DEFAULT_DOGS)
        dogs["dog_two"]["name"] = "Kalle"
        barf_app.SHARE_DIR.mkdir(parents=True)

        ok, notice = barf_app.save_dogs_config(dogs)

        self.assertTrue(ok)
        self.assertEqual("", notice)
        stored = json.loads(barf_app.DATA_CONFIG_PATH.read_text(encoding="utf-8"))
        shared = json.loads(barf_app.SHARE_CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual("Kalle", stored["dog_two"]["name"])
        self.assertEqual(stored, shared)

    def test_newer_protected_copy_wins_over_stale_share_copy(self) -> None:
        barf_app.SHARE_DIR.mkdir(parents=True)
        old_copy = copy.deepcopy(barf_app.DEFAULT_DOGS)
        old_copy["dog_one"]["name"] = "Alt"
        new_copy = copy.deepcopy(barf_app.DEFAULT_DOGS)
        new_copy["dog_one"]["name"] = "Neu"
        barf_app._write_config(barf_app.SHARE_CONFIG_PATH, old_copy)
        barf_app._write_config(barf_app.DATA_CONFIG_PATH, new_copy)
        os.utime(barf_app.SHARE_CONFIG_PATH, (1, 1))

        loaded, _ = barf_app.load_dogs_config()

        self.assertEqual("Neu", loaded["dog_one"]["name"])


if __name__ == "__main__":
    unittest.main()
