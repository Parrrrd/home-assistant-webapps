import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import app as manager


class RepublishTransactionTests(unittest.TestCase):
    def test_confirmed_delete_creates_publish_only_transaction_with_old_id(self):
        meta = {}
        manager._mark_republish_delete_success(meta, "old-42")

        transaction = meta["republish_transaction"]
        self.assertEqual(transaction["phase"], "publish_pending")
        self.assertEqual(transaction["old_remote_id"], "old-42")
        self.assertEqual(transaction["before_live_ids"], ["old-42"])

    def test_true_publish_failure_after_delete_retries_only_publish(self):
        state, meta = {"ads": {}}, {}
        manager._mark_republish_delete_success(meta, "old-42")

        with patch.object(manager, "_retry_time_iso", return_value="2030-01-01T00:00:00+00:00"):
            retry_at = manager._queue_publish_only_after_republish(state, "bike", meta, "publish rejected")

        self.assertEqual(retry_at, "2030-01-01T00:00:00+00:00")
        self.assertIn("publish_retry_at", meta)
        self.assertNotIn("republish_retry_at", meta)
        self.assertEqual(meta["republish_transaction"]["phase"], "publish_retry_pending")

    def test_publish_only_retry_is_recognized_as_republish_not_second_delete(self):
        operation = {
            "status": "waiting",
            "action": "republish",
            "retry_mode": "publish_only",
            "old_live_deleted": True,
        }
        with patch.object(manager, "_operation_get", return_value=operation):
            self.assertEqual(manager._operation_existing_action_for_publish_retry("bike"), "republish")

    def test_delayed_publish_is_confirmed_with_new_remote_id(self):
        bot_result = {"ok": True, "output": "DONE: (Re-)published 1 ads"}
        with patch.object(manager, "_load_state", return_value={"ads": {}}), patch.object(
            manager, "_ad_account_id", return_value="main"
        ), patch.object(manager, "_capture_live_ids", return_value={"old-42"}), patch.object(
            manager, "_prepare_publish_image_order_staging", return_value=(Path("/tmp/config.yaml"), None, "")
        ), patch.object(manager, "_read_ad_yaml", return_value={"title": "Fahrrad"}), patch.object(
            manager, "_run_bot", return_value=bot_result.copy()
        ), patch.object(manager, "_sync_remote_link_after_publish", return_value=""), patch.object(
            manager, "_confirm_uncertain_publish_after_submit", return_value=("new-99", "nach Verzögerung gefunden")
        ), patch.object(Path, "unlink", return_value=None):
            result = manager._run_bot_for_slug("publish", "bike", account_id="main", force_new=True)

        self.assertTrue(result["ok"])
        self.assertEqual(result["remote_id"], "new-99")

    def test_successful_republish_keeps_new_remote_id(self):
        bot_result = {"ok": True, "output": "DONE: (Re-)published 1 ads"}
        with patch.object(manager, "_load_state", return_value={"ads": {}}), patch.object(
            manager, "_ad_account_id", return_value="main"
        ), patch.object(manager, "_capture_live_ids", return_value={"old-42"}), patch.object(
            manager, "_prepare_publish_image_order_staging", return_value=(Path("/tmp/config.yaml"), None, "")
        ), patch.object(manager, "_read_ad_yaml", return_value={"title": "Fahrrad"}), patch.object(
            manager, "_run_bot", return_value=bot_result.copy()
        ), patch.object(manager, "_sync_remote_link_after_publish", return_value="new-77"), patch.object(
            manager, "_confirm_uncertain_publish_after_submit"
        ) as confirm, patch.object(Path, "unlink", return_value=None):
            result = manager._run_bot_for_slug("publish", "bike", account_id="main", force_new=True)

        self.assertTrue(result["ok"])
        self.assertEqual(result["remote_id"], "new-77")
        confirm.assert_not_called()

    def test_timeout_after_submit_is_treated_as_uncertain_and_verified(self):
        self.assertTrue(manager._publish_submission_uncertain_text("request timed out after publish submit"))
        self.assertTrue(manager._publish_submission_uncertain_text("connection reset after publish"))

    def test_pending_republish_is_not_counted_as_unpublished_in_ui_badge(self):
        state = {"ads": {"bike": {"republish_transaction": {"phase": "publish_retry_pending"}}}}
        with TemporaryDirectory() as temp:
            Path(temp, "bike.yaml").touch()
            with patch.object(manager, "ADS_DIR", Path(temp)), patch.object(
                manager, "_read_ad_yaml", return_value={"title": "Fahrrad"}
            ):
                self.assertEqual(manager._count_unpublished_ads(state), 0)


if __name__ == "__main__":
    unittest.main()
