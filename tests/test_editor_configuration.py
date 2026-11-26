"""Display preferences must never remove physical model inputs or outputs."""

from copy import deepcopy
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from energy_gui.controller import Controller
from energy_gui.engine import build_network
from energy_gui.storage import load_project, save_project
from PySide6.QtWidgets import QApplication, QMessageBox


class EditorConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.controller = Controller()
        self.controller.loadDemo()

    def test_visibility_does_not_change_network_tables_or_profiles(self):
        before = self.controller.project.to_dict()
        old = build_network(self.controller.project)
        self.assertTrue(self.controller.applyEditorConfiguration(["Generator"], {"Generator": ["p_nom"]}))
        state = self.controller.state
        self.assertEqual([t["name"] for t in state["visibleTypes"]], ["Generator"])
        self.assertEqual(state["inputNames"], ["p_nom"])
        self.assertEqual(self.controller.sheetModel.columns, ["name", "p_nom"])
        self.assertEqual(self.controller.project.objects, before["objects"])
        self.assertEqual(self.controller.project.profiles, before["profiles"])
        self.assertFalse(self.controller.sheetModel.addColumn("marginal_cost"))
        self.assertFalse(self.controller.sheetModel.pasteTsv("name\tmarginal_cost\nThermal\t1\n"))
        self.assertTrue(self.controller.sheetModel.pasteTsv("name\tp_nom\nThermal\t160\n"))
        self.assertTrue(self.controller.applySheet())
        self.assertEqual(self.controller.project.object("Generator", "Thermal")["attributes"]["marginal_cost"], 2500)
        # Return to the original capacity to compare every actual PyPSA input.
        self.assertTrue(self.controller.sheetHistory(False))
        new = build_network(self.controller.project)
        pd.testing.assert_frame_equal(old.snapshot_weightings, new.snapshot_weightings)
        for key in old.components.keys():
            pd.testing.assert_frame_equal(old.components[key].static, new.components[key].static)
            for attribute in old.components[key].dynamic:
                pd.testing.assert_frame_equal(old.components[key].dynamic[attribute], new.components[key].dynamic[attribute])

    def test_configuration_roundtrip_and_old_database_default(self):
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        with tempfile.TemporaryDirectory(dir=preferred) as tmp:
            path = Path(tmp) / "project.sqlite"
            self.controller.applyEditorConfiguration(["Bus", "Generator"], {"Bus": [], "Generator": ["p_nom"]})
            save_project(self.controller.project, path)
            reopened = load_project(path)
            self.assertEqual(reopened.to_dict(), self.controller.project.to_dict())
            with closing(sqlite3.connect(path)) as connection, connection:
                payload = json.loads(connection.execute("SELECT value FROM metadata WHERE key='project'").fetchone()[0])
                self.assertNotIn("editor_config", payload, "Older readers must still recognize the project payload.")
                connection.execute("DELETE FROM metadata WHERE key='editor_config'")
            self.assertEqual(load_project(path).editor_config, {})

    def test_empty_selections_and_restore_are_non_destructive(self):
        before = deepcopy(self.controller.project.objects)
        self.assertTrue(self.controller.applyEditorConfiguration([], {}))
        self.assertEqual(self.controller.state["visibleTypes"], [])
        self.assertFalse(self.controller.state["editable"])
        self.assertFalse(self.controller.sheetModel.addRow())
        self.assertEqual(self.controller.project.objects, before)
        settings = self.controller.editorConfiguration()
        all_categories = list(settings["catalogue"])
        self.assertTrue(self.controller.applyEditorConfiguration(all_categories, {}))
        self.assertTrue(self.controller.state["componentVisible"])
        self.assertEqual(self.controller.project.objects, before)

    def test_invalid_preferences_and_draft_cancellation_are_atomic(self):
        before = self.controller.project.to_dict()
        for categories, properties in [(["Unknown"], {}), (["Bus", "Bus"], {}), (["Bus"], {"Bus": ["not_real"]})]:
            self.assertFalse(self.controller.applyEditorConfiguration(categories, properties))
            self.assertEqual(self.controller.project.to_dict(), before)
        self.controller.selectType("Generator")
        self.controller.sheetModel.pasteTsv("name\tp_nom\nThermal\t160\n")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.controller.applyEditorConfiguration(["Bus"], {}))
        self.assertEqual(self.controller.project.to_dict(), before)
        self.assertTrue(self.controller.sheetModel.dirty)
