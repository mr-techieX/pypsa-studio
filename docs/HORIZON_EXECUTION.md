# H01–H05: bounded sequential execution

Development location: **RawBuild only**. No v1.1.0 release until all targets and
user acceptance are complete. H06–H10 report/query/listing/navigator features
are now documented in `TEMPORAL_RESULTS.md`; the H01–H05 checks are retained.

## Run controls

Run model in the ribbon opens Runs for review; it no longer starts a solve
without showing the effective settings. Choose:

- **Project snapshots · one solve**: the original workflow, unchanged.
- **Configured sequential steps**: start, overall upper duration/unit, snapshot
  interval, optimization step size/unit, and number of solves. Step unit defaults
  to day. Sync Horizon selects the maximum whole count that fits.

Hour/day/week/month/year are available. Each optimization step contains as many
snapshots as its duration requires at the chosen snapshot interval. Fifteen
two-day optimizations with hourly snapshots contain 48 snapshots per optimization,
720 snapshots in total—not 15 two-day averaged snapshots.

January 2027:

- Overall interval `[2027-01-01T00:00, 2027-02-01T00:00)`.
- 15 × 2 days: solve through January 30, ending January 31 at 00:00, with January
  31 unused. Preview explicitly reports 24 unused hours.
- 16 × 2 days: red/orange-red error text/border (theme danger role), Start disabled.
- Sync: 15 steps, not a sixteenth shortened step.

All ends are exclusive. Month/year offsets are anchored to the original start:
Jan 31 + 1/2 months gives Feb 28 / Mar 31. Snapshots must exactly divide and align
with step boundaries. Timestamp convention is timezone-naive with no implicit
DST conversion. Preview includes the dates of every solve. At small window sizes
the Runs page scrolls to keep settings and logs reachable.

Run controls are session-local. Each started run freezes its effective settings,
but these controls are not new project/model inputs and do not resample or change
the live project's dates. Existing project snapshots remain independently editable
through the established guarded project-settings workflow.

## Inputs and supported scope

Static-only models can use a newly selected axis. Profiles and explicit weights
default to exact timestamp and duration coverage. A matching subset is selected
into an independent frozen copy; no zero fill, interpolation, year shifting,
downsampling or profile overwriting occurs. Run inputs and step inputs are saved
as separate portable SQLite files. Unequal calendar intervals have explicit
objective/stores/generators elapsed-hour weights.

### Reusing 24 hourly values every day

Enable **Repeat daily profiles** in Runs for a one-day input template. The source
must be exactly one complete midnight-to-midnight day of contiguous, uniformly
spaced snapshots, and its interval must match the run interval. For example, 24
hourly demand/availability/price values repeat by time of day on every run date.
An hourly 12:00 start uses the template's 12:00 value first, not its 00:00 value.
Explicit opt-in permits different source and run dates/years. All supplied input
profiles (including any explicit setpoint profiles) use this same mapping.

For 15 two-day solves, the template expands to 720 hourly values in frozen run
inputs. The original project's 24 snapshots/profile values are unchanged.
Configured initial storage energy and solved storage states are not daily
profiles: state handoff still carries energy forward between solves. A deliberately
provided energy-setpoint input profile, however, repeats like other input profiles.

No interpolation, missing-hour filling or conversion from hourly to daily averages
is performed. Partial/multi-day/gapped templates and differing intervals are
rejected; custom weights must represent uniform physical interval hours. Exact
coverage remains the default for existing and genuinely date-specific datasets.
Run metadata records the explicit repetition policy and original template dates/
profile identities; expanded effective values are frozen in `inputs.sqlite`.

Initial support is chronological fixed-capacity dispatch, Store/StorageUnit
energy handoff, and native Generator/Link ramp/commitment inputs with uniform
snapshot durations for commitment/ramps. Minimum times still count snapshots,
not weighted hours; ramp limits remain per snapshot. Daily snapshots cannot
reconstruct intraday dispatch or battery cycles.

Unsupported sequential combinations fail before worker creation: investment
capacities, investment periods, representative/discounted time weights, whole-
horizon GlobalConstraints, Process state and delayed links, cyclic/per-period
storage conditions, and irregular-duration commitment/ramps. These continue to
use the existing project-axis single solve where supported by that workflow.
No silent reset of a global budget or repeated independent investment decision.

