"""Data-only named variations and frozen, unstarted runs (no Qt or solver).

Contract: definitions are a JSON list of ``{id, name, changes}`` dictionaries.
Each change has exactly ``component, name, attribute, operation, value``.
``set`` accepts a schema-typed scalar but refuses an existing matching profile.
``scale`` accepts a numeric factor and scales BOTH the static value (or schema
default) and every value of an existing matching numeric profile. It never
creates/removes a profile. A piecewise curve on the target always blocks edits.
Targets must be existing objects and static INPUT attributes; identities,
references, activation and connection topology cannot be changed here.

IDs are portable 1–64 character ASCII tokens; names are 1–120 characters.
IDs and names are independently unique, case-insensitively, after trimming.
There are at most 30 definitions, 100 changes per definition, 512 KiB of clean
definition JSON, and 1024 characters per scalar string. Numeric edits, factors
and their results must be finite with absolute value at most 1e15. Duplicate
targets within one definition are rejected (no order-dependent overrides).
An empty definition list returns []; a definition may have no changes, making
an explicit baseline case. All cases independently start from the same base.

Run metadata adds scenario_id, scenario_name, scenario_definition and
scenario_base. The latter records the base project_id/name, database basename
and SHA-256 of canonical base Project.to_dict() JSON, not scratch-file paths.
Run preparation does not execute a solver or modify the saved base project.
"""

import hashlib
import json
import math
from pathlib import Path
import re
import tempfile

from .engine import prepare_run, write_json
from .run_layout import metadata_path
from .object_edits import references, standard_names
from .project import Project
from .schema import attribute_spec, parse_value, registry
from .storage import load_project, save_project

MAX_SCENARIOS = 30
MAX_CHANGES = 100
MAX_DEFINITION_BYTES = 512 * 1024
MAX_ABSOLUTE_VALUE = 1e15
_IDENTITY_ATTRIBUTES = {
    "name", "carrier", "type", "component", "idx", "carrier_attribute", "active",
}


def _text(value, label, maximum, *, trim=True):
    if type(value) is not str or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f"{label}: use text of at most {maximum} characters without control characters.")
    value = value.strip() if trim else value
    if not value:
        raise ValueError(f"{label}: provide nonempty text.")
    return value


def _number(value, label):
    if type(value) not in (int, float):
        raise ValueError(f"{label}: expected a finite JSON number, not text or a boolean.")
    try:
        valid = math.isfinite(value) and abs(value) <= MAX_ABSOLUTE_VALUE
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{label}: expected a finite number with absolute value <= {MAX_ABSOLUTE_VALUE:g}.")
    return value


def _scalar(spec, value, label):
    dtype = spec["dtype"]
    if "bool" in dtype:
        if type(value) is not bool:
            raise ValueError(f"{label}: expected a JSON boolean (true or false).")
    elif "str" in dtype or "geometry" in dtype:
        # Empty strings can be valid scalar inputs, unlike object identities.
        if type(value) is not str or len(value) > 1024 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError(f"{label}: expected scalar text of at most 1024 characters without controls.")
    else:
        _number(value, label)
    try:
        return parse_value(spec, value)
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError(f"{label}: {error}") from error


def _validate_project(project, label, *, check_references=False):
    try:
        errors = project.validate()
        if check_references and not errors:
            existing = {(o["component"], o["name"]) for o in project.objects}
            builtins = standard_names()
            for owner, attribute, kind, name, _ in references(project):
                if (kind, name) not in existing and name not in builtins.get(kind, set()):
                    errors.append(
                        f"{owner['component']} {owner['name']}.{attribute}: undefined {kind} '{name}'; "
                        "add the referenced object to the base project first."
                    )
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"{label}: malformed project inputs: {error}") from error
    if errors:
        raise ValueError(f"{label}:\n" + "\n".join(errors))


