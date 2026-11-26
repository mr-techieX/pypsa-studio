"""Offline Stage 3E validation/performance runner; measurements are not SLAs.

python -m energy_gui.acceptance --output docs/stage3e_measurements.json
Each case runs in a fresh process; temporary projects/runs are cleaned afterwards.
"""

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from time import perf_counter


def peak_memory_mib():
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [(n, ctypes.c_size_t) for n in
                ["peak_working_set", "working_set", "peak_paged", "paged", "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile"]]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return counters.peak_working_set/1024**2
        return None
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/(1024**2 if sys.platform == "darwin" else 1024)


def measure(key):
    start = perf_counter()
    from .demo_library import make_demo
    from .engine import prepare_run, execute_run, build_network
    from .network_view import frozen_overlay
    from .results import ResultsRepository
    from .sheet import ObjectSheet
    from .storage import save_project, load_project
    from .study_validation import validate_study
    times = {"scientific_import_s": perf_counter()-start}

    def timed(label, function):
        before = perf_counter()
        result = function()
        times[label] = perf_counter()-before
        return result

    preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
    with tempfile.TemporaryDirectory(prefix="stage3e_case_", dir=preferred) as tmp:
        path = Path(tmp)/"project.sqlite"
        project = timed("create_s", lambda: make_demo(key))
        errors = timed("validate_s", project.validate)
        if errors:
            raise ValueError("\n".join(errors))
        timed("build_s", lambda: build_network(project))
        sheet = ObjectSheet(lambda: True)
        timed("sheet_load_s", lambda: sheet.load(project, "Generator"))
        timed("save_s", lambda: save_project(project, path))
        reopened = timed("reopen_s", lambda: load_project(path))
        if reopened.to_dict() != project.to_dict():
            raise ValueError("Save/reopen mismatch.")
        run = timed("prepare_s", lambda: prepare_run(path, export_format="none"))
        timed("solve_and_export_s", lambda: execute_run(run))
        checks = timed("independent_checks_s", lambda: validate_study(project, run, key))
        from .run_layout import metadata_path
        repo = timed("repository_s", lambda: ResultsRepository(run, json.loads(metadata_path(run, "catalog.json").read_text())))
        names = next(c["objects"] for c in repo.describe() if c["name"] == "Generator")
        timed("query_s", lambda: repo.query("Generator", names, ["p"]))
        timed("overlay_cold_s", lambda: frozen_overlay(repo, project.snapshots[-1]))
        timed("overlay_warm_s", lambda: frozen_overlay(repo, project.snapshots[0]))
        return dict(id=key, buses=sum(r["component"] == "Bus" for r in project.objects),
                    objects=len(project.objects), snapshots=len(project.snapshots), times=times,
                    peak_process_memory_mib=peak_memory_mib(), checks=checks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", help="One demo id (default: all, isolated processes)")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--gui-probe", action="store_true", help="Measure offscreen window/load/view handling for every demo.")
    args = parser.parse_args()
    if args.gui_probe:
        from .ui_acceptance import measure_ui
        report = measure_ui()
    elif args.case:
        report = measure(args.case)
    else:
        from .demo_library import DEMO_SPECS
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        cases = []
        with tempfile.TemporaryDirectory(prefix="stage3e_report_", dir=preferred) as tmp:
            for spec in DEMO_SPECS:
                path = Path(tmp)/(spec["id"]+".json")
                start = perf_counter()
                completed = subprocess.run([sys.executable, "-m", "energy_gui.acceptance", "--case", spec["id"], "--output", str(path)], capture_output=True, text=True, timeout=180)
                if completed.returncode:
                    raise RuntimeError(f"{spec['id']} failed:\n{completed.stderr[-6000:]}")
                result = json.loads(path.read_text())
                result["isolated_process_wall_s"] = perf_counter()-start
                cases.append(result)
        import importlib.metadata
        from datetime import datetime, timezone
        report = dict(created_utc=datetime.now(timezone.utc).isoformat(), python=platform.python_version(),
                      platform=platform.platform(), versions={p: importlib.metadata.version(p) for p in ["pypsa", "linopy", "highspy", "pandas", "PySide6"]},
                      methodology="One fresh process per case; wall-clock seconds, no LP export; import timing is not GUI startup. Peak process working set/RSS includes scientific imports and native solver allocations. Measurements are development-machine observations, not guarantees.", cases=cases)
    text = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text+"\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
