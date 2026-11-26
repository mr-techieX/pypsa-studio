"""Actionable read-only diagnostics; never repairs or rewrites user artifacts."""

import json
from .run_layout import metadata_path


def failure_message(error):
    detail = str(error)
    if isinstance(error, PermissionError):
        return "Access denied or file locked. Close programs using the file, check folder permissions, and retry or choose another location.\n\n" + detail
    if isinstance(error, FileNotFoundError):
        return "A required local file is missing. Check the project/run folder and restore the complete saved artifact from a backup if available. No files were repaired or overwritten.\n\n" + detail
    if isinstance(error, json.JSONDecodeError):
        return "A saved JSON artifact is incomplete or corrupt. Select a complete run or restore a backup; automatic rewriting is disabled.\n\n" + detail
    return detail


def run_metadata(directory):
    path = metadata_path(directory, "run_config.json")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path.name} is incomplete/corrupt JSON. Restore a complete run or backup; the original was not modified.") from error
    if (not isinstance(value, dict) or not isinstance(value.get("project_id"), str)
            or value.get("status") not in {"queued", "running", "succeeded", "failed", "cancelled"}):
        raise ValueError("run_config.json lacks a valid project identity or known status. Choose a complete supported run; the original was not modified.")
    return value
