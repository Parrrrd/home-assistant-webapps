import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import app as manager


class LiveConversationStatusTests(unittest.TestCase):
    def setUp(self):
        self.live_cache = {"updated_at": "2026-08-24T19:00:00+00:00", "items": [], "error": ""}

    def test_only_own_seller_listing_can_become_deleted_when_absent(self):
        with patch.object(manager, "_read_api_cache", return_value=self.live_cache):
            self.assertEqual(manager._cached_live_ad_message_status("main", "foreign"), "")
            self.assertEqual(
                manager._cached_live_ad_message_status("main", "own", absent_means_deleted=True),
                "deleted",
            )

    def test_live_refresh_only_changes_own_seller_chat(self):
        messages = {
            "items": [
                {"id": "foreign-chat", "role": "BUYER", "ad_id": "foreign", "ad_status": "deleted"},
                {"id": "own-chat", "role": "SELLER", "ad_id": "own", "ad_status": "online"},
            ]
        }
        written = []

        def read_cache(kind, _account_id):
            return messages if kind == "messages" else self.live_cache

        with patch.object(manager, "_read_api_cache", side_effect=read_cache), patch.object(
            manager, "_write_api_cache", side_effect=lambda kind, account, items: written.append((kind, account, items))
        ):
            self.assertTrue(manager._refresh_cached_conversation_ad_statuses_from_live("main"))

        self.assertEqual(messages["items"][0]["ad_status"], "deleted")
        self.assertEqual(messages["items"][1]["ad_status"], "deleted")
        self.assertEqual(written[0][0], "messages")

    def test_external_listing_status_uses_sellers_actual_listing(self):
        listing = {"id": "foreign", "status": "RESERVED"}
        api = SimpleNamespace(get_ad=lambda _ad_id: listing)
        with patch.object(manager, "_api_client", return_value=(api, None)):
            self.assertEqual(
                manager._check_external_conversation_ad_status(
                    "main", {"id": "foreign-chat", "role": "BUYER", "ad_id": "foreign"}
                ),
                "reserved",
            )

    def test_external_404_means_deleted_but_other_errors_do_not_guess(self):
        class Missing(Exception):
            status_code = 404

        missing_api = SimpleNamespace(get_ad=lambda _ad_id: (_ for _ in ()).throw(Missing("missing")))
        with patch.object(manager, "_api_client", return_value=(missing_api, None)):
            self.assertEqual(
                manager._check_external_conversation_ad_status("main", {"role": "BUYER", "ad_id": "foreign"}),
                "deleted",
            )
        failed_api = SimpleNamespace(get_ad=lambda _ad_id: (_ for _ in ()).throw(RuntimeError("timeout")))
        with patch.object(manager, "_api_client", return_value=(failed_api, None)):
            self.assertEqual(
                manager._check_external_conversation_ad_status("main", {"role": "BUYER", "ad_id": "foreign"}),
                "",
            )

    def test_old_unchecked_buyer_deleted_marker_is_cleared_before_new_check(self):
        old_messages = {"items": [{
            "id": "foreign-chat", "role": "BUYER", "ad_id": "foreign", "ad_status": "deleted",
        }]}
        api = SimpleNamespace(conversations=lambda page, size: [
            {"id": "foreign-chat", "role": "BUYER", "ad_id": "foreign"}
        ])
        writes = []

        def read_cache(kind, _account_id):
            return old_messages if kind == "messages" else self.live_cache

        with patch.object(manager, "_api_client", return_value=(api, None)), patch.object(
            manager, "_read_api_cache", side_effect=read_cache
        ), patch.object(manager, "_write_api_cache", side_effect=lambda kind, account, items: writes.append(items)), patch.object(
            manager, "_schedule_external_conversation_ad_status_check", return_value=True
        ):
            _conversations, items = manager._fetch_conversations_to_cache("main")

        self.assertEqual(items[0]["ad_status"], "")
        self.assertEqual(writes[0][0]["ad_status"], "")


    def test_live_posted_label_includes_time_for_today_and_yesterday(self):
        now = datetime(2026, 9, 23, 20, 30, tzinfo=manager.APP_TZ)
        with patch.object(manager, "_local_datetime", return_value=now):
            self.assertEqual(manager.liveposted_filter("2026-09-23T14:35:00+02:00"), "heute 14:35 Uhr")
            self.assertEqual(manager.liveposted_filter("2026-09-22T09:07:00+02:00"), "gestern 09:07 Uhr")
            self.assertEqual(manager.liveposted_filter("2026-09-20T09:07:00+02:00"), "20.09.2026")

    def test_top_satisfaction_is_used_for_profile_badge(self):
        self.assertEqual(manager._profile_badge_label("rating"), "TOP Zufriedenheit")


if __name__ == "__main__":
    unittest.main()
