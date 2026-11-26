"""Independent calendar arithmetic, quantity rules and read-only presentation."""

import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from energy_gui.project import Project
from energy_gui.results import ResultsRepository, query_charts
from energy_gui.storage import save_project
from energy_gui.temporal import aggregate, options, listing, available_resolutions
from energy_gui.temporal_reports import generate_reports, validate_reports


def repository(directory, count=48, hours=1, start="2027-01-01"):
    p = Project(name="Calendar fixture")
    p.set_horizon(start, count, hours*60)
    p.upsert("Carrier", "gas", {})
    p.upsert("Bus", "bus", {})
    for name in ["A", "B"]:
        p.upsert("Generator", name, dict(bus="bus", p_nom=100, carrier="gas"))
    p.upsert("StorageUnit", "Battery", dict(bus="bus", p_nom=10))
    directory.mkdir(exist_ok=True)
    save_project(p, directory / "inputs.sqlite")
    tables = directory / "tables"
    tables.mkdir()
    pd.DataFrame(dict(name=["A", "B"], p_nom_opt=[100, 100])).to_csv(tables / "generators.csv", index=False)
    pd.DataFrame(dict(name=["Battery"], p_nom=[10])).to_csv(tables / "storage.csv", index=False)
    catalog = [
        dict(component="Generator", attribute="static properties", kind="static", file="generators.csv"),
        dict(component="StorageUnit", attribute="static properties", kind="static", file="storage.csv"),
    ]
    for component, attr, columns in [
        ("Generator", "p", dict(A=[float(i+1) for i in range(count)], B=[2.0]*(count))),
        ("Generator", "status", dict(A=[float(i%2) for i in range(count)], B=[1.0]*count)),
        ("Generator", "marginal_cost", dict(A=[10.0]*count, B=[20.0]*count)),
        ("Generator", "start_up", dict(A=[float(i%2) for i in range(count)], B=[0.0]*count)),
        ("StorageUnit", "state_of_charge", dict(Battery=[float(i+1) for i in range(count)])),
    ]:
        filename = component+"-"+attr+".csv"
        pd.DataFrame(dict(snapshot=p.snapshots, **columns)).to_csv(tables / filename, index=False)
        catalog.append(dict(component=component, attribute=attr, kind="time series", file=filename))
    (directory / "catalog.json").write_text(json.dumps(catalog))
    return ResultsRepository(directory, catalog)


class TemporalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.repo = repository(self.directory)

    def query(self, component="Generator", objects=None, properties=None, **settings):
        return self.repo.query(component, objects or ["A"], properties or ["p"],
                               aggregation=options({"resolution": "daily", **settings}))

    def test_daily_mean_energy_and_complete_coverage(self):
        frame, specs, _ = self.query()
        self.assertEqual(frame.p.tolist(), [12.5, 36.5])
        self.assertEqual(frame.coverage_hours.tolist(), [24, 24])
        self.assertEqual(frame.partial.tolist(), [False, False])
        energy, specs, _ = self.query(metric="energy")
        self.assertEqual(energy.p.tolist(), [300, 876])
        self.assertEqual(specs[0]["unit"], "MWh")
        native = self.repo.query("Generator", ["A"], ["p"])[0]
        self.assertEqual(energy.p.sum(), native.p.sum())

    def test_partial_range_and_calendar_buckets(self):
        for resolution in ["weekly", "monthly", "yearly"]:
            frame, _, _ = self.repo.query("Generator", ["A"], ["p"], "2027-01-01T12:00",
                aggregation=dict(resolution=resolution, metric="energy"))
            self.assertTrue(frame.partial.all())
            self.assertEqual(frame.coverage_hours.sum(), 36)
            self.assertEqual(frame.p.sum(), sum(range(13, 49)))

    def test_monday_and_sunday_week_anchors(self):
        monday = self.query(resolution="weekly")[0]
        sunday = self.query(resolution="weekly", week_start="Sunday")[0]
        self.assertEqual(monday.snapshot.iloc[0], pd.Timestamp("2026-12-28"))
        self.assertEqual(sunday.snapshot.iloc[0], pd.Timestamp("2026-12-27"))

    def test_calendar_leap_year_and_interval_overlap(self):
        p = self.repo.project
        p.snapshots = ["2028-02-28T23:00:00"]
        p.duration_hours = 2
        frame = pd.DataFrame(dict(snapshot=pd.to_datetime(p.snapshots), object=["A"], p=[10.0]))
        specs = [dict(name="p", unit="MW", kind="time series")]
        values, _ = aggregate(p, "Generator", frame, specs, dict(resolution="daily", metric="energy"))
        self.assertEqual(values.p.tolist(), [10, 10])
        self.assertEqual(values.coverage_hours.tolist(), [1, 1])
        self.assertEqual(values.snapshot.iloc[-1], pd.Timestamp("2028-02-29"))

    def test_storage_end_extrema_and_no_state_integration(self):
        frame, specs, _ = self.query("StorageUnit", ["Battery"], ["state_of_charge"])
        self.assertEqual(frame.state_of_charge.tolist(), [24, 48])
        self.assertEqual(specs[0]["metric"], "end")
        self.assertEqual(self.query("StorageUnit", ["Battery"], ["state_of_charge"], metric="min")[0].state_of_charge.tolist(), [1, 25])
        with self.assertRaisesRegex(ValueError, "invalid"):
            self.query("StorageUnit", ["Battery"], ["state_of_charge"], metric="energy")

    def test_no_interpolation_of_endpoint_states_across_buckets(self):
        p = self.repo.project
        p.snapshots = ["2027-01-01T23:00:00"]
        p.duration_hours = 2
        frame = pd.DataFrame(dict(snapshot=pd.to_datetime(p.snapshots), object=["Battery"], state_of_charge=[10.0]))
        with self.assertRaisesRegex(ValueError, "cross"):
            aggregate(p, "StorageUnit", frame, [dict(name="state_of_charge", unit="MWh", kind="time series")], dict(resolution="daily"))

    def test_status_fraction_hours_and_event_counts(self):
        self.assertEqual(self.query(properties=["status"])[0].status.tolist(), [0.5, 0.5])
        self.assertEqual(self.query(properties=["status"], metric="operating_hours")[0].status.tolist(), [12, 12])
        self.assertEqual(self.query(properties=["start_up"])[0].start_up.tolist(), [12, 12])
        with self.assertRaises(ValueError):
            self.query(properties=["status"], metric="energy")

    def test_price_is_duration_mean_not_effective_price(self):
        report = ResultsRepository(self.directory, self.repo.catalog, output_only=False)
        args = ("Generator", ["A"], ["marginal_cost"])
        frame, specs, _ = report.query(*args, aggregation=dict(resolution="daily"))
        self.assertEqual(frame.marginal_cost.tolist(), [10, 10])
        self.assertEqual(specs[0]["metric"], "mean")
        with self.assertRaises(ValueError):
            report.query(*args, aggregation=dict(resolution="daily", metric="total"))

    def test_synchronous_grouping_before_temporal_extrema(self):
        frame, _, _ = self.query(objects=["A", "B"], group_by="carrier", metric="max")
        self.assertEqual(frame.object.tolist(), ["gas", "gas"])
        self.assertEqual(frame.p.tolist(), [26, 50])
        report = ResultsRepository(self.directory, self.repo.catalog, output_only=False)
        with self.assertRaisesRegex(ValueError, "additive"):
            report.query("Generator", ["A", "B"], ["marginal_cost"],
                         aggregation=dict(resolution="daily", group_by="component"))

    def test_finer_resolution_and_representative_weights_rejected(self):
        p = self.repo.project
        p.duration_hours = 2
        p.snapshots = [t.isoformat() for t in pd.date_range("2027-01-01", periods=48, freq="2h")]
        self.assertNotIn("hourly", available_resolutions(p))
        with self.assertRaisesRegex(ValueError, "finer"):
            validate_reports(p, ["hourly"])
        p.advanced_inputs["weights"] = [dict(objective=2, stores=2, generators=3)]*48
        self.assertEqual(available_resolutions(p), ["native"])
        with self.assertRaisesRegex(ValueError, "weights"):
            validate_reports(p, ["daily"])

    def test_missing_values_and_unknown_rules_rejected(self):
        path = self.directory / "tables/Generator-p.csv"
        data = pd.read_csv(path)
        data.loc[0, "A"] = float("nan")
        data.to_csv(path, index=False)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.query()
        with self.assertRaisesRegex(ValueError, "static"):
            self.query(properties=["p_nom_opt"])

    def test_listing_modes_preserve_values_and_static_once(self):
        frame, specs, temporal = self.repo.query("Generator", ["A", "B"], ["p", "p_nom_opt"])
        for order in ["snapshot", "object", "property"]:
            result = listing(frame, specs, temporal, order, "long")
            self.assertEqual(len(result[result.property == "p"]), 96)
            self.assertEqual(len(result[result.property == "p_nom_opt"]), 2)
            self.assertEqual(result[result.property == "p"].value.sum(), frame.p.sum())
        wide = listing(frame, specs, temporal)
        self.assertEqual(wide.p_nom_opt.notna().sum(), 2)
        self.assertEqual(len(frame), 96)

    def test_report_and_query_engine_agree(self):
        generate_reports(self.directory, dict(report_resolutions=["native", "daily", "monthly"]))
        path = self.directory / "reports/daily/Generator__p__energy.csv"
        saved = pd.read_csv(path)
        queried = self.query(objects=["A", "B"], metric="energy")[0]
        self.assertEqual(saved.p.tolist(), queried.p.tolist())
        manifest = json.loads((self.directory / "reports/manifest.json").read_text())
        self.assertEqual(manifest["version"], 1)
        self.assertTrue((self.directory / "reports/daily/Generator__marginal_cost__auto.csv").is_file())
        self.assertTrue((self.directory / "reports/index.html").exists())

    def test_chart_range_reaches_beyond_old_thousand_point_limit(self):
        dates = pd.date_range("2027-01-01", periods=2000, freq="h")
        frame = pd.DataFrame(dict(snapshot=dates, object=["A"]*2000, p=range(2000)))
        specs = [dict(name="p", unit="MW", kind="time series")]
        full = query_charts(frame, specs, True)[0]
        self.assertEqual(full["series"][0]["values"][-1], 1999)
        zoom = query_charts(frame, specs, True, viewport=[1500, 1510])[0]
        self.assertEqual(zoom["series"][0]["values"], list(range(1500, 1511)))
        self.assertEqual(len(frame), 2000)


if __name__ == "__main__":
    unittest.main()
