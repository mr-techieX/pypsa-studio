"""Read-only input screening and explanations of existing run failures (no Qt).

Public contracts:
* ``diagnose_project(project)`` returns JSON-safe errors/warnings/checks. Every
  finding has code, label, message, supported input field labels, and details.
* ``format_diagnostics(report, *, max_items=40, max_chars=16000)`` is a bounded
  plain-text preview, not an HTML renderer or a complete export.
* ``explain_run_failure(run_directory)`` reads only four fixed artifact names;
  it does not load a network, solve, generate an IIS, repair, or write anything.

Connectivity is undirected *potential* connectivity, including conversion ports,
not a PyPSA passive SubNetwork or a test of deliverability. Capacity comparisons
evaluate all snapshots but omit expansion, conversion and storage contributions.
They are warnings, never certificates of feasibility or infeasibility.
"""

from collections import defaultdict
import json
import math
from pathlib import Path
import re
import stat

import numpy as np

from .schema import attribute_spec, registry
from .run_layout import metadata_path
from .validation import formulation_warnings


MAX_FINDINGS = 200  # Per category; counts include findings omitted from previews.
MAX_PREVIEW = 8  # Snapshot, island and object examples in structured details.
MAX_MESSAGE = 2000
MAX_TEXT = 16000
MAX_CONFIG_BYTES = 65536
MAX_LOG_BYTES = 65536  # Per log, a head and tail when the file is larger.
_TRUNCATED = "\n[Preview truncated; inspect the source for complete details.]"
_SCOPE = (
    "Read-only structural screening, not an infeasibility proof or feasibility "
    "guarantee. No solve, IIS/conflict analysis or automatic fix is performed."
)
_SCREEN_FIELDS = [
    "Load.bus", "Load.p_set", "Load.sign", "Generator.bus",
    "Generator.p_nom", "Generator.p_max_pu", "Generator.active",
    "Generator.p_nom_extendable",
]
_SCREEN_LIMITS = (
    "Screening only: positive demand is max(-Load.sign * Load.p_set, 0); "
    "fixed available capacity is max(Generator.p_nom * Generator.p_max_pu, 0) "
    "for active, non-extendable, sign=1 generators, with scalar/profile fallback. "
    "Extendable capacity, storage dispatch/inflow, Link/Process conversion, "
    "negative-load injections and nonstandard Generator.sign are omitted. "
    "Branch limits/directions, commitment, maintenance, ramping, dispatch/energy "
    "targets and global constraints are not solved. Gross totals across carriers "
    "are not a conserved balance: carriers are not interchangeable. Values are "
    "power, not weighted energy; a deficit is not an infeasibility proof, and a "
    "surplus does not establish feasibility."
)


def _clip(text, limit):
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:max(0, limit - len(_TRUNCATED))] + _TRUNCATED[:limit]


def _plain(value, limit=MAX_MESSAGE, *, single_line=False):
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(value))
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text)
    if single_line:
        text = " ".join(text.split())
    return _clip(text, limit)


def _enabled(attrs, field="active", default=True):
    value = attrs.get(field, default)
    return value is True or (not isinstance(value, bool) and str(value).lower() == "true")


def _supported(fields):
    """Only advertise installed input fields; extra ports use schema expansion."""
    result = []
    for field in fields:
        kind, key = field.split(".", 1)
        try:
            if attribute_spec(kind, key)["input"]:
                result.append(field)
        except ValueError:
            continue
    return result


def _add(report, category, code, label, message, fields=(), details=None, *, priority=False):
    report["counts"][category] += 1
    if len(report[category]) < MAX_FINDINGS or priority:
        finding = {
            "code": code, "label": _plain(label, 240, single_line=True),
            "message": _plain(message), "fields": _supported(fields),
            "details": details or {},
        }
        if priority:
            report[category].insert(0, finding)
            if len(report[category]) > MAX_FINDINGS:
                report[category].pop()
                report["truncated"][category] += 1
        else:
            report[category].append(finding)
    else:
        report["truncated"][category] += 1


