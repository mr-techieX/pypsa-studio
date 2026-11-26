# Development foundations and capability matrix

Date: 2026-11-10. Initial Windows development baseline uses the existing Python 3.14.8 / PyPSA 1.4.0 environment. Registry coverage is version-checked, not guessed from historical tutorials.

## Component inventory

Counts include static and time-dependent inputs/outputs from the installed schema. Extended ports add further attributes at runtime. Network itself is the container, not an asset component. The initial uniform snapshot/interval settings are extended in 0.11 with explicit weights and investment-period assignments; see the final section below.

| Component | Base attributes | Authorable input attributes | Representation in RawBuild |
|---|---:|---:|---|
| Bus | 19 | 11 | Inspector / reusable builder |
| Carrier | 6 | 6 | Inspector / reusable builder |
| Generator | 61 | 46 | Inspector / profiles / builder |
| Load | 10 | 8 | Inspector / profiles / builder |
| Link | 61 | 45 | Inspector / profiles / builder; extra ports via JSON |
| Store | 40 | 31 | Inspector / profiles / builder |
| StorageUnit | 52 | 39 | Inspector / profiles / builder |
| Line | 43 | 28 | Inspector / profiles / builder |
| LineType | 9 | 9 | Inspector / catalogue insertion |
| Process | 64 | 48 | Inspector / profiles / builder; extra ports via JSON |
| Transformer | 47 | 32 | Inspector / profiles / builder |
| TransformerType | 16 | 16 | Inspector / catalogue insertion |
| ShuntImpedance | 10 | 6 | Inspector / builder; AC-shunt effects are not a DC-OPF feature |
| GlobalConstraint | 8 | 7 | Inspector / builder; not every constraint variant is validated |
| Shape | 5 | 5 | WKT geometry / metadata builder; no optimization effect |
| SubNetwork | 3 | 0 | Derived; result inspection only |
| **Total** | **454** | **337** | Runtime schema is authoritative |

The total input count must be derived from `registry()` rather than hard-coded; individual counts include the `name` identifier. Outputs are not offered as editable inputs. Component names and field membership are regression-tested against the installed Network schema.

## Initial formulation compatibility

| Capability | Current position |
|---|---|
| Continuous linear nodal economic dispatch with AC Lines under DC approximation | Implemented; small synthetic congestion case used for numerical tests |
| Time-varying load / generator availability / marginal price inputs | CSV-to-profile path implemented; exact snapshot alignment required |
| HiGHS commitment/MILP path | Native PyPSA formulation; startup/shutdown and minimum-snapshot references tested through 0.12, not comprehensive scheduling certification |
| Carrier conversion / multiport Link and Process | Generic schema/builder and multiport construction tests; 0.12 adds numerical restricted two-port Link efficiency-curve references, not general conversion certification |
| Storage / hydro constraints, investment variables, global constraints | Numerical storage boundaries/retention/efficiencies, nominal investment and explicit primary-energy CO2 caps tested through 0.12; other variants need acceptance cases |
| Transformer / standard type behavior | Stage 2 tests manual Transformer congestion and input/type references; comprehensive catalogue/tap/phase behavior still needs benchmarks |
| Custom weights / multi-investment periods / piecewise functions | Explicit positive weights and globally unique timestamp assignments; 0.12 supports bounded native Generator marginal cost, Generator/Line/Link capital cost and restricted fixed forward two-port Link efficiency curves. Unsupported combinations, zero weights and repeated period timestamps are rejected; exact axes/limits are in STAGES_3M_4B.md. |
| Quadratic objective | Outside initial LP/MILP path; nonzero coefficients rejected, not silently ignored |
| Reactive power and nonlinear AC-OPF | Not provided by the standard linear workflow; no AC-OPF claim |
| AC power-flow validation | Future feature; a power-flow check would not be AC-OPF |
| LP/MPS export | Export native Linopy model before solve; independent LP re-solve test compares objective |
| Readable mathematical report | 0.11 annotates actual saved LP/MPS with symbols.csv; original coefficients/bounds remain. This is not a newly generated full algebraic model or valid solver-input syntax. |

## Project schema version 1

