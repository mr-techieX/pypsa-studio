"""Qt bridge: file dialogs and view state, not mathematical model construction."""

import json
from copy import deepcopy
from pathlib import Path
import sys

import pandas as pd

from .demo_library import DEMO_SPECS, make_demo
from .diagnostics import failure_message, run_metadata
from .engine import prepare_run, write_json
from .run_layout import metadata_path
from .profiles import import_profile, preview_csv
from .project import Project
from .schema import attribute_spec, parse_value, registry
from .storage import load_project, save_project
from .results import ResultsRepository, query_charts
from .workspace import QueryWorkspace, QueryTab
from .validation import formulation_warnings
from .sheet import ObjectSheet
from .editor_config import checked_config, property_specs, visible_categories, visible_properties
from .references import property_reference, reference_catalogue
from .object_edits import delete_candidate, deletion_preview, rename_candidate
from .network_view import topology, frozen_overlay, checked_layout, saved_layout
from .layout_state import sheet_state
from .history import ModelHistory
from .study_extensions import StudyExtensions

# Keep scientific dependencies ahead of PySide's import-inspection hook.
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, Property, QProcess, QThread, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox


class ResultTable(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame = pd.DataFrame()

    def replace(self, frame):
        self.beginResetModel()
        self.frame = frame.head(1000).fillna("").astype(str)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role == Qt.ItemDataRole.DisplayRole:
            return self.frame.iat[index.row(), index.column()]
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            return str(self.frame.columns[section]) if orientation == Qt.Orientation.Horizontal else str(section + 1)
        return None


class Controller(StudyExtensions):
    changed = Signal()
    uiStateChanged = Signal()
    notice = Signal(str)
    runCompleted = Signal()
    resultsOpened = Signal()
    queryOptionsChanged = Signal()
    querySelectionChanged = Signal("QVariantMap")
    editorReset = Signal()
    helpersReset = Signal()
    helpersChanged = Signal()
    networkChanged = Signal()
    analysisViewRequested = Signal(int)

    def __init__(self):
        super().__init__()
        self._ui_state_cache = None
        # Register before QML observers: each notification starts one fresh,
        # lazily built UI snapshot, shared by all bindings for that revision.
        self.changed.connect(self._invalidate_ui_state)
        # These signals also have imperative QML readers and can precede changed.
        self.editorReset.connect(self._invalidate_ui_state)
        self.helpersReset.connect(self._invalidate_ui_state)
        self.helpersChanged.connect(self._invalidate_ui_state)
        self.project = Project()
        self.path = None
        self.dirty = False
        self.component = "Bus"
        self.selected = ""
        self._result_model = ResultTable(self)
        self._result_frame = pd.DataFrame()
        self._filtered_frame = pd.DataFrame()
        self._chart = {"series": [], "labels": []}
        self._charts = []
        self.repository = None
        self.query_categories = []
        self.query_snapshots = []
        self.query_description = "No query executed. Select objects and properties, then click Query."
        self._query_specs = []
        self._query_temporal = False
        self.catalog = []
        self.run_directory = None
        self.run_meta = {}
        self.process = None
        self._backup_thread = None
        self._backup_worker = None
        self.backup_progress = 0
        self.cancel_requested = False
        self.progress_stage = "idle"
        self.messages = []
        self.events_buffer = ""
        self.csv_info = {"path": "", "columns": [], "preview": ""}
        self.workspace = QueryWorkspace()
        self._draft_name = ""
        self._draft_json = "{}"
        self._sheet = ObjectSheet(lambda: self.process is None and self.component in visible_categories(self.project), self)
        self._sheet.load(self.project, self.component)
        self._sheet.statusChanged.connect(self.changed)
        self._sheet_undo = []
        self._sheet_redo = []
        self.model_history = ModelHistory()
        self._settings_draft = None
        self._csv_mapping = {}
        self._csv_pending = False
        self._network_repository = None
        self._network_directory = None
        self._network_graph = None
        self._network_index = 0
        self._network_generation = 0
        self.changed.connect(self.networkChanged)
        # Enabled only by the desktop entry point, never silently by headless
        # controllers/tests. Tests inject their own isolated recovery directory.
        self.recovery_store = None
        self._recovery_timer = QTimer(self)
        self._recovery_timer.setSingleShot(True)
        self._recovery_timer.setInterval(1000)
        self._recovery_timer.timeout.connect(self.flushRecovery)
        self.changed.connect(self._schedule_recovery)
        self._initialize_studies()

    def enableRecovery(self, directory):
        from .safety import RecoveryStore
        self.recovery_store = RecoveryStore(directory)

    def _schedule_recovery(self):
        if self.recovery_store and self.dirty and not self._recovery_timer.isActive():
            self._recovery_timer.start()

    @Slot(result=bool)
    def flushRecovery(self):
        self._recovery_timer.stop()
        if not self.recovery_store or not self.dirty:
            return True
        try:
            self.recovery_store.capture(self.project, self.path)
            return True
        except Exception as error:
            self._error(ValueError("Recovery copy could not be updated; use Save/backup. " + str(error)))
            return False

    def _clear_recovery(self):
        self._recovery_timer.stop()
        if self.recovery_store:
            try:
                self.recovery_store.clear()
            except OSError as error:
                self._error(error)

    @Slot()
    def recoverProject(self):
        if not self.recovery_store or self.process:
            return
        try:
            candidates = self.recovery_store.candidates()
        except Exception as error:
            self._error(error)
            return
        if not candidates:
            self.notice.emit("No recovery copies from inactive sessions. Active sessions are excluded.")
            return
        labels = [p.name for p in candidates]
        label, accepted = QInputDialog.getItem(None, "Recovery copies · inspect before restoring",
                                             "Choose a copy (UTC date/source shown next):", labels, 0, False)
        if not accepted:
            return
        path = candidates[labels.index(label)]
        claim = None
        try:
            claim = self.recovery_store.claim(path)
            project, meta = self.recovery_store.inspect(path)
            answer = QMessageBox.question(None, "Inspect recovery copy",
                f"{meta['project']}\nCaptured: {meta['created_utc']}\nOriginal: {meta['source'] or '(never saved)'}\n\n"
                "Yes: restore as an UNSAVED project. Original SQLite/runs will not be overwritten. "
                "Only applied model changes are captured, not pending fields, spreadsheet drafts or query tabs. "
                "Discard deletes only this recovery copy; Cancel keeps it for later.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Discard:
                path.unlink()
                return
            if answer != QMessageBox.StandardButton.Yes or not self._can_replace():
                return
            # Capture in this active session BEFORE deleting the offered copy.
            self.recovery_store.capture(project, None)
            self.project, self.path, self.selected = project, None, ""
            self.component = "Bus"
            self._reset_helpers()
            self._reset_draft()
            self._reset_results()
            self._touch()
            path.unlink()
            self.notice.emit("Recovered as unsaved. Save to a NEW file in the original folder to retain access to its matching runs; original files were not changed.")
        except Exception as error:
            self._error(ValueError("Recovery copy remains available if unreadable; no automatic repair. " + str(error)))
        finally:
            if claim:
                claim.unlock()

    @Slot()
    def offerRecovery(self):
        try:
            if self.recovery_store and self.recovery_store.candidates():
                answer = QMessageBox.question(None, "Recovery available", "An inactive session has recovery copies. Inspect now? You can also use File → Recover applied changes… later.",
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
                if answer == QMessageBox.StandardButton.Yes:
                    self.recoverProject()
        except Exception as error:
            self._error(error)

    @Slot(result=bool)
    def backupProject(self):
        if self.process or self.path is None:
            self.notice.emit("Save a project and stop its active run before making a backup.")
            return False
        path, _ = QFileDialog.getSaveFileName(None, "Backup SAVED project + matching runs (not unsaved edits). Stop other application writers first.", "project-backup.zip", "ZIP backup (*.zip)")
        if not path:
            return False
        try:
            from .safety import create_backup
            result = create_backup(self.path, Path(path).with_suffix(".zip"))
            self.notice.emit("Saved-project backup created: " + str(result))
            return True
        except Exception as error:
            self._error(error)
            return False

    def _network_layout_key(self):
        return "run:" + self._network_directory.name if self._network_directory else "current"

    @Slot(result=bool)
    def startBackup(self):
        if self.process or self._backup_thread or not self.path:
            self.notice.emit("Save first and stop active work before starting a backup.")
            return False
        path, _ = QFileDialog.getSaveFileName(None, "Background backup of SAVED project + runs (stop other writers)", "project-backup.zip", "ZIP (*.zip)")
        if not path:
            return False
        from .backup_worker import BackupWorker
        self.backup_progress = 0
        self._backup_thread = QThread(self)
        self._backup_worker = BackupWorker(self.path, Path(path).with_suffix(".zip"))
        self._backup_worker.moveToThread(self._backup_thread)
        self._backup_thread.started.connect(self._backup_worker.run)
        self._backup_worker.progress.connect(self._backup_progress)
        self._backup_worker.finished.connect(self._backup_finished)
        self._backup_thread.finished.connect(self._backup_cleanup)
        self._backup_thread.finished.connect(self._backup_thread.deleteLater)
        self._backup_thread.start()
        self.changed.emit()
        return True

    @Slot(int)
    def _backup_progress(self, value):
        self.backup_progress = value
        self.changed.emit()

    @Slot(str, bool)
    def _backup_finished(self, message, success):
        self._backup_message = message
        self._backup_worker.deleteLater()
        self._backup_thread.quit()

    @Slot()
    def _backup_cleanup(self):
        self._backup_thread = None
        self._backup_worker = None
        self.changed.emit()
        self.notice.emit(self._backup_message)

    @Slot()
    def cancelBackup(self):
        if self._backup_worker:
            self._backup_worker.cancelled.set()

    @Property("QVariantList", notify=changed)
    def savedAnalyses(self):
        return [dict(id=a.get("id", ""), title=a.get("title", "Invalid analysis")) for a in self.project.analysis_workspace if isinstance(a, dict)]

    @Slot(str, result=bool)
    def saveAnalysis(self, title):
        if self.process or self._backup_thread:
            return False
        try:
            if any(tab.run_meta.get("source_kind") == "netcdf" for tab in self.workspace.tabs):
                raise ValueError("Close external NetCDF tabs before saving a Studio run dashboard.")
            from .analysis import capture_analysis
            saved = capture_analysis(self.path, self.workspace, title)
            if len(self.project.analysis_workspace) >= 50:
                raise ValueError("At most 50 saved dashboards per project.")
            self.project.analysis_workspace.append(saved)
            self._touch()
            return True
        except Exception as error:
            self._error(error)
            return False

    @Slot(int, int, result=bool)
    def arrangeAnalysis(self, index, direction):
        items = self.project.analysis_workspace
        if self.process or self._backup_thread or not 0 <= index < len(items):
            return False
        if direction == 0:
            items.pop(index)
        elif direction in {-1, 1} and 0 <= index+direction < len(items):
            items[index], items[index+direction] = items[index+direction], items[index]
        else:
            return False
        self._touch()
        return True

    @Slot(int, result=bool)
    def restoreAnalysis(self, index):
        if self.process or self._backup_thread:
            return False
        try:
            from .analysis import prepare_analysis
            if not 0 <= index < len(self.project.analysis_workspace):
                raise ValueError("Select an existing saved dashboard.")
            prepared, active = prepare_analysis(self.project, self.path, self.project.analysis_workspace[index])
            if not self.resolveDraft():
                return False
            if self.workspace.tabs and QMessageBox.question(None, "Restore saved dashboard", "Replace session query tabs with these saved queries? Saved run files stay unchanged.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return False
            tabs = []
            for card, repo, meta, frame, specs, temporal in prepared:
                tabs.append(QueryTab(title=f"{card['criteria']['component']} · saved query", run_path=str(repo.directory), run_meta=meta,
                    criteria=card["criteria"], frame=frame, specs=specs, temporal=temporal, description="Saved analysis · " + str(repo.directory.name),
                    chart_types=card.get("chart_types", {}), pinned=card.get("pinned", False), view=card.get("view", 0),
                    listing=card.get("listing", "snapshot"), table_form=card.get("table_form", "wide"),
                    chart_range=card.get("chart_range", [0, -1]),
                    sort_column=card.get("sort_column", ""), sort_descending=card.get("sort_descending", False)))
            self.workspace.tabs, self.workspace.active_id = tabs, tabs[active].id
            card, repo, meta, *_ = prepared[active]
            self.run_directory, self.run_meta, self.repository = repo.directory, meta, repo
            self.catalog = repo.catalog
            self.query_categories, self.query_snapshots = repo.describe(), list(repo.project.snapshots)
            self.queryOptionsChanged.emit()
            self._show_active_tab()
            self.querySelectionChanged.emit(tabs[active].criteria)
            self.analysisViewRequested.emit(tabs[active].view)
            return True
        except Exception as error:
            self._error(error)
            return False

    @Slot(int)
    def setAnalysisView(self, view):
        if self.workspace.active and view in {0, 1}:
            self.workspace.active.view = view

    @Slot(str, str, result=str)
    def compareRuns(self, left, right):
        try:
            if not self.workspace.active:
                raise ValueError("Execute a query first; comparison uses its captured criteria, not draft selections.")
            from .analysis import compare_query, run_path
            frame, meta = compare_query(self.project, run_path(self.path, left), run_path(self.path, right), self.workspace.active.criteria)
            frame["left_run"], frame["right_run"], frame["currency"] = left, right, meta["currency"]
            self._comparison_frame, self._comparison_meta = frame, meta
            self._comparison_capture = {"run_path": str(run_path(self.path, left)),
                                        "criteria": deepcopy(self.workspace.active.criteria)}
            return json.dumps(meta, indent=2, allow_nan=False) + "\n\n" + frame.head(100).to_string(index=False) + f"\nPreview 100 of {len(frame)} rows; export full comparison CSV."
        except Exception as error:
            self._comparison_frame = None
            self._comparison_capture = None
            self._error(error)
            return "Comparison unavailable; previous query tabs and frozen network are unchanged."

    @Slot()
    def exportComparison(self):
        frame = getattr(self, "_comparison_frame", None)
        if frame is None:
            self.notice.emit("Run a compatible comparison first.")
            return
        path, _ = QFileDialog.getSaveFileName(None, "Export full right-minus-left comparison", "comparison.csv", "CSV (*.csv)")
        if path:
            try:
                destination = self._safe_analysis_export(path)
                frame.to_csv(destination, index=False)
            except Exception as error:
                self._error(error)

    def _safe_analysis_export(self, path):
        destination = Path(path).resolve()
        if destination.suffix.lower() == ".nc":
            raise ValueError("Choose a non-NetCDF destination; original results are read-only.")
        if self.path and (destination == Path(self.path).resolve() or destination.is_relative_to((Path(self.path).resolve().parent/"runs").resolve())):
            raise ValueError("Export outside the project database and frozen runs directory.")
        return destination

    @Slot(str, result=bool)
    def exportAnalysis(self, kind):
        try:
            tab = self.workspace.active
            if not tab:
                raise ValueError("Execute a query first.")
            if tab.run_meta.get("source_kind") == "netcdf" and kind != "chart":
                raise ValueError("External NetCDF supports query CSV and chart export; study reports and formulations require a Studio run.")
            from .reporting import annotate_formulation, write_chart, write_report
            choices = {"chart": ("charts.svg", "Chart (*.svg *.png)"), "report": ("study.html", "HTML (*.html)"), "formulation": ("formulation-readable.txt", "Text (*.txt)")}
            filename, filter = choices[kind]
            path, _ = QFileDialog.getSaveFileName(None, "Export captured analysis (local)", filename, filter)
            if not path:
                return False
            destination = self._safe_analysis_export(path)
            frozen = Path(tab.run_path).resolve()
            if destination.is_relative_to(frozen) or destination == self.path:
                raise ValueError("Export outside the frozen run and project database.")
            charts = query_charts(tab.frame, tab.specs, tab.temporal, tab.chart_types, self._chart_bounds(tab))
            if kind == "chart":
                write_chart(destination, charts)
            elif kind == "report":
                from .analysis import repository_for, run_metrics
                repo, meta = repository_for(self.project, tab.run_path)
                from dataclasses import replace
                from .temporal import listing
                presented = replace(tab, frame=listing(tab.frame, tab.specs, tab.temporal, tab.listing, tab.table_form))
                write_report(destination, presented, charts, run_metrics(repo, meta))
            else:
                annotate_formulation(tab.run_path, destination)
            return True
        except Exception as error:
            self._error(error)
            return False

    @Slot(result=str)
    def advancedInputs(self):
        return json.dumps(self.project.advanced_inputs or dict(weights=[], periods=[], snapshot_periods=[], piecewise=[]), indent=2)

    @Slot(str, result=bool)
    def applyAdvancedInputs(self, text):
        if self.process or self._backup_thread or not self.resolveDraft():
            return False
        try:
            from .advanced import checked_advanced
            before = self.project.to_dict()
            candidate = Project(**deepcopy(before))
            candidate.advanced_inputs = checked_advanced(candidate, json.loads(text))
            self.project = candidate
            self._record_model_edit(before, "Advanced time/curve inputs")
            self._touch()
            return True
        except Exception as error:
            self._error(error)
            return False

    @Slot(str, str, str, result=str)
    def profileGrid(self, component, name, attribute):
        try:
            spec = attribute_spec(component, attribute)
            if not spec["varying"] or not spec["input"] or not self.project.object(component, name):
                raise ValueError("Choose an existing object and time-varying input.")
            record = self.project.object(component, name)
            values = next((p["values"] for p in self.project.profiles if (p["component"], p["name"], p["attribute"]) == (component, name, attribute)), [record["attributes"].get(attribute, spec["default"])]*len(self.project.snapshots))
            return "snapshot\tvalue\n" + "".join(f"{t}\t{v}\n" for t,v in zip(self.project.snapshots, values))
        except Exception as error:
            self._error(error)
            return ""

    @Slot(str, str, str, str, result=bool)
    def applyProfileGrid(self, component, name, attribute, text):
        if self.process or self._backup_thread or not self.resolveDraft():
            return False
        try:
            from io import StringIO
            import math
            if len(text.encode("utf-8")) > 10*1024*1024:
                raise ValueError("Profile grid limit: 10 MiB TSV.")
            spec = attribute_spec(component, attribute)
            if not spec["varying"] or not spec["input"] or not self.project.object(component, name):
                raise ValueError("Choose an existing object and varying input.")
            frame = pd.read_csv(StringIO(text), sep="\t")
            if list(frame.columns) != ["snapshot", "value"]:
                raise ValueError("Use snapshot and value TSV columns.")
            index = pd.DatetimeIndex(pd.to_datetime(frame["snapshot"]))
            target = pd.DatetimeIndex(self.project.snapshots)
            if index.has_duplicates or index.tz is not None or set(index) != set(target) or len(index) != len(target):
                raise ValueError("Profile timestamps must exactly match the project; no implicit resampling.")
            values = pd.Series(pd.to_numeric(frame["value"]).to_numpy(), index=index).reindex(target).tolist()
            if any(not math.isfinite(v) for v in values):
                raise ValueError("Profile values must be finite.")
            before = self.project.to_dict()
            candidate = Project(**deepcopy(before))
            candidate.profiles = [p for p in candidate.profiles if (p["component"],p["name"],p["attribute"]) != (component,name,attribute)]
            candidate.profiles.append(dict(component=component,name=name,attribute=attribute,values=values,unit=spec["unit"],source="Structured TSV editor"))
            introduced = set(candidate.validate())-set(self.project.validate())
            if introduced:
                raise ValueError("\n".join(sorted(introduced)))
            self.project = candidate
            self._record_model_edit(before, "Edit profile grid")
            self._touch()
            return True
        except Exception as error:
            self._error(error)
            return False

    def _record_model_edit(self, before, label, identity=None):
        if not self.model_history.record(before, self.project.history_snapshot(), label, identity):
            self.notice.emit("Applied edit exceeds the 32 MiB encoded history budget. Model retained; model Undo/Redo cleared. Save/make a backup.")

    @Slot(bool, result=bool)
    def modelHistory(self, redo):
        if self.process or not self.resolveDraft():
            return False
        try:
            entry = self.model_history.entry(self.project.model_state(), redo)
            data = deepcopy(entry["after" if redo else "before"])
            # View saves/drags are not model-history commands. Preserve newer
            # layouts, but reverse identity-key changes and prune live removals.
            data["schematic_layouts"] = deepcopy(self.project.schematic_layouts)
            data["analysis_workspace"] = deepcopy(self.project.analysis_workspace)
            data["scenario_library"] = deepcopy(self.project.scenario_library)
            data["interchange_info"] = self.project.interchange_info
            candidate = Project(**data)
            if entry["identity"]:
                from .network_view import edit_layout_identity
                kind, old, new = entry["identity"]
                edit_layout_identity(candidate, kind, old if redo else new, new if redo else old)
            layout = candidate.schematic_layouts.get("current", {})
            if isinstance(layout, dict) and isinstance(layout.get("positions"), dict):
                keys = {o["key"] for o in topology(candidate)["objects"]}
                # Deleted objects can regain their previously saved positions;
                # all surviving positions/viewport and historical layouts stay put.
                prior = entry["after" if redo else "before"].get("schematic_layouts", {}).get("current", {}).get("positions", {})
                layout["positions"] = {k: v for k, v in layout["positions"].items() if k in keys}
                for key, point in prior.items():
                    if (key in keys and key not in layout["positions"]
                            and point["x"] <= layout.get("width", 900)
                            and point["y"] <= layout.get("height", 520)):
                        layout["positions"][key] = deepcopy(point)
            self.project = candidate
            self.model_history.commit_step(redo)
            # Separate legacy spreadsheet stacks cannot replay across this step.
            self._sheet_undo.clear()
            self._sheet_redo.clear()
            shown = visible_categories(self.project)
            if self.component not in shown:
                self.component = shown[0] if shown else "Bus"
            if not self.project.object(self.component, self.selected):
                self.selected = ""
            self._reset_helpers()
            self._sheet.load(self.project, self.component)
            self._reset_draft()
            self._touch()  # Unsaved + eligible for applied-state recovery; no disk/run writes.
            return True
        except (ValueError, TypeError, KeyError) as error:
            self._error(error)
            return False

    @Property("QVariantMap", notify=networkChanged)
    def networkState(self):
        frozen = self._network_repository is not None
        graph = self._network_graph if frozen else topology(self.project)
        key = self._network_layout_key()
        layout = saved_layout(self.project, key, graph)
        if frozen and not layout:
            # Use the layout captured WITH this run as its initial schematic,
            # never the current edited model's live coordinates.
            layout = saved_layout(self._network_repository.project, "current", graph)
        runs = [r for r in self._runs() if r["status"] == "succeeded"]
        if frozen and not any(r["path"] == str(self._network_directory) for r in runs):
            runs.insert(0, {"path": str(self._network_directory), "name": self._network_directory.name})
        period_label = ""
        if frozen:
            periods = self._network_repository.project.advanced_inputs.get("snapshot_periods", [])
            if periods:
                period_label = f" · investment period {periods[self._network_index]}"
        return {"frozen": frozen, "topology": graph, "runs": runs,
                "source": self._network_directory.name + period_label if frozen else "Current project inputs · no solved flows",
                "snapshots": self._network_repository.project.snapshots if frozen else [],
                "snapshotIndex": self._network_index,
                "viewKey": self.project.project_id + ":" + key + ":" + str(self._network_generation),
                "layout": layout}

    @Slot()
    def showLiveNetwork(self):
        self._network_repository = None
        self._network_directory = None
        self._network_graph = None
        self._network_index = 0
        self.networkChanged.emit()

    @Slot()
    def browseNetworkRun(self):
        path = QFileDialog.getExistingDirectory(None, "Select a successful frozen run for network flows")
        if path:
            self.loadNetworkRun(path)

    @Slot(str, result=bool)
    def loadNetworkRun(self, directory):
        try:
            path = Path(directory).resolve()
            config = run_metadata(path)
            if config.get("status") != "succeeded" or config.get("project_id") != self.project.project_id:
                raise ValueError("Choose a successful run belonging to this project.")
            repository = ResultsRepository(path, json.loads(metadata_path(path, "catalog.json").read_text(encoding="utf-8")))
            if repository.project.project_id != self.project.project_id:
                raise ValueError("Frozen run inputs and project identity disagree.")
            graph = frozen_overlay(repository, repository.project.snapshots[0])
            self._network_repository, self._network_directory = repository, path
            self._network_graph, self._network_index = graph, 0
            self.networkChanged.emit()
            return True
        except (ValueError, OSError, KeyError, IndexError) as error:
            self._error(error)
            return False

    @Slot(int, result=bool)
    def setNetworkSnapshot(self, index):
        if self._network_repository is None:
            return False
        try:
            snapshots = self._network_repository.project.snapshots
            if not 0 <= index < len(snapshots):
                raise ValueError("Select a snapshot from the displayed frozen run.")
            graph = frozen_overlay(self._network_repository, snapshots[index])
            self._network_graph, self._network_index = graph, index
            self.networkChanged.emit()
            return True
        except (ValueError, OSError, KeyError) as error:
            self._error(error)
            return False

    @Slot(str, "QVariantMap", result=bool)
    def saveNetworkLayout(self, view_key, layout):
        if self.process or view_key != self.networkState["viewKey"] or not self.resolveDraft():
            return False
        try:
            keys = {o["key"] for o in self.networkState["topology"]["objects"]}
            clean = checked_layout(dict(layout), keys)
            if len(self.project.schematic_layouts) >= 101 and self._network_layout_key() not in self.project.schematic_layouts:
                raise ValueError("At most 100 historical layouts plus the current layout can be saved per project.")
            self.project.schematic_layouts[self._network_layout_key()] = clean
            self._touch()
            # Explicit Save layout saves the project too. If cancelled/failed,
            # the captured layout remains an unsaved project change, not lost data.
            return self.saveProject()
        except (ValueError, TypeError) as error:
            self._error(error)
            return False

    def _live_settings(self):
        return {"name": self.project.name, "currency": self.project.currency,
                "start": self.project.snapshots[0], "count": len(self.project.snapshots),
                "minutes": round(self.project.duration_hours * 60)}

    @Property("QVariantMap", notify=helpersChanged)
    def helperState(self):
        return {"settings": self._settings_draft or self._live_settings(),
                "settingsDirty": self._settings_draft is not None,
                "csv": self._csv_mapping, "csvDirty": self._csv_pending}

    def _reset_helpers(self):
        self._settings_draft = None
        self.csv_info = {"path": "", "columns": [], "preview": ""}
        self._csv_mapping = {}
        self._csv_pending = False
        self.helpersChanged.emit()
        self.helpersReset.emit()

    @Slot(str, str, str, int, int)
    def updateSettingsDraft(self, name, currency, start, count, minutes):
        if self.process:
            return
        draft = dict(name=name, currency=currency, start=start, count=count, minutes=minutes)
        self._settings_draft = draft if draft != self._live_settings() else None
        self.helpersChanged.emit()

    @Slot(result=bool)
    def applySettingsDraft(self):
        if self.process:
            return False
        if self._settings_draft is None:
            return True
        try:
            values = self._settings_draft
            candidate = Project(**deepcopy(self.project.to_dict()))
            candidate.set_horizon(values["start"], values["count"], values["minutes"])
            candidate.name = values["name"].strip() or "Untitled energy system"
            candidate.currency = values["currency"].strip() or "currency"
            before = self.project.to_dict()
            self.project = candidate
            self._record_model_edit(before, "Project settings")
            self._settings_draft = None
            self.helpersChanged.emit()
            self.helpersReset.emit()
            self._touch()
            return True
        except (ValueError, TypeError) as error:
            self._error(error)
            return False

    @Slot()
    def discardSettingsDraft(self):
        self._settings_draft = None
        self.helpersChanged.emit()
        self.helpersReset.emit()

    @Slot(str, str, str, str, str)
    def updateCsvDraft(self, component, name, attribute, timestamp_column, value_column):
        if self.process:
            return
        mapping = dict(component=component, name=name, attribute=attribute,
                       timestamp=timestamp_column, value=value_column)
        if mapping != self._csv_mapping:
            self._csv_mapping = mapping
            self._csv_pending = True
            self.helpersChanged.emit()

    @Slot(str, result="QVariantMap")
    def profileOptions(self, component):
        return {"objects": [r["name"] for r in self.project.objects if r["component"] == component],
                "attributes": [a["name"] for a in property_specs(self.project, component)
                               if a["input"] and a["varying"]]}

    @Slot(str, str, result=bool)
    def objectExists(self, component, name):
        return self.project.object(component, name) is not None

    @Slot()
    def discardCsvDraft(self):
        self.csv_info = {"path": "", "columns": [], "preview": ""}
        self._csv_mapping = {}
        self._csv_pending = False
        self.helpersChanged.emit()
        self.helpersReset.emit()
        self.changed.emit()

    @Slot(result=bool)
    def applyCsvDraft(self):
        if self.process:
            return False
        if not self._csv_pending:
            return True
        try:
            mapping = self._csv_mapping
            if not self.csv_info["path"]:
                raise ValueError("Choose a CSV file before importing, or discard the import selections.")
            candidate = Project(**deepcopy(self.project.to_dict()))
            import_profile(candidate, self.csv_info["path"], mapping["component"], mapping["name"],
                           mapping["attribute"], mapping["timestamp"], mapping["value"])
            before = self.project.to_dict()
            self.project = candidate
            self._record_model_edit(before, "Import profile")
            self.discardCsvDraft()
            self._touch()
            return True
        except (ValueError, TypeError, KeyError, OSError) as error:
            self._error(error)
            return False

    def _resolve_helpers(self):
        for pending, title, apply, discard in [
            (lambda: self._settings_draft is not None, "Unapplied project settings", self.applySettingsDraft, self.discardSettingsDraft),
            (lambda: self._csv_pending, "Unimported CSV selections", self.applyCsvDraft, self.discardCsvDraft),
        ]:
            if pending():
                answer = QMessageBox.question(None, title,
                    "Apply these pending changes before continuing? Save applies them to the in-memory project; Discard clears the helper draft. Cancel stays here.",
                    QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel)
                if answer == QMessageBox.StandardButton.Save:
                    if not apply():
                        return False
                elif answer == QMessageBox.StandardButton.Discard:
                    discard()
                else:
                    return False
        return True

    @Property(QObject, constant=True)
    def sheetModel(self):
        return self._sheet

    @Property(QObject, constant=True)
    def resultModel(self):
        return self._result_model

    @Property("QVariantMap", notify=queryOptionsChanged)
    def queryOptions(self):
        # Only notify when a run changes, not on Query/result updates. This keeps
        # QML snapshot dropdowns and draft selections from being reset mid-query.
        from .temporal import available_resolutions
        repo = self.repository
        if (repo is not None and hasattr(repo, "project") and getattr(repo, "has_weights", True)
                and not hasattr(repo, "_calendar_resolutions")):
            repo._calendar_resolutions = available_resolutions(repo.project)
        return {"categories": self.query_categories, "snapshots": self.query_snapshots,
                 "sourceLoaded": repo is not None,
                 "resolutions": getattr(repo, "_calendar_resolutions", ["native"]),
                 "external": getattr(repo, "description", ""),
                 "externalName": repo.path.name if getattr(repo, "description", "") else "",
                 "externalPath": str(repo.path) if getattr(repo, "description", "") else ""}

    @Property("QVariantMap", notify=changed)
    def state(self):
        # Python callers may intentionally inspect externally mutated fixtures
        # before emitting changed. Keep that contract uncached.
        return self._build_state()

    def _invalidate_ui_state(self):
        self._ui_state_cache = None
        # QML property notifiers can run before ordinary slots on the same
        # signal. Notify only AFTER invalidating, never via changed directly.
        self.uiStateChanged.emit()

    @Property("QVariantMap", notify=uiStateChanged)
    def uiState(self):
        if self._ui_state_cache is None:
            self._ui_state_cache = self._build_state()
        return self._ui_state_cache

    def _build_state(self):
        objects = [o for o in self.project.objects if o["component"] == self.component]
        selected = self.project.object(self.component, self.selected)
        counts = {name: sum(o["component"] == name for o in self.project.objects) for name in registry()}
        attrs = property_specs(self.project, self.component)
        visible = visible_categories(self.project)
        shown_attrs = set(visible_properties(self.project, self.component))
        # Comparisons read model fields only; no serialization, metadata clone
        # or history work at all when no stack exists or a worker owns the model.
        idle = not self.process
        comparison = self.project.model_state() if idle and (
            self._sheet_undo or self._sheet_redo or self.model_history.undo or self.model_history.redo
        ) else None
        return {
            "projectName": self.project.name, "projectId": self.project.project_id, "path": str(self.path) if self.path else "Not saved · choose a project folder with Save",
            "dirty": self.dirty, "component": self.component, "selected": self.selected,
            "types": [{"name": n, "count": counts[n], "editable": d["editable"]} for n, d in registry().items()],
            "visibleTypes": [{"name": n, "count": counts[n], "editable": registry()[n]["editable"]} for n in visible],
            "componentVisible": self.component in visible,
            "propertyFilterActive": shown_attrs != {a["name"] for a in attrs},
            "objects": [{**o, "summary": ", ".join(f"{k}: {v}" for k, v in list(o["attributes"].items())[:3])} for o in objects],
            "objectCount": len(self.project.objects), "busCount": counts["Bus"], "profileCount": len(self.project.profiles),
            "snapshotCount": len(self.project.snapshots), "duration": self.project.duration_hours,
            "demoInfo": self.project.demo_info,
            "start": self.project.snapshots[0], "currency": self.project.currency,
            "editable": registry()[self.component]["editable"] and self.component in visible,
            "schema": [a for a in attrs if a["name"] in shown_attrs],
            "attributesJson": json.dumps(selected["attributes"] if selected else {}, indent=2),
            "inputNames": [a["name"] for a in attrs if a["input"] and a["static"] and a["name"] != "name" and a["name"] in shown_attrs],
            "profileAttributes": [a["name"] for a in attrs if a["input"] and a["varying"]],
            "profiles": [{**p, "values": [], "length": len(p["values"])} for p in self.project.profiles],
            "busy": self.process is not None or self._backup_thread is not None or self._batch_active, "stage": self.progress_stage,
            "backupBusy": self._backup_thread is not None, "backupProgress": self.backup_progress,
            "messages": "\n".join(self.messages[-300:]), "runPath": str(self.run_directory or ""),
            "runStatus": self.run_meta.get("status", "No run loaded"),
            "objective": str(round(self.run_meta["objective"], 3)) if "objective" in self.run_meta else "—",
            "catalog": self.catalog, "csv": self.csv_info, "chart": self._chart,
            "charts": self._charts, "queryCategories": self.query_categories,
            "chartRange": self._chart_range_info(),
            "resultListing": self.workspace.active.listing if self.workspace.active else "snapshot",
            "resultForm": self.workspace.active.table_form if self.workspace.active else "wide",
            "queryUnits": " · ".join(s["name"]+" ["+s.get("unit", "")+"]"
                + (" "+s["metric"] if "metric" in s else "") for s in self._query_specs),
            "resultSort": self.workspace.active.sort_column if self.workspace.active else "",
            "resultSortDescending": self.workspace.active.sort_descending if self.workspace.active else False,
            "querySnapshots": self.query_snapshots, "queryDescription": self.query_description,
            "resultRows": len(self._filtered_frame), "resultShown": min(1000, len(self._filtered_frame)),
            "runs": self._runs(), "topology": self._topology(),
            "queryTabs": [{"id": t.id, "title": t.title, "pinned": t.pinned, "run": Path(t.run_path).name} for t in self.workspace.tabs],
            "activeTabId": self.workspace.active_id,
            "queryRun": Path(self.workspace.active.run_path).name if self.workspace.active else "",
            "queryObjective": str(self.workspace.active.run_meta.get("objective", "—")) if self.workspace.active else "—",
            "busNames": [o["name"] for o in self.project.objects if o["component"] == "Bus"],
            "sheetDirty": self._sheet.dirty,
            "sheetCanUndo": bool(idle and self._sheet_undo and comparison == sheet_state(self._sheet_undo[-1][1])),
            "sheetCanRedo": bool(idle and self._sheet_redo and comparison == sheet_state(self._sheet_redo[-1][0])),
            "modelCanUndo": bool(idle and self.model_history.undo and self.model_history.available(comparison)),
            "modelCanRedo": bool(idle and self.model_history.redo and self.model_history.available(comparison, True)),
            "modelUndoLabel": self.model_history.undo[-1]["label"] if self.model_history.undo else "",
            "modelRedoLabel": self.model_history.redo[-1]["label"] if self.model_history.redo else "",
        }

    @Slot(result="QVariantMap")
    def editorConfiguration(self):
        return {
            "categories": visible_categories(self.project),
            "properties": {name: visible_properties(self.project, name) for name in registry()},
            "catalogue": {name: property_specs(self.project, name) for name in registry()},
        }

    @Slot(result="QVariantMap")
    def referenceCatalogue(self):
        return reference_catalogue(self.project)

    @Slot(str, str, result="QVariantMap")
    def propertyReference(self, component, name):
        try:
            return property_reference(self.project, component, name)
        except ValueError as error:
            return {"component": component, "name": name, "description": str(error), "guide": ""}

    @Slot("QVariantList", "QVariantMap", result=bool)
    def applyEditorConfiguration(self, categories, properties):
        if self.process:
            return False
        try:
            config = checked_config(self.project, list(categories), dict(properties))
            if not self.resolveDraft():
                return False
            before = self.project.to_dict()
            self.project.editor_config = config
            self._record_model_edit(before, "Visibility configuration")
            shown = visible_categories(self.project)
            if self.component not in shown:
                self.component = shown[0] if shown else "Bus"
                self.selected = ""
            self._reset_draft()
            self._touch()
            return True
        except (ValueError, TypeError) as error:
            self._error(error)
            return False

    def _topology(self):
        return topology(self.project)

    @Slot(str, str, result=bool)
    def inspectNetworkObject(self, component, name):
        """Select atomically: cancelling a draft must not partially change type."""
        if self._network_repository is not None:
            historical = self._network_repository.project.object(component, name)
            current = self.project.object(component, name)
            if historical is None or current != historical:
                self.notice.emit("Historical object differs from the current model. Switch to Live inputs to edit; frozen-run details remain read-only.")
                return False
        if not self.project.object(component, name) or not self.resolveDraft():
            return False
        self.component, self.selected = component, name
        self._reset_draft()
        self.changed.emit()
        return True

    def _runs(self):
        if self.path is None or not (self.path.parent / "runs").is_dir():
            return []
        runs = []
        root = self.path.parent / "runs"
        directories = {p.parent for p in root.glob("*/run_config.json")}
        directories.update(p.parent.parent for p in root.glob("*/metadata/run_config.json"))
        for directory in sorted(directories, reverse=True):
            try:
                data = run_metadata(directory)
                if data.get("project_id") != self.project.project_id:
                    continue
                active = (self.process is not None and self.run_directory == directory) or directory in self._batch_remaining
                status = "interrupted / unconfirmed" if data["status"] in {"queued", "running"} and not active else data["status"]
                runs.append({"path": str(directory), "name": directory.name, "status": status,
                             "created": data.get("created_utc", "Unknown time"), "objective": str(data.get("objective", "—"))})
            except (ValueError, OSError):
                continue
        return runs

    def _error(self, error):
        self.notice.emit(failure_message(error))

    def _touch(self):
        self.dirty = True
        # An idle grid follows normal inspector/profile/settings mutations. An
        # actual draft is retained instead, and its stale-baseline check protects
        # it from overwriting changes made elsewhere.
        if not self._sheet.dirty and self._sheet.baseline != self.project.model_state():
            self._sheet.load(self.project, self.component)
        self.changed.emit()

    def _reset_results(self):
        self._analytics = None
        self._batch_rows = []
        self.extensionsChanged.emit()
        self._comparison_frame = None
        self._comparison_capture = None
        self.model_history.clear()
        self._network_generation += 1
        self.showLiveNetwork()
        self._sheet_undo.clear()
        self._sheet_redo.clear()
        self.workspace.clear()
        self.run_directory = None
        self.run_meta = {}
        self.catalog = []
        self.messages = []
        self.progress_stage = "idle"
        self._result_frame = pd.DataFrame()
        self._reset_query()
        self.filterResults("")

    def _reset_query(self):
        self.repository = None
        self.query_categories = []
        self.query_snapshots = []
        self._query_specs = []
        self._query_temporal = False
        self.query_description = "No query executed. Select objects and properties, then click Query."
        self.queryOptionsChanged.emit()

    def _prepare_queries(self):
        self.repository = ResultsRepository(self.run_directory, self.catalog)
        self.query_categories = self.repository.describe()
        self.query_snapshots = [time.isoformat() for time in self.repository.snapshots]
        self.query_description = "Run loaded. Select objects and properties, then click Query."
        self.queryOptionsChanged.emit()
        self._show_active_tab()

    def _can_replace(self):
        if self._batch_active:
            self.notice.emit("Stop the scenario batch before replacing/closing the project.")
            return False
        if self._backup_thread:
            self.notice.emit("Cancel or finish the background backup before replacing/closing the project.")
            return False
        if self.process:
            self.notice.emit("Stop the active run before replacing the project.")
            return False
        if not self.resolveDraft():
            return False
        pinned = sum(t.pinned for t in self.workspace.tabs)
        if self.dirty or pinned:
            message = ("Discard unsaved project changes?\n" if self.dirty else "")
            message += f"Closing/replacing the project releases {pinned} pinned query tab(s) from memory. Saved run files are not deleted."
            answer = QMessageBox.question(None, "Leave project", message, QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
            return answer == QMessageBox.StandardButton.Discard
        return True

    @Slot(result=bool)
    def canClose(self):
        if self.process:
            self.notice.emit("A run is active. Stop it before closing the application.")
            return False
        allowed = self._can_replace()
        if allowed:
            self._clear_recovery()  # Normal confirmed close/discard is not a crash.
        return allowed

    @Slot()
    def newProject(self):
        if not self._can_replace():
            return
        self._clear_recovery()
        self.project, self.path, self.selected = Project(), None, ""
        self._reset_helpers()
        self.dirty = False
        self._reset_draft()
        self._reset_results()
        self.changed.emit()

    @Slot()
    def loadDemo(self):
        self.loadDemoModel("urban3")

    @Slot(result="QVariantList")
    def demoCatalogue(self):
        return deepcopy(DEMO_SPECS)

    @Slot(str, result=bool)
    def loadDemoModel(self, key):
        try:
            project = make_demo(key)
            errors = project.validate()
            if errors:
                raise ValueError("Demo input validation failed:\n" + "\n".join(errors))
        except (ValueError, KeyError) as error:
            self._error(error)
            return False
        if not self._can_replace():
            return False
        self._clear_recovery()
        self.project, self.path, self.selected = project, None, ""
        self.component = "Bus"
        self._reset_helpers()
        self._reset_draft()
        self._reset_results()
        self._touch()
        return True

    @Slot()
    def openProject(self):
        if self.process or self._batch_active or self._backup_thread:
            self.notice.emit("Finish or stop the active task before opening a model.")
            return
        path, _ = QFileDialog.getOpenFileName(None, "Open model database", "", "SQLite project (*.sqlite)")
        if not path:
            return
        self._open_model_file(path, reload_current=True)

    @Slot(str, result=bool)
    def openModelFile(self, value):
        """Shared candidate-first opening; never clear state on a rejected file."""
        return self._open_model_file(value)

    def _open_model_file(self, value, reload_current=False):
        try:
            from .file_opening import local_file
            if self.process or self._batch_active or self._backup_thread:
                raise ValueError("Finish or stop the active task before opening a model.")
            path = local_file(value)
            if path.suffix.lower() == ".nc":
                return self.openNetcdfResults(str(path))
            if not reload_current and self.path is not None and Path(self.path).resolve() == path:
                self.notice.emit("This project is already open. No reload or draft changes were made.")
                return True
            project = load_project(path)
            if not self._can_replace():
                return False
            self._clear_recovery()
            self.project, self.path, self.selected = project, Path(path).resolve(), ""
            self._reset_helpers()
            self.dirty = False
            self._reset_draft()
            self._reset_results()
            self.changed.emit()
            return True
        except Exception as error:
            self._error(error)
            return False

    @Slot("QVariantList", result=bool)
    def acceptsModelFiles(self, urls):
        if len(urls) != 1 or self.process or self._batch_active or self._backup_thread:
            return False
        from .file_opening import model_path
        from PySide6.QtCore import QUrl
        url = QUrl(str(urls[0]))
        if not url.isLocalFile():
            return False
        try:
            model_path(str(urls[0]))
            return True
        except ValueError:
            return False

    @Slot("QVariantList", result=bool)
    def dropModelFiles(self, urls):
        if len(urls) != 1:
            self.notice.emit("Drop one local project or results file at a time.")
            return False
        return self.openModelFile(str(urls[0]))

    @Slot(result=bool)
    def saveProject(self):
        if self._batch_active:
            self.notice.emit("Finish or cancel the scenario batch before saving.")
            return False
        if self._backup_thread:
            self.notice.emit("Wait for backup completion/cancellation before saving this database.")
            return False
        if not self.resolveDraft():
            return False
        try:
            if self.path is None:
                path, _ = QFileDialog.getSaveFileName(None, "Save project in your chosen folder", "project.sqlite", "SQLite project (*.sqlite)")
                if not path:
                    return False
                target = Path(path).with_suffix(".sqlite").resolve()
            else:
                target = self.path
            save_project(self.project, target)
            self.path, self.dirty = target, False
            self._clear_recovery()
            self.changed.emit()
            return True
        except Exception as error:
            self._error(error)
            return False

    @Slot(str)
    def selectType(self, component):
        if component == self.component:
            return
        if not self.resolveDraft():
            return
        self.component, self.selected = component, ""
        self._reset_draft()
        self.changed.emit()

    @Slot(str)
    def selectObject(self, name):
        if name == self.selected and not self._has_draft():
            return
        if not self.resolveDraft():
            return
        self.selected = name
        self._reset_draft()
        self.changed.emit()

    @Slot(str, str, result=bool)
    def storeObject(self, name, attributes_json):
        if self.process:
            return False
        try:
            attrs = json.loads(attributes_json)
            if not isinstance(attrs, dict):
                raise ValueError("Properties must be a JSON object.")
            if not self.selected and self.project.object(self.component, name.strip()):
                raise ValueError("An object with this name exists. Select it to edit instead of overwriting it.")
            before = self.project.history_snapshot()
            self.project.upsert(self.component, name, attrs)
            self._record_model_edit(before, "Edit " + self.component if self.selected else "Create " + self.component)
            self.selected = name.strip()
            self._reset_draft()
            self._touch()
            return True
        except Exception as error:
            self._error(error)
            return False

    def _reset_draft(self):
        record = self.project.object(self.component, self.selected)
        self._draft_name = self.selected
        self._draft_json = json.dumps(record["attributes"] if record else {})
        if not self._sheet.dirty:
            self._sheet.load(self.project, self.component)
        self.editorReset.emit()

    @Slot(str, str)
    def updateDraft(self, name, text):
        self._draft_name, self._draft_json = name, text

    def _has_draft(self):
        record = self.project.object(self.component, self.selected)
        try:
            return self._draft_name != self.selected or json.loads(self._draft_json) != (record["attributes"] if record else {})
        except ValueError:
            return True

    @Slot(result=bool)
    def resolveDraft(self):
        if self._sheet.dirty:
            answer = QMessageBox.question(None, "Unapplied spreadsheet edits", "Apply the spreadsheet batch before continuing? Save applies it to the project, not the database.",
                                          QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                          QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Save:
                if not self.applySheet():
                    return False
            elif answer == QMessageBox.StandardButton.Discard:
                self.discardSheet()
            else:
                return False
        if not self._has_draft():
            return self._resolve_helpers()
        answer = QMessageBox.question(None, "Unapplied object edits", "Apply the inspector edits to the project before continuing? Save applies them; it does not save the database yet.",
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save:
            return self.storeObject(self._draft_name, self._draft_json) and self._resolve_helpers()
        if answer == QMessageBox.StandardButton.Discard:
            self._reset_draft()
            self.changed.emit()
            return self._resolve_helpers()
        return False

    @Slot(result=bool)
    def beginSheet(self):
        if not self.resolveDraft():
            return False
        self._sheet.load(self.project, self.component)
        return True

    @Slot()
    def discardSheet(self):
        self._sheet.load(self.project, self.component)

    @Slot(result=bool)
    def validateSheet(self):
        return self._sheet.validate_changes(self.project) is not None

    @Slot(result=bool)
    def applySheet(self):
        if self.process:
            return False
        candidate = self._sheet.validate_changes(self.project)
        if candidate is None:
            return False
        validation_report = self._sheet.validationReport
        before, after = self.project.history_snapshot(), candidate.history_snapshot()
        if before != after:
            if self._sheet_undo and sheet_state(self._sheet_undo[-1][1]) != sheet_state(before):
                self._sheet_undo.clear()
            self._sheet_undo.append((before, after))
            self._sheet_undo = self._sheet_undo[-20:]
            self._sheet_redo.clear()
            self.project = candidate
            self._record_model_edit(before, "Spreadsheet batch")
            self.dirty = True
        self._sheet.load(self.project, self.component)
        self._reset_draft()
        self._sheet.report = ("Batch applied to project; Save writes SQLite.\n" if before != after else "No model changes.\n") + validation_report
        self._sheet.statusChanged.emit()
        self.changed.emit()
        return True

    @Slot(bool, result=bool)
    def sheetHistory(self, redo):
        if self.process or not self.resolveDraft():
            return False
        source, target = (self._sheet_redo, self._sheet_undo) if redo else (self._sheet_undo, self._sheet_redo)
        if not source:
            return False
        before, after = source[-1]
        if self.project.model_state() != sheet_state(before if redo else after):
            self.notice.emit("Batch history cannot overwrite edits made outside the spreadsheet.")
            return False
        layouts = deepcopy(self.project.schematic_layouts)
        analysis = deepcopy(self.project.analysis_workspace)
        scenarios = deepcopy(self.project.scenario_library)
        model_before = self.project.history_snapshot()
        interchange_info = self.project.interchange_info
        self.project = Project(**deepcopy(after if redo else before))
        self.project.interchange_info = interchange_info
        self.project.schematic_layouts = layouts
        self.project.analysis_workspace = analysis
        self.project.scenario_library = scenarios
        self._record_model_edit(model_before, "Redo spreadsheet batch" if redo else "Undo spreadsheet batch")
        target.append(source.pop())
        if not self.project.object(self.component, self.selected):
            self.selected = ""
        self._sheet.load(self.project, self.component)
        self._reset_draft()
        self._touch()
        return True

    @Slot()
    def copySheet(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._sheet.copyTsv())
        self._sheet.report = f"Copied {self._sheet.rowCount()} rows and attribute headers to the clipboard (TSV)."
        self._sheet.statusChanged.emit()

    @Slot(result=bool)
    def pasteSheet(self):
        from PySide6.QtWidgets import QApplication
        return self._sheet.pasteTsv(QApplication.clipboard().text())

    @Slot(str, result="QVariantMap")
    def propertyInfo(self, name):
        try:
            spec = attribute_spec(self.component, name)
            record = self.project.object(self.component, self.selected)
            value = (record or {}).get("attributes", {}).get(name, spec["default"])
            return {**spec, "value": str(value).lower() if isinstance(value, bool) else str(value) if value is not None else "",
                    "busReference": name.startswith("bus"), "boolean": "bool" in spec["dtype"]}
        except ValueError:
            return {"unit": "", "description": "", "value": "", "default": "", "busReference": False, "boolean": False}

    @Slot(str, str, str, result=str)
    def editAttribute(self, attributes_json, attribute, text):
        try:
            attrs = json.loads(attributes_json)
            spec = attribute_spec(self.component, attribute)
            attrs[attribute] = parse_value(spec, text)
            return json.dumps(attrs, indent=2)
        except Exception as error:
            self._error(error)
            return attributes_json

    @Slot()
    def deleteObject(self):
        if self.selected:
            self.deleteObjects([{"component": self.component, "name": self.selected}])

    def _publish_identity_edit(self, candidate, label="Delete objects", identity=None):
        before = self.project.to_dict()
        self.project = candidate
        self._record_model_edit(before, label, identity)
        self._sheet_undo.clear()
        self._sheet_redo.clear()
        if not self.project.object(self.component, self.selected):
            self.selected = ""
        self._sheet.load(self.project, self.component)
        self._reset_draft()
        self._touch()

    @Slot("QVariantList", result=bool)
    def deleteObjects(self, records):
        if self.process or not self.resolveDraft():
            return False
        try:
            baseline = self.project.to_dict()
            preview = deletion_preview(self.project, records)
            candidate = delete_candidate(self.project, records)
            message = "Delete these objects?\n" + "\n".join(preview["objects"])
            message += "\n\nImported profiles removed:\n" + ("\n".join(preview["profiles"]) or "None")
            message += "\n\nNo referencing objects will be silently deleted. Frozen runs are unchanged. Spreadsheet history will be cleared; model Undo is available within session limits."
            answer = QMessageBox.question(None, "Confirm bulk deletion", message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return False
            if self.project.to_dict() != baseline:
                raise ValueError("The model changed during confirmation. Review the deletion again.")
            self._publish_identity_edit(candidate)
            return True
        except (ValueError, TypeError, KeyError) as error:
            self._error(error)
            return False

    @Slot()
    def renameSelected(self):
        if self.process or not self.selected or not self.resolveDraft():
            return
        name, accepted = QInputDialog.getText(None, "Rename object", "New unique name:", text=self.selected)
        if accepted:
            self.renameObject(name)

    @Slot(str, result=bool)
    def renameObject(self, name):
        if self.process or not self.selected or not self.resolveDraft():
            return False
        try:
            baseline = self.project.to_dict()
            candidate, updates = rename_candidate(self.project, self.component, self.selected, name)
            message = f"Rename {self.component} '{self.selected}' to '{name.strip()}'?\n\nUpdated references/profiles:\n"
            message += "\n".join(updates) or "None"
            message += "\n\nFrozen runs keep their original names. Spreadsheet history will be cleared; model Undo is available within session limits."
            answer = QMessageBox.question(None, "Confirm rename", message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return False
            if self.project.to_dict() != baseline:
                raise ValueError("The model changed during confirmation. Review the rename again.")
            old_name = self.selected
            self.selected = name.strip()
            self._publish_identity_edit(candidate, "Rename " + self.component, (self.component, old_name, name.strip()))
            return True
        except (ValueError, TypeError, KeyError) as error:
            self._error(error)
            return False

    @Slot(str, str, str, int, int)
    def configure(self, name, currency, start, count, minutes):
        self.updateSettingsDraft(name, currency, start, count, minutes)
        self.applySettingsDraft()

    @Slot()
    def validate(self):
        try:
            errors = self.project.validate()
            warnings = formulation_warnings(self.project)
            message = "\n".join(errors) if errors else "Input checks passed. PyPSA and solver checks run during optimization; feasibility is not yet established."
            if warnings:
                message += "\n\nDC-OPF applicability notes:\n" + "\n".join(warnings)
            self.notice.emit(message)
        except Exception as error:
            self._error(error)

    @Slot()
    def chooseCsv(self):
        if self.process:
            return
        path, _ = QFileDialog.getOpenFileName(None, "Import CSV profile", "", "CSV files (*.csv)")
        if path:
            self.previewCsv(path)

    @Slot(str)
    def previewCsv(self, path):
        try:
            if self.process:
                return
            # Cancelling the picker itself preserves the old draft. Resolve only
            # when a replacement file was actually chosen.
            if self.csv_info["path"] and self._csv_pending and not self._resolve_helpers():
                return
            mapping = dict(self._csv_mapping)
            self.csv_info = {"path": path, **preview_csv(path)}
            component = mapping.get("component", self.component)
            options = self.profileOptions(component)
            columns = self.csv_info["columns"]
            self._csv_mapping = {"component": component,
                "name": mapping.get("name") or next(iter(options["objects"]), ""),
                "attribute": mapping.get("attribute") or next(iter(options["attributes"]), ""),
                "timestamp": columns[0] if columns else "", "value": columns[1] if len(columns) > 1 else ""}
            self._csv_pending = True
            self.helpersChanged.emit()
            self.changed.emit()
            self.helpersReset.emit()
        except Exception as error:
            self._error(error)

    @Slot(str, str, str, str)
    def importCsv(self, name, attribute, timestamp_column, value_column):
        if self.process:
            return
        try:
            before = self.project.to_dict()
            import_profile(self.project, self.csv_info["path"], self.component, name, attribute, timestamp_column, value_column)
            self._record_model_edit(before, "Import profile")
            self.discardCsvDraft()
            self._touch()
            self.notice.emit("Profile imported and aligned. Save to persist it in SQLite.")
        except Exception as error:
            self._error(error)

    @Slot(int)
    def removeProfile(self, index):
        if not self.process and 0 <= index < len(self.project.profiles):
            before = self.project.to_dict()
            self.project.profiles.pop(index)
            self._record_model_edit(before, "Remove profile")
            self._touch()

    @Slot(str, str)
    def startRun(self, label, export_format):
        self._start_run(label, export_format)

    @Slot(str, bool, result="QVariantMap")
    def previewHorizon(self, text, sync=False):
        from .horizon import schedule
        try:
            plan = schedule(json.loads(text), sync=sync)
            return {"valid": True, "summary": plan["summary"], "count": plan["spec"]["step_count"],
                    "end": plan["horizon_end"], "steps": plan["steps"]}
        except Exception as error:
            return {"valid": False, "summary": str(error), "steps": []}

    @Slot(str)
    def showHorizonMessage(self, text):
        self.notice.emit(text)

    @Slot(str, str, str)
    def startConfiguredRun(self, label, export_format, text):
        try:
            from .horizon import schedule, aligned_project
            spec = json.loads(text)
            # Fail before saving or creating artifacts when inputs do not align.
            aligned_project(self.project, schedule(spec))
            self._start_run(label, export_format, spec)
        except Exception as error:
            self._error(error)

    @Slot(str, str, str, str)
    @Slot(str, str, str, str, bool)
    def startRunWithReports(self, label, export_format, horizon_text, report_text, export_python=False):
        try:
            horizon = json.loads(horizon_text) if horizon_text else None
            reports = json.loads(report_text)
            from .horizon import schedule, aligned_project
            from .temporal_reports import validate_reports
            candidate = aligned_project(self.project, schedule(horizon)) if horizon else self.project
            validate_reports(candidate, reports)
            self._start_run(label, export_format, horizon, reports, export_python)
        except Exception as error:
            self._error(error)

    def _start_run(self, label, export_format, horizon=None, report_resolutions=None, export_python=False):
        if self._batch_active:
            self.notice.emit("Finish or cancel the scenario batch before another run.")
            return
        if self._backup_thread:
            self.notice.emit("Finish or cancel the backup before starting a solve.")
            return
        if self.process:
            return
        if not self.saveProject():
            return
        try:
            directory = prepare_run(self.path, label, export_format, horizon=horizon,
                                    report_resolutions=report_resolutions, export_python=export_python)
            self._launch_run(directory)
        except Exception as error:
            self._error(error)

    def _launch_run(self, directory):
        """Launch one already frozen run; a batch uses the same owned process path."""
        self.run_directory = directory
        self.run_meta = {"status": "running"}
        self.messages = ["Queued · frozen input database created"]
        self.events_buffer = ""
        self.progress_stage = "queued"
        self.cancel_requested = False
        self.catalog = []
        self._reset_query()
        self._show_active_tab()
        process = QProcess(self)
        self.process = process
        process.setWorkingDirectory(str(Path(__file__).resolve().parent.parent))
        process.setStandardErrorFile(str(directory / "worker.log"))
        process.readyReadStandardOutput.connect(self._read_progress)
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._process_error)
        process.start(sys.executable, ["-u", "-m", "energy_gui.worker", "--run", str(directory)])
        self.changed.emit()

    def _read_progress(self):
        if not self.process:
            return
        self.events_buffer += bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        while "\n" in self.events_buffer:
            line, self.events_buffer = self.events_buffer.split("\n", 1)
            try:
                event = json.loads(line)
                self.progress_stage = event["stage"]
                self.messages.append(f"{event['stage'].upper()}  ·  {event['message']}")
            except (ValueError, KeyError):
                self.messages.append(line)
        self.changed.emit()

    def _process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.messages.append("Worker failed to start: " + self.process.errorString())
            self._finished(-1, QProcess.ExitStatus.CrashExit)

    def _finished(self, exit_code, exit_status):
        if self.process is None:
            return
        self._read_progress()
        self.process.deleteLater()
        self.process = None
        try:
            path = metadata_path(self.run_directory, "run_config.json")
            self.run_meta = json.loads(path.read_text(encoding="utf-8"))
            if self.cancel_requested:
                self.run_meta.update(status="cancelled", error="Stopped by user. Partial files are not validated results.")
                write_json(path, self.run_meta)
                if "horizon" in self.run_meta:
                    from .sequential import mark_cancelled
                    mark_cancelled(self.run_directory)
            if self.run_meta["status"] in {"queued", "running"}:
                self.run_meta.update(status="failed", error=f"Worker stopped (exit {exit_code}). See worker.log.")
                write_json(path, self.run_meta)
            if self.run_meta["status"] == "succeeded":
                self.catalog = json.loads(metadata_path(self.run_directory, "catalog.json").read_text(encoding="utf-8"))
                self._prepare_queries()
                self.progress_stage = "complete"
                if not self._batch_active:
                    self.runCompleted.emit()
            else:
                self.progress_stage = self.run_meta["status"]
                self.messages.append(self.run_meta.get("error", "Run did not succeed."))
        except Exception as error:
            self._error(error)
        self.changed.emit()

        if self._batch_active:
            self._batch_run_finished()

    @Slot()
    def cancelRun(self):
        if self._batch_active:
            self._cancel_batch_pending()
        if self.process:
            self.cancel_requested = True
            self.process.kill()

    @Slot(str, result=bool)
    def openRun(self, directory):
        if self.process:
            return False
        try:
            path = Path(directory).resolve()
            meta = run_metadata(path)
            if meta.get("project_id") != self.project.project_id:
                raise ValueError("This run belongs to another project. Open that project first.")
            catalog = json.loads(metadata_path(path, "catalog.json").read_text(encoding="utf-8")) if meta["status"] == "succeeded" else []
            if meta["status"] == "succeeded" and not catalog:
                raise ValueError("Malformed result catalogue: a successful run must contain saved tables. Restore a complete run; the prior display is unchanged.")
            repository = ResultsRepository(path, catalog) if catalog else None
            if repository and repository.project.project_id != self.project.project_id:
                raise ValueError("Run metadata and frozen project identity disagree.")
            if self.workspace.active and self.workspace.active.run_meta.get("source_kind") == "netcdf":
                self.workspace.active_id = ""
            self.run_directory, self.run_meta = path, meta
            self.catalog = catalog
            self._reset_query()
            if repository:
                self.repository = repository
                self.query_categories = repository.describe()
                self.query_snapshots = [t.isoformat() for t in repository.snapshots]
                self.queryOptionsChanged.emit()
            self._show_active_tab()
            if meta["status"] != "succeeded":
                self.messages = [meta.get("error", "No validated solution for this run.")]
                if meta["status"] in {"queued", "running"}:
                    self.messages.append("Interrupted / unconfirmed: this application does not own an active worker for this saved run. Another application may still be running it. No process was killed, status file rewritten or solution promoted. Inspect logs; restart recovery/resume is not implemented.")
                self.notice.emit("This run has no validated solution. See its diagnostics in Runs; query tabs are unchanged.")
            self.changed.emit()
            return True
        except Exception as error:
            self._error(error)
            return False

    @Slot()
    def browseRun(self):
        directory = QFileDialog.getExistingDirectory(None, "Select the saved run folder", str(self.path.parent / "runs") if self.path else "")
        if directory:
            self.openRun(directory)

    @Slot()
    def browseNetcdfResults(self):
        path, _ = QFileDialog.getOpenFileName(None, "Open standalone PyPSA results", "", "NetCDF results (*.nc)")
        if path:
            self.openNetcdfResults(path)

    @Slot(str, result=bool)
    def openNetcdfResults(self, value):
        return self._open_netcdf_results(value, activate_page=True)

    def _open_netcdf_results(self, value, activate_page):
        if self.process or self._batch_active or self._backup_thread:
            self.notice.emit("Finish or stop the active task before opening results.")
            return False
        try:
            from .file_opening import local_file
            from .netcdf_ui import read_results
            path = local_file(value)
            if path.suffix.lower() != ".nc":
                raise ValueError("Choose a local PyPSA .nc archive.")
            try:
                repository = read_results(path)
            except OSError as error:
                raise ValueError(f"Cannot read {path.name} as NetCDF. Check that the file is accessible "
                                 "and re-export it if it is incomplete or damaged.") from error
            if repository is None:
                return False
            categories = repository.describe()
            self.repository = repository
            self.query_categories = categories
            self.query_snapshots = repository.snapshot_labels
            self.workspace.active_id = ""  # Existing captured queries remain selectable.
            self._show_active_tab()
            self.query_description = "Select available properties and click Query. Values not stored in the archive are unavailable."
            self.queryOptionsChanged.emit()
            self.changed.emit()
            if activate_page:
                self.resultsOpened.emit()
            return True
        except Exception as error:
            self._error(error)
            return False

    @Slot()
    def refreshRuns(self):
        self.changed.emit()

    @Slot(str, "QVariantList", "QVariantList", str, str, result=bool)
    def queryResults(self, component, objects, properties, start, end):
        return self._query_results(component, objects, properties, start, end)

    @Slot(str, "QVariantList", "QVariantList", str, str, str, result=bool)
    def queryTemporalResults(self, component, objects, properties, start, end, settings):
        try:
            from .temporal import options
            value = options(json.loads(settings))
            return self._query_results(component, objects, properties, start, end,
                                       None if value["resolution"] == "native" else value)
        except Exception as error:
            self._error(error)
            return False

    def _query_results(self, component, objects, properties, start, end, aggregation=None):
        try:
            if self.repository is None:
                raise ValueError("Open a NetCDF archive or load a successful Studio run before querying results.")
            args = (component, list(objects), list(properties), start, end)
            frame, specs, temporal = (
                self.repository.query(*args) if aggregation is None
                else self.repository.query(*args, aggregation=aggregation)
            )
            interval = f" · {start or self.query_snapshots[0]} → {end or self.query_snapshots[-1]} (inclusive)" if temporal else " · static properties (snapshot range not applicable)"
            self.workspace.put(
                title=f"{component} · {', '.join(properties)}",
                run_path=str(getattr(self.repository, "path", self.run_directory) or ""),
                run_meta=getattr(self.repository, "meta", self.run_meta),
                criteria={"component": component, "objects": list(objects), "properties": list(properties), "start": start, "end": end,
                          **({"aggregation": aggregation} if aggregation else {})},
                frame=frame, specs=specs, temporal=temporal,
                description=f"{component}: {len(objects)} objects · {', '.join(properties)}{interval}"
                            + (f" · {aggregation['resolution']} / {aggregation['metric']} / {aggregation['group_by']} · physical hours · partial buckets labelled" if aggregation else ""),
            )
            self._show_active_tab()
            return True
        except Exception as error:
            self._error(error)
            return False

    @Slot(str)
    def filterResults(self, text):
        from .temporal import listing
        self._table_filter = text
        tab = self.workspace.active
        frame = listing(self._result_frame, self._query_specs, self._query_temporal,
                        tab.listing if tab else "snapshot", tab.table_form if tab else "wide")
        if tab and tab.sort_column in frame:
            try:
                frame = frame.sort_values(tab.sort_column, ascending=not tab.sort_descending, kind="stable")
            except TypeError:
                # Mixed property-first values may have different scalar types.
                # Sort their display strings, without coercing the actual values.
                frame = frame.sort_values(tab.sort_column, ascending=not tab.sort_descending,
                                          key=lambda col: col.astype(str), kind="stable")
        if text and not frame.empty:
            mask = frame.astype(str).apply(lambda column: column.str.contains(text, case=False, regex=False)).any(axis=1)
            frame = frame.loc[mask]
        self._filtered_frame = frame
        self._result_model.replace(frame)
        self._refresh_charts()
        self.changed.emit()

    def _chart_bounds(self, tab):
        if not tab or not tab.temporal or tab.frame.empty:
            return None
        count = tab.frame["snapshot"].nunique()
        return (tab.chart_range[0], count-1 if tab.chart_range[1] == -1 else tab.chart_range[1])

    def _chart_range_info(self):
        tab = self.workspace.active
        bounds = self._chart_bounds(tab)
        if bounds is None:
            return {"count": 0, "first": 0, "last": 0, "fromLabel": "", "toLabel": ""}
        dates = sorted(tab.frame["snapshot"].unique())
        return {"count": len(dates), "first": bounds[0], "last": bounds[1],
                "fromLabel": str(dates[bounds[0]]), "toLabel": str(dates[bounds[1]])}

    def _refresh_charts(self):
        tab = self.workspace.active
        styles = tab.chart_types if tab else {}
        self._charts = query_charts(self._result_frame, self._query_specs, self._query_temporal,
                                    styles, self._chart_bounds(tab))
        self._chart = self._charts[0] if self._charts else {"series": [], "labels": []}

    @Slot(int, int, result=bool)
    def setChartRange(self, first, last):
        tab = self.workspace.active
        bounds = self._chart_bounds(tab)
        if bounds is None:
            return False
        count = tab.frame["snapshot"].nunique()
        if not 0 <= first <= last < count:
            return False
        tab.chart_range = [first, last]
        self._refresh_charts()
        self.changed.emit()
        return True

    @Slot(str, str)
    def setResultListing(self, order, form):
        tab = self.workspace.active
        if not tab:
            return
        try:
            from .temporal import listing
            listing(tab.frame, tab.specs, tab.temporal, order, form)
            tab.listing, tab.table_form = order, form
            tab.sort_column = ""
            self.filterResults(getattr(self, "_table_filter", ""))
        except Exception as error:
            self._error(error)

    @Slot(str)
    def sortResultTable(self, column):
        tab = self.workspace.active
        if tab and column in self._filtered_frame:
            tab.sort_descending = not tab.sort_descending if tab.sort_column == column else False
            tab.sort_column = column
            self.filterResults(getattr(self, "_table_filter", ""))

    def _show_active_tab(self):
        tab = self.workspace.active
        self._result_frame = tab.frame if tab else pd.DataFrame()
        self._query_specs = tab.specs if tab else []
        self._query_temporal = tab.temporal if tab else False
        self.query_description = tab.description if tab else "Select objects and properties, then click Query."
        self.filterResults("")

    @Slot(str)
    def selectQueryTab(self, tab_id):
        try:
            tab = next((t for t in self.workspace.tabs if t.id == tab_id), None)
            if tab is None:
                raise ValueError("Query tab no longer exists.")
            external = getattr(self.repository, "path", None)
            if tab.run_meta.get("source_kind") == "netcdf":
                if str(external) != tab.run_path and not self._open_netcdf_results(tab.run_path, activate_page=False):
                    return
            elif external is not None or str(self.run_directory) != tab.run_path:
                if not self.openRun(tab.run_path):
                    return
            self.workspace.select(tab_id)
            self._show_active_tab()
            self.querySelectionChanged.emit(tab.criteria)
            self.analysisViewRequested.emit(tab.view)
        except ValueError as error:
            self._error(error)

    @Slot(str)
    def pinQueryTab(self, tab_id):
        try:
            self.workspace.toggle_pin(tab_id)
            self.changed.emit()
        except StopIteration:
            self.notice.emit("Query tab no longer exists.")

    @Slot(str)
    def closeQueryTab(self, tab_id):
        try:
            was_active = self.workspace.active_id == tab_id
            self.workspace.close(tab_id)
            if self.workspace.active and was_active:
                self.selectQueryTab(self.workspace.active_id)
            elif not self.workspace.active:
                self._show_active_tab()
            else:
                self.changed.emit()
        except StopIteration:
            self.notice.emit("Query tab no longer exists.")

    @Slot(str, str, result=bool)
    def setChartType(self, attribute, kind):
        tab = self.workspace.active
        if tab is None:
            return False
        try:
            if attribute not in {s["name"] for s in tab.specs}:
                raise ValueError("Choose a numeric property from the active query.")
            styles = {**tab.chart_types, attribute: kind}
            query_charts(tab.frame, tab.specs, tab.temporal, styles)
            tab.chart_types = styles
            self._show_active_tab()
            return True
        except ValueError as error:
            self._error(error)
            return False

    @Slot()
    def exportResults(self):
        if self._filtered_frame.empty:
            self.notice.emit("Load a nonempty result table first.")
            return
        path, _ = QFileDialog.getSaveFileName(None, "Export query results", "results.csv", "CSV (*.csv)")
        if path:
            try:
                destination = self._safe_analysis_export(path)
                self._filtered_frame.to_csv(destination, index=False)
                tab = self.workspace.active
                if tab:
                    write_json(destination.with_suffix(destination.suffix + ".metadata.json"), {
                        "run": tab.run_path, "criteria": tab.criteria, "specs": tab.specs,
                        **({"source_kind": "netcdf", "source": tab.run_meta}
                           if tab.run_meta.get("source_kind") == "netcdf" else {}),
                        "listing": tab.listing, "form": tab.table_form,
                        "sort_column": tab.sort_column, "sort_descending": tab.sort_descending,
                        "table_filter": getattr(self, "_table_filter", ""),
                        "note": "Full filtered listing. Chart viewport does not trim this table.",
                    })
                self.notice.emit("Full filtered table exported (not limited to the 1000-row preview).")
            except Exception as error:
                self._error(error)
