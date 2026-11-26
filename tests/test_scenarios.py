"""Stage 3M pure-backend scenario contracts and independent tiny numerics."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from energy_gui.engine import build_network, execute_run, prepare_run
from energy_gui.project import Project
from energy_gui.scenarios import checked_scenarios, prepare_scenarios, scenario_project
from energy_gui.storage import load_project, save_project


def base_project():
    project = Project(name="Scenario base", currency="USD")
    project.set_horizon("2030-01-01", 2, 60)
    project.upsert("Carrier", "AC", {})
    project.upsert("Bus", "B", {})
    project.upsert("Generator", "G", dict(bus="B", carrier="AC", p_nom=100, marginal_cost=10))
    project.upsert("Load", "D", dict(bus="B", p_set=20))
    return project


def change(attribute="marginal_cost", operation="scale", value=2, component="Generator", name="G"):
    return dict(component=component, name=name, attribute=attribute, operation=operation, value=value)


def definition(identifier="dear", name="Higher fuel cost", changes=None):
    return dict(id=identifier, name=name, changes=[change()] if changes is None else changes)


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        preferred = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" if sys.platform == "win32" else None
        self.temp = tempfile.TemporaryDirectory(prefix="stage3m_scenarios_", dir=preferred)
        self.root = Path(self.temp.name)
        self.project = base_project()
        self.database = self.root / "project.sqlite"
        save_project(self.project, self.database)

    def tearDown(self):
        self.temp.cleanup()

    def frozen_bytes(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def test_canonical_definitions_roundtrip_and_independent_detached_candidates(self):
        definitions = [definition(" dear ", " Higher fuel cost "), definition("low", "Lower cost", [change(value=.5)])]
        original = deepcopy(definitions)
        before = self.project.to_dict()
        clean = checked_scenarios(self.project, definitions)
        self.assertEqual(json.loads(json.dumps(clean, allow_nan=False)), clean)
        self.assertEqual(checked_scenarios(self.project, clean), clean)
        self.assertEqual(clean[0]["id"], "dear")
        self.assertEqual(clean[0]["name"], "Higher fuel cost")
        left = scenario_project(self.project, clean[0])
        right = scenario_project(self.project, clean[1])
        self.assertEqual(left.object("Generator", "G")["attributes"]["marginal_cost"], 20)
        self.assertEqual(right.object("Generator", "G")["attributes"]["marginal_cost"], 5)
        self.assertEqual(left.project_id, self.project.project_id)
        left.editor_config["only_left"] = True
        clean[0]["changes"][0]["value"] = 3
        self.assertEqual(self.project.to_dict(), before)
        self.assertEqual(definitions, original)

    def test_empty_list_and_explicit_baseline(self):
        self.assertEqual(checked_scenarios(self.project, []), [])
        before = self.frozen_bytes()
        self.assertEqual(prepare_scenarios(self.database, []), [])
        self.assertEqual(before, self.frozen_bytes())
        self.assertFalse((self.root / "runs").exists())
        baseline = scenario_project(self.project, definition(changes=[]))
        self.assertEqual(baseline.to_dict(), self.project.to_dict())
        self.assertIsNot(baseline.objects, self.project.objects)

    def test_preserves_all_non_model_metadata_and_nested_state(self):
        self.project.editor_config = {"nested": [1]}
        self.project.schematic_layouts = {"one": {"positions": [[1, 2]]}}
        self.project.demo_info = {"source": "test"}
        self.project.analysis_workspace = [{"id": "saved", "cards": []}]
        self.project.advanced_inputs = {"weights": [dict(objective=2, stores=1, generators=1)] * 2}
        before = self.project.to_dict()
        candidate = scenario_project(self.project, definition())
        for key in ("editor_config", "schematic_layouts", "demo_info", "analysis_workspace", "advanced_inputs"):
            self.assertEqual(candidate.to_dict()[key], before[key])
        candidate.editor_config["nested"].append(2)
        candidate.advanced_inputs["weights"][0]["objective"] = 4
        self.assertEqual(self.project.to_dict(), before)

    def test_scale_numeric_profile_and_static_with_metadata_unchanged(self):
        self.project.profiles = [dict(component="Load", name="D", attribute="p_set", values=[10, 30],
                                      source="original.csv", unit="MW")]
        before = self.project.to_dict()
        case = definition(changes=[change("p_set", "scale", 1.5, "Load", "D")])
        candidate = scenario_project(self.project, case)
        self.assertEqual(candidate.profiles[0], {**self.project.profiles[0], "values": [15, 45]})
        self.assertEqual(candidate.object("Load", "D")["attributes"]["p_set"], 30)
        self.assertEqual(build_network(candidate).loads_t.p_set["D"].tolist(), [15, 45])
        self.assertEqual(self.project.to_dict(), before)

    def test_scale_materializes_finite_default_but_does_not_create_profile(self):
        candidate = scenario_project(self.project, definition(changes=[change("p_max_pu", "scale", .5)]))
        self.assertEqual(candidate.object("Generator", "G")["attributes"]["p_max_pu"], .5)
        self.assertEqual(candidate.profiles, [])
        self.assertNotIn("p_max_pu", self.project.object("Generator", "G")["attributes"])

    def test_scalar_set_numbers_booleans_and_text_use_schema_types(self):
        candidate = scenario_project(self.project, definition(changes=[
            change("p_nom", "set", 90), change("p_nom_extendable", "set", True),
            change("location", "set", "North", "Bus", "B"),
        ]))
        self.assertEqual(candidate.object("Generator", "G")["attributes"]["p_nom"], 90)
        self.assertIs(candidate.object("Generator", "G")["attributes"]["p_nom_extendable"], True)
        self.assertEqual(candidate.object("Bus", "B")["attributes"]["location"], "North")

    def test_set_profiled_attribute_refuses_ignored_override(self):
        self.project.profiles = [dict(component="Load", name="D", attribute="p_set", values=[10, 30])]
        with self.assertRaisesRegex(ValueError, "profile overrides.*use scale"):
            scenario_project(self.project, definition(changes=[change("p_set", "set", 25, "Load", "D")]))

    def test_advanced_curve_rejects_both_set_and_scale_with_clear_location(self):
        self.project.advanced_inputs = {"piecewise": [dict(component="Generator", name="G", attribute="marginal_cost",
                                                          points=[[0, 0], [1, 20]])]}
        before = self.project.to_dict()
        for operation in ("set", "scale"):
            with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, "Generator G.marginal_cost.*piecewise curve"):
                scenario_project(self.project, definition(changes=[change(operation=operation)]))
        self.assertEqual(self.project.to_dict(), before)
        candidate = scenario_project(self.project, definition(changes=[change("p_nom", "scale", 2)]))
        self.assertEqual(candidate.advanced_inputs, self.project.advanced_inputs)

    def test_wrong_targets_outputs_unknown_fields_and_topology_rejected(self):
        cases = [change("p"), change("p_nom_opt"), change("not_an_attribute"), change(component="Unknown"),
                 change(name="missing"), change("name", "set", "new"), change("bus", "set", "missing"),
                 change("bus2", "set", "B", "Link", "missing"), change("carrier", "set", "missing"),
                 change("type", "set", "unknown"), change("active", "set", False)]
        for item in cases:
            with self.subTest(item=item), self.assertRaises(ValueError):
                scenario_project(self.project, definition(changes=[item]))

    def test_strict_scalar_types_are_not_coerced_or_evaluated(self):
        cases = [change(value=True), change(value="2"), change(value=None), change(value=[2]), change(value={"factor": 2}),
                 change("marginal_cost", "set", "2"), change("marginal_cost", "set", False),
                 change("marginal_cost", "set", "__import__('os').getcwd()"),
                 change("committable", "set", "false"), change("committable", "set", 1), change("committable", "scale", 2),
                 change("location", "set", 1, "Bus", "B"), change("location", "scale", 2, "Bus", "B"),
                 change("min_up_time", "set", .5), change(operation="multiply"), change(operation=["set"])]
        for item in cases:
            with self.subTest(item=item), self.assertRaises(ValueError):
                scenario_project(self.project, definition(changes=[item]))

    def test_nonfinite_extreme_and_scaled_overflow_inputs_rejected(self):
        for value in (float("nan"), float("inf"), -float("inf"), 1e16, 10**1000):
            for operation in ("set", "scale"):
                with self.subTest(value=str(value)[:30], operation=operation), self.assertRaisesRegex(ValueError, "finite"):
                    scenario_project(self.project, definition(changes=[change(operation=operation, value=value)]))
        with self.assertRaisesRegex(ValueError, "scaled value.*finite"):
            scenario_project(self.project, definition(changes=[change(value=1e15)]))
        with self.assertRaisesRegex(ValueError, "static/default value.*finite"):
            scenario_project(self.project, definition(changes=[change("p_nom_max")]))

    def test_numeric_profile_types_and_scaled_profile_bounds_checked(self):
        for values in ([True, 30], ["10", 30], [1e15, 30]):
            self.project.profiles = [dict(component="Load", name="D", attribute="p_set", values=values)]
            with self.subTest(values=values), self.assertRaisesRegex(ValueError, "profile row 1"):
                scenario_project(self.project, definition(changes=[change("p_set", "scale", 2, "Load", "D")]))

    def test_invalid_resulting_engineering_bounds_are_rejected(self):
        cases = [[change("p_nom", "set", -1)], [change("efficiency", "set", 0)],
                 [change("p_nom_min", "set", 80), change("p_nom_max", "set", 40)],
                 [change("p_min_pu", "set", .9), change("p_max_pu", "set", .1)],
                 [change("marginal_cost_quadratic", "set", 1)]]
        before = self.project.to_dict()
        for edits in cases:
            with self.subTest(edits=edits), self.assertRaises(ValueError):
                checked_scenarios(self.project, [definition(changes=edits)])
        self.assertEqual(self.project.to_dict(), before)

    def test_malformed_definition_fields_and_data_only_list(self):
        variants = [None, {}, (definition(),), [None], [{"id": "a", "name": "b"}],
                    [{**definition(), "code": "print(1)"}], [definition(changes={})],
                    [definition(changes=[{**change(), "profiles": True}])],
                    [definition(changes=[{"operation": "set"}])]]
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError):
                checked_scenarios(self.project, value)

    def test_unique_ids_names_limits_and_unsafe_text(self):
        for definitions in ([definition(), definition()],
                            [definition(), definition("other", "HIGHER FUEL COST")],
                            [definition(), definition("DEAR", "Other")],
                            [definition(str(i), str(i)) for i in range(31)],
                            [definition(changes=[change()] * 101)],
                            [definition("../escape")], [definition("a/b")], [definition("a:b")],
                            [definition("x" * 65)], [definition(name="x" * 121)],
                            [definition(name="bad\nname")], [definition(name=" ")],
                            [definition(changes=[change("location", "set", "x" * 1025, "Bus", "B")])]):
            with self.subTest(definitions=str(definitions)[:100]), self.assertRaises(ValueError):
                checked_scenarios(self.project, definitions)

    def test_definition_json_size_bound(self):
        definitions = [definition(str(i), str(i), [change("location", "set", "x" * 1024, "Bus", "B")]) for i in range(2)]
        with patch("energy_gui.scenarios.MAX_DEFINITION_BYTES", 1024), self.assertRaisesRegex(ValueError, "JSON size limit"):
            checked_scenarios(self.project, definitions)

    def test_duplicate_target_rejected_instead_of_order_dependent_override(self):
        with self.assertRaisesRegex(ValueError, "duplicate target"):
            scenario_project(self.project, definition(changes=[change(), change(operation="set", value=5)]))

    def test_undefined_referenced_objects_are_rejected_in_base(self):
        for component, name, attr, value in (("Generator", "G", "carrier", "missing"),
                                             ("Generator", "G", "bus", "missing")):
            project = base_project()
            project.object(component, name)["attributes"][attr] = value
            with self.subTest(attr=attr), self.assertRaisesRegex(ValueError, "Base project"):
                checked_scenarios(project, [definition()])
        project = base_project()
        project.objects = [o for o in project.objects if o["component"] != "Carrier"]
        with self.assertRaisesRegex(ValueError, "undefined Carrier 'AC'"):
            scenario_project(project, definition())

    def test_all_candidates_validate_before_any_prepare_or_publication(self):
        old_run = prepare_run(self.database, label="existing", export_format="none")
        before = self.frozen_bytes()
        definitions = [definition(), definition("bad", "Bad bounds", [change("p_nom", "set", -5)])]
        with patch("energy_gui.scenarios.prepare_run", side_effect=AssertionError("Should not prepare")) as prepare:
            with self.assertRaisesRegex(ValueError, "Bad bounds"):
                prepare_scenarios(self.database, definitions)
            prepare.assert_not_called()
        self.assertEqual(before, self.frozen_bytes())
        self.assertTrue(old_run.exists())
        self.assertFalse(list(self.root.glob(".scenario-stage-*")))

    def test_freeze_provenance_order_base_and_existing_files_invariant(self):
        old_run = prepare_run(self.database, label="existing", export_format="none")
        before = self.frozen_bytes()
        definitions = [definition(), definition("low", "Lower cost", [change(value=.5)])]
        runs = prepare_scenarios(self.database, definitions, export_format="mps")
        self.assertEqual(len(runs), 2)
        self.assertEqual(len(set(runs)), 2)
        for index, (run, expected) in enumerate(zip(runs, [20, 5])):
            self.assertEqual(run.parent, self.root / "runs")
            self.assertNotEqual(run, old_run)
            frozen = load_project(run / "inputs.sqlite")
            self.assertEqual(frozen.project_id, self.project.project_id)
            self.assertEqual(frozen.object("Generator", "G")["attributes"]["marginal_cost"], expected)
            config = json.loads((run / "metadata/run_config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["status"], "queued")
            self.assertEqual(config["export_format"], "mps")
            self.assertEqual(config["scenario_id"], definitions[index]["id"])
            self.assertEqual(config["scenario_name"], definitions[index]["name"])
            self.assertEqual(config["scenario_definition"], definitions[index])
            canonical = json.dumps(self.project.to_dict(), sort_keys=True, ensure_ascii=True,
                                   separators=(",", ":"), allow_nan=False).encode("utf-8")
            self.assertEqual(config["scenario_base"], dict(project_id=self.project.project_id,
                             name=self.project.name, database="project.sqlite",
                             project_sha256=hashlib.sha256(canonical).hexdigest()))
            self.assertEqual(set(p.name for p in run.iterdir()), {"inputs.sqlite", "metadata"})
        after = self.frozen_bytes()
        self.assertTrue(all(after[key] == value for key, value in before.items()))
        self.assertEqual(load_project(self.database).to_dict(), self.project.to_dict())
        self.assertFalse(list(self.root.glob(".scenario-stage-*")))

    def test_prepare_failure_after_first_scratch_case_publishes_nothing(self):
        existing = prepare_run(self.database, label="existing", export_format="none")
        before = self.frozen_bytes()
        calls = []

        def failing_prepare(database, label, export_format):
            calls.append(Path(database))
            if len(calls) == 2:
                raise OSError("Injected scratch failure")
            return prepare_run(database, label=label, export_format=export_format)

        with patch("energy_gui.scenarios.prepare_run", side_effect=failing_prepare):
            with self.assertRaisesRegex(OSError, "scratch failure"):
                prepare_scenarios(self.database, [definition(), definition("other", "Other")])
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(path != self.database for path in calls))
        self.assertEqual(before, self.frozen_bytes())
        self.assertTrue(existing.exists())
        self.assertFalse(list(self.root.glob(".scenario-stage-*")))

    def test_publication_failure_rolls_back_only_new_unstarted_runs(self):
        existing = prepare_run(self.database, label="existing", export_format="none")
        before = self.frozen_bytes()
        calls = []

        def fail_second(source, destination):
            calls.append(destination)
            if len(calls) == 2:
                raise OSError("Injected publication failure")
            source.rename(destination)

        with patch("energy_gui.scenarios._publish_run", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "publication failure"):
                prepare_scenarios(self.database, [definition(), definition("other", "Other")])
        self.assertEqual(before, self.frozen_bytes())
        self.assertEqual(list((self.root / "runs").iterdir()), [existing])

    def test_invalid_export_format_refuses_before_files(self):
        before = self.frozen_bytes()
        for export_format in ("sql", [], None):
            with self.subTest(export_format=export_format), self.assertRaisesRegex(ValueError, "Export format"):
                prepare_scenarios(self.database, [definition()], export_format)
        self.assertEqual(before, self.frozen_bytes())

    def test_repeat_calls_make_distinct_runs_without_modifying_prior_batch(self):
        first = prepare_scenarios(self.database, [definition()])
        before = self.frozen_bytes()
        second = prepare_scenarios(self.database, [definition()])
        self.assertNotEqual(first, second)
        after = self.frozen_bytes()
        self.assertTrue(all(after[key] == value for key, value in before.items()))

    def test_frozen_input_database_is_not_used_as_editable_base(self):
        existing = prepare_run(self.database, label="existing", export_format="none")
        before = self.frozen_bytes()
        with self.assertRaisesRegex(ValueError, "outside frozen run directories"):
            prepare_scenarios(existing / "inputs.sqlite", [definition()])
        self.assertEqual(before, self.frozen_bytes())
        self.assertFalse((existing / "runs").exists())

    def test_preexisting_destination_collision_is_never_replaced(self):
        existing = prepare_run(self.database, label="existing", export_format="none")
        before = self.frozen_bytes()

        def colliding_prepare(database, label, export_format):
            prepared = prepare_run(database, label=label, export_format=export_format)
            colliding = prepared.parent / existing.name
            prepared.rename(colliding)
            return colliding

        with patch("energy_gui.scenarios.prepare_run", side_effect=colliding_prepare):
            with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
                prepare_scenarios(self.database, [definition()])
        self.assertEqual(before, self.frozen_bytes())
        self.assertEqual(list((self.root / "runs").iterdir()), [existing])

    def test_failed_publication_removes_only_its_new_empty_runs_directory(self):
        before = self.frozen_bytes()
        with patch("energy_gui.scenarios._publish_run", side_effect=PermissionError("Destination blocked")):
            with self.assertRaisesRegex(PermissionError, "blocked"):
                prepare_scenarios(self.database, [definition()])
        self.assertEqual(before, self.frozen_bytes())
        self.assertFalse((self.root / "runs").exists())

    def test_builtin_line_types_are_defined_reference_targets(self):
        from energy_gui.object_edits import standard_names

        self.project.upsert("Bus", "B2", {})
        self.project.upsert("Line", "L", dict(bus0="B", bus1="B2", type=next(iter(standard_names()["LineType"])),
                                                length=1, num_parallel=1))
        candidate = scenario_project(self.project, definition())
        self.assertEqual(candidate.validate(), [])

    def test_real_two_case_worker_objectives_and_profile_dispatch(self):
        self.project.profiles = [dict(component="Load", name="D", attribute="p_set", values=[10, 30],
                                      unit="MW", source="analytical case")]
        save_project(self.project, self.database)
        before = self.database.read_bytes()
        definitions = [definition("cost", "Doubled cost", [change(value=2)]),
                       definition("demand", "Half demand", [change("p_set", "scale", .5, "Load", "D")])]
        runs = prepare_scenarios(self.database, definitions)
        for run, objective, dispatch in zip(runs, [800, 200], [[10, 30], [5, 15]]):
            config = execute_run(run)
            self.assertEqual(config["status"], "succeeded")
            self.assertAlmostEqual(config["objective"], objective, places=6)
            actual = pd.read_csv(run / "tables" / "generators__p.csv")["G"].tolist()
            self.assertEqual(actual, dispatch)
            self.assertIn("scenario_base", config)
            self.assertEqual(json.loads((run / "metadata/solution_checks.json").read_text())["status"], "passed")
        self.assertEqual(self.database.read_bytes(), before)
        self.assertEqual(load_project(self.database).to_dict(), self.project.to_dict())


if __name__ == "__main__":
    unittest.main()