- `metadata(key PRIMARY KEY, value)`: application identifier, schema version, JSON project settings including project UUID, target PyPSA version, snapshots, interval hours, name and currency label. From 0.11, nonempty `advanced_inputs` remains in the core settings so older constructors reject unsupported model semantics rather than silently dropping them; empty defaults are omitted.
- From 0.12, optional `metadata.scenario_library` stores named definitions separately from core inputs/model history; old readers can ignore it and older saves may drop it.
- `components(component, name, attributes)`: composite primary key; attributes are JSON input values checked against the versioned component registry.
- `profiles(component, name, attribute, data)`: composite primary key; aligned numeric values, source filename and unit are stored in JSON. Original source file paths are not a runtime dependency.
- SQLite transactions make saves atomic. The loader uses read-only mode. Foreign project/schema versions are refused, not silently migrated. Input validity is checked before run creation and again inside the worker.
- This schema is an initial internal format; no migration promise until tested migration tools are added.
- Inputs are the SQLite source of truth; solved output uses NetCDF + CSV table catalogue. This separation prevents solver outputs overwriting inputs.

## Run names, statuses and scope

`runs/YYYY-MM-DD_HHMMSS_sanitized-label_uniqueid/` is under the selected database's parent directory. Project UUID filters the history when multiple project DBs share a folder.

Lifecycle: `queued → running → succeeded | failed | cancelled`. A process that terminates unexpectedly is marked failed when observed by the GUI. Recovering stale queued/running entries after a whole-application crash remains future work. Only optimal results are published; feasible nonoptimal time-limit incumbents are not currently supported.

Development choices are recorded, not user acceptance sign-off. Phase 0 remains in progress until the user reviews the initial scope/format/compatibility constraints.

## RawBuild 0.2 presentation and query contract

- Theme preference is local application state (Qt user settings), not an energy-model attribute. Light/Dark overrides and live System detection share palette tokens from `qml/Theme.qml`; the original four user colours are retained with derived accessible foreground/background shades.
- Query selectors are separate from editor selections. The component-category tree allows multiple objects in one category, and the property list exposes individual available attributes rather than an entire static table as one item.
- Loading a run populates metadata only. Static tables supply object/property metadata; time-series tables are read lazily when an explicit Query requests them. Changing controls does not execute a query.
- Results object scope is the intersection of explicit `(component, name)` records in that run's frozen `inputs.sqlite` and exported static table rows. A category with no matching objects is not displayed. This excludes standard-only type catalogues, automatically introduced records and derived SubNetworks, without hard-coding a blacklist: explicit LineType/TransformerType/Carrier records remain queryable. A reference to a built-in type is not an explicit object definition. The same scope is enforced by `ResultsRepository.query`, not only the QML tree. All available input/output properties of the retained objects remain exposed; this is an object filter, not a restriction to user-entered attribute names. Old run artifacts remain read-only and need no re-solve; the full raw export/NetCDF is retained for diagnostics. Current model edits never redefine the scope of saved runs or their pinned queries.
- A temporal query returns `snapshot, object, <selected attributes>` with an inclusive interval (0.11 multi-period models additionally retain `period`). A static-only query returns `object, <selected attributes>`. Mixed queries broadcast selected scalar values over the requested snapshots. These transformations do not alter the saved outputs.
- Dynamic input columns absent for some objects fall back to corresponding scalar values when available. Missing outputs remain missing, not zero. Numeric properties each receive their own unit-labelled chart; string properties are table-only.
- Data/Charts retain the last completed query when drafts change. The query-options Qt signal is separate from ordinary result-state updates so snapshot endpoints are not reset by execution.
- Current query limits: one category and contiguous interval per query, table preview ≤1000 rows, temporal charts ≤1000 snapshots / 6 object series per property, static bar/dot plots ≤1000 objects and horizontal bars ≤100. Full queried CSV export is uncapped. 0.11 adds saved ordered query dashboards; 0.12 adds separate bounded frozen-query energy/duration/storage/comparison analytics. Arbitrary SQL, general-purpose aggregation and free-form dashboard design remain unsupported.

## Stage 2 / RawBuild 0.3 additions

