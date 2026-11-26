"""Conservative checks for the supported linear workflow, not all grid-code rules."""

from functools import lru_cache
import math

import pypsa

from .schema import attribute_spec, parse_value


@lru_cache(maxsize=1)
def type_catalogues():
    network = pypsa.Network()
    return {"Line": set(network.line_types.index), "Transformer": set(network.transformer_types.index)}


def engineering_errors(project):
    errors = []
    buses = {o["name"]: o["attributes"] for o in project.objects if o["component"] == "Bus"}
    types = {kind: set(names) for kind, names in type_catalogues().items()}
    for record in project.objects:
        if record["component"] in {"LineType", "TransformerType"}:
            types[record["component"].removesuffix("Type")].add(record["name"])
    for record in project.objects:
        kind, name, attrs = record["component"], record["name"], record["attributes"]
        label = f"{kind} {name}"

        def number(key):
            try:
                spec = attribute_spec(kind, key)
                value = attrs.get(key, spec["default"])
                return float(value) if value is not None else None
            except (ValueError, TypeError):
                return None

        def effective(key):
            profile = next((p for p in project.profiles if p["component"] == kind and p["name"] == name and p["attribute"] == key), None)
            try:
                values = [float(v) for v in profile["values"]] if profile else [number(key)] * len(project.snapshots)
                return values if len(values) == len(project.snapshots) and all(v is not None for v in values) else []
            except (ValueError, TypeError):
                return []

        for base in ("p_nom", "e_nom", "s_nom"):
            for suffix in ("", "_min", "_max", "_mod", "_set"):
                value = number(base + suffix)
                if value is not None and (value < 0 or (suffix in {"", "_min", "_mod", "_set"} and not math.isfinite(value))):
                    errors.append(f"{label}.{base+suffix}: capacity must be nonnegative and finite (only maximum bounds may be infinite).")
            low, high = number(base + "_min"), number(base + "_max")
            if low is not None and high is not None and low > high:
                errors.append(f"{label}: {base}_min exceeds {base}_max.")
        for low, high in [("p_min_pu", "p_max_pu"), ("e_min_pu", "e_max_pu")]:
            lower, upper = effective(low), effective(high)
            if lower and upper and any(a > b for a, b in zip(lower, upper)):
                errors.append(f"{label}: {low} exceeds {high} at one or more snapshots.")
        for key in ("s_max_pu", "max_hours", "min_up_time", "min_down_time", "up_time_before", "down_time_before"):
            values = effective(key)
            if values and any(not math.isfinite(v) or v < 0 for v in values):
                errors.append(f"{label}.{key}: expected finite nonnegative values.")
        for key in ("efficiency_store", "efficiency_dispatch", "standing_loss"):
            values = effective(key)
            if values and any(not math.isfinite(v) or (v <= 0 or v > 1 if key == "efficiency_dispatch" else v < 0 or v > 1) for v in values):
                errors.append(f"{label}.{key}: use [0, 1] for standing loss/charging efficiency and (0, 1] for discharge efficiency.")
        if kind == "Generator":
            values = effective("efficiency")
            if any(not math.isfinite(v) or v <= 0 for v in values):
                errors.append(f"{label}.efficiency: must be positive and finite.")
        if kind in {"Line", "Transformer"}:
            standard = attrs.get("type", "")
            if standard and standard not in types[kind]:
                errors.append(f"{label}.type: unknown {kind}Type '{standard}'.")
            if not standard:
                x = number("x")
                if x is not None and (not math.isfinite(x) or x == 0):
                    errors.append(f"{label}.x: DC-OPF requires finite nonzero reactance (ohm for Lines, per unit for Transformers).")
                if kind == "Transformer" and (number("s_nom") or 0) <= 0:
                    errors.append(f"{label}.s_nom: a manual Transformer requires a positive MVA base.")
            if kind == "Transformer" and not standard and ((number("tap_ratio") or 0) <= 0):
                errors.append(f"{label}.tap_ratio: must be positive.")
            a, b = buses.get(attrs.get("bus0")), buses.get(attrs.get("bus1"))
            if kind == "Line" and a is not None and b is not None:
                try:
                    if not math.isclose(float(a.get("v_nom", 1)), float(b.get("v_nom", 1))):
                        errors.append(f"{label}: endpoint voltage levels differ; use a Transformer, not a Line.")
                except (ValueError, TypeError):
                    pass  # The malformed bus voltage is reported by input checks.
        if kind == "Bus" and (number("v_nom") is None or not math.isfinite(number("v_nom"))):
            errors.append(f"{label}.v_nom: expected a finite voltage in kV.")
    return errors


def formulation_warnings(project):
    warnings = []
    for record in project.objects:
        kind, name, attrs = record["component"], record["name"], record["attributes"]
        if "q_set" in attrs or "control" in attrs or (kind == "Bus" and "v_mag_pu_set" in attrs):
            warnings.append(f"{kind} {name}: reactive-power/voltage-control inputs do not constrain this DC-OPF workflow.")
        if kind == "ShuntImpedance":
            warnings.append(f"ShuntImpedance {name}: AC shunt effects are not modeled by this lossless DC-OPF.")
    for profile in project.profiles:
        if profile["attribute"] in {"q_set", "v_mag_pu_set"}:
            warnings.append(f"Profile {profile['component']} {profile['name']}.{profile['attribute']}: power-flow input, not a DC-OPF dispatch constraint.")
    return warnings
