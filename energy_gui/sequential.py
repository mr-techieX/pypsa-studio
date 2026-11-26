"""Independent chronological optimizations with explicit, auditable handoffs."""

from copy import deepcopy
from datetime import datetime, timezone
import math
import json

import pandas as pd

from .advanced import snapshot_weights
from .horizon import schedule, validate_sequential
from .project import Project
from .sequence_replay import initial_energy, outgoing_state, state_rows
from .storage import load_project, save_project
from .run_layout import metadata_path


def step_project(project, first, stop, incoming):
    """Slice exact inputs and apply incoming state (MWh, MW), without mutation.

    Native 1.4 initial energy bypasses first-interval standing loss. At subsequent
    handoffs pre-attenuate carried energy for that interval, restoring the same
    recurrence as an internal snapshot. Preserve the original first-run convention.
    """
    result = Project(**deepcopy(project.to_dict()))
    result.snapshots = project.snapshots[first:stop]
    for profile in result.profiles:
        profile["values"] = profile["values"][first:stop]
    result.advanced_inputs["weights"] = project.advanced_inputs["weights"][first:stop]
    result.duration_hours = result.advanced_inputs["weights"][0]["stores"]
    applied = []
    for record in result.objects:
        kind, name, attrs = record["component"], record["name"], record["attributes"]
        if not attrs.get("active", True):
            continue
        identity = (kind, name)
        if identity not in incoming:
            continue
        item = incoming[identity]
        if kind in {"Store", "StorageUnit"}:
            loss = next((p["values"][0] for p in result.profiles
                         if (p["component"], p["name"], p["attribute"]) == (kind, name, "standing_loss")),
                        attrs.get("standing_loss", 0))
            effective = initial_energy(item["energy"], loss, result.duration_hours)
            attrs["e_initial" if kind == "Store" else "state_of_charge_initial"] = effective
            applied.append(dict(component=kind, name=name, incoming_energy=item["energy"],
                                applied_initial_energy=effective, boundary_loss=item["energy"]-effective))
        elif kind in {"Generator", "Link"}:
            attrs["p_init"] = item["dispatch"]
            if attrs.get("committable"):
                attrs["up_time_before"] = item["up_time_before"]
                attrs["down_time_before"] = item["down_time_before"]
                if item["down_time_before"] > 0:
                    # Native 1.4 infers zero dispatch for an off unit and rejects
                    # an explicit p_init, even 0, in strict consistency checks.
                    attrs.pop("p_init", None)
            applied.append(dict(component=kind, name=name, previous_dispatch=item["dispatch"]))
    return result, applied