- `workspace.py` owns session-only dataframes, run metadata, criteria and chart styles. One preview is replaceable; pinned tabs are never selected as replacement targets. Unpinning another tab pins the old preview rather than discarding it. Closing a background tab does not change the current query source.
- Chart styles are per property/tab. Temporal line/grouped-bar/dot are supported; stacked-area is restricted to finite nonnegative MW/MWh data. Static-only queries offer bar/horizontal-bar/dot, not temporal charts. Style changes do not modify query values or invoke a solver. Each plot explains applicable options.
- Query controls place Snapshots over Properties at approximately 1:2 height, with Objects alongside. Data/Charts toggle views replace the earlier vertical split. Chart delegates bind only to the active workspace tab, never the union of saved/pinned queries. Overlay dropdowns dismiss on ancestor scroll/movement, external focus, hiding, deactivation and model changes without interfering with their own list scrolling or native keyboard selection.
- `NetworkView.qml` gives project records other than Carrier a draggable delegate. Carrier definitions remain unchanged/editable in Objects, but no longer form network nodes: each object's own carrier reference (or installed schema default, e.g. Bus AC) becomes a compact badge and full-name tooltip. Blank labels are hidden; no fuel/technology label is inferred from connected buses and no carrier wires are invented. Badges share their object's drag/Ctrl-click gesture. `NetworkIcons.js` retains all installed type symbols and a fallback. Typed/name-pair keys avoid cross-type name collisions. Actual bus ports (including numbered Link/Process ports) generate wires; other unconnected records remain visible. Ctrl-click inspection selects atomically after draft resolution. Visual positions survive page/state refreshes within the current project/session but are not saved to SQLite, used as geographic coordinates or interpreted as rewiring. Reset layout restores the initial arrangement. Large/dense-grid layout validation remains pending.
- Run source browsing loads saved inputs/catalogues without optimization. Project identity is checked before source state is committed; incompatible/foreign/missing run data leaves the previous source intact. Pinned values remain in memory independently of saved artifacts.
- Object inspector drafts are synchronized with the controller and protected at object/category navigation, page navigation, save, run, delete and close. The typed helper exposes units/defaults, bus choices and boolean choices. This is not a full spreadsheet editor or undo system.
- `validation.py` adds nominal-capacity/range checks, scalar/profile limit comparisons, storage-efficiency/loss checks, type-catalogue checks and Line voltage consistency. Warnings explain reactive/power-flow inputs that do not constrain DC-OPF. Converter efficiencies above 1 (heat pumps) and signed Link dispatch remain representable.
- New-run publication requires `solution_checks.py` to pass finite primal, linear constraint, bound and integer checks. Constraint residuals scale by `1+abs(rhs)` with tolerance `1e-5`; reports are stored in `solution_checks.json`. Older saved runs remain readable without this additional file and without a re-solve. No nonlinear feasibility claim is made.
- Independent acceptance cases now cover StorageUnit charging/discharging and energy, Store with Links, fractional-hour hydro inflow, a manual Transformer bottleneck, Link/Process conversion economics, a primary-energy emissions constraint, and commitment startup cost/minimum output. Investment, delays, piecewise, contingency and full multi-port operational combinations still need further validation.
- SQLite schema v1 is unchanged; no security signatures or new dependencies introduced.

## Stage 3A / RawBuild 0.4 — initial bulk editing increment

- Stage 2 was explicitly accepted by the user on 2026-11-11. Stage 3A adds an optional static-input grid to Objects while retaining the original inspector and its guards. It is not completion of all proposed Stage 3 work.
- `ObjectSheet` stages raw cell strings against an immutable project snapshot. Existing identities are locked; new rows/pasted names create objects, never implicit renames. Raw schema column names and extra numbered ports are accepted through header-based TSV. Outputs, unknown/duplicate headers, malformed rows, duplicate pasted names and invalid scalar values reject the whole paste before changing the draft.
- Apply constructs a cloned candidate, preserves unspecified fields/profiles, rejects stale baselines and newly introduced `Project.validate()` errors, and swaps it into the controller only when accepted. Existing unrelated errors remain visible so incomplete projects can be repaired by category. Full validation and solve publication checks remain mandatory; validation is not a feasibility proof.
- Draft resolution protects category/object/page changes, editor switching, save/run, close and project replacement. Busy workers disable edits and Apply. A 20-batch session snapshot history is guarded by exact full-project equality, so undo/redo cannot overwrite unrelated mutations. It is not crash recovery, global history, persisted dashboards or saved network layout storage.
- The 14-bus/24-hour ring benchmark is explicitly synthetic. Spreadsheet-edited inputs are saved/solved; checks independently reconstruct nodal balances, cyclic battery energy, transformer/converter limits and the generator-cost objective. This extends development evidence, not engineering certification or a large-scale performance claim.
- No schema migration, new package, raw result-format change, cryptographic signing or AC-OPF integration was introduced. Global rename/history, broader draft protection and saved layouts/flow overlays remain later increments.

