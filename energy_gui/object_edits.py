"""Atomic identity edits with explicit PyPSA 1.4 reference semantics (no Qt)."""

from copy import deepcopy
from functools import lru_cache
import re

from .project import Project
from .schema import registry
from .network_view import edit_layout_identity


@lru_cache(maxsize=1)
def standard_names():
    import pypsa
    network = pypsa.Network()
    return {kind: set(network.components[kind].static.index)
            for kind in ("LineType", "TransformerType")}


def shape_kind(value):
    aliases = {alias: kind for kind, spec in registry().items()
               for alias in (kind, spec["list_name"])}
    return aliases.get(value)


def references(project):
    """Yield (owner, field, target kind, target name, selector-list flag)."""
    for record in project.objects:
        kind, attrs = record["component"], record["attributes"]
        # Include implicit defaults, notably Bus.carrier='AC'. Materialise them
        # on rename, rather than leaving a default pointing to the former name.
        fields = {a["name"]: a["default"] for a in registry()[kind]["attributes"]
                  if a["input"] and a["static"]}
        fields.update(attrs)
        for key, value in fields.items():
            if not value or not isinstance(value, str):
                continue
            if re.fullmatch(r"bus\d*", key):
                yield record, key, "Bus", value, False
            elif key == "carrier":
                yield record, key, "Carrier", value, False
            elif key == "type" and kind in {"Line", "Transformer"}:
                yield record, key, kind + "Type", value, False
        if kind == "Shape" and attrs.get("idx"):
            yield record, "idx", shape_kind(attrs.get("component", "")) or "?", attrs["idx"], False
        if kind == "GlobalConstraint":
            value = fields["carrier_attribute"]
            formulation = fields["type"]
            if formulation in {"tech_capacity_expansion_limit", "operational_limit"}:
                yield record, "carrier_attribute", "Carrier", value, False
            elif formulation in {"transmission_volume_expansion_limit", "transmission_expansion_cost_limit"}:
                for token in re.sub(r"[\[\]\(\)]", "", value).split(","):
                    if token.strip():
                        yield record, "carrier_attribute", "Carrier", token.strip(), True
            elif formulation != "primary_energy":
                # Unknown semantics must not be guessed or silently rewritten.
                yield record, "carrier_attribute", "?", value, False
                for token in re.sub(r"[\[\]\(\)]", "", value).split(","):
                    if token.strip():
                        yield record, "carrier_attribute", "?", token.strip(), False


def identities(project, records):
    chosen = {(r["component"], r["name"]) for r in records}
    if not chosen or len(chosen) != len(records):
        raise ValueError("Choose existing objects without duplicates.")
    for kind, name in chosen:
        if kind not in registry() or not registry()[kind]["editable"] or not project.object(kind, name):
            raise ValueError(f"Unknown or non-editable object: {kind} {name}.")
    return chosen


def deletion_preview(project, records):
    chosen = identities(project, records)
    blockers = []
    for owner, field, target_kind, target, _ in references(project):
        if (owner["component"], owner["name"]) in chosen:
            continue
        if ((target_kind, target) in chosen or
                (target_kind == "?" and any(name == target for _, name in chosen))):
            blockers.append(f"Referenced by {owner['component']} {owner['name']}.{field} → {target}.")
    profiles = [p for p in project.profiles if (p["component"], p["name"]) in chosen]
    return {"objects": [f"{kind} {name}" for kind, name in sorted(chosen)],
            "profiles": [f"{p['component']} {p['name']}.{p['attribute']}" for p in profiles] +
                        [f"Piecewise {p['component']} {p['name']}.{p['attribute']}" for p in project.advanced_inputs.get("piecewise", []) if (p["component"], p["name"]) in chosen],
            "blockers": sorted(set(blockers))}


def delete_candidate(project, records):
    preview = deletion_preview(project, records)
    if preview["blockers"]:
        raise ValueError("Deletion blocked. Include or edit the referencing objects first.\n" + "\n".join(preview["blockers"]))
    chosen = identities(project, records)
    candidate = Project(**deepcopy(project.to_dict()))
    candidate.objects = [r for r in candidate.objects if (r["component"], r["name"]) not in chosen]
    candidate.profiles = [p for p in candidate.profiles if (p["component"], p["name"]) not in chosen]
    if candidate.advanced_inputs.get("piecewise"):
        candidate.advanced_inputs["piecewise"] = [p for p in candidate.advanced_inputs["piecewise"] if (p["component"], p["name"]) not in chosen]
    for kind, name in chosen:
        edit_layout_identity(candidate, kind, name)
    return candidate


def rename_candidate(project, kind, old, new):
    identities(project, [{"component": kind, "name": old}])
    new = str(new).strip()
    if not new or any(ord(c) < 32 for c in new):
        raise ValueError("Use a nonempty name without control characters.")
    if new == old:
        raise ValueError("The new name is unchanged.")
    if project.object(kind, new) or new in standard_names().get(kind, set()):
        raise ValueError("The new name already exists (including built-in standard types).")
    if any(target_kind == kind and target == new
           for _, _, target_kind, target, _ in references(project)):
        raise ValueError("The new name is already used by references, including implicit defaults; merging identities is not supported.")
    candidate = Project(**deepcopy(project.to_dict()))
    updates = []
    for owner, field, target_kind, target, is_list in list(references(candidate)):
        if target != old:
            continue
        if target_kind == "?":
            raise ValueError(f"Ambiguous reference in {owner['component']} {owner['name']}.{field}; resolve it before renaming.")
        if target_kind != kind:
            continue
        if kind == "Carrier" and {old, new} & {"AC", "DC"} and owner["component"] in {"Bus", "Line"}:
            raise ValueError("AC/DC electrical carrier labels affect power-flow semantics and cannot be renamed while used by buses/lines.")
        if is_list:
            if any(c in new for c in ",[]()"):
                raise ValueError("Carrier selectors cannot represent names containing commas or brackets unambiguously.")
            tokens = re.sub(r"[\[\]\(\)]", "", owner["attributes"][field]).split(",")
            owner["attributes"][field] = ", ".join(new if t.strip() == old else t.strip() for t in tokens)
        else:
            owner["attributes"][field] = new
        updates.append(f"{owner['component']} {owner['name']}.{field}")
    candidate.object(kind, old)["name"] = new
    edit_layout_identity(candidate, kind, old, new)
    for profile in candidate.profiles:
        if (profile["component"], profile["name"]) == (kind, old):
            profile["name"] = new
            updates.append(f"Profile {profile['attribute']}")
    for curve in candidate.advanced_inputs.get("piecewise", []):
        if (curve["component"], curve["name"]) == (kind, old):
            curve["name"] = new
            updates.append("Piecewise " + curve["attribute"])
    return candidate, sorted(set(updates))
