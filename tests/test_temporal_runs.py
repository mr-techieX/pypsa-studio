"""Real solve/report integration and backward-compatible saved criteria."""

import json
from pathlib import Path
import tempfile
import unittest

from energy_gui.engine import prepare_run, execute_run
from energy_gui.storage import save_project
from energy_gui.results import ResultsRepository
from energy_gui.analysis import compare_query, prepare_analysis
from test_horizon import fixture, specification


class TemporalRunTests(unittest.TestCase):
    def test_single_and_sequential_reports_match_saved_queries(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            p = fixture()
            p.set_horizon("2027-01-01", 48, 60)
            db = root / "p.sqlite"
            save_project(p, db)
            original = db.read_bytes()
            sequential = prepare_run(db, "sequential", "none",
                horizon=specification(duration=2, duration_unit="day", step_count=2, step_size=1),
                report_resolutions=["native", "daily", "weekly", "monthly", "yearly"])
            single = prepare_run(db, "single", "none", report_resolutions=["daily"])
            for run in [sequential, single]:
                result = execute_run(run)
                self.assertEqual(result["status"], "succeeded")
                manifest = json.loads((run / "metadata/manifest.json").read_text())
                self.assertTrue(any(e.get("file") == "daily/Generator__p__energy.csv" for e in manifest["entries"]))
                self.assertFalse(any((run / "steps").glob("*/reports")))
                repo = ResultsRepository(run, json.loads((run / "metadata/catalog.json").read_text()))
                summary = repo.query("Generator", ["Supply"], ["p"],
                                    aggregation=dict(resolution="daily", metric="energy"))[0]
                self.assertEqual(summary.p.tolist(), [120, 120])
            criteria = dict(component="Generator", objects=["Supply"], properties=["p"], start="", end="",
                            aggregation=dict(resolution="daily", metric="energy"))
            delta, details = compare_query(p, single, sequential, criteria)
            self.assertEqual(delta.delta_right_minus_left.tolist(), [0, 0])
            self.assertEqual(delta.unit.tolist(), ["MWh", "MWh"])
            self.assertEqual(db.read_bytes(), original)

    def test_report_resolution_rejected_before_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "p.sqlite"
            p = fixture()
            p.set_horizon("2027-01-01", 2, 1440)
            save_project(p, db)
            with self.assertRaisesRegex(ValueError, "finer"):
                prepare_run(db, report_resolutions=["hourly"])
            self.assertFalse((db.parent / "runs").exists())
