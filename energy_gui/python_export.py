"""Render one frozen Studio solve as editable, standalone PyPSA code."""

from math import isfinite, isnan
from pathlib import Path

from .advanced import native_piecewise_options
from .schema import attribute_spec, SUPPORTED_PYPSA


def literal(value):
    if isinstance(value, float) and not isfinite(value):
        return f"float({('nan' if isnan(value) else str(value))!r})"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{literal(k)}: {literal(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(map(literal, value)) + "]"
    return repr(value)


def render_sequence(step_count):
    source = Path(__file__).with_name("sequence_replay.py").read_text(encoding="utf-8")
    return source + f'\n\nif __name__ == "__main__":\n    run_sequence(Path(__file__).resolve().parent, {step_count})\n'


def render_script(project, step=False):
    advanced = project.advanced_inputs
    periods = advanced.get("periods", [])
    dates = f"pd.DatetimeIndex({literal(project.snapshots)}, name='snapshot')"
    axis = (f"pd.MultiIndex.from_arrays([{literal(advanced['snapshot_periods'])}, {dates}], "
            "names=['period', 'timestep'])") if periods else dates
    lines = [
        f"# PyPSA {SUPPORTED_PYPSA}; solver: HiGHS (highspy).",
        "import pandas as pd",
        "import pypsa",
        "",
        f"n = pypsa.Network(name={project.name!r})",
        f"n.set_snapshots({axis}, default_snapshot_weightings={float(project.duration_hours)!r})",
    ]
    if advanced.get("weights"):
        lines.append(f"n.snapshot_weightings = pd.DataFrame({literal(advanced['weights'])}, index=n.snapshots)")
    if periods:
        lines.extend([
            f"n.set_investment_periods({literal([p['period'] for p in periods])})",
            f"n.investment_period_weightings = pd.DataFrame({literal(periods)}).set_index('period')",
        ])
    order = {"Carrier": 0, "LineType": 1, "TransformerType": 1, "Bus": 2, "Shape": 9}
    curves = {}
    for curve in advanced.get("piecewise", []):
        curves.setdefault((curve["component"], curve["name"]), {})[curve["attribute"]] = dict(curve["points"])
    lines.append("")
    for record in sorted(project.objects, key=lambda row: order.get(row["component"], 5)):
        kind, name = record["component"], record["name"]
        attributes = {}
        for key, value in record["attributes"].items():
            dtype = attribute_spec(kind, key)["dtype"]
            if "geometry" in dtype:
                if "from shapely import from_wkt" not in lines:
                    lines.insert(3, "from shapely import from_wkt")
                attributes[key] = f"from_wkt({literal(value)})"
            else:
                attributes[key] = literal(float(value) if "float" in dtype else value)
        attributes.update({key: literal(value) for key, value in curves.get((kind, name), {}).items()})
        args = "".join(f", {key}={value}" for key, value in attributes.items())
        lines.append(f"n.add({kind!r}, {name!r}{args})")
    if project.profiles:
        lines.append("")
    for profile in project.profiles:
        kind, attribute, name = (profile[key] for key in ("component", "attribute", "name"))
        lines.append(
            f"n.components[{kind!r}].dynamic[{attribute!r}][{name!r}] = "
            f"pd.Series({literal(profile['values'])}, index=n.snapshots)"
        )
    options = native_piecewise_options(project)
    args = ", multi_investment_periods=True" if periods else ""
    if options:
        args += f", piecewise_options={literal(options)}"
    solve = [
        "n.consistency_check(strict=['all'])",
        f"status, condition = n.optimize(solver_name='highs', threads=1, include_objective_constant=True{args})",
        "if (status, condition) != ('ok', 'optimal'):",
        "    raise RuntimeError(f'Optimization failed: {status} / {condition}')",
    ]
    if step:
        start = lines.index(f"n = pypsa.Network(name={project.name!r})")
        lines = lines[:start] + ["def build_network():"] + [
            "    " + line if line else "" for line in lines[start:]
        ] + [
            "    return n", "", "", "def solve(n):",
            *("    " + line for line in solve),
            "", "", 'if __name__ == "__main__":',
            "    n = build_network()", "    solve(n)", "    print(n.objective)",
        ]
        return "\n".join(lines) + "\n"
    lines += [
        "",
        *solve,
        "print(n.objective)",
    ]
    return "\n".join(lines) + "\n"
