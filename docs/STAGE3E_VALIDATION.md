# Stage 3E — validation, performance and reliability

Date: 2026-11-11 · RawBuild 0.8.0 · local Windows development environment.
User review remains a separate acceptance gate. This is **not engineering or
utility-grid certification**, an AC-OPF comparison, or a packaging readiness claim.

## Scope and reproducibility

The accepted Stage 3D baseline had 163 passing tests. Stage 3E adds a guarded
seven-case library, an attributed public DC reference, independent numerical
checks, artifact-failure diagnostics and measured 2–20-bus handling. No packages
were installed, core SQLite migration performed, or user projects/runs rewritten.
No AI, cloud service or network data is needed at runtime.

From `PyPSA GUI/RawBuild`, using the existing environment:

```powershell
& '..\..\EnEx\Scripts\python.exe' -m unittest discover -s tests -q
& '..\..\EnEx\Scripts\python.exe' -m compileall -q energy_gui tests
& '..\..\EnEx\Scripts\python.exe' -m energy_gui.acceptance --output docs/stage3e_measurements.json
& '..\..\EnEx\Scripts\python.exe' -m energy_gui.acceptance --gui-probe --output docs/stage3e_ui_measurements.json
& '..\..\EnEx\Scripts\python.exe' -m energy_gui --smoke-test --solve-demo --theme Light
& '..\..\EnEx\Scripts\python.exe' -m energy_gui --smoke-test --solve-demo --demo regional20 --theme Light
& '..\..\EnEx\Scripts\python.exe' -m energy_gui --smoke-test --solve-demo --demo regional20 --theme Dark
& '..\..\EnEx\Scripts\python.exe' -m energy_gui --smoke-test --solve-demo --demo pglib14 --theme Dark
& '..\..\EnEx\Scripts\python.exe' -m energy_gui --smoke-test --demo regional20 --theme System
```

Add `--screenshot <local-path>.png` to smoke commands to capture each page,
spreadsheet, query chart, frozen flows/details, minimum-window Fit, Help, ribbon
and chooser. No screenshot is required for normal launch. `--demo <id>` also
loads a selected case interactively; `acceptance --case <id>` isolates one study.
The acceptance tools use temporary generated projects/runs and clean them after
completion, not user-selected projects. The only retained writes are requested
report files; interactive saves remain user-controlled.

Environment recorded in the JSON reports: Windows 11 build 26200, Python 3.14.8,
PyPSA 1.4.0, Linopy 0.10.1, highspy 1.15.1, pandas 3.1.1, PySide6 6.12.0. These
are observations, not a tested support matrix. No hardware-independent target
is inferred from this one machine/run; hardware, OS caches and concurrent work
can change timings. Detailed CPU/RAM hardware is not captured by this probe.

## Independent numerical validation

All seven factories validate, save/reopen without data changes and solve with
HiGHS. Inputs are fixed arrays/functions; a fresh project UUID is deliberately
assigned on each load. Equal-cost units may admit different optimal dispatch
splits, so fixed input data do not imply every optimum is unique.

Every new successful run still passes the existing actual-Linopy constraint,
bound and integrality checks. `study_validation.py` additionally reads exported
tables and independently reconstructs:

- Given demand and generator availability/capacity bounds.
- Each bus's signed MW balance, subtracting branch port withdrawals rather than
  assuming converters/passive branches have interchangeable signs.
- Fixed passive branch limits and converter efficiency delivery.
- Battery energy recurrence, cyclic boundary and energy capacity.
- Duration-weighted variable operating cost (the demos have fixed capacities,
  no investment/startup/quadratic costs or storage standing losses).
- Frozen-overlay values against each corresponding exported branch-port value.

These demo-specific checks are not a general independent validator for every
PyPSA component/formulation. Existing storage/Store, fractional weighting,
transformer, Process, emissions and commitment references remain in regression.
Numeric checks use absolute tolerances: normally 1e-5, objective 1e-4; explicit
bounds allow 1e-6. Generic Linopy checks retain their existing scaled tolerance.

Observed maximum nodal imbalance across all cases: **1.42e-14 MW**; maximum
independent objective reconstruction error: **9.31e-10** currency units.

| Demo | Independently verified observation |
|---|---|
| `congestion2` | Remote plant 40 MW, local peaker 20 MW, one-hour objective 2800. |
| `urban3` | Original objective 5,958,353.622563 INR; all hourly balances and port overlays agree. |
| `campus6` | COP-3 heat delivery; battery discharges 32.4 MWh during the representative day. |
| `wind10` | 1256.4 MWh of unused available wind; inland generation 928.8 MWh under the 30 MW export bottleneck. |
| `pglib14` | 259 MW supplied at bus 1, objective 2051.526309; all 20 branch flows match a separate nodal solve. |
| `district14` | Transformer bound, heat conversion and battery recurrence hold; discharge 40.5 MWh. |
| `regional20` | All 20 bus balances, 48 passive port overlays and cost agree; battery discharge 81 MWh. |

