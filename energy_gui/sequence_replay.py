"""Replay an exported PyPSA sequence; keep this file beside the steps folder."""

import json
import math
import os
from pathlib import Path
import runpy
import shutil
import tempfile

import pandas as pd


WEIGHTS = ["objective", "stores", "generators"]
STATE_FIELDS = {
    "Store": ("e", "energy"), "StorageUnit": ("state_of_charge", "energy"),
    "Generator": ("p", "dispatch"), "Link": ("p0", "dispatch"),
}


def initial_energy(energy, loss, hours):
    # PyPSA 1.4 starts with already-attenuated energy at a step boundary.
    return energy * (1 - float(loss)) ** hours


def outgoing_state(network):
    state = {}
    for kind, (attribute, key) in STATE_FIELDS.items():
        component = network.components[kind]
        table = component.dynamic.get(attribute)
        for name in component.static.index[component.static.active]:
            if table is None or table.empty or name not in table:
                if key == "energy":
                    raise ValueError(f"{kind} {name}: missing outgoing storage energy.")
                continue
            value = float(table[name].iloc[-1])
            if not math.isfinite(value):
                raise ValueError(f"{kind} {name}: nonfinite boundary state.")
            item = state[kind, str(name)] = {key: value}
            if key == "dispatch" and component.static.at[name, "committable"]:
                statuses = component.dynamic.status[name]
                on = bool(round(float(statuses.iloc[-1])))
                consecutive = 0
                for status in reversed(statuses.to_numpy()):
                    if bool(round(float(status))) != on:
                        break
                    consecutive += 1
                if consecutive == len(statuses):
                    before = "up_time_before" if on else "down_time_before"
                    consecutive += int(component.static.at[name, before])
                item.update(up_time_before=consecutive if on else 0,
                            down_time_before=0 if on else consecutive)
    return state


def apply_handoff(network, incoming):
    for kind, (_, key) in STATE_FIELDS.items():
        component = network.components[kind]
        for name in component.static.index[component.static.active]:
            if (kind, str(name)) not in incoming:
                raise ValueError(f"{kind} {name}: no fresh handoff; keep stateful objects active across steps.")
            item = incoming[kind, str(name)]
            if key == "energy":
                loss_profile = component.dynamic.standing_loss
                loss = loss_profile[name].iloc[0] if name in loss_profile else component.static.at[name, "standing_loss"]
                hours = network.snapshot_weightings.stores.iloc[0]
                attr = "e_initial" if kind == "Store" else "state_of_charge_initial"
                component.static.at[name, attr] = initial_energy(item[key], loss, hours)
            else:
                dispatch = item[key]
                if component.static.at[name, "committable"]:
                    for attr in ("up_time_before", "down_time_before"):
                        if attr not in item:
                            raise ValueError(f"{kind} {name}: commitment settings changed between steps.")
                        component.static.at[name, attr] = item[attr]
                    if item["down_time_before"] > 0:
                        dispatch = component.defaults.at["p_init", "default"]
                component.static.at[name, "p_init"] = dispatch


def state_rows(state):
    return [dict(component=k[0], name=k[1], **v) for k, v in sorted(state.items())]


def check_compatible(base, step):
    """One combined network cannot represent different static models per step."""
    if base.crs != step.crs:
        raise ValueError("Incompatible coordinate reference systems across replay steps.")
    initial = {
        "Store": ["e_initial"], "StorageUnit": ["state_of_charge_initial"],
        "Generator": ["p_init", "up_time_before", "down_time_before"],
        "Link": ["p_init", "up_time_before", "down_time_before"],
    }
    for kind in base.components.keys():
        component, other = base.components[kind], step.components[kind]
        drop = initial.get(component.name, [])
        left = component.static.drop(columns=drop, errors="ignore")
        right = other.static.drop(columns=drop, errors="ignore")
        try:
            pd.testing.assert_frame_equal(left, right, check_like=True, check_dtype=False, check_exact=True)
            if set(component.piecewise) != set(other.piecewise):
                raise AssertionError("Different piecewise properties")
            for attribute in component.piecewise:
                pd.testing.assert_frame_equal(component.piecewise[attribute], other.piecewise[attribute],
                                              check_like=True, check_dtype=False, check_exact=True)
        except AssertionError as error:
            raise ValueError(f"{component.name}: incompatible static inputs across replay steps.") from error


def step_axis(network):
    index, weights = network.snapshots, network.snapshot_weightings
    if (not isinstance(index, pd.DatetimeIndex) or index.tz is not None or index.empty
            or index.hasnans or index.has_duplicates or not index.is_monotonic_increasing):
        raise ValueError("Step snapshots must be nonempty, timezone-naive and strictly ordered.")
    if not weights.index.equals(index) or list(weights) != WEIGHTS or any(
            not math.isfinite(value) or value <= 0 for value in weights.to_numpy().flat):
        raise ValueError("Step snapshot weights must match the axis and be finite and positive.")
    # Convert fractional hours directly to rounded ns. Converting from float
    # hours via pandas can shift a valid minute boundary by 1–2 ns.
    durations = pd.to_timedelta((weights.stores * 3.6e12).round(), unit="ns")
    if not (index[:-1] + durations.iloc[:-1].array).equals(index[1:]):
        raise ValueError("Step snapshot durations must form contiguous coverage.")
    return index, weights.copy(), index[-1] + durations.iloc[-1]


