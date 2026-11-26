"""Independent arithmetic and persisted frozen-run analytics; no solver or Qt."""

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from energy_gui.analytics import comparison_charts, summarize_query
from energy_gui.project import Project
from energy_gui.reporting import chart_svg, write_report
from energy_gui.results import ResultsRepository
from energy_gui.storage import save_project
from energy_gui.workspace import QueryTab


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        self.temp = tempfile.TemporaryDirectory(prefix="analytics_test_", dir=preferred)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        (self.directory / "tables").mkdir()
        self.project = Project()
        self.project.set_horizon("2026-01-01", 3, 30)
        self.project.upsert("Bus", "electricity", {"unit": "MW", "carrier": "electricity"})
        self.project.upsert("Carrier", "wind", {})
        for name in ["001", "B"]:
            self.project.upsert("Generator", name, {"bus": "electricity", "carrier": "wind", "p_nom": 100})
        self.project.advanced_inputs = dict(weights=[
            dict(generators=g, stores=s, objective=o)
            for g, s, o in [(0.5, 0.25, 0.1), (1.25, 0.5, 0.2), (2.0, 0.75, 0.3)]
        ])

    def repository(self, component="Generator", values=None, extra=None):
        if values is None:
            values = {"p": {"001": [2., -4., 8.], "B": [1., 2., 3.]}}
        save_project(self.project, self.directory / "inputs.sqlite")
        objects = [r for r in self.project.objects if r["component"] == component]
        static = pd.DataFrame([dict(name=r["name"], **r["attributes"]) for r in objects])
        if extra:
            for key, data in extra.items():
                static[key] = data
        static.to_csv(self.directory / "tables" / "static.csv", index=False)
        catalog = [dict(component=component, attribute="static properties", kind="static", file="static.csv")]
        for attribute, columns in values.items():
            table = pd.DataFrame(dict(snapshot=self.project.snapshots, **columns))
            if self.project.advanced_inputs.get("snapshot_periods"):
                table.insert(0, "period", self.project.advanced_inputs["snapshot_periods"])
            filename = attribute + ".csv"
            table.to_csv(self.directory / "tables" / filename, index=False)
            catalog.append(dict(component=component, attribute=attribute, kind="time series", file=filename))
        return ResultsRepository(self.directory, catalog)

    def tab(self, repo, component="Generator", objects=None, properties=None, start="", end=""):
        objects = ["001", "B"] if objects is None else objects
        properties = ["p"] if properties is None else properties
        criteria = dict(component=component, objects=objects, properties=properties, start=start, end=end)
        frame, specs, temporal = repo.query(**criteria)
        return QueryTab(
            title="<frozen & query>", run_path=str(self.directory), run_meta={"status": "succeeded"},
            criteria=criteria, frame=frame, specs=specs, temporal=temporal,
            description="original", pinned=True,
        )

    def metric(self, frame, group="001", metric="net_energy", period="", attribute="p"):
        rows = frame.loc[(frame["group"] == group) & (frame["metric"] == metric)
                         & (frame["period"] == period) & (frame["property"] == attribute)]
        self.assertEqual(len(rows), 1)
        return rows["value"].iloc[0]

    def test_fractional_weighted_energy_signed_parts_and_explicit_weight_columns(self):
        repo = self.repository()
        tab = self.tab(repo)
        frame, charts, description = summarize_query(tab, repo, "energy")
        # Independently: 2*.5 - 4*1.25 + 8*2 = 12 MWh, not a raw sum.
        self.assertEqual(self.metric(frame), 12)
        self.assertEqual(self.metric(frame, metric="positive_energy"), 17)
        self.assertEqual(self.metric(frame, metric="negative_energy"), -5)
        self.assertEqual(self.metric(frame, group="B"), 9)
        self.assertTrue((frame["snapshot_hours"] == 3.75).all())
        self.assertTrue((frame["weighted_hours"] == 3.75).all())
        self.assertEqual(charts[0]["unit"], "MWh")
        self.assertIn("not universal generation/consumption", description)
        self.assertIn("uncapped", description)
        for weighting, answer in [("stores", 4.5), ("objective", 1.8)]:
            with self.subTest(weighting=weighting):
                result, _, note = summarize_query(tab, repo, "energy", weighting=weighting)
                self.assertAlmostEqual(self.metric(result), answer)
                self.assertTrue((result["weighting"] == weighting).all())
                if weighting == "objective":
                    self.assertIn("not a claim of physical duration or cost", note)

    def test_default_interval_hours_and_range_use_executed_selection(self):
        self.project.advanced_inputs = {}
        repo = self.repository()
        tab = self.tab(repo, start=self.project.snapshots[1], end=self.project.snapshots[2])
        frame, _, _ = summarize_query(tab, repo, "energy")
        self.assertEqual(self.metric(frame), 2)
        self.assertTrue((frame["snapshot_hours"] == 1).all())
        # Current editable inputs are NOT the frozen repository or executed tab.
        self.project.duration_hours = 99
        self.project.objects[2]["attributes"]["carrier"] = "edited carrier"
        again, _, _ = summarize_query(tab, repo, "energy", group_by="carrier")
        self.assertEqual(again["group"].unique().tolist(), ["wind"])
        self.assertEqual(self.metric(again, group="wind"), 4.5)

    def test_multiperiod_years_not_discount_weights_or_joined_periods(self):
        self.project.advanced_inputs = {}
        self.project.set_horizon("2026-01-01", 4, 60)
        self.project.advanced_inputs = dict(
            weights=[dict(generators=x, stores=x, objective=x) for x in [0.5, 1, 2, 0.25]],
            periods=[dict(period=2030, years=2, objective=99), dict(period=2040, years=3, objective=0.01)],
            snapshot_periods=[2030, 2030, 2040, 2040],
        )
        repo = self.repository(values={"p": {"001": [2., 4., 10., -8.], "B": [1., 1., 1., 1.]}})
        tab = self.tab(repo)
        frame, charts, _ = summarize_query(tab, repo, "energy")
        self.assertEqual(self.metric(frame, period=2030), (2 * .5 + 4 * 1) * 2)
        self.assertEqual(self.metric(frame, period=2040), (10 * 2 - 8 * .25) * 3)
        self.assertEqual(frame["period"].unique().tolist(), [2030, 2040])
        self.assertEqual(len(charts), 2)
        grouped, _, _ = summarize_query(tab, repo, "energy", group_by="period")
        self.assertEqual(self.metric(grouped, group="2030", period=2030), 13)
        self.assertEqual(self.metric(grouped, group="2040", period=2040), 60.75)
        duration, curves, description = summarize_query(tab, repo, "duration")
        a = duration.loc[(duration["period"] == 2030) & (duration["group"] == "001")]
        self.assertEqual(a["duration_hours"].tolist(), [1, .5])
        self.assertEqual(a["cumulative_hours"].tolist(), [1, 1.5])
        self.assertTrue((a["period_years"] == 2).all())
        self.assertIn("excludes period years", description)
        self.assertEqual(len(curves), 2)

    def test_duration_descending_stable_ties_and_paired_weights_numeric_steps(self):
        repo = self.repository(values={"p": {"001": [5., 10., 5.], "B": [1., 2., 3.]}})
        frame, charts, _ = summarize_query(self.tab(repo), repo, "duration")
        a = frame.loc[frame["group"] == "001"]
        self.assertEqual(a["value"].tolist(), [10, 5, 5])
        self.assertEqual(a["snapshot"].tolist(), list(pd.to_datetime([
            self.project.snapshots[1], self.project.snapshots[0], self.project.snapshots[2],
        ])))
        self.assertEqual(a["duration_hours"].tolist(), [1.25, .5, 2])
        self.assertEqual(a["start_hours"].tolist(), [0, 1.25, 1.75])
        self.assertEqual(a["cumulative_hours"].tolist(), [1.25, 1.75, 3.75])
        self.assertEqual(a["rank"].tolist(), [1, 2, 3])
        self.assertEqual(charts[0]["series"][0]["values"], [10, 10, 5, 5, 5, 5])
        self.assertEqual(charts[0]["series"][0]["x_values"], [0, 1.25, 1.25, 1.75, 1.75, 3.75])
        self.assertIn("Cumulative", charts[0]["x_label"])
        self.assertIn("MUST", charts[0]["hint"])

    def test_carrier_and_component_energy_parts_do_not_hide_cancellation(self):
        repo = self.repository(values={"p": {"001": [2., -4., 8.], "B": [-2., 4., -8.]}})
        for group_by, name in [("carrier", "wind"), ("component", "Generator")]:
            with self.subTest(group_by=group_by):
                frame, _, _ = summarize_query(self.tab(repo), repo, "energy", group_by=group_by)
                self.assertEqual(self.metric(frame, group=name), 0)
                self.assertEqual(self.metric(frame, group=name, metric="positive_energy"), 22)
                self.assertEqual(self.metric(frame, group=name, metric="negative_energy"), -22)
                self.assertTrue((frame["weighted_hours"] == 3.75).all())
        curve, _, _ = summarize_query(self.tab(repo), repo, "duration", group_by="carrier")
        self.assertEqual(curve["value"].tolist(), [0, 0, 0])
        self.assertEqual(curve["duration_hours"].tolist(), [.5, 1.25, 2])

    def storage(self):
        for name in ["001", "B"]:
            self.project.upsert("Store", name, {"bus": "electricity", "carrier": "wind", "e_initial": 99})
        repo = self.repository("Store", values={"e": {"001": [1., 10., 3.], "B": [10., 1., 4.]}})
        return repo, self.tab(repo, component="Store", properties=["e"])

    def test_storage_arithmetic_statistics_not_integrated_or_sum_of_extrema(self):
        repo, tab = self.storage()
        frame, charts, description = summarize_query(tab, repo, "storage", group_by="carrier", weighting="stores")
        for metric, expected in [("initial", 11), ("last", 7), ("min", 7), ("max", 11), ("mean", 29 / 3)]:
            self.assertAlmostEqual(self.metric(frame, group="wind", metric=metric, attribute="e"), expected)
        self.assertTrue((frame["samples"] == 3).all())
        self.assertTrue((frame["unit"] == "MWh").all())
        self.assertTrue((frame["weighting"] == "none").all())
        self.assertNotIn("weighted_hours", frame)
        self.assertIn("first selected result", description)
        self.assertIn("No integration", description)
        self.assertEqual(len(charts[0]["series"]), 5)
        changed, _, _ = summarize_query(tab, repo, "storage", group_by="carrier", weighting="objective")
        pd.testing.assert_frame_equal(frame, changed)

    def test_storageunit_state_and_first_selected_result(self):
        self.project.upsert("StorageUnit", "battery", {"bus": "electricity", "carrier": "wind"})
        repo = self.repository("StorageUnit", {"state_of_charge": {"battery": [5., 2., 9.]}})
        tab = self.tab(repo, component="StorageUnit", objects=["battery"], properties=["state_of_charge"], start=self.project.snapshots[1])
        frame, _, _ = summarize_query(tab, repo, "storage")
        self.assertEqual(self.metric(frame, group="battery", metric="initial", attribute="state_of_charge"), 2)
        self.assertEqual(self.metric(frame, group="battery", metric="mean", attribute="state_of_charge"), 5.5)

    def test_storage_period_years_are_metadata_not_state_scaling(self):
        self.project.advanced_inputs.update(
            periods=[dict(period=2030, years=25, objective=.01)],
            snapshot_periods=[2030, 2030, 2030],
        )
        repo, tab = self.storage()
        frame, _, _ = summarize_query(tab, repo, "storage")
        self.assertEqual(self.metric(frame, period=2030, metric="initial", attribute="e"), 1)
        self.assertAlmostEqual(self.metric(frame, period=2030, metric="mean", attribute="e"), 14 / 3)
        self.assertTrue((frame["period_years"] == 25).all())

    def test_multiple_properties_separate_panels_never_sum_terminals(self):
        self.project.upsert("Link", "line", {"bus0": "electricity", "bus1": "electricity", "carrier": "wind"})
        repo = self.repository("Link", {"p0": {"line": [1., 2., 3.]}, "p1": {"line": [-.5, -1., -1.5]}})
        tab = self.tab(repo, component="Link", objects=["line"], properties=["p0", "p1"])
        frame, charts, _ = summarize_query(tab, repo, "energy")
        self.assertEqual(self.metric(frame, group="line", attribute="p0"), 9)
        self.assertEqual(self.metric(frame, group="line", attribute="p1"), -4.5)
        self.assertEqual(len(charts), 2)

    def test_static_repeated_nonpower_cost_state_and_bad_inputs_rejected(self):
        repo = self.repository(values={
            "p": {"001": [1., 2., 3.], "B": [1., 2., 3.]},
            "marginal_cost": {"001": [1., 2., 3.], "B": [1., 2., 3.]},
        })
        for properties in [["p_nom"], ["p", "p_nom"], ["marginal_cost"], ["p", "marginal_cost"]]:
            with self.subTest(properties=properties), self.assertRaises(ValueError):
                summarize_query(self.tab(repo, properties=properties), repo, "energy")
        for kwargs in [dict(mode="cost"), dict(mode="energy", weighting="marginal_cost"),
                       dict(mode="energy", group_by="bus"), dict(mode="energy", group_by="period"), dict(mode="storage")]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                summarize_query(self.tab(repo), repo, **kwargs)
        with self.assertRaises(ValueError):
            summarize_query(None, repo, "energy")
        repo, tab = self.storage()
        with self.assertRaises(ValueError):
            summarize_query(tab, repo, "energy")

    def test_nonfinite_nonnumeric_missing_duplicate_and_empty_results_rejected(self):
        repo = self.repository()
        for value in [np.nan, np.inf, -np.inf, True, "2", 1j]:
            with self.subTest(value=value):
                tab = self.tab(repo)
                tab.frame["p"] = tab.frame["p"].astype(object)
                tab.frame.loc[0, "p"] = value
                with self.assertRaises(ValueError):
                    summarize_query(tab, repo, "energy")
        for change in [lambda frame: frame.iloc[1:], lambda frame: pd.concat([frame, frame.iloc[[0]]]),
                       lambda frame: frame.assign(object="missing"), lambda frame: frame.iloc[:0]]:
            tab = self.tab(repo)
            tab.frame = change(tab.frame)
            with self.assertRaises(ValueError):
                summarize_query(tab, repo, "duration")
        with self.assertRaises(ValueError):
            summarize_query(self.tab(repo, start="2027-01-01", end="2027-01-02"), repo, "energy")
        tab = self.tab(repo)
        tab.run_path = str(self.directory / "different_run")
        with self.assertRaises(ValueError):
            summarize_query(tab, repo, "energy")

    def test_missing_exported_property_and_carrier_identity_rejected(self):
        repo = self.repository(values={"p": {"B": [1., 2., 3.]}})
        with self.assertRaises(ValueError):
            summarize_query(self.tab(repo), repo, "energy")
        self.project.object("Generator", "001")["attributes"].pop("carrier")
        repo = self.repository()
        with self.assertRaisesRegex(ValueError, "carrier identity"):
            summarize_query(self.tab(repo), repo, "energy", group_by="carrier")

    def test_effective_bus_units_not_only_nominal_schema_and_port_specific(self):
        self.project.upsert("Bus", "mass", {"unit": "t/h"})
        self.project.object("Generator", "B")["attributes"]["bus"] = "mass"
        repo = self.repository()
        with self.assertRaisesRegex(ValueError, "non-MW"):
            summarize_query(self.tab(repo), repo, "energy")
        self.project.upsert("Link", "conversion", {"bus0": "electricity", "bus1": "mass"})
        repo = self.repository("Link", {"p0": {"conversion": [1., 2., 3.]}, "p1": {"conversion": [4., 5., 6.]}})
        valid = self.tab(repo, component="Link", objects=["conversion"], properties=["p0"])
        self.assertEqual(self.metric(summarize_query(valid, repo, "energy")[0], group="conversion", attribute="p0"), 9)
        with self.assertRaisesRegex(ValueError, "non-MW"):
            summarize_query(self.tab(repo, component="Link", objects=["conversion"], properties=["p1"]), repo, "energy")

    def test_period_mismatch_missing_and_nonfinite_weights_rejected(self):
        self.project.advanced_inputs.update(
            periods=[dict(period=2030, years=2, objective=.01)], snapshot_periods=[2030, 2030, 2030],
        )
        repo = self.repository()
        for change in [lambda frame: frame.drop(columns="period"), lambda frame: frame.assign(period=2040)]:
            tab = self.tab(repo)
            tab.frame = change(tab.frame)
            with self.assertRaisesRegex(ValueError, "period"):
                summarize_query(tab, repo, "energy")
        for key, value in [("generators", 0), ("generators", np.inf), ("stores", True)]:
            repo = self.repository()
            tab = self.tab(repo)
            repo.project.advanced_inputs["weights"][0][key] = value
            with self.assertRaises(ValueError):
                summarize_query(tab, repo, "energy")

    def test_finite_inputs_that_overflow_integration_are_rejected(self):
        repo = self.repository(values={"p": {"001": [1e308, 1e308, 1e308], "B": [1., 2., 3.]}})
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            summarize_query(self.tab(repo), repo, "energy")

    def test_no_mutation_no_requery_or_solve_and_export_safety(self):
        repo = self.repository()
        tab = self.tab(repo)
        before_frame = tab.frame.copy(deep=True)
        before_tab = deepcopy({key: value for key, value in vars(tab).items() if key != "frame"})
        before_project = deepcopy(repo.project.to_dict())
        before_files = {path: path.read_bytes() for path in self.directory.rglob("*") if path.is_file()}
        cache = {key: value.copy(deep=True) for key, value in repo._cache.items()}
        with patch.object(repo, "query", side_effect=AssertionError("No requery")):
            frame, charts, description = summarize_query(tab, repo, "energy")
        pd.testing.assert_frame_equal(tab.frame, before_frame)
        self.assertEqual(before_tab, {key: value for key, value in vars(tab).items() if key != "frame"})
        self.assertEqual(repo.project.to_dict(), before_project)
        self.assertEqual({path: path.read_bytes() for path in before_files}, before_files)
        for key in cache:
            pd.testing.assert_frame_equal(repo._cache[key], cache[key])
        json.dumps(charts, allow_nan=False)
        self.assertIn("<svg", chart_svg(charts))
        frame.to_csv(self.directory / "computed.csv", index=False)
        exported = pd.read_csv(self.directory / "computed.csv", keep_default_na=False)
        self.assertEqual(len(exported), len(frame))
        report_tab = deepcopy(tab)
        report_tab.frame, report_tab.description = frame, description
        write_report(self.directory / "report.html", report_tab, charts, {})
        html = (self.directory / "report.html").read_text(encoding="utf-8")
        self.assertIn("&lt;frozen &amp; query&gt;", html)
        self.assertNotIn("<frozen & query>", html)

    def test_uncapped_duration_table_bounded_exact_step_preview(self):
        self.project.advanced_inputs = {}
        self.project.set_horizon("2026-01-01", 1100, 30)
        for number in range(7):
            self.project.upsert("Generator", f"G{number}", {"bus": "electricity", "carrier": "wind"})
        names = [f"G{number}" for number in range(7)]
        repo = self.repository(values={"p": {name: np.arange(1100, dtype=float) for name in names}})
        tab = self.tab(repo, objects=names)
        frame, charts, _ = summarize_query(tab, repo, "duration")
        self.assertEqual(len(frame), 7700)
        self.assertEqual(len(charts[0]["series"]), 6)
        for series in charts[0]["series"]:
            self.assertEqual(len(series["values"]), 1000)
            self.assertEqual(len(series["x_values"]), 1000)
            self.assertEqual(series["x_values"][-1], 250)
            self.assertEqual(series["values"][-1], 600)
        self.assertIn("First 500", charts[0]["hint"])
        json.dumps(charts, allow_nan=False)
        frame.to_csv(self.directory / "full_duration.csv", index=False)
        self.assertEqual(len(pd.read_csv(self.directory / "full_duration.csv")), 7700)

    def test_panels_are_report_bounded_but_full_table_keeps_all_periods_properties(self):
        self.project.advanced_inputs = {}
        self.project.set_horizon("2026-01-01", 16, 30)
        periods = list(range(2030, 2046))
        self.project.advanced_inputs = dict(
            periods=[dict(period=period, years=1, objective=1) for period in periods],
            snapshot_periods=periods,
        )
        self.project.upsert("Link", "001", {"bus0": "electricity", "bus1": "electricity"})
        self.project.upsert("Link", "B", {"bus0": "electricity", "bus1": "electricity"})
        repo = self.repository("Link", values={
            attribute: {"001": [1.] * 16, "B": [2.] * 16} for attribute in ["p0", "p1"]
        })
        tab = self.tab(repo, component="Link", properties=["p0", "p1"])
        frame, charts, _ = summarize_query(tab, repo, "energy")
        self.assertEqual(len(charts), 30)
        self.assertEqual(len(frame), 192)
        self.assertEqual(self.metric(frame, period=2045, attribute="p1"), .5)
        self.assertIn("<svg", chart_svg(charts))


