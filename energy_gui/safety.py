"""Local recovery snapshots and explicit saved-project backups; no auto restore."""

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import uuid
import zipfile

from .storage import load_project, save_project
from PySide6.QtCore import QLockFile


class RecoveryStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.key = uuid.uuid4().hex
        self.path = self.directory / (self.key + ".sqlite")
        self.lock = QLockFile(str(self.directory / (self.key + ".lock")))
        self.lock.setStaleLockTime(0)  # PID liveness, not an elapsed-time expiry.
        if not self.lock.tryLock(0):
            raise OSError("Could not lock the recovery session directory.")

    def capture(self, project, source):
        # Publish only a complete SQLite copy. Failed publication leaves the
        # previous recovery intact, and never touches the saved source.
        with tempfile.TemporaryDirectory(prefix="capture_", dir=self.directory) as tmp:
            candidate = Path(tmp) / "snapshot.sqlite"
            save_project(project, candidate)
            metadata = dict(created_utc=datetime.now(timezone.utc).isoformat(),
                            project=project.name, source=str(source or ""),
                            scope="Applied model changes only; not pending fields or query tabs")
            with closing(sqlite3.connect(candidate)) as connection, connection:
                connection.execute("INSERT INTO metadata VALUES (?, ?)", ("recovery", json.dumps(metadata)))
            candidate.replace(self.path)

    def candidates(self):
        result = []
        for path in sorted(self.directory.glob("*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True):
            if path == self.path:
                continue
            lock = QLockFile(str(path.with_suffix(".lock")))
            lock.setStaleLockTime(0)
            if lock.tryLock(0):
                lock.unlock()
                result.append(path)
        return result

    def inspect(self, path):
        path = Path(path).resolve()
        if path.parent != self.directory.resolve() or path.suffix != ".sqlite":
            raise ValueError("Choose a recovery copy from the local recovery directory.")
        project = load_project(path)
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
            row = connection.execute("SELECT value FROM metadata WHERE key='recovery'").fetchone()
        meta = json.loads(row[0]) if row else None
        if not isinstance(meta, dict) or not all(isinstance(meta.get(k), str) for k in ["source", "created_utc", "project"]):
            raise ValueError("Recovery metadata is incomplete; original files were not modified.")
        return project, meta

    def claim(self, path):
        path = Path(path).resolve()
        if path.parent != self.directory.resolve() or path == self.path or path.suffix != ".sqlite":
            raise ValueError("Invalid recovery selection.")
        lock = QLockFile(str(path.with_suffix(".lock")))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            raise OSError("This recovery copy is owned by another active session. Retry later.")
        return lock

    def clear(self):
        self.path.unlink(missing_ok=True)

    def close(self):
        self.lock.unlock()


def publish_backup(archive, destination):
    # Both paths share a filesystem. Windows rename fails if destination exists;
    # POSIX rename overwrites, so use an exclusive hard link there instead.
    if os.name == "nt":
        archive.rename(destination)
    else:
        os.link(archive, destination)


def create_backup(database, destination, progress=lambda value: None, cancelled=lambda: False):
    """Archive SAVED inputs plus matching frozen-run folders, never live drafts.

    Caller must stop its worker. Concurrent external writers are unsupported;
    reject symlinks and detected file changes rather than publishing a partial ZIP.
    """
    database, destination = Path(database).resolve(), Path(destination).resolve()
    def check_cancel():
        if cancelled():
            raise InterruptedError("Backup cancelled; no public archive was created.")
    check_cancel()
    project = load_project(database)
    if destination.exists():
        raise FileExistsError("Backup destination already exists; choose a new filename.")
    runs = database.parent / "runs"
    if destination == database or destination.is_relative_to(runs):
        raise ValueError("Choose a backup location outside the project's runs folder.")
    files = []
    if runs.is_dir():
        for folder in sorted(runs.iterdir()):
            if folder.is_symlink():
                raise ValueError("Backup refuses symlinked run folders.")
            if not folder.is_dir() or not (folder / "inputs.sqlite").exists():
                continue
            # Frozen identity, not directory name, scopes runs sharing a folder.
            if load_project(folder / "inputs.sqlite").project_id != project.project_id:
                continue
            for path in sorted(folder.rglob("*")):
                if path.is_symlink():
                    raise ValueError("Backup refuses symlinked run artifacts.")
                if path.is_file():
                    files.append(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="backup_", dir=destination.parent) as tmp:
        snapshot = Path(tmp) / "project.sqlite"
        # SQLite's backup API captures a consistent committed database, including
        # WAL contents, without copying a potentially half-updated main DB file.
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(snapshot)) as target:
                source.backup(target, pages=256, progress=lambda *args: check_cancel())
        archive = Path(tmp) / "backup.zip"
        manifest = dict(created_utc=datetime.now(timezone.utc).isoformat(), project_id=project.project_id,
                        project_file=database.name, files={})
        initial = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in files}
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
            sources = [(snapshot, database.name)] + [(p, p.relative_to(database.parent).as_posix()) for p in files]
            for index, (path, name) in enumerate(sources):
                check_cancel()
                digest = hashlib.sha256()
                with path.open("rb") as source, output.open(name, "w", force_zip64=True) as entry:
                    while chunk := source.read(1024*1024):
                        check_cancel()
                        digest.update(chunk)
                        entry.write(chunk)
                manifest["files"][name] = digest.hexdigest()
                progress(int(100*(index+1)/len(sources)))
            output.writestr("backup_manifest.json", json.dumps(manifest, indent=2))
        if any((p.stat().st_size, p.stat().st_mtime_ns) != state for p, state in initial.items()):
            raise OSError("Run files changed during backup. Stop all writers and retry.")
        # Exclusive creation prevents overwriting an existing archive, including
        # one created after the initial existence check.
        check_cancel()
        publish_backup(archive, destination)
    return destination
