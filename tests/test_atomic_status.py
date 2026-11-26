"""Bounded retry of transient Windows locks without non-atomic writes."""

import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from energy_gui.engine import execute_run, write_json


class AtomicStatusTests(unittest.TestCase):
    def setUp(self):
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        self.temp = tempfile.TemporaryDirectory(prefix="atomic_status_", dir=preferred)
        self.path = Path(self.temp.name) / "run_config.json"
        self.path.write_text('{"status":"running"}')

    def tearDown(self):
        self.temp.cleanup()

    def test_transient_permission_error_retries_and_publishes_atomically(self):
        replace = Path.replace
        attempts = []

        def temporarily_locked(source, target):
            attempts.append(source)
            self.assertEqual(json.loads(self.path.read_text())["status"], "running")
            if len(attempts) < 3:
                raise PermissionError("Transient file lock")
            return replace(source, target)

        with patch.object(Path, "replace", autospec=True, side_effect=temporarily_locked), patch("energy_gui.engine.time.sleep") as delay:
            write_json(self.path, {"status": "succeeded"})
        self.assertEqual(len(attempts), 3)
        self.assertEqual(delay.call_count, 2)
        self.assertEqual(json.loads(self.path.read_text())["status"], "succeeded")
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_permanent_permission_error_preserves_prior_status_and_cleans_temp(self):
        with patch.object(Path, "replace", side_effect=PermissionError("Permanent denial")) as replace, patch("energy_gui.engine.time.sleep") as delay:
            with self.assertRaises(PermissionError):
                write_json(self.path, {"status": "succeeded"})
        self.assertEqual(replace.call_count, 10)
        self.assertEqual(delay.call_count, 9)
        self.assertEqual(json.loads(self.path.read_text())["status"], "running")
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_failed_publication_never_reports_complete_or_leaks_log_handler(self):
        handlers = list(logging.getLogger().handlers)
        events = []
        with patch("energy_gui.engine.write_json", side_effect=PermissionError("Permanent denial")), patch("energy_gui.engine.logging.exception") as logged:
            with self.assertRaises(PermissionError):
                execute_run(self.path.parent, lambda stage, message: events.append(stage))
            logged.assert_called_once()
        self.assertNotIn("complete", events)
        self.assertEqual(logging.getLogger().handlers, handlers)
        log = self.path.parent / "application.log"
        log.rename(log.with_suffix(".closed"))
