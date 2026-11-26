"""Small independently calculated acceptance cases for the linear formulation."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

from energy_gui.engine import execute_run, prepare_run
from energy_gui.project import Project
from energy_gui.storage import save_project


def base_project(hours=1):
    project = Project(name="Stage 2 acceptance case")
    project.set_horizon("2026-01-01", hours, 60)
    project.upsert("Carrier", "AC", {})
    project.upsert("Bus", "electric", {"v_nom": 220, "carrier": "AC"})
    return project


class NumericalAcceptanceTests(unittest.TestCase):
    def setUp(self):
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        self.temp = tempfile.TemporaryDirectory(prefix="stage2_numeric_", dir=preferred)
        self.directory = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def solve(self, project):
        self.assertEqual(project.validate(), [])
        database = self.directory / "project.sqlite"
        save_project(project, database)
        self.run = prepare_run(database, export_format="none")
        result = execute_run(self.run)
        checks = json.loads((self.run / "metadata/solution_checks.json").read_text())
        self.assertEqual(checks["status"], "passed")
        return result

    def table(self, name):
        return pd.read_csv(self.run / "tables" / name, index_col=0)

    def profile(self, project, kind, name, attribute, values):
        project.profiles.append({"component": kind, "name": name, "attribute": attribute, "values": values})

    def test_storage_unit_efficiency_and_energy_balance(self):
        project = base_project(2)
        project.upsert("Generator", "grid", {"bus": "electric", "p_nom": 100, "marginal_cost": 10})
        project.upsert("Load", "demand", {"bus": "electric"})
        project.upsert("StorageUnit", "battery", {"bus": "electric", "p_nom": 10, "max_hours": 1, "efficiency_store": 0.8, "efficiency_dispatch": 1})
        self.profile(project, "Generator", "grid", "marginal_cost", [10, 100])
        self.profile(project, "Load", "demand", "p_set", [0, 8])
        result = self.solve(project)
        self.assertAlmostEqual(result["objective"], 100, places=5)
        charge = self.table("storage_units__p_store.csv").battery.to_numpy()
        discharge = self.table("storage_units__p_dispatch.csv").battery.to_numpy()
        energy = self.table("storage_units__state_of_charge.csv").battery.to_numpy()
        np.testing.assert_allclose(charge, [10, 0], atol=1e-6)
        np.testing.assert_allclose(discharge, [0, 8], atol=1e-6)
        np.testing.assert_allclose(energy, np.cumsum(0.8*charge-discharge), atol=1e-6)
        self.assertTrue((energy <= 10+1e-6).all())

    def test_store_and_links_have_independent_power_energy_limits(self):
        project = base_project(2)
        project.upsert("Carrier", "battery", {})
        project.upsert("Bus", "reservoir", {"carrier": "battery"})
        project.upsert("Generator", "grid", {"bus": "electric", "p_nom": 100, "marginal_cost": 10})
        project.upsert("Load", "demand", {"bus": "electric"})
        project.upsert("Store", "tank", {"bus": "reservoir", "e_nom": 10})
        project.upsert("Link", "charge", {"bus0": "electric", "bus1": "reservoir", "p_nom": 10, "efficiency": 0.8})
        project.upsert("Link", "discharge", {"bus0": "reservoir", "bus1": "electric", "p_nom": 10})
        self.profile(project, "Generator", "grid", "marginal_cost", [10, 100])
        self.profile(project, "Load", "demand", "p_set", [0, 8])
        result = self.solve(project)
        self.assertAlmostEqual(result["objective"], 100, places=5)
        np.testing.assert_allclose(self.table("stores__e.csv").tank, [8, 0], atol=1e-6)
        np.testing.assert_allclose(self.table("links__p0.csv")["charge"], [10, 0], atol=1e-6)

    def test_hydro_inflow_is_power_weighted_into_energy(self):
        project = base_project()
        project.set_horizon("2026-01-01", 1, 30)
        project.upsert("Load", "demand", {"bus": "electric", "p_set": 10})
        project.upsert("StorageUnit", "hydro", {"bus": "electric", "p_nom": 10, "max_hours": 1, "inflow": 10, "marginal_cost": 1})
        result = self.solve(project)
        self.assertAlmostEqual(result["objective"], 5)
        self.assertAlmostEqual(self.table("storage_units__p.csv").hydro.iloc[0], 10)
        self.assertAlmostEqual(self.table("storage_units__state_of_charge.csv").hydro.iloc[0], 0)

    def test_transformer_congestion_with_different_voltage_levels(self):
        project = base_project()
        project.upsert("Bus", "city", {"v_nom": 110, "carrier": "AC"})
        project.upsert("Generator", "cheap", {"bus": "electric", "p_nom": 100, "marginal_cost": 20})
        project.upsert("Generator", "expensive", {"bus": "city", "p_nom": 100, "marginal_cost": 100})
        project.upsert("Load", "demand", {"bus": "city", "p_set": 60})
        project.upsert("Transformer", "T", {"bus0": "electric", "bus1": "city", "s_nom": 40, "x": 0.1, "r": 0.01})
        result = self.solve(project)
        self.assertAlmostEqual(result["objective"], 2800, places=5)
        self.assertAlmostEqual(self.table("transformers__p0.csv").T.iloc[0, 0], 40, places=5)

    def test_link_and_process_conversion_economics(self):
        for kind in ["Link", "Process"]:
            with self.subTest(kind=kind):
                project = base_project()
                project.upsert("Carrier", "fuel", {})
                project.upsert("Bus", "fuel_node", {"carrier": "fuel"})
                project.upsert("Generator", "supply", {"bus": "fuel_node", "p_nom": 100, "marginal_cost": 10})
                project.upsert("Load", "demand", {"bus": "electric", "p_set": 40})
                attrs = {"bus0": "fuel_node", "bus1": "electric", "p_nom": 100}
                attrs.update({"efficiency": 0.8} if kind == "Link" else {"rate0": -1, "rate1": 0.8})
                project.upsert(kind, "converter", attrs)
                result = self.solve(project)
                self.assertAlmostEqual(result["objective"], 500, places=5)
                self.assertAlmostEqual(self.table("generators__p.csv").supply.iloc[0], 50)

    def test_emissions_limit_changes_merit_order(self):
        project = base_project()
        project.upsert("Carrier", "coal", {"co2_emissions": 1})
        project.upsert("Carrier", "clean", {"co2_emissions": 0})
        project.upsert("Generator", "dirty", {"bus": "electric", "carrier": "coal", "p_nom": 100, "marginal_cost": 10})
        project.upsert("Generator", "clean", {"bus": "electric", "carrier": "clean", "p_nom": 100, "marginal_cost": 50})
        project.upsert("Load", "demand", {"bus": "electric", "p_set": 100})
        project.upsert("GlobalConstraint", "CO2", {"type": "primary_energy", "carrier_attribute": "co2_emissions", "sense": "<=", "constant": 40})
        result = self.solve(project)
        self.assertAlmostEqual(result["objective"], 3400, places=5)
        self.assertAlmostEqual(self.table("generators__p.csv").dirty.iloc[0], 40)

    def test_commitment_startup_and_minimum_output(self):
        project = base_project(3)
        project.upsert("Generator", "unit", {"bus": "electric", "p_nom": 50, "marginal_cost": 20, "committable": True,
                       "p_min_pu": 0.2, "start_up_cost": 100, "up_time_before": 0, "down_time_before": 1, "min_up_time": 1})
        project.upsert("Load", "demand", {"bus": "electric"})
        self.profile(project, "Load", "demand", "p_set", [0, 30, 0])
        result = self.solve(project)
        self.assertAlmostEqual(result["objective"], 700, places=5)
        np.testing.assert_allclose(self.table("generators__status.csv").unit, [0, 1, 0], atol=1e-6)


if __name__ == "__main__":
    unittest.main()
