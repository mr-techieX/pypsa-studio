"""Schematic UI metadata and read-only frozen-run overlays; no solver mutation."""

import json
import math

import pandas as pd

from .schema import registry


def object_key(kind, name):
    return json.dumps([kind, name])


def topology(project):
    bus_keys = {r["name"]: object_key("Bus", r["name"]) for r in project.objects if r["component"] == "Bus"}
    defaults = {kind: next((a["default"] for a in spec["attributes"] if a["name"] == "carrier"), "")
                for kind, spec in registry().items()}
    objects, wires, edges, attached = [], [], [], []
    for record in project.objects:
        kind, name, attrs = record["component"], record["name"], record["attributes"]
        if kind == "Carrier":
            continue
        key = object_key(kind, name)
        ports = sorted((p for p in attrs if p == "bus" or (p.startswith("bus") and p[3:].isdigit())),
                       key=lambda p: -1 if p == "bus" else int(p[3:]))
        objects.append({"key": key, "name": name, "kind": kind,
                        "buses": [bus_keys[attrs[p]] for p in ports if attrs[p] in bus_keys],
                        "carrier": attrs.get("carrier", defaults[kind]) or "",
                        "detail": f"{kind} {name} · " + ", ".join(f"{k}={v}" for k, v in attrs.items())})
        for port in ports:
            if attrs[port] in bus_keys:
                wires.append({"a": key, "b": bus_keys[attrs[port]], "port": port})
        if kind in {"Line", "Transformer", "Link", "Process"}:
            values = [attrs[p] for p in ports if attrs[p]]
            edges.extend({"name": name, "kind": kind, "a": values[0], "b": other} for other in values[1:])
        elif "bus" in attrs:
            attached.append({"name": name, "kind": kind, "bus": attrs["bus"]})
    return {"objects": objects, "wires": wires, "edges": edges, "attached": attached,
            "buses": [{"name": r["name"], "carrier": r["attributes"].get("carrier", "AC")}
                      for r in project.objects if r["component"] == "Bus"]}


def checked_layout(layout, keys):
    """Validate a bounded UI-only payload, keeping only extant object positions."""
    def number(value, low, high):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError("Layout coordinates, zoom and viewport must be finite and within supported bounds.")
        return float(value)

    if not isinstance(layout, dict) or not isinstance(layout.get("positions"), dict) or len(layout["positions"]) > 10000:
        raise ValueError("Invalid schematic layout (maximum 10000 positions).")
    # These are logical workspace dimensions, not a graphics texture allocation:
    # the QML wire/grid Canvas now renders only the visible viewport.
    width = number(layout.get("width", 900), 900, 100000)
    height = number(layout.get("height", 520), 520, 100000)
    paper_version = layout.get("paperVersion")
    if paper_version is not None and (type(paper_version) is not int or paper_version != 1):
        raise ValueError("Unsupported schematic workspace version.")
    positions = {}
    for key, point in layout["positions"].items():
        if not isinstance(point, dict):
            raise ValueError("Invalid schematic position.")
        x, y = number(point.get("x"), 0, 100000), number(point.get("y"), 0, 100000)
        if x > width or y > height:
            raise ValueError("Schematic positions must lie within the saved canvas.")
        if key in keys:
            positions[key] = {"x": x, "y": y}
    return {"positions": positions, "zoom": number(layout.get("zoom", 1), 0.1, 3),
            "panX": number(layout.get("panX", 0), 0, 400000), "panY": number(layout.get("panY", 0), 0, 400000),
            "width": width, "height": height, **({"paperVersion": 1} if paper_version is not None else {})}


def saved_layout(project, key, graph):
    try:
        return checked_layout(project.schematic_layouts.get(key, {}), {o["key"] for o in graph["objects"]})
    except (ValueError, TypeError, AttributeError):
        return {}  # Broken optional UI metadata must not prevent opening the model.


def edit_layout_identity(project, kind, old, new=None):
    """Only the live layout follows identity edits; historical layouts stay frozen."""
    layout = project.schematic_layouts.get("current", {})
    positions = layout.get("positions", {}) if isinstance(layout, dict) else {}
    if not isinstance(positions, dict):
        return
    key = object_key(kind, old)
    if key in positions:
        point = positions.pop(key)
        if new is not None:
            positions[object_key(kind, new)] = point


