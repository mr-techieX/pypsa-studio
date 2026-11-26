"""Explicit query semantics with tiny persisted fixtures; no solver needed."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

import pandas as pd

from energy_gui.project import Project
from energy_gui.result_properties import is_result
from energy_gui.results import ResultsRepository, query_charts
from energy_gui.storage import save_project


class QueryTests(unittest.TestCase):
    def test_reviewed_dynamic_port_outputs_and_model_context(self):
        for kind in ("Link", "Process"):
            self.assertTrue(is_result(kind, "p2", "time series"))
            for attr in ("efficiency2", "rate2", "bus2", "p2_opt"):
                self.assertFalse(is_result(kind, attr, "time series"))
        self.assertFalse(is_result("Line", "x_pu_eff", "static"))
        self.assertFalse(is_result("Bus", "sub_network", "static"))
        self.assertTrue(is_result("Line", "s_nom_opt", "static"))
        self.assertFalse(is_result("Line", "s_nom_opt", "time series"))

    def setUp(self):
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        self.temp = tempfile.TemporaryDirectory(prefix="query_test_", dir=preferred)
        self.directory = Path(self.temp.name)
        tables = self.directory / "tables"
        tables.mkdir()
        project = Project()
        project.set_horizon("2026-01-01", 3, 60)
        project.upsert("Generator", "001", {"p_nom": 50})
        project.upsert("Generator", "B", {"p_nom": 80})
        save_project(project, self.directory / "inputs.sqlite")
        times = project.snapshots
        pd.DataFrame({"name": ["001", "B"], "p_nom": [50., 80.], "p_nom_opt": [55., 85.],
                      "carrier": ["coal", "solar"], "marginal_cost": [20., 10.],
                      "fake_opt": [1, 2]}).to_csv(tables / "static.csv", index=False)
        pd.DataFrame({"snapshot": times, "001": [10., 20., 30.], "B": [1., 2., 3.]}).to_csv(tables / "dispatch.csv", index=False)
        pd.DataFrame({"snapshot": times, "B": [3., 4., 5.]}).to_csv(tables / "cost.csv", index=False)
        pd.DataFrame({"snapshot": times, "B": [1., 1., 0.]}).to_csv(tables / "status.csv", index=False)
        self.catalog = [
            {"component": "Generator", "attribute": "static properties", "kind": "static", "file": "static.csv"},
            {"component": "Generator", "attribute": "p", "kind": "time series", "file": "dispatch.csv"},
            {"component": "Generator", "attribute": "marginal_cost", "kind": "time series", "file": "cost.csv"},
            {"component": "Generator", "attribute": "status", "kind": "time series", "file": "status.csv"},
        ]
        self.repo = ResultsRepository(self.directory, self.catalog)

    def tearDown(self):
        self.temp.cleanup()

    def test_multiple_objects_properties_and_inclusive_range(self):
        frame, specs, temporal = self.repo.query("Generator", ["001", "B"], ["p", "p_nom_opt"], "2026-01-01T01:00", "2026-01-01T02:00")
        self.assertEqual(frame.columns.tolist(), ["snapshot", "object", "p", "p_nom_opt"])
        self.assertEqual(len(frame), 4)
        self.assertEqual(frame.p.tolist(), [20, 2, 30, 3])
        self.assertEqual(frame.p_nom_opt.tolist(), [55, 85, 55, 85])
        self.assertTrue(temporal)
        self.assertEqual(len(query_charts(frame, specs, temporal)), 2)

    def test_static_only_has_no_spurious_snapshots_or_unselected_attributes(self):
        frame, specs, temporal = self.repo.query("Generator", ["001"], ["p_nom_opt"])
        self.assertEqual(frame.columns.tolist(), ["object", "p_nom_opt"])
        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.object.iloc[0], "001")
        self.assertFalse(temporal)
        charts = query_charts(frame, specs, temporal)
        self.assertEqual(len(charts), 1)
        self.assertEqual(charts[0]["kind"], "bar")

    def test_dynamic_input_only_available_in_report_mode(self):
        self.assertEqual({p["name"] for p in self.repo.describe()[0]["properties"]},
                         {"p", "p_nom_opt", "status"})
        for prop in ("marginal_cost", "p_nom", "carrier", "fake_opt"):
            with self.subTest(prop=prop), self.assertRaisesRegex(ValueError, prop):
                self.repo.query("Generator", ["001", "B"], ["p", prop])
        report = ResultsRepository(self.directory, self.catalog, output_only=False)
        frame, _, _ = report.query("Generator", ["001", "B"], ["marginal_cost"])
        self.assertEqual(frame.marginal_cost.tolist(), [20, 3, 20, 4, 20, 5])
        props = report.describe()[0]["properties"]
        self.assertEqual(sum(p["name"] == "marginal_cost" for p in props), 1)

    def test_unused_piecewise_defaults_hidden_but_real_zero_outputs_remain(self):
        table = self.directory / "tables" / "static.csv"
        static = pd.read_csv(table, dtype={"name": str})
        static["capital_cost_piecewise_opt"] = [0., 0.]
        static["p_nom_opt"] = [0., 0.]
        static.to_csv(table, index=False)
        before = table.read_bytes()
        repo = ResultsRepository(self.directory, self.catalog)
        properties = {spec["name"] for spec in repo.describe()[0]["properties"]}
        self.assertNotIn("capital_cost_piecewise_opt", properties)
        self.assertIn("p_nom_opt", properties)
        with self.assertRaisesRegex(ValueError, "unavailable.*capital_cost_piecewise_opt"):
            repo.query("Generator", ["001"], ["capital_cost_piecewise_opt"])
        self.assertEqual(table.read_bytes(), before)

        # Legacy exports can contain nondefault data even without curve metadata.
        static.loc[0, "capital_cost_piecewise_opt"] = 12.5
        static.to_csv(table, index=False)
        repo = ResultsRepository(self.directory, self.catalog)
        self.assertEqual(repo.query("Generator", ["001"], ["capital_cost_piecewise_opt"])[0].iloc[0, 1], 12.5)

        # With an explicit curve, zero is a possible model output, not a default
        # that can be discarded simply for being zero.
        static.loc[0, "capital_cost_piecewise_opt"] = 0.
        static.to_csv(table, index=False)
        project = repo.project
        project.advanced_inputs["piecewise"] = [
            dict(component="Generator", name="001", attribute="capital_cost", points=[[0., 0.], [50., 0.]])
        ]
        save_project(project, self.directory / "inputs.sqlite")
        repo = ResultsRepository(self.directory, self.catalog)
        self.assertEqual(repo.query("Generator", ["001"], ["capital_cost_piecewise_opt"])[0].iloc[0, 1], 0.)

    def test_zero_price_placeholder_requires_evidence_for_every_window(self):
        project = self.repo.project
        project.upsert("Bus", "B", {})
        save_project(project, self.directory / "inputs.sqlite")
        self.add_static_table("Bus", ["B"], "v_nom")
        table = self.directory / "tables" / "prices.csv"
        data = pd.DataFrame({"snapshot": project.snapshots, "B": [0., 0., 0.]})
        data.to_csv(table, index=False)
        self.catalog.append(dict(component="Bus", attribute="marginal_price", kind="time series", file="prices.csv"))
        config = self.directory / "run_config.json"
        config.write_text(json.dumps({"solver": "highs", "horizon": {}, "execution": "sequential; no look-ahead",
                                      "completed_steps": 2, "total_steps": 2}))
        logs = [self.directory / "steps" / f"step-{i:04d}" / "highs.log" for i in (1, 2)]
        for log in logs:
            log.parent.mkdir(parents=True)
        mip = "MIP model has 4 rows; 2 cols; 8 nonzeros; 1 integer variables (1 binary)\n"
        logs[0].write_text(mip)
        logs[1].write_text("LP model has 4 rows; 2 cols; 8 nonzeros\n")
        repo = ResultsRepository(self.directory, self.catalog)
        self.assertEqual(repo.query("Bus", ["B"], ["marginal_price"])[0].marginal_price.tolist(), [0.] * 3)
        logs[1].write_text(mip)
        repo = ResultsRepository(self.directory, self.catalog)
        self.assertNotIn("Bus", [c["name"] for c in repo.describe()])
        with self.assertRaisesRegex(ValueError, "marginal_price"):
            repo.query("Bus", ["B"], ["marginal_price"])
        data.loc[1, "B"] = 2.
        data.to_csv(table, index=False)
        repo = ResultsRepository(self.directory, self.catalog)
        self.assertEqual(repo.query("Bus", ["B"], ["marginal_price"])[0].marginal_price.tolist(), [0., 2., 0.])

    def test_missing_output_is_missing_not_an_invented_zero(self):
        frame, specs, temporal = self.repo.query("Generator", ["001", "B"], ["status"])
        self.assertTrue(frame.loc[frame.object == "001", "status"].isna().all())
        chart = query_charts(frame, specs, temporal)[0]
        self.assertEqual(chart["series"][0]["values"], [None, None, None])

    def test_empty_interval_returns_zero_rows(self):
        frame, specs, temporal = self.repo.query("Generator", ["B"], ["p"], "2026-01-02", "2026-01-03")
        self.assertTrue(frame.empty)
        self.assertEqual(query_charts(frame, specs, temporal), [])

    def test_bad_selections_and_reverse_range_are_rejected(self):
        cases = [
            ("Generator", [], ["p"], "", ""),
            ("Generator", ["001"], [], "", ""),
            ("Load", ["001"], ["p"], "", ""),
            ("Generator", ["missing"], ["p"], "", ""),
            ("Generator", ["001"], ["wrong"], "", ""),
            ("Generator", ["001"], ["p"], "2026-01-02", "2026-01-01"),
            ("Generator", ["001"], ["p"], "2026-01-01T00:00Z", ""),
        ]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.repo.query(*args)

    def test_catalogue_cannot_escape_run_tables(self):
        catalog = [{**self.catalog[0], "file": "../inputs.sqlite"}]
        with self.assertRaises(ValueError):
            ResultsRepository(self.directory, catalog)

    def test_mixed_units_use_separate_charts(self):
        frame, specs, temporal = self.repo.query("Generator", ["B"], ["p", "status"])
        charts = query_charts(frame, specs, temporal)
        self.assertEqual([c["title"] for c in charts], ["p", "status"])
        self.assertNotEqual(charts[0]["unit"], charts[1]["unit"])

    def test_time_series_are_read_only_when_queried(self):
        self.assertEqual(set(self.repo._cache), {"static.csv"})
        self.repo.query("Generator", ["B"], ["p"])
        self.assertEqual(set(self.repo._cache), {"static.csv", "dispatch.csv"})

    def add_static_table(self, component, names, attribute="value"):
        filename = component + ".csv"
        pd.DataFrame({"name": names, attribute: range(len(names))}).to_csv(self.directory / "tables" / filename, index=False)
        self.catalog.append({"component": component, "attribute": "static properties", "kind": "static", "file": filename})

    def test_only_defined_categories_and_objects_are_listed_or_queryable(self):
        # Simulate an older export containing built-in tables, derived topology,
        # and an automatically added object in an otherwise user-defined type.
        static = pd.read_csv(self.directory / "tables" / "static.csv", dtype={"name": str})
        extra = static.iloc[[0]].assign(name="automatic generator")
        pd.concat([static, extra]).to_csv(self.directory / "tables" / "static.csv", index=False)
        for component, names in [("LineType", ["standard line"]), ("TransformerType", ["standard transformer"]),
                                 ("SubNetwork", ["0"]), ("Carrier", ["001", "automatic carrier"])]:
            self.add_static_table(component, names)
        before = {path: path.read_bytes() for path in self.directory.rglob("*") if path.is_file()}
        repo = ResultsRepository(self.directory, self.catalog)
        self.assertEqual([(c["name"], c["objects"]) for c in repo.describe()], [("Generator", ["001", "B"])])
        self.assertEqual(set(repo._cache), {"static.csv"}, "Hidden catalogue tables should not be read.")
        for component, objects, properties in [
            ("Generator", ["automatic generator"], ["p_nom"]),
            ("Generator", ["001", "automatic generator"], ["p"]),
            ("LineType", ["standard line"], ["value"]),
            ("TransformerType", ["standard transformer"], ["value"]),
            ("SubNetwork", ["0"], ["value"]), ("Carrier", ["001"], ["value"]),
        ]:
            with self.subTest(component=component, objects=objects), self.assertRaises(ValueError):
                repo.query(component, objects, properties)
        self.assertEqual(repo.query("Generator", ["001"], ["p"])[0].p.tolist(), [10., 20., 30.])
        self.assertEqual({path: path.read_bytes() for path in before}, before, "Opening/querying old runs must not rewrite artifacts.")

    def test_input_only_categories_hidden_even_if_explicitly_defined(self):
        project = self.repo.project
        project.upsert("LineType", "custom line", {"x_per_length": 0.4})
        project.upsert("TransformerType", "custom transformer", {})
        project.upsert("Carrier", "001", {})
        project.upsert("Load", "no exported data", {})
        save_project(project, self.directory / "inputs.sqlite")
        self.add_static_table("LineType", ["standard line", "custom line"], "x_per_length")
        self.add_static_table("TransformerType", ["standard transformer", "custom transformer"], "s_nom")
        self.add_static_table("Carrier", ["automatic carrier", "001"], "co2_emissions")
        repo = ResultsRepository(self.directory, self.catalog)
        categories = {c["name"]: c["objects"] for c in repo.describe()}
        self.assertEqual(categories, {"Generator": ["001", "B"]})
        for component, name, attribute in [("LineType", "custom line", "x_per_length"),
                                           ("TransformerType", "custom transformer", "s_nom"),
                                           ("Carrier", "001", "co2_emissions")]:
            with self.assertRaisesRegex(ValueError, attribute):
                repo.query(component, [name], [attribute])

    def test_empty_inputs_and_categories_without_matching_export_rows_stay_empty(self):
        save_project(Project(), self.directory / "inputs.sqlite")
        repo = ResultsRepository(self.directory, self.catalog)
        self.assertEqual(repo.describe(), [])
        with self.assertRaises(ValueError):
            repo.query("Generator", ["001"], ["p"])
        project = Project()
        project.upsert("Generator", "not exported", {})
        save_project(project, self.directory / "inputs.sqlite")
        repo = ResultsRepository(self.directory, self.catalog)
        self.assertEqual(repo.describe(), [])
        with self.assertRaises(ValueError):
            repo.query("Generator", ["001"], ["p"])

    def test_hidden_category_filenames_are_still_validated(self):
        catalog = [{"component": "SubNetwork", "kind": "static", "file": "../inputs.sqlite"}]
        with self.assertRaises(ValueError):
            ResultsRepository(self.directory, catalog)

    def test_static_styles_preserve_values_units_and_categorical_labels(self):
        frame = pd.DataFrame({"object": ["001", "B", "C"], "value": [-2., float("nan"), 4.]})
        frozen = frame.copy(deep=True)
        specs = [{"name": "value", "unit": "currency/MWh"}]
        for kind in ["bar", "horizontal bar", "dot"]:
            with self.subTest(kind=kind):
                chart = query_charts(frame, specs, False, {"value": kind})[0]
                self.assertEqual(chart["options"], ["bar", "horizontal bar", "dot"])
                self.assertEqual(chart["labels"], ["001", "B", "C"])
                self.assertEqual(chart["series"][0]["values"], [-2., None, 4.])
                self.assertEqual(chart["unit"], "currency/MWh")
                self.assertIn("Static", chart["hint"])
        for invalid in ["line", "stacked area", "pie"]:
            with self.assertRaises(ValueError):
                query_charts(frame, specs, False, {"value": invalid})
        pd.testing.assert_frame_equal(frame, frozen)

    def test_dot_time_series_and_horizontal_preview_limit(self):
        frame, specs, temporal = self.repo.query("Generator", ["001", "B"], ["p"])
        chart = query_charts(frame, specs, temporal, {"p": "dot"})[0]
        self.assertEqual(chart["series"][0]["values"], [10., 20., 30.])
        self.assertEqual(chart["options"], ["line", "bar", "dot", "stacked area"])
        large = pd.DataFrame({"object": [str(i) for i in range(1100)], "value": range(1100)})
        chart = query_charts(large, [{"name": "value", "unit": "MW"}], False, {"value": "horizontal bar"})[0]
        self.assertEqual(len(chart["labels"]), 100)
        self.assertEqual(len(chart["series"][0]["values"]), 100)
        self.assertEqual(len(large), 1100)
