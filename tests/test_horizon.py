"""Calendar contract, actual independent solves, state transfer and frozen queries."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from energy_gui.engine import prepare_run, execute_run, build_network
from energy_gui.horizon import schedule, aligned_project
from energy_gui.project import Project
from energy_gui.results import ResultsRepository
from energy_gui.storage import save_project, load_project


def specification(**kwargs):
    return {**dict(start="2027-01-01", duration=1, duration_unit="month",
                   snapshot_size=1, snapshot_unit="hour", step_count=15,
                   step_size=2, step_unit="day"), **kwargs}


def fixture():
    p = Project(name="Sequential reference")
    p.upsert("Carrier", "AC", {})
    p.upsert("Bus", "Bus", {})
    p.upsert("Generator", "Supply", dict(bus="Bus", p_nom=100, marginal_cost=10))
    p.upsert("Load", "Demand", dict(bus="Bus", p_set=5))
    return p


class HorizonTests(unittest.TestCase):
    def test_confirmed_month_rule_and_floor_sync(self):
        p = schedule(specification())
        self.assertEqual(len(p["steps"]), 15)
        self.assertEqual(len(p["snapshots"]), 720)
        self.assertEqual(p["unused_hours"], 24)
        self.assertEqual(p["execution_end"], "2027-01-31T00:00:00")
        self.assertEqual(p["horizon_end"], "2027-02-01T00:00:00")
        with self.assertRaisesRegex(ValueError, "beyond"):
            schedule(specification(step_count=16))
        self.assertEqual(schedule(specification(step_count=16), sync=True)["spec"]["step_count"], 15)

    def test_leap_calendar_and_month_end_anchor(self):
        p = schedule(specification(start="2028-02-01", step_count=29, step_size=1))
        self.assertEqual(len(p["snapshots"]), 696)
        p = schedule(specification(start="2027-01-31", duration=3,
                                  step_count=3, step_size=1, step_unit="month",
                                  snapshot_unit="month"))
        self.assertEqual(p["snapshots"], ["2027-01-31T00:00:00", "2027-02-28T00:00:00", "2027-03-31T00:00:00"])
        self.assertEqual(p["hours"], [672, 744, 720])

    def test_invalid_and_nondivisible_inputs(self):
        for kwargs in [dict(step_count=0), dict(step_size=True), dict(start="bad"),
                       dict(start="2027-01-01Z"), dict(snapshot_size=7),
                       dict(step_unit="fortnight"), dict(step_count=10001)]:
            with self.subTest(kwargs=kwargs), self.assertRaises((ValueError, TypeError)):
                schedule(specification(**kwargs))
        with self.assertRaisesRegex(ValueError, "No complete"):
            schedule(specification(step_size=2, step_unit="month"), sync=True)

    def test_input_alignment_no_mutation_or_relabelling(self):
        p = fixture()
        p.set_horizon("2027-01-01", 744, 60)
        p.profiles = [dict(component="Load", name="Demand", attribute="p_set",
                           values=list(range(744)))]
        original = p.to_dict()
        q = aligned_project(p, schedule(specification()))
        self.assertEqual(len(q.profiles[0]["values"]), 720)
        self.assertEqual(p.to_dict(), original)
        with self.assertRaisesRegex(ValueError, "coverage"):
            aligned_project(p, schedule(specification(start="2027-02-01", step_count=1)))
        with self.assertRaisesRegex(ValueError, "durations"):
            aligned_project(p, schedule(specification(snapshot_size=2)))

    def test_reject_unverified_semantics_before_run_creation(self):
        for kind, attrs in [
            ("Generator", dict(bus="Bus", p_nom_extendable=True)),
            ("StorageUnit", dict(bus="Bus", cyclic_state_of_charge=True)),
            ("Store", dict(bus="Bus", e_cyclic=True)),
            ("GlobalConstraint", dict(constant=10)),
            ("Link", dict(bus0="Bus", bus1="Bus", delay=1)),
        ]:
            p = fixture()
            p.upsert(kind, "Unsupported", attrs)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                aligned_project(p, schedule(specification()))

    def run_case(self, p, spec, export="lp"):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        db = self.root / "project.sqlite"
        save_project(p, db)
        before = db.read_bytes()
        run = prepare_run(db, "sequential", export, horizon=spec)
        events = []
        result = execute_run(run, lambda *event: events.append(event))
        self.assertEqual(db.read_bytes(), before)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(len([e for e in events if e[0] == "step"]), spec["step_count"])
        repo = ResultsRepository(run, json.loads((run / "metadata/catalog.json").read_text()))
        return run, result, repo

    def test_real_fifteen_step_month_cost_and_query(self):
        run, result, repo = self.run_case(fixture(), specification())
        self.assertAlmostEqual(result["objective"], 5 * 10 * 720)
        self.assertEqual(len(list((run / "steps").glob("*/formulation/model.lp"))), 15)
        self.assertFalse((run / "formulation/model.lp").exists())
        self.assertEqual(len(repo.snapshots), 720)
        self.assertEqual(repo.snapshots[-1], pd.Timestamp("2027-01-30T23:00"))
        manifest = json.loads((run / "metadata/execution_manifest.json").read_text())
        self.assertEqual(manifest["completed_steps"], 15)
        self.assertEqual(manifest["status"], "succeeded")

    def test_storage_loss_handoff_matches_full_solve(self):
        p = fixture()
        # Fix storage dispatch to isolate state recurrence, including efficiency/inflow.
        p.upsert("StorageUnit", "Battery", dict(
            bus="Bus", p_nom=1, max_hours=100, state_of_charge_initial=20,
            p_set=0.1, standing_loss=0.01, inflow=0.2,
            efficiency_store=0.8, efficiency_dispatch=0.9, marginal_cost=1))
        p.upsert("Store", "Tank", dict(
            bus="Bus", e_nom=100, e_initial=20, p_set=0.1, standing_loss=0.02))
        spec = specification(duration=6, duration_unit="hour", step_size=2,
                             step_unit="hour", step_count=3)
        run, _, _ = self.run_case(p, spec)
        effective = load_project(run / "inputs.sqlite")
        full = build_network(effective)
        status, _ = full.optimize(solver_name="highs", include_objective_constant=True,
                                  solver_options={"threads": 1}, log_to_console=False)
        self.assertEqual(status, "ok")
        for component, attr in [("StorageUnit", "state_of_charge"), ("Store", "e")]:
            saved = pd.read_csv(run / "tables" / f"{full.components[component].list_name}__{attr}.csv", index_col=0)
            expected = full.components[component].dynamic[attr]
            self.assertAlmostEqual(float(saved.iloc[-1, 0]), float(expected.iloc[-1, 0]), places=7)
        handoff = json.loads((run / "steps/step-0002/metadata/handoff.json").read_text())
        self.assertTrue(all(r["boundary_loss"] > 0 for r in handoff["applied"] if "boundary_loss" in r))

    def test_ramping_crosses_step_boundary(self):
        p = fixture()
        p.object("Generator", "Supply")["attributes"].update(ramp_limit_up=0.01, p_init=0)
        p.upsert("Generator", "Peaker", dict(bus="Bus", p_nom=100, marginal_cost=100))
        run, _, _ = self.run_case(p, specification(duration=4, duration_unit="hour",
                                  step_size=2, step_unit="hour", step_count=2))
        frame = pd.read_csv(run / "tables/generators__p.csv")
        self.assertEqual(frame["Supply"].round(6).tolist(), [1, 2, 3, 4])

    def test_commitment_history_is_carried(self):
        p = fixture()
        p.object("Generator", "Supply")["attributes"].update(
            committable=True, min_up_time=4, up_time_before=0, down_time_before=2,
            p_min_pu=0.01, stand_by_cost=1, start_up_cost=10)
        p.upsert("Generator", "Peaker", dict(bus="Bus", p_nom=100, marginal_cost=100))
        run, _, _ = self.run_case(p, specification(duration=6, duration_unit="hour",
                                  step_size=2, step_unit="hour", step_count=3))
        second = load_project(run / "steps/step-0002/inputs.sqlite")
        self.assertEqual(second.object("Generator", "Supply")["attributes"]["up_time_before"], 2)
        third = load_project(run / "steps/step-0003/inputs.sqlite")
        self.assertEqual(third.object("Generator", "Supply")["attributes"]["up_time_before"], 4)
        starts = pd.read_csv(run / "tables/generators__start_up.csv")
        self.assertAlmostEqual(starts["Supply"].sum(), 1)

    def test_second_step_failure_keeps_diagnostics_not_complete_solution(self):
        p = fixture()
        p.set_horizon("2027-01-01", 4, 60)
        p.profiles = [dict(component="Load", name="Demand", attribute="p_set", values=[5, 5, 500, 500])]
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "p.sqlite"
            save_project(p, db)
            run = prepare_run(db, horizon=specification(duration=4, duration_unit="hour",
                              step_size=2, step_unit="hour", step_count=2))
            with self.assertRaises(RuntimeError):
                execute_run(run)
            meta = json.loads((run / "metadata/run_config.json").read_text())
            self.assertEqual(meta["status"], "failed")
            self.assertEqual(meta["completed_steps"], 1)
            self.assertFalse((run / "metadata/catalog.json").exists())
            self.assertTrue((run / "steps/step-0002/highs.log").exists())

    def test_zero_output_steps_remain_complete_and_mps_export(self):
        p = fixture()
        p.set_horizon("2027-01-01", 4, 60)
        p.profiles = [dict(component="Load", name="Demand", attribute="p_set", values=[0, 0, 5, 5])]
        run, _, _ = self.run_case(p, specification(duration=4, duration_unit="hour",
                                  step_size=2, step_unit="hour", step_count=2), export="mps")
        frame = pd.read_csv(run / "tables/generators__p.csv")
        self.assertEqual(frame["Supply"].tolist(), [0, 0, 5, 5])
        self.assertEqual(len(list((run / "steps").glob("*/formulation/model.mps"))), 2)

    def test_tampered_schedule_fails_without_solving(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "p.sqlite"
            save_project(fixture(), db)
            run = prepare_run(db, horizon=specification())
            path = run / "metadata/run_config.json"
            value = json.loads(path.read_text())
            value["horizon"]["steps"][0]["stop"] += 1
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "inconsistent"):
                execute_run(run)
            self.assertFalse((run / "steps").exists())
            self.assertEqual(json.loads(path.read_text())["status"], "failed")

    def test_link_ramp_and_commitment_handoff(self):
        p = fixture()
        p.upsert("Bus", "City", {})
        p.object("Load", "Demand")["attributes"]["bus"] = "City"
        p.upsert("Link", "Connection", dict(
            bus0="Bus", bus1="City", p_nom=100, efficiency=1,
            committable=True, min_up_time=3, up_time_before=1,
            p_init=0, ramp_limit_up=0.01, marginal_cost=1))
        p.upsert("Generator", "City peaker", dict(bus="City", p_nom=100, marginal_cost=100))
        run, _, _ = self.run_case(p, specification(duration=4, duration_unit="hour",
                                  step_size=2, step_unit="hour", step_count=2))
        frame = pd.read_csv(run / "tables/links__p0.csv")
        self.assertEqual(frame["Connection"].round(6).tolist(), [1, 2, 3, 4])
        second = load_project(run / "steps/step-0002/inputs.sqlite")
        self.assertEqual(second.object("Link", "Connection")["attributes"]["up_time_before"], 3)

    def test_minimum_down_time_survives_restart_boundary(self):
        p = fixture()
        p.set_horizon("2027-01-01", 4, 60)
        p.object("Generator", "Supply")["attributes"].update(
            committable=True, min_down_time=3, up_time_before=0,
            down_time_before=1, stand_by_cost=1)
        p.upsert("Generator", "Peaker", dict(bus="Bus", p_nom=100, marginal_cost=100))
        run, _, _ = self.run_case(p, specification(duration=4, duration_unit="hour",
                                  step_size=1, step_unit="hour", step_count=4))
        # First two snapshots complete the remaining off-time (3 - 1).
        status = pd.read_csv(run / "tables/generators__status.csv")
        self.assertEqual(status["Supply"].round().tolist(), [0, 0, 1, 1])
        second = load_project(run / "steps/step-0002/inputs.sqlite")
        self.assertEqual(second.object("Generator", "Supply")["attributes"]["down_time_before"], 2)


if __name__ == "__main__":
    unittest.main()
