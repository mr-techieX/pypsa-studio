"""Versioned, physical-time calendar aggregation of frozen results (no mutation)."""

from copy import deepcopy
import math
import re

import numpy as np
import pandas as pd

from .advanced import snapshot_weights


RESOLUTIONS = ("native", "hourly", "daily", "weekly", "monthly", "yearly")
METRICS = ("auto", "mean", "energy", "end", "min", "max", "total", "operating_hours", "fraction")
DEFAULT = dict(version=1, resolution="native", metric="auto", week_start="Monday", group_by="object")
POWER = {"p", "p_set", "p_dispatch", "p_store", "inflow", "spill", "p_dispatch_set", "p_store_set"}
INTENSIVE = {"p_min_pu", "p_max_pu", "s_max_pu", "e_min_pu", "e_max_pu", "efficiency",
             "efficiency_store", "efficiency_dispatch", "standing_loss", "marginal_cost",
             "marginal_cost_storage", "spill_cost", "marginal_price", "v_mag_pu", "v_ang"}


def options(value=None):
    if value is None:
        return dict(DEFAULT)
    if not isinstance(value, dict) or set(value) - set(DEFAULT):
        raise ValueError("Invalid temporal query options.")
    result = {**DEFAULT, **value}
    if (type(result["version"]) is not int or result["version"] != 1
            or result["resolution"] not in RESOLUTIONS or result["metric"] not in METRICS
            or result["week_start"] not in {"Monday", "Sunday"}
            or result["group_by"] not in {"object", "carrier", "component"}):
        raise ValueError("Choose a supported resolution, metric, week anchor and object grouping.")
    if result["resolution"] == "native" and (result["metric"] != "auto" or result["group_by"] != "object"):
        raise ValueError("Native results use Auto / object grouping; choose a calendar resolution for statistics.")
    return result


def rule(component, spec, requested="auto"):
    """Explicit quantity semantics; unknown properties have no guessed reducer."""
    attr, unit = spec["name"], spec["unit"]
    if spec["kind"] != "time series":
        raise ValueError(f"{attr}: static values are not temporal aggregates; query them separately.")
    if (attr in POWER or re.fullmatch(r"p\d+", attr)) and unit == "MW":
        family, default, allowed = "power", "mean", {"mean", "energy", "min", "max", "end"}
    elif (component, attr) in {("StorageUnit", "state_of_charge"), ("Store", "e")}:
        family, default, allowed = "state", "end", {"end", "min", "max", "mean"}
    elif attr == "status":
        family, default, allowed = "status", "fraction", {"fraction", "operating_hours", "end", "min", "max"}
    elif attr in {"start_up", "shut_down"}:
        family, default, allowed = "event", "total", {"total"}
    elif attr in INTENSIVE or attr.startswith("efficiency"):
        family, default, allowed = "intensive", "mean", {"mean", "min", "max", "end"}
    else:
        raise ValueError(f"{attr}: no verified calendar aggregation rule; use Native.")
    metric = default if requested == "auto" else requested
    if metric not in allowed:
        raise ValueError(f"{attr}: {metric} is invalid for {family}; choose {', '.join(sorted(allowed))}.")
    return family, metric, "MWh" if metric == "energy" else "hours" if metric == "operating_hours" else "per unit" if metric == "fraction" else "count" if family == "event" else unit


def bucket(t, resolution, week_start="Monday"):
    if resolution == "hourly":
        first = t.floor("h")
        return first, first + pd.Timedelta(hours=1)
    if resolution == "daily":
        first = t.normalize()
        return first, first + pd.Timedelta(days=1)
    if resolution == "weekly":
        first = t.normalize() - pd.Timedelta(days=(t.weekday() - (0 if week_start == "Monday" else 6)) % 7)
        return first, first + pd.Timedelta(days=7)
    first = t.to_period("M" if resolution == "monthly" else "Y").start_time
    return first, first + pd.DateOffset(**{"months" if resolution == "monthly" else "years": 1})


