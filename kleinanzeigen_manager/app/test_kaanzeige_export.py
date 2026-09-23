import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import app as manager


class KaanzeigeExportTests(unittest.TestCase):
    def test_export_is_import_compatible_and_preserves_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            ads_dir = data_dir / "ads"
            images_dir = data_dir / "images"
            app_state = data_dir / "app-state.json"
            slug = "alte-sammelanzeige"
            image_dir = images_dir / slug
            image_dir.mkdir(parents=True)
            ads_dir.mkdir(parents=True)

            first_bytes = b"PNG-original-\x00\x01\x02"
            second_bytes = b"JPEG-original-\xff\xd8\xff\xd9"
            (image_dir / "zweitbild.png").write_bytes(first_bytes)
            (image_dir / "erstbild.jpg").write_bytes(second_bytes)

            ad = {
                "active": True,
                "type": "OFFER",
                "title": "Mäntel & Schuhe – Größe 44",
                "description": "Originalbeschreibung mit Umlauten: äöü ß.",
                "price": 42.5,
                "price_type": "NEGOTIABLE",
                "category": "Mode & Beauty",
                "folder": "Sammelanzeigen",
                "shipping_type": "SHIPPING",
                "shipping_costs": 4.5,
                "shipping_options": ["Hermes_S"],
                "contact": {"name": "Testkontakt"},
                "location": "49000 Testort",
                "republication_interval": 7,
                "republish_price_reduction_enabled": True,
                "republish_price_reduction_days": 10,
                "republish_price_drop": 2.5,
                "republish_min_price": 30,
                "images": [
                    f"../images/{slug}/zweitbild.png",
                    f"../images/{slug}/erstbild.jpg",
                ],
                # Even if legacy data contains state-like keys, they are not exported.
                "price_reduction_anchor_at": "2026-09-01T00:00:00+00:00",
                "last_price_reduction_at": "2026-09-02T00:00:00+00:00",
                "price_reduction_count": 3,
            }

            defaults = {
                "contact_name": "",
                "default_location": "",
                "republish_days": manager.REPUBLISH_INTERVAL,
            }
            with patch.object(manager, "DATA_DIR", data_dir), patch.object(
                manager, "ADS_DIR", ads_dir
            ), patch.object(manager, "IMAGES_DIR", images_dir), patch.object(
                manager, "APP_STATE", app_state
            ), patch.object(manager, "_get_settings", return_value=defaults):
                manager._write_yaml_file(manager._ad_yaml_path(slug), ad)
                archive = manager._build_kaanzeige_export(slug)
                archive_bytes = archive.getvalue()

                self.assertTrue(zipfile.is_zipfile(io.BytesIO(archive_bytes)))
                with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as zf:
                    self.assertIn("anzeige.json", zf.namelist())
                    payload = json.loads(zf.read("anzeige.json").decode("utf-8"))
                    self.assertEqual(payload["format"], "kleinanzeigen-manager-import")
                    self.assertEqual(payload["version"], 1)
                    self.assertEqual(payload["title"], ad["title"])
                    self.assertEqual(payload["description"], ad["description"])
                    self.assertEqual(payload["price"], ad["price"])
                    self.assertEqual(payload["price_type"], ad["price_type"])
                    self.assertEqual(payload["category"], ad["category"])
                    self.assertEqual(payload["folder"], ad["folder"])
                    self.assertEqual(payload["ad_type"], ad["type"])
                    self.assertEqual(payload["shipping_type"], ad["shipping_type"])
                    self.assertEqual(payload["shipping_costs"], ad["shipping_costs"])
                    self.assertEqual(payload["shipping_options"], ad["shipping_options"])
                    self.assertEqual(payload["contact_name"], ad["contact"]["name"])
                    self.assertEqual(payload["location"], ad["location"])
                    self.assertEqual(payload["republish_days"], 7)
                    self.assertTrue(payload["republish_price_reduction_enabled"])
                    self.assertEqual(payload["republish_price_reduction_days"], 10)
                    self.assertEqual(payload["republish_price_drop"], 2.5)
                    self.assertEqual(payload["republish_min_price"], 30)
                    self.assertTrue(payload["active"])
                    self.assertEqual(payload["images"], ["bilder/01.png", "bilder/02.jpg"])
                    self.assertEqual(zf.read("bilder/01.png"), first_bytes)
                    self.assertEqual(zf.read("bilder/02.jpg"), second_bytes)
                    self.assertEqual(zf.getinfo("bilder/01.png").compress_type, zipfile.ZIP_STORED)
                    self.assertEqual(zf.getinfo("bilder/02.jpg").compress_type, zipfile.ZIP_STORED)
                    for image_path in payload["images"]:
                        self.assertFalse(Path(image_path).is_absolute())
                        self.assertNotIn("..", Path(image_path).parts)
                        self.assertIn(image_path, zf.namelist())
                    for state_key in (
                        "price_reduction_anchor_at",
                        "last_price_reduction_at",
                        "price_reduction_count",
                    ):
                        self.assertNotIn(state_key, payload)

                    normalized = manager._normalize_import_data(payload)
                    _files, image_names = manager._archive_image_names(zf, payload)
                    self.assertEqual(image_names, payload["images"])
                    self.assertEqual(normalized["ad_type"], "OFFER")
                    self.assertEqual(normalized["republish_days"], 7)
                    self.assertTrue(normalized["republish_price_reduction_enabled"])

                package = data_dir / "roundtrip.kaanzeige"
                package.write_bytes(archive_bytes)
                result = manager._import_single_package(package)
                self.assertFalse(package.exists())
                imported = manager._read_ad_yaml(result["slug"])
                self.assertEqual(imported["title"], ad["title"])
                self.assertEqual(imported["description"], ad["description"])
                self.assertEqual(imported["type"], ad["type"])
                self.assertEqual(imported["folder"], ad["folder"])
                self.assertEqual(imported["shipping_options"], ad["shipping_options"])
                self.assertEqual(imported["contact"]["name"], ad["contact"]["name"])
                self.assertEqual(imported["location"], ad["location"])
                self.assertEqual(imported["republication_interval"], 7)
                self.assertTrue(imported["republish_price_reduction_enabled"])
                imported_image_names = manager._list_ad_images(result["slug"])
                self.assertEqual(len(imported_image_names), 2)
                imported_dir = manager._ad_images_dir(result["slug"])
                self.assertEqual((imported_dir / imported_image_names[0]).read_bytes(), first_bytes)
                self.assertEqual((imported_dir / imported_image_names[1]).read_bytes(), second_bytes)

    def test_legacy_ad_without_image_list_uses_import_defaults_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            ads_dir = data_dir / "ads"
            images_dir = data_dir / "images"
            app_state = data_dir / "app-state.json"
            ads_dir.mkdir(parents=True)
            slug = "alte-anzeige"
            legacy_ad = {
                "title": "Ältere Anzeige",
                "description": "Bestehender Datensatz ohne neue optionale Felder.",
                "price": 12,
                "price_type": "FIXED",
                "type": "OFFER",
                "shipping_type": "PICKUP",
                "republication_interval": "ungueltig",
                "active": "false",
            }
            defaults = {
                "contact_name": "",
                "default_location": "",
                "republish_days": manager.REPUBLISH_INTERVAL,
            }
            with patch.object(manager, "DATA_DIR", data_dir), patch.object(
                manager, "ADS_DIR", ads_dir
            ), patch.object(manager, "IMAGES_DIR", images_dir), patch.object(
                manager, "APP_STATE", app_state
            ), patch.object(manager, "_get_settings", return_value=defaults):
                manager._write_yaml_file(manager._ad_yaml_path(slug), legacy_ad)
                archive = manager._build_kaanzeige_export(slug)
                with zipfile.ZipFile(io.BytesIO(archive.getvalue()), "r") as zf:
                    payload = json.loads(zf.read("anzeige.json").decode("utf-8"))
                    self.assertEqual(payload["images"], [])
                    self.assertEqual(payload["republish_days"], manager.REPUBLISH_INTERVAL)
                    self.assertFalse(payload["active"])
                    manager._normalize_import_data(payload)
                    _files, image_names = manager._archive_image_names(zf, payload)
                    self.assertEqual(image_names, [])


if __name__ == "__main__":
    unittest.main()
