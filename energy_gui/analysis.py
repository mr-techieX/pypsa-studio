"""Portable saved analysis and explicit compatible-run comparisons (read only)."""

from copy import deepcopy
import json
from pathlib import Path
import uuid

import numpy as np
import pandas as pd

from .advanced import snapshot_weights
from .diagnostics import run_metadata
from .run_layout import metadata_path
from .results import ResultsRepository, query_charts
from .result_properties import require_results


def repository_for(project, directory):
    directory = Path(directory).resolve()
    meta = run_metadata(directory)
    if meta["status"] != "succeeded" or meta["project_id"] != project.project_id:
        raise ValueError("Analysis requires a successful run from this project.")
    repository = ResultsRepository(directory, json.loads(metadata_path(directory, "catalog.json").read_text(encoding="utf-8")))
    if repository.project.project_id != project.project_id:
        raise ValueError("Frozen inputs disagree with run identity.")
    return repository, meta


def run_path(project_path, folder):
    if not project_path or not isinstance(folder, str) or not folder or Path(folder).name != folder or folder in {".", ".."} or any(c in folder for c in "/\\:"):
        raise ValueError("Use a portable run folder name under the saved project's runs directory.")
    root = (Path(project_path).resolve().parent / "runs").resolve()
    path = (root / folder).resolve()
    if path.parent != root:
        raise ValueError("Saved analysis cannot escape the runs directory.")
    return path


def capture_analysis(project_path, workspace, title):
    if not title.strip() or len(title) > 150 or not workspace.active or not project_path:
        raise ValueError("Save the project, execute a query, and provide a title (1–150 characters).")
    cards = []
    for tab in workspace.tabs:
        source = Path(tab.run_path).resolve()
        if run_path(project_path, source.name) != source:
            raise ValueError("Copy external run folders under this project's runs directory before saving analysis.")
        cards.append(dict(run=source.name, criteria=deepcopy(tab.criteria), chart_types=deepcopy(tab.chart_types),
                          pinned=tab.pinned, view=tab.view, listing=tab.listing,
                          table_form=tab.table_form, chart_range=list(tab.chart_range),
                          sort_column=tab.sort_column, sort_descending=tab.sort_descending))
    if len(cards) > 50:
        raise ValueError("A saved dashboard supports at most 50 query cards.")
    return dict(id=uuid.uuid4().hex, title=title.strip(), cards=cards,
                active=next(i for i, tab in enumerate(workspace.tabs) if tab.id == workspace.active_id))


def prepare_analysis(project, project_path, saved):
    if not isinstance(saved, dict) or not isinstance(saved.get("cards"), list) or not 1 <= len(saved["cards"]) <= 50:
        raise ValueError("Malformed saved dashboard; expected 1–50 cards.")
    active = saved.get("active", 0)
    if type(active) is not int or not 0 <= active < len(saved["cards"]):
        raise ValueError("Invalid active saved card.")
    prepared = []
    for card in saved["cards"]:
        if not isinstance(card, dict) or type(card.get("pinned", False)) is not bool or type(card.get("view", 0)) is not int:
            raise ValueError("Malformed saved card/pin/view state.")
        repo, meta = repository_for(project, run_path(project_path, card["run"]))
        criteria = card["criteria"]
        if not {"component", "objects", "properties", "start", "end"} <= set(criteria) or set(criteria) - {"component", "objects", "properties", "start", "end", "aggregation"}:
            raise ValueError("Malformed saved query criteria.")
        styles = card.get("chart_types", {})
        if not isinstance(styles, dict) or not set(styles).issubset(criteria["properties"]):
            raise ValueError("Saved chart styles must belong to selected properties.")
        frame, specs, temporal = repo.query(**criteria)
        from .temporal import listing
        presented = listing(frame, specs, temporal, card.get("listing", "snapshot"), card.get("table_form", "wide"))
        if (not isinstance(card.get("sort_column", ""), str) or type(card.get("sort_descending", False)) is not bool
                or (card.get("sort_column") and card["sort_column"] not in presented)):
            raise ValueError("Invalid saved table sort column/direction.")
        bounds = card.get("chart_range", [0, -1])
        count = frame["snapshot"].nunique() if temporal else 0
        if (not isinstance(bounds, list) or len(bounds) != 2 or any(type(v) is not int for v in bounds)
                or bounds[0] < 0 or bounds[1] < -1 or (bounds[1] != -1 and not 0 <= bounds[0] <= bounds[1] < count)
                or (count and bounds[0] >= count)):
            raise ValueError("Invalid saved chart timeline range.")
        query_charts(frame, specs, temporal, card.get("chart_types", {}))
        if card.get("view", 0) not in {0, 1}:
            raise ValueError("Saved view must be Data or Charts.")
        prepared.append((card, repo, meta, frame, specs, temporal))
    if sum(not card[0].get("pinned", False) for card in prepared) > 1:
        raise ValueError("A saved dashboard may have at most one unpinned preview.")
    return prepared, active


