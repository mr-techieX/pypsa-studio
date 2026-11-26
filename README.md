# PyPSA Studio v1.3.1

Local PySide6/Qt Quick + PyPSA 1.4.0 + HiGHS desktop build, based on the
v1.2.0 native source release. **PLEXOS interoperability is
excluded from this build.** RawBuild development remains separate.

## Start from this repository

From this directory, use an existing environment with the dependencies in
`requirements.txt`. For the checkout inside the PyPSA workspace:

```powershell
& '..\EnEx\Scripts\python.exe' -m energy_gui
```

The included `.cmd` and `.ps1` launchers retain the original release-folder
layout assumption. For an independent checkout, use an environment that
satisfies `requirements.txt` and launch from the repository root:

```powershell
# In this build's directory, using that environment's Python:
python -m energy_gui
```

The v1.3.1 application name isolates theme settings and applied-state recovery
from RawBuild/v1.0.0. Curated F1 guides are bundled. Projects are saved where you
choose; keep the matching `runs/` folder when moving a saved model.

## Included

- New run folders organize JSON under `metadata/` and LP/MPS exports under
  `formulation/`. [Run file guide](docs/RUN_FILES.md). Older runs are unchanged.

- The Solution Explorer lists only solved outputs, whether you Browse to a
  Studio run or open a standalone `.nc`. It hides unused CSV placeholders but
  preserves genuine zero results. Older dashboards that query model inputs
  must be rebuilt with output properties; the saved definitions are unchanged.

- Drop a standalone PyPSA `.nc` or choose **File → Open results (.nc)…** to
  query a read-only archive without companion files or changing your model.
  See [Standalone NetCDF results](docs/NETCDF_RESULTS.md).
- Newly exported sequential `run.py` publishes one shareable `solution.nc`
  in a new `replay-*` folder after all steps succeed. Regenerate older
  exports to get this behavior.

- **Save as Python run** in Runs: export one standalone model script or a
  sequential runner plus one model script per step. See
  [Python replay](docs/PYTHON_REPLAY.md).

- All retained native modeling, component/schema editors, spreadsheet and profile
  workflows, demo models, scenarios/batches, model Undo/Redo, recovery/backups,
  saved studies/comparisons, analytics and native mathematical/report exports.
- Atlas Light/Dark/System appearance and vector application/header icon.
- H01–H10: configured sequential solves and state handoffs, explicit daily-profile
  repetition, calendar reports, result listing/sorting/filtering, temporal queries
  and chart timeline zoom/pan.
- Expandable network playground, scrollbars, edge dragging, cursor-centered zoom,
  view-only navigation/filtering and saved-layout compatibility.
- Guarded native `.sqlite` file drag/drop, including safe URL handling and
  already-open drop no-op; explicit File → Open still reloads through guards.
- UI responsiveness correction: shared lightweight state; inert metadata does not
  enter hot UI/history/spreadsheet copying paths.
- Ctrl+N / Ctrl+O / Ctrl+S / model Ctrl+Z / Ctrl+Y or Ctrl+Shift+Z.
  Editable text retains local Undo/Redo; busy/modal/draft protections apply.

See `RELEASE_NOTES.md` and the focused guides in `docs/`.

## Excluded / compatibility

There is **no PLEXOS XML import, export, inspection or conversion-report command**.
XML drops/open requests are rejected without replacing the current project.
No PLEXOS converter/parser modules, XML seed, profile sidecars or sample source
models are included. Native profile CSV import and LP/MPS/report exports remain.

Previously saved native SQLite models can still open; optional provenance is
preserved as opaque metadata, not executed or offered as interoperability.
Opening a SQLite does not certify its electrical validity or fix missing carriers.
Use Validate and review assumptions before solving.

No user projects, saved runs, virtual environment or old experimental `.deb` are
bundled. The Linux package recipe is retained but has not been built/validated
for v1.3.1. This is not AC feasibility, engineering certification, a PLEXOS
replacement or cross-solver equivalence certification.

## Validation

This checkout was seeded from the verified v1.3.1 source package. Detailed
validation logs and manifests are retained with the original distribution,
not in this source checkout.

## License

Original PyPSA Studio material is licensed under the [MIT License](LICENSE).
The bundled PGLib demo data remains under CC BY 4.0. See
[third-party notices](THIRD_PARTY_NOTICES.md) for attribution and scope.
