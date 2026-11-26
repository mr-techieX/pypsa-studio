"""Standalone NetCDF queries and Windows Qt open/drop integration."""

import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import test_qml_controls as controls
import numpy as np
import pandas as pd
import xarray as xr
from energy_gui.netcdf_results import NetcdfResults
from energy_gui.results import query_charts
from energy_gui.storage import save_project
from PySide6.QtCore import QMimeData, QObject, QPoint, QPointF, QTimer, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QMessageBox, QPushButton


def archive():
    return xr.Dataset(
        {
            "snapshots_snapshot": ("snapshots", pd.date_range("2027", periods=3, freq="h")),
            **{f"snapshots_{key}": ("snapshots", [1., 1., 1.])
               for key in ("objective", "stores", "generators")},
            "generators_bus": ("generators_i", ["bus", "bus"]),
            "generators_p_nom": ("generators_i", [50., 80.]),
            "generators_p_nom_opt": ("generators_i", [50., 80.]),
            "generators_p_max_pu": ("generators_i", [0.9, 0.8]),
            "generators_t_p": (("snapshots", "generators_t_p_i"), [[2.], [np.nan], [4.]]),
            "generators_t_p_max_pu": (("snapshots", "generators_t_p_max_pu_i"), [[0.7], [0.6], [0.5]]),
        },
        coords={"generators_i": ["001", "snapshot"], "generators_t_p_i": ["snapshot"],
                "generators_t_p_max_pu_i": ["snapshot"], "buses_i": ["bus"]},
        attrs={"network_pypsa_version": "1.4.0", "network__objective": 30.},
    )


class NetcdfQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "solution.nc"

    def load(self, data):
        data.to_netcdf(self.path, engine="netcdf4")
        return NetcdfResults(self.path)

    def test_read_only_filters_chart_missing_and_blocks_inputs(self):
        repo = self.load(archive())
        before = self.path.read_bytes()
        frame, specs, temporal = repo.query("Generator", ["001", "snapshot"], ["p", "p_nom_opt"],
                                            start="2027-01-01T01:00")
        self.assertTrue(temporal)
        self.assertEqual(frame.object.tolist(), ["001", "snapshot"] * 2)
        self.assertEqual(frame.p_nom_opt.tolist(), [50., 80., 50., 80.])
        self.assertEqual({p["name"] for p in repo.describe()[0]["properties"]}, {"p", "p_nom_opt"})
        for prop in ("bus", "p_nom", "p_max_pu"):
            with self.assertRaisesRegex(ValueError, prop):
                repo.query("Generator", ["001"], [prop])
        self.assertTrue(frame.p.iloc[:3].isna().all())
        self.assertEqual(frame.p.iloc[3], 4.)
        self.assertEqual(query_charts(frame, specs, temporal)[0]["series"][1]["values"], [None, 4.])
        self.assertEqual(specs[0]["unit"], "MW")
        self.assertEqual(repo.meta["objective"], 30.)
        self.assertIn("unverified", repo.description)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        self.assertEqual(self.path.read_bytes(), before)

    def test_missing_and_invalid_weights_disable_aggregation(self):
        data = archive().drop_attrs()
        data.attrs["network_pypsa_version"] = "1.4.0"
        repo = self.load(data.drop_vars("snapshots_stores"))
        self.assertNotIn("objective", repo.meta)
        self.assertEqual(repo._calendar_resolutions, ["native"])
        with self.assertRaisesRegex(ValueError, "explicit valid"):
            repo.query("Generator", ["001"], ["p"], aggregation={"resolution": "daily"})
        data["snapshots_stores"] = ("snapshots", [1., 0., 1.])
        self.assertFalse(self.load(data).has_weights)

    def test_inputs_only_archive_has_no_queryable_categories(self):
        data = archive().drop_vars(["generators_t_p", "generators_p_nom_opt"]).drop_attrs()
        data.attrs["network_pypsa_version"] = "1.4.0"
        repo = self.load(data)
        self.assertEqual(repo.describe(), [])
        self.assertIn("no queryable outputs stored", repo.description)
        self.assertNotIn("objective", repo.meta)

    def test_aggregation_and_units(self):
        data = archive()
        data["generators_t_p"][:] = [[2.], [3.], [4.]]
        repo = self.load(data)
        options = dict(version=1, resolution="daily", metric="energy")
        frame, specs, _ = repo.query("Generator", ["snapshot"], ["p"], aggregation=options)
        self.assertEqual(frame.p.tolist(), [9.])
        self.assertEqual(specs[0]["unit"], "MWh")
        data["buses_unit"] = ("buses_i", ["t/h"])
        repo = self.load(data)
        self.assertEqual(repo.query("Generator", ["snapshot"], ["p"])[1][0]["unit"], "t/h")
        with self.assertRaisesRegex(ValueError, "no verified calendar aggregation rule"):
            repo.query("Generator", ["snapshot"], ["p"], aggregation=options)

    def test_reject_corrupt_unrelated_integer_axis_duplicate_and_unknown_identity(self):
        self.path.write_bytes(b"Not NetCDF")
        with self.assertRaisesRegex(ValueError, "supported NetCDF"):
            NetcdfResults(self.path)
        cases = [
            (archive().drop_attrs(), "not a PyPSA"),
            (archive().assign(snapshots_snapshot=("snapshots", [0, 1, 2])), "datetime snapshots"),
            (archive().assign(snapshots_snapshot=("snapshots", pd.to_datetime(["2027"]*3))), "unique"),
            (archive().assign_coords(generators_t_p_i=["unknown"]), "unknown object"),
            (archive().assign_coords(generators_i=["001", "001"]), "Duplicate"),
        ]
        for data, error in cases:
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                self.load(data)

    def test_limits_preflight_and_query(self):
        repo = self.load(archive())
        for constant in ("MAX_FILE_BYTES", "MAX_CELLS", "MAX_VARIABLES", "MAX_SNAPSHOTS", "MAX_TEXT_CHARS", "MAX_OBJECTS"):
            with self.subTest(limit=constant), patch(f"energy_gui.netcdf_results.{constant}", 1):
                with self.assertRaisesRegex(ValueError, "limit"):
                    NetcdfResults(self.path)
        with patch("energy_gui.netcdf_results.MAX_QUERY_CELLS", 1):
            with self.assertRaisesRegex(ValueError, "query is too large"):
                repo.query("Generator", ["001", "snapshot"], ["p"])
            self.assertEqual(len(repo.query("Generator", ["001"], ["p_nom_opt"])[0]), 1)


