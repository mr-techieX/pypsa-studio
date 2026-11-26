"""Release-specific contracts: no interoperability, all native entry points kept."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from energy_gui import __version__
from energy_gui.controller import Controller
from energy_gui.file_opening import model_path
from energy_gui.project import Project
from energy_gui.references import REFERENCE_DIRECTORY, reference_document
from energy_gui.storage import save_project, load_project
import test_qml_controls as controls
from PySide6.QtCore import QObject, QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


class ReleaseScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_version_and_interoperability_implementation_absent(self):
        self.assertEqual(__version__, "1.3.1")
        for module in ("source", "conversion", "export", "inspection", "mapping", "ui"):
            self.assertIsNone(importlib.util.find_spec("energy_gui.plexos_" + module))
        for name in ("importPlexosXml", "_import_plexos", "exportPlexosXml", "conversionReport"):
            self.assertFalse(hasattr(Controller, name), name)
        for name in ("startRunWithReports", "startConfiguredRun", "previewHorizon", "modelHistory",
                     "openModelFile", "dropModelFiles", "backupProject", "startBackup",
                     "openNetcdfResults", "browseNetcdfResults"):
            self.assertTrue(callable(getattr(Controller, name)), name)

    def test_xml_rejected_without_reading_or_replacing(self):
        controller = Controller()
        before = controller.project.to_dict()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "model.XML"
            path.write_text("<invalid/>", encoding="utf-8")
            with patch.object(Path, "open", side_effect=AssertionError("XML must not be opened")):
                self.assertFalse(controller.openModelFile(str(path)))
                self.assertFalse(controller.acceptsModelFiles([QUrl.fromLocalFile(str(path)).toString()]))
        self.assertEqual(controller.project.to_dict(), before)
        with self.assertRaises(ValueError):
            model_path("file:///C:/model.xml")

    def test_opaque_native_metadata_preserved_without_converter(self):
        project = Project()
        project.interchange_info = {"report": {"source": "unknown"}, "export_schema": {"inert": "x" * 10000}}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "project.sqlite"
            save_project(project, path)
            reopened = load_project(path)
            self.assertEqual(reopened.to_dict(), project.to_dict())
        controller = Controller()
        controller.project = project
        with patch.object(Project, "to_dict", side_effect=AssertionError("No hot-path copy")):
            controller.changed.emit()
            self.assertFalse(controller.uiState["modelCanUndo"])

    def test_bundled_help_and_no_user_payload(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(REFERENCE_DIRECTORY, root / "Attribute-Info")
        self.assertIn("Generator", reference_document("Generator"))
        for name in ("myTest", "EnEx", "dist"):
            self.assertFalse((root / name).exists())
        self.assertEqual(list((root / "energy_gui").glob("plexos_*.py")), [])


class ReleaseUiScopeTests(unittest.TestCase):
    setUpClass = classmethod(controls.QmlControlsTests.setUpClass.__func__)
    setUp = controls.QmlControlsTests.setUp
    tearDown = controls.QmlControlsTests.tearDown
    visual_item = controls.QmlControlsTests.visual_item

    def test_native_ui_retained_and_no_interoperability_commands(self):
        self.assertIn("PyPSA Studio v1.3.1", self.root.title())
        for name in ("importPlexosXml", "exportPlexosXml", "conversionReport"):
            self.assertIsNone(self.root.findChild(QObject, name))
        for name in ("modelFileDrop",
                     "networkViewport", "networkHorizontalScroll", "networkVerticalScroll",
                     "shortcutSave", "shortcutNew", "shortcutOpen", "shortcutUndo", "shortcutRedo"):
            self.assertIsNotNone(self.root.findChild(QObject, name), name)
        self.assertIsNotNone(self.root.findChild(QObject, "openNetcdfResults"))
        # Inspect the active page's visual tree, not QObject ownership of
        # controls nested in the Runs scroll view.
        self.root.setProperty("page", 4)
        QTest.qWait(80)
        for name in ("horizonMode", "configuredRunStart", "exportPythonScript"):
            item = self.visual_item(name)
            self.assertIsNotNone(item, name)
            self.assertTrue(item.isVisible(), name)
        self.assertIsNotNone(self.visual_item("horizonRepeatDaily"))
        self.assertEqual(self.warnings, [])
