# Stages 3M–4B — integrated studies and analysis

RawBuild 0.12.0 · implemented/integrated/verified, ready for user review.
**370 tests passed in 384.495 s**, retaining the **247-test** baseline.

## 3M: named scenarios and sequential batches

Run tools → Scenarios / modeling / diagnostics / analytics… → Scenarios / batch.
Definitions are optional SQLite metadata, not electrical inputs. Older readers
can ignore the library (older saves may drop it). Definitions survive model Undo
independently; project replacement clears session batch state. Apply validates
every detached candidate; Save persists definitions. Closing retains only session
editor drafts, not crash-recovery copies until Apply.

```json
[
  {"id":"base","name":"Base","changes":[]},
  {"id":"high","name":"High demand","changes":[
    {"component":"Load","name":"City demand","attribute":"p_set",
     "operation":"scale","value":1.1}
  ]}
]
```

Each case starts from the same saved base, not the preceding case. `scale` applies
to static/default values and matching profile values. `set` refuses a matching
profile rather than accepting an ignored scalar. Curve-owned targets are refused;
identity/reference/activation/topology edits are not scenario operations. Values
retain schema units; scale factors are dimensionless. Max 30 cases, 100 changes
each, 512 KiB definitions, finite numeric edits/results of magnitude ≤1e15.

Start saves the base, validates all cases, stages them privately, then publishes
complete unstarted runs under the base's `runs/`. Each captures its inputs,
definition/id/name and base-project SHA-256 provenance. Base input records and
existing runs are not altered by scenario construction. Batch preparation is
synchronous; cancellation becomes available when solving starts. One owned QProcess
executes the established worker at a time; failure retains diagnostics and the
queue continues. Stop cancels the active worker and marks waiting cases cancelled.
Save/replace/close/new solve waits for the batch to finish/cancel. Failed/cancelled
artifacts are not validated solutions. Machine-crash atomicity across publication,
automatic resume, detached-job execution and parallel solver scheduling are not
claimed. On reopen, unowned queued/running records remain interrupted/unconfirmed.

## 3N: native modeling controls and bounded curve extensions

Modeling controls loads a curated JSON subset for an existing Generator,
StorageUnit or GlobalConstraint, not a replacement object. Unlisted fields survive;
native optional defaults represented by null restore omission. Schema typing and
newly introduced validation errors are checked on a detached candidate. Apply
participates in model Undo/recovery; stale owner/value drafts cannot overwrite
newer edits. Units/defaults and individual field references remain in Help/F1.
Time profiles continue to override scalar inputs; no profile is silently removed.

Use Time / curves in the existing Saved analysis tools. Supported native pairs:

| Component / attribute | x | y / interpretation |
|---|---|---|
| Generator marginal_cost | p / fixed p_nom, 0..1 | Currency/MWh incremental prices |
| Generator / Link capital_cost | Total optimized p_nom, MW | Currency/MW incremental prices |
| Line capital_cost | Total optimized s_nom, native MVA | Currency/MVA incremental prices; native DC active-flow bound is numerically MW |
| Link efficiency | p0 / fixed p_nom, 0..1 | eta at each power point; output = x × eta × p_nom |

Costs start [0,0] with nonnegative nondecreasing segment prices. Investment prices
apply to total optimized capacity, not only an addition above today's capacity;
require extendability, finite explicit nominal maximum within the curve domain,
no overnight_cost and zero separate fom_cost (include fixed O&M in curve prices).
Period objective weights price investment, not snapshot durations. Native
capital_cost_piecewise_opt is average currency/capacity, not total currency.
Line impedance stays fixed; this is not iterative physical grid redesign.

Example investment curve (Generator G must be extendable with p_nom_max=100):

```json
{"component":"Generator","name":"G","attribute":"capital_cost",
 "points":[[0,0],[50,10],[100,30]]}
```

At 75 MW the capital contribution is 50×10 + 25×30 = 1250 currency units,
before explicit period objective factors. The scalar capital price is overridden,
not added again. Existing nominal capacity does not change this integral's origin.

Link efficiency uses native interpolation between **output-power** points, not
linear interpolation of eta. Fixed positive noncommittable capacity, forward bounds
within [0,1], distinct bus0/bus1 only, no extra ports/delays, eta in (0,1] away from
the [0,0] origin and strictly increasing x×eta. Equality may introduce binaries
even for a noncommittable Link. Example for p_nom=100:

