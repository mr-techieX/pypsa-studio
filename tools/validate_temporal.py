"""Reproducible H06–H10 regression/UI/solve/scale checks, sequential Qt jobs."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "temporal-validation"


def fingerprint(directory):
    return {
        str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in directory.rglob("*") if p.is_file()
        and not set(p.relative_to(directory).parts) & {"__pycache__", ".pytest_cache", "dist", "EnEx"}
    }


def benchmark():
    sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
    from test_horizon import fixture, specification
    from test_temporal import repository
    from energy_gui.engine import prepare_run, execute_run
    from energy_gui.results import query_charts
    from energy_gui.storage import save_project
    records = {}
    preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
    with tempfile.TemporaryDirectory(dir=preferred) as temp:
        root = Path(temp)
        p = fixture()
        p.set_horizon("2027-01-01", 48, 60)
        db = root / "p.sqlite"
        save_project(p, db)
        for name, horizon in [("full", None), ("sequential", specification(
                duration=2, duration_unit="day", step_count=2, step_size=1))]:
            started = time.perf_counter()
            run = prepare_run(db, name, "lp", horizon=horizon, report_resolutions=["daily"])
            result = execute_run(run)
            records[name] = dict(seconds=time.perf_counter()-started, objective=result["objective"],
                                 snapshots=48, includes="build/solve/LP/export/calendar reports")
        repo = repository(root / "annual", count=8760)
        started = time.perf_counter()
        frame, specs, temporal = repo.query("Generator", ["A", "B"], ["p"])
        charts = query_charts(frame, specs, temporal, viewport=[8500, 8600])
        records["annual_native_query_zoom"] = dict(seconds=time.perf_counter()-started,
            rows=len(frame), visible_points=len(charts[0]["labels"]), expected_last_value=8601,
            actual_last_value=charts[0]["series"][0]["values"][-1])
        started = time.perf_counter()
        daily, _, _ = repo.query("Generator", ["A", "B"], ["p"],
                                aggregation=dict(resolution="daily", metric="energy"))
        records["annual_daily_query"] = dict(seconds=time.perf_counter()-started, rows=len(daily))
        assert daily.p.sum() == frame.p.sum()
        assert records["full"]["objective"] == records["sequential"]["objective"]
        assert records["annual_native_query_zoom"]["actual_last_value"] == 8601
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ["PeakWorkingSetSize", "WorkingSetSize",
                "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage"]]
        counter = Counters()
        counter.cb = ctypes.sizeof(counter)
        ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        fn = ctypes.windll.psapi.GetProcessMemoryInfo
        fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if fn(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counter), counter.cb):
            records["peak_process_working_set_MiB"] = counter.PeakWorkingSetSize / 2**20
    records["note"] = "Synthetic bounded fixtures, not realistic-grid certification. Timings include cold/warm effects; peak memory is the whole isolated benchmark process, not per solve. No universal speedup claim."
    records["hardware"] = dict(platform=platform.platform(), processor=platform.processor(),
                               logical_cpus=os.cpu_count(), python=platform.python_version())
    OUTPUT.mkdir(exist_ok=True, parents=True)
    (OUTPUT / "benchmark.json").write_text(json.dumps(records, indent=2), encoding="utf-8")


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    targets = {"v100": ROOT.parent / "PyPSA Studio v1.0.0", "legacy_rawbuild_inputs_runs": ROOT / "myTest"}
    before = {name: fingerprint(path) for name, path in targets.items()}
    jobs = [("regression", ["-m", "unittest", "discover", "-v", "-s", "tests"], {}, 1800)]
    for mode in ["Light", "Dark"]:
        jobs.append(("ui-"+mode.lower(), ["-m", "unittest", "test_qml_controls", "test_network_navigation",
            "test_atlas_theme", "test_temporal_ui", "test_horizon_ui"], {"PYPSA_TEST_THEME": mode}, 900))
    if sys.platform == "win32":
        jobs.append(("native-ui", ["-m", "unittest", "test_temporal_ui", "test_horizon_ui"],
                     {"QT_QPA_PLATFORM": "windows"}, 600))
    for mode in ["Light", "Dark", "System"]:
        jobs.append(("solve-"+mode.lower(), ["-m", "energy_gui", "--smoke-test", "--solve-demo", "--theme", mode,
                    "--screenshot", str(OUTPUT / ("solve-"+mode.lower()) / "studio.png")], {}, 300))
    jobs += [("benchmark", [str(Path(__file__).resolve()), "--benchmark"], {}, 600),
             ("compile", ["-m", "compileall", "-q", "energy_gui", "tests"], {}, 120)]
    records = []
    for name, arguments, overrides, timeout in jobs:
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(ROOT / "tests"),
                   STUDIO_TEMPORAL_EVIDENCE=str(OUTPUT / name))
        env.pop("PYPSA_TEST_THEME", None)
        env.update(overrides)
        print("START "+name, flush=True)
        started = time.perf_counter()
        log = OUTPUT / (name+".log")
        try:
            with log.open("w", encoding="utf-8") as stream:
                code = subprocess.run([sys.executable, *arguments], cwd=ROOT, env=env,
                    stdout=stream, stderr=subprocess.STDOUT, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            code = -1
        text = log.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"Ran (\d+) tests? in ([\d.]+)s", text)
        records.append(dict(job=name, passed=code == 0, exit_code=code,
            seconds=time.perf_counter()-started, tests=int(match[1]) if match else None))
        (OUTPUT / "jobs.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
        print(("PASS " if code == 0 else "FAIL ")+name, flush=True)
    changed = {}
    for name, directory in targets.items():
        after = fingerprint(directory)
        changed[name] = [key for key in set(before[name]) | set(after) if before[name].get(key) != after.get(key)]
    summary = dict(created_utc=datetime.now(timezone.utc).isoformat(), platform=platform.platform(),
        python=sys.version, jobs=records, protected_changed=changed,
        protected_counts={name: len(rows) for name, rows in before.items()},
        all_passed=all(job["passed"] for job in records) and not any(changed.values()))
    (OUTPUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    if "--benchmark" in sys.argv:
        benchmark()
    else:
        raise SystemExit(main())
