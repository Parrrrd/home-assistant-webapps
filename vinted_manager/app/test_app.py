import base64
import csv
import io
import inspect
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch
from urllib.parse import parse_qsl, urlparse

import app as vinted_app


class VintedManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        vinted_app.DATA_DIR = Path(self.temp_dir.name)
        vinted_app.DRAFTS_FILE = vinted_app.DATA_DIR / "vinted-drafts.json"
        vinted_app.IMAGES_DIR = vinted_app.DATA_DIR / "images"
        vinted_app.BROWSER_PROFILE_DIR = vinted_app.DATA_DIR / "vinted-browser-profile"
        vinted_app.BACKGROUND_BROWSER_PROFILE_DIR = vinted_app.DATA_DIR / "vinted-background-browser-profile"
        vinted_app.METADATA_CACHE_FILE = vinted_app.DATA_DIR / "vinted-metadata-cache.json"
        vinted_app.CATEGORY_RULES_FILE = vinted_app.DATA_DIR / "vinted-category-rules.json"
        vinted_app._category_rules_cache = None
        vinted_app._push_person_discovery_cache["expires_at"] = 0.0
        vinted_app._push_person_discovery_cache["labels"] = {}
        vinted_app.LIVE_CACHE_FILE = vinted_app.DATA_DIR / "vinted-live-cache.json"
        vinted_app.VINTED_SESSION_FILE = vinted_app.DATA_DIR / "vinted-session-cookies.json"
        vinted_app.VINTED_SESSION_STATUS_FILE = vinted_app.DATA_DIR / "vinted-session-status.json"
        vinted_app.INBOX_CACHE_FILE = vinted_app.DATA_DIR / "vinted-inbox-cache.json"
        vinted_app.NOTIFICATIONS_CACHE_FILE = vinted_app.DATA_DIR / "vinted-notifications-cache.json"
        vinted_app.USER_MESSAGE_STATE_FILE = vinted_app.DATA_DIR / "vinted-user-message-state.json"
        vinted_app.MESSAGE_ITEM_STATE_FILE = vinted_app.DATA_DIR / "vinted-message-item-states.json"
        vinted_app.ACTIVITY_MONITOR_FILE = vinted_app.DATA_DIR / "vinted-activity-monitor.json"
        vinted_app.SEARCH_MONITOR_FILE = vinted_app.DATA_DIR / "vinted-search-monitor.json"
        vinted_app.SEARCH_ALERTS_FILE = vinted_app.DATA_DIR / "vinted-search-alerts.json"
        vinted_app.SEARCH_DEBUG_FILE = vinted_app.DATA_DIR / "vinted-search-debug.json"
        vinted_app.APP_SETTINGS_FILE = vinted_app.DATA_DIR / "vinted-manager-settings.json"
        vinted_app.PUSH_DEVICES_FILE = vinted_app.DATA_DIR / "vinted-push-devices.json"
        vinted_app.PUSH_INVITES_FILE = vinted_app.DATA_DIR / "vinted-push-invites.json"
        vinted_app.PUSH_VAPID_PRIVATE_KEY_FILE = vinted_app.DATA_DIR / "vinted-push-vapid-private.pem"
        vinted_app.RUNTIME_HEALTH_FILE = vinted_app.DATA_DIR / "vinted-runtime-health.json"
        vinted_app.KA_CROSS_ACTION_INBOX_DIR = vinted_app.DATA_DIR / "cross" / "vinted-to-kleinanzeigen"
        vinted_app.KA_DELETE_ACTION_INBOX_DIR = vinted_app.DATA_DIR / "cross" / "kleinanzeigen-to-vinted"
        with vinted_app._terminal_draft_lock:
            vinted_app._terminal_draft_ids.clear()
        vinted_app._browser_process = None
        vinted_app._primary_browser_target_id = ""
        vinted_app._vinted_live_preview.update({"image": b"", "captured_at": 0.0, "target_id": ""})
        vinted_app._vinted_live_preview_target_id = ""
        with vinted_app._visible_browser_activity_lock:
            vinted_app._visible_browser_active_commands = 0
            vinted_app._visible_browser_last_activity_monotonic = 0.0
            vinted_app._visible_browser_frozen_target_ids.clear()
            vinted_app._visible_browser_manual_awake_until = 0.0
            vinted_app._visible_browser_lifecycle_supported = True
        vinted_app._visible_browser_last_recovery_monotonic = 0.0
        vinted_app._background_browser_process = None
        vinted_app._background_api_target = None
        vinted_app._background_session_refreshed_at = 0.0
        with vinted_app._saved_search_sync_state_lock:
            vinted_app._saved_search_sync_state.update({
                "running": False,
                "manual_pending": False,
                "alerts_suppressed": False,
                "source": "",
                "started_at": "",
                "finished_at": "",
                "current": 0,
                "total": 0,
                "current_name": "",
                "last_count": 0,
                "last_error": "",
                "last_warning": "",
            })
        vinted_app.app.config["TESTING"] = True
        self.client = vinted_app.app.test_client()
        with self.client.session_transaction() as browser_session:
            browser_session["app_user_id"] = "primary"
            browser_session["app_user_email"] = vinted_app.APP_USERS["primary"]["email"]
            browser_session.permanent = True

    def tearDown(self):
        vinted_app._browser_process = None
        vinted_app._background_browser_process = None
        self.temp_dir.cleanup()

    def draft_data(self, **overrides):
        data = {
            "title": "Affenzahn Sandalen Gr. 32",
            "description": "Dunkelblaue Kindersandalen in gutem Zustand.",
            "brand": "Affenzahn",
            "price": "39",
            "photos": (io.BytesIO(b"test image"), "test.jpg"),
        }
        data.update(overrides)
        return data

    def create_draft(self, **overrides):
        response = self.client.post("/drafts/new", data=self.draft_data(**overrides), follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        return response.headers["Location"].rsplit("/", 1)[-1]

    def metadata(self):
        return {
            "schema": 2,
            "fetched_at": vinted_app._now(),
            "catalogs": [
                {"id": 100, "title": "Schuhe", "path": "Kinder > Schuhe", "size_group_id": 10, "leaf": False},
                {"id": 101, "title": "Sandalen", "path": "Kinder > Schuhe > Sandalen", "size_group_id": 10, "leaf": True},
                {"id": 102, "title": "Sneaker", "path": "Kinder > Schuhe > Sneaker", "size_group_id": 10, "leaf": True},
                {"id": 201, "title": "Jacken", "path": "Damen > Kleidung > Jacken", "size_group_id": 20, "leaf": True},
            ],
            "size_groups": [
                {"id": 10, "caption": "Schuhe", "description": "", "sizes": [{"id": 320, "label": "32"}, {"id": 330, "label": "33"}]},
                {"id": 20, "caption": "Kleidung", "description": "", "sizes": [{"id": 900, "label": "XXL"}]},
            ],
            "colors": [{"id": 1, "label": "Blau", "hex": "#0000ff"}],
        }

    def test_complete_draft_passes_local_check(self):
        draft_id = self.create_draft()
        response = self.client.post(f"/drafts/{draft_id}/dry-run", follow_redirects=True)
        self.assertIn("Lokale Pruefung bestanden".encode(), response.data)
        self.assertEqual(vinted_app._find_draft(draft_id)["status"], "Bereit fuer Kontotest")

    def test_live_view_lists_only_confirmed_publications(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        draft.update({
            "status": "Veröffentlicht",
            "published_item_id": "987654321",
            "published_url": "https://www.vinted.de/items/987654321",
            "published_at": vinted_app._now(),
        })
        vinted_app._replace_draft(draft)
        self.create_draft(title="Nur ein Entwurf")

        live_items = [{
            "published_item_id": "987654321",
            "published_url": "https://www.vinted.de/items/987654321",
            "title": "Affenzahn Sandalen Gr. 32",
            "brand": "Affenzahn",
            "price": "39",
            "currency": "EUR",
            "photo_url": "",
            "published_at": vinted_app._now(),
            "live_state": "active",
        }]
        with patch.object(vinted_app, "_load_live_vinted_items", return_value=live_items):
            response = self.client.get("/live")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Affenzahn Sandalen".encode(), response.data)
        self.assertNotIn("Nur ein Entwurf".encode(), response.data)
        self.assertIn(b"Bei Vinted aktiv", response.data)
        self.assertIn("Als verkauft markieren".encode(), response.data)
        self.assertIn("Reservieren".encode(), response.data)
        self.assertIn(b"member-dialog", response.data)
        self.assertIn(b"data-member-action=\"reserved\"", response.data)
        self.assertIn(b"data-member-action=\"sold\"", response.data)
        self.assertIn("Im Manager bearbeiten".encode(), response.data)
        self.assertNotIn("Bei Vinted bearbeiten".encode(), response.data)

    def test_live_publication_age_labels_today_yesterday_and_older(self):
        tz = vinted_app._display_timezone()
        now = vinted_app.datetime(2026, 9, 20, 9, 44, tzinfo=tz)
        self.assertEqual(
            vinted_app._live_published_age_label(vinted_app.datetime(2026, 9, 20, 3, 35, tzinfo=tz), now=now),
            "heute 03:35 Uhr",
        )
        self.assertEqual(
            vinted_app._live_published_age_label(vinted_app.datetime(2026, 9, 19, 3, 35, tzinfo=tz), now=now),
            "gestern 03:35 Uhr",
        )
        self.assertEqual(
            vinted_app._live_published_age_label(vinted_app.datetime(2026, 9, 15, 3, 35, tzinfo=tz), now=now),
            "vor 5 Tagen",
        )

    def test_live_listing_action_uses_confirmed_published_draft(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        draft.update({
            "status": "Veröffentlicht",
            "published_item_id": "987654321",
            "published_url": "https://www.vinted.de/items/987654321",
        })
        vinted_app._replace_draft(draft)

        live_item = {
            "published_item_id": "987654321",
            "published_url": "https://www.vinted.de/items/987654321",
            "title": "Affenzahn Sandalen Gr. 32",
            "live_state": "active",
        }
        with patch.object(vinted_app, "_load_live_vinted_items", return_value=[live_item]), \
             patch.object(vinted_app, "_run_vinted_listing_action", return_value={"ok": True}) as action, \
             patch.object(vinted_app, "_wait_for_live_action", return_value={"live_state": "reserved"}):
            response = self.client.post(
                "/live/items/987654321/action",
                data={"action": "reserved", "member_name": "Beispielmitglied"},
                follow_redirects=True,
            )

        self.assertEqual(response.status_code, 200)
        action.assert_called_once_with(live_item, "reserved", "Beispielmitglied")
        self.assertEqual(vinted_app._find_draft(draft_id)["last_live_action"], "reserved")
        self.assertEqual(vinted_app._find_draft(draft_id)["live_state"], "reserved")
        self.assertEqual(vinted_app._find_draft(draft_id)["reserved_for"], "Beispielmitglied")

    def test_published_draft_updates_same_vinted_listing_without_republishing(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        draft.update({
            "status": "Veröffentlicht",
            "published_item_id": "987654321",
            "published_url": "https://www.vinted.de/items/987654321-affenzahn-sandalen",
        })
        vinted_app._replace_draft(draft)
        confirmed = {
            "published_item_id": "987654321",
            "title": "Überarbeitete Sandalen Gr. 32",
            "price": "40",
            "live_state": "active",
        }
        with patch.object(vinted_app, "_update_live_vinted_listing", return_value={"ok": True}) as update, \
             patch.object(vinted_app, "_wait_for_live_listing_update", return_value=confirmed) as verify, \
             patch.object(vinted_app, "_run_browser_direct_upload") as publish:
            response = self.client.post(
                f"/drafts/{draft_id}/prepare-upload",
                data={
                    "title": "Überarbeitete Sandalen Gr. 32",
                    "description": "Aktualisierte Beschreibung.",
                    "brand": "Affenzahn",
                    "price": "40",
                    "workflow_action": "update_live",
                },
                follow_redirects=True,
            )

        self.assertEqual(response.status_code, 200)
        update.assert_called_once()
        verify.assert_called_once()
        publish.assert_not_called()
        saved = vinted_app._find_draft(draft_id)
        self.assertEqual(saved["published_item_id"], "987654321")
        self.assertEqual(saved["published_url"], "https://www.vinted.de/items/987654321-affenzahn-sandalen")
        self.assertEqual(saved["status"], "Bei Vinted aktualisiert")
        self.assertEqual(saved["last_live_update_fields"], ["Titel", "Beschreibung", "Preis"])
        self.assertIn("keine neue Anzeige erstellt".encode(), response.data)

    def test_live_update_uses_an_isolated_item_tab_not_the_current_vinted_page(self):
        draft = {
            "published_item_id": "987654321",
            "published_url": "https://www.vinted.de/items/987654321-affenzahn-sandalen",
            "title": "Aktualisierte Sandalen",
            "description": "Aktualisierte Beschreibung",
            "price": "39,50",
        }
        item_page = {"id": "item"}
        editor_page = {"id": "editor"}
        with patch.object(vinted_app, "_open_live_listing_target", return_value=item_page) as open_item, \
             patch.object(vinted_app, "_wait_for_vinted_listing_editor", return_value=editor_page), \
             patch.object(vinted_app, "_navigate_to_live_listing") as current_tab, \
             patch.object(vinted_app, "_cdp_command", side_effect=[
                 {"result": {"value": {"ok": True}}},
                 {"result": {"value": {"ok": True}}},
             ]) as cdp:
            result = vinted_app._update_live_vinted_listing(draft)

        self.assertTrue(result["ok"])
        open_item.assert_called_once_with(draft["published_url"])
        current_tab.assert_not_called()
        self.assertEqual(cdp.call_count, 2)

    def test_published_draft_form_offers_live_update_instead_of_republishing(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        draft.update({
            "published_item_id": "987654321",
            "published_url": "https://www.vinted.de/items/987654321-affenzahn-sandalen",
            "category_verified": True,
        })
        vinted_app._replace_draft(draft)

        response = self.client.get(f"/drafts/{draft_id}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Änderungen bei Vinted aktualisieren".encode(), response.data)
        self.assertNotIn(b'name="workflow_action" value="publish"', response.data)

    def test_live_listing_can_be_linked_to_a_new_manager_template(self):
        live_item = {
            "published_item_id": "123456789",
            "published_url": "https://www.vinted.de/items/123456789-existing-sandals",
            "title": "Bestehende Sandalen Gr. 32",
            "brand": "Affenzahn",
            "size": "32",
            "price": "39",
            "currency": "EUR",
            "live_state": "active",
        }
        with patch.object(vinted_app, "_load_live_vinted_items", return_value=[live_item]), \
             patch.object(vinted_app, "_browser_fetch_json", return_value={"item": {"title": live_item["title"], "description": "Vorhandene Beschreibung"}}):
            response = self.client.post("/live/items/123456789/adopt", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        linked = next(item for item in vinted_app._load_drafts() if item.get("published_item_id") == "123456789")
        self.assertEqual(linked["title"], "Bestehende Sandalen Gr. 32")
        self.assertEqual(linked["description"], "Vorhandene Beschreibung")
        self.assertEqual(linked["status"], "Bei Vinted verknüpft")
        self.assertIn("Änderungen bei Vinted aktualisieren".encode(), response.data)

    def test_live_view_offers_manager_adoption_for_unlinked_listing(self):
        live_item = {
            "published_item_id": "123456789",
            "published_url": "https://www.vinted.de/items/123456789-existing-sandals",
            "title": "Bestehende Sandalen Gr. 32",
            "price": "39",
            "live_state": "active",
        }
        with patch.object(vinted_app, "_load_live_vinted_items", return_value=[live_item]):
            response = self.client.get("/live")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Als neue Manager-Anzeige übernehmen".encode(), response.data)

    def test_member_name_is_required_before_reserving(self):
        response = self.client.post(
            "/live/items/987654321/action",
            data={"action": "reserved"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Bitte zuerst das Vinted-Mitglied".encode(), response.data)

    def test_live_member_suggestions_are_loaded_from_vinted(self):
        live_item = {
            "published_item_id": "987654321",
            "published_url": "https://www.vinted.de/items/987654321",
            "title": "Affenzahn Sandalen Gr. 32",
            "live_state": "active",
        }
        with patch.object(vinted_app, "_load_live_vinted_items", return_value=[live_item]), \
             patch.object(vinted_app, "_load_vinted_member_suggestions", return_value=["Vinted Name"]):
            response = self.client.get("/live/items/987654321/members?action=reserved")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"members": ["Vinted Name"]})

    def test_live_action_confirmation_reads_the_live_wardrobe(self):
        live_item = {
            "published_item_id": "987654321",
            "title": "Affenzahn Sandalen Gr. 32",
            "live_state": "hidden",
        }
        with patch.object(vinted_app, "_load_live_vinted_items", return_value=[live_item]) as live_feed:
            confirmed = vinted_app._wait_for_live_action("987654321", "hide", timeout=0.1)

        self.assertEqual(confirmed, live_item)
        live_feed.assert_called_once_with(force=True)

    def test_delete_action_rebuilds_fresh_home_tab_when_seller_controls_never_hydrate(self):
        listing = {
            "published_item_id": "987654321",
            "published_url": "https://www.vinted.de/items/987654321-test",
        }
        evaluations = iter([
            {"result": {"value": {"bodyTextLength": 1200, "skeletons": 3}}},
            {"result": {"value": {"confirm": True, "bodyTextLength": 1400, "skeletons": 0}}},
            {"result": {"value": {"clicked": True, "kind": "confirm"}}},
        ])
        clock = [0.0]
        def monotonic():
            clock[0] += 6.0
            return clock[0]

        with patch.object(vinted_app, "_navigate_to_live_listing", return_value={"id": "item"}), \
             patch.object(vinted_app, "_verify_vinted_session"), \
             patch.object(vinted_app, "_refresh_browser_target", side_effect=lambda page: page), \
             patch.object(vinted_app, "_vinted_login_link_visible", return_value=False), \
             patch.object(vinted_app, "_vinted_listing_document_probe", return_value={"usable": True, "degraded": False, "reason": "ok", "bodyTextLength": 1200, "skeletons": 3}), \
             patch.object(vinted_app, "_recover_degraded_vinted_listing", return_value={"id": "fresh-item"}) as recover, \
             patch.object(vinted_app.time, "monotonic", side_effect=monotonic), \
             patch.object(vinted_app.time, "sleep"), \
             patch.object(vinted_app, "_cdp_command", side_effect=lambda *a, **k: next(evaluations)):
            result = vinted_app._run_vinted_listing_action(listing, "delete")

        self.assertTrue(result["ok"])
        recover.assert_called_once_with({"id": "item"}, listing["published_url"])

    def test_hard_listing_recovery_uses_new_home_target_and_requires_seller_controls(self):
        listing_url = "https://www.vinted.de/items/987654321-test"
        recovered_page = {"id": "fresh-item"}
        with patch.object(vinted_app, "_open_fresh_visible_vinted_home_target", return_value={"id": "fresh-home"}) as fresh_home, \
             patch.object(vinted_app, "_vinted_login_link_visible", return_value=False), \
             patch.object(vinted_app, "_navigate_fresh_vinted_target_to_listing", return_value=recovered_page) as navigate, \
             patch.object(vinted_app, "_vinted_listing_document_probe", return_value={
                 "usable": True, "degraded": False, "sellerControl": True, "page": recovered_page
             }):
            result = vinted_app._recover_degraded_vinted_listing({"id": "broken-item"}, listing_url)

        self.assertEqual(result, recovered_page)
        fresh_home.assert_called_once_with(timeout=18)
        navigate.assert_called_once_with({"id": "fresh-home"}, listing_url, timeout=20)

    def test_delete_action_resets_degraded_item_page_via_home_before_clicking(self):
        listing = {
            "published_item_id": "987654321",
            "published_url": "https://www.vinted.de/items/987654321-test",
        }
        evaluations = iter([
            {"result": {"value": {"confirm": True, "bodyTextLength": 1400, "skeletons": 0}}},
            {"result": {"value": {"clicked": True, "kind": "confirm"}}},
        ])
        with patch.object(vinted_app, "_navigate_to_live_listing", return_value={"id": "item"}), \
             patch.object(vinted_app, "_verify_vinted_session"), \
             patch.object(vinted_app, "_hold_visible_browser_awake"), \
             patch.object(vinted_app, "_refresh_browser_target", side_effect=lambda page: page), \
             patch.object(vinted_app, "_vinted_login_link_visible", return_value=False), \
             patch.object(vinted_app, "_vinted_listing_document_probe", return_value={"usable": False, "degraded": True, "reason": "unsupported-shell", "bodyTextLength": 42, "sample": "You are using an unsupported browser"}), \
             patch.object(vinted_app, "_recover_degraded_vinted_listing", return_value={"id": "recovered"}) as recover, \
             patch.object(vinted_app.time, "monotonic", side_effect=[0.0, 5.0, 6.0, 7.0]), \
             patch.object(vinted_app, "_cdp_command", side_effect=lambda *a, **k: next(evaluations)):
            result = vinted_app._run_vinted_listing_action(listing, "delete")

        self.assertTrue(result["ok"])
        recover.assert_called_once_with({"id": "item"}, listing["published_url"])

    def test_delete_navigation_is_provisional_success_for_live_confirmation(self):
        listing = {
            "published_item_id": "987654321",
            "published_url": "https://www.vinted.de/items/987654321-test",
        }
        with patch.object(vinted_app, "_navigate_to_live_listing", return_value={"id": "item"}), \
             patch.object(vinted_app, "_verify_vinted_session"), \
             patch.object(vinted_app, "_refresh_browser_target", side_effect=lambda page: page), \
             patch.object(vinted_app, "_vinted_login_link_visible", return_value=False), \
             patch.object(vinted_app, "_vinted_listing_document_probe", return_value={"usable": True, "degraded": False}), \
             patch.object(vinted_app, "_cdp_command", side_effect=RuntimeError("Inspected target navigated or closed")):
            result = vinted_app._run_vinted_listing_action(listing, "delete")

        self.assertTrue(result["ok"])
        self.assertTrue(result["delete_action_started"])

    def test_reservation_action_finishes_vinteds_second_confirmation_page(self):
        listing = {
            "published_item_id": "987654321",
            "published_url": "https://www.vinted.de/items/987654321-affenzahn-sandalen",
        }
        with patch.object(vinted_app, "_navigate_to_live_listing", return_value={"id": "item"}), \
             patch.object(vinted_app, "_verify_vinted_session"), \
             patch.object(vinted_app, "_refresh_browser_target", side_effect=lambda page: page), \
             patch.object(vinted_app, "_vinted_login_link_visible", return_value=False), \
             patch.object(vinted_app, "_cdp_command", return_value={"result": {"value": {"ok": True}}}), \
             patch.object(vinted_app, "_confirm_vinted_member_action", return_value={"ok": True}) as confirm:
            result = vinted_app._run_vinted_listing_action(listing, "reserved", "Beispielmitglied")

        confirm.assert_called_once_with("reserved", "Beispielmitglied", "", "987654321", "")
        self.assertEqual(result["live_state"], "reserved")

    def test_member_confirmation_carries_chat_member_and_item_identity(self):
        with patch.object(vinted_app, "_wait_for_vinted_route", return_value={"id": "reservation"}), \
             patch.object(vinted_app, "_confirm_vinted_reservation_by_pointer", return_value={"ok": False}), \
             patch.object(vinted_app, "_cdp_command", return_value={"result": {"value": {"ok": True}}}) as cdp:
            result = vinted_app._confirm_vinted_member_action(
                "reserved", "kathkroe888", "83077265", "9789597726", "Forschur Pink Kapuzenjacke",
            )

        self.assertTrue(result["ok"])
        expression = cdp.call_args.args[2]["expression"]
        self.assertIn("83077265", expression)
        self.assertIn("9789597726", expression)
        self.assertIn("reservieren\\s+für", expression)
        self.assertIn("itemTitle", expression)
        self.assertIn("visibleMemberTextNodes", expression)
        self.assertIn("exactMemberTextTargets", expression)
        self.assertIn("neutralMemberTile", expression)
        self.assertIn("[role=\"option\"], [role=\"listbox\"] li, [role=\"listbox\"] button, ' +", expression)

    def test_reservation_uses_trusted_pointer_events_for_vinted_picker(self):
        evaluations = iter([
            {"result": {"value": {"ok": True, "x": 550, "y": 350, "label": "Mitglied"}}},
            {"result": {"value": {"ok": True, "x": 540, "y": 396, "label": "kathkroe888"}}},
            {"result": {"value": {"ok": True, "x": 690, "y": 525, "label": "Reservieren"}}},
        ])

        def cdp(page, method, params, timeout=0):
            if method == "Runtime.evaluate":
                return next(evaluations)
            self.assertEqual(method, "Input.dispatchMouseEvent")
            return {}

        with patch.object(vinted_app, "_wait_for_vinted_route", return_value={"id": "reservation"}), \
             patch.object(vinted_app, "_cdp_command", side_effect=cdp) as command:
            result = vinted_app._confirm_vinted_member_action("reserved", "kathkroe888", "83077265", "9789597726")

        self.assertTrue(result["ok"])
        self.assertEqual(result["via"], "trusted_pointer")
        self.assertEqual(command.call_count, 9)

    def test_chat_push_is_readable_and_does_not_repeat_the_item_title(self):
        title, message = vinted_app._chat_push_content({
            "sender": "kathkroe888",
            "text": "Affenzahn Vegan Free Elefant Sandalen Gr. 32",
            "item_title": "Affenzahn Vegan Free Elefant Sandalen Gr. 32",
        })

        self.assertEqual(title, "Vinted · Update im Chat mit kathkroe888")
        self.assertEqual(message, "Artikel: Affenzahn Vegan Free Elefant Sandalen Gr. 32")

    def test_chat_push_identifies_status_and_price_events(self):
        status_title, status_message = vinted_app._chat_push_content({
            "sender": "kathkroe888", "text": "Reserviert für dich.", "item_title": "Jacke",
        })
        price_title, price_message = vinted_app._chat_push_content({
            "sender": "vivjaj", "text": "Hat dir einen Preisvorschlag gesendet", "item_title": "Jacke",
        })

        self.assertEqual(status_title, "Vinted · Artikelstatus")
        self.assertEqual(status_message, "kathkroe888: Reserviert für dich.\nArtikel: Jacke")
        self.assertEqual(price_title, "Vinted · Preisvorschlag von vivjaj")
        self.assertEqual(price_message, "Hat dir einen Preisvorschlag gesendet\nArtikel: Jacke")

    def test_member_confirmation_reports_a_browser_evaluation_without_value(self):
        evaluation = {
            "result": {"type": "undefined"},
            "exceptionDetails": {"text": "Uncaught TypeError: visible is not a function"},
        }
        with patch.object(vinted_app, "_wait_for_vinted_route", return_value={"id": "reservation"}), \
             patch.object(vinted_app, "_cdp_command", return_value=evaluation):
            with self.assertRaisesRegex(RuntimeError, "Vinteds Auswahlseite brach technisch ab"):
                vinted_app._confirm_vinted_member_action("reserved", "kathkroe888", "83077265", "9789597726")

    def test_reservation_opens_vinteds_fixed_item_confirmation_route(self):
        page = {"id": "vinted"}
        with patch.object(vinted_app, "_wait_for_vinted_page", return_value=page), \
             patch.object(vinted_app, "_cdp_command", return_value={"result": {"value": {}}}) as cdp, \
             patch.object(vinted_app, "_wait_for_vinted_route", return_value={"id": "reservation"}) as wait_route:
            result = vinted_app._navigate_to_vinted_member_confirmation(
                "9789597726", "reserved", "https://www.vinted.de/items/9789597726-jacke",
            )

        self.assertEqual(result, {"id": "reservation"})
        self.assertIn("/member/items/reservation?id=9789597726", cdp.call_args.args[2]["url"])
        self.assertIn("ref_url=%2Fitems%2F9789597726-jacke", cdp.call_args.args[2]["url"])
        wait_route.assert_called_once_with("/member/items/reservation", timeout=12)

    def test_same_item_status_marks_every_matching_chat(self):
        rows = [
            {"id": "1", "item_id": "978", "item_title": "Jacke"},
            {"id": "2", "item_id": "978", "item_title": "Jacke"},
            {"id": "3", "item_id": "999", "item_title": "Hose"},
        ]
        with patch.object(vinted_app, "_load_live_vinted_items", return_value=[{"published_item_id": "978", "live_state": "reserved"}]):
            marked = vinted_app._decorate_message_listing_states(rows)

        self.assertEqual([row["item_state"] for row in marked], ["reserved", "reserved", ""])
        self.assertEqual(vinted_app._read_message_item_states().get("978"), "reserved")

    def test_live_view_includes_unmatched_vinted_item(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        draft.update({"published_item_id": "111", "published_url": "https://www.vinted.de/items/111"})
        vinted_app._replace_draft(draft)
        live_items = [
            {"published_item_id": "111", "title": "Bekannt", "price": "39", "live_state": "active"},
            {"published_item_id": "222", "title": "Direkt bei Vinted eingestellt", "price": "12", "live_state": "reserved"},
            {"published_item_id": "333", "title": "Dritte Anzeige", "price": "20", "live_state": "active"},
        ]
        with patch.object(vinted_app, "_load_live_vinted_items", return_value=live_items):
            response = self.client.get("/live")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Dritte Anzeige".encode(), response.data)
        self.assertIn("Noch nicht mit einer Vorlage verknüpft".encode(), response.data)
        self.assertEqual(response.data.count("Im Manager bearbeiten".encode()), 1)
        self.assertIn("Bei Vinted reserviert".encode(), response.data)

    def test_hidden_live_item_offers_reactivate_instead_of_reserve(self):
        hidden_item = {
            "published_item_id": "444",
            "title": "Versteckte Anzeige",
            "price": "10",
            "live_state": "hidden",
        }
        with patch.object(vinted_app, "_load_live_vinted_items", return_value=[hidden_item]):
            response = self.client.get("/live")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Wieder anzeigen".encode(), response.data)
        self.assertNotIn(b'data-member-action="reserved"', response.data)

    def test_normalise_vinted_item_uses_remote_state_and_fields(self):
        item = vinted_app._normalise_vinted_item({
            "id": 222,
            "title": "Sandalen",
            "brand_title": "Affenzahn",
            "size_title": "32",
            "price": {"amount": "39.00", "currency_code": "EUR"},
            "photo": {"url": "https://images.example/item.jpg"},
            "is_reserved": True,
        })
        self.assertEqual(item["published_item_id"], "222")
        self.assertEqual(item["price"], "39")
        self.assertEqual(item["live_state"], "reserved")
        self.assertEqual(item["photo_url"], "https://images.example/item.jpg")

    def test_normalise_vinted_item_prefers_current_nested_live_counters(self):
        item = vinted_app._normalise_vinted_item({
            "id": 222, "title": "Sandalen", "view_count": 0, "favourite_count": 0,
            "statistics": {
                "views": {"count": 17},
                "favourites": {"count": 4},
            },
        })
        self.assertEqual(item["views"], 17)
        self.assertEqual(item["favourites"], 4)

    def test_item_payload_uses_seller_id_not_item_id(self):
        payload = {"id": 999, "title": "Artikel", "user": {"id": 123}}
        self.assertEqual(vinted_app._payload_user_id(payload), "123")

    def test_live_sync_uses_current_wardrobe_endpoint(self):
        payload = {"items": [{"id": 222, "title": "Dritte Anzeige", "price": {"amount": "20"}}]}
        with patch.object(vinted_app, "_verify_vinted_session"), \
             patch.object(vinted_app, "_discover_vinted_user_id", return_value="3163319923"), \
             patch.object(vinted_app, "_background_fetch_json", return_value=payload) as fetch:
            items = vinted_app._load_live_vinted_items(force=True)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["published_item_id"], "222")
        self.assertIn("/api/v2/wardrobe/3163319923/items", fetch.call_args.args[0])
        self.assertNotIn("/api/v2/users/", fetch.call_args.args[0])

    def test_live_sync_paginates_even_when_vinted_caps_page_below_requested_size(self):
        first = {"items": [{"id": n, "title": f"Artikel {n}"} for n in range(1, 25)]}
        second = {"items": [{"id": 25, "title": "Neuer Artikel"}]}
        third = {"items": []}
        with patch.object(vinted_app, "_verify_vinted_session"), \
             patch.object(vinted_app, "_discover_vinted_user_id", return_value="3163319923"), \
             patch.object(vinted_app, "_background_fetch_json", side_effect=[first, second, third]) as fetch:
            items = vinted_app._load_live_vinted_items(force=True)
        self.assertEqual(len(items), 25)
        self.assertIn("25", {str(item.get("published_item_id")) for item in items})
        self.assertEqual(fetch.call_count, 3)
        self.assertIn("page=2", fetch.call_args_list[1].args[0])
        self.assertIn("order=newest_first", fetch.call_args_list[0].args[0])

    def test_live_sync_stops_when_vinted_repeats_same_page(self):
        repeated = {"items": [{"id": 1, "title": "Artikel"}]}
        with patch.object(vinted_app, "_verify_vinted_session"), \
             patch.object(vinted_app, "_discover_vinted_user_id", return_value="3163319923"), \
             patch.object(vinted_app, "_background_fetch_json", side_effect=[repeated, repeated]) as fetch:
            items = vinted_app._load_live_vinted_items(force=True)
        self.assertEqual([str(item.get("published_item_id")) for item in items], ["1"])
        self.assertEqual(fetch.call_count, 2)

    def test_live_sync_falls_back_to_visible_profile(self):
        profile_items = [{"published_item_id": "333", "title": "Profilanzeige", "live_state": "active"}]
        with patch.object(vinted_app, "_verify_vinted_session"), \
             patch.object(vinted_app, "_discover_vinted_user_id", return_value="123"), \
             patch.object(vinted_app, "_background_fetch_json", side_effect=RuntimeError("blocked")), \
             patch.object(vinted_app, "_load_live_vinted_items_from_profile", return_value=profile_items) as profile:
            items = vinted_app._load_live_vinted_items(force=True)
            self.assertEqual(items, profile_items)
            profile.assert_called_once_with("123")

    def test_idle_browser_freeze_skips_login_upload_and_non_vinted_pages(self):
        home = {"type": "page", "url": "https://www.vinted.de/", "webSocketDebuggerUrl": "ws://home"}
        listing = {"type": "page", "url": "https://www.vinted.de/items/123-test", "webSocketDebuggerUrl": "ws://item"}
        login = {"type": "page", "url": "https://www.vinted.de/member/login", "webSocketDebuggerUrl": "ws://login"}
        upload = {"type": "page", "url": "https://www.vinted.de/items/new", "webSocketDebuggerUrl": "ws://upload"}
        external = {"type": "page", "url": "https://example.org/", "webSocketDebuggerUrl": "ws://external"}
        self.assertTrue(vinted_app._visible_browser_freeze_candidate(home))
        self.assertTrue(vinted_app._visible_browser_freeze_candidate(listing))
        self.assertFalse(vinted_app._visible_browser_freeze_candidate(login))
        self.assertFalse(vinted_app._visible_browser_freeze_candidate(upload))
        self.assertFalse(vinted_app._visible_browser_freeze_candidate(external))

    def test_idle_browser_freezes_after_idle_and_wakes_before_next_command(self):
        process = MagicMock()
        process.poll.return_value = None
        page = {
            "id": "primary",
            "type": "page",
            "url": "https://www.vinted.de/",
            "webSocketDebuggerUrl": "ws://primary",
        }
        vinted_app._browser_process = process
        vinted_app._visible_browser_last_activity_monotonic = 10.0
        with patch.object(vinted_app, "_browser_idle_sleep_enabled", return_value=True), \
             patch.object(vinted_app, "_debug_targets", return_value=[page]), \
             patch.object(vinted_app, "_set_visible_browser_lifecycle_state_direct") as lifecycle:
            frozen = vinted_app._visible_browser_idle_freeze_once(now=20.0)
            self.assertEqual(frozen, 1)
            lifecycle.assert_called_once_with(page, "frozen")
            self.assertIn("primary", vinted_app._visible_browser_frozen_target_ids)

            tracked = vinted_app._visible_browser_command_enter(page, "Runtime.evaluate")
            self.assertTrue(tracked)
            self.assertEqual(lifecycle.call_args_list[-1], call(page, "active"))
            self.assertNotIn("primary", vinted_app._visible_browser_frozen_target_ids)
            vinted_app._visible_browser_command_exit(tracked)
            self.assertEqual(vinted_app._visible_browser_active_commands, 0)

    def test_manual_browser_hold_wakes_frozen_page_and_blocks_immediate_refreeze(self):
        page = {
            "id": "primary",
            "type": "page",
            "url": "https://www.vinted.de/",
            "webSocketDebuggerUrl": "ws://primary",
        }
        process = MagicMock()
        process.poll.return_value = None
        vinted_app._browser_process = process
        vinted_app._visible_browser_frozen_target_ids.add("primary")
        with patch.object(vinted_app, "_debug_targets", return_value=[page]), \
             patch.object(vinted_app, "_set_visible_browser_lifecycle_state_direct") as lifecycle, \
             patch.object(vinted_app.time, "monotonic", return_value=100.0):
            vinted_app._hold_visible_browser_awake(300)
            lifecycle.assert_called_once_with(page, "active")
            self.assertNotIn("primary", vinted_app._visible_browser_frozen_target_ids)
            self.assertEqual(vinted_app._visible_browser_manual_awake_until, 400.0)
            self.assertEqual(vinted_app._visible_browser_idle_freeze_once(now=200.0), 0)

    def test_manual_browser_prepare_reloads_hidden_tab_after_idle_wake(self):
        page = {
            "id": "primary",
            "type": "page",
            "url": "https://www.vinted.de/",
            "webSocketDebuggerUrl": "ws://primary",
        }
        vinted_app._visible_browser_frozen_target_ids.add("primary")
        with patch.object(vinted_app, "_start_login_browser"), \
             patch.object(vinted_app, "_wait_for_vinted_page", return_value=page), \
             patch.object(vinted_app, "_hold_visible_browser_awake"), \
             patch.object(vinted_app, "_cdp_command"), \
             patch.object(vinted_app, "_visible_browser_health_snapshot", return_value={
                 "healthy": True, "visibility": "hidden", "ready": "complete",
             }), \
             patch.object(vinted_app, "_reload_visible_vinted_page", return_value={
                 "healthy": True, "visibility": "visible", "ready": "complete",
             }) as reload_page:
            result = vinted_app._prepare_visible_browser_for_manual_use()
        reload_page.assert_called_once_with(
            page, keep_awake_seconds=vinted_app.VINTED_BROWSER_MANUAL_AWAKE_SECONDS
        )
        self.assertTrue(result["reloaded"])

    def test_manual_browser_prepare_reloads_hidden_safe_tab_even_without_frozen_marker(self):
        page = {
            "id": "primary",
            "type": "page",
            "url": "https://www.vinted.de/",
            "webSocketDebuggerUrl": "ws://primary",
        }
        self.assertNotIn("primary", vinted_app._visible_browser_frozen_target_ids)
        with patch.object(vinted_app, "_start_login_browser"), \
             patch.object(vinted_app, "_wait_for_vinted_page", return_value=page), \
             patch.object(vinted_app, "_hold_visible_browser_awake"), \
             patch.object(vinted_app, "_cdp_command"), \
             patch.object(vinted_app, "_visible_browser_health_snapshot", return_value={
                 "healthy": True, "visibility": "hidden", "ready": "complete",
             }), \
             patch.object(vinted_app, "_reload_visible_vinted_page", return_value={
                 "healthy": True, "visibility": "visible", "ready": "complete",
             }) as reload_page:
            result = vinted_app._prepare_visible_browser_for_manual_use()
        reload_page.assert_called_once_with(
            page, keep_awake_seconds=vinted_app.VINTED_BROWSER_MANUAL_AWAKE_SECONDS
        )
        self.assertTrue(result["reloaded"])

    def test_manual_browser_prepare_does_not_reload_hidden_interactive_page(self):
        page = {
            "id": "primary",
            "type": "page",
            "url": "https://www.vinted.de/items/new",
            "webSocketDebuggerUrl": "ws://primary",
        }
        with patch.object(vinted_app, "_start_login_browser"), \
             patch.object(vinted_app, "_wait_for_vinted_page", return_value=page), \
             patch.object(vinted_app, "_hold_visible_browser_awake"), \
             patch.object(vinted_app, "_cdp_command"), \
             patch.object(vinted_app, "_visible_browser_health_snapshot", return_value={
                 "healthy": True, "visibility": "hidden", "ready": "complete",
             }), \
             patch.object(vinted_app, "_reload_visible_vinted_page") as reload_page:
            result = vinted_app._prepare_visible_browser_for_manual_use()
        reload_page.assert_not_called()
        self.assertFalse(result["reloaded"])

    def test_manual_browser_prepare_does_not_reload_normal_visible_tab(self):
        page = {
            "id": "primary",
            "type": "page",
            "url": "https://www.vinted.de/",
            "webSocketDebuggerUrl": "ws://primary",
        }
        vinted_app._visible_browser_frozen_target_ids.add("primary")
        with patch.object(vinted_app, "_start_login_browser"), \
             patch.object(vinted_app, "_wait_for_vinted_page", return_value=page), \
             patch.object(vinted_app, "_hold_visible_browser_awake"), \
             patch.object(vinted_app, "_cdp_command"), \
             patch.object(vinted_app, "_visible_browser_health_snapshot", return_value={
                 "healthy": True, "visibility": "visible", "ready": "complete",
             }), \
             patch.object(vinted_app, "_reload_visible_vinted_page") as reload_page:
            result = vinted_app._prepare_visible_browser_for_manual_use()
        reload_page.assert_not_called()
        self.assertFalse(result["reloaded"])

    def test_browser_recovery_reloads_unhealthy_renderer_before_restart(self):
        page = {
            "id": "primary",
            "type": "page",
            "url": "https://www.vinted.de/",
            "webSocketDebuggerUrl": "ws://primary",
        }
        unhealthy = {"healthy": False, "reason": "runtime: target crashed", "page": page}
        with patch.object(vinted_app, "_visible_browser_health_snapshot", side_effect=[unhealthy, unhealthy]), \
             patch.object(vinted_app, "_visible_browser_recovery_block_reason", return_value=""), \
             patch.object(vinted_app, "_reload_visible_vinted_page", return_value={"healthy": True}) as reload_page, \
             patch.object(vinted_app, "_stop_visible_browser") as stop, \
             patch.object(vinted_app, "_start_login_browser") as start:
            recovered = vinted_app._recover_visible_browser_if_unhealthy(
                "saved-search", RuntimeError("target crashed")
            )
        self.assertTrue(recovered)
        reload_page.assert_called_once_with(page)
        stop.assert_not_called()
        start.assert_not_called()

    def test_browser_recovery_does_nothing_for_healthy_browser_api_error(self):
        with patch.object(vinted_app, "_visible_browser_health_snapshot", return_value={"healthy": True}), \
             patch.object(vinted_app, "_stop_visible_browser") as stop:
            recovered = vinted_app._recover_visible_browser_if_unhealthy(
                "saved-search", RuntimeError("HTTP 503")
            )
        self.assertFalse(recovered)
        stop.assert_not_called()

    def test_settings_browser_link_uses_wake_recovery_route(self):
        with patch.object(vinted_app, "_account_status", return_value={"state": "connected", "title": "OK", "message": "OK"}), \
             patch.object(vinted_app, "_backup_rows", return_value=[]), \
             patch.object(vinted_app, "_log_rows", return_value=[]), \
             patch.object(vinted_app, "_novnc_url", return_value="http://example.invalid:6081/vnc.html"):
            response = self.client.get("/settings")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'href="/vinted-browser"', response.data)

    def test_background_session_refresh_only_verifies_primary_session(self):
        vinted_app._background_session_refreshed_at = 0.0
        with patch.object(vinted_app, "_saved_session_cookie_records", return_value=[{"name": "access_token_web", "value": "token", "domain": ".vinted.de"}]), \
             patch.object(vinted_app, "_verify_vinted_session") as verify, \
             patch.object(vinted_app, "_stop_background_browser") as stop:
            vinted_app._refresh_background_vinted_session(force=True)
        verify.assert_called_once_with(persist=True)
        stop.assert_not_called()

    def test_background_reads_use_primary_vinted_profile(self):
        with patch.object(vinted_app, "_browser_fetch_json", return_value={"items": []}) as read:
            self.assertEqual(vinted_app._background_fetch_json("/api/v2/inbox", headers={"Platform": "web"}), {"items": []})
        read.assert_called_once_with("/api/v2/inbox", timeout=14, headers={"Platform": "web"})

    def test_background_page_targets_never_open_visible_browser_tabs(self):
        source = inspect.getsource(vinted_app._open_vinted_background_target)
        self.assertIn("BACKGROUND_CHROME_DEBUG_PORT", source)
        self.assertNotIn("_open_vinted_target(target_page_url", source)

    def test_saved_search_probe_uses_the_authenticated_page_without_opening_a_tab(self):
        page = {"id": "primary", "webSocketDebuggerUrl": "ws://primary"}
        with patch.object(vinted_app, "_wait_for_vinted_page", return_value=page), \
             patch.object(vinted_app, "_wait_for_stable_vinted_document", return_value=page), \
             patch.object(vinted_app, "_open_saved_search_menu", return_value=[]), \
             patch.object(vinted_app, "_open_vinted_background_target") as background:
            probe, rows = vinted_app._open_saved_search_probe()
        self.assertEqual(rows, [])
        self.assertTrue(probe["_shared_primary"])
        background.assert_not_called()

    def test_unsupported_photo_is_rejected(self):
        response = self.client.post(
            "/drafts/new",
            data=self.draft_data(photos=(io.BytesIO(b"not image"), "test.txt")),
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"JPG, PNG oder WebP", response.data)

    def test_catalog_tree_is_flattened_with_size_group(self):
        raw = [{
            "id": 1, "title": "Kinder", "catalogs": [{
                "id": 2, "title": "Schuhe", "catalogs": [{
                    "id": 3, "title": "Sandalen", "size_group_id": 44, "catalogs": []
                }]
            }]
        }]
        result = vinted_app._flatten_catalog_document(raw)
        leaf = next(item for item in result if item["id"] == 3)
        self.assertEqual(leaf["path"], "Kinder > Schuhe > Sandalen")
        self.assertEqual(leaf["size_group_id"], 44)
        self.assertTrue(leaf["leaf"])

    def test_catalog_parent_breadcrumb_gets_current_node_appended(self):
        raw = [
            {"id": 1037, "title": "Jacken & Mäntel", "path": "Damen > Kleidung"},
            {"id": 1773, "title": "Capes & Ponchos", "path": "Damen > Kleidung > Jacken & Mäntel"},
            {"id": 3303, "title": "Babymonitore", "path": "Kinder > Schlafen & Bettzeug"},
        ]
        result = vinted_app._flatten_catalog_document(raw)
        paths = {item["id"]: item["path"] for item in result}
        self.assertEqual(paths[1037], "Damen > Kleidung > Jacken & Mäntel")
        self.assertEqual(paths[1773], "Damen > Kleidung > Jacken & Mäntel > Capes & Ponchos")
        self.assertEqual(paths[3303], "Kinder > Schlafen & Bettzeug > Babymonitore")

    def test_catalog_full_explicit_path_is_not_duplicated(self):
        raw = [{
            "id": 2525,
            "title": "Mäntel",
            "path": "Damen > Kleidung > Jacken & Mäntel > Mäntel",
        }]
        result = vinted_app._flatten_catalog_document(raw)
        self.assertEqual(result[0]["path"], "Damen > Kleidung > Jacken & Mäntel > Mäntel")

    def test_category_tree_never_exposes_parent_marked_as_leaf(self):
        catalogs = [
            {"id": 3477, "title": "Küchenhelfer", "path": "Home > Küchenhelfer", "leaf": True},
            {"id": 3478, "title": "Backen", "path": "Home > Küchenhelfer > Backen", "leaf": True},
        ]
        tree = vinted_app._build_category_tree(catalogs)
        encoded = json.dumps(tree, ensure_ascii=False)
        self.assertNotIn('"id": 3477', encoded)
        self.assertIn('"id": 3478', encoded)
        self.assertFalse(vinted_app._catalog_is_selectable({"catalogs": catalogs}, catalogs[0]))
        self.assertTrue(vinted_app._catalog_is_selectable({"catalogs": catalogs}, catalogs[1]))

    def test_category_tree_keeps_detailed_leaves_in_their_real_branch(self):
        catalogs = [
            {"id": 1, "title": "Kleider", "path": "Damen > Kleidung > Kleider", "leaf": True},
            {"id": 2, "title": "Blusen", "path": "Damen > Kleidung > Blusen", "leaf": True},
            {"id": 3, "title": "Abendkleider", "path": "Damen > Kleidung > Kleider > Abendkleider", "leaf": True},
        ]
        tree = vinted_app._build_category_tree(catalogs)
        damen = next(node for node in tree if node["title"] == "Damen")
        kleidung = next(node for node in damen["children"] if node["title"] == "Kleidung")
        self.assertEqual([node["title"] for node in kleidung["children"]], ["Blusen", "Kleider"])
        self.assertNotIn("Sonstiges", json.dumps(tree, ensure_ascii=False))

    def test_known_navigation_parent_is_never_selectable_or_rendered_as_a_leaf(self):
        parent = {"id": 77, "title": "Koch- und Backutensilien", "path": "Home > Koch- und Backutensilien", "leaf": True}
        metadata = {"catalogs": [parent]}
        self.assertFalse(vinted_app._catalog_is_selectable(metadata, parent))
        self.assertNotIn('"id": 77', json.dumps(vinted_app._build_category_tree([parent]), ensure_ascii=False))

    def test_cached_category_tree_uses_previous_schema_without_network(self):
        vinted_app.METADATA_CACHE_FILE.write_text(json.dumps({
            "schema": vinted_app.METADATA_CACHE_SCHEMA - 1,
            "fetched_at": vinted_app._now(),
            "catalogs": [{"id": 1, "title": "Sonstiges", "path": "Damen > Kleidung > Sonstiges", "leaf": True}],
        }), "utf-8")
        tree = vinted_app._cached_category_tree()
        self.assertTrue(tree)
        self.assertIn("Sonstiges", json.dumps(tree, ensure_ascii=False))

    def test_cached_metadata_recomputes_false_terminal_leaf_without_network(self):
        vinted_app.METADATA_CACHE_FILE.write_text(json.dumps({
            "schema": vinted_app.METADATA_CACHE_SCHEMA,
            "fetched_at": vinted_app._now(),
            "catalogs": [
                {"id": 3296, "title": "Schlafen & Bettzeug", "path": "Kinder > Schlafen & Bettzeug", "leaf": False},
                {"id": 3308, "title": "Schlafsäcke", "path": "Kinder > Schlafen & Bettzeug > Schlafsäcke", "leaf": False},
            ],
        }), "utf-8")
        cache = vinted_app._read_vinted_metadata_cache()
        rows = {int(row["id"]): row for row in cache["catalogs"]}
        self.assertFalse(rows[3296]["leaf"])
        self.assertTrue(rows[3308]["leaf"])
        tree = json.dumps(vinted_app._cached_category_tree(), ensure_ascii=False)
        self.assertIn('"id": 3308', tree)

    def test_category_form_search_is_local_and_clickable(self):
        template = (Path(vinted_app.__file__).parent / "templates" / "form.html").read_text("utf-8")
        self.assertIn('id="category-local-search"', template)
        self.assertIn("entry.radio.checked = true", template)
        self.assertNotIn('value="search_categories"', template)

    def test_verified_food_category_supplement_keeps_bottles_and_storage_as_real_leaves(self):
        supplement = vinted_app._verified_category_supplement_rows()
        paths = {row["path"] for row in supplement}
        self.assertIn("Home > Essen > Wasserflaschen", paths)
        self.assertIn("Home > Essen > Aufbewahrung von Lebensmitteln", paths)
        self.assertIn("Home > Essen > Tassen, Gläser & Kannen", paths)
        tree = vinted_app._build_category_tree(supplement)
        home = next(node for node in tree if node["title"] == "Home")
        essen = next(node for node in home["children"] if node["title"] == "Essen")
        labels = {node["title"] for node in essen["children"]}
        self.assertIn("Wasserflaschen", labels)
        self.assertIn("Aufbewahrung von Lebensmitteln", labels)
        self.assertNotIn("Sonstiges", labels)

    def test_catalog_selectability_uses_breadcrumb_segments_not_label_prefixes(self):
        catalogs = [
            {"id": 3308, "title": "Schlafsäcke", "path": "Kinder > Schlafen & Bettzeug > Schlafsäcke", "leaf": True},
            {"id": 3307, "title": "Schlafsäcke & Decken mit Ärmeln", "path": "Kinder > Schlafen & Bettzeug > Schlafsäcke & Decken mit Ärmeln", "leaf": True},
        ]
        self.assertTrue(vinted_app._catalog_is_selectable({"catalogs": catalogs}, catalogs[0]))

    def test_catalog_selectability_still_rejects_real_parent_with_child_segment(self):
        catalogs = [
            {"id": 3297, "title": "Bettzeug, Decken & Überwürfe", "path": "Kinder > Schlafen & Bettzeug > Bettzeug, Decken & Überwürfe", "leaf": True},
            {"id": 3301, "title": "Bettwäsche", "path": "Kinder > Schlafen & Bettzeug > Bettzeug, Decken & Überwürfe > Bettwäsche", "leaf": True},
        ]
        self.assertFalse(vinted_app._catalog_is_selectable({"catalogs": catalogs}, catalogs[0]))

    def test_known_rejected_categories_are_never_selectable(self):
        catalogs = [
            {"id": 3477, "title": "Küchenhelfer", "path": "Home > Küchenhelfer", "leaf": True},
            {"id": 5426, "title": "Lehrbücher & Lernmaterialien", "path": "Bücher & andere Medien > Bücher > Lehrbücher & Lernmaterialien", "leaf": True},
        ]
        tree = vinted_app._build_category_tree(catalogs)
        encoded = json.dumps(tree, ensure_ascii=False)
        self.assertNotIn('"id": 3477', encoded)
        self.assertNotIn('"id": 5426', encoded)
        self.assertFalse(vinted_app._catalog_is_selectable({"catalogs": catalogs}, catalogs[0]))
        self.assertFalse(vinted_app._catalog_is_selectable({"catalogs": catalogs}, catalogs[1]))

    def test_rejected_isbn_category_is_reset_without_losing_listing(self):
        draft = {
            "title": "Zwei Rezepthefte",
            "description": "Rezepte",
            "category": "Bücher > Lehrbücher",
            "category_id": "5426",
            "category_verified": True,
            "manual_review_confirmed": True,
            "brand": "Tupperware",
            "brand_id": "12",
            "condition_id": "1",
            "photos": [{"id": "one", "file": "one.jpg"}],
        }
        self.assertTrue(vinted_app._repair_known_blocked_category(draft))
        self.assertEqual(draft["category_id"], "")
        self.assertFalse(draft["category_verified"])
        self.assertFalse(draft["manual_review_confirmed"])
        self.assertEqual(draft["title"], "Zwei Rezepthefte")
        self.assertEqual(draft["photos"], [{"id": "one", "file": "one.jpg"}])
        self.assertIn("ISBN", draft["last_error"])

    def test_title_suggests_real_sandals_category(self):
        result = vinted_app._suggest_catalogs(self.metadata(), {"title": "Affenzahn Vegan Free Sandalen Gr. 32", "description": ""})
        self.assertTrue(result)
        self.assertEqual(result[0]["id"], 101)
        self.assertEqual(result[0]["path"], "Kinder > Schuhe > Sandalen")

    def test_unpublished_review_prefers_precise_title_over_broad_source_category(self):
        metadata = self.metadata()
        metadata["catalogs"].extend([
            {
                "id": 304,
                "title": "Kinder & junge Erwachsene",
                "path": "Bücher & andere Medien > Bücher > Kinder & junge Erwachsene",
                "size_group_id": None,
                "leaf": True,
            },
            {
                "id": 303,
                "title": "Comics, Mangas & Graphic Novels",
                "path": "Bücher & andere Medien > Bücher > Comics, Mangas & Graphic Novels",
                "size_group_id": None,
                "leaf": True,
            },
        ])
        draft = {
            "source_category": "Bücher",
            "title": "Manga Love Story Band 20–23",
            "description": "Manga-Set",
        }
        suggestions = vinted_app._suggest_catalogs(metadata, draft)
        self.assertEqual(suggestions[0]["id"], 303)
        self.assertEqual(vinted_app._auto_select_unpublished_category(suggestions, draft)["id"], 303)

    def test_unpublished_review_does_not_confirm_broad_source_category(self):
        suggestions = [
            {"id": 304, "title": "Kinder & junge Erwachsene", "path": "Bücher & andere Medien > Bücher > Kinder & junge Erwachsene", "score": 300},
            {"id": 303, "title": "Belletristik", "path": "Bücher & andere Medien > Bücher > Belletristik", "score": 299},
        ]
        draft = {"source_category": "Kinder", "title": "Sammlung", "description": ""}
        self.assertIsNone(vinted_app._auto_select_unpublished_category(suggestions, draft))

    def test_unpublished_review_keeps_specific_source_branch_manual_when_leaf_is_unclear(self):
        suggestions = [
            {"id": 101, "title": "Sandalen", "path": "Kinder > Schuhe > Sandalen", "score": 500, "_match_source": "source_category"},
            {"id": 102, "title": "Sneaker", "path": "Kinder > Schuhe > Sneaker", "score": 499, "_match_source": "source_category"},
        ]
        draft = {"source_category": "Kinder > Schuhe", "title": "Affenzahn Vegan Breezy Gr. 26", "description": ""}
        self.assertIsNone(vinted_app._auto_select_unpublished_category(suggestions, draft))

    def test_unpublished_review_uses_distinctive_article_terms_for_leaf_categories(self):
        suggestions = [
            {"id": 201, "title": "Barfußschuhe", "path": "Kinder > Schuhe > Barfußschuhe", "score": 500, "_match_source": "title"},
            {"id": 202, "title": "Sandalen", "path": "Kinder > Schuhe > Sandalen", "score": 499, "_match_source": "source_category"},
        ]
        draft = {"source_category": "Schuhe", "title": "Wildling Arrow Gr. 32 Barfußschuhe", "description": ""}
        self.assertEqual(vinted_app._auto_select_unpublished_category(suggestions, draft)["id"], 201)

    def test_unpublished_review_rejects_unqualified_womens_overall_category(self):
        suggestions = [{
            "id": 401,
            "title": "Overalls",
            "path": "Damen > Kleidung > Overalls",
            "score": 500,
            "_match_source": "title",
        }]
        draft = {"source_category": "Kleidung", "title": "Walk Overall Gr. 86/92", "description": ""}
        self.assertIsNone(vinted_app._auto_select_unpublished_category(suggestions, draft))

    def test_unpublished_review_rejects_unqualified_baby_clothing_category(self):
        suggestions = [{
            "id": 402,
            "title": "Bodys",
            "path": "Baby > Kleidung > Bodys",
            "score": 500,
            "_match_source": "title",
        }]
        draft = {"source_category": "Kleidung", "title": "Windelinge Walk Overall", "description": ""}
        self.assertIsNone(vinted_app._auto_select_unpublished_category(suggestions, draft))

    def test_unpublished_review_rejects_unqualified_boys_or_girls_branch(self):
        suggestions = [
            {"id": 403, "title": "Sneaker", "path": "Kinder > Mädchen > Schuhe > Sneaker", "score": 500, "_match_source": "title"},
            {"id": 404, "title": "Sneaker", "path": "Kinder > Jungs > Schuhe > Sneaker", "score": 499, "_match_source": "title"},
        ]
        draft = {"source_category": "Schuhe", "title": "Wildling Kordian Gr. 32 Barfußschuhe", "description": ""}
        self.assertIsNone(vinted_app._auto_select_unpublished_category(suggestions, draft))

    def test_unpublished_review_never_marks_automatic_proposal_as_processed(self):
        automatic_proposal = {
            "category": "Kinder > Schuhe > Barfußschuhe",
            "category_id": "201",
            "category_verified": False,
            "manual_review_confirmed": False,
        }
        self.assertEqual(vinted_app._draft_review_state(automatic_proposal), "unprocessed")
        legacy_without_confirmation = dict(automatic_proposal, category_verified=True)
        legacy_without_confirmation.pop("manual_review_confirmed")
        self.assertEqual(vinted_app._draft_review_state(legacy_without_confirmation), "unprocessed")
        manually_confirmed = dict(automatic_proposal, category_verified=True, manual_review_confirmed=True)
        self.assertEqual(vinted_app._draft_review_state(manually_confirmed), "processed")

    def test_category_learning_uses_only_manually_confirmed_choices(self):
        unconfirmed = {
            "title": "Affenzahn Breezy Sandalen Gr. 26",
            "brand": "Affenzahn",
            "category_id": "101",
            "category": "Kinder > Schuhe > Sandalen",
            "manual_review_confirmed": False,
        }
        vinted_app._remember_manual_category_choice(unconfirmed)
        self.assertEqual(vinted_app._load_category_learning(), [])

        confirmed = dict(unconfirmed, manual_review_confirmed=True)
        vinted_app._remember_manual_category_choice(confirmed)
        learned = vinted_app._learned_category_suggestions(
            self.metadata(),
            {"title": "Affenzahn Free Sandalen Gr. 32", "brand": "Affenzahn"},
        )
        self.assertEqual(learned[0]["id"], 101)
        self.assertEqual(learned[0]["_match_source"], "learned")

    def test_unpublished_review_uses_title_as_brand_search_fallback(self):
        self.assertEqual(
            vinted_app._unpublished_brand_keyword({"brand": "", "title": "Affenzahn Vegan Breezy Gr. 26"}),
            "Affenzahn",
        )

    def test_unpublished_review_maps_exact_brand_and_vinted_fields(self):
        draft = {
            "brand": "Affenzahn",
            "condition": "Sehr gut",
            "colour": "Blau",
            "package_size": "Klein",
            "brand_options": [{"id": 1, "label": "Keine Marke"}, {"id": 77, "label": "Affenzahn"}],
            "vinted_field_options": {
                "condition": vinted_app.VINTED_CONDITIONS,
                "colour": [{"id": 1, "label": "Blau"}],
                "package": [{"id": 1, "label": "Klein"}],
            },
        }
        changed = vinted_app._auto_fill_unpublished_fields(draft)
        self.assertEqual(draft["brand_id"], "77")
        self.assertEqual(draft["condition_id"], "2")
        self.assertEqual(draft["color_id"], "1")
        self.assertEqual(draft["package_size_id"], "1")
        self.assertEqual(len(changed), 4)

    def test_unpublished_review_infers_brand_colour_and_condition_from_article_text(self):
        draft = {
            "title": "Affenzahn Sandalen blau",
            "description": "Sehr gut erhalten",
            "brand_options": [{"id": 1, "label": "Keine Marke"}, {"id": 77, "label": "Affenzahn"}],
            "vinted_field_options": {
                "condition": vinted_app.VINTED_CONDITIONS,
                "colour": [{"id": 1, "label": "Blau"}, {"id": 2, "label": "Rot"}],
                "package": [{"id": 1, "label": "Klein"}, {"id": 2, "label": "Mittel"}],
            },
        }
        changed = vinted_app._auto_fill_unpublished_fields(draft)
        self.assertEqual(draft["brand_id"], "77")
        self.assertEqual(draft["condition_id"], "2")
        self.assertEqual(draft["color_id"], "1")
        self.assertEqual(draft["package_size_id"], "1")
        self.assertIn("Marke aus Titel/Beschreibung übernommen", changed)

    def test_unpublished_review_accepts_safe_brand_inflection(self):
        draft = {
            "title": "Wildling Kordian Gr. 32",
            "description": "",
            "brand": "Wildling",
            "brand_options": [{"id": 1, "label": "Keine Marke"}, {"id": 88, "label": "Wildlinge"}],
            "vinted_field_options": {},
        }
        changed = vinted_app._auto_fill_unpublished_fields(draft)
        self.assertEqual(draft["brand_id"], "88")
        self.assertIn("Marke übernommen", changed)

    def test_unpublished_review_infers_required_size_from_title(self):
        draft = {
            "title": "Affenzahn Breezy Gr. 26",
            "description": "",
            "vinted_requires_size": True,
            "vinted_field_options": {
                "size": [{"id": 260, "label": "26"}, {"id": 270, "label": "27"}],
            },
        }
        changed = vinted_app._auto_fill_unpublished_fields(draft)
        self.assertEqual(draft["size_id"], "260")
        self.assertEqual(draft["size"], "26")
        self.assertIn("Größe aus Titel/Beschreibung übernommen", changed)

    def test_unpublished_review_infers_combined_required_size_from_title(self):
        draft = {
            "title": "Walk Overall Gr. 86/92",
            "description": "",
            "vinted_requires_size": True,
            "vinted_field_options": {
                "size": [{"id": 8692, "label": "86/92"}],
            },
        }
        vinted_app._auto_fill_unpublished_fields(draft)
        self.assertEqual(draft["size_id"], "8692")
        self.assertEqual(draft["size"], "86/92")

    def test_category_search_only_returns_catalog_entries(self):
        result = vinted_app._search_catalog_metadata(self.metadata(), "Sandalen")
        self.assertEqual([item["id"] for item in result], [101])
        self.assertNotIn("Marke", [item["title"] for item in result])

    def test_category_search_matches_parent_path_for_comics(self):
        metadata = self.metadata()
        metadata["catalogs"].append({
            "id": 303,
            "title": "Comics, Mangas & Graphic Novels",
            "path": "Bücher & andere Medien > Bücher > Comics, Mangas & Graphic Novels",
            "size_group_id": None,
            "leaf": True,
        })
        result = vinted_app._search_catalog_metadata(metadata, "Bücher")
        self.assertIn(303, [item["id"] for item in result])
        comics = next(item for item in result if item["id"] == 303)
        self.assertEqual(comics["path"], "Bücher & andere Medien > Bücher > Comics, Mangas & Graphic Novels")

    def test_public_navigation_rows_preserve_books_branch_paths(self):
        rows = vinted_app._public_navigation_catalog_rows([
            {
                "id": 5425,
                "title": "Comics, Mangas & Graphic Novels",
                "path": "Bücher & andere Medien > Bücher > Comics, Mangas & Graphic Novels",
                "leaf": True,
            },
        ])
        self.assertEqual(rows[0]["id"], 5425)
        self.assertEqual(rows[0]["path"], "Bücher & andere Medien > Bücher > Comics, Mangas & Graphic Novels")
        self.assertTrue(rows[0]["leaf"])

    def test_category_search_refreshes_even_when_broad_cached_results_exist(self):
        stale = self.metadata()
        stale["catalogs"].append({
            "id": 301, "title": "Kinderbücher",
            "path": "Bücher & andere Medien > Bücher > Kinderbücher",
            "size_group_id": None, "leaf": True,
        })
        fresh = json.loads(json.dumps(stale))
        fresh["catalogs"].append({
            "id": 303, "title": "Comics, Mangas & Graphic Novels",
            "path": "Bücher & andere Medien > Bücher > Comics, Mangas & Graphic Novels",
            "size_group_id": None, "leaf": True,
        })
        with patch.object(vinted_app, "_load_vinted_metadata", side_effect=[stale, fresh]) as load:
            result = vinted_app._search_catalog_metadata_with_refresh("Bücher", 100)
        self.assertEqual(load.call_count, 2)
        self.assertIn(303, [item["id"] for item in result])

    def test_category_search_keeps_direct_public_navigation_rows(self):
        stale = self.metadata()
        stale["catalogs"] = [{
            "id": 2318,
            "title": "Kinder & junge Erwachsene",
            "path": "Bücher & andere Medien > Bücher > Kinder & junge Erwachsene",
            "size_group_id": None,
            "leaf": True,
        }]
        fresh = json.loads(json.dumps(stale))
        fresh["public_navigation_catalogs"] = [
            {
                "id": 2319,
                "title": "Belletristik",
                "path": "Bücher & andere Medien > Bücher > Belletristik",
                "leaf": True,
            },
            {
                "id": 5425,
                "title": "Comics, Mangas & Graphic Novels",
                "path": "Bücher & andere Medien > Bücher > Comics, Mangas & Graphic Novels",
                "leaf": True,
            },
        ]
        with patch.object(vinted_app, "_load_vinted_metadata", side_effect=[stale, fresh]), \
             patch.object(vinted_app, "_browser_fetch_json", side_effect=RuntimeError("not available")):
            result = vinted_app._search_catalog_metadata_with_refresh("Bücher", 100)
        self.assertEqual([item["id"] for item in result[:2]], [2319, 5425])
        self.assertIn(2318, [item["id"] for item in result])

    def test_metadata_load_merges_full_public_catalog_tree_for_books(self):
        full_tree = {"catalogs": [{
            "id": 10, "title": "Bücher & andere Medien", "catalogs": [{
                "id": 11, "title": "Bücher", "catalogs": [{
                    "id": 12, "title": "Comics, Mangas & Graphic Novels", "catalogs": []
                }]
            }]
        }]}
        initializer = {"catalogs": [{
            "id": 20, "title": "Bücher & andere Medien", "catalogs": [{
                "id": 21, "title": "Musik", "catalogs": []
            }]
        }]}
        upload = {"catalogs": [{
            "id": 30, "title": "Bücher & andere Medien", "catalogs": [{
                "id": 31, "title": "Video", "catalogs": []
            }]
        }]}
        colors = {"colors": [{"id": 1, "title": "Schwarz"}]}
        # Unscoped recursive initializer, legacy public catalog, filtered
        # initializer, upload catalog, colors.
        responses = [full_tree, {}, initializer, upload, colors]
        with patch.object(vinted_app, "_load_vinted_public_navigation_catalog", return_value=[]), \
             patch.object(vinted_app, "_browser_fetch_json", side_effect=responses):
            metadata = vinted_app._load_vinted_metadata(force=True)
        result = vinted_app._search_catalog_metadata(metadata, "Bücher")
        paths = [row["path"] for row in result]
        self.assertIn("Bücher & andere Medien > Bücher > Comics, Mangas & Graphic Novels", paths)
        self.assertNotIn("Bücher & andere Medien > Musik", paths)
        self.assertNotIn("Bücher & andere Medien > Video", paths)
        self.assertEqual(metadata["schema"], vinted_app.METADATA_CACHE_SCHEMA)

    def test_category_search_refreshes_vinted_catalog_after_cache_miss(self):
        draft_id = self.create_draft()
        stale = self.metadata()
        fresh = self.metadata()
        fresh["catalogs"].append({
            "id": 303,
            "title": "Comics, Mangas & Graphic Novels",
            "path": "Bücher & andere Medien > Bücher > Comics, Mangas & Graphic Novels",
            "size_group_id": None,
            "leaf": True,
        })
        with patch.object(vinted_app, "_load_vinted_metadata", side_effect=[stale, fresh]) as load:
            response = self.client.post(
                f"/drafts/{draft_id}/prepare-upload",
                data={
                    "title": "Manga Love Story Band 20–23",
                    "description": "Manga-Set",
                    "price": "15",
                    "brand": "",
                    "category_query": "Comics, Mangas & Graphic Novels",
                    "workflow_action": "search_categories",
                },
                follow_redirects=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(load.call_count, 2)
        draft = vinted_app._find_draft(draft_id)
        self.assertEqual(draft["category_suggestions"][0]["id"], 303)

    def test_suggest_route_uses_json_metadata_not_dom_workflow(self):
        draft_id = self.create_draft()
        with patch.object(vinted_app, "_load_vinted_metadata", return_value=self.metadata()), \
             patch.object(vinted_app, "_prepare_vinted_upload") as old_dom:
            response = self.client.post(
                f"/drafts/{draft_id}/prepare-upload",
                data={**self.draft_data(photos=(io.BytesIO(b""), "")), "workflow_action": "suggest_categories"},
                follow_redirects=True,
            )
        self.assertEqual(response.status_code, 200)
        old_dom.assert_not_called()
        draft = vinted_app._find_draft(draft_id)
        self.assertEqual(draft["category_suggestions"][0]["id"], 101)
        self.assertFalse(draft.get("category_verified"))

    def test_new_draft_category_suggestion_saves_before_lookup(self):
        with patch.object(vinted_app, "_load_vinted_metadata", return_value=self.metadata()):
            response = self.client.post(
                "/drafts/prepare-upload",
                data={**self.draft_data(), "workflow_action": "suggest_categories"},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 302)
        draft_id = response.headers["Location"].rsplit("/", 1)[-1]
        draft = vinted_app._find_draft(draft_id)
        self.assertIsNotNone(draft)
        self.assertEqual(len(draft["photos"]), 1)
        self.assertEqual(draft["category_suggestions"][0]["id"], 101)

    def test_new_draft_form_uses_autosaving_category_endpoint(self):
        with patch.object(vinted_app, "_load_vinted_metadata", return_value=self.metadata()):
            response = self.client.get("/drafts/new")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'action="/drafts/prepare-upload"', response.data)
        self.assertIn(b"Sandalen", response.data)
        self.assertNotIn("Browser-gestützter Direkt-Workflow".encode(), response.data)

    def test_untouched_import_opens_the_category_catalog_on_first_edit(self):
        draft = {
            "id": "imported-1", "title": "Affenzahn Sandalen", "description": "Gut", "price": "39",
            "category": "", "category_id": "", "category_verified": False,
            "status": "Unbearbeitet", "source_platform": "kleinanzeigen", "photos": [],
        }
        vinted_app._save_drafts([draft])
        with patch.object(vinted_app, "_load_vinted_metadata", return_value=self.metadata()) as load:
            response = self.client.get("/drafts/imported-1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(load.call_count, 1)
        self.assertIn(b"Sandalen", response.data)
        saved = vinted_app._find_draft("imported-1")
        self.assertEqual(saved["status"], "Kategorie auswaehlen")
        self.assertTrue(saved["category_catalog_auto_opened_at"])

    def test_edited_import_does_not_auto_open_the_category_catalog(self):
        draft = {
            "id": "imported-2", "title": "Affenzahn Sandalen", "description": "Gut", "price": "39",
            "category": "", "category_id": "", "category_verified": False,
            "status": "Unbearbeitet", "source_platform": "kleinanzeigen", "manager_edited_at": vinted_app._now(), "photos": [],
        }
        vinted_app._save_drafts([draft])
        with patch.object(vinted_app, "_load_vinted_metadata") as load:
            response = self.client.get("/drafts/imported-2")
        self.assertEqual(response.status_code, 200)
        load.assert_not_called()
        self.assertNotIn(b"category-tree-list", response.data)

    def test_select_category_loads_size_colors_and_brand_ids(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        draft["category_suggestions"] = [{"id": 101, "path": "Kinder > Schuhe > Sandalen"}]
        vinted_app._replace_draft(draft)
        with patch.object(vinted_app, "_load_vinted_metadata", return_value=self.metadata()), \
             patch.object(vinted_app, "_load_category_runtime_options", return_value={
                 "size": [{"id": 320, "label": "32"}],
                 "condition": vinted_app.VINTED_CONDITIONS,
                 "material": [],
                 "package": [{"id": 1, "label": "Klein"}],
                 "package_error": "",
                 "attributes_error": "",
             }), \
             patch.object(vinted_app, "_search_vinted_brands", return_value=[{"id": 77, "label": "Affenzahn"}]):
            response = self.client.post(
                f"/drafts/{draft_id}/prepare-upload",
                data={
                    "title": "Affenzahn Sandalen Gr. 32", "description": "Gut", "price": "39", "brand": "Affenzahn",
                    "category_id": "101", "workflow_action": "select_category",
                },
                follow_redirects=True,
            )
        self.assertEqual(response.status_code, 200)
        draft = vinted_app._find_draft(draft_id)
        self.assertTrue(draft["category_verified"])
        self.assertEqual(draft["category"], "Kinder > Schuhe > Sandalen")
        self.assertEqual(draft["vinted_field_options"]["size"][0]["label"], "32")
        self.assertEqual(draft["brand_options"][0]["id"], 77)

    def test_retired_category_id_is_remapped_by_its_current_vinted_path(self):
        metadata = {
            "catalogs": [{"id": 202, "path": "Kinder > Schuhe > Sandalen", "leaf": True, "size_group_id": 7}],
            "colors": [{"id": 3, "label": "Blau"}],
        }
        draft = {
            "category_verified": True,
            "category_id": "101",
            "category": "Kinder > Schuhe > Sandalen",
            "manual_review_confirmed": True,
            "vinted_field_options": {},
        }
        with patch.object(vinted_app, "_load_vinted_metadata", return_value=metadata), \
             patch.object(vinted_app, "_load_category_runtime_options", return_value={
                 "size": [], "condition": vinted_app.VINTED_CONDITIONS, "material": [], "package": [{"id": 1, "label": "Klein"}],
                 "requires_size": False, "size_group_id": None, "package_error": "", "attributes_error": "",
             }):
            vinted_app._refresh_selected_category_runtime(draft)
        self.assertEqual(draft["category_id"], "202")
        self.assertFalse(draft["manual_review_confirmed"])
        self.assertIn("aktualisiert", draft["status"])

    def test_all_unpublished_drafts_with_retired_category_ids_are_remapped(self):
        metadata = {
            "catalogs": [{"id": 202, "path": "Kinder > Schuhe > Sandalen", "leaf": True}],
            "colors": [],
        }
        drafts = [
            {"category_verified": True, "category_id": "101", "category": "Kinder > Schuhe > Sandalen", "manual_review_confirmed": True},
            {"category_verified": True, "category_id": "202", "category": "Kinder > Schuhe > Sandalen", "manual_review_confirmed": True},
            {"category_verified": True, "category_id": "101", "category": "Kinder > Schuhe > Sandalen", "published_item_id": "live"},
        ]
        with patch.object(vinted_app, "_load_vinted_metadata", return_value=metadata):
            repaired = vinted_app._remap_retired_draft_categories(drafts)
        self.assertEqual(repaired, 1)
        self.assertEqual(drafts[0]["category_id"], "202")
        self.assertFalse(drafts[0]["manual_review_confirmed"])
        self.assertEqual(drafts[2]["category_id"], "101")

    def test_browser_fetch_json_runs_inside_vinted_page(self):
        page = {"webSocketDebuggerUrl": "ws://example"}
        with patch.object(vinted_app, "_wait_for_vinted_page", return_value=page), \
             patch.object(vinted_app, "_cdp_command", return_value={"result": {"value": {"ok": True, "status": 200, "text": '{"colors":[]}'}}}) as cdp:
            result = vinted_app._browser_fetch_json("/api/v2/item_upload/colors")
        self.assertEqual(result, {"colors": []})
        expression = cdp.call_args.args[2]["expression"]
        self.assertIn("/api/v2/item_upload/colors", expression)
        self.assertIn("credentials", expression)
        self.assertIn("include", expression)


    def test_metadata_uses_publication_endpoints_not_removed_initializer(self):
        catalogs = {"catalogs": [{"id": 1, "title": "Kinder", "catalogs": [{"id": 2, "title": "Schuhe", "catalogs": []}]}]}
        colors = {"colors": [{"id": 10, "title": "Blau"}]}
        with patch.object(vinted_app, "_load_vinted_public_navigation_catalog", return_value=[]), \
             patch.object(vinted_app, "_browser_fetch_json", side_effect=[catalogs, catalogs, catalogs, catalogs, colors]) as fetch:
            result = vinted_app._load_vinted_metadata(force=True)
        called_paths = [call.args[0] for call in fetch.call_args_list]
        self.assertTrue(called_paths[0].startswith("/api/v2/catalog/initializers?page=1"))
        self.assertEqual(called_paths[-1], "/api/v2/item_upload/colors")
        self.assertTrue(any(path.startswith("/api/v2/catalog/initializers") for path in called_paths))
        self.assertEqual(result["schema"], vinted_app.METADATA_CACHE_SCHEMA)
        self.assertTrue(result["catalogs"])

    def test_runtime_attributes_use_item_upload_endpoint(self):
        attributes = {"attributes": [{"code": "size", "values": [{"id": 320, "title": "32"}]}]}
        packages = {"package_sizes": [{"id": 1, "title": "Klein"}]}
        with patch.object(vinted_app, "_vinted_dynamic_attribute_headers", return_value={}), \
             patch.object(vinted_app, "_resolve_size_group_id", return_value=None), \
             patch.object(vinted_app, "_browser_fetch_json", side_effect=[attributes, packages]) as fetch:
            result = vinted_app._load_category_runtime_options(101)
        self.assertEqual(result["size"][0]["id"], 320)
        self.assertEqual(result["package"][0]["id"], 1)
        first = fetch.call_args_list[0]
        self.assertEqual(first.args[0], "/api/v2/item_upload/attributes")
        self.assertEqual(first.kwargs["method"], "POST")

    def test_auth_cookie_is_read_from_real_browser_session(self):
        page = {"webSocketDebuggerUrl": "ws://example"}
        cookies = [
            {"domain": ".vinted.de", "name": "access_token_web", "value": "secret-token"},
            {"domain": ".vinted.de", "name": "refresh_token_web", "value": "refresh"},
            {"domain": ".example.org", "name": "other", "value": "ignore"},
        ]
        with patch.object(vinted_app, "_wait_for_vinted_page", return_value=page), \
             patch.object(vinted_app, "_cdp_command", return_value={"cookies": cookies}):
            result = vinted_app._vinted_auth_cookies()
        self.assertEqual(result["access_token_web"], "secret-token")
        self.assertNotIn("other", result)

    def test_uploader_csv_contains_vinted_ids_and_ordered_images(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        draft.update({
            "category_id": "101", "brand_id": "77", "brand": "Affenzahn", "size_id": "320",
            "condition_id": "2", "color_id": "1", "package_size_id": "1",
        })
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = vinted_app._build_uploader_csv(draft, Path(tmp))
            with csv_path.open(encoding="utf-8", newline="") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["catalog_id"], "101")
            self.assertEqual(row["brand_id"], "77")
            self.assertEqual(row["size_id"], "320")
            self.assertEqual(row["condition_ids"], "2")
            self.assertEqual(row["color_ids"], "1")
            self.assertTrue((Path(tmp) / "images" / "01.jpg").is_file())

    def test_workflow_failure_is_shown_in_app_instead_of_raw_500(self):
        draft_id = self.create_draft()
        with patch.object(vinted_app, "_load_vinted_metadata", side_effect=RuntimeError("API Testfehler")):
            response = self.client.post(
                f"/drafts/{draft_id}/prepare-upload",
                data={"title": "Test", "description": "Test", "price": "10", "brand": "Test", "workflow_action": "suggest_categories"},
                follow_redirects=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"API Testfehler", response.data)
        self.assertEqual(vinted_app._find_draft(draft_id)["status"], "Fehler")

    def test_form_keeps_the_workflow_out_of_the_way(self):
        response = self.client.get("/drafts/new")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Kategorien vorschlagen".encode(), response.data)
        self.assertNotIn("Browser-gestützter Direkt-Workflow".encode(), response.data)


    def test_datadome_response_becomes_manual_security_challenge(self):
        challenge = "https://geo.captcha-delivery.com/interstitial/?initialCid=test&cid=abc"
        page = {"id": "publish-tab", "url": "https://www.vinted.de/items/new"}
        with patch.object(vinted_app, "_open_security_challenge", return_value="publish-tab") as opener:
            with self.assertRaises(vinted_app.VintedSecurityChallenge) as raised:
                vinted_app._raise_for_browser_response(
                    {"ok": False, "status": 403, "url": "/api/v2/item_upload/items", "text": json.dumps({"url": challenge})},
                    "/api/v2/item_upload/items",
                    page=page,
                )
        self.assertEqual(raised.exception.challenge_url, challenge)
        self.assertEqual(raised.exception.challenge_target_id, "publish-tab")
        opener.assert_called_once_with(challenge, page=page)

    def test_security_clearance_tracks_exact_challenge_tab_before_retry(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        draft.update({
            "security_challenge_required": True,
            "security_challenge_target_id": "publish-tab",
            "security_challenge_state": "waiting",
            "security_challenge_deadline_at": (vinted_app.datetime.now(vinted_app.timezone.utc) + vinted_app.timedelta(minutes=5)).isoformat(timespec="seconds"),
        })
        vinted_app._replace_draft(draft)
        challenge_target = {
            "id": "publish-tab", "type": "page", "webSocketDebuggerUrl": "ws://publish",
            "url": "https://geo.captcha-delivery.com/captcha",
        }
        cleared_target = {
            "id": "publish-tab", "type": "page", "webSocketDebuggerUrl": "ws://publish",
            "url": "https://www.vinted.de/items/new",
        }
        with patch.object(vinted_app, "_debug_targets", side_effect=[[challenge_target], [cleared_target]]), \
             patch.object(vinted_app.time, "sleep"):
            self.assertTrue(vinted_app._wait_for_security_clearance(draft))
        saved = vinted_app._find_draft(draft_id)
        self.assertEqual(saved["security_challenge_state"], "cleared")
        self.assertEqual(saved["security_challenge_target_id"], "publish-tab")
        self.assertTrue(saved.get("security_challenge_cleared_at"))

    def test_security_success_marker_does_not_require_visible_dimensions(self):
        page = {
            "id": "publish-tab", "type": "page",
            "webSocketDebuggerUrl": "ws://publish",
            "url": "https://geo.captcha-delivery.com/captcha",
        }
        with patch.object(vinted_app, "_cdp_command", return_value={"result": {"value": True}}) as cdp:
            self.assertTrue(vinted_app._security_challenge_success_visible(page))
        expression = cdp.call_args.args[2]["expression"]
        self.assertIn("#captcha-success", expression)
        self.assertNotIn("getBoundingClientRect", expression)
        self.assertNotIn("getComputedStyle", expression)

    def test_security_record_captures_all_datadome_cookie_values_as_baseline(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        challenge = vinted_app.VintedSecurityChallenge(
            "Sicherheitsprüfung",
            "https://geo.captcha-delivery.com/captcha/?initialCid=start&cid=old-cookie",
            "publish-tab",
        )
        page = {
            "id": "publish-tab", "type": "page", "webSocketDebuggerUrl": "ws://publish",
            "url": challenge.challenge_url,
        }
        with patch.object(vinted_app, "_security_challenge_target", return_value=page), \
             patch.object(vinted_app, "_security_challenge_datadome_cookies", return_value={"old-cookie", "host-cookie"}):
            self.assertTrue(vinted_app._record_security_challenge(draft, challenge))
        self.assertEqual(set(draft["security_challenge_datadome_before"]), {"old-cookie", "host-cookie"})

    def test_security_clearance_resumes_on_new_profile_cookie_without_waiting_for_captcha_redirect(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        draft.update({
            "security_challenge_required": True,
            "security_challenge_target_id": "publish-tab",
            "security_challenge_url": "https://geo.captcha-delivery.com/captcha/?initialCid=start&cid=old-cookie",
            "security_challenge_datadome_before": ["old-cookie", "host-cookie"],
            "security_challenge_state": "waiting",
            "security_challenge_deadline_at": (vinted_app.datetime.now(vinted_app.timezone.utc) + vinted_app.timedelta(minutes=5)).isoformat(timespec="seconds"),
        })
        vinted_app._replace_draft(draft)
        challenge_target = {
            "id": "publish-tab", "type": "page", "webSocketDebuggerUrl": "ws://publish",
            "url": "https://geo.captcha-delivery.com/captcha/?initialCid=start&cid=old-cookie",
        }
        with patch.object(vinted_app, "_security_challenge_target", return_value=challenge_target), \
             patch.object(vinted_app, "_security_challenge_success_visible", return_value=False), \
             patch.object(vinted_app, "_security_challenge_datadome_cookies", return_value={"old-cookie", "host-cookie", "new-cookie"}), \
             patch.object(vinted_app.time, "sleep"):
            self.assertTrue(vinted_app._wait_for_security_clearance(draft))
        saved = vinted_app._find_draft(draft_id)
        self.assertEqual(saved["security_challenge_state"], "cleared")

    def test_security_clearance_resumes_after_green_slider_even_if_captcha_page_stays_open(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        draft.update({
            "security_challenge_required": True,
            "security_challenge_notification_open": True,
            "security_challenge_target_id": "publish-tab",
            "security_challenge_url": "https://geo.captcha-delivery.com/captcha/?initialCid=start&cid=old-cookie",
            "security_challenge_datadome_before": ["old-cookie"],
            "security_challenge_state": "waiting",
            "security_challenge_deadline_at": (vinted_app.datetime.now(vinted_app.timezone.utc) + vinted_app.timedelta(minutes=5)).isoformat(timespec="seconds"),
        })
        vinted_app._replace_draft(draft)
        challenge_target = {
            "id": "publish-tab", "type": "page", "webSocketDebuggerUrl": "ws://publish",
            "url": "https://geo.captcha-delivery.com/captcha/?initialCid=start&cid=old-cookie",
        }
        with patch.object(vinted_app, "_security_challenge_target", return_value=challenge_target), \
             patch.object(vinted_app, "_security_challenge_success_visible", return_value=True), \
             patch.object(vinted_app, "_security_challenge_datadome_cookies", return_value={"old-cookie"}), \
             patch.object(vinted_app.time, "sleep"):
            self.assertTrue(vinted_app._wait_for_security_clearance(draft))
        saved = vinted_app._find_draft(draft_id)
        self.assertEqual(saved["security_challenge_state"], "cleared")
        self.assertNotIn("security_challenge_notification_open", saved)

    def test_security_clearance_does_not_resume_without_profile_change_or_success_marker(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        draft.update({
            "security_challenge_required": True,
            "security_challenge_target_id": "publish-tab",
            "security_challenge_url": "https://geo.captcha-delivery.com/captcha/?initialCid=start&cid=old-cookie",
            "security_challenge_datadome_before": ["old-cookie"],
            "security_challenge_state": "waiting",
            "security_challenge_deadline_at": (vinted_app.datetime.now(vinted_app.timezone.utc) - vinted_app.timedelta(seconds=1)).isoformat(timespec="seconds"),
        })
        challenge_target = {
            "id": "publish-tab", "type": "page", "webSocketDebuggerUrl": "ws://publish",
            "url": "https://geo.captcha-delivery.com/captcha/?initialCid=start&cid=old-cookie",
        }
        with patch.object(vinted_app, "_security_challenge_target", return_value=challenge_target), \
             patch.object(vinted_app, "_security_challenge_success_visible", return_value=False), \
             patch.object(vinted_app, "_security_challenge_datadome_cookies", return_value={"old-cookie"}), \
             patch.object(vinted_app.time, "sleep"):
            self.assertFalse(vinted_app._wait_for_security_clearance(draft))

    def test_security_network_event_accepts_successful_datadome_post(self):
        requests = {}
        request = {
            "method": "Network.requestWillBeSent",
            "params": {
                "requestId": "verify-1",
                "type": "Fetch",
                "request": {
                    "url": "https://geo.captcha-delivery.com/captcha/check?cid=abc",
                    "method": "POST",
                },
            },
        }
        self.assertFalse(vinted_app._security_challenge_network_event_is_clearance(request, requests))
        response = {
            "method": "Network.responseReceived",
            "params": {
                "requestId": "verify-1",
                "type": "Fetch",
                "response": {
                    "url": "https://geo.captcha-delivery.com/captcha/check?cid=abc",
                    "status": 200,
                    "headers": {},
                },
            },
        }
        self.assertTrue(vinted_app._security_challenge_network_event_is_clearance(response, requests))

    def test_security_network_event_ignores_static_captcha_asset(self):
        requests = {}
        request = {
            "method": "Network.requestWillBeSent",
            "params": {
                "requestId": "asset-1",
                "type": "Image",
                "request": {
                    "url": "https://geo.captcha-delivery.com/assets/shield.png",
                    "method": "GET",
                },
            },
        }
        vinted_app._security_challenge_network_event_is_clearance(request, requests)
        response = {
            "method": "Network.responseReceived",
            "params": {
                "requestId": "asset-1",
                "type": "Image",
                "response": {
                    "url": "https://geo.captcha-delivery.com/assets/shield.png",
                    "status": 200,
                    "headers": {},
                },
            },
        }
        self.assertFalse(vinted_app._security_challenge_network_event_is_clearance(response, requests))

    def test_security_network_event_ignores_datadome_telemetry_post(self):
        requests = {}
        request = {
            "method": "Network.requestWillBeSent",
            "params": {
                "requestId": "telemetry-1",
                "type": "Fetch",
                "request": {
                    "url": "https://geo.captcha-delivery.com/log/event",
                    "method": "POST",
                },
            },
        }
        vinted_app._security_challenge_network_event_is_clearance(request, requests)
        response = {
            "method": "Network.responseReceived",
            "params": {
                "requestId": "telemetry-1",
                "type": "Fetch",
                "response": {
                    "url": "https://geo.captcha-delivery.com/log/event",
                    "status": 200,
                    "headers": {},
                },
            },
        }
        self.assertFalse(vinted_app._security_challenge_network_event_is_clearance(response, requests))

    def test_security_network_event_accepts_datadome_set_cookie(self):
        requests = {
            "verify-2": {
                "url": "https://geo.captcha-delivery.com/captcha/check",
                "method": "POST",
                "type": "Fetch",
            }
        }
        extra = {
            "method": "Network.responseReceivedExtraInfo",
            "params": {
                "requestId": "verify-2",
                "headers": {"set-cookie": "datadome=new-clearance; Path=/; Secure"},
            },
        }
        self.assertTrue(vinted_app._security_challenge_network_event_is_clearance(extra, requests))

    def test_security_manual_continue_fallback_releases_waiting_job(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        draft.update({
            "security_challenge_required": True,
            "security_challenge_target_id": "publish-tab",
            "security_challenge_url": "https://geo.captcha-delivery.com/captcha/?cid=old-cookie",
            "security_challenge_datadome_before": ["old-cookie"],
            "security_challenge_state": "waiting",
            "security_challenge_deadline_at": (vinted_app.datetime.now(vinted_app.timezone.utc) + vinted_app.timedelta(minutes=5)).isoformat(timespec="seconds"),
        })
        vinted_app._replace_draft(draft)
        challenge_target = {
            "id": "publish-tab", "type": "page", "webSocketDebuggerUrl": "ws://publish",
            "url": "https://geo.captcha-delivery.com/captcha/?cid=old-cookie",
        }
        with patch.object(vinted_app, "_security_challenge_target", return_value=challenge_target), \
             patch.object(vinted_app, "_security_challenge_network_listener", return_value=None), \
             patch.object(vinted_app, "_security_challenge_install_continue_control"), \
             patch.object(vinted_app, "_security_challenge_manual_continue_requested", return_value=True), \
             patch.object(vinted_app, "_security_challenge_success_visible", return_value=False), \
             patch.object(vinted_app, "_security_challenge_datadome_cookies", return_value={"old-cookie"}), \
             patch.object(vinted_app.time, "sleep"):
            self.assertTrue(vinted_app._wait_for_security_clearance(draft))
        saved = vinted_app._find_draft(draft_id)
        self.assertEqual(saved["security_challenge_state"], "cleared")

    def test_security_fallback_control_contains_manual_continue_button(self):
        page = {
            "id": "publish-tab", "type": "page", "webSocketDebuggerUrl": "ws://publish",
            "url": "https://geo.captcha-delivery.com/captcha",
        }
        with patch.object(vinted_app, "_cdp_command", return_value={}) as cdp:
            vinted_app._security_challenge_install_continue_control(page)
        expression = cdp.call_args.args[2]["expression"]
        self.assertIn("Prüfung abgeschlossen", expression)
        self.assertIn("__vintedManagerSecurityContinueRequested", expression)


    def test_publish_retry_reuses_cleared_security_tab(self):
        draft = {
            "id": "draft-1", "title": "Testjacke",
            "security_challenge_state": "cleared",
            "security_challenge_target_id": "publish-tab",
        }
        target = {
            "id": "publish-tab", "type": "page", "webSocketDebuggerUrl": "ws://publish",
            "url": "https://www.vinted.de/items/new",
        }
        previous = vinted_app._primary_browser_target_id
        vinted_app._primary_browser_target_id = "main-tab"
        try:
            with patch.object(vinted_app, "_security_challenge_target", return_value=target), \
                 patch.object(vinted_app, "_open_vinted_target") as open_new, \
                 patch.object(vinted_app, "_set_publish_tab_status"):
                selected, old_target = vinted_app._open_visible_publish_target(draft)
            self.assertEqual(selected["id"], "publish-tab")
            self.assertEqual(old_target, "main-tab")
            self.assertEqual(vinted_app._primary_browser_target_id, "publish-tab")
            open_new.assert_not_called()
        finally:
            vinted_app._primary_browser_target_id = previous

    def test_solved_security_check_opens_exactly_one_fresh_publish_tab(self):
        draft = {
            "id": "draft-1", "title": "Testjacke",
            "security_challenge_state": "cleared",
            "security_challenge_target_id": "publish-tab",
            "security_challenge_url": "https://geo.captcha-delivery.com/captcha/?cid=old",
            "security_challenge_force_fresh_publish": True,
        }
        fresh = {
            "id": "fresh-publish", "type": "page",
            "url": "https://www.vinted.de/items/new", "webSocketDebuggerUrl": "ws://fresh",
        }
        with patch.object(vinted_app, "_open_vinted_target", return_value=fresh) as open_new, \
             patch.object(vinted_app, "_set_publish_tab_status"):
            target, _previous = vinted_app._open_visible_publish_target(draft)
        self.assertEqual(target["id"], "fresh-publish")
        open_new.assert_called_once()
        self.assertTrue(open_new.call_args.kwargs.get("security_redirect_is_challenge"))
        self.assertTrue(open_new.call_args.kwargs.get("renavigate_vinted_once"))
        self.assertGreaterEqual(int(open_new.call_args.kwargs.get("timeout") or 0), 40)
        self.assertNotIn("security_challenge_force_fresh_publish", draft)


    def test_fresh_publish_target_preserves_captcha_redirect_as_security_challenge(self):
        created = {
            "id": "fresh-publish", "type": "page",
            "url": "https://www.vinted.de/items/new", "webSocketDebuggerUrl": "ws://fresh",
        }
        captcha = {
            **created,
            "url": "https://geo.captcha-delivery.com/captcha/?cid=next-check",
        }
        response = io.BytesIO(json.dumps(created).encode("utf-8"))
        with patch.object(vinted_app, "_wait_for_vinted_page", return_value={"id": "main"}), \
             patch.object(vinted_app, "urlopen", return_value=response), \
             patch.object(vinted_app, "_refresh_browser_target", return_value=captcha), \
             patch.object(vinted_app, "_close_browser_target") as close_target:
            with self.assertRaises(vinted_app.VintedSecurityChallenge) as raised:
                vinted_app._open_vinted_target(
                    vinted_app.VINTED_NEW_ITEM_URL,
                    "document.readyState !== 'loading' && location.pathname.startsWith('/items/new')",
                    timeout=1,
                    security_redirect_is_challenge=True,
                    renavigate_vinted_once=True,
                )
        self.assertEqual(raised.exception.challenge_target_id, "fresh-publish")
        self.assertIn("captcha-delivery.com", raised.exception.challenge_url)
        close_target.assert_not_called()

    def test_explicit_renew_retry_reuses_the_visible_vinted_tab(self):
        draft = {
            "id": "draft-retry", "title": "Testjacke",
            "security_challenge_required": True,
            "security_challenge_state": "waiting",
            "security_challenge_retry_requested_at": vinted_app._now(),
        }
        visible_tab = {
            "id": "vinted-home", "type": "page",
            "url": "https://www.vinted.de/", "webSocketDebuggerUrl": "ws://home",
        }

        def cdp_response(_target, method, _params, **_kwargs):
            if method == "Runtime.evaluate":
                return {"result": {"value": True}}
            return {}

        with patch.object(vinted_app, "_vinted_page_target", return_value=visible_tab), \
             patch.object(vinted_app, "_refresh_browser_target", return_value=visible_tab), \
             patch.object(vinted_app, "_cdp_command", side_effect=cdp_response), \
             patch.object(vinted_app, "_open_vinted_target") as open_new:
            target, _previous = vinted_app._open_visible_publish_target(draft)

        self.assertEqual(target["id"], "vinted-home")
        open_new.assert_not_called()
        self.assertNotIn("security_challenge_retry_requested_at", draft)

    def test_waiting_security_worker_leaves_wait_loop_for_explicit_retry(self):
        draft = {
            "id": "draft-waiting-retry",
            "security_challenge_state": "waiting",
            "security_challenge_retry_requested_at": vinted_app._now(),
        }
        self.assertTrue(vinted_app._wait_for_security_clearance(draft))

    def test_index_shows_security_continue_controls_for_waiting_renewal(self):
        draft_id = self.create_draft(title="Wartende Erneuerung")
        draft = vinted_app._find_draft(draft_id)
        draft.update({
            "published_item_id": "111", "renewal_upload_pending": True,
            "security_challenge_required": True, "security_challenge_state": "waiting",
        })
        vinted_app._replace_draft(draft)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Prüfung erledigt – fortsetzen".encode(), response.data)
        self.assertIn("Sicherheitsabfrage öffnen".encode(), response.data)

    def test_index_shows_security_controls_when_challenge_happens_before_delete(self):
        draft_id = self.create_draft(title="Clarks Herren Sneaker")
        draft = vinted_app._find_draft(draft_id)
        draft.update({
            "published_item_id": "111",
            "security_challenge_required": True, "security_challenge_state": "waiting",
        })
        draft.pop("renewal_upload_pending", None)
        vinted_app._replace_draft(draft)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Prüfung erledigt – fortsetzen".encode(), response.data)
        self.assertIn(f"/drafts/{draft_id}/security-browser".encode(), response.data)

    def test_security_challenge_renewal_notifies_only_primarys_iphone(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        draft.update({
            "published_item_id": "111", "published_url": "https://www.vinted.de/items/111",
            "published_at": vinted_app._now(), "last_renewed_at": vinted_app._now(), "publish_count": 1,
        })
        vinted_app._replace_draft(draft)
        listing = {"published_item_id": "111", "published_url": "https://www.vinted.de/items/111"}
        challenge = vinted_app.VintedSecurityChallenge("Sicherheitsprüfung", "https://geo.captcha-delivery.com/captcha")
        with patch.object(vinted_app, "_create_backup"), \
             patch.object(vinted_app, "_load_live_vinted_items", return_value=[listing]), \
             patch.object(vinted_app, "_run_vinted_listing_action", return_value={"ok": True}), \
             patch.object(vinted_app, "_wait_for_live_action", return_value={}), \
             patch.object(vinted_app, "_run_browser_direct_upload", side_effect=challenge), \
             patch.object(vinted_app, "_notify_vinted_security_challenge", return_value=True) as notify:
            with self.assertRaises(vinted_app.VintedSecurityChallenge):
                vinted_app._renew_vinted_draft(draft_id, automatic=False)
        current = vinted_app._find_draft(draft_id)
        self.assertEqual(current["status"], "Sicherheitsprüfung erforderlich")
        self.assertTrue(current["security_challenge_required"])
        self.assertTrue(current["security_challenge_notification_open"])
        notify.assert_called_once_with(current)

    def test_security_challenge_notification_is_silent_critical_and_opens_affected_draft(self):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False

        draft = {"id": "draft-42", "title": "Affenzahn Sandalen"}
        (vinted_app.DATA_DIR / "options.json").write_text(
            json.dumps({"notify_service": "notify.mobile_app_primary_private"}), "utf-8"
        )
        with patch.dict(vinted_app.os.environ, {"SUPERVISOR_TOKEN": "token"}), \
             patch.object(vinted_app, "urlopen", return_value=Response()) as request_call:
            self.assertTrue(vinted_app._notify_vinted_security_challenge(draft))
        payload = json.loads(request_call.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(payload["data"]["url"], "http://192.168.10.199:8153/vinted-browser")
        self.assertEqual(payload["data"]["push"]["sound"], {"name": "default", "critical": 1, "volume": 0.0})

    def test_renewal_live_lookup_retries_transient_websocket_timeout(self):
        listing = {"published_item_id": "111", "published_url": "https://www.vinted.de/items/111"}
        timeout = vinted_app.websocket.WebSocketTimeoutException("Connection timed out")
        with patch.object(vinted_app, "_load_live_vinted_items", side_effect=[timeout, [listing]]) as load_live, \
             patch.object(vinted_app.time, "sleep"):
            result = vinted_app._load_live_vinted_items_for_renewal()
        self.assertEqual(result, [listing])
        self.assertEqual(load_live.call_count, 2)

    def test_renewal_delete_timeout_does_not_reclick_when_live_confirms_deletion(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        draft.update({
            "published_item_id": "111", "published_url": "https://www.vinted.de/items/111",
            "published_at": vinted_app._now(), "last_renewed_at": vinted_app._now(), "publish_count": 1,
        })
        vinted_app._replace_draft(draft)
        listing = {"published_item_id": "111", "published_url": "https://www.vinted.de/items/111"}
        timeout = vinted_app.websocket.WebSocketTimeoutException("Connection timed out")
        with patch.object(vinted_app, "_create_backup"), \
             patch.object(vinted_app, "_load_live_vinted_items_for_renewal", return_value=[listing]), \
             patch.object(vinted_app, "_run_vinted_listing_action", side_effect=timeout) as delete_action, \
             patch.object(vinted_app, "_wait_for_live_action", return_value={"published_item_id": "111", "live_state": "sold"}), \
             patch.object(vinted_app, "_run_browser_direct_upload", return_value={"item_id": "222", "item_url": "https://www.vinted.de/items/222"}), \
             patch.object(vinted_app, "_load_live_vinted_items", return_value=[]):
            result = vinted_app._renew_vinted_draft(draft_id, automatic=False)
        self.assertTrue(result["ok"])
        delete_action.assert_called_once()
        self.assertEqual(vinted_app._find_draft(draft_id)["published_item_id"], "222")

    def test_renewal_delete_timeout_retries_once_only_when_old_item_still_live(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        draft.update({
            "published_item_id": "111", "published_url": "https://www.vinted.de/items/111",
            "published_at": vinted_app._now(), "last_renewed_at": vinted_app._now(), "publish_count": 1,
        })
        vinted_app._replace_draft(draft)
        listing = {"published_item_id": "111", "published_url": "https://www.vinted.de/items/111"}
        timeout = vinted_app.websocket.WebSocketTimeoutException("Connection timed out")
        with patch.object(vinted_app, "_create_backup"), \
             patch.object(vinted_app, "_load_live_vinted_items_for_renewal", side_effect=[[listing], [listing]]) as load_live, \
             patch.object(vinted_app, "_run_vinted_listing_action", side_effect=[timeout, {"ok": True}]) as delete_action, \
             patch.object(vinted_app, "_wait_for_live_action", side_effect=[RuntimeError("noch vorhanden"), {}]), \
             patch.object(vinted_app, "_run_browser_direct_upload", return_value={"item_id": "222", "item_url": "https://www.vinted.de/items/222"}), \
             patch.object(vinted_app, "_load_live_vinted_items", return_value=[]):
            result = vinted_app._renew_vinted_draft(draft_id, automatic=False)
        self.assertTrue(result["ok"])
        self.assertEqual(delete_action.call_count, 2)
        self.assertEqual(load_live.call_count, 2)
        self.assertEqual(vinted_app._find_draft(draft_id)["published_item_id"], "222")

    def test_automatic_renewal_success_pushes_only_general_service(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        draft.update({
            "title": "Testjacke",
            "published_item_id": "111", "published_url": "https://www.vinted.de/items/111",
            "published_at": vinted_app._now(), "last_renewed_at": vinted_app._now(), "publish_count": 1,
        })
        vinted_app._replace_draft(draft)
        listing = {"published_item_id": "111", "published_url": "https://www.vinted.de/items/111"}
        with patch.object(vinted_app, "_create_backup"), \
             patch.object(vinted_app, "_load_live_vinted_items_for_renewal", return_value=[listing]), \
             patch.object(vinted_app, "_run_vinted_listing_action", return_value={"ok": True}), \
             patch.object(vinted_app, "_wait_for_live_action", return_value={}), \
             patch.object(vinted_app, "_run_browser_direct_upload", return_value={"item_id": "222", "item_url": "https://www.vinted.de/items/222"}), \
             patch.object(vinted_app, "_load_live_vinted_items", return_value=[]), \
             patch.object(vinted_app, "_notify_general", return_value=True) as notify:
            result = vinted_app._renew_vinted_draft(draft_id, automatic=True)
        self.assertTrue(result["ok"])
        notify.assert_called_once()
        self.assertIn("Automatisch veröffentlicht", notify.call_args.args[0])
        self.assertIn("Testjacke", notify.call_args.args[1])
        self.assertEqual(notify.call_args.args[2], "https://www.vinted.de/items/222")

    def test_manual_renew_without_delete_keeps_old_vinted_item(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        draft.update({
            "published_item_id": "111", "published_url": "https://www.vinted.de/items/111",
            "published_at": vinted_app._now(), "last_renewed_at": vinted_app._now(), "publish_count": 1,
        })
        vinted_app._replace_draft(draft)
        with patch.object(vinted_app, "_create_backup"), \
             patch.object(vinted_app, "_load_live_vinted_items") as load_live, \
             patch.object(vinted_app, "_run_vinted_listing_action") as delete_action, \
             patch.object(vinted_app, "_run_browser_direct_upload", return_value={"item_id": "222", "item_url": "https://www.vinted.de/items/222"}):
            result = vinted_app._renew_vinted_draft(draft_id, automatic=False, delete_old=False)
        self.assertTrue(result["ok"])
        load_live.assert_called_once_with(force=True)
        delete_action.assert_not_called()
        saved = vinted_app._find_draft(draft_id)
        self.assertEqual(saved["published_item_id"], "222")
        self.assertIn("111", saved["previous_published_item_ids"])

    def test_security_retry_resumes_upload_without_second_delete(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        draft.update({
            "published_item_id": "111", "published_url": "https://www.vinted.de/items/111",
            "published_at": vinted_app._now(), "last_renewed_at": vinted_app._now(), "publish_count": 1,
        })
        vinted_app._replace_draft(draft)
        challenge = vinted_app.VintedSecurityChallenge("Sicherheitsprüfung", "https://geo.captcha-delivery.com/captcha")
        with patch.object(vinted_app, "_create_backup"), \
             patch.object(vinted_app, "_load_live_vinted_items", side_effect=[[{"published_item_id": "111"}], []]) as load_live, \
             patch.object(vinted_app, "_run_vinted_listing_action", return_value={}) as delete_action, \
             patch.object(vinted_app, "_wait_for_live_action", return_value={}), \
             patch.object(vinted_app, "_run_browser_direct_upload", side_effect=[challenge, {"item_id": "222", "item_url": "https://www.vinted.de/items/222"}]) as upload, \
             patch.object(vinted_app, "_notify_vinted_security_challenge", return_value=True):
            with self.assertRaises(vinted_app.VintedSecurityChallenge):
                vinted_app._renew_vinted_draft(draft_id)
            result = vinted_app._renew_vinted_draft(draft_id)
        self.assertTrue(result["ok"])
        self.assertEqual(upload.call_count, 2)
        delete_action.assert_called_once()
        self.assertEqual(load_live.call_count, 2)  # initial lookup + success cache refresh

    def test_explicit_retry_resumes_an_expired_security_recovery(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        draft.update({
            "published_item_id": "111", "published_url": "https://www.vinted.de/items/111",
            "published_at": vinted_app._now(), "last_renewed_at": vinted_app._now(), "publish_count": 1,
            "renewal_upload_pending": True,
            "security_challenge_required": True,
            "security_challenge_state": "timed_out",
            "security_challenge_started_at": vinted_app._now(),
            "security_challenge_deadline_at": "2000-01-01T00:00:00+00:00",
            "security_challenge_retry_requested_at": vinted_app._now(),
        })
        vinted_app._replace_draft(draft)
        with patch.object(vinted_app, "_create_backup"), \
             patch.object(vinted_app, "_run_browser_direct_upload", return_value={"item_id": "222", "item_url": "https://www.vinted.de/items/222"}) as upload, \
             patch.object(vinted_app, "_load_live_vinted_items", return_value=[]):
            result = vinted_app._renew_vinted_draft(draft_id)
        self.assertTrue(result["ok"])
        upload.assert_called_once()
        self.assertEqual(vinted_app._find_draft(draft_id)["published_item_id"], "222")

    def test_renew_button_preserves_expired_security_retry_and_recovers_stale_current(self):
        draft_id = self.create_draft()
        expired = (vinted_app.datetime.now(vinted_app.timezone.utc) - vinted_app.timedelta(minutes=1)).isoformat(timespec="seconds")
        draft = vinted_app._find_draft(draft_id)
        draft.update({
            "published_item_id": "111", "renewal_upload_pending": True,
            "security_challenge_required": True, "security_challenge_state": "timed_out",
            "security_challenge_deadline_at": expired,
        })
        vinted_app._replace_draft(draft)
        vinted_app._save_bulk_publish_state({"queue": [], "current": {"draft_id": draft_id, "action": "renew"}})
        with patch.object(vinted_app, "_bulk_publish_worker_alive", return_value=False), \
             patch.object(vinted_app, "_ensure_bulk_publish_worker") as ensure_worker:
            response = self.client.post(f"/drafts/{draft_id}/renew", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        saved = vinted_app._find_draft(draft_id)
        self.assertTrue(saved.get("security_challenge_required"))
        self.assertTrue(saved.get("security_challenge_retry_requested_at"))
        self.assertEqual(vinted_app._load_bulk_publish_state()["current"], {})
        self.assertEqual(vinted_app._load_bulk_publish_state()["queue"], [{"draft_id": draft_id, "action": "renew"}])
        ensure_worker.assert_called_once()

    def test_saving_an_existing_draft_reactivates_automation(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        draft["automation_active"] = False
        vinted_app._replace_draft(draft)
        response = self.client.post(
            f"/drafts/{draft_id}", data=self.draft_data(), follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(vinted_app._find_draft(draft_id)["automation_active"])

    def test_upload_session_id_is_read_in_real_browser_context(self):
        page = {"webSocketDebuggerUrl": "ws://example"}
        with patch.object(vinted_app, "_wait_for_vinted_page", return_value=page), \
             patch.object(vinted_app, "_cdp_command", return_value={"result": {"value": {
                 "ok": True, "status": 200, "url": "https://www.vinted.de/items/new",
                 "text": 'x "uploadSessionId":"session-123" y',
             }}}):
            self.assertEqual(vinted_app._browser_upload_session_id(), "session-123")

    def test_legacy_capsolver_error_is_migrated_to_manual_browser_check(self):
        draft = {"status": "Fehler", "last_error": "datadome challenge requires CAPSOLVER_KEY: https://example.invalid"}
        self.assertTrue(vinted_app._normalize_legacy_security_error(draft))
        self.assertEqual(draft["status"], "Sicherheitsprüfung erforderlich")
        self.assertTrue(draft["security_challenge_required"])
        self.assertNotIn("CAPSOLVER", draft["last_error"])


    def test_runtime_size_falls_back_to_public_catalog_and_size_groups(self):
        public_catalogs = {
            "catalogs": [{
                "id": 1, "title": "Kinder", "catalogs": [{
                    "id": 2, "title": "Schuhe", "catalogs": [{
                        "id": 101, "title": "Sandalen", "size_id": 31, "catalogs": []
                    }]
                }]
            }]
        }
        size_groups = {
            "size_groups": [{
                "id": 31, "title": "Kinderschuhgröße",
                "sizes": [{"id": 600, "title": "31"}, {"id": 601, "title": "32"}, {"id": 602, "title": "33"}],
            }]
        }
        packages = {"package_sizes": [{"id": 1, "title": "Klein"}]}

        def fake_fetch(path, *args, **kwargs):
            if path == "/api/v2/item_upload/attributes":
                raise RuntimeError("HTTP 403 access_denied")
            if path == "/api/v2/catalogs":
                return public_catalogs
            if path == "/api/v2/size_groups":
                return size_groups
            if "shipping-estimation" in path:
                return packages
            raise AssertionError(path)

        with patch.object(vinted_app, "_browser_fetch_json", side_effect=fake_fetch):
            result = vinted_app._load_category_runtime_options(101, None, "Kinder > Jungs > Schuhe > Sandalen")
        self.assertTrue(result["requires_size"])
        self.assertEqual(result["size_group_id"], 31)
        self.assertEqual([item["id"] for item in result["size"]], [600, 601, 602])
        self.assertEqual(result["size"][1]["label"], "32")

    def test_child_shoe_path_infers_vinted_size_group(self):
        self.assertEqual(
            vinted_app._infer_size_group_from_path("Kinder > Jungs > Schuhe > Sandalen, Pantoletten & Badelatschen"),
            31,
        )

    def test_size_less_category_clears_stale_size(self):
        draft = {
            "size_id": "601",
            "size": "32",
            "vinted_requires_size": False,
            "vinted_field_options": {"size": []},
        }
        vinted_app._normalise_current_size_selection(draft)
        self.assertEqual(draft["size_id"], "")
        self.assertEqual(draft["size"], "")

    def test_browser_payload_omits_stale_size_for_size_less_category(self):
        draft = {
            "title": "Taf Toys Kinderlenkrad",
            "description": "Spielzeug",
            "price": "8",
            "brand_id": "1",
            "brand": "Keine Marke",
            "size_id": "601",
            "category_id": "3471",
            "package_size_id": "2",
            "color_id": "4",
            "condition_id": "3",
            "vinted_requires_size": False,
            "vinted_field_options": {"size": []},
        }
        payload = vinted_app._browser_listing_payload(draft, "session", [123])
        item = payload["item"]
        self.assertNotIn("size_id", item)
        self.assertEqual(item["item_attributes"], [{"code": "condition", "ids": [3]}])

    def test_browser_payload_mirrors_required_size_as_dynamic_attribute(self):
        draft = {
            "title": "Clarks Sportschuhe",
            "description": "Schuhe",
            "price": "25",
            "brand_id": "77",
            "brand": "Clarks",
            "size_id": "710",
            "category_id": "2672",
            "package_size_id": "2",
            "color_id": "4",
            "condition_id": "3",
            "vinted_requires_size": True,
            "vinted_field_options": {"size": [{"id": 710, "label": "44"}]},
        }
        payload = vinted_app._browser_listing_payload(draft, "session", [123])
        item = payload["item"]
        self.assertEqual(item["size_id"], 710)
        self.assertIn({"code": "size", "ids": [710]}, item["item_attributes"])

    def test_browser_payload_rejects_size_from_different_category(self):
        draft = {
            "title": "Clarks Sportschuhe",
            "description": "Schuhe",
            "price": "25",
            "brand_id": "77",
            "brand": "Clarks",
            "size_id": "999",
            "category_id": "2672",
            "package_size_id": "2",
            "color_id": "4",
            "condition_id": "3",
            "vinted_requires_size": True,
            "vinted_field_options": {"size": [{"id": 710, "label": "44"}]},
        }
        with self.assertRaisesRegex(RuntimeError, "aktuellen Vinted-Kategorie"):
            vinted_app._browser_listing_payload(draft, "session", [123])

    def test_direct_upload_never_accepts_legacy_dummy_size(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        draft.update({
            "category_id": "101", "category": "Kinder > Schuhe > Sandalen", "category_verified": True,
            "brand_id": "77", "size_id": "", "condition_id": "2", "color_id": "1", "package_size_id": "1",
            "vinted_requires_size": True,
            "vinted_field_options": {
                "size": [{"id": 601, "label": "32"}], "condition": vinted_app.VINTED_CONDITIONS,
                "colour": [{"id": 1, "label": "Blau"}], "package": [{"id": 1, "label": "Klein"}],
            },
        })
        errors = vinted_app._direct_upload_errors(draft)
        self.assertIn("Größe", errors)
        with self.assertRaisesRegex(RuntimeError, "echte Größe"):
            vinted_app._browser_listing_payload({**draft, "size_id": ""}, "session", [123])

    def test_normal_validation_error_clears_stale_security_state(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        draft.update({
            "category_id": "101", "category": "Kinder > Schuhe > Sandalen", "category_verified": True,
            "security_challenge_required": True, "security_challenge_url": "https://captcha.example",
        })
        vinted_app._replace_draft(draft)
        with patch.object(vinted_app, "_refresh_selected_category_runtime", side_effect=RuntimeError("Normale Validierung")):
            response = self.client.post(
                f"/drafts/{draft_id}/prepare-upload",
                data={
                    "title": "Affenzahn Sandalen Gr. 32", "description": "Gut", "price": "39", "brand": "Affenzahn",
                    "category": "Kinder > Schuhe > Sandalen", "category_id": "101", "workflow_action": "publish",
                },
                follow_redirects=True,
            )
        self.assertEqual(response.status_code, 200)
        saved = vinted_app._find_draft(draft_id)
        self.assertEqual(saved["status"], "Fehler")
        self.assertNotIn("security_challenge_required", saved)
        self.assertNotIn("security_challenge_url", saved)
        self.assertIn(b"Normale Validierung", response.data)

    def test_form_does_not_emit_dummy_size_one(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        draft.update({
            "category_verified": True, "category": "Kinder > Schuhe > Sandalen", "category_id": "101",
            "vinted_requires_size": True, "vinted_field_options": {"size": [], "condition": vinted_app.VINTED_CONDITIONS, "colour": [], "package": []},
        })
        vinted_app._replace_draft(draft)
        response = self.client.get(f"/drafts/{draft_id}")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'name="size_id" type="hidden" value="1"', response.data)
        self.assertIn("Upload bleibt gesperrt".encode(), response.data)

    def test_verified_session_is_persisted_without_password(self):
        cookies = [{"name": "access_token_web", "value": "token", "domain": ".vinted.de", "path": "/", "secure": True, "httpOnly": True}]
        with patch.object(vinted_app, "_vinted_cookie_records", return_value=cookies):
            count = vinted_app._persist_vinted_session({"id": "page"})
        self.assertEqual(count, 1)
        payload = json.loads(vinted_app.VINTED_SESSION_FILE.read_text("utf-8"))
        self.assertEqual(payload["cookies"][0]["name"], "access_token_web")
        self.assertNotIn("password", json.dumps(payload).lower())
        self.assertEqual(vinted_app.VINTED_SESSION_FILE.stat().st_mode & 0o777, 0o600)

    def test_background_session_never_receives_refresh_cookie(self):
        vinted_app.VINTED_SESSION_FILE.write_text(json.dumps({"cookies": [
            {"name": "access_token_web", "value": "access", "domain": ".vinted.de"},
            {"name": "refresh_token_web", "value": "refresh", "domain": ".vinted.de"},
            {"name": "anon_id", "value": "anon", "domain": ".vinted.de"},
        ]}), "utf-8")
        cookies = vinted_app._background_session_cookie_records()
        self.assertEqual([item["name"] for item in cookies], ["access_token_web", "anon_id"])
        self.assertNotIn("refresh", json.dumps(cookies).casefold())

    def test_periodic_cookie_checkpoint_never_executes_in_visible_page(self):
        cookies = [{"name": "access_token_web", "value": "token", "domain": ".vinted.de"}]
        with patch.object(vinted_app, "_vinted_cookie_records", return_value=cookies), \
             patch.object(vinted_app, "_page_has_authenticated_vinted_user") as api_proof, \
             patch.object(vinted_app, "_persist_vinted_session", return_value=1) as persist:
            count = vinted_app._checkpoint_vinted_session(
                {"id": "page"},
                source="visible-cookie-snapshot",
                min_interval=0,
                require_api_proof=False,
            )
        self.assertEqual(count, 1)
        api_proof.assert_not_called()
        persist.assert_called_once()

    def test_periodic_cookie_checkpoint_never_replaces_login_with_anonymous_cookies(self):
        cookies = [{"name": "anonymous_id", "value": "value", "domain": ".vinted.de"}]
        with patch.object(vinted_app, "_vinted_cookie_records", return_value=cookies), \
             patch.object(vinted_app, "_persist_vinted_session") as persist:
            count = vinted_app._checkpoint_vinted_session(
                {"id": "page"},
                source="visible-cookie-snapshot",
                min_interval=0,
                require_api_proof=False,
            )
        self.assertEqual(count, 0)
        persist.assert_not_called()

    def test_authenticated_account_api_wins_over_transient_login_control(self):
        with patch.object(vinted_app, "_wait_for_vinted_page", return_value={"id": "page"}), \
             patch.object(vinted_app, "_refresh_browser_target", return_value={"id": "page"}), \
             patch.object(vinted_app, "_vinted_login_ui_state", return_value={"login_visible": True, "account_visible": False}), \
             patch.object(vinted_app, "_browser_fetch_json", return_value={"user": {"id": 83077265}}), \
             patch.object(vinted_app, "_checkpoint_vinted_session"):
            result = vinted_app._verify_vinted_session()
        self.assertEqual(result["user_id"], "83077265")

    def test_visible_login_without_authenticated_api_is_not_logged_in(self):
        with patch.object(vinted_app, "_wait_for_vinted_page", return_value={"id": "page"}), \
             patch.object(vinted_app, "_refresh_browser_target", return_value={"id": "page"}), \
             patch.object(vinted_app, "_vinted_login_ui_state", return_value={"login_visible": True, "account_visible": False}), \
             patch.object(vinted_app, "_browser_fetch_json", side_effect=RuntimeError("HTTP 401")):
            with self.assertRaisesRegex(RuntimeError, "nicht angemeldet"):
                vinted_app._verify_vinted_session()

    def test_account_status_does_not_call_transient_browser_error_a_logout(self):
        process = MagicMock()
        process.poll.return_value = None
        with patch.object(vinted_app, "_browser_process", process), \
             patch.object(vinted_app, "_verify_vinted_session", side_effect=RuntimeError("Execution context was destroyed")):
            status = vinted_app._account_status()
        self.assertEqual(status["state"], "checking")
        self.assertIn("keine Abmeldung", status["message"])

    def test_api_401_is_never_logout_proof(self):
        with patch.object(vinted_app, "_verify_vinted_session") as verify, \
             patch.object(vinted_app.time, "sleep") as sleep:
            self.assertFalse(vinted_app._logout_still_confirmed("HTTP 401 invalid_authentication_token"))
        verify.assert_not_called()
        sleep.assert_not_called()

    def test_visible_logout_requires_three_consecutive_visible_failures(self):
        error = "Die sichtbare Vinted-Sitzung ist nicht angemeldet. Bitte im Vinted-Browser einloggen."
        with patch.object(vinted_app, "_verify_vinted_session", side_effect=RuntimeError(error)), \
             patch.object(vinted_app.time, "sleep") as sleep:
            self.assertTrue(vinted_app._logout_still_confirmed(error))
        self.assertEqual(sleep.call_count, vinted_app.VINTED_LOGOUT_CONFIRMATION_ATTEMPTS - 1)

    def test_login_required_status_notifies_only_once(self):
        (vinted_app.DATA_DIR / "options.json").write_text(
            json.dumps({"notify_service": "notify.mobile_app_primary_private"}), "utf-8"
        )
        with patch.object(vinted_app, "_notify_service") as notify:
            vinted_app._mark_vinted_login_required("Vinted zeigt die Anmeldung an.")
            vinted_app._mark_vinted_login_required("Dies darf keine zweite Nachricht ausloesen.")
        self.assertEqual(vinted_app._vinted_session_status()["state"], "login_required")
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[0], "notify.mobile_app_primary_private")
        self.assertIn("Anmeldung erforderlich", notify.call_args.args[1])
        self.assertEqual(notify.call_args.kwargs["extra_data"]["push"]["sound"], {"name": "default", "critical": 1, "volume": 0.0})

    def test_account_link_with_api_401_is_transient_not_logout(self):
        with patch.object(vinted_app, "_wait_for_vinted_page", return_value={"id": "page"}), \
             patch.object(vinted_app, "_refresh_browser_target", return_value={"id": "page"}), \
             patch.object(vinted_app, "_vinted_login_ui_state", return_value={"login_visible": False, "account_visible": True}), \
             patch.object(vinted_app, "_browser_fetch_json", side_effect=RuntimeError("HTTP 401 invalid_authentication_token")):
            with self.assertRaisesRegex(RuntimeError, "vorübergehend ungültig") as caught:
                vinted_app._verify_vinted_session()
        self.assertFalse(vinted_app._is_confirmed_vinted_logout(caught.exception))

    def test_account_status_marks_vinted_login_screen_as_not_connected(self):
        process = MagicMock()
        process.poll.return_value = None
        with patch.object(vinted_app, "_browser_process", process), \
             patch.object(vinted_app, "_verify_vinted_session", side_effect=RuntimeError("Die Vinted-Anmeldung läuft gerade.")), \
             patch.object(vinted_app, "_mark_vinted_login_required") as mark_login_required:
            status = vinted_app._account_status()
        self.assertEqual(status["state"], "not_connected")
        self.assertEqual(status["title"], "Vinted-Anmeldung erforderlich")
        mark_login_required.assert_called_once()

    def test_manual_vinted_login_is_never_overwritten_by_cookie_recovery(self):
        login_page = {"id": "page", "url": "https://www.vinted.de/member/signup/select_type"}
        with patch.object(vinted_app, "_wait_for_vinted_page", return_value=login_page), \
             patch.object(vinted_app, "_refresh_browser_target", return_value=login_page), \
             patch.object(vinted_app, "_restore_persisted_vinted_session") as restore:
            with self.assertRaisesRegex(RuntimeError, "Anmeldung läuft"):
                vinted_app._verify_vinted_session()
        restore.assert_not_called()

    def test_live_item_can_link_to_existing_manager_draft_and_unlink_again(self):
        draft_id = self.create_draft(title="Vorhandene Manager-Anzeige")
        listing = {
            "published_item_id": "555",
            "published_url": "https://www.vinted.de/items/555-test",
            "title": "Live Anzeige",
            "live_state": "active",
        }
        linked = vinted_app._link_live_vinted_listing(listing, draft_id)
        self.assertEqual(linked["published_item_id"], "555")
        self.assertEqual(linked["status"], "Bei Vinted verknüpft")
        unlinked = vinted_app._unlink_live_vinted_listing("555")
        self.assertEqual(unlinked["status"], "Verknüpfung gelöst")
        self.assertNotIn("published_item_id", unlinked)

    def test_live_view_offers_manual_link_to_existing_draft(self):
        self.create_draft(title="Lokale Jacke")
        live_item = {"published_item_id": "777", "title": "Vinted Jacke", "price": "25", "live_state": "active"}
        with patch.object(vinted_app, "_load_live_vinted_items", return_value=[live_item]):
            response = self.client.get("/live")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Manager-Anzeige auswählen".encode(), response.data)
        self.assertIn("Lokale Jacke".encode(), response.data)

    def test_confirmed_live_delete_removes_linked_manager_draft(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        draft.update({"published_item_id": "888", "published_url": "https://www.vinted.de/items/888", "status": "Veröffentlicht"})
        vinted_app._replace_draft(draft)
        live_item = {"published_item_id": "888", "published_url": "https://www.vinted.de/items/888", "title": "Test", "live_state": "active"}
        with patch.object(vinted_app, "_load_live_vinted_items", side_effect=[[live_item], [], []]), \
             patch.object(vinted_app, "_run_vinted_listing_action", return_value={"ok": True}), \
             patch.object(vinted_app, "_wait_for_live_action", return_value={"published_item_id": "888", "live_state": "sold"}):
            response = self.client.post("/live/items/888/action", data={"action": "delete"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(vinted_app._find_draft(draft_id))

    def test_messages_and_notifications_have_manager_views(self):
        message = {"sender": "Kaeuferin", "item_title": "Jacke", "text": "Noch da?", "unread": 1, "url": "https://www.vinted.de/inbox"}
        notification = {"actor": "Maria", "text": "Maria folgt dir", "is_follow": True, "is_favourite": False, "unread": True, "url": "https://www.vinted.de/notifications"}
        vinted_app._write_activity_cache(vinted_app.INBOX_CACHE_FILE, [message])
        vinted_app._write_activity_cache(vinted_app.NOTIFICATIONS_CACHE_FILE, [notification])
        with patch.object(vinted_app, "_load_vinted_messages") as inbox_loader, \
             patch.object(vinted_app, "_load_vinted_notifications") as notification_loader:
            inbox_response = self.client.get("/messages")
            notification_response = self.client.get("/notifications")
        self.assertIn(b"Kaeuferin", inbox_response.data)
        self.assertIn(b"Maria", notification_response.data)
        inbox_loader.assert_not_called()
        notification_loader.assert_not_called()

    def test_sidebar_shows_unread_message_and_notification_counts(self):
        message = vinted_app._message_entry({
            "id": 88, "description": "Noch da?", "unread": True,
            "opposite_user": {"login": "Maria"},
        })
        notification = vinted_app._notification_entry({
            "id": 89, "text": "Nina folgt dir", "unread": True,
        })
        vinted_app._write_activity_cache(vinted_app.INBOX_CACHE_FILE, [message])
        vinted_app._write_activity_cache(vinted_app.NOTIFICATIONS_CACHE_FILE, [notification])
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.data.count(b'nav-badge">1</b>'), 2)

    def test_stale_live_id_is_offered_and_can_be_relinked(self):
        draft_id = self.create_draft(title="Affenzahn Altbestand")
        draft = vinted_app._find_draft(draft_id)
        draft.update({"published_item_id": "111", "published_url": "https://www.vinted.de/items/111-alt"})
        vinted_app._replace_draft(draft)
        current = [{"published_item_id": "222", "published_url": "https://www.vinted.de/items/222-neu", "title": "Affenzahn Altbestand", "live_state": "active"}]
        candidates = vinted_app._live_link_candidates(vinted_app._load_drafts(), current)
        candidate = next(item for item in candidates if item.get("id") == draft_id)
        self.assertEqual(candidate["stale_id"], "111")
        linked = vinted_app._link_live_vinted_listing(current[0], draft_id, current)
        self.assertEqual(linked["published_item_id"], "222")

    def test_current_live_link_is_not_offered_as_link_candidate(self):
        draft_id = self.create_draft(title="Bereits verbunden")
        draft = vinted_app._find_draft(draft_id)
        draft["published_item_id"] = "333"
        vinted_app._replace_draft(draft)
        current = [{"published_item_id": "333", "title": "Bereits verbunden", "live_state": "active"}, {"published_item_id": "444", "title": "Andere Live-Anzeige", "live_state": "active"}]
        candidates = vinted_app._live_link_candidates(vinted_app._load_drafts(), current)
        self.assertNotIn(draft_id, {item.get("id") for item in candidates})

    def test_existing_activity_can_be_extracted_from_observed_vinted_json(self):
        inbox_payload = {"conversations": [{"id": 7, "other_user": {"login": "Maria"}, "item": {"title": "Jacke"}, "last_message": {"body": "Ist sie noch da?"}, "unread_count": 2}]}
        notification_payload = {"notifications": [{"id": 8, "type": "favourite", "actor": {"login": "Nina"}, "text": "Nina hat deinen Artikel favorisiert", "is_unread": False}]}
        messages = vinted_app._dedupe_activity_entries(vinted_app._extract_activity_candidates(inbox_payload, "messages"), "messages")
        notifications = vinted_app._dedupe_activity_entries(vinted_app._extract_activity_candidates(notification_payload, "notifications"), "notifications")
        self.assertEqual(messages[0]["sender"], "Maria")
        self.assertEqual(messages[0]["text"], "Ist sie noch da?")
        self.assertEqual(messages[0]["unread"], 2)
        self.assertEqual(notifications[0]["actor"], "Nina")
        self.assertTrue(notifications[0]["is_favourite"])

    def test_activity_cache_uses_new_schema_to_invalidate_old_empty_cache(self):
        vinted_app._write_activity_cache(vinted_app.INBOX_CACHE_FILE, [{"id": "1", "text": "Alt"}])
        payload = json.loads(vinted_app.INBOX_CACHE_FILE.read_text("utf-8"))
        self.assertEqual(payload["schema"], 4)

    def test_real_vinted_inbox_schema_is_loaded_without_page_navigation(self):
        payload = {
            "conversations": [{
                "id": 71,
                "description": "Ist der Artikel noch da?",
                "unread": True,
                "updated_at": "2026-08-27T10:00:00Z",
                "opposite_user": {"login": "Maria"},
            }],
            "pagination": {"total_pages": 1},
        }
        with patch.object(vinted_app, "_background_fetch_json", return_value=payload) as fetch:
            entries = vinted_app._load_vinted_messages_from_api()
        self.assertEqual(entries[0]["sender"], "Maria")
        self.assertEqual(entries[0]["text"], "Ist der Artikel noch da?")
        self.assertEqual(entries[0]["unread"], 1)
        self.assertTrue(entries[0]["url"].endswith("/inbox/71"))
        fetch.assert_called_once()

    def test_empty_inbox_api_falls_back_to_rendered_vinted_inbox(self):
        rendered = [{
            "id": "72", "sender": "Maria", "item_title": "Jacke", "text": "Noch da?",
            "unread": 1, "url": "https://www.vinted.de/inbox/72",
        }]
        with patch.object(vinted_app, "_load_vinted_messages_from_api", return_value=[]), \
             patch.object(vinted_app, "_load_vinted_entries_from_page", return_value=rendered):
            entries = vinted_app._load_vinted_messages(force=True)
        self.assertEqual(entries[0]["sender"], "Maria")
        self.assertEqual(entries[0]["unread"], 1)

    def test_real_vinted_notification_schema_marks_unread_and_existing_entry(self):
        payload = {
            "notifications": [{
                "id": "91",
                "entry_type": 123,
                "is_read": False,
                "updated_at": "2026-08-27T10:01:00Z",
                "body": "Nina hat deinen Artikel favorisiert",
                "link": "/items/123-test",
            }],
            "pagination": {"total_pages": 1},
        }
        with patch.object(vinted_app, "_background_fetch_json", return_value=payload):
            entries = vinted_app._load_vinted_notifications_from_api()
        self.assertEqual(entries[0]["text"], "Nina hat deinen Artikel favorisiert")
        self.assertTrue(entries[0]["unread"])
        self.assertTrue(entries[0]["is_favourite"])
        self.assertTrue(entries[0]["url"].startswith("https://www.vinted.de/items/"))

    def test_vinted_activity_api_reads_existing_pages(self):
        first = {"conversations": [{"id": 1, "description": "A", "opposite_user": {"login": "A"}}], "pagination": {"total_pages": 2}}
        second = {"conversations": [{"id": 2, "description": "B", "opposite_user": {"login": "B"}}], "pagination": {"total_pages": 2}}
        with patch.object(vinted_app, "_background_fetch_json", side_effect=[first, second]) as fetch:
            rows = vinted_app._load_vinted_api_collection("/api/v2/inbox", "conversations")
        self.assertEqual([row["id"] for row in rows], [1, 2])
        self.assertEqual(fetch.call_count, 2)

    def test_browser_fetch_retries_when_vinted_replaces_execution_context(self):
        success = {
            "result": {
                "value": {
                    "ok": True,
                    "status": 200,
                    "url": "https://www.vinted.de/api/v2/inbox?page=1",
                    "text": '{"conversations": []}',
                }
            }
        }
        with patch.object(vinted_app, "_wait_for_vinted_page", return_value={"webSocketDebuggerUrl": "ws://page"}), \
             patch.object(vinted_app, "_cdp_command", side_effect=[RuntimeError("Execution context was destroyed."), success]) as command:
            payload = vinted_app._browser_fetch_json("/api/v2/inbox?page=1", timeout=1)
        self.assertEqual(payload["conversations"], [])
        self.assertEqual(command.call_count, 2)


    def test_messages_are_kept_without_local_new_markers(self):
        entry = vinted_app._message_entry({
            "id": 901, "description": "Ist die Jacke noch da?", "unread": True,
            "updated_at": "2026-08-27T12:00:00+02:00",
            "opposite_user": {"id": 77, "login": "Nina"},
        })
        primary = vinted_app._decorate_messages_for_user([entry], vinted_app.APP_USERS["primary"])[0]
        secondary = vinted_app._decorate_messages_for_user([entry], vinted_app.APP_USERS["secondary"])[0]
        self.assertFalse(primary["unread"])
        self.assertFalse(secondary["unread"])

    def test_message_read_state_is_quiet_for_every_profile(self):
        entries = [
            vinted_app._message_entry({
                "id": 902, "description": "Erste Nachricht", "unread": True,
                "updated_at": "2026-08-27T12:01:00+02:00",
                "opposite_user": {"id": 78, "login": "Nina"},
            }),
            vinted_app._message_entry({
                "id": 903, "description": "Zweite Nachricht", "unread": True,
                "updated_at": "2026-08-27T12:02:00+02:00",
                "opposite_user": {"id": 79, "login": "Mia"},
            }),
        ]
        primary_entries = vinted_app._decorate_messages_for_user(entries, vinted_app.APP_USERS["primary"])
        secondary_entries = vinted_app._decorate_messages_for_user(entries, vinted_app.APP_USERS["secondary"])

        self.assertEqual(vinted_app._mark_all_user_messages_read("primary", primary_entries), 0)
        self.assertEqual(vinted_app._mark_all_user_messages_read("primary", primary_entries), 0)
        self.assertEqual([row["unread"] for row in vinted_app._decorate_messages_for_user(entries, vinted_app.APP_USERS["primary"])], [0, 0])
        self.assertEqual([row["unread"] for row in vinted_app._decorate_messages_for_user(entries, vinted_app.APP_USERS["secondary"])], [0, 0])

    def test_messages_page_keeps_inbox_without_unread_controls(self):
        entries = [vinted_app._message_entry({
            "id": 904, "description": "Ungelesene Nachricht", "unread": True,
            "updated_at": "2026-08-27T12:03:00+02:00",
            "opposite_user": {"id": 80, "login": "Lena"},
        })]
        vinted_app._write_activity_cache(vinted_app.INBOX_CACHE_FILE, entries)
        response = self.client.get("/messages")
        self.assertEqual(response.status_code, 200)
        self.assertIn("1 Unterhaltungen".encode(), response.data)
        self.assertNotIn("Alle als gelesen markieren".encode(), response.data)
        self.assertNotIn(b"message-new-badge", response.data)

    def test_mark_all_messages_read_route_updates_local_read_state(self):
        entries = [vinted_app._message_entry({
            "id": 905, "description": "Ungelesene Nachricht", "unread": True,
            "updated_at": "2026-08-27T12:04:00+02:00",
            "opposite_user": {"id": 81, "login": "Lena"},
        })]
        vinted_app._write_activity_cache(vinted_app.INBOX_CACHE_FILE, entries)
        response = self.client.post("/messages/mark-all-read", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Keine ungelesenen Unterhaltungen vorhanden.".encode(), response.data)
        decorated = vinted_app._decorate_messages_for_user(entries, vinted_app.APP_USERS["primary"])
        self.assertFalse(decorated[0]["unread"])

    def test_conversation_detail_builds_chat_directions_and_article_context(self):
        inbox = vinted_app._message_entry({"id": 123, "description": "Hallo", "unread": True, "opposite_user": {"id": 9, "login": "Kunde"}})
        conversation = vinted_app._normalise_conversation({
            "id": 123,
            "opposite_user": {"id": 9, "login": "Kunde", "profile_url": "/member/9"},
            "transaction": {"item_id": 77, "item_title": "Wolljacke", "item_url": "/items/77", "item_photo": {"url": "https://img.example/item.jpg"}},
            "messages": [
                {"entity_type": "message", "entity": {"id": 1, "user_id": 9, "body": "Noch da?"}, "created_at_ts": "1"},
                {"entity_type": "message", "entity": {"id": 2, "user_id": 42, "body": "Ja"}, "created_at_ts": "2"},
            ],
        }, inbox)
        self.assertEqual([row["direction"] for row in conversation["messages"]], ["received", "sent"])
        self.assertEqual(conversation["item_id"], "77")
        self.assertEqual(conversation["item_title"], "Wolljacke")
        self.assertTrue(conversation["item_url"].endswith("/items/77"))
        self.assertTrue(conversation["incoming_marker"])

    def test_reply_uses_vinted_conversation_replies_endpoint(self):
        with patch.object(vinted_app, "_verify_vinted_session", return_value={"verified": "1"}), \
             patch.object(vinted_app, "_browser_post_json", return_value={}) as post:
            vinted_app._reply_to_vinted_conversation("123", "Hallo zurück")
        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], "/api/v2/conversations/123/replies")
        self.assertEqual(args[1]["reply"]["body"], "Hallo zurück")

    def test_notification_subject_id_links_to_vinted_item(self):
        entry = vinted_app._notification_entry({
            "id": "n1", "body": "Jemand hat deinen Artikel favorisiert",
            "entry_type": "favourite", "subject_id": 7788, "is_read": False,
            "small_photo_url": "https://img.example/fav.jpg",
        })
        self.assertTrue(entry["is_favourite"])
        self.assertEqual(entry["url"], "https://www.vinted.de/items/7788")
        self.assertEqual(entry["image_url"], "https://img.example/fav.jpg")

    def test_profile_login_is_available_without_existing_profile(self):
        client = vinted_app.app.test_client()
        response = client.get("/profile-login")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"primary", response.data)
        self.assertIn(b"secondary", response.data)



    def test_member_rating_is_normalised_for_message_badges(self):
        rating = vinted_app._normalise_member_rating({"feedback_count": 31, "feedback_reputation": 0.972})
        self.assertEqual(rating["rating_percent"], 97)
        self.assertEqual(rating["rating_stars"], 4.9)
        self.assertEqual(rating["feedback_count"], 31)

    def test_favourite_notification_keeps_actor_and_item_for_internal_reply(self):
        entry = vinted_app._notification_entry({
            "id": "fav-1",
            "entry_type": "favourite",
            "body": "Nina hat deinen Artikel favorisiert",
            "actor": {"id": 55, "login": "Nina"},
            "subject_id": 7788,
            "link": "https://www.vinted.de/notifications?offering_id=12",
        })
        self.assertEqual(entry["actor_user_id"], "55")
        self.assertEqual(entry["subject_id"], "7788")
        self.assertTrue(entry["is_favourite"])

    def test_notification_link_can_resolve_to_vinted_conversation(self):
        entry = {"source_link": "https://www.vinted.de/notifications?offering_id=12", "conversation_id": "", "url": ""}
        with patch.object(vinted_app, "_browser_resolve_vinted_url", return_value="https://www.vinted.de/inbox/987654321"):
            self.assertEqual(vinted_app._notification_conversation_id(entry), "987654321")



    def test_price_automation_chip_distinguishes_each_renewal_and_independent_interval(self):
        draft = {
            "published_item_id": "123", "published_at": vinted_app._now(), "price": "27",
            "renew_interval_days": 7, "automation_active": True,
            "republish_price_reduction_enabled": True, "republish_price_drop": 5,
            "republish_price_reduction_days": 7, "republish_min_price": 22,
        }
        view = vinted_app._draft_schedule_view(draft)
        self.assertEqual(view["price_automation_summary"], "↓5€ · min. 22€")
        draft["republish_price_reduction_days"] = 21
        view = vinted_app._draft_schedule_view(draft)
        self.assertEqual(view["price_automation_summary"], "↓5€ / 21T · min. 22€")

    def test_due_today_and_tomorrow_include_the_scheduled_time(self):
        now = vinted_app.datetime.now(vinted_app._display_timezone()).replace(second=0, microsecond=0)
        today = {
            "published_item_id": "123", "last_renewed_at": (now - vinted_app.timedelta(days=7)).isoformat(),
            "renew_interval_days": 7, "automation_active": True,
        }
        tomorrow = {**today, "last_renewed_at": (now - vinted_app.timedelta(days=6)).isoformat()}
        self.assertIn(f"heute um {now.strftime('%H:%M')} Uhr", vinted_app._draft_schedule_view(today)["next_due_label"])
        self.assertIn(f"morgen um {now.strftime('%H:%M')} Uhr", vinted_app._draft_schedule_view(tomorrow)["next_due_label"])

    def test_automatic_renewal_waits_for_exact_scheduled_clock_time(self):
        tz = vinted_app._display_timezone()
        due_at = vinted_app.datetime(2026, 9, 6, 9, 16, tzinfo=tz)
        base = due_at - vinted_app.timedelta(days=7)
        draft = {
            "published_item_id": "123",
            "last_renewed_at": base.astimezone(vinted_app.timezone.utc).isoformat(),
            "renew_interval_days": 7,
            "automation_active": True,
        }
        self.assertFalse(vinted_app._draft_renewal_due(draft, due_at - vinted_app.timedelta(minutes=1)))
        self.assertTrue(vinted_app._draft_renewal_due(draft, due_at))
        self.assertTrue(vinted_app._draft_renewal_due(draft, due_at + vinted_app.timedelta(minutes=1)))

    def test_same_day_past_due_time_is_shown_as_overdue(self):
        now = vinted_app.datetime.now(vinted_app._display_timezone()).replace(second=0, microsecond=0)
        draft = {
            "published_item_id": "123",
            "last_renewed_at": (now - vinted_app.timedelta(days=7, hours=2)).isoformat(),
            "renew_interval_days": 7,
            "automation_active": True,
        }
        view = vinted_app._draft_schedule_view(draft)
        self.assertIn("überfällig", view["next_due_label"])
        self.assertIn("überfällig", view["renewal_due_detail_label"])
        self.assertNotIn("nächste Erneuerung heute um", view["renewal_due_detail_label"])

    def test_automatic_candidate_prefers_oldest_overdue_item(self):
        now = vinted_app.datetime.now(vinted_app._display_timezone()).replace(second=0, microsecond=0)
        newer_due = {
            "id": "newer", "title": "Später", "published_item_id": "2",
            "last_renewed_at": (now - vinted_app.timedelta(days=7, hours=1)).isoformat(),
            "renew_interval_days": 7, "automation_active": True,
        }
        older_due = {
            "id": "older", "title": "Früher", "published_item_id": "1",
            "last_renewed_at": (now - vinted_app.timedelta(days=7, hours=3)).isoformat(),
            "renew_interval_days": 7, "automation_active": True,
        }
        candidate, mode = vinted_app._next_automatic_renewal_candidate([newer_due, older_due])
        self.assertEqual(mode, "renewal")
        self.assertEqual(candidate["id"], "older")

    def test_price_reduction_respects_minimum_and_independent_anchor(self):
        now = vinted_app.datetime(2026, 8, 27, 12, 0, tzinfo=vinted_app.timezone.utc)
        draft = {
            "price": "25", "renew_interval_days": 7,
            "republish_price_reduction_enabled": True, "republish_price_drop": 5,
            "republish_price_reduction_days": 21, "republish_min_price": 22,
            "price_reduction_anchor_at": (now - vinted_app.timedelta(days=21)).isoformat(),
        }
        change = vinted_app._prepare_draft_price_reduction(draft, renewal=True, now=now)
        self.assertEqual(change["new_price"], 22)
        self.assertEqual(draft["price"], "22")
        vinted_app._commit_draft_price_reduction(draft, change)
        self.assertEqual(draft["price_reduction_count"], 1)
        self.assertIsNone(vinted_app._prepare_draft_price_reduction(draft, renewal=True, now=now + vinted_app.timedelta(days=21)))

    def test_legacy_price_anchor_uses_first_publication_not_latest_renewal(self):
        now = vinted_app.datetime(2026, 9, 9, 8, 0, tzinfo=vinted_app.timezone.utc)
        draft = {
            "price": "60", "renew_interval_days": 7,
            "republish_price_reduction_enabled": True, "republish_price_drop": 1,
            "republish_price_reduction_days": 14, "republish_min_price": 55,
            "first_published_at": (now - vinted_app.timedelta(days=14)).isoformat(),
            "published_at": (now - vinted_app.timedelta(days=7)).isoformat(),
            "last_renewed_at": (now - vinted_app.timedelta(days=7)).isoformat(),
        }
        anchor = vinted_app._ensure_price_reduction_anchor(draft, now=now)
        self.assertEqual(anchor, now - vinted_app.timedelta(days=14))
        change = vinted_app._prepare_draft_price_reduction(draft, renewal=True, now=now)
        self.assertEqual(change["new_price"], 59)

    def test_schedule_view_labels_actual_renewals_not_total_publications(self):
        now = vinted_app.datetime.now(vinted_app.timezone.utc)
        draft = {
            "published_item_id": "123", "price": "60",
            "publish_count": 2, "renew_interval_days": 7, "automation_active": True,
            "first_published_at": (now - vinted_app.timedelta(days=10)).isoformat(),
            "published_at": (now - vinted_app.timedelta(days=3)).isoformat(),
            "last_renewed_at": (now - vinted_app.timedelta(days=3)).isoformat(),
            "republish_price_reduction_enabled": True, "republish_price_drop": 1,
            "republish_price_reduction_days": 14, "republish_min_price": 55,
        }
        view = vinted_app._draft_schedule_view(draft)
        self.assertEqual(view["renewal_count"], 1)
        self.assertTrue(view["price_reduction_due_label"])

    def test_manual_renew_keeps_manager_draft_and_links_new_vinted_id(self):
        draft_id = self.create_draft()
        draft = vinted_app._find_draft(draft_id)
        draft.update({
            "published_item_id": "111", "published_url": "https://www.vinted.de/items/111",
            "published_at": vinted_app._now(), "last_renewed_at": vinted_app._now(), "publish_count": 1,
        })
        vinted_app._replace_draft(draft)
        listing = {"published_item_id": "111", "published_url": "https://www.vinted.de/items/111"}
        with patch.object(vinted_app, "_create_backup"), \
             patch.object(vinted_app, "_load_live_vinted_items", side_effect=[[listing], []]), \
             patch.object(vinted_app, "_run_vinted_listing_action", return_value={"ok": True}), \
             patch.object(vinted_app, "_wait_for_live_action", return_value={}), \
             patch.object(vinted_app, "_run_browser_direct_upload", return_value={"item_id": "222", "item_url": "https://www.vinted.de/items/222"}):
            result = vinted_app._renew_vinted_draft(draft_id, automatic=False)
        self.assertTrue(result["ok"])
        saved = vinted_app._find_draft(draft_id)
        self.assertEqual(saved["published_item_id"], "222")
        self.assertIn("111", saved["previous_published_item_ids"])

    def test_first_publication_success_sends_primary_system_push(self):
        draft_id = self.create_draft(title="Push Erfolg")
        draft = vinted_app._find_draft(draft_id)
        draft["manual_review_confirmed"] = True
        vinted_app._replace_draft(draft)
        with patch.object(vinted_app, "_refresh_selected_category_runtime"), \
             patch.object(vinted_app, "_sync_selected_labels"), \
             patch.object(vinted_app, "_direct_upload_errors", return_value=[]), \
             patch.object(vinted_app, "_run_browser_direct_upload", return_value={"item_id": "222", "item_url": "https://www.vinted.de/items/222"}), \
             patch.object(vinted_app, "_verify_new_publication_visibility", return_value=True) as visibility, \
             patch.object(vinted_app, "_notify_general", return_value=True) as notify:
            result = vinted_app._publish_unpublished_draft(draft_id)
        self.assertTrue(result["ok"])
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[0], "Vinted · Anzeige veröffentlicht")
        self.assertIn("Push Erfolg", notify.call_args.args[1])
        visibility.assert_called_once()
        self.assertEqual(visibility.call_args.args[0]["published_item_id"], "222")

    def test_post_publish_visibility_success_does_not_send_second_push(self):
        draft = {
            "title": "Sichtbar",
            "published_item_id": "222",
            "published_url": "https://www.vinted.de/items/222",
        }
        with patch.object(vinted_app, "_read_live_cache", side_effect=[{"fetched_at": 1.0}, {"fetched_at": 2.0}]), \
             patch.object(vinted_app, "_load_live_vinted_items", return_value=[{"published_item_id": "222"}]) as live, \
             patch.object(vinted_app, "_notify_general", return_value=True) as normal, \
             patch.object(vinted_app, "_notify_primary_critical", return_value=True) as critical:
            self.assertTrue(vinted_app._verify_new_publication_visibility(draft, attempts=1, delay_seconds=0))
        live.assert_called_once_with(force=True, allow_visible_fallback=False)
        normal.assert_not_called()
        critical.assert_not_called()

    def test_post_publish_visibility_missing_is_silent_critical_primary(self):
        draft = {
            "title": "Nicht sichtbar",
            "published_item_id": "333",
            "published_url": "https://www.vinted.de/items/333",
        }
        with patch.object(vinted_app, "_read_live_cache", side_effect=[{"fetched_at": 1.0}, {"fetched_at": 2.0}]), \
             patch.object(vinted_app, "_load_live_vinted_items", return_value=[]), \
             patch.object(vinted_app, "_notify_general", return_value=True) as normal, \
             patch.object(vinted_app, "_notify_primary_critical", return_value=True) as critical:
            self.assertFalse(vinted_app._verify_new_publication_visibility(draft, attempts=1, delay_seconds=0))
        normal.assert_not_called()
        critical.assert_called_once()
        self.assertEqual(critical.call_args.args[0], "Vinted · Sichtprüfung kritisch")
        self.assertIn("Nicht sichtbar", critical.call_args.args[1])

    def test_post_publish_visibility_requires_fresh_live_snapshot(self):
        draft = {"title": "Altcache", "published_item_id": "444", "published_url": "https://www.vinted.de/items/444"}
        with patch.object(vinted_app, "_read_live_cache", side_effect=[{"fetched_at": 5.0}, {"fetched_at": 5.0}]), \
             patch.object(vinted_app, "_load_live_vinted_items", return_value=[{"published_item_id": "444"}]), \
             patch.object(vinted_app, "_notify_general", return_value=True) as normal, \
             patch.object(vinted_app, "_notify_primary_critical", return_value=True) as critical:
            self.assertFalse(vinted_app._verify_new_publication_visibility(draft, attempts=1, delay_seconds=0))
        normal.assert_not_called()
        critical.assert_called_once()

    def test_first_publication_failure_sends_primary_system_push(self):
        draft_id = self.create_draft(title="Push Fehler")
        draft = vinted_app._find_draft(draft_id)
        draft["manual_review_confirmed"] = True
        vinted_app._replace_draft(draft)
        with patch.object(vinted_app, "_refresh_selected_category_runtime"), \
             patch.object(vinted_app, "_sync_selected_labels"), \
             patch.object(vinted_app, "_direct_upload_errors", return_value=[]), \
             patch.object(vinted_app, "_run_browser_direct_upload", side_effect=RuntimeError("Upload fehlgeschlagen")), \
             patch.object(vinted_app, "_handle_vinted_category_rejection", return_value=False), \
             patch.object(vinted_app, "_notify_general", return_value=True) as notify:
            with self.assertRaisesRegex(RuntimeError, "Upload fehlgeschlagen"):
                vinted_app._publish_unpublished_draft(draft_id)
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[0], "Vinted · Veröffentlichung fehlgeschlagen")
        self.assertIn("Push Fehler", notify.call_args.args[1])

    def test_unpublished_get_never_refreshes_vinted_metadata(self):
        draft_id = self.create_draft(title="Cache Test")
        draft = vinted_app._find_draft(draft_id)
        draft.update({"category_verified": True, "category_id": "101", "category": "Kinder > Schuhe > Sandalen"})
        vinted_app._replace_draft(draft)
        with patch.object(vinted_app, "_load_vinted_metadata", side_effect=AssertionError("GET /unpublished must not contact Vinted")):
            response = self.client.get("/unpublished")
        self.assertEqual(response.status_code, 200)

    def test_edit_get_uses_cached_session_status_without_verifying_browser(self):
        draft_id = self.create_draft(title="Edit Cache Test")
        with patch.object(vinted_app, "_account_status", side_effect=AssertionError("edit GET must not verify Chromium")):
            response = self.client.get(f"/drafts/{draft_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Kategorien aktualisieren".encode(), response.data)

    def test_unpublished_page_has_individual_and_bulk_actions(self):
        self.create_draft(title="Importierter Entwurf")
        response = self.client.get("/unpublished")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Ausgewählte einstellen".encode(), response.data)
        self.assertIn("Veröffentlichen".encode(), response.data)
        self.assertIn("Bearbeiten".encode(), response.data)
        self.assertIn("Löschen".encode(), response.data)

    def test_unpublished_individual_delete_persists_even_if_image_cleanup_fails(self):
        draft_id = self.create_draft(title="Zu löschender Testentwurf")
        with patch.object(vinted_app, "_remove_draft_images", side_effect=PermissionError("image is busy")):
            response = self.client.post(
                f"/drafts/{draft_id}/delete",
                data={"next": "unpublished"},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/unpublished")
        self.assertIsNone(vinted_app._find_draft(draft_id))

    def test_unpublished_bulk_delete_persists_even_if_image_cleanup_fails(self):
        draft_id = self.create_draft(title="Zu löschender Sammeltest")
        with patch.object(vinted_app, "_remove_draft_images", side_effect=PermissionError("image is busy")):
            response = self.client.post(
                "/unpublished/bulk",
                data={"bulk_action": "delete", "draft_ids": [draft_id]},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/unpublished")
        self.assertIsNone(vinted_app._find_draft(draft_id))

    def test_unpublished_security_problem_shows_resume_and_external_browser_actions(self):
        draft_id = self.create_draft(title="Sicherheitsprüfung Test")
        draft = vinted_app._find_draft(draft_id)
        draft.update({
            "manual_review_confirmed": True, "category_verified": True, "category_id": "101",
            "security_challenge_required": True, "security_challenge_state": "waiting",
            "security_challenge_url": "https://geo.captcha-delivery.com/captcha/?cid=test",
            "security_challenge_started_at": vinted_app._now(),
            "security_challenge_deadline_at": (vinted_app.datetime.now(vinted_app.timezone.utc) + vinted_app.timedelta(minutes=20)).isoformat(timespec="seconds"),
            "status": "Sicherheitsprüfung erforderlich",
        })
        vinted_app._replace_draft(draft)
        response = self.client.get("/unpublished")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Prüfung erledigt – fortsetzen".encode(), response.data)
        self.assertIn("Sicherheitsabfrage öffnen".encode(), response.data)
        self.assertIn(b'target="_blank"', response.data)
        self.assertIn(f'/drafts/{draft_id}/security-browser'.encode(), response.data)

    def test_manager_security_continue_marks_request_and_requeues_stale_job(self):
        draft = {
            "id": "recover-sec-ui", "title": "Schlafsack", "published_item_id": "",
            "renewal_upload_pending": True, "automation_active": True, "photos": [],
            "security_challenge_required": True, "security_challenge_state": "waiting",
            "security_challenge_started_at": vinted_app._now(),
            "security_challenge_deadline_at": (vinted_app.datetime.now(vinted_app.timezone.utc) + vinted_app.timedelta(minutes=20)).isoformat(timespec="seconds"),
        }
        vinted_app._save_drafts([draft])
        vinted_app._save_bulk_publish_state({"queue": [], "current": {"draft_id": "recover-sec-ui", "action": "renew"}})
        with patch.object(vinted_app, "_bulk_publish_worker_alive", return_value=False), \
             patch.object(vinted_app, "_ensure_bulk_publish_worker") as ensure_worker:
            response = self.client.post("/unpublished/recover-sec-ui/security-continue", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        saved = vinted_app._find_draft("recover-sec-ui")
        self.assertTrue(saved.get("security_challenge_manual_continue_at"))
        self.assertTrue(saved.get("security_challenge_force_fresh_publish"))
        state = vinted_app._load_bulk_publish_state()
        self.assertEqual(state["current"], {})
        self.assertEqual(state["queue"], [{"draft_id": "recover-sec-ui", "action": "renew"}])
        ensure_worker.assert_called_once()

    def test_security_browser_route_focuses_exact_challenge_target(self):
        draft = {
            "id": "clarks-browser", "title": "Clarks Herren Sneaker",
            "published_item_id": "4711",
            "security_challenge_required": True, "security_challenge_state": "waiting",
            "security_challenge_target_id": "captcha-tab",
        }
        vinted_app._save_drafts([draft])
        target = {
            "id": "captcha-tab", "type": "page",
            "url": "https://geo.captcha-delivery.com/captcha/?cid=abc",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/captcha-tab",
        }
        with patch.object(vinted_app, "_start_login_browser"), \
             patch.object(vinted_app, "_hold_visible_browser_awake"), \
             patch.object(vinted_app, "_security_challenge_target", return_value=target), \
             patch.object(vinted_app, "_cdp_command", return_value={}) as cdp, \
             patch.object(vinted_app, "_novnc_url", return_value="http://example.test:6081/vnc.html"):
            response = self.client.get("/drafts/clarks-browser/security-browser", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "http://example.test:6081/vnc.html")
        cdp.assert_called_once_with(target, "Page.bringToFront", {}, timeout=4)

    def test_manager_security_continue_accepts_published_renewal_challenge(self):
        draft = {
            "id": "clarks-sec-ui", "title": "Clarks Herren Sneaker",
            "published_item_id": "4711", "published_url": "https://www.vinted.de/items/4711",
            "automation_active": True, "photos": [],
            "security_challenge_required": True, "security_challenge_state": "waiting",
            "security_challenge_started_at": vinted_app._now(),
            "security_challenge_deadline_at": (vinted_app.datetime.now(vinted_app.timezone.utc) + vinted_app.timedelta(minutes=20)).isoformat(timespec="seconds"),
        }
        vinted_app._save_drafts([draft])
        vinted_app._save_bulk_publish_state({
            "queue": [{"draft_id": "clarks-sec-ui", "action": "renew"}],
            "current": {"draft_id": "clarks-sec-ui", "action": "renew", "security_waiting": True},
        })
        with patch.object(vinted_app, "_ensure_bulk_publish_worker") as ensure_worker:
            response = self.client.post("/drafts/clarks-sec-ui/security-continue", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/"))
        saved = vinted_app._find_draft("clarks-sec-ui")
        self.assertTrue(saved.get("security_challenge_manual_continue_at"))
        self.assertTrue(saved.get("security_challenge_force_fresh_publish"))
        ensure_worker.assert_called_once()

    def test_wait_for_security_clearance_accepts_manager_continue_without_browser_signal(self):
        draft = {
            "id": "security-ui", "title": "Jacke", "published_item_id": "",
            "security_challenge_required": True, "security_challenge_state": "waiting",
            "security_challenge_started_at": vinted_app._now(),
            "security_challenge_deadline_at": (vinted_app.datetime.now(vinted_app.timezone.utc) + vinted_app.timedelta(minutes=20)).isoformat(timespec="seconds"),
            "security_challenge_manual_continue_at": vinted_app._now(),
        }
        vinted_app._save_drafts([draft])
        with patch.object(vinted_app, "_security_challenge_target", side_effect=AssertionError("browser target must not be required")), \
             patch.object(vinted_app.time, "sleep"):
            self.assertTrue(vinted_app._wait_for_security_clearance(draft))
        saved = vinted_app._find_draft("security-ui")
        self.assertEqual(saved["security_challenge_state"], "cleared")

    def test_publish_state_uses_draft_security_state_even_without_current_flag(self):
        draft = {
            "id": "security-state", "title": "Schlafsack", "published_item_id": "",
            "security_challenge_required": True, "security_challenge_state": "waiting",
        }
        vinted_app._save_drafts([draft])
        vinted_app._save_bulk_publish_state({
            "queue": [{"draft_id": "security-state", "action": "publish"}],
            "current": {"draft_id": "security-state", "action": "publish"},
        })
        view = vinted_app._publish_state_view()
        self.assertTrue(view["running"])
        self.assertTrue(view["security_waiting"])
        self.assertEqual(view["status"], "Sicherheitsprüfung erforderlich")

    def test_manual_vinted_audio_page_is_available(self):
        response = self.client.get("/vinted-audio")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Ton aus dem Vinted-Browser".encode(), response.data)
        self.assertIn("/vinted-audio/stream".encode(), response.data)

    def test_unpublished_page_puts_uncategorized_drafts_first_and_labels_review_state(self):
        drafts = [
            {"id": "processed", "title": "Bereits geprüft", "category": "Kinder > Schuhe", "category_id": "101", "category_verified": True, "manual_review_confirmed": True, "photos": [], "price": "12"},
            {"id": "unprocessed", "title": "Noch offen", "category": "", "category_id": "", "category_verified": False, "photos": [], "price": "10"},
        ]
        with patch.object(vinted_app, "_load_drafts", return_value=drafts):
            response = self.client.get("/unpublished")
        self.assertEqual(response.status_code, 200)
        self.assertLess(response.data.index("Noch offen".encode()), response.data.index("Bereits geprüft".encode()))
        self.assertIn("UNBEARBEITET".encode(), response.data)
        self.assertIn("BEARBEITET".encode(), response.data)

    def test_unpublished_page_shows_last_review_result(self):
        drafts = [{
            "id": "reviewed",
            "title": "Geprüfter Entwurf",
            "category": "Bücher > Comics",
            "category_id": "303",
            "category_verified": True,
            "last_review_summary": "Kategorie automatisch übernommen; Marke übernommen; offen: Farbe",
            "photos": [],
            "price": "10",
        }]
        with patch.object(vinted_app, "_load_drafts", return_value=drafts):
            response = self.client.get("/unpublished")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Kategorie automatisch übernommen".encode(), response.data)
        self.assertIn("offen: Farbe".encode(), response.data)

    def test_message_menu_contains_reserve_and_sold_but_no_duplicate_vinted_open(self):
        source = (Path(vinted_app.__file__).parent / "templates" / "message_thread.html").read_text("utf-8")
        self.assertIn('value="reserved"', source)
        self.assertIn('value="sold"', source)
        self.assertNotIn("Bei Vinted öffnen", source)

    def test_message_menu_can_release_a_reservation_from_the_header_menu(self):
        template = (Path(vinted_app.__file__).parent / "templates" / "message_thread.html").read_text("utf-8")
        stylesheet = (Path(vinted_app.__file__).parent / "static" / "style.css").read_text("utf-8")
        self.assertIn('value="activate"', template)
        self.assertIn("Reservierung aufheben", template)
        self.assertIn(".vinted-thread-page .vinted-chat-actions .vinted-more-popover{position:absolute;top:calc(100% + 7px)", stylesheet)

    def test_message_lists_render_item_state_overlays(self):
        messages = (Path(vinted_app.__file__).parent / "templates" / "messages.html").read_text("utf-8")
        thread = (Path(vinted_app.__file__).parent / "templates" / "message_thread.html").read_text("utf-8")
        stylesheet = (Path(vinted_app.__file__).parent / "static" / "style.css").read_text("utf-8")
        for state in ("reserved", "sold", "hidden", "deleted"):
            self.assertIn("entry.item_state == '" + state + "'", messages)
            self.assertIn("entry.item_state == '" + state + "'", thread)
            self.assertIn(".item-state-" + state, stylesheet)

    def test_saved_search_initial_snapshot_never_sends_a_push(self):
        source_url = "https://www.vinted.de/catalog?search_text=forschur&size_ids%5B%5D=625&search_id=2474429823&order=newest_first"
        searches = vinted_app._merge_discovered_searches([{"id": vinted_app._search_alert_id(source_url), "name": "forschur", "detail": "6 Jahre / 116", "source_url": source_url}])
        items = [{"id": "100", "url": "https://www.vinted.de/items/100-test", "title": "Testartikel", "detail": "Größe: 116", "image_url": ""}]
        with patch.object(vinted_app, "_catalog_search_items", return_value=items), \
             patch.object(vinted_app, "_notify_search_recipient") as notify:
            result = vinted_app._check_search_alert(searches[0]["id"])
        self.assertTrue(result["first_run"])
        notify.assert_not_called()
        saved = vinted_app._load_search_alert_state()["searches"][0]
        self.assertTrue(saved["initialized"])
        self.assertEqual(saved["seen_item_ids"], ["100"])
        self.assertEqual(saved["snapshot_item_ids"], ["100"])
        self.assertEqual(saved["snapshot_count"], 1)

    def test_saved_search_seen_history_is_append_only_across_reappearance(self):
        source_url = "https://www.vinted.de/catalog?search_text=forschur&search_id=seen-history"
        search = vinted_app._merge_discovered_searches([{
            "id": vinted_app._search_alert_id(source_url), "name": "forschur", "source_url": source_url,
        }])[0]
        rows = [
            [{"id": "old", "url": "https://www.vinted.de/items/old", "title": "Alt", "detail": "", "image_url": ""}],
            [{"id": "new", "url": "https://www.vinted.de/items/new", "title": "Neu", "detail": "", "image_url": ""}],
            [{"id": "old", "url": "https://www.vinted.de/items/old", "title": "Alt geändert", "detail": "", "image_url": ""}],
        ]
        with patch.object(vinted_app, "_catalog_search_items", side_effect=rows), \
             patch.object(vinted_app, "_ordered_search_additions", return_value=([], "", 0)), \
             patch.object(vinted_app, "_notify_search_recipient") as notify:
            vinted_app._check_search_alert(search["id"])
            vinted_app._check_search_alert(search["id"])
            result = vinted_app._check_search_alert(search["id"])
        saved = vinted_app._load_search_alert_state()["searches"][0]
        self.assertIn("old", saved["seen_item_ids"])
        self.assertIn("new", saved["seen_item_ids"])
        self.assertEqual(result["new_items"], [])
        notify.assert_not_called()

    def test_saved_search_sync_marks_verified_and_preserves_existing_baseline(self):
        source_url = "https://www.vinted.de/catalog?search_text=forschur&search_id=2474429823&order=newest_first"
        state = {
            "schema": 1,
            "searches": [{
                "id": vinted_app._search_alert_id(source_url),
                "name": "forschur",
                "source_url": source_url,
                "recipient": "primary",
                "active": True,
                "initialized": True,
                "seen_item_ids": ["old"],
                "matches": [{"id": "old"}],
            }],
        }
        vinted_app._save_search_alert_state(state)
        search = vinted_app._merge_discovered_searches([{
            "id": vinted_app._search_alert_id(source_url),
            "name": "forschur",
            "detail": "6 Jahre / 116",
            "source_url": source_url,
        }])[0]
        self.assertTrue(search["verified_saved_search"])
        self.assertEqual(search["verified_saved_search_generation"], vinted_app.SAVED_SEARCH_VERIFICATION_GENERATION)
        self.assertTrue(search["initialized"])
        self.assertEqual(search["seen_item_ids"], ["old"])
        self.assertEqual(search["matches"], [{"id": "old"}])
        self.assertEqual(vinted_app._load_search_alert_state()["schema"], 3)

    def test_saved_search_poll_skips_legacy_unverified_rows(self):
        source_url = "https://www.vinted.de/catalog?search_text=Kinder&catalog[]=123&order=newest_first"
        vinted_app._save_search_alert_state({
            "schema": 1,
            "searches": [{
                "id": vinted_app._search_alert_id(source_url),
                "name": "Kinder",
                "source_url": source_url,
                "active": True,
                "initialized": True,
                "seen_item_ids": ["1"],
            }],
        })
        with patch.object(vinted_app, "_check_search_alert") as check:
            vinted_app._poll_search_alerts()
        check.assert_not_called()

    def test_saved_search_poll_stops_batch_after_browser_transport_failure(self):
        first_url = "https://www.vinted.de/catalog?search_text=first&search_id=1111"
        second_url = "https://www.vinted.de/catalog?search_text=second&search_id=2222"
        vinted_app._save_search_alert_state({
            "schema": 3,
            "searches": [
                {
                    "id": vinted_app._search_alert_id(first_url),
                    "name": "first",
                    "source_url": first_url,
                    "active": True,
                    "verified_saved_search": True,
                    "verified_saved_search_generation": vinted_app.SAVED_SEARCH_VERIFICATION_GENERATION,
                },
                {
                    "id": vinted_app._search_alert_id(second_url),
                    "name": "second",
                    "source_url": second_url,
                    "active": True,
                    "verified_saved_search": True,
                    "verified_saved_search_generation": vinted_app.SAVED_SEARCH_VERIFICATION_GENERATION,
                },
            ],
        })
        with patch.object(vinted_app, "_saved_search_sync_snapshot", return_value={"alerts_suppressed": False}), \
             patch.object(vinted_app, "_check_search_alert", side_effect=RuntimeError("target crashed")) as check, \
             patch.object(vinted_app, "_recover_visible_browser_if_unhealthy", return_value=True) as recover:
            vinted_app._poll_search_alerts()
        self.assertEqual(check.call_count, 1)
        recover.assert_called_once()

    def test_saved_search_poll_is_silent_while_sync_rebuilds_state(self):
        source_url = "https://www.vinted.de/catalog?search_text=forschur&search_id=2474429823"
        search = vinted_app._merge_discovered_searches([{
            "id": vinted_app._search_alert_id(source_url),
            "name": "forschur",
            "source_url": source_url,
        }])[0]
        state = vinted_app._load_search_alert_state()
        state["searches"][0].update({
            "initialized": True,
            "snapshot_item_ids": ["old"],
            "active": True,
        })
        vinted_app._save_search_alert_state(state)
        with vinted_app._saved_search_sync_state_lock:
            vinted_app._saved_search_sync_state.update({"running": True, "alerts_suppressed": True})
        with patch.object(vinted_app, "_check_search_alert") as check:
            vinted_app._poll_search_alerts()
        check.assert_not_called()

    def test_saved_search_menu_walks_scrollable_saved_search_list(self):
        source = inspect.getsource(vinted_app._open_saved_search_menu)
        self.assertIn("scrollContainer.scrollTop", source)
        self.assertIn("scrollHeight - scrollContainer.clientHeight", source)
        self.assertIn("collectVisibleRows", source)

    def test_saved_search_multiple_new_items_are_grouped_into_one_push(self):
        source_url = "https://www.vinted.de/catalog?search_text=forschur&search_id=2474429823&order=newest_first"
        search = vinted_app._merge_discovered_searches([{
            "id": vinted_app._search_alert_id(source_url),
            "name": "forschur",
            "detail": "",
            "source_url": source_url,
        }])[0]
        first = [{"id": "100", "url": "https://www.vinted.de/items/100-alt", "title": "Alt", "detail": "", "image_url": ""}]
        second = [
            {"id": "103", "url": "https://www.vinted.de/items/103-neu", "title": "Neu 3", "detail": "", "image_url": ""},
            {"id": "102", "url": "https://www.vinted.de/items/102-neu", "title": "Neu 2", "detail": "", "image_url": ""},
            {"id": "101", "url": "https://www.vinted.de/items/101-neu", "title": "Neu 1", "detail": "", "image_url": ""},
        ] + first
        with patch.object(vinted_app, "_catalog_search_items", side_effect=[first, second]), \
             patch.object(vinted_app, "_catalog_item_detail_created_at", return_value=vinted_app._now()), \
             patch.object(vinted_app, "_notify_search_recipient", return_value=True) as notify:
            vinted_app._check_search_alert(search["id"])
            result = vinted_app._check_search_alert(search["id"])
        self.assertEqual(len(result["new_items"]), 3)
        notify.assert_called_once()
        recipient, title, message, path = notify.call_args.args
        self.assertEqual(recipient, "primary")
        self.assertEqual(title, "Vinted · Neue Anzeigen")
        self.assertEqual(message, "3 neue Anzeigen der gespeicherten Suche „forschur“ liegen vor.")
        self.assertEqual(path, f"/searches/{search['id']}/open")

    def test_saved_search_ignores_lower_page_churn_when_newest_item_is_unchanged(self):
        source_url = "https://www.vinted.de/catalog?search_text=forschur&search_id=2474429823"
        search = vinted_app._merge_discovered_searches([{
            "id": vinted_app._search_alert_id(source_url), "name": "forschur", "source_url": source_url,
        }])[0]
        first = [{"id": item_id, "url": f"https://www.vinted.de/items/{item_id}", "title": item_id, "detail": "", "image_url": ""} for item_id in ("100", "99", "98")]
        churned = [{"id": item_id, "url": f"https://www.vinted.de/items/{item_id}", "title": item_id, "detail": "", "image_url": ""} for item_id in ("100", "97", "96")]
        with patch.object(vinted_app, "_catalog_search_items", side_effect=[first, churned]), \
             patch.object(vinted_app, "_notify_search_recipient") as notify:
            vinted_app._check_search_alert(search["id"])
            result = vinted_app._check_search_alert(search["id"])
        self.assertEqual(result["new_items"], [])
        self.assertEqual(result["silent_rebaseline_reason"], "")
        notify.assert_not_called()

    def test_ordered_search_additions_accepts_fresh_unseen_id_even_below_numeric_watermark(self):
        now = vinted_app._now()
        rows = [{
            "id": "150", "url": "https://www.vinted.de/items/150",
            "title": "Alt", "detail": "", "image_url": "", "created_at": now,
        }, {
            "id": "200", "url": "https://www.vinted.de/items/200",
            "title": "Bekannt", "detail": "", "image_url": "", "created_at": now,
        }]
        additions, reason, count = vinted_app._ordered_search_additions(
            rows, ["200"], {"200"}, max_seen_item_id=200, last_success_at=now
        )
        self.assertEqual(additions, [rows[0]])
        self.assertEqual(reason, "")
        self.assertEqual(count, 0)

    def test_ordered_search_additions_requires_freshness_baseline(self):
        rows = [{
            "id": "201", "url": "https://www.vinted.de/items/201",
            "title": "Unklar", "detail": "", "image_url": "", "created_at": vinted_app._now(),
        }, {
            "id": "200", "url": "https://www.vinted.de/items/200",
            "title": "Bekannt", "detail": "", "image_url": "", "created_at": vinted_app._now(),
        }]
        additions, reason, _count = vinted_app._ordered_search_additions(
            rows, ["200"], {"200"}, max_seen_item_id=200, last_success_at=""
        )
        self.assertEqual(additions, [])
        self.assertEqual(reason, "missing_freshness_baseline")

    def test_ordered_search_additions_rejects_item_older_than_poll_window(self):
        now = vinted_app.datetime.now(vinted_app.timezone.utc)
        rows = [{
            "id": "201", "url": "https://www.vinted.de/items/201",
            "title": "Zu alt", "detail": "", "image_url": "",
            "created_at": (now - vinted_app.timedelta(seconds=vinted_app.SEARCH_ALERT_POLL_SECONDS + 1)).isoformat(),
        }]
        additions, reason, count = vinted_app._ordered_search_additions(
            rows, ["200"], {"200"}, max_seen_item_id=200,
            last_success_at=(now - vinted_app.timedelta(seconds=10)).isoformat(),
        )
        self.assertEqual(additions, [])
        self.assertEqual(reason, "old_backfill")
        self.assertEqual(count, 1)

    def test_ordered_search_additions_never_uses_numeric_id_without_verified_age(self):
        rows = [{
            "id": "9999999999", "url": "https://www.vinted.de/items/9999999999",
            "title": "Unbekanntes Alter", "detail": "", "image_url": "",
            "_age_unverified": "1",
        }]
        additions, reason, count = vinted_app._ordered_search_additions(
            rows, ["100"], {"100"}, max_seen_item_id=100, last_success_at=vinted_app._now()
        )
        self.assertEqual(additions, [])
        self.assertEqual(reason, "age_unverified")
        self.assertEqual(count, 1)

    def test_relative_vinted_upload_datetime_accepts_vinted_few_seconds_label(self):
        before = vinted_app.datetime.now(vinted_app.timezone.utc)
        parsed = vinted_app._relative_vinted_upload_datetime("Hochgeladen wenigen Sek.")
        after = vinted_app.datetime.now(vinted_app.timezone.utc)
        self.assertIsNotNone(parsed)
        self.assertGreaterEqual(parsed, before - vinted_app.timedelta(seconds=11))
        self.assertLessEqual(parsed, after)

    def test_relative_vinted_upload_datetime_accepts_hour_short_form(self):
        before = vinted_app.datetime.now(vinted_app.timezone.utc)
        parsed = vinted_app._relative_vinted_upload_datetime("Hochgeladen 17 h")
        after = vinted_app.datetime.now(vinted_app.timezone.utc)
        self.assertIsNotNone(parsed)
        self.assertGreaterEqual(parsed, before - vinted_app.timedelta(hours=17, seconds=1))
        self.assertLessEqual(parsed, after - vinted_app.timedelta(hours=17) + vinted_app.timedelta(seconds=1))

    def test_saved_search_latest_item_age_label_uses_newest_verified_timestamp(self):
        now = vinted_app.datetime.now(vinted_app.timezone.utc)
        search = {"snapshot_items": [
            {"id": "old", "created_at": (now - vinted_app.timedelta(weeks=2)).isoformat(), "created_at_verified": "1"},
            {"id": "new", "created_at": (now - vinted_app.timedelta(hours=3)).isoformat(), "created_at_verified": "1"},
        ]}
        self.assertEqual(vinted_app._saved_search_latest_item_age_label(search), "3 Stunden")

    def test_saved_search_latest_item_age_ignores_unverified_catalog_timestamp(self):
        search = {"snapshot_items": [{"id": "new", "created_at": vinted_app._now()}]}
        self.assertEqual(vinted_app._saved_search_latest_item_age_label(search), "")

    def test_saved_search_reuses_verified_upload_time_from_snapshot(self):
        created_at = (vinted_app.datetime.now(vinted_app.timezone.utc) - vinted_app.timedelta(hours=2)).isoformat()
        items = [{"id": "9855280423", "url": "https://www.vinted.de/items/9855280423"}]
        vinted_app._restore_search_snapshot_ages(items, [{"id": "9855280423", "created_at": created_at, "created_at_verified": "1"}])
        self.assertEqual(items[0]["created_at"], created_at)
        self.assertEqual(items[0]["created_at_verified"], "1")

    def test_saved_search_reads_one_newest_item_for_legacy_age_display(self):
        items = [{"id": "9855280423", "url": "https://www.vinted.de/items/9855280423"}]
        created_at = (vinted_app.datetime.now(vinted_app.timezone.utc) - vinted_app.timedelta(hours=17)).isoformat()
        with patch.object(vinted_app, "_catalog_item_detail_created_at", return_value=created_at) as item_page:
            vinted_app._enrich_search_newest_item_age(items)
        self.assertEqual(items[0]["created_at"], created_at)
        self.assertEqual(items[0]["created_at_verified"], "1")
        item_page.assert_called_once_with("9855280423", "https://www.vinted.de/items/9855280423")

    def test_saved_search_normalizes_nested_percent_encoding_into_one_identity(self):
        normal = "https://www.vinted.de/catalog?search_text=Merino%20100%20cardigan&order=newest_first"
        nested = "https://www.vinted.de/catalog?order=newest_first&search_text=Merino%2520100%2520cardigan"
        self.assertEqual(vinted_app._search_alert_id(normal), vinted_app._search_alert_id(nested))
        self.assertEqual(
            dict(parse_qsl(urlparse(vinted_app._safe_vinted_catalog_url(nested)).query)),
            {"order": "newest_first", "search_text": "Merino 100 cardigan"},
        )

    def test_saved_search_repair_merges_encoded_duplicates_and_preserves_seen_ids(self):
        normal = "https://www.vinted.de/catalog?search_text=Merino%20100%20cardigan&order=newest_first"
        nested = "https://www.vinted.de/catalog?search_text=Merino%2520100%2520cardigan&order=newest_first"
        rows = vinted_app._deduplicate_saved_search_rows([
            {"id": "old-one", "name": "Merino 100 cardigan", "source_url": normal, "recipient": "primary", "seen_item_ids": ["10"], "active": True},
            {"id": "old-two", "name": "Merino%20100%20cardigan", "source_url": nested, "recipient": "secondary", "seen_item_ids": ["11"], "active": True},
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Merino 100 cardigan")
        self.assertEqual(rows[0]["recipient"], "both")
        self.assertEqual(rows[0]["seen_item_ids"], ["10", "11"])

    def test_saved_search_identity_keeps_same_text_with_different_vinted_ids_separate(self):
        first = "https://www.vinted.de/catalog?search_text=forschur&search_id=111"
        second = "https://www.vinted.de/catalog?search_text=forschur&search_id=222"
        self.assertNotEqual(vinted_app._search_alert_id(first), vinted_app._search_alert_id(second))

    def test_saved_search_does_not_push_high_id_when_age_lookup_fails(self):
        source_url = "https://www.vinted.de/catalog?search_text=Merino%20100%20cardigan&search_id=merino-age-fallback"
        search = vinted_app._merge_discovered_searches([{
            "id": vinted_app._search_alert_id(source_url),
            "name": "Merino 100 cardigan",
            "source_url": source_url,
        }])[0]
        first = [{
            "id": "100", "url": "https://www.vinted.de/items/100", "title": "Bekannt",
            "detail": "", "image_url": "", "created_at": vinted_app._now(),
        }]
        old_reordered_high_id = [{
            "id": "9999999999", "url": "https://www.vinted.de/items/9999999999",
            "title": "Alt wieder einsortiert", "detail": "", "image_url": "",
        }, *first]
        with patch.object(vinted_app, "_catalog_search_items", side_effect=[first, old_reordered_high_id]), \
             patch.object(vinted_app, "_catalog_item_detail_created_at", return_value=""), \
             patch.object(vinted_app, "_notify_search_recipient") as notify:
            vinted_app._check_search_alert(search["id"])
            result = vinted_app._check_search_alert(search["id"])
        self.assertEqual(result["new_items"], [])
        self.assertEqual(result["silent_rebaseline_reason"], "age_unverified")
        notify.assert_not_called()
        saved = vinted_app._load_search_alert_state()["searches"][0]
        self.assertNotIn("9999999999", saved["seen_item_ids"])
        self.assertIn("Uploadzeit", saved["last_error"])

    def test_saved_search_never_pushes_old_backfill_that_moves_to_the_front(self):
        source_url = "https://www.vinted.de/catalog?search_text=forschur&search_id=backfill"
        search = vinted_app._merge_discovered_searches([{
            "id": vinted_app._search_alert_id(source_url), "name": "forschur", "source_url": source_url,
        }])[0]
        first = [
            {"id": item_id, "url": f"https://www.vinted.de/items/{item_id}", "title": item_id, "detail": "", "image_url": ""}
            for item_id in ("200", "199", "198")
        ]
        # 150 was not on the previous visible page, but is older than every
        # known listing. It can surface after a newer row is hidden/reserved.
        reordered = [
            {"id": "150", "url": "https://www.vinted.de/items/150", "title": "Alt wieder sichtbar", "detail": "", "image_url": ""},
            *first,
        ]
        old_timestamp = (vinted_app.datetime.now(vinted_app.timezone.utc) - vinted_app.timedelta(hours=19)).isoformat()
        with patch.object(vinted_app, "_catalog_search_items", side_effect=[first, reordered]), \
             patch.object(vinted_app, "_catalog_item_detail_created_at", return_value=old_timestamp), \
             patch.object(vinted_app, "_notify_search_recipient") as notify:
            vinted_app._check_search_alert(search["id"])
            result = vinted_app._check_search_alert(search["id"])
        self.assertEqual(result["new_items"], [])
        self.assertEqual(result["silent_rebaseline_reason"], "old_backfill")
        notify.assert_not_called()

    def test_saved_search_pushes_fresh_item_even_when_result_page_has_no_overlap(self):
        source_url = "https://www.vinted.de/catalog?search_text=forschur&search_id=2474429823"
        search = vinted_app._merge_discovered_searches([{
            "id": vinted_app._search_alert_id(source_url), "name": "forschur", "source_url": source_url,
        }])[0]
        first = [{"id": item_id, "url": f"https://www.vinted.de/items/{item_id}", "title": item_id, "detail": "", "image_url": ""} for item_id in ("100", "99")]
        different = [{"id": item_id, "url": f"https://www.vinted.de/items/{item_id}", "title": item_id, "detail": "", "image_url": ""} for item_id in ("50", "49")]
        with patch.object(vinted_app, "_catalog_search_items", side_effect=[first, different]), \
             patch.object(vinted_app, "_catalog_item_detail_created_at", return_value=vinted_app._now()), \
             patch.object(vinted_app, "_notify_search_recipient") as notify:
            vinted_app._check_search_alert(search["id"])
            result = vinted_app._check_search_alert(search["id"])
        self.assertEqual([item["id"] for item in result["new_items"]], ["50", "49"])
        self.assertEqual(result["silent_rebaseline_reason"], "")
        notify.assert_called_once()

    def test_saved_search_suppresses_implausible_mass_insertion(self):
        source_url = "https://www.vinted.de/catalog?search_text=wildling&search_id=3"
        search = vinted_app._merge_discovered_searches([{
            "id": vinted_app._search_alert_id(source_url), "name": "wildling", "source_url": source_url,
        }])[0]
        first = [{"id": "100", "url": "https://www.vinted.de/items/100", "title": "Alt", "detail": "", "image_url": ""}]
        inserted = [
            {"id": str(item_id), "url": f"https://www.vinted.de/items/{item_id}", "title": str(item_id), "detail": "", "image_url": ""}
            for item_id in range(200, 200 - vinted_app.SEARCH_ALERT_MAX_NEW_PER_CYCLE - 1, -1)
        ] + first
        with patch.object(vinted_app, "_catalog_search_items", side_effect=[first, inserted]), \
             patch.object(vinted_app, "_notify_search_recipient") as notify:
            vinted_app._check_search_alert(search["id"])
            result = vinted_app._check_search_alert(search["id"])
        self.assertEqual(result["new_items"], [])
        self.assertEqual(result["silent_rebaseline_reason"], "large_change")
        self.assertEqual(result["silent_rebaseline_count"], vinted_app.SEARCH_ALERT_MAX_NEW_PER_CYCLE + 1)
        notify.assert_not_called()

    def test_saved_search_can_notify_after_an_explicit_empty_baseline(self):
        source_url = "https://www.vinted.de/catalog?search_text=selten&search_id=4"
        search = vinted_app._merge_discovered_searches([{
            "id": vinted_app._search_alert_id(source_url), "name": "selten", "source_url": source_url,
        }])[0]
        new_item = {"id": "101", "url": "https://www.vinted.de/items/101", "title": "Neu", "detail": "", "image_url": "", "created_at": vinted_app._now()}
        with patch.object(vinted_app, "_catalog_search_items", side_effect=[[], [new_item]]), \
             patch.object(vinted_app, "_notify_search_recipient", return_value=True) as notify:
            vinted_app._check_search_alert(search["id"])
            result = vinted_app._check_search_alert(search["id"])
        self.assertEqual([item["id"] for item in result["new_items"]], ["101"])
        notify.assert_called_once()

    def test_saved_search_notifies_only_selected_recipient_for_new_item(self):
        source_url = "https://www.vinted.de/catalog?search_text=forschur&search_id=2474429823&order=newest_first"
        search = vinted_app._merge_discovered_searches([{"id": vinted_app._search_alert_id(source_url), "name": "forschur", "detail": "", "source_url": source_url}])[0]
        first = [{"id": "100", "url": "https://www.vinted.de/items/100-test", "title": "Alt", "detail": "Größe: 116", "image_url": ""}]
        second = [{"id": "101", "url": "https://www.vinted.de/items/101-neu", "title": "Neu", "detail": "Größe: 116", "image_url": "", "created_at": vinted_app._now()}] + first
        with patch.object(vinted_app, "_catalog_search_items", side_effect=[first, second]), \
             patch.object(vinted_app, "_notify_search_recipient", return_value=True) as notify:
            vinted_app._check_search_alert(search["id"])
            result = vinted_app._check_search_alert(search["id"])
        self.assertEqual([item["id"] for item in result["new_items"]], ["101"])
        notify.assert_called_once()
        recipient, title, message, path = notify.call_args.args
        self.assertEqual(recipient, "primary")
        self.assertEqual(title, "Vinted · Neue Anzeige")
        self.assertEqual(message, "Eine neue Anzeige der gespeicherten Suche „forschur“ liegt vor.")
        self.assertEqual(path, "https://www.vinted.de/items/101-neu")

    def test_saved_search_notification_includes_filter_detail(self):
        source_url = "https://www.vinted.de/catalog?search_text=forschur&size_ids%5B%5D=625&search_id=2474429823"
        search = vinted_app._merge_discovered_searches([{
            "id": vinted_app._search_alert_id(source_url), "name": "forschur",
            "detail": "6 Jahre / 116", "source_url": source_url,
        }])[0]
        first = [{"id": "100", "url": "https://www.vinted.de/items/100-test", "title": "Alt", "detail": "", "image_url": ""}]
        second = [{"id": "101", "url": "https://www.vinted.de/items/101-neu", "title": "Neu", "detail": "", "image_url": "", "created_at": vinted_app._now()}] + first
        with patch.object(vinted_app, "_catalog_search_items", side_effect=[first, second]), \
             patch.object(vinted_app, "_notify_search_recipient", return_value=True) as notify:
            vinted_app._check_search_alert(search["id"])
            vinted_app._check_search_alert(search["id"])
        _, title, message, _ = notify.call_args.args
        self.assertIn("6 Jahre / 116", title)
        self.assertIn("6 Jahre / 116", message)

    def test_search_alerts_route_only_to_selected_webpush_people(self):
        with patch.object(vinted_app, "_send_webpush_to_person", return_value=True) as notify:
            self.assertTrue(vinted_app._notify_search_recipient("none", "Titel", "Text", "/searches"))
            notify.assert_not_called()
            self.assertTrue(vinted_app._notify_search_recipient("primary", "Titel", "Text", "/searches"))
            notify.assert_called_once_with("primary", "Titel", "Text", "/searches")
            notify.reset_mock()
            self.assertTrue(vinted_app._notify_search_recipient("secondary", "Titel", "Text", "/searches"))
            notify.assert_called_once_with("secondary", "Titel", "Text", "/searches")
            notify.reset_mock()
            self.assertTrue(vinted_app._notify_search_recipient("both", "Titel", "Text", "/searches"))
            self.assertEqual([call.args[0] for call in notify.call_args_list], ["primary", "secondary"])

    def test_one_search_hit_passes_its_vinted_image_to_webpush(self):
        image = "https://images1.vinted.net/t/03_1234567890abcdef0123456789abcdef/310x430/1234567890.jpeg"
        with patch.object(vinted_app, "_send_webpush_to_person", return_value=True) as notify:
            self.assertTrue(vinted_app._notify_search_recipient("primary", "Titel", "Text", "https://www.vinted.de/items/123", image_url=image))
        notify.assert_called_once_with("primary", "Titel", "Text", "https://www.vinted.de/items/123", image_url=image)

    def test_webpush_uses_vinted_item_photo_as_icon_and_expanded_image(self):
        image = "https://images1.vinted.net/t/03_1234567890abcdef0123456789abcdef/310x430/1234567890.jpeg"
        vinted_app._save_webpush_devices_unlocked({
            "schema": 1,
            "devices": [{"id": "iphone", "person": "primary", "active": True, "name": "iPhone", "subscription": {"endpoint": "https://push.example.test/endpoint", "keys": {}}}],
        })
        with patch.object(vinted_app, "send_webpush") as deliver:
            self.assertTrue(vinted_app._send_webpush_to_person("primary", "Titel", "Text", "https://www.vinted.de/items/123", image_url=image))
        payload = deliver.call_args.args[1]
        self.assertEqual(payload["notification"]["icon"], image)
        self.assertEqual(payload["notification"]["image"], image)
        self.assertEqual(payload["image"], image)

    def test_manager_manifest_uses_the_vinted_manager_icon(self):
        response = self.client.get("/manager.webmanifest")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["name"], "Vinted Manager")
        self.assertEqual(payload["icons"][0]["src"], "/push-icon-192.png")

    def test_search_alerts_both_attempts_second_person_even_if_first_fails(self):
        with patch.object(vinted_app, "_send_webpush_to_person", side_effect=[False, True]) as notify:
            self.assertFalse(vinted_app._notify_search_recipient("both", "Titel", "Text", "/searches"))
        self.assertEqual([call.args[0] for call in notify.call_args_list], ["primary", "secondary"])

    def test_message_and_general_push_services_are_separated(self):
        (vinted_app.DATA_DIR / "options.json").write_text(
            json.dumps({"notify_service": "notify.mobile_app_primary_private"}), "utf-8"
        )
        with patch.object(vinted_app, "_notify_service", return_value=True) as notify:
            self.assertTrue(vinted_app._notify_message("Nachricht", "Text", "/messages/1"))
            self.assertTrue(vinted_app._notify_general("Problem", "Text", "/"))
        self.assertEqual(notify.call_args_list[0].args[0], "notify.notify")
        self.assertEqual(notify.call_args_list[1].args[0], "notify.mobile_app_primary_private")

    def test_primary_system_push_never_uses_broadcast_fallback(self):
        (vinted_app.DATA_DIR / "options.json").write_text(
            json.dumps({"notify_service": "notify.notify"}), "utf-8"
        )
        vinted_app._save_app_settings({"schema": 1, "push_targets": {"primary": "notify.mobile_app_primary_private"}})
        self.assertEqual(vinted_app._configured_primary_notify_service(), "notify.mobile_app_primary_private")

    def test_primary_critical_push_is_silent_critical(self):
        (vinted_app.DATA_DIR / "options.json").write_text(
            json.dumps({"notify_service": "notify.mobile_app_primary_private"}), "utf-8"
        )
        with patch.object(vinted_app, "_notify_service", return_value=True) as notify:
            self.assertTrue(vinted_app._notify_primary_critical("Titel", "Text", "/live"))
        notify.assert_called_once_with(
            "notify.mobile_app_primary_private", "Titel", "Text", "/live",
            extra_data={"push": {"sound": {"name": "default", "critical": 1, "volume": 0.0}}},
        )

    def test_slow_search_check_preserves_recipient_changed_while_fetching(self):
        source_url = "https://www.vinted.de/catalog?search_text=forschur&search_id=5"
        search_id = vinted_app._search_alert_id(source_url)
        vinted_app._save_search_alert_state({
            "schema": 2,
            "searches": [{
                "id": search_id, "name": "forschur", "source_url": source_url,
                "recipient": "primary", "active": True, "verified_saved_search": True,
                "verified_saved_search_generation": vinted_app.SAVED_SEARCH_VERIFICATION_GENERATION,
                "initialized": True, "snapshot_item_ids": ["100"], "snapshot_at": vinted_app._now(), "last_success_at": vinted_app._now(), "freshness_schema": vinted_app.SEARCH_ALERT_FRESHNESS_SCHEMA,
                "seen_item_ids": ["100"], "matches": [],
            }],
        })
        items = [
            {"id": "101", "url": "https://www.vinted.de/items/101", "title": "Neu", "detail": "", "image_url": "", "created_at": vinted_app._now()},
            {"id": "100", "url": "https://www.vinted.de/items/100", "title": "Alt", "detail": "", "image_url": ""},
        ]

        def fetch_and_change_recipient(*_args, **_kwargs):
            state = vinted_app._load_search_alert_state()
            state["searches"][0]["recipient"] = "both"
            vinted_app._save_search_alert_state(state)
            return items

        with patch.object(vinted_app, "_catalog_search_items", side_effect=fetch_and_change_recipient), \
             patch.object(vinted_app, "_notify_search_recipient", return_value=True) as notify:
            vinted_app._check_search_alert(search_id)
        self.assertEqual(notify.call_args.args[0], "both")
        self.assertEqual(vinted_app._load_search_alert_state()["searches"][0]["recipient"], "both")

    def test_saved_search_poll_urls_force_newest_first_without_losing_filters(self):
        api = "https://www.vinted.de/api/v2/catalog/items?page=4&per_page=96&search_text=forschur&size_ids=625&order=relevance"
        public = "https://www.vinted.de/catalog?page=3&search_text=forschur&size_ids%5B%5D=625&order=relevance"
        api_params = dict(parse_qsl(urlparse(vinted_app._catalog_api_poll_url(api)).query))
        public_params = dict(parse_qsl(urlparse(vinted_app._catalog_page_poll_url(public)).query))
        self.assertEqual(api_params["page"], "1")
        self.assertEqual(api_params["order"], "newest_first")
        self.assertEqual(api_params["size_ids"], "625")
        self.assertEqual(public_params["page"], "1")
        self.assertEqual(public_params["order"], "newest_first")
        self.assertEqual(public_params["size_ids[]"], "625")

    def test_saved_search_poll_api_url_adds_fresh_cachebuster(self):
        api = "https://www.vinted.de/api/v2/catalog/items?page=4&per_page=96&search_text=forschur&size_ids=625&order=relevance&time=1"
        with patch.object(vinted_app.time, "time", side_effect=[1000.001, 1000.999]):
            first = dict(parse_qsl(urlparse(vinted_app._catalog_api_poll_url(api)).query))
            second = dict(parse_qsl(urlparse(vinted_app._catalog_api_poll_url(api)).query))
        self.assertNotEqual(first["time"], second["time"])
        self.assertEqual(first["disable_search_saving"], "true")
        self.assertEqual(first["size_ids"], "625")
        self.assertEqual(first["order"], "newest_first")

    def test_ordered_search_additions_accepts_item_from_delayed_poll_window(self):
        now = vinted_app.datetime.now(vinted_app.timezone.utc)
        rows = [{
            "id": "201", "url": "https://www.vinted.de/items/201",
            "title": "Neu trotz verspätetem Lauf", "detail": "", "image_url": "",
            "created_at": (now - vinted_app.timedelta(seconds=90)).isoformat(),
        }]
        additions, reason, count = vinted_app._ordered_search_additions(
            rows, ["200"], {"200"}, max_seen_item_id=200,
            last_success_at=(now - vinted_app.timedelta(seconds=150)).isoformat(),
        )
        self.assertEqual(additions, rows)
        self.assertEqual(reason, "")
        self.assertEqual(count, 0)

    def test_saved_search_newest_age_is_not_blocked_by_older_verified_row(self):
        now = vinted_app.datetime.now(vinted_app.timezone.utc)
        items = [
            {"id": "new", "url": "https://www.vinted.de/items/new"},
            {"id": "old", "url": "https://www.vinted.de/items/old",
             "created_at": (now - vinted_app.timedelta(hours=12)).isoformat(), "created_at_verified": "1"},
        ]
        fresh = (now - vinted_app.timedelta(minutes=2)).isoformat()
        with patch.object(vinted_app, "_catalog_item_detail_created_at", return_value=fresh) as detail:
            vinted_app._enrich_search_newest_item_age(items)
        self.assertEqual(items[0]["created_at"], fresh)
        self.assertEqual(items[0]["created_at_verified"], "1")
        detail.assert_called_once()

    def test_search_alert_page_uses_local_time_and_recipient_options(self):
        source_url = "https://www.vinted.de/catalog?search_text=forschur&search_id=2474429823"
        search = vinted_app._merge_discovered_searches([{
            "id": vinted_app._search_alert_id(source_url), "name": "forschur",
            "detail": "Keine Filter", "source_url": source_url,
        }])[0]
        state = vinted_app._load_search_alert_state()
        state["searches"][0]["last_checked_at"] = "2026-08-29T15:00:00+00:00"
        vinted_app._save_search_alert_state(state)
        response = self.client.get("/searches")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Niemand", response.data)
        self.assertIn(b"primary", response.data)
        self.assertIn(b"secondary", response.data)
        self.assertIn(b"17:00 Uhr", response.data)
        self.assertNotIn(b"2026-08-29", response.data)
        self.assertNotIn(b"alle 5 Minuten", response.data)

    def test_search_alert_page_offers_bulk_recipient_setting(self):
        first_url = "https://www.vinted.de/catalog?search_text=erster&search_id=1"
        second_url = "https://www.vinted.de/catalog?search_text=zweiter&search_id=2"
        vinted_app._merge_discovered_searches([
            {"id": vinted_app._search_alert_id(first_url), "name": "erster", "source_url": first_url},
            {"id": vinted_app._search_alert_id(second_url), "name": "zweiter", "source_url": second_url},
        ])
        response = self.client.get("/searches")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Ausgewählte Pushs an:".encode(), response.data)
        self.assertIn("Alle auswählen".encode(), response.data)
        self.assertIn(b'action="/searches/settings"', response.data)

    def test_bulk_search_alert_recipient_update_preserves_monitoring_state(self):
        first_url = "https://www.vinted.de/catalog?search_text=erster&search_id=1"
        second_url = "https://www.vinted.de/catalog?search_text=zweiter&search_id=2"
        vinted_app._save_search_alert_state({
            "schema": 2,
            "searches": [
                {"id": "first", "name": "erster", "recipient": "primary", "active": True, "source_url": first_url},
                {"id": "second", "name": "zweiter", "recipient": "secondary", "active": False, "source_url": second_url},
            ],
        })
        response = self.client.post(
            "/searches/settings",
            data={"search_ids": ["first"], "recipient_primary": "1", "recipient_secondary": "1"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        saved = vinted_app._load_search_alert_state()["searches"]
        self.assertEqual([row["recipient"] for row in saved], ["both", "secondary"])
        self.assertEqual([row["active"] for row in saved], [True, False])

    def test_individual_search_alert_saves_preserve_previous_recipient_change(self):
        vinted_app._save_search_alert_state({
            "schema": 2,
            "searches": [
                {"id": "first", "name": "erster", "recipient": "primary", "active": True},
                {"id": "second", "name": "zweiter", "recipient": "primary", "active": True},
            ],
        })
        form = {"recipient_primary": "1", "recipient_secondary": "1", "active": "1", "poll_interval_minutes": "1"}
        self.assertEqual(self.client.post("/searches/first/settings", data=form).status_code, 302)
        self.assertEqual(self.client.post("/searches/second/settings", data=form).status_code, 302)
        saved = vinted_app._load_search_alert_state()["searches"]
        self.assertEqual([row["recipient"] for row in saved], ["both", "both"])

    def test_saved_search_alert_poll_interval_is_one_minute(self):
        self.assertEqual(vinted_app.SEARCH_ALERT_POLL_SECONDS, 60)

    def test_saved_search_monitor_runs_alerts_after_one_minute(self):
        vinted_app._save_search_monitor_state({
            "saved_searches_synced_at": 1000.0,
            "search_alerts_checked_at": 1000.0,
        })
        with patch.object(vinted_app, "_poll_search_alerts") as poll:
            vinted_app._run_saved_search_monitor_cycle(now=1059.0)
            poll.assert_not_called()
            vinted_app._run_saved_search_monitor_cycle(now=1060.0)
            poll.assert_called_once_with()

    def test_saved_search_monitor_does_not_poll_during_sync(self):
        vinted_app._save_search_monitor_state({
            "saved_searches_synced_at": 1000.0,
            "search_alerts_checked_at": 1000.0,
        })
        with vinted_app._saved_search_sync_state_lock:
            vinted_app._saved_search_sync_state.update({"running": True, "alerts_suppressed": True})
        with patch.object(vinted_app, "_poll_search_alerts") as poll:
            vinted_app._run_saved_search_monitor_cycle(now=1060.0)
        poll.assert_not_called()

    def test_saved_search_auto_sync_keeps_strict_ten_minute_cadence_for_legacy_rows(self):
        vinted_app._save_search_monitor_state({
            "saved_searches_synced_at": 1000.0,
            "search_alerts_checked_at": 1000.0,
        })
        vinted_app._save_search_alert_state({
            "schema": 2,
            "searches": [{"id": "legacy", "name": "Alt", "verified_saved_search": False}],
        })
        with patch.object(vinted_app, "_poll_search_alerts"), \
             patch.object(vinted_app, "_start_saved_search_sync", return_value=True) as start_sync:
            vinted_app._run_saved_search_monitor_cycle(now=1599.0)
            start_sync.assert_not_called()
            vinted_app._run_saved_search_monitor_cycle(now=1600.0)
            start_sync.assert_called_once_with(replace=True, source="automatic")

    def test_manual_saved_search_sync_is_queued_while_automatic_sync_runs(self):
        with vinted_app._saved_search_sync_state_lock:
            vinted_app._saved_search_sync_state.update({
                "running": True, "manual_pending": False, "source": "automatic",
                "alerts_suppressed": False,
            })
        with patch.object(vinted_app.threading, "Thread") as thread:
            self.assertTrue(vinted_app._start_saved_search_sync(replace=True, source="manual"))
        thread.assert_not_called()
        self.assertTrue(vinted_app._saved_search_sync_snapshot().get("manual_pending"))

    def test_saved_search_match_page_opens_saved_vinted_item(self):
        source_url = "https://www.vinted.de/catalog?search_text=forschur&search_id=2474429823"
        search = vinted_app._merge_discovered_searches([{"id": vinted_app._search_alert_id(source_url), "name": "forschur", "detail": "", "source_url": source_url}])[0]
        with patch.object(vinted_app, "_catalog_search_items", return_value=[{"id": "101", "url": "https://www.vinted.de/items/101-neu", "title": "Neu", "detail": "Größe: 116", "image_url": ""}]):
            vinted_app._check_search_alert(search["id"])
        response = self.client.get(f"/searches/{search['id']}/matches/101")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Artikel bei Vinted öffnen".encode(), response.data)
        self.assertIn(b"https://www.vinted.de/items/101-neu", response.data)

    def test_notification_service_accepts_direct_vinted_search_url(self):
        source_url = "https://www.vinted.de/catalog?search_text=forschur&search_id=2474429823"
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
        with patch.dict(vinted_app.os.environ, {"SUPERVISOR_TOKEN": "token"}), \
             patch.object(vinted_app, "urlopen", return_value=Response()) as request_call:
            ok = vinted_app._notify_service("notify.mobile_app_example_iphone", "Titel", "Text", source_url)
        self.assertTrue(ok)
        request = request_call.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["data"]["url"], source_url)
        self.assertEqual(payload["data"]["clickAction"], source_url)

    def test_saved_search_url_requires_vinted_catalog(self):
        self.assertTrue(vinted_app._safe_vinted_catalog_url("https://www.vinted.de/catalog?search_id=1"))
        self.assertFalse(vinted_app._safe_vinted_catalog_url("https://evil.example/catalog?search_id=1"))
        self.assertFalse(vinted_app._safe_vinted_catalog_url("https://www.vinted.de/items/1"))

    def test_saved_search_accepts_filtered_catalog_without_search_id(self):
        url = "https://www.vinted.de/catalog?search_text=forschur&catalog[]=123&order=newest_first"
        self.assertEqual(vinted_app._usable_vinted_saved_search_url(url), url)
        self.assertFalse(vinted_app._usable_vinted_saved_search_url("https://www.vinted.de/catalog"))

    def test_saved_search_click_accepts_catalog_query_without_search_id(self):
        page = {"id": "main", "url": "https://www.vinted.de/catalog?search_text=forschur&order=newest_first"}
        row = {"name": "forschur", "detail": "", "x": 100, "y": 100}
        with patch.object(vinted_app, "_click_vinted_point"), \
             patch.object(vinted_app, "_refresh_browser_target", return_value=page):
            result = vinted_app._saved_search_url_after_click(page, row)
        self.assertEqual(result, page["url"])

    def test_saved_search_waits_for_the_vinted_header_then_uses_a_real_click(self):
        page = {"id": "vinted"}
        with patch.object(vinted_app, "_cdp_command", side_effect=[
            {"result": {"value": {"ok": True, "x": 100, "y": 50}}},
            {}, {},
            {"result": {"value": {"ok": True, "rows": [{"name": "forschur", "detail": "6 Jahre / 116", "x": 100, "y": 100, "source_url": "https://www.vinted.de/catalog?search_text=forschur&size_ids%5B%5D=625&search_id=2474429823&order=newest_first", "saved_marker": True, "bookmark_marker": True}]}}},
        ]) as cdp, patch.object(vinted_app.time, "sleep"):
            rows = vinted_app._open_saved_search_menu(page)
        self.assertEqual(rows[0]["name"], "forschur")
        self.assertEqual(cdp.call_args_list[1].args[1], "Input.dispatchMouseEvent")
        self.assertEqual(cdp.call_args_list[2].args[1], "Input.dispatchMouseEvent")


    def test_saved_search_menu_filters_catalog_button_and_product_rows(self):
        page = {"id": "vinted"}
        valid_one = "https://www.vinted.de/catalog?search_text=forschur&size_ids%5B%5D=625&search_id=2474429823&order=newest_first"
        valid_two = "https://www.vinted.de/catalog?search_text=wildling&search_id=2425022737&order=newest_first"
        rows = [
            {"name": "Katalog", "detail": "", "x": 185, "y": 26, "source_url": ""},
            {"name": "forschur", "detail": "6 Jahre / 116", "x": 185, "y": 90, "source_url": valid_one, "saved_marker": True, "bookmark_marker": True},
            {"name": "wildling", "detail": "Keine Filter", "x": 185, "y": 242, "source_url": valid_two, "saved_marker": False},
            {"name": "16,45 €", "detail": "inkl.", "x": 64, "y": 539, "source_url": ""},
        ]
        with patch.object(vinted_app, "_evaluate_search_runtime", side_effect=[
            (page, {"ok": True, "x": 100, "y": 50}),
            (page, {"ok": True, "rows": rows}),
        ]), patch.object(vinted_app, "_click_vinted_point"), patch.object(vinted_app.time, "sleep"):
            result = vinted_app._open_saved_search_menu(page)
        self.assertEqual([row["name"] for row in result], ["forschur"])
        self.assertEqual([row["source_url"] for row in result], [valid_one])

    def test_saved_search_menu_rejects_plus_counter_even_if_marker_is_misdetected(self):
        page = {"id": "vinted"}
        saved = "https://www.vinted.de/catalog?search_text=forschur&search_id=2474429823&order=newest_first"
        suggestion = "https://www.vinted.de/catalog?search_text=wildling&search_id=2425022737&order=newest_first"
        rows = [
            {"name": "forschur", "detail": "6 Jahre / 116", "x": 185, "y": 90, "source_url": saved, "saved_marker": True, "bookmark_marker": True, "suggestion_counter": False},
            {"name": "wildling", "detail": "Keine Filter", "x": 185, "y": 242, "source_url": suggestion, "saved_marker": True, "bookmark_marker": True, "suggestion_counter": True},
        ]
        with patch.object(vinted_app, "_evaluate_search_runtime", side_effect=[
            (page, {"ok": True, "x": 100, "y": 50}),
            (page, {"ok": True, "rows": rows}),
        ]), patch.object(vinted_app, "_click_vinted_point"), patch.object(vinted_app.time, "sleep"):
            result = vinted_app._open_saved_search_menu(page)
        self.assertEqual([row["name"] for row in result], ["forschur"])

    def test_saved_search_menu_rejects_catalog_suggestions_without_bookmark_marker(self):
        page = {"id": "vinted"}
        saved = "https://www.vinted.de/catalog?search_text=forschur&size_ids%5B%5D=625&search_id=2474429823&order=newest_first"
        suggestion = "https://www.vinted.de/catalog?search_text=wildling&search_id=2425022737&order=newest_first"
        rows = [
            {"name": "forschur", "detail": "6 Jahre / 116", "x": 185, "y": 90, "source_url": saved, "saved_marker": True, "bookmark_marker": True},
            {"name": "wildling", "detail": "Keine Filter", "x": 185, "y": 242, "source_url": suggestion, "saved_marker": False},
        ]
        with patch.object(vinted_app, "_evaluate_search_runtime", side_effect=[
            (page, {"ok": True, "x": 100, "y": 50}),
            (page, {"ok": True, "rows": rows}),
        ]), patch.object(vinted_app, "_click_vinted_point"), patch.object(vinted_app.time, "sleep"):
            result = vinted_app._open_saved_search_menu(page)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "forschur")
        self.assertEqual(result[0]["source_url"], saved)

    def test_saved_search_menu_rejects_catalog_link_without_bookmark_marker(self):
        page = {"id": "vinted"}
        saved = "https://www.vinted.de/catalog?search_text=forschur&search_id=2474429823&order=newest_first"
        rows = [{
            "name": "forschur", "detail": "Keine Filter", "x": 185, "y": 90,
            "source_url": saved, "saved_marker": True, "bookmark_marker": False,
            "fallback_catalog_link": True,
        }]
        with patch.object(vinted_app, "_evaluate_search_runtime", side_effect=[
            (page, {"ok": True, "x": 100, "y": 50}),
            (page, {"ok": True, "rows": rows}),
        ]), patch.object(vinted_app, "_click_vinted_point"), patch.object(vinted_app.time, "sleep"):
            result = vinted_app._open_saved_search_menu(page)
        self.assertEqual(result, [])

    def test_saved_search_menu_keeps_real_unfiltered_bookmark_and_ignores_plus_rows(self):
        page = {"id": "vinted"}
        rows = [
            {
                "name": "Wildling", "detail": "33", "x": 185, "y": 90,
                "source_url": "https://www.vinted.de/catalog?search_text=Wildling&size_ids%5B%5D=602&search_id=2515322783",
                "saved_marker": True, "bookmark_marker": True, "new_counter": "+1",
            },
            {
                "name": "forschur", "detail": "6 Jahre / 116", "x": 185, "y": 166,
                "source_url": "https://www.vinted.de/catalog?search_text=forschur&size_ids%5B%5D=625&search_id=2474429823",
                "saved_marker": True, "bookmark_marker": True,
            },
            {
                "name": "hessnatur damen", "detail": "Keine Filter", "x": 185, "y": 242,
                "source_url": "https://www.vinted.de/catalog?search_text=hessnatur%20damen&search_id=2504023454",
                "saved_marker": True, "bookmark_marker": True, "new_counter": "+31",
            },
            {
                "name": "DE", "detail": "Keine Filter", "x": 185, "y": 318,
                "source_url": "https://www.vinted.de/catalog?search_text=DE&search_id=2518339682",
                "saved_marker": False, "bookmark_marker": False, "new_counter": "+99",
            },
            {
                "name": "Artikel verkaufen", "detail": "Keine Filter", "x": 185, "y": 394,
                "source_url": "https://www.vinted.de/catalog?search_text=Artikel%20verkaufen&search_id=2518447627",
                "saved_marker": False, "bookmark_marker": False, "new_counter": "+99",
            },
        ]
        with patch.object(vinted_app, "_evaluate_search_runtime", side_effect=[
            (page, {"ok": True, "x": 100, "y": 50}),
            (page, {"ok": True, "rows": rows}),
        ]), patch.object(vinted_app, "_click_vinted_point"), patch.object(vinted_app.time, "sleep"):
            result = vinted_app._open_saved_search_menu(page)
        self.assertEqual([row["name"] for row in result], ["Wildling", "forschur", "hessnatur damen"])


    def test_saved_search_menu_rejects_search_box_pseudo_row_named_artikel(self):
        page = {"id": "vinted"}
        rows = [
            {
                "name": "Artikel", "detail": "", "x": 185, "y": 50,
                "source_url": "", "search_id": "",
                "saved_marker": True, "bookmark_marker": True,
                "explicit_bookmark_marker": False,
            },
            {
                "name": "Forschur", "detail": "ForSchur", "x": 185, "y": 120,
                "source_url": "https://www.vinted.de/catalog?search_text=Forschur&brand_ids%5B%5D=3369228&search_id=2560327461",
                "saved_marker": True, "bookmark_marker": True,
                "explicit_bookmark_marker": False,
            },
        ]
        with patch.object(vinted_app, "_evaluate_search_runtime", side_effect=[
            (page, {"ok": True, "x": 100, "y": 50}),
            (page, {"ok": True, "rows": rows}),
        ]), patch.object(vinted_app, "_click_vinted_point"), patch.object(vinted_app.time, "sleep"):
            result = vinted_app._open_saved_search_menu(page)
        self.assertEqual([row["name"] for row in result], ["Forschur"])

    def test_saved_search_menu_keeps_explicit_url_less_keyword_bookmark(self):
        page = {"id": "vinted"}
        rows = [{
            "name": "Hessnatur Damen", "detail": "", "x": 185, "y": 90,
            "source_url": "", "search_id": "",
            "saved_marker": True, "bookmark_marker": True,
            "explicit_bookmark_marker": True,
        }]
        with patch.object(vinted_app, "_evaluate_search_runtime", side_effect=[
            (page, {"ok": True, "x": 100, "y": 50}),
            (page, {"ok": True, "rows": rows}),
        ]), patch.object(vinted_app, "_click_vinted_point"), patch.object(vinted_app.time, "sleep"):
            result = vinted_app._open_saved_search_menu(page)
        self.assertEqual([row["name"] for row in result], ["Hessnatur Damen"])

    def test_saved_search_menu_requires_vinteds_bookmark_marker(self):
        source = inspect.getsource(vinted_app._open_saved_search_menu)
        self.assertIn('[data-testid="saved-search-bookmark"]', source)
        self.assertIn("bookmarkSelector", source)
        self.assertIn('raw_row.get("bookmark_marker") is not True', source)

    def test_mobile_navigation_keeps_five_bottom_items_and_moves_search_to_header(self):
        template = (Path(vinted_app.__file__).parent / "templates" / "base.html").read_text("utf-8")
        bottom = template.split('<nav class="vinted-mobile-bottom"', 1)[1]
        self.assertIn('class="mobile-search"', template)
        self.assertNotIn("<span>Suchen</span>", bottom)
        self.assertEqual(bottom.split("</nav>", 1)[0].count("href="), 5)

    def test_saved_search_probe_retries_expected_vinted_document_replacement(self):
        first = {"id": "first"}
        second = {"id": "second"}
        rows = [{"name": "forschur", "detail": "6 Jahre / 116", "x": 100, "y": 100}]
        with patch.object(vinted_app, "_open_vinted_background_target", side_effect=[first, second]), \
             patch.object(vinted_app, "_wait_for_stable_vinted_document", side_effect=lambda page, **kwargs: page), \
             patch.object(vinted_app, "_open_saved_search_menu", side_effect=[RuntimeError("Execution context was destroyed."), rows]), \
             patch.object(vinted_app, "_close_browser_target") as close, \
             patch.object(vinted_app.time, "sleep"):
            probe, result = vinted_app._open_saved_search_probe()
        self.assertEqual(probe, second)
        self.assertEqual(result, rows)
        close.assert_called_once_with(first)


    def test_isolated_probe_matches_same_filtered_bookmark_when_fresh_menu_omits_search_id(self):
        expected = {
            "name": "Forschur Kleid 98",
            "detail": "ForSchur, 18–24 Monate / 86, 24–36 Monate / 92, 4 Jahre / 104, 3 Jahre / 98",
            "source_url": "https://www.vinted.de/catalog?search_text=Forschur+Kleid+98&brand_ids%5B%5D=3369228&size_ids%5B%5D=619&size_ids%5B%5D=622&size_ids%5B%5D=623&size_ids%5B%5D=1567&search_id=2560327461&order=newest_first",
            "search_id": "2560327461",
        }
        candidate = {
            "name": "Forschur Kleid 98",
            "detail": expected["detail"],
            "source_url": "https://www.vinted.de/catalog?search_text=Forschur+Kleid+98&brand_ids%5B%5D=3369228&size_ids%5B%5D=619&size_ids%5B%5D=622&size_ids%5B%5D=623&size_ids%5B%5D=1567&order=newest_first",
            "x": 100, "y": 100,
        }
        matched, mode = vinted_app._match_saved_search_probe_row(expected, [candidate], 0)
        self.assertIs(matched, candidate)
        self.assertEqual(mode, "filter_signature")

    def test_isolated_probe_matches_unique_name_when_fresh_menu_strips_filter_href(self):
        expected = {
            "name": "Forschur", "detail": "ForSchur",
            "source_url": "https://www.vinted.de/catalog?search_text=Forschur&brand_ids%5B%5D=3369228&search_id=31101173889",
            "search_id": "31101173889",
        }
        candidate = {
            "name": "Forschur", "detail": "ForSchur",
            "source_url": "https://www.vinted.de/catalog?search_text=Forschur",
            "x": 100, "y": 100,
        }
        matched, mode = vinted_app._match_saved_search_probe_row(expected, [candidate], 0)
        self.assertIs(matched, candidate)
        self.assertEqual(mode, "name")

    def test_isolated_probe_never_uses_unrelated_row_only_because_index_matches(self):
        expected = {
            "name": "Forschur", "detail": "ForSchur",
            "source_url": "https://www.vinted.de/catalog?search_text=Forschur&brand_ids%5B%5D=3369228&search_id=31101173889",
            "search_id": "31101173889",
        }
        unrelated = {
            "name": "Werbung", "detail": "",
            "source_url": "https://www.vinted.de/catalog?search_text=Werbung",
            "x": 100, "y": 100,
        }
        matched, mode = vinted_app._match_saved_search_probe_row(expected, [unrelated], 0)
        self.assertIsNone(matched)
        self.assertEqual(mode, "not_found")

    def test_saved_search_direct_href_is_verified_when_row_has_filters(self):
        source_url = "https://www.vinted.de/catalog?search_text=forschur&search_id=2474429823"
        filtered_url = "https://www.vinted.de/catalog?search_text=forschur&size_ids%5B%5D=625&search_id=2474429823&order=newest_first"
        api_url = "https://www.vinted.de/api/v2/catalog/items?page=1&search_text=forschur&size_ids=625&search_id=2474429823&order=newest_first"
        row = {"name": "forschur", "detail": "6 Jahre / 116", "source_url": source_url, "x": 100, "y": 100}
        probe = {"id": "fresh"}
        with patch.object(vinted_app, "_open_saved_search_probe", return_value=(probe, [row])) as open_probe, \
             patch.object(vinted_app, "_saved_search_resolution_after_click", return_value={"source_url": filtered_url, "api_url": api_url}) as resolve, \
             patch.object(vinted_app, "_close_browser_target"):
            result = vinted_app._saved_search_resolution_from_fresh_probe(row, 0)
        self.assertEqual(result["source_url"], filtered_url)
        self.assertEqual(result["api_url"], api_url)
        open_probe.assert_called_once()
        resolve.assert_called_once_with(probe, row)

    def test_saved_search_discovery_uses_confirmed_bookmark_filters_without_click_capture(self):
        probe = {"id": "main", "_shared_primary": True}
        bookmark_url = (
            "https://www.vinted.de/catalog?search_text=forschur"
            "&brand_ids%5B%5D=3369228"
            "&size_ids%5B%5D=619&size_ids%5B%5D=622"
            "&search_id=2474429823&order=newest_first"
        )
        rows = [{
            "name": "forschur",
            "detail": "ForSchur, 86, 92",
            "source_url": bookmark_url,
            "search_id": "2474429823",
        }]
        with patch.object(vinted_app, "_refresh_background_vinted_session"), \
             patch.object(vinted_app, "_open_saved_search_probe", side_effect=[(probe, rows), (probe, rows)]), \
             patch.object(vinted_app, "_saved_search_resolution_from_primary_probe") as click_capture, \
             patch.object(vinted_app.time, "sleep"):
            result = vinted_app._discover_vinted_saved_searches()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source_url"], bookmark_url)
        self.assertIn("brand_ids%5B%5D=3369228", result[0]["api_url"])
        self.assertIn("size_ids%5B%5D=619", result[0]["api_url"])
        self.assertIn("size_ids%5B%5D=622", result[0]["api_url"])
        self.assertTrue(result[0]["api_verified_via_saved_search"])
        click_capture.assert_not_called()

    def test_saved_search_discovery_keeps_confirmed_filtered_bookmark_without_search_id(self):
        probe = {"id": "main", "_shared_primary": True}
        bookmark_url = (
            "https://www.vinted.de/catalog?search_text=merino"
            "&size_ids%5B%5D=619&size_ids%5B%5D=622&order=newest_first"
        )
        rows = [{
            "name": "Merino",
            "detail": "86, 92",
            "source_url": bookmark_url,
            "search_id": "",
        }]
        with patch.object(vinted_app, "_refresh_background_vinted_session"), \
             patch.object(vinted_app, "_open_saved_search_probe", side_effect=[(probe, rows), (probe, rows)]), \
             patch.object(vinted_app, "_saved_search_resolution_from_fresh_probe") as resolver, \
             patch.object(vinted_app.time, "sleep"):
            result = vinted_app._discover_vinted_saved_searches()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source_url"], bookmark_url)
        self.assertEqual(result[0]["search_id"], "")
        self.assertIn("size_ids%5B%5D=619", result[0]["api_url"])
        self.assertIn("size_ids%5B%5D=622", result[0]["api_url"])
        resolver.assert_not_called()

    def test_saved_search_discovery_builds_plain_url_for_url_less_keyword_bookmark(self):
        probe = {"id": "main", "_shared_primary": True}
        rows = [{"name": "Merino Cardigan", "detail": "Keine Filter", "source_url": "", "search_id": ""}]
        with patch.object(vinted_app, "_refresh_background_vinted_session"), \
             patch.object(vinted_app, "_open_saved_search_probe", side_effect=[(probe, rows), (probe, rows)]), \
             patch.object(vinted_app.time, "sleep"):
            result = vinted_app._discover_vinted_saved_searches()
        self.assertEqual(len(result), 1)
        self.assertIn("search_text=Merino+Cardigan", result[0]["source_url"])
        self.assertTrue(result[0]["api_url"])

    def test_auto_saved_search_sync_adds_new_search_silently_and_preserves_existing_baseline(self):
        old_url = "https://www.vinted.de/catalog?search_text=forschur&search_id=1"
        new_url = "https://www.vinted.de/catalog?search_text=wildling&search_id=2"
        old_id = vinted_app._search_alert_id(old_url)
        vinted_app._save_search_alert_state({
            "schema": 2,
            "searches": [{
                "id": old_id, "name": "forschur", "detail": "6 Jahre / 116",
                "source_url": old_url, "api_url": "", "recipient": "secondary",
                "active": True, "verified_saved_search": True,
                "verified_saved_search_generation": 3, "initialized": True,
                "seen_item_ids": ["100"], "matches": [{"id": "100"}],
            }],
        })
        added = vinted_app._auto_merge_new_saved_searches([
            {"id": old_id, "name": "forschur", "detail": "6 Jahre / 116", "source_url": old_url, "api_url": ""},
            {"id": vinted_app._search_alert_id(new_url), "name": "wildling", "detail": "Keine Filter", "source_url": new_url, "api_url": ""},
        ])
        self.assertEqual(added, 1)
        searches = vinted_app._load_search_alert_state()["searches"]
        old = next(row for row in searches if row["id"] == old_id)
        new = next(row for row in searches if row["id"] != old_id)
        self.assertTrue(old["initialized"])
        self.assertEqual(old["seen_item_ids"], ["100"] )
        self.assertEqual(old["recipient"], "secondary")
        self.assertEqual(old["verified_saved_search_generation"], vinted_app.SAVED_SEARCH_VERIFICATION_GENERATION)
        self.assertFalse(new["initialized"])
        self.assertEqual(new["seen_item_ids"], [])
        self.assertEqual(new["recipient"], "secondary")
        self.assertEqual(new["verified_saved_search_generation"], vinted_app.SAVED_SEARCH_VERIFICATION_GENERATION)

    def test_automatic_saved_search_sync_requires_three_confirmed_misses_before_removal(self):
        old_url = "https://www.vinted.de/catalog?search_text=old&search_id=old"
        keep_url = "https://www.vinted.de/catalog?search_text=keep&search_id=keep"
        old_id = vinted_app._search_alert_id(old_url)
        keep_id = vinted_app._search_alert_id(keep_url)
        vinted_app._save_search_alert_state({
            "schema": 3,
            "searches": [
                {"id": old_id, "name": "old", "source_url": old_url, "recipient": "primary", "active": True, "verified_saved_search": True, "verified_saved_search_generation": vinted_app.SAVED_SEARCH_VERIFICATION_GENERATION},
                {"id": keep_id, "name": "keep", "source_url": keep_url, "recipient": "primary", "active": True, "verified_saved_search": True, "verified_saved_search_generation": vinted_app.SAVED_SEARCH_VERIFICATION_GENERATION},
            ],
        })
        discovered = [{"id": keep_id, "name": "keep", "detail": "", "source_url": keep_url, "api_url": ""}]
        for expected_missing in (1, 2):
            vinted_app._auto_merge_new_saved_searches(discovered)
            state = vinted_app._load_search_alert_state()
            old = next(row for row in state["searches"] if row["id"] == old_id)
            self.assertEqual(old["sync_missing_count"], expected_missing)
        vinted_app._auto_merge_new_saved_searches(discovered)
        ids = [row["id"] for row in vinted_app._load_search_alert_state()["searches"]]
        self.assertNotIn(old_id, ids)
        self.assertIn(keep_id, ids)

    def test_automatic_saved_search_sync_mirrors_vinted_list_immediately(self):
        old_url = "https://www.vinted.de/catalog?search_text=old&search_id=old-immediate"
        keep_url = "https://www.vinted.de/catalog?search_text=keep&search_id=keep-immediate"
        old_id = vinted_app._search_alert_id(old_url)
        keep_id = vinted_app._search_alert_id(keep_url)
        vinted_app._save_search_alert_state({
            "schema": 3,
            "searches": [
                {"id": old_id, "name": "old", "source_url": old_url, "recipient": "primary", "active": True, "initialized": True},
                {"id": keep_id, "name": "keep", "source_url": keep_url, "recipient": "primary", "active": True, "initialized": True},
            ],
        })
        with patch.object(vinted_app, "_discover_vinted_saved_searches", return_value=[{
            "id": keep_id, "name": "keep", "detail": "", "source_url": keep_url, "api_url": "",
        }]), patch.object(vinted_app, "_check_search_alert"):
            vinted_app._saved_search_sync_worker(replace=True, source="automatic")
        ids = [row["id"] for row in vinted_app._load_search_alert_state()["searches"]]
        self.assertEqual(ids, [keep_id])

    def test_full_saved_search_sync_inherits_uniform_both_recipient_for_changed_ids(self):
        old_url = "https://www.vinted.de/catalog?search_text=forschur&search_id=old"
        new_url = "https://www.vinted.de/catalog?search_text=forschur&search_id=new"
        vinted_app._save_search_alert_state({
            "schema": 2,
            "searches": [{
                "id": vinted_app._search_alert_id(old_url), "name": "forschur",
                "source_url": old_url, "recipient": "both", "active": True,
            }],
        })
        searches = vinted_app._merge_discovered_searches([{
            "id": vinted_app._search_alert_id(new_url), "name": "forschur",
            "detail": "Keine Filter", "source_url": new_url, "api_url": "",
        }])
        self.assertEqual(searches[0]["recipient"], "both")
        self.assertFalse(searches[0]["initialized"])

    def test_legacy_saved_search_state_requires_full_replacement(self):
        current = {"searches": [{
            "verified_saved_search": True,
            "verified_saved_search_generation": vinted_app.SAVED_SEARCH_VERIFICATION_GENERATION,
        }]}
        legacy = {"searches": [
            {"name": "Artikel verkaufen", "verified_saved_search": True, "verified_saved_search_generation": 9},
            {"name": "forschur", "verified_saved_search": True, "verified_saved_search_generation": vinted_app.SAVED_SEARCH_VERIFICATION_GENERATION},
        ]}
        self.assertFalse(vinted_app._saved_search_needs_full_sync(current))
        self.assertTrue(vinted_app._saved_search_needs_full_sync(legacy))

    def test_full_saved_search_sync_removes_stale_rows_and_initializes_counts(self):
        discovered = [{
            "id": "new",
            "name": "forschur",
            "detail": "",
            "source_url": "https://www.vinted.de/catalog?search_text=forschur",
        }]
        with patch.object(vinted_app, "_discover_vinted_saved_searches", return_value=discovered), \
             patch.object(vinted_app, "_check_search_alert", return_value={"items": [{"id": "1"}]}) as check:
            vinted_app._saved_search_sync_worker(replace=True, source="automatic")
        state = vinted_app._load_search_alert_state()
        self.assertEqual([row["name"] for row in state["searches"]], ["forschur"])
        check.assert_called_once_with(state["searches"][0]["id"], notify=False, allow_visible_fallback=False)

    def test_partial_manual_saved_search_sync_never_removes_existing_watches(self):
        existing = [
            {"id": "one", "name": "eins", "source_url": "https://www.vinted.de/catalog?search_text=eins", "initialized": True, "active": True},
            {"id": "two", "name": "zwei", "source_url": "https://www.vinted.de/catalog?search_text=zwei", "initialized": True, "active": True},
        ]
        vinted_app._save_search_alert_state({"schema": 3, "searches": existing})
        discovered = [{"id": "one", "name": "eins", "source_url": "https://www.vinted.de/catalog?search_text=eins"}]
        with patch.object(vinted_app, "_discover_vinted_saved_searches", return_value=discovered), \
             patch.object(vinted_app, "_saved_search_discovery_snapshot", return_value={"consistent": False, "first_count": 1, "second_count": 2}), \
             patch.object(vinted_app, "_check_search_alert") as check:
            vinted_app._saved_search_sync_worker(replace=True, source="manual")
        state = vinted_app._load_search_alert_state()
        self.assertEqual({row["name"] for row in state["searches"]}, {"eins", "zwei"})
        self.assertIn("nicht identisch", vinted_app._saved_search_sync_snapshot()["last_warning"])
        check.assert_not_called()

    def test_consistent_manual_saved_search_sync_mirrors_vinted_exactly(self):
        existing = [
            {"id": "one", "name": "eins", "source_url": "https://www.vinted.de/catalog?search_text=eins", "initialized": True, "active": True},
            {"id": "two", "name": "zwei", "source_url": "https://www.vinted.de/catalog?search_text=zwei", "initialized": True, "active": True},
        ]
        vinted_app._save_search_alert_state({"schema": 3, "searches": existing})
        discovered = [{"id": "one", "name": "eins", "source_url": "https://www.vinted.de/catalog?search_text=eins"}]
        with patch.object(vinted_app, "_discover_vinted_saved_searches", return_value=discovered), \
             patch.object(vinted_app, "_saved_search_discovery_snapshot", return_value={"consistent": True, "first_count": 1, "second_count": 1}), \
             patch.object(vinted_app, "_check_search_alert"):
            vinted_app._saved_search_sync_worker(replace=True, source="manual")
        state = vinted_app._load_search_alert_state()
        self.assertEqual([row["name"] for row in state["searches"]], ["eins"])
        status = vinted_app._saved_search_sync_snapshot()
        self.assertEqual(status["remote_count"], 1)
        self.assertEqual(status["manager_count"], 1)

    def test_bookmark_detection_upgrade_keeps_unconfirmed_rows_but_never_reactivates_them(self):
        old_rows = [
            {
                "id": "suggestion", "name": "#wollbody",
                "source_url": "https://www.vinted.de/catalog?search_text=%23wollbody",
                "active": True, "initialized": True,
                "verified_saved_search": True,
                "verified_saved_search_generation": vinted_app.SAVED_SEARCH_VERIFICATION_GENERATION - 1,
            },
            {
                "id": "bookmark", "name": "Merino 100 cardigan",
                "source_url": "https://www.vinted.de/catalog?search_text=Merino+100+cardigan",
                "active": True, "initialized": True,
                "verified_saved_search": True,
                "verified_saved_search_generation": vinted_app.SAVED_SEARCH_VERIFICATION_GENERATION - 1,
            },
        ]
        discovered = [{
            "id": "bookmark", "name": "Merino 100 cardigan",
            "source_url": "https://www.vinted.de/catalog?search_text=Merino+100+cardigan",
        }]
        vinted_app._save_search_alert_state({"schema": 3, "searches": old_rows})
        with patch.object(vinted_app, "_discover_vinted_saved_searches", return_value=discovered), \
             patch.object(vinted_app, "_check_search_alert") as check:
            vinted_app._saved_search_sync_worker(replace=True, source="automatic")
        state = vinted_app._load_search_alert_state()
        rows_by_name = {row["name"]: row for row in state["searches"]}
        self.assertEqual(set(rows_by_name), {"#wollbody", "Merino 100 cardigan"})
        self.assertEqual(rows_by_name["Merino 100 cardigan"]["verified_saved_search_generation"], vinted_app.SAVED_SEARCH_VERIFICATION_GENERATION)
        self.assertLess(rows_by_name["#wollbody"]["verified_saved_search_generation"], vinted_app.SAVED_SEARCH_VERIFICATION_GENERATION)
        check.assert_not_called()

    def test_search_overview_hides_unconfirmed_suggestions_without_deleting_them(self):
        vinted_app._save_search_alert_state({"searches": [
            {
                "id": "suggestion", "name": "#wollbody", "active": True,
                "verified_saved_search": True,
                "verified_saved_search_generation": vinted_app.SAVED_SEARCH_VERIFICATION_GENERATION - 1,
            },
            {
                "id": "bookmark", "name": "Merino 100 cardigan", "active": True,
                "verified_saved_search": True,
                "verified_saved_search_generation": vinted_app.SAVED_SEARCH_VERIFICATION_GENERATION,
            },
        ]})
        response = self.client.get("/searches")
        self.assertIn(b"Merino 100 cardigan", response.data)
        self.assertNotIn(b"#wollbody", response.data)
        self.assertIn(b"ohne aktuell best\xc3\xa4tigtes Vinted-Lesezeichen", response.data)
        self.assertEqual(len(vinted_app._load_search_alert_state()["searches"]), 2)

    def test_search_runtime_retries_same_tab_after_execution_context_replacement(self):
        page = {"id": "main", "webSocketDebuggerUrl": "ws://first"}
        refreshed = {"id": "main", "webSocketDebuggerUrl": "ws://second"}
        success = {"result": {"value": {"ok": True}}}
        with patch.object(vinted_app, "_refresh_browser_target", side_effect=[None, refreshed, refreshed]), \
             patch.object(vinted_app, "_cdp_command", side_effect=[RuntimeError("Execution context was destroyed."), success]), \
             patch.object(vinted_app.time, "sleep"):
            current, value = vinted_app._evaluate_search_runtime(page, "({ok:true})", attempts=3)
        self.assertEqual(current, refreshed)
        self.assertEqual(value, {"ok": True})

    def test_saved_search_click_retries_the_whole_fresh_probe_after_document_replacement(self):
        first = {"id": "first"}
        second = {"id": "second"}
        rows = [{"name": "forschur", "detail": "6 Jahre / 116", "x": 100, "y": 100}]
        source_url = "https://www.vinted.de/catalog?search_text=forschur&search_id=2474429823"
        with patch.object(vinted_app, "_open_saved_search_probe", side_effect=[(first, rows), (second, rows)]), \
             patch.object(vinted_app, "_saved_search_resolution_after_click", side_effect=[RuntimeError("Execution context was destroyed."), {"source_url": source_url, "api_url": ""}]), \
             patch.object(vinted_app, "_close_browser_target") as close, \
             patch.object(vinted_app.time, "sleep"):
            result = vinted_app._saved_search_url_from_fresh_probe(rows[0], 0)
        self.assertEqual(result, source_url)
        self.assertEqual(close.call_args_list, [call(first), call(second)])

    def test_saved_search_menu_keeps_bookmarked_row_without_href(self):
        page = {"id": "main", "url": "https://www.vinted.de/", "webSocketDebuggerUrl": "ws://example"}
        value = {"ok": True, "rows": [{
            "name": "wildling", "detail": "", "x": 120, "y": 180,
            "source_url": "", "saved_marker": True, "bookmark_marker": True, "suggestion_counter": False,
        }]}
        with patch.object(vinted_app, "_evaluate_search_runtime", side_effect=[(page, {"ok": True, "x": 100, "y": 40}), (page, value)]), \
             patch.object(vinted_app, "_click_vinted_point"), \
             patch.object(vinted_app.time, "sleep"):
            rows = vinted_app._open_saved_search_menu(page)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "wildling")
        self.assertEqual(rows[0]["source_url"], "")

    def test_saved_search_catalog_request_prefers_filtered_request_after_broad_request(self):
        row = {
            "name": "forschur",
            "detail": "6 Jahre / 116",
            "source_url": "https://www.vinted.de/catalog?search_text=forschur&search_id=2474429823",
        }
        broad = "https://www.vinted.de/api/v2/catalog/items?page=1&search_text=forschur&search_id=2474429823&order=newest_first"
        filtered = "https://www.vinted.de/api/v2/catalog/items?page=1&search_text=forschur&size_ids=625&search_id=2474429823&order=newest_first"
        chosen = vinted_app._choose_saved_search_catalog_api([broad, filtered], row)
        self.assertIn("size_ids=625", chosen)

    def test_saved_search_catalog_url_keeps_current_vinted_filtered_url_when_available(self):
        api_url = "https://www.vinted.de/api/v2/catalog/items?page=1&search_text=forschur&size_ids=625&order=newest_first"
        generated = vinted_app._catalog_url_from_vinted_api_url(api_url)
        self.assertIn("size_ids%5B%5D=625", generated)
        self.assertIn("search_text=forschur", generated)

    def test_public_saved_search_translation_preserves_vinted_array_filter_semantics(self):
        public = (
            "https://www.vinted.de/catalog?search_text=Kapuzenjacke"
            "&size_ids%5B%5D=4&size_ids%5B%5D=5"
            "&material_ids%5B%5D=123&search_id=2551816920"
        )
        api_url = vinted_app._catalog_api_url_from_public_catalog(public)
        self.assertIn("size_ids%5B%5D=4", api_url)
        self.assertIn("size_ids%5B%5D=5", api_url)
        self.assertIn("material_ids%5B%5D=123", api_url)
        self.assertNotIn("&size_ids=4", api_url)
        self.assertNotIn("&size_ids=5", api_url)

    def test_saved_search_poll_drops_bookmark_search_id_but_keeps_real_filters(self):
        api_url = (
            "https://www.vinted.de/api/v2/catalog/items?page=3&search_text=forschur"
            "&size_ids%5B%5D=625&search_id=2474429823&order=relevance"
        )
        poll_url = vinted_app._catalog_api_poll_url(api_url)
        self.assertIn("search_text=forschur", poll_url)
        self.assertIn("size_ids%5B%5D=625", poll_url)
        self.assertNotIn("search_id=", poll_url)
        self.assertIn("page=1", poll_url)
        self.assertIn("order=newest_first", poll_url)

    def test_saved_search_check_falls_back_when_stored_api_returns_404(self):
        source_url = (
            "https://www.vinted.de/catalog?search_text=forschur"
            "&size_ids%5B%5D=625&search_id=2474429823"
        )
        stale_api = (
            "https://www.vinted.de/api/v2/catalog/items?page=1&per_page=96"
            "&search_text=forschur&size_ids%5B%5D=625&search_id=2474429823"
        )
        parsed = {"id": "987", "url": "https://www.vinted.de/items/987", "title": "Test"}
        with patch.object(vinted_app, "_catalog_search_items_from_api", side_effect=RuntimeError("HTTP 404")), \
             patch.object(vinted_app, "_background_fetch_json", return_value={"items": []}) as fetch, \
             patch.object(vinted_app, "_extract_catalog_item_payloads", return_value=[{"id": 987}]), \
             patch.object(vinted_app, "_catalog_item_from_api_payload", return_value=parsed):
            result = vinted_app._catalog_search_items(source_url, stale_api, allow_visible_fallback=False)
        self.assertEqual(result, [parsed])
        self.assertNotIn("search_id=", fetch.call_args.args[0])

    def test_saved_search_accepts_catalog_api_request_with_real_filters(self):
        api_url = "https://www.vinted.de/api/v2/catalog/items?page=1&per_page=96&search_text=forschur&catalog_ids=123&size_ids=625,626&order=newest_first"
        self.assertEqual(vinted_app._safe_vinted_catalog_api_url(api_url), api_url)
        source_url = vinted_app._catalog_url_from_vinted_api_url(api_url)
        self.assertIn("search_text=forschur", source_url)
        self.assertIn("catalog%5B%5D=123", source_url)
        self.assertIn("size_ids%5B%5D=625", source_url)

    def test_saved_search_canonical_api_drops_cachebuster_but_keeps_size_filter(self):
        api_url = "https://www.vinted.de/api/v2/catalog/items?page=1&per_page=96&search_text=forschur&size_ids=625,626&order=newest_first&time=999999&disable_search_saving=true"
        canonical = vinted_app._canonical_vinted_catalog_api_url(api_url)
        self.assertIn("size_ids=625%2C626", canonical)
        self.assertIn("search_text=forschur", canonical)
        self.assertNotIn("time=", canonical)
        self.assertNotIn("disable_search_saving", canonical)

    def test_text_only_catalog_href_is_not_treated_as_explicitly_filtered(self):
        self.assertFalse(vinted_app._catalog_url_has_explicit_filters("https://www.vinted.de/catalog?search_text=forschur&search_id=1&order=newest_first"))
        self.assertTrue(vinted_app._catalog_url_has_explicit_filters("https://www.vinted.de/catalog?search_text=forschur&size_ids%5B%5D=625&search_id=1"))

    def test_catalog_tracking_and_pagination_parameters_are_not_filters(self):
        broad = (
            "https://www.vinted.de/catalog?search_text=Kapuzenjacke&search_id=123"
            "&page=1&per_page=96&time=999&disable_search_saving=true&localize=false"
        )
        self.assertFalse(vinted_app._catalog_url_has_explicit_filters(broad))

    def test_catalog_material_and_size_are_real_filters(self):
        filtered = (
            "https://www.vinted.de/catalog?search_text=Kapuzenjacke"
            "&size_ids%5B%5D=42&material_ids%5B%5D=7"
        )
        self.assertTrue(vinted_app._catalog_url_has_explicit_filters(filtered))

    def test_saved_search_rejects_unfiltered_background_catalog_api_request(self):
        api_url = "https://www.vinted.de/api/v2/catalog/items?page=1&per_page=96&order=newest_first&time=123"
        self.assertFalse(vinted_app._safe_vinted_catalog_api_url(api_url))

    def test_saved_search_network_event_extracts_exact_catalog_request(self):
        api_url = "https://www.vinted.de/api/v2/catalog/items?page=1&search_text=forschur&size_ids=625"
        event = {"method": "Network.requestWillBeSent", "params": {"request": {"url": api_url}}}
        self.assertEqual(vinted_app._catalog_api_url_from_network_event(event), api_url)

    def test_search_debug_request_summary_keeps_vinted_filter_request_without_headers(self):
        event = {
            "method": "Network.requestWillBeSent",
            "params": {
                "type": "Fetch",
                "request": {
                    "method": "GET",
                    "url": "https://www.vinted.de/api/v2/catalog/items?page=1&search_text=jacke&token=secret",
                    "headers": {"Cookie": "should-not-appear"},
                },
            },
        }
        row = vinted_app._debug_request_summary(event)
        self.assertIsNotNone(row)
        self.assertIn("search_text=jacke", row["url"])
        self.assertIn("token=%3Credacted%3E", row["url"])
        self.assertNotIn("should-not-appear", json.dumps(row))

    def test_search_debug_report_roundtrip(self):
        payload = {"status": "ok", "steps": [{"name": "Browser", "status": "ok", "detail": "sichtbar"}]}
        vinted_app._save_search_debug_report(payload)
        self.assertEqual(vinted_app._load_search_debug_report(), payload)

    def test_saved_search_check_prefers_captured_api_url(self):
        source_url = "https://www.vinted.de/catalog?search_text=forschur"
        api_url = "https://www.vinted.de/api/v2/catalog/items?page=1&search_text=forschur"
        search = vinted_app._merge_discovered_searches([{
            "id": vinted_app._search_alert_id(source_url, api_url),
            "name": "forschur", "detail": "", "source_url": source_url, "api_url": api_url,
        }])[0]
        with patch.object(vinted_app, "_catalog_search_items", return_value=[]) as load_items:
            vinted_app._check_search_alert(search["id"], notify=False)
        load_items.assert_called_once_with(source_url, api_url, allow_visible_fallback=True)

    def test_catalog_payload_reader_accepts_nested_vinted_result_envelopes(self):
        payload = {
            "pagination": {"total_entries": 1},
            "data": {"results": [{
                "id": 987654321,
                "title": "Gefilterte Forschur-Anzeige",
                "brand_title": "Forschur",
                "size_title": "116",
                "price": {"amount": "12.50", "currency_code": "EUR"},
                "url": "https://www.vinted.de/items/987654321",
            }]},
        }
        raw_items = vinted_app._extract_catalog_item_payloads(payload)
        self.assertEqual([item["id"] for item in raw_items], [987654321])
        result = vinted_app._catalog_item_from_api_payload(raw_items[0])
        self.assertEqual(result["id"], "987654321")
        self.assertIn("12,50 EUR", result["detail"])

    def test_catalog_payload_reader_accepts_direct_item_list(self):
        payload = [{"id": 42, "title": "Direkter Treffer", "price": "8.00"}]
        self.assertEqual(
            vinted_app._catalog_item_from_api_payload(vinted_app._extract_catalog_item_payloads(payload)[0])["title"],
            "Direkter Treffer",
        )

    def test_catalog_api_reader_returns_matches_from_nested_payload(self):
        api_url = "https://www.vinted.de/api/v2/catalog/items?page=1&search_text=forschur&size_ids=625"
        page = {"id": "catalog"}
        response = {"ok": True, "status": 200, "payload": {"data": {"items": [{
            "id": 77, "title": "API-Treffer", "size_title": "116",
        }]}}}
        with patch.object(vinted_app, "_wait_for_vinted_page", return_value=page), \
             patch.object(vinted_app, "_wait_for_stable_vinted_document", return_value=page), \
             patch.object(vinted_app, "_evaluate_search_runtime", return_value=(page, response)):
            result = vinted_app._catalog_search_items_from_api(api_url)
        self.assertEqual([item["id"] for item in result], ["77"])
        self.assertEqual(result[0]["detail"], "116")

    def test_catalog_search_falls_back_to_visible_catalog_when_captured_api_is_empty(self):
        source_url = "https://www.vinted.de/catalog?search_text=forschur&size_ids%5B%5D=625"
        api_url = "https://www.vinted.de/api/v2/catalog/items?page=1&search_text=forschur&size_ids=625"
        page = {"id": "catalog"}
        payload = {"data": {"items": [{"id": 55, "title": "Fallback-Treffer", "size_title": "116"}]}}
        with patch.object(vinted_app, "_catalog_search_items_from_api", return_value=[]), \
             patch.object(vinted_app, "_open_vinted_target", return_value=page), \
             patch.object(vinted_app, "_wait_for_stable_vinted_document", return_value=page), \
             patch.object(vinted_app, "_evaluate_search_runtime", return_value=(page, {"cards": [], "payloads": [payload]})), \
             patch.object(vinted_app, "_close_browser_target"):
            result = vinted_app._catalog_search_items(source_url, api_url)
        self.assertEqual([item["id"] for item in result], ["55"])
        self.assertEqual(result[0]["detail"], "116")

    def test_saved_search_filter_count_accepts_bracket_array_keys(self):
        api_url = "https://www.vinted.de/api/v2/catalog/items?page=1&search_text=forschur&size_ids%5B%5D=625&order=newest_first"
        self.assertEqual(vinted_app._catalog_api_filter_count(api_url), 1)

    def test_saved_search_catalog_url_normalizes_bracket_api_keys(self):
        api_url = "https://www.vinted.de/api/v2/catalog/items?page=1&search_text=forschur&size_ids%5B%5D=625&size_ids%5B%5D=626&order=newest_first"
        source_url = vinted_app._catalog_url_from_vinted_api_url(api_url)
        self.assertIn("size_ids%5B%5D=625", source_url)
        self.assertIn("size_ids%5B%5D=626", source_url)
        self.assertNotIn("size_ids%5B%5D%5B%5D", source_url)

    def test_saved_search_open_url_uses_verified_api_filters_not_broad_bookmark_href(self):
        source_url = (
            "https://www.vinted.de/catalog?search_text=Forschur+Kleid+98"
            "&brand_ids%5B%5D=3369228&search_id=2560327461"
        )
        search = {
            "bookmark_source_url": source_url,
            "source_url": source_url,
            "api_url": (
                "https://www.vinted.de/api/v2/catalog/items?page=1&per_page=96"
                "&search_text=Forschur+Kleid+98&brand_ids%5B%5D=3369228"
                "&size_ids%5B%5D=619&size_ids%5B%5D=622&size_ids%5B%5D=623"
                "&size_ids%5B%5D=1567&search_id=2560327461&order=newest_first"
            ),
        }
        target = vinted_app._saved_search_public_url(search)
        pairs = parse_qsl(urlparse(target).query, keep_blank_values=False)
        self.assertIn(("search_text", "Forschur Kleid 98"), pairs)
        self.assertIn(("brand_ids[]", "3369228"), pairs)
        self.assertEqual(
            [value for key, value in pairs if key == "size_ids[]"],
            ["619", "622", "623", "1567"],
        )
        self.assertEqual(
            [value for key, value in pairs if key == "size_id[]"],
            [],
        )
        self.assertEqual(urlparse(target).netloc, "www.vinted.de")
        self.assertIn(("search_id", "2560327461"), pairs)
        self.assertIn("search_id=2560327461", target)
        self.assertIn("Forschur%20Kleid%2098", target)

    def test_saved_search_forward_link_does_not_change_monitor_url(self):
        api_url = (
            "https://www.vinted.de/api/v2/catalog/items?page=1&search_text=Kapuzenjacke"
            "&size_ids%5B%5D=4&size_ids%5B%5D=5&material_ids%5B%5D=123"
            "&search_id=2551816920&order=newest_first"
        )
        search = {"api_url": api_url}
        target = vinted_app._saved_search_public_url(search)
        self.assertEqual(search["api_url"], api_url)
        self.assertIn("size_ids%5B%5D=4", target)
        self.assertIn("size_ids%5B%5D=5", target)
        self.assertIn("material_ids%5B%5D=123", target)

    def test_saved_search_template_opens_through_exact_search_route(self):
        template = (Path(vinted_app.__file__).parent / "templates" / "searches.html").read_text("utf-8")
        self.assertIn("open_saved_search", template)
        self.assertNotIn('href="{{ search.source_url }}"', template)

    def test_saved_search_sync_button_is_not_disabled_by_background_sync(self):
        template = (Path(vinted_app.__file__).parent / "templates" / "searches.html").read_text("utf-8")
        self.assertNotIn("'disabled' if sync_status.running", template)
        self.assertIn("manual_pending", template)

    def test_saved_search_open_route_uses_server_side_http_302_with_exact_web_url(self):
        source_url = (
            "https://www.vinted.de/catalog?search_text=Forschur+Kleid+98"
            "&brand_ids%5B%5D=3369228&size_ids%5B%5D=619&search_id=2560327461"
        )
        search = {
            "id": "abc123", "name": "Forschur Kleid 98", "source_url": source_url,
            "api_url": (
                "https://www.vinted.de/api/v2/catalog/items?page=1&per_page=96"
                "&search_text=Forschur+Kleid+98&brand_ids%5B%5D=3369228"
                "&size_ids%5B%5D=619&size_ids%5B%5D=622&size_ids%5B%5D=623"
                "&size_ids%5B%5D=1567&search_id=2560327461&order=newest_first"
            ),
        }
        with patch.object(vinted_app, "_repair_saved_search_state", return_value={"searches": [search]}):
            with vinted_app.app.test_request_context("/searches/abc123/open"):
                response = vinted_app.open_saved_search("abc123")
        self.assertEqual(response.status_code, 302)
        target = response.headers["Location"]
        self.assertIn("Forschur%20Kleid%2098", target)
        self.assertIn("size_ids%5B%5D=619", target)
        self.assertIn("size_ids%5B%5D=1567", target)
        self.assertIn("search_id=2560327461", target)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store, max-age=0")
        self.assertEqual(response.headers.get("Pragma"), "no-cache")


    def test_backup_includes_saved_search_state_and_manager_settings(self):
        vinted_app.SEARCH_ALERTS_FILE.write_text(json.dumps({"searches": [{"id": "s1", "seen_item_ids": ["1"]}]}), "utf-8")
        vinted_app.SEARCH_MONITOR_FILE.write_text(json.dumps({"search_alerts_checked_at": 123}), "utf-8")
        vinted_app.APP_SETTINGS_FILE.write_text(json.dumps({"push_targets": {"primary": "notify.mobile_app_test"}}), "utf-8")
        vinted_app.PUSH_DEVICES_FILE.write_text(json.dumps({"devices": [{"id": "p1", "person": "primary"}]}), "utf-8")
        vinted_app.PUSH_VAPID_PRIVATE_KEY_FILE.write_text("test-private-key", "utf-8")
        backup = vinted_app._create_backup("test")
        import zipfile
        with zipfile.ZipFile(backup, "r") as archive:
            names = set(archive.namelist())
        self.assertIn("vinted-search-alerts.json", names)
        self.assertIn("vinted-search-monitor.json", names)
        self.assertIn("vinted-manager-settings.json", names)
        self.assertIn("vinted-push-devices.json", names)
        self.assertIn("vinted-push-vapid-private.pem", names)

    def test_search_recipient_ignores_legacy_home_assistant_push_targets(self):
        vinted_app._save_app_settings({
            "schema": 1,
            "push_targets": {
                "primary": "notify.mobile_app_primary_neu",
                "secondary": "notify.mobile_app_secondary_neu",
            },
            "migrations": {},
        })
        with patch.object(vinted_app, "_send_webpush_to_person", return_value=True) as notify:
            self.assertTrue(vinted_app._notify_search_recipient("both", "Titel", "Text", "/searches"))
        self.assertEqual([current.args[0] for current in notify.call_args_list], ["primary", "secondary"])

    def test_legacy_price_anchor_migration_uses_first_publication(self):
        draft = {
            "id": "price-1", "title": "Pullover", "price": "60",
            "published_item_id": "123", "automation_active": True,
            "renew_interval_days": 7,
            "republish_price_reduction_enabled": True,
            "republish_price_reduction_days": 14,
            "republish_price_drop": 1,
            "republish_min_price": 55,
            "first_published_at": "2026-09-01T08:00:00+00:00",
            "last_renewed_at": "2026-09-08T08:00:00+00:00",
            "published_at": "2026-09-08T08:00:00+00:00",
            "price_reduction_anchor_at": "2026-09-08T08:00:00+00:00",
        }
        vinted_app._save_drafts([draft])
        count = vinted_app._migrate_legacy_price_reduction_anchors()
        saved = vinted_app._load_drafts()[0]
        self.assertEqual(count, 1)
        self.assertTrue(saved["price_reduction_anchor_at"].startswith("2026-09-01T08:00:00"))
        self.assertEqual(saved["automation_history"][-1]["event"], "price_anchor_migrated")

    def test_bulk_automation_updates_only_selected_fields(self):
        drafts = [
            {
                "id": "a", "title": "A", "automation_active": True,
                "renew_interval_days": 7, "republish_price_reduction_enabled": False,
                "republish_price_reduction_days": 14, "republish_price_drop": 0,
                "republish_min_price": 0,
            },
            {
                "id": "b", "title": "B", "automation_active": True,
                "renew_interval_days": 10, "republish_price_reduction_enabled": False,
                "republish_price_reduction_days": 21, "republish_price_drop": 0,
                "republish_min_price": 0,
            },
        ]
        vinted_app._save_drafts(drafts)
        response = self.client.post("/drafts/bulk", data={
            "draft_ids": ["a"], "bulk_action": "automation",
            "bulk_renew_interval_days": "9",
            "bulk_price_mode": "on",
            "bulk_price_reduction_days": "14",
            "bulk_price_drop": "1",
            "bulk_min_price": "5",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        saved = {row["id"]: row for row in vinted_app._load_drafts()}
        self.assertEqual(saved["a"]["renew_interval_days"], 9)
        self.assertTrue(saved["a"]["republish_price_reduction_enabled"])
        self.assertEqual(saved["a"]["republish_price_drop"], 1.0)
        self.assertEqual(saved["b"]["renew_interval_days"], 10)
        self.assertFalse(saved["b"]["republish_price_reduction_enabled"])
        self.assertEqual(saved["a"]["automation_history"][-1]["event"], "automation_settings")

    def test_search_template_exposes_test_push_action(self):
        template = (Path(vinted_app.__file__).parent / "templates" / "searches.html").read_text("utf-8")
        self.assertIn("test_search_alert_notification", template)
        self.assertIn("Test-Push", template)

    def test_settings_template_exposes_diagnostics_and_webpush_devices(self):
        template = (Path(vinted_app.__file__).parent / "templates" / "settings.html").read_text("utf-8")
        self.assertIn("SYSTEMSTATUS", template)
        self.assertIn("VINTED WEB-PUSH", template)
        self.assertIn("settings_webpush_invite", template)
        self.assertIn("settings_webpush_test", template)

    def test_public_push_host_does_not_expose_manager_routes(self):
        public = f"https://{vinted_app.PUSH_PUBLIC_HOST}"
        root = self.client.get("/", base_url=public)
        self.assertEqual(root.status_code, 200)
        self.assertIn(b"Vinted Push", root.data)
        self.assertEqual(self.client.get("/settings", base_url=public).status_code, 404)
        self.assertEqual(self.client.get("/searches", base_url=public).status_code, 404)
        self.assertEqual(self.client.get("/messages", base_url=public).status_code, 404)

    def test_webpush_click_uses_signed_public_hop_to_internal_manager(self):
        target = vinted_app._webpush_click_target("/searches/abc123/matches/987")
        parsed = urlparse(target)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, vinted_app.PUSH_PUBLIC_HOST)
        self.assertEqual(parsed.path, "/push/manager-open")
        query = dict(parse_qsl(parsed.query))
        self.assertEqual(query.get("path"), "/searches/abc123/matches/987")
        self.assertEqual(query.get("sig"), vinted_app._push_redirect_signature(query["path"]))
        self.assertNotIn("192.168.10.199", target)

    def test_public_push_manager_hop_redirects_to_lan_vpn_url(self):
        path = "/searches/abc123/matches/987"
        signature = vinted_app._push_redirect_signature(path)
        public = f"https://{vinted_app.PUSH_PUBLIC_HOST}"
        response = self.client.get(
            "/push/manager-open",
            base_url=public,
            query_string={"path": path, "sig": signature},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], f"{vinted_app.DIRECT_PUSH_BASE_URL}{path}")
        self.assertEqual(response.headers.get("Cache-Control"), "no-store, max-age=0")

    def test_public_push_manager_hop_rejects_unsigned_and_external_targets(self):
        public = f"https://{vinted_app.PUSH_PUBLIC_HOST}"
        unsigned = self.client.get(
            "/push/manager-open",
            base_url=public,
            query_string={"path": "/settings"},
        )
        self.assertEqual(unsigned.status_code, 404)
        self.assertEqual(vinted_app._safe_internal_push_path("https://evil.example/path"), "/")
        self.assertEqual(vinted_app._safe_internal_push_path("//evil.example/path"), "/")

    def test_public_push_registration_consumes_one_time_invite(self):
        public = f"https://{vinted_app.PUSH_PUBLIC_HOST}"
        token, _invite = vinted_app._create_push_invite("primary")
        subscription = {
            "endpoint": "https://web.push.apple.com/QM-test-endpoint",
            "keys": {
                "p256dh": "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
                "auth": "BTBZMqHH6r4Tts7J_aSIgg",
            },
        }
        payload = {"invite": token, "subscription": subscription, "installation_id": "iphone-test", "device_name": "iPhone"}
        first = self.client.post("/api/push/subscribe", base_url=public, json=payload)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json()["person"], "primary")
        state = vinted_app._load_webpush_devices_unlocked()
        self.assertEqual(len(state["devices"]), 1)
        self.assertEqual(state["devices"][0]["person"], "primary")
        second = self.client.post("/api/push/subscribe", base_url=public, json=payload)
        self.assertEqual(second.status_code, 400)

    def test_display_names_prefer_local_home_assistant_people_over_generic_notify_slugs(self):
        vinted_app._save_app_settings({
            "schema": 1,
            "push_targets": {
                "primary": "notify.mobile_app_iphone_a",
                "secondary": "notify.mobile_app_secondary_iphone",
            },
            "migrations": {},
        })
        with patch.object(vinted_app, "_home_assistant_person_display_names", return_value={"primary": "Paula", "secondary": "Klara"}):
            self.assertEqual(vinted_app._push_person_display_name("primary"), "Paula")
            self.assertEqual(vinted_app._push_person_display_name("secondary"), "Klara")

    def test_explicit_local_push_person_labels_override_discovery(self):
        vinted_app._save_app_settings({
            "schema": 1,
            "push_targets": {
                "primary": "notify.mobile_app_iphone_a",
                "secondary": "notify.mobile_app_secondary_iphone",
            },
            "push_person_labels": {"primary": "Alpha", "secondary": "Beta"},
            "migrations": {},
        })
        with patch.object(vinted_app, "_home_assistant_person_display_names", return_value={"primary": "Paula", "secondary": "Klara"}):
            self.assertEqual(vinted_app._push_person_display_name("primary"), "Alpha")
            self.assertEqual(vinted_app._push_person_display_name("secondary"), "Beta")

    def test_push_person_label_route_saves_only_local_app_settings(self):
        response = self.client.post(
            "/settings/push-person-labels",
            data={"primary_label": "Alpha", "secondary_label": "Beta"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        settings = vinted_app._load_app_settings()
        self.assertEqual(settings["push_person_labels"], {"primary": "Alpha", "secondary": "Beta"})

    def test_home_assistant_person_discovery_matches_neutral_profile_initials(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps([
                    {"entity_id": "person.paula_koenig", "attributes": {"friendly_name": "Paula König"}},
                    {"entity_id": "person.kira_klein", "attributes": {"friendly_name": "Kira Klein"}},
                    {"entity_id": "person.emil", "attributes": {"friendly_name": "Emil"}},
                ]).encode("utf-8")

        vinted_app._push_person_discovery_cache["expires_at"] = 0.0
        vinted_app._push_person_discovery_cache["labels"] = {}
        with patch.dict(os.environ, {"SUPERVISOR_TOKEN": "local-test-token", "SUPERVISOR_URL": "http://supervisor"}, clear=False), \
             patch.object(vinted_app, "urlopen", return_value=FakeResponse()):
            labels = vinted_app._home_assistant_person_display_names()
        self.assertEqual(labels, {"primary": "Paula", "secondary": "Kira"})

    def test_display_names_are_derived_from_local_notify_targets_without_source_personal_data(self):
        vinted_app._save_app_settings({
            "schema": 1,
            "push_targets": {
                "primary": "notify.mobile_app_iphone_alex",
                "secondary": "notify.mobile_app_samiras_iphone",
            },
            "migrations": {},
        })
        self.assertEqual(vinted_app._push_person_display_name("primary"), "Alex")
        self.assertEqual(vinted_app._push_person_display_name("secondary"), "Samira")
        self.assertEqual(vinted_app._app_users_for_display()[0]["name"], "Alex")
        self.assertEqual(vinted_app._app_users_for_display()[1]["name"], "Samira")
        options = vinted_app._search_recipient_options_for_display()
        self.assertEqual(options["primary"]["name"], "Alex")
        self.assertEqual(options["secondary"]["name"], "Samira")

    def test_history_view_is_linked_from_listing_more_menu(self):
        template = (Path(vinted_app.__file__).parent / "templates" / "index.html").read_text("utf-8")
        self.assertIn("draft_history", template)
        self.assertIn("Anzeigen- &amp; Preisverlauf", template)

    def test_manual_price_change_is_logged_without_resetting_price_automation(self):
        before = {
            "price": "179",
            "price_reduction_anchor_at": "2026-09-01T12:00:00+00:00",
            "last_price_reduction_at": "2026-08-20T12:00:00+00:00",
            "price_reduction_count": 2,
            "automation_history": [],
        }
        after = dict(before)
        after["price"] = "170"
        changed = vinted_app._record_manual_price_change(before, after)
        self.assertTrue(changed)
        self.assertEqual(after["price_reduction_anchor_at"], before["price_reduction_anchor_at"])
        self.assertEqual(after["last_price_reduction_at"], before["last_price_reduction_at"])
        self.assertEqual(after["price_reduction_count"], 2)
        event = after["automation_history"][-1]
        self.assertEqual(event["event"], "price_changed")
        self.assertEqual(event["old_price"], "179")
        self.assertEqual(event["new_price"], "170")
        self.assertEqual(event["source"], "manual")

    def test_price_history_summary_uses_earliest_recorded_old_price(self):
        draft = {"price": "160"}
        history = [
            {"event": "price_changed", "old_price": "179", "new_price": "170"},
            {"event": "price_reduced", "old_price": "170", "new_price": "160"},
        ]
        summary = vinted_app._price_history_summary(draft, history)
        self.assertEqual(summary["first_known"], "179")
        self.assertEqual(summary["current"], "160")
        self.assertEqual(summary["delta"], "19")
        self.assertEqual(summary["direction"], "down")
        self.assertEqual(summary["event_count"], 2)

    def test_search_actions_use_clean_two_by_two_mobile_grid(self):
        base = Path(vinted_app.__file__).parent
        template = (base / "templates" / "searches.html").read_text("utf-8")
        css = (base / "static" / "style.css").read_text("utf-8")
        self.assertIn('class="search-card-action-grid"', template)
        self.assertIn('form="search-settings-{{ search.id }}"', template)
        self.assertIn("grid-template-columns:repeat(2,minmax(0,1fr))", css)

    def test_listing_overview_uses_full_width_status_rows(self):
        base = Path(vinted_app.__file__).parent
        template = (base / "templates" / "index.html").read_text("utf-8")
        css = (base / "static" / "style.css").read_text("utf-8")
        self.assertIn('class="draft-status-lines"', template)
        self.assertIn("renewal_interval_detail_label", template)
        self.assertIn("renewal_due_detail_label", template)
        self.assertIn("price_automation_detail_label", template)
        self.assertIn(".draft-status-line.status-price", css)

    def test_remote_vinted_sale_removes_only_linked_draft_and_queues_ka_cleanup(self):
        draft = {
            "id": "vinted-1", "title": "Fahrrad", "published_item_id": "item-1",
            "source_platform": "kleinanzeigen", "source_slug": "bike",
            "source_id": "kleinanzeigen:bike", "photos": [],
        }
        vinted_app._save_drafts([draft])

        vinted_app._reconcile_sold_vinted_drafts(
            [{"published_item_id": "item-1", "live_state": "sold"}], [draft]
        )

        self.assertIsNone(vinted_app._find_draft("vinted-1"))
        actions = list(vinted_app.KA_CROSS_ACTION_INBOX_DIR.glob("*.json"))
        self.assertEqual(len(actions), 1)
        payload = json.loads(actions[0].read_text("utf-8"))
        self.assertEqual(payload["action"], "vinted_sold_cleanup")
        self.assertEqual(payload["source_slug"], "bike")
        self.assertEqual(payload["vinted_draft_id"], "vinted-1")
        self.assertEqual(payload["title"], "Fahrrad")

    def test_bulk_renew_stops_remaining_jobs_after_first_real_failure(self):
        drafts = [
            {"id": "a", "title": "Erste", "published_item_id": "", "renewal_upload_pending": True,
             "status": "Fehlgeschlagen – erneut versuchen", "last_error": "Upload fehlgeschlagen", "photos": []},
            {"id": "b", "title": "Zweite", "published_item_id": "222", "status": "Veröffentlicht", "photos": []},
        ]
        vinted_app._save_drafts(drafts)
        vinted_app._save_bulk_publish_state({
            "queue": [
                {"draft_id": "a", "action": "renew"},
                {"draft_id": "b", "action": "renew"},
            ],
            "current": {},
        })
        with patch.object(vinted_app, "_renew_vinted_draft", side_effect=RuntimeError("Upload fehlgeschlagen")) as renew, \
             patch.object(vinted_app.time, "sleep"):
            vinted_app._bulk_publish_worker()
        state = vinted_app._load_bulk_publish_state()
        self.assertEqual(renew.call_count, 1)
        self.assertEqual(state["queue"], [])
        self.assertTrue(state["last_finished"]["batch_stopped"])
        self.assertEqual(state["last_finished"]["remaining_not_started"], 1)
        self.assertIn("Upload fehlgeschlagen", state["last_finished"]["error"])

    def test_publish_state_does_not_show_stale_failure_while_retry_is_running(self):
        draft = {
            "id": "a", "title": "Schlafsack", "published_item_id": "",
            "renewal_upload_pending": True, "status": "Fehlgeschlagen – erneut versuchen",
            "last_error": "alter Fehler", "photos": [],
        }
        vinted_app._save_drafts([draft])
        vinted_app._save_bulk_publish_state({
            "queue": [{"draft_id": "a", "action": "renew"}],
            "current": {"draft_id": "a", "action": "renew"},
        })
        state = vinted_app._publish_state_view()
        self.assertTrue(state["running"])
        self.assertEqual(state["title"], "Schlafsack")
        self.assertEqual(state["status"], "wird verarbeitet")

    def test_vinted_sale_cancels_any_queued_renewal_before_it_can_republish(self):
        draft = {
            "id": "vinted-1", "title": "Fahrrad", "published_item_id": "item-1",
            "source_platform": "kleinanzeigen", "source_slug": "bike",
            "source_id": "kleinanzeigen:bike", "photos": [],
        }
        vinted_app._save_drafts([draft])
        vinted_app._save_bulk_publish_state({"queue": [{"draft_id": "vinted-1", "action": "renew"}], "current": {}})

        vinted_app._reconcile_sold_vinted_drafts(
            [{"published_item_id": "item-1", "live_state": "sold"}], [draft]
        )

        self.assertTrue(vinted_app._draft_is_terminal("vinted-1"))
        self.assertEqual(vinted_app._load_bulk_publish_state()["queue"], [])
        self.assertFalse(vinted_app._enqueue_vinted_job("vinted-1", "renew"))
        with vinted_app._terminal_draft_lock:
            vinted_app._terminal_draft_ids.clear()
        self.assertTrue(vinted_app._draft_is_terminal("vinted-1"))

    def test_cross_platform_delete_push_is_critical_and_silent_for_primary(self):
        (vinted_app.DATA_DIR / "options.json").write_text(
            json.dumps({"notify_service": "notify.mobile_app_primary_private"}), "utf-8"
        )
        with patch.object(vinted_app, "_notify_service", return_value=True) as notify:
            self.assertTrue(vinted_app._notify_primary_critical("Titel", "Text", "/live"))
        notify.assert_called_once_with(
            "notify.mobile_app_primary_private", "Titel", "Text", "/live",
            extra_data={"push": {"sound": {"name": "default", "critical": 1, "volume": 0.0}}},
        )

    def test_ka_delete_action_only_removes_exact_transferred_vinted_draft(self):
        draft = {
            "id": "vinted-1", "title": "Fahrrad", "published_item_id": "",
            "source_platform": "kleinanzeigen", "source_slug": "bike",
            "source_id": "kleinanzeigen:bike", "photos": [],
        }
        unrelated = {"id": "vinted-2", "title": "Fahrrad", "photos": []}
        vinted_app._save_drafts([draft, unrelated])
        path = vinted_app.KA_DELETE_ACTION_INBOX_DIR / "delete.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "action": "kleinanzeigen_delete_cleanup", "source_platform": "kleinanzeigen",
            "source_slug": "bike", "source_id": "kleinanzeigen:bike", "vinted_draft_id": "vinted-1",
        }), "utf-8")

        vinted_app._process_kleinanzeigen_delete_action(path)

        self.assertIsNone(vinted_app._find_draft("vinted-1"))
        self.assertIsNotNone(vinted_app._find_draft("vinted-2"))
        self.assertFalse(path.exists())

    def test_ka_both_delete_removes_live_vinted_item_then_the_exact_template(self):
        draft = {
            "id": "vinted-1", "title": "Fahrrad", "published_item_id": "item-1",
            "source_platform": "kleinanzeigen", "source_slug": "bike",
            "source_id": "kleinanzeigen:bike", "photos": [],
        }
        vinted_app._save_drafts([draft])
        path = vinted_app.KA_DELETE_ACTION_INBOX_DIR / "delete.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "action": "kleinanzeigen_delete_cleanup", "source_platform": "kleinanzeigen",
            "source_slug": "bike", "source_id": "kleinanzeigen:bike", "vinted_draft_id": "vinted-1",
        }), "utf-8")

        with patch.object(vinted_app, "_load_live_vinted_items", return_value=[{"published_item_id": "item-1"}]), \
             patch.object(vinted_app, "_run_vinted_listing_action") as delete_remote, \
             patch.object(vinted_app, "_wait_for_live_action") as verify, \
             patch.object(vinted_app, "_notify_primary_critical") as notify:
            vinted_app._process_kleinanzeigen_delete_action(path)

        delete_remote.assert_called_once_with({"published_item_id": "item-1"}, "delete")
        verify.assert_called_once_with("item-1", "delete", timeout=10)
        self.assertIsNone(vinted_app._find_draft("vinted-1"))
        self.assertFalse(path.exists())
        notify.assert_called_once()

    def test_uncertain_ka_both_delete_never_repeats_remote_vinted_delete(self):
        draft = {
            "id": "vinted-1", "title": "Fahrrad", "published_item_id": "item-1",
            "source_platform": "kleinanzeigen", "source_slug": "bike",
            "source_id": "kleinanzeigen:bike", "photos": [],
        }
        vinted_app._save_drafts([draft])
        path = vinted_app.KA_DELETE_ACTION_INBOX_DIR / "delete.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "action": "kleinanzeigen_delete_cleanup", "source_platform": "kleinanzeigen",
            "source_slug": "bike", "source_id": "kleinanzeigen:bike", "vinted_draft_id": "vinted-1",
            "phase": "delete_started",
        }), "utf-8")

        with patch.object(vinted_app, "_run_vinted_listing_action") as delete_remote, \
             patch.object(vinted_app, "_wait_for_live_action", side_effect=RuntimeError("timeout")):
            vinted_app._process_kleinanzeigen_delete_action(path)

        delete_remote.assert_not_called()
        self.assertIsNotNone(vinted_app._find_draft("vinted-1"))
        failed = path.with_suffix(".failed.json")
        self.assertTrue(failed.exists())
        self.assertFalse(path.exists())


    def test_renewal_recovery_is_shown_as_processed_unpublished_draft(self):
        recovery = {"id":"recover-1","published_item_id":"","renewal_upload_pending":True,"status":"Erneuerung unterbrochen"}
        fresh = {"id":"new-1","published_item_id":"","renewal_upload_pending":False}
        self.assertTrue(vinted_app._draft_is_true_unpublished(recovery))
        self.assertFalse(vinted_app._draft_is_reviewable_unpublished(recovery))
        self.assertEqual(vinted_app._draft_review_state(recovery), "processed")
        self.assertTrue(vinted_app._draft_is_true_unpublished(fresh))
        self.assertTrue(vinted_app._draft_is_reviewable_unpublished(fresh))

    def test_unpublished_bulk_publish_queues_recovery_as_renew_and_regular_as_publish(self):
        recovery = {
            "id": "recover-1", "title": "Kaschmir Hoodie", "published_item_id": "",
            "renewal_upload_pending": True, "status": "Erneuerung unterbrochen",
            "last_error": "alter Fehler", "photos": [],
        }
        fresh = {
            "id": "fresh-1", "title": "Neue Jacke", "published_item_id": "",
            "renewal_upload_pending": False, "manual_review_confirmed": True,
            "category_verified": True, "category_id": "101", "photos": [],
        }
        vinted_app._save_drafts([recovery, fresh])
        with patch.object(vinted_app, "_ensure_bulk_publish_worker") as worker:
            response = self.client.post(
                "/unpublished/bulk",
                data={"bulk_action": "publish", "draft_ids": ["fresh-1", "recover-1"]},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 302)
        state = vinted_app._load_bulk_publish_state()
        self.assertEqual(
            state["queue"],
            [
                {"draft_id": "recover-1", "action": "renew"},
                {"draft_id": "fresh-1", "action": "publish"},
            ],
        )
        worker.assert_called_once()

    def test_unpublished_bulk_retry_clears_expired_security_state_before_queueing(self):
        expired = (vinted_app.datetime.now(vinted_app.timezone.utc) - vinted_app.timedelta(minutes=1)).isoformat(timespec="seconds")
        recovery = {
            "id": "recover-timeout", "title": "Walkhose", "published_item_id": "",
            "renewal_upload_pending": True, "status": "Erneuerung unterbrochen – Sicherheitsprüfung abgelaufen",
            "last_error": "Die Vinted-Sicherheitsprüfung wurde nicht rechtzeitig abgeschlossen.",
            "security_challenge_required": True, "security_challenge_state": "timed_out",
            "security_challenge_deadline_at": expired, "security_challenge_target_id": "old-tab",
            "photos": [],
        }
        vinted_app._save_drafts([recovery])
        with patch.object(vinted_app, "_ensure_bulk_publish_worker"):
            response = self.client.post(
                "/unpublished/bulk",
                data={"bulk_action": "publish", "draft_ids": ["recover-timeout"]},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 302)
        saved = vinted_app._find_draft("recover-timeout")
        self.assertEqual(saved["status"], "Veröffentlichung wartet")
        self.assertEqual(saved["last_error"], "")
        self.assertNotIn("security_challenge_deadline_at", saved)
        self.assertNotIn("security_challenge_target_id", saved)
        self.assertEqual(vinted_app._load_bulk_publish_state()["queue"], [{"draft_id": "recover-timeout", "action": "renew"}])

    def test_real_security_challenge_during_recovery_sends_primary_push(self):
        recovery = {
            "id": "recover-sec", "title": "Winterjacke", "published_item_id": "",
            "renewal_upload_pending": True, "automation_active": True, "photos": [],
        }
        vinted_app._save_drafts([recovery])
        challenge = vinted_app.VintedSecurityChallenge(
            "Vinted verlangt eine Sicherheitsprüfung.",
            "https://geo.captcha-delivery.com/captcha/?cid=test",
            "challenge-tab",
        )
        with patch.object(vinted_app, "_create_backup"), \
             patch.object(vinted_app, "_prepare_draft_price_reduction", return_value=None), \
             patch.object(vinted_app, "_run_browser_direct_upload", side_effect=challenge), \
             patch.object(vinted_app, "_notify_vinted_security_challenge", return_value=True) as notify:
            with self.assertRaises(vinted_app.VintedSecurityChallenge):
                vinted_app._renew_vinted_draft("recover-sec", automatic=False)
        notify.assert_called_once()
        saved = vinted_app._find_draft("recover-sec")
        self.assertEqual(saved["security_challenge_state"], "waiting")
        self.assertEqual(saved["security_challenge_target_id"], "challenge-tab")

    def test_other_renewal_is_blocked_while_recovery_is_pending(self):
        vinted_app._save_drafts([
            {"id":"recover-1","title":"Schlafsack","published_item_id":"","renewal_upload_pending":True,"automation_active":True,"photos":[]},
            {"id":"other-1","title":"Stiefel","published_item_id":"222","automation_active":True,"photos":[]},
        ])
        with self.assertRaisesRegex(RuntimeError, "Schlafsack"):
            vinted_app._renew_vinted_draft("other-1", automatic=False)

    def test_pending_recovery_blocks_normal_automatic_renewals(self):
        drafts=[
            {"id":"recover-1","renewal_upload_pending":True,"automation_active":True},
            {"id":"other-1","published_item_id":"222","automation_active":True},
        ]
        with patch.object(vinted_app, "_draft_security_retry_due", return_value=False) as retry, \
             patch.object(vinted_app, "_draft_renewal_due", return_value=True) as due:
            candidate, mode = vinted_app._next_automatic_renewal_candidate(drafts)
        self.assertIsNone(candidate)
        self.assertEqual(mode, "recovery_blocked")
        retry.assert_called_once()
        due.assert_not_called()

    def test_automatic_renewal_candidate_is_limited_to_one_item_per_cycle(self):
        drafts=[
            {"id":"first","published_item_id":"111","automation_active":True},
            {"id":"second","published_item_id":"222","automation_active":True},
        ]
        with patch.object(vinted_app, "_draft_renewal_due", return_value=True) as due:
            candidate, mode = vinted_app._next_automatic_renewal_candidate(drafts)
        self.assertEqual(candidate["id"], "first")
        self.assertEqual(mode, "renewal")
        self.assertEqual(due.call_count, 2)

    def test_security_timeout_keeps_pending_renewal_in_recovery_state(self):
        draft={"id":"recover-timeout","title":"Jacke","published_item_id":"","renewal_upload_pending":True,"photos":[]}
        vinted_app._save_drafts([draft])
        vinted_app._mark_security_challenge_timeout(draft)
        saved=vinted_app._find_draft("recover-timeout")
        self.assertIn("Erneuerung unterbrochen", saved["status"])
        self.assertTrue(saved["renewal_upload_pending"])

    def test_login_recovery_uses_short_checkpoint_interval(self):
        self.assertEqual(vinted_app._session_keeper_interval_seconds(), vinted_app.VINTED_SESSION_CHECKPOINT_SECONDS)
        vinted_app._set_vinted_session_status("login_required", "Vinted zeigt die Anmeldung an.")
        self.assertEqual(vinted_app._session_keeper_interval_seconds(), vinted_app.VINTED_LOGIN_RECOVERY_CHECK_SECONDS)

    def test_visible_login_page_is_checkpointed_quickly_even_before_status_changes(self):
        process = MagicMock()
        process.poll.return_value = None
        vinted_app._browser_process = process
        with patch.object(vinted_app, "_browser_page_target", return_value={
            "url": "https://www.vinted.de/member/login",
        }):
            self.assertEqual(vinted_app._session_keeper_interval_seconds(), vinted_app.VINTED_LOGIN_RECOVERY_CHECK_SECONDS)

    def test_browser_idle_sleep_is_disabled_by_default_but_can_be_enabled(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(vinted_app._browser_idle_sleep_enabled())
            (vinted_app.DATA_DIR / "options.json").write_text(json.dumps({"browser_idle_sleep": True}), "utf-8")
            self.assertTrue(vinted_app._browser_idle_sleep_enabled())

    def test_live_status_reports_publish_progress_without_browser_content(self):
        process = MagicMock()
        process.poll.return_value = None
        vinted_app._browser_process = process
        vinted_app._save_drafts([{
            "id": "renew-1", "title": "Walkhose", "renewal_upload_pending": True, "photos": [],
        }])
        vinted_app._save_bulk_publish_state({
            "queue": [{"draft_id": "renew-1", "action": "renew"}],
            "current": {"draft_id": "renew-1", "action": "renew"},
        })
        target = {
            "id": "upload-tab", "type": "page", "webSocketDebuggerUrl": "ws://upload-tab",
            "url": "https://www.vinted.de/items/new?private=must-not-appear",
        }
        with patch.object(vinted_app, "_debug_targets", return_value=[target]):
            status = vinted_app._vinted_live_status_view()
        self.assertEqual(status["state"], "working")
        self.assertEqual(status["headline"], "Neu einstellen läuft")
        self.assertIn("Walkhose", status["detail"])
        self.assertEqual(status["tabs_label"], "1 Vinted-Tab geöffnet")
        self.assertNotIn("private=", json.dumps(status))

    def test_live_status_reports_photo_progress_without_temporary_upload_data(self):
        process = MagicMock()
        process.poll.return_value = None
        vinted_app._browser_process = process
        vinted_app._save_drafts([{
            "id": "upload-1", "title": "Koffer", "photos": [{"file": "one.jpg"}, {"file": "two.jpg"}, {"file": "three.jpg"}],
            "browser_upload_state": {"photo_ids": [101, 102], "uploading_photo_index": 3, "upload_session_id": "private-session"},
        }])
        vinted_app._save_bulk_publish_state({
            "queue": [{"draft_id": "upload-1", "action": "publish"}],
            "current": {"draft_id": "upload-1", "action": "publish"},
        })
        target = {"id": "upload-tab", "type": "page", "webSocketDebuggerUrl": "ws://upload-tab", "url": "https://www.vinted.de/items/new"}
        with patch.object(vinted_app, "_debug_targets", return_value=[target]):
            status = vinted_app._vinted_live_status_view()
        self.assertEqual(status["progress_label"], "Foto 3 von 3 wird hochgeladen")
        self.assertNotIn("private-session", json.dumps(status))

    def test_base_template_uses_one_combined_vinted_status_card(self):
        template = (Path(vinted_app.__file__).parent / "templates" / "base.html").read_text("utf-8")
        form_template = (Path(vinted_app.__file__).parent / "templates" / "form.html").read_text("utf-8")
        self.assertIn('id="vinted-live-status"', template)
        self.assertIn('id="vinted-live-progress"', template)
        self.assertIn('id="vinted-live-preview"', template)
        self.assertIn("x-safari-http://", template)
        self.assertIn("running ? 1000 : 5000", template)
        self.assertNotIn('id="vinted-publish-running"', template)
        self.assertNotIn("monitorVintedPublishJob", template)
        self.assertNotIn("vinted-publish-running", form_template)

    def test_live_preview_returns_one_local_jpeg_frame(self):
        process = MagicMock()
        process.poll.return_value = None
        vinted_app._browser_process = process
        target = {"id": "preview-tab", "type": "page", "webSocketDebuggerUrl": "ws://preview", "url": "https://www.vinted.de/items/new"}
        encoded = base64.b64encode(b"jpeg-preview").decode("ascii")
        with patch.object(vinted_app, "_debug_targets", return_value=[target]), \
             patch.object(vinted_app, "_cdp_command", return_value={"data": encoded}) as capture:
            response = self.client.get("/vinted-browser-preview")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/jpeg")
        self.assertEqual(response.data, b"jpeg-preview")
        self.assertEqual(capture.call_args.args[1], "Page.captureScreenshot")

    def test_live_preview_prefers_the_publish_tab_over_the_restored_primary_tab(self):
        process = MagicMock()
        process.poll.return_value = None
        vinted_app._browser_process = process
        vinted_app._primary_browser_target_id = "catalogue-tab"
        vinted_app._vinted_live_preview_target_id = "publish-tab"
        catalogue = {"id": "catalogue-tab", "type": "page", "webSocketDebuggerUrl": "ws://catalogue", "url": "https://www.vinted.de/catalog"}
        publish = {"id": "publish-tab", "type": "page", "webSocketDebuggerUrl": "ws://publish", "url": "https://www.vinted.de/items/123"}
        with patch.object(vinted_app, "_debug_targets", return_value=[catalogue, publish]):
            selected = vinted_app._vinted_live_preview_target()
        self.assertEqual(selected["id"], "publish-tab")

    def test_live_card_is_limited_to_my_listings_page_and_messages_stay_quiet(self):
        with patch.object(vinted_app, "_load_vinted_messages", return_value=[]):
            response = self.client.get("/messages")
        self.assertNotIn(b'id="vinted-live-status"', response.data)
        self.assertNotIn(b"message-new-badge", response.data)
        self.assertNotIn("_notify_message(", inspect.getsource(vinted_app._activity_monitor_loop))

    def test_live_status_prioritizes_login_over_an_idle_vinted_tab(self):
        process = MagicMock()
        process.poll.return_value = None
        vinted_app._browser_process = process
        vinted_app._set_vinted_session_status("login_required", "Vinted verlangt eine erneute Anmeldung.")
        targets = [
            {"id": "home", "type": "page", "webSocketDebuggerUrl": "ws://home", "url": "https://www.vinted.de/"},
            {"id": "login", "type": "page", "webSocketDebuggerUrl": "ws://login", "url": "https://www.vinted.de/member/login"},
        ]
        with patch.object(vinted_app, "_debug_targets", return_value=targets):
            status = vinted_app._vinted_live_status_view()
        self.assertEqual(status["state"], "attention")
        self.assertEqual(status["headline"], "Vinted-Anmeldung erforderlich")
        self.assertEqual(status["tabs_label"], "2 Vinted-Tabs geöffnet")


if __name__ == "__main__":
    unittest.main()