```json
{"component":"Link","name":"converter","attribute":"efficiency",
 "points":[[0,0],[0.5,0.8],[1,0.6]],
 "options":{"method":"incremental","sign":"="}}
```

50 MW input gives 40 MW output; 100 MW gives 60 MW. A 50 MW output demand needs
75 MW input, not an eta-interpolated approximation. Matching profiles/conflicting
combinations are rejected. Optional methods: cost auto/lp with sign >=; efficiency
auto/incremental with sign =. Axes/integration cannot be overridden. Native HiGHS
LP/MILP is retained; SOS2/nonconvex/general curves, extendable+committable and
security/AC formulations are not offered.

Numerical references include all three investment types at 75 capacity, capital
1250 plus operation 225 = objective1475; conversion p0=75/p1=-50/objective900;
period-weighted investment, commitment startup/shutdown/minimum snapshots,
storage boundaries/retention/efficiencies/max_hours and explicit primary-energy
CO2 caps. PyPSA1.4 injects prescribed initial SOC without first-step standing loss;
later recurrence applies retention to the preceding optimized SOC. This behavior
is tested and documented rather than changed to a different recurrence.

## 3O: diagnostics

Diagnostics reads the current model or the separately loaded run's artifacts.
Structural/capacity screening is advisory, not an infeasibility proof or automatic
repair. Storage, extendable supply and conversion can invalidate a simple fixed
generation/demand screen; the report must disclose this. Solver failure advice
does not invent an IIS or promote infeasible/nonoptimal output to a solution.
No input/run files are rewritten. Known warnings remain visible unless an actual
root cause is demonstrated and repaired; no blanket warning suppression.

## 4A: network navigation

Network search/filter/focus and connected highlighting are presentation only.
Explicit readable arrangement does not change bus coordinates or connections;
Save layout remains necessary for persistence. Congestion refers only to actual
frozen passive p0 active-flow bound utilisation, not AC MVA/thermal loading.
Unavailable ratings/results remain unavailable. Historical snapshot navigation
remains independent of the active Results query. Native offline schematic, no GIS
or external map service introduced.

## 4B: explicit results analytics and report configuration

Results analytics uses the active executed QueryTab and its frozen repository,
not pending selectors or today's model. Energy requires temporal MW and explicit
weights; storage states in MWh are summarized, not integrated again. Signed power
retains its direction and is not automatically generation/consumption attribution.
Missing/nonfinite/unsupported units are rejected, not filled or converted.
Duration ranks preserve each value's own weight; no implicit hourly sampling or
interpolation. Duration hours exclude period years; those remain metadata. Energy
includes period years but never period objective/discount factors. Energy reports
signed net, positive and negative parts; negative stays negative. Storage reports
first-selected/last/min/max/arithmetic mean levels. Grouped duration/storage sums
simultaneous objects first, then ranks/summarizes; independent extrema are not
summed. Carrier grouping requires explicit frozen carrier identities. Periods and
properties stay in separate panels. Comparison charts use the last validated
comparison, with units and right-minus-left identity preserved even after changing
the active Results tab.

Computed output is captured separately from subsequent query/model edits. CSV is
complete; screen/report/chart bounds are explicit. HTML report title, 1–1000 data
preview rows and chart inclusion are configurable. SVG/PNG previews and HTML are
local; export paths cannot overwrite project/frozen-run artifacts. No new browser,
PDF/Excel, external service or arbitrary template engine dependency.

Chart bounds: at most 30 panels, 1000 points/series and six series. Weighted
duration steps contain two endpoints/rank, so previews show the first 500 ranks.
Numeric `x_values` drive both Canvas and SVG/PNG geometry, not equally spaced
indices. Complete cumulative hours remain available in uncapped CSV. Screen data
shows 100 rows, report 1–1000 chosen rows, always labelled against total count.

## Measured scale and remaining warnings

The refreshed `scale_gui_200_012.json` probe passed for 200 buses/602 objects/24
input hours: window 1.308 s, initial Bus-sheet load 7.972 s, Fit/capture 0.588 s,
peak process memory 550.13 MiB. Imports/native allocations and explicit event waits
are included as documented by the probe. This remains an approximately eight-second
large initial GUI load, not a demonstrated speed-up or responsiveness guarantee.
No annual/200-bus solve or utility-grid certification is claimed by a GUI probe.

Diagnostics investigation reproduced a shutdown-uncollectable object with a
standalone QObject subclass containing only one PySide `@Property(str)`, without
creating an application/controller. Controller instances collected normally in
that probe. This supports further upstream Python/PySide descriptor-GC investigation,
not a completed root-cause fix; warnings remain visible and unsuppressed.

