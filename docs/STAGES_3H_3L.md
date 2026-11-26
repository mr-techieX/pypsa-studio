# Integrated stages 3H–3L — saved studies, reporting, scale and advanced inputs

2026-11-12 · RawBuild 0.11.0 · **final: 247 tests passed in 335.228 s**, retaining
the **212-test** verified baseline. Implemented/verified; user review is next.
All runtime operations remain local. No dependencies installed, AC integration,
signing, installer or destructive project migration. User acceptance is separate.

## 3H — portable analysis workspace

Run tools → Saved analysis / comparison / advanced inputs… → Saved analysis.
Capture the current ordered query-card session under a name, then Save project.
Each definition stores source run folder names, executed criteria, chart choices,
pin flags, active card and Data/Charts views. The library itself can be reordered
or definitions removed; this never deletes result folders. Limits: 50 dashboards
per project, 50 cards each. This is an ordered query dashboard, not a free-form
visual designer or a copy of result data.

Restore reads/validates every source and chart before replacing tabs, with a
replacement confirmation when tabs exist. Missing/corrupt/foreign inputs retain
the prior workspace. No solver is invoked. Paths must be single folder names
under the saved project's `runs/`; absolute/traversal/external references are
refused. Move SQLite **and matching runs** together. Frozen files are read, not
rewritten or re-solved. File identity is not a cryptographic signature.

Optional `metadata.analysis_workspace` is outside the core payload. Older projects
default to an empty library; older readers may ignore it and older saves may drop
it. Model/batch Undo preserves newer saved-analysis metadata rather than reverting
it. Session tabs remain temporary unless explicitly captured and the project saved.

## 3I — compatible frozen-run comparisons

Comparison uses the active **executed** query criteria, not pending selector edits.
Choose left/right successful run names from this project. Require matching project
identity, currency, formulation, timestamps, declared periods/period weights and
effective snapshot weights. Require the same selected identities and property
kinds/units; reject different declared object/bus units and incomplete/nonfinite
numeric series. No silent intersection, interpolation, currency/unit conversion,
zero-filling or treating static values as time series.

Result rows include object/time/property/unit, left/right values and signed
`delta_right_minus_left`. CSV adds source run names and currency. The screen shows
100 rows; export includes the entire comparison. Existing query tabs/frozen network
remain unchanged. Live edits do not relabel the source data. Changed unselected
objects can influence results: differences are not causal attribution.

Metrics: saved objective (full formulation objective), exported optimised Generator
capacity (or frozen fixed capacity when optimised capacity is absent), weighted
Generator dispatch energy, and operational CO2 only when explicit factors exist
for every Generator carrier. No invented zero factors. Generator energy/CO2 uses
`snapshot_weightings.generators`; multi-period accounting additionally uses period
`years`. CO2 = sum(p / efficiency × generator weights × period years × carrier
co2_emissions). Only MW electrical declarations and finite data support those energy
metrics. This is operational accounting, not lifecycle or certified emissions.
Capacity totals are exported Generator capacities, not per-year installed-stock
diagrams. Objective differences are only compared with matching weight conventions.

## 3J — reproducible local exports

- SVG/PNG charts preserve chosen line/bar/dot/horizontal-bar/compatible stacked-area
  styles and gaps. Exports use the same bounded preview data (1000 snapshots/six
  objects per temporal property; static bounds retained), at most 30 properties.
- Self-contained HTML includes source/criteria, metrics, bounded chart previews and
  first 1000 data rows, explicitly labelled with total row count. HTML/XML data are
  escaped; no scripts/CDNs/web fonts/network resources. Select properties/styles
  through the executed query to configure the report. Use CSV for complete data.
- Readable formulation annotation streams the **actual saved LP or MPS** and expands
  numeric x/c labels through the saved symbol map. Coefficients, signs and bounds
  remain those exported by the solver adapter. Annotated text is **not valid solver
  input**; MPS stays a labelled matrix representation, not a new independent model.
  Runs without a mathematical export produce actionable advice to make a new
  labelled run with LP/MPS enabled. No retrofit or silent rewriting of old artifacts.
