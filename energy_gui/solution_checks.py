"""Check the solved linear program itself, not nonlinear AC feasibility."""

import numpy as np
import xarray as xr


def check_solution(model, tolerance=1e-5):
    failures = []
    max_scaled = 0.0
    for name in model.constraints:
        constraint = model.constraints[name]
        lhs, rhs, sign, labels = xr.broadcast(
            constraint.lhs.solution, constraint.rhs, constraint.sign, constraint.labels
        )
        active = labels.values >= 0
        a, b, direction = lhs.values[active], rhs.values[active], sign.values[active]
        residual = np.where(direction == "=", np.abs(a-b), np.where(direction == "<=", np.maximum(a-b, 0), np.maximum(b-a, 0)))
        scaled = residual / (1 + np.abs(b))
        if not np.isfinite(scaled).all() or (scaled > tolerance).any():
            failures.append(name)
        if scaled.size:
            max_scaled = max(max_scaled, float(np.nanmax(scaled)))
    for name in model.variables:
        variable = model.variables[name]
        value, lower, upper, labels = xr.broadcast(variable.solution, variable.lower, variable.upper, variable.labels)
        active = labels.values >= 0
        x, lo, hi = value.values[active], lower.values[active], upper.values[active]
        if (not np.isfinite(x).all() or (x < lo-tolerance*(1+np.abs(x))).any() or (x > hi+tolerance*(1+np.abs(x))).any()):
            failures.append(name + " bounds")
        if variable.attrs.get("binary") or variable.attrs.get("integer"):
            if (np.abs(x-np.rint(x)) > tolerance).any():
                failures.append(name + " integrality")
    if failures:
        raise ValueError("Post-solve linear feasibility checks failed: " + ", ".join(failures))
    return {"status": "passed", "relative_tolerance": tolerance, "max_scaled_constraint_residual": max_scaled,
            "scope": "Solved linear constraints, variable bounds and integer values; not AC power-flow feasibility."}