### Public IEEE/PGLib reference derivation

Source: PGLib OPF v23.07 `pglib_opf_case14_ieee.m`, pinned to commit
`dc6be4b2f85ca0e776952ec22cbd4c22396ea5a3`. The bundled numeric subset is
CC BY 4.0; see [attribution and changes](../THIRD_PARTY_NOTICES.md).

For incidence matrix A (positive at each branch's from bus), source base
100 MVA, reactance x and unity-or-specified tap t, define
`b = 100 / (x*t)`. The independent calculation forms
`B = A diag(b) A.T`, fixes bus-1 angle to zero and solves the reduced system
for the other 13 angles. Then `f = diag(b) A.T theta` gives all branch MW flows.
It uses the attributed source numbers, **not** PyPSA's builder, cycle matrix,
exported coefficients or solver flow variables.

Dispatching all 259 MW from bus 1 is within its 340 MW capacity; all independently
calculated flows satisfy source rate-A and symmetric 30-degree bounds. Its
linear offer 7.920951 is below the other positive-capacity unit's 23.269494.
Therefore this feasible dispatch attains the cheapest-unit lower bound,
`259 * 7.920951 = 2051.526309`, proving the linear adaptation's optimum.
All 20 exported port-0 flows differ from the independent calculation by at most
**8.53e-14 MW**; both ports are checked by the overlay comparison.

This is **not the source AC problem**. Uniform 110 kV is normalization, effective
Line reactance includes tap effects, and source resistance/reactive/shunt/voltage
effects are omitted. Nonzero resistance placeholders satisfy strict consistency
but do not enter this lossless solve. Source ratings/offers/capacities include
PGLib modeling estimates. No comparison to an incompatible published AC optimum
or claim of real equipment limits is made.

## Performance observations

Authoritative machine-readable evidence:
[isolated cases](stage3e_measurements.json) and
[offscreen GUI](stage3e_ui_measurements.json), refreshed after the final Fit and
artifact-validation changes. Values below are rounded, not thresholds.

### Isolated model/solver process

One fresh child process per case; wall-clock timing includes network/model
construction, checks, optimization and result/NetCDF/CSV persistence within
`solve_and_export_s`. LP/MPS export is disabled for these measurements; smoke
checks also exercise real LP export. Free-standing `build_s`, input save/reopen,
repository, query and overlay timings are separate operations, not additive
subparts of the solve timer. The historical field name `scientific_import_s`
also includes importing Qt classes needed by the sheet model, not creating a GUI.

| Case | Objects / hours | Save / reopen (ms) | Solve + export (s) | Warm overlay (ms) | Peak process MiB |
|---|---:|---:|---:|---:|---:|
| congestion2 | 13 / 1 | 18.97 / 2.42 | 1.398 | 6.00 | 328.94 |
| urban3 | 13 / 24 | 18.25 / 3.42 | 1.471 | 5.39 | 330.99 |
| campus6 | 27 / 24 | 17.41 / 2.41 | 2.210 | 8.66 | 335.43 |
| wind10 | 33 / 24 | 18.47 / 2.38 | 1.564 | 8.47 | 330.96 |
| pglib14 | 57 / 1 | 47.11 / 4.16 | 1.887 | 8.36 | 330.16 |
| district14 | 51 / 24 | 18.40 / 2.43 | 2.712 | 13.61 | 338.46 |
| regional20 | 76 / 24 | 20.63 / 2.64 | 2.493 | 11.13 | 337.90 |

Object counts include explicit Carrier records, which do not become physical
diagram nodes. Imports took 3.32–3.38 s; complete child processes took 5.87–7.52 s.
The 20-bus network build was 0.618 s and query 5.26 ms. Overlay timers build the
Python payload; they do not include QML rendering. The warm measurement uses
cached table reads and another exact snapshot (the one-hour case repeats its
only snapshot). Peak working set/RSS includes imports/native solver allocations;
it is neither model-only memory nor aggregate GUI-plus-worker memory.

### Separate offscreen GUI probe

One GUI process, seven sequential generated cases at 1440×920; **Bus** sheet
contains 2–20 rows. Internal import timer: **3.526 s**; application/window creation:
**0.378 s**; sum **3.904 s**. This is not OS process-launch-to-interactive time.
Peak process working set across this GUI-only sequence: **383.74 MiB**.

20-bus load + Bus spreadsheet: **0.245 s**; Network Fit + capture: **0.181 s**.
These include intentional event-settle waits of 80 ms for window/sheet and
160 ms for diagram plus image capture. They are **not FPS, mouse latency or
native desktop rendering guarantees**. The earlier Generator-only probe is
superseded by this Bus-sheet measurement. No claim is made for 8760 snapshots,
hundreds of buses or large pinned queries.

Scientific imports dominate cold startup at these sizes; warm overlays are
roughly 5–14 ms. No broad caching/threading/numerical rewrite is justified by
these measurements. Retain the existing scientific-before-Qt import order and
read-only table cache. Focus changes on demonstrated correctness/failure issues;
profile again before optimizing larger workloads.

## Reliability, geometry and regression evidence

- Eight injected-failure tests cover truncated/invalid status, missing/malformed/
  empty catalogue, duplicate/empty static tables and locked saves. Reads validate
  before publishing new Results/network state. Tests preserve active query tabs,
  prior topology and every remaining artifact's bytes; no silent repair occurs.
- Missing files and permission errors include restore/retry advice. Existing
  bounded atomic status-write retry, permanent-denial preservation, infeasibility
  and QProcess cancellation tests are retained. This is not an implementation of
  restart recovery, database signing or exhaustive malicious-file validation.
- Runtime output tables remain lazy; absent/nonfinite port outputs are explicitly
  unavailable, not invented zero or an automatic replacement from live inputs.
  Structural checks cannot detect all plausible-but-edited numeric data.
- Screenshot review found the former 25% zoom floor clipped a 20-bus frozen view
  at 1140×760. A failing regression reproduced it; 10% minimum zoom now allows
  full-node Fit in both themes and save/reopen of that view. Maximum zoom and
  bounded canvas limits are unchanged. Fit provides an overview; zoom/pan is
  still required for individual labels, and huge custom diagrams may not fit.
- A separate regression checks frozen captured-layout fallback, explicit per-run
  override precedence and unchanged frozen SQLite bytes after live layout edits.
- Real chooser mouse clicks load regional20 without solving; cancellation retains
  the previous project and dialog. Existing drafts/history/Help/F1/themes and
  compact explicit-input spreadsheet regressions remain in the full suite.

| Check | Observed result |
|---|---|
| First full Stage 3E regression | 179 tests passed in 82.119 s, before two final layout regressions. |
| Focused final QML controls | 27 tests passed in 25.133 s. |
| Focused network/layout backend | 16 tests passed in 2.791 s. |
| Final expanded full regression | **181 tests passed in 79.290 s**, including both final layout regressions. |
| 20-bus Light and Dark real solve/LP/query/flow render | Passed; refreshed whole-ring/minimum-size captures reviewed. |
| Original three-bus Light real solve smoke | Passed; Apply/Undo/Redo, pinned query/charts and overlays retained. |
| Public IEEE14 Dark real solve smoke | Passed; G01=259 MW and objective 2051.526309 visible in captured results. |
| 20-bus System render smoke | Passed. |
| Python compilation | Passed. |
| All-case isolated acceptance and GUI measurement commands | Passed; both JSON reports refreshed. |

Final capture prefixes are `stage3e-final-20-light`, `stage3e-final-20-dark`,
`stage3e-final-original` and `stage3e-final-public` in the approved local OpenCode
temporary directory. They are development evidence, not application assets or
portable project dependencies. Light/Dark chooser, network, minimum Fit,
spreadsheet, public Results and original charts were inspected.

Upstream PyPSA/pandas future/deprecation warnings remain visible. The previously
observed Qt shutdown GC ResourceWarning occurred in a passing standalone network
test run; it is not hidden or counted as a numerical failure. A transient
indentation error introduced while adjusting smoke capture timing was caught by
compilation and fixed before the successful refreshed smoke/compile checks.

The shutdown GC warning did not recur in the final combined 181-test suite.

## Remaining limits and safe recovery practice

Keep a manual backup of the SQLite project **and its matching runs folder** with
the application/worker stopped. Preserve corrupt originals and restore a known
complete copy rather than hand-editing artifacts. This stage adds no automatic
repair, crash recovery, destructive migration or cryptographic tamper detection.

These small/medium teaching studies do not certify real utility data, extreme
scale, AC/reactive/voltage feasibility, contingencies or every PyPSA combination.
Global history, custom weights/investment axes, saved dashboards/comparisons,
geographic maps, installers and complete dependency/license distribution review
remain future increments. Stage 3E verification is not completion of all Stage 3
or the wider product roadmap.
