import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as manager


class CrossPlatformSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patches = [
            patch.object(manager, "ADS_DIR", root / "ads"),
            patch.object(manager, "IMAGES_DIR", root / "images"),
            patch.object(manager, "APP_STATE", root / "state.json"),
            patch.object(manager, "VINTED_SOLD_ACTION_INBOX_DIR", root / "vinted-to-ka"),
            patch.object(manager, "VINTED_DELETE_ACTION_INBOX_DIR", root / "ka-to-vinted"),
        ]
        for item in self.patches:
            item.start()
        manager.ADS_DIR.mkdir(parents=True)
        with manager._cross_platform_terminal_lock:
            manager._cross_platform_terminal_slugs.clear()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def _write_linked_ad(self):
        manager._write_yaml_file(manager._ad_yaml_path("bike"), {"title": "Fahrrad", "id": "ka-1"})
        state = {"ads": {"bike": {
            "account_id": "main",
            "vinted_transfer_source_id": "kleinanzeigen:bike",
            "vinted_transfer_status": "imported",
            "vinted_draft_id": "vinted-1",
        }}}
        manager._save_state(state)
        return state

    def test_vinted_sale_action_deletes_only_exact_linked_ka_ad(self):
        self._write_linked_ad()
        path = manager.VINTED_SOLD_ACTION_INBOX_DIR / "sold.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "action": "vinted_sold_cleanup", "source_platform": "vinted",
            "source_slug": "bike", "source_id": "kleinanzeigen:bike", "vinted_draft_id": "vinted-1",
        }), "utf-8")
        with patch.object(manager, "_sync_vinted_transfer_receipts", return_value=False), patch.object(
            manager, "_direct_delete_remote", return_value="bike"
        ) as remote_delete, patch.object(manager, "_notify_primary_critical") as notify:
            manager._process_vinted_sold_cleanup(path)

        remote_delete.assert_called_once_with("main", "ka-1", sold=False)
        self.assertFalse(path.exists())
        self.assertTrue(manager._is_cross_platform_terminal("bike"))
        with manager._cross_platform_terminal_lock:
            manager._cross_platform_terminal_slugs.clear()
        self.assertTrue(manager._is_cross_platform_terminal("bike"))
        notify.assert_called_once_with(
            "Vinted · Artikel verkauft",
            "Artikel: Fahrrad\nDie Anzeige wurde bei Vinted und Kleinanzeigen gelöscht.",
            click_url=manager.PUBLIC_BASE_URL,
        )

    def test_terminal_cross_platform_delete_is_never_enqueued_again_for_republish(self):
        self._write_linked_ad()
        manager._mark_cross_platform_terminal("bike", "Vinted-Verkauf bestätigt")

        self.assertTrue(manager._is_cross_platform_terminal("bike"))
        source = Path(manager.__file__).read_text("utf-8")
        self.assertIn("if _is_cross_platform_terminal(slug):", source)
        self.assertIn("Neu-Veröffentlichen beendet: Anzeige wurde plattformübergreifend gelöscht.", source)

    def test_cross_platform_delete_push_is_critical_and_silent_for_primary(self):
        with patch.object(manager, "_call_notify_service", return_value=(True, "ok")) as notify:
            ok, _detail = manager._notify_primary_critical("Titel", "Text", "/live")
        self.assertTrue(ok)
        _service, _title, _message = notify.call_args.args[:3]
        self.assertEqual((_title, _message), ("Titel", "Text"))
        self.assertEqual(notify.call_args.kwargs["critical"], True)

    def test_ka_both_delete_queues_exact_vinted_draft_id(self):
        state = self._write_linked_ad()
        self.assertTrue(manager._queue_vinted_delete_for_kleinanzeigen("bike", state))

        actions = list(manager.VINTED_DELETE_ACTION_INBOX_DIR.glob("*.json"))
        self.assertEqual(len(actions), 1)
        payload = json.loads(actions[0].read_text("utf-8"))
        self.assertEqual(payload["action"], "kleinanzeigen_delete_cleanup")
        self.assertEqual(payload["source_slug"], "bike")
        self.assertEqual(payload["vinted_draft_id"], "vinted-1")

    def test_mismatched_vinted_draft_id_is_rejected_before_delete(self):
        self._write_linked_ad()
        path = manager.VINTED_SOLD_ACTION_INBOX_DIR / "wrong.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "action": "vinted_sold_cleanup", "source_platform": "vinted",
            "source_slug": "bike", "source_id": "kleinanzeigen:bike", "vinted_draft_id": "other-draft",
        }), "utf-8")
        with patch.object(manager, "_sync_vinted_transfer_receipts", return_value=False), patch.object(manager, "_direct_delete_remote") as remote_delete:
            with self.assertRaises(ValueError):
                manager._process_vinted_sold_cleanup(path)
        remote_delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
