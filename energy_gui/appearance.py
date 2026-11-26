"""Local appearance preference, following live OS color-scheme changes in System mode."""

from PySide6.QtCore import QObject, Property, QSettings, Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication


def is_dark(mode, system_scheme):
    return mode == "Dark" or (mode == "System" and system_scheme == Qt.ColorScheme.Dark)


class Appearance(QObject):
    changed = Signal()

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.settings = settings if settings is not None else QSettings()
        stored = self.settings.value("appearance/theme", "System")
        self._mode = stored if stored in {"Light", "Dark", "System"} else "System"
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._system_changed)

    def _system_changed(self, scheme):
        if self._mode == "System":
            self.changed.emit()

    @Property(str, notify=changed)
    def mode(self):
        return self._mode

    @Property(bool, notify=changed)
    def dark(self):
        return is_dark(self._mode, QGuiApplication.styleHints().colorScheme())

    @Slot(str)
    def setMode(self, mode):
        if mode not in {"Light", "Dark", "System"}:
            return
        self._mode = mode
        self.settings.setValue("appearance/theme", mode)
        self.changed.emit()
