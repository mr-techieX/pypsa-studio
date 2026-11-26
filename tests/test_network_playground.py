"""Expandable paper, real drag/scroll gestures, old/new layout and input isolation."""

from copy import deepcopy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_network_navigation as navigation
from PySide6.QtCore import QObject, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog

from energy_gui.network_view import checked_layout, object_key
from energy_gui.storage import save_project, load_project


class NetworkPlaygroundTests(unittest.TestCase):
    setUpClass = classmethod(navigation.NetworkNavigationTests.setUpClass.__func__)
    setUp = navigation.NetworkNavigationTests.setUp
    tearDown = navigation.NetworkNavigationTests.tearDown
    evaluate = navigation.NetworkNavigationTests.evaluate
    visual_item = navigation.NetworkNavigationTests.visual_item
    show_network = navigation.NetworkNavigationTests.show_network
    frozen_network = navigation.NetworkNavigationTests.frozen_network
    json_value = navigation.NetworkNavigationTests.json_value
    click = navigation.NetworkNavigationTests.click

    def drag(self, start, stop):
        # Move onto the target first and send a physical-looking stream. Native
        # Windows coalesces a two-move drag differently from the offscreen plugin.
        QTest.mouseMove(self.root, start, 20)
        QTest.qWait(30)
        QTest.mousePress(self.root, Qt.MouseButton.LeftButton, pos=start)
        QTest.qWait(30)
        for step in range(1, 9):
            QTest.mouseMove(self.root, start+(stop-start)*step/8, 15)
        QTest.mouseRelease(self.root, Qt.MouseButton.LeftButton, pos=stop)
        QTest.qWait(80)

    def test_node_uses_free_visible_space_beyond_old_scene_at_low_zoom(self):
        view = self.show_network()
        viewport = self.visual_item("networkViewport")
        key = object_key("Generator", "Thermal")
        # At 40% zoom, overlapping hit areas make selection ambiguous. Keep this
        # drag fixture's other objects off its press/release path.
        for index, obj in enumerate(self.controller.networkState["topology"]["objects"]):
            if obj["key"] != key:
                view.moveObject(obj["key"], 900+index*130, 100)
        view.moveObject(key, 450, 260)
        view.setProperty("zoomFactor", 0.4)
        margin = view.property("paperMargin")
        viewport.setProperty("contentX", margin)
        viewport.setProperty("contentY", margin)
        QTest.qWait(60)
        output = os.environ.get("STUDIO_PLAYGROUND_EVIDENCE")
        if output:
            dest = Path(output)
            dest.mkdir(parents=True, exist_ok=True)
            self.root.grabWindow().save(str(dest / "live-before-drag.png"))
        before = deepcopy(self.controller.project.to_dict())
        node = self.visual_item("networkObject-Generator-Thermal")
        start = node.mapToScene(node.boundingRect().center()).toPoint()
        stop = viewport.mapToScene(viewport.boundingRect().bottomRight()).toPoint()-QPoint(100, 55)
        self.drag(start, stop)
        point = self.json_value(view, "positions")[key]
        self.assertGreater(point["x"], 900)
        self.assertGreater(point["y"], 520)
        center = node.mapToScene(node.boundingRect().center()).toPoint()
        self.assertLess((center-stop).manhattanLength(), 5)
        self.assertEqual(self.controller.project.to_dict(), before)
        if output:
            self.root.grabWindow().save(str(Path(output) / "live-expanded-drag.png"))
        self.assertEqual(self.warnings, [])

    def test_loading_while_hidden_fits_on_first_open_without_coordinate_inflation(self):
        self.root.setProperty("page", 0)
        for _ in range(3):
            self.controller.dirty = False  # Fixture models are treated as saved.
            self.controller.loadDemo()
            QTest.qWait(80)
        view = self.visual_item("networkView")
        points = self.json_value(view, "positions")
        self.assertTrue(points)
        self.assertLess(max(p["x"] for p in points.values()), 2000)
        self.assertLess(max(p["y"] for p in points.values()), 1200)
        self.root.setProperty("page", 3)
        QTest.qWait(120)
        navigation.NetworkNavigationTests.assert_whole_nodes_fit(self)
        self.assertFalse(view.property("fitOnShow"))
        viewport = self.visual_item("networkViewport")
        camera = (viewport.property("contentX"), viewport.property("contentY"))
        self.root.setProperty("page", 0)
        QTest.qWait(40)
        self.root.setProperty("page", 3)
        QTest.qWait(100)
        self.assertAlmostEqual(viewport.property("contentX"), camera[0], delta=1)
        self.assertAlmostEqual(viewport.property("contentY"), camera[1], delta=1)
        self.assertEqual(self.warnings, [])

    def test_grow_left_up_preserves_other_screen_positions_and_model(self):
        view = self.show_network()
        viewport = self.visual_item("networkViewport")
        key = object_key("Generator", "Thermal")
        peer = self.visual_item("networkObject-Bus-North")
        before_position = peer.mapToItem(viewport, peer.boundingRect().center())
        before = deepcopy(self.controller.project.to_dict())
        self.assertTrue(view.moveObject(key, -350, -200))
        QTest.qWait(80)
        after = peer.mapToItem(viewport, peer.boundingRect().center())
        self.assertAlmostEqual(before_position.x(), after.x(), delta=0.1)
        self.assertAlmostEqual(before_position.y(), after.y(), delta=0.1)
        point = self.json_value(view, "positions")[key]
        self.assertEqual(point, dict(x=80, y=90))
        self.assertGreater(viewport.property("contentX"), 0)
        self.assertGreater(viewport.property("contentY"), 0)
        # The real gesture also crosses the logical origin without hitting an
        # invisible stop or making other nodes jump.
        view.moveObject(key, 300, 250)
        viewport.setProperty("contentX", view.property("paperMargin"))
        viewport.setProperty("contentY", view.property("paperMargin"))
        QTest.qWait(50)
        before_position = peer.mapToItem(viewport, peer.boundingRect().center())
        node = self.visual_item("networkObject-Generator-Thermal")
        start = node.mapToScene(node.boundingRect().center()).toPoint()
        stop = viewport.mapToScene(viewport.boundingRect().topLeft()).toPoint()+QPoint(40, 40)
        self.drag(start, stop)
        after = peer.mapToItem(viewport, peer.boundingRect().center())
        self.assertAlmostEqual(before_position.x(), after.x(), delta=1)
        self.assertAlmostEqual(before_position.y(), after.y(), delta=1)
        self.assertLess((node.mapToScene(node.boundingRect().center()).toPoint()-stop).manhattanLength(), 5)
        self.assertEqual(self.controller.project.to_dict(), before)
        self.assertEqual(self.warnings, [])

    def test_drag_near_edge_auto_scrolls_and_stops_on_release(self):
        view = self.show_network()
        viewport = self.visual_item("networkViewport")
        key = object_key("Generator", "Thermal")
        view.moveObject(key, 300, 160)
        view.setProperty("zoomFactor", 1)
        viewport.setProperty("contentX", view.property("paperMargin"))
        viewport.setProperty("contentY", view.property("paperMargin"))
        QTest.qWait(50)
        node = self.visual_item("networkObject-Generator-Thermal")
        start = node.mapToScene(node.boundingRect().center()).toPoint()
        stop = viewport.mapToScene(viewport.boundingRect().topRight()).toPoint()+QPoint(-15, 160)
        initial = viewport.property("contentX")
        QTest.mousePress(self.root, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(self.root, start+QPoint(30, 0), 30)
        QTest.mouseMove(self.root, stop, 60)
        QTest.qWait(180)
        self.assertGreater(viewport.property("contentX"), initial)
        QTest.mouseRelease(self.root, Qt.MouseButton.LeftButton, pos=stop)
        QTest.qWait(40)
        at_release = viewport.property("contentX")
        QTest.qWait(100)
        self.assertEqual(viewport.property("contentX"), at_release)
        self.assertIsNone(view.property("activeDrag"))
        self.assertEqual(self.warnings, [])

    def test_blank_pan_and_both_scrollbars_leave_positions_unchanged(self):
        view = self.show_network()
        viewport = self.visual_item("networkViewport")
        before = self.json_value(view, "positions")
        first_x, first_y = viewport.property("contentX"), viewport.property("contentY")
        start = viewport.mapToScene(viewport.boundingRect().topLeft()).toPoint()+QPoint(24, 24)
        self.drag(start, start+QPoint(80, 55))
        self.evaluate(viewport, "cancelFlick()")
        self.assertLess(viewport.property("contentX"), first_x)
        self.assertLess(viewport.property("contentY"), first_y)
        viewport.setProperty("contentX", first_x)
        viewport.setProperty("contentY", first_y)
        QTest.qWait(40)
        for name, delta, prop in [
            ("networkHorizontalScroll", QPoint(60, 0), "contentX"),
            ("networkVerticalScroll", QPoint(0, 45), "contentY"),
        ]:
            bar = self.visual_item(name)
            self.assertTrue(bar.isVisible())
            thumb = bar.property("contentItem")
            start = thumb.mapToScene(thumb.boundingRect().center()).toPoint()
            initial = viewport.property(prop)
            self.drag(start, start+delta)
            self.assertGreater(viewport.property(prop), initial)
        self.assertEqual(self.json_value(view, "positions"), before)
        self.assertEqual(self.warnings, [])

    def test_ctrl_wheel_zooms_around_cursor_without_moving_objects(self):
        view = self.show_network()
        viewport = self.visual_item("networkViewport")
        local = QPointF(viewport.width()*0.7, viewport.height()*0.4)
        before = self.json_value(view, "positions")
        zoom = view.property("zoomFactor")
        old_x = (viewport.property("contentX")+local.x()-view.property("paperMargin"))/zoom
        old_y = (viewport.property("contentY")+local.y()-view.property("paperMargin"))/zoom
        position = viewport.mapToScene(local)
        event = QWheelEvent(position, QPointF(self.root.mapToGlobal(position.toPoint())),
                            QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.ControlModifier, Qt.ScrollPhase.NoScrollPhase, False)
        self.app.sendEvent(self.root, event)
        QTest.qWait(100)
        new_zoom = view.property("zoomFactor")
        self.assertGreater(new_zoom, zoom)
        self.assertAlmostEqual((viewport.property("contentX")+local.x()-view.property("paperMargin"))/new_zoom, old_x, delta=1)
        self.assertAlmostEqual((viewport.property("contentY")+local.y()-view.property("paperMargin"))/new_zoom, old_y, delta=1)
        self.assertEqual(self.json_value(view, "positions"), before)
        self.assertEqual(self.warnings, [])

    def test_large_paper_has_viewport_sized_renderer_and_saves_reopens(self):
        view = self.show_network()
        viewport = self.visual_item("networkViewport")
        key = object_key("Generator", "Thermal")
        self.assertTrue(view.moveObject(key, 42000, 26000))
        QTest.qWait(60)
        renderer = self.visual_item("networkTopologyCanvas")
        self.assertAlmostEqual(renderer.width(), viewport.width())
        self.assertAlmostEqual(renderer.height(), viewport.height())
        self.assertGreater(view.property("canvasWidth"), 42000)
        self.assertGreater(view.property("canvasHeight"), 26000)
        layout = self.json_value(view, "layoutData()")
        self.assertEqual(layout["paperVersion"], 1)
        checked_layout(layout, set(layout["positions"]))
        self.controller.path = Path(self.temp.name) / "playground.sqlite"
        self.assertTrue(self.controller.saveNetworkLayout(self.controller.networkState["viewKey"], layout))
        saved = load_project(self.controller.path).schematic_layouts["current"]
        self.assertEqual(saved["positions"][key], dict(x=42000, y=26000))
        self.assertEqual(saved["paperVersion"], 1)
        with patch.object(QFileDialog, "getOpenFileName", return_value=(str(self.controller.path), "SQLite")):
            self.controller.openProject()
        QTest.qWait(100)
        self.assertEqual(self.json_value(view, "positions")[key], dict(x=42000, y=26000))
        self.assertAlmostEqual(viewport.property("contentX"), saved["panX"])
        self.assertFalse(view.moveObject(key, 100001, 0))
        self.assertEqual(self.warnings, [])

    def test_legacy_camera_converts_in_memory_without_rewriting_file(self):
        # Load into a genuinely unvisited Network tab (the normal application
        # opening path), not a viewport already laid out by show_network().
        self.controller.loadDemo()
        view = self.visual_item("networkView")
        viewport = self.visual_item("networkViewport")
        key = object_key("Generator", "Thermal")
        old = dict(positions={key: dict(x=450, y=260)}, zoom=0.7,
                   panX=50, panY=70, width=1200, height=800)
        self.controller.project.schematic_layouts["current"] = old
        self.controller.path = Path(self.temp.name) / "legacy.sqlite"
        save_project(self.controller.project, self.controller.path)
        self.controller.dirty = False
        original = self.controller.path.read_bytes()
        with patch.object(QFileDialog, "getOpenFileName", return_value=(str(self.controller.path), "SQLite")):
            self.controller.openProject()
        QTest.qWait(100)
        self.root.setProperty("page", 3)
        QTest.qWait(100)
        node = self.visual_item("networkObject-Generator-Thermal")
        center = node.mapToItem(viewport, node.boundingRect().center())
        self.assertAlmostEqual(center.x(), 450*0.7-50+max(0, (viewport.width()-1200*0.7)/2), delta=1)
        self.assertAlmostEqual(center.y(), 260*0.7-70+max(0, (viewport.height()-800*0.7)/2), delta=1)
        self.assertEqual(self.controller.path.read_bytes(), original)
        self.assertNotIn("paperVersion", load_project(self.controller.path).schematic_layouts["current"])
        self.assertEqual(self.warnings, [])

    def test_frozen_flows_queries_footer_and_themed_playground_isolation(self):
        view, run = self.frozen_network(results=True)
        frozen = {p: p.read_bytes() for p in run.rglob("*") if p.is_file()}
        tab = self.controller.workspace.active
        frame = tab.frame.copy(deep=True)
        key = object_key("Line", "L")
        view.moveObject(key, 1400, 1100)
        view.fitView()
        QTest.qWait(80)
        for mode in ["Light", "Dark"]:
            self.appearance.setMode(mode)
            for width, height in [(1140, 760), (1440, 920)]:
                self.root.resize(width, height)
                QTest.qWait(70)
                view.fitView()
                QTest.qWait(60)
                output = os.environ.get("STUDIO_PLAYGROUND_EVIDENCE")
                if output:
                    dest = Path(output)
                    dest.mkdir(parents=True, exist_ok=True)
                    self.root.grabWindow().save(str(dest / f"playground-{mode.lower()}-{width}.png"))
        self.assertTrue(tab.frame.equals(frame))
        self.assertEqual({p: p.read_bytes() for p in frozen}, frozen)
        main = Path(__file__).resolve().parents[1] / "energy_gui/qml/Main.qml"
        self.assertNotIn("No AI · no cloud · SQLite project storage", main.read_text(encoding="utf-8"))
        self.assertEqual(self.warnings, [])
