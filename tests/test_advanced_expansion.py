"""Stage 3N native-curve and static-control acceptance (no Qt required).

These small references check independent arithmetic, not grid certification.
All inputs travel through the existing project/SQLite/frozen-run path.
"""

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
import pypsa

from energy_gui.advanced import (
    advanced_modeling_controls,
    checked_advanced,
    native_piecewise_options,
    piecewise_capabilities,
)
from energy_gui.engine import build_network, execute_run, prepare_run
from energy_gui.project import Project
from energy_gui.schema import attribute_spec
from energy_gui.storage import load_project, save_project


def base_project(snapshots=1, two_buses=False):
    project = Project(name="Stage 3N arithmetic references", currency="USD")
    project.set_horizon("2030-01-01", snapshots, 60)
    project.upsert("Carrier", "AC", {})
    project.upsert("Bus", "A", dict(carrier="AC", v_nom=220))
    if two_buses:
        project.upsert("Bus", "B", dict(carrier="AC", v_nom=220))
    return project


def add_profile(project, component, name, attribute, values):
    project.profiles.append(dict(component=component, name=name, attribute=attribute, values=values))


def curve(component, name, attribute, points, **extra):
    return dict(component=component, name=name, attribute=attribute, points=points, **extra)


def capital_project(component="Generator"):
    project = base_project(two_buses=component != "Generator")
    if component == "Generator":
        attrs = dict(bus="A", p_nom=0, p_nom_extendable=True, p_nom_max=100,
                     p_nom_min=0, marginal_cost=3, carrier="AC")
        demand_bus = "A"
    else:
        project.upsert("Generator", "supply", dict(bus="A", p_nom=200, marginal_cost=3, carrier="AC"))
        attrs = dict(bus0="A", bus1="B", carrier="AC")
        if component == "Line":
            attrs.update(s_nom=0, s_nom_extendable=True, s_nom_min=0, s_nom_max=100,
                         x=0.2, r=0.01, s_max_pu=1)
        else:
            attrs.update(p_nom=0, p_nom_extendable=True, p_nom_min=0, p_nom_max=100, efficiency=1)
        demand_bus = "B"
    project.upsert(component, "asset", attrs)
    project.upsert("Load", "demand", dict(bus=demand_bus, p_set=75))
    project.advanced_inputs = dict(piecewise=[curve(component, "asset", "capital_cost",
                                                   [[0, 0], [50, 10], [100, 30]])])
    return project


def efficiency_project(snapshots=1):
    project = base_project(snapshots, two_buses=True)
    project.upsert("Generator", "supply", dict(bus="A", p_nom=200, marginal_cost=10, carrier="AC"))
    project.upsert("Link", "converter", dict(bus0="A", bus1="B", p_nom=100,
                                            efficiency=0.99, marginal_cost=2, carrier="AC"))
    project.upsert("Load", "demand", dict(bus="B", p_set=50))
    # Native power points are (input, output) = (0,0), (50,40), (100,60).
    project.advanced_inputs = dict(piecewise=[curve("Link", "converter", "efficiency",
                                                   [[0, 0], [0.5, 0.8], [1, 0.6]])])
    return project


