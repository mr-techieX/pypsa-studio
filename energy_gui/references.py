"""Local, read-only schema and curated reference help; never opens remote URLs."""

from functools import lru_cache
from pathlib import Path
import re

from .editor_config import property_specs
from .schema import SUPPORTED_PYPSA, attribute_spec, registry

REFERENCE_DIRECTORY = Path(__file__).resolve().parents[1] / "Attribute-Info"
if not REFERENCE_DIRECTORY.is_dir():
    REFERENCE_DIRECTORY = Path(__file__).resolve().parents[3] / "Attribute-Info"


@lru_cache(maxsize=32)
def reference_document(component):
    if component not in registry() and component != "Network":
        raise ValueError("Choose a known reference class.")
    slug = re.sub(r"(?<!^)(?=[A-Z])", "-", component).lower()
    path = REFERENCE_DIRECTORY / f"{slug}-attribute.md"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return f"# {component}\n\nThe curated guide is not included at this location. Installed PyPSA {SUPPORTED_PYPSA} schema details remain available for component properties."


def network_entries():
    entries = {}
    for line in reference_document("Network").splitlines():
        match = re.match(r"^\| `([^`]+)` \|", line)
        if not match:
            continue
        name = match[1]
        if name.startswith("network."):
            name = name.removeprefix("network.").split("(")[0]
        fields = [field.strip() for field in line.split("|")[2:-1]]
        if len(fields) >= 2 and name not in entries:
            entries[name] = {"name": name, "type": fields[0], "unit": "", "default": fields[1] if len(fields) > 2 else "See call pattern",
                             "description": fields[-1], "input": False, "required": False, "static": False, "varying": False}
    return list(entries.values())


def reference_catalogue(project):
    # Help includes hidden categories/fields and outputs, independent of editor
    # visibility. Existing extra Link/Process ports are included as well.
    return {**{name: property_specs(project, name) for name in registry()}, "Network": network_entries()}


def property_reference(project, component, name):
    guide = reference_document(component)
    if not name:
        return {"component": component, "name": "", "description": "Select a property for its exact definition, units and default.", "guide": guide}
    try:
        if component == "Network":
            spec = next((entry for entry in network_entries() if entry["name"] == name), None)
            if spec is None:
                raise ValueError("Unknown Network reference entry.")
        else:
            spec = attribute_spec(component, name)
        return {**spec, "component": component, "guide": guide}
    except ValueError:
        return {"component": component, "name": name, "description": "This property is not in the installed base schema. Consult the class guide and the saved run table; no default or unit is inferred.", "guide": guide}
