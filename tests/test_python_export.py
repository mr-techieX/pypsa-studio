"""Standalone PyPSA replay and the Runs export toggle."""

import json
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_qml_controls as controls
import numpy as np
import pandas as pd
import pypsa
import xarray as xr
from test_horizon import fixture, specification
from energy_gui.advanced import snapshot_weights
from energy_gui.engine import execute_run, prepare_run
from energy_gui.netcdf_results import NetcdfResults
from energy_gui.results import ResultsRepository
from energy_gui.sequence_replay import run_sequence, step_axis
from energy_gui.storage import save_project
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest


class PythonExportTests(unittest.TestCase):
    def test_step_axis_accepts_fractional_hour_snapshots_and_rejects_gaps(self):
        network = pypsa.Network()
        network.set_snapshots(pd.date_range("2027-01-01", periods=2, freq="5min"))
        network.snapshot_weightings = network.snapshot_weightings.astype(float) * (5/60)
        self.assertEqual(step_axis(network)[2], pd.Timestamp("2027-01-01T00:10:00"))
        network.snapshot_weightings.loc[network.snapshots[0], "stores"] = 1
        with self.assertRaisesRegex(ValueError, "contiguous coverage"):
            step_axis(network)

    def test_combined_assembly_keeps_missing_and_does_not_publish_on_export_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for label in ("step-0001", "step-0002"):
                folder = root / "steps" / label
                folder.mkdir(parents=True)
                (folder / "model.py").touch()

            def staged_step(path):
                first = Path(path).parent.name == "step-0001"

                def build():
                    network = pypsa.Network()
                    start = "2027-01-01T00:00:00" if first else "2027-01-01T01:00:00"
                    network.set_snapshots(pd.DatetimeIndex([start]))
                    network.add("Bus", "Bus")
                    network.add("Generator", "Supply", bus="Bus", p_nom=10)
                    return network

                def solve(network):
                    network._objective = 4.
                    network.generators_t.p = pd.DataFrame({"Supply": [4.]}, index=network.snapshots)
                    if first:
                        network.buses_t.marginal_price = pd.DataFrame({"Bus": [1.]}, index=network.snapshots)

                return {"build_network": build, "solve": solve}

            with patch("energy_gui.sequence_replay.runpy.run_path", side_effect=staged_step):
                run_sequence(root, 2)
                success, = root.glob("replay-*")
                repo = NetcdfResults(success / "solution.nc")
                prices = repo.query("Bus", ["Bus"], ["marginal_price"])[0]["marginal_price"]
                self.assertEqual(prices.iloc[0], 1.)
                self.assertTrue(pd.isna(prices.iloc[1]))
                export = pypsa.Network.export_to_netcdf

                def fail_combined(network, path):
                    if path.name == "solution-pending.nc":
                        path.write_bytes(b"incomplete")
                        raise OSError("simulated combined export failure")
                    return export(network, path)

                with patch.object(pypsa.Network, "export_to_netcdf", fail_combined):
                    with self.assertRaisesRegex(OSError, "simulated combined export failure"):
                        run_sequence(root, 2)
                failed, = set(root.glob("replay-*")) - {success}
                self.assertEqual(len(list(failed.glob("step-*.nc"))), 2)
                self.assertEqual(list(failed.glob("solution*.nc")), [])
                summary = json.loads((failed / "metadata/summary.json").read_text(encoding="utf-8"))
                self.assertEqual((summary["status"], summary["failed_at"]), ("failed", "assembly"))

    def test_standalone_replay_matches_studio_and_export_is_opt_in(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = fixture()
            project.set_horizon("2027-01-01", 2, 30)
            project.profiles.append(dict(component="Load", name="Demand", attribute="p_set", values=[5, 7]))
            database = root / "project.sqlite"
            save_project(project, database)
            self.assertFalse((prepare_run(database, export_format="none") / "model.py").exists())
            run = prepare_run(database, export_format="none", export_python=True)
            self.assertEqual(json.loads((run / "metadata/run_config.json").read_text())["python_script"], "model.py")
            script = root / "model.py"
            script.write_bytes((run / "model.py").read_bytes())
            expected = execute_run(run)["objective"]
            self.assertEqual({p.name for p in run.iterdir() if p.is_file()},
                             {"inputs.sqlite", "solution.nc", "highs.log", "application.log", "model.py"})
            self.assertEqual({p.name for p in (run / "metadata").glob("*.json")},
                             {"run_config.json", "catalog.json", "formulation_summary.json", "solution_checks.json"})
            replay = subprocess.run([sys.executable, "-I", str(script)], cwd=root,
                                    capture_output=True, text=True, timeout=120)
            self.assertEqual(replay.returncode, 0, replay.stderr)
            self.assertAlmostEqual(float(replay.stdout.strip().splitlines()[-1]), expected)

    def replay(self, script, expected_success=True):
        result = subprocess.run([sys.executable, "-I", str(script)], cwd=script.parent,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode == 0, expected_success, result.stderr)
        return result

    def test_sequential_replay_matches_and_recomputes_state_after_edit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = fixture()
            project.set_horizon("2027-01-01", 6, 60)
            project.object("Generator", "Supply")["attributes"].update(
                committable=True, min_down_time=3, up_time_before=0, down_time_before=1,
                stand_by_cost=1, start_up_cost=10, p_min_pu=0.01)
            project.upsert("Bus", "City", {})
            project.upsert("Bus", "Junction", {})
            project.upsert("Line", "Feeder", dict(bus0="Junction", bus1="City", r=0.01, x=0.1, s_nom=100))
            project.object("Load", "Demand")["attributes"]["bus"] = "City"
            project.upsert("Link", "Connection", dict(bus0="Bus", bus1="Junction", p_nom=100,
                           committable=True, min_up_time=3, up_time_before=1, p_init=0,
                           ramp_limit_up=0.01, marginal_cost=1))
            project.upsert("Generator", "Peaker", dict(bus="City", p_nom=100, marginal_cost=100))
            project.upsert("Store", "Tank", dict(bus="Bus", e_nom=100, e_initial=20, p_set=0.1))
            project.upsert("StorageUnit", "Battery", dict(bus="City", p_nom=1, max_hours=100,
                           state_of_charge_initial=20, p_set=0.1, standing_loss=0.01))
            project.profiles = [
                dict(component="Load", name="Demand", attribute="p_set", values=[5, 6, 7, 8, 9, 10]),
                dict(component="Load", name="Junction demand", attribute="p_set", values=[0.03]*6),
                dict(component="Store", name="Tank", attribute="standing_loss", values=[.01, .01, .02, .01, .03, .01]),
            ]
            project.upsert("Load", "Junction demand", dict(bus="Junction"))
            database = root / "project.sqlite"
            save_project(project, database)
            spec = specification(duration=6, duration_unit="hour", step_size=2,
                                 step_unit="hour", step_count=3)
            no_export = prepare_run(database, horizon=spec, export_format="none")
            self.assertFalse((no_export / "run.py").exists())
            original = database.read_bytes()
            run = prepare_run(database, horizon=spec, export_format="none", export_python=True)
            self.assertEqual(json.loads((run / "metadata/run_config.json").read_text())["python_script"], "run.py")
            expected = execute_run(run)["objective"]
            self.assertEqual(database.read_bytes(), original)
            portable = root / "portable"
            portable.mkdir()
            shutil.copyfile(run / "run.py", portable / "run.py")
            for folder in (run / "steps").iterdir():
                dest = portable / "steps" / folder.name
                dest.mkdir(parents=True)
                shutil.copyfile(folder / "model.py", dest / "model.py")
            frozen = {path: hashlib.sha256(path.read_bytes()).digest()
                      for path in run.rglob("*") if path.is_file()}
            self.replay(portable / "run.py")
            output, = portable.glob("replay-*")
            summary = json.loads((output / "metadata/summary.json").read_text())
            manifest = json.loads((run / "metadata/execution_manifest.json").read_text())
            self.assertFalse(list(run.glob("*.json")))
            self.assertFalse(list(run.glob("steps/*/*.json")))
            self.assertFalse(list(output.glob("*.json")))
            self.assertEqual(summary["status"], "succeeded")
            self.assertAlmostEqual(summary["objective"], expected)
            solution = output / "solution.nc"
            self.assertEqual(len(list(output.glob("step-*.nc"))), 3)
            self.assertFalse((output / "solution-pending.nc").exists())
            original_solution = solution.read_bytes()
            lone = root / "lone"
            lone.mkdir()
            shutil.copyfile(solution, lone / "solution.nc")
            combined, studio = NetcdfResults(lone / "solution.nc"), NetcdfResults(run / "solution.nc")
            native = ResultsRepository(run, json.loads((run / "metadata/catalog.json").read_text(encoding="utf-8")))
            for repo in (combined, studio, native):
                generator = next(c for c in repo.describe() if c["name"] == "Generator")
                self.assertTrue({"p", "p_nom_opt"} <= {p["name"] for p in generator["properties"]})
                with self.assertRaisesRegex(ValueError, "p_nom"):
                    repo.query("Generator", ["Supply"], ["p_nom"])
            pd.testing.assert_index_equal(combined.snapshots, studio.snapshots)
            pd.testing.assert_frame_equal(snapshot_weights(combined.project), snapshot_weights(studio.project))
            self.assertAlmostEqual(combined.meta["objective"], studio.meta["objective"])
            self.assertIn("Sequential replay", combined.description)
            for kind, names, properties in [
                ("Generator", ["Supply", "Peaker"], ["p", "p_nom_opt"]),
                ("Line", ["Feeder"], ["p0", "p1"]),
                ("Link", ["Connection"], ["p0"]),
                ("Store", ["Tank"], ["e"]),
                ("StorageUnit", ["Battery"], ["state_of_charge"]),
            ]:
                args = (kind, names, properties, combined.snapshots[1].isoformat(), combined.snapshots[-1].isoformat())
                pd.testing.assert_frame_equal(combined.query(*args)[0], studio.query(*args)[0],
                                              check_exact=False, rtol=1e-8, atol=1e-8)
                pd.testing.assert_frame_equal(combined.query(*args)[0], native.query(*args)[0],
                                              check_exact=False, check_dtype=False, rtol=1e-8, atol=1e-8)
            with xr.open_dataset(solution, engine="netcdf4") as dataset:
                provenance = json.loads(dataset.attrs["meta"])["studio_replay"]
                self.assertEqual(provenance["kind"], "sequential_replay")
                self.assertEqual([s["start"] for s in provenance["steps"]], [s["start"] for s in summary["steps"]])
                self.assertEqual(provenance["steps"][-1]["end"], "2027-01-01T06:00:00")
            for got, wanted in zip(summary["steps"], manifest["steps"], strict=True):
                self.assertAlmostEqual(got["objective"], wanted["objective"])
                for a, b in zip(got["outgoing"], wanted["outgoing"], strict=True):
                    self.assertEqual(a.keys(), b.keys())
                    for key in a:
                        if isinstance(a[key], float):
                            self.assertAlmostEqual(a[key], b[key])
                        else:
                            self.assertEqual(a[key], b[key])
            second = portable / "steps/step-0002/model.py"
            single = self.replay(second)
            self.assertAlmostEqual(float(single.stdout.strip().splitlines()[-1]), manifest["steps"][1]["objective"])
            for table in ("stores__e.csv", "storage_units__state_of_charge.csv",
                          "generators__status.csv", "links__p0.csv"):
                pd.testing.assert_frame_equal(pd.read_csv(output / "tables" / table),
                                              pd.read_csv(run / "tables" / table), check_dtype=False)
            first = portable / "steps/step-0001/model.py"
            first.write_text(first.read_text(encoding="utf-8").replace("e_initial=20.0", "e_initial=30.0"),
                             encoding="utf-8")
            self.replay(portable / "run.py")
            edited, = set(portable.glob("replay-*")) - {output}
            self.assertGreater(pd.read_csv(edited / "tables/stores__e.csv")["Tank"].iloc[-1],
                                pd.read_csv(output / "tables/stores__e.csv")["Tank"].iloc[-1] + 8)
            edited_repo = NetcdfResults(edited / "solution.nc")
            np.testing.assert_allclose(edited_repo.query("Store", ["Tank"], ["e"])[0]["e"],
                                       pd.read_csv(edited / "tables/stores__e.csv")["Tank"])
            self.assertEqual(solution.read_bytes(), original_solution)
            second_source = second.read_text(encoding="utf-8")
            self.assertIn("p_nom=100.0", second_source)
            second.write_text(second_source.replace("p_nom=100.0", "p_nom=101.0", 1), encoding="utf-8")
            rejection = self.replay(portable / "run.py", expected_success=False)
            self.assertIn("incompatible static inputs", rejection.stderr)
            incompatible, = set(portable.glob("replay-*")) - {output, edited}
            self.assertTrue((incompatible / "step-0001.nc").is_file())
            self.assertFalse((incompatible / "solution.nc").exists())
            second.write_text(second_source.replace("[7, 8]", "[700, 800]"),
                              encoding="utf-8")
            self.replay(portable / "run.py", expected_success=False)
            failed, = set(portable.glob("replay-*")) - {output, edited, incompatible}
            self.assertTrue((failed / "step-0001.nc").is_file())
            self.assertFalse((failed / "tables").exists())
            self.assertFalse((failed / "solution.nc").exists())
            self.assertFalse((failed / "solution-pending.nc").exists())
            failure = json.loads((failed / "metadata/summary.json").read_text())
            self.assertEqual((failure["status"], failure["failed_at"]), ("failed", "step-0002"))

            second.unlink()
            missing = self.replay(portable / "run.py", expected_success=False)
            self.assertIn("export the complete sequence", missing.stderr)
            self.assertEqual(set(portable.glob("replay-*")), {output, edited, incompatible, failed})
            self.assertEqual({path: hashlib.sha256(path.read_bytes()).digest()
                              for path in run.rglob("*") if path.is_file()}, frozen)


class PythonExportUiTests(unittest.TestCase):
    setUpClass = classmethod(controls.QmlControlsTests.setUpClass.__func__)
    setUp = controls.QmlControlsTests.setUp
    tearDown = controls.QmlControlsTests.tearDown
    visual_item = controls.QmlControlsTests.visual_item

    def test_checkbox_controls_both_run_modes(self):
        self.controller.loadDemo()
        self.controller.path = Path(self.temp.name) / "model.sqlite"
        self.root.setProperty("page", 4)
        QTest.qWait(80)
        checkbox = self.visual_item("exportPythonScript")
        self.assertTrue(checkbox.isVisible())
        self.assertEqual(checkbox.property("text"), "Save as Python run")
        self.assertFalse(checkbox.property("checked"))
        checkbox.setProperty("checked", True)
        start = self.visual_item("configuredRunStart")
        with patch.object(self.controller, "_launch_run") as launch:
            QTest.mouseClick(self.root, Qt.MouseButton.LeftButton,
                             pos=start.mapToScene(start.boundingRect().center()).toPoint())
            launch.assert_called_once()
            self.assertTrue((launch.call_args.args[0] / "model.py").is_file())
        self.visual_item("horizonMode").setProperty("currentIndex", 1)
        QTest.qWait(80)
        self.assertTrue(checkbox.isVisible())
        self.assertEqual(checkbox.property("text"), "Save as Python run")
        self.assertTrue(checkbox.property("checked"))
        self.controller.project = fixture()
        self.controller.changed.emit()
        self.visual_item("horizonStart").setProperty("text", "2027-01-01T00:00:00")
        QTest.qWait(60)
        with patch.object(self.controller, "_launch_run") as launch:
            QTest.mouseClick(self.root, Qt.MouseButton.LeftButton,
                             pos=start.mapToScene(start.boundingRect().center()).toPoint())
            launch.assert_called_once()
            run = launch.call_args.args[0]
            self.assertTrue((run / "run.py").is_file())
            self.assertFalse((run / "model.py").exists())
        self.assertEqual(self.warnings, [])
