"""Real selectors, chart handles, pinned tabs and portable saved analyses."""

import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_qml_controls as controls
from test_temporal import repository
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox, QFileDialog

from energy_gui.storage import save_project
from energy_gui.analysis import capture_analysis, prepare_analysis


class TemporalUiTests(unittest.TestCase):
    setUpClass = classmethod(controls.QmlControlsTests.setUpClass.__func__)
    tearDown = controls.QmlControlsTests.tearDown
    evaluate = controls.QmlControlsTests.evaluate
    visual_item = controls.QmlControlsTests.visual_item

    def setUp(self):
        controls.QmlControlsTests.setUp(self)
        root = Path(self.temp.name)
        run = root / "runs" / "calendar"
        run.mkdir(parents=True)
        repo = repository(run, count=72)
        self.controller.project = repo.project
        self.controller.path = root / "project.sqlite"
        save_project(repo.project, self.controller.path)
        (run / "run_config.json").write_text(json.dumps(dict(
            project_id=repo.project.project_id, status="succeeded", objective=123,
            formulation="linear nodal optimization (LP/MILP)", currency="INR")))
        self.assertTrue(self.controller.openRun(str(run)))
        self.evaluate(self.root, "page=5")
        QTest.qWait(80)
        self.explorer = self.visual_item("resultsExplorer")
        self.evaluate(self.explorer, "chooseCategory('Generator'); selectedObjects=['A']; selectedProperties=['p']; expanded=({Generator:true})")
        QTest.qWait(40)

    def click(self, name):
        item = self.visual_item(name)
        self.assertIsNotNone(item, name)
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         item.mapToScene(item.boundingRect().center()).toPoint())
        QTest.qWait(150)
        return item

    def set_choice(self, name, value):
        item = self.visual_item(name)
        self.evaluate(item, f"currentIndex=model.indexOf({json.dumps(value)}); activated(currentIndex)")
        QTest.qWait(40)

    def test_calendar_query_drafts_listing_and_full_csv(self):
        self.set_choice("queryResolution", "daily")
        self.set_choice("queryMetric", "energy")
        self.click("executeQuery")
        tab = self.controller.workspace.active
        self.assertEqual(tab.frame.p.tolist(), [300, 876, 1452])
        self.assertEqual(tab.specs[0]["unit"], "MWh")
        self.set_choice("queryResolution", "monthly")
        self.assertTrue(self.explorer.property("pending"))
        self.assertEqual(tab.criteria["aggregation"]["resolution"], "daily")
        self.set_choice("resultListing", "property")
        self.assertIn("property", self.controller._filtered_frame)
        self.assertEqual(len(self.controller._filtered_frame), 3)
        self.controller.sortResultTable("value")
        self.controller.sortResultTable("value")
        self.assertEqual(self.controller._filtered_frame.value.tolist(), [1452, 876, 300])
        export = Path(self.temp.name) / "query.csv"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(export), "CSV")):
            self.controller.exportResults()
        self.assertTrue(export.exists())
        meta = json.loads(export.with_suffix(".csv.metadata.json").read_text())
        self.assertEqual(meta["criteria"]["aggregation"]["resolution"], "daily")
        self.assertEqual(meta["specs"][0]["unit"], "MWh")
        self.assertEqual(meta["sort_column"], "value")
        self.assertTrue(meta["sort_descending"])
        self.assertEqual(self.warnings, [])

    def test_draggable_range_changes_charts_not_table_and_persists(self):
        self.click("executeQuery")
        tab = self.controller.workspace.active
        original = tab.frame.copy(deep=True)
        self.click("chartsViewToggle")
        self.root.setWidth(1140); self.root.setHeight(760)
        QTest.qWait(80)
        right = self.visual_item("timelineRightHandle")
        start = right.mapToScene(right.boundingRect().center()).toPoint()
        finish = start
        finish.setX(start.x()-140)
        # QPoint is implicitly shared: obtain the original handle point again.
        start = right.mapToScene(right.boundingRect().center()).toPoint()
        QTest.mousePress(self.root, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(self.root, finish, 100)
        QTest.mouseRelease(self.root, Qt.MouseButton.LeftButton, pos=finish)
        QTest.qWait(250)
        self.assertLess(self.controller.state["chartRange"]["last"], 71)
        self.assertTrue(tab.frame.equals(original))
        self.assertEqual(len(self.controller._filtered_frame), 72)
        left = self.visual_item("timelineLeftHandle")
        start = left.mapToScene(left.boundingRect().center()).toPoint()
        finish = left.mapToScene(left.boundingRect().center()).toPoint()
        finish.setX(finish.x()+55)
        QTest.mousePress(self.root, Qt.MouseButton.LeftButton, pos=start)
        halfway = left.mapToScene(left.boundingRect().center()).toPoint()
        halfway.setX(start.x()+20)
        QTest.mouseMove(self.root, halfway, 50)
        QTest.mouseMove(self.root, finish, 100)
        QTest.mouseRelease(self.root, Qt.MouseButton.LeftButton, pos=finish)
        QTest.qWait(250)
        self.assertGreater(tab.chart_range[0], 0, str(self.evaluate(self.visual_item("chartTimelineRange"),
            "JSON.stringify({first:first.value,last:second.value,firstPressed:first.pressed,lastPressed:second.pressed})")) + str(start) + str(finish))
        narrowed = list(tab.chart_range)
        pan = self.visual_item("timelinePan")
        start = pan.mapToScene(pan.boundingRect().center()).toPoint()
        finish = pan.mapToScene(pan.boundingRect().center()).toPoint()
        finish.setX(finish.x()+30)
        QTest.mousePress(self.root, Qt.MouseButton.LeftButton, pos=start)
        halfway = pan.mapToScene(pan.boundingRect().center()).toPoint()
        halfway.setX(start.x()+15)
        QTest.mouseMove(self.root, halfway, 50)
        QTest.mouseMove(self.root, finish, 100)
        QTest.mouseRelease(self.root, Qt.MouseButton.LeftButton, pos=finish)
        QTest.qWait(250)
        self.assertGreater(tab.chart_range[0], narrowed[0])
        self.assertEqual(tab.chart_range[1]-tab.chart_range[0], narrowed[1]-narrowed[0])
        narrowed = list(tab.chart_range)
        self.click("timelineNext")
        self.assertGreaterEqual(tab.chart_range[0], narrowed[0])
        self.assertEqual(tab.chart_range[1]-tab.chart_range[0], narrowed[1]-narrowed[0])
        self.controller.setResultListing("object", "long")
        saved = capture_analysis(self.controller.path, self.controller.workspace, "Navigator")
        prepared, _ = prepare_analysis(self.controller.project, self.controller.path, saved)
        self.assertEqual(prepared[0][0]["chart_range"], tab.chart_range)
        self.controller.project.analysis_workspace = [saved]
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(self.controller.restoreAnalysis(0))
        self.assertEqual(self.controller.workspace.active.chart_range, saved["cards"][0]["chart_range"])
        self.assertEqual(self.controller.workspace.active.listing, "object")
        self.click("timelineReset")
        self.assertEqual(self.controller.state["chartRange"]["last"], 71)
        self.assertTrue(self.controller.workspace.active.frame.equals(original))
        self.visual_item("timelineLeftHandle").forceActiveFocus()
        QTest.keyClick(self.root, Qt.Key.Key_Right)
        QTest.qWait(200)
        self.assertEqual(self.controller.state["chartRange"]["first"], 1)
        self.assertEqual(self.warnings, [])

    def test_pinned_queries_keep_aggregation_and_zoom_independent(self):
        self.click("executeQuery")
        first = self.controller.workspace.active
        self.controller.pinQueryTab(first.id)
        self.assertTrue(self.controller.setChartRange(30, 40))
        self.set_choice("queryResolution", "daily")
        self.click("executeQuery")
        second = self.controller.workspace.active
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(len(second.frame), 3)
        self.controller.selectQueryTab(first.id)
        self.assertEqual(self.controller.state["chartRange"]["first"], 30)
        self.assertEqual(first.criteria.get("aggregation"), None)
        self.assertFalse(self.controller.setChartRange(-1, 5))
        self.assertEqual(self.warnings, [])

    def test_themes_minimum_size_and_reporting_checkboxes(self):
        self.click("executeQuery")
        self.click("chartsViewToggle")
        for mode in ["Light", "Dark"]:
            self.appearance.setMode(mode)
            self.root.setWidth(1140); self.root.setHeight(760)
            QTest.qWait(100)
            navigator = self.visual_item("chartTimelineNavigator")
            bounds = navigator.mapRectToScene(navigator.boundingRect())
            self.assertGreater(bounds.width(), 300)
            self.assertLessEqual(bounds.right(), self.root.width())
            self.assertLessEqual(bounds.bottom(), self.root.height())
            output = os.environ.get("STUDIO_TEMPORAL_EVIDENCE")
            if output:
                Path(output).mkdir(parents=True, exist_ok=True)
                self.root.grabWindow().save(str(Path(output) / f"navigator-{mode.lower()}.png"))
                self.root.setWidth(1440); self.root.setHeight(920)
                QTest.qWait(100)
                self.root.grabWindow().save(str(Path(output) / f"navigator-{mode.lower()}-normal.png"))
        self.evaluate(self.root, "page=4")
        QTest.qWait(60)
        page = self.visual_item("runPage")
        self.evaluate(page, "contentItem.contentY=100")
        QTest.qWait(60)
        self.click("reportResolution-daily")
        reports = self.visual_item("reportingSettings")
        self.assertIn("daily", json.loads(reports.property("specification")))
        self.assertEqual(self.warnings, [])