def execute_sequential(directory, config, progress):
    from .engine import build_network, execute_run, export_tables, write_json
    path = metadata_path(directory, "run_config.json")
    manifest = dict(version=1, status="running", completed_steps=0, steps=[],
                    note="Independent nonoverlapping solves; free terminal energy, no look-ahead.")
    try:
        # Check frozen schedule rather than trusting stored derived boundaries.
        plan = schedule(config["horizon"]["spec"])
        if plan != config["horizon"]:
            raise ValueError("Frozen horizon schedule is inconsistent.")
        project = load_project(directory / "inputs.sqlite")
        validate_sequential(project)
        if project.snapshots != plan["snapshots"]:
            raise ValueError("Frozen input axis differs from the schedule.")
        expected_weights = pd.DataFrame(
            [dict(objective=h, stores=h, generators=h) for h in plan["hours"]],
            index=pd.DatetimeIndex(project.snapshots, name="snapshot"),
        )
        if not snapshot_weights(project).equals(expected_weights):
            raise ValueError("Frozen duration weights differ from the schedule.")
        config.update(status="running", execution="sequential; no look-ahead",
                      completed_steps=0, total_steps=len(plan["steps"]))
        write_json(path, config)
        combined = build_network(project)
        parts, incoming, costs, checks = {}, {}, [], []
        (directory / "steps").mkdir()
        manifest_path = metadata_path(directory, "execution_manifest.json")
        write_json(manifest_path, manifest)
        for step in plan["steps"]:
            label = f"step-{step['number']:04d}"
            current_path = directory / "steps" / label
            current_path.mkdir()
            if (directory / "metadata").is_dir():
                (current_path / "metadata").mkdir()
            progress("step", f"{step['number']}/{len(plan['steps'])}: {step['start']} → {step['end']} (exclusive)")
            candidate, applied = step_project(project, step["first"], step["stop"], incoming)
            save_project(candidate, current_path / "inputs.sqlite")
            child = {k: v for k, v in config.items() if k not in {
                "horizon", "objective", "finished_utc", "error", "solver_status", "termination_condition",
                "report_resolutions", "python_script"}}
            child.update(status="queued", step=step, parent_run=directory.name)
            if config.get("python_script") == "run.py":
                from .python_export import render_script
                (current_path / "model.py").write_text(render_script(candidate, step=True), encoding="utf-8")
                child["python_script"] = "model.py"
            write_json(metadata_path(current_path, "run_config.json"), child)
            handoff_path = metadata_path(current_path, "handoff.json")
            write_json(handoff_path, dict(incoming=state_rows(incoming), applied=applied))
            manifest["active_step"] = step["number"]
            write_json(manifest_path, manifest)
            solved = []
            result = execute_run(
                current_path, lambda stage, message: progress(stage, f"{label}: {message}"),
                network_sink=solved.append,
            )
            # Use actual solved frames: NetCDF may omit native default-valued
            # columns, and is an archival artifact, not the assembly authority.
            network = solved[0]
            # Actual per-step feasibility already checked before publication.
            check = json.loads(metadata_path(current_path, "solution_checks.json").read_text(encoding="utf-8"))
            checks.append(check)
            incoming = outgoing_state(network)
            write_json(handoff_path, dict(
                incoming=manifest["steps"][-1]["outgoing"] if manifest["steps"] else [],
                applied=applied, outgoing=state_rows(incoming)))
            for key in network.components.keys():
                c = network.components[key]
                for attr, frame in c.dynamic.items():
                    if not frame.empty:
                        parts.setdefault((key, attr), []).append(frame)
                # Capacities are fixed; native opt columns reflect those fixed inputs.
                for column in c.static:
                    if column.endswith("_opt") and len(c.static):
                        combined.components[key].static[column] = c.static[column].copy()
            costs.append(float(result["objective"]))
            entry = dict(**step, directory=f"steps/{label}", objective=costs[-1],
                         status="succeeded", outgoing=state_rows(incoming))
            manifest["steps"].append(entry)
            manifest["completed_steps"] += 1
            manifest.pop("active_step", None)
            config["completed_steps"] = manifest["completed_steps"]
            write_json(manifest_path, manifest)
            write_json(path, config)
        progress("results", "Assembling validated nonoverlapping step results")
        for (key, attr), frames in parts.items():
            frame = pd.concat(frames)
            if frame.index.has_duplicates or not frame.index.equals(combined.snapshots):
                raise ValueError(f"{key}.{attr}: missing, duplicate or unordered step snapshots.")
            combined.components[key].dynamic[attr] = frame
        total = math.fsum(costs)
        if not math.isfinite(total):
            raise ValueError("Nonfinite sequential objective.")
        combined._objective = total
        combined.export_to_netcdf(directory / "solution.nc")
        export_tables(combined, directory)
        write_json(metadata_path(directory, "solution_checks.json"), dict(
            status="passed", scope="Per-step LP checks plus exact snapshot assembly and explicit state handoffs; not AC feasibility.",
            steps=len(checks), max_scaled_constraint_residual=max(c["max_scaled_constraint_residual"] for c in checks)))
        write_json(metadata_path(directory, "formulation_summary.json"), dict(
            note="Actual models are exported per step when requested; no synthetic combined LP.",
            steps=len(checks), objective_scope="Sum of nonoverlapping fixed-capacity window objectives; not a full-horizon optimum."))
        if config.get("report_resolutions"):
            progress("reporting", "Generating selected calendar reports from all assembled steps")
            from .temporal_reports import generate_reports
            generate_reports(directory, config)
        manifest.update(status="succeeded", objective=total)
        config.update(status="succeeded", objective=total, solver_status="ok", termination_condition="optimal",
                      objective_scope="sum of independent, nonoverlapping fixed-capacity step objectives")
        progress("complete", "All configured steps solved; unused upper-horizon time was not simulated.")
    except Exception as error:
        manifest.update(status="failed", error=str(error))
        config.update(status="failed", error=str(error))
        progress("failed", str(error))
        raise
    finally:
        config["finished_utc"] = datetime.now(timezone.utc).isoformat()
        write_json(metadata_path(directory, "execution_manifest.json"), manifest)
        write_json(path, config)
    return config


def mark_cancelled(directory):
    """Called only by the controller owning the killed worker, never on browse."""
    from .engine import write_json
    path = metadata_path(directory, "execution_manifest.json")
    if not path.exists():
        return
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.update(status="cancelled", error="Stopped by user; partial results are not a complete solution.")
    write_json(path, manifest)
    number = manifest.get("active_step")
    if isinstance(number, int) and 1 <= number <= 10000:
        child_path = metadata_path(directory / "steps" / f"step-{number:04d}", "run_config.json")
        if child_path.exists():
            child = json.loads(child_path.read_text(encoding="utf-8"))
            if child.get("status") in {"queued", "running"}:
                child.update(status="cancelled", error=manifest["error"])
                write_json(child_path, child)
