# Stage 3G — bounded session model history

2026-11-12 · RawBuild 0.10.0 · previous verified baseline: 200 tests.

## User contract

Data → Undo model edit / Redo model edit restores a complete atomic applied model
change. Supported paths: inspector create/property apply, guarded rename,
dependency-aware deletion with owned profiles, imported profile apply/replacement/
removal, project settings, visibility and spreadsheet application. A no-op does
not create an entry or invalidate Redo; a new real edit discards the Redo branch.
History never applies component operations one-by-one with dangling references.

`history.py` stores detached before/after snapshots and labels. It limits retained
operations to 20 and their combined UTF-8 JSON snapshot size to 32 MiB; this is
not an exact RAM cap and does not bound transient serialization/legacy spreadsheet
memory. Oldest entries are evicted. An oversized edit remains applied but clears
model history and emits backup/Save advice. The small bound is deliberate for
this initial whole-project implementation, not a large-model performance claim.

Undo/Redo checks the current model against the expected source snapshot; stale
history cannot overwrite unrelated changes. Recording after an external/detached
replacement starts a fresh chain. Active solver processes block history. Existing
draft guards run first; Cancel changes neither model nor stacks, Discard removes
the pending draft, Apply creates a new command and Undo targets that newest edit.
Sequential draft prompts retain previously explicitly applied sections if a later
prompt is cancelled, as before. Invalid edits create no command.

On success, selections no longer present/visible are cleared or moved to an
available category, helper/editor views reset, and the model is marked dirty.
Dirty tracking is conservative: Undo to values equal to a saved version still
requires Save. Save retains history; open/new/demo/recovery replacement clears
it. History is never serialized to project SQLite, run inputs, backups or recovery.
Recovery captures the current applied model after history actions, not the chain.

## Isolation and compatibility

- Project path and saved database bytes are not part of history. Solver inputs
  already frozen on disk, Results/pinned tab data and active frozen topology/port
  values are not rewritten or replaced. Historical layout records are untouched.
- Layout-only saves/drags/zoom/pan are not model commands or compatibility changes.
  Newer saved view metadata is preserved. Live keys reverse rename identities;
  deleted keys are pruned and restored saved positions can return where they fit
  the current bounded canvas. Undo is not diagram-drag history; unpersisted view
  arrangements may reset when topology identities change.
- Legacy spreadsheet-batch history stays available with its old stale-edit guards.
  Batch apply and legacy batch Undo/Redo are recorded as model edits. A model
  history step clears legacy stacks, avoiding incompatible two-stack replay.
  Identity edits still clear legacy batch history, while the model chain retains
  their atomic before/after model snapshots. No old batch guard was weakened.
- No global Ctrl+Z shortcut was installed over field-local editing; use Data menu
  commands. Run execution, backup creation, recovery deletion, result/tab actions,
  file operations and geographic/topology rewiring through dragging are not
  undoable model commands.

## Verification

```powershell
& '..\..\EnEx\Scripts\python.exe' -m unittest discover -s tests -p test_model_history.py -v
& '..\..\EnEx\Scripts\python.exe' -m unittest discover -s tests -q
& '..\..\EnEx\Scripts\python.exe' -m compileall -q energy_gui tests
& '..\..\EnEx\Scripts\python.exe' -m energy_gui --smoke-test --solve-demo --theme Light
& '..\..\EnEx\Scripts\python.exe' -m energy_gui --smoke-test --solve-demo --demo regional20 --theme Dark
& '..\..\EnEx\Scripts\python.exe' -m energy_gui --smoke-test --theme System
```

- 11 focused history tests passed in **1.940 s**: exact model round trips,
  omission/explicit defaults, reference/profile rename and deletion, mixed settings/
  configuration/profile chain, imported-data restoration without CSV, legacy batch
  integration, busy/stale/draft cancellation, disk/recovery and project-open
  boundaries, frozen query/graph/file-byte isolation, limits/no-op/oversize policy.
- Actual Data menu Undo/Redo clicks passed in Light/Dark (**3.875 s**), restoring
  3/4 buses and showing operation labels. Initial backend test attempted a second
  create without selecting the existing object after Redo; corrected to the
  existing create/edit guard, not by weakening production safety.
- **Full combined regression: 212 tests passed in 240.855 s**, retaining every
  prior 200-test case, all seven demo solves/independent checks, 18 safety cases
  and all 29 QML controls tests. Some render checks ran concurrently; total time
  is not a controlled performance comparison. No test failed.
- Final compilation, original Light/20-bus Dark real-solve renders, System smoke,
  local documentation-link checks and `pip check` (no broken requirements) pass.
  User acceptance remains separate from verified implementation.

Additional completed checks: global rename Undo, pending settings Apply then Undo,
save, real HiGHS solve and independent balance/cost/overlay validation reproduce
the original objective **5958353.622562704**. Original three-bus Light real-solve/
spreadsheet-history/query render, regional20 Dark real-solve/flow render, System
smoke and final compilation pass. Original chart and minimum 20-bus frozen-view
captures were inspected. These checks used isolated temporary data, not user files.

No dependencies, core schema changes, destructive migration, cryptographic signing,
AC work, history persistence or full-session recovery. Existing upstream pandas/
Qt shutdown warnings remain visible rather than globally suppressed.

The known Qt shutdown GC ResourceWarning recurred after the passing combined run
with 11 uncollectable objects. It remains unresolved; it is neither hidden nor
presented as a failed numerical check. No universal crash-proof, memory-performance
or zero-warning guarantee is implied.
