"""Stage 3O diagnostics are conservative, bounded and strictly read-only."""

from copy import deepcopy
from contextlib import closing
import json
import os
from pathlib import Path
import sys
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from energy_gui.model_diagnostics import (
    MAX_CONFIG_BYTES, MAX_FINDINGS, MAX_LOG_BYTES, MAX_PREVIEW, MAX_TEXT,
    diagnose_project, explain_run_failure, format_diagnostics,
)
from energy_gui.project import Project
from energy_gui.schema import attribute_spec
from energy_gui.storage import load_project, save_project


def fixture(snapshots=3):
    project = Project()
    project.set_horizon("2026-01-01", snapshots, 60)
    project.upsert("Bus", "A", {"v_nom": 220})
    project.upsert("Generator", "G", {"bus": "A", "p_nom": 10})
    project.upsert("Load", "demand", {"bus": "A", "p_set": 5})
    return project


def finding(report, code, category="checks"):
    return next(row for row in report[category] if row["code"] == code)


class ModelDiagnosticsTests(unittest.TestCase):
    def assert_json_safe(self, report):
        json.dumps(report, allow_nan=False)
        for category in ("errors", "warnings", "checks"):
            self.assertEqual(report["counts"][category], len(report[category]) + report["truncated"][category])
            for row in report[category]:
                self.assertEqual(set(row), {"code", "label", "message", "fields", "details"})
                for field in row["fields"]:
                    component, attribute = field.split(".", 1)
                    self.assertTrue(attribute_spec(component, attribute)["input"], field)

    def test_valid_project_is_not_mutated_and_has_structured_input_labels(self):
        project = fixture()
        before = deepcopy(project.to_dict())
        with patch.object(project, "validate", wraps=project.validate) as validate:
            report = diagnose_project(project)
            validate.assert_called_once_with()
        self.assertEqual(project.to_dict(), before)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["warnings"], [])
        self.assertEqual(finding(report, "connected_islands")["details"]["island_count"], 1)
        total = finding(report, "capacity_screen")
        self.assertIn("Generator.p_max_pu", total["fields"])
        self.assertEqual(total["details"]["snapshot_count"], 3)
        self.assertEqual(total["details"]["deficit_snapshot_count"], 0)
        self.assert_json_safe(report)

    def test_invalid_bus_reference_reuses_validation_and_skips_numeric_claims(self):
        project = fixture()
        project.object("Load", "demand")["attributes"]["bus"] = "missing"
        expected = project.validate()
        report = diagnose_project(project)
        self.assertEqual([row["message"] for row in report["errors"]], expected)
        self.assertIn("Load.bus", report["errors"][0]["fields"])
        self.assertIn("missing Bus", format_diagnostics(report))
        finding(report, "capacity_screen_skipped")
        self.assertFalse(any("deficit" in row["code"] for row in report["warnings"]))

    def test_invalid_numeric_and_nonfinite_values_are_not_silently_zeroed(self):
        for field, value in (("p_nom", "bad"), ("p_nom", float("nan")), ("p_max_pu", float("inf"))):
            with self.subTest(field=field, value=value):
                project = fixture()
                project.object("Generator", "G")["attributes"][field] = value
                report = diagnose_project(project)
                self.assertTrue(report["errors"])
                self.assertIn(field, format_diagnostics(report))
                finding(report, "capacity_screen_skipped")
                self.assert_json_safe(report)

    def test_valid_infinite_expansion_maximum_is_not_an_invalid_input(self):
        project = fixture()
        project.object("Generator", "G")["attributes"]["p_nom_max"] = "inf"
        self.assertEqual(diagnose_project(project)["errors"], [])

    def test_profile_override_scalar_fallback_and_positive_signed_demand(self):
        project = fixture()
        project.upsert("Generator", "scalar fallback", {"bus": "A", "p_nom": 2, "p_max_pu": 0.5})
        project.profiles = [
            {"component": "Load", "name": "demand", "attribute": "p_set", "values": [4, 7, -10]},
            {"component": "Generator", "name": "G", "attribute": "p_max_pu", "values": [0.5, 0.1, 1]},
        ]
        report = diagnose_project(project)
        rows = finding(report, "capacity_screen")["details"]
        self.assertEqual(rows["deficit_snapshot_count"], 1)
        self.assertEqual(rows["max_shortfall"], 5)
        self.assertEqual(rows["snapshots"][0]["index"], 1)
        self.assertEqual(rows["snapshots"][0]["fixed_available_generation"], 2)
        self.assertEqual(rows["snapshots"][0]["positive_demand"], 7)
        project.object("Load", "demand")["attributes"]["sign"] = 1
        rows = finding(diagnose_project(project), "capacity_screen")["details"]
        self.assertEqual(rows["deficit_snapshot_count"], 0)
        self.assertEqual(rows["snapshots"][2]["positive_demand"], 10)

    def test_disconnected_load_is_warned_even_when_global_supply_is_adequate(self):
        project = fixture()
        project.upsert("Bus", "B", {"v_nom": 220})
        project.object("Load", "demand")["attributes"]["bus"] = "B"
        report = diagnose_project(project)
        self.assertEqual(report["errors"], [])
        self.assertEqual(finding(report, "connected_islands")["details"]["island_count"], 2)
        self.assertEqual(finding(report, "capacity_screen")["details"]["deficit_snapshot_count"], 0)
        self.assertEqual(finding(report, "island_deficit", "warnings")["details"]["max_shortfall"], 5)
        finding(report, "disconnected_load_supply", "warnings")
        finding(report, "isolated_supply", "warnings")
        self.assertIn("not an infeasibility proof", format_diagnostics(report))

    def test_active_line_and_numbered_conversion_ports_connect_without_asserting_delivery(self):
        project = fixture()
        for name in ("B", "C", "D"):
            project.upsert("Bus", name, {"v_nom": 220})
        project.upsert("Line", "line", {"bus0": "A", "bus1": "B", "x": 1, "s_nom": 1})
        project.upsert("Link", "converter", {"bus0": "B", "bus1": "C", "bus2": "D", "efficiency2": 0.3})
        report = diagnose_project(project)
        self.assertEqual(report["errors"], [])
        self.assertEqual(finding(report, "connected_islands")["details"]["island_count"], 1)
        self.assertIn("undirected", finding(report, "conversion_guidance")["message"])
        project.object("Link", "converter")["attributes"]["active"] = "false"
        report = diagnose_project(project)
        self.assertEqual(finding(report, "connected_islands")["details"]["island_count"], 3)

    def test_extendable_storage_and_conversion_contributions_never_become_hard_infeasibility(self):
        for component, attributes in (
            ("Generator", {"bus": "A", "p_nom_extendable": True, "p_nom_max": 20}),
            ("StorageUnit", {"bus": "A", "p_nom": 10, "max_hours": 4, "state_of_charge_initial": 20}),
            ("Store", {"bus": "A", "e_nom": 20, "e_initial": 20}),
            ("Link", {"bus0": "B", "bus1": "A", "p_nom": 10, "efficiency": 3}),
            ("Process", {"bus0": "B", "bus1": "A", "p_nom": 10}),
        ):
            with self.subTest(component=component):
                project = fixture()
                project.object("Generator", "G")["attributes"]["p_nom"] = 0
                if component in {"Link", "Process"}:
                    project.upsert("Bus", "B", {"v_nom": 220})
                project.upsert(component, "alternative supply", attributes)
                report = diagnose_project(project)
                self.assertEqual(report["errors"], [])
                self.assertEqual(finding(report, "capacity_screen")["details"]["max_shortfall"], 5)
                text = format_diagnostics(report)
                self.assertIn("omitted", text)
                self.assertIn("not an infeasibility proof", text)
                self.assertNotIn("model is infeasible", text.lower())
                self.assert_json_safe(report)

    def test_committable_storage_and_global_guidance_uses_supported_input_fields(self):
        project = fixture()
        project.object("Generator", "G")["attributes"]["committable"] = True
        project.upsert("StorageUnit", "battery", {"bus": "A", "p_nom": 1})
        project.upsert("Store", "tank", {"bus": "A", "e_nom": 1})
        project.upsert("GlobalConstraint", "budget", {"type": "primary_energy", "sense": "<=", "constant": 10})
        report = diagnose_project(project)
        finding(report, "commitment_guidance")
        self.assertEqual(len([row for row in report["checks"] if row["code"] == "storage_guidance"]), 2)
        self.assertIn("GlobalConstraint.constant", finding(report, "global_constraint_guidance")["fields"])
        self.assertIn("weights.stores", format_diagnostics(report))
        self.assert_json_safe(report)

    def test_inactive_and_nonstandard_sign_generators_are_not_fixed_supply(self):
        project = fixture()
        for attrs in ({"active": False}, {"active": "false"}, {"sign": -1}):
            with self.subTest(attributes=attrs):
                project.object("Generator", "G")["attributes"] = {"bus": "A", "p_nom": 10, **attrs}
                report = diagnose_project(project)
                self.assertEqual(finding(report, "capacity_screen")["details"]["max_shortfall"], 5)

    def test_investment_period_activity_and_no_weighting_of_mw_values(self):
        project = fixture(2)
        project.advanced_inputs = {
            "periods": [{"period": year, "objective": 1, "years": 1} for year in (2026, 2030)],
            "snapshot_periods": [2026, 2030],
            "weights": [{"objective": 2, "stores": 4, "generators": 8}] * 2,
        }
        project.object("Generator", "G")["attributes"].update(build_year=2026, lifetime=3)
        report = diagnose_project(project)
        self.assertEqual(report["errors"], [])
        details = finding(report, "capacity_screen")["details"]
        self.assertEqual(details["deficit_snapshot_count"], 1)
        self.assertEqual(details["snapshots"][0]["index"], 1)
        self.assertEqual(details["max_shortfall"], 5)

    def test_distinct_bus_units_are_not_summed_or_implicitly_converted(self):
        project = fixture()
        project.upsert("Bus", "mass", {"unit": "t/h"})
        project.upsert("Load", "mass demand", {"bus": "mass", "p_set": 100})
        report = diagnose_project(project)
        finding(report, "mixed_units")
        self.assertFalse(any(row["code"] == "capacity_screen" for row in report["checks"]))
        units = {row["details"]["unit"] for row in report["checks"] if row["code"] == "island_capacity_screen"}
        self.assertEqual(units, {"MW", "t/h"})

    def test_snapshot_and_text_previews_are_bounded_but_all_snapshots_are_evaluated(self):
        project = fixture(100)
        project.profiles = [{"component": "Load", "name": "demand", "attribute": "p_set", "values": [1] * 99 + [12]}]
        report = diagnose_project(project)
        details = finding(report, "capacity_screen")["details"]
        self.assertEqual(details["snapshot_count"], 100)
        self.assertEqual(details["deficit_snapshot_count"], 1)
        self.assertEqual(details["snapshots"][0]["index"], 99)
        self.assertLessEqual(len(details["snapshots"]), MAX_PREVIEW)
        self.assertLessEqual(len(format_diagnostics(report, max_chars=250)), 250)
        self.assertLessEqual(len(format_diagnostics(report, max_chars=999999)), MAX_TEXT)
        self.assertIn("omitted", format_diagnostics(report, max_items=0))

    def test_large_island_inventory_has_bounded_findings_and_linear_indexing(self):
        project = Project()
        # Direct record creation isolates the diagnostic graph/aggregation path
        # from upsert's unrelated linear lookup overhead.
        for index in range(250):
            bus = f"bus {index}"
            project.objects.extend([
                {"component": "Bus", "name": bus, "attributes": {"v_nom": 220}},
                {"component": "Load", "name": f"load {index}", "attributes": {"bus": bus, "p_set": 1}},
            ])
        with patch.object(project, "object", side_effect=AssertionError("No repeated project.object lookup")):
            report = diagnose_project(project)
        self.assertEqual(finding(report, "connected_islands")["details"]["island_count"], 250)
        self.assertEqual(len(report["checks"]), MAX_FINDINGS)
        self.assertEqual(len(report["warnings"]), MAX_FINDINGS)
        self.assertGreater(report["truncated"]["checks"], 0)
        self.assertGreater(report["truncated"]["warnings"], 0)
        self.assertEqual(finding(report, "capacity_screen")["details"]["max_shortfall"], 250)
        self.assertEqual(report["checks"][0]["code"], "capacity_screen")
        self.assertEqual(report["warnings"][0]["code"], "capacity_deficit")
        self.assert_json_safe(report)

    def test_long_connected_chain_uses_nonrecursive_graph_and_scalar_aggregation(self):
        project = Project()
        for index in range(1500):
            project.objects.append({"component": "Bus", "name": str(index), "attributes": {"v_nom": 220}})
            if index:
                project.objects.append({
                    "component": "Line", "name": f"line {index}",
                    "attributes": {"bus0": str(index - 1), "bus1": str(index), "x": 1, "s_nom": 10},
                })
        project.upsert("Generator", "supply", {"bus": "0", "p_nom": 10})
        project.upsert("Load", "demand", {"bus": "1499", "p_set": 5})
        report = diagnose_project(project)
        self.assertEqual(report["errors"], [])
        self.assertEqual(finding(report, "connected_islands")["details"]["island_count"], 1)
        self.assertEqual(finding(report, "capacity_screen")["details"]["peak_positive_demand"], 5)

    def test_overflow_has_actionable_error_and_no_nonstandard_json_numbers(self):
        project = fixture()
        project.object("Generator", "G")["attributes"].update(p_nom=1e308, p_max_pu=1e308)
        report = diagnose_project(project)
        self.assertIn("overflowed", finding(report, "capacity_screen_invalid", "errors")["message"])
        self.assert_json_safe(report)

    def test_malformed_legacy_record_reports_validation_failure_instead_of_crashing(self):
        project = fixture()
        project.objects.append({"component": "Load"})
        report = diagnose_project(project)
        finding(report, "validation_incomplete", "errors")
        self.assert_json_safe(report)


class RunFailureDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        self.temp = tempfile.TemporaryDirectory(prefix="model_diagnostics_", dir=preferred)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "run"
        self.run.mkdir()

    def write_config(self, data):
        (self.run / "run_config.json").write_text(json.dumps(data), encoding="utf-8")

    def unchanged_explanation(self):
        before = {p.relative_to(self.root): (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in self.root.rglob("*") if p.is_file() and not p.is_symlink()}
        text = explain_run_failure(self.run)
        after = {p.relative_to(self.root): (p.read_bytes(), p.stat().st_mtime_ns)
                 for p in self.root.rglob("*") if p.is_file() and not p.is_symlink()}
        self.assertEqual(before, after)
        self.assertLessEqual(len(text), MAX_TEXT)
        self.assertIn("No files were modified", text)
        return text

    def test_saved_infeasible_status_has_relevant_repair_guidance_no_iis_claim(self):
        self.write_config({"status": "failed", "solver_status": "warning", "termination_condition": "infeasible"})
        text = self.unchanged_explanation()
        self.assertIn("recorded native solver status is infeasible", text)
        self.assertIn("No conflicting row set or IIS has been identified", text)
        for field in ("Load.bus/p_set", "Generator.bus/p_nom/p_max_pu", "GlobalConstraint.type/sense/constant",
                      "StorageUnit.p_nom/max_hours", "Store.e_nom/e_initial", "min_up_time/min_down_time"):
            self.assertIn(field, text)

    def test_native_highs_unbounded_status_surfaces_with_bound_and_cost_review(self):
        self.write_config({"status": "failed", "error": "solver did not finish optimally"})
        (self.run / "highs.log").write_text("HiGHS\nModel status        : Unbounded\n", encoding="utf-8")
        text = self.unchanged_explanation()
        self.assertIn("recorded native solver status is unbounded", text)
        self.assertIn("p_nom_extendable/p_nom_max", text)
        self.assertIn("negative-cost cycles", text)
        self.assertIn("No unbounded ray has been computed", text)

    def test_ambiguous_native_status_is_not_mislabelled_as_definitely_infeasible(self):
        (self.run / "highs.log").write_text("Model status : Unbounded or infeasible\n", encoding="utf-8")
        text = self.unchanged_explanation()
        self.assertIn("does not distinguish the two", text)
        self.assertNotIn("status is infeasible for", text)
        self.assertNotIn("status is unbounded:", text)

    def test_conflicting_native_statuses_are_disclosed_not_arbitrarily_chosen(self):
        self.write_config({"termination_condition": "optimal", "status": "failed"})
        (self.run / "highs.log").write_text("Model status : Infeasible\n", encoding="utf-8")
        self.assertIn("statuses conflict", self.unchanged_explanation())

    def test_arbitrary_infeasible_log_mention_does_not_invent_native_status(self):
        self.write_config({"status": "failed", "error": "infeasible is one possible status"})
        (self.run / "application.log").write_text("Check for infeasible models; no solver was started.\n", encoding="utf-8")
        text = self.unchanged_explanation()
        self.assertIn("No explicit native infeasible/unbounded termination status", text)
        self.assertNotIn("recorded native solver status is infeasible", text)

    def test_malformed_config_and_binary_log_are_readable_without_repair(self):
        (self.run / "run_config.json").write_bytes(b'{"status":')
        (self.run / "worker.log").write_bytes(b"\x00\xff\xfe\x1b[31mworker crashed\x1b[0m\n")
        text = self.unchanged_explanation()
        self.assertIn("malformed/incomplete JSON", text)
        self.assertIn("worker crashed", text)
        self.assertNotIn("\x00", text)
        self.assertNotIn("\x1b", text)

    def test_non_object_and_nonstandard_json_or_nested_fields_are_safe(self):
        for value in ("[]", '{"error":NaN}', '{"termination_condition":{"file":"../secret"}}'):
            with self.subTest(config=value):
                (self.run / "run_config.json").write_text(value, encoding="utf-8")
                self.assertIn("malformed", self.unchanged_explanation())

    def test_artifact_paths_from_config_are_never_followed(self):
        secret = self.root / "outside.txt"
        secret.write_text("PRIVATE-DO-NOT-READ", encoding="utf-8")
        self.write_config({"status": "failed", "log_file": "../outside.txt", "artifacts": {"highs.log": str(secret)}})
        self.assertNotIn("PRIVATE-DO-NOT-READ", self.unchanged_explanation())

    def test_external_resolved_artifact_is_refused_before_open(self):
        secret = self.root / "outside.txt"
        secret.write_text("PRIVATE-DO-NOT-READ", encoding="utf-8")
        actual_resolve = Path.resolve

        def resolve(path, *args, **kwargs):
            if path == self.run / "highs.log":
                return secret
            return actual_resolve(path, *args, **kwargs)

        with patch.object(Path, "resolve", resolve):
            text = explain_run_failure(self.run)
        self.assertIn("refused a linked/escaping artifact", text)
        self.assertNotIn("PRIVATE-DO-NOT-READ", text)

    def test_large_config_and_logs_are_bounded_and_tail_status_is_kept(self):
        (self.run / "run_config.json").write_bytes(b" " * (MAX_CONFIG_BYTES + 1))
        (self.run / "highs.log").write_bytes(
            b"start\n" + b"x" * (MAX_LOG_BYTES * 3) + b"\nModel status : Infeasible\n"
        )
        text = self.unchanged_explanation()
        self.assertIn("diagnostic read limit", text)
        self.assertIn("recorded native solver status is infeasible", text)
        self.assertIn("bounded", text)

    def test_missing_directory_or_files_do_not_create_artifacts(self):
        self.assertIn("missing", self.unchanged_explanation())
        self.assertEqual(list(self.run.iterdir()), [])
        missing = self.root / "not created"
        self.assertIn("Run directory is missing", explain_run_failure(missing))
        self.assertFalse(missing.exists())

    def test_directory_in_place_of_log_is_not_opened_as_an_artifact(self):
        (self.run / "highs.log").mkdir()
        (self.run / "highs.log" / "private").write_text("PRIVATE-DO-NOT-READ", encoding="utf-8")
        text = self.unchanged_explanation()
        self.assertIn("not a regular file", text)
        self.assertNotIn("PRIVATE-DO-NOT-READ", text)

    def test_log_symlink_is_refused_even_if_its_target_resolves_within_the_run(self):
        (self.run / "highs.log").write_text("Model status : Infeasible\n", encoding="utf-8")
        actual_is_symlink = Path.is_symlink

        def is_symlink(path):
            return path == self.run / "highs.log" or actual_is_symlink(path)

        with patch.object(Path, "is_symlink", is_symlink):
            text = explain_run_failure(self.run)
        self.assertIn("refused a linked/escaping artifact", text)
        self.assertNotIn("recorded native solver status is infeasible", text)

    def test_old_minimal_config_and_saved_project_need_no_new_artifact(self):
        self.write_config({"status": "failed", "error": "older run"})
        self.assertIn("older run", self.unchanged_explanation())
        path = self.root / "old.sqlite"
        save_project(fixture(), path)
        # The historical core payload and optional-metadata defaults remain
        # readable without adding any diagnostics metadata or migrating a DB.
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(
                "DELETE FROM metadata WHERE key IN "
                "('editor_config', 'schematic_layouts', 'demo_info', 'analysis_workspace')"
            )
        before = path.read_bytes()
        project = load_project(path)
        report = diagnose_project(project)
        self.assertEqual(report["errors"], [])
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.run / "diagnostics.json").exists())


if __name__ == "__main__":
    unittest.main()