## Stage 3B / RawBuild 0.5 — ribbon and non-destructive editor configuration

- The user confirmed component-category selection and hide-only behavior. The new ribbon replaces sidebar navigation and routes tabs/menu commands through existing draft-protected controller paths.
- `editor_config.py` validates selected categories/property names. `Project.editor_config` is UI metadata; construction/validation/optimization still uses every original object, attribute and profile. Objects filters only its category list, property references/helpers and spreadsheet columns; Results/Profiles/Network keep their existing scope. Explicit Advanced JSON can still reveal all stored inputs. Hidden TSV columns are rejected, not silently ignored, and unchanged hidden inputs survive visible batch edits.
- Persistence adds an optional `metadata.editor_config` JSON entry to schema-v1 SQLite. `storage.py` excludes it from the core `metadata.project` payload for older-reader compatibility. Missing metadata means all categories/properties visible. Apply configuration changes in-memory preferences; Save persists them. Unapplied configuration drafts are not restored after project replacement/restart. Preference changes can invalidate incompatible spreadsheet history, rather than allowing history to overwrite newer settings.
- The mandatory name property remains visible. Output/reference properties are labelled as such and never become writable spreadsheet inputs. Existing extra ports are included in property metadata. Empty visible-category lists are safe and reversible; visibility never defines optimization participation.
- Help follow-up removes the inline Objects reference list. `references.py` supplies the full, unfiltered installed component schema plus local `Attribute-Info/` Markdown guides and curated Network entries; validated class names constrain file lookup. `ReferenceHelp.qml` is a read-only modal library with search and exact-property deep links. F1 walks active-focus ancestry for `referenceComponent`/`referenceProperty` metadata, falling back to the current class. Opening Help never resolves/applies/discards an editing draft or executes a query. Missing guide files retain component schema information with a notice. Bundling these guides outside the workspace remains a packaging task.
- Tests compare all built PyPSA static/dynamic input tables before/after display configuration, test SQLite/default round trips, hidden-value preservation, stale/draft rejection, search/checklist interactions, ribbon menu navigation/save, and retained spreadsheet/result interactions. No claim of global undo, rename, geographic layouts, flow overlays or production certification is added.

## Stage 3C / RawBuild 0.6 — identity-safe editing and helper draft lifecycle

- The refined ribbon keeps navigation separate from commands. Local SVG icons and explicit white-on-purple pointer/keyboard menu highlights avoid platform-dependent contrast. Existing controller command paths and Help/F1 remain in use.
- `object_edits.py` enumerates typed references including implicit defaults. Candidate rename/deletion operates on a deep project copy, not live records. Bus ports, carrier references, standard types, Shape component/index pairs and type-dependent GlobalConstraint selectors have explicit semantics. Unknown/ambiguous references are blocked; descriptive fields and primary-energy coefficient-column names are not blindly replaced. AC/DC labels used by buses/lines are protected. Native confirmation describes affected references/profiles, then a full-project revision check rejects stale candidates. Deletion includes only explicitly selected records plus their own imported profiles, and blocks all surviving known references. The legacy single-delete path shares these checks.
- Identity changes clear spreadsheet snapshot history to avoid resurrecting renamed/deleted objects, but do not clear/rewrite frozen results or query tabs. They are not global undoable commands. Storage schema and raw run format remain unchanged.
- Controller-owned settings/CSV drafts are session state, not persisted model inputs. QML synchronizes them only on explicit resets, retaining typed settings and stable CSV mappings across unrelated notifications. Profile import targets are independent of the Objects inspector. Apply stages/validates a detached project before publication; invalid input stays pending. Navigation/save/run/close/replacement resolves drafts with Save-to-project/Discard/Cancel. CSV discard clears the source/mapping, not imported model values. Prompts are sequential rather than one multi-section transaction; already applied sections remain if a later prompt is cancelled.
- Verification includes reference/profile/type/default/ambiguity cases, cancellation and active-run guards, stale confirmations, SQLite round trips, live UI actions and a real renamed-model solve with independently reconstructed objective. Later live edits leave historical names/inputs/query results untouched. Large-grid performance, global history, crash recovery and realistic-system certification remain out of scope.

