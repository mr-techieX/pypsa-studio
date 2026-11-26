"""Shared Solution Explorer policy for stored PyPSA result properties."""

from functools import lru_cache
import re

from .schema import registry


# PyPSA also labels topology and calculated electrical parameters as outputs.
# These describe the model, not the solution of a run.
_MODEL_CONTEXT = {
    "Bus": {"control", "generator", "sub_network"},
    "SubNetwork": {"name", "carrier", "slack_bus"},
    **{kind: {"sub_network", "x_pu", "r_pu", "g_pu", "b_pu", "x_pu_eff", "r_pu_eff"}
       for kind in ("Line", "Transformer")},
    "ShuntImpedance": {"g_pu", "b_pu"},
}
_ADDITIONAL_PORT = re.compile(r"p(?:[2-9]|[1-9][0-9]+)")


@lru_cache(maxsize=1)
def _solved_specs():
    return {(kind, spec["name"]): spec for kind, definition in registry().items()
            for spec in definition["attributes"]
            if spec["output"] and spec["name"] not in _MODEL_CONTEXT.get(kind, ())}


def result_spec(component, attribute):
    specs = _solved_specs()
    result = specs.get((component, attribute))
    if result is None and component in {"Link", "Process"} and _ADDITIONAL_PORT.fullmatch(attribute):
        # PyPSA creates extra terminal power series on demand from the p1 schema.
        return specs.get((component, "p1"))
    return result


def is_result(component, attribute, kind):
    spec = result_spec(component, attribute)
    return bool(spec and spec["static" if kind == "static" else "varying"])


def require_results(component, properties):
    excluded = [attribute for attribute in properties if result_spec(component, attribute) is None]
    if excluded:
        raise ValueError(f"{component}: Solution Explorer only queries solved outputs. "
                         f"Input, model context, or unclassified properties: {', '.join(excluded)}. "
                         "Revise the query in Results and, for a saved dashboard, save a new dashboard.")
