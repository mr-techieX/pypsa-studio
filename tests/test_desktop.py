"""Headless Qt/QProcess integration; no application window or file dialog required."""

import json
import os
from pathlib import Path
import tempfile
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from energy_gui.schema import registry
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from energy_gui.controller import Controller
from energy_gui.demo import demo_project
from energy_gui.storage import save_project


class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_qprocess_run_populates_results_and_filter(self):
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        with tempfile.TemporaryDirectory(prefix="pypsa_gui_qt_", dir=preferred) as tmp:
            controller = Controller()
            controller.project = demo_project()
            controller.path = Path(tmp) / "project.sqlite"
            save_project(controller.project, controller.path)
            messages = []
            controller.notice.connect(messages.append)
            loop = QEventLoop()
            complete = []
            controller.runCompleted.connect(lambda: (complete.append(True), loop.quit()))
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            controller.startRun("qt-test", "lp")
            timer.start(90000)
            loop.exec()
            timer.stop()
            if controller.process:
                controller.cancelRun()
                controller.process.waitForFinished(5000)
            self.assertTrue(complete, controller.messages + messages)
            self.assertEqual(controller.state["runStatus"], "succeeded")
            self.assertEqual(controller.state["resultRows"], 0, "Loading a run must not implicitly query it.")
            expected = {}
            for record in controller.project.objects:
                if record["component"] == "Carrier":
                    continue  # Carrier definitions are inputs, not solved results.
                expected.setdefault(record["component"], set()).add(record["name"])
            actual = {c["name"]: set(c["objects"]) for c in controller.queryOptions["categories"]}
            self.assertEqual(actual, expected, "Results must exclude standard catalogues and derived subnetworks.")
            # These tables remain in the raw exports for diagnostics/compatibility,
            # but may not bypass the model-scoped query API.
            self.assertTrue(any(e["component"] == "SubNetwork" for e in controller.catalog))
            self.assertFalse(controller.queryResults("SubNetwork", ["0"], ["carrier"], "", ""))
            self.assertTrue(controller.queryResults("Generator", ["Thermal", "Solar", "City peaker"], ["p"], "", ""))
            self.assertEqual(controller.state["resultRows"], 72)
            self.assertEqual(len(controller.state["chart"]["series"]), 3)
            controller.filterResults("2026-01-01 01:00")
            self.assertEqual(controller.state["resultRows"], 3)
            controller.filterResults("")
            self.assertEqual(controller.resultModel.rowCount(), 72)
            config = json.loads((controller.run_directory / "metadata/run_config.json").read_text())
            self.assertEqual(config["project_id"], controller.project.project_id)
            self.assertEqual(len(controller.state["runs"]), 1)
            controller.runCompleted.disconnect()
            controller.notice.disconnect()
            controller.deleteLater()
            self.app.processEvents()

    def test_stop_worker_records_cancelled_without_publishing_results(self):
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        with tempfile.TemporaryDirectory(prefix="pypsa_gui_cancel_", dir=preferred) as tmp:
            controller = Controller()
            controller.project = demo_project()
            controller.path = Path(tmp) / "project.sqlite"
            save_project(controller.project, controller.path)
            controller.startRun("cancel-test", "none")
            loop = QEventLoop()
            process = controller.process
            process.finished.connect(loop.quit)
            QTimer.singleShot(20, controller.cancelRun)
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            timer.start(10000)
            loop.exec()
            timer.stop()
            if controller.process:
                controller.cancelRun()
                controller.process.waitForFinished(5000)
            self.assertEqual(controller.state["runStatus"], "cancelled")
            self.assertEqual(controller.state["catalog"], [])
            config = json.loads((controller.run_directory / "metadata/run_config.json").read_text())
            self.assertEqual(config["status"], "cancelled")
            controller.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
