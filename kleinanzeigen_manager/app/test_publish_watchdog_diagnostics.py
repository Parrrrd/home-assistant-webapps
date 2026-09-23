import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import app as manager


class PublishWatchdogDiagnosticsTests(unittest.TestCase):
    def test_runtime_redaction_removes_email_password_and_bearer(self):
        clean = manager._debug_redact_runtime_text(
            'login person@example.com password=supersecret Authorization=abc {"access_token":"json-secret"} Bearer abcdefghijklmnopqrstuvwxyz'
        )
        self.assertNotIn("person@example.com", clean)
        self.assertNotIn("supersecret", clean)
        self.assertNotIn("json-secret", clean)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", clean)
        self.assertIn("<redacted-email>", clean)
        self.assertIn("<redacted>", clean)

    def test_manager_timeout_always_creates_sanitized_zip(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(manager, "DIAGNOSTICS_DIR", Path(tmp)):
            error = subprocess.TimeoutExpired(
                ["python3", "-m", "kleinanzeigen_bot"],
                210,
                output="still running for person@example.com password=hunter2",
                stderr="Bearer abcdefghijklmnopqrstuvwxyz",
            )
            archive = manager._write_manager_watchdog_debug(
                "publish",
                {"slug": "example-ad", "title": "Example ad"},
                210,
                error,
            )
            self.assertIsNotNone(archive)
            self.assertTrue(Path(archive).is_file())
            with zipfile.ZipFile(archive, "r") as zf:
                names = set(zf.namelist())
                self.assertIn("00-summary.txt", names)
                self.assertIn("01-manager-context.json", names)
                text = "\n".join(zf.read(name).decode("utf-8") for name in names)
            self.assertNotIn("person@example.com", text)
            self.assertNotIn("hunter2", text)
            self.assertNotIn("abcdefghijklmnopqrstuvwxyz", text)

    def test_manager_timeout_after_submit_is_marked_no_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "bot.yaml"
            config.write_text("browser: {}\n", "utf-8")
            timeout = subprocess.TimeoutExpired(
                ["python3", "-m", "kleinanzeigen_bot"],
                540,
                output="PublishSubmissionUncertainError: Publish watchdog exceeded after the submit boundary",
            )
            with patch.object(manager, "_prepare_browser_profile_for_bot", return_value=[]), \
                    patch.object(manager, "_cleanup_bot_profile", return_value=[]), \
                    patch.object(manager, "_write_manager_watchdog_debug", return_value=Path(tmp) / "debug.zip"), \
                    patch.object(manager.subprocess, "run", side_effect=timeout):
                result = manager._run_bot("publish", config_path=config)

        self.assertFalse(result["ok"])
        self.assertTrue(result["uncertain_submit"])
        self.assertFalse(result["safe_retry"])
        self.assertIn("kein erneutes Veröffentlichen", result["output"])

    def test_manager_preflight_debug_contains_safe_state_and_never_secrets(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(manager, "DIAGNOSTICS_DIR", Path(tmp)):
            config = Path(tmp) / "bot.yaml"
            config.write_text(
                "browser:\n  user_data_dir: /private/profile\nlogin:\n  email: person@example.com\n  password: hunter2\n",
                "utf-8",
            )
            archive = manager._write_manager_failure_debug(
                "publish", {"slug": "example-ad", "title": "Example ad"},
                phase="manager-preflight", reason="Failed to connect for person@example.com",
                output="password=hunter2 Bearer abcdefghijklmnopqrstuvwxyz",
                config_path=config, returncode=-9, signal_name="signal-9",
            )
            self.assertTrue(Path(archive).is_file())
            with zipfile.ZipFile(archive, "r") as zf:
                names = set(zf.namelist())
                self.assertTrue({
                    "00-summary.txt", "02-manager-operation-state.json", "03-sanitized-bot-config.json",
                    "04-ad-data.json", "05-browser-process-status.json", "06-runtime.json",
                }.issubset(names))
                text = "\n".join(zf.read(name).decode("utf-8") for name in names)
            self.assertNotIn("person@example.com", text)
            self.assertNotIn("hunter2", text)
            self.assertNotIn("/private/profile", text)
            self.assertNotIn("abcdefghijklmnopqrstuvwxyz", text)

    def test_prestart_retry_stops_at_visible_attempt_limit(self):
        state, meta = {"ads": {}}, {}
        with patch.object(manager, "PUBLISH_PRESTART_RETRY_MAX", 3), \
                patch.object(manager, "_operation_get", return_value={"attempt": 3}), \
                patch.object(manager, "_operation_failed") as failed:
            retry_at = manager._queue_prestart_publish_retry(
                state, "example-ad", meta, {"debug_zip": "/share/Kleinanzeigen/debug/example.zip"},
                wait_message="retry", origin_label="Test",
            )
        self.assertIsNone(retry_at)
        self.assertNotIn("publish_retry_at", meta)
        failed.assert_called_once()
        self.assertIn("example.zip", meta["history"][-1]["action"])

    def test_bot_patch_contains_hard_attempt_watchdog_and_early_zip(self):
        source = (Path(__file__).resolve().parents[1] / "kleinanzeigen_bot_init_patched.py").read_text("utf-8")
        self.assertIn("PUBLISH_ATTEMPT_WATCHDOG_SECONDS:Final[float] = 480.0", source)
        self.assertIn("class PublishAttemptWatchdogError", source)
        self.assertIn("Create a minimal ZIP immediately", source)
        self.assertIn("Not retrying this run", source)
        self.assertIn('"p-anzeige-aufgeben-bestaetigung.html" in url', source)
        self.assertIn("confirmation page omitted ID", source)

    def test_uncertain_publish_result_requires_manual_review_not_retry(self):
        self.assertTrue(manager._publish_result_requires_manual_review({
            "uncertain_submit": True,
            "no_retry": True,
        }))
        self.assertFalse(manager._publish_result_requires_manual_review({
            "uncertain_submit": True,
            "safe_retry": True,
        }))


if __name__ == "__main__":
    unittest.main()