def _validation_fields(message):
    match = re.match(r"(?:Profile )?([A-Za-z]+)\b", str(message))
    definition = registry().get(match[1]) if match else None
    if definition is None:
        return []
    tokens = set(re.findall(r"\b[A-Za-z_]\w*\b", str(message)))
    return [f"{match[1]}.{spec['name']}" for spec in definition["attributes"]
            if spec["input"] and spec["name"] in tokens and spec["name"] != "name"]


def _connectivity(records):
    """Union/find: O(bus + port count), without repeatedly scanning each bus."""
    buses = {r["name"]: r["attributes"] for r in records if r["component"] == "Bus"}
    parent = {name: name for name in buses}
    size = dict.fromkeys(buses, 1)

    def find(name):
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    for record in records:
        attrs = record["attributes"]
        if record["component"] not in {"Line", "Transformer", "Link", "Process"} or not _enabled(attrs):
            continue
        ports = [v for k, v in attrs.items() if re.fullmatch(r"bus\d+", k) and isinstance(v, str) and v in buses]
        if not ports:
            continue
        for bus in ports[1:]:
            a, b = find(ports[0]), find(bus)
            if a != b:
                if size[a] < size[b]:
                    a, b = b, a
                parent[b] = a
                size[a] += size[b]
    groups = defaultdict(list)
    for bus in buses:
        groups[find(bus)].append(bus)
    islands = list(groups.values())
    by_bus = {bus: index for index, group in enumerate(islands) for bus in group}
    return buses, islands, by_bus


def _finite_input_findings(project, report):
    # Project.validate is authoritative for ordinary parsing and engineering
    # errors. It permits infinity for floats; additionally reject it where the
    # installed default does not explicitly describe an unbounded input.
    for record in project.objects:
        kind, name, attrs = record["component"], record["name"], record["attributes"]
        for key, value in attrs.items():
            try:
                spec = attribute_spec(kind, key)
                if not spec["input"] or "float" not in spec["dtype"]:
                    continue
                number = float(value)
            except (ValueError, TypeError, OverflowError):
                continue  # Reported by Project.validate; do not guess a value.
            if math.isinf(number) and spec["default"] not in {"inf", "-inf"}:
                _add(report, "errors", "nonfinite_input", f"{kind} {name}.{key}",
                     f"{kind} {name}.{key}: expected a finite input. Review this value and its units; no value was changed.",
                     [f"{kind}.{key}"])