## Stage 3D / RawBuild 0.7 — persisted schematics and frozen port flows

- `network_view.py` owns pure typed topology construction, layout validation and snapshot overlay payloads. `NetworkView.qml` retains drag/badges/pan/zoom/inspection and adds explicit layout save/reset, Fit, successful-run selection, snapshot selection, MW arrows/labels and read-only details. New unsaved views auto-fit; saved views restore their own geometry/viewport. Unsaved adjustments are session-only, separate from model drafts.
- `Project.schematic_layouts` persists under a separate optional SQLite metadata key, excluded from `metadata.project` for older-reader compatibility. Old/malformed optional data falls back to arrangement; older writers may discard the optional key. Current layout and portable run-folder-keyed historical layouts are independent. Save layout also saves the project; failed/cancelled file saving retains a dirty in-memory capture. Reset alone is not a database write. Layout validation limits 10000 positions, coordinates within an at-most-8000-per-side/16-million-pixel canvas, finite pan and 0.1–3 zoom (minimum lowered from 0.25 in Stage 3E for 20-bus frozen Fit); at most 100 historical layouts plus live are saved. Older readers may fall back for layouts below their old zoom minimum; model inputs remain readable.
- Saved live positions follow reference-safe rename/deletion; run layouts do not. `layout_state.sheet_state` excludes layouts from spreadsheet model compatibility and preserves newer metadata when restoring history/candidates. Neither topology construction nor layout saving changes component attributes, bus coordinates, profiles, snapshot weights or mathematical construction.
- The controller holds a dedicated network-results repository independent of Results tabs. Loading validates succeeded status and matching project identities; each payload uses the frozen input topology with its saved port outputs. Changing current project objects never changes that graph. Missing snapshot/source selection preserves the prior view; project replacement clears historical view state. Historical Ctrl-click requires an identical extant live record and normal draft resolution.
- Overlay p_i > 0 means withdrawal from bus_i into the branch; negative means delivery. Each numbered Line/Transformer/Link/Process port is read directly from its result column, with no output-to-static-default fallback, lossless assumption or guessed conversion. Only MW ports are overlaid; explicit other units and missing/nonfinite outputs are unavailable. Passive p0 utilisation uses exported fixed/type-derived s_nom or extendable s_nom_opt, times actual snapshot s_max_pu. It is explicitly linear active-flow bound use, not AC apparent power/thermal assessment. Converter percentages are not synthesized.
- Verification includes optional-key/default compatibility, save/reopen/reset/zoom/pan, identity/history preservation, unchanged built PyPSA inputs, frozen-byte/topology/query isolation, failed/foreign selection, signs/reverse flows/losses/multiports, absent columns and non-MW units, dynamic bounds/optimised capacity, malformed payloads and real QML interactions. The existing solved 14-bus acceptance case cross-checks port overlay values against raw exported tables. Geographic mapping, large-grid certification, dashboard persistence, scenario comparison and installer work remain deferred.

## Stage 3E / RawBuild 0.8 — use-case library, validation and measured reliability

- `demo_library.py` builds seven fixed-data studies from 2–20 buses. `DemoLibrary.qml` exposes notes/assumptions before guarded replacement. `loadDemo()` stays the original three-bus wrapper; `loadDemoModel(id)` validates a detached candidate and uses existing draft/unsaved/pinned guards. Loading never solves. Each new load has a new project identity.
- Optional `Project.demo_info` persists in its own SQLite `metadata.demo_info`, excluded from `metadata.project`; older files default to `{}` and older readers can ignore it. Frozen inputs preserve notes/attribution. These describe the initial case, not correctness after editing. Core schema version 1, profiles and result export formats stay unchanged.
- PGLib IEEE14 is pinned, explicitly CC BY 4.0 and adapted to lossless DC with documented effective reactance/taps, estimated ratings, one-hour costs and uniform voltage normalization; source AC resistance/reactive/shunt/voltage effects are not validated. See `../THIRD_PARTY_NOTICES.md`. `study_validation.py` independently reconstructs balance/cost/storage/converter checks, overlays and public DC nodal flows, separate from generic Linopy constraint/bound/integrality checks.
- Frozen network layout precedence: explicit current-project per-run layout, then the live layout captured in that run's inputs, then automatic arrangement. Never fall back to today's live coordinates. Minimum-window whole-node Fit/save tests cover both themes and 20 buses; 10–300% zoom changes only optional UI state.
- `diagnostics.py` validates saved run status/identity and adds actionable lock/missing/corrupt messages. Results rejects malformed/empty catalogues and duplicate/missing static identities. Candidates are read before replacing Results/network state. No repair, migration, signature or crash recovery is implied; absent port outputs remain unavailable as before.
- `acceptance.py` isolates numerical/performance cases in fresh processes and temporary directories; `ui_acceptance.py` separately times offscreen Bus-sheet and diagram handling. Timings include stated scopes/imports/waits/native process memory, not guarantees. See `STAGE3E_VALIDATION.md` and machine-readable measurements for evidence and limits.