def _clean_definitions(project, definitions):
    if type(definitions) is not list or len(definitions) > MAX_SCENARIOS:
        raise ValueError(f"Scenarios must be a data-only list of at most {MAX_SCENARIOS} definitions.")
    clean, ids, names = [], set(), set()
    for index, definition in enumerate(definitions, 1):
        label = f"Scenario {index}"
        if type(definition) is not dict or set(definition) != {"id", "name", "changes"}:
            raise ValueError(f"{label}: expected exactly id, name and changes.")
        identifier = _text(definition["id"], f"{label} id", 64)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", identifier):
            raise ValueError(f"{label} id: use an ASCII letter/digit followed by letters, digits, '_' or '-'.")
        name = _text(definition["name"], f"{label} name", 120)
        if identifier.casefold() in ids or name.casefold() in names:
            raise ValueError(f"{label}: scenario id and name must each be unique (case-insensitive).")
        ids.add(identifier.casefold())
        names.add(name.casefold())
        changes = definition["changes"]
        if type(changes) is not list or len(changes) > MAX_CHANGES:
            raise ValueError(f"{label} '{name}': changes must be a list of at most {MAX_CHANGES} entries.")
        clean_changes, targets = [], set()
        for position, change in enumerate(changes, 1):
            location = f"{label} '{name}', change {position}"
            if type(change) is not dict or set(change) != {"component", "name", "attribute", "operation", "value"}:
                raise ValueError(f"{location}: expected exactly component, name, attribute, operation and value.")
            component = _text(change["component"], f"{location} component", 64, trim=False)
            object_name = _text(change["name"], f"{location} object name", 1024, trim=False)
            attribute = _text(change["attribute"], f"{location} attribute", 128, trim=False)
            location += f" ({component} {object_name}.{attribute})"
            if component not in registry() or not registry()[component]["editable"] or project.object(component, object_name) is None:
                raise ValueError(f"{location}: target an existing editable object; scenarios cannot add or rename objects.")
            if attribute in _IDENTITY_ATTRIBUTES or re.fullmatch(r"bus\d*", attribute):
                raise ValueError(f"{location}: identity, reference, activation and topology edits are not scenario operations.")
            try:
                spec = attribute_spec(component, attribute)
            except ValueError as error:
                raise ValueError(f"{location}: {error}") from error
            if not spec["input"] or not spec["static"]:
                raise ValueError(f"{location}: target a static INPUT attribute, not an output or profile-only attribute.")
            target = component, object_name, attribute
            if target in targets:
                raise ValueError(f"{location}: duplicate target; combine the edit into one change.")
            targets.add(target)
            if any((c["component"], c["name"], c["attribute"]) == target
                   for c in project.advanced_inputs.get("piecewise", [])):
                raise ValueError(f"{location}: an advanced piecewise curve overrides this scalar/profile; edit the base curve instead.")
            operation = change["operation"]
            if type(operation) is not str or operation not in {"set", "scale"}:
                raise ValueError(f"{location}: operation must be 'set' or 'scale'.")
            profile = next((p for p in project.profiles
                            if (p["component"], p["name"], p["attribute"]) == target), None)
            if operation == "set":
                if profile is not None:
                    raise ValueError(f"{location}: an existing profile overrides a scalar set; use scale, or remove/edit the base profile explicitly.")
                value = _scalar(spec, change["value"], location)
            else:
                if not any(t in spec["dtype"] for t in ("int", "float")) or "bool" in spec["dtype"]:
                    raise ValueError(f"{location}: scale requires a numeric attribute, not text or a boolean.")
                value = _number(change["value"], location + " scale factor")
            clean_changes.append(dict(component=component, name=object_name, attribute=attribute,
                                      operation=operation, value=value))
        clean.append(dict(id=identifier, name=name, changes=clean_changes))
    if len(json.dumps(clean, allow_nan=False, ensure_ascii=True).encode("utf-8")) > MAX_DEFINITION_BYTES:
        raise ValueError(f"Scenario definitions exceed the {MAX_DEFINITION_BYTES // 1024} KiB JSON size limit.")
    return clean


def _candidate(project, definition):
    candidate = Project(**project.to_dict())  # Dataclass asdict deeply detaches every project field.
    for change in definition["changes"]:
        component, name, attribute = change["component"], change["name"], change["attribute"]
        attrs = candidate.object(component, name)["attributes"]
        spec = attribute_spec(component, attribute)
        label = f"Scenario '{definition['name']}' ({component} {name}.{attribute})"
        if change["operation"] == "set":
            attrs[attribute] = change["value"]
            continue
        # Defaults may be stored as JSON 'inf'/None. Such values cannot be
        # meaningfully scaled, even when a matching finite profile exists.
        try:
            original = parse_value(spec, attrs.get(attribute, spec["default"]))
        except (ValueError, TypeError, OverflowError) as error:
            raise ValueError(f"{label} static/default value cannot be scaled: {error}") from error
        original = _number(original, label + " static/default value")
        attrs[attribute] = _scalar(spec, original * change["value"], label + " scaled value")
        for profile in candidate.profiles:
            if (profile["component"], profile["name"], profile["attribute"]) != (component, name, attribute):
                continue
            values = []
            for index, value in enumerate(profile["values"], 1):
                value = _number(value, f"{label} profile row {index}")
                values.append(_scalar(spec, value * change["value"], f"{label} scaled profile row {index}"))
            profile["values"] = values
    _validate_project(candidate, f"Scenario '{definition['name']}'")
    return candidate


