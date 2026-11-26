"""Bounded advanced inputs backed by the installed PyPSA 1.4 formulation.

Cost points are *incremental prices*, not total-cost coordinates: y[i] prices
(x[i-1], x[i]], and y[0]=0 is an ignored zero-width sentinel. PyPSA integrates
these prices. Dispatch x is p/p_nom; investment x is absolute optimised nominal
capacity, not an addition above the existing nominal capacity. Investment prices
must already be periodised and include fixed O&M. Snapshot objective weights
apply to dispatch costs; active investment-period objective weights apply to
capital costs (not snapshot durations).
Native saved capital_cost_piecewise_opt is the resulting average unit price;
the model's capital_cost_piecewise auxiliary variable is total currency.

Link efficiency points have different native semantics: [x, eta] defines output
power eta*x*p_nom at input power x*p_nom. PyPSA interpolates those POWER points
with an equality, not eta itself. At x=0 the zero sentinel still means zero
output, not a zero-efficiency operating segment. Equality may introduce binary
variables, even on a noncommittable Link.
"""

import math

import pandas as pd

from .schema import attribute_spec


_CURVE_AXES = {
    ("Generator", "marginal_cost"): ("p_pu", False),
    ("Generator", "capital_cost"): ("p_nom", True),
    ("Line", "capital_cost"): ("s_nom", True),
    ("Link", "capital_cost"): ("p_nom", True),
    ("Link", "efficiency"): ("p_pu", False),
}

# These are views of existing static attributes, not another persisted model.
_CONTROL_GROUPS = {
    "Generator": [(
        "Unit commitment",
        "Fixed-capacity binary commitment. Minimum times count snapshots, not "
        "weighted hours; ramps are per snapshot. Extendable+committable and "
        "dispatch-cost curves+committable are outside this bounded editor.",
        ("committable", "p_nom", "p_nom_extendable", "p_min_pu", "p_max_pu",
         "start_up_cost", "shut_down_cost", "stand_by_cost", "min_up_time",
         "min_down_time", "up_time_before", "down_time_before", "p_init",
         "ramp_limit_up", "ramp_limit_down", "ramp_limit_start_up", "ramp_limit_shut_down"),
    )],
    "StorageUnit": [(
        "Storage energy and boundaries",
        "Energy capacity = p_nom * max_hours (MWh). Initial state is MWh, not "
        "percent; cyclic boundaries override initial state. Stores weights are "
        "elapsed hours; retention is (1-standing_loss)**hours. Charging and "
        "discharging efficiencies multiply for round-trip efficiency. Native "
        "1.4 injects prescribed initial energy without first-step standing loss; "
        "retention multiplies preceding optimised SOC on subsequent steps.",
        ("p_nom", "p_nom_extendable", "p_nom_min", "p_nom_max", "max_hours",
         "efficiency_store", "efficiency_dispatch", "standing_loss", "inflow",
         "state_of_charge_initial", "state_of_charge_set", "cyclic_state_of_charge",
         "state_of_charge_initial_per_period", "cyclic_state_of_charge_per_period"),
    )],
    "GlobalConstraint": [(
        "System-wide cap",
        "For a CO2 cap use primary_energy / co2_emissions / <=; constant is "
        "tonnes over the accounting horizon. Carrier factors are tonnes/MWh "
        "of primary energy: generator emissions use dispatch/efficiency and "
        "generators weights (and period years). Other types use different units "
        "and carrier selections; do not interpret them as CO2 caps.",
        ("type", "carrier_attribute", "sense", "constant", "investment_period", "bus"),
    )],
}


def advanced_modeling_controls(component):
    """Return fresh schema-field groups for a static-attribute UI (no mutation).

    ``component`` is a PyPSA class name; unsupported classes return []. Field
    dictionaries retain attribute_spec's units, defaults, types and descriptions.
    Edits belong in the component's existing attributes, NOT advanced_inputs.
    """
    groups = []
    for title, description, names in _CONTROL_GROUPS.get(component, []):
        fields = [dict(attribute_spec(component, name)) for name in names]
        if component == "GlobalConstraint":
            choices = {
                "sense": ["<=", "==", ">="],
                "type": ["primary_energy", "operational_limit", "tech_capacity_expansion_limit",
                         "transmission_volume_expansion_limit", "transmission_expansion_cost_limit"],
            }
            for field in fields:
                if field["name"] in choices:
                    field["choices"] = choices[field["name"]]
        groups.append(dict(component=component, title=title, description=description, fields=fields))
    return groups


