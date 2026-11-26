"""Reusable component builders and reproducible local optimization runs (no Qt)."""

from datetime import datetime, timezone
import csv
import importlib.metadata
import json
import logging
from pathlib import Path
import platform
import tempfile
import time
import uuid

import pandas as pd
import pypsa

from .schema import attribute_spec, registry
from .storage import load_project, save_project
from .validation import formulation_warnings
from .solution_checks import check_solution
from .advanced import time_index, snapshot_weights, native_piecewise_options
from .run_layout import metadata_path, formulation_directory


def add_component(network, record, piecewise=None):
    """Insert all scalar attributes and native curves together, exactly once.

    A second network.add(..., overwrite=True) for a curve can reset the original
    bus/capacity/commitment inputs. Curves replace only their matching scalar
    attribute in the initial add; they never require a second insertion.
    """
    attrs = dict(record["attributes"])
    for name, value in attrs.items():
        spec = attribute_spec(record["component"], name)
        if "float" in spec["dtype"]:
            attrs[name] = float(value)
        elif "geometry" in spec["dtype"]:
            from shapely import from_wkt
            attrs[name] = from_wkt(value)
    attrs.update(piecewise or {})
    network.add(record["component"], record["name"], **attrs)


# Separate entries permit type-specific templates without duplicating model logic.
BUILDERS = {name: add_component for name, spec in registry().items() if spec["editable"]}


def build_network(project):
    errors = project.validate()
    if errors:
        raise ValueError("\n".join(errors))
    network = pypsa.Network(name=project.name)
    # Snapshot rows do not imply hours. Explicit weights drive costs and storage.
    network.set_snapshots(
        time_index(project),
        default_snapshot_weightings=float(project.duration_hours),
    )
    if project.advanced_inputs.get("weights"):
        network.snapshot_weightings = snapshot_weights(project)
    periods = project.advanced_inputs.get("periods", [])
    if periods:
        network.set_investment_periods([p["period"] for p in periods])
        network.investment_period_weightings = pd.DataFrame(periods).set_index("period")
    order = {"Carrier": 0, "LineType": 1, "TransformerType": 1, "Bus": 2, "Shape": 9}
    records = sorted(project.objects, key=lambda o: order.get(o["component"], 5))
    # Large homogeneous tables use PyPSA's vector insertion contract. Small or
    # specialised records retain the established builder path and ordering.
    batched = set()
    batch_inputs = {}
    for kind in ["Bus", "Generator", "Load", "Line"]:
        group = [r for r in records if r["component"] == kind]
        if (len(group) < 20 or BUILDERS[kind] is not add_component
                or any(c["component"] == kind for c in project.advanced_inputs.get("piecewise", []))):
            continue
        fields = list(dict.fromkeys(k for r in group for k in r["attributes"]))
        values = {}
        for field in fields:
            spec = attribute_spec(kind, field)
            column = [r["attributes"].get(field, spec["default"]) for r in group]
            if "float" in spec["dtype"]:
                column = [float(v) for v in column]
            values[field] = column
        batch_inputs[kind] = ([r["name"] for r in group], values)
    for record in records:
        kind = record["component"]
        if record["component"] in batched:
            continue
        if kind in batch_inputs:
            names, values = batch_inputs[kind]
            network.add(kind, names, **values)
            batched.add(kind)
            continue
        curves = {c["attribute"]: dict(c["points"]) for c in project.advanced_inputs.get("piecewise", [])
                  if (c["component"], c["name"]) == (record["component"], record["name"])}
        if curves:
            add_component(network, record, curves)
        else:
            BUILDERS[record["component"]](network, record)
    profiles = {}
    for profile in project.profiles:
        profiles.setdefault((profile["component"], profile["attribute"]), {})[profile["name"]] = profile["values"]
    for (kind, attribute), columns in profiles.items():
        table = network.components[kind].dynamic
        existing = table.get(attribute, pd.DataFrame(index=network.snapshots))
        frame = pd.DataFrame(columns, index=network.snapshots)
        frame.columns.name = existing.columns.name
        table[attribute] = pd.concat([existing.drop(columns=list(columns), errors="ignore"), frame], axis=1)
    return network


