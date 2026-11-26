"""Failure diagnostics preserve prior displays and never repair artifacts silently."""

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from energy_gui.controller import Controller
from energy_gui.diagnostics import failure_message
from test_network_view import overlay_fixture
from PySide6.QtWidgets import QApplication


class Stage3EFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        self.temp = tempfile.TemporaryDirectory(prefix="failure_context_", dir=preferred)
        self.run = Path(self.temp.name)/"runs"/"reference"
        self.project, self.catalog = overlay_fixture(self.run)
        self.controller = Controller()
        self.controller.project = deepcopy(self.project)
        self.controller._reset_draft()
        self.messages = []
        self.controller.notice.connect(self.messages.append)
        self.assertTrue(self.controller.openRun(str(self.run)))
        self.assertTrue(self.controller.queryResults("Line", ["L"], ["p0"], "", ""))
        self.assertTrue(self.controller.loadNetworkRun(str(self.run)))
        self.tab = self.controller.workspace.active_id
        self.graph = deepcopy(self.controller.networkState["topology"])

    def tearDown(self):
        self.controller.notice.disconnect()
        self.temp.cleanup()

    def assert_failed_read_preserves_views(self):
        before = {str(p.relative_to(self.run)): p.read_bytes() for p in self.run.rglob("*") if p.is_file()}
        self.assertFalse(self.controller.openRun(str(self.run)))
        self.assertFalse(self.controller.loadNetworkRun(str(self.run)))
        self.assertEqual(self.controller.workspace.active_id, self.tab)
        self.assertEqual(self.controller.networkState["topology"], self.graph)
        self.assertEqual({str(p.relative_to(self.run)): p.read_bytes() for p in self.run.rglob("*") if p.is_file()}, before)

    def test_truncated_status_has_actionable_diagnostic_and_preserves_display(self):
        (self.run/"run_config.json").write_text('{"status":')
        self.assert_failed_read_preserves_views()
        self.assertIn("run_config.json", self.messages[-1])
        self.assertIn("Restore", self.messages[-1])

    def test_missing_catalogue_is_not_created_and_prior_results_survive(self):
        (self.run/"catalog.json").unlink()
        self.assert_failed_read_preserves_views()
        self.assertIn("required local file is missing", self.messages[-1])
        self.assertFalse((self.run/"catalog.json").exists())

    def test_invalid_status_schema_is_rejected_before_state_mutation(self):
        (self.run/"run_config.json").write_text('[]')
        self.assert_failed_read_preserves_views()
        self.assertIn("valid project identity", self.messages[-1])

    def test_malformed_catalogue_entry_is_explained_without_typeerror(self):
        (self.run/"catalog.json").write_text('[42]')
        self.assert_failed_read_preserves_views()
        self.assertIn("Malformed result catalogue", self.messages[-1])

    def test_empty_catalogue_is_not_a_valid_successful_run(self):
        (self.run/"catalog.json").write_text('[]')
        self.assert_failed_read_preserves_views()

    def test_duplicate_object_identities_in_static_table_are_rejected(self):
        path = self.run/"tables"/"Line.csv"
        path.write_text(path.read_text()+path.read_text().splitlines()[1]+"\n")
        self.assert_failed_read_preserves_views()
        self.assertIn("unique name", self.messages[-1])

    def test_empty_static_table_gives_filename_and_restore_advice(self):
        (self.run/"tables"/"Line.csv").write_text("")
        self.assert_failed_read_preserves_views()
        self.assertIn("Line.csv", self.messages[-1])
        self.assertIn("unreadable", self.messages[-1])

    def test_permission_error_has_retry_advice_and_no_state_change(self):
        before = self.controller.project.to_dict()
        with patch("energy_gui.controller.save_project", side_effect=PermissionError("test locked file")):
            self.controller.path = Path(self.temp.name)/"locked.sqlite"
            self.assertFalse(self.controller.saveProject())
        self.assertIn("file locked", self.messages[-1])
        self.assertEqual(self.controller.project.to_dict(), before)
        self.assertIn("retry", failure_message(PermissionError("locked")))
