"""Read an archive off the GUI thread in a cancellable modal operation."""

from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout

from .netcdf_results import NetcdfResults


def read_results(path):
    class Reader(QThread):
        result = None
        error = None

        def run(self):
            try:
                self.result = NetcdfResults(path, self.isInterruptionRequested)
            except Exception as error:
                self.error = error

    reader = Reader()

    class Progress(QDialog):
        def reject(self):
            reader.requestInterruption()
            label.setText("Cancelling after the current read…")
            cancel.setEnabled(False)

    dialog = Progress()
    dialog.setWindowTitle("Open NetCDF results")
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    layout = QVBoxLayout(dialog)
    label = QLabel("Reading and validating the archive…")
    layout.addWidget(label)
    bar = QProgressBar()
    bar.setRange(0, 0)
    layout.addWidget(bar)
    cancel = QPushButton("Cancel")
    cancel.clicked.connect(dialog.reject)
    layout.addWidget(cancel)
    reader.finished.connect(dialog.accept, Qt.ConnectionType.QueuedConnection)
    reader.start()
    dialog.exec()
    reader.wait()
    if not cancel.isEnabled():
        return None
    if reader.error is not None:
        raise reader.error
    return reader.result
