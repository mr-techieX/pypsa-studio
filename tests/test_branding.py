"""The selected icon is vector artwork, renders at small sizes, and reaches Qt/Windows."""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET

import test_qml_controls as _controls
from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QIcon, QImage, QPainter
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtTest import QTest

from energy_gui.branding import ICON_PATH, configure_application_icon


class BrandingTests(unittest.TestCase):
    setUpClass = classmethod(_controls.QmlControlsTests.setUpClass.__func__)
    setUp = _controls.QmlControlsTests.setUp
    tearDown = _controls.QmlControlsTests.tearDown
    evaluate = _controls.QmlControlsTests.evaluate
    visual_item = _controls.QmlControlsTests.visual_item

    def test_master_is_self_contained_vector_and_renders_at_icon_sizes(self):
        text = ICON_PATH.read_text(encoding="utf-8")
        root = ET.fromstring(text)
        self.assertEqual(root.attrib["viewBox"], "0 0 256 256")
        tags = {item.tag.split("}")[-1] for item in root.iter()}
        self.assertTrue(tags <= {"svg", "title", "desc", "rect", "path"})
        for unwanted in ["<image", "data:image", "<script", "href="]:
            self.assertNotIn(unwanted, text)
        self.assertEqual(
            {item.attrib["fill"] for item in root if "fill" in item.attrib},
            {"#f7f3e8", "#15384a", "#287e71", "#e6b552"},
        )
        renderer = QSvgRenderer(str(ICON_PATH))
        self.assertTrue(renderer.isValid())
        icon = QIcon(str(ICON_PATH))
        for size in [16, 20, 24, 30, 32, 48, 64, 128, 256, 512]:
            image = QImage(size, size, QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            renderer.render(painter)
            painter.end()
            self.assertFalse(icon.pixmap(size, size).isNull())
            # Uniform cream tile, transparent corners, opaque mark: no PNG artifacts.
            self.assertEqual(image.pixelColor(size // 2, size // 10).name(), "#f7f3e8")
            self.assertLess(image.pixelColor(0, 0).alpha(), 64)  # Tiny sizes antialias the corner.
            self.assertEqual(image.pixelColor(size // 2, size // 2).alpha(), 255)

    def test_header_loads_the_same_vector_in_both_themes(self):
        badge = self.visual_item("studioAppIcon")
        self.assertIsNotNone(badge)
        self.assertEqual(Path(badge.property("source").toLocalFile()), ICON_PATH)
        for mode in ["Light", "Dark"]:
            self.appearance.setMode(mode)
            QTest.qWait(100)
            self.assertTrue(self.evaluate(badge, "status === 1"))  # QQuickImage.Ready
            self.assertEqual(round(badge.width()), 30)
            self.assertEqual(round(badge.height()), 30)
            bounds = badge.mapRectToScene(badge.boundingRect()).toAlignedRect()
            image = self.root.grabWindow().copy(bounds)
            self.assertFalse(image.isNull())
            self.assertEqual(image.pixelColor(image.width() // 2, 3).name(), "#f7f3e8")
        self.assertEqual(self.warnings, [])

    def test_application_and_window_receive_the_vector_icon(self):
        previous = self.app.windowIcon()
        desktop = self.app.desktopFileName()
        try:
            configure_application_icon(self.app)
            QTest.qWait(30)
            self.assertEqual(self.app.desktopFileName(), "pypsa-studio")
            self.assertFalse(self.app.windowIcon().isNull())
            self.assertFalse(self.root.icon().isNull())
            self.assertEqual(self.app.windowIcon().cacheKey(), self.root.icon().cacheKey())
            self.assertFalse(self.root.icon().pixmap(16, 16).isNull())
        finally:
            self.app.setWindowIcon(previous)
            self.app.setDesktopFileName(desktop)

    def test_actual_entrypoint_applies_icon_offscreen_and_on_windows(self):
        # Fresh processes exercise the production startup path, not just the helper.
        directory = Path(os.environ.get("STUDIO_ICON_EVIDENCE", self.temp.name))
        directory.mkdir(parents=True, exist_ok=True)
        platforms = ["offscreen", "windows"] if sys.platform == "win32" else ["offscreen"]
        for platform in platforms:
            for mode in ["Light", "Dark"]:
                output = directory / (platform + "-" + mode.lower())
                output.mkdir(exist_ok=True)
                root = Path(__file__).resolve().parents[1]
                env = dict(
                    os.environ, QT_QPA_PLATFORM=platform,
                    PYTHONPATH=os.pathsep.join([str(root), str(root / "tests")]),
                )
                completed = subprocess.run(
                    [sys.executable, str(Path(__file__).resolve()), "--probe", mode, str(output)],
                    cwd=Path(__file__).resolve().parents[1], env=env,
                    capture_output=True, text=True, timeout=60,
                )
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                result = json.loads((output / "result.json").read_text(encoding="utf-8"))
                self.assertTrue(result["application_icon"])
                self.assertTrue(result["window_icon"])
                self.assertTrue(result["header_ready"])
                if platform == "windows":
                    self.assertTrue(result["native_big_icon"])
                    self.assertTrue(result["native_small_icon"])


def probe(mode, output):
    """Observe the real entry point after its QML window appears, then exit cleanly."""
    from energy_gui import branding
    from energy_gui.__main__ import main

    output = Path(output)
    original = branding.configure_application_icon

    def configure(app):
        original(app)

        def inspect():
            try:
                window = next(w for w in app.topLevelWindows() if w.findChild(QObject, "studioAppIcon"))
                badge = window.findChild(QObject, "studioAppIcon")
                expression = QQmlExpression(QQmlEngine.contextForObject(badge), badge, "status === 1")
                header_ready, _ = expression.evaluate()
                assert not expression.hasError(), expression.error().toString()
                result = dict(
                    theme=mode, platform=QGuiApplication.platformName(),
                    application_icon=not app.windowIcon().isNull(),
                    window_icon=not window.icon().isNull(),
                    header_ready=header_ready,
                    desktop_file=app.desktopFileName(),
                )
                if result["platform"] == "windows":
                    import ctypes
                    from ctypes import wintypes
                    user32 = ctypes.windll.user32
                    user32.SendMessageW.argtypes = [
                        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                    ]
                    user32.SendMessageW.restype = ctypes.c_ssize_t
                    hwnd = int(window.winId())
                    # WM_GETICON verifies the native handles published by Qt.
                    result["native_big_icon"] = bool(user32.SendMessageW(hwnd, 0x007F, 1, 0))
                    result["native_small_icon"] = bool(user32.SendMessageW(hwnd, 0x007F, 0, 0))
                    assert result["native_big_icon"] and result["native_small_icon"], result
                assert result["application_icon"] and result["window_icon"] and result["header_ready"], result
                assert window.grabWindow().save(str(output / "window.png"))
                renderer = QSvgRenderer(str(ICON_PATH))
                image = QImage(512, 512, QImage.Format.Format_ARGB32)
                image.fill(Qt.GlobalColor.transparent)
                painter = QPainter(image)
                renderer.render(painter)
                painter.end()
                assert image.save(str(output / "vector-preview.png"))
                (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
                app.exit(0)
            except Exception:
                import traceback
                traceback.print_exc()
                app.exit(1)

        QTimer.singleShot(200, inspect)

    branding.configure_application_icon = configure
    sys.argv = ["energy_gui", "--smoke-test", "--theme", mode]
    return main()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--probe":
        raise SystemExit(probe(sys.argv[2], sys.argv[3]))
    unittest.main()