def piecewise_capabilities():
    """Describe only supported curves; native support alone is not GUI support."""
    result = []
    for (component, attribute), (axis, extendable) in _CURVE_AXES.items():
        cost = attribute != "efficiency"
        result.append(dict(
            component=component, attribute=attribute, x_attribute=axis,
            x_unit=("per unit of fixed p_nom" if not extendable else
                    "MVA (native s_nom; MW active-flow bound in DC-OPF)" if component == "Line" else "MW"),
            y_unit=("per unit output/input at the breakpoint" if not cost else
                    "currency/MWh" if not extendable else
                    "currency/MVA (DC MW-equivalent)" if component == "Line" else "currency/MW"),
            semantics=(("Incremental segment price on (previous x, x]; integrated from zero. "
                        + ("Capital costs cover total optimised capacity and include fixed O&M; "
                           "capital_cost_piecewise_opt reports average currency/capacity, not total cost."
                           if extendable else "The physical dispatch integral is weighted by objective hours."))
                       if cost else "Interpolate output power eta*x*p_nom, NOT efficiency; p1 is negative output."),
            extendable=extendable,
            limits=("Nonnegative nondecreasing prices; origin [0,0]. Finite nominal maximum "
                    "within the curve domain; no overnight_cost or nonzero fom_cost. "
                    + ("Line impedance is fixed; this is not an iterative physical grid redesign."
                       if component == "Line" else "")
                    if extendable else "Fixed positive p_nom, noncommittable, dispatch in [0,1]."
                    + (" Two ports, no delay, eta in (0,1] away from origin; output strictly increasing."
                       if not cost else "")),
            methods=["auto", "lp"] if cost else ["auto", "incremental"],
            sign=">=" if cost else "=",
        ))
    return result


def _finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _curve_options(curve):
    options = curve.get("options", {})
    if not isinstance(options, dict) or set(options) - {"method", "sign"}:
        raise ValueError("Curve options support method and sign only; axes/integration/name cannot be overridden.")
    cost = curve["attribute"] != "efficiency"
    sign = ">=" if cost else "="
    methods = {"auto", "lp"} if cost else {"auto", "incremental"}
    if not isinstance(options.get("method", "auto"), str) or options.get("method", "auto") not in methods:
        raise ValueError("Cost curve methods are auto/lp; efficiency methods are auto/incremental (HiGHS-safe).")
    if options.get("sign", sign) != sign:
        raise ValueError(f"This curve requires native sign '{sign}'; changing the physical/cost relation is unsupported.")
    return dict(method=options.get("method", "auto"), sign=sign)


def native_piecewise_options(project):
    """Return validated PyPSA create_model(piecewise_options=...) overrides.

    Native options are scoped to each exact component/name/attribute. Cost
    integration and conversion multiplication are fixed by PyPSA, not exposed
    as user switches; SOS2 is not offered by this HiGHS LP/MILP workflow. Omitted
    options retain native defaults and existing exported constraint block names.
    """
    clean = checked_advanced(project, project.advanced_inputs)
    return [dict(component=c["component"], attribute=c["attribute"], name=c["name"],
                 **_curve_options(c)) for c in clean.get("piecewise", []) if "options" in c]


