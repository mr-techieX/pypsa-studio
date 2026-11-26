"""Local tests; run with `python -m unittest discover -s tests -v`."""

import json
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

import highspy
import pandas as pd
import pypsa

from energy_gui.demo import demo_project
from energy_gui.engine import BUILDERS, build_network, execute_run, prepare_run
from energy_gui.profiles import import_profile
from energy_gui.project import Project
from energy_gui.schema import attribute_spec, parse_value, registry
from energy_gui.storage import load_project, save_project


def small_project():
    project = Project(name="Known congestion case")
    project.upsert("Carrier", "AC", {})
    for name in ["A", "B"]:
        project.upsert("Bus", name, {"v_nom": 220, "carrier": "AC"})
    project.upsert("Generator", "cheap", {"bus": "A", "carrier": "AC", "p_nom": 100, "marginal_cost": 20})
    project.upsert("Generator", "expensive", {"bus": "B", "carrier": "AC", "p_nom": 100, "marginal_cost": 100})
    project.upsert("Load", "demand", {"bus": "B", "carrier": "AC", "p_set": 60})
    project.upsert("Line", "A-B", {"bus0": "A", "bus1": "B", "x": 10, "r": 0.5, "s_nom": 40, "carrier": "AC"})
    return project


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        self.temp = tempfile.TemporaryDirectory(prefix="pypsa_gui_test_", dir=preferred)
        self.directory = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def database(self, project):
        path = self.directory / "project.sqlite"
        save_project(project, path)
        return path

    def worker(self, directory, expected_code=0):
        process = subprocess.run(
            [sys.executable, "-m", "energy_gui.worker", "--run", str(directory)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
        )
        self.assertEqual(process.returncode, expected_code, process.stderr)
        events = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
        return json.loads((directory / "metadata/run_config.json").read_text()), events

    def test_registry_covers_every_component_and_attribute(self):
        network = pypsa.Network()
        self.assertEqual(len(registry()), 16)
        self.assertEqual(sum(len(c["attributes"]) for c in registry().values()), 454)
        for key in network.components.keys():
            component = network.components[key]
            self.assertEqual({a["name"] for a in registry()[component.name]["attributes"]}, set(component.defaults.index))
        self.assertNotIn("SubNetwork", BUILDERS)
        self.assertIn("Process", BUILDERS)
        self.assertIn("Shape", BUILDERS)

    def test_sqlite_roundtrip_and_profiles_are_self_contained(self):
        original = demo_project()
        loaded = load_project(self.database(original))
        self.assertEqual(loaded.to_dict(), original.to_dict())
        self.assertEqual(loaded.validate(), [])

    def test_refuses_unrecognized_database(self):
        path = self.directory / "other.sqlite"
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("CREATE TABLE unrelated (value TEXT)")
            connection.execute("INSERT INTO unrelated VALUES ('keep me')")
        with self.assertRaises(ValueError):
            save_project(Project(), path)
        with closing(sqlite3.connect(path)) as connection:
            self.assertEqual(connection.execute("SELECT value FROM unrelated").fetchone()[0], "keep me")

    def test_refuses_future_schema_without_modifying(self):
        path = self.database(demo_project())
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("UPDATE metadata SET value='99' WHERE key='schema_version'")
        with self.assertRaises(ValueError):
            load_project(path)
        with self.assertRaises(ValueError):
            save_project(Project(), path)
        with closing(sqlite3.connect(path)) as connection:
            self.assertEqual(connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0], "99")

    def test_outputs_are_not_editable_and_bool_is_strict(self):
        project = Project()
        with self.assertRaises(ValueError):
            project.upsert("Generator", "bad", {"p_nom_opt": 100})
        spec = attribute_spec("Generator", "committable")
        self.assertIs(parse_value(spec, "false"), False)
        with self.assertRaises(ValueError):
            parse_value(spec, "yes")

    def test_bus_references_and_safe_deletion(self):
        project = small_project()
        with self.assertRaises(ValueError):
            project.delete("Bus", "A")
        project.object("Generator", "cheap")["attributes"]["bus"] = "missing"
        self.assertTrue(any("missing Bus" in e for e in project.validate()))

    def test_invalid_reactance_and_nonnumeric_snapshots(self):
        project = small_project()
        project.object("Line", "A-B")["attributes"]["x"] = 0
        self.assertTrue(any("reactance" in e for e in project.validate()))
        project.snapshots = ["not a date"]
        self.assertTrue(any("timestamp" in e for e in project.validate()))

    def test_unsupported_quadratic_is_rejected_not_ignored(self):
        project = small_project()
        project.object("Generator", "cheap")["attributes"]["marginal_cost_quadratic"] = 2
        self.assertTrue(any("quadratic" in e for e in project.validate()))

    def test_csv_alignment_uses_timestamps_not_row_order(self):
        project = small_project()
        project.set_horizon("2026-01-01", 2, 30)
        path = self.directory / "profile.csv"
        pd.DataFrame({"time": list(reversed(project.snapshots)), "load": [20, 10]}).to_csv(path, index=False)
        import_profile(project, path, "Load", "demand", "p_set", "time", "load")
        self.assertEqual(project.profiles[0]["values"], [10, 20])
        network = build_network(project)
        self.assertEqual(network.loads_t.p_set["demand"].tolist(), [10, 20])
        self.assertEqual(network.snapshot_weightings.objective.tolist(), [0.5, 0.5])
        path.unlink()
        self.assertEqual(load_project(self.database(project)).profiles[0]["values"], [10, 20])

    def test_csv_rejects_missing_duplicate_and_blank_data(self):
        project = small_project()
        project.set_horizon("2026-01-01", 2, 60)
        path = self.directory / "bad.csv"
        cases = [
            {"time": [project.snapshots[0]], "load": [10]},
            {"time": [project.snapshots[0]] * 2, "load": [10, 20]},
            {"time": project.snapshots, "load": [10, None]},
        ]
        for data in cases:
            pd.DataFrame(data).to_csv(path, index=False)
            with self.assertRaises(ValueError):
                import_profile(project, path, "Load", "demand", "p_set", "time", "load")
        self.assertEqual(project.profiles, [])

    def test_horizon_does_not_silently_realign_profiles(self):
        project = demo_project()
        with self.assertRaises(ValueError):
            project.set_horizon("2026-02-01", 12, 60)

    def test_extended_link_and_process_ports_construct(self):
        project = small_project()
        project.upsert("Link", "conversion", {"bus0": "A", "bus1": "B", "bus2": "A", "efficiency": 0.7, "efficiency2": 0.2})
        project.upsert("Process", "process", {"bus0": "A", "bus1": "B", "bus2": "A", "rate2": 0.2})
        network = build_network(project)
        self.assertEqual(network.links.at["conversion", "bus2"], "A")
        self.assertAlmostEqual(network.processes.at["process", "rate2"], 0.2)

    def test_shape_wkt_and_type_catalogue_construct(self):
        project = small_project()
        project.upsert("Shape", "point", {"geometry": "POINT (1 2)", "component": "Bus", "idx": "A"})
        project.upsert("LineType", "custom", {"r_per_length": 0.1, "x_per_length": 0.2, "i_nom": 1})
        network = build_network(project)
        self.assertEqual(network.shapes.at["point", "geometry"].wkt, "POINT (1 2)")
        self.assertIn("custom", network.line_types.index)

    def test_run_frozen_inputs_and_unique_names(self):
        project = small_project()
        database = self.database(project)
        first = prepare_run(database)
        second = prepare_run(database)
        self.assertNotEqual(first, second)
        project.name = "changed after run"
        save_project(project, database)
        self.assertEqual(load_project(first / "inputs.sqlite").name, "Known congestion case")

    def test_lp_dispatch_balance_congestion_and_independent_export_solve(self):
        directory = prepare_run(self.database(small_project()))
        config, events = self.worker(directory)
        self.assertEqual(config["status"], "succeeded")
        self.assertAlmostEqual(config["objective"], 2800, places=5)
        dispatch = pd.read_csv(directory / "tables" / "generators__p.csv")
        self.assertAlmostEqual(dispatch.cheap.iloc[0], 40, places=6)
        self.assertAlmostEqual(dispatch.expensive.iloc[0], 20, places=6)
        self.assertAlmostEqual(dispatch.cheap.iloc[0] + dispatch.expensive.iloc[0], 60)
        self.assertEqual(events[-1]["stage"], "complete")
        self.assertTrue((directory / "solution.nc").is_file())
        highs = highspy.Highs()
        highs.setOptionValue("output_flag", False)
        highs.setOptionValue("threads", 1)
        self.assertEqual(highs.readModel(str(directory / "formulation/model.lp")), highspy.HighsStatus.kOk)
        highs.run()
        self.assertAlmostEqual(highs.getObjectiveValue(), config["objective"], places=6)
        highs.clear()

    def test_mps_export_and_milp_commitment_solve(self):
        project = small_project()
        project.object("Generator", "expensive")["attributes"]["committable"] = True
        directory = prepare_run(self.database(project), export_format="mps")
        config, _ = self.worker(directory)
        self.assertAlmostEqual(config["objective"], 2800, places=5)
        self.assertTrue((directory / "formulation/model.mps").is_file())
        status = pd.read_csv(directory / "tables" / "generators__status.csv")
        self.assertAlmostEqual(status.expensive.iloc[0], 1)

    def test_fractional_snapshot_duration_scales_objective(self):
        project = small_project()
        project.set_horizon("2026-01-01", 1, 30)
        directory = prepare_run(self.database(project), export_format="none")
        config, _ = self.worker(directory)
        self.assertAlmostEqual(config["objective"], 1400, places=5)

    def test_infeasible_run_is_not_published_as_success(self):
        project = small_project()
        project.object("Load", "demand")["attributes"]["p_set"] = 1000
        directory = prepare_run(self.database(project), export_format="none")
        config, events = self.worker(directory, expected_code=1)
        self.assertEqual(config["status"], "failed")
        self.assertEqual(config["termination_condition"], "infeasible")
        self.assertEqual(events[-1]["stage"], "failed")
        self.assertFalse((directory / "metadata/catalog.json").exists())

    def test_direct_run_releases_windows_log_handle(self):
        directory = prepare_run(self.database(small_project()), export_format="none")
        execute_run(directory)
        log = directory / "highs.log"
        log.rename(directory / "released.log")


if __name__ == "__main__":
    unittest.main()
