# Standalone NetCDF results

Drop one local PyPSA `.nc` file onto the Studio window, or choose
**File → Open results (.nc)…**. A Studio single-solve `solution.nc`, sequential
parent `solution.nc`, per-step archive, or new sequential
[replay `solution.nc`](PYTHON_REPLAY.md) can be opened on its own. No SQLite,
catalogue, CSV or other companion file is needed.

Studio opens the archive as a **read-only external source** in Results. It does
not replace the active model, apply or discard drafts, run a solve, or add to
Run history. Previously pinned queries remain in the workspace. Use **Query
source** or **Browse…** to return to a native saved run.

Select a component, objects, output properties, and an inclusive snapshot range,
then click **Query**. The Solution Explorer uses the same output-only rule for
standalone archives and saved Studio runs. For example, generator dispatch `p`
and optimized capacity `p_nom_opt` are results; input capacity `p_nom`, marginal
cost and setpoints belong in the modeling views. If PyPSA omitted an output
field or object column, Studio does not assume a zero or synthesize missing
results. An inputs-only archive opens with no queryable outputs. Calendar
aggregation additionally needs valid saved chronological weights, compatible
units, and complete selected data; otherwise use native snapshots. Saved Studio
dashboards, formulations, and study analytics still require a native Studio run.

When browsing a Studio run folder, the viewer also hides unused piecewise-cost
placeholders and uncomputed zero-price columns from verified HiGHS integer
runs. It does not hide genuine zero outputs just to match a NetCDF file. Older
or third-party archives may still list fewer outputs when PyPSA omitted stored
data during export.

An older Studio dashboard that queries inputs cannot be restored as-is. Studio
identifies the excluded properties and leaves the saved dashboard and current
tabs unchanged. Run a new output-only query and save a new dashboard if needed.
Existing raw exports and **Reports after run** are unchanged.

A reported objective is not independent evidence of a successful solve.
Inputs-only archives may have no stored output series. Sequential replay
objectives are sums of step objectives, not full-horizon optima.

The viewer requires sorted, unique datetime snapshots; integer-indexed
networks and repeated timestamps across investment periods are not supported.
Archive limits are 512 MiB on disk, 2,048 root variables, 100,000 snapshots,
25,000 component objects, 8 million variable cells, and 8 million characters
in decoded text fields.
Each query is limited to 2 million selected property cells; select fewer
objects or a shorter range if needed. Loading can be cancelled between reads;
failure or cancellation leaves the current Results display unchanged.
On Windows, Unicode paths may need a temporary local copy because of the
NetCDF library's path handling. Studio removes that copy when loading ends.
If the Windows temporary directory also has a Unicode path, move a copy of
the archive to an ASCII-only path before opening it.
