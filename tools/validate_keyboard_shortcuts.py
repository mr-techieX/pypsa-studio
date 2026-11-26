"""Feature-only shortcut verification; no full-application regression."""

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
OUTPUT = ROOT / "docs" / "keyboard-shortcuts-validation"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    protected = {
        "v100": ROOT.parent / "PyPSA Studio v1.0.0", "saved_inputs_runs": ROOT / "myTest",
        "references": ROOT.parents[1] / "sample-ui-template",
    }
    before = {k: fingerprint(p) for k, p in protected.items()}
    jobs = [
        ("shortcuts-native", ["-m", "unittest", "-v", "test_keyboard_shortcuts"],
         {"QT_QPA_PLATFORM": "windows" if sys.platform == "win32" else "offscreen"}, 180),
        *[("shortcuts-" + theme.lower(), ["-m", "unittest", "-v", "test_keyboard_shortcuts"],
           {"PYPSA_TEST_THEME": theme}, 180) for theme in ("Light", "Dark")],
        ("related-guards", ["-m", "unittest", "-v", "test_model_history",
         "test_qml_controls.QmlControlsTests.test_ribbon_menu_highlight_contrast_for_pointer_keyboard_and_disabled_items",
         "test_qml_controls.QmlControlsTests.test_unapplied_inspector_edits_block_navigation_and_discard_restores"], {}, 180),
    ]
    results = []
    for name, args, overrides, timeout in jobs:
        print("START " + name, flush=True)
        env = dict(os.environ, PYTHONPATH=str(ROOT / "tests"), QT_QPA_PLATFORM="offscreen")
        env.pop("PYPSA_TEST_THEME", None)
        env.update(overrides)
        started = time.perf_counter()
        log = OUTPUT / (name + ".log")
        try:
            with log.open("w", encoding="utf-8") as stream:
                code = subprocess.run([sys.executable, *args], cwd=ROOT, env=env, stdout=stream,
                                      stderr=subprocess.STDOUT, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            code = -1
        match = re.search(r"Ran (\d+) tests? in ([\d.]+)s", log.read_text(encoding="utf-8", errors="replace"))
        results.append(dict(job=name, passed=code == 0, exit_code=code,
                            tests=int(match[1]) if match else None, seconds=time.perf_counter()-started))
        print(("PASS " if code == 0 else "FAIL ") + name, flush=True)
    changes = {}
    for key, path in protected.items():
        after = fingerprint(path)
        changes[key] = sorted(k for k in before[key].keys() | after.keys() if before[key].get(k) != after.get(k))
    report = dict(
        created_utc=datetime.now(timezone.utc).isoformat(), scope="Keyboard shortcuts and related guards only",
        jobs=results, protected_changes=changes,
        protected_counts={k: len(v) for k, v in before.items()},
        all_passed=all(r["passed"] for r in results) and not any(changes.values()),
    )
    (OUTPUT / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
