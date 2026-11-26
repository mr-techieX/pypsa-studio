"""Reproducible nonrandom scaling probes; temporary data, no latency guarantees."""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import platform
import tempfile
from time import perf_counter


def scale_project(buses, hours):
    from .project import Project
    project = Project(name=f"Scale probe {buses} buses / {hours} hours", currency="USD")
    project.set_horizon("2026-01-01", hours, 60)
    for carrier in ["AC", "grid"]:
        project.upsert("Carrier", carrier, {})
    for i in range(buses):
        project.upsert("Bus", f"B{i:03}", dict(v_nom=220, carrier="AC"))
        project.upsert("Load", f"D{i:03}", dict(bus=f"B{i:03}", p_set=1))
        project.profiles.append(dict(component="Load", name=f"D{i:03}", attribute="p_set", unit="MW", source="Fixed daily sine scale probe",
            values=[1+0.2*math.sin(h*math.pi/12) for h in range(hours)]))
        if i:
            project.upsert("Line", f"L{i:03}", dict(bus0=f"B{i-1:03}",bus1=f"B{i:03}",s_nom=2*buses,x=10,r=0.5))
    project.upsert("Generator", "Grid", dict(bus="B000",p_nom=2*buses,marginal_cost=30,carrier="grid"))
    # Bounded, non-geographic overview; not an engineering asset layout.
    from .network_view import topology
    graph = topology(project)
    positions = {}
    for i in range(buses):
        angle = 2*math.pi*i/buses
        positions[json.dumps(["Bus", f"B{i:03}"])] = dict(x=2000+1400*math.cos(angle),y=1500+1000*math.sin(angle))
    for obj in graph["objects"]:
        ports = [positions[k] for k in obj["buses"]]
        if obj["kind"] != "Bus":
            positions[obj["key"]] = dict(x=sum(p["x"] for p in ports)/len(ports),y=sum(p["y"] for p in ports)/len(ports)+(80 if len(ports)==1 else 0))
    project.schematic_layouts["current"] = dict(positions=positions,zoom=0.1,panX=0,panY=0,width=4000,height=3000)
    return project


def measure(buses, hours, solve=False):
    from .acceptance import peak_memory_mib
    from .engine import build_network, execute_run, prepare_run
    from .network_view import frozen_overlay
    from .results import ResultsRepository
    from .sheet import ObjectSheet
    from .storage import save_project, load_project
    times = {}
    def timed(key, call):
        start = perf_counter(); value = call(); times[key] = perf_counter()-start
        return value
    preferred = Path(os.environ["LOCALAPPDATA"])/"Temp"/"opencode" if os.name=="nt" else None
    with tempfile.TemporaryDirectory(prefix="scale_probe_",dir=preferred) as tmp:
        project = timed("create_s",lambda:scale_project(buses,hours))
        timed("build_s",lambda:build_network(project))
        sheet = ObjectSheet(lambda:True)
        timed("bus_sheet_s",lambda:sheet.load(project,"Bus"))
        path = Path(tmp)/"project.sqlite"
        timed("save_s",lambda:save_project(project,path))
        reopened = timed("reopen_s",lambda:load_project(path))
        if reopened.to_dict()!=project.to_dict():
            raise ValueError("Scale save/reopen mismatch.")
        checks = "build/persistence only; no solve claimed"
        if solve:
            run = prepare_run(path,export_format="none")
            meta = timed("solve_export_s",lambda:execute_run(run))
            expected = buses*sum(project.profiles[0]["values"])*30
            if abs(meta["objective"]-expected)>1e-4:
                raise ValueError("Scale objective disagrees with independent load cost.")
            from .run_layout import metadata_path
            repo = timed("repository_s",lambda:ResultsRepository(run,json.loads(metadata_path(run, "catalog.json").read_text())))
            timed("query_s",lambda:repo.query("Generator",["Grid"],["p"]))
            timed("overlay_cold_s",lambda:frozen_overlay(repo,project.snapshots[0]))
            timed("overlay_warm_s",lambda:frozen_overlay(repo,project.snapshots[-1]))
            checks = dict(analytic_objective=expected, solved_objective=meta["objective"])
        return dict(buses=buses,hours=hours,objects=len(project.objects),times=times,checks=checks,peak_process_memory_mib=peak_memory_mib())