def _guidance(project, report):
    groups = defaultdict(list)
    for record in project.objects:
        if _enabled(record["attributes"]):
            groups[record["component"]].append(record)
    committed = [r for kind in ("Generator", "Link", "Process") for r in groups[kind]
                 if _enabled(r["attributes"], "committable", False)]
    if committed:
        fields = [f"{kind}.{key}" for kind in dict.fromkeys(r["component"] for r in committed)
                  for key in ("committable", "p_nom", "p_nom_extendable", "p_min_pu", "p_max_pu",
                              "min_up_time", "min_down_time", "up_time_before", "down_time_before",
                              "ramp_limit_up", "ramp_limit_down", "ramp_limit_start_up", "ramp_limit_shut_down")]
        _add(report, "checks", "commitment_guidance", "Unit commitment and ramping",
             "Review minimum output, on/off history, minimum up/down times and start/stop ramp limits together. "
             "Minimum times count snapshots, not weighted hours; ramp limits are not automatically duration-scaled. "
             "Fixed available capacity is an optimistic upper bound, not a commitment schedule. "
             "Check the supported committable/extendable combination before solving.", fields,
             {"object_count": len(committed), "objects": [_plain(r["name"], 160) for r in committed[:MAX_PREVIEW]]})
    for kind, keys in {
        "StorageUnit": ["bus", "p_nom", "p_nom_extendable", "max_hours", "p_min_pu", "p_max_pu",
                        "state_of_charge_initial", "state_of_charge_set", "cyclic_state_of_charge",
                        "state_of_charge_initial_per_period", "cyclic_state_of_charge_per_period",
                        "efficiency_store", "efficiency_dispatch", "standing_loss", "inflow"],
        "Store": ["bus", "e_nom", "e_nom_extendable", "e_min_pu", "e_max_pu", "e_initial", "e_set",
                  "e_cyclic", "e_initial_per_period", "e_cyclic_per_period", "p_set", "standing_loss"],
    }.items():
        if groups[kind]:
            _add(report, "checks", "storage_guidance", f"{kind} energy and boundary conditions",
                 "Storage contribution is omitted from the capacity screen, not assumed unavailable. "
                 "Review initial/target energy, cyclic boundaries, energy and power bounds, efficiencies, "
                 "losses and inflow where applicable. Check Snapshot duration / advanced weights.stores "
                 "(elapsed hours); MW and MWh are different. A cyclic store cannot be assumed initially full.",
                 [f"{kind}.{key}" for key in keys], {"object_count": len(groups[kind])})
    if groups["GlobalConstraint"]:
        _add(report, "checks", "global_constraint_guidance", "Global constraints and accounting",
             "Review type, sense, constant, bus scope and investment_period. Equality requires the exact "
             "total; a maximum budget usually uses <=. carrier_attribute selects either a Carrier coefficient "
             "or a technology carrier depending on type. Check Generator.carrier/efficiency, Carrier.co2_emissions, "
             "snapshot generator weights and investment-period accounting. The capacity screen does not test budgets.",
             [f"GlobalConstraint.{key}" for key in ("type", "sense", "constant", "bus", "investment_period", "carrier_attribute")]
             + ["Generator.carrier", "Generator.efficiency", "Carrier.co2_emissions"],
             {"object_count": len(groups["GlobalConstraint"])})
    conversions = groups["Link"] + groups["Process"]
    if conversions:
        _add(report, "checks", "conversion_guidance", "Conversion and controllable transfers",
             "Connectivity includes every declared Link/Process bus port as undirected potential connectivity. "
             "It does not establish a usable supply path. Conversion output, efficiencies/rates, reverse-flow "
             "bounds, capacity and delays are omitted from the capacity comparison; review the numbered ports too.",
             ["Link.bus0", "Link.bus1", "Link.efficiency", "Link.p_nom", "Link.p_min_pu", "Link.p_max_pu",
              "Process.bus0", "Process.bus1", "Process.rate0", "Process.rate1", "Process.p_nom"],
             {"object_count": len(conversions)})


def _series(record, attribute, profiles, default):
    key = record["component"], record["name"], attribute
    value = profiles.get(key, record["attributes"].get(attribute, default))
    return np.asarray(value, dtype=float)


def _aggregate(records, profiles, periods, *, demand):
    # Scalars accumulate in O(objects); only genuine profiles/activity masks
    # require snapshot vectors. There is no bus-by-snapshot dense matrix.
    scalar = 0.0
    vector = None
    for record in records:
        attrs = record["attributes"]
        if demand:
            value = np.maximum(-float(attrs.get("sign", -1)) * _series(record, "p_set", profiles, 0), 0)
        else:
            if _enabled(attrs, "p_nom_extendable", False) or float(attrs.get("sign", 1)) != 1:
                continue
            value = float(attrs.get("p_nom", 0)) * np.maximum(_series(record, "p_max_pu", profiles, 1), 0)
        if periods is not None:
            year, lifetime = float(attrs.get("build_year", 0)), float(attrs.get("lifetime", "inf"))
            value = value * ((periods >= year) & (periods < year + lifetime))
        if value.ndim == 0:
            scalar += float(value)
        elif vector is None:
            vector = value.copy()
        else:
            vector += value
    return np.asarray(scalar) if vector is None else vector + scalar


