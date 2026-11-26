# PyPSA Studio v1.3.1

- New run folders organize JSON under `metadata/` and LP/MPS exports under
  `formulation/`. [Run file guide](docs/RUN_FILES.md). Older runs are unchanged.

- Saved Studio runs and standalone NetCDF archives, including Python replay,
  use the same output-only Solution Explorer. Inputs stay in the model views.
- The browsed-run list no longer exposes unused piecewise-cost placeholders
  or uncomputed all-zero prices from confirmed HiGHS integer runs. Genuine
  zero results remain queryable. An archive cannot show an output omitted
  during export.
- Older dashboards that request inputs are rejected with the property names;
  saved definitions and current query tabs are preserved.

See [NetCDF results](docs/NETCDF_RESULTS.md). Validation evidence is retained
with the original distribution.
No historical runs, reports, or exports were rewritten. This is a native-only
source release; no PLEXOS integration or new installer is included.

- Quoted the chart canvas font family and added a sans-serif fallback to avoid font warnings.