## Verification

Final integrated regression passed **370 tests in 384.495 s**. Final-source actual
UI suite passed **42 tests in 113.246 s** (32 retained QML controls +7 network +3
extended interactions). No regressions detected in tested behavior. Known pandas
warnings and Qt shutdown GC ResourceWarning (13 uncollectable objects) remain
visible/unresolved. Runs overlapped independent checks; wall times are not speed
comparisons. User review is the next gate, not universal engineering certification.
Focused integrated checks passed **11 tests in 60.054 s**, including real batch
objectives 1500/750 with an infeasible middle case, cancellation of waiting cases,
metadata/history/diagnostic isolation, configurable report guards, comparison
source retention, numeric duration spacing and real themed QML controls. Independent
module suites passed 29 scenario, 31 diagnostic, 22 analytics, 7 navigation and
23 advanced-modeling tests. All **247 prior tests passed in 305.789 s** against
the integrated changes; all are retained in the final 370-test pass.

| Test inventory | Count |
|---|---:|
| Every retained test module from the first build through 3L | 247 |
| Named scenarios / construction / provenance / numeric cases | 29 |
| Native modeling curves and commitment/storage/cap references | 23 |
| Read-only model / run-failure diagnostics | 31 |
| Actual network navigation/layout/congestion interactions | 7 |
| Weighted aggregation/duration/storage/comparison analytics | 22 |
| Controller/Qt batch, history, metadata, export and real QML integration | 11 |
| **Total, 28 modules** | **370** |

Light original-demo and Dark regional20 real solve/edit-history/query/LP/frozen-flow
smokes and System smoke passed. All four populated Extended tools tabs in both
themes, network grid/focus and numeric duration exports were captured. Inspection
found a chart/description stretching beyond its viewport; constrained ScrollView
content width fixes it, and a real QML geometry assertion now protects it. The
final readable diagnostic view uses bounded plain text instead of a raw JSON dump.
Updated real QML tests passed 3/3 in 8.315 s. Final full-source Light original-demo,
Dark regional20 real-solve captures and System smoke passed; minimum Study tools,
new tabs, frozen Fit and 200-bus focused views were inspected. Captures use
`stage_m_b_final_light`, `stage_m_b_final_dark`, `stage_m_b_final_system` prefixes.

Separate real-solve acceptance exported weighted duration CSV/SVG/PNG and a
configured 12-row HTML report; all frozen SHA-256 hashes stayed unchanged. Review
artifacts are under `stage_m_b_review_v_7poxj4` in the approved temporary folder.
An independent 200-bus/600-displayed-node minimum-window probe passed bounded
readable layout, search and locate/zoom with the input project unchanged.
Compilation, local documentation links and dependency checks pass; no package
installation was performed. No whole-product or zero-warning claim.

The initial integrated UI fixture omitted QApplication setup and exited before a
test result; the fixture now uses the established setup contract. Optional native
NaN defaults in curated controls are represented by null/omission rather than
being reapplied as forbidden numeric NaN values. These fixes did not weaken earlier
tests or suppress warnings. A sub-agent's early concurrent full run was not used
as final acceptance; the parent completed the full regression after integration,
then rechecked the final UI source separately.

Reproduce from RawBuild with the existing environment:

```powershell
& '..\..\EnEx\Scripts\python.exe' -m unittest discover -s tests -q
& '..\..\EnEx\Scripts\python.exe' -m compileall -q energy_gui tests
& '..\..\EnEx\Scripts\python.exe' -m pip check
& '..\..\EnEx\Scripts\python.exe' -m energy_gui --smoke-test --solve-demo --theme Light
& '..\..\EnEx\Scripts\python.exe' -m energy_gui --smoke-test --solve-demo --demo regional20 --theme Dark
& '..\..\EnEx\Scripts\python.exe' -m energy_gui --smoke-test --demo regional20 --theme System
& '..\..\EnEx\Scripts\python.exe' -m energy_gui.scale_acceptance --buses 200 --hours 24 --gui --output docs/scale_gui_200_012.json
```
Independent module tests are development evidence, not acceptance of integration.
Original 247 regressions must remain, including original/public/demo solves,
schema/persistence, input/reference validation, editing/history/draft guards,
backup/recovery, frozen network/Results isolation, reports/charts and QML controls.
No whole-product, realistic-grid or zero-warning certification is claimed.
