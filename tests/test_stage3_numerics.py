"""A larger synthetic acceptance case; not realistic-grid certification."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

from energy_gui.benchmarks import stage3_grid
from energy_gui.engine import execute_run, prepare_run
from energy_gui.results import ResultsRepository
from energy_gui.sheet import ObjectSheet
from energy_gui.storage import save_project
from energy_gui.network_view import frozen_overlay


class GridAcceptanceTests(unittest.TestCase):
    def test_ring_transformer_heat_and_storage_balance_objective_and_scoped_results(self):
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        with tempfile.TemporaryDirectory(prefix="stage3_grid_", dir=preferred) as tmp:
            project = stage3_grid()
            # Exercise the bulk-edit -> frozen input -> solve -> query path,
            # including preservation of the imported time profiles.
            sheet = ObjectSheet(lambda: True)
            sheet.load(project, "Generator")
            self.assertTrue(sheet.pasteTsv("name\tp_nom\nGrid\t160\n"))
            edited = sheet.validate_changes(project)
            self.assertIsNotNone(edited, sheet.validationReport)
            self.assertEqual(edited.profiles, project.profiles)
            project = edited
            self.assertEqual(project.validate(), [])
            path = Path(tmp) / "project.sqlite"
            save_project(project, path)
            run = prepare_run(path, export_format="none")
            result = execute_run(run)
            self.assertEqual(json.loads((run / "metadata/solution_checks.json").read_text())["status"], "passed")

            def table(kind, attribute):
                return pd.read_csv(run / "tables" / f"{kind}__{attribute}.csv", index_col=0)

            balance = {o["name"]: np.zeros(24) for o in project.objects if o["component"] == "Bus"}
            for component, list_name, sign in [("Generator", "generators", 1), ("Load", "loads", -1), ("StorageUnit", "storage_units", 1)]:
                values = table(list_name, "p")
                for record in [o for o in project.objects if o["component"] == component]:
                    balance[record["attributes"]["bus"]] += sign*values[record["name"]].to_numpy()
            for component, list_name in [("Line", "lines"), ("Transformer", "transformers"), ("Link", "links")]:
                for port in [0, 1]:
                    values = table(list_name, f"p{port}")
                    for record in [o for o in project.objects if o["component"] == component]:
                        balance[record["attributes"][f"bus{port}"]] -= values[record["name"]].to_numpy()
            for bus, residual in balance.items():
                np.testing.assert_allclose(residual, 0, atol=1e-6, err_msg=bus)

            charge = table("storage_units", "p_store").Battery.to_numpy()
            dispatch = table("storage_units", "p_dispatch").Battery.to_numpy()
            energy = table("storage_units", "state_of_charge").Battery.to_numpy()
            self.assertGreater(charge.sum(), 1)
            self.assertGreater(dispatch.sum(), 1)
            np.testing.assert_allclose(energy-np.roll(energy, 1), 0.9*charge-dispatch/0.9, atol=1e-6)
            self.assertLessEqual(np.abs(table("transformers", "p0")["T"].to_numpy()).max(), 20+1e-6)
            np.testing.assert_allclose(table("links", "p0")["Heat pump"], 3, atol=1e-6)
            np.testing.assert_allclose(table("links", "p1")["Heat pump"], -9, atol=1e-6)
            generators = table("generators", "p")
            prices = np.array([10]*8+[60]*8+[100]*8)
            independent_cost = np.dot(generators.Grid, prices)+150*generators.Backup.sum()
            self.assertAlmostEqual(result["objective"], independent_cost, places=4)
            repo = ResultsRepository(run, json.loads((run / "metadata/catalog.json").read_text()))
            expected = {(o["component"], o["name"]) for o in project.objects if o["component"] != "Carrier"}
            self.assertEqual({(c["name"], n) for c in repo.describe() for n in c["objects"]}, expected)
            self.assertEqual(len(repo.query("Bus", list(balance), ["marginal_price"])[0]), 14*24)
            # Overlay values are read from the same saved run, port by port;
            # do not assume converter efficiency=1 or lossless port equality.
            overlay = frozen_overlay(repo, project.snapshots[4])
            for wire in overlay["wires"]:
                if wire.get("attribute") and wire["flow"] is not None:
                    kind, name = json.loads(wire["a"])
                    list_name = {"Line": "lines", "Transformer": "transformers", "Link": "links"}[kind]
                    self.assertAlmostEqual(wire["flow"], table(list_name, wire["attribute"])[name].iloc[4])
