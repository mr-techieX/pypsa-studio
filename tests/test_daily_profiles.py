"""Explicit daily-template expansion is by clock time, not implicit row cycling."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from energy_gui.engine import prepare_run, execute_run
from energy_gui.horizon import schedule, aligned_project
from energy_gui.storage import save_project, load_project
from test_horizon import fixture, specification


def daily_fixture(minutes=60):
    project = fixture()
    count = 24 * 60 // minutes
    project.set_horizon("2026-01-01", count, minutes)
    project.profiles = [
        dict(component="Load", name="Demand", attribute="p_set", values=list(range(1, count + 1)))
    ]
    return project


class DailyProfileTests(unittest.TestCase):
    def test_daily_repeat_maps_new_dates_and_preserves_project(self):
        project = daily_fixture()
        before = deepcopy(project.to_dict())
        plan = schedule(specification(profile_policy="repeat_daily"))
        result = aligned_project(project, plan)
        self.assertEqual(result.profiles[0]["values"], list(range(1, 25)) * 30)
        self.assertEqual(len(result.snapshots), 720)
        self.assertEqual(result.snapshots[0], "2027-01-01T00:00:00")
        self.assertEqual(project.to_dict(), before)
        self.assertIn("repeat daily", plan["summary"])

    def test_exact_coverage_is_still_the_default(self):
        with self.assertRaisesRegex(ValueError, "Repeat daily profiles"):
            aligned_project(daily_fixture(), schedule(specification()))
        with self.assertRaisesRegex(ValueError, "profile"):
            schedule(specification(profile_policy="repeat_anything"))

    def test_non_midnight_start_uses_clock_time_not_first_row(self):
        plan = schedule(specification(start="2028-02-28T12:00:00",
                                     duration=2, duration_unit="day",
                                     step_count=2, step_size=1,
                                     profile_policy="repeat_daily"))
        result = aligned_project(daily_fixture(), plan)
        self.assertEqual(result.profiles[0]["values"], list(range(13, 25)) + list(range(1, 25)) + list(range(1, 13)))
        self.assertIn("2028-02-29T00:00:00", result.snapshots)

    def test_half_hour_templates_work_only_at_matching_resolution(self):
        project = daily_fixture(minutes=30)
        # The schedule API currently exposes whole hours and larger, so exercise
        # rejection rather than silently downsampling 48 half-hour values to 24.
        with self.assertRaisesRegex(ValueError, "interval"):
            aligned_project(project, schedule(specification(profile_policy="repeat_daily")))

    def test_missing_duplicate_multiday_or_irregular_templates_are_rejected(self):
        for kind in ["short", "duplicate", "shifted", "multiday", "gap"]:
            p = daily_fixture()
            if kind == "short":
                p.snapshots.pop()
                p.profiles[0]["values"].pop()
            elif kind == "duplicate":
                p.snapshots[-1] = p.snapshots[0]
            elif kind == "shifted":
                p.snapshots = [t.isoformat() for t in pd.date_range("2026-01-01T01:00", periods=24, freq="h")]
            elif kind == "multiday":
                p.snapshots = [t.isoformat() for t in pd.date_range("2026-01-01", periods=48, freq="h")]
                p.profiles[0]["values"] *= 2
            else:
                p.snapshots[-1] = "2026-01-02T00:00:00"
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                aligned_project(p, schedule(specification(profile_policy="repeat_daily")))

    def test_no_resampling_and_custom_accounting_weights_are_rejected(self):
        p = daily_fixture()
        with self.assertRaisesRegex(ValueError, "interval"):
            aligned_project(p, schedule(specification(snapshot_size=2, profile_policy="repeat_daily")))
        p.advanced_inputs["weights"] = [dict(objective=1, stores=1, generators=1) for _ in p.snapshots]
        self.assertEqual(len(aligned_project(p, schedule(specification(profile_policy="repeat_daily"))).snapshots), 720)
        p.advanced_inputs["weights"][3]["objective"] = 2
        with self.assertRaisesRegex(ValueError, "weights"):
            aligned_project(p, schedule(specification(profile_policy="repeat_daily")))

    def test_actual_month_run_repeats_inputs_but_not_storage_state(self):
        p = daily_fixture()
        p.upsert("Generator", "Solar", dict(bus="Bus", p_nom=10, marginal_cost=0))
        solar = [0.0] * 6 + [0.5] * 12 + [0.0] * 6
        p.profiles.append(dict(component="Generator", name="Solar", attribute="p_max_pu", values=solar))
        p.upsert("StorageUnit", "Battery", dict(
            bus="Bus", p_nom=1, max_hours=100, state_of_charge_initial=100, p_set=0.01))
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "p.sqlite"
            save_project(p, db)
            before = db.read_bytes()
            run = prepare_run(db, horizon=specification(profile_policy="repeat_daily"))
            result = execute_run(run)
            self.assertEqual(result["status"], "succeeded")
            frozen = load_project(run / "inputs.sqlite")
            self.assertEqual(frozen.profiles[0]["values"], list(range(1, 25)) * 30)
            self.assertEqual(frozen.profiles[1]["values"], solar * 30)
            self.assertEqual(db.read_bytes(), before)
            meta = json.loads((run / "metadata/run_config.json").read_text())
            self.assertEqual(meta["horizon"]["spec"]["profile_policy"], "repeat_daily")
            self.assertEqual(meta["profile_source"]["template_snapshots"], p.snapshots)
            energy = pd.read_csv(run / "tables/storage_units__state_of_charge.csv")["Battery"]
            self.assertAlmostEqual(energy.iloc[23], 99.76, places=6)
            self.assertAlmostEqual(energy.iloc[-1], 92.8, places=6)
            self.assertEqual(len(energy), 720)
