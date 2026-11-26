"""Read-only, unit-checked analytics for an already executed frozen-run query.

``summarize_query`` returns ``(frame, charts, description)``. The uncapped frame
is long-form: component, group_by, group, period ("" for a single horizon),
property, metric, unit, value, weighting, period_years. Energy adds snapshot_hours
and weighted_hours, and has net_energy/positive_energy/negative_energy metrics
(negative energy retains its sign). It integrates MW with snapshot weights AND
period years, never investment-period objective/discount weights. Directional
parts are calculated before aggregating objects, so cancellation remains visible.

Storage adds samples and has initial/last/min/max/mean metrics in MWh. Initial is
the FIRST SELECTED RESULT, not the configured pre-snapshot initial condition.
Groups are summed synchronously before state statistics; mean is arithmetic,
never duration-weighted. Storage states are never integrated.

Duration adds snapshot, rank, duration_hours, start_hours, cumulative_hours.
Each property/group/period is sorted descending, retaining each sample's own
snapshot weight. These hours describe the representative snapshots within the
period: period_years is explicit metadata, NOT a multiplier for duration curves.
Charts are exact, piecewise-constant steps with per-series numeric ``x_values``
and chart-level ``x_label``. Renderers MUST use x_values, not uniform index
spacing. Only the preview is bounded (30 panels, 1000 points/series, 6 series).

All modes preserve separate property and period identities. Grouping by period
or component sums the selected objects, never different investment periods.
There is no unit conversion, imputation, solve, live-project access or mutation.
"""

from pathlib import Path
import re

import numpy as np
import pandas as pd

from .advanced import checked_advanced
from .results import ResultsRepository
from .workspace import QueryTab


MAX_CHARTS = 30
MAX_POINTS = 1000
MAX_SERIES = 6
_WEIGHTINGS = {"generators", "stores", "objective"}
_METRICS = {
    "energy": ["net_energy", "positive_energy", "negative_energy"],
    "storage": ["initial", "last", "min", "max", "mean"],
}
_BOUNDS = (
    "Preview only: at most 30 panels, 1000 points per series and 6 series per "
    "panel; first entries only, no interpolation. The computed table/CSV is uncapped."
)


def _numeric(values, label):
    """Reject strings, booleans, complex numbers, missing values and infinities."""
    if (
        not pd.api.types.is_numeric_dtype(values)
        or pd.api.types.is_bool_dtype(values)
        or pd.api.types.is_complex_dtype(values)
    ):
        raise ValueError(f"{label} requires complete finite real numeric values.")
    array = values.to_numpy(dtype=float, na_value=np.nan)
    if not np.isfinite(array).all():
        raise ValueError(f"{label} requires complete finite real numeric values; no missing-value filling.")
    return array


def _finite(values, label):
    if not np.isfinite(np.asarray(values, dtype=float)).all():
        raise ValueError(f"{label} produced nonfinite values (including numeric overflow).")


def _bus_unit(project, component, name, attribute):
    """Resolve the selected terminal only; nominal schema MW is not proof of MW."""
    record = project.object(component, name)
    if record is None:
        raise ValueError(f"{component} {name} is absent from the frozen inputs.")
    attrs = record["attributes"]
    declared = attrs.get("unit", "")
    if declared and declared != "MW":
        raise ValueError(f"{component} {name} declares non-MW units: {declared!r}.")
    if component == "Bus":
        return declared or "MW"
    port = re.fullmatch(r"p(\d+)", attribute)
    bus_key = f"bus{port[1]}" if port else ("bus" if "bus" in attrs else "bus0")
    bus = project.object("Bus", attrs.get(bus_key, ""))
    if bus is None:
        raise ValueError(f"{component} {name}.{attribute} needs its frozen {bus_key} identity/units.")
    return bus["attributes"].get("unit", "") or "MW"


