"""Calendar schedules and frozen input alignment. No Qt, solver or project mutation."""

from copy import deepcopy
import math

import pandas as pd

from .project import Project


UNITS = ("hour", "day", "week", "month", "year")
MAX_SNAPSHOTS = 100000
MAX_STEPS = 10000


def positive_integer(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive whole number.")
    return value


def timestamp(value):
    result = pd.Timestamp(value)
    if pd.isna(result) or result.tzinfo is not None:
        raise ValueError("Use a valid timezone-naive start date/time (no implicit DST).")
    return result


def advance(start, amount, unit):
    """Return a new boundary; months/years are anchored calendar offsets."""
    positive_integer(amount, "Duration")
    if unit not in UNITS:
        raise ValueError("Choose hour, day, week, month or year.")
    return start + pd.DateOffset(**{unit + "s": amount})


def schedule(spec, sync=False):
    """Return JSON-safe schedule. Sync floors the count, never prorates a step.

    Boundaries use [start,end); calendar boundaries are computed from the original
    anchor (Jan 31 -> Feb 28 -> Mar 31), not repeated month-end drift.
    """
    fields = {"start", "duration", "duration_unit", "snapshot_size", "snapshot_unit",
              "step_count", "step_size", "step_unit"}
    if not isinstance(spec, dict) or not fields <= set(spec) or set(spec) - fields - {"profile_policy"}:
        raise ValueError("Incomplete or unknown horizon settings.")
    if spec.get("profile_policy", "exact") not in {"exact", "repeat_daily"}:
        raise ValueError("Choose exact input coverage or daily profile repetition.")
    start = timestamp(spec["start"])
    end = advance(start, spec["duration"], spec["duration_unit"])
    size = positive_integer(spec["step_size"], "Step size")
    count = positive_integer(spec["step_count"], "Number of steps")
    interval = positive_integer(spec["snapshot_size"], "Snapshot interval")
    # Validate units even when no step fits.
    advance(start, size, spec["step_unit"])
    advance(start, interval, spec["snapshot_unit"])
    if sync:
        count = 0
        while count < MAX_STEPS and advance(start, (count + 1) * size, spec["step_unit"]) <= end:
            count += 1
        if not count:
            raise ValueError("No complete step fits. Reduce the step size.")
        if count == MAX_STEPS and advance(start, (count + 1) * size, spec["step_unit"]) <= end:
            raise ValueError(f"Schedule exceeds the {MAX_STEPS} step safety limit.")
    if count > MAX_STEPS:
        raise ValueError(f"Use at most {MAX_STEPS} steps.")
    stop = advance(start, count * size, spec["step_unit"])
    if stop > end:
        raise ValueError(
            f"Invalid horizon: {count} × {size} {spec['step_unit']} steps end at "
            f"{stop.isoformat()}, beyond {end.isoformat()}. Reduce steps or use Sync Horizon."
        )
    # Build only the requested execution axis; unused upper-bound time is not solved.
    boundaries = [start]
    while boundaries[-1] < stop:
        if len(boundaries) > MAX_SNAPSHOTS:
            raise ValueError(f"Run exceeds the {MAX_SNAPSHOTS} snapshot safety limit.")
        boundaries.append(advance(start, len(boundaries) * interval, spec["snapshot_unit"]))
    if boundaries[-1] != stop:
        raise ValueError("Snapshot interval must exactly divide the requested execution range; no prorating.")
    positions = {t: i for i, t in enumerate(boundaries)}
    steps = []
    for i in range(count):
        first = advance(start, i * size, spec["step_unit"]) if i else start
        last = advance(start, (i + 1) * size, spec["step_unit"])
        if first not in positions or last not in positions:
            raise ValueError("Each optimization step boundary must align with a snapshot boundary.")
        steps.append(dict(number=i + 1, start=first.isoformat(), end=last.isoformat(),
                          first=positions[first], stop=positions[last]))
    hours = [(b - a).total_seconds() / 3600 for a, b in zip(boundaries, boundaries[1:])]
    clean = dict(spec, start=start.isoformat(), step_count=count)
    return dict(version=1, spec=clean, start=start.isoformat(), horizon_end=end.isoformat(),
                execution_end=stop.isoformat(), snapshots=[t.isoformat() for t in boundaries[:-1]],
                hours=hours, steps=steps, unused_hours=(end-stop).total_seconds()/3600,
                timezone="naive; no DST conversion", terminal_policy="free; no look-ahead",
                summary=f"{count} separate optimizations · {len(hours)} snapshots · "
                        f"{sum(hours):g} hours · end {stop.isoformat()} (exclusive) · "
                        f"{(end-stop).total_seconds()/3600:g} hours unused"
                        + (" · input profiles repeat daily" if spec.get("profile_policy") == "repeat_daily" else ""))


def daily_positions(project, target, hours):
    """Map one complete, uniform calendar-day template by time of day.

    No interpolation or time weighting is inferred from the number of values.
    Explicitly opted-in templates may be used on different run dates/years.
    """
    source = pd.DatetimeIndex(project.snapshots)
    if source.empty or source.hasnans or source.tz is not None:
        raise ValueError("Daily repetition needs a complete timezone-naive day of input snapshots.")
    interval = float(project.duration_hours)
    weights = project.advanced_inputs.get("weights", [])
    if weights:
        if len(weights) != len(source):
            raise ValueError("Daily template weights must cover every input snapshot.")
        interval = float(weights[0]["stores"])
        if any(not math.isclose(float(w), interval) for row in weights for w in row.values()):
            raise ValueError("Daily repetition requires uniform elapsed-hour weights, not representative weights.")
    if not math.isfinite(interval) or interval <= 0 or not math.isclose(len(source) * interval, 24):
        raise ValueError("Daily repetition needs exactly one complete 24-hour input day (for example, 24 hourly values).")
    expected = pd.date_range(source[0].normalize(), periods=len(source), freq=pd.Timedelta(hours=interval))
    if not source.equals(expected):
        raise ValueError("Daily input snapshots must be contiguous from midnight with no gaps or duplicate times.")
    if any(not math.isclose(interval, h, abs_tol=1e-9) for h in hours):
        raise ValueError("Daily template interval must match the run snapshot interval; no automatic resampling.")
    positions = (source - source.normalize()).get_indexer(target - target.normalize())
    if (positions < 0).any():
        raise ValueError("Run snapshot times do not align with the daily template's time-of-day intervals.")
    return positions


def aligned_project(project, plan):
    """Return an independent run copy; repeat a daily template only when opted in."""
    result = Project(**deepcopy(project.to_dict()))
    target = pd.DatetimeIndex(plan["snapshots"])
    source = pd.DatetimeIndex(project.snapshots)
    repeat = plan["spec"].get("profile_policy", "exact") == "repeat_daily"
    positions = (
        daily_positions(project, target, plan["hours"])
        if repeat and (project.profiles or project.advanced_inputs.get("weights"))
        else source.get_indexer(target)
    )
    if project.profiles or project.advanced_inputs.get("weights"):
        if (positions < 0).any():
            raise ValueError("Run dates/resolution lack exact profile/weight coverage. "
                             "For one complete input day, enable Repeat daily profiles in Runs; "
                             "otherwise prepare aligned inputs. No implicit filling or date shifting.")
        old_hours = [r["stores"] for r in project.advanced_inputs["weights"]] if project.advanced_inputs.get("weights") else [project.duration_hours] * len(source)
        if any(not math.isclose(old_hours[p], h, abs_tol=1e-9) for p, h in zip(positions, plan["hours"])):
            raise ValueError("Input interval durations differ from the run intervals. Explicit resampling is required.")
        for profile in result.profiles:
            profile["values"] = [profile["values"][p] for p in positions]
    if project.advanced_inputs.get("periods"):
        raise ValueError("Custom run horizons do not support investment periods; use project-axis execution.")
    if project.advanced_inputs.get("weights"):
        for p, hours in zip(positions, plan["hours"]):
            if any(not math.isclose(float(w), hours) for w in project.advanced_inputs["weights"][p].values()):
                raise ValueError("Sequential execution requires chronological elapsed-hour weights, not representative weights.")
    result.snapshots = plan["snapshots"]
    result.duration_hours = plan["hours"][0]
    result.advanced_inputs["weights"] = [
        dict(objective=h, stores=h, generators=h) for h in plan["hours"]
    ]
    validate_sequential(result)
    errors = result.validate()
    if errors:
        raise ValueError("\n".join(errors))
    return result


def validate_sequential(project):
    """Fail closed on semantics not yet verified across independent solves."""
    for record in project.objects:
        kind, name, attrs = record["component"], record["name"], record["attributes"]
        if kind == "GlobalConstraint":
            raise ValueError("Sequential execution does not yet allocate GlobalConstraint budgets between steps.")
        if kind == "Process":
            raise ValueError("Process state transfer is not yet supported in sequential execution.")
        if any(v for k, v in attrs.items() if k.endswith("_extendable")):
            raise ValueError(f"{kind} {name}: sequential execution requires fixed capacities.")
        cyclic = ("cyclic_state_of_charge", "cyclic_state_of_charge_per_period",
                  "state_of_charge_initial_per_period", "e_cyclic", "e_cyclic_per_period",
                  "e_initial_per_period")
        if any(attrs.get(k, False) for k in cyclic):
            raise ValueError(f"{kind} {name}: disable cyclic/per-period storage boundaries for sequential execution.")
        if any(v for k, v in attrs.items() if k.startswith("delay")):
            raise ValueError(f"{kind} {name}: delayed links are not supported across steps.")
        if attrs.get("committable") or any(k.startswith("ramp_limit") for k in attrs):
            hours = [r["stores"] for r in project.advanced_inputs.get("weights", [])]
            if hours and any(not math.isclose(h, hours[0]) for h in hours):
                raise ValueError(f"{kind} {name}: commitment/ramps require uniform snapshot durations in sequential mode.")
    if any(p["attribute"].startswith("delay") for p in project.profiles):
        raise ValueError("Time-dependent link delays are not supported across steps.")
