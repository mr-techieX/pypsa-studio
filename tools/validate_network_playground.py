"""Network-workspace follow-up: regressions, themed/native gestures and integrity."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from validate_temporal import fingerprint


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/network-playground-validation"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    protected = {"v100": ROOT.parent / "PyPSA Studio v1.0.0", "saved_rawbuild_inputs_runs": ROOT / "myTest"}
    before = {name: fingerprint(path) for name, path in protected.items()}
    jobs = [("regression", ["-m", "unittest", "discover", "-v", "-s", "tests"], {}, 1800)]
    for theme in ["Light", "Dark"]:
        jobs.append(("ui-"+theme.lower(), ["-m", "unittest", "test_qml_controls", "test_network_navigation",
            "test_atlas_theme", "test_network_playground"], {"PYPSA_TEST_THEME": theme}, 900))
    if sys.platform == "win32":
        jobs.append(("native", ["-m", "unittest", "test_network_navigation", "test_network_playground"],
                     {"QT_QPA_PLATFORM": "windows"}, 600))
    for theme in ["Light", "Dark", "System"]:
        name = "solve-"+theme.lower()
        jobs.append((name, ["-m", "energy_gui", "--smoke-test", "--solve-demo", "--theme", theme,
            "--screenshot", str(OUTPUT / name / "studio.png")], {}, 300))
    jobs.append(("compile", ["-m", "compileall", "-q", "energy_gui", "tests"], {}, 120))
    results = []
    for name, arguments, overrides, timeout in jobs:
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(ROOT / "tests"),
                   STUDIO_PLAYGROUND_EVIDENCE=str(OUTPUT / name))
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
        match = re.search(r"Ran (\d+) tests? in ([\d.]+)s", log.read_text(encoding="utf-8", errors="replace"))
        results.append(dict(job=name, passed=code == 0, exit_code=code,
            seconds=time.perf_counter()-started, tests=int(match[1]) if match else None))
        (OUTPUT / "jobs.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(("PASS " if code == 0 else "FAIL ")+name, flush=True)
    changes = {}
    for name, directory in protected.items():
        after = fingerprint(directory)
        changes[name] = [key for key in set(before[name]) | set(after) if before[name].get(key) != after.get(key)]
    report = dict(created_utc=datetime.now(timezone.utc).isoformat(), jobs=results,
        protected_changes=changes, protected_counts={name: len(files) for name, files in before.items()},
        all_passed=all(r["passed"] for r in results) and not any(changes.values()))
    (OUTPUT / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
