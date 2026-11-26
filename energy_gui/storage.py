"""SQLite is the source of truth for inputs, including imported profile values."""

import json
from contextlib import closing
import sqlite3
from pathlib import Path

from .project import Project, SCHEMA_VERSION


def save_project(project, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = project.to_dict()
    objects, profiles = data.pop("objects"), data.pop("profiles")
    editor_config = data.pop("editor_config", {})
    schematic_layouts = data.pop("schematic_layouts", {})
    demo_info = data.pop("demo_info", {})
    analysis_workspace = data.pop("analysis_workspace", [])
    scenario_library = data.pop("scenario_library", [])
    interchange_info = data.pop("interchange_info", {})
    # Old projects keep their exact core payload. New model semantics deliberately
    # fail closed in older readers (unknown constructor key), never silently drop.
    if not data.get("advanced_inputs"):
        data.pop("advanced_inputs", None)
    # A single transaction preserves the previous project if an insert fails.
    # sqlite3's own context manager commits/rolls back but does NOT close the DB.
    with closing(sqlite3.connect(path)) as connection, connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables and "metadata" not in tables:
            raise ValueError("Not a PyPSA Studio project; refusing to overwrite another database.")
        connection.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        if tables:
            identity = connection.execute("SELECT value FROM metadata WHERE key='application'").fetchone()
            if identity != ("pypsa-studio",):
                raise ValueError("Unrecognized project database; refusing to overwrite it.")
        current = connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        if current and int(current[0]) != SCHEMA_VERSION:
            raise ValueError("Unsupported project schema; refusing to overwrite it.")
        connection.execute("CREATE TABLE IF NOT EXISTS components (component TEXT, name TEXT, attributes TEXT NOT NULL, PRIMARY KEY (component, name))")
        connection.execute("CREATE TABLE IF NOT EXISTS profiles (component TEXT, name TEXT, attribute TEXT, data TEXT NOT NULL, PRIMARY KEY (component, name, attribute))")
        connection.execute("DELETE FROM metadata")
        connection.executemany("INSERT INTO metadata VALUES (?, ?)", [
            ("schema_version", str(SCHEMA_VERSION)),
            ("application", "pypsa-studio"),
            ("project", json.dumps(data, allow_nan=False)),
            ("editor_config", json.dumps(editor_config, allow_nan=False)),
            ("schematic_layouts", json.dumps(schematic_layouts, allow_nan=False)),
            ("demo_info", json.dumps(demo_info, allow_nan=False)),
            ("analysis_workspace", json.dumps(analysis_workspace, allow_nan=False)),
            ("scenario_library", json.dumps(scenario_library, allow_nan=False)),
            ("interchange_info", json.dumps(interchange_info, allow_nan=False)),
        ])
        connection.execute("DELETE FROM components")
        connection.executemany("INSERT INTO components VALUES (?, ?, ?)", [
            (o["component"], o["name"], json.dumps(o["attributes"], allow_nan=False)) for o in objects
        ])
        connection.execute("DELETE FROM profiles")
        connection.executemany("INSERT INTO profiles VALUES (?, ?, ?, ?)", [
            (p["component"], p["name"], p["attribute"], json.dumps(p, allow_nan=False)) for p in profiles
        ])


def load_project(path):
    path = Path(path).resolve()
    # Read-only mode prevents accidentally creating or modifying an unknown DB.
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        if metadata.get("application") != "pypsa-studio":
            raise ValueError("This is not a recognized PyPSA Studio project.")
        if int(metadata["schema_version"]) != SCHEMA_VERSION:
            raise ValueError("Unsupported project schema; no automatic migration is available yet.")
        data = json.loads(metadata["project"])
        # Optional, non-model metadata. Older databases default to all visible;
        # older application versions can still read the unchanged project payload.
        data["editor_config"] = json.loads(metadata.get("editor_config", "{}"))
        data["demo_info"] = json.loads(metadata.get("demo_info", "{}"))
        data["analysis_workspace"] = json.loads(metadata.get("analysis_workspace", "[]"))
        data["scenario_library"] = json.loads(metadata.get("scenario_library", "[]"))
        data["interchange_info"] = json.loads(metadata.get("interchange_info", "{}"))
        try:
            layouts = json.loads(metadata.get("schematic_layouts", "{}"))
            data["schematic_layouts"] = layouts if isinstance(layouts, dict) else {}
        except ValueError:
            data["schematic_layouts"] = {}
        data["objects"] = [
            {"component": c, "name": n, "attributes": json.loads(a)}
            for c, n, a in connection.execute("SELECT component, name, attributes FROM components ORDER BY rowid")
        ]
        data["profiles"] = [json.loads(row[0]) for row in connection.execute("SELECT data FROM profiles ORDER BY rowid")]
    return Project(**data)
