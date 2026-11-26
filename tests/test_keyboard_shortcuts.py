"""Real keyboard events in QML; no replacement of the save/history implementation."""

from pathlib import Path
import unittest
from unittest.mock import patch

import test_qml_controls as controls
from energy_gui.project import Project
from energy_gui.storage import load_project, save_project
from PySide6.QtCore import QObject, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QMessageBox


class KeyboardShortcutTests(unittest.TestCase):
    setUpClass = classmethod(controls.QmlControlsTests.setUpClass.__func__)
    setUp = controls.QmlControlsTests.setUp
    tearDown = controls.QmlControlsTests.tearDown
    visual_item = controls.QmlControlsTests.visual_item
    evaluate = controls.QmlControlsTests.evaluate

    def press(self, key, modifiers=Qt.KeyboardModifier.ControlModifier):
        self.root.requestActivate()
        QTest.qWait(40)
        QTest.keyClick(self.root, key, modifiers)
        QTest.qWait(80)
        self.assertEqual(self.warnings, [])

    def button_focus(self):
        self.visual_item("quickSave").forceActiveFocus()
        QTest.qWait(30)

    def saved(self):
        self.controller.loadDemo()
        self.controller.path = (Path(self.temp.name) / "saved.sqlite").resolve()
        self.assertTrue(self.controller.saveProject())
        self.button_focus()
        return self.controller.path

    def test_ctrl_s_saves_existing_database(self):
        path = self.saved()
        self.assertTrue(self.controller.storeObject("Keyboard Bus", "{}"))
        self.button_focus()
        self.press(Qt.Key.Key_S)
        self.assertIsNotNone(load_project(path).object("Bus", "Keyboard Bus"))
        self.assertFalse(self.controller.dirty)

    def test_ctrl_s_new_project_save_dialog_and_cancel(self):
        self.button_focus()
        before = self.controller.project.to_dict()
        with patch.object(QFileDialog, "getSaveFileName", return_value=("", "")) as dialog:
            self.press(Qt.Key.Key_S)
            dialog.assert_called_once()
        self.assertIsNone(self.controller.path)
        self.assertEqual(self.controller.project.to_dict(), before)
        path = (Path(self.temp.name) / "first-save.sqlite").resolve()
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(path), "")):
            self.press(Qt.Key.Key_S)
        self.assertTrue(path.exists())

    def test_ctrl_s_respects_pending_inspector_cancel_then_apply(self):
        path = self.saved()
        self.controller.selectType("Generator")
        self.controller.selectObject("Solar")
        field = self.visual_item("objectJsonEditor")
        self.root.setProperty("page", 1)
        field.setProperty("text", '{"bus":"South","p_nom":123}')
        field.forceActiveFocus()
        QTest.qWait(40)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel) as question:
            self.press(Qt.Key.Key_S)
            question.assert_called_once()
        self.assertNotEqual(load_project(path).object("Generator", "Solar")["attributes"]["p_nom"], 123)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save):
            self.press(Qt.Key.Key_S)
        self.assertEqual(load_project(path).object("Generator", "Solar")["attributes"]["p_nom"], 123)

    def test_ctrl_s_respects_pending_spreadsheet_cancel_then_apply(self):
        path = self.saved()
        self.controller.selectType("Generator")
        self.assertTrue(self.controller.beginSheet())
        self.assertTrue(self.controller.sheetModel.pasteTsv("name\tp_nom\nSolar\t123\n"))
        self.button_focus()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.press(Qt.Key.Key_S)
        self.assertTrue(self.controller.sheetModel.dirty)
        self.assertNotEqual(load_project(path).object("Generator", "Solar")["attributes"]["p_nom"], 123)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save):
            self.press(Qt.Key.Key_S)
        self.assertEqual(load_project(path).object("Generator", "Solar")["attributes"]["p_nom"], 123)

    def test_ctrl_o_opens_and_cancellation_preserves_current(self):
        self.button_focus()
        before = self.controller.project.to_dict()
        with patch.object(QFileDialog, "getOpenFileName", return_value=("", "")):
            self.press(Qt.Key.Key_O)
        self.assertEqual(self.controller.project.to_dict(), before)
        path = (Path(self.temp.name) / "open.sqlite").resolve()
        project = Project(name="Keyboard opened")
        save_project(project, path)
        with patch.object(QFileDialog, "getOpenFileName", return_value=(str(path), "")):
            self.press(Qt.Key.Key_O)
        self.assertEqual(self.controller.project.name, "Keyboard opened")
        self.assertEqual(self.controller.path, path)

    def test_ctrl_n_preserves_dirty_cancel_and_resets_after_discard(self):
        path = self.saved()
        self.controller.storeObject("Extra", "{}")
        before = self.controller.project.to_dict()
        self.button_focus()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.press(Qt.Key.Key_N)
        self.assertEqual(self.controller.project.to_dict(), before)
        self.assertEqual(self.controller.path, path)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.press(Qt.Key.Key_N)
        self.assertIsNone(self.controller.path)
        self.assertNotEqual(self.controller.project.project_id, before["project_id"])

    def test_model_undo_and_both_redo_keys(self):
        self.saved()
        self.controller.storeObject("Extra", "{}")
        self.button_focus()
        for modifiers in (
            Qt.KeyboardModifier.ControlModifier,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        ):
            self.press(Qt.Key.Key_Z)
            self.assertIsNone(self.controller.project.object("Bus", "Extra"))
            self.press(Qt.Key.Key_Y if modifiers == Qt.KeyboardModifier.ControlModifier else Qt.Key.Key_Z, modifiers)
            self.assertIsNotNone(self.controller.project.object("Bus", "Extra"))

    def test_ctrl_z_in_text_field_undoes_text_not_model(self):
        self.saved()
        self.controller.storeObject("Extra", "{}")
        self.root.setProperty("page", 1)
        field = self.visual_item("objectNameEditor")
        # Use a new-object name field (existing names are read-only).
        self.controller.selectObject("")
        field.forceActiveFocus()
        for character in "KeyboardDraft":
            QTest.keyClick(self.root, Qt.Key(ord(character.upper())))
        QTest.qWait(40)
        self.assertTrue(field.property("text"))
        self.assertTrue(self.evaluate(self.root, "editingText()"))
        self.assertFalse(self.root.findChild(QObject, "shortcutUndo").property("enabled"))
        self.press(Qt.Key.Key_Z)
        self.assertEqual(field.property("text"), "")
        self.assertIsNotNone(self.controller.project.object("Bus", "Extra"))
        self.press(Qt.Key.Key_Y)
        self.assertTrue(field.property("text"))
        self.assertIsNotNone(self.controller.project.object("Bus", "Extra"))

    def test_busy_and_modal_tools_do_not_accept_project_shortcuts(self):
        self.saved()
        for flag in ("_batch_active", "_backup_thread", "process"):
            setattr(self.controller, flag, True)
            self.controller.changed.emit()
            with patch.object(QFileDialog, "getOpenFileName") as open_dialog:
                self.press(Qt.Key.Key_O)
                open_dialog.assert_not_called()
            setattr(self.controller, flag, None if flag != "_batch_active" else False)
            self.controller.changed.emit()
        self.controller.notice.emit("Shortcut modal test")
        QTest.qWait(40)
        self.assertFalse(self.root.findChild(QObject, "shortcutSave").property("enabled"))
        with patch.object(QFileDialog, "getOpenFileName") as dialog:
            self.press(Qt.Key.Key_O)
            dialog.assert_not_called()
        self.press(Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
