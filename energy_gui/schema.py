"""Read component definitions from the installed, explicitly supported PyPSA."""

import math
import re
from functools import lru_cache

import pypsa

SUPPORTED_PYPSA = "1.4.0"


def json_value(value):
    """Make schema defaults serializable without nonstandard JSON NaN tokens."""
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
    return value


@lru_cache(maxsize=1)
def registry():
    if pypsa.__version__ != SUPPORTED_PYPSA:
        raise RuntimeError(
            f"This build supports PyPSA {SUPPORTED_PYPSA}; found {pypsa.__version__}."
        )
    network = pypsa.Network()
    result = {}
    # Iterate explicit keys: ComponentsStore iteration otherwise skips empty types.
    for key in network.components.keys():
        component = network.components[key]
        attributes = []
        for name, row in component.defaults.iterrows():
            status = str(row["status"]).strip()
            attributes.append({
                "name": name,
                "type": str(row["type"]),
                "unit": "" if str(row["unit"]) == "nan" else str(row["unit"]),
                "default": json_value(row["default"]),
                "description": str(row["description"]),
                "input": status.startswith("Input"),
                "output": status == "Output",
                "required": "required" in status,
                "static": bool(row["static"]),
                "varying": bool(row["varying"]),
                "dtype": str(row["typ"]),
            })
        result[component.name] = {
            "name": component.name,
            "list_name": component.list_name,
            "editable": any(a["input"] for a in attributes),
            "attributes": attributes,
        }
    return result


def attribute_spec(component, name):
    definition = registry().get(component)
    if definition is None:
        raise ValueError(f"Unknown component type: {component}")
    for attribute in definition["attributes"]:
        if attribute["name"] == name:
            return attribute
    # PyPSA expands Link/Process ports dynamically; do not drop these inputs.
    if component in {"Link", "Process"}:
        match = re.fullmatch(r"(bus|efficiency|rate|delay|cyclic_delay)(\d+)", name)
        if match and int(match[2]) >= 2:
            base = match[1] + "1"
            if match[1] == "efficiency" and component == "Link":
                base = "efficiency"
            for attribute in definition["attributes"]:
                if attribute["name"] == base:
                    return {**attribute, "name": name, "required": False}
    raise ValueError(f"Unknown {component} attribute: {name}")


def parse_value(spec, value):
    """Convert scalar edits strictly; strings such as 'false' must not be truthy."""
    if value is None:
        raise ValueError(f"{spec['name']}: omit the attribute to use its default.")
    dtype = spec["dtype"]
    if isinstance(value, bool) and ("int" in dtype or "float" in dtype):
        raise ValueError(f"{spec['name']}: expected a number, not a boolean.")
    if "bool" in dtype:
        if isinstance(value, bool):
            return value
        if str(value).lower() in {"true", "false"}:
            return str(value).lower() == "true"
        raise ValueError(f"{spec['name']}: expected true or false.")
    if "str" in dtype or "geometry" in dtype:
        if not isinstance(value, str):
            raise ValueError(f"{spec['name']}: expected text.")
        return value
    if "int" in dtype:
        number = float(value)
        if not math.isfinite(number) or not number.is_integer():
            raise ValueError(f"{spec['name']}: expected an integer.")
        return int(number)
    if "float" in dtype:
        number = float(value)
        if math.isnan(number):
            raise ValueError(f"{spec['name']}: NaN is not an input value.")
        return json_value(number)
    raise ValueError(f"{spec['name']}: unsupported value type {dtype}.")
