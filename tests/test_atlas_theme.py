"""Atlas role fidelity, rendered controls, live-switch isolation and print exports."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET

import test_qml_controls as _controls
from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
import pandas as pd

from energy_gui.reporting import chart_svg, write_chart, write_report
from test_network_view import overlay_fixture


def contrast(first, second):
    def luminance(value):
        color = QColor(value)
        linear = [
            v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
            for v in [color.redF(), color.greenF(), color.blueF()]
        ]
        return sum(v * w for v, w in zip(linear, [0.2126, 0.7152, 0.0722]))
    high, low = sorted([luminance(first), luminance(second)], reverse=True)
    return (high + 0.05) / (low + 0.05)


class AtlasThemeTests(unittest.TestCase):
    setUpClass = classmethod(_controls.QmlControlsTests.setUpClass.__func__)
    setUp = _controls.QmlControlsTests.setUp
    tearDown = _controls.QmlControlsTests.tearDown
    evaluate = _controls.QmlControlsTests.evaluate
    visual_item = _controls.QmlControlsTests.visual_item

    def token(self, name):
        return self.evaluate(self.root, f"appTheme.{name}.toString()")

    def test_reference_roles_header_navigation_checks_and_chart_defaults(self):
        # Pin the reviewed roles, rather than comparing a token only with itself.
        for mode, selection, primary, primary_text, chart in [
            ("Light", "#acd0c2", "#245d5a", "#ffffff", "#236b66"),
            ("Dark", "#665222", "#e6b552", "#152c38", "#e6b552"),
        ]:
            self.appearance.setMode(mode)
            self.root.setProperty("page", 6)
            QTest.qWait(80)
            self.assertEqual(self.token("selected"), selection)
            self.assertEqual(self.token("primary"), primary)
            self.assertEqual(self.token("primaryText"), primary_text)
            self.assertEqual(self.evaluate(self.root, "appTheme.chartColors[0]"), chart)
            header = self.root.findChild(QObject, "atlasHeader")
            self.assertEqual(header.property("color").name(), self.token("header"))
            self.assertEqual(
                self.root.findChild(QObject, "atlasProjectTitle").property("color").name(),
                self.token("headerInk"),
            )
            image = self.root.grabWindow()
            self.assertFalse(image.isNull())
            self.assertEqual(image.pixelColor(3, 3).name(), self.token("header"))
            tab = self.visual_item("ribbonPage-6")
            self.assertEqual(tab.property("background").property("color").name(), selection)
            checkbox = self.visual_item("configCategory-Bus")
            self.assertTrue(checkbox.property("checked"))
            self.assertEqual(checkbox.property("indicator").property("color").name(), primary)
            # Pointer clicks and keyboard toggles must retain normal semantics.
            checkbox.forceActiveFocus()
            QTest.keyClick(self.root, Qt.Key.Key_Space)
            self.assertFalse(checkbox.property("checked"))
            QTest.keyClick(self.root, Qt.Key.Key_Space)
            self.assertTrue(checkbox.property("checked"))
            select = self.root.findChild(QObject, "themeSelect")
            self.assertEqual(select.property("contentItem").property("color").name(), self.token("headerInk"))
        self.assertEqual(self.warnings, [])

    def test_extended_contrast_and_distinct_alert_selection_roles(self):
        for mode in ["Light", "Dark"]:
            self.appearance.setMode(mode)
            for foreground, background in [
                ("headerInk", "header"), ("headerMuted", "header"),
                ("headerInk", "headerHover"), ("ink", "selected"),
                ("ink", "button"), ("muted", "button"), ("ink", "buttonDown"),
                ("primaryText", "primary"), ("primaryText", "primaryHover"),
                ("calloutInk", "callout"),
            ]:
                self.assertGreaterEqual(
                    contrast(self.token(foreground), self.token(background)), 4.5,
                    (mode, foreground, background),
                )
            for role in ["warning", "danger", "success", "wind", "solar", "hydro",
                         "gas", "biomass", "storage", "neutral", "focus"]:
                self.assertGreaterEqual(contrast(self.token(role), self.token("panel")), 3,
                                        (mode, role))
            for alert in ["warning", "danger"]:
                self.assertNotEqual(self.token(alert), self.token("focus"))
                self.assertNotEqual(self.token(alert), self.token("primary"))
            # Disabled checkbox indicators must also remain readable.
            self.assertGreaterEqual(contrast(self.token("ink"), self.token("buttonDown")), 4.5)
        self.assertEqual(self.warnings, [])

    def test_carrier_technology_colors_do_not_guess_from_object_names(self):
        for mode in ["Light", "Dark"]:
            self.appearance.setMode(mode)
            for carrier, kind, role in [
                ("offwind-ac", "Generator", "wind"), ("solar", "Generator", "solar"),
                ("ror", "Generator", "hydro"), ("biogas", "Generator", "biomass"),
                ("CCGT", "Generator", "gas"), ("coal", "Generator", "gas"),
                ("", "StorageUnit", "storage"), ("battery", "Store", "storage"),
                ("AC", "Bus", "neutral"), ("", "Generator", "neutral"),
            ]:
                actual = self.evaluate(
                    self.root,
                    f"appTheme.technologyColor({json.dumps(carrier)}, {json.dumps(kind)}).toString()",
                )
                self.assertEqual(actual, self.token(role))
        self.assertEqual(self.warnings, [])

    def test_live_switch_preserves_drafts_queries_frozen_flows_and_layout(self):
        run = Path(self.temp.name) / "runs" / "atlas-fixture"
        project, _ = overlay_fixture(run)
        self.controller.project = project
        self.controller.path = Path(self.temp.name) / "project.sqlite"
        self.controller._reset_helpers()
        self.controller._reset_draft()
        self.assertTrue(self.controller.openRun(str(run)))
        self.assertTrue(self.controller.queryResults("Line", ["L"], ["p0"], "", ""))
        self.assertTrue(self.controller.loadNetworkRun(str(run)))
        self.root.setProperty("page", 3)
        QTest.qWait(100)
        network = self.root.findChild(QObject, "networkView")
        key = json.dumps(["Line", "L"])
        network.setProperty("activeObject", key)
        frozen_project = deepcopy(self.controller.project.to_dict())
        positions = self.evaluate(network, "JSON.stringify(positions)")
        network_context = deepcopy(self.controller.networkState)
        frame = self.controller.workspace.active.frame.copy(deep=True)
        self.root.setProperty("page", 0)
        self.root.findChild(QObject, "projectNameInput").setProperty("text", "Unsaved Atlas draft")
        draft = deepcopy(self.controller.helperState)
        for mode in ["Dark", "Light", "Dark", "Light", "System"]:
            self.appearance.setMode(mode)
            QTest.qWait(80)
            self.assertEqual(self.controller.project.to_dict(), frozen_project)
            self.assertEqual(self.controller.helperState, draft)
            self.assertEqual(self.controller.networkState, network_context)
            self.assertEqual(self.evaluate(network, "JSON.stringify(positions)"), positions)
            pd.testing.assert_frame_equal(self.controller.workspace.active.frame, frame)
            self.assertEqual(self.evaluate(network, "activeObject"), key)
            self.assertFalse(self.root.grabWindow().isNull())
        self.assertEqual(self.warnings, [])

    def test_selected_network_color_never_hides_congestion(self):
        run = Path(self.temp.name) / "runs" / "atlas-flows"
        project, _ = overlay_fixture(run)
        self.controller.project = project
        self.controller.path = Path(self.temp.name) / "project.sqlite"
        self.controller._reset_helpers()
        self.controller._reset_draft()
        self.assertTrue(self.controller.loadNetworkRun(str(run)))
        self.root.setProperty("page", 3)
        QTest.qWait(80)
        view = self.root.findChild(QObject, "networkView")
        key = json.dumps(["Line", "L"])
        self.evaluate(view, f"activeObject = {json.dumps(key)}")
        expression = "topology.wires.find(function(w) { return w.port === 'bus0' })"
        for mode in ["Light", "Dark"]:
            self.appearance.setMode(mode)
            style = self.evaluate(view, f"wireAppearance({expression}).color")
            self.assertEqual(style, self.token("focus"))
            label = self.visual_item("flowLabel-" + key + "-bus0")
            self.assertEqual(label.property("color").name(), self.token("callout"))
            self.evaluate(view, "congestionEnabled = true")
            wire = json.loads(self.evaluate(view, f"JSON.stringify({expression})"))
            for percent, role in [(95, "warning"), (120, "danger")]:
                test_wire = wire | {"utilisation": percent, "flow": 1, "unit": "MW", "attribute": "p0"}
                actual = self.evaluate(view, f"wireAppearance({json.dumps(test_wire)}).color")
                self.assertEqual(actual, self.token(role))
            self.evaluate(view, "congestionEnabled = false")
        self.assertEqual(self.warnings, [])

    def test_print_exports_use_atlas_and_preserve_escaped_content(self):
        charts = [dict(title="Flow <&>", unit="MW", kind=kind, labels=["0", "1"],
                       series=[dict(name="L <&>", values=[1, 2])])
                  for kind in ["line", "bar", "dot", "stacked area", "horizontal bar"]]
        svg = chart_svg(charts)
        ET.fromstring(svg)
        self.assertIn("#236b66", svg)
        for legacy in ["#5c5c99", "#292966", "#a3a3cc", "#ccccff"]:
            self.assertNotIn(legacy, svg.lower())
        self.assertIn("Flow &lt;&amp;&gt;", svg)
        for extension in ["svg", "png"]:
            path = Path(self.temp.name) / ("chart." + extension)
            write_chart(path, charts)
            self.assertTrue(path.is_file())
            if extension == "png":
                self.assertFalse(QImage(str(path)).isNull())
        tab = SimpleNamespace(
            title="<Atlas>", run_path="run", description="<script>bad</script>",
            criteria={}, frame=pd.DataFrame({"value": [1, 2]}),
        )
        path = Path(self.temp.name) / "report.html"
        write_report(path, tab, charts, {})
        html = path.read_text(encoding="utf-8")
        self.assertIn("#acd0c2", html)
        self.assertIn("@media print", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("#292966", html)

    def test_chart_canvas_repaints_with_actual_light_dark_series_pixels(self):
        run = Path(self.temp.name) / "runs" / "atlas-chart"
        project, _ = overlay_fixture(run)
        self.controller.project = project
        self.controller.path = Path(self.temp.name) / "project.sqlite"
        self.controller._reset_helpers()
        self.controller._reset_draft()
        self.assertTrue(self.controller.openRun(str(run)))
        self.assertTrue(self.controller.queryResults("Line", ["L"], ["p0"], "", ""))
        self.assertTrue(self.controller.setChartType("p0", "bar"))
        self.root.setProperty("page", 5)
        self.root.findChild(QObject, "resultsExplorer").setProperty("resultView", 1)
        for mode, expected in [("Light", "#236b66"), ("Dark", "#e6b552"), ("Light", "#236b66")]:
            self.appearance.setMode(mode)
            QTest.qWait(200)
            chart = self.visual_item("queryChart-p0")
            self.assertTrue(chart.isVisible())
            bounds = chart.mapRectToScene(chart.boundingRect()).toAlignedRect()
            image = self.root.grabWindow().copy(bounds).convertToFormat(QImage.Format.Format_RGB32)
            pixel = QColor(expected).rgb().to_bytes(4, "little")
            self.assertGreater(bytes(image.constBits()).count(pixel), 30, (mode, expected))
        self.assertEqual(self.warnings, [])
