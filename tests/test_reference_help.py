"""Read-only help covers hidden fields, outputs, curated guides and extra ports."""

from pathlib import Path
import unittest
from unittest.mock import patch

from energy_gui.demo import demo_project
from energy_gui.references import property_reference, reference_catalogue, reference_document
from energy_gui.schema import registry


class ReferenceHelpTests(unittest.TestCase):
    def test_all_classes_have_local_guides_and_schema_fields(self):
        project = demo_project()
        project.editor_config = {"categories": [], "properties": {"Generator": ["name"]}}
        before = project.to_dict()
        catalogue = reference_catalogue(project)
        self.assertEqual(set(catalogue), set(registry()) | {"Network"})
        for component in catalogue:
            guide = reference_document(component)
            self.assertIn("# PyPSA", guide)
            self.assertNotIn("not included", guide)
        self.assertIn("p_nom", [p["name"] for p in catalogue["Generator"]])
        self.assertIn("p", [p["name"] for p in catalogue["Generator"]])
        self.assertIn("snapshot_weightings", [p["name"] for p in catalogue["Network"]])
        self.assertEqual(project.to_dict(), before)

    def test_exact_property_metadata_and_extended_ports(self):
        project = demo_project()
        spec = property_reference(project, "Generator", "p_nom")
        self.assertEqual(spec["unit"], "MW")
        self.assertTrue(spec["input"])
        self.assertFalse(property_reference(project, "Generator", "p")["input"])
        project.upsert("Link", "converter", {"bus0": "North", "bus1": "City", "bus2": "Central"})
        self.assertIn("bus2", [p["name"] for p in reference_catalogue(project)["Link"]])
        self.assertEqual(property_reference(project, "Link", "bus7")["name"], "bus7")

    def test_unknown_property_is_not_given_an_invented_default_or_unit(self):
        info = property_reference(demo_project(), "Generator", "not_a_schema_property")
        self.assertIn("not in the installed base schema", info["description"])
        self.assertNotIn("default", info)
        self.assertNotIn("unit", info)

    def test_unknown_class_cannot_read_arbitrary_paths(self):
        with self.assertRaises(ValueError):
            reference_document("../AGENTS")

    def test_missing_guide_keeps_installed_schema_available(self):
        reference_document.cache_clear()
        try:
            with patch("energy_gui.references.REFERENCE_DIRECTORY", Path("missing-local-reference-directory")):
                info = property_reference(demo_project(), "Generator", "p_nom")
                self.assertEqual(info["unit"], "MW")
                self.assertIn("not included", info["guide"])
        finally:
            reference_document.cache_clear()