## Stage 3F / RawBuild 0.9 — backup and applied-state recovery

- `safety.py` owns separate session-locked atomic recovery copies and exclusive
  saved-project ZIP backups with SQLite snapshotting, frozen-identity run scope
  and checksum inventories. It never repairs/migrates original projects/runs.
- Desktop startup enables per-user recovery; controller mutation notifications
  schedule a one-second capture only for dirty applied state. Save/confirmed
  normal discard clears only the owning copy. Startup/File inspection uses
  explicit restore/discard/cancel; restore starts unsaved with no original target.
- Unowned queued/running run entries are read-only interrupted/unconfirmed,
  including possible other-session workers, never promoted to valid solutions.
- Core schema-v1 project/run formats remain unchanged; recovery tags exist only
  in separate local copies. Full contracts, exclusions and evidence are in
  `STAGE3F_SAFETY.md`. Full-session recovery, power-failure guarantees, global
  undo, automatic solver resume and distribution remain out of scope.

## Stage 3G / RawBuild 0.10 — session model history

`history.py` provides detached atomic applied-state snapshots, labels, exact
source-state guards, Redo branching and 20-operation/32-MiB encoded limits. The
controller records explicit successful mutation paths rather than view/selection
notifications. Model steps preserve newer layout metadata while reconciling live
identity keys, retain frozen Results/network repositories, clear incompatible
legacy batch stacks, reset editor/helpers and trigger normal dirty/recovery logic.
New/open/demo/recovery clears model history; Save retains it. Model history never
enters core SQLite/frozen inputs/backup/recovery payloads. See `STAGE3G_HISTORY.md`
for supported commands, exclusions, limits and actual verification evidence.

## Stages 3H–3L / RawBuild 0.11 — integrated studies and advanced inputs

- `analysis.py` stores optional portable query definitions under
  `metadata.analysis_workspace`, never duplicated results. Every source is a
  single folder name under `runs/`, with matching successful-run/frozen project
  identity. Every card validates before tabs/source state are replaced. Model and
  batch history preserve newer analysis definitions independently of model steps.
- Compatible-run comparison requires the same project/currency/formulation,
  exact timestamp/period axes and effective weights, property units/kinds and
  selected identities/object/bus units. Numeric values must be finite/complete.
  Delta is right minus left. Metrics use frozen inputs/results and explicit
  factors; missing emissions data is unavailable, not zero.
- `reporting.py` produces escaped offline HTML and bounded SVG/PNG previews;
  complete queried/comparison tables remain separate CSV exports. LP/MPS
  annotation streams actual saved mathematics and expands symbols without changing
  source bytes. Controller destinations exclude project/frozen-run paths.
- Large standard components use native vector insertion and profile tables are
  built in bulk. Static/dynamic tables and default weights match the old scalar
  construction, including dtypes/index names. Results cache time indexes. Four
  reproducible scale reports distinguish solves from build-only inputs and
  disclose the observed ~8.1 s first 200-bus GUI load; no universal SLA.
- `backup_worker.py` runs streamed ZIP backup on QThread with file-count progress
  and cancellation before exclusive publication. Saved-project scope and earlier
  checksum/collision/concurrent-change guards remain. Save/solve/replace/close
  waits for completion/cancellation; no forced thread termination. Original
  synchronous backup remains available and external writers must still stop.
- `advanced.py` validates positive objective/storage/generator snapshot weights,
  explicit ordered investment periods/objective/years weights and one assignment
  per globally unique timestamp. Native MultiIndex construction avoids implicit
  snapshot replication; no automatic discounting. Raw CSV/query/chart/network
  readouts preserve period identity. Empty legacy defaults retain previous build
  behavior exactly. Nonempty core `advanced_inputs` deliberately fails closed in
  older readers; no destructive schema migration.