def _checked_candidates(project, definitions):
    _validate_project(project, "Base project", check_references=True)
    clean = _clean_definitions(project, definitions)
    candidates = [_candidate(project, definition) for definition in clean]
    return clean, candidates


def checked_scenarios(project, definitions):
    """Return detached canonical definitions after validating EVERY candidate.

    Accept Project plus the contract list above; values retain schema units
    (scale factors are dimensionless). Raises actionable ValueError on invalid
    definitions/models. Does not mutate the project/list or write any files.
    """
    return _checked_candidates(project, definitions)[0]


def scenario_project(project, definition):
    """Return one detached, validated Project, preserving project_id and metadata.

    Accept one definition, not a list. No files, solver or base/list mutation.
    Static sets use attribute units; numeric scale factors are dimensionless.
    """
    return _checked_candidates(project, [definition])[1][0]


def _publish_run(source, destination):
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Scenario run already exists; refusing to overwrite {destination}.")
    source.rename(destination)


def prepare_scenarios(database, definitions, export_format="none"):
    """Return ordered list[Path] of queued runs under the saved database's runs/.

    Read SAVED inputs, not live drafts. Validate every variation before any
    publication, then prepare all frozen inputs/configs in a private sibling
    scratch directory (same filesystem for atomic directory moves). On a normal
    preparation/publication exception, roll back only this call's newly queued
    directories. Existing runs/database are never overwritten. No solver runs.
    A machine crash during publication can leave a prefix of complete queued
    cases; the caller must only start workers after this function returns.
    """
    if type(export_format) is not str or export_format not in {"none", "lp", "mps"}:
        raise ValueError("Export format must be none, lp, or mps.")
    database = Path(database).resolve()
    if any(metadata_path(parent, "run_config.json").is_file() and (parent / "inputs.sqlite").is_file()
           for parent in database.parents):
        raise ValueError("Choose an editable base database outside frozen run directories; no frozen run may be modified.")
    project = load_project(database)
    clean, candidates = _checked_candidates(project, definitions)
    if not clean:
        return []
    base_json = json.dumps(project.to_dict(), sort_keys=True, ensure_ascii=True,
                           separators=(",", ":"), allow_nan=False).encode("utf-8")
    provenance = dict(project_id=project.project_id, name=project.name,
                      database=database.name, project_sha256=hashlib.sha256(base_json).hexdigest())
    runs = database.parent / "runs"
    if runs.is_symlink() or runs.is_junction() or runs.resolve().parent != database.parent:
        raise ValueError("Scenario runs directory must be a real folder beside the base database, not a link.")
    runs_existed = runs.exists()
    with tempfile.TemporaryDirectory(prefix=".scenario-stage-", dir=database.parent) as temporary:
        scratch = Path(temporary)
        staged = []
        # prepare_run only sees scratch databases. Even a later preparation
        # failure leaves the real runs directory and all existing inputs alone.
        for index, (definition, candidate) in enumerate(zip(clean, candidates)):
            scratch_database = scratch / f"case_{index}.sqlite"
            save_project(candidate, scratch_database)
            directory = prepare_run(scratch_database, label="scenario_" + definition["id"],
                                    export_format=export_format)
            config_path = metadata_path(directory, "run_config.json")
            config = json.loads(config_path.read_text(encoding="utf-8"))
            if config.get("status") != "queued":
                raise ValueError("Scenario preparation requires an unstarted queued run.")
            config.update(scenario_id=definition["id"], scenario_name=definition["name"],
                          scenario_definition=definition, scenario_base=provenance)
            write_json(config_path, config)
            staged.append((directory, runs / directory.name))
        if len({destination for _, destination in staged}) != len(staged):
            raise FileExistsError("Scenario run directory names collided; no cases were published.")
        for _, destination in staged:
            if destination.exists() or destination.is_symlink():
                raise FileExistsError(f"Scenario run already exists; refusing to overwrite {destination}.")
        published = []
        try:
            runs.mkdir(exist_ok=True)
            for source, destination in staged:
                _publish_run(source, destination)
                published.append((source, destination))
        except Exception:
            # These are exclusively this call's unstarted runs, never preexisting
            # frozen runs. Moving back lets the scoped scratch owner clean up.
            for source, destination in reversed(published):
                destination.rename(source)
            if not runs_existed and runs.exists() and not any(runs.iterdir()):
                runs.rmdir()
            raise
    return [destination for _, destination in staged]