def measure_gui(buses, hours, screenshot=None):
    os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
    from .schema import registry  # Scientific modules before Qt inspection hooks.
    from .acceptance import peak_memory_mib
    from .appearance import Appearance
    from .controller import Controller
    from PySide6.QtCore import QMetaObject, QObject, QSettings, QUrl
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    project=scale_project(buses,hours)
    preferred=Path(os.environ["LOCALAPPDATA"])/"Temp"/"opencode" if os.name=="nt" else None
    with tempfile.TemporaryDirectory(prefix="scale_ui_",dir=preferred) as tmp:
        app=QApplication.instance() or QApplication([])
        if os.name=="nt":
            QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"])/"Fonts"/"segoeui.ttf"))
        QQuickStyle.setStyle("Basic")
        controller=Controller()
        appearance=Appearance(QSettings(str(Path(tmp)/"theme.ini"),QSettings.Format.IniFormat))
        engine=QQmlApplicationEngine()
        engine.rootContext().setContextProperty("backend",controller)
        engine.rootContext().setContextProperty("appearance",appearance)
        warnings=[];engine.warnings.connect(lambda items:warnings.extend(str(m) for m in items))
        start=perf_counter()
        engine.load(QUrl.fromLocalFile(str(Path(__file__).parent/"qml"/"Main.qml")))
        root=engine.rootObjects()[0];QTest.qWait(100)
        times={"window_s":perf_counter()-start}
        start=perf_counter()
        controller.project=project;controller._reset_helpers();controller._reset_draft();controller.changed.emit()
        root.setProperty("page",1);app.processEvents()
        if not root.findChild(QObject,"objectSpreadsheet").isVisible():
            QMetaObject.invokeMethod(root.findChild(QObject,"objectEditorToggle"),"clicked")
        QTest.qWait(100)
        times["load_bus_sheet_s"]=perf_counter()-start
        start=perf_counter();root.setProperty("page",3);QTest.qWait(100)
        root.findChild(QObject,"networkView").fitView();QTest.qWait(150)
        if root.grabWindow().isNull():raise ValueError("Large-model GUI render failed.")
        times["network_fit_capture_s"]=perf_counter()-start
        if screenshot:
            Path(screenshot).parent.mkdir(parents=True,exist_ok=True)
            root.grabWindow().save(str(screenshot))
        root.openStudyTools();QTest.qWait(100)
        if screenshot:
            path=Path(screenshot);root.grabWindow().save(str(path.with_name(path.stem+"-studies"+path.suffix)))
        root.findChild(QObject,"studyTools").close()
        controller.dirty=False;root.close();engine.deleteLater();app.processEvents()
        if warnings:raise ValueError("QML warnings: "+"\n".join(warnings))
        return dict(buses=buses,hours=hours,objects=len(project.objects),times=times,
                    peak_process_memory_mib=peak_memory_mib(),checks="offscreen Bus sheet/diagram/study dialog render passed; waits 100ms window/sheet and 250ms diagram; not native FPS or solve timing")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--buses",type=int,default=100)
    parser.add_argument("--hours",type=int,default=168)
    parser.add_argument("--solve",action="store_true")
    parser.add_argument("--gui",action="store_true")
    parser.add_argument("--screenshot",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if not 2<=args.buses<=500 or not 1<=args.hours<=8760:
        parser.error("Supported probe range: 2–500 buses and 1–8760 hours.")
    report=dict(created_utc=datetime.now(timezone.utc).isoformat(),platform=platform.platform(),python=platform.python_version(),
        methodology="Single process fixed-data radial load/remote supply probe, explicit hour weights. Peak process memory includes imports/native allocations. No AC/security/large-grid certification or hardware-independent SLA. Build-only cases are not solve evidence.",
        case=measure_gui(args.buses,args.hours,args.screenshot) if args.gui else measure(args.buses,args.hours,args.solve))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8")


if __name__=="__main__":
    main()
