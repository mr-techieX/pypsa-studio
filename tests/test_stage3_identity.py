"""Identity edits preserve references, frozen inputs and atomic cancellation."""

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from energy_gui.controller import Controller
from energy_gui.demo import demo_project
import pandas as pd
from energy_gui.engine import build_network, execute_run, prepare_run
from energy_gui.object_edits import delete_candidate, deletion_preview, rename_candidate, standard_names
from energy_gui.storage import load_project, save_project
from energy_gui.results import ResultsRepository
from PySide6.QtWidgets import QApplication, QMessageBox


def record(kind, name):
    return {"component": kind, "name": name}


class IdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.project = demo_project()

    def test_bus_rename_updates_ports_shapes_and_global_scope_without_mutation(self):
        self.project.upsert("Link", "multi", {"bus0": "North", "bus1": "City", "bus7": "North"})
        self.project.upsert("Shape", "area", {"component": "buses", "idx": "North"})
        self.project.upsert("GlobalConstraint", "scope", {"type": "tech_capacity_expansion_limit", "bus": "North", "carrier_attribute": "coal"})
        before = self.project.to_dict()
        renamed, updates = rename_candidate(self.project, "Bus", "North", "New North")
        self.assertEqual(self.project.to_dict(), before)
        self.assertIsNotNone(renamed.object("Bus", "New North"))
        self.assertEqual(renamed.object("Link", "multi")["attributes"]["bus7"], "New North")
        self.assertEqual(renamed.object("Shape", "area")["attributes"]["idx"], "New North")
        self.assertEqual(renamed.object("GlobalConstraint", "scope")["attributes"]["bus"], "New North")
        self.assertIn("Generator Thermal.bus", updates)

    def test_carrier_rename_discriminates_coefficients_and_selectors(self):
        for name, kind, value in [("co2", "primary_energy", "co2_emissions"),
                                  ("ops", "operational_limit", "coal"),
                                  ("tech", "tech_capacity_expansion_limit", "coal"),
                                  ("trans", "transmission_volume_expansion_limit", "[coal, solar]")]:
            self.project.upsert("GlobalConstraint", name, {"type": kind, "carrier_attribute": value})
        renamed, _ = rename_candidate(self.project, "Carrier", "coal", "fuel")
        self.assertEqual(renamed.object("Generator", "Thermal")["attributes"]["carrier"], "fuel")
        self.assertEqual(renamed.object("GlobalConstraint", "co2")["attributes"]["carrier_attribute"], "co2_emissions")
        self.assertEqual(renamed.object("GlobalConstraint", "trans")["attributes"]["carrier_attribute"], "fuel, solar")
        self.assertEqual(renamed.object("GlobalConstraint", "tech")["attributes"]["carrier_attribute"], "fuel")

    def test_rename_profiles_preserves_values_and_frozen_roundtrip(self):
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        with tempfile.TemporaryDirectory(dir=preferred) as tmp:
            frozen = Path(tmp) / "inputs.sqlite"
            save_project(self.project, frozen)
            old_bytes = frozen.read_bytes()
            renamed, _ = rename_candidate(self.project, "Generator", "Solar", "PV 001")
            old_profile = next(p for p in self.project.profiles if p["name"] == "Solar")
            new_profile = next(p for p in renamed.profiles if p["name"] == "PV 001")
            self.assertEqual(new_profile["values"], old_profile["values"])
            save_project(renamed, Path(tmp) / "edited.sqlite")
            self.assertEqual(load_project(Path(tmp) / "edited.sqlite").to_dict(), renamed.to_dict())
            self.assertEqual(frozen.read_bytes(), old_bytes)
            self.assertIsNotNone(load_project(frozen).object("Generator", "Solar"))
            network = build_network(renamed)
            self.assertIn("PV 001", network.generators.index)
            self.assertIn("PV 001", network.generators_t.p_max_pu.columns)

    def test_standard_type_references_and_target_collision(self):
        for kind, asset in [("LineType", "Line"), ("TransformerType", "Transformer")]:
            self.project.upsert(kind, "custom", {})
            self.project.upsert(asset, "typed", {"bus0": "North", "bus1": "City", "type": "custom"})
            renamed, _ = rename_candidate(self.project, kind, "custom", "other")
            self.assertEqual(renamed.object(asset, "typed")["attributes"]["type"], "other")
            with self.assertRaises(ValueError):
                rename_candidate(self.project, kind, "custom", next(iter(standard_names()[kind])))
            with self.assertRaisesRegex(ValueError, "Referenced by"):
                delete_candidate(self.project, [record(kind, "custom")])

    def test_ambiguous_references_and_reserved_electrical_carriers_are_rejected(self):
        self.project.upsert("Shape", "ambiguous", {"idx": "North"})
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            rename_candidate(self.project, "Bus", "North", "N")
        with self.assertRaises(ValueError):
            delete_candidate(self.project, [record("Bus", "North")])
        self.project.upsert("GlobalConstraint", "unknown", {"type": "future_constraint", "carrier_attribute": "coal, solar"})
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            rename_candidate(self.project, "Carrier", "coal", "fuel")
        with self.assertRaisesRegex(ValueError, "AC/DC"):
            rename_candidate(self.project, "Carrier", "AC", "electric")

    def test_invalid_and_duplicate_names_do_not_mutate(self):
        before = self.project.to_dict()
        for new in ["", "  ", "North", "City", "bad\nname"]:
            with self.assertRaises(ValueError):
                rename_candidate(self.project, "Bus", "North", new)
        self.assertEqual(self.project.to_dict(), before)

    def test_deletion_blocks_dependencies_but_allows_explicit_cross_category_batch(self):
        before = self.project.to_dict()
        preview = deletion_preview(self.project, [record("Carrier", "coal")])
        self.assertTrue(preview["blockers"])
        with self.assertRaises(ValueError):
            delete_candidate(self.project, [record("Carrier", "coal")])
        self.assertEqual(self.project.to_dict(), before)
        chosen = [record("Generator", "Thermal"), record("Generator", "City peaker"), record("Carrier", "coal")]
        candidate = delete_candidate(self.project, chosen)
        self.assertIsNone(candidate.object("Carrier", "coal"))
        self.assertIsNotNone(candidate.object("Generator", "Solar"))
        self.assertEqual(self.project.to_dict(), before)

    def test_profile_preview_and_removal_are_explicit(self):
        chosen = [record("Generator", "Solar")]
        preview = deletion_preview(self.project, chosen)
        self.assertIn("Generator Solar.p_max_pu", preview["profiles"])
        candidate = delete_candidate(self.project, chosen)
        self.assertFalse(any(p["name"] == "Solar" for p in candidate.profiles))
        with self.assertRaises(ValueError):
            delete_candidate(self.project, chosen + chosen)

    def test_controller_confirmation_history_invalidation_and_cancel(self):
        controller = Controller()
        controller.loadDemo()
        controller.selectType("Generator")
        controller.selectObject("Solar")
        before = controller.project.to_dict()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.assertFalse(controller.renameObject("PV"))
            self.assertFalse(controller.deleteObjects([record("Generator", "Solar")]))
        self.assertEqual(controller.project.to_dict(), before)
        controller._sheet_undo = [(deepcopy(before), deepcopy(before))]
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(controller.renameObject("PV"))
        self.assertEqual(controller.selected, "PV")
        self.assertEqual(controller._sheet_undo, [])
        self.assertFalse(controller.sheetHistory(False))
        controller.sheetModel.editCell(0, 1, "new draft")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(controller.deleteObjects([record("Generator", "PV")]))
        self.assertIsNotNone(controller.project.object("Generator", "PV"))

    def test_confirmation_rechecks_model_revision(self):
        controller = Controller()
        controller.loadDemo()
        controller.selectType("Generator")
        controller.selectObject("Solar")
        def concurrent_change(*args):
            controller.project.name = "Another edit"
            return QMessageBox.StandardButton.Yes
        with patch.object(QMessageBox, "question", side_effect=concurrent_change):
            self.assertFalse(controller.renameObject("PV"))
        self.assertIsNotNone(controller.project.object("Generator", "Solar"))
        self.assertEqual(controller.project.name, "Another edit")

    def test_renamed_model_solve_query_and_frozen_identity_after_later_edit(self):
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        with tempfile.TemporaryDirectory(prefix="identity_solve_", dir=preferred) as tmp:
            project, _ = rename_candidate(self.project, "Bus", "North", "Supply bus")
            project, _ = rename_candidate(project, "Generator", "Solar", "PV")
            project.upsert("Carrier", "unused", {})
            project = delete_candidate(project, [record("Carrier", "unused")])
            self.assertEqual(project.validate(), [])
            path = Path(tmp) / "model.sqlite"
            save_project(project, path)
            run = prepare_run(path, export_format="none")
            result = execute_run(run)
            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(json.loads((run / "metadata/solution_checks.json").read_text())["status"], "passed")
            generation = pd.read_csv(run / "tables" / "generators__p.csv", index_col=0)
            independent_cost = 2500 * generation.Thermal.sum() + 6000 * generation["City peaker"].sum()
            self.assertAlmostEqual(result["objective"], independent_cost, places=4)
            frozen_bytes = (run / "inputs.sqlite").read_bytes()
            later, _ = rename_candidate(project, "Generator", "PV", "PV later")
            save_project(later, path)
            repository = ResultsRepository(run, json.loads((run / "metadata/catalog.json").read_text()))
            generator_names = next(c["objects"] for c in repository.describe() if c["name"] == "Generator")
            self.assertIn("PV", generator_names)
            self.assertNotIn("PV later", generator_names)
            self.assertEqual(len(repository.query("Generator", ["PV"], ["p"])[0]), 24)
            self.assertEqual((run / "inputs.sqlite").read_bytes(), frozen_bytes)
