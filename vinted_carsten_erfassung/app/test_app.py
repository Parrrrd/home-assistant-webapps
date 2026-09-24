import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("app.py")
SPEC = importlib.util.spec_from_file_location("carsten_app", MODULE_PATH)
carsten_app = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(carsten_app)


class RequestFormatTests(unittest.TestCase):
    def test_request_has_stable_vintake_shape_without_category(self):
        with carsten_app.app.test_request_context("/", method="POST", data={}):
            payload = carsten_app.build_request("sample123", [{"filename": "photo-01.jpg", "position": 1}])
        self.assertEqual(payload["format"], "vintake")
        self.assertEqual(payload["version"], "1.0")
        self.assertEqual(payload["item"]["category"], "")
        self.assertEqual(payload["item"]["category_id"], "")
        self.assertEqual(payload["item"]["photos"][0]["position"], 1)

    def test_archive_contains_request_and_images(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "images").mkdir()
            (folder / "images" / "photo-01.jpg").write_bytes(b"not-a-real-image")
            (folder / "request.json").write_text(json.dumps({"format": "vintake"}), encoding="utf-8")
            archive = carsten_app.create_archive(folder, "carsten-vinted-test.vintake.zip")
            import zipfile
            with zipfile.ZipFile(archive) as bundle:
                self.assertEqual(sorted(bundle.namelist()), ["images/photo-01.jpg", "request.json"])

    def test_submit_persists_a_waiting_package_before_drive_delivery(self):
        with tempfile.TemporaryDirectory() as temporary:
            original_data_dir = carsten_app.DATA_DIR
            original_outbox_dir = carsten_app.OUTBOX_DIR
            original_options_file = carsten_app.OPTIONS_FILE
            try:
                carsten_app.DATA_DIR = Path(temporary)
                carsten_app.OUTBOX_DIR = carsten_app.DATA_DIR / "outbox"
                carsten_app.OPTIONS_FILE = carsten_app.DATA_DIR / "options.json"
                response = carsten_app.app.test_client().post(
                    "/submit",
                    data={"photos": (io.BytesIO(b"photo"), "title.jpg", "image/jpeg")},
                    content_type="multipart/form-data",
                    follow_redirects=False,
                )
                self.assertEqual(response.status_code, 302)
                submissions = list(carsten_app.OUTBOX_DIR.iterdir())
                self.assertEqual(len(submissions), 1)
                state = json.loads((submissions[0] / "state.json").read_text(encoding="utf-8"))
                self.assertEqual(state["state"], "waiting")
                self.assertTrue((submissions[0] / state["archive"]).is_file())
            finally:
                carsten_app.DATA_DIR = original_data_dir
                carsten_app.OUTBOX_DIR = original_outbox_dir
                carsten_app.OPTIONS_FILE = original_options_file

    def test_index_has_gallery_upload_and_default_automation(self):
        response = carsten_app.app.test_client().get("/")
        html = response.get_data(as_text=True)
        self.assertIn("Carstens Vinted Importeur", html)
        self.assertIn("Foto hinzufügen", html)
        self.assertIn('id="photos"', html)
        self.assertIn('accept="image/*" multiple', html)
        self.assertNotIn('capture=', html)
        self.assertIn("className = 'photo-remove'", html)
        self.assertIn('new DataTransfer()', html)
        self.assertIn('name="relist_enabled" data-toggle="relist" checked', html)
        self.assertIn('name="relist_interval_days" inputmode="numeric" value="7"', html)
        self.assertIn('name="reduction_enabled" data-toggle="reduction" checked', html)
        self.assertNotIn("Fotos sind Pflicht. Alles andere kannst du leer lassen.", html)
        self.assertNotIn("Titelbild", html)

    def test_heic_photo_is_accepted(self):
        with carsten_app.app.test_request_context(
            "/",
            method="POST",
            data={"photos": (io.BytesIO(b"photo"), "image.heic", "image/heic")},
            content_type="multipart/form-data",
        ):
            files = carsten_app.photo_files()
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].filename, "image.heic")

    def test_multiple_photos_are_preserved_in_one_submission(self):
        with carsten_app.app.test_request_context(
            "/",
            method="POST",
            data={
                "photos": [
                    (io.BytesIO(b"photo-one"), "one.jpg", "image/jpeg"),
                    (io.BytesIO(b"photo-two"), "two.jpg", "image/jpeg"),
                    (io.BytesIO(b"photo-three"), "three.jpg", "image/jpeg"),
                ]
            },
            content_type="multipart/form-data",
        ):
            files = carsten_app.photo_files()
        self.assertEqual([file.filename for file in files], ["one.jpg", "two.jpg", "three.jpg"])

    def test_photo_picker_keeps_previous_inputs_outside_clickable_label(self):
        response = carsten_app.app.test_client().get("/")
        html = response.get_data(as_text=True)
        self.assertIn('id="stored-photo-inputs" hidden', html)
        self.assertIn('data-photo-picker data-camera-picker', html)
        self.assertIn('data-photo-picker data-library-picker', html)
        self.assertIn("storedPhotoInputs.append(input)", html)

    def test_multiple_photos_are_accepted_together(self):
        with carsten_app.app.test_request_context(
            "/",
            method="POST",
            data={
                "photos": [
                    (io.BytesIO(b"one"), "one.jpg", "image/jpeg"),
                    (io.BytesIO(b"two"), "two.jpg", "image/jpeg"),
                    (io.BytesIO(b"three"), "three.jpg", "image/jpeg"),
                ]
            },
            content_type="multipart/form-data",
        ):
            files = carsten_app.photo_files()
        self.assertEqual([file.filename for file in files], ["one.jpg", "two.jpg", "three.jpg"])


if __name__ == "__main__":
    unittest.main()
