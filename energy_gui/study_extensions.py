"""Extended study commands; existing controller retains file/run ownership."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

from .project import Project
from .schema import attribute_spec, json_value, parse_value
from .storage import load_project
from .run_layout import metadata_path
from PySide6.QtCore import QObject, Property, Signal, Slot
from PySide6.QtWidgets import QFileDialog


CONTROL_FIELDS = {
    "Generator": ["committable", "p_nom", "p_nom_extendable", "p_min_pu", "p_max_pu",
                  "start_up_cost", "shut_down_cost", "stand_by_cost", "min_up_time",
                  "min_down_time", "up_time_before", "down_time_before",
                  "ramp_limit_up", "ramp_limit_down"],
    "StorageUnit": ["p_nom", "p_nom_extendable", "max_hours", "efficiency_store",
                    "efficiency_dispatch", "standing_loss", "state_of_charge_initial",
                    "cyclic_state_of_charge"],
    "GlobalConstraint": ["type", "carrier_attribute", "sense", "constant", "investment_period"],
}


class StudyExtensions(QObject):
    extensionsChanged = Signal()

    def _initialize_studies(self):
        self._batch_active = False
        self._batch_cancelled = False
        self._batch_remaining = []
        self._batch_rows = []
        self._analytics = None

    @Property("QVariantMap", notify=extensionsChanged)
    def studyState(self):
        payload = self._analytics or {}
        return {"batchActive": self._batch_active, "batchRows": deepcopy(self._batch_rows),
                "analyticsCharts": payload.get("charts", []),
                "analyticsDescription": payload.get("description", "Execute a Results query first."),
                "analyticsPreview": payload["frame"].head(100).to_string(index=False) if payload else "",
                "analyticsRows": len(payload["frame"]) if payload else 0}

    @Slot(result=str)
    def scenarioDefinitions(self):
        return json.dumps(self.project.scenario_library, indent=2)

    @Slot(str, result=bool)
    def applyScenarios(self, text):
        if self.process or self._backup_thread or self._batch_active:
            return False
        try:
            from .scenarios import checked_scenarios
            self.project.scenario_library = checked_scenarios(self.project, json.loads(text))
            self._touch()
            self.extensionsChanged.emit()
            return True
        except Exception as error:
            self._error(error)
            return False

    @Slot(str, result=bool)
    def startScenarioBatch(self, export_format):
        if self.process or self._backup_thread or self._batch_active:
            return False
        if not self.saveProject():
            return False
        try:
            from .scenarios import prepare_scenarios
            runs = prepare_scenarios(self.path, self.project.scenario_library, export_format)
            if not runs:
                raise ValueError("Define at least one scenario before starting a batch.")
            self._batch_rows = []
            for run in runs:
                meta = json.loads(metadata_path(run, "run_config.json").read_text(encoding="utf-8"))
                self._batch_rows.append({"run": Path(run).name, "status": "queued", "objective": "",
                                         "scenario": meta.get("scenario_name", Path(run).name)})
            self._batch_remaining = list(runs)
            self._batch_active, self._batch_cancelled = True, False
            self._advance_batch()
            return True
        except Exception as error:
            self._error(error)
            return False

    def _advance_batch(self):
        if self._batch_remaining and not self._batch_cancelled:
            directory = self._batch_remaining.pop(0)
            for row in self._batch_rows:
                if row["run"] == Path(directory).name:
                    row["status"] = "running"
            self._launch_run(Path(directory))
        else:
            self._batch_active = False
            self.changed.emit()
        self.extensionsChanged.emit()

    def _batch_run_finished(self):
        for row in self._batch_rows:
            if row["run"] == self.run_directory.name:
                row["status"] = self.run_meta.get("status", "failed")
                row["objective"] = str(self.run_meta.get("objective", ""))
        self._advance_batch()

    def _cancel_batch_pending(self):
        from .engine import write_json
        self._batch_cancelled = True
        for directory in self._batch_remaining:
            status = "cancellation unconfirmed"
            try:
                path = metadata_path(directory, "run_config.json")
                meta = json.loads(path.read_text(encoding="utf-8"))
                if meta.get("status") == "queued":
                    meta.update(status="cancelled", error="Batch cancelled before this scenario started.")
                    write_json(path, meta)
                status = meta["status"]
            except Exception as error:
                self._error(ValueError("Waiting scenario will not start, but its status could not be saved: " + str(error)))
            for row in self._batch_rows:
                if row["run"] == Path(directory).name:
                    row["status"] = status
        self._batch_remaining.clear()
        self.extensionsChanged.emit()

    @Slot(result=str)
    def modelDiagnostics(self):
        try:
            from .model_diagnostics import diagnose_project
            return json.dumps(diagnose_project(self.project), indent=2, allow_nan=False)
        except Exception as error:
            self._error(error)
            return "Diagnostics unavailable; no input changes were made."

    @Slot(result=str)
    def modelDiagnosticsText(self):
        try:
            from .model_diagnostics import diagnose_project, format_diagnostics
            return format_diagnostics(diagnose_project(self.project))
        except Exception as error:
            self._error(error)
            return "Diagnostics unavailable; no input changes were made."

    @Slot(result=str)
    def runFailureAdvice(self):
        if not self.run_directory:
            return "Load a run in Run history first."
        from .model_diagnostics import explain_run_failure
        return explain_run_failure(self.run_directory)

    @Slot(str, str, result=str)
    def modelingControls(self, component, name):
        try:
            record = self.project.object(component, name)
            if not record or component not in CONTROL_FIELDS:
                raise ValueError("Choose an existing Generator, StorageUnit or GlobalConstraint.")
            return json.dumps({key: json_value(record["attributes"].get(key, attribute_spec(component, key)["default"]))
                               for key in CONTROL_FIELDS[component]}, indent=2, allow_nan=False)
        except Exception as error:
            self._error(error)
            return ""

    @Slot(str, str, str, result=bool)
    def applyModelingControls(self, component, name, text):
        if self.process or self._backup_thread or self._batch_active or not self.resolveDraft():
            return False
        try:
            values = json.loads(text)
            if not isinstance(values, dict) or not values or set(values) - set(CONTROL_FIELDS.get(component, [])):
                raise ValueError("Supply only the displayed modeling-control fields.")
            before = self.project.to_dict()
            candidate = Project(**deepcopy(before))
            record = candidate.object(component, name)
            if record is None:
                raise ValueError("The modeling-control owner no longer exists.")
            for key, value in values.items():
                spec = attribute_spec(component, key)
                if value is None and json_value(spec["default"]) is None:
                    record["attributes"].pop(key, None)  # Native optional/default NaN, not a numeric NaN input.
                else:
                    record["attributes"][key] = parse_value(spec, value)
            introduced = set(candidate.validate()) - set(self.project.validate())
            if introduced:
                raise ValueError("\n".join(sorted(introduced)))
            self.project = candidate
            self._record_model_edit(before, "Modeling controls " + component)
            self._reset_draft()
            self._touch()
            return True
        except Exception as error:
            self._error(error)
            return False

    @Slot(str, str, str, result=bool)
    def analyzeQuery(self, mode, group_by, weighting):
        try:
            from .analysis import repository_for
            from .analytics import summarize_query, comparison_charts
            tab = self.workspace.active
            if mode == "comparison":
                frame = getattr(self, "_comparison_frame", None)
                capture = getattr(self, "_comparison_capture", None)
                if frame is None or capture is None:
                    raise ValueError("Execute a compatible comparison in Saved analysis tools first.")
                frame = frame.copy(deep=True)
                charts = comparison_charts(frame)
                description = json.dumps(self._comparison_meta, indent=2, allow_nan=False)
                source_path = capture["run_path"]
                _, source_meta = repository_for(self.project, source_path)
                criteria = capture["criteria"]
            else:
                if tab is None:
                    raise ValueError("Execute a Results query first.")
                if tab.run_meta.get("source_kind") == "netcdf":
                    raise ValueError("Study analytics require a Studio run. For NetCDF, use Results queries and calendar aggregation where available.")
                repo, _ = repository_for(self.project, tab.run_path)
                frame, charts, description = summarize_query(tab, repo, mode, group_by, weighting)
                source_path, source_meta, criteria = tab.run_path, tab.run_meta, tab.criteria
            # Own a separate captured result; later tab/model changes cannot relabel it.
            self._analytics = {"frame": frame.copy(deep=True), "charts": deepcopy(charts),
                               "description": description, "run_path": source_path,
                               "run_meta": deepcopy(source_meta),
                               "criteria": {"query": deepcopy(criteria), "mode": mode,
                                            "group_by": group_by, "weighting": weighting}}
            self.extensionsChanged.emit()
            return True
        except Exception as error:
            self._analytics = None
            self.extensionsChanged.emit()
            self._error(error)
            return False

    @Slot(str, str, int, bool, result=bool)
    def exportStudyResult(self, kind, title, rows, include_charts):
        try:
            if not self._analytics:
                raise ValueError("Compute an analysis first.")
            if not title.strip() or len(title) > 150 or not 1 <= rows <= 1000:
                raise ValueError("Use a 1–150 character report title and 1–1000 preview rows.")
            names = {"csv": ("analysis.csv", "CSV (*.csv)"), "chart": ("analysis.svg", "Charts (*.svg *.png)"),
                     "report": ("analysis.html", "HTML (*.html)")}
            name, filter_text = names[kind]
            path, _ = QFileDialog.getSaveFileName(None, "Export captured analysis", name, filter_text)
            if not path:
                return False
            destination = self._safe_analysis_export(path)
            if destination.is_relative_to(Path(self._analytics["run_path"]).resolve()):
                raise ValueError("Export outside frozen results.")
            from .reporting import write_chart, write_report
            payload = self._analytics
            if kind == "csv":
                payload["frame"].to_csv(destination, index=False)
            elif kind == "chart":
                write_chart(destination, payload["charts"])
            else:
                tab = SimpleNamespace(title=title.strip(), **{k: payload[k] for k in
                    ["frame", "run_path", "run_meta", "criteria", "description"]})
                write_report(destination, tab, payload["charts"] if include_charts else [],
                             {"source_objective": payload["run_meta"].get("objective")}, row_limit=rows,
                             accounting_note="Accounting follows the captured description and weighting/period fields. Storage states are not integrated; duration excludes period years. Source objective is not a reconstructed cost.")
            return True
        except Exception as error:
            self._error(error)
            return False