def write_summary(output, summary):
    metadata = output / "metadata"
    pending = metadata / "summary-pending.json"
    pending.write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    pending.replace(metadata / "summary.json")


def export_network(network, path):
    if os.name != "nt" or str(path).isascii():
        network.export_to_netcdf(path)
        return
    # The Windows NetCDF backend can misinterpret Unicode path bytes.
    with tempfile.TemporaryDirectory(prefix="studio-replay-") as directory:
        if not directory.isascii():
            raise ValueError("NetCDF export needs an ASCII-only output or temporary path on this Windows runtime.")
        staged = Path(directory) / path.name
        network.export_to_netcdf(staged)
        shutil.copyfile(staged, path)


def run_sequence(root, count):
    labels = [f"step-{number:04d}" for number in range(1, count + 1)]
    scripts = [root / "steps" / label / "model.py" for label in labels]
    for script in scripts:
        if not script.is_file():
            raise FileNotFoundError(f"Missing {script.relative_to(root)}; export the complete sequence first.")
    output = Path(tempfile.mkdtemp(prefix="replay-", dir=root))
    (output / "metadata").mkdir()
    print(f"Replay output: {output}", flush=True)
    summary = {"status": "running", "steps": []}
    parts, axes, weights, incoming = {}, [], [], {}
    combined = None
    optimized = {}
    next_start = None
    label = "assembly"
    try:
        for label, script in zip(labels, scripts):
            step = runpy.run_path(str(script))
            network = step["build_network"]()
            index, step_weights, end = step_axis(network)
            if next_start is not None:
                if index[0] != next_start:
                    raise ValueError("Step boundaries must be contiguous and nonoverlapping.")
                check_compatible(combined, network)
                apply_handoff(network, incoming)
            else:
                combined = network.copy()
            step["solve"](network)
            if not network.snapshots.equals(index) or not network.snapshot_weightings.equals(step_weights):
                raise ValueError("The solve changed the step snapshots or snapshot weights.")
            cost = float(network.objective)
            if not math.isfinite(cost):
                raise ValueError("Nonfinite step objective.")
            incoming = outgoing_state(network)
            export_network(network, output / f"{label}.nc")
            axes.append(index)
            weights.append(step_weights)
            next_start = end
            for component in network.components.values():
                base = combined.components[component.name]
                if (not component.static.index.is_unique
                        or set(base.static.index) != set(component.static.index)):
                    # SubNetwork identities are derived by PyPSA during the solve.
                    if component.name != "SubNetwork":
                        raise ValueError(f"{component.name}: the solve changed component identities.")
                for attribute, frame in component.dynamic.items():
                    if not frame.empty:
                        if (not frame.index.equals(index) or not frame.columns.is_unique
                                or not frame.columns.isin(base.static.index).all()):
                            raise ValueError(f"{component.name}.{attribute}: invalid solved snapshot/object identities.")
                        parts.setdefault((component.name, attribute), []).append(frame)
                for column in component.static:
                    if column.endswith("_opt") and not component.static.empty:
                        key = component.name, column
                        values = component.static[column].reindex(base.static.index)
                        if key in optimized:
                            try:
                                pd.testing.assert_series_equal(optimized[key], values, check_exact=False,
                                                               rtol=1e-7, atol=1e-8)
                            except AssertionError as error:
                                raise ValueError(f"{component.name}.{column}: optimized values differ across steps.") from error
                        optimized[key] = values
            summary["steps"].append(dict(step=label, start=index[0].isoformat(), end=next_start.isoformat(),
                                         objective=cost, outgoing=state_rows(incoming)))
        label = "assembly"
        index = axes[0].append(axes[1:])
        tables = output / "tables-pending"
        tables.mkdir()
        combined.set_snapshots(index)
        combined.snapshot_weightings = pd.concat(weights)
        for (kind, column), values in optimized.items():
            combined.components[kind].static[column] = values
        for (kind, attribute), frames in parts.items():
            # A missing step/object stays blank rather than being filled with a
            # PyPSA default. Reindex only after verifying each solved frame.
            frame = pd.concat(frames).reindex(index)
            component = combined.components[kind]
            component.dynamic[attribute] = frame
            frame.to_csv(tables / f"{component.list_name}__{attribute}.csv", index_label="snapshot")
        summary["objective"] = math.fsum(step["objective"] for step in summary["steps"])
        combined._objective = summary["objective"]
        combined.meta = {**combined.meta, "studio_replay": {
            "kind": "sequential_replay", "objective_scope": "sum of independent step objectives",
            "steps": [{key: value for key, value in step.items() if key != "outgoing"}
                      for step in summary["steps"]],
        }}
        pending = output / "solution-pending.nc"
        export_network(combined, pending)
        tables.rename(output / "tables")
        summary["status"] = "succeeded"
        write_summary(output, summary)
        pending.rename(output / "solution.nc")
    except (Exception, KeyboardInterrupt) as error:
        (output / "solution-pending.nc").unlink(missing_ok=True)
        summary.update(status="failed", failed_at=label, error=str(error))
        write_summary(output, summary)
        raise
    print(f"Sequence objective: {summary['objective']}")
