# PyPSA Studio release notes

## v1.3.1 Preview — initial GitHub feature baseline

This entry records the capabilities available in the first GitHub preview, including features developed before the repository was published. Future entries should list only changes since the preceding release, rather than repeating this baseline.

### Project and model editing

- **Local projects:** Create, save, and reopen SQLite projects. Open native project files from the File menu or by drag-and-drop.
- **Schema-driven editing:** Define buses, generators, loads, lines, transformers, links, storage, and other supported PyPSA components. Edit properties in the object inspector or use the spreadsheet for bulk edits and TSV copy/paste.
- **Time-series inputs:** Configure snapshots, import CSV profiles, and review timestamp alignment before applying data. Sequential runs support explicitly repeating a daily profile.
- **Advanced modeling:** Configure supported unit-commitment and ramping constraints, snapshot and investment-period weights, and supported piecewise cost and efficiency curves.
- **Guided modeling:** Use built-in demos, plain-language attribute help (F1), validation, and read-only diagnostics for model and saved-run issues.
- **Editing safeguards:** Use model undo/redo, draft protections, local project backups, and recovery of applied changes.

### Network visualization

- **Interactive schematic:** View buses, branches, and attached assets with carrier badges. Pan, zoom, fit, filter, locate objects, and save or reset layouts without changing the model topology.
- **Saved-run flow overlays:** Inspect a frozen network at a selected snapshot and display solved active-power flows. Highlight passive-branch use of the modeled linear flow bound; this is not AC thermal loading.

### Solves and reproducibility

- **Single and sequential execution:** Solve with PyPSA, Linopy, and HiGHS. Sequential mode solves separate windows and carries supported operating states forward; it does not compute a single full-horizon optimum.
- **Scenarios and batch runs:** Define named variants, freeze their effective inputs, and run them as a batch without replacing the base project.
- **Run history and artifacts:** Reopen frozen inputs and results without solving again. New runs organize JSON under `metadata/`, optional LP/MPS files and symbol maps under `formulation/`, and sequential windows under `steps/`. Older runs remain readable without migration.
- **Formulation and numerical checks:** Export the actual LP or MPS formulation when requested, generate a readable annotation using its symbol map, and retain solver logs and post-solve numerical checks.
- **Standalone Python replay:** Export a `model.py` for one solve or a `run.py` plus step scripts for sequential replay. Each sequential replay creates a new folder, retains per-step outputs, and publishes a combined `solution.nc` only after all steps and assembly succeed.

### Results and reporting

- **Output-only Solution Explorer:** Query solved dispatch, line flows, storage levels, prices, commitment status, and optimized capacities where available. The selector excludes model inputs and known unused placeholders without treating genuine zeros as missing.
- **Portable NetCDF viewing:** Open a standalone `.nc` from the File menu or by drag-and-drop. Browse stored outputs read-only without the project database or CSV sidecars. Outputs omitted from the archive are not reconstructed.
- **Tables and charts:** Filter by snapshot and object, switch table layouts, sort results, pin queries, and zoom or pan chart timelines. Export the queried data to CSV.
- **Calendar summaries:** Aggregate supported quantities by hour, day, week, month, or year with valid weights and units. Optionally generate CSV reports and an HTML index after a run.
- **Saved studies and comparisons:** Restore saved dashboards, compare compatible frozen runs, and analyze energy, duration curves, and storage. Export charts and supported study reports.

### Desktop and preview scope

- **Desktop controls:** Light, Dark, and System themes; keyboard shortcuts for common project and editing actions; and a chart-font fallback for Windows.
- **Source preview:** Requires a compatible Python environment. No bundled runtime, standalone installer, or PLEXOS import/export is included. Linear optimization results do not establish AC feasibility or engineering suitability.

See the [README](README.md) for setup and a first study, the [run file guide](docs/RUN_FILES.md) for artifact locations, and the [Python replay guide](docs/PYTHON_REPLAY.md) for replay instructions.