def _screen_details(demand, capacity, snapshots, scope, unit):
    difference = demand - capacity
    if not (np.isfinite(demand).all() and np.isfinite(capacity).all() and np.isfinite(difference).all()):
        raise ValueError("Aggregated demand/capacity overflowed; review magnitudes and input units.")
    # A relative tolerance avoids spurious round-off warnings at equal capacity.
    deficient = difference > 1e-7 * np.maximum(1, np.maximum(np.abs(demand), np.abs(capacity)))
    count = len(snapshots) * int(deficient) if deficient.ndim == 0 else int(np.count_nonzero(deficient))
    indices = list(range(min(len(snapshots), MAX_PREVIEW))) if deficient.ndim == 0 else np.flatnonzero(deficient)[:MAX_PREVIEW].tolist()
    if not count:
        indices = list(range(min(len(snapshots), MAX_PREVIEW)))

    def at(values, index):
        return float(values) if values.ndim == 0 else float(values[index])

    return {
        "scope": scope, "unit": _plain(unit, 80, single_line=True), "snapshot_count": len(snapshots),
        "deficit_snapshot_count": count, "max_shortfall": max(0.0, float(np.max(difference))),
        "peak_positive_demand": float(np.max(demand)), "peak_fixed_available_generation": float(np.max(capacity)),
        "snapshots": [{"index": i, "snapshot": _plain(snapshots[i], 160, single_line=True),
                       "positive_demand": at(demand, i), "fixed_available_generation": at(capacity, i),
                       "shortfall": max(0.0, at(demand, i) - at(capacity, i))} for i in indices],
    }


def _capacity_screens(project, report, buses, islands, by_bus):
    profiles = {(p["component"], p["name"], p["attribute"]): p["values"] for p in project.profiles}
    advanced = getattr(project, "advanced_inputs", {}) or {}
    periods = np.asarray(advanced["snapshot_periods"]) if advanced.get("periods") else None
    units = {name: attrs.get("unit") or "MW" for name, attrs in buses.items()}
    groups = defaultdict(lambda: {"Load": [], "Generator": []})
    for record in project.objects:
        attrs = record["attributes"]
        if record["component"] in {"Load", "Generator"} and _enabled(attrs) and attrs.get("bus") in by_bus:
            bus = attrs["bus"]
            groups[by_bus[bus], units[bus]][record["component"]].append(record)
    total_demand, total_capacity = np.asarray(0.0), np.asarray(0.0)
    all_units = set(units.values())
    for (index, unit), records in groups.items():
        with np.errstate(over="raise", invalid="raise"):
            demand = _aggregate(records["Load"], profiles, periods, demand=True)
            capacity = _aggregate(records["Generator"], profiles, periods, demand=False)
        details = _screen_details(demand, capacity, project.snapshots, f"island_{index + 1}", unit)
        details["buses"] = [_plain(b, 160) for b in islands[index][:MAX_PREVIEW]]
        details["bus_count"] = len(islands[index])
        label = f"Island {index + 1} ({unit}) demand / fixed Generator capacity"
        _add(report, "checks", "island_capacity_screen", label,
             f"All {len(project.snapshots)} snapshots screened; peak positive demand {details['peak_positive_demand']:.6g} {unit}; "
             f"peak fixed available Generator capacity {details['peak_fixed_available_generation']:.6g} {unit}. "
             "These peaks need not coincide. See the bounded snapshot examples and screening omissions.", _SCREEN_FIELDS, details)
        if details["deficit_snapshot_count"]:
            _add(report, "warnings", "island_deficit", label,
                 f"Positive demand exceeds the counted fixed available Generator capacity in {details['deficit_snapshot_count']} "
                 f"snapshots; maximum screened shortfall {details['max_shortfall']:.6g} {unit}. "
                 "Review Load.p_set profiles, Generator.p_nom/p_max_pu, bus references and intended supply paths. "
                 "Expansion, conversion and storage supply are omitted: this is not an infeasibility proof.", _SCREEN_FIELDS, details)
        if details["peak_positive_demand"] > 0 and details["peak_fixed_available_generation"] == 0:
            _add(report, "warnings", "disconnected_load_supply", f"Island {index + 1}: load / supply hint",
                 "This potential-connectivity island has positive demand but no counted fixed Generator supply. "
                 "Supply on other islands cannot reach it through the declared ports. Check bus/bus0/bus1 and "
                 "numbered ports, active flags and intended branches. Extendable generators, storage, conversion "
                 "and signed injections may supply it and were not counted; no infeasibility conclusion is made.",
                 ["Load.bus", "Generator.bus", "Line.bus0", "Line.bus1", "Transformer.bus0", "Transformer.bus1",
                  "Link.bus0", "Link.bus1", "Process.bus0", "Process.bus1"],
                 {"scope": details["scope"], "buses": details["buses"], "bus_count": len(islands[index])})
        elif len(islands) > 1 and details["peak_positive_demand"] == 0 and details["peak_fixed_available_generation"] > 0:
            _add(report, "warnings", "isolated_supply", f"Island {index + 1}: supply without counted demand",
                 "Fixed Generator capacity is on an island with no counted positive Load demand. It cannot "
                 "serve another island through the declared ports. Check intended connections; storage or "
                 "conversion demand and negative dispatch are not represented in this screen.",
                 ["Generator.bus", "Load.bus", "Line.bus0", "Line.bus1"], {"scope": details["scope"]})
        if len(all_units) == 1:
            with np.errstate(over="raise", invalid="raise"):
                total_demand = total_demand + demand
                total_capacity = total_capacity + capacity
    if len(all_units) == 1:
        unit = next(iter(all_units))
        details = _screen_details(total_demand, total_capacity, project.snapshots, "total", unit)
        _add(report, "checks", "capacity_screen", "Total positive demand / fixed available Generator capacity",
             f"All {len(project.snapshots)} snapshots screened in {unit}; {details['deficit_snapshot_count']} have a screened "
             f"deficit, maximum {details['max_shortfall']:.6g} {unit}. Totals ignore inter-island transfer restrictions "
             "and do not make different carriers substitutable. See the screening omissions.", _SCREEN_FIELDS, details,
             priority=True)
        if details["deficit_snapshot_count"]:
            _add(report, "warnings", "capacity_deficit", "Total fixed-capacity screening deficit",
                 f"Positive demand exceeds counted fixed available generation in {details['deficit_snapshot_count']} snapshots; "
                 f"maximum screened shortfall {details['max_shortfall']:.6g} {unit}. Storage, expansion and conversion "
                 "are omitted; this warning is not an infeasibility proof.", _SCREEN_FIELDS, details, priority=True)
    else:
        _add(report, "checks", "mixed_units", "Total capacity comparison omitted",
             "Bus.unit differs across the project. No cross-unit total or implicit conversion is made; "
             "island screens are separated by declared unit. Review unit consistency and conversion ports.", ["Bus.unit"])


