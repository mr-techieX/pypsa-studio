"""Preselected post-solve calendar CSV reports using the interactive query engine."""

import json
from html import escape

from .results import ResultsRepository
from .run_layout import metadata_path
from .temporal import RESOLUTIONS, chronological_hours, rule, interval_map, options


def validate_reports(project, resolutions):
    if not isinstance(resolutions, list) or len(set(resolutions)) != len(resolutions) or any(r not in RESOLUTIONS for r in resolutions):
        raise ValueError("Choose unique Native/Hourly/Daily/Weekly/Monthly/Yearly reporting resolutions.")
    for resolution in resolutions:
        if resolution != "native":
            hours = chronological_hours(project)
            interval_map(project, hours.index, options(dict(resolution=resolution)))
    return list(resolutions)


def generate_reports(directory, config):
    """Create derived outputs once on a complete solution, never inside each step.

    Unsupported/unavailable quantities are catalogued as skipped, not guessed.
    Neither the source tables nor missing observations are repaired/zero-filled.
    """
    from .engine import write_json
    selected = config.get("report_resolutions", [])
    if not selected:
        return
    # Preserve post-run report contents; the output-only rule applies to the
    # interactive Solution Explorer, not to the existing reports pipeline.
    repository = ResultsRepository(directory, json.loads(metadata_path(directory, "catalog.json").read_text(encoding="utf-8")),
                                   output_only=False)
    validate_reports(repository.project, selected)
    root = directory / "reports"
    root.mkdir()
    entries, skipped = [], []
    for resolution in selected:
        if resolution == "native":
            entries.append(dict(resolution=resolution, source="../tables", note="Original native result tables, unchanged."))
            continue
        dest = root / resolution
        dest.mkdir()
        for category in repository.describe():
            component, names = category["name"], category["objects"]
            supported, power = [], []
            for spec in category["properties"]:
                if spec["kind"] != "time series":
                    continue
                try:
                    family, _, _ = rule(component, spec)
                    supported.append(spec["name"])
                    if family == "power":
                        power.append(spec["name"])
                except ValueError as error:
                    skipped.append(dict(component=component, property=spec["name"], reason=str(error)))
            for metric, properties in [("auto", supported), ("energy", power)]:
                if not properties or not names:
                    continue
                # Aggregate one property at a time so endpoint-state constraints
                # do not prevent interval-overlap power integration.
                for attribute in properties:
                    settings = options(dict(resolution=resolution, metric=metric))
                    try:
                        frame, specs, _ = repository.query(component, names, [attribute], aggregation=settings)
                    except ValueError as error:
                        skipped.append(dict(component=component, property=attribute, resolution=resolution,
                                            metric=metric, reason=str(error)))
                        continue
                    filename = f"{component}__{attribute}__{metric}.csv"
                    frame.to_csv(dest / filename, index=False)
                    entries.append(dict(resolution=resolution, file=f"{resolution}/{filename}",
                                        component=component, criteria=settings, specs=specs, rows=len(frame)))
    manifest = dict(version=1, selected=selected, entries=entries, skipped=skipped,
                    note="Physical-hour calendar summaries, Monday weeks. Partial buckets labelled. Native facts are retained. No interpolation, imputation, implicit unit conversion or period-year weighting.")
    manifest_path = metadata_path(directory, "manifest.json") if (directory / "metadata").is_dir() else root / "manifest.json"
    write_json(manifest_path, manifest)
    links = "".join(f'<li><a href="{escape(e["file"], quote=True)}">{escape(e["file"])}</a> ({e["rows"]} rows)</li>' for e in entries if "file" in e)
    (root / "index.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>PyPSA calendar reports</title>"
        "<h1>Calendar reports</h1><p>" + escape(manifest["note"]) + "</p><ul>" + links +
        "</ul><h2>Skipped quantities / limitations</h2><pre>" +
        escape(json.dumps(skipped, indent=2)) + "</pre>", encoding="utf-8")
