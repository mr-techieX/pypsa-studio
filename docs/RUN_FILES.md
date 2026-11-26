# Run folders and metadata

New Studio runs keep `inputs.sqlite`, `solution.nc`, logs, and the optional
`model.py` or `run.py` at the top level. JSON goes into `metadata/`; solved
tables, calendar reports, optional LP/MPS and `symbols.csv`, and sequential
children stay in `tables/`, `reports/`, `formulation/`, and `steps/` respectively.
Each sequential child has its own metadata. Older flat runs still open and
are not migrated. To browse a saved run, select the run folder, not `metadata/`.

| JSON file | Meaning |
|---|---|
| `run_config.json` | Frozen run setup, project identity, solver and versions, status, timestamps, and final objective or error. Sequential parents also include the schedule. |
| `catalog.json` | Index of static and time-series result CSVs, used by the Results viewer. It contains references, not the solved values. |
| `formulation_summary.json` | Model variable and constraint inventory, or the sequential parent's explanation of the per-step formulations and objective scope. |
| `solution_checks.json` | Numerical post-solve checks and residuals; not an AC feasibility certificate. The sequential parent summarizes the step checks. |
| `execution_manifest.json` | Sequential parent only: planned and completed windows, progress, objectives and boundary-state records. |
| `handoff.json` | Sequential child only: the incoming, applied and outgoing states for that window. |
| `manifest.json` | Optional calendar reports: selected resolutions, generated CSVs (relative to `reports/`), aggregation details and anything skipped. |
| `summary.json` | Standalone Python replay only: final status, step boundaries, objectives and outgoing state, or the failed step and error. |

**Standalone replay naming:** `run.py` uses Python's `tempfile.mkdtemp` to
create `replay-<random suffix>` alongside the script. Python picks a unique
directory atomically so repeated or concurrent launches don't overwrite each
other. The suffix is not a date, run ID, or model parameter. New exports put
the replay summary in `metadata/summary.json`; older `run.py` files are unchanged.