def prepare_run(database, label="dispatch", export_format="lp", horizon=None, report_resolutions=None,
                export_python=False):
    if export_format not in {"none", "lp", "mps"}:
        raise ValueError("Export format must be none, lp, or mps.")
    database = Path(database).resolve()
    project = load_project(database)
    errors = project.validate()
    if errors:
        raise ValueError("\n".join(errors))
    plan = None
    profile_source = None
    if horizon is not None:
        from .horizon import schedule, aligned_project
        plan = schedule(horizon)
        if horizon.get("profile_policy") == "repeat_daily" and project.profiles:
            profile_source = {
                "policy": "repeat_daily",
                "template_snapshots": list(project.snapshots),
                "profiles": [{k: p[k] for k in ("component", "name", "attribute")} for p in project.profiles],
                "note": "Explicit clock-time repetition; expanded values are frozen in inputs.sqlite. Live project unchanged.",
            }
        project = aligned_project(project, plan)
    from .temporal_reports import validate_reports
    reports = validate_reports(project, report_resolutions or [])
    script = None
    if export_python:
        from .python_export import render_script, render_sequence
        script = render_sequence(len(plan["steps"])) if plan else render_script(project)
    script_name = "run.py" if plan else "model.py"
    # UUID suffix avoids collisions even for two runs started within one second.
    safe_label = "".join(c if c.isalnum() or c in "-_" else "-" for c in label)[:60] or "dispatch"
    run_id = datetime.now().strftime("%Y-%m-%d_%H%M%S") + "_" + safe_label + "_" + uuid.uuid4().hex[:8]
    directory = database.parent / "runs" / run_id
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "metadata").mkdir()
    save_project(project, directory / "inputs.sqlite")
    if script is not None:
        (directory / script_name).write_text(script, encoding="utf-8")
    write_json(metadata_path(directory, "run_config.json"), {
        "project": project.name, "project_id": project.project_id, "status": "queued", "solver": "highs",
        "formulation": "linear nodal optimization (LP/MILP)", "export_format": export_format,
        "currency": project.currency, "created_utc": datetime.now(timezone.utc).isoformat(),
        "versions": {name: importlib.metadata.version(name) for name in ["pypsa", "linopy", "highspy"]},
        "python": platform.python_version(), "platform": platform.platform(),
        **({"horizon": plan} if plan else {}),
        **({"profile_source": profile_source} if profile_source else {}),
        **({"report_resolutions": reports} if reports else {}),
        **({"python_script": script_name} if script is not None else {}),
    })
    return directory


def write_json(path, value):
    path = Path(path)
    temporary = None
    try:
        # Readers see either the old or new status, not a half-written JSON file.
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, indent=2, allow_nan=False)
        # Windows readers / file scanners can briefly deny replacement even
        # after our own handle has closed. Keep atomic publication; never fall
        # back to truncating the live file. Persistent denial still fails.
        for attempt in range(10):
            try:
                temporary.replace(path)
                break
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(min(0.01 * 2**attempt, 0.1))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def export_symbol_map(model, path):
    """Keep portable x/c solver labels and a separate human-readable mapping."""
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["kind", "symbol", "block", "coordinates"])
        for kind, blocks, prefix in [("variable", model.variables, "x"), ("constraint", model.constraints, "c")]:
            for name in blocks:
                labels = blocks[name].labels.to_series()
                for coordinate, label in labels.items():
                    if label < 0:
                        continue
                    values = coordinate if isinstance(coordinate, tuple) else (coordinate,)
                    coordinates = dict(zip(labels.index.names, map(str, values)))
                    writer.writerow([kind, f"{prefix}{int(label)}", name, json.dumps(coordinates)])


def export_tables(network, directory):
    """Export every available static/dynamic table; catalogue supports GUI queries."""
    tables = directory / "tables"
    tables.mkdir()
    catalog = []
    for key in network.components.keys():
        component = network.components[key]
        if not component.static.empty:
            filename = f"{component.list_name}__static.csv"
            component.static.to_csv(tables / filename, index_label="name")
            catalog.append({"component": component.name, "attribute": "static properties", "kind": "static", "file": filename})
        for attribute, frame in component.dynamic.items():
            if frame.empty:
                continue
            filename = f"{component.list_name}__{attribute}.csv"
            labels = ["period", "snapshot"] if isinstance(frame.index, pd.MultiIndex) else "snapshot"
            frame.to_csv(tables / filename, index_label=labels)
            spec = component.defaults.loc[attribute] if attribute in component.defaults.index else None
            catalog.append({
                "component": component.name, "attribute": attribute, "kind": "time series",
                "unit": str(spec["unit"]) if spec is not None else "", "file": filename,
            })
    write_json(metadata_path(directory, "catalog.json"), catalog)