def _prepare(tab, repository, mode, group_by, weighting):
    if mode not in {"energy", "duration", "storage"}:
        raise ValueError("Choose energy, duration or storage analytics.")
    if group_by not in {"object", "carrier", "period", "component"}:
        raise ValueError("Group by object, carrier, period or component.")
    if weighting not in _WEIGHTINGS:
        raise ValueError("Choose the explicit generators, stores or objective snapshot weighting.")
    if not isinstance(tab, QueryTab) or not isinstance(repository, ResultsRepository):
        raise ValueError("Execute a query and supply its frozen ResultsRepository.")
    if Path(tab.run_path).resolve() != repository.directory:
        raise ValueError("The active query and frozen repository must belong to the same run.")
    criteria = tab.criteria
    if not isinstance(criteria, dict) or set(criteria) != {"component", "objects", "properties", "start", "end"}:
        raise ValueError("Weighted analytics requires the original Native query; calendar summaries have already aggregated time.")
    component, objects, properties = (criteria[key] for key in ("component", "objects", "properties"))
    category = repository.categories.get(component, {})
    if (
        not objects or not properties or len(set(objects)) != len(objects)
        or len(set(properties)) != len(properties)
        or not set(objects).issubset(category.get("objects", []))
    ):
        raise ValueError("Selected identities must exist uniquely in the frozen query and results.")
    if not tab.temporal:
        raise ValueError("Analytics requires temporal results; static scalars cannot be integrated or repeated.")
    if mode == "storage" and component not in {"Store", "StorageUnit"}:
        raise ValueError("Storage summaries require Store/StorageUnit temporal MWh states.")
    specs = {spec["name"]: spec for spec in tab.specs}
    available = {spec["name"]: spec for spec in category.get("properties", [])}
    if len(specs) != len(tab.specs) or set(specs) != set(properties):
        raise ValueError("Property metadata must match the executed selection.")
    expected_unit = "MWh" if mode == "storage" else "MW"
    for attribute in properties:
        spec = specs[attribute]
        if spec != available.get(attribute):
            raise ValueError("Property kind/units disagree with the frozen results catalogue.")
        if spec["kind"] != "time series" or spec["unit"] != expected_unit:
            raise ValueError(
                f"{attribute}: {mode} requires temporal {expected_unit}, not static values, costs or other units."
            )
        units = {_bus_unit(repository.project, component, name, attribute) for name in objects}
        if units != {"MW"}:
            raise ValueError(f"{attribute}: mixed/non-MW bus units {sorted(units)!r}; no implicit conversion.")

    project = repository.project
    dates = pd.DatetimeIndex(project.snapshots)
    if dates.empty or dates.has_duplicates or dates.hasnans or dates.tz is not None or not dates.is_monotonic_increasing:
        raise ValueError("Frozen snapshots must be complete, unique, ordered and timezone-naive.")
    advanced = checked_advanced(project, project.advanced_inputs)
    first = pd.Timestamp(criteria["start"]) if criteria["start"] else dates[0]
    last = pd.Timestamp(criteria["end"]) if criteria["end"] else dates[-1]
    if pd.isna(first) or pd.isna(last) or first.tzinfo is not None or last.tzinfo is not None or first > last:
        raise ValueError("The executed range must be ordered and timezone-naive.")
    selected = dates[(dates >= first) & (dates <= last)]
    if selected.empty:
        raise ValueError("The executed query has no selected snapshots to summarize.")
    if not isinstance(tab.frame, pd.DataFrame) or tab.frame.columns.has_duplicates:
        raise ValueError("The executed frame must have unique columns.")
    frame = tab.frame.copy(deep=True)
    if not {"snapshot", "object", *properties}.issubset(frame.columns):
        raise ValueError("The executed frame is missing selected time/object/property identities.")
    times = pd.DatetimeIndex(pd.to_datetime(frame["snapshot"], errors="raise"))
    if times.hasnans or times.tz is not None:
        raise ValueError("Result snapshots must be complete and timezone-naive.")
    frame["snapshot"] = times
    expected = pd.MultiIndex.from_product([selected, objects], names=["snapshot", "object"])
    actual = pd.MultiIndex.from_frame(frame[["snapshot", "object"]])
    if actual.has_duplicates or len(actual) != len(expected) or len(expected.difference(actual)):
        raise ValueError("Missing/mismatched snapshot-object identities; no intersection, filling or duplicate summing.")
    # Reordering is safe only AFTER exact identity validation; reindex never fills.
    frame = frame.set_index(["snapshot", "object"]).reindex(expected).reset_index()
    periods = advanced.get("snapshot_periods", [])
    if bool(periods) != ("period" in frame):
        raise ValueError("Result period identities disagree with the frozen inputs.")
    if periods:
        mapping = dict(zip(dates, periods))
        period_values = frame["snapshot"].map(mapping)
        if not frame["period"].equals(period_values.rename("period")):
            raise ValueError("Result period identities disagree with the frozen snapshot-period axis.")
        years = {row["period"]: row["years"] for row in advanced["periods"]}
        frame["period_years"] = frame["period"].map(years)
    else:
        if group_by == "period":
            raise ValueError("Period grouping requires explicit frozen investment periods.")
        frame["period"], frame["period_years"] = "", 1.0
    if advanced.get("weights"):
        hours = pd.Series([row[weighting] for row in advanced["weights"]], index=dates)
    else:
        if isinstance(project.duration_hours, bool) or not np.isfinite(project.duration_hours) or project.duration_hours <= 0:
            raise ValueError("Default snapshot duration must be positive finite hours.")
        hours = pd.Series(float(project.duration_hours), index=dates)
    frame["snapshot_hours"] = frame["snapshot"].map(hours)
    if group_by == "carrier":
        carriers = {}
        for name in objects:
            carrier = project.object(component, name)["attributes"].get("carrier")
            if not isinstance(carrier, str) or not carrier.strip():
                raise ValueError(f"{component} {name} has no explicit frozen carrier identity; no invented grouping.")
            carriers[name] = carrier
        frame["group"] = frame["object"].map(carriers)
    elif group_by == "object":
        frame["group"] = frame["object"]
    elif group_by == "component":
        frame["group"] = component
    else:
        frame["group"] = frame["period"].map(str)
    for attribute in properties:
        frame[attribute] = _numeric(frame[attribute], attribute)
    return frame, component, properties


