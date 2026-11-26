"""Portable layouts and frozen-topology flow semantics, without a GUI renderer."""

from contextlib import closing
from copy import deepcopy
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
from energy_gui.demo import demo_project
from energy_gui.engine import build_network
from energy_gui.network_view import checked_layout, frozen_overlay, object_key, topology
from energy_gui.object_edits import delete_candidate, rename_candidate
from energy_gui.project import Project
from energy_gui.results import ResultsRepository
from energy_gui.storage import load_project, save_project
from PySide6.QtWidgets import QApplication, QMessageBox


def overlay_fixture(directory):
    directory = Path(directory)
    (directory / "tables").mkdir(parents=True)
    project = Project(name="Overlay reference")
    project.set_horizon("2026-01-01", 2, 60)
    for bus in ["A", "B", "Heat"]:
        project.upsert("Bus", bus, {"unit": "t/h"} if bus == "Heat" else {})
    project.upsert("Line", "L", {"bus0": "A", "bus1": "B", "s_nom": 10, "x": 0.1})
    project.upsert("Transformer", "T", {"bus0": "A", "bus1": "B", "s_nom": 1, "s_nom_extendable": True, "x": 0.1})
    project.upsert("Link", "C", {"bus0": "A", "bus1": "B", "bus2": "Heat", "bus7": "A", "p_nom": 10})
    save_project(project, directory / "inputs.sqlite")
    catalog = []
    for kind in ["Bus", "Line", "Transformer", "Link"]:
        rows = [{"name": r["name"], **r["attributes"]} for r in project.objects if r["component"] == kind]
        frame = pd.DataFrame(rows)
        if kind in {"Line", "Transformer"}:
            frame["s_nom_opt"] = 40 if kind == "Transformer" else 10
            frame["s_max_pu"] = 0.5
        file = kind + ".csv"
        frame.to_csv(directory / "tables" / file, index=False)
        catalog.append({"component": kind, "kind": "static", "file": file, "attribute": "static properties"})
    for kind, attr, name, values in [
        ("Line", "p0", "L", [4, -8]), ("Line", "p1", "L", [-4, 8]),
        ("Line", "s_max_pu", "L", [0.5, 1]),
        ("Transformer", "p0", "T", [5, 0]), ("Transformer", "p1", "T", [-4.9, 0]),
        ("Link", "p0", "C", [5, -5]), ("Link", "p1", "C", [-4, 4]), ("Link", "p2", "C", [-10, 10]),
    ]:
        file = kind + "_" + attr + ".csv"
        pd.DataFrame({"snapshot": project.snapshots, name: values}).to_csv(directory / "tables" / file, index=False)
        catalog.append({"component": kind, "kind": "time series", "attribute": attr, "file": file})
    (directory / "catalog.json").write_text(json.dumps(catalog))
    (directory / "run_config.json").write_text(json.dumps({"project_id": project.project_id, "status": "succeeded"}))
    return project, catalog


class NetworkViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        self.temp = tempfile.TemporaryDirectory(prefix="network_view_", dir=preferred)
        self.directory = Path(self.temp.name)
        self.run = self.directory / "runs" / "reference"
        self.project, self.catalog = overlay_fixture(self.run)
        self.controller = Controller()
        self.controller.project = deepcopy(self.project)
        self.controller.path = self.directory / "model.sqlite"
        self.controller._reset_draft()

    def tearDown(self):
        self.temp.cleanup()

    def layout(self, kind="Bus", name="A"):
        return {"positions": {object_key(kind, name): {"x": 420, "y": 200}},
                "zoom": 1.8, "panX": 50, "panY": 70, "width": 1200, "height": 800}

    def wire(self, graph, kind, name, port):
        return next(w for w in graph["wires"] if w["a"] == object_key(kind, name) and w["port"] == port)

    def test_layout_roundtrip_optional_metadata_and_old_reader_payload(self):
        self.assertTrue(self.controller.saveNetworkLayout(self.controller.networkState["viewKey"], self.layout()))
        reopened = load_project(self.controller.path)
        self.assertEqual(reopened.schematic_layouts["current"], self.layout())
        self.assertEqual(reopened.objects, self.project.objects)
        with closing(sqlite3.connect(self.controller.path)) as connection, connection:
            payload = json.loads(connection.execute("SELECT value FROM metadata WHERE key='project'").fetchone()[0])
            self.assertNotIn("schematic_layouts", payload)
            connection.execute("DELETE FROM metadata WHERE key='schematic_layouts'")
        self.assertEqual(load_project(self.controller.path).schematic_layouts, {})

    def test_layout_changes_do_not_change_any_built_model_inputs(self):
        project = demo_project()
        old = build_network(project)
        project.schematic_layouts["current"] = self.layout("Bus", "North")
        new = build_network(project)
        pd.testing.assert_frame_equal(old.snapshot_weightings, new.snapshot_weightings)
        for key in old.components.keys():
            pd.testing.assert_frame_equal(old.components[key].static, new.components[key].static)
            for attr in old.components[key].dynamic:
                pd.testing.assert_frame_equal(old.components[key].dynamic[attr], new.components[key].dynamic[attr])

    def test_malformed_layout_is_rejected_without_changing_saved_state(self):
        for layout in [self.layout() | {"zoom": float("nan")}, self.layout() | {"panX": -1},
                       self.layout() | {"width": 100001, "height": 8000},
                       self.layout() | {"positions": {object_key("Bus", "A"): {"x": True, "y": 0}}}]:
            self.assertFalse(self.controller.saveNetworkLayout(self.controller.networkState["viewKey"], layout))
        self.assertEqual(self.controller.project.schematic_layouts, {})
        self.assertFalse(self.controller.saveNetworkLayout("stale view", self.layout()))
        with self.assertRaises(ValueError):
            checked_layout({"positions": []}, set())

    def test_identity_edits_follow_only_live_layout_and_prune_deleted_positions(self):
        self.project.schematic_layouts = {"current": self.layout(), "run:reference": self.layout()}
        renamed, _ = rename_candidate(self.project, "Bus", "A", "Renamed")
        self.assertIn(object_key("Bus", "Renamed"), renamed.schematic_layouts["current"]["positions"])
        self.assertIn(object_key("Bus", "A"), renamed.schematic_layouts["run:reference"]["positions"])
        renamed.schematic_layouts["current"]["positions"][object_key("Link", "C")] = {"x": 400, "y": 300}
        deleted = delete_candidate(renamed, [{"component": "Link", "name": "C"}])
        self.assertNotIn(object_key("Link", "C"), deleted.schematic_layouts["current"]["positions"])

    def test_frozen_ports_reverse_signs_losses_and_time_varying_bound(self):
        repo = ResultsRepository(self.run, self.catalog)
        first = frozen_overlay(repo, self.project.snapshots[0])
        second = frozen_overlay(repo, self.project.snapshots[1])
        self.assertEqual(self.wire(first, "Line", "L", "bus0")["flow"], 4)
        self.assertEqual(self.wire(first, "Line", "L", "bus1")["flow"], -4)
        self.assertEqual(self.wire(second, "Line", "L", "bus0")["flow"], -8)
        self.assertEqual(self.wire(second, "Line", "L", "bus1")["flow"], 8)
        self.assertEqual(self.wire(first, "Line", "L", "bus0")["utilisation"], 80)
        self.assertEqual(self.wire(second, "Line", "L", "bus0")["utilisation"], 80)
        self.assertEqual(self.wire(first, "Transformer", "T", "bus1")["flow"], -4.9)
        self.assertEqual(self.wire(first, "Transformer", "T", "bus0")["utilisation"], 25)
        self.assertEqual(self.wire(second, "Transformer", "T", "bus0")["flow"], 0)

    def test_missing_outputs_unsupported_units_and_converter_percent_are_not_invented(self):
        graph = frozen_overlay(ResultsRepository(self.run, self.catalog), self.project.snapshots[0])
        missing = self.wire(graph, "Link", "C", "bus7")
        self.assertIsNone(missing["flow"])
        self.assertIn("Missing", missing["unavailable"])
        mass = self.wire(graph, "Link", "C", "bus2")
        self.assertIsNone(mass["flow"])
        self.assertIn("t/h", mass["unavailable"])
        self.assertIsNone(self.wire(graph, "Link", "C", "bus0")["utilisation"])
        (self.run / "tables" / "Line_p0.csv").unlink()
        graph = frozen_overlay(ResultsRepository(self.run, self.catalog), self.project.snapshots[0])
        self.assertIsNone(self.wire(graph, "Line", "L", "bus0")["flow"])

    def test_overlay_is_frozen_and_does_not_replace_results_repository_or_query_tabs(self):
        original_repo = self.controller.repository
        before = (self.run / "inputs.sqlite").read_bytes()
        self.assertTrue(self.controller.loadNetworkRun(str(self.run)))
        self.controller.project, _ = rename_candidate(self.controller.project, "Bus", "A", "New A")
        self.assertTrue(self.controller.setNetworkSnapshot(1))
        graph = self.controller.networkState["topology"]
        self.assertIn("A", [o["name"] for o in graph["objects"]])
        self.assertNotIn("New A", [o["name"] for o in graph["objects"]])
        self.assertIs(self.controller.repository, original_repo)
        self.assertEqual(self.controller.workspace.tabs, [])
        self.assertEqual((self.run / "inputs.sqlite").read_bytes(), before)
        self.controller.showLiveNetwork()
        self.assertIn("New A", [o["name"] for o in self.controller.networkState["topology"]["objects"]])

    def test_frozen_layout_fallback_uses_captured_inputs_not_live_coordinates(self):
        # A run without its own user-saved view starts from its frozen live
        # layout; editing today's layout must not change that historical view.
        self.project.schematic_layouts["current"] = self.layout()
        save_project(self.project, self.run / "inputs.sqlite")
        frozen_bytes = (self.run / "inputs.sqlite").read_bytes()
        self.controller.project.schematic_layouts["current"] = self.layout() | {"zoom": 0.7}
        self.controller.project.schematic_layouts["current"]["positions"][object_key("Bus", "A")]["x"] = 600
        self.assertTrue(self.controller.loadNetworkRun(str(self.run)))
        self.assertEqual(self.controller.networkState["layout"], self.layout())
        # An explicit per-run layout still takes precedence over the fallback.
        explicit = self.layout() | {"zoom": 0.1}
        self.assertTrue(self.controller.saveNetworkLayout(self.controller.networkState["viewKey"], explicit))
        self.assertEqual(self.controller.networkState["layout"], explicit)
        self.assertEqual((self.run / "inputs.sqlite").read_bytes(), frozen_bytes)

    def test_failed_foreign_and_bad_snapshot_selections_preserve_prior_view(self):
        self.assertTrue(self.controller.loadNetworkRun(str(self.run)))
        before = self.controller.networkState
        self.assertFalse(self.controller.setNetworkSnapshot(-1))
        self.assertFalse(self.controller.setNetworkSnapshot(99))
        config = self.run / "run_config.json"
        for metadata in [{"status": "failed", "project_id": self.project.project_id}, {"status": "succeeded", "project_id": "foreign"}]:
            config.write_text(json.dumps(metadata))
            self.assertFalse(self.controller.loadNetworkRun(str(self.run)))
            self.assertEqual(self.controller.networkState["topology"], before["topology"])
        self.assertEqual(self.controller.networkState["snapshotIndex"], 0)

    def test_historical_inspection_refuses_changed_record_and_preserves_draft(self):
        self.assertTrue(self.controller.loadNetworkRun(str(self.run)))
        self.controller.project.object("Line", "L")["attributes"]["s_nom"] = 99
        self.assertFalse(self.controller.inspectNetworkObject("Line", "L"))
        self.controller.updateSettingsDraft("Draft", "INR", self.project.snapshots[0], 2, 60)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.controller.inspectNetworkObject("Bus", "A"))
        self.assertTrue(self.controller.helperState["settingsDirty"])

    def test_layouts_are_separate_per_view_and_do_not_rewrite_frozen_inputs(self):
        self.assertTrue(self.controller.saveNetworkLayout(self.controller.networkState["viewKey"], self.layout()))
        before = (self.run / "inputs.sqlite").read_bytes()
        self.assertTrue(self.controller.loadNetworkRun(str(self.run)))
        alternate = self.layout() | {"zoom": 2.5}
        self.assertTrue(self.controller.saveNetworkLayout(self.controller.networkState["viewKey"], alternate))
        self.assertEqual(self.controller.project.schematic_layouts["current"]["zoom"], 1.8)
        self.assertEqual(self.controller.project.schematic_layouts["run:reference"]["zoom"], 2.5)
        self.assertEqual((self.run / "inputs.sqlite").read_bytes(), before)

    def test_spreadsheet_history_and_staged_edits_preserve_new_layout_metadata(self):
        self.controller.loadDemo()
        self.controller.path = self.directory / "demo.sqlite"
        self.controller.selectType("Generator")
        self.assertTrue(self.controller.sheetModel.pasteTsv("name\tp_nom\nThermal\t160\n"))
        self.assertTrue(self.controller.applySheet())
        self.assertTrue(self.controller.saveNetworkLayout(self.controller.networkState["viewKey"], self.layout("Bus", "North")))
        self.assertTrue(self.controller.state["sheetCanUndo"])
        self.assertTrue(self.controller.sheetHistory(False))
        self.assertIn("current", self.controller.project.schematic_layouts)
        self.assertTrue(self.controller.sheetHistory(True))
        self.assertIn("current", self.controller.project.schematic_layouts)
        self.assertTrue(self.controller.sheetModel.pasteTsv("name\tp_nom\nThermal\t170\n"))
        self.controller.project.schematic_layouts["current"]["zoom"] = 2
        self.assertTrue(self.controller.applySheet())
        self.assertEqual(self.controller.project.schematic_layouts["current"]["zoom"], 2)

    def test_missing_object_output_never_uses_schema_or_static_zero(self):
        frame = pd.read_csv(self.run / "tables" / "Line.csv")
        frame["p0"] = 0
        frame.to_csv(self.run / "tables" / "Line.csv", index=False)
        pd.DataFrame({"snapshot": self.project.snapshots, "not_defined": [0, 0]}).to_csv(self.run / "tables" / "Line_p0.csv", index=False)
        graph = frozen_overlay(ResultsRepository(self.run, self.catalog), self.project.snapshots[0])
        self.assertIsNone(self.wire(graph, "Line", "L", "bus0")["flow"])

    def test_zero_or_missing_rating_has_no_utilisation_percentage(self):
        frame = pd.read_csv(self.run / "tables" / "Line.csv")
        for rating in [0, 1e-320]:
            frame["s_nom"] = rating
            frame.to_csv(self.run / "tables" / "Line.csv", index=False)
            graph = frozen_overlay(ResultsRepository(self.run, self.catalog), self.project.snapshots[0])
            self.assertIsNone(self.wire(graph, "Line", "L", "bus0")["utilisation"])

    def test_bad_optional_metadata_does_not_prevent_model_opening(self):
        save_project(self.project, self.controller.path)
        with closing(sqlite3.connect(self.controller.path)) as connection, connection:
            connection.execute("UPDATE metadata SET value='not-json' WHERE key='schematic_layouts'")
        self.assertEqual(load_project(self.controller.path).schematic_layouts, {})
        self.controller.project.schematic_layouts["current"] = {"positions": {"bad": []}}
        self.assertEqual(self.controller.networkState["layout"], {})

    def test_save_layout_obeys_busy_and_pending_draft_guards(self):
        self.controller.updateSettingsDraft("Pending", "INR", self.project.snapshots[0], 2, 60)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.controller.saveNetworkLayout(self.controller.networkState["viewKey"], self.layout()))
        self.assertEqual(self.controller.project.schematic_layouts, {})
        self.controller.process = object()
        self.assertFalse(self.controller.saveNetworkLayout(self.controller.networkState["viewKey"], self.layout()))
        self.controller.process = None