def execute_run(directory, progress=lambda stage, message: None, network_sink=None):
    directory = Path(directory).resolve()
    config_path = metadata_path(directory, "run_config.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if "horizon" in config:
        from .sequential import execute_sequential
        return execute_sequential(directory, config, progress)
    handler = logging.FileHandler(directory / "application.log", encoding="utf-8")
    root = logging.getLogger()
    root.addHandler(handler)
    model = None
    try:
        config["status"] = "running"
        write_json(config_path, config)
        progress("validation", "Checking the frozen SQLite inputs and CSV profile alignment")
        project = load_project(directory / "inputs.sqlite")
        errors = project.validate()
        if errors:
            raise ValueError("\n".join(errors))
        for warning in formulation_warnings(project):
            progress("warning", warning)
        progress("network", "Constructing components with reusable PyPSA builders")
        network = build_network(project)
        network.consistency_check(strict=["all"])
        progress("formulation", "Creating the Linopy LP/MILP model")
        model = network.optimize.create_model(
            include_objective_constant=True,
            multi_investment_periods=bool(project.advanced_inputs.get("periods")),
            piecewise_options=native_piecewise_options(project),
        )
        if config["export_format"] != "none":
            progress("export", f"Exporting the actual {config['export_format'].upper()} formulation")
            # Coordinate names can contain ':' timestamps, invalid in an LP label.
            # Native numeric labels preserve solver portability; ship the mapping.
            formulation = formulation_directory(directory)
            formulation.mkdir(exist_ok=True)
            model.to_file(formulation / f"model.{config['export_format']}", explicit_coordinate_names=False)
            export_symbol_map(model, formulation / "symbols.csv")
        write_json(metadata_path(directory, "formulation_summary.json"), {
            "variables": model.nvars, "constraints": model.ncons,
            "variable_blocks": list(model.variables), "constraint_blocks": list(model.constraints),
            "note": "Block inventory, not a complete algebraic report. See LP/MPS for coefficients.",
        })
        progress("solver", "HiGHS is solving. The solver log is available; percentage is not estimated.")
        status, condition = network.optimize.solve_model(
            solver_name="highs", log_to_console=False,
            log_fn=directory / "highs.log", solver_options={"threads": 1},
        )
        config.update(solver_status=status, termination_condition=condition)
        if status != "ok" or condition != "optimal":
            raise RuntimeError(f"Optimization did not finish optimally: {status} / {condition}")
        progress("results", "Checking objective and saving solution tables")
        import math
        if not math.isfinite(float(network.objective)):
            raise RuntimeError("The solver returned a non-finite objective.")
        write_json(metadata_path(directory, "solution_checks.json"), check_solution(model))
        export_tables(network, directory)
        network.export_to_netcdf(directory / "solution.nc")
        if network_sink is not None:
            network_sink(network)
        if config.get("report_resolutions"):
            progress("reporting", "Generating selected calendar summaries from native results")
            from .temporal_reports import generate_reports
            generate_reports(directory, config)
        config.update(status="succeeded", objective=float(network.objective))
    except Exception as error:
        logging.exception("Run failed")
        config.update(status="failed", error=str(error))
        progress("failed", str(error))
        raise
    finally:
        # HiGHS keeps its log file open on Windows until the native handle closes.
        try:
            if model is not None and model.solver_model is not None:
                model.solver_model.setOptionValue("log_file", "")
                model.solver_model.clear()
            config["finished_utc"] = datetime.now(timezone.utc).isoformat()
            write_json(config_path, config)
        finally:
            root.removeHandler(handler)
            handler.close()
    progress("complete", "Optimized results saved. Open Results to query attributes.")
    return config