def _checked_curve(project, curve, seen):
    required = {"component", "name", "attribute", "points"}
    if (not isinstance(curve, dict) or not required <= set(curve)
            or set(curve) - required - {"options"}):
        raise ValueError("Each curve needs component, name, attribute and points; only options is optional.")
    if any(not isinstance(curve[k], str) or not curve[k] for k in ("component", "name", "attribute")):
        raise ValueError("Curve component, name and attribute must be nonempty strings.")
    key = curve["component"], curve["name"], curve["attribute"]
    component, name, attribute = key
    if (component, attribute) not in _CURVE_AXES:
        raise ValueError("Supported curves: Generator marginal_cost; Generator/Line/Link capital_cost; Link efficiency only.")
    record = project.object(component, name)
    if record is None or key in seen:
        raise ValueError("Curve must reference a unique existing component/name/attribute.")

    # Match the installed native axis/extendability contract before accepting data.
    from pypsa.constants import piecewise_schema
    native = piecewise_schema(component, attribute)
    axis, extendable = _CURVE_AXES[component, attribute]
    if native.empty or native.x != axis or bool(native.allow_extendable) != extendable:
        raise ValueError("Installed PyPSA piecewise schema does not match the supported curve contract.")
    options = _curve_options(curve)
    attrs = record["attributes"]

    def number(field):
        value = attrs.get(field, attribute_spec(component, field)["default"])
        if isinstance(value, bool):
            raise ValueError(f"{component} {name}.{field}: expected a number, not a boolean.")
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"{component} {name}.{field}: expected a numeric value.") from error

    points = curve["points"]
    if not isinstance(points, list) or len(points) < 2:
        raise ValueError("Supply at least two [x, y] breakpoints.")
    if any(not isinstance(p, list) or len(p) != 2 or not all(_finite_number(v) for v in p) for p in points):
        raise ValueError("Curve points must be finite numeric pairs, not booleans.")
    # Validate in the same floating-point coordinates that PyPSA will consume;
    # distinct huge integers must not silently collapse to duplicate floats.
    points = [[float(a), float(b)] for a, b in points]
    x, y = zip(*points)
    if x[0] != 0 or y[0] != 0 or any(a >= b for a, b in zip(x, x[1:])):
        raise ValueError("Use strictly increasing x starting at [0,0].")
    profiles = [p for p in project.profiles if (p["component"], p["name"]) == (component, name)]
    if any(p["attribute"] == attribute for p in profiles):
        raise ValueError("A piecewise attribute cannot also have a time profile.")
    if attrs.get("committable", False):
        raise ValueError("Curves require noncommittable components; commitment+curve is outside this bounded workflow.")

    if attribute == "capital_cost":
        if not attrs.get(axis + "_extendable", False):
            raise ValueError("Capital-cost curves require extendable nominal capacity.")
        if not math.isfinite(number(axis)) or number(axis) < 0:
            raise ValueError("Existing nominal capacity must be finite and nonnegative; the curve prices total optimised capacity.")
        low, high = number(axis + "_min"), number(axis + "_max")
        if not (math.isfinite(low) and math.isfinite(high) and 0 <= low <= high <= x[-1] and high > 0):
            raise ValueError("Capital curves need finite 0 <= nominal_min <= nominal_max within the curve domain, with nominal_max > 0.")
        if attrs.get(axis + "_set") is not None and not low <= number(axis + "_set") <= high:
            raise ValueError("Nominal set capacity must be finite and within the declared capacity bounds.")
        if attrs.get("overnight_cost") is not None:
            raise ValueError("Capital curve prices must already be periodised; overnight_cost is unsupported.")
        if number("fom_cost") != 0:
            raise ValueError("Native piecewise capital cost does not add fom_cost; include fixed O&M in the curve and omit fom_cost.")
    else:
        if attrs.get("p_nom_extendable", False) or not math.isfinite(number("p_nom")) or number("p_nom") <= 0:
            raise ValueError("Dispatch/efficiency curves require fixed positive finite p_nom, not extendable capacity.")
        if x[-1] != 1:
            raise ValueError("Dispatch/efficiency curves must cover x=0..1 of fixed p_nom.")
        bounds = {}
        for field in ("p_min_pu", "p_max_pu"):
            static = number(field)
            values = next((p["values"] for p in profiles if p["attribute"] == field), [static] * len(project.snapshots))
            if (not math.isfinite(static) or not 0 <= static <= 1
                    or any(not math.isfinite(float(v)) or not 0 <= float(v) <= 1 for v in values)):
                raise ValueError("Static and time-profile dispatch bounds must stay in [0,1] for curves.")
            bounds[field] = values
        if any(float(a) > float(b) for a, b in zip(bounds["p_min_pu"], bounds["p_max_pu"])):
            raise ValueError("Curve dispatch minimum exceeds maximum.")
        setpoints = [p["values"] for p in profiles if p["attribute"] == "p_set"]
        if attrs.get("p_set") is not None:
            setpoints.append([number("p_set")])
        if any(not math.isfinite(float(v)) or not 0 <= float(v) <= number("p_nom") for values in setpoints for v in values):
            raise ValueError("Curve dispatch set points must stay within [0,p_nom] MW.")

    if attribute == "efficiency":
        # Restrict to forward, instantaneous two-port conversion; no reverse-loss
        # interpretation or higher-port/delay interactions are implied.
        if (not attrs.get("bus0") or not attrs.get("bus1") or attrs["bus0"] == attrs["bus1"]
                or any(k.startswith("bus") and k[3:].isdigit() and int(k[3:]) >= 2 and v for k, v in attrs.items())
                or any(k.startswith(("efficiency", "delay")) and k[-1:].isdigit() for k in attrs)
                or number("delay") != 0):
            raise ValueError("Efficiency curves support distinct bus0/bus1 only, without extra ports or delays.")
        if any(not 0 < v <= 1 for v in y[1:]):
            raise ValueError("Link breakpoint efficiencies must be positive and <=1 away from the zero origin sentinel.")
        output = [float(a) * float(b) for a, b in points]
        if any(a >= b for a, b in zip(output, output[1:])):
            raise ValueError("Link output power x*efficiency must strictly increase with forward input power.")
    else:
        if any(v < 0 for v in y) or any(a > b for a, b in zip(y[1:], y[2:])):
            raise ValueError("Use nonnegative nondecreasing incremental segment prices (convex cost).")
        scale = 1 if extendable else number("p_nom")
        total = scale * sum(float(b-a) * float(price) for a, b, price in zip(x, x[1:], y[1:]))
        if not math.isfinite(total):
            raise ValueError("Integrated curve cost must remain finite.")
    seen.add(key)
    clean = {k: curve[k] for k in ("component", "name", "attribute")}
    clean["points"] = [[float(a), float(b)] for a, b in points]
    if "options" in curve:
        clean["options"] = options
    return clean