def diagnose_project(project) -> dict:
    """Screen a Project without mutation; no project network build or solver call.

    Existing ``Project.validate()`` runs once, including its engineering/advanced
    checks. Invalid projects retain topology/guidance but skip numeric screening.
    New topology/aggregation is linear in records/ports and supplied profile data
    (plus vector activity masks for investment periods), using O(snapshots) working
    arrays, not O(buses * snapshots). Existing validator costs are unchanged.
    Up to 200 findings/category and eight examples/finding are retained; counts
    and truncation counts describe the complete evaluation.
    """
    report = {category: [] for category in ("errors", "warnings", "checks")}
    report.update(scope=_SCOPE, counts=dict.fromkeys(report, 0), truncated=dict.fromkeys(report, 0),
                  limits={"findings_per_category": MAX_FINDINGS, "examples_per_finding": MAX_PREVIEW})
    try:
        errors = project.validate()
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as error:
        _add(report, "errors", "validation_incomplete", "Project validation could not complete",
             f"Malformed project data: {error}. Review the stored input records; no input was modified.")
        return report
    for error in errors:
        _add(report, "errors", "project_validation", "Project.validate input check", error, _validation_fields(error))
    _finite_input_findings(project, report)
    for warning in formulation_warnings(project):
        _add(report, "warnings", "formulation_scope", "Supported formulation", warning)
    buses, islands, by_bus = _connectivity(project.objects)
    details = {"bus_count": len(buses), "island_count": len(islands),
               "islands": [{"id": f"island_{i + 1}", "bus_count": len(group),
                            "buses": [_plain(b, 160) for b in group[:MAX_PREVIEW]]}
                           for i, group in enumerate(islands[:MAX_PREVIEW])]}
    message = (f"{len(buses)} buses form {len(islands)} connected islands using active Line/Transformer/Link/Process ports. "
               "This is undirected potential connectivity, not passive electrical SubNetworks; branch capacity, "
               "flow direction, losses and conversion rates are not tested. Separate islands may be intentional.")
    _add(report, "checks", "connected_islands", "Connected islands", message,
         ["Line.bus0", "Line.bus1", "Transformer.bus0", "Transformer.bus1", "Link.bus0", "Link.bus1",
          "Process.bus0", "Process.bus1"], details)
    if len(islands) > 1:
        _add(report, "warnings", "disconnected_islands", "Disconnected islands", message,
             ["Load.bus", "Generator.bus", "Line.bus0", "Line.bus1", "Link.bus0", "Link.bus1"], details)
    _add(report, "checks", "screening_scope", "Capacity-screening scope and omissions", _SCREEN_LIMITS, _SCREEN_FIELDS)
    _guidance(project, report)
    if report["counts"]["errors"]:
        _add(report, "checks", "capacity_screen_skipped", "Capacity comparison not evaluated",
             "Repair the reported validation/nonfinite input errors deliberately, then rerun diagnostics. "
             "No demand or available-capacity values were invented for invalid inputs.", _SCREEN_FIELDS)
    else:
        try:
            _capacity_screens(project, report, buses, islands, by_bus)
        except FloatingPointError:
            _add(report, "errors", "capacity_screen_invalid", "Capacity comparison could not complete",
                 "Capacity arithmetic overflowed or became invalid; review magnitudes and input units.", _SCREEN_FIELDS)
        except (ValueError, TypeError, OverflowError) as error:
            _add(report, "errors", "capacity_screen_invalid", "Capacity comparison could not complete", str(error), _SCREEN_FIELDS)
    return report


