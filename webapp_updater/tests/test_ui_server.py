#!/usr/bin/env python3
"""Behavior tests for the unprivileged version-history web endpoint."""

import importlib.util
import json
import threading
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


MODULE = Path(__file__).resolve().parents[1] / "rootfs" / "ui_server.py"
SPEC = importlib.util.spec_from_file_location("updater_ui", MODULE)
ui = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ui)


class UiServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        data = Path(self.temporary.name)
        ui.DATA = data
        ui.CATALOG = data / "version-catalog.json"
        ui.STATUS = data / "version-status.json"
        ui.BACKUPS = data / "pre-update-backups.json"
        ui.REQUESTS = data / "rollback-requests"
        ui.ACCESS_FILE = data / "version-ui-access-code"
        ui.ACCESS_CODE = ui.load_access_code()
        ui.CATALOG.write_text(json.dumps({
            "generated_at": "2026-09-25 01:26:00 CEST",
            "apps": [{
                "source": "barf_portionsrechner",
                "local_folder": "barf_portionsrechner",
                "local_slug": "local_barf_portionsrechner",
                "versions": [{"version": "1.5.0", "commit": "a" * 40}],
            }],
        }), encoding="utf-8")
        ui.STATUS.write_text(json.dumps({"apps": [{
            "local_slug": "local_barf_portionsrechner", "version": "1.10.0",
        }]}), encoding="utf-8")
        ui.BACKUPS.write_text("[]", encoding="utf-8")
        self.server = ui.ThreadingHTTPServer(("127.0.0.1", 0), ui.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.temporary.cleanup()

    def request(self, path, payload=None, access=True):
        request = Request(f"{self.base}{path}")
        if access:
            request.add_header("X-WebApp-Access", ui.ACCESS_CODE)
        if payload is not None:
            request.method = "POST"
            request.add_header("Content-Type", "application/json")
            request.data = json.dumps(payload).encode()
        with urlopen(request, timeout=2) as response:
            return response.status, json.loads(response.read())

    def test_only_catalogued_version_can_be_queued_once(self):
        self.assertEqual(ui.ACCESS_FILE.stat().st_mode & 0o777, 0o600)
        self.assertEqual(ui.load_access_code(), ui.ACCESS_CODE)
        with self.assertRaises(HTTPError) as anonymous:
            self.request("/api/state", access=False)
        self.assertEqual(anonymous.exception.code, 401)
        with self.assertRaises(HTTPError) as anonymous_write:
            self.request("/api/rollback", {
                "slug": "local_barf_portionsrechner", "version": "1.5.0",
            }, access=False)
        self.assertEqual(anonymous_write.exception.code, 401)
        self.assertFalse(ui.REQUESTS.exists())

        status, payload = self.request("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(payload["apps"][0]["status"]["version"], "1.10.0")

        with self.assertRaises(HTTPError) as invalid:
            self.request("/api/rollback", {
                "slug": "local_barf_portionsrechner", "version": "9.9.9",
            })
        self.assertEqual(invalid.exception.code, 400)
        with self.assertRaises(HTTPError) as invalid_shape:
            self.request("/api/rollback", ["not", "an", "action"])
        self.assertEqual(invalid_shape.exception.code, 400)

        status, _ = self.request("/api/rollback", {
            "slug": "local_barf_portionsrechner",
            "version": "1.5.0",
            "restore_data": True,
        })
        self.assertEqual(status, 202)
        saved = json.loads((ui.REQUESTS / "local_barf_portionsrechner.json").read_text())
        self.assertEqual(saved["action"], "rollback")
        self.assertTrue(saved["restore_data"])

        with self.assertRaises(HTTPError) as duplicate:
            self.request("/api/rollback", {
                "slug": "local_barf_portionsrechner", "version": "1.5.0",
            })
        self.assertEqual(duplicate.exception.code, 409)

    def test_running_job_rejects_new_rollback(self):
        ui.STATUS.write_text(json.dumps({"apps": [{
            "local_slug": "local_barf_portionsrechner",
            "version": "1.10.0",
            "job_status": "running",
        }]}), encoding="utf-8")
        with self.assertRaises(HTTPError) as busy:
            self.request("/api/rollback", {
                "slug": "local_barf_portionsrechner", "version": "1.5.0",
            })
        self.assertEqual(busy.exception.code, 409)
        self.assertFalse(ui.REQUESTS.exists())

    def test_simultaneous_requests_queue_only_one_action(self):
        def submit(_index):
            try:
                return self.request("/api/rollback", {
                    "slug": "local_barf_portionsrechner", "version": "1.5.0",
                })[0]
            except HTTPError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=4) as executor:
            responses = list(executor.map(submit, range(10)))
        self.assertEqual(responses.count(202), 1)
        self.assertEqual(responses.count(409), 9)
        self.assertEqual(len(list(ui.REQUESTS.glob("*.json"))), 1)
        self.assertEqual(list(ui.REQUESTS.glob("*.new")), [])


if __name__ == "__main__":
    unittest.main()
