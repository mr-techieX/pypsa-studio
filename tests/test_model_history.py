"""Atomic model history and its separation from disk, views and frozen runs."""

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from energy_gui.controller import Controller
from energy_gui.history import ModelHistory
from energy_gui.network_view import object_key
from energy_gui.storage import load_project
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from test_network_view import overlay_fixture


class ModelHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        self.temp = tempfile.TemporaryDirectory(prefix="model_history_", dir=preferred)
        self.root = Path(self.temp.name)
        self.c = Controller()
        self.c.loadDemo()

    def tearDown(self):
        self.c._recovery_timer.stop()
        if self.c.recovery_store:
            self.c.recovery_store.close()
        self.temp.cleanup()

    def data(self):
        return self.c.project.to_dict()

    def roundtrip(self, before, after):
        self.assertTrue(self.c.modelHistory(False))
        self.assertEqual(self.data(), before)
        self.assertTrue(self.c.modelHistory(True))
        self.assertEqual(self.data(), after)

    def test_create_edit_noop_invalid_and_redo_branching(self):
        self.assertFalse(self.c.state["modelCanUndo"])
        before = self.data()
        self.assertTrue(self.c.storeObject("Extra", '{"v_nom":110}'))
        after = self.data()
        self.roundtrip(before, after)
        count = len(self.c.model_history.undo)
        self.c.selectObject("Extra")
        self.assertTrue(self.c.storeObject("Extra", '{"v_nom":110}'))
        self.assertEqual(len(self.c.model_history.undo), count)
        self.assertFalse(self.c.storeObject("Extra", '{"v_nom":"bad"}'))
        self.assertEqual(self.data(), after)
        self.assertTrue(self.c.modelHistory(False))
        self.assertTrue(self.c.storeObject("Other", '{}'))
        self.assertFalse(self.c.state["modelCanRedo"])

    def test_property_edit_restores_omission_and_explicit_default(self):
        self.c.selectType("Generator")
        self.c.selectObject("Solar")
        before = self.data()
        attrs = deepcopy(self.c.project.object("Generator", "Solar")["attributes"])
        attrs["p_nom"] = 100
        attrs["p_min_pu"] = 0  # Explicit default must not disappear on redo.
        self.assertTrue(self.c.storeObject("Solar", json.dumps(attrs)))
        self.roundtrip(before, self.data())

    def test_rename_reverses_references_profiles_and_saved_layout_keys(self):
        old, new = object_key("Generator", "Solar"), object_key("Generator", "PV")
        layout = dict(positions={old: dict(x=100, y=100)}, zoom=1, panX=0, panY=0, width=900, height=520)
        self.c.project.schematic_layouts = {"current": deepcopy(layout), "run:old": deepcopy(layout)}
        self.c.selectType("Generator")
        self.c.selectObject("Solar")
        before = self.data()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(self.c.renameObject("PV"))
        after = self.data()
        self.roundtrip(before, after)
        self.c.project.schematic_layouts["current"]["zoom"] = 1.7
        self.c.project.schematic_layouts["current"]["positions"][new] = dict(x=300, y=200)
        self.assertTrue(self.c.modelHistory(False))
        current = self.c.project.schematic_layouts["current"]
        self.assertEqual(current["zoom"], 1.7)
        self.assertEqual(current["positions"][old], dict(x=300, y=200))
        self.assertEqual(self.c.project.schematic_layouts["run:old"], layout)

    def test_dependency_aware_bulk_delete_restores_objects_and_profiles(self):
        before = self.data()
        records = [dict(component="Generator", name="Solar")]
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(self.c.deleteObjects(records))
        self.roundtrip(before, self.data())
        count = len(self.c.model_history.undo)
        self.assertFalse(self.c.deleteObjects([dict(component="Bus", name="North")]))
        self.assertEqual(len(self.c.model_history.undo), count)

    def test_settings_visibility_profile_remove_in_one_ordered_chain(self):
        states = [self.data()]
        self.c.configure("Renamed study", "USD", self.c.project.snapshots[0], 24, 60)
        states.append(self.data())
        self.assertTrue(self.c.applyEditorConfiguration(["Bus"], {}))
        states.append(self.data())
        self.c.removeProfile(0)
        states.append(self.data())
        for expected in reversed(states[:-1]):
            self.assertTrue(self.c.modelHistory(False))
            self.assertEqual(self.data(), expected)
        for expected in states[1:]:
            self.assertTrue(self.c.modelHistory(True))
            self.assertEqual(self.data(), expected)

    def test_imported_values_undo_redo_do_not_need_original_csv(self):
        path = self.root / "load.csv"
        path.write_text("time,mw\n" + "".join(f"{t},50\n" for t in self.c.project.snapshots))
        self.c.selectType("Load")
        self.c.previewCsv(str(path))
        self.c.updateCsvDraft("Load", "City demand", "p_set", "time", "mw")
        before = self.data()
        self.assertTrue(self.c.applyCsvDraft())
        after = self.data()
        path.unlink()
        self.roundtrip(before, after)

    def test_spreadsheet_and_legacy_history_are_safely_integrated(self):
        self.c.selectType("Generator")
        before = self.data()
        self.assertTrue(self.c.beginSheet())
        self.assertTrue(self.c.sheetModel.pasteTsv("name\tp_nom\nThermal\t160\n"))
        self.assertTrue(self.c.applySheet())
        after = self.data()
        self.roundtrip(before, after)
        self.assertFalse(self.c.state["sheetCanUndo"])
        self.assertTrue(self.c.beginSheet())
        self.assertTrue(self.c.sheetModel.pasteTsv("name\tp_nom\nThermal\t170\n"))
        self.assertTrue(self.c.applySheet())
        self.assertTrue(self.c.sheetHistory(False))
        self.assertEqual(self.data(), after)
        self.assertTrue(self.c.modelHistory(False))
        self.assertEqual(self.c.project.object("Generator", "Thermal")["attributes"]["p_nom"], 170)

    def test_busy_stale_and_pending_cancel_are_nonmutating(self):
        self.c.storeObject("Extra", '{}')
        self.c.updateSettingsDraft("pending", "USD", self.c.project.snapshots[0], 24, 60)
        before = self.data()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.c.modelHistory(False))
        self.assertEqual(self.data(), before)
        self.c.discardSettingsDraft()
        self.c.process = object()
        self.assertFalse(self.c.modelHistory(False))
        self.c.process = None
        self.c.project.name = "External mutation"
        self.assertFalse(self.c.modelHistory(False))
        self.assertEqual(self.c.project.name, "External mutation")

    def test_save_recovery_and_project_open_history_boundaries(self):
        self.c.enableRecovery(self.root / "recovery")
        before = self.data()
        self.c.storeObject("Extra", '{}')
        self.c.path = self.root / "model.sqlite"
        self.assertTrue(self.c.saveProject())
        saved = self.c.path.read_bytes()
        self.assertTrue(self.c.modelHistory(False))
        self.assertTrue(self.c.dirty)
        self.assertEqual(self.data(), before)
        self.assertEqual(self.c.path.read_bytes(), saved)
        self.assertTrue(self.c.flushRecovery())
        self.assertEqual(load_project(self.c.recovery_store.path).to_dict(), before)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard), patch.object(QFileDialog, "getOpenFileName", return_value=(str(self.c.path), "SQLite")):
            self.c.openProject()
        self.assertFalse(self.c.state["modelCanUndo"])
        self.assertFalse(self.c.state["modelCanRedo"])

    def test_frozen_queries_graph_and_files_survive_model_history(self):
        run = self.root / "runs" / "one"
        project, _ = overlay_fixture(run)
        self.c.project = project
        self.c._reset_draft()
        self.assertTrue(self.c.openRun(str(run)))
        self.assertTrue(self.c.queryResults("Line", ["L"], ["p0"], "", ""))
        self.c.pinQueryTab(self.c.workspace.active_id)
        self.assertTrue(self.c.loadNetworkRun(str(run)))
        graph, frame = deepcopy(self.c.networkState["topology"]), self.c._result_frame.copy()
        files = {str(p): p.read_bytes() for p in run.rglob("*") if p.is_file()}
        self.assertTrue(self.c.storeObject("Extra", '{}'))
        self.assertTrue(self.c.modelHistory(False))
        self.assertTrue(self.c.modelHistory(True))
        self.assertEqual(self.c.networkState["topology"], graph)
        self.assertTrue(self.c._result_frame.equals(frame))
        self.assertEqual({str(p): p.read_bytes() for p in run.rglob("*") if p.is_file()}, files)

    def test_stack_limits_noop_and_oversized_edit_policy(self):
        history = ModelHistory(limit=2, byte_limit=10000)
        for n in range(4):
            self.assertTrue(history.record(dict(x=n), dict(x=n+1), str(n)))
        self.assertEqual(len(history.undo), 2)
        entry = history.entry(dict(x=4))
        history.commit_step()
        self.assertTrue(history.record(entry["before"], entry["before"], "no-op"))
        self.assertEqual(len(history.redo), 1)
        self.assertFalse(history.record(dict(x=3), dict(x="x" * 20000), "too large"))
        self.assertEqual(history.undo + history.redo, [])