def format_diagnostics(report, *, max_items=40, max_chars=16000) -> str:
    """Bounded plain text; item cap is per category, char cap is overall.

    Custom limits may reduce, not exceed, the 200-item/16000-character hard caps.
    Snapshot examples are already bounded in the report; they are never an
    unbounded dump of profiles. Report input and project data are not modified.
    """
    item_limit = max(0, min(MAX_FINDINGS, int(max_items)))
    char_limit = max(0, min(MAX_TEXT, int(max_chars)))
    lines = [_plain(report.get("scope", _SCOPE))]
    for category in ("errors", "warnings", "checks"):
        findings = report.get(category, [])
        count = report.get("counts", {}).get(category, len(findings))
        lines.append(f"\n{category.title()} ({count})")
        for finding in findings[:item_limit]:
            lines.append(f"- {_plain(finding.get('label', ''), 240, single_line=True)}: {_plain(finding.get('message', ''))}")
            if finding.get("fields"):
                lines.append("  Input fields: " + ", ".join(finding["fields"]))
            for row in finding.get("details", {}).get("snapshots", [])[:MAX_PREVIEW]:
                lines.append(f"  {row['snapshot']}: demand={row['positive_demand']:.6g}, "
                             f"fixed available={row['fixed_available_generation']:.6g}, shortfall={row['shortfall']:.6g} "
                             + finding["details"]["unit"])
        omitted = count - min(len(findings), item_limit)
        if omitted:
            lines.append(f"  {omitted} additional findings omitted from this preview.")
    return _clip("\n".join(lines), char_limit)