- Controller export commands reject project SQLite/frozen-run destinations. A
  report is separate from the saved model/results. PDF/Excel and arbitrary report
  template design are not included in this increment.

## 3K — scale/performance and responsive backup

`scale_acceptance.py` builds fixed-data radial load/remote-supply probes, never
random/measured utility grids. One fresh process per report; temporary projects
and run files are cleaned. Build-only rows are explicitly **not solves**.

| Probe | Observed evidence | Peak process memory |
|---|---|---:|
| 100 buses / 168 hours / 302 objects | Build 0.985 s; solve+export 7.613 s; objective 504000 matches independent load-cost calculation; warm overlay 176.8 ms | 407.35 MiB |
| 200 buses / 168 hours / 602 objects | Build 1.244 s; save 134.9 ms; reopen 44.2 ms; **no solve** | 281.23 MiB |
| 20 buses / 8760 hours / 62 objects | Build 2.001 s; save 336.5 ms; reopen 139.0 ms; **no annual solve** | 295.39 MiB |
| 200 buses / 24 hours, offscreen 1440×920 | Initial Bus-sheet load 8.112 s; Fit+capture 0.917 s; diagram/Study tools render passed | 532.98 MiB |

Authoritative reports: `scale_100_168.json`, `scale_200_168.json`,
`scale_20_8760.json`, `scale_gui_200.json`. These are observations on Windows 11 /
Python 3.14.8 / the existing PyPSA 1.4.0 environment, not limits or hardware-independent
SLAs. Memory includes imports/native allocations, not model-only memory. UI times
include explicit waits (100 ms window/sheet and 250 ms diagram) and image capture;
not native FPS or mouse latency. The 8.1-second first large GUI load remains a
known responsiveness limit; dense 200-bus labels require zoom/pan and suitable
layout work. Hundred-bus solves are not realistic-grid, AC or contingency validation.

Measured/observed bottleneck work: vector insertion for large homogeneous standard
Bus/Load/Line/Generator groups, bulk profile DataFrame construction instead of
fragmenting column inserts, and cached result time indexes with range selection
before numeric conversion. Small/specialised builders remain. Tests compare every
static/dynamic table and snapshot weights with the previous scalar path, including
dtypes and column-index names. Initial equality discrepancies in weight dtype and
profile column names were fixed rather than weakening that comparison. No speed-up
ratio is claimed without a controlled before/after benchmark.

Background backup streams ZIP entries in 1 MiB chunks on QThread, emits file-count
progress and supports cancellation during SQLite copying/file streaming, before
exclusive publication. Original saved data/archives remain unchanged on cancel or
failure. Save/solve/replace/close is blocked until completion/cancellation; pending
model edits remain separate. Stop external writers. The original synchronous backup
method remains compatible. Qt test waits use a real event loop so the Python worker
is not starved by repeated test-only waits. No thread is forcibly terminated.

## 3L — explicit time/period/curve inputs and tabular profiles

The Profile grid is a complete snapshot/value TSV editor: Load values for an
existing varying input, edit/paste numeric rows and Apply atomically. Timestamp
alignment is exact, with no implicit resampling or conversion; maximum 10 MiB text.
Source/profile-owner baselines prevent stale dialog drafts from overwriting newer
data. Applied changes enter model Undo and recovery. Closing retains session drafts;
project replacement clears them. They are not included in crash recovery until Apply.

Time / curves uses validated JSON data with a helper for common uniform weights:

```json
{
  "weights": [
    {"objective": 1, "stores": 0.5, "generators": 0.5},
    {"objective": 2, "stores": 1, "generators": 1}
  ],
  "periods": [
    {"period": 2030, "objective": 1, "years": 1},
    {"period": 2040, "objective": 2, "years": 2}
  ],
  "snapshot_periods": [2030, 2040],
  "piecewise": []
}
```

This example requires exactly two globally unique project timestamps. `weights`
is either empty (interval defaults) or one complete positive finite numeric row
per timestamp. Objective weights multiply operating costs; stores weights are
elapsed hours in storage recurrence/standing loss; generators weights affect energy
accounting. Period identifiers are increasing integers; every declared period must
have ordered snapshot assignments. Objective/years weights are explicit, positive
and finite. No discount rate or representative-day replication is guessed. Timestamps
need not have the same year as a period identifier, but must remain globally unique;
repeated representative timestamps across periods are not supported by this UI.