def checked_advanced(project, data):
    if not isinstance(data, dict) or set(data) - {"weights", "periods", "snapshot_periods", "piecewise"}:
        raise ValueError("Advanced inputs use weights, periods, snapshot_periods and piecewise only.")
    # Keep the bounded static commitment editor away from native big-M joint
    # investment/commitment, even when no piecewise curves have been entered.
    for record in project.objects:
        attrs = record["attributes"]
        if (record["component"] in {"Generator", "Link"}
                and attrs.get("committable", False) and attrs.get("p_nom_extendable", False)):
            raise ValueError(f"{record['component']} {record['name']}: extendable+committable is outside the bounded advanced workflow; use fixed capacity.")
    count = len(project.snapshots)
    def positive(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("Weights must be positive finite numbers, not booleans.")
        return float(value)
    weights = data.get("weights", [])
    if not isinstance(weights, list):
        raise ValueError("weights must be a list of snapshot rows.")
    if weights and (not isinstance(weights, list) or len(weights) != count):
        raise ValueError("Supply exactly one weight row per snapshot, or [] for interval defaults.")
    clean_weights = []
    for row in weights:
        if not isinstance(row, dict) or set(row) != {"objective", "stores", "generators"}:
            raise ValueError("Each weight row needs objective, stores and generators.")
        clean_weights.append({key: positive(row[key]) for key in row})
    periods, assignment = data.get("periods", []), data.get("snapshot_periods", [])
    if not isinstance(periods, list) or not isinstance(assignment, list):
        raise ValueError("Periods and snapshot_periods must be lists.")
    identifiers, clean_periods = [], []
    for row in periods:
        if not isinstance(row, dict) or set(row) != {"period", "objective", "years"}:
            raise ValueError("Each period needs integer period, objective weight and years.")
        period = row["period"]
        if isinstance(period, bool) or not isinstance(period, int) or period <= 0:
            raise ValueError("Period identifiers must be positive integers.")
        identifiers.append(period)
        clean_periods.append(dict(period=period, objective=positive(row["objective"]), years=positive(row["years"])))
    if identifiers != sorted(set(identifiers)):
        raise ValueError("Periods must be unique increasing integers.")
    if periods:
        if (len(assignment) != count or any(type(p) is not int for p in assignment)
                or assignment != sorted(assignment) or sorted(set(assignment)) != identifiers):
            raise ValueError("Assign every unique timestamp to an ordered period; every declared period needs snapshots.")
    elif assignment:
        raise ValueError("snapshot_periods requires declared periods.")
    curves, seen = data.get("piecewise", []), set()
    if not isinstance(curves, list):
        raise ValueError("piecewise must be a list.")
    clean_curves = [_checked_curve(project, curve, seen) for curve in curves]
    return dict(weights=clean_weights, periods=clean_periods, snapshot_periods=assignment, piecewise=clean_curves) if any([weights, periods, curves]) else {}


def time_index(project):
    dates = pd.DatetimeIndex(project.snapshots, name="snapshot")
    periods = project.advanced_inputs.get("snapshot_periods", [])
    return pd.MultiIndex.from_arrays([periods, dates], names=["period", "timestep"]) if periods else dates


def snapshot_weights(project):
    data = project.advanced_inputs.get("weights", [])
    return pd.DataFrame(data, index=time_index(project)) if data else pd.DataFrame(
        project.duration_hours, index=time_index(project), columns=["objective", "stores", "generators"])
