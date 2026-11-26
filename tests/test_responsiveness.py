"""Guard the UI hot path and retention of non-model interchange metadata."""

from copy import deepcopy
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from energy_gui.controller import Controller
from energy_gui.history import ModelHistory
from energy_gui.project import Project
from energy_gui.storage import load_project, save_project
from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtWidgets import QApplication


class NoCopy(dict):
    def __deepcopy__(self, memo):
        raise AssertionError("Inert export definitions entered a hot copy path.")


class ResponsivenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.c = Controller()
        self.c.loadDemo()
        self.info = {"report": {"version": 1}, "export_schema": NoCopy({"large": ["definitions"]})}
        self.c.project.interchange_info = self.info
        self.c.changed.emit()

    def test_state_reads_never_serialize_even_with_undo_and_redo_stacks(self):
        with patch.object(Project, "to_dict", side_effect=AssertionError("State must not serialize")):
            for _ in range(10):
                self.assertFalse(self.c.state["modelCanUndo"])
                self.c.uiState
            self.assertTrue(self.c.storeObject("Extra", "{}"))
            self.assertTrue(self.c.state["modelCanUndo"])
            self.assertTrue(self.c.uiState["modelCanUndo"])
            self.assertTrue(self.c.modelHistory(False))
            self.assertTrue(self.c.state["modelCanRedo"])
            self.assertTrue(self.c.modelHistory(True))
        self.assertIs(self.c.project.interchange_info, self.info)

    def test_qml_snapshot_is_built_once_until_a_notification(self):
        with patch.object(self.c, "_build_state", wraps=self.c._build_state) as build:
            for _ in range(50):
                self.c.uiState
            self.assertEqual(build.call_count, 1)
            self.c.project.name = "Renamed"
            self.c.changed.emit()
            self.assertEqual(self.c.uiState["projectName"], "Renamed")
            self.c.uiState
            self.assertEqual(build.call_count, 2)

    def test_python_state_remains_fresh_for_external_mutation(self):
        self.c.uiState
        self.c.project.name = "External"
        self.assertEqual(self.c.state["projectName"], "External")
        self.c.changed.emit()
        self.assertEqual(self.c.uiState["projectName"], "External")

    def test_qml_binding_is_fresh_on_the_first_notification(self):
        engine = QQmlEngine()
        engine.rootContext().setContextProperty("backend", self.c)
        component = QQmlComponent(engine)
        component.setData(
            b'import QtQml\nQtObject { property string shown: backend.uiState.projectName }',
            QUrl(),
        )
        obj = component.create()
        self.assertIsNotNone(obj, [e.toString() for e in component.errors()])
        self.assertEqual(obj.property("shown"), self.c.project.name)
        for name in ("First change", "Second change"):
            self.c.project.name = name
            self.c.changed.emit()
            self.app.processEvents()
            self.assertEqual(obj.property("shown"), name)
        obj.deleteLater()
        engine.deleteLater()

    def test_reset_readers_observe_new_state_before_changed(self):
        self.c.uiState
        reads = []
        self.c.editorReset.connect(lambda: reads.append(self.c.uiState["selected"]))
        self.c.component, self.c.selected = "Generator", "Solar"
        self.c._reset_draft()
        self.assertEqual(reads[-1], "Solar")
        self.c.uiState
        self.c.project.name = "Updated helpers"
        self.c.helpersReset.connect(lambda: reads.append(self.c.uiState["projectName"]))
        self.c._reset_helpers()
        self.assertEqual(reads[-1], "Updated helpers")

    def test_spreadsheet_baseline_is_detached_without_export_dictionary(self):
        self.c.selectType("Generator")
        self.assertNotIn("interchange_info", self.c._sheet.baseline)
        baseline = deepcopy(self.c._sheet.baseline)
        self.c.project.object("Generator", "Solar")["attributes"]["p_nom"] += 1
        self.assertEqual(self.c._sheet.baseline, baseline)
        self.assertTrue(self.c.sheetModel.pasteTsv("name\tp_nom\nSolar\t123\n"))
        # Stale real model edits must still be rejected, not masked by caching.
        self.assertFalse(self.c.applySheet())

    def test_undo_preserves_latest_metadata_and_ignores_its_size(self):
        self.assertTrue(self.c.storeObject("Extra", "{}"))
        self.assertNotIn("interchange_info", self.c.model_history.undo[-1]["before"])
        self.assertNotIn("interchange_info", self.c.model_history.undo[-1]["after"])
        self.info["report"]["version"] = 2
        self.assertTrue(self.c.modelHistory(False))
        self.assertIs(self.c.project.interchange_info, self.info)
        self.assertEqual(self.c.project.interchange_info["report"]["version"], 2)
        self.assertTrue(self.c.modelHistory(True))
        self.c.project.name = "Unrelated edit"
        self.assertFalse(self.c.state["modelCanUndo"])
        self.assertFalse(self.c.modelHistory(False))

    def test_serialization_keeps_metadata_and_returns_detached_data(self):
        self.c.project.interchange_info = {"report": {"version": 1}, "export_schema": {"rows": [1, 2]}}
        data = self.c.project.to_dict()
        data["interchange_info"]["export_schema"]["rows"].append(3)
        self.assertEqual(self.c.project.interchange_info["export_schema"]["rows"], [1, 2])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "project.sqlite"
            save_project(self.c.project, path)
            self.assertEqual(load_project(path).interchange_info, self.c.project.interchange_info)

    def test_history_budget_does_not_count_or_copy_inert_metadata(self):
        history = ModelHistory(byte_limit=500)
        self.assertTrue(history.record(
            {"x": 1, "interchange_info": NoCopy({"payload": "x" * 10000})},
            {"x": 2, "interchange_info": NoCopy({"payload": "x" * 10000})}, "edit",
        ))
        self.assertTrue(history.available({"x": 2, "interchange_info": self.info}))
        self.assertLess(history.undo[0]["size"], 500)