class ComparisonChartTests(unittest.TestCase):
    def comparison(self, temporal=False, periods=False):
        rows = []
        for attribute, unit, scale in [("p", "MW", 1), ("marginal_cost", "INR/MWh", 10)]:
            for sample in range(4 if temporal else 1):
                for number, name in enumerate(["001", "<B>", "C"]):
                    left = scale * (number + sample)
                    row = dict(object=name, property=attribute, unit=unit, left=left, right=left-2,
                               delta_right_minus_left=-2)
                    if temporal:
                        row["snapshot"] = pd.Timestamp("2026-01-01") + pd.Timedelta(hours=sample)
                    if periods:
                        row["period"] = 2030 if sample < 2 else 2040
                    rows.append(row)
        return pd.DataFrame(rows)

    def test_static_separate_units_and_signed_right_minus_left(self):
        frame = self.comparison()
        frozen = frame.copy(deep=True)
        charts = comparison_charts(frame)
        self.assertEqual([chart["unit"] for chart in charts], ["MW", "INR/MWh"])
        self.assertEqual(charts[0]["labels"], ["001", "<B>", "C"])
        self.assertEqual(charts[0]["series"][2], dict(name="delta_right_minus_left", values=[-2., -2., -2.]))
        self.assertIn("&lt;B&gt;", chart_svg([{**charts[0], "title": "<B>"}]))
        json.dumps(charts, allow_nan=False)
        pd.testing.assert_frame_equal(frame, frozen)

    def test_temporal_periods_separate_and_six_series_limit(self):
        frame = self.comparison(temporal=True, periods=True)
        frozen = frame.copy(deep=True)
        charts = comparison_charts(frame)
        self.assertEqual(len(charts), 4)
        self.assertTrue(all(len(chart["series"]) == 6 for chart in charts))
        self.assertTrue(all(len(chart["labels"]) == 2 for chart in charts))
        self.assertEqual(charts[0]["series"][2]["values"], [-2., -2.])
        self.assertIn("2030", charts[0]["title"])
        self.assertIn("2040", charts[1]["title"])
        self.assertIn("6 series", charts[0]["hint"])
        pd.testing.assert_frame_equal(frame, frozen)

    def test_reject_nonfinite_mixedunits_bad_delta_missing_and_duplicate_identities(self):
        for column, value in [("left", np.nan), ("right", np.inf), ("delta_right_minus_left", 2), ("unit", None),
                              ("object", ""), ("left", True), ("unit", "MWh")]:
            with self.subTest(column=column, value=value):
                frame = self.comparison()
                if isinstance(value, bool):
                    frame[column] = frame[column].astype(object)
                elif column in {"left", "right", "delta_right_minus_left"}:
                    frame[column] = frame[column].astype(float)
                frame.loc[0, column] = value
                with self.assertRaises(ValueError):
                    comparison_charts(frame)
        frame = self.comparison(temporal=True, periods=True)
        for broken in [frame.iloc[1:], pd.concat([frame, frame.iloc[[0]]]), frame.assign(period=None)]:
            with self.assertRaises(ValueError):
                comparison_charts(broken)
        # Remove the same sample from EVERY property: the rectangular axes must
        # still be complete, not silently pivoted into NaN or intersected.
        missing = frame.loc[~((frame["object"] == "001") & (frame["snapshot"] == frame["snapshot"].iloc[0]))]
        with self.assertRaises(ValueError):
            comparison_charts(missing)
        missing_period_object = frame.loc[~((frame["object"] == "001") & (frame["period"] == 2040))]
        with self.assertRaises(ValueError):
            comparison_charts(missing_period_object)

    def test_static_preview_points_bounded_without_mutating_full_frame(self):
        frame = pd.DataFrame(dict(object=[str(i) for i in range(1200)], property="p", unit="MW",
                                  left=np.arange(1200), right=np.arange(1200)+1, delta_right_minus_left=1))
        charts = comparison_charts(frame)
        self.assertEqual(len(charts[0]["labels"]), 1000)
        self.assertTrue(all(len(series["values"]) == 1000 for series in charts[0]["series"]))
        self.assertEqual(len(frame), 1200)


if __name__ == "__main__":
    unittest.main()