def chronological_hours(project):
    """Return elapsed hours only when weights/axis describe chronological time."""
    times = pd.DatetimeIndex(project.snapshots)
    if (times.empty or times.tz is not None or times.hasnans or times.has_duplicates
            or not times.is_monotonic_increasing or project.advanced_inputs.get("periods")):
        raise ValueError("Calendar aggregation requires a chronological, timezone-naive, single-period axis.")
    weights = snapshot_weights(project).to_numpy(dtype=float)
    if not np.isfinite(weights).all() or (weights <= 0).any() or not np.allclose(weights, weights[:, :1], rtol=0, atol=1e-9):
        raise ValueError("Calendar aggregation needs physical elapsed-hour weights, not representative/discount weights.")
    hours = snapshot_weights(project)["stores"].to_numpy(dtype=float)
    if len(times) > 1 and not np.allclose(np.diff(times.as_unit("ns").asi8) / 3.6e12, hours[:-1], rtol=0, atol=1e-8):
        raise ValueError("Snapshot durations do not form contiguous chronological coverage; use Native/weighted analytics.")
    return pd.Series(hours, index=times)


def available_resolutions(project):
    try:
        hours = chronological_hours(project)
    except ValueError:
        return ["native"]
    result = ["native"]
    minima = dict(hourly=1, daily=24, weekly=168, monthly=672, yearly=8760)
    for resolution, minimum in minima.items():
        if hours.max() <= minimum + 1e-9 or all(
            h <= (bucket(t, resolution)[1]-bucket(t, resolution)[0]).total_seconds()/3600 + 1e-9
            for t, h in hours.items()
        ):
            result.append(resolution)
    return result


def interval_map(project, dates, settings):
    all_hours = chronological_hours(project)
    rows = []
    for index, t in enumerate(dates):
        hours = float(all_hours.loc[t])
        end = t + pd.Timedelta(hours=hours)
        cursor = t
        while cursor < end:
            first, last = bucket(cursor, settings["resolution"], settings["week_start"])
            if hours > (last-first).total_seconds()/3600 + 1e-9:
                raise ValueError("Requested resolution is finer than a native interval; no disaggregation/interpolation.")
            stop = min(end, last)
            rows.append((index, first, last, (stop-cursor).total_seconds()/3600, end <= last and cursor == t))
            cursor = stop
    return pd.DataFrame(rows, columns=["sample", "snapshot", "bucket_end", "overlap", "whole"])