def frozen_overlay(repository, snapshot):
    """Use actual exported port outputs; never derive missing flows from defaults.

    p_i > 0 withdraws from bus_i into the branch. Passive p0 utilisation is the
    standard linear active-flow bound, NOT AC apparent-power/thermal loading.
    Link/Process percentages are deliberately unavailable (direction/port bounds).
    """
    project = repository.project
    if snapshot not in project.snapshots:
        raise ValueError("Select an exact snapshot from this frozen run.")
    graph = topology(project)
    records = {object_key(r["component"], r["name"]): r for r in project.objects}
    buses = {r["name"]: r for r in project.objects if r["component"] == "Bus"}
    cache = {}

    def value(kind, name, attribute, output=False):
        cache_key = kind, attribute, output
        if cache_key not in cache:
            category = repository.categories.get(kind, {})
            props = {p["name"] for p in category.get("properties", [])}
            names = category.get("objects", [])
            result = {}
            try:
                if kind in {"Line", "Transformer"} and attribute in {"s_nom", "s_max_pu"}:
                    result = repository.branch_bound_inputs(kind, attribute, snapshot)
                elif attribute in props and names and (not output or attribute in category.get("series_files", {})):
                    if output:
                        frame = repository._read(category["series_files"][attribute])
                        rows = repository.series_index(category["series_files"][attribute]) == pd.Timestamp(snapshot)
                        if rows.sum() == 1:
                            result = {n: frame.loc[rows, n].iloc[0] for n in names if n in frame.columns[1:]}
                    else:
                        frame, _, _ = repository.query(kind, names, [attribute], snapshot, snapshot)
                        result = dict(zip(frame["object"], frame[attribute]))
            except (ValueError, OSError, KeyError):
                pass
            cache[cache_key] = result
        raw = cache[cache_key].get(name)
        try:
            return float(raw) if raw is not None and math.isfinite(float(raw)) else None
        except (TypeError, ValueError):
            return None

    port_details = {}
    for wire in graph["wires"]:
        record = records[wire["a"]]
        kind, name, attrs = record["component"], record["name"], record["attributes"]
        wire.update(flow=None, unit="", unavailable="No branch port output", utilisation=None)
        if kind not in {"Line", "Transformer", "Link", "Process"} or wire["port"] == "bus":
            continue
        bus = buses[attrs[wire["port"]]]
        unit = bus["attributes"].get("unit", "") or "MW"
        attribute = "p" + wire["port"][3:]
        wire.update(attribute=attribute, unit=unit)
        if unit != "MW":
            wire["unavailable"] = f"Unsupported port unit {unit}; MW overlays only"
        else:
            wire["flow"] = value(kind, name, attribute, output=True)
            wire["unavailable"] = "Missing/non-finite port output" if wire["flow"] is None else ""
        if kind in {"Line", "Transformer"} and attrs.get("active", True) and wire["port"] == "bus0" and wire["flow"] is not None:
            extendable = attrs.get("s_nom_extendable", False)
            capacity = value(kind, name, "s_nom_opt" if extendable else "s_nom")
            bound = value(kind, name, "s_max_pu")
            limit = capacity * bound if capacity is not None and bound is not None else None
            if capacity is not None and bound is not None and capacity > 0 and bound > 0 and limit > 0 and math.isfinite(limit):
                percent = abs(wire["flow"]) / limit * 100
                wire["utilisation"] = percent if math.isfinite(percent) else None
        text = f"{attribute} ({wire['port']}={bus['name']}): "
        text += f"{wire['flow']:.3f} MW" if wire["flow"] is not None else wire["unavailable"]
        if wire["utilisation"] is not None:
            text += f" · p0 bound use {wire['utilisation']:.1f}% (linear active-flow limit, not AC MVA loading)"
        port_details.setdefault(wire["a"], []).append(text)
    for obj in graph["objects"]:
        details = port_details.get(obj["key"], [])
        if obj["kind"] in {"Link", "Process"}:
            details.append("Loading percentage unavailable for this converter; no rating/directional bound is inferred.")
        obj["detail"] = f"Frozen {obj['kind']} {obj['name']} · {snapshot}\n" + ("\n".join(details) or obj["detail"])
    return graph
