import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from energy_gui.schema import registry  # Match application scientific-before-Qt startup.
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from energy_gui.appearance import Appearance, is_dark


class AppearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_system_resolution_and_explicit_overrides(self):
        self.assertTrue(is_dark("System", Qt.ColorScheme.Dark))
        self.assertFalse(is_dark("System", Qt.ColorScheme.Light))
        self.assertFalse(is_dark("System", Qt.ColorScheme.Unknown))
        self.assertTrue(is_dark("Dark", Qt.ColorScheme.Light))
        self.assertFalse(is_dark("Light", Qt.ColorScheme.Dark))

    def test_local_preference_persists_and_invalid_modes_do_not(self):
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        with tempfile.TemporaryDirectory(prefix="appearance_test_", dir=preferred) as tmp:
            settings = QSettings(str(Path(tmp) / "settings.ini"), QSettings.Format.IniFormat)
            first = Appearance(settings)
            first.setMode("Dark")
            second = Appearance(settings)
            self.assertEqual(second.mode, "Dark")
            self.assertTrue(second.dark)
            second.setMode("Light")
            self.assertFalse(second.dark)
            second.setMode("invalid")
            self.assertEqual(second.mode, "Light")
            settings.sync()

    def test_live_system_change_notifies_only_in_system_mode(self):
        settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "test-in-memory", "appearance")
        # No settings are written in this test.
        view = Appearance(settings)
        view._mode = "System"
        events = []
        view.changed.connect(lambda: events.append(True))
        view._system_changed(Qt.ColorScheme.Dark)
        self.assertEqual(len(events), 1)
        view._mode = "Light"
        view._system_changed(Qt.ColorScheme.Dark)
        self.assertEqual(len(events), 1)
        view.changed.disconnect()
