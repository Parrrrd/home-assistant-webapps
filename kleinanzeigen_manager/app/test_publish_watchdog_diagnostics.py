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
            "login person@example.com password=supersecret Authorization=abc Bearer abcdefghijklmnopqrstuvwxyz"
        )
        self.assertNotIn("person@example.com", clean)
        self.assertNotIn("supersecret", clean)
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

    def test_bot_patch_contains_hard_attempt_watchdog_and_early_zip(self):
        source = (Path(__file__).resolve().parents[1] / "kleinanzeigen_bot_init_patched.py").read_text("utf-8")
        self.assertIn("PUBLISH_ATTEMPT_WATCHDOG_SECONDS:Final[float] = 120.0", source)
        self.assertIn("class PublishAttemptWatchdogError", source)
        self.assertIn("Create a minimal ZIP immediately", source)
        self.assertIn("Not retrying this run", source)


if __name__ == "__main__":
    unittest.main()
