import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

os.environ.setdefault("VINTED_CARSTEN_DRIVE_ENABLED", "false")

import carsten_intake as intake


class CarstenIntakeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        intake.DATA_DIR = Path(self.tmp.name)
        intake.OUTBOX_DIR = intake.DATA_DIR / "outbox"
        intake.STATE_FILE = intake.DATA_DIR / "submissions.json"
        intake.app.config.update(TESTING=True)
        self.client = intake.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def _submit(self, **changes):
        data = {
            "notes": "Adidas Sneaker, selten getragen",
            "brand_hint": "Adidas",
            "size_hint": "44",
            "condition_notes": "Kleine Stelle hinten rechts",
            "price": "35",
            "renew_interval_days": "7",
            "price_reduction_enabled": "on",
            "price_reduction_days": "21",
            "price_drop": "3",
            "min_price": "23",
            "photos": (io.BytesIO(b"fake-jpeg"), "schuh.jpg"),
        }
        data.update(changes)
        return self.client.post("/submit", data=data, content_type="multipart/form-data", follow_redirects=False)

    def test_submission_creates_unedited_package_without_category(self):
        response = self._submit()
        self.assertEqual(response.status_code, 302)
        packages = list(intake.OUTBOX_DIR.glob("*.vintake.zip"))
        self.assertEqual(len(packages), 1)
        with zipfile.ZipFile(packages[0], "r") as archive:
            payload = json.loads(archive.read("request.json"))
            self.assertEqual(payload["format"], "vinted-carsten-intake")
            self.assertEqual(payload["status"], "unbearbeitet")
            self.assertEqual(payload["category"], "")
            self.assertEqual(payload["category_id"], "")
            self.assertEqual(payload["automation"]["renew_interval_days"], 7)
            self.assertEqual(payload["automation"]["price_reduction_days"], 21)
            self.assertEqual(payload["automation"]["price_drop"], 3.0)
            self.assertEqual(payload["automation"]["min_price"], 23.0)
            self.assertEqual(payload["images"][0]["file"], "images/01.jpg")

    def test_missing_photo_is_rejected(self):
        response = self.client.post(
            "/submit",
            data={"notes": "Test", "price": "10", "renew_interval_days": "7"},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("mindestens ein Foto", response.get_data(as_text=True))
        self.assertFalse(list(intake.OUTBOX_DIR.glob("*.zip")))

    def test_minimum_price_must_be_below_start_price(self):
        response = self._submit(min_price="35")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(list(intake.OUTBOX_DIR.glob("*.zip")))


if __name__ == "__main__":
    unittest.main()