def aggregate(project, component, frame, specs, settings):
    """Return (wide facts, enriched property specs). Interval means use hours.

    Power is piecewise constant within a native interval. States are endpoint
    observations: cross-boundary interpolation and summing states are prohibited.
    """
    settings = options(settings)
    if settings["resolution"] == "native":
        return frame.copy(deep=True), deepcopy(specs)
    if frame.empty or "snapshot" not in frame:
        raise ValueError("Select a nonempty temporal query to aggregate; static properties have no time resolution.")
    rules = {s["name"]: rule(component, s, settings["metric"]) for s in specs}
    properties = list(rules)
    data = frame[["snapshot", "object", *properties]].copy()
    if data.duplicated(["snapshot", "object"]).any():
        raise ValueError("Duplicate snapshot/object facts cannot be aggregated.")
    for prop in properties:
        data[prop] = pd.to_numeric(data[prop], errors="raise")
        if not np.isfinite(data[prop].to_numpy()).all():
            raise ValueError(f"{prop}: incomplete/nonfinite results cannot be aggregated; no filling.")
        if rules[prop][0] == "power":
            from .analytics import _bus_unit
            if any(_bus_unit(project, component, name, prop) != "MW" for name in data["object"].unique()):
                raise ValueError(f"{prop}: declared object/bus units are not MW; no implicit conversion.")
    dates = pd.DatetimeIndex(sorted(data["snapshot"].unique()))
    names = data["object"].unique().tolist()
    if len(data) != len(dates)*len(names):
        raise ValueError("Missing snapshot/object facts; no implicit intersection or summing.")
    grouping = settings["group_by"]
    if grouping != "object":
        if any(r[0] not in {"power", "state", "event"} for r in rules.values()):
            raise ValueError("Object grouping supports additive power, energy states and event counts only.")
        identities = {}
        for name in names:
            carrier = project.object(component, name)["attributes"].get("carrier", "")
            if grouping == "carrier" and not carrier:
                raise ValueError(f"{name}: no explicit frozen carrier for grouping.")
            identities[name] = carrier if grouping == "carrier" else component
        data["object"] = data["object"].map(identities)
        # Sum synchronous objects BEFORE calculating temporal extrema/statistics.
        data = data.groupby(["snapshot", "object"], sort=False)[properties].sum().reset_index()
    mapping = interval_map(project, dates, settings)
    if not mapping["whole"].all() and any(r[0] in {"state", "event"} for r in rules.values()):
        raise ValueError("State/event intervals cross calendar boundaries; no endpoint interpolation or event splitting.")
    lookup = {t: i for i, t in enumerate(dates)}
    data["sample"] = data["snapshot"].map(lookup)
    pieces = data.drop(columns="snapshot").merge(mapping, on="sample", validate="many_to_many")
    rows = []
    for (time, name), values in pieces.groupby(["snapshot", "object"], sort=True):
        weights = values["overlap"].to_numpy()
        coverage = math.fsum(weights)
        last = values["bucket_end"].iloc[0]
        capacity = (last-time).total_seconds()/3600
        row = dict(snapshot=time, bucket_end=last, object=name, coverage_hours=coverage,
                   bucket_hours=capacity, partial=not math.isclose(coverage, capacity, abs_tol=1e-8))
        for prop, (family, metric, _) in rules.items():
            xs = values[prop].to_numpy(dtype=float)
            row[prop] = (
                float(np.dot(xs, weights)) if metric in {"energy", "operating_hours"} else
                float(np.dot(xs, weights)/coverage) if metric in {"mean", "fraction"} else
                float(xs[-1]) if metric == "end" else
                float(xs.min()) if metric == "min" else
                float(xs.max()) if metric == "max" else float(xs.sum())
            )
            if not math.isfinite(row[prop]):
                raise ValueError(f"{prop}: nonfinite aggregate.")
        rows.append(row)
    enriched = [{**s, "unit": rules[s["name"]][2], "metric": rules[s["name"]][1],
                 "quantity": rules[s["name"]][0], "weighting": "physical elapsed hours; no period-year multiplier"}
                for s in specs]
    return pd.DataFrame(rows), enriched


def listing(frame, specs, temporal, order="snapshot", form="wide"):
    """Pure presentation: reorder facts, never sum or modify the query."""
    if order not in {"snapshot", "object", "property"} or form not in {"wide", "long"}:
        raise ValueError("Choose snapshot/object/property listing and wide/long format.")
    result = frame.copy()
    props = [s["name"] for s in specs]
    if form == "long" or order == "property":
        ids = [c for c in result if c not in props]
        result = result.melt(id_vars=ids, value_vars=props, var_name="property", value_name="value")
        result["unit"] = result["property"].map({s["name"]: s["unit"] for s in specs})
        result["kind"] = result["property"].map({s["name"]: s.get("kind", "") for s in specs})
        # Static properties appear once per object even in a mixed native query.
        static = result["kind"] == "static"
        static_rows = result.loc[static].drop_duplicates(["object", "property"]).copy()
        for col in ["snapshot", "period"]:
            if col in static_rows:
                static_rows[col] = pd.NaT if col == "snapshot" else ""
        result = pd.concat([result.loc[~static], static_rows], ignore_index=True)
    elif temporal and any(s.get("kind") == "static" for s in specs):
        static = [s["name"] for s in specs if s.get("kind") == "static"]
        facts = result.drop(columns=static).copy()
        facts["row_kind"] = "temporal"
        scalars = result[["object", *static]].drop_duplicates("object").copy()
        scalars["row_kind"] = "static"
        result = pd.concat([facts, scalars], ignore_index=True)
    keys = (["property", "object", "snapshot"] if order == "property" else
            ["object", "snapshot"] if order == "object" else ["snapshot", "object"])
    keys = [c for c in keys if c in result]
    if keys:
        result = result.sort_values(keys, kind="stable", na_position="last")
    return result[[*keys, *[c for c in result if c not in keys]]].reset_index(drop=True)
