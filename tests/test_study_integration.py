"""Real controller/UI lifecycle regression for the integrated 3M–4B increment."""

from contextlib import closing
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from energy_gui.controller import Controller
from energy_gui.project import Project
from energy_gui.storage import load_project, save_project
from energy_gui.reporting import write_report
from PySide6.QtCore import QEventLoop, QObject, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog


def reference_project():
    project = Project(currency="USD")
    project.set_horizon("2030-01-01", 2, 60)
    project.upsert("Carrier", "AC", {})
    project.upsert("Carrier", "gas", {"co2_emissions": 0.2})
    project.upsert("Bus", "B", {})
    project.upsert("Generator", "G", {"bus": "B", "carrier": "gas", "p_nom": 100, "marginal_cost": 10})
    project.upsert("Load", "D", {"bus": "B", "p_set": 75})
    return project


class StudyIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="study_integration_", dir=Path(os.environ["LOCALAPPDATA"])/"Temp"/"opencode")
        self.root = Path(self.temp.name)
        self.c = Controller()
        self.c.project = reference_project()
        self.c.path = self.root / "project.sqlite"
        self.c._reset_helpers()
        self.c._reset_draft()
        self.notices = []
        self.c.notice.connect(self.notices.append)
        save_project(self.c.project, self.c.path)

    def tearDown(self):
        if self.c.process:
            self.c.cancelRun()
            self.c.process.waitForFinished(10000)
            self.app.processEvents()
        self.c._recovery_timer.stop()
        self.temp.cleanup()

    def scenarios(self):
        return [dict(id="base", name="Base", changes=[]),
                dict(id="large", name="Too much demand", changes=[dict(component="Load", name="D", attribute="p_set", operation="scale", value=2)]),
                dict(id="low", name="Half demand", changes=[dict(component="Load", name="D", attribute="p_set", operation="scale", value=0.5)])]

    def wait_batch(self):
        loop = QEventLoop()
        timer = QTimer(loop)
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        finished = lambda: loop.quit() if not self.c._batch_active else None
        self.c.extensionsChanged.connect(finished)
        timer.start(180000)
        if self.c._batch_active:
            loop.exec()
        timer.stop()
        self.c.extensionsChanged.disconnect(finished)
        self.assertFalse(self.c._batch_active, self.c.messages)
        self.assertIsNone(self.c.process)

    def test_scenario_metadata_roundtrip_and_model_history_independence(self):
        self.assertTrue(self.c.applyScenarios(json.dumps(self.scenarios())))
        self.assertTrue(self.c.saveProject())
        with closing(sqlite3.connect(self.c.path)) as connection:
            core = json.loads(connection.execute("select value from metadata where key='project'").fetchone()[0])
            self.assertNotIn("scenario_library", core)
        self.assertEqual(load_project(self.c.path).scenario_library, self.c.project.scenario_library)
        text = self.c.modelingControls("Generator", "G")
        data = json.loads(text)
        data["p_nom"] = 120
        self.assertTrue(self.c.applyModelingControls("Generator", "G", json.dumps(data)), self.notices)
        definitions = deepcopy(self.c.project.scenario_library)
        self.assertTrue(self.c.modelHistory(False))
        self.assertEqual(self.c.project.scenario_library, definitions)
        self.assertEqual(self.c.project.object("Generator", "G")["attributes"]["p_nom"], 100)

    def test_model_controls_invalid_unknown_and_busy_are_atomic(self):
        before = self.c.project.to_dict()
        self.assertFalse(self.c.applyModelingControls("Generator", "G", '{"bus":"other"}'))
        self.assertFalse(self.c.applyModelingControls("Generator", "G", '{"p_nom":-1}'))
        self.c._batch_active = True
        self.assertFalse(self.c.applyScenarios("[]"))
        self.assertFalse(self.c.saveProject())
        self.assertFalse(self.c._can_replace())
        self.assertFalse(self.c.applyModelingControls("Generator", "G", '{"p_nom":120}'))
        self.c._batch_active = False
        self.assertEqual(before, self.c.project.to_dict())

    def test_diagnostics_are_read_only_and_no_solution_claim(self):
        before = self.c.project.to_dict()
        result = json.loads(self.c.modelDiagnostics())
        self.assertIsInstance(result, dict)
        self.assertEqual(before, self.c.project.to_dict())
        self.assertIn("Load a run", self.c.runFailureAdvice())

    def test_real_batch_continues_after_infeasibility_and_preserves_base(self):
        self.assertTrue(self.c.applyScenarios(json.dumps(self.scenarios())))
        before = self.c.project.to_dict()
        self.assertTrue(self.c.startScenarioBatch("none"), self.notices)
        self.assertTrue(self.c.state["busy"])
        self.wait_batch()
        rows = self.c.studyState["batchRows"]
        self.assertEqual([r["status"] for r in rows], ["succeeded", "failed", "succeeded"])
        self.assertAlmostEqual(float(rows[0]["objective"]), 1500)
        self.assertAlmostEqual(float(rows[2]["objective"]), 750)
        self.assertEqual(self.c.project.to_dict(), before)
        self.assertEqual(load_project(self.c.path).to_dict(), before)
        self.assertTrue(self.c.queryResults("Generator", ["G"], ["p"], "", ""))
        self.assertEqual(self.c.workspace.active.frame["p"].tolist(), [37.5, 37.5])
        self.assertTrue(self.c.analyzeQuery("energy", "object", "generators"), self.notices)
        self.assertEqual(self.c.studyState["analyticsRows"], 3)

    def test_cancel_batch_marks_waiting_runs_and_releases_lifecycle(self):
        self.assertTrue(self.c.applyScenarios(json.dumps(self.scenarios())))
        self.assertTrue(self.c.startScenarioBatch("none"))
        self.c.cancelRun()
        self.wait_batch()
        self.assertEqual([r["status"] for r in self.c.studyState["batchRows"]], ["cancelled"] * 3)
        self.assertTrue(self.c.saveProject())
        for path in (self.root / "runs").glob("*/metadata/run_config.json"):
            self.assertEqual(json.loads(path.read_text())["status"], "cancelled")

    def test_analytics_capture_export_configuration_and_frozen_guard(self):
        from test_network_view import overlay_fixture
        run = self.root / "runs" / "reference"
        project, _ = overlay_fixture(run)
        self.c.project = project
        self.c._reset_helpers()
        self.c._reset_draft()
        self.assertTrue(self.c.openRun(str(run)))
        self.assertTrue(self.c.queryResults("Line", ["L"], ["p0"], "", ""))
        self.assertTrue(self.c.analyzeQuery("energy", "object", "generators"), self.notices)
        captured = self.c._analytics["frame"].copy(deep=True)
        self.c.project.name = "Edited after computation"
        self.assertTrue(self.c.queryResults("Line", ["L"], ["p1"], "", ""))
        self.assertTrue(captured.equals(self.c._analytics["frame"]))
        destination = self.root / "analysis.html"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(destination), "HTML")):
            self.assertTrue(self.c.exportStudyResult("report", "<study>", 1, False), self.notices)
        text = destination.read_text(encoding="utf-8")
        self.assertIn("&lt;study&gt;", text)
        self.assertNotIn("<svg", text)
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(run / "inputs.sqlite"), "HTML")):
            self.assertFalse(self.c.exportStudyResult("report", "Study", 1, True))

    def test_weighted_duration_svg_uses_numeric_horizontal_spacing(self):
        from energy_gui.reporting import chart_svg
        chart = dict(title="Duration", unit="MW", kind="line", labels=["0 h", "4 h"],
                     x_label="Cumulative hours", series=[dict(name="G", values=[4, 4, -8, -8],
                                                               x_values=[0, 1, 1, 4])])
        svg = chart_svg([chart])
        self.assertIn("330.00,70.00 330.00,280.00", svg)
        self.assertIn("Cumulative hours", svg)
        chart["series"][0]["x_values"] = [0, 1]
        with self.assertRaises(ValueError):
            chart_svg([chart])

    def test_comparison_analytics_retains_original_source_after_query_switch(self):
        import shutil
        from test_network_view import overlay_fixture
        left, right = self.root / "runs" / "left", self.root / "runs" / "right"
        project, _ = overlay_fixture(left)
        shutil.copytree(left, right)
        self.c.project = project
        self.c._reset_helpers(); self.c._reset_draft()
        self.assertTrue(self.c.openRun(str(left)))
        self.assertTrue(self.c.queryResults("Line", ["L"], ["p0"], "", ""))
        self.assertNotIn("unavailable", self.c.compareRuns("left", "right"))
        self.assertTrue(self.c.openRun(str(right)))
        self.assertTrue(self.c.queryResults("Line", ["L"], ["p1"], "", ""))
        self.assertTrue(self.c.analyzeQuery("comparison", "object", "generators"), self.notices)
        self.assertEqual(Path(self.c._analytics["run_path"]), left)
        self.assertEqual(self.c._analytics["criteria"]["query"]["properties"], ["p0"])


class ExtendedQmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_qml_controls as helpers
        helpers.QmlControlsTests.setUpClass()

    def setUp(self):
        import test_qml_controls as helpers
        self.fixture = helpers.QmlControlsTests("runTest")
        self.fixture.setUp()
        self.c, self.root = self.fixture.controller, self.fixture.root

    def tearDown(self):
        self.fixture.tearDown()

    def test_extended_dialog_real_tabs_and_model_controls_in_both_themes(self):
        self.c.loadDemo()
        self.root.resize(1140, 760)
        self.root.openExtendedTools()
        from PySide6.QtTest import QTest
        QTest.qWait(80)
        for mode in ["Light", "Dark"]:
            self.fixture.appearance.setMode(mode)
            for index in range(4):
                self.fixture.study_click("extensionTab" + str(index))
                self.assertEqual(self.root.findChild(QObject, "extensionSections").property("currentIndex"), index)
        self.fixture.study_click("extensionTab1")
        self.root.findChild(QObject, "controlName").setProperty("text", "Thermal")
        self.fixture.study_click("loadControlsButton")
        editor = self.root.findChild(QObject, "modelingControlsEditor")
        data = json.loads(editor.property("text"))
        data["p_nom"] = 170
        editor.setProperty("text", json.dumps(data))
        self.fixture.study_click("applyControlsButton")
        self.assertEqual(self.c.project.object("Generator", "Thermal")["attributes"]["p_nom"], 170)
        self.root.findChild(QObject, "extendedTools").close()
        self.assertTrue(self.c.modelHistory(False))
        self.assertEqual(self.fixture.warnings, [])

    def test_scenario_and_diagnostic_ui_buttons(self):
        self.c.loadDemo()
        self.root.openExtendedTools()
        from PySide6.QtTest import QTest
        QTest.qWait(80)
        editor = self.root.findChild(QObject, "scenarioEditor")
        editor.setProperty("text", '[{"id":"base","name":"Base","changes":[]}]')
        self.fixture.study_click("applyScenariosButton")
        self.assertEqual(len(self.c.project.scenario_library), 1)
        self.fixture.study_click("extensionTab2")
        self.fixture.study_click("modelDiagnosticsButton")
        text = self.root.findChild(QObject, "diagnosticsReadout").property("text")
        self.assertIn("Errors (", text)
        self.assertIn("Checks (", text)
        self.root.findChild(QObject, "extendedTools").close()
        self.assertEqual(self.fixture.warnings, [])

    def test_analytics_compute_and_numeric_duration_chart_in_real_qml(self):
        from test_network_view import overlay_fixture
        from PySide6.QtTest import QTest
        run = Path(self.fixture.temp.name) / "runs" / "analytics"
        project, _ = overlay_fixture(run)
        project.advanced_inputs = {"weights": [dict(objective=1, stores=1, generators=1),
                                               dict(objective=1, stores=3, generators=3)]}
        save_project(project, run / "inputs.sqlite")
        self.c.project = project
        self.c.path = Path(self.fixture.temp.name) / "project.sqlite"
        self.c._reset_helpers(); self.c._reset_draft()
        self.assertTrue(self.c.openRun(str(run)))
        self.assertTrue(self.c.queryResults("Line", ["L"], ["p0"], "", ""))
        self.root.openExtendedTools(); QTest.qWait(80)
        self.fixture.study_click("extensionTab3")
        self.root.findChild(QObject, "analyticMode").setProperty("currentIndex", 1)
        self.fixture.study_click("computeAnalyticsButton")
        charts = self.c.studyState["analyticsCharts"]
        self.assertEqual(charts[0]["series"][0]["x_values"], [0, 1, 1, 4])
        self.assertIn("cumulative_hours", self.root.findChild(QObject, "analyticsReadout").property("text"))
        plot = self.fixture.visual_item("analyticsPlot-0")
        self.assertLessEqual(plot.width(), self.root.findChild(QObject, "analyticsScroll").property("availableWidth"))
        self.assertFalse(self.root.grabWindow().isNull())
        self.root.findChild(QObject, "extendedTools").close()
        self.assertEqual(self.fixture.warnings, [])
