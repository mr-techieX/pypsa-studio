import unittest

from energy_gui.project import Project
from energy_gui.validation import formulation_warnings


class ValidationTests(unittest.TestCase):
    def base(self):
        project = Project()
        project.upsert("Bus", "A", {"v_nom": 220})
        project.upsert("Bus", "B", {"v_nom": 110})
        project.upsert("Generator", "G", {"bus": "A", "p_nom": 10})
        return project

    def test_negative_capacity_and_inverted_expansion_bounds(self):
        project = self.base()
        project.object("Generator", "G")["attributes"].update(p_nom=-10, p_nom_min=20, p_nom_max=10)
        text = "\n".join(project.validate())
        self.assertIn("capacity must", text)
        self.assertIn("p_nom_min exceeds", text)

    def test_dynamic_limits_use_scalar_fallback(self):
        project = self.base()
        project.object("Generator", "G")["attributes"]["p_min_pu"] = 0.5
        project.profiles = [{"component": "Generator", "name": "G", "attribute": "p_max_pu", "values": [0.1]}]
        self.assertTrue(any("p_min_pu exceeds" in e for e in project.validate()))

    def test_storage_efficiency_and_losses_are_checked(self):
        project = self.base()
        project.upsert("StorageUnit", "battery", {"bus": "A", "efficiency_store": 1.5, "standing_loss": -0.1})
        self.assertTrue(any("efficiency_store" in e for e in project.validate()))
        self.assertTrue(any("standing_loss" in e for e in project.validate()))

    def test_line_voltage_mismatch_and_bad_type(self):
        project = self.base()
        project.upsert("Line", "line", {"bus0": "A", "bus1": "B", "x": 1, "s_nom": 10, "type": "missing"})
        errors = "\n".join(project.validate())
        self.assertIn("voltage levels differ", errors)
        self.assertIn("unknown LineType", errors)

    def test_manual_transformer_requires_impedance_base(self):
        project = self.base()
        project.upsert("Transformer", "T", {"bus0": "A", "bus1": "B", "x": 0})
        errors = "\n".join(project.validate())
        self.assertIn("nonzero reactance", errors)
        self.assertIn("positive MVA", errors)

    def test_reactive_inputs_warn_but_do_not_claim_ac_dispatch(self):
        project = self.base()
        project.object("Generator", "G")["attributes"]["q_set"] = 3
        self.assertEqual(project.validate(), [])
        self.assertIn("DC-OPF", formulation_warnings(project)[0])

    def test_heat_pump_efficiency_above_one_and_negative_link_flow_are_valid(self):
        project = self.base()
        project.upsert("Link", "heat pump", {"bus0": "A", "bus1": "B", "p_nom": 10, "efficiency": 3, "p_min_pu": -1})
        self.assertEqual(project.validate(), [])

    def test_malformed_numeric_attributes_report_errors_without_crashing(self):
        project = self.base()
        project.object("Generator", "G")["attributes"]["p_nom"] = "not a number"
        self.assertTrue(project.validate())
        with self.assertRaises(ValueError):
            project.upsert("Generator", "other", {"p_nom": True})