class AdvancedCurveValidationTests(unittest.TestCase):
    def assert_invalid(self, project, pattern=None):
        before = deepcopy(project.to_dict())
        with self.assertRaises(ValueError) as caught:
            checked_advanced(project, project.advanced_inputs)
        if pattern:
            self.assertIn(pattern, str(caught.exception))
        # Validation must not normalise live inputs in place.
        self.assertEqual(project.to_dict(), before)
        self.assertTrue(project.validate())
        with self.assertRaises(ValueError):
            build_network(project)

    def test_supported_capabilities_are_explicit_and_match_native_schema(self):
        from pypsa.constants import piecewise_schema
        supported = piecewise_capabilities()
        self.assertEqual({(c["component"], c["attribute"]) for c in supported}, {
            ("Generator", "marginal_cost"), ("Generator", "capital_cost"),
            ("Line", "capital_cost"), ("Link", "capital_cost"), ("Link", "efficiency"),
        })
        for item in supported:
            native = piecewise_schema(item["component"], item["attribute"])
            self.assertEqual(item["x_attribute"], native.x)
            self.assertEqual(item["extendable"], bool(native.allow_extendable))
        line = next(c for c in supported if c["component"] == "Line")
        self.assertIn("MVA", line["x_unit"])
        self.assertIn("MW", line["x_unit"])
        conversion = next(c for c in supported if c["attribute"] == "efficiency")
        self.assertIn("NOT efficiency", conversion["semantics"])

    def test_new_curves_preserve_every_scalar_on_the_single_initial_add(self):
        for project in [capital_project(k) for k in ("Generator", "Line", "Link")] + [efficiency_project()]:
            c = project.advanced_inputs["piecewise"][0]
            attrs = project.object(c["component"], c["name"])["attributes"]
            attrs.update(build_year=2030, lifetime=25, capital_cost=999)
            if c["component"] == "Line":
                attrs.update(length=12, terrain_factor=1.2)
            else:
                attrs.update(p_min_pu=0.1, p_max_pu=0.95, ramp_limit_up=0.4)
            with self.subTest(component=c["component"], attribute=c["attribute"]):
                original_add = pypsa.Network.add
                calls = []

                def capture(network, component, name, **kwargs):
                    calls.append((component, name, deepcopy(kwargs)))
                    return original_add(network, component, name, **kwargs)

                with patch.object(pypsa.Network, "add", capture):
                    network = build_network(project)
                insertion = [kw for kind, name, kw in calls if (kind, name) == (c["component"], c["name"])]
                self.assertEqual(len(insertion), 1)
                expected = {**attrs, c["attribute"]: dict(c["points"])}
                self.assertEqual(insertion[0], expected)
                static = network.components[c["component"]].static.loc[c["name"]]
                for name, value in attrs.items():
                    if name != c["attribute"]:
                        self.assertEqual(static[name], value, name)
                stored = network.components[c["component"]].piecewise[c["attribute"]][c["name"]]
                self.assertEqual(stored.iloc[:, 0].tolist(), [p[0] for p in c["points"]])
                self.assertEqual(stored[c["attribute"]].tolist(), [p[1] for p in c["points"]])

    def test_missing_link_remains_invalid_without_changing_the_old_fixture(self):
        project = base_project()
        project.advanced_inputs = dict(piecewise=[curve("Link", "L", "efficiency", [[0, 0], [1, 1]])])
        self.assert_invalid(project, "existing")

    def test_unsupported_component_attribute_pairs_and_duplicate_curves(self):
        project = base_project(two_buses=True)
        for kind, name, attrs in [
            ("StorageUnit", "asset", dict(bus="A", p_nom=10)),
            ("Store", "asset", dict(bus="A", e_nom=10)),
            ("Transformer", "asset", dict(bus0="A", bus1="B", s_nom=10, x=0.1)),
            ("Process", "asset", dict(bus0="A", bus1="B", p_nom=10)),
            ("Generator", "asset", dict(bus="A", p_nom=10)),
            ("Link", "asset", dict(bus0="A", bus1="B", p_nom=10)),
        ]:
            project.upsert(kind, name, attrs)
        for kind, attribute in [("StorageUnit", "capital_cost"), ("Store", "marginal_cost"),
                                ("Transformer", "capital_cost"), ("Process", "rate1"),
                                ("Generator", "efficiency"), ("Link", "marginal_cost"),
                                ("Link", "efficiency2"), ("Line", "marginal_cost")]:
            with self.subTest(kind=kind, attribute=attribute):
                project.advanced_inputs = dict(piecewise=[curve(kind, "asset", attribute, [[0, 0], [1, 1]])])
                self.assert_invalid(project, "Supported curves")
        project = capital_project()
        project.advanced_inputs["piecewise"] *= 2
        self.assert_invalid(project, "unique")

    def test_malformed_nonfinite_negative_nonconvex_and_wrong_origin_cost_points(self):
        cases = [None, {}, [], [[0, 0]], [[0, 0], [100, True]],
                 [[0, 0], [100, float("inf")]], [[0, 0], [float("inf"), 2]],
                 [[0, 0], [100, float("nan")]], [[0, 0], [float("nan"), 2]],
                 [[0, 0], [100, "20"]], [[0, 0], [100]],
                 [[0, 1], [100, 2]], [[1, 0], [100, 2]],
                 [[0, 0], [-1, 1], [100, 2]], [[0, 0], [0, 1], [100, 2]],
                 [[0, 0], [50, -1], [100, 2]], [[0, 0], [50, 30], [100, 10]]]
        for points in cases:
            with self.subTest(points=points):
                project = capital_project()
                project.advanced_inputs["piecewise"][0]["points"] = points
                self.assert_invalid(project)
        project = capital_project()
        project.advanced_inputs["piecewise"][0]["points"] = [[0, 0], [10**20, 2], [10**20+1, 3]]
        self.assert_invalid(project, "strictly increasing")

    def test_capital_capacity_domain_and_native_pricing_restrictions(self):
        for component in ("Generator", "Line", "Link"):
            nominal = "s_nom" if component == "Line" else "p_nom"
            cases = [{nominal + "_extendable": False}, {nominal + "_max": "inf"},
                     {nominal: -1}, {nominal: "inf"},
                     {nominal + "_max": 101}, {nominal + "_max": 0},
                     {nominal + "_min": -1}, {nominal + "_min": 101},
                     {nominal + "_set": 101}, {nominal + "_set": -1},
                     {"overnight_cost": 0}, {"overnight_cost": 100}, {"fom_cost": 2}]
            for change in cases:
                with self.subTest(component=component, change=change):
                    project = capital_project(component)
                    project.object(component, "asset")["attributes"].update(change)
                    self.assert_invalid(project)
            # A tighter declared bound need not duplicate the final breakpoint;
            # all feasible capacities still lie in the finite curve domain.
            project = capital_project(component)
            project.object(component, "asset")["attributes"][nominal + "_max"] = 90
            self.assertEqual(project.validate(), [])

    def test_native_options_fail_closed_and_remain_exactly_scoped(self):
        # Original four-field curves use PyPSA defaults: do not rename old
        # constraint blocks by adding gratuitous name-scoped overrides.
        self.assertEqual(native_piecewise_options(capital_project()), [])
        for options in [{"method": "sos2"}, {"method": "incremental"}, {"method": "invalid"},
                        {"method": True}, {"method": []}, {"sign": "="}, {"sign": "<="},
                        {"cumulative_attr": False}, {"name": "other"}, {"component": "Link"}, []]:
            with self.subTest(options=options):
                project = capital_project()
                project.advanced_inputs["piecewise"][0]["options"] = options
                self.assert_invalid(project)
        project = capital_project()
        project.advanced_inputs["piecewise"][0]["options"] = dict(method="lp", sign=">=")
        self.assertEqual(native_piecewise_options(project), [dict(
            component="Generator", name="asset", attribute="capital_cost", method="lp", sign=">=")])
        for options in [{"method": "lp"}, {"method": "sos2"}, {"sign": ">="}]:
            with self.subTest(options=options):
                project = efficiency_project()
                project.advanced_inputs["piecewise"][0]["options"] = options
                self.assert_invalid(project)
        project = efficiency_project()
        project.advanced_inputs["piecewise"][0]["options"] = dict(method="incremental", sign="=")
        self.assertEqual(native_piecewise_options(project)[0]["method"], "incremental")

    def test_conflicting_time_profiles_are_rejected_for_every_supported_curve(self):
        projects = [capital_project(k) for k in ("Generator", "Line", "Link")] + [efficiency_project()]
        dispatch = base_project()
        dispatch.upsert("Generator", "asset", dict(bus="A", p_nom=100))
        dispatch.advanced_inputs = dict(piecewise=[curve("Generator", "asset", "marginal_cost", [[0, 0], [1, 2]])])
        projects.append(dispatch)
        for project in projects:
            c = project.advanced_inputs["piecewise"][0]
            with self.subTest(component=c["component"], attribute=c["attribute"]):
                add_profile(project, c["component"], c["name"], c["attribute"], [0.5])
                self.assert_invalid(project, "time profile")

    def test_efficiency_limits_negative_flow_extra_ports_and_delays(self):
        changes = [dict(p_nom=0), dict(p_nom=-1), dict(p_nom="inf"), dict(p_nom_extendable=True),
                   dict(committable=True), dict(p_min_pu=-0.1), dict(p_max_pu=1.1),
                   dict(p_min_pu=0.9, p_max_pu=0.8), dict(p_set=-1), dict(p_set=101),
                   dict(bus2="A", efficiency2=0.1), dict(delay=1), dict(bus1="A")]
        for change in changes:
            with self.subTest(change=change):
                project = efficiency_project()
                project.object("Link", "converter")["attributes"].update(change)
                self.assert_invalid(project)
        for points in [[[0, 0], [0.9, 0.6]], [[0, 0], [1, -0.6]], [[0, 0], [1, 0]],
                       [[0, 0], [1, 1.1]], [[0, 0], [0.5, 0.9], [1, 0.4]],
                       [[0, 0.8], [1, 0.8]]]:
            with self.subTest(points=points):
                project = efficiency_project()
                project.advanced_inputs["piecewise"][0]["points"] = points
                self.assert_invalid(project)
        for attribute, value in [("p_min_pu", -0.01), ("p_max_pu", 1.01), ("p_set", -1)]:
            with self.subTest(attribute=attribute):
                project = efficiency_project()
                add_profile(project, "Link", "converter", attribute, [value])
                self.assert_invalid(project)
        # An overriding legal profile does not make an out-of-domain static
        # bound safe for future snapshots or edits; reject both representations.
        project = efficiency_project()
        project.object("Link", "converter")["attributes"]["p_min_pu"] = -0.1
        add_profile(project, "Link", "converter", "p_min_pu", [0])
        self.assert_invalid(project)

    def test_generator_dispatch_curve_still_rejects_negative_nonconvex_and_commitment(self):
        for change in [dict(p_nom_extendable=True), dict(committable=True), dict(p_min_pu=-0.1),
                       dict(p_max_pu=1.01), dict(p_nom=0)]:
            project = base_project()
            project.upsert("Generator", "asset", dict(bus="A", p_nom=100, **{
                k: v for k, v in change.items() if k != "p_nom"}))
            project.object("Generator", "asset")["attributes"].update(change)
            project.advanced_inputs = dict(piecewise=[curve("Generator", "asset", "marginal_cost", [[0, 0], [1, 2]])])
            with self.subTest(change=change):
                self.assert_invalid(project)
        for points in [[[0, 0], [0.5, -1], [1, 20]], [[0, 0], [0.5, 30], [1, 20]]]:
            project = base_project()
            project.upsert("Generator", "asset", dict(bus="A", p_nom=100))
            project.advanced_inputs = dict(piecewise=[curve("Generator", "asset", "marginal_cost", points)])
            self.assert_invalid(project)

    def test_joint_extendable_commitment_is_an_explicit_static_control_restriction(self):
        for kind in ("Generator", "Link"):
            project = base_project(two_buses=kind == "Link")
            attrs = dict(p_nom=100, p_nom_extendable=True, p_nom_max=200, committable=True)
            attrs.update(dict(bus="A") if kind == "Generator" else dict(bus0="A", bus1="B"))
            project.upsert(kind, "unit", attrs)
            self.assert_invalid(project, "extendable+committable")

    def test_structured_controls_use_real_static_fields_and_do_not_mutate_schema(self):
        expected = {
            "Generator": {"committable", "start_up_cost", "min_up_time", "p_min_pu"},
            "StorageUnit": {"max_hours", "state_of_charge_initial", "efficiency_store", "efficiency_dispatch"},
            "GlobalConstraint": {"type", "sense", "constant", "carrier_attribute"},
        }
        for kind, required in expected.items():
            groups = advanced_modeling_controls(kind)
            self.assertTrue(groups[0]["description"])
            fields = {field["name"]: field for group in groups for field in group["fields"]}
            self.assertTrue(required <= set(fields))
            for name, field in fields.items():
                self.assertTrue(field["input"] and field["static"])
                for key, value in attribute_spec(kind, name).items():
                    self.assertEqual(field[key], value)
            groups[0]["fields"][0]["description"] = "modified UI copy"
            self.assertNotEqual(advanced_modeling_controls(kind)[0]["fields"][0]["description"], "modified UI copy")
        self.assertEqual(advanced_modeling_controls("Transformer"), [])


