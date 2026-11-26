"""Shared artifact locations for current and historical Studio runs."""

from pathlib import Path


def metadata_path(run, name):
    run = Path(run)
    return (run / "metadata" if (run / "metadata").is_dir() else run) / name


def formulation_directory(run):
    run = Path(run)
    return run / "formulation" if (run / "metadata").is_dir() else run
