"""Actual Qt URL drop events, not just calling the open helper."""

from pathlib import Path
import unittest

import test_qml_controls as controls
from energy_gui.project import Project
from energy_gui.storage import save_project
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtTest import QTest


class FileDropUiTests(unittest.TestCase):
    setUpClass = classmethod(controls.QmlControlsTests.setUpClass.__func__)
    setUp = controls.QmlControlsTests.setUp
    tearDown = controls.QmlControlsTests.tearDown

    def test_qt_drop_opens_native_project_without_solve(self):
        path = Path(self.temp.name) / "drop model.sqlite"
        save_project(Project(name="Dropped project"), path)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path))])
        event = QDragEnterEvent(QPoint(300, 240), Qt.DropAction.CopyAction, mime,
                                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(self.root, event)
        self.assertTrue(event.isAccepted())
        drop = QDropEvent(QPointF(300, 240), Qt.DropAction.CopyAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(self.root, drop)
        QTest.qWait(80)
        self.assertEqual(self.controller.project.name, "Dropped project")
        self.assertIsNone(self.controller.process)
        self.assertEqual(self.warnings, [])

    def test_remote_and_multiple_urls_are_rejected_at_drag_enter(self):
        for values in [
            [QUrl("https://example.com/model.sqlite")],
            [QUrl.fromLocalFile(str(Path(self.temp.name) / "x.csv"))],
            [QUrl.fromLocalFile(str(Path(self.temp.name) / "model.xml"))],
            [QUrl("file:///C:/a.sqlite"), QUrl("file:///C:/b.sqlite")],
        ]:
            mime = QMimeData()
            mime.setUrls(values)
            event = QDragEnterEvent(QPoint(300, 240), Qt.DropAction.CopyAction, mime,
                                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            self.app.sendEvent(self.root, event)
            self.assertFalse(event.isAccepted())
        self.assertEqual(self.warnings, [])
