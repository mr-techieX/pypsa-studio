# Stage 3F — local backup and applied-change recovery

2026-11-12 · RawBuild 0.9.0 · Stage 3E baseline: 181 passing tests.

## Contracts

**Backup:** File → Backup saved project + runs… operates on the saved database,
not the current model/drafts. SQLite's read-only backup API captures committed
database state, including WAL. Frozen `inputs.sqlite` project identities scope
matching runs in shared parent folders. All their files, including unsuccessful
run diagnostics, are copied byte-for-byte. Unreadable frozen inputs abort rather
than silently omitting an unidentified run. Symlinked runs/artifacts are refused.
Stop other writers; detected size/mtime changes abort publication. There is no
multi-file transaction across an unrelated external writer.

A new ZIP contains the original project filename, relative `runs/` paths and
`backup_manifest.json` with UTC date/project identity/SHA-256 per file. Checksums
are an inventory, not a signature or tamper-proof evidence. Build in a temporary
folder on the destination filesystem, then publish exclusively: Windows rename,
or POSIX hard link, never overwrite. Failed publication preserves existing files;
no partial public archive is left. Choose outside `runs/` to avoid recursive
backups. Backup runs synchronously; very large archives may temporarily block the
UI. Background/progress/cancel backup work is not claimed by this increment.

**Recovery:** normal desktop entry enables `RecoveryStore` in Qt's per-user local
application-data `recovery` directory. Unit-test controllers and smoke launch do
not silently touch real user recovery storage; tests inject temporary locations.
Each session owns a UUID-named SQLite copy and QLockFile (PID-liveness checks,
no elapsed-time lock expiry). Active sessions are excluded; a selected inactive
copy is claimed throughout inspection/restore/discard to prevent competing use.

Applied unsaved changes schedule a single-shot 1-second capture. The current
project is serialized to a complete temporary SQLite, tagged with source path,
capture date and project name, then atomically replaces only that session's
copy. Failed publication preserves the last complete copy and warns the user.
This is local model data, not telemetry, encryption or an off-machine backup.

Startup asks whether to inspect inactive copies; declining keeps them. File →
Recover applied changes… selects a copy; the next prompt shows project/date/source.
Yes restores **as an unsaved project, with no original save path selected**.
The active recovery copy is written before the offered copy is deleted. Normal
current-project draft/unsaved/pinned-tab guards still apply. Save to a **new file
in the original folder** to keep access to matching run history, or move/copy
matching run folders deliberately. No automatic copy of historical runs occurs
when recovering an unsaved model to a different directory.

Discard removes only the offered recovery copy; Cancel preserves it. Corrupt
copies are retained with a diagnostic, not repaired. Save success or confirmed
normal close/replacement clears only the owning session copy; failed Save or
cancelled close keeps it. File-picker cancellation/failed open does not silently
delete a recovery copy.

Recovery excludes pending field/JSON/spreadsheet/settings drafts, unimported CSV
selections, query tabs, session-only diagram positions and solver process state.
Applied imported profile values, configured visibility and explicitly captured
layouts travel as normal project data. Changes within the capture interval,
disk-full/inaccessible storage and machine/power failure remain risks. Keep
independent backups and use Save. Old inactive copies have no silent retention
expiry; inspect/discard them explicitly. A failed capture may leave temporary
files after abrupt process death; only completed top-level `.sqlite` copies are
offered, not unfinished temporary captures.

**Runs:** queued/running saved entries not owned by this controller display
`interrupted / unconfirmed`. Another session may still be running them. No
status rewrite, auto-failure conversion, process kill, result promotion or
optimization resume occurs. They remain non-queryable as successful results;
inspect retained diagnostics. Frozen-run MW views still require success.

## Verification

Reproduce from `RawBuild` using the existing interpreter:

```powershell
& '..\..\EnEx\Scripts\python.exe' -m unittest discover -s tests -p test_safety.py -v
& '..\..\EnEx\Scripts\python.exe' -m unittest discover -s tests -p test_qml_controls.py -q
& '..\..\EnEx\Scripts\python.exe' -m unittest discover -s tests -q
& '..\..\EnEx\Scripts\python.exe' -m compileall -q energy_gui tests
& '..\..\EnEx\Scripts\python.exe' -m energy_gui --smoke-test --solve-demo --theme Light
& '..\..\EnEx\Scripts\python.exe' -m energy_gui --smoke-test --solve-demo --demo regional20 --theme Dark
& '..\..\EnEx\Scripts\python.exe' -m energy_gui --smoke-test --theme System
```

- 18 focused safety tests passed in **10.432 s**. Includes a separate process
  that captures then exits through `os._exit(23)` (no normal cleanup), lock recovery,
  atomic write/publication failures, saved-vs-unsaved distinction, source/copy
  preservation, corrupted copy, cancellation/discard/close/save behavior,
  current-project guards, startup-later, competing claims, changing run files,
  archive collision/checksums, foreign-run exclusion and restored-run queries
  without invoking a solver.
- Real QML File-menu clicks create backups in Light/Dark and restore the 20-bus
  copy without changing original bytes; focused test passed in **2.461 s**.
  Popup items must be retrieved from Menu `itemAt`, and the success notice closed
  before the next click; initial test lookup/notice-focus errors were corrected.
- Initial restore implementation used a nonexistent QMessageBox `Restore` enum;
  tests caught it. Corrected to an explicit Yes/Discard/Cancel prompt before any
  successful restore is claimed.
- **Full regression: 200 tests passed in 229.239 s**, retaining all 181 previous
  tests, all seven demo solves/independent checks and all 28 QML controls tests.
  Run overlapped render checks; wall time is not a startup/solver performance
  benchmark or a fair comparison with the earlier isolated baseline.
- Original three-bus Light real solve/edit/history/query render, 20-bus Dark real
  solve/frozen-flow render, System smoke and final Python compilation passed.
  Normal/minimum File-menu/network captures were inspected; new commands fit.
- Separate normal entry-point probe (not smoke mode), temporary injected app-data
  directory, `--demo urban3`, automatic one-second capture and abrupt exit at
  1.8 seconds passed: a later reader found one intact unlocked recovery copy.
  Initial probe passed self to Qt's static exec incorrectly; the harness was
  corrected before the passing probe. Real user application-data was not touched.
- Upstream pandas warnings remain visible. The previously observed Qt shutdown
  GC ResourceWarning recurred after the passing combined run (11 uncollectable
  objects). It is unresolved, not suppressed or represented as numerical failure.
  No regression test failed; user acceptance and wider platform/failure testing
  remain separate from this verification.

No packages installed, notebook/learning files changed, core database migration,
cryptographic signing, global history or AC work. Prior demo/reference validation
and performance reports remain applicable to their measured builds; Stage 3F
does not claim new performance measurements or universal failure-proof recovery.
