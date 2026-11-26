"""Safe local open/drop routing and native-only release routing."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from energy_gui.controller import Controller
from energy_gui.file_opening import local_file
from energy_gui.project import Project
from energy_gui.storage import save_project
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QMessageBox


class FileOpeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.c = Controller()
        self.messages = []
        self.c.notice.connect(self.messages.append)
        self.path = self.root / "模型 literal% # model.SQLITE"
        save_project(Project(name="Opened file"), self.path)
        self.path = self.path.resolve()

    def test_local_url_unicode_and_literal_characters_open_same_model(self):
        self.assertEqual(local_file(QUrl.fromLocalFile(str(self.path)).toString()), self.path)
        self.assertTrue(self.c.dropModelFiles([QUrl.fromLocalFile(str(self.path)).toString()]))
        self.assertEqual(self.c.project.name, "Opened file")
        self.assertEqual(self.c.path, self.path)

    def test_rejected_files_preserve_dirty_drafts_without_guard(self):
        before = self.c.project.to_dict()
        self.c.dirty = True
        bad = self.root / "bad.sqlite"
        bad.write_text("not sqlite")
        with patch.object(self.c, "_can_replace") as guard:
            self.assertFalse(self.c.openModelFile(str(bad)))
            guard.assert_not_called()
        self.assertEqual(self.c.project.to_dict(), before)
        self.assertTrue(self.c.dirty)

    def test_drag_enter_has_no_filesystem_access_and_rejects_unsafe_urls(self):
        url = QUrl.fromLocalFile(str(self.path)).toString()
        with patch.object(Path, "resolve", side_effect=AssertionError("No drag-enter I/O")):
            self.assertTrue(self.c.acceptsModelFiles([url]))
            for value in [
                "file:////server/share/a.sqlite", "file://server/share/a.sqlite",
                url + "#fragment", url + "?query", "https://example.com/model.sqlite",
            ]:
                with self.subTest(value=value):
                    self.assertFalse(self.c.acceptsModelFiles([value]))

    def test_cancel_busy_same_file_and_multifile(self):
        self.c.dirty = True
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.c.openModelFile(str(self.path)))
        self.assertIsNone(self.c.path)
        self.c.dirty = False
        self.assertTrue(self.c.openModelFile(str(self.path)))
        with patch.object(self.c, "_can_replace") as guard:
            self.assertTrue(self.c.openModelFile(str(self.path)))
            guard.assert_not_called()
        self.c._batch_active = True
        self.assertFalse(self.c.openModelFile(str(self.path)))
        self.c._batch_active = False
        self.assertFalse(self.c.dropModelFiles([str(self.path), str(self.path)]))
        for path in [
            "https://example.com/a.sqlite", str(self.root), "file://server/share/a.sqlite",
            "file:////server/share/a.sqlite", str(self.path) + "?query",
            QUrl.fromLocalFile(str(self.path)).toString() + "#fragment",
        ]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                local_file(path)


    def test_xml_rejected_without_replacement_or_file_reads(self):
        path = self.root / "model.xml"
        path.write_text("<not-parsed/>", encoding="utf-8")
        before = self.c.project.to_dict()
        self.c.dirty = True
        with patch.object(self.c, "_can_replace") as guard:
            self.assertFalse(self.c.openModelFile(str(path)))
            guard.assert_not_called()
        self.assertFalse(self.c.acceptsModelFiles([QUrl.fromLocalFile(str(path)).toString()]))
        self.assertEqual(self.c.project.to_dict(), before)
        self.assertTrue(self.c.dirty)
