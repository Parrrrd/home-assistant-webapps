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


if __name__ == "__main__":
    unittest.main()