## State transfer and costs

Independent windows have **no look-ahead** and **free terminal energy** unless
explicit energy setpoints impose bounds. Short foresight may drain a battery at
a step endpoint; this is disclosed, not disguised as full-horizon optimality.

Storage handoff is from the preceding solve's final result. PyPSA 1.4 applies
configured initial energy without first-snapshot standing loss. For later windows,
the adapter applies the next interval's retention factor to the incoming energy
before setting the native initial value. This reproduces the internal recurrence
across boundaries, without omitting or double-counting boundary losses. The first
window preserves PyPSA's original initialization convention. Incoming energy,
effective initial value and boundary loss are separately recorded.

For Generator/Link, final dispatch supplies `p_init`; committable assets additionally
carry consecutive up/down snapshot counts. This preserves startup/shutdown and
minimum-time history across windows. Unsupported cases are blocked, not reset.

No overlapping intervals are added. The parent objective is the sum of disjoint
fixed-capacity step objectives, including native startup costs once where incurred;
it is not a full-horizon optimality claim or a prorated annual cost estimate.
Runtime/memory gains are workload-dependent, not guaranteed.

## Artifacts and failures

Parent folder: `run_config.json` with complete schedule, effective `inputs.sqlite`,
`execution_manifest.json`, assembled `solution.nc`, `tables/`, `catalog.json`,
`solution_checks.json`, `formulation_summary.json`.

Each `steps/step-NNNN/` has its own inputs, status, logs, actual solved LP/MPS and
symbol map when enabled, solution tables/NetCDF, checks and `handoff.json`. The
step record maps global snapshot slice `[first,stop)` to its local model. Numeric
x/c solver identifiers are unchanged. There is **no synthetic parent LP**.
Existing readable-formulation export applies to each actual step file; a new
step-picker in the reporting UI is not part of H01–H05.

The existing owned worker runs all steps off the UI thread. Progress gives step
number/dates and stages, not invented solver percentages. Per-step LP feasibility
is checked; assembly rejects duplicate, missing or unordered snapshot rows.

On failure/cancellation, completed step files remain diagnostic partial results.
Parent status is not succeeded and its results cannot be queried as a complete
solution. Cancellation kills only the owned worker and marks the active child
when available; interrupted runs opened later are not automatically rewritten.
Automatic resume/retry is not implemented. Existing frozen runs are untouched.

## Verification

Run from RawBuild with the existing EnEx Python:

```powershell
$env:PYTHONPATH = 'tests'
python -m unittest -v test_horizon test_horizon_ui
python -m unittest discover -s tests
```

Evidence: `docs/horizon-validation/`. Baseline port comparison records hashes and
file differences before porting; `port-regression.log` records 382 passing tests
before horizon work. Independent fixtures cover January floor/count semantics,
leap/month boundaries, input preservation/alignment, unsupported combinations,
15 actual solves, storage recurrence against a full-horizon reference, ramping,
commitment history, infeasible second step, actual themed controls, frozen-input
start, owned-worker solve/reopen/query and real mid-run cancellation. Final full
suite and platform render results are recorded in the project status handoff.

Final verification (2026-11-16): **400 regression tests passed in 767.782 s**,
47 supplemental UI tests passed in each theme, and four native Windows horizon
tests passed. Additional boundary cases include Link ramp/commitment, Generator
minimum-down history, zero-output windows, MPS export and tampered schedule
rejection. No v1.0.0 source files or matching legacy run artifacts changed; see
`horizon-validation/summary.json` for counts, timings and disclosed test limits.

Daily-profile follow-up: **408 tests passed in 813.312 s** after adding daily
repetition; see `horizon-validation/daily-profiles-regression.log`. Tests include
date/year changes, leap-day/non-midnight mapping, preservation of live inputs,
bad/incomplete/multi-day templates, interval and weight rejection, actual 30-day
load/solar repetition with continuous battery energy, and explicit checkbox/run
metadata handling. The new checkbox also passed a native Windows interaction test.
