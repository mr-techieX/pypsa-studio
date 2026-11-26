# Standalone Python replay

In **Runs**, select **Save as Python run** and click **Start**. The checkbox has
the same label in both execution modes.
The scripts use PyPSA 1.4.0 and HiGHS; use the versions recorded in the original
`run_config.json` for the closest match. The scripts do not require Studio, the
SQLite databases, or source profile CSVs. This option is independent of LP/MPS
export. Studio generates the scripts but does not execute them.

| Run mode | Output | How to replay |
|---|---|---|
| Project snapshots · one solve | `model.py` | `python model.py` |
| Configured sequential steps | `run.py` and `steps/step-000N/model.py` | From the run folder, `python run.py` |
| One step in isolation | That step's `model.py` | `python steps/step-0002/model.py` |

The single-solve and individual-step commands print the objective. A step script
contains plain PyPSA model calls and the actual frozen initial conditions. It can
be run independently or imported without triggering a solve. The step script is
generated as Studio prepares that step, before optimization. A failed or stopped
Studio run may not have scripts for unreached steps; `run.py` checks the full
script list before replay and refuses an incomplete export.

For an entire sequence, the first step uses its saved initial conditions. Each
later step receives fresh state from the new preceding solve: Store and
StorageUnit energy with first-interval loss, and Generator and Link dispatch and
commitment history. The runner replaces saved initial conditions; it does not
add to them or reapply the original handoff. Keep ordered, contiguous snapshot
windows and matching static topology and inputs across steps, apart from the
initial conditions used for handoffs. Time series can differ by window.
If you edit the model, work on a copy of `run.py` and its `steps/` tree.

Each invocation writes a new `replay-*` directory with per-step NetCDF files,
combined time-series CSVs under `tables/`, and `metadata/summary.json`. The runner builds
`solution.nc` from the networks it just solved, preserving snapshot weights and
combining the step trajectories without running another solve. The file records
the step boundaries and the summed step objective: **not** a full-horizon
optimum. On solve or assembly failure there is no published `solution.nc`;
completed step files and failure diagnostics are retained.

Copy only the final `solution.nc` to share it; recipients can drop it into
RawBuild or use **File → Open results (.nc)…**. This does not create a Studio
run. See [Standalone NetCDF results](NETCDF_RESULTS.md). This applies to newly
generated sequential `run.py` exports; regenerate older exports to get the
new behavior. Single-solve and standalone step scripts are unchanged.

Run generated scripts only from sources you trust; editing them is editing
ordinary executable Python.
