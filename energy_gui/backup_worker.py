"""Cancellable background backup job; never calls widgets from the worker."""

from threading import Event

from .safety import create_backup
from PySide6.QtCore import QObject, Signal, Slot


class BackupWorker(QObject):
    progress = Signal(int)
    finished = Signal(str, bool)

    def __init__(self, source, destination):
        super().__init__()
        self.source, self.destination = source, destination
        self.cancelled = Event()

    @Slot()
    def run(self):
        try:
            path = create_backup(self.source, self.destination, self.progress.emit, self.cancelled.is_set)
            self.finished.emit("Backup created: " + str(path), True)
        except Exception as error:
            self.finished.emit(str(error), False)