- Native piecewise support is limited to convex nonnegative fixed positive
  noncommittable Generator marginal cost with dispatch in [0,1]. Breakpoint y
  values are preceding-segment incremental prices, not total cost coordinates.
  Other types/conflicting profiles are rejected, never silently ignored.
- `StudyTools.qml` exposes five tabs through Run tools. Profile TSV and advanced
  JSON Apply are atomic model edits participating in Undo/recovery. Draft-owner/
  source baselines prevent stale overwrites; project replacement clears drafts.
  Closing retains only session drafts, not crash-recovery copies until Apply.
- Full contracts, independent numerical references, scaling methodology,
  compatibility limits and final regression/render evidence are in
  `STAGES_3H_3L.md` and `../../PROJECT_STATUS.md`. Scenario automation, general
  piecewise modeling, GIS, AC/security, persistent history/full-session recovery,
  packaging and signing are not included.

Final integrated verification (2026-11-12): **247 tests passed in 335.228 s**,
retaining all 212 earlier tests. Final themed solve/render, export/hash/relocation,
combined advanced/history/recovery numerical, compilation and dependency checks
pass. Known pandas and Qt shutdown GC warnings remain unresolved; user review is
the next gate, not full-product certification.

## Stages 3M–4B / RawBuild 0.12 — scenarios and richer analysis

- `scenarios.py` validates data-only named variations against detached copies of
  a saved base; scale includes profiles, ignored scalar sets/curve targets and
  identity/topology edits are refused. Optional `metadata.scenario_library` is
  outside the core payload and excluded from model-history compatibility; older
  readers may ignore it. Every candidate validates before private staging and
  publication of unstarted frozen runs with scenario/base-hash provenance.
- `study_extensions.py` supplies inherited Qt study commands; Controller retains
  the same QProcess worker/status/results path. Batches run sequentially, continue
  after failure, cancel waiting/active cases and block save/replace/close/new runs
  until terminal. No worker grandchildren, arbitrary code or automatic resume.
  Preparation is synchronous; no multi-directory machine-crash transaction claim.
- Native bounded curves extend Generator marginal cost with Generator/Line/Link
  capital cost and fixed forward two-port Link efficiency. Cost y values are
  incremental prices; capital x is total nominal capacity with finite maximum.
  Conversion points interpolate output power x*eta*p_nom, not eta. Line s_nom
  retains native MVA units (numerical DC MW bound). General/nonconvex curves,
  joint extendable commitment, overnight/fixed-O&M double counting and unsupported
  profile/port/delay combinations fail explicitly. Structured controls edit only
  curated existing attributes and participate in model Undo/recovery.
- `model_diagnostics.py` provides bounded read-only structural/capacity findings
  and fixed-file solver-failure advice, with explicit omitted contributions and
  no IIS/feasibility certificate or automatic repair. A minimal PySide Property
  descriptor reproduces shutdown GC behavior independently of the controller;
  this is investigation evidence, not a resolved upstream warning.
- Network presentation adds filters, safe focus/connected highlights, explicit
  deterministic grid arrangement, frozen passive-p0-only congestion and snapshot
  stepping, preserving topology/results/unsaved coordinate isolation. The default
  arrangement and all old view methods/objectNames remain.
- `analytics.py` computes signed weighted energy, synchronous-group duration/state
  summaries and comparison panels from captured frozen queries. Numeric duration
  coordinates are rendered by Canvas and SVG/PNG as paired weighted steps, not
  uniform samples. Properties/units/periods stay separate; missing identities or
  data are rejected. Full CSV and configurable bounded HTML/chart reports retain
  run/query/accounting provenance independently of later edits.
- ExtendedTools is opened from Run tools; the existing five-tab Saved analysis
  dialog is retained. Full scope/curve axes, test inventory, measured scale and
  final acceptance evidence are in `STAGES_3M_4B.md`. Packaging, GIS, AC/security,
  persistent/full-session history and general scenario optimization remain future.

Final 0.12 verification: **370 tests passed in 384.495 s**, including all 247 prior
tests; final actual UI suite **42/113.246 s**. Themed real solves/System smoke,
numeric references, batch failure/cancel, frozen hashes, inspected populated/
minimum/export/200-bus views, compilation and dependencies pass. Known upstream/
Qt shutdown warnings and large initial-load latency remain; user review is next.
