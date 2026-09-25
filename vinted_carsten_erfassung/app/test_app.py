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
        self.assertIn('selectedPhotos.push(...incoming.slice(0, freeSlots))', html)
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

    def test_drive_configuration_uses_shared_kleinanzeigen_credentials_by_default(self):
        with tempfile.TemporaryDirectory() as data_tmp, tempfile.TemporaryDirectory() as share_tmp:
            original_options = carsten_app.OPTIONS_FILE
            original_shared = carsten_app.SHARED_CREDENTIAL_FILE
            original_default = carsten_app.DEFAULT_CREDENTIAL_FILE
            try:
                carsten_app.OPTIONS_FILE = Path(data_tmp) / "options.json"
                carsten_app.SHARED_CREDENTIAL_FILE = Path(share_tmp) / "google-drive-service-account.json"
                carsten_app.DEFAULT_CREDENTIAL_FILE = carsten_app.SHARED_CREDENTIAL_FILE
                carsten_app.SHARED_CREDENTIAL_FILE.write_text("{}", encoding="utf-8")
                carsten_app.OPTIONS_FILE.write_text(
                    json.dumps({"drive_folder_id": "folder_123"}),
                    encoding="utf-8",
                )
                folder_id, credentials = carsten_app.drive_configuration()
                self.assertEqual(folder_id, "folder_123")
                self.assertEqual(credentials, carsten_app.SHARED_CREDENTIAL_FILE.resolve())
            finally:
                carsten_app.OPTIONS_FILE = original_options
                carsten_app.SHARED_CREDENTIAL_FILE = original_shared
                carsten_app.DEFAULT_CREDENTIAL_FILE = original_default

    def test_drive_configuration_migrates_old_config_default_to_shared_file(self):
        with tempfile.TemporaryDirectory() as data_tmp, tempfile.TemporaryDirectory() as config_tmp, tempfile.TemporaryDirectory() as share_tmp:
            original_options = carsten_app.OPTIONS_FILE
            original_config_dir = carsten_app.CONFIG_DIR
            original_shared = carsten_app.SHARED_CREDENTIAL_FILE
            try:
                carsten_app.OPTIONS_FILE = Path(data_tmp) / "options.json"
                carsten_app.CONFIG_DIR = Path(config_tmp)
                carsten_app.SHARED_CREDENTIAL_FILE = Path(share_tmp) / "google-drive-service-account.json"
                carsten_app.SHARED_CREDENTIAL_FILE.write_text("{}", encoding="utf-8")
                carsten_app.OPTIONS_FILE.write_text(
                    json.dumps({
                        "drive_folder_id": "folder_123",
                        "drive_service_account_file": "/config/drive-service-account.json",
                    }),
                    encoding="utf-8",
                )
                folder_id, credentials = carsten_app.drive_configuration()
                self.assertEqual(folder_id, "folder_123")
                self.assertEqual(credentials, carsten_app.SHARED_CREDENTIAL_FILE.resolve())
            finally:
                carsten_app.OPTIONS_FILE = original_options
                carsten_app.CONFIG_DIR = original_config_dir
                carsten_app.SHARED_CREDENTIAL_FILE = original_shared

    def test_drive_configuration_keeps_existing_app_specific_config_file(self):
        with tempfile.TemporaryDirectory() as data_tmp, tempfile.TemporaryDirectory() as config_tmp, tempfile.TemporaryDirectory() as share_tmp:
            original_options = carsten_app.OPTIONS_FILE
            original_config_dir = carsten_app.CONFIG_DIR
            original_shared = carsten_app.SHARED_CREDENTIAL_FILE
            try:
                carsten_app.OPTIONS_FILE = Path(data_tmp) / "options.json"
                carsten_app.CONFIG_DIR = Path(config_tmp)
                carsten_app.SHARED_CREDENTIAL_FILE = Path(share_tmp) / "google-drive-service-account.json"
                config_file = carsten_app.CONFIG_DIR / "drive-service-account.json"
                config_file.write_text("{}", encoding="utf-8")
                carsten_app.OPTIONS_FILE.write_text(
                    json.dumps({
                        "drive_folder_id": "folder_123",
                        "drive_service_account_file": "/config/drive-service-account.json",
                    }),
                    encoding="utf-8",
                )
                folder_id, credentials = carsten_app.drive_configuration()
                self.assertEqual(folder_id, "folder_123")
                self.assertEqual(credentials, config_file.resolve())
            finally:
                carsten_app.OPTIONS_FILE = original_options
                carsten_app.CONFIG_DIR = original_config_dir
                carsten_app.SHARED_CREDENTIAL_FILE = original_shared

    def test_drive_configuration_rejects_other_share_credentials(self):
        with tempfile.TemporaryDirectory() as data_tmp, tempfile.TemporaryDirectory() as config_tmp, tempfile.TemporaryDirectory() as share_tmp:
            original_options = carsten_app.OPTIONS_FILE
            original_config_dir = carsten_app.CONFIG_DIR
            original_shared = carsten_app.SHARED_CREDENTIAL_FILE
            try:
                carsten_app.OPTIONS_FILE = Path(data_tmp) / "options.json"
                carsten_app.CONFIG_DIR = Path(config_tmp)
                carsten_app.SHARED_CREDENTIAL_FILE = Path(share_tmp) / "Kleinanzeigen" / "google-drive-service-account.json"
                carsten_app.OPTIONS_FILE.write_text(
                    json.dumps({
                        "drive_folder_id": "folder_123",
                        "drive_service_account_file": str(Path(share_tmp) / "Other" / "credentials.json"),
                    }),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(RuntimeError, "Kleinanzeigen"):
                    carsten_app.drive_configuration()
            finally:
                carsten_app.OPTIONS_FILE = original_options
                carsten_app.CONFIG_DIR = original_config_dir
                carsten_app.SHARED_CREDENTIAL_FILE = original_shared

    def test_config_maps_share_read_only_and_defaults_to_existing_credentials(self):
        config_text = (MODULE_PATH.parent.parent / "config.yaml").read_text(encoding="utf-8")
        self.assertIn("type: addon_config", config_text)
        self.assertIn("type: share", config_text)
        self.assertGreaterEqual(config_text.count("read_only: true"), 2)
        self.assertIn(
            'drive_service_account_file: "/share/Kleinanzeigen/google-drive-service-account.json"',
            config_text,
        )
        self.assertNotIn("homeassistant_config", config_text)
        self.assertNotIn("all_addon_configs", config_text)



if __name__ == "__main__":
    unittest.main()