def _read_artifact(root, name, limit, *, log=False):
    """Only fixed leaf names, regular files, no symlink/junction escapes."""
    path = root / name
    try:
        resolved = path.resolve(strict=True)
        parent = path.parent
        if (resolved != path or not resolved.is_relative_to(root) or path.is_symlink() or path.is_junction()
                or parent.is_symlink() or parent.is_junction()):
            return None, f"{name}: refused a linked/escaping artifact; no external file was read."
        if not stat.S_ISREG(resolved.stat().st_mode):
            return None, f"{name}: not a regular file; left unchanged."
        with path.open("rb") as source:
            size = source.seek(0, 2)
            if size > limit and not log:
                return None, f"{name}: exceeds the {limit}-byte diagnostic read limit; left unchanged."
            source.seek(0)
            if size > limit:
                head = source.read(limit // 4)
                source.seek(-3 * limit // 4, 2)
                data = head + b"\n[Middle omitted: bounded head/tail log read.]\n" + source.read(3 * limit // 4)
            else:
                data = source.read(limit)
        text = data.decode("utf-8-sig", errors="replace" if log else "strict")
        return text, ""
    except FileNotFoundError:
        return None, f"{name}: missing; no replacement was created."
    except (OSError, ValueError, RuntimeError, UnicodeError):
        return None, f"{name}: unreadable or malformed; check permissions/locks or restore a complete backup. Original unchanged."


def _condition(value):
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    if normalized in {"infeasible_or_unbounded", "unbounded_or_infeasible", "unboundedorinfeasible"}:
        return "ambiguous"
    if normalized in {"infeasible", "unbounded", "optimal"}:
        return normalized
    return None


def _reject_constant(value):
    raise ValueError(f"Nonstandard JSON constant {value}")


def explain_run_failure(run_directory) -> str:
    """Explain saved config/native logs read-only, including older partial runs.

    Reads run_config.json (<=64 KiB) and at most 64 KiB head/tail each from
    highs.log, application.log and worker.log. No metadata-selected paths, SQLite,
    LP/MPS, output catalogues or external artifacts are opened. Malformed/missing
    files are reported and never rewritten. Text is capped at 16000 characters.
    Evidence may be partial or contradictory; only explicit status fields/native
    status lines are interpreted, not arbitrary mentions of "infeasible".
    """
    lines = ["Read-only run failure diagnostics. No files were modified. "
             "This is not an IIS/conflict analysis or automatic repair."]
    try:
        root = Path(run_directory).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Not a directory")
    except (OSError, ValueError, TypeError, RuntimeError):
        return lines[0] + "\nRun directory is missing, unreadable or invalid. Select the existing run folder."
    evidence = []
    config_text, note = _read_artifact(root, str(metadata_path(root, "run_config.json").relative_to(root)), MAX_CONFIG_BYTES)
    if note:
        lines.append(note)
    if config_text is not None:
        try:
            config = json.loads(config_text, parse_constant=_reject_constant)
            if not isinstance(config, dict):
                raise ValueError("Expected a JSON object")
            for key in ("status", "solver_status", "termination_condition", "error"):
                if key not in config:
                    continue  # Old runs need not contain every newer field.
                value = config[key]
                if not isinstance(value, str):
                    lines.append(f"run_config.json: malformed {key} field; left unchanged.")
                    continue
                lines.append(f"Saved {key}: {_plain(value, 1800, single_line=True)}")
                if key in {"solver_status", "termination_condition"}:
                    condition = _condition(value)
                    if condition:
                        evidence.append((condition, "run_config.json " + key, _plain(value, 160, single_line=True)))
        except (ValueError, TypeError, RecursionError):
            lines.append("run_config.json: malformed/incomplete JSON. Restore a complete run or backup if available; original unchanged.")
    status_pattern = re.compile(
        r"(?im)^\s*(?:Model\s+status|Termination\s+condition|Solver\s+status|Presolve\s+status|"
        r"Problem\s+status\s+detected\s+on\s+presolve)\s*[:=]\s*([^\r\n]{1,160})"
    )
    excerpts = []
    for filename in ("highs.log", "application.log", "worker.log"):
        text, note = _read_artifact(root, filename, MAX_LOG_BYTES, log=True)
        if note:
            lines.append(note)
        if text is None:
            continue
        text = _plain(text, MAX_LOG_BYTES + 100)
        matches = list(status_pattern.finditer(text))[-MAX_PREVIEW:]
        for match in matches:
            condition = _condition(match[1])
            if condition:
                evidence.append((condition, filename, _plain(match[0], 200, single_line=True)))
        # Retain a bounded tail, including any head/tail omission notice.
        excerpt = _clip(text[-2200:], 2200)
        if len(text) > 2200:
            excerpt = "[Earlier log text omitted from preview.]\n" + excerpt
        excerpts.append(f"\n{filename} excerpt (bounded; not a complete log):\n{excerpt}")
    conditions = {item[0] for item in evidence}
    if evidence:
        lines.append("\nRecorded solver termination evidence:")
        for condition, source, value in evidence[:MAX_PREVIEW]:
            lines.append(f"- {source}: {value}")
    if len(conditions - {"ambiguous"}) > 1:
        lines.append("Saved solver statuses conflict. Logs/config may be stale or partial; no single solver outcome is inferred.")
    elif "infeasible" in conditions:
        lines.append("The recorded native solver status is infeasible for the saved formulation. "
                     "No conflicting row set or IIS has been identified by these diagnostics.")
    elif "unbounded" in conditions:
        lines.append("The recorded native solver status is unbounded: inspect improving directions and missing finite bounds, "
                     "not just supply adequacy. No unbounded ray has been computed by these diagnostics.")
    elif "ambiguous" in conditions:
        lines.append("The recorded status is infeasible-or-unbounded; it does not distinguish the two. "
                     "Inspect the native log and formulation before choosing a deliberate rerun or model edit.")
    elif "optimal" in conditions:
        lines.append("A recorded solver status is optimal. A later export, numerical check or application error can still fail a run; "
                     "do not relabel that as solver infeasibility.")
    else:
        lines.append("No explicit native infeasible/unbounded termination status was found in the bounded reads. "
                     "A failed/interrupted application run or an arbitrary log mention alone proves neither. "
                     "Check application.log/worker.log for the first validation, file, permission or runtime error.")
    lines.extend([
        "\nReview inputs deliberately (no values are changed):",
        "- Demand/supply: Load.bus/p_set/sign and aligned Profiles; Generator.bus/p_nom/p_max_pu/active. "
        "Check disconnected islands and snapshot availability. A simple capacity deficit is screening, not proof; "
        "expansion, storage, conversion and signed injections may supply omitted power.",
        "- Transfers/conversion: Line/Transformer.bus0/bus1/s_nom/s_max_pu and x/type; "
        "Link.bus0/bus1/efficiency/p_nom/p_min_pu/p_max_pu; Process.bus0/bus1/rate0/rate1 and numbered ports. "
        "Connectivity is not deliverability.",
        "- Commitment: Generator/Link/Process.committable, p_min_pu/p_max_pu, min_up_time/min_down_time, "
        "up_time_before/down_time_before and ramp_limit_up/down/start_up/shut_down; review the actual supported combination.",
        "- Storage: StorageUnit.p_nom/max_hours/state_of_charge_initial/state_of_charge_set/cyclic_state_of_charge, "
        "efficiency_store/efficiency_dispatch/standing_loss/inflow; Store.e_nom/e_initial/e_set/e_cyclic/e_min_pu/e_max_pu. "
        "Check MW vs MWh, period boundaries and advanced weights.stores (hours).",
        "- Budgets: GlobalConstraint.type/sense/constant/carrier_attribute/investment_period/bus; "
        "Generator.carrier/efficiency, Carrier.co2_emissions and snapshot/period weights. Equality is not a maximum budget.",
        "- Unboundedness review: Generator/Link/Process.p_nom_extendable/p_nom_max, Store.e_nom_extendable/e_nom_max, "
        "Line/Transformer.s_nom_extendable/s_nom_max and capital_cost/marginal_cost. Check negative-cost cycles and "
        "unlimited rewarded investment/dispatch; do not blindly remove constraints or enlarge all bounds.",
    ])
    lines.extend(excerpts)
    return _clip("\n".join(lines), MAX_TEXT)