class AdvancedExpansionNumericsTests(unittest.TestCase):
    def setUp(self):
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        self.temp = tempfile.TemporaryDirectory(prefix="stage3n_", dir=preferred)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def solve(self, project, label="native", export_format="lp"):
        self.assertEqual(project.validate(), [])
        path = self.root / label / "project.sqlite"
        save_project(project, path)
        reopened = load_project(path)
        self.assertEqual(reopened.to_dict(), project.to_dict())
        self.run = prepare_run(path, label=label, export_format=export_format)
        frozen = load_project(self.run / "inputs.sqlite")
        self.assertEqual(frozen.to_dict(), project.to_dict())
        result = execute_run(self.run)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["solver_status"], "ok")
        self.assertEqual(result["termination_condition"], "optimal")
        self.assertEqual(json.loads((self.run / "metadata/solution_checks.json").read_text())["status"], "passed")
        if export_format != "none":
            self.assertTrue((self.run / ("model." + export_format)).is_file())
            self.assertTrue((self.run / "formulation/symbols.csv").is_file())
        return result

    def table(self, component, attribute):
        return pd.read_csv(self.run / "tables" / f"{component}__{attribute}.csv", index_col=0)

    def test_capital_investment_prices_integrate_physical_capacity_for_all_three_types(self):
        for component, table, nominal in [("Generator", "generators", "p_nom"),
                                          ("Line", "lines", "s_nom"), ("Link", "links", "p_nom")]:
            with self.subTest(component=component):
                project = capital_project(component)
                project.advanced_inputs["piecewise"][0]["options"] = dict(method="lp", sign=">=")
                result = self.solve(project, component)
                # 75 capacity units: first 50 at $10, next 25 at $30. One hour
                # dispatch costs 75*3. No division by 100 and no y*x averaging.
                self.assertAlmostEqual(result["objective"], 50*10 + 25*30 + 75*3, places=6)
                static = self.table(table, "static")
                self.assertAlmostEqual(static.at["asset", nominal + "_opt"], 75)
                # Native saved output is average currency/capacity, whereas the
                # model auxiliary variable and objective contain total currency.
                self.assertAlmostEqual(static.at["asset", "capital_cost_piecewise_opt"], 1250/75)
                attribute = "p" if component == "Generator" else "p0"
                self.assertAlmostEqual(self.table(table, attribute).asset.iloc[0], 75)
                 summary = json.loads((self.run / "metadata/formulation_summary.json").read_text())
                self.assertIn(component + "-capital_cost_piecewise", summary["variable_blocks"])

    def test_capital_existing_nominal_and_scalar_price_are_not_silently_reapplied(self):
        project = capital_project()
        project.object("Generator", "asset")["attributes"].update(p_nom=20, capital_cost=999)
        result = self.solve(project, "existing")
        # The native curve covers total p_nom_opt; scalar capital_cost is replaced
        # by the curve, not added, and there is no subtraction of 20*999.
        self.assertAlmostEqual(result["objective"], 1475)
        self.assertAlmostEqual(self.table("generators", "static").at["asset", "p_nom"], 20)

    def test_capital_minimum_setpoint_and_availability_profiles_use_native_nominal_axes(self):
        project = capital_project()
        project.object("Generator", "asset")["attributes"].update(p_nom_min=60, p_nom_max=100, p_nom_set=90)
        add_profile(project, "Generator", "asset", "p_max_pu", [0.9])
        result = self.solve(project, "capacity_set", export_format="none")
        self.assertAlmostEqual(self.table("generators", "static").at["asset", "p_nom_opt"], 90)
        self.assertAlmostEqual(result["objective"], 50*10 + 40*30 + 75*3)

    def test_capital_period_weights_not_snapshot_weights_price_investment(self):
        project = capital_project()
        # Horizon changes are intentionally blocked while advanced curves exist.
        project.advanced_inputs = {}
        project.set_horizon("2030-01-01", 2, 60)
        project.advanced_inputs = dict(
            piecewise=[curve("Generator", "asset", "capital_cost", [[0, 0], [50, 10], [100, 30]])],
            periods=[dict(period=2030, objective=1, years=1), dict(period=2040, objective=2, years=1)],
            snapshot_periods=[2030, 2040],
            weights=[dict(objective=2, stores=1, generators=1), dict(objective=4, stores=1, generators=1)],
        )
        project.object("Generator", "asset")["attributes"].update(build_year=2030, lifetime=20)
        add_profile(project, "Load", "demand", "p_set", [25, 75])
        result = self.solve(project, "capital_periods", export_format="none")
        expected = (1+2)*(50*10+25*30) + 25*3*2*1 + 75*3*4*2
        self.assertAlmostEqual(result["objective"], expected)
        self.assertAlmostEqual(self.table("generators", "static").at["asset", "p_nom_opt"], 75)

    def test_link_efficiency_native_power_interpolation_not_eta_interpolation(self):
        for method in ("auto", "incremental"):
            with self.subTest(method=method):
                project = efficiency_project()
                project.advanced_inputs["piecewise"][0]["options"] = dict(method=method, sign="=")
                result = self.solve(project, "conversion_" + method, export_format="mps")
                # At 50 MW output, the segment (50,40)->(100,60) requires
                # 75 MW input. Interpolating eta=0.7 at x=.75 would be WRONG.
                self.assertAlmostEqual(self.table("links", "p0").converter.iloc[0], 75)
                self.assertAlmostEqual(self.table("links", "p1").converter.iloc[0], -50)
                self.assertAlmostEqual(self.table("generators", "p").supply.iloc[0], 75)
                self.assertAlmostEqual(result["objective"], 75*(10+2))

    def test_link_efficiency_zero_breakpoint_and_legal_availability_profiles(self):
        project = efficiency_project(3)
        add_profile(project, "Load", "demand", "p_set", [0, 20, 40])
        add_profile(project, "Link", "converter", "p_max_pu", [0, 0.5, 0.5])
        project.advanced_inputs["weights"] = [dict(objective=2, stores=1, generators=1)]*3
        result = self.solve(project, "conversion_profile", export_format="none")
        np.testing.assert_allclose(self.table("links", "p0").converter, [0, 25, 50], atol=1e-6)
        np.testing.assert_allclose(self.table("links", "p1").converter, [0, -20, -40], atol=1e-6)
        self.assertAlmostEqual(result["objective"], 2*(25+50)*12)

    def test_structured_commitment_start_stop_minimum_time_and_snapshot_count(self):
        project = base_project(4)
        project.duration_hours = 0.5
        attrs = dict(bus="A", carrier="AC", p_nom=50, committable=True, p_min_pu=0.2,
                     marginal_cost=20, start_up_cost=100, shut_down_cost=40, stand_by_cost=6,
                     up_time_before=0, down_time_before=2, min_up_time=2, min_down_time=1)
        project.upsert("Generator", "unit", attrs)
        project.upsert("Load", "demand", dict(bus="A"))
        add_profile(project, "Load", "demand", "p_set", [0, 30, 10, 0])
        result = self.solve(project, "commitment", export_format="mps")
        np.testing.assert_allclose(self.table("generators", "status").unit, [0, 1, 1, 0], atol=1e-6)
        np.testing.assert_allclose(self.table("generators", "start_up").unit, [0, 1, 0, 0], atol=1e-6)
        np.testing.assert_allclose(self.table("generators", "shut_down").unit, [0, 0, 0, 1], atol=1e-6)
        # Start/stop are event prices, not half-hour prices; standby/dispatch are
        # duration weighted. min_up_time=2 means TWO snapshots, only one hour.
        self.assertAlmostEqual(result["objective"], 0.5*40*20 + 100 + 40 + 2*0.5*6)
        static = self.table("generators", "static")
        for name, value in attrs.items():
            self.assertEqual(static.at["unit", name], value)

    def test_structured_storage_initial_state_retention_and_efficiency(self):
        project = base_project(2)
        project.duration_hours = 0.5
        project.upsert("Generator", "supply", dict(bus="A", p_nom=100, marginal_cost=10, carrier="AC"))
        project.upsert("Load", "demand", dict(bus="A", p_set=2))
        attrs = dict(bus="A", carrier="AC", p_nom=10, max_hours=2, efficiency_store=0.8,
                     efficiency_dispatch=0.5, standing_loss=0.19, state_of_charge_initial=4,
                     cyclic_state_of_charge=False, state_of_charge_set=0)
        project.upsert("StorageUnit", "battery", attrs)
        # 0.5 hours retains sqrt(0.81)=0.9 of preceding optimised SOC. Native 1.4
        # injects initial energy WITHOUT standing loss at the first snapshot.
        # Fixed SOC targets remove terminal-value ambiguity.
        add_profile(project, "StorageUnit", "battery", "state_of_charge_set", [2, 0])
        result = self.solve(project, "storage_initial", export_format="none")
        charge = self.table("storage_units", "p_store").battery.to_numpy()
        dispatch = self.table("storage_units", "p_dispatch").battery.to_numpy()
        state = self.table("storage_units", "state_of_charge").battery.to_numpy()
        np.testing.assert_allclose(state, [2, 0], atol=1e-6)
        retained = np.array([4, 0.9*2])
        np.testing.assert_allclose(state, retained + 0.5*(0.8*charge-dispatch/0.5), atol=1e-6)
        np.testing.assert_allclose(dispatch, [2, 1.8], atol=1e-6)
        np.testing.assert_allclose(self.table("generators", "p").supply, [0, 0.2], atol=1e-6)
        self.assertAlmostEqual(result["objective"], 0.5*10*0.2)
        static = self.table("storage_units", "static")
        for name, value in attrs.items():
            self.assertEqual(static.at["battery", name], value)

    def test_structured_cyclic_storage_round_trip_arbitrage(self):
        project = base_project(2)
        project.upsert("Generator", "supply", dict(bus="A", p_nom=100, marginal_cost=10, carrier="AC"))
        project.upsert("Load", "demand", dict(bus="A"))
        project.upsert("StorageUnit", "battery", dict(bus="A", p_nom=10, max_hours=1,
                       efficiency_store=0.8, efficiency_dispatch=0.5, state_of_charge_initial=1,
                       cyclic_state_of_charge=True))
        add_profile(project, "Generator", "supply", "marginal_cost", [10, 100])
        add_profile(project, "Load", "demand", "p_set", [0, 4])
        result = self.solve(project, "storage_cyclic", export_format="none")
        np.testing.assert_allclose(self.table("storage_units", "p_store").battery, [10, 0], atol=1e-6)
        np.testing.assert_allclose(self.table("storage_units", "p_dispatch").battery, [0, 4], atol=1e-6)
        np.testing.assert_allclose(self.table("storage_units", "state_of_charge").battery, [8, 0], atol=1e-6)
        self.assertAlmostEqual(result["objective"], 100)

    def test_structured_global_co2_cap_uses_primary_energy_and_generator_weights(self):
        project = base_project()
        project.upsert("Carrier", "fuel", dict(co2_emissions=0.25))
        project.upsert("Carrier", "clean", dict(co2_emissions=0))
        project.upsert("Generator", "dirty", dict(bus="A", carrier="fuel", p_nom=100,
                                                   marginal_cost=10, efficiency=0.5))
        project.upsert("Generator", "clean", dict(bus="A", carrier="clean", p_nom=100, marginal_cost=50))
        project.upsert("Load", "demand", dict(bus="A", p_set=100))
        attrs = dict(type="primary_energy", carrier_attribute="co2_emissions", sense="<=", constant=30)
        project.upsert("GlobalConstraint", "CO2", attrs)
        project.advanced_inputs = dict(weights=[dict(objective=2, stores=1, generators=3)])
        result = self.solve(project, "co2", export_format="none")
        # 30 tonnes / (3 hours * .25 tonnes/MWh_primary / .5 efficiency) = 20 MW.
        self.assertAlmostEqual(self.table("generators", "p").dirty.iloc[0], 20)
        self.assertAlmostEqual(self.table("generators", "p").clean.iloc[0], 80)
        self.assertAlmostEqual(result["objective"], 2*(20*10+80*50))
        static = self.table("global_constraints", "static")
        for name, value in attrs.items():
            self.assertEqual(static.at["CO2", name], value)

    def test_structured_storage_max_hours_binds_energy_not_dispatch_power(self):
        project = base_project(2)
        project.upsert("Generator", "supply", dict(bus="A", p_nom=100, marginal_cost=10, carrier="AC"))
        project.upsert("Load", "demand", dict(bus="A"))
        project.upsert("StorageUnit", "battery", dict(bus="A", p_nom=10, max_hours=0.5,
                       efficiency_store=0.8, efficiency_dispatch=0.5, cyclic_state_of_charge=True))
        add_profile(project, "Generator", "supply", "marginal_cost", [10, 100])
        add_profile(project, "Load", "demand", "p_set", [0, 4])
        result = self.solve(project, "storage_energy_bound", export_format="none")
        # The 5 MWh inventory bound binds before the 10 MW charging power bound.
        # 6.25 MW charge stores 5 MWh and supplies 2.5 MW in the expensive hour.
        np.testing.assert_allclose(self.table("storage_units", "p_store").battery, [6.25, 0], atol=1e-6)
        np.testing.assert_allclose(self.table("storage_units", "p_dispatch").battery, [0, 2.5], atol=1e-6)
        np.testing.assert_allclose(self.table("storage_units", "state_of_charge").battery, [5, 0], atol=1e-6)
        np.testing.assert_allclose(self.table("generators", "p").supply, [6.25, 1.5], atol=1e-6)
        self.assertAlmostEqual(result["objective"], 6.25*10 + 1.5*100)


if __name__ == "__main__":
    unittest.main()
