"""Explicit CSV column mapping; timestamps are aligned, never positionally guessed."""

import math
from pathlib import Path

import pandas as pd

from .schema import attribute_spec


def preview_csv(path):
    frame = pd.read_csv(path, nrows=8)
    return {"columns": frame.columns.tolist(), "preview": frame.fillna("").astype(str).to_string(index=False)}


def import_profile(project, path, component, name, attribute, timestamp_column, value_column):
    spec = attribute_spec(component, attribute)
    if not spec["input"] or not spec["varying"]:
        raise ValueError("Select a time-varying input, not an output or static attribute.")
    if project.object(component, name) is None:
        raise ValueError("Create the target component first.")
    frame = pd.read_csv(path)
    if timestamp_column == value_column:
        raise ValueError("Timestamp and value columns must differ.")
    timestamps = pd.DatetimeIndex(pd.to_datetime(frame[timestamp_column], errors="raise"))
    target = pd.DatetimeIndex(project.snapshots)
    if timestamps.tz is not None or timestamps.hasnans or timestamps.has_duplicates:
        raise ValueError("CSV timestamps must be timezone-naive, nonempty, and unique.")
    if len(timestamps) != len(target) or set(timestamps) != set(target):
        raise ValueError("CSV timestamps must exactly match project snapshots. No implicit resampling.")
    series = pd.Series(pd.to_numeric(frame[value_column], errors="raise").to_numpy(), index=timestamps).reindex(target)
    values = [float(v) for v in series]
    if any(not math.isfinite(v) for v in values):
        raise ValueError("Profile values must be finite numbers without blanks.")
    profile = {
        "component": component, "name": name, "attribute": attribute,
        "values": values, "source": Path(path).name, "unit": spec["unit"],
    }
    project.profiles = [p for p in project.profiles if not (p["component"] == component and p["name"] == name and p["attribute"] == attribute)]
    project.profiles.append(profile)
    return profile
