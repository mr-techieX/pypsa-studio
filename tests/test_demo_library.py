"""All selectable use cases are reproducible, valid, persisted and solvable."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from energy_gui.controller import Controller
from energy_gui.demo_library import DEMO_SPECS, make_demo, pglib_data
from energy_gui.engine import execute_run, prepare_run
from energy_gui.network_view import checked_layout, topology
from energy_gui.storage import load_project, save_project
from energy_gui.study_validation import validate_study
from PySide6.QtWidgets import QApplication, QMessageBox


class DemoLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_every_case_is_deterministic_and_has_documented_use_case(self):
        self.assertEqual([s["buses"] for s in DEMO_SPECS], [2, 3, 6, 10, 14, 14, 20])
        for spec in DEMO_SPECS:
            with self.subTest(case=spec["id"]):
                first, second = make_demo(spec["id"]), make_demo(spec["id"])
                self.assertNotEqual(first.project_id, second.project_id)
                a, b = first.to_dict(), second.to_dict()
                a.pop("project_id"); b.pop("project_id")
                self.assertEqual(a, b)
                self.assertEqual(first.validate(), [])
                self.assertEqual(sum(r["component"] == "Bus" for r in first.objects), spec["buses"])
                self.assertEqual(len(first.snapshots), spec["hours"])
                self.assertTrue(spec["summary"] and spec["expected"] and spec["assumptions"])
                self.assertEqual(first.demo_info["id"], spec["id"])
                if first.schematic_layouts:
                    checked_layout(first.schematic_layouts["current"], {o["key"] for o in topology(first)["objects"]})

    def test_pglib_attribution_and_dc_assumptions_are_kept_with_model(self):
        project = make_demo("pglib14")
        source = project.demo_info["provenance"]
        self.assertEqual(source["license"], "CC BY 4.0")
        self.assertIn("Richard D. Christie", source["attribution"])
        self.assertIn("not an ac", source["changes"].lower())
        self.assertEqual(sum(pglib_data()["load_mw"]), 259)

    def test_invalid_and_cancelled_selection_does_not_replace_project(self):
        controller = Controller()
        controller.loadDemo()
        before = controller.project.to_dict()
        self.assertFalse(controller.loadDemoModel("unknown"))
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(controller.loadDemoModel("regional20"))
        self.assertEqual(controller.project.to_dict(), before)
        self.assertTrue(controller.dirty)

    def test_pending_drafts_block_model_choice_and_success_clears_old_context(self):
        controller = Controller()
        controller.loadDemo()
        controller.updateSettingsDraft("Pending", "INR", controller.project.snapshots[0], 24, 60)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(controller.loadDemoModel("campus6"))
        self.assertTrue(controller.helperState["settingsDirty"])
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(controller.loadDemoModel("campus6"))
        self.assertIsNone(controller.path)
        self.assertEqual(controller.project.demo_info["id"], "campus6")
        self.assertFalse(controller.helperState["settingsDirty"])
        self.assertFalse(controller.networkState["frozen"])
        self.assertEqual(controller.workspace.tabs, [])

    def test_all_seven_cases_solve_and_pass_independent_checks(self):
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        with tempfile.TemporaryDirectory(prefix="demo_acceptance_", dir=preferred) as tmp:
            for spec in DEMO_SPECS:
                with self.subTest(case=spec["id"]):
                    project = make_demo(spec["id"])
                    path = Path(tmp)/spec["id"]/"model.sqlite"
                    save_project(project, path)
                    self.assertEqual(load_project(path).to_dict(), project.to_dict())
                    run = prepare_run(path, export_format="none")
                    execute_run(run)
                    self.assertEqual(validate_study(project, run, spec["id"])["status"], "passed")

    def test_demo_notes_are_optional_and_excluded_from_core_project_payload(self):
        import json
        import sqlite3
        from contextlib import closing
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        with tempfile.TemporaryDirectory(dir=preferred) as tmp:
            path = Path(tmp)/"model.sqlite"
            save_project(make_demo("pglib14"), path)
            with closing(sqlite3.connect(path)) as conn, conn:
                payload = json.loads(conn.execute("SELECT value FROM metadata WHERE key='project'").fetchone()[0])
                self.assertNotIn("demo_info", payload)
                conn.execute("DELETE FROM metadata WHERE key='demo_info'")
            self.assertEqual(load_project(path).demo_info, {})