Builder calls: `n.set_snapshots(index, default_snapshot_weightings=hours)` returns
None and mutates/reindexes time tables. With explicit periods, `index` is a two-level
MultiIndex; `n.set_investment_periods(ids)` mutates period state without replicating
those already-assigned snapshots. Explicit snapshot/period weighting DataFrames
replace their corresponding tables. `n.optimize.create_model(...,
multi_investment_periods=True)` returns/attaches the Linopy model. Legacy projects
keep their previous single-index/default-weight construction exactly.

Piecewise example (append inside the `piecewise` list):

```json
{"component":"Generator","name":"G","attribute":"marginal_cost",
 "points":[[0,0],[0.5,20],[1,50]]}
```

Fixed positive p_nom, noncommittable, nonnegative dispatch up to p_nom; no concurrent
cost profile. x = p/p_nom; each y prices the increment from the preceding breakpoint
in currency/MWh (not a total-cost y coordinate). x must increase from 0 to 1;
y(0)=0 and segment prices are nonnegative/nondecreasing. At p_nom=100 MW and
p=75 MW, one hour costs 50×20 + 25×50 = 2250. The native PyPSA curve overrides the
scalar marginal_cost for that Generator. It is passed with all other attributes
in the **initial** `n.add(...)`, never an overwrite that resets bus/capacity fields.
Other component/attribute curve types, nonconvex/negative offers, extendable or
committable piecewise generation are explicitly rejected. Rename/deletion carries
or removes owned curves; model Undo restores them atomically.

New advanced model data live in the core `advanced_inputs` payload. Empty legacy
defaults are omitted on disk. Older application constructors reject nonempty advanced
payloads rather than silently ignoring model semantics; use 0.11+ to open such
projects. No core-table migration or rewriting of existing frozen runs occurs.
New multi-period CSVs retain both period and snapshot columns; readers validate
them against frozen assignments, query output/chart labels retain period identity,
and frozen network captions show the active investment period.

## Integrated validation evidence

Independent numerical references passed during focused checks:

- Custom objective weighting: 3000; weighted generation 450 MWh and CO2 90 t.
- Custom storage elapsed weights: 10 MW charge for 0.5 h, then 5 MW dispatch for
  1 h; energy [5,0] MWh and objective 50.
- Two operating periods: objective 2250; raw/query period identities retained.
- Multi-period extendable capacity: 20 MW; capacity+operation objective 800.
- Native convex cost curve: 75 MW for two hours, objective 4500; bus/capacity
  attributes preserved; actual LP annotation exported.

Initial development checks found/fixed a curve-overwrite bug, batch dtype/index-name
differences, a test-only pandas typed-assignment error, a test-only Qt event-loop
wait issue, and low-contrast default Study tab/placeholder styling. Old ribbon icon tests now
wait boundedly for asynchronous SVG decoding and still require Ready (not Error).
An early unoptimised large-input test hit its deadline; this is not recorded as a
passing numerical or scale check. The final measured probes above passed separately
from the combined regression.

The first integrated checkpoint passed **244 tests in 390.531 s**, including all
212 earlier tests. Three additional regressions cover malformed saved card state,
declared-unit/formulation mismatch and static/full CSV with protected export paths.
Actual Study tools clicks also exercise comparison after saved-chart restoration.
The expanded checkpoint passed **247 tests in 347.377 s**. The final
post-placeholder-contrast repeat passed **247 tests in 335.228 s** (212 prior +
32 new backend/numerical tests + 3 real QML interactions, 32 QML tests total).
Focused checks passed 32 tests in 41.075 s and 3 Study tools tests in 11.889 s.
No regressions detected in tested behavior. Combined suites overlapped some other
checks, so their wall times are not controlled performance comparisons.

The retained baseline spans every earlier test module, not only the new features:

| Retained regression area | Tests |
|---|---:|
| Core backend/schema/persistence, desktop process, atomic status, appearance | 27 |
| Results, pinned/session workspace and solution checks | 34 |
| Spreadsheet, identity editing, helper drafts, configuration, Help, model history | 58 |
| Backup/recovery/crash safety | 18 |
| Frozen network/layout/flow semantics | 16 |
| Demo library, artifact failures, Stage 2 numerical/validation and larger edited grid | 30 |
| Prior real QML controls/interactions | 29 |
| **Retained total** | **212** |
| New backend/numerical and real Study tools interactions | 35 |
| **Combined total across 22 test modules** | **247** |

An additional combined advanced workflow passed: controller Apply, applied-state
recovery inspection, Undo/Redo, Save/reopen, two real solves and frozen-run
comparison with explicit snapshot weights, two periods and convex cost curves
enabled together. At 75 MW, curves [20,50] and [30,60] price 50/25 MW segments;
snapshot-objective × period-objective factors are 2 and 6. Independent objectives
are therefore 18000/24000. Generator weights × period years give 375 MWh and
explicit-factor CO2 75 t; unchanged dispatch deltas are zero, with periods retained.
The initial manual harness guessed a nonexistent private recovery helper and then
hit its unreleased temporary lock during cleanup. It was corrected to public
`flushRecovery()` with finally-close before the successful check; no production
change or passing claim was made for that failed probe.

Light original-demo and Dark regional20 real-solve/LP/query/edit-history/frozen-flow
smokes, plus System regional20 smoke, passed without QML warnings. All five Study
tabs were captured at 1140×760 in Light/Dark and inspected; placeholder contrast
was improved from those captures. Original Results charts and the complete minimum
20-bus frozen overview were reviewed. Final post-contrast Light/Dark real solves
and System smoke passed, and refreshed placeholders/readouts were inspected.
Populated saved-library/comparison/24-row profile views were also captured in both
themes. A copied project plus matching runs restored its complete two-card saved
dashboard from a different directory without solving. Python compilation, local
documentation links and dependency checks pass.

Separate export acceptance solved the original demo with both LP and MPS exports,
annotated the actual artifacts and verified every frozen file's SHA-256 remained
unchanged. Exported line/bar/dot/stacked-area/horizontal-bar SVG/PNG previews and an
escaped HTML report were inspected, including an offline headless-browser render.
The PNG offscreen fixture registers Windows fonts, as the existing smoke harness
does; initial unregistered-font fixture output was not accepted as a readable
export. No runtime browser dependency was added. Local temporary review prefix:
`stage_h_l_export_review_2azlvyxb`; themed capture prefixes: `stage_h_l_light`,
`stage_h_l_dark`, `stage_h_l_system` in the approved temporary directory.
The first populated-view probe reached its captures but then timed out at the
intentional pinned-tab close confirmation. The corrected harness explicitly clears
its temporary session tabs before closing; relocation/render/clean-exit passed.
This was not treated as a passing close test or a production-close defect.

Existing upstream pandas/Qt shutdown warnings remain visible (12 uncollectable
objects in the first integrated run); no blanket suppression, universal memory/
latency guarantee or whole-product completion claim. Scenario automation,
security/reserve studies, GIS, full-session history/recovery, packaging and AC
remain future work.

Reproduce from RawBuild:

```powershell
& '..\..\EnEx\Scripts\python.exe' -m unittest discover -s tests -q
& '..\..\EnEx\Scripts\python.exe' -m compileall -q energy_gui tests
& '..\..\EnEx\Scripts\python.exe' -m energy_gui --smoke-test --solve-demo --theme Light
& '..\..\EnEx\Scripts\python.exe' -m energy_gui --smoke-test --solve-demo --demo regional20 --theme Dark
& '..\..\EnEx\Scripts\python.exe' -m energy_gui.scale_acceptance --buses 100 --hours 168 --solve --output docs/scale_100_168.json
& '..\..\EnEx\Scripts\python.exe' -m energy_gui.scale_acceptance --buses 200 --hours 168 --output docs/scale_200_168.json
& '..\..\EnEx\Scripts\python.exe' -m energy_gui.scale_acceptance --buses 20 --hours 8760 --output docs/scale_20_8760.json
& '..\..\EnEx\Scripts\python.exe' -m energy_gui.scale_acceptance --buses 200 --hours 24 --gui --output docs/scale_gui_200.json
```
