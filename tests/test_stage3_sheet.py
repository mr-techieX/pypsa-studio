"""Transactional spreadsheet edits, with the existing project as source of truth."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from energy_gui.controller import Controller
from energy_gui.project import Project
from energy_gui.schema import registry
from energy_gui.storage import load_project
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox


class SheetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.controller = Controller()
        self.controller.loadDemo()
        self.controller.selectType("Generator")
        self.sheet = self.controller.sheetModel

    def paste(self, text):
        self.assertTrue(self.sheet.pasteTsv(text), self.sheet.validationReport)

    def test_batch_is_staged_atomic_and_preserves_unshown_properties_profiles(self):
        before = self.controller.project.to_dict()
        self.paste("name\tp_nom\tmarginal_cost\nThermal\t160\t2400\nSolar\t90\t0\n")
        self.assertEqual(self.controller.project.to_dict(), before)
        self.assertTrue(self.controller.applySheet(), self.sheet.validationReport)
        project = self.controller.project
        self.assertEqual(project.object("Generator", "Thermal")["attributes"]["p_nom"], 160)
        self.assertEqual(project.object("Generator", "Thermal")["attributes"]["carrier"], "coal")
        self.assertEqual(project.profiles, before["profiles"])
        self.assertFalse(self.sheet.dirty)
        self.assertTrue(self.controller.state["sheetCanUndo"])

    def test_new_rows_leading_zero_names_boolean_and_dynamic_ports(self):
        self.paste("name\tbus\tp_nom\tcommittable\n001\tNorth\t10\tfalse\n")
        self.assertTrue(self.controller.applySheet())
        record = self.controller.project.object("Generator", "001")
        self.assertIs(record["attributes"]["committable"], False)
        self.controller.selectType("Link")
        self.paste("name\tbus0\tbus1\tbus2\tefficiency2\tp_nom\nconverter\tNorth\tCity\tCentral\t0.5\t10\n")
        self.assertTrue(self.controller.applySheet(), self.sheet.validationReport)
        self.assertEqual(self.controller.project.object("Link", "converter")["attributes"]["bus2"], "Central")

    def test_invalid_paste_never_partially_changes_draft_or_project(self):
        self.paste("name\tp_nom\nThermal\t170\n")
        draft, project = self.sheet.copyTsv(), self.controller.project.to_dict()
        for text in [
            "name\tp_nom\nThermal\t200\nSolar\tbad\n",
            "name\tp_nom\nThermal\t200\nThermal\t201\n",
            "name\tp\nThermal\t5\n", "name\tunknown\nThermal\t1\n",
            "name\tp_nom\tp_nom\nThermal\t1\t2\n",
            "p_nom\n12\n", "name\tp_nom\n\t12\n", "name\tp_nom\nThermal\t12\textra\n",
            "name\tcommittable\nThermal\tyes\n", "name\tp_nom\nThermal\tnan\n",
        ]:
            with self.subTest(text=text):
                self.assertFalse(self.sheet.pasteTsv(text))
                self.assertEqual(self.sheet.copyTsv(), draft)
                self.assertEqual(self.controller.project.to_dict(), project)

    def test_bad_reference_negative_capacity_and_bounds_block_entire_apply(self):
        before = self.controller.project.to_dict()
        for text in ["name\tbus\nThermal\tMissing\n", "name\tp_nom\nThermal\t-2\n",
                     "name\tp_nom_min\tp_nom_max\nThermal\t20\t10\n"]:
            self.controller.discardSheet()
            self.paste(text)
            self.assertFalse(self.controller.applySheet())
            self.assertEqual(self.controller.project.to_dict(), before)
            self.assertTrue(self.sheet.dirty)
            self.assertIn("Apply blocked", self.sheet.validationReport)

    def test_cell_parse_error_and_duplicate_new_name_are_actionable(self):
        row = self.sheet.original_names.index("Thermal")
        column = self.sheet.columns.index("p_nom")
        self.assertFalse(self.sheet.editCell(row, 0, "renamed"))
        self.assertTrue(self.sheet.editCell(row, column, "bad"))
        self.assertFalse(self.controller.validateSheet())
        self.assertIn("Row 1, p_nom", self.sheet.validationReport)
        self.controller.discardSheet()
        self.sheet.addRow()
        self.sheet.editCell(self.sheet.rowCount()-1, 0, "Thermal")
        self.assertFalse(self.controller.applySheet())
        self.assertIn("unique object name", self.sheet.validationReport)

    def test_blank_removes_explicit_input_but_untouched_empty_string_is_preserved(self):
        self.controller.project.upsert("Bus", "Blank", {"carrier": ""})
        self.controller.selectType("Bus")
        self.assertTrue(self.sheet.addColumn("v_mag_pu_set"))
        self.paste("name\tx\nNorth\t\n")
        self.assertTrue(self.controller.applySheet())
        self.assertNotIn("x", self.controller.project.object("Bus", "North")["attributes"])
        self.assertEqual(self.controller.project.object("Bus", "Blank")["attributes"]["carrier"], "")

    def test_copy_paste_roundtrip_and_blank_new_row_do_not_invent_objects(self):
        before = self.controller.project.to_dict()
        self.paste(self.sheet.copyTsv())
        self.assertFalse(self.sheet.dirty)
        self.sheet.addRow()
        self.assertTrue(self.controller.applySheet())
        self.assertEqual(self.controller.project.to_dict(), before)

    def test_incomplete_model_can_be_repaired_without_hiding_existing_issues(self):
        self.controller.project = Project()
        self.controller.project.upsert("Generator", "unfinished", {})
        self.controller.discardSheet()
        self.controller.selectType("Bus")
        self.paste("name\tv_nom\nA\t220\n")
        self.assertTrue(self.controller.applySheet())
        self.assertIn("bus is required", " ".join(self.controller.project.validate()))
        self.controller.selectType("Generator")
        self.paste("name\tbus\nunfinished\tA\n")
        self.assertTrue(self.controller.applySheet())
        self.assertEqual(self.controller.project.validate(), [])

    def test_stale_draft_cannot_overwrite_external_edits(self):
        self.paste("name\tp_nom\nThermal\t160\n")
        self.controller.project.currency = "USD"
        self.assertFalse(self.controller.applySheet())
        self.assertIn("project changed", self.sheet.validationReport)
        self.assertEqual(self.controller.project.object("Generator", "Thermal")["attributes"]["p_nom"], 150)

    def test_batch_undo_redo_and_external_edit_guard(self):
        before = self.controller.project.to_dict()
        self.paste("name\tp_nom\nThermal\t160\n")
        self.assertTrue(self.controller.applySheet())
        after = self.controller.project.to_dict()
        self.assertTrue(self.controller.sheetHistory(False))
        self.assertEqual(self.controller.project.to_dict(), before)
        self.assertTrue(self.controller.sheetHistory(True))
        self.assertEqual(self.controller.project.to_dict(), after)
        self.controller.project.currency = "USD"
        self.assertFalse(self.controller.state["sheetCanUndo"])
        self.assertFalse(self.controller.sheetHistory(False))
        self.assertEqual(self.controller.project.currency, "USD")

    def test_draft_cancel_discard_apply_and_invalid_apply_protect_navigation(self):
        self.paste("name\tp_nom\nThermal\t160\n")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.controller.selectType("Bus")
        self.assertEqual(self.controller.component, "Generator")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save):
            self.controller.selectType("Bus")
        self.assertEqual(self.controller.project.object("Generator", "Thermal")["attributes"]["p_nom"], 160)
        self.paste("name\tv_nom\nNorth\t-1\n")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save):
            self.assertFalse(self.controller.resolveDraft())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(self.controller.resolveDraft())
        self.assertFalse(self.sheet.dirty)

    def test_save_reopen_and_no_edits_while_running(self):
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        with tempfile.TemporaryDirectory(dir=preferred) as tmp:
            self.controller.path = Path(tmp) / "project.sqlite"
            self.paste("name\tp_nom\nThermal\t160\n")
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save):
                self.assertTrue(self.controller.saveProject())
            self.assertEqual(load_project(self.controller.path).object("Generator", "Thermal")["attributes"]["p_nom"], 160)
        self.controller.process = object()
        self.assertFalse(self.sheet.editCell(0, 1, "bad"))
        self.assertFalse(self.sheet.addRow())
        self.assertFalse(self.sheet.pasteTsv("name\tp_nom\nThermal\t200\n"))
        self.assertFalse(self.controller.applySheet())
        self.controller.process = None

    def test_all_static_input_columns_and_derived_read_only(self):
        for component, definition in registry().items():
            self.controller.selectType(component)
            for spec in definition["attributes"]:
                if spec["name"] == "name":
                    continue
                expected = definition["editable"] and spec["input"] and spec["static"]
                self.assertEqual(self.sheet.addColumn(spec["name"]), expected, (component, spec["name"]))
        self.controller.selectType("SubNetwork")
        self.assertFalse(self.sheet.addRow())

    def test_cancel_blocks_save_run_close_and_project_replacement(self):
        self.paste("name\tp_nom\nThermal\t160\n")
        before = self.controller.project.to_dict()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel), patch("energy_gui.controller.prepare_run") as prepare:
            self.assertFalse(self.controller.saveProject())
            self.controller.startRun("not-started", "none")
            self.assertFalse(self.controller.canClose())
            self.controller.newProject()
            prepare.assert_not_called()
        self.assertEqual(self.controller.project.to_dict(), before)
        self.assertTrue(self.sheet.dirty)

    def test_clean_sheet_tracks_profile_and_settings_changes_before_new_edits(self):
        self.controller.removeProfile(0)
        self.controller.configure("Renamed project", "USD", "2026-01-01", 24, 60)
        self.paste("name\tp_nom\nThermal\t160\n")
        self.assertTrue(self.controller.applySheet(), self.sheet.validationReport)
        self.assertEqual(self.controller.project.currency, "USD")
        self.assertEqual(len(self.controller.project.profiles), 1)

    def test_initial_columns_only_include_explicit_inputs_even_with_show_everything(self):
        before = self.controller.project.to_dict()
        expected = {"name", "bus", "carrier", "p_nom", "marginal_cost"}
        self.assertEqual(set(self.sheet.columns), expected)
        self.assertNotIn("p_set", self.sheet.columns)
        self.assertIn("p_set", self.sheet.availableColumns)
        settings = self.controller.editorConfiguration()
        properties = {kind: [p["name"] for p in specs] for kind, specs in settings["catalogue"].items()}
        self.assertTrue(self.controller.applyEditorConfiguration(list(settings["catalogue"]), properties))
        self.assertEqual(set(self.sheet.columns), expected)
        self.assertEqual(self.controller.project.objects, before["objects"])
        self.assertEqual(self.controller.project.profiles, before["profiles"])
        self.assertFalse(self.sheet.dirty)

    def test_explicit_default_valued_input_is_not_confused_with_omission(self):
        # Explicit zero is intentional data; a default-only field is absent.
        self.assertEqual(self.controller.project.object("Generator", "Solar")["attributes"]["marginal_cost"], 0)
        self.assertIn("marginal_cost", self.sheet.columns)
        self.assertNotIn("efficiency", self.sheet.columns)
        self.assertTrue(self.sheet.addColumn("efficiency"))
        self.assertFalse(self.sheet.dirty)
        self.controller.discardSheet()
        self.assertNotIn("efficiency", self.sheet.columns)
        self.assertIn("efficiency", self.sheet.availableColumns)

    def test_added_column_becomes_automatic_only_after_an_explicit_edit(self):
        self.assertTrue(self.sheet.addColumn("efficiency"))
        row = self.sheet.original_names.index("Thermal")
        self.assertTrue(self.sheet.editCell(row, self.sheet.columns.index("efficiency"), "0.4"))
        self.assertTrue(self.controller.applySheet())
        self.assertIn("efficiency", self.sheet.columns)
        self.controller.discardSheet()
        self.assertIn("efficiency", self.sheet.columns)

    def test_empty_category_starts_with_identity_only_and_respects_hidden_inputs(self):
        self.controller.selectType("Link")
        self.assertEqual(self.sheet.columns, ["name"])
        self.assertIn("bus0", self.sheet.availableColumns)
        self.assertTrue(self.controller.applyEditorConfiguration(["Link"], {"Link": ["name", "bus0"]}))
        self.assertEqual(self.sheet.columns, ["name"])
        self.assertTrue(self.sheet.addColumn("bus0"))
        self.assertFalse(self.sheet.addColumn("bus1"))