def _chart(title, unit, kind, labels, series, hint, **extra):
    return dict(
        title=title, unit=unit, kind=kind, options=[kind], labels=labels,
        series=series, hint=f"{hint} {_BOUNDS}", **extra,
    )


def _title(attribute, period):
    return attribute + (f" · period {period}" if period != "" else "")


def _summary_charts(frame, mode):
    charts = []
    for (attribute, period), panel in frame.groupby(["property", "period"], sort=False):
        if len(charts) == MAX_CHARTS:
            break
        unit = panel["unit"].iloc[0]
        if mode == "duration":
            series = []
            # Two endpoints per ranked sample preserve the exact step geometry.
            # Truncating ranks, rather than interpolating, retains paired weights.
            for name, part in panel.groupby("group", sort=False):
                if len(series) == MAX_SERIES:
                    break
                part = part.iloc[:MAX_POINTS // 2]
                x_values = part[["start_hours", "cumulative_hours"]].to_numpy().reshape(-1).tolist()
                values = np.repeat(part["value"].to_numpy(), 2).tolist()
                series.append(dict(name=str(name), values=values, x_values=x_values))
            # Labels are endpoint annotations only, NOT the numeric x coordinates.
            end = max(s["x_values"][-1] for s in series)
            charts.append(_chart(
                f"{_title(attribute, period)} · weighted duration", unit, "line",
                ["0 h", f"{end:g} h"], series,
                "Exact descending steps; numeric x_values MUST control horizontal spacing. "
                "First 500 ranks per selected group; no period-year multiplier.",
                x_label="Cumulative snapshot-weighted hours (no period-year multiplier)",
            ))
        else:
            groups = panel["group"].drop_duplicates().iloc[:MAX_POINTS].tolist()
            series = []
            for metric in _METRICS[mode]:
                values = panel.loc[panel["metric"] == metric].set_index("group").loc[groups, "value"]
                series.append(dict(name=metric, values=values.astype(float).tolist()))
            charts.append(_chart(
                f"{_title(attribute, period)} · {mode}", unit, "bar",
                [str(group) for group in groups], series,
                "Separate property/period panel; no unit mixing. "
                + ("Signed directional energy, including period years." if mode == "energy" else
                   "First/last selected state, extrema and arithmetic mean; no integration."),
            ))
    return charts


def summarize_query(tab, repository, mode, group_by="object", weighting="generators"):
    """Summarize the full executed selection, returning a fresh frame and charts.

    Explicit generators/stores/objective weights are supported. Objective snapshot
    weights are an opt-in accounting-hours convention, NOT physical time or a cost
    calculation; period objective/discount factors are never used. For storage
    states weighting is recorded as ``none`` and does not affect the statistics.
    Unknown modes/units, static properties and incomplete axes raise ValueError.
    """
    source, component, properties = _prepare(tab, repository, mode, group_by, weighting)
    rows = []
    keys = ["period", "group"]
    for attribute in properties:
        for (period, group), part in source.groupby(keys, sort=False):
            base = dict(
                component=component, group_by=group_by, group=group, period=period,
                property=attribute, weighting="none" if mode == "storage" else weighting,
                period_years=float(part["period_years"].iloc[0]),
            )
            # Each snapshot has one common weight, not one duration per object.
            hours = part.drop_duplicates("snapshot")["snapshot_hours"].to_numpy()
            if mode == "energy":
                with np.errstate(over="ignore", invalid="ignore"):
                    weights = part["snapshot_hours"].to_numpy() * base["period_years"]
                    values = part[attribute].to_numpy()
                    totals = (
                        np.sum(values * weights),
                        np.sum(np.maximum(values, 0) * weights),
                        np.sum(np.minimum(values, 0) * weights),
                    )
                    total_hours = float(np.sum(hours))
                    represented_hours = total_hours * base["period_years"]
                _finite([*totals, total_hours, represented_hours], "Energy integration")
                for metric, value in zip(_METRICS[mode], totals):
                    rows.append(dict(
                        **base, metric=metric, unit="MWh", value=float(value),
                        snapshot_hours=total_hours, weighted_hours=represented_hours,
                    ))
                continue
            # State statistics and grouped duration curves aggregate simultaneous
            # samples first; summing independent extrema/ranks would be incorrect.
            samples = part.groupby("snapshot", sort=True)[attribute].sum()
            _finite(samples.to_numpy(), "Synchronous object aggregation")
            if mode == "storage":
                with np.errstate(over="ignore", invalid="ignore"):
                    values = [samples.iloc[0], samples.iloc[-1], samples.min(), samples.max(), samples.mean()]
                _finite(values, "Storage statistics")
                for metric, value in zip(_METRICS[mode], values):
                    rows.append(dict(**base, metric=metric, unit="MWh", value=float(value), samples=len(samples)))
            else:
                # Stable descending order leaves ties in their original time order.
                samples = samples.sort_values(ascending=False, kind="stable")
                paired = part.drop_duplicates("snapshot").set_index("snapshot")["snapshot_hours"]
                durations = paired.loc[samples.index].to_numpy(dtype=float)
                with np.errstate(over="ignore", invalid="ignore"):
                    cumulative = np.cumsum(durations)
                _finite(cumulative, "Cumulative duration")
                starts = np.r_[0.0, cumulative[:-1]]
                for rank, (snapshot, value) in enumerate(samples.items(), 1):
                    rows.append(dict(
                        **base, metric="duration", unit="MW", value=float(value),
                        snapshot=snapshot, rank=rank, duration_hours=float(durations[rank-1]),
                        start_hours=float(starts[rank-1]), cumulative_hours=float(cumulative[rank-1]),
                    ))
    frame = pd.DataFrame(rows)
    description = (
        f"Frozen executed query: {mode}, grouped by {group_by}; separate properties and periods. "
        "Raw property signs are retained: positive/negative mean the property's declared direction, "
        "not universal generation/consumption. Generator/Store/StorageUnit p is normally injection/discharge, "
        "Load p consumption, branch pN withdrawal at that terminal; p_store/p_dispatch are directional "
        "quantities, not net production. Different terminals/properties are never added together. "
    )
    if mode == "energy":
        description += (
            f"MWh = sum(MW × {weighting} snapshot hours × period years). "
            "Positive/negative parts are split per object before grouping; negative totals stay negative. "
            "weighted_hours includes years once, not once per object. No period objective/discount factors or cost reconstruction. "
        )
    elif mode == "duration":
        description += (
            f"Descending power paired with its own {weighting} snapshot hours, within each period; "
            "cumulative_hours excludes period years (shown as metadata). Grouped power is summed "
            "synchronously before ranking. Exact step charts require numeric x_values rendering. "
        )
    else:
        description += (
            "MWh states only: initial means first selected result, then last/min/max/arithmetic mean "
            "of synchronous grouped states. No integration, duration weighting or period-year scaling; weighting=none. "
        )
    if weighting == "objective" and mode != "storage":
        description += "Objective snapshot weights are explicitly selected accounting hours, not a claim of physical duration or cost. "
    return frame, _summary_charts(frame, mode), description + _BOUNDS


def comparison_charts(frame):
    """Preview ``analysis.compare_query`` long frames; delta is right minus left.

    Keep property/unit/period panels separate. Static panels contain left/right/
    delta series. Temporal panels show those three series for at most two objects
    (six series), preserving their common snapshot axes. Inputs remain uncapped
    and unchanged. Missing/duplicate identities, mixed units within a property,
    nonfinite values and inconsistent deltas are rejected rather than repaired.
    """
    columns = {"object", "property", "unit", "left", "right", "delta_right_minus_left"}
    if not isinstance(frame, pd.DataFrame) or frame.empty or frame.columns.has_duplicates or not columns.issubset(frame):
        raise ValueError("Comparison charts require a nonempty compare_query long frame.")
    data = frame.copy(deep=True)
    for column in ["object", "property", "unit"]:
        if not data[column].map(lambda value: isinstance(value, str) and (bool(value.strip()) or column == "unit")).all():
            raise ValueError(f"Comparison {column} identities must be explicit strings.")
    for column in ["left", "right", "delta_right_minus_left"]:
        data[column] = _numeric(data[column], column)
    with np.errstate(over="ignore", invalid="ignore"):
        expected_delta = data["right"].to_numpy() - data["left"].to_numpy()
    _finite(expected_delta, "Right-minus-left comparison")
    if not np.allclose(expected_delta, data["delta_right_minus_left"], rtol=1e-12, atol=1e-12):
        raise ValueError("Comparison delta must be right minus left.")
    temporal = "snapshot" in data
    if "period" in data:
        if not temporal or not data["period"].map(lambda value: isinstance(value, (int, np.integer)) and not isinstance(value, bool) and value > 0).all():
            raise ValueError("Comparison periods require explicit positive integer temporal identities.")
    else:
        data["period"] = ""
    keys = ["period", "object"]
    if temporal:
        times = pd.DatetimeIndex(pd.to_datetime(data["snapshot"], errors="raise"))
        if times.hasnans or times.tz is not None:
            raise ValueError("Comparison snapshots must be complete and timezone-naive.")
        data["snapshot"] = times
        keys.insert(1, "snapshot")
        if (data.groupby("snapshot")["period"].nunique() > 1).any():
            raise ValueError("A comparison snapshot cannot belong to mismatched periods.")
    reference = None
    for attribute, part in data.groupby("property", sort=False):
        if part["unit"].nunique(dropna=False) != 1:
            raise ValueError(f"{attribute}: mixed units within a comparison property.")
        identities = pd.MultiIndex.from_frame(part[keys])
        if identities.has_duplicates:
            raise ValueError("Duplicate comparison identities; no implicit aggregation.")
        if reference is not None and (len(reference) != len(identities) or len(reference.difference(identities))):
            raise ValueError("Comparison properties have mismatched period/object/time axes.")
        reference = identities

    charts = []
    measures = ["left", "right", "delta_right_minus_left"]
    selected_objects = data["object"].drop_duplicates().tolist()
    for (attribute, period), panel in data.groupby(["property", "period"], sort=False):
        unit = panel["unit"].iloc[0]
        series = []
        if temporal:
            times = pd.DatetimeIndex(panel["snapshot"].drop_duplicates()).sort_values()
            # A selected object cannot silently disappear for a whole period.
            objects = selected_objects
            expected = pd.MultiIndex.from_product([times, objects], names=["snapshot", "object"])
            actual = pd.MultiIndex.from_frame(panel[["snapshot", "object"]])
            if len(actual) != len(expected) or len(expected.difference(actual)):
                raise ValueError("Missing comparison samples; no filling or implicit intersection.")
            labels = times[:MAX_POINTS].astype(str).tolist()
            for name in objects[:MAX_SERIES // len(measures)]:
                part = panel.loc[panel["object"] == name].set_index("snapshot").loc[times[:MAX_POINTS]]
                for measure in measures:
                    series.append(dict(name=f"{name} · {measure}", values=part[measure].tolist()))
        else:
            part = panel.iloc[:MAX_POINTS]
            labels = part["object"].tolist()
            series = [dict(name=measure, values=part[measure].tolist()) for measure in measures]
        # Validate ALL panels above, even ones omitted from the bounded preview.
        if len(charts) < MAX_CHARTS:
            charts.append(_chart(
                f"{_title(attribute, period)} · comparison (right − left)", unit,
                "line" if temporal else "bar", labels, series,
                "Left/right and signed right-minus-left delta; no unit conversion or causal attribution.",
            ))
    return charts
