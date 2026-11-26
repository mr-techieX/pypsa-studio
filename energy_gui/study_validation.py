"""Independent demo checks, separate from Linopy's own feasibility report."""

import json
import numpy as np
import pandas as pd

from .demo_library import pglib_data
from .network_view import frozen_overlay
from .results import ResultsRepository
from .schema import registry


def validate_study(project, directory, demo_id):
    def table(kind, attr):
        return pd.read_csv(directory / "tables" / f"{registry()[kind]['list_name']}__{attr}.csv", index_col=0)

    def effective(record, attr, default):
        profile = next((p for p in project.profiles if (p["component"], p["name"], p["attribute"]) ==
                        (record["component"], record["name"], attr)), None)
        return np.asarray(profile["values"] if profile else [record["attributes"].get(attr, default)] * len(project.snapshots), dtype=float)

    def close(actual, expected, label, tolerance=1e-5):
        residual = float(np.max(np.abs(np.asarray(actual) - np.asarray(expected))))
        if not np.isfinite(residual) or residual > tolerance:
            raise ValueError(f"Independent check failed: {label}; max residual={residual}.")
        return residual

    from .run_layout import metadata_path
    config = json.loads(metadata_path(directory, "run_config.json").read_text())
    if config.get("status") != "succeeded":
        raise ValueError("Independent validation requires a successful run.")
    balance = {r["name"]: np.zeros(len(project.snapshots)) for r in project.objects if r["component"] == "Bus"}
    objective = 0.0
    cache = {}
    for kind in ["Generator", "Load", "StorageUnit"]:
        records = [r for r in project.objects if r["component"] == kind]
        if not records:
            continue
        power = table(kind, "p")
        cache[kind] = power
        for r in records:
            name, attrs = r["name"], r["attributes"]
            balance[attrs["bus"]] += (-1 if kind == "Load" else 1) * power[name].to_numpy()
            if kind == "Load":
                close(power[name], effective(r, "p_set", 0), "given load " + name)
            if kind == "Generator":
                p = power[name].to_numpy()
                maximum = attrs["p_nom"] * effective(r, "p_max_pu", 1)
                if (p < -1e-6).any() or (p > maximum+1e-6).any():
                    raise ValueError("Generator bound check failed: " + name)
                objective += np.dot(p, effective(r, "marginal_cost", 0)) * project.duration_hours
            if kind == "StorageUnit":
                charge, dispatch, energy = (table(kind, attr)[name].to_numpy() for attr in ["p_store", "p_dispatch", "state_of_charge"])
                previous = np.roll(energy, 1)
                if not attrs.get("cyclic_state_of_charge", False):
                    previous[0] = attrs.get("state_of_charge_initial", 0)
                close(energy-previous, project.duration_hours*(attrs.get("efficiency_store", 1)*charge-dispatch/attrs.get("efficiency_dispatch", 1)), "storage recurrence " + name)
                if min(energy) < -1e-6 or max(energy) > attrs["p_nom"]*attrs["max_hours"]+1e-6:
                    raise ValueError("Storage energy bound check failed.")
                objective += np.dot(dispatch, effective(r, "marginal_cost", 0)) * project.duration_hours
    for kind in ["Line", "Transformer", "Link"]:
        records = [r for r in project.objects if r["component"] == kind]
        if not records:
            continue
        for port in [0, 1]:
            power = table(kind, f"p{port}")
            for r in records:
                balance[r["attributes"][f"bus{port}"]] -= power[r["name"]].to_numpy()
        for r in records:
            attrs = r["attributes"]
            p0 = table(kind, "p0")[r["name"]].to_numpy()
            if kind in {"Line", "Transformer"}:
                if (np.abs(p0) > attrs["s_nom"]*effective(r, "s_max_pu", 1)+1e-6).any():
                    raise ValueError("Passive branch limit check failed: " + r["name"])
            else:
                close(table(kind, "p1")[r["name"]], -p0*effective(r, "efficiency", 1), "converter delivery")
                objective += np.dot(p0, effective(r, "marginal_cost", 0)) * project.duration_hours
    residual = max(close(values, 0, "nodal balance " + bus) for bus, values in balance.items())
    objective_error = close(objective, config["objective"], "independent cost reconstruction", 1e-4)
    from .run_layout import metadata_path
    repository = ResultsRepository(directory, json.loads(metadata_path(directory, "catalog.json").read_text()))
    graph = frozen_overlay(repository, project.snapshots[-1])
    overlay_count = 0
    for w in graph["wires"]:
        if w.get("flow") is not None:
            kind, name = json.loads(w["a"])
            close(w["flow"], table(kind, w["attribute"])[name].iloc[-1], "overlay " + name)
            overlay_count += 1
    observations = {}
    if demo_id == "congestion2":
        close(cache["Generator"]["Remote plant"], 40, "congested import")
        close(cache["Generator"]["City peaker"], 20, "local peaker")
        close(objective, 2800, "analytic two-bus objective")
        observations["analytic_objective"] = 2800
    if demo_id in {"campus6", "district14", "regional20"}:
        dispatch_mwh = float(table("StorageUnit", "p_dispatch")["Battery"].sum()*project.duration_hours)
        if dispatch_mwh < 1:
            raise ValueError("Demo did not demonstrate the intended battery use case.")
        observations["battery_discharge_mwh"] = dispatch_mwh
    if demo_id == "wind10":
        offered = sum(float((effective(r, "p_max_pu", 1)*r["attributes"]["p_nom"]).sum())
                      for r in project.objects if r["component"] == "Generator" and r["attributes"].get("carrier") == "wind")
        curtailed = offered - cache["Generator"][["Coastal wind A", "Coastal wind B"]].sum().sum()
        gas = float(cache["Generator"]["Inland gas"].sum())
        if curtailed <= 1 or gas <= 1:
            raise ValueError("Wind demo did not demonstrate curtailment and local backup.")
        observations.update(wind_curtailment_mwh=float(curtailed), inland_generation_mwh=gas)
    if demo_id == "pglib14":
        # Independent reduced nodal matrix using the attributed source subset,
        # not PyPSA's network builder, cycle constraints or exported coefficients.
        data = pglib_data()
        branches = data["branches_from_to_x_tap_rate"]
        incidence = np.zeros((14, len(branches)))
        susceptance = []
        for j, (first, last, x, tap, _) in enumerate(branches):
            incidence[first-1, j], incidence[last-1, j] = 1, -1
            susceptance.append(data["base_mva"]/(x*tap))
        susceptance = np.asarray(susceptance)
        injections = -np.asarray(data["load_mw"], dtype=float)
        injections[0] += sum(data["load_mw"])
        matrix = (incidence*susceptance) @ incidence.T
        angles = np.zeros(14)
        angles[1:] = np.linalg.solve(matrix[1:, 1:], injections[1:])
        flows = susceptance * (incidence.T @ angles)
        if any(abs(flow) > branch[4]+1e-6 for flow, branch in zip(flows, branches)):
            raise ValueError("Analytic cheapest-unit dispatch is not feasible under the reference ratings.")
        if max(abs(incidence.T @ angles)) > np.pi/6+1e-6:
            raise ValueError("Reference dispatch violates the source 30-degree angle limits.")
        outputs = table("Line", "p0")
        error = close([outputs[f"Branch {a:02}-{b:02}"].iloc[0] for a, b, *_ in branches], flows, "independent IEEE14 DC flows")
        close(cache["Generator"]["G01"], 259, "cheapest-unit feasible optimum")
        close(objective, 259*data["generators_bus_pmax_cost"][0][2], "IEEE14 linear reference objective")
        observations.update(independent_dc_flow_max_error_mw=error, analytic_objective=259*data["generators_bus_pmax_cost"][0][2])
    return dict(status="passed", max_nodal_residual_mw=residual, objective=objective,
                objective_error=objective_error, overlay_ports_checked=overlay_count, observations=observations)
