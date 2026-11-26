"""Stage4A: real QML navigation clicks, frozen semantics and view-only state."""

from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

# Reuse only the fixture/helper methods, NOT the 32-test legacy test class.
# Importing the module (rather than its TestCase) also avoids duplicate discovery.
import test_qml_controls as _controls
from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog
import pandas as pd

from energy_gui.demo_library import make_demo
from energy_gui.network_view import checked_layout, object_key
from energy_gui.storage import load_project, save_project
from test_network_view import overlay_fixture


class NetworkNavigationTests(unittest.TestCase):
    setUpClass = classmethod(_controls.QmlControlsTests.setUpClass.__func__)
    setUp = _controls.QmlControlsTests.setUp
    tearDown = _controls.QmlControlsTests.tearDown
    evaluate = _controls.QmlControlsTests.evaluate
    visual_item = _controls.QmlControlsTests.visual_item

    def click(self, name):
        item = self.visual_item(name)
        self.assertIsNotNone(item, name)
        self.assertTrue(item.isVisible(), name)
        self.assertTrue(item.isEnabled(), name)
        QTest.mouseClick(
            self.root, Qt.MouseButton.LeftButton,
            pos=item.mapToScene(item.boundingRect().center()).toPoint(),
        )
        QTest.qWait(45)
        return item

    def json_value(self, item, expression):
        return json.loads(self.evaluate(item, f"JSON.stringify({expression})"))

    def replace_search(self, text):
        self.click("networkSearchField")
        QTest.keyClick(self.root, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(self.root, Qt.Key.Key_Backspace)
        for character in text:
            QTest.keyClick(self.root, Qt.Key(ord(character.upper())))
        QTest.qWait(45)

    def choose(self, name, text):
        select = self.click(name)
        index = self.json_value(select, "model").index(text)
        self.assertTrue(self.evaluate(select, "popup.visible"))
        option = self.evaluate(select, f"popup.contentItem.itemAtIndex({index})")
        self.assertIsNotNone(option, (name, text))
        QTest.mouseClick(
            self.root, Qt.MouseButton.LeftButton,
            pos=option.mapToScene(option.boundingRect().center()).toPoint(),
        )
        QTest.qWait(45)
        self.assertEqual(select.property("currentText"), text)

    def show_network(self, project=None):
        if project is None:
            self.controller.loadDemo()
        else:
            self.controller.project = project
            self.controller._reset_helpers()
            self.controller._reset_draft()
            self.controller.changed.emit()
        self.root.resize(1140, 760)
        self.root.setProperty("page", 3)
        QTest.qWait(80)
        return self.root.findChild(QObject, "networkView")

    def frozen_network(self, high_flows=False, results=False):
        run = Path(self.temp.name) / "runs" / "navigation-reference"
        project, _ = overlay_fixture(run)
        if high_flows:
            # Actual exported values exercise both explicit highlight thresholds.
            for attribute, values in [("p0", [4.75, -12]), ("p1", [-4.75, 12])]:
                pd.DataFrame({"snapshot": project.snapshots, "L": values}).to_csv(
                    run / "tables" / f"Line_{attribute}.csv", index=False,
                )
        view = self.show_network(project)
        self.controller.path = Path(self.temp.name) / "model.sqlite"
        if results:
            self.assertTrue(self.controller.openRun(str(run)))
            self.assertTrue(self.controller.queryResults("Line", ["L"], ["p0"], "", ""))
            self.assertTrue(self.controller.setChartType("p0", "dot"))
            self.controller.setAnalysisView(1)
        self.assertTrue(self.controller.loadNetworkRun(str(run)))
        QTest.qWait(80)
        return view, run

    def assert_whole_nodes_fit(self):
        viewport = self.root.findChild(QObject, "networkViewport")
        self.assertGreater(viewport.height(), 100)
        for obj in self.controller.networkState["topology"]["objects"]:
            node = self.visual_item(f"networkObject-{obj['kind']}-{obj['name']}")
            bounds = node.mapRectToItem(viewport, node.boundingRect())
            self.assertGreaterEqual(bounds.left(), -0.01, obj["key"])
            self.assertGreaterEqual(bounds.top(), -0.01, obj["key"])
            self.assertLessEqual(bounds.right(), viewport.width() + 0.01, obj["key"])
            self.assertLessEqual(bounds.bottom(), viewport.height() + 0.01, obj["key"])

    def test_filters_real_controls_are_view_only_and_readable_in_both_themes(self):
        view = self.show_network()
        before = deepcopy(self.controller.project.to_dict())
        positions = self.json_value(view, "positions")
        count = len(positions)
        view.setProperty("layoutPending", False)
        for mode in ["Light", "Dark"]:
            self.appearance.setMode(mode)
            self.click("networkNavigate")
            popup = self.root.findChild(QObject, "networkNavigationPopup")
            self.assertTrue(popup.property("visible"))
            self.assertGreaterEqual(popup.property("x"), 0)
            self.assertGreaterEqual(popup.property("y"), 0)
            self.assertLessEqual(popup.property("y") + popup.property("height"), 760)
            field = self.root.findChild(QObject, "networkSearchField")
            self.assertEqual(
                self.evaluate(field, "placeholderTextColor.toString()"),
                self.evaluate(view, "theme.muted.toString()"),
            )
            self.assertNotEqual(field.property("color"), self.evaluate(field, "background.color"))
            self.replace_search("GENERATOR SOLAR")
            self.assertEqual(
                self.json_value(view, "filteredObjects.map(function(o) { return o.name })"),
                ["Solar"],
            )
            self.assertEqual(self.evaluate(view, "filteredObjects.length"), 1)
            self.assertTrue(self.visual_item("networkObject-Generator-Solar").isVisible())
            self.assertFalse(self.visual_item("networkObject-Bus-North").isVisible())
            self.assertFalse(self.json_value(view, "wireAppearance(topology.wires[0])")["visible"])
            self.replace_search("")
            self.choose("networkKindFilter", "Generator")
            self.choose("networkCarrierFilter", "solar")
            self.assertEqual(self.evaluate(view, "filteredObjects.length"), 1)
            self.replace_search("no such object")
            self.assertEqual(self.evaluate(view, "filteredObjects.length"), 0)
            self.assertTrue(self.visual_item("networkNoMatches").isVisible())
            self.click("networkClearFilters")
            self.assertEqual(self.evaluate(view, "filteredObjects.length"), count)
            self.assertEqual(self.json_value(view, "positions"), positions)
            self.assertFalse(view.property("layoutPending"))
            self.click("networkNavigationClose")
        self.assertEqual(self.controller.project.to_dict(), before)
        self.assertEqual(self.warnings, [])

    def test_locate_selection_zooms_centres_and_highlights_connections_without_moving(self):
        view = self.show_network()
        key = object_key("Generator", "Thermal")
        view.moveObject(key, 450, 260)
        view.fitView()
        QTest.qWait(60)
        overview_zoom = view.property("zoomFactor")
        before = deepcopy(self.controller.project.to_dict())
        positions = self.json_value(view, "positions")
        self.click("networkNavigate")
        self.replace_search("thermal")
        selected = self.click("networkSearchResult-Generator-Thermal")
        self.assertEqual(selected.property("contentItem").property("color"), QColor(self.evaluate(self.root, "appTheme.primaryText.toString()")))
        self.click("networkLocateSelected")
        self.assertGreater(view.property("zoomFactor"), overview_zoom)
        self.assertEqual(view.property("activeObject"), key)
        self.assertEqual(view.property("searchText"), "")
        node = self.visual_item("networkObject-Generator-Thermal")
        self.assertTrue(node.property("selected"))
        self.assertTrue(self.visual_item("networkObject-Bus-North").property("connected"))
        self.assertTrue(self.visual_item("networkFocusRing-Generator-Thermal").isVisible())
        viewport = self.root.findChild(QObject, "networkViewport")
        center = node.mapToItem(viewport, node.boundingRect().center())
        self.assertAlmostEqual(center.x(), viewport.width() / 2, delta=1)
        self.assertAlmostEqual(center.y(), viewport.height() / 2, delta=1)
        styles = self.json_value(view, "topology.wires.map(function(w) { return wireAppearance(w) })")
        self.assertEqual(sum(style["focused"] for style in styles), 1)
        self.assertTrue(all(style["width"] == 4.5 for style in styles if style["focused"]))
        self.assertTrue(all(style["alpha"] < 1 for style in styles if not style["focused"]))
        self.assertEqual(self.json_value(view, "positions"), positions)
        self.assertFalse(view.focusObject("not an object"))
        self.assertFalse(view.locateObject("Bus", "not a bus"))
        self.assertEqual(view.property("activeObject"), key)
        self.click("networkNavigate")
        self.click("networkClearFocus")
        self.assertFalse(node.property("selected"))
        self.assertFalse(self.visual_item("networkObject-Bus-North").property("connected"))
        self.click("networkNavigationClose")
        self.assertTrue(view.locateObject("Bus", "North"))
        QTest.qWait(40)
        self.assertEqual(view.property("activeObject"), object_key("Bus", "North"))
        self.assertEqual(self.controller.project.to_dict(), before)
        self.assertEqual(self.warnings, [])

    def test_grid_is_explicit_deterministic_nonoverlapping_and_only_saved_on_request(self):
        view = self.show_network(make_demo("regional20"))
        self.controller.path = Path(self.temp.name) / "grid.sqlite"
        key = object_key("Bus", self.controller.networkState["topology"]["buses"][0]["name"])
        view.moveObject(key, 400, 200)
        self.click("networkSaveLayout")
        saved_bytes = self.controller.path.read_bytes()
        before = deepcopy(self.controller.project.to_dict())
        original = self.json_value(view, "positions")
        self.controller.changed.emit()
        QTest.qWait(50)
        self.assertEqual(self.json_value(view, "positions"), original)
        self.click("networkNavigate")
        self.click("networkReadableGridLayout")
        grid = self.json_value(view, "positions")
        self.assertNotEqual(grid, original)
        self.assertEqual(set(grid), set(original))
        self.assertTrue(view.property("layoutPending"))
        self.assertEqual(self.controller.project.to_dict(), before)
        self.assertEqual(self.controller.path.read_bytes(), saved_bytes)
        points = list(grid.values())
        for index, first in enumerate(points):
            for second in points[index + 1:]:
                self.assertTrue(abs(first["x"] - second["x"]) >= 100 or abs(first["y"] - second["y"]) >= 124)
        checked_layout(self.json_value(view, "layoutData()"), set(grid))
        self.assert_whole_nodes_fit()
        self.click("networkNavigate")
        self.click("networkReadableGridLayout")
        self.assertEqual(self.json_value(view, "positions"), grid)
        self.click("networkSaveLayout")
        self.assertEqual(load_project(self.controller.path).schematic_layouts["current"]["positions"], grid)
        view.moveObject(key, 300, 200)
        with patch.object(QFileDialog, "getOpenFileName", return_value=(str(self.controller.path), "SQLite")):
            self.controller.openProject()
        QTest.qWait(90)
        self.assertEqual(self.json_value(view, "positions"), grid)
        self.assertEqual(self.warnings, [])

    def test_frozen_grid_fit_contains_whole_nodes_at_minimum_window_in_both_themes(self):
        project = make_demo("regional20")
        run = Path(self.temp.name) / "runs" / "large-navigation"
        (run / "tables").mkdir(parents=True)
        save_project(project, run / "inputs.sqlite")
        catalog = []
        for kind in sorted({record["component"] for record in project.objects}):
            rows = [{"name": record["name"], **record["attributes"]}
                    for record in project.objects if record["component"] == kind]
            filename = f"{kind}.csv"
            pd.DataFrame(rows).to_csv(run / "tables" / filename, index=False)
            catalog.append(dict(component=kind, kind="static", attribute="static properties", file=filename))
        (run / "catalog.json").write_text(json.dumps(catalog))
        (run / "run_config.json").write_text(json.dumps(dict(project_id=project.project_id, status="succeeded")))
        frozen_bytes = (run / "inputs.sqlite").read_bytes()
        view = self.show_network(project)
        self.assertTrue(self.controller.loadNetworkRun(str(run)))
        QTest.qWait(80)
        before = deepcopy(self.controller.project.to_dict())
        self.click("networkNavigate")
        self.click("networkReadableGridLayout")
        grid = self.json_value(view, "positions")
        for mode in ["Light", "Dark"]:
            self.appearance.setMode(mode)
            self.click("networkFitView")
            self.assert_whole_nodes_fit()
        checked_layout(self.json_value(view, "layoutData()"), set(grid))
        self.assertEqual((run / "inputs.sqlite").read_bytes(), frozen_bytes)
        self.assertEqual(self.controller.project.to_dict(), before)
        self.assertEqual(self.warnings, [])

    def test_congestion_opt_in_uses_actual_passive_p0_payload_only(self):
        view, _ = self.frozen_network(high_flows=True)
        line_key = object_key("Line", "L")
        expression = "topology.wires.find(function(w) { return w.a === %s && w.port === 'bus0' })" % json.dumps(line_key)
        self.assertEqual(self.json_value(view, f"passiveUtilisation({expression})"), 95)
        self.assertFalse(self.json_value(view, f"wireAppearance({expression})")["congested"])
        before = deepcopy(self.controller.project.to_dict())
        for mode in ["Light", "Dark"]:
            self.appearance.setMode(mode)
            self.click("networkNavigate")
            self.click("networkCongestionToggle")
            self.assertTrue(view.property("congestionEnabled"))
            styles = self.json_value(view, "topology.wires.map(function(w) { return wireAppearance(w) })")
            wires = self.controller.networkState["topology"]["wires"]
            self.assertEqual(
                [(wire["a"], wire["port"]) for wire, style in zip(wires, styles) if style["congested"]],
                [(line_key, "bus0")],
            )
            self.assertEqual(
                self.json_value(view, f"wireAppearance({expression})")["color"],
                self.evaluate(view, "theme.warning.toString()"),
            )
            # Invalid/missing percentages, absent output, p1 and converters cannot
            # acquire inferred utilisation even if a lookalike wire is supplied.
            actual = self.json_value(view, expression)
            variants = [actual | {"utilisation": value} for value in [None, "100", -1]]
            variants += [actual | {"flow": None}, actual | {"unit": "t/h"},
                         actual | {"port": "bus1", "attribute": "p1"},
                         actual | {"a": object_key("Link", "C")}]
            for wire in variants:
                self.assertIsNone(self.json_value(view, f"passiveUtilisation({json.dumps(wire)})"))
                self.assertFalse(self.json_value(view, f"wireAppearance({json.dumps(wire)})")["congested"])
            self.click("networkCongestionToggle")
            self.assertFalse(view.property("congestionEnabled"))
            self.click("networkNavigationClose")
        self.click("networkNavigate")
        self.click("networkCongestionToggle")
        self.click("networkNavigationClose")
        self.click("networkNextSnapshot")
        self.assertEqual(self.json_value(view, f"passiveUtilisation({expression})"), 120)
        self.assertEqual(
            self.json_value(view, f"wireAppearance({expression})")["color"],
            self.json_value(self.root, "appTheme.danger.toString()"),
        )
        self.click("networkLiveView")
        self.assertFalse(view.property("congestionEnabled"))
        self.click("networkNavigate")
        self.assertFalse(self.root.findChild(QObject, "networkCongestionToggle").property("enabled"))
        self.click("networkNavigationClose")
        self.assertEqual(self.controller.project.to_dict(), before)
        self.assertEqual(self.warnings, [])

    def test_snapshot_previous_next_keep_results_queries_layout_and_artifacts_unchanged(self):
        view, run = self.frozen_network(results=True)
        repository = self.controller.repository
        tab = self.controller.workspace.active
        frame = tab.frame.copy(deep=True)
        criteria = deepcopy(tab.criteria)
        chart_types = deepcopy(tab.chart_types)
        active_id = self.controller.workspace.active_id
        before = deepcopy(self.controller.project.to_dict())
        artifacts = {path: path.read_bytes() for path in run.rglob("*") if path.is_file()}
        positions = self.json_value(view, "positions")
        self.assertFalse(self.root.findChild(QObject, "networkPreviousSnapshot").property("enabled"))
        self.click("networkNextSnapshot")
        self.assertEqual(self.controller.networkState["snapshotIndex"], 1)
        self.assertEqual(self.root.findChild(QObject, "networkSnapshotSelect").property("currentIndex"), 1)
        self.assertFalse(self.root.findChild(QObject, "networkNextSnapshot").property("enabled"))
        self.assertFalse(view.stepSnapshot(1))
        self.click("networkPreviousSnapshot")
        self.assertEqual(self.controller.networkState["snapshotIndex"], 0)
        self.assertFalse(view.stepSnapshot(-1))
        self.assertFalse(view.stepSnapshot(5))
        self.assertIs(self.controller.repository, repository)
        self.assertIs(self.controller.workspace.active, tab)
        self.assertEqual(self.controller.workspace.active_id, active_id)
        self.assertEqual(tab.criteria, criteria)
        self.assertEqual(tab.chart_types, chart_types)
        self.assertEqual(tab.view, 1)
        pd.testing.assert_frame_equal(tab.frame, frame)
        self.assertEqual(self.json_value(view, "positions"), positions)
        self.assertEqual(self.controller.project.to_dict(), before)
        self.assertEqual({path: path.read_bytes() for path in artifacts}, artifacts)
        self.assertEqual(self.warnings, [])

    def test_search_enter_locates_match_and_clear_filters_restores_dropdown_state(self):
        view = self.show_network()
        self.click("networkNavigate")
        self.choose("networkKindFilter", "Generator")
        self.choose("networkCarrierFilter", "coal")
        self.replace_search("thermal")
        QTest.keyClick(self.root, Qt.Key.Key_Return)
        QTest.qWait(60)
        self.assertFalse(self.root.findChild(QObject, "networkNavigationPopup").property("visible"))
        self.assertEqual(view.property("activeObject"), object_key("Generator", "Thermal"))
        self.click("networkNavigate")
        self.assertEqual(self.root.findChild(QObject, "networkSearchField").property("text"), "")
        self.assertEqual(self.root.findChild(QObject, "networkKindFilter").property("currentIndex"), 0)
        self.assertEqual(self.root.findChild(QObject, "networkCarrierFilter").property("currentIndex"), 0)
        self.click("networkNavigationClose")
        self.assertEqual(self.warnings, [])


if __name__ == "__main__":
    unittest.main()
