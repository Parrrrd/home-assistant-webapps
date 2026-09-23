import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as manager


class ProfileReadStateTests(unittest.TestCase):
    def test_primary_and_secondary_keep_independent_read_state(self):
        cache_items = [
            {"id": "new", "account_id": "main", "unread": True, "unread_count": 1},
            {"id": "old", "account_id": "main", "unread": False, "unread_count": 0},
        ]
        markers = {
            "new": {"marker": "marker-new", "at": "2026-08-26T20:00:00+00:00"},
            "old": {"marker": "marker-old", "at": "2026-08-25T20:00:00+00:00"},
        }
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            manager, "USER_MESSAGE_STATE_FILE", Path(tmp) / "user-message-state.json"
        ), patch.object(manager, "_load_state", return_value={"accounts": {"main": {"id": "main"}}}), patch.object(
            manager, "_accounts_from_state", return_value={"main": {"id": "main"}}
        ), patch.object(
            manager, "_read_api_cache", side_effect=lambda kind, account: {"items": [dict(x) for x in cache_items]}
        ), patch.object(
            manager, "_message_incoming_marker", side_effect=lambda account, cid, state=None: markers[str(cid)]
        ):
            rows = [{**x, "incoming_marker": markers[x["id"]]["marker"]} for x in cache_items]
            primary = manager._decorate_profile_unread(rows, "primary")
            self.assertEqual({x["id"]: x["unread"] for x in primary}, {"new": True, "old": False})

            manager._mark_user_message_read("primary", "main", "new", "marker-new")
            primary = manager._decorate_profile_unread(rows, "primary")
            self.assertFalse(next(x for x in primary if x["id"] == "new")["unread"])

            # Kleinanzeigen itself may already regard it as read after primary opened it.
            cache_items[0]["unread"] = False
            cache_items[0]["unread_count"] = 0
            secondary = manager._decorate_profile_unread(rows, "secondary")
            self.assertTrue(next(x for x in secondary if x["id"] == "new")["unread"])


    def test_mark_all_read_marks_every_cached_incoming_marker_for_profile(self):
        cache_items = [
            {"id": "one", "account_id": "main", "unread": True, "unread_count": 1},
            {"id": "two", "account_id": "second", "unread": True, "unread_count": 1},
        ]
        markers = {"one": {"marker": "m1", "at": ""}, "two": {"marker": "m2", "at": ""}}
        state = {"accounts": {"main": {"id": "main"}, "second": {"id": "second"}}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            manager, "USER_MESSAGE_STATE_FILE", Path(tmp) / "user-message-state.json"
        ), patch.object(manager, "_load_state", return_value=state), patch.object(
            manager, "_accounts_from_state", return_value={"main": {}, "second": {}}
        ), patch.object(
            manager, "_read_api_cache", side_effect=lambda kind, account: {"items": [dict(x) for x in cache_items if x["account_id"] == account]}
        ), patch.object(
            manager, "_message_incoming_marker", side_effect=lambda account, cid, state=None: markers[str(cid)]
        ):
            manager._save_user_message_state({"version": 1, "users": {"primary": {"seen": {}, "initialized": True}}})
            self.assertEqual(manager._mark_all_user_messages_read("primary"), 2)
            saved = manager._load_user_message_state()["users"]["primary"]["seen"]
            self.assertEqual(saved["main:one"], "m1")
            self.assertEqual(saved["second:two"], "m2")
            self.assertEqual(manager._mark_all_user_messages_read("primary"), 0)

    def test_display_profiles_keep_technical_ids_but_use_local_names(self):
        with patch.object(manager, "_home_assistant_profile_display_names", return_value={"primary": "Name A", "secondary": "Name B"}):
            users = manager._app_users_for_display()
        self.assertEqual([(u["id"], u["name"]) for u in users], [("primary", "Name A"), ("secondary", "Name B")])

    def test_profile_emails_are_normalized(self):
        self.assertEqual(manager._app_user_by_email(" primary.Person user@example.invalid ")["id"], "primary")
        self.assertEqual(manager._app_user_by_email("user@example.invalid")["id"], "secondary")
        self.assertIsNone(manager._app_user_by_email("nobody@example.invalid"))


if __name__ == "__main__":
    unittest.main()
