"""Portable project records and pre-solve validation, independent of Qt."""

from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields
import math
import re
import uuid

import pandas as pd

from .schema import SUPPORTED_PYPSA, attribute_spec, parse_value, registry

SCHEMA_VERSION = 1


@dataclass
class Project:
    name: str = "Untitled energy system"
    currency: str = "INR"
    pypsa_version: str = SUPPORTED_PYPSA
    snapshots: list[str] = field(default_factory=lambda: ["2026-01-01T00:00:00"])
    duration_hours: float = 1.0
    objects: list[dict] = field(default_factory=list)
    profiles: list[dict] = field(default_factory=list)
    project_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    editor_config: dict = field(default_factory=dict)
    schematic_layouts: dict = field(default_factory=dict)
    demo_info: dict = field(default_factory=dict)
    analysis_workspace: list = field(default_factory=list)
    scenario_library: list = field(default_factory=list)
    advanced_inputs: dict = field(default_factory=dict)
    interchange_info: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

    def model_state(self):
        """Transient comparison view; never retain it as a mutable baseline."""
        from .layout_state import sheet_state
        return sheet_state({spec.name: getattr(self, spec.name) for spec in fields(self)})

    def history_snapshot(self):
        """Detached undo payload; inert conversion metadata stays on the project."""
        return {spec.name: deepcopy(getattr(self, spec.name)) for spec in fields(self)
                if spec.name != "interchange_info"}

    def set_horizon(self, start, count, minutes):
        count, minutes = int(count), int(minutes)
        if not 1 <= count <= 100000 or minutes <= 0:
            raise ValueError("Use 1–100000 snapshots and a positive interval in minutes.")
        dates = pd.date_range(start, periods=count, freq=pd.Timedelta(minutes=minutes))
        if dates.tz is not None:
            raise ValueError("Use timezone-naive timestamps in a documented local time zone.")
        if self.profiles and [d.isoformat() for d in dates] != self.snapshots:
            raise ValueError("Remove imported profiles before changing the time horizon.")
        if self.advanced_inputs and [d.isoformat() for d in dates] != self.snapshots:
            raise ValueError("Clear advanced time/curve inputs before changing the horizon.")
        self.snapshots = [d.isoformat() for d in dates]
        self.duration_hours = minutes / 60

    def object(self, component, name):
        return next((o for o in self.objects if o["component"] == component and o["name"] == name), None)

    def upsert(self, component, name, attributes):
        name = str(name).strip()
        if not name or not registry()[component]["editable"]:
            raise ValueError("Provide a name for an editable component.")
        clean = {}
        for key, value in attributes.items():
            spec = attribute_spec(component, key)
            if key == "name" or not spec["input"] or not spec["static"]:
                raise ValueError(f"{component}.{key} is not an editable static input.")
            clean[key] = parse_value(spec, value)
        record = {"component": component, "name": name, "attributes": clean}
        previous = self.object(component, name)
        if previous:
            self.objects[self.objects.index(previous)] = record
        else:
            self.objects.append(record)

    def delete(self, component, name):
        from .object_edits import delete_candidate
        candidate = delete_candidate(self, [{"component": component, "name": name}])
        self.objects, self.profiles = candidate.objects, candidate.profiles

    def validate(self):
        errors = []
        if self.pypsa_version != SUPPORTED_PYPSA:
            errors.append(f"Project targets unsupported PyPSA {self.pypsa_version}.")
        try:
            index = pd.DatetimeIndex(self.snapshots)
        except (ValueError, TypeError):
            index = pd.DatetimeIndex([])
            errors.append("Snapshots could not be parsed as timestamps.")
        if index.empty or index.hasnans or index.has_duplicates or not index.is_monotonic_increasing or index.tz is not None:
            errors.append("Snapshots must be unique, ordered, timezone-naive timestamps.")
        if not math.isfinite(self.duration_hours) or self.duration_hours <= 0:
            errors.append("Snapshot duration must be positive and finite.")
        identities = [(o["component"], o["name"]) for o in self.objects]
        if len(set(identities)) != len(identities):
            errors.append("Duplicate component names within a component type.")
        buses = {o["name"] for o in self.objects if o["component"] == "Bus"}
        if not buses:
            errors.append("At least one Bus is required.")
        for record in self.objects:
            component, name, attrs = record["component"], record["name"], record["attributes"]
            definition = registry().get(component)
            if definition is None or not definition["editable"]:
                errors.append(f"{component} {name}: unknown or derived component.")
                continue
            for spec in definition["attributes"]:
                if spec["required"] and re.fullmatch(r"bus\d*", spec["name"]) and not attrs.get(spec["name"]):
                    errors.append(f"{component} {name}: {spec['name']} is required.")
            for key, value in attrs.items():
                try:
                    spec = attribute_spec(component, key)
                    if not spec["input"] or not spec["static"] or key == "name":
                        raise ValueError("not an editable static input")
                    parse_value(spec, value)
                except (ValueError, TypeError) as error:
                    errors.append(f"{component} {name}.{key}: {error}")
                if re.fullmatch(r"bus\d*", key) and value and value not in buses:
                    errors.append(f"{component} {name}.{key}: missing Bus '{value}'.")
                # Initial study is LP/MILP, even though HiGHS also has QP capabilities.
                if key == "marginal_cost_quadratic":
                    try:
                        if float(value) != 0:
                            errors.append(f"{component} {name}: quadratic costs are outside the initial LP/MILP workflow.")
                    except (ValueError, TypeError):
                        pass  # Invalid scalar is already reported above.
            if component == "Line" and not attrs.get("type") and attrs.get("x", 0) == 0:
                errors.append(f"Line {name}: supply nonzero total reactance x (ohm) or a valid line type.")
            if component in {"Line", "Transformer"} and attrs.get("bus0") == attrs.get("bus1"):
                errors.append(f"{component} {name}: endpoints must differ.")
            if component == "Bus":
                try:
                    if float(attrs.get("v_nom", 1)) <= 0:
                        errors.append(f"Bus {name}: v_nom must be positive (kV).")
                except (ValueError, TypeError):
                    pass  # Schema parsing already reports malformed values.
        seen = set()
        for profile in self.profiles:
            key = (profile["component"], profile["name"], profile["attribute"])
            try:
                spec = attribute_spec(key[0], key[2])
                if not spec["input"] or not spec["varying"]:
                    raise ValueError("attribute is not a time-varying input")
                if key in seen:
                    raise ValueError("duplicate profile")
                if self.object(key[0], key[1]) is None:
                    raise ValueError("component does not exist")
                if len(profile["values"]) != len(index):
                    raise ValueError("profile length differs from snapshots")
                if any(not math.isfinite(float(v)) for v in profile["values"]):
                    raise ValueError("profile contains non-finite values")
                if key[2] == "marginal_cost_quadratic" and any(float(v) != 0 for v in profile["values"]):
                    raise ValueError("quadratic costs are outside the LP/MILP workflow")
                seen.add(key)
            except (ValueError, TypeError) as error:
                errors.append(f"Profile {'.'.join(key)}: {error}")
        from .validation import engineering_errors
        from .advanced import checked_advanced
        try:
            checked_advanced(self, self.advanced_inputs)
        except (ValueError, TypeError, KeyError) as error:
            errors.append("Advanced inputs: " + str(error))
        return errors + engineering_errors(self)