class NetcdfUiTests(unittest.TestCase):
    setUpClass = classmethod(controls.QmlControlsTests.setUpClass.__func__)
    setUp = controls.QmlControlsTests.setUp
    tearDown = controls.QmlControlsTests.tearDown
    visual_item = controls.QmlControlsTests.visual_item

    def fixture_path(self, name):
        paths = Path(self.temp.name) / "lone"
        paths.mkdir(exist_ok=True)
        path = paths / name
        staged = paths / "fixture.nc"
        archive().to_netcdf(staged, engine="netcdf4")
        staged.rename(path)
        return path

    def drop(self, path):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path))])
        action, mouse, key = Qt.DropAction.CopyAction, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
        event = QDragEnterEvent(QPoint(300, 240), action, mime, mouse, key)
        self.app.sendEvent(self.root, event)
        self.assertTrue(event.isAccepted())
        self.app.sendEvent(self.root, QDropEvent(QPointF(300, 240), action, mime, mouse, key))
        QTest.qWait(50)

    def test_browse_and_drop_list_same_outputs_without_csv_placeholders(self):
        path = self.fixture_path("solution.nc")
        run = Path(self.temp.name) / "run"
        tables = run / "tables"
        tables.mkdir(parents=True)
        project = self.controller.project
        project.set_horizon("2027-01-01", 3, 60)
        for name in ("001", "snapshot"):
            project.upsert("Generator", name, {"p_nom": 100})
        save_project(project, run / "inputs.sqlite")
        (run / "run_config.json").write_text(json.dumps(dict(
            project_id=project.project_id, status="succeeded", objective=30.0,
        )), encoding="utf-8")
        pd.DataFrame({"name": ["001", "snapshot"], "p_nom": [100, 100], "p_nom_opt": [50., 80.],
                      "capital_cost_piecewise_opt": [0., 0.]}).to_csv(tables / "static.csv", index=False)
        # The object called "snapshot" also occupies a result column.
        pd.DataFrame({"timestamp": project.snapshots, "snapshot": [2., np.nan, 4.]}).to_csv(
            tables / "p.csv", index=False,
        )
        (run / "catalog.json").write_text(json.dumps([
            dict(component="Generator", kind="static", attribute="static properties", file="static.csv"),
            dict(component="Generator", kind="time series", attribute="p", file="p.csv"),
        ]), encoding="utf-8")
        with patch.object(QFileDialog, "getExistingDirectory", return_value=str(run)):
            self.controller.browseRun()
        native = self.controller.queryOptions["categories"]
        self.assertEqual([p["name"] for p in native[0]["properties"]], ["p", "p_nom_opt"])
        self.drop(path)
        self.assertEqual(self.root.property("page"), 5)
        self.assertEqual(self.controller.queryOptions["categories"], native)
        self.assertTrue(self.controller.queryResults("Generator", ["snapshot"], ["p", "p_nom_opt"], "", ""))
        self.assertEqual(self.controller.workspace.active.frame.p_nom_opt.tolist(), [80.] * 3)
        self.assertEqual(self.warnings, [])

    def test_drop_lone_archive_keeps_dirty_project_and_pins_and_exports_csv(self):
        first = self.fixture_path("previous.nc")
        second = self.fixture_path("outside #Ω.NC")
        dropped_bytes = second.read_bytes()
        self.controller.loadDemo()
        project = self.controller.project
        self.controller.path = Path(self.temp.name) / "project.sqlite"
        save_project(project, self.controller.path)
        self.controller.dirty = True
        database = self.controller.path.read_bytes()
        runs_before = self.controller.state["runs"]
        self.assertTrue(self.controller.openNetcdfResults(str(first)))
        self.assertTrue(self.controller.queryResults("Generator", ["snapshot"], ["p"], "", ""))
        pinned = self.controller.workspace.active
        self.controller.pinQueryTab(pinned.id)
        self.controller.selectType("Generator")
        self.controller.selectObject("Thermal")
        self.root.setProperty("page", 1)
        QTest.qWait(40)
        editor = self.root.findChild(QObject, "objectJsonEditor")
        edit = {**json.loads(editor.property("text")), "p_nom": 999}
        editor.setProperty("text", json.dumps(edit))
        self.assertTrue(self.controller._has_draft())
        notices = []
        self.controller.notice.connect(notices.append)
        with patch.object(QMessageBox, "question", side_effect=AssertionError("Draft prompts are not allowed")):
            self.drop(second)
        self.assertEqual(self.root.property("page"), 5, notices)
        banner = self.visual_item("netcdfSourceBanner")
        self.assertTrue(banner.isVisible())
        self.assertIn(second.name, banner.property("text"))
        self.assertIn("read-only", banner.property("text"))
        self.assertIs(self.controller.project, project)
        self.assertTrue(self.controller.dirty)
        self.assertTrue(self.controller._has_draft())
        self.assertEqual(json.loads(editor.property("text")), edit)
        self.assertEqual(self.controller.path.read_bytes(), database)
        self.assertEqual(self.controller.state["runs"], runs_before)
        self.assertIsNone(self.controller.process)
        self.assertEqual(second.read_bytes(), dropped_bytes)
        self.assertIs(self.controller.workspace.tabs[0], pinned)
        self.controller.selectQueryTab(pinned.id)
        self.assertEqual(self.controller.queryOptions["externalPath"], str(first))
        self.assertIs(self.controller.workspace.active, pinned)
        export = Path(self.temp.name) / "query.csv"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(export), "")):
            self.controller.exportResults()
        self.assertEqual(pd.read_csv(export).p.iloc[0], 2.)
        self.assertEqual(json.loads(export.with_suffix(".csv.metadata.json").read_text())["source_kind"], "netcdf")
        original = first.read_bytes()
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(first), "")):
            self.controller.exportResults()
        self.assertEqual(first.read_bytes(), original)
        self.assertEqual(self.warnings, [])

    def test_file_menu_success_and_picker_cancel(self):
        path = self.fixture_path("menu.nc")
        file_button = self.visual_item("ribbonFile")
        menu = self.root.findChild(QObject, "ribbonFileMenu")
        item = menu.findChild(QObject, "openNetcdfResults")
        def choose(filedialog_response):
            QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=file_button.mapToScene(file_button.boundingRect().center()).toPoint())
            QTest.qWait(40)
            self.assertTrue(menu.property("visible"))
            with patch.object(QFileDialog, "getOpenFileName", return_value=filedialog_response) as picker:
                QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=item.mapToScene(item.boundingRect().center()).toPoint())
                picker.assert_called_once()
            QTest.qWait(30)
        choose((str(path), "NetCDF results (*.nc)"))
        self.assertEqual(self.root.property("page"), 5)
        previous = self.controller.repository
        self.root.setProperty("page", 0)
        choose(("", ""))
        self.assertEqual(self.root.property("page"), 0)
        self.assertIs(self.controller.repository, previous)
        self.assertEqual(self.warnings, [])

    def test_corrupt_and_worker_cancel_keep_table_and_pinned_query(self):
        path = self.fixture_path("keep.nc")
        self.assertTrue(self.controller.openNetcdfResults(str(path)))
        self.assertTrue(self.controller.queryResults("Generator", ["snapshot"], ["p"], "", ""))
        before = self.controller.repository
        tab = self.controller.workspace.active
        self.controller.pinQueryTab(tab.id)
        corrupt = path.with_name("corrupt.nc")
        corrupt.write_bytes(b"broken")
        self.assertFalse(self.controller.openNetcdfResults(str(corrupt)))
        QTest.keyClick(self.root, Qt.Key.Key_Escape)
        calls = []

        def wait_for_cancel(_, cancelled):
            calls.append(threading.current_thread().ident)
            # Bounded wait for the real modal Cancel button to request interruption.
            for _ in range(100):
                if cancelled():
                    raise ValueError("Cancelled")
                threading.Event().wait(0.02)
            raise AssertionError("Cancel was not delivered")

        def click_cancel():
            for widget in self.app.topLevelWidgets():
                if widget.isVisible() and widget.windowTitle() == "Open NetCDF results":
                    widget.findChild(QPushButton).click()
                    return

        with patch("energy_gui.netcdf_ui.NetcdfResults", side_effect=wait_for_cancel):
            QTimer.singleShot(60, click_cancel)
            self.assertFalse(self.controller.openNetcdfResults(str(path)))
        self.assertTrue(calls)
        self.assertNotEqual(calls[0], threading.get_ident())
        self.assertIs(self.controller.repository, before)
        self.assertIs(self.controller.workspace.active, tab)
        self.assertTrue(tab.pinned)
        self.assertEqual(self.controller.state["resultRows"], 3)
        self.assertEqual(self.warnings, [])
