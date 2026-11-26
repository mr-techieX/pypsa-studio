"""Entry point: run with the parent EnEx Python, from the versioned build folder."""

import argparse
import os
from pathlib import Path
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true", help="Load all QML pages offscreen and exit.")
    parser.add_argument("--screenshot", help="Optional local PNG from the smoke test.")
    parser.add_argument("--solve-demo", action="store_true", help="With --smoke-test, exercise a real demo solve before rendering pages.")
    parser.add_argument("--theme", choices=["Light", "Dark", "System"], help="Theme override for render tests (not persisted).")
    from .demo_library import DEMO_SPECS
    parser.add_argument("--demo", choices=[s["id"] for s in DEMO_SPECS], help="Load a selected local demo (also selects the smoke/solve case).")
    args = parser.parse_args()
    if args.smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # Import the scientific stack before PySide installs its module-inspection
    # hook. On this Python/Qt combination the reverse order is extremely slow.
    from .schema import registry
    from PySide6.QtCore import QMetaObject, QObject, QStandardPaths, QTimer, QUrl
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication
    from .controller import Controller
    from .appearance import Appearance
    from .branding import configure_application_icon

    app = QApplication(sys.argv[:1])
    if args.smoke_test and sys.platform == "win32":
        # Qt's offscreen platform does not discover Windows system fonts itself.
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for filename in ["segoeui.ttf", "segoeuib.ttf", "consola.ttf", "seguisym.ttf"]:
            if (fonts / filename).exists():
                QFontDatabase.addApplicationFont(str(fonts / filename))
    app.setApplicationName("PyPSA Studio v1.3.1")
    app.setApplicationVersion("1.3.1")
    app.setOrganizationName("Local Energy Workbench")
    configure_application_icon(app)
    QQuickStyle.setStyle("Basic")
    controller = Controller()
    if not args.smoke_test:
        try:
            controller.enableRecovery(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)) / "recovery")
        except Exception as error:
            QTimer.singleShot(500, lambda error=error: controller.notice.emit("Recovery unavailable; use Save/backup. " + str(error)))
    appearance = Appearance()
    if args.theme:
        appearance._mode = args.theme
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", controller)
    engine.rootContext().setContextProperty("appearance", appearance)
    qml_warnings = []
    engine.warnings.connect(lambda warnings: qml_warnings.extend(str(w) for w in warnings))
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parent / "qml" / "Main.qml")))
    if not engine.rootObjects():
        print("QML failed to load:", *qml_warnings, sep="\n", file=sys.stderr)
        return 1
    if args.smoke_test:
        root = engine.rootObjects()[0]
        controller.loadDemoModel(args.demo or "urban3")
        smoke_temp = None
        if args.solve_demo:
            preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
            smoke_temp = tempfile.TemporaryDirectory(prefix="pypsa_gui_smoke_", dir=preferred)
            controller.path = Path(smoke_temp.name) / "project.sqlite"

        def capture(suffix):
            if args.screenshot:
                path = Path(args.screenshot)
                path.parent.mkdir(parents=True, exist_ok=True)
                path = path.with_name(path.stem + suffix + path.suffix)
                if not root.grabWindow().save(str(path)):
                    qml_warnings.append("Could not capture screenshot: " + str(path))

        def visit(index=0):
            if index < 7:
                root.setProperty("page", index)
                if index == 1:
                    controller.selectType("Generator")
                    controller.selectObject(next(r["name"] for r in controller.project.objects if r["component"] == "Generator"))
                def capture_page():
                    capture("-" + str(index))
                    if index == 1:
                        toggle = root.findChild(QObject, "objectEditorToggle")
                        QMetaObject.invokeMethod(toggle, "clicked")
                        def capture_sheet():
                            capture("-1-sheet")
                            QMetaObject.invokeMethod(toggle, "clicked")
                            visit(index+1)
                        QTimer.singleShot(150, capture_sheet)
                        return
                    if index == 5:
                        root.findChild(QObject, "resultsExplorer").setProperty("resultView", 1)
                        QTimer.singleShot(150, lambda: (capture("-5-charts"), visit(index+1)))
                    elif index == 3 and args.solve_demo:
                        schematic = root.findChild(QObject, "networkView")
                        data = {"positions": schematic.property("positions").toVariant(),
                                "zoom": schematic.property("zoomFactor"),
                                "panX": root.findChild(QObject, "networkViewport").property("contentX"),
                                "panY": root.findChild(QObject, "networkViewport").property("contentY"),
                                 "width": schematic.property("sceneWidth"), "height": schematic.property("sceneHeight"),
                                 "paperVersion": 1}
                        if not controller.saveNetworkLayout(controller.networkState["viewKey"], data):
                            qml_warnings.append("Could not save schematic layout.")
                        if not controller.loadNetworkRun(str(controller.run_directory)):
                            qml_warnings.append("Could not load frozen-run flows.")
                        def capture_flows():
                            capture("-3-flows")
                            controller.setNetworkSnapshot(min(12, len(controller.project.snapshots)-1))
                            branch = next(o for o in controller.networkState["topology"]["objects"] if o["kind"] == "Line")
                            schematic.setProperty("activeObject", branch["key"])
                            QTimer.singleShot(150, lambda: (capture("-3-flows-details"), controller.showLiveNetwork(), visit(index+1)))
                        QTimer.singleShot(150, lambda: (schematic.fitView(), QTimer.singleShot(150, capture_flows)))
                    else:
                        visit(index+1)
                QTimer.singleShot(150, capture_page)
                return
            root.setProperty("page", 1)
            help_window = root.findChild(QObject, "referenceHelp")
            help_window.showReference("Generator", "p_nom")

            def capture_help():
                capture("-help")
                root.resize(1140, 760)
                help_window.showReference("Network", "snapshot_weightings")
                QTimer.singleShot(150, finish_help)

            def finish_help():
                capture("-help-minimum")
                help_window.close()
                QTimer.singleShot(150, capture_ribbon)

            def capture_ribbon():
                capture("-ribbon-minimum")
                QMetaObject.invokeMethod(root.findChild(QObject, "ribbonFile"), "clicked")
                QTimer.singleShot(150, finish_ribbon)

            def finish_ribbon():
                capture("-ribbon-menu")
                root.findChild(QObject, "ribbonFileMenu").close()
                root.setProperty("page", 3)
                if args.solve_demo:
                    controller.loadNetworkRun(str(controller.run_directory))
                def capture_minimum():
                    root.findChild(QObject, "networkView").fitView()
                    QTimer.singleShot(150, capture_library)
                def capture_library():
                    capture("-3-minimum")
                    root.openDemoLibrary()
                    QTimer.singleShot(150, capture_studies)
                def capture_studies(index=-1):
                    if index == -1:
                        capture("-demo-library")
                        root.findChild(QObject, "demoLibrary").close()
                        root.openStudyTools()
                        index=0
                    if index == 5:
                        root.findChild(QObject, "studyTools").close()
                        root.openExtendedTools()
                        capture_extensions()
                        return
                    root.findChild(QObject, "studySections").setProperty("currentIndex",index)
                    QTimer.singleShot(150, lambda: (capture("-study-"+str(index)),capture_studies(index+1)))
                def capture_extensions(index=0):
                    if index == 4:
                        root.findChild(QObject, "extendedTools").close()
                        finish()
                        return
                    root.findChild(QObject, "extensionSections").setProperty("currentIndex", index)
                    QTimer.singleShot(150, lambda: (capture("-extended-"+str(index)), capture_extensions(index+1)))
                QTimer.singleShot(150, capture_minimum)

            QTimer.singleShot(150, capture_help)

        def finish():
            print("QML smoke test:", "PASS" if not qml_warnings else "FAIL")
            for warning in qml_warnings:
                print(warning)
            if smoke_temp is not None:
                smoke_temp.cleanup()
            app.exit(0 if not qml_warnings else 1)

        if args.solve_demo:
            def after_run():
                controller.selectType("Generator")
                if args.demo and args.demo != "urban3":
                    names = [r["name"] for r in controller.project.objects if r["component"] == "Generator"][:2]
                    view = root.findChild(QObject, "resultsExplorer")
                    view.chooseCategory("Generator")
                    for name in names:
                        view.toggleObject("Generator", name)
                    view.toggleProperty("p")
                    if not controller.queryResults("Generator", names, ["p"], "", ""):
                        qml_warnings.append("Selected demo query failed.")
                    view.setProperty("pending", False)
                    visit()
                    return
                controller.beginSheet()
                steps = [
                    controller.sheetModel.pasteTsv("name\tp_nom\nThermal\t160\n"),
                    controller.applySheet(), controller.sheetHistory(False),
                    controller.sheetHistory(True), controller.sheetHistory(False),
                ]
                if not all(steps):
                    qml_warnings.append("Spreadsheet apply/undo/redo smoke failed.")
                view = root.findChild(QObject, "resultsExplorer")
                view.chooseCategory("Generator")
                view.toggleObject("Generator", "Thermal")
                view.toggleObject("Generator", "Solar")
                view.toggleProperty("p")
                view.toggleProperty("p_nom")
                view.setProperty("expanded", {"Generator": True})
                controller.queryResults("Generator", ["Thermal", "Solar"], ["p", "p_nom"], "", "")
                first_tab = controller.workspace.active_id
                controller.pinQueryTab(first_tab)
                if not controller.queryResults("Load", ["City demand"], ["p"], "", ""):
                    qml_warnings.append("Demo load query failed.")
                controller.setChartType("p", "bar")
                controller.selectQueryTab(first_tab)
                if not controller.setChartType("p", "stacked area"):
                    qml_warnings.append("Demo stacked-area selection failed.")
                view.setProperty("pending", False)
                visit()

            controller.runCompleted.connect(after_run)
            QTimer.singleShot(300, lambda: controller.startRun("render-test", "lp"))

            def timeout():
                if controller.process:
                    controller.cancelRun()
                    controller.process.waitForFinished(5000)
                print("Smoke solve did not complete within 90 seconds.", controller.messages)
                if controller.run_directory:
                    log = controller.run_directory / "worker.log"
                    if log.exists():
                        print("Worker diagnostics:\n" + log.read_text(encoding="utf-8", errors="replace")[-12000:])
                if smoke_temp is not None:
                    smoke_temp.cleanup()
                app.exit(1)

            QTimer.singleShot(90000, timeout)
        else:
            QTimer.singleShot(300, visit)
    elif args.demo:
        controller.loadDemoModel(args.demo)
    if not args.smoke_test:
        QTimer.singleShot(600, controller.offerRecovery)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
