"""Project and CSV helpers participate in the same guarded lifecycle as objects."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from energy_gui.controller import Controller
from energy_gui.storage import load_project
from PySide6.QtWidgets import QApplication, QMessageBox


class HelperDraftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        self.temp = tempfile.TemporaryDirectory(dir=preferred)
        self.controller = Controller()
        self.controller.loadDemo()
        self.controller.path = Path(self.temp.name) / "project.sqlite"

    def tearDown(self):
        self.temp.cleanup()

    def settings(self, **changes):
        values = self.controller._live_settings() | changes
        self.controller.updateSettingsDraft(values["name"], values["currency"], values["start"], values["count"], values["minutes"])

    def csv(self):
        path = Path(self.temp.name) / "profile.csv"
        pd.DataFrame({"time": self.controller.project.snapshots, "power": [12.] * 24}).to_csv(path, index=False)
        self.controller.previewCsv(str(path))
        self.controller.updateCsvDraft("Load", "City demand", "p_set", "time", "power")

    def test_settings_cancel_blocks_save_run_close_and_replacement(self):
        before = self.controller.project.to_dict()
        self.settings(name="Pending")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.controller.saveProject())
            self.controller.startRun("pending", "none")
            self.assertIsNone(self.controller.process)
            self.assertFalse(self.controller.canClose())
            self.controller.newProject()
        self.assertEqual(self.controller.project.to_dict(), before)
        self.assertTrue(self.controller.helperState["settingsDirty"])
        self.assertFalse(self.controller.path.exists())

    def test_settings_save_applies_then_persists_and_discard_restores(self):
        self.settings(name="Applied", currency="USD")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save):
            self.assertTrue(self.controller.saveProject())
        self.assertEqual(load_project(self.controller.path).name, "Applied")
        self.assertFalse(self.controller.helperState["settingsDirty"])
        self.settings(name="Discard me")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(self.controller.resolveDraft())
        self.assertEqual(self.controller.helperState["settings"]["name"], "Applied")

    def test_invalid_settings_remain_draft_and_do_not_partially_change_project(self):
        before = self.controller.project.to_dict()
        self.settings(name="Should not apply", count=12)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save):
            self.assertFalse(self.controller.resolveDraft())
        self.assertEqual(self.controller.project.to_dict(), before)
        self.assertTrue(self.controller.helperState["settingsDirty"])

    def test_csv_cancel_then_apply_uses_captured_target_not_editor_category(self):
        self.csv()
        before = self.controller.project.to_dict()
        self.controller.component = "Generator"
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.controller.saveProject())
        self.assertEqual(self.controller.project.to_dict(), before)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save):
            self.assertTrue(self.controller.saveProject())
        profile = next(p for p in load_project(self.controller.path).profiles if p["component"] == "Load")
        self.assertEqual(profile["values"], [12.] * 24)
        self.assertEqual(self.controller.csv_info["path"], "")
        self.assertFalse(self.controller.helperState["csvDirty"])

    def test_csv_missing_file_and_bad_mapping_preserve_draft_and_values(self):
        self.csv()
        before = self.controller.project.to_dict()
        self.controller.updateCsvDraft("Load", "City demand", "p_set", "bad column", "power")
        self.assertFalse(self.controller.applyCsvDraft())
        self.assertEqual(self.controller.project.to_dict(), before)
        Path(self.controller.csv_info["path"]).unlink()
        self.assertFalse(self.controller.applyCsvDraft())
        self.assertTrue(self.controller.helperState["csvDirty"])
        self.assertEqual(self.controller.project.to_dict(), before)

    def test_csv_discard_leaves_imported_values_and_replacement_clears_source(self):
        self.csv()
        before = self.controller.project.to_dict()
        self.controller.discardCsvDraft()
        self.assertEqual(self.controller.project.to_dict(), before)
        self.csv()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.controller.newProject()
        self.assertEqual(self.controller.csv_info["path"], "")
        self.assertFalse(self.controller.helperState["csvDirty"])
        self.assertEqual(self.controller.project.profiles, [])

    def test_active_run_blocks_helper_and_identity_mutations(self):
        self.settings(name="Pending")
        before = self.controller.project.to_dict()
        self.controller.process = object()
        self.assertFalse(self.controller.applySettingsDraft())
        self.assertFalse(self.controller.applyCsvDraft())
        self.assertFalse(self.controller.renameObject("new"))
        self.assertFalse(self.controller.deleteObjects([{"component": "Bus", "name": "North"}]))
        self.assertEqual(self.controller.project.to_dict(), before)
        self.controller.process = None

    def test_replacement_csv_cancel_preserves_file_and_mapping(self):
        self.csv()
        before_file = self.controller.csv_info.copy()
        before_mapping = self.controller.helperState["csv"].copy()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.controller.previewCsv(str(Path(self.temp.name) / "another.csv"))
        self.assertEqual(self.controller.csv_info, before_file)
        self.assertEqual(self.controller.helperState["csv"], before_mapping)
