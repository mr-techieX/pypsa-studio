"""Actual Run-window controls and owned-worker sequential lifecycle."""

import json
import os
from pathlib import Path
import time

import test_qml_controls as controls
from test_horizon import fixture, specification
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from unittest.mock import patch
import unittest

from energy_gui.storage import save_project


class HorizonUiTests(unittest.TestCase):
    setUpClass = classmethod(controls.QmlControlsTests.setUpClass.__func__)
    setUp = controls.QmlControlsTests.setUp
    tearDown = controls.QmlControlsTests.tearDown
    evaluate = controls.QmlControlsTests.evaluate
    visual_item = controls.QmlControlsTests.visual_item

    def click(self, name):
        item = self.visual_item(name)
        self.assertIsNotNone(item, name)
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         item.mapToScene(item.boundingRect().center()).toPoint())
        QTest.qWait(40)
        return item

    def configure(self):
        self.evaluate(self.root, "page = 4")
        mode = self.visual_item("horizonMode")
        mode.setProperty("currentIndex", 1)
        self.visual_item("horizonStart").setProperty("text", "2027-01-01")
        self.visual_item("horizonStepSize").setProperty("value", 2)
        self.visual_item("horizonStepCount").setProperty("value", 16)
        QTest.qWait(60)

    def test_actual_sync_error_colour_and_bounds_in_both_themes(self):
        self.configure()
        settings = self.visual_item("horizonSettings")
        for theme in ["Light", "Dark"]:
            self.appearance.setMode(theme)
            self.visual_item("horizonStepCount").setProperty("value", 16)
            QTest.qWait(50)
            self.assertFalse(settings.property("valid"))
            self.assertFalse(self.visual_item("configuredRunStart").isEnabled())
            preview = self.visual_item("horizonPreview")
            self.assertEqual(preview.property("color"), self.evaluate(self.root, "appTheme.danger"))
            self.assertIn("beyond", preview.property("text"))
            self.click("horizonSync")
            self.assertEqual(self.visual_item("horizonStepCount").property("value"), 15)
            self.assertTrue(settings.property("valid"))
            self.assertTrue(self.visual_item("configuredRunStart").isEnabled())
            self.assertIn("24 hours unused", preview.property("text"))
            self.assertEqual(preview.property("color"), self.evaluate(self.root, "appTheme.success"))
            self.root.setWidth(1140)
            self.root.setHeight(760)
            QTest.qWait(60)
            for name in ["horizonSync", "horizonSchedule", "configuredRunStart"]:
                item = self.visual_item(name)
                bounds = item.mapRectToScene(item.boundingRect())
                self.assertGreaterEqual(bounds.left(), 0, name)
                self.assertLessEqual(bounds.right(), self.root.width(), name)
                self.assertLessEqual(bounds.bottom(), self.root.height(), name)
            output = os.environ.get("STUDIO_HORIZON_EVIDENCE")
            if output:
                dest = Path(output)
                dest.mkdir(parents=True, exist_ok=True)
                self.assertTrue(self.root.grabWindow().save(str(dest / f"horizon-{theme.lower()}.png")))
        page = self.visual_item("runPage")
        self.evaluate(page, "contentItem.contentY = contentItem.contentHeight - contentItem.height")
        QTest.qWait(80)
        timeline = self.visual_item("executionTimeline")
        bounds = timeline.mapRectToScene(timeline.boundingRect())
        self.assertGreaterEqual(bounds.top(), 0)
        self.assertLess(bounds.bottom(), self.root.height())
        if output:
            self.assertTrue(self.root.grabWindow().save(str(Path(output) / "horizon-scrolled.png")))
        self.assertEqual(self.warnings, [])

    def test_start_freezes_effective_axis_without_project_mutation(self):
        self.configure()
        self.click("horizonSync")
        self.controller.project = fixture()
        self.controller.path = Path(self.temp.name) / "project.sqlite"
        save_project(self.controller.project, self.controller.path)
        before = self.controller.project.to_dict()
        with patch.object(self.controller, "_launch_run") as launch:
            self.click("configuredRunStart")
            launch.assert_called_once()
            run = launch.call_args.args[0]
        self.assertEqual(self.controller.project.to_dict(), before)
        config = json.loads((run / "metadata/run_config.json").read_text())
        self.assertEqual(len(config["horizon"]["steps"]), 15)
        self.assertFalse(self.warnings)

    def test_daily_repeat_checkbox_is_explicit_and_frozen(self):
        from test_daily_profiles import daily_fixture
        self.configure()
        self.click("horizonSync")
        self.controller.project = daily_fixture()
        self.controller.path = Path(self.temp.name) / "daily.sqlite"
        save_project(self.controller.project, self.controller.path)
        settings = self.visual_item("horizonSettings")
        self.assertEqual(json.loads(settings.property("specification"))["profile_policy"], "exact")
        self.click("horizonRepeatDaily")
        self.assertEqual(json.loads(settings.property("specification"))["profile_policy"], "repeat_daily")
        before = self.controller.project.to_dict()
        with patch.object(self.controller, "_launch_run") as launch:
            self.click("configuredRunStart")
            launch.assert_called_once()
            run = launch.call_args.args[0]
        self.assertEqual(self.controller.project.to_dict(), before)
        self.assertEqual(json.loads((run / "metadata/run_config.json").read_text())["horizon"]["spec"]["profile_policy"], "repeat_daily")
        self.assertEqual(self.warnings, [])

    def wait_worker(self, timeout=120):
        until = time.monotonic() + timeout
        while self.controller.process and time.monotonic() < until:
            QTest.qWait(50)
        if self.controller.process:
            self.controller.cancelRun()
            QTest.qWait(1000)
            self.fail("Worker exceeded test timeout.")

    def launch(self, spec):
        self.controller.project = fixture()
        self.controller.path = Path(self.temp.name) / "project.sqlite"
        save_project(self.controller.project, self.controller.path)
        self.controller.startConfiguredRun("gui", "lp", json.dumps(spec))
        self.assertIsNotNone(self.controller.process)

    def test_real_worker_reopen_and_query_without_resolve(self):
        self.launch(specification(duration=4, duration_unit="hour", step_size=2,
                                  step_unit="hour", step_count=2))
        self.wait_worker()
        self.assertEqual(self.controller.run_meta["status"], "succeeded", self.controller.messages)
        run = self.controller.run_directory
        self.assertTrue(self.controller.openRun(str(run)))
        self.assertTrue(self.controller.queryResults("Generator", ["Supply"], ["p"], "", ""))
        self.assertIsNone(self.controller.process)
        self.assertEqual(len(self.controller.repository.snapshots), 4)

    def test_real_owned_worker_cancel_preserves_partial_diagnostics(self):
        self.launch(specification())
        until = time.monotonic() + 90
        while self.controller.process and self.controller.run_directory.joinpath("steps/step-0002").exists() is False and time.monotonic() < until:
            QTest.qWait(50)
        self.assertIsNotNone(self.controller.process)
        self.controller.cancelRun()
        self.wait_worker()
        run = self.controller.run_directory
        meta = json.loads((run / "metadata/run_config.json").read_text())
        self.assertEqual(meta["status"], "cancelled")
        manifest = json.loads((run / "metadata/execution_manifest.json").read_text())
        self.assertEqual(manifest["status"], "cancelled")
        self.assertGreaterEqual(manifest["completed_steps"], 1)
        self.assertFalse((run / "metadata/catalog.json").exists())
        self.assertTrue(self.controller.openRun(str(run)))
        self.assertEqual(self.controller.catalog, [])
