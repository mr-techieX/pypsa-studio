"""Recovery/backup failure cases use isolated directories, never real user state."""

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from energy_gui.controller import Controller
from energy_gui.demo_library import make_demo
from energy_gui.safety import RecoveryStore, create_backup
from energy_gui.storage import load_project, save_project
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox
from PySide6.QtTest import QTest
from test_network_view import overlay_fixture


class SafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        self.temp = tempfile.TemporaryDirectory(prefix="stage3f_", dir=preferred)
        self.root = Path(self.temp.name)
        self.store = RecoveryStore(self.root / "recovery")
        self.controller = Controller()
        self.controller.enableRecovery(self.root / "recovery")
        self.notices = []
        self.controller.notice.connect(self.notices.append)

    def tearDown(self):
        self.controller._recovery_timer.stop()
        self.controller.recovery_store.close()
        self.controller.notice.disconnect()
        self.store.close()
        self.temp.cleanup()

    def inactive_copy(self):
        project = make_demo("campus6")
        self.store.capture(project, self.root / "original.sqlite")
        self.store.close()  # Represents a session whose process is no longer active.
        return project, self.store.path

    def select_copy(self, path):
        return patch.object(QInputDialog, "getItem", return_value=(path.name, True))

    def test_active_sessions_are_excluded_and_complete_metadata_roundtrips(self):
        project = make_demo("regional20")
        self.store.capture(project, self.root / "original.sqlite")
        self.assertEqual(self.controller.recovery_store.candidates(), [])
        self.store.close()
        self.assertEqual(self.controller.recovery_store.candidates(), [self.store.path])
        copy, meta = self.controller.recovery_store.inspect(self.store.path)
        self.assertEqual(copy.to_dict(), project.to_dict())
        self.assertEqual(meta["source"], str(self.root / "original.sqlite"))

    def test_failed_atomic_recovery_publication_preserves_previous_and_original(self):
        original = self.root / "original.sqlite"
        project = make_demo("urban3")
        save_project(project, original)
        self.store.capture(project, original)
        before, saved = self.store.path.read_bytes(), original.read_bytes()
        project.name = "New applied name"
        with patch.object(Path, "replace", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                self.store.capture(project, original)
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(original.read_bytes(), saved)

    def test_delayed_capture_includes_applied_model_but_not_pending_settings(self):
        self.controller.loadDemo()
        self.controller.updateSettingsDraft("NOT APPLIED", "USD", "2026-01-01", 24, 60)
        QTest.qWait(1200)
        copy = load_project(self.controller.recovery_store.path)
        self.assertEqual(copy.to_dict(), self.controller.project.to_dict())
        self.assertNotEqual(copy.name, "NOT APPLIED")

    def test_successful_save_clears_only_own_copy_failed_save_keeps_it(self):
        self.controller.loadDemo()
        self.controller.flushRecovery()
        self.controller.path = self.root / "saved.sqlite"
        own = self.controller.recovery_store.path
        with patch("energy_gui.controller.save_project", side_effect=PermissionError("locked")):
            self.assertFalse(self.controller.saveProject())
        self.assertTrue(own.exists())
        self.assertTrue(self.controller.saveProject())
        self.assertFalse(own.exists())

    def test_restore_is_unsaved_and_keeps_original_and_applied_values(self):
        project, path = self.inactive_copy()
        original = self.root / "original.sqlite"
        save_project(make_demo("urban3"), original)
        before = original.read_bytes()
        with self.select_copy(path), patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.controller.recoverProject()
        self.assertEqual(self.controller.project.to_dict(), project.to_dict())
        self.assertTrue(self.controller.dirty)
        self.assertIsNone(self.controller.path)
        self.assertEqual(original.read_bytes(), before)
        self.assertFalse(path.exists())
        self.assertTrue(self.controller.recovery_store.path.exists())

    def test_cancel_and_discard_affect_only_offered_copy(self):
        _, path = self.inactive_copy()
        before = self.controller.project.to_dict()
        with self.select_copy(path), patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.controller.recoverProject()
        self.assertTrue(path.exists())
        with self.select_copy(path), patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.controller.recoverProject()
        self.assertFalse(path.exists())
        self.assertEqual(self.controller.project.to_dict(), before)

    def test_corrupt_copy_is_retained_and_never_replaces_current_project(self):
        _, path = self.inactive_copy()
        path.write_bytes(b"not sqlite")
        before = self.controller.project.to_dict()
        with self.select_copy(path):
            self.controller.recoverProject()
        self.assertEqual(self.controller.project.to_dict(), before)
        self.assertEqual(path.read_bytes(), b"not sqlite")
        self.assertIn("no automatic repair", self.notices[-1])

    def test_current_draft_cancellation_blocks_restore_and_preserves_copy(self):
        _, path = self.inactive_copy()
        self.controller.loadDemo()
        before = self.controller.project.to_dict()
        with self.select_copy(path), patch.object(QMessageBox, "question", side_effect=[QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Cancel]):
            self.controller.recoverProject()
        self.assertEqual(self.controller.project.to_dict(), before)
        self.assertTrue(path.exists())

    def test_confirmed_close_clears_copy_cancelled_close_keeps_it(self):
        self.controller.loadDemo()
        self.controller.flushRecovery()
        own = self.controller.recovery_store.path
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.controller.canClose())
        self.assertTrue(own.exists())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(self.controller.canClose())
        self.assertFalse(own.exists())

    def test_actual_abnormal_process_exit_leaves_recoverable_unlocked_copy(self):
        directory = self.root / "crash"
        script = "from energy_gui.safety import RecoveryStore; from energy_gui.demo_library import make_demo; import os,sys; s=RecoveryStore(sys.argv[1]); s.capture(make_demo('wind10'), None); os._exit(23)"
        result = subprocess.run([sys.executable, "-c", script, str(directory)], capture_output=True, timeout=45)
        self.assertEqual(result.returncode, 23, result.stderr)
        reader = RecoveryStore(directory)
        try:
            paths = reader.candidates()
            self.assertEqual(len(paths), 1)
            self.assertEqual(reader.inspect(paths[0])[0].demo_info["id"], "wind10")
        finally:
            reader.close()

    def test_active_or_claimed_copy_cannot_be_claimed_by_second_session(self):
        project, path = self.inactive_copy()
        claim = self.controller.recovery_store.claim(path)
        other = RecoveryStore(self.root / "recovery")
        try:
            self.assertEqual(other.candidates(), [])
            with self.assertRaises(OSError):
                other.claim(path)
        finally:
            claim.unlock()
            other.close()

    def test_failed_restore_capture_preserves_offer_and_current_project(self):
        _, path = self.inactive_copy()
        before = self.controller.project.to_dict()
        with self.select_copy(path), patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), patch.object(self.controller.recovery_store, "capture", side_effect=PermissionError("locked")):
            self.controller.recoverProject()
        self.assertEqual(self.controller.project.to_dict(), before)
        self.assertTrue(path.exists())

    def backup_fixture(self):
        project, _ = overlay_fixture(self.root / "runs" / "one")
        database = self.root / "saved.sqlite"
        save_project(project, database)
        other = make_demo("urban3")
        save_project(other, self.root / "runs" / "foreign" / "inputs.sqlite")
        return project, database

    def test_backup_reopens_saved_inputs_and_matching_run_with_valid_checksums(self):
        project, database = self.backup_fixture()
        original = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        destination = self.root / "archive.zip"
        create_backup(database, destination)
        with zipfile.ZipFile(destination) as archive:
            names = archive.namelist()
            self.assertIn("runs/one/inputs.sqlite", names)
            self.assertFalse(any("foreign" in name for name in names))
            manifest = json.loads(archive.read("backup_manifest.json"))
            for name, digest in manifest["files"].items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest)
            target = self.root / "restore"
            archive.extractall(target)  # Only this test's own generated archive.
        self.assertEqual(load_project(target / database.name).to_dict(), project.to_dict())
        for name, data in original.items():
            self.assertEqual((self.root / name).read_bytes(), data)
        controller = Controller()
        controller.project = project
        self.assertTrue(controller.openRun(str(target / "runs" / "one")))
        self.assertTrue(controller.queryResults("Line", ["L"], ["p0"], "", ""))

    def test_backup_collision_and_publication_failure_do_not_overwrite(self):
        _, database = self.backup_fixture()
        destination = self.root / "archive.zip"
        destination.write_bytes(b"existing")
        with self.assertRaises(FileExistsError):
            create_backup(database, destination)
        self.assertEqual(destination.read_bytes(), b"existing")
        other = self.root / "other.zip"
        with patch("energy_gui.safety.publish_backup", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                create_backup(database, other)
        self.assertFalse(other.exists())

    def test_backup_is_saved_state_and_guards_busy_and_cancel(self):
        project, database = self.backup_fixture()
        self.controller.project, self.controller.path = project, database
        self.controller.project.name = "UNSAVED EDIT"
        self.controller.dirty = True
        destination = self.root / "archive.zip"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(destination), "ZIP")):
            self.assertTrue(self.controller.backupProject())
        with zipfile.ZipFile(destination) as archive:
            restored = self.root / "snapshot.sqlite"
            restored.write_bytes(archive.read(database.name))
        self.assertNotEqual(load_project(restored).name, "UNSAVED EDIT")
        self.assertTrue(self.controller.dirty)
        with patch.object(QFileDialog, "getSaveFileName", return_value=("", "ZIP")):
            self.assertFalse(self.controller.backupProject())
        self.controller.process = object()
        self.assertFalse(self.controller.backupProject())
        self.controller.process = None

    def test_backup_detects_changed_artifacts_and_rejects_nested_destination(self):
        _, database = self.backup_fixture()
        destination = self.root / "archive.zip"
        path = self.root / "runs" / "one" / "catalog.json"
        original_write = zipfile.ZipFile.writestr
        changed = False
        def write(archive, name, data, *args, **kwargs):
            nonlocal changed
            result = original_write(archive, name, data, *args, **kwargs)
            if not changed:
                path.write_text(path.read_text() + " ")
                changed = True
            return result
        with patch.object(zipfile.ZipFile, "writestr", write), self.assertRaises(OSError):
            create_backup(database, destination)
        self.assertFalse(destination.exists())
        with self.assertRaises(ValueError):
            create_backup(database, self.root / "runs" / "one" / "backup.zip")

    def test_startup_offer_later_preserves_inactive_copy(self):
        _, path = self.inactive_copy()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as prompt:
            self.controller.offerRecovery()
        self.assertEqual(prompt.call_count, 1)
        self.assertTrue(path.exists())

    def test_nonterminal_run_is_unconfirmed_read_only_and_never_queryable(self):
        project, database = self.backup_fixture()
        run = self.root / "runs" / "one"
        status = run / "run_config.json"
        for state in ["queued", "running"]:
            status.write_text(json.dumps(dict(project_id=project.project_id, status=state)))
            before = status.read_bytes()
            self.controller.project, self.controller.path = project, database
            self.assertEqual(self.controller._runs()[0]["status"], "interrupted / unconfirmed")
            self.assertTrue(self.controller.openRun(str(run)))
            self.assertIsNone(self.controller.repository)
            self.assertIn("Another application", self.controller.messages[-1])
            self.assertEqual(status.read_bytes(), before)
            self.assertFalse(self.controller.loadNetworkRun(str(run)))
