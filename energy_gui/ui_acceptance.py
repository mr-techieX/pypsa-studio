"""Development-only offscreen GUI measurements, no user project writes."""

import os
from pathlib import Path
import platform
import sys
import tempfile
from time import perf_counter


def measure_ui():
    start = perf_counter()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from .schema import registry  # Scientific imports before Qt's import hook.
    from .appearance import Appearance
    from .controller import Controller
    from .demo_library import DEMO_SPECS
    from PySide6.QtCore import QMetaObject, QObject, QSettings, QUrl
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    import_s = perf_counter()-start
    preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
    with tempfile.TemporaryDirectory(prefix="stage3e_ui_", dir=preferred) as tmp:
        before = perf_counter()
        app = QApplication.instance() or QApplication([])
        QQuickStyle.setStyle("Basic")
        controller = Controller()
        appearance = Appearance(QSettings(str(Path(tmp)/"appearance.ini"), QSettings.Format.IniFormat))
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty("backend", controller)
        engine.rootContext().setContextProperty("appearance", appearance)
        warnings = []
        engine.warnings.connect(lambda messages: warnings.extend(str(m) for m in messages))
        engine.load(QUrl.fromLocalFile(str(Path(__file__).parent/"qml"/"Main.qml")))
        if not engine.rootObjects():
            raise RuntimeError("QML probe failed: " + "\n".join(warnings))
        root = engine.rootObjects()[0]
        QTest.qWait(80)
        window_s = perf_counter()-before
        cases = []
        for spec in DEMO_SPECS:
            controller.dirty = False  # Only discard the previous generated probe case.
            before = perf_counter()
            if not controller.loadDemoModel(spec["id"]):
                raise RuntimeError("Probe could not load " + spec["id"])
            root.setProperty("page", 1)
            controller.selectType("Bus")  # Exercise all 2–20 bus rows, not just a few generators.
            app.processEvents()
            if not root.findChild(QObject, "objectSpreadsheet").isVisible():
                QMetaObject.invokeMethod(root.findChild(QObject, "objectEditorToggle"), "clicked")
            QTest.qWait(80)
            sheet_s = perf_counter()-before
            before = perf_counter()
            root.setProperty("page", 3)
            QTest.qWait(80)
            root.findChild(QObject, "networkView").fitView()
            QTest.qWait(80)
            if root.grabWindow().isNull():
                raise RuntimeError("Diagram failed to render.")
            cases.append(dict(id=spec["id"], sheet_component="Bus", sheet_rows=spec["buses"],
                              load_and_sheet_s=sheet_s, network_fit_render_s=perf_counter()-before))
        controller.dirty = False
        root.close()
        engine.deleteLater()
        app.processEvents()
        if warnings:
            raise RuntimeError("QML probe warnings: " + "\n".join(warnings))
    from datetime import datetime, timezone
    import importlib.metadata
    from .acceptance import peak_memory_mib
    return dict(created_utc=datetime.now(timezone.utc).isoformat(), python=platform.python_version(),
                platform=platform.platform(), versions={p: importlib.metadata.version(p) for p in ["pypsa", "PySide6"]},
                methodology="One offscreen GUI process, 1440x920, Bus spreadsheet (2–20 rows). Import timing includes scientific/Qt imports. Window/sheet/diagram times include fixed event-settle waits of 80/80/160 ms respectively. Diagram timing also includes image capture; this is not an interactive FPS test or native desktop launch measurement. Memory is peak process working set/RSS, not additional model-only memory.",
                import_s=import_s, window_s=window_s, cold_window_total_s=import_s+window_s,
                peak_process_memory_mib=peak_memory_mib(), cases=cases)