def compatible(left, right, left_meta, right_meta):
    if left.project_id != right.project_id or left.currency != right.currency:
        raise ValueError("Compare runs of the same project and currency; no implicit conversion.")
    if left.snapshots != right.snapshots or left.advanced_inputs.get("periods", []) != right.advanced_inputs.get("periods", []) or left.advanced_inputs.get("snapshot_periods", []) != right.advanced_inputs.get("snapshot_periods", []):
        raise ValueError("Run snapshot/period axes and period weights must match exactly.")
    if not snapshot_weights(left).equals(snapshot_weights(right)):
        raise ValueError("Run objective/storage/generator weights differ; comparison is refused.")
    if left_meta.get("formulation") != right_meta.get("formulation"):
        raise ValueError("Run formulations differ.")


def compare_query(project, left_path, right_path, criteria):
    require_results(criteria["component"], criteria["properties"])
    left, lm = repository_for(project, left_path)
    right, rm = repository_for(project, right_path)
    compatible(left.project, right.project, lm, rm)
    def unit_signature(project, component, name):
        record = project.object(component, name)
        if not record:
            raise ValueError("A selected object is absent from one frozen model; no implicit intersection.")
        attrs = record["attributes"]
        signature = {"unit": attrs.get("unit", "") or ("MW" if component == "Bus" else "")}
        for key, bus in attrs.items():
            if key == "bus" or (key.startswith("bus") and key[3:].isdigit()):
                record = project.object("Bus", bus)
                if record:
                    signature[key] = record["attributes"].get("unit", "") or "MW"
        return signature
    for name in criteria["objects"]:
        a_units = unit_signature(left.project, criteria["component"], name)
        b_units = unit_signature(right.project, criteria["component"], name)
        if a_units != b_units:
            raise ValueError("Selected objects' declared bus/object units differ between runs.")
    a, sa, ta = left.query(**criteria)
    b, sb, tb = right.query(**criteria)
    if sa != sb or ta != tb:
        raise ValueError("Property units/kinds differ between runs.")
    keys = ["snapshot", "object"] if ta else ["object"]
    if ta and "bucket_end" in a:
        keys += ["bucket_end", "coverage_hours", "bucket_hours", "partial"]
    if ta and "period" in a:
        keys.insert(0,"period")
    if not a[keys].equals(b[keys]):
        raise ValueError("Selected object/time identities differ; no implicit intersection.")
    rows = []
    for spec in sa:
        attr = spec["name"]
        x, y = pd.to_numeric(a[attr], errors="raise"), pd.to_numeric(b[attr], errors="raise")
        if not np.isfinite(x).all() or not np.isfinite(y).all():
            raise ValueError("Comparison requires complete finite numeric properties.")
        part = a[keys].copy()
        part["property"], part["unit"] = attr, spec["unit"]
        part["left"], part["right"], part["delta_right_minus_left"] = x, y, y-x
        rows.append(part)
    details = dict(left=Path(left_path).name, right=Path(right_path).name, currency=left.project.currency,
                   objective_left=lm.get("objective"), objective_right=rm.get("objective"),
                    left_metrics=run_metrics(left, lm), right_metrics=run_metrics(right, rm),
                    query_criteria=deepcopy(criteria),
                   note="Right minus left. Same selected identities/axes/weights/units; changed unselected objects may affect these results. Not causal attribution or AC/security validation.")
    return pd.concat(rows, ignore_index=True), details


def run_metrics(repo, meta):
    project = repo.project
    result = {"objective": meta.get("objective"), "currency": project.currency}
    category = repo.categories.get("Generator", {})
    names = category.get("objects", [])
    if not names or "p" not in category.get("series_files", {}):
        return result
    frame, _, _ = repo.query("Generator", names, ["p"])
    wide = frame.pivot(index="snapshot", columns="object", values="p").reindex(pd.DatetimeIndex(project.snapshots))
    mw = all((project.object("Bus", project.object("Generator", name)["attributes"]["bus"])["attributes"].get("unit", "") or "MW") == "MW" for name in names)
    finite = np.isfinite(wide.to_numpy()).all()
    weights = snapshot_weights(project)["generators"].to_numpy()
    if project.advanced_inputs.get("periods"):
        years = {p["period"]: p["years"] for p in project.advanced_inputs["periods"]}
        weights = weights * np.array([years[p] for p in project.advanced_inputs["snapshot_periods"]])
    result["weighted_generation_MWh"] = float((wide.sum(axis=1, skipna=False).to_numpy() * weights).sum()) if mw and finite else None
    carriers = {r["name"]: r["attributes"] for r in project.objects if r["component"] == "Carrier"}
    emissions, capacity = 0.0, 0.0
    for name in names:
        record = project.object("Generator", name)
        attrs = record["attributes"]
        # Use exported optimised capacities, not today's inputs.
        capacity += float(repo.query("Generator", [name], ["p_nom_opt"])[0]["p_nom_opt"].iloc[0]) if "p_nom_opt" in {s["name"] for s in category["properties"]} else float(attrs.get("p_nom", 0))
        carrier = carriers.get(attrs.get("carrier", ""), {})
        if "co2_emissions" not in carrier:
            emissions = None
            continue
        if emissions is not None:
            eff = next((p["values"] for p in project.profiles if (p["component"], p["name"], p["attribute"]) == ("Generator", name, "efficiency")), [attrs.get("efficiency", 1)] * len(weights))
            if min(eff) <= 0:
                emissions = None
            else:
                emissions += float((wide[name].to_numpy() / np.array(eff) * weights).sum()) * float(carrier["co2_emissions"])
    result.update(generator_capacity_MW=capacity if mw else None, weighted_operational_CO2_t=emissions if mw and finite else None)
    return result
