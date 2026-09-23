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


    def test_profile_emails_are_normalized(self):
        self.assertEqual(manager._app_user_by_email(" primary.Person user@example.invalid ")["id"], "primary")
        self.assertEqual(manager._app_user_by_email("user@example.invalid")["id"], "secondary")
        self.assertIsNone(manager._app_user_by_email("nobody@example.invalid"))


if __name__ == "__main__":
    unittest.main()
