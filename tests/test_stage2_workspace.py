import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from energy_gui.project import Project
from energy_gui.storage import load_project, save_project
from energy_gui.results import query_charts
from energy_gui.workspace import QueryWorkspace
from energy_gui.controller import Controller
from PySide6.QtWidgets import QApplication, QMessageBox


class WorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        self.temp = tempfile.TemporaryDirectory(prefix="stage2_workspace_", dir=preferred)
        self.directory = Path(self.temp.name)
        self.controller = Controller()
        self.controller.path = self.directory / "project.sqlite"
        self.controller.project.set_horizon("2026-01-01", 2, 60)
        save_project(self.controller.project, self.controller.path)
        self.notices = []
        self.controller.notice.connect(self.notices.append)
        self.first = self.make_run("first", [10., 20.])
        self.second = self.make_run("second", [30., 40.])

    def tearDown(self):
        self.controller.workspace.clear()
        self.temp.cleanup()

    def make_run(self, name, values):
        run = self.directory / "runs" / name
        (run / "tables").mkdir(parents=True)
        # The tiny table fixtures must have matching definitions in frozen inputs.
        frozen = Project(**self.controller.project.to_dict())
        frozen.upsert("Generator", "G", {"p_nom": 50})
        save_project(frozen, run / "inputs.sqlite")
        meta = {"project_id": self.controller.project.project_id, "status": "succeeded", "objective": sum(values), "created_utc": "2026-01-01T00:00:00Z"}
        (run / "run_config.json").write_text(json.dumps(meta))
        pd.DataFrame({"name": ["G"], "p_nom": [50.], "p_nom_opt": [50.]}).to_csv(run / "tables" / "static.csv", index=False)
        pd.DataFrame({"snapshot": self.controller.project.snapshots, "G": values}).to_csv(run / "tables" / "p.csv", index=False)
        catalog = [{"component": "Generator", "attribute": "static properties", "kind": "static", "file": "static.csv"},
                   {"component": "Generator", "attribute": "p", "kind": "time series", "file": "p.csv"}]
        (run / "catalog.json").write_text(json.dumps(catalog))
        return run

    def query(self, properties=None):
        self.assertTrue(self.controller.queryResults("Generator", ["G"], properties or ["p"], "", ""), self.notices)
        return self.controller.workspace.active

    def test_preview_reused_and_pinned_values_preserved_across_runs(self):
        self.controller.openRun(str(self.first))
        first = self.query()
        self.query(["p_nom_opt"])
        self.assertEqual(len(self.controller.workspace.tabs), 1)
        self.assertEqual(self.controller.workspace.active.id, first.id)
        pinned = self.query()
        self.controller.pinQueryTab(pinned.id)
        frame = pinned.frame.copy(deep=True)
        self.controller.openRun(str(self.second))
        second = self.query()
        self.assertNotEqual(second.id, pinned.id)
        self.assertEqual(len(self.controller.workspace.tabs), 2)
        pd.testing.assert_frame_equal(pinned.frame, frame)
        self.controller.selectQueryTab(pinned.id)
        self.assertEqual(self.controller._result_frame.p.tolist(), [10, 20])
        self.assertEqual(self.controller.run_directory, self.first)
        self.assertEqual(self.controller.state["queryObjective"], "30.0")

    def test_chart_settings_per_tab_and_restrictions(self):
        self.controller.openRun(str(self.first))
        first = self.query()
        self.assertTrue(self.controller.setChartType("p", "stacked area"))
        self.controller.pinQueryTab(first.id)
        second = self.query(["p_nom_opt"])
        self.assertEqual(self.controller.state["charts"][0]["kind"], "bar")
        self.assertFalse(self.controller.setChartType("p_nom_opt", "line"))
        self.assertTrue(self.controller.setChartType("p_nom_opt", "dot"))
        self.controller.selectQueryTab(first.id)
        self.assertEqual(self.controller.state["charts"][0]["kind"], "stacked area")
        self.controller.selectQueryTab(second.id)
        self.assertEqual(self.controller.state["charts"][0]["kind"], "dot")

    def test_network_ports_unique_identities_and_atomic_draft_guard(self):
        project = self.controller.project
        project.upsert("Bus", "same", {})
        project.upsert("Bus", "B", {})
        project.upsert("Bus", "C", {})
        project.upsert("Generator", "same", {"bus": "same", "p_nom": 10})
        project.upsert("Link", "multi", {"bus2": "C", "bus1": "B", "bus0": "same"})
        project.upsert("Carrier", "fuel", {})
        topology = self.controller._topology()
        self.assertEqual(len({o["key"] for o in topology["objects"]}), len(project.objects)-1)
        link = next(o for o in topology["objects"] if o["kind"] == "Link")
        self.assertEqual([json.loads(key)[1] for key in link["buses"]], ["same", "B", "C"])
        self.assertEqual([w["port"] for w in topology["wires"] if w["a"] == link["key"]], ["bus0", "bus1", "bus2"])
        self.assertFalse(any(o["kind"] == "Carrier" for o in topology["objects"]))
        self.controller.selectObject("same")
        self.controller.updateDraft("same", '{"v_nom":220}')
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.controller.inspectNetworkObject("Generator", "same"))
        self.assertEqual((self.controller.component, self.controller.selected), ("Bus", "same"))
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(self.controller.inspectNetworkObject("Generator", "same"))
        self.assertEqual((self.controller.component, self.controller.selected), ("Generator", "same"))
        self.assertFalse(self.controller.inspectNetworkObject("Bus", "missing"))

    def test_network_carrier_tags_use_own_reference_and_defaults_without_mutation(self):
        project = self.controller.project
        project.upsert("Carrier", "solar", {})
        project.upsert("Carrier", "unused", {})
        project.upsert("Bus", "A", {})
        project.upsert("Bus", "B", {"carrier": "heat"})
        project.upsert("Generator", "PV", {"bus": "A", "carrier": "solar"})
        project.upsert("Generator", "Custom", {"bus": "A", "carrier": "unregistered technology"})
        project.upsert("Load", "Demand", {"bus": "A"})
        project.upsert("Link", "Converter", {"bus0": "A", "bus1": "B", "carrier": "heat pump"})
        before = project.to_dict()
        topology = self.controller._topology()
        tags = {(o["kind"], o["name"]): o["carrier"] for o in topology["objects"]}
        self.assertEqual(tags, {
            ("Bus", "A"): "AC", ("Bus", "B"): "heat", ("Generator", "PV"): "solar",
            ("Generator", "Custom"): "unregistered technology", ("Load", "Demand"): "",
            ("Link", "Converter"): "heat pump",
        })
        self.assertEqual(len(topology["wires"]), 5, "Carrier references must never add electrical wires.")
        self.assertTrue(all(json.loads(w["a"])[0] != "Carrier" for w in topology["wires"]))
        self.assertEqual(project.to_dict(), before)
        self.assertTrue(self.controller.inspectNetworkObject("Carrier", "unused"))
        self.assertEqual((self.controller.component, self.controller.selected), ("Carrier", "unused"))

    def test_close_frees_memory_not_run_files_and_new_session_empty(self):
        self.controller.openRun(str(self.first))
        tab = self.query()
        self.controller.pinQueryTab(tab.id)
        self.controller.closeQueryTab(tab.id)
        self.assertEqual(self.controller.workspace.tabs, [])
        self.assertTrue((self.first / "tables" / "p.csv").is_file())
        self.assertEqual(self.controller.resultModel.rowCount(), 0)
        self.assertEqual(Controller().workspace.tabs, [])

    def test_unpin_preserves_other_preview_and_keeps_one_preview(self):
        self.controller.openRun(str(self.first))
        a = self.query()
        self.controller.pinQueryTab(a.id)
        b = self.query(["p_nom_opt"])
        self.controller.pinQueryTab(a.id)
        self.assertFalse(a.pinned)
        self.assertTrue(b.pinned)
        self.assertEqual(sum(not t.pinned for t in self.controller.workspace.tabs), 1)

    def test_previous_run_reopens_without_invoking_solver(self):
        reopened = Controller()
        reopened.project = load_project(self.controller.path)
        reopened.path = self.controller.path
        with patch("energy_gui.controller.prepare_run") as start:
            self.assertTrue(reopened.openRun(str(self.first)))
            self.assertTrue(reopened.queryResults("Generator", ["G"], ["p"], "", ""))
            start.assert_not_called()
        self.assertEqual(reopened._result_frame.p.tolist(), [10, 20])
        self.assertEqual(len(reopened.state["runs"]), 2)

    def test_legacy_input_dashboard_and_comparison_rejected_without_replacing_pins(self):
        self.assertTrue(self.controller.openRun(str(self.first)))
        tab = self.query()
        self.controller.pinQueryTab(tab.id)
        saved = {"title": "Old dashboard", "active": 0, "cards": [
            {"run": "first", "criteria": {**tab.criteria, "properties": ["p", "p_nom"]}},
        ]}
        self.controller.project.analysis_workspace.append(saved)
        before = json.dumps(saved)
        self.assertFalse(self.controller.restoreAnalysis(0))
        self.assertIn("p_nom", self.notices[-1])
        self.assertIs(self.controller.workspace.active, tab)
        self.assertTrue(tab.pinned)
        self.assertEqual(json.dumps(saved), before)
        from energy_gui.analysis import compare_query
        with self.assertRaisesRegex(ValueError, "p_nom"):
            compare_query(self.controller.project, self.first, self.second, saved["cards"][0]["criteria"])

    def test_result_object_scope_follows_frozen_run_and_pinned_tab_not_live_model(self):
        self.controller.openRun(str(self.first))
        pinned = self.query()
        self.controller.pinQueryTab(pinned.id)
        self.controller.project.upsert("Generator", "current only", {"p_nom": 60})
        self.controller.changed.emit()
        self.assertEqual(self.controller.queryOptions["categories"][0]["objects"], ["G"])
        self.assertFalse(self.controller.queryResults("Generator", ["current only"], ["p"], "", ""))

        # Same project, later frozen model: G still occurs in raw tables, but
        # only the newly defined object belongs to this run's query scope.
        save_project(self.controller.project, self.second / "inputs.sqlite")
        pd.DataFrame({"name": ["G", "current only"], "p_nom": [50., 60.]}).to_csv(
            self.second / "tables" / "static.csv", index=False,
        )
        pd.DataFrame({"snapshot": self.controller.project.snapshots, "G": [30., 40.], "current only": [3., 4.]}).to_csv(
            self.second / "tables" / "p.csv", index=False,
        )
        self.assertTrue(self.controller.openRun(str(self.second)))
        self.assertEqual(self.controller.queryOptions["categories"][0]["objects"], ["current only"])
        self.assertFalse(self.controller.queryResults("Generator", ["G"], ["p"], "", ""))
        self.assertTrue(self.controller.queryResults("Generator", ["current only"], ["p"], "", ""))
        self.assertEqual(self.controller._result_frame.p.tolist(), [3., 4.])
        self.controller.selectQueryTab(pinned.id)
        self.assertEqual(self.controller.queryOptions["categories"][0]["objects"], ["G"])
        self.assertEqual(self.controller._result_frame.p.tolist(), [10., 20.])
        self.assertEqual(self.controller.state["charts"][0]["series"][0]["name"], "G")

    def test_foreign_run_rejected_without_changing_current_source(self):
        self.controller.openRun(str(self.first))
        config = self.second / "run_config.json"
        meta = json.loads(config.read_text())
        meta["project_id"] = "another project"
        config.write_text(json.dumps(meta))
        self.assertFalse(self.controller.openRun(str(self.second)))
        self.assertEqual(self.controller.run_directory, self.first)

    def test_project_close_warns_about_pinned_tabs(self):
        self.controller.openRun(str(self.first))
        self.controller.pinQueryTab(self.query().id)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel) as prompt:
            self.assertFalse(self.controller.canClose())
            self.assertIn("pinned", prompt.call_args.args[2])
        self.assertEqual(len(self.controller.workspace.tabs), 1)

    def test_draft_apply_discard_cancel_and_invalid_apply(self):
        self.controller.updateDraft("A", '{"v_nom":220}')
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.controller.selectType("Generator")
        self.assertEqual(self.controller.component, "Bus")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save):
            self.assertTrue(self.controller.resolveDraft())
        self.assertEqual(self.controller.project.object("Bus", "A")["attributes"]["v_nom"], 220)
        self.controller.updateDraft("A", "invalid JSON")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save):
            self.assertFalse(self.controller.resolveDraft())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(self.controller.resolveDraft())
        self.assertFalse(self.controller._has_draft())

    def test_save_and_run_cancel_if_draft_not_resolved(self):
        self.controller.updateDraft("A", '{"v_nom":220}')
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel), patch("energy_gui.controller.prepare_run") as prepare:
            self.assertFalse(self.controller.saveProject())
            self.controller.startRun("should-not-start", "none")
            prepare.assert_not_called()

    def test_bus_property_helper_has_units_and_reference_metadata(self):
        self.controller.selectType("Generator")
        self.assertTrue(self.controller.propertyInfo("bus")["busReference"])
        self.assertEqual(self.controller.propertyInfo("p_nom")["unit"], "MW")
        self.assertTrue(self.controller.propertyInfo("committable")["boolean"])

    def test_negative_missing_and_cost_data_cannot_be_stacked(self):
        for values, unit in [([-1., 2.], "MW"), ([float("nan"), 2.], "MW"), ([1., 2.], "currency/MWh")]:
            frame = pd.DataFrame({"snapshot": pd.date_range("2026-01-01", periods=2, freq="h"), "object": ["G", "G"], "value": values})
            with self.assertRaises(ValueError):
                query_charts(frame, [{"name": "value", "unit": unit}], True, {"value": "stacked area"})

    def test_failed_run_retains_pinned_data_but_cannot_be_queried(self):
        self.controller.openRun(str(self.first))
        first = self.query()
        self.controller.pinQueryTab(first.id)
        config = self.second / "run_config.json"
        meta = json.loads(config.read_text())
        meta.update(status="failed", error="infeasible")
        config.write_text(json.dumps(meta))
        self.assertTrue(self.controller.openRun(str(self.second)))
        self.assertEqual(self.controller._result_frame.p.tolist(), [10, 20])
        self.assertFalse(self.controller.queryResults("Generator", ["G"], ["p"], "", ""))
        self.assertEqual(len(self.controller.workspace.tabs), 1)

    def test_closing_background_tab_does_not_switch_query_source(self):
        self.controller.openRun(str(self.first))
        first = self.query()
        self.controller.pinQueryTab(first.id)
        self.controller.openRun(str(self.second))
        self.query()
        self.controller.closeQueryTab(first.id)
        self.assertEqual(self.controller.run_directory, self.second)
        self.assertEqual(self.controller._result_frame.p.tolist(), [30, 40])


if __name__ == "__main__":
    unittest.main()
