"""Exercise the actual QML controls, not just Python query helpers."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
import pandas as pd
from unittest.mock import patch
import json

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from energy_gui.schema import registry  # Match the application startup order.
from PySide6.QtCore import QObject, QPoint, QPointF, QSettings, Qt, QUrl
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from energy_gui.appearance import Appearance
from energy_gui.controller import Controller
from energy_gui.demo_library import make_demo
from energy_gui.safety import RecoveryStore
from energy_gui.storage import load_project, save_project
from test_network_view import overlay_fixture
from energy_gui.object_edits import rename_candidate


class QmlControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        QQuickStyle.setStyle("Basic")
        if sys.platform == "win32":
            QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / "segoeui.ttf"))

    def setUp(self):
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        self.temp = tempfile.TemporaryDirectory(prefix="qml_test_", dir=preferred)
        self.appearance = Appearance(QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat))
        # Matrix runs start every legacy interaction test in an explicit theme.
        # The temporary INI still isolates all preference writes from user settings.
        if os.environ.get("PYPSA_TEST_THEME") in {"Light", "Dark"}:
            self.appearance._mode = os.environ["PYPSA_TEST_THEME"]
        self.controller = Controller()
        self.engine = QQmlApplicationEngine()
        self.engine.rootContext().setContextProperty("appearance", self.appearance)
        self.engine.rootContext().setContextProperty("backend", self.controller)
        self.warnings = []
        self.engine.warnings.connect(lambda warnings: self.warnings.extend(str(w) for w in warnings))
        self.engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / "energy_gui" / "qml" / "Main.qml")))
        self.assertTrue(self.engine.rootObjects(), self.warnings)
        self.root = self.engine.rootObjects()[0]
        self.root.requestActivate()
        QTest.qWait(80)

    def tearDown(self):
        self.controller.dirty = False
        self.controller.workspace.clear()
        self.controller.discardSheet()
        self.controller.discardSettingsDraft()
        self.controller.discardCsvDraft()
        self.controller._reset_draft()
        self.root.close()
        self.engine.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def evaluate(self, item, expression):
        code = QQmlExpression(self.engine.rootContext(), item, expression)
        result, _ = code.evaluate()
        self.assertFalse(code.hasError(), code.error().toString())
        return result

    def visual_item(self, name, parent=None):
        # Repeater delegates have visual parents, not necessarily QObject parents.
        parent = parent or self.root.contentItem()
        if parent.objectName() == name:
            return parent
        for child in parent.childItems():
            found = self.visual_item(name, child)
            if found is not None:
                return found
        return None

    def test_light_dark_and_popup_highlight_have_explicit_contrast(self):
        select = self.root.findChild(QObject, "themeSelect")
        for mode in ["Light", "Dark"]:
            self.appearance.setMode(mode)
            QTest.qWait(40)
            select.forceActiveFocus()
            # Popup delegates have a visual parent but are not QObject children
            # of ComboBox. Address the actual ListView delegate through QML.
            expression = QQmlExpression(self.engine.rootContext(), select, "popup.open()")
            expression.evaluate()
            self.assertFalse(expression.hasError())
            QTest.qWait(40)
            expression = QQmlExpression(self.engine.rootContext(), select, "popup.contentItem.itemAtIndex(1)")
            option, _ = expression.evaluate()
            self.assertIsNotNone(option, "Popup delegate must be instantiated.")
            expression = QQmlExpression(self.engine.rootContext(), option, "mapToItem(null, width/2, height/2)")
            point, _ = expression.evaluate()
            # Reset the pointer between windows/modes: moving to the same cached
            # position need not deliver a new hover event in the offscreen plugin.
            QTest.mouseMove(self.root, QPoint(2, 2))
            QTest.qWait(30)
            QTest.mouseMove(self.root, QPoint(round(point.x()), round(point.y())))
            QTest.qWait(100)
            self.assertTrue(option.property("hovered"), "The test must exercise actual mouse hover.")
            foreground = option.property("contentItem").property("color")
            background = option.property("background").property("color")
            self.assertEqual(foreground, QColor(self.evaluate(self.root, "appTheme.primaryText.toString()")))
            self.assertEqual(background, QColor(self.evaluate(self.root, "appTheme.primary.toString()")))
            QTest.keyClick(self.root, Qt.Key.Key_Escape)
        self.assertEqual(self.warnings, [])

    def test_ribbon_menu_highlight_contrast_for_pointer_keyboard_and_disabled_items(self):
        for mode in ["Light", "Dark"]:
            self.appearance.setMode(mode)
            for button_name, menu_name in [
                ("ribbonFile", "ribbonFileMenu"), ("ribbonModel", "ribbonModelMenu"),
                ("ribbonData", "ribbonDataMenu"), ("ribbonSolve", "ribbonSolveMenu"),
                ("ribbonHelp", "ribbonHelpMenu"),
            ]:
                button = self.visual_item(button_name)
                QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=button.mapToScene(button.boundingRect().center()).toPoint())
                QTest.qWait(40)
                menu = self.root.findChild(QObject, menu_name)
                self.assertTrue(menu.property("visible"))
                option = self.evaluate(menu, "itemAt(0)")
                QTest.mouseMove(self.root, QPoint(2, 2))
                QTest.qWait(30)
                QTest.mouseMove(self.root, option.mapToScene(option.boundingRect().center()).toPoint())
                QTest.qWait(40)
                self.assertTrue(option.property("hovered"))
                self.assertEqual(option.property("contentItem").property("color"), QColor(self.evaluate(self.root, "appTheme.primaryText.toString()")), (mode, menu_name))
                self.assertEqual(option.property("background").property("color"), QColor(self.evaluate(self.root, "appTheme.primary.toString()")))
                QTest.mouseMove(self.root, QPoint(2, 2))
                self.evaluate(menu, "currentIndex = -1")
                menu.forceActiveFocus(Qt.FocusReason.OtherFocusReason)
                QTest.keyClick(self.root, Qt.Key.Key_Down)
                QTest.qWait(30)
                self.assertTrue(option.property("highlighted"))
                self.assertEqual(option.property("contentItem").property("color"), QColor(self.evaluate(self.root, "appTheme.primaryText.toString()")))
                self.assertEqual(option.property("background").property("color"), QColor(self.evaluate(self.root, "appTheme.primary.toString()")))
                if menu_name == "ribbonDataMenu":
                    disabled = self.evaluate(menu, "itemAt(4)")
                    self.assertFalse(disabled.property("enabled"))
                    self.assertNotEqual(disabled.property("contentItem").property("color"), disabled.property("background").property("color"))
                QTest.keyClick(self.root, Qt.Key.Key_Escape)
                QTest.qWait(30)
        self.assertEqual(self.warnings, [])

    def test_atlas_semantic_palette_contrast_in_light_and_dark(self):
        def luminance(color):
            channels = [color.redF(), color.greenF(), color.blueF()]
            linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
                      for value in channels]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

        def contrast(foreground, background):
            high, low = sorted([luminance(QColor(foreground)), luminance(QColor(background))], reverse=True)
            return (high + 0.05) / (low + 0.05)

        for mode in ["Light", "Dark"]:
            self.appearance.setMode(mode)
            QTest.qWait(30)
            colors = {
                name: self.evaluate(self.root, f"appTheme.{name}.toString()")
                for name in [
                    "window", "panel", "sidebar", "field", "alternate", "selected",
                    "ink", "muted", "accent", "primary", "primaryHover", "primaryText",
                    "warning", "danger",
                ]
            }
            for surface in ["window", "panel", "sidebar", "field", "alternate", "selected"]:
                self.assertGreaterEqual(contrast(colors["ink"], colors[surface]), 4.5, (mode, "ink", surface))
            for surface in ["window", "panel", "field"]:
                for role in ["muted", "accent", "warning", "danger"]:
                    self.assertGreaterEqual(contrast(colors[role], colors[surface]), 4.5, (mode, role, surface))
            for role in ["primary", "primaryHover"]:
                self.assertGreaterEqual(contrast(colors["primaryText"], colors[role]), 4.5, (mode, role))
            chart = self.evaluate(self.root, "appTheme.chartColors")
            chart = chart.toVariant() if hasattr(chart, "toVariant") else chart
            self.assertGreaterEqual(len(chart), 6)
            self.assertEqual(len({QColor(color).name() for color in chart}), len(chart))
        self.assertEqual(self.warnings, [])

    def test_unapplied_inspector_edits_block_navigation_and_discard_restores(self):
        self.controller.loadDemo()
        self.controller.selectType("Generator")
        self.controller.selectObject("Thermal")
        self.root.setProperty("page", 1)
        QTest.qWait(40)
        editor = self.root.findChild(QObject, "objectJsonEditor")
        attributes = json.loads(editor.property("text"))
        attributes["p_nom"] = 999
        editor.setProperty("text", json.dumps(attributes))
        self.assertEqual(self.controller._draft_name, "Thermal")
        self.assertTrue(self.controller._has_draft())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.root.navigatePage(4)
        self.assertEqual(self.root.property("page"), 1)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.root.navigatePage(4)
        self.assertEqual(self.root.property("page"), 4)
        self.assertEqual(json.loads(editor.property("text"))["p_nom"], 150)
        self.assertEqual(self.controller.project.object("Generator", "Thermal")["attributes"]["p_nom"], 150)
        self.assertEqual(self.warnings, [])

    def test_project_settings_draft_survives_refresh_and_guards_ribbon_navigation(self):
        self.controller.loadDemo()
        field = self.root.findChild(QObject, "projectNameInput")
        field.setProperty("text", "Draft project name")
        self.assertTrue(self.controller.helperState["settingsDirty"])
        self.controller.changed.emit()
        self.assertEqual(field.property("text"), "Draft project name")
        tab = self.visual_item("ribbonPage-1")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=tab.mapToScene(tab.boundingRect().center()).toPoint())
        self.assertEqual(self.root.property("page"), 0)
        self.assertNotEqual(self.controller.project.name, "Draft project name")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save):
            QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=tab.mapToScene(tab.boundingRect().center()).toPoint())
        self.assertEqual(self.root.property("page"), 1)
        self.assertEqual(self.controller.project.name, "Draft project name")
        self.assertFalse(self.controller.helperState["settingsDirty"])
        self.assertEqual(self.warnings, [])

    def test_rename_and_cross_category_bulk_delete_through_real_controls(self):
        self.controller.loadDemo()
        self.controller.selectType("Generator")
        self.controller.selectObject("Solar")
        self.root.setProperty("page", 1)
        QTest.qWait(50)
        def click(name):
            item = self.visual_item(name)
            self.assertIsNotNone(item, name)
            QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=item.mapToScene(item.boundingRect().center()).toPoint())
            QTest.qWait(30)
        with patch.object(QInputDialog, "getText", return_value=("PV 001", True)), patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            click("renameObject")
        self.assertEqual(self.controller.selected, "PV 001")
        self.assertIsNotNone(self.controller.project.object("Generator", "PV 001"))
        self.assertTrue(any(p["name"] == "PV 001" for p in self.controller.project.profiles))
        click("deleteMark-Thermal")
        click("deleteMark-City peaker")
        self.controller.selectType("Carrier")
        QTest.qWait(40)
        click("deleteMark-coal")
        before = self.controller.project.to_dict()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            click("deleteSelectedObjects")
        self.assertEqual(self.controller.project.to_dict(), before)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            click("deleteSelectedObjects")
        self.assertIsNone(self.controller.project.object("Carrier", "coal"))
        self.assertIsNone(self.controller.project.object("Generator", "Thermal"))
        self.assertIsNotNone(self.controller.project.object("Generator", "PV 001"))
        self.assertEqual(self.warnings, [])

    def test_csv_helper_mapping_survives_notifications_and_navigation_cancel(self):
        self.controller.loadDemo()
        self.root.setProperty("page", 2)
        component = self.root.findChild(QObject, "profileComponentSelect")
        self.evaluate(component, "currentIndex = model.indexOf('Load'); activated(currentIndex)")
        path = Path(self.temp.name) / "draft.csv"
        pd.DataFrame({"time": self.controller.project.snapshots, "unused": [0.] * 24, "power": [23.] * 24}).to_csv(path, index=False)
        self.controller.previewCsv(str(path))
        attribute = self.root.findChild(QObject, "profilePropertySelect")
        self.evaluate(attribute, "currentIndex = model.indexOf('p_set'); activated(currentIndex)")
        value = self.root.findChild(QObject, "csvValueSelect")
        self.evaluate(value, "currentIndex = model.indexOf('power'); activated(currentIndex)")
        before = self.controller.project.to_dict()
        self.controller.changed.emit()
        QTest.qWait(40)
        self.assertEqual(component.property("currentText"), "Load")
        self.assertEqual(value.property("currentText"), "power")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.root.navigatePage(0)
        self.assertEqual(self.root.property("page"), 2)
        self.assertEqual(self.controller.project.to_dict(), before)
        self.assert_f1_help_after_focus(attribute, "Load", "p_set")
        button = self.visual_item("importCsvDraft")
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=button.mapToScene(button.boundingRect().center()).toPoint())
        profile = next(p for p in self.controller.project.profiles if p["component"] == "Load")
        self.assertEqual(profile["values"], [23.] * 24)
        self.assertFalse(self.controller.helperState["csvDirty"])
        self.assertEqual(self.warnings, [])

    def assert_f1_help_after_focus(self, item, component, attribute):
        item.forceActiveFocus()
        self.assert_f1_help(component, attribute)

    def test_demo_library_choice_loads_twenty_buses_without_running_solver(self):
        self.root.resize(1140, 760)
        button = self.visual_item("openDemoLibrary")
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=button.mapToScene(button.boundingRect().center()).toPoint())
        QTest.qWait(40)
        listing = self.root.findChild(QObject, "demoModelList")
        self.assertEqual(listing.property("count"), 7)
        self.evaluate(listing, "positionViewAtEnd()")
        QTest.qWait(50)
        option = self.visual_item("demoModel-regional20")
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=option.mapToScene(option.boundingRect().center()).toPoint())
        load = self.visual_item("demoLoadSelected")
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=load.mapToScene(load.boundingRect().center()).toPoint())
        QTest.qWait(70)
        self.assertFalse(self.root.findChild(QObject, "demoLibrary").property("visible"))
        self.assertEqual(self.controller.state["busCount"], 20)
        self.assertEqual(self.controller.project.demo_info["id"], "regional20")
        self.assertIsNone(self.controller.process)
        self.assertIsNone(self.controller.path)
        self.root.setProperty("page", 3)
        QTest.qWait(60)
        view = self.root.findChild(QObject, "networkView")
        view.fitView()
        QTest.qWait(60)
        viewport = self.root.findChild(QObject, "networkViewport")
        for obj in self.controller.networkState["topology"]["objects"]:
            node = self.visual_item("networkObject-" + obj["kind"] + "-" + obj["name"])
            point = node.mapToItem(viewport,node.boundingRect().center())
            self.assertGreaterEqual(point.y(), 0)
            self.assertLessEqual(point.y(), viewport.height())
        self.assertEqual(self.warnings, [])

    def test_file_menu_backup_and_recovery_commands_work_with_real_clicks(self):
        self.controller.loadDemo()
        self.controller.path = Path(self.temp.name) / "original.sqlite"
        self.assertTrue(self.controller.saveProject())
        original = self.controller.path.read_bytes()
        directory = Path(self.temp.name) / "recovery"
        inactive = RecoveryStore(directory)
        inactive.capture(make_demo("regional20"), self.controller.path)
        inactive.close()
        self.controller.enableRecovery(directory)
        archive = Path(self.temp.name) / "backup.zip"
        try:
            for mode in ["Light", "Dark"]:
                self.appearance.setMode(mode)
                button = self.visual_item("ribbonFile")
                QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=button.mapToScene(button.boundingRect().center()).toPoint())
                QTest.qWait(40)
                backup = self.root.findChild(QObject, "backupProjectCommand")
                self.assertTrue(backup.isVisible())
                with patch.object(QFileDialog, "getSaveFileName", return_value=(str(archive), "ZIP")):
                    QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=backup.mapToScene(backup.boundingRect().center()).toPoint())
                self.assertTrue(archive.exists())
                QTest.keyClick(self.root, Qt.Key.Key_Escape)  # Dismiss the backup-success notice.
                QTest.qWait(60)
                archive = archive.with_name("dark-backup.zip")
            button = self.visual_item("ribbonFile")
            QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=button.mapToScene(button.boundingRect().center()).toPoint())
            QTest.qWait(40)
            recover = self.root.findChild(QObject, "recoverProjectCommand")
            with patch.object(QInputDialog, "getItem", return_value=(inactive.path.name, True)), patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=recover.mapToScene(recover.boundingRect().center()).toPoint())
            self.assertEqual(self.controller.state["busCount"], 20)
            self.assertTrue(self.controller.dirty)
            self.assertIsNone(self.controller.path)
            self.assertEqual((Path(self.temp.name) / "original.sqlite").read_bytes(), original)
            self.assertEqual(self.warnings, [])
            QTest.keyClick(self.root, Qt.Key.Key_Escape)
        finally:
            self.controller._recovery_timer.stop()
            self.controller.recovery_store.close()

    def test_model_undo_redo_menu_clicks_preserve_previous_gui_workflow(self):
        self.controller.loadDemo()
        self.assertTrue(self.controller.storeObject("Extra bus", '{"v_nom":110}'))
        for mode in ["Light", "Dark"]:
            self.appearance.setMode(mode)
            for index, count in [(7, 3), (8, 4)]:
                button = self.visual_item("ribbonData")
                QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=button.mapToScene(button.boundingRect().center()).toPoint())
                QTest.qWait(40)
                menu = self.root.findChild(QObject, "ribbonDataMenu")
                command = self.evaluate(menu, f"itemAt({index})")
                self.assertTrue(command.property("enabled"))
                self.assertIn("Create Bus", command.property("text"))
                QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=command.mapToScene(command.boundingRect().center()).toPoint())
                QTest.qWait(60)
                self.assertEqual(self.controller.state["busCount"], count)
                self.assertTrue(self.controller.dirty)
        self.assertEqual(self.warnings, [])

    def study_click(self, name):
        item=self.visual_item(name)
        self.assertIsNotNone(item,name)
        QTest.mouseClick(self.root,Qt.MouseButton.LeftButton,pos=item.mapToScene(item.boundingRect().center()).toPoint())
        QTest.qWait(60)

    def test_study_tools_actual_menu_tabs_advanced_apply_and_undo(self):
        self.controller.loadDemo()
        self.root.resize(1140,760)
        self.study_click("ribbonSolve")
        menu=self.root.findChild(QObject,"ribbonSolveMenu")
        item=self.evaluate(menu,"itemAt(7)")
        QTest.mouseClick(self.root,Qt.MouseButton.LeftButton,pos=item.mapToScene(item.boundingRect().center()).toPoint())
        QTest.qWait(70)
        dialog=self.root.findChild(QObject,"studyTools")
        self.assertTrue(dialog.property("visible"))
        for mode in ["Light","Dark"]:
            self.appearance.setMode(mode)
            for i in range(5):
                self.study_click("studyTab"+str(i))
                self.assertEqual(self.root.findChild(QObject,"studySections").property("currentIndex"),i)
            for field in ["analysisName", "gridProfileName"]:
                self.assertEqual(
                    self.evaluate(self.root.findChild(QObject, field), "placeholderTextColor.toString()"),
                    self.evaluate(dialog, "theme.muted.toString()"),
                )
        self.study_click("studyTab2")
        editor=self.root.findChild(QObject,"advancedInputsEditor")
        data=json.loads(editor.property("text"))
        data["weights"]=[dict(objective=2,stores=1,generators=1)]*24
        editor.setProperty("text",json.dumps(data))
        self.study_click("applyAdvancedButton")
        self.assertEqual(self.controller.project.advanced_inputs["weights"][0]["objective"],2)
        dialog.close()
        self.assertTrue(self.controller.modelHistory(False))
        self.assertEqual(self.controller.project.advanced_inputs,{})
        self.assertEqual(self.warnings,[])

    def test_study_saved_dashboard_buttons_restore_chart_view(self):
        run=Path(self.temp.name)/"runs"/"study"
        project,_=overlay_fixture(run)
        self.controller.project=project
        self.controller.path=Path(self.temp.name)/"project.sqlite"
        self.controller._reset_helpers();self.controller._reset_draft()
        self.assertTrue(self.controller.saveProject())
        self.assertTrue(self.controller.openRun(str(run)))
        self.assertTrue(self.controller.queryResults("Line",["L"],["p0"],"",""))
        self.assertTrue(self.controller.setChartType("p0","dot"))
        self.controller.setAnalysisView(1)
        self.root.openStudyTools();QTest.qWait(60)
        self.root.findChild(QObject,"analysisName").setProperty("text","Saved flow study")
        self.study_click("saveAnalysisButton")
        self.assertEqual(self.root.findChild(QObject,"savedAnalysisList").property("count"),1)
        with patch.object(QMessageBox,"question",return_value=QMessageBox.StandardButton.Yes):
            self.study_click("restoreAnalysis-0")
        self.assertEqual(self.controller.workspace.active.chart_types,{"p0":"dot"})
        self.assertEqual(self.root.findChild(QObject,"resultsExplorer").property("resultView"),1)
        self.study_click("studyTab1")
        self.study_click("compareRunsButton")
        self.assertEqual(self.controller._comparison_frame["delta_right_minus_left"].tolist(), [0, 0])
        self.assertIn("delta_right_minus_left", self.root.findChild(QObject, "comparisonReadout").property("text"))
        self.root.findChild(QObject,"studyTools").close()
        self.assertEqual(self.warnings,[])

    def test_study_profile_grid_apply_and_project_replacement_clear_old_draft(self):
        self.controller.loadDemo()
        self.root.openStudyTools();QTest.qWait(60)
        self.study_click("studyTab3")
        self.root.findChild(QObject,"gridProfileName").setProperty("text","City demand")
        self.study_click("loadProfileGridButton")
        editor=self.root.findChild(QObject,"profileGridEditor")
        lines=editor.property("text").splitlines()
        lines[1]=lines[1].split("\t")[0]+"\t42"
        editor.setProperty("text","\n".join(lines))
        self.study_click("applyProfileGridButton")
        entry=next(p for p in self.controller.project.profiles if p["component"]=="Load")
        self.assertEqual(entry["values"][0],42)
        self.root.findChild(QObject,"studyTools").close()
        with patch.object(QMessageBox,"question",return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(self.controller.loadDemoModel("campus6"))
        self.root.openStudyTools();QTest.qWait(60)
        self.assertEqual(editor.property("text"),"")
        self.root.findChild(QObject,"studyTools").close()
        self.assertEqual(self.warnings,[])

    def test_demo_library_cancelled_replacement_retains_original_and_dialog(self):
        self.controller.loadDemo()
        before = self.controller.project.to_dict()
        self.root.openDemoLibrary()
        QTest.qWait(40)
        option = self.visual_item("demoModel-congestion2")
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=option.mapToScene(option.boundingRect().center()).toPoint())
        load = self.visual_item("demoLoadSelected")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=load.mapToScene(load.boundingRect().center()).toPoint())
        self.assertTrue(self.root.findChild(QObject, "demoLibrary").property("visible"))
        self.assertEqual(self.controller.project.to_dict(), before)
        QTest.keyClick(self.root, Qt.Key.Key_Escape)
        self.assertEqual(self.warnings, [])

    def test_twenty_bus_frozen_fit_contains_whole_nodes_at_minimum_size(self):
        # A read-only artifact fixture exercises frozen geometry without another
        # solver run. Numerical port values are checked by the demo solve suite.
        project = make_demo("regional20")
        run = Path(self.temp.name) / "runs" / "large-layout"
        (run / "tables").mkdir(parents=True)
        save_project(project, run / "inputs.sqlite")
        catalog = []
        for kind in sorted({r["component"] for r in project.objects}):
            rows = [{"name": r["name"], **r["attributes"]}
                    for r in project.objects if r["component"] == kind]
            filename = kind + ".csv"
            pd.DataFrame(rows).to_csv(run / "tables" / filename, index=False)
            catalog.append(dict(component=kind, kind="static", attribute="static properties", file=filename))
        (run / "catalog.json").write_text(json.dumps(catalog))
        (run / "run_config.json").write_text(json.dumps(dict(project_id=project.project_id, status="succeeded")))
        self.controller.project = project
        self.controller.path = Path(self.temp.name) / "model.sqlite"
        self.controller._reset_helpers()
        self.controller._reset_draft()
        self.assertTrue(self.controller.loadNetworkRun(str(run)))
        self.root.setProperty("page", 3)
        view = self.root.findChild(QObject, "networkView")
        viewport = self.root.findChild(QObject, "networkViewport")
        for mode in ["Light", "Dark"]:
            self.appearance.setMode(mode)
            self.root.resize(1140, 760)
            QTest.qWait(80)
            view.fitView()
            QTest.qWait(80)
            for obj in self.controller.networkState["topology"]["objects"]:
                node = self.visual_item("networkObject-" + obj["kind"] + "-" + obj["name"])
                bounds = node.mapRectToItem(viewport, node.boundingRect())
                self.assertGreaterEqual(bounds.left(), 0, obj["key"])
                self.assertGreaterEqual(bounds.top(), 0, obj["key"])
                self.assertLessEqual(bounds.right(), viewport.width(), obj["key"])
                self.assertLessEqual(bounds.bottom(), viewport.height(), obj["key"])
        # The smaller Fit zoom must remain explicitly saveable and reopenable.
        button = self.visual_item("networkSaveLayout")
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=button.mapToScene(button.boundingRect().center()).toPoint())
        saved = load_project(self.controller.path).schematic_layouts["run:large-layout"]
        self.assertAlmostEqual(saved["zoom"], view.property("zoomFactor"))
        self.assertEqual(self.warnings, [])

    def test_network_topology_icons_drag_and_ctrl_click_inspector(self):
        self.controller.loadDemo()
        topology = self.controller.state["topology"]
        self.assertEqual(len(topology["buses"]), 3)
        self.assertEqual(len(topology["edges"]), 3)
        self.root.setProperty("page", 3)
        QTest.qWait(80)
        network = self.root.findChild(QObject, "networkView")
        self.assertEqual(set(network.property("iconTypes").toVariant()), set(registry()))
        visible_objects = [o for o in self.controller.project.objects if o["component"] != "Carrier"]
        self.assertEqual(len(topology["objects"]), len(visible_objects))
        self.assertEqual(len(topology["wires"]), 10)
        frozen = json.dumps(self.controller.project.objects)
        for kind, name in [("Bus", "North"), ("Generator", "Thermal"), ("Line", "North-City")]:
            # Branches and attached assets have exactly the same drag/inspect gesture.
            record = next((o for o in topology["objects"] if o["kind"] == kind and o["name"] == name), None)
            if record is None:
                record = next(o for o in topology["objects"] if o["kind"] == kind)
                name = record["name"]
            node = self.visual_item("networkObject-" + kind + "-" + name)
            self.assertIsNotNone(node)
            point = node.mapToScene(node.boundingRect().center()).toPoint()
            QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=point)
            self.assertEqual(self.root.property("page"), 3, "Ordinary clicks must not open properties.")
            old = (node.x(), node.y())
            QTest.mousePress(self.root, Qt.MouseButton.LeftButton, pos=point)
            QTest.mouseMove(self.root, point + QPoint(20, 10), 20)
            QTest.mouseMove(self.root, point + QPoint(80, 45), 20)
            QTest.mouseRelease(self.root, Qt.MouseButton.LeftButton, pos=point + QPoint(80, 45))
            QTest.qWait(30)
            self.assertGreater(node.x(), old[0] + 20)
            self.assertGreater(node.y(), old[1] + 10)
            moved = network.property("positions").toVariant()[record["key"]]
            self.assertAlmostEqual(moved["x"], node.x()+node.width()/2)
            point = node.mapToScene(node.boundingRect().center()).toPoint()
            QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, point)
            QTest.qWait(30)
            self.assertEqual(self.root.property("page"), 1)
            self.assertEqual(self.controller.component, kind)
            self.assertEqual(self.controller.selected, name)
            self.root.setProperty("page", 3)
            QTest.qWait(30)
            self.assertEqual(network.property("positions").toVariant()[record["key"]], moved)
        self.assertEqual(json.dumps(self.controller.project.objects), frozen)
        network.arrange(True)
        QTest.qWait(30)
        for record in topology["objects"]:
            node = self.visual_item("networkObject-" + record["kind"] + "-" + record["name"])
            position = network.property("positions").toVariant()[record["key"]]
            self.assertAlmostEqual(node.x()+node.width()/2, position["x"])
            self.assertAlmostEqual(node.y()+node.height()/2, position["y"])
        self.assertEqual(self.warnings, [])

    def test_network_saved_layout_reopens_and_reset_is_explicit(self):
        self.controller.loadDemo()
        self.controller.path = Path(self.temp.name) / "layout.sqlite"
        self.root.setProperty("page", 3)
        QTest.qWait(70)
        view = self.root.findChild(QObject, "networkView")
        viewport = self.root.findChild(QObject, "networkViewport")
        key = json.dumps(["Bus", "North"])
        view.moveObject(key, 400, 200)
        view.setProperty("zoomFactor", 1.8)
        viewport.setProperty("contentX", 40)
        viewport.setProperty("contentY", 20)
        before = json.dumps(self.controller.project.objects)
        save = self.visual_item("networkSaveLayout")
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=save.mapToScene(save.boundingRect().center()).toPoint())
        QTest.qWait(70)
        self.assertFalse(view.property("layoutPending"))
        self.assertEqual(load_project(self.controller.path).schematic_layouts["current"]["positions"][key], {"x": 400, "y": 200})
        path = str(self.controller.path)
        view.moveObject(key, 500, 300)  # A session-only change must not override a reopened file.
        with patch.object(QFileDialog, "getOpenFileName", return_value=(path, "SQLite")):
            self.controller.openProject()
        QTest.qWait(100)
        self.assertEqual(view.property("positions").toVariant()[key], {"x": 400, "y": 200})
        self.assertAlmostEqual(view.property("zoomFactor"), 1.8)
        self.assertAlmostEqual(viewport.property("contentX"), 40)
        self.assertAlmostEqual(viewport.property("contentY"), 20)
        reset = self.visual_item("networkResetLayout")
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=reset.mapToScene(reset.boundingRect().center()).toPoint())
        self.assertEqual(view.property("zoomFactor"), 1)
        self.assertTrue(view.property("layoutPending"))
        self.assertEqual(load_project(path).schematic_layouts["current"]["zoom"], 1.8, "Reset alone must not overwrite a saved layout.")
        self.assertEqual(json.dumps(self.controller.project.objects), before)
        self.assertEqual(self.warnings, [])

    def test_network_flow_controls_snapshot_labels_details_and_live_isolation(self):
        run = Path(self.temp.name) / "runs" / "network-reference"
        project, _ = overlay_fixture(run)
        self.controller.project = project
        self.controller.path = Path(self.temp.name) / "model.sqlite"
        self.controller._reset_helpers()
        self.controller._reset_draft()
        self.controller.changed.emit()
        self.root.setProperty("page", 3)
        QTest.qWait(80)
        button = self.visual_item("networkLoadFlows")
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=button.mapToScene(button.boundingRect().center()).toPoint())
        QTest.qWait(80)
        self.assertTrue(self.controller.networkState["frozen"])
        snapshot = self.root.findChild(QObject, "networkSnapshotSelect")
        snapshot.forceActiveFocus()
        QTest.keyClick(self.root, Qt.Key.Key_Down)
        QTest.qWait(80)
        self.assertEqual(self.controller.networkState["snapshotIndex"], 1)
        self.assertEqual(snapshot.property("currentIndex"), 1)
        key = json.dumps(["Line", "L"])
        label = self.visual_item("flowLabel-"+key+"-bus0")
        self.assertIn("-8.0 MW", self.evaluate(label, "children[0].text"))
        view = self.root.findChild(QObject, "networkView")
        view.moveObject(key, 350, 180)
        node = self.visual_item("networkObject-Line-L")
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=node.mapToScene(node.boundingRect().center()).toPoint())
        QTest.qWait(40)
        details = self.root.findChild(QObject, "networkObjectDetails")
        self.assertIn("-8.000 MW", details.property("text"))
        self.assertTrue(details.property("readOnly"))
        self.controller.project, _ = rename_candidate(self.controller.project, "Bus", "A", "New A")
        self.controller.changed.emit()
        QTest.qWait(40)
        self.assertIsNotNone(self.visual_item("networkObject-Bus-A"))
        self.assertIsNone(self.visual_item("networkObject-Bus-New A"))
        for mode in ["Light", "Dark"]:
            self.appearance.setMode(mode)
            self.root.resize(1140, 760)
            QTest.qWait(40)
            viewport = self.root.findChild(QObject, "networkViewport")
            self.assertGreater(viewport.height(), 100)
            fit = self.visual_item("networkFitView")
            QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=fit.mapToScene(fit.boundingRect().center()).toPoint())
            QTest.qWait(60)
            for obj in self.controller.networkState["topology"]["objects"]:
                node = self.visual_item("networkObject-" + obj["kind"] + "-" + obj["name"])
                center = node.mapToItem(viewport, node.boundingRect().center())
                self.assertGreaterEqual(center.y(), 0)
                self.assertLessEqual(center.y(), viewport.height())
            self.assertIn("NOT AC MVA", self.root.findChild(QObject, "networkSourceCaption").property("text"))
        button = self.visual_item("networkLiveView")
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=button.mapToScene(button.boundingRect().center()).toPoint())
        QTest.qWait(80)
        self.assertFalse(self.controller.networkState["frozen"])
        self.assertIsNotNone(self.visual_item("networkObject-Bus-New A"))
        self.assertEqual(self.warnings, [])

    def test_network_carrier_badges_replace_nodes_and_follow_asset_drags(self):
        self.controller.loadDemo()
        self.root.setProperty("page", 3)
        QTest.qWait(80)
        network = self.root.findChild(QObject, "networkView")
        for carrier in ["AC", "coal", "solar"]:
            self.assertIsNone(self.visual_item("networkObject-Carrier-" + carrier))
            self.assertNotIn(json.dumps(["Carrier", carrier]), network.property("positions").toVariant())
        for kind, name, carrier in [("Bus", "North", "AC"), ("Generator", "Thermal", "coal"), ("Generator", "Solar", "solar")]:
            badge = self.visual_item("carrierBadge-" + kind + "-" + name)
            self.assertTrue(badge.isVisible())
            self.assertEqual(self.evaluate(badge, "children[0].text"), carrier)
        self.assertFalse(self.visual_item("carrierBadge-Load-City demand").isVisible(), "Do not infer a demand label from its bus.")
        badge = self.visual_item("carrierBadge-Generator-Thermal")
        node = self.visual_item("networkObject-Generator-Thermal")
        before = self.controller.project.to_dict()
        start = badge.mapToScene(badge.boundingRect().center()).toPoint()
        old = node.x()
        QTest.mousePress(self.root, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(self.root, start + QPoint(20, 0), 20)
        QTest.mouseMove(self.root, start + QPoint(100, 0), 20)
        QTest.mouseRelease(self.root, Qt.MouseButton.LeftButton, pos=start + QPoint(100, 0))
        QTest.qWait(30)
        self.assertGreater(node.x(), old+30)
        point = badge.mapToScene(badge.boundingRect().center()).toPoint()
        self.assertGreater(point.x(), start.x()+30)
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, point)
        QTest.qWait(30)
        self.assertEqual((self.controller.component, self.controller.selected), ("Generator", "Thermal"))
        self.assertEqual(self.root.property("page"), 1)
        self.assertEqual(self.controller.project.to_dict(), before)
        self.assertEqual(self.warnings, [])

    def test_results_tree_uses_only_defined_objects_from_saved_run(self):
        self.controller.loadDemo()
        run = Path(self.temp.name) / "saved_run"
        (run / "tables").mkdir(parents=True)
        save_project(self.controller.project, run / "inputs.sqlite")
        (run / "run_config.json").write_text(json.dumps({
            "project_id": self.controller.project.project_id, "status": "succeeded", "objective": 1,
        }))
        entries = []
        for component, names in [
            ("Generator", ["Thermal", "Solar", "City peaker", "automatic generator"]),
            ("Carrier", ["AC", "coal", "solar", "automatic carrier"]),
            ("LineType", ["standard line"]), ("TransformerType", ["standard transformer"]),
            ("SubNetwork", ["0"]),
        ]:
            filename = component + ".csv"
            prop = "p_nom_opt" if component == "Generator" else "value"
            pd.DataFrame({"name": names, prop: range(len(names)), "p_nom": 99}).to_csv(run / "tables" / filename, index=False)
            entries.append({"component": component, "kind": "static", "attribute": "static properties", "file": filename})
        (run / "catalog.json").write_text(json.dumps(entries))
        self.assertTrue(self.controller.openRun(str(run)))
        self.root.setProperty("page", 5)
        QTest.qWait(40)
        view = self.root.findChild(QObject, "resultsExplorer")
        categories = view.property("categories")
        if hasattr(categories, "toVariant"):
            categories = categories.toVariant()
        self.assertEqual({c["name"]: c["objects"] for c in categories}, {
            "Generator": ["Thermal", "Solar", "City peaker"],
        })
        view.chooseCategory("Generator")
        self.assertEqual(self.evaluate(view, "categoryInfo.objects.join(',')"), "Thermal,Solar,City peaker")
        self.assertEqual(self.evaluate(view, "categoryInfo.properties.map(p => p.name).join(',')"), "p_nom_opt")
        self.assertTrue(self.controller.queryResults("Generator", ["Thermal"], ["p_nom_opt"], "", ""))
        QTest.qWait(30)
        self.assertEqual(self.controller.resultModel.rowCount(), 1)
        self.assertEqual(self.warnings, [])

    def test_spreadsheet_real_cell_edit_apply_history_clipboard_and_navigation_guard(self):
        self.controller.loadDemo()
        self.controller.selectType("Generator")
        self.root.setProperty("page", 1)
        QTest.qWait(40)
        toggle = self.root.findChild(QObject, "objectEditorToggle")
        point = toggle.mapToScene(toggle.boundingRect().center()).toPoint()
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=point)
        QTest.qWait(60)
        view = self.root.findChild(QObject, "objectSpreadsheet")
        self.assertTrue(view.isVisible())
        column = self.controller.sheetModel.columns.index("p_nom")
        cell = self.visual_item(f"sheetCell-0-{column}")
        self.assertIsNotNone(cell)
        self.assertTrue(self.visual_item("sheetCell-0-0").property("readOnly"))
        point = cell.mapToScene(cell.boundingRect().center()).toPoint()
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=point)
        QTest.keyClick(self.root, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        for key in [Qt.Key.Key_1, Qt.Key.Key_6, Qt.Key.Key_0]:
            QTest.keyClick(self.root, key)
        QTest.keyClick(self.root, Qt.Key.Key_Tab)
        self.assertTrue(self.controller.sheetModel.dirty)
        self.assertEqual(self.controller.project.object("Generator", "Thermal")["attributes"]["p_nom"], 150)

        def click(name):
            button = self.root.findChild(QObject, name)
            QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=button.mapToScene(button.boundingRect().center()).toPoint())
            QTest.qWait(40)

        click("sheetApply")
        self.assertEqual(self.controller.project.object("Generator", "Thermal")["attributes"]["p_nom"], 160)
        click("sheetUndo")
        self.assertEqual(self.controller.project.object("Generator", "Thermal")["attributes"]["p_nom"], 150)
        click("sheetRedo")
        self.assertEqual(self.controller.project.object("Generator", "Thermal")["attributes"]["p_nom"], 160)
        self.app.clipboard().setText("name\tbus\tp_nom\nExtra\tNorth\t10\n")
        click("sheetPaste")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.root.navigatePage(4)
        self.assertEqual(self.root.property("page"), 1)
        click("sheetApply")
        self.assertIsNotNone(self.controller.project.object("Generator", "Extra"))
        self.controller.copySheet()
        self.assertIn("name\tbus", self.app.clipboard().text())
        # Inspector remains available and gets the freshly applied values.
        click("objectEditorToggle")
        self.assertFalse(view.isVisible())
        self.controller.selectObject("Thermal")
        self.assertEqual(json.loads(self.root.findChild(QObject, "objectJsonEditor").property("text"))["p_nom"], 160)
        self.assertEqual(self.warnings, [])

    def test_spreadsheet_add_column_row_validate_discard_and_copy_buttons(self):
        self.controller.loadDemo()
        self.controller.selectType("Generator")
        self.root.setProperty("page", 1)
        QTest.qWait(40)

        def click(name):
            button = self.root.findChild(QObject, name)
            self.assertTrue(button.property("enabled"), name)
            QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=button.mapToScene(button.boundingRect().center()).toPoint())
            QTest.qWait(70)

        click("objectEditorToggle")
        model = self.controller.sheetModel
        picker = self.root.findChild(QObject, "sheetColumnPicker")
        added = picker.property("currentText")
        click("sheetAddColumn")
        self.assertIn(added, model.columns)
        grid = self.root.findChild(QObject, "objectSheetTable")
        if grid.property("contentWidth") > grid.width():
            self.assertGreater(grid.property("contentX"), 0, "Offscreen additions must be revealed.")
        self.assertIsNotNone(self.visual_item("sheetCell-0-" + str(model.columns.index(added))))
        rows = model.rowCount()
        click("sheetAddRow")
        self.assertEqual(model.rowCount(), rows+1)
        self.assertIsNotNone(self.visual_item(f"sheetCell-{rows}-0"))
        click("sheetValidate")
        self.assertIn("checks passed", model.validationReport)
        click("sheetCopy")
        self.assertEqual(self.app.clipboard().text(), model.copyTsv())
        self.assertIn("Copied", model.validationReport)
        click("sheetDiscard")
        self.assertEqual(model.rowCount(), rows)
        self.assertFalse(model.dirty)
        self.assertFalse(self.root.findChild(QObject, "sheetApply").property("enabled"))
        self.assertFalse(self.root.findChild(QObject, "sheetUndo").property("enabled"))
        self.assertFalse(self.root.findChild(QObject, "sheetRedo").property("enabled"))
        self.assertEqual(self.warnings, [])

    def test_ribbon_navigation_configuration_search_checklists_and_restore(self):
        self.controller.loadDemo()
        self.root.resize(1140, 760)
        QTest.qWait(60)

        def click(name):
            item = self.visual_item(name) or self.root.findChild(QObject, name)
            self.assertIsNotNone(item, name)
            QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=item.mapToScene(item.boundingRect().center()).toPoint())
            QTest.qWait(40)

        for page in [1, 2, 3, 4, 5, 6]:
            click(f"ribbonPage-{page}")
            self.assertEqual(self.root.property("page"), page)
        config = self.root.findChild(QObject, "editorConfiguration")
        self.root.findChild(QObject, "configCategorySearch").setProperty("text", "Line")
        QTest.qWait(40)
        click("configCategory-Line")
        config.setProperty("category", "Generator")
        click("configNameOnly")
        self.root.findChild(QObject, "configPropertySearch").setProperty("text", "p_nom")
        QTest.qWait(40)
        click("configProperty-p_nom")
        click("configApply")
        self.assertNotIn("Line", [t["name"] for t in self.controller.state["visibleTypes"]])
        self.assertEqual(len([o for o in self.controller.project.objects if o["component"] == "Line"]), 3)
        click("ribbonPage-1")
        self.controller.selectType("Generator")
        self.assertEqual(self.controller.state["inputNames"], ["p_nom"])
        click("objectEditorToggle")
        self.assertEqual(self.controller.sheetModel.columns, ["name", "p_nom"])
        click("ribbonPage-6")
        click("configShowAll")
        click("configApply")
        self.assertIn("Line", [t["name"] for t in self.controller.state["visibleTypes"]])
        # Dropdowns must open and close through real pointer/keyboard events.
        for button, menu in [("ribbonFile", "ribbonFileMenu"), ("ribbonModel", "ribbonModelMenu"),
                             ("ribbonData", "ribbonDataMenu"), ("ribbonSolve", "ribbonSolveMenu")]:
            click(button)
            popup = self.root.findChild(QObject, menu)
            self.assertTrue(popup.property("visible"), menu)
            QTest.keyClick(self.root, Qt.Key.Key_Escape)
            QTest.qWait(30)
            self.assertFalse(popup.property("visible"), menu)

        def menu_action(button, menu, index):
            click(button)
            item = self.evaluate(self.root.findChild(QObject, menu), f"itemAt({index})")
            QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=item.mapToScene(item.boundingRect().center()).toPoint())
            QTest.qWait(60)

        self.controller.path = Path(self.temp.name) / "configured.sqlite"
        click("ribbonFile")
        click("saveProjectCommand")
        self.assertTrue(self.controller.path.exists())
        self.assertEqual(load_project(self.controller.path).editor_config, self.controller.project.editor_config)
        menu_action("ribbonData", "ribbonDataMenu", 0)
        self.assertEqual(self.root.property("page"), 1)
        self.assertTrue(self.root.findChild(QObject, "objectSpreadsheet").isVisible())
        menu_action("ribbonSolve", "ribbonSolveMenu", 0)
        self.assertEqual(self.root.property("page"), 4)
        menu_action("ribbonModel", "ribbonModelMenu", 3)
        self.assertEqual(self.root.property("page"), 6)
        self.assertEqual(self.warnings, [])

    def assert_f1_help(self, component, attribute):
        QTest.keyClick(self.root, Qt.Key.Key_F1)
        QTest.qWait(100)
        help_window = self.root.findChild(QObject, "referenceHelp")
        self.assertTrue(help_window.property("visible"))
        self.assertEqual(help_window.property("componentName"), component)
        self.assertEqual(help_window.property("propertyName"), attribute)
        self.assertEqual(self.root.findChild(QObject, "helpPropertyTitle").property("text"), component + "." + attribute)
        QTest.keyClick(self.root, Qt.Key.Key_Escape)
        QTest.qWait(50)
        self.assertFalse(help_window.property("visible"))

    def test_refined_ribbon_geometry_icons_and_keyboard_in_both_themes(self):
        for mode in ["Light", "Dark"]:
            self.appearance.setMode(mode)
            for width, height in [(1440, 920), (1140, 760)]:
                self.root.resize(width, height)
                QTest.qWait(50)
                for row in [["ribbonFile"] + [f"ribbonPage-{i}" for i in range(7)] + ["ribbonHelp"],
                            ["ribbonModel", "ribbonData", "ribbonValidate", "ribbonSolve", "ribbonRun"]]:
                    previous_right = 0
                    for name in row:
                        item = self.visual_item(name)
                        self.assertIsNotNone(item, name)
                        left = item.mapToScene(QPointF()).x()
                        self.assertGreaterEqual(left, previous_right, name)
                        previous_right = left + item.width()
                        self.assertLessEqual(previous_right, width, name)
                        self.assertGreaterEqual(item.height(), 30)
                for name in ["ribbonFile", "ribbonModel", "ribbonData", "ribbonValidate", "ribbonSolve", "ribbonHelp", "ribbonRun", "quickSave"]:
                    item = self.visual_item(name)
                    self.assertTrue(self.evaluate(item, "contentItem.children[0].source.toString().startsWith('data:image/svg+xml,')"))
                    # SVG decoding is asynchronous, especially under concurrent
                    # numerical tests. Still require Ready, never accept Error.
                    for _ in range(40):
                        if self.evaluate(item, "contentItem.children[0].status") != 2:
                            break
                        QTest.qWait(50)
                    self.assertEqual(self.evaluate(item, "contentItem.children[0].status"), 1, name)
                help_button = self.visual_item("ribbonHelp")
                help_button.forceActiveFocus()
                QTest.keyClick(self.root, Qt.Key.Key_Space)
                QTest.qWait(40)
                menu = self.root.findChild(QObject, "ribbonHelpMenu")
                self.assertTrue(menu.property("visible"))
                QTest.keyClick(self.root, Qt.Key.Key_Escape)
                QTest.qWait(30)
                self.assertFalse(menu.property("visible"))
        self.assertEqual(self.warnings, [])

    def test_refined_ribbon_quick_save_and_run_keep_draft_guards(self):
        self.controller.loadDemo()
        self.controller.path = Path(self.temp.name) / "quick-save.sqlite"
        save = self.visual_item("quickSave")
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=save.mapToScene(save.boundingRect().center()).toPoint())
        self.assertEqual(load_project(self.controller.path).to_dict(), self.controller.project.to_dict())
        self.controller.selectType("Generator")
        self.controller.sheetModel.editCell(0, self.controller.sheetModel.columns.index("p_nom"), "161")
        before = self.controller.project.to_dict()
        run = self.visual_item("ribbonRun")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=run.mapToScene(run.boundingRect().center()).toPoint())
        self.assertIsNone(self.controller.process)
        self.assertTrue(self.controller.sheetModel.dirty)
        self.assertEqual(self.controller.project.to_dict(), before)
        self.assertEqual(self.root.property("page"), 0)
        self.assertEqual(self.warnings, [])

    def test_f1_spreadsheet_cell_header_and_inspector_preserve_drafts(self):
        self.controller.loadDemo()
        self.controller.selectType("Generator")
        self.root.setProperty("page", 1)
        QTest.qWait(40)
        # The inline reference list is removed, not simply hidden elsewhere in Objects.
        source = Path(__file__).resolve().parents[1] / "energy_gui" / "qml" / "Main.qml"
        self.assertNotIn("ATTRIBUTE REFERENCE", source.read_text(encoding="utf-8"))
        toggle = self.root.findChild(QObject, "objectEditorToggle")
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=toggle.mapToScene(toggle.boundingRect().center()).toPoint())
        QTest.qWait(70)
        column = self.controller.sheetModel.columns.index("p_nom")
        cell = self.visual_item(f"sheetCell-0-{column}")
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=cell.mapToScene(cell.boundingRect().center()).toPoint())
        self.controller.sheetModel.editCell(0,column,"160")
        before = self.controller.project.to_dict()
        self.assert_f1_help("Generator", "p_nom")
        self.assertTrue(self.controller.sheetModel.dirty)
        self.assertEqual(self.controller.project.to_dict(), before)
        header = self.visual_item(f"sheetHeader-{column}")
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=header.mapToScene(header.boundingRect().center()).toPoint())
        self.assert_f1_help("Generator", "p_nom")
        self.controller.discardSheet()
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=toggle.mapToScene(toggle.boundingRect().center()).toPoint())
        QTest.qWait(50)
        select = self.root.findChild(QObject, "inspectorPropertySelect")
        self.evaluate(select, "currentIndex = model.indexOf('efficiency')")
        value = self.root.findChild(QObject, "inspectorPropertyValue")
        value.forceActiveFocus()
        self.assert_f1_help("Generator", "efficiency")
        self.controller.selectObject("Thermal")
        QTest.qWait(30)
        editor = self.root.findChild(QObject, "objectJsonEditor")
        draft = editor.property("text").replace('"p_nom": 150', '"p_nom": 163')
        editor.setProperty("text", draft)
        editor.forceActiveFocus()
        text = editor.property("text")
        editor.setProperty("cursorPosition", text.index('"p_nom"')+3)
        self.assert_f1_help("Generator", "p_nom")
        self.assertEqual(editor.property("text"), draft)
        self.assertTrue(editor.hasActiveFocus())
        self.assertEqual(self.warnings, [])

    def test_ribbon_help_library_search_includes_hidden_fields_and_network(self):
        self.controller.loadDemo()
        self.controller.applyEditorConfiguration(["Bus"], {"Bus": ["name"]})
        button = self.root.findChild(QObject, "ribbonHelp")
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=button.mapToScene(button.boundingRect().center()).toPoint())
        QTest.qWait(40)
        menu = self.root.findChild(QObject, "ribbonHelpMenu")
        entry = self.evaluate(menu, "itemAt(0)")
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=entry.mapToScene(entry.boundingRect().center()).toPoint())
        QTest.qWait(100)
        help_window = self.root.findChild(QObject, "referenceHelp")
        self.assertTrue(help_window.property("visible"))
        catalogue = help_window.property("catalogue")
        if hasattr(catalogue, "toVariant"):
            catalogue = catalogue.toVariant()
        self.assertEqual(set(catalogue), set(registry()) | {"Network"})
        search = self.root.findChild(QObject, "helpPropertySearch")
        search.setProperty("text", "v_nom")
        QTest.qWait(40)
        listing = self.root.findChild(QObject, "helpPropertyList")
        self.assertGreater(listing.property("count"), 0)
        self.assertLess(listing.property("count"), len(catalogue["Bus"]))
        item = self.visual_item("helpProperty-v_nom")
        self.assertIsNotNone(item)
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=item.mapToScene(item.boundingRect().center()).toPoint())
        self.assertIn("Bus.v_nom", self.root.findChild(QObject, "helpPropertyTitle").property("text"))
        scroll = self.root.findChild(QObject, "helpDetailScroll")
        self.evaluate(scroll, "contentItem.contentY = 250")
        QTest.qWait(30)
        self.assertGreater(self.evaluate(scroll, "contentItem.contentY"), 0)
        help_window.showReference("Network", "snapshot_weightings")
        QTest.qWait(50)
        self.assertIn("snapshot_weightings", self.root.findChild(QObject, "helpPropertyTitle").property("text"))
        self.assertGreater(self.root.findChild(QObject, "helpClassGuide").property("length"), 100)
        self.assertTrue(self.root.findChild(QObject, "helpClassGuide").property("readOnly"))
        self.assertEqual(self.evaluate(scroll, "contentItem.contentY"), 0)
        QTest.keyClick(self.root, Qt.Key.Key_Escape)
        self.assertEqual(self.warnings, [])

    def test_f1_configuration_property_uses_its_category_not_the_editor_category(self):
        self.controller.loadDemo()
        self.root.setProperty("page", 6)
        QTest.qWait(40)
        config = self.root.findChild(QObject, "editorConfiguration")
        config.setProperty("category", "Generator")
        self.root.findChild(QObject, "configPropertySearch").setProperty("text", "p_nom")
        QTest.qWait(40)
        item = self.visual_item("configProperty-p_nom")
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=item.mapToScene(item.boundingRect().center()).toPoint())
        before = self.controller.project.to_dict()
        self.assert_f1_help("Generator", "p_nom")
        self.assertTrue(config.property("pending"))
        self.assertEqual(self.controller.project.to_dict(), before)
        self.assertEqual(self.warnings, [])

    def test_f1_results_and_profiles_resolve_property_context(self):
        self.controller.loadDemo()
        # Results can reference a different class than the Objects inspector.
        self.controller.query_categories = [{"name": "Generator", "objects": ["Thermal"],
                                             "properties": [{"name": "p", "unit": "MW"}]}]
        self.controller.queryOptionsChanged.emit()
        self.root.setProperty("page", 5)
        view = self.root.findChild(QObject, "resultsExplorer")
        view.chooseCategory("Generator")
        QTest.qWait(50)
        item = self.visual_item("resultProperty-p")
        self.assertIsNotNone(item)
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=item.mapToScene(item.boundingRect().center()).toPoint())
        self.assert_f1_help("Generator", "p")
        self.assertTrue(view.property("pending"))
        self.controller.selectType("Load")
        self.root.setProperty("page", 2)
        QTest.qWait(50)
        select = self.root.findChild(QObject, "profilePropertySelect")
        self.evaluate(select, "currentIndex = model.indexOf('p_set')")
        select.forceActiveFocus()
        before = self.controller.project.to_dict()
        self.assert_f1_help("Load", "p_set")
        self.assertEqual(self.controller.project.to_dict(), before)
        self.assertEqual(self.warnings, [])

    def configure_query_stub(self):
        class QueryStub:
            def query(self, component, objects, properties, first, last):
                static = properties == ["efficiency"]
                frame = pd.DataFrame({"object": objects}) if static else pd.DataFrame({
                    "snapshot": pd.to_datetime(["2026-01-01T00:00", "2026-01-01T01:00"]),
                    "object": [objects[0], objects[0]],
                })
                for p in properties:
                    frame[p] = [0.8, 0.9] if static else [5., 6.]
                return frame, [{"name": p, "unit": "per unit" if static else "MW"} for p in properties], not static

        self.controller.repository = QueryStub()
        self.controller.run_directory = Path(self.temp.name) / "synthetic"
        self.controller.run_meta = {"status": "succeeded", "objective": 11}
        self.controller.query_snapshots = pd.date_range("2026-01-01", periods=40, freq="h").astype(str).tolist()
        self.controller.queryOptionsChanged.emit()
        self.root.setProperty("page", 5)
        QTest.qWait(40)

    def test_query_pane_proportions_data_chart_toggle_and_active_tab_isolation(self):
        self.configure_query_stub()
        view = self.root.findChild(QObject, "resultsExplorer")
        snapshots = self.root.findChild(QObject, "snapshotPane")
        properties = self.root.findChild(QObject, "propertiesPane")
        objects = self.root.findChild(QObject, "objectsPane")
        for width, height in [(1440, 920), (1140, 760)]:
            self.root.resize(width, height)
            QTest.qWait(40)
            self.assertLess(snapshots.mapToScene(QPointF()).y(), properties.mapToScene(QPointF()).y())
            self.assertGreater(objects.mapToScene(QPointF()).x(), snapshots.mapToScene(QPointF()).x())
            ratio = snapshots.height() / (snapshots.height() + properties.height())
            self.assertAlmostEqual(ratio, 1/3, delta=0.04)
        self.assertTrue(self.controller.queryResults("Generator", ["A", "B"], ["efficiency"], "", ""))
        first = self.controller.workspace.active_id
        self.controller.pinQueryTab(first)
        self.assertTrue(self.controller.setChartType("efficiency", "horizontal bar"))
        self.assertTrue(self.controller.queryResults("Load", ["L"], ["p"], "", ""))
        second = self.controller.workspace.active_id
        self.controller.setChartType("p", "dot")
        charts_button = self.root.findChild(QObject, "chartsViewToggle")
        point = charts_button.mapToScene(charts_button.boundingRect().center()).toPoint()
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=point)
        QTest.qWait(50)
        data = self.root.findChild(QObject, "queriedDataPane")
        charts = self.root.findChild(QObject, "queriedChartsPane")
        self.assertFalse(data.isVisible())
        self.assertTrue(charts.isVisible())
        for tab, attribute, kind, expected in [(first, "efficiency", "horizontal bar", [0.8, 0.9]), (second, "p", "dot", [5., 6.])]:
            self.controller.selectQueryTab(tab)
            QTest.qWait(50)
            self.assertEqual([c["title"] for c in self.controller.state["charts"]], [attribute])
            chart = self.visual_item("queryChart-" + attribute)
            self.assertIsNotNone(chart)
            payload = chart.property("chart")
            if hasattr(payload, "toVariant"):
                payload = payload.toVariant()
            self.assertEqual(payload["kind"], kind)
            self.assertEqual(payload["series"][0]["values"], expected)
            other = "p" if attribute == "efficiency" else "efficiency"
            self.assertIsNone(self.visual_item("queryChart-" + other))
            self.assertEqual(list(self.controller._result_frame[attribute]), expected)
        view.setProperty("resultView", 0)
        QTest.qWait(30)
        self.assertTrue(data.isVisible())
        self.assertFalse(charts.isVisible())
        self.assertEqual(self.warnings, [])

    def test_chart_popup_dismisses_on_scroll_focus_hide_and_tab_switch(self):
        self.configure_query_stub()
        self.controller.queryResults("Generator", ["A"], ["p", "p2", "p3"], "", "")
        first = self.controller.workspace.active_id
        self.controller.pinQueryTab(first)
        view = self.root.findChild(QObject, "resultsExplorer")
        view.setProperty("resultView", 1)
        QTest.qWait(60)
        scroll = self.root.findChild(QObject, "queryChartsScroll")

        def open_select():
            select = self.visual_item("chartType-p")
            point = select.mapToScene(select.boundingRect().center()).toPoint()
            QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=point)
            QTest.qWait(30)
            self.assertTrue(self.evaluate(select, "popup.visible"))
            return select

        select = open_select()
        self.evaluate(scroll, "contentItem.contentY = 100")
        QTest.qWait(30)
        self.assertFalse(self.evaluate(select, "popup.visible"))
        self.evaluate(scroll, "contentItem.contentY = 0")
        select = open_select()
        chart = self.visual_item("queryChart-p")
        point = chart.mapToScene(QPointF(chart.width()-15, chart.height()-15))
        QTest.wheelEvent(self.root, point, QPoint(0, -120))
        QTest.qWait(150)
        self.assertGreater(self.evaluate(scroll, "contentItem.contentY"), 0)
        self.assertFalse(self.evaluate(select, "popup.visible"))
        self.evaluate(scroll, "contentItem.cancelFlick(); contentItem.contentY = 0")
        select = open_select()
        self.root.findChild(QObject, "executeQuery").forceActiveFocus()
        QTest.qWait(30)
        self.assertFalse(self.evaluate(select, "popup.visible"))
        select = open_select()
        view.setProperty("resultView", 0)
        QTest.qWait(30)
        self.assertFalse(self.evaluate(select, "popup.visible"))
        view.setProperty("resultView", 1)
        QTest.qWait(30)
        select = open_select()
        # Popup keyboard navigation must still activate a chart choice.
        QTest.keyClick(self.root, Qt.Key.Key_Down)
        QTest.keyClick(self.root, Qt.Key.Key_Return)
        QTest.qWait(50)
        self.assertEqual(self.controller.state["charts"][0]["kind"], "bar")
        select = open_select()
        option = self.evaluate(select, "popup.contentItem.itemAtIndex(2)")
        point = option.mapToScene(option.boundingRect().center()).toPoint()
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=point)
        QTest.qWait(40)
        self.assertEqual(self.controller.state["charts"][0]["kind"], "dot")
        select = open_select()
        self.root.setProperty("page", 0)
        QTest.qWait(30)
        self.assertFalse(self.evaluate(select, "popup.visible"))
        self.root.setProperty("page", 5)
        self.controller.queryResults("Load", ["L"], ["q"], "", "")
        self.controller.selectQueryTab(first)
        QTest.qWait(30)
        select = open_select()
        self.controller.selectQueryTab(self.controller.workspace.tabs[-1].id)
        QTest.qWait(30)
        # No chart selector/popup from the previous query may remain onscreen.
        self.assertIsNone(self.visual_item("chartType-p"))
        # Scrolling a long dropdown's OWN list should not dismiss that dropdown.
        snapshot = self.root.findChild(QObject, "queryFromSnapshot")
        snapshot.forceActiveFocus()
        self.evaluate(snapshot, "popup.open()")
        self.evaluate(snapshot, "popup.contentItem.contentY = 80")
        QTest.qWait(40)
        self.assertTrue(self.evaluate(snapshot, "popup.visible"))
        QTest.keyClick(self.root, Qt.Key.Key_Escape)
        self.assertEqual(self.warnings, [])

    def test_pin_button_preserves_query_and_chart_control_changes_only_style(self):
        class QueryStub:
            def query(self, component, objects, properties, first, last):
                frame = pd.DataFrame({"snapshot": pd.to_datetime(["2026-01-01T00:00", "2026-01-01T01:00"]), "object": ["G", "G"], "p": [5., 6.]})
                return frame, [{"name": "p", "unit": "MW"}], True

        self.controller.repository = QueryStub()
        self.controller.run_directory = Path(self.temp.name) / "synthetic"
        self.controller.run_meta = {"status": "succeeded", "objective": 11}
        self.controller.query_snapshots = ["2026-01-01T00:00:00", "2026-01-01T01:00:00"]
        self.assertTrue(self.controller.queryResults("Generator", ["G"], ["p"], "", ""))
        self.root.setProperty("page", 5)
        QTest.qWait(60)
        first = self.controller.workspace.active
        strip = self.root.findChild(QObject, "queryTabStrip")
        expression = QQmlExpression(self.engine.rootContext(), strip, "itemAtIndex(0)")
        delegate, _ = expression.evaluate()
        pin = delegate.findChild(QObject, "pinQuery-" + first.id)
        self.assertEqual(pin.property("width"), 26)
        self.assertEqual(pin.property("height"), 26)
        self.assertEqual(pin.property("contentItem").property("rotation"), 45)
        # The button's background and hit area must stay inside the 36px tab.
        top_left = pin.mapToItem(delegate, pin.boundingRect().topLeft())
        self.assertGreaterEqual(top_left.y(), 0)
        self.assertLessEqual(top_left.y() + pin.height(), delegate.height())
        center = pin.mapToScene(pin.boundingRect().center())
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=QPoint(round(center.x()), round(center.y())))
        QTest.qWait(30)
        self.assertTrue(first.pinned)
        # The model refresh recreates delegates; inspect the new pinned instance.
        expression = QQmlExpression(self.engine.rootContext(), strip, "itemAtIndex(0)")
        delegate, _ = expression.evaluate()
        pin = delegate.findChild(QObject, "pinQuery-" + first.id)
        self.assertEqual(pin.property("contentItem").property("rotation"), 0)
        background = pin.property("background")
        self.assertGreaterEqual(background.property("x"), 0)
        self.assertGreaterEqual(background.property("y"), 0)
        self.assertLessEqual(background.property("x") + background.property("width"), pin.width())
        self.assertLessEqual(background.property("y") + background.property("height"), pin.height())
        # Same query now creates a second tab rather than touching the pinned one.
        self.assertTrue(self.controller.queryResults("Generator", ["G"], ["p"], "", ""))
        self.assertEqual(len(self.controller.workspace.tabs), 2)
        frame = self.controller._result_frame.copy()
        self.assertTrue(self.controller.setChartType("p", "stacked area"))
        QTest.qWait(50)
        pd.testing.assert_frame_equal(frame, self.controller._result_frame)
        self.assertEqual(self.controller.state["charts"][0]["kind"], "stacked area")
        self.assertEqual(self.warnings, [])

    def test_object_tree_selection_is_single_category_and_does_not_query(self):
        self.controller.query_categories = [
            {"name": "Generator", "objects": ["G1", "G2"], "properties": [{"name": "p", "unit": "MW", "kind": "time series"}]},
            {"name": "Load", "objects": ["L1"], "properties": [{"name": "p", "unit": "MW", "kind": "time series"}]},
        ]
        self.controller.query_snapshots = ["2026-01-01T00:00:00", "2026-01-01T01:00:00"]
        self.controller.queryOptionsChanged.emit()
        self.controller.changed.emit()
        self.root.setProperty("page", 5)
        QTest.qWait(40)
        view = self.root.findChild(QObject, "resultsExplorer")
        view.toggleObject("Generator", "G1")
        view.toggleObject("Generator", "G2")
        view.toggleProperty("p")
        QTest.qWait(40)
        self.assertEqual(view.property("selectedObjects").toVariant(), ["G1", "G2"])
        self.assertEqual(self.controller.resultModel.rowCount(), 0)
        # Result refresh must not reinitialize the selected snapshot dropdowns.
        start = self.root.findChild(QObject, "queryFromSnapshot")
        end = self.root.findChild(QObject, "queryToSnapshot")
        self.assertEqual(end.property("currentIndex"), 1, "To defaults to the last snapshot.")
        start.setProperty("currentIndex", 1)
        self.controller.filterResults("")
        self.assertEqual(start.property("currentIndex"), 1)
        captured = []

        class QueryStub:
            def query(self, component, objects, properties, first, last):
                captured.append((component, objects, properties, first, last))
                frame = pd.DataFrame({"snapshot": pd.to_datetime([first, first]), "object": objects, "p": [5., 6.]})
                return frame, [{"name": "p", "unit": "MW"}], True

        self.controller.repository = QueryStub()
        self.controller.query_snapshots = ["2026-01-01T00:00:00", "2026-01-01T01:00:00"]
        button = self.root.findChild(QObject, "executeQuery")
        QTest.qWait(40)
        self.assertTrue(button.property("enabled"))
        center = button.mapToScene(button.boundingRect().center())
        QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=QPoint(round(center.x()), round(center.y())))
        QTest.qWait(40)
        self.assertEqual(len(captured), 1, "Only the explicit Query click should fetch results.")
        self.assertEqual(captured[0], ("Generator", ["G1", "G2"], ["p"], "2026-01-01T01:00:00", "2026-01-01T01:00:00"))
        self.assertEqual(self.controller.resultModel.rowCount(), 2)
        self.assertFalse(view.property("pending"))
        view.toggleObject("Load", "L1")
        self.assertEqual(view.property("selectedObjects").toVariant(), ["L1"])
        self.assertEqual(view.property("selectedProperties").toVariant(), [])
        self.assertEqual(self.controller.resultModel.rowCount(), 2, "Draft edits retain the previous query's data until Query is clicked.")
        self.assertEqual(self.warnings, [])
