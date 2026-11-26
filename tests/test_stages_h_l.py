"""Integrated analysis/time/report/backup acceptance, with frozen-file isolation."""

from copy import deepcopy
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import pandas as pd

from energy_gui.advanced import checked_advanced
from energy_gui.analysis import capture_analysis, compare_query, prepare_analysis, repository_for, run_metrics, run_path
from energy_gui.controller import Controller
from energy_gui.engine import add_component, build_network, execute_run, prepare_run
from energy_gui.object_edits import delete_candidate, rename_candidate
from energy_gui.project import Project
from energy_gui.reporting import annotate_formulation, chart_svg, write_chart, write_report
from energy_gui.results import ResultsRepository, query_charts
from energy_gui.safety import create_backup
from energy_gui.storage import load_project, save_project
from energy_gui.scale_acceptance import scale_project
from energy_gui.workspace import QueryTab
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from test_network_view import overlay_fixture


def simple_project():
    project = Project(currency="USD")
    project.set_horizon("2030-01-01", 2, 60)
    for name, attrs in [("AC", {}), ("gas", {"co2_emissions": 0.2})]:
        project.upsert("Carrier", name, attrs)
    project.upsert("Bus", "B", {})
    project.upsert("Generator", "G", dict(bus="B", p_nom=100, marginal_cost=10, carrier="gas"))
    project.upsert("Load", "D", dict(bus="B", p_set=75))
    return project


class AnalysisAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="stage_h_l_", dir=Path(os.environ["LOCALAPPDATA"])/"Temp"/"opencode")
        self.root = Path(self.temp.name)
        self.a, self.b = self.root/"runs"/"left", self.root/"runs"/"right"
        project, _ = overlay_fixture(self.a)
        other, _ = overlay_fixture(self.b)
        other.project_id = project.project_id
        save_project(other, self.b/"inputs.sqlite")
        (self.b/"run_config.json").write_text(json.dumps(dict(project_id=project.project_id,status="succeeded",objective=20)))
        self.c = Controller()
        self.c.project, self.c.path = project, self.root/"project.sqlite"
        self.c._reset_draft()
        save_project(project, self.c.path)
        self.assertTrue(self.c.openRun(str(self.a)))
        self.assertTrue(self.c.queryResults("Line", ["L"], ["p0"], "", ""))
        self.notices = []
        self.c.notice.connect(self.notices.append)

    def tearDown(self):
        if self.c._backup_worker:
            self.c.cancelBackup()
            self.wait_backup()
        self.c._recovery_timer.stop()
        self.c.notice.disconnect()
        self.temp.cleanup()

    def wait_backup(self):
        if not self.c._backup_thread:
            return
        # Run a real Qt event loop: repeated QTest waits can starve Python worker
        # execution on some PySide builds by holding the GIL between callbacks.
        loop=QEventLoop()
        timer=QTimer(loop);timer.setSingleShot(True);timer.timeout.connect(loop.quit)
        self.c._backup_thread.finished.connect(loop.quit)
        timer.start(30000);loop.exec();timer.stop()
        self.app.processEvents()

    def saved(self):
        self.assertTrue(self.c.setChartType(self.c.workspace.active.specs[0]["name"], "dot"))
        self.c.setAnalysisView(1)
        self.assertTrue(self.c.saveAnalysis("Comparison dashboard"))
        self.assertTrue(self.c.saveProject())
        return deepcopy(self.c.project.analysis_workspace[0])

    def bytes(self):
        return {str(p):p.read_bytes() for p in (self.root/"runs").rglob("*") if p.is_file()}

    def test_saved_analysis_roundtrip_styles_view_source_and_no_solver(self):
        saved = self.saved()
        self.assertEqual(saved["cards"][0]["run"], "left")
        self.assertEqual(load_project(self.c.path).analysis_workspace, [saved])
        before = self.bytes()
        self.c.project.name = "Live edited model"
        with patch.object(QMessageBox,"question",return_value=QMessageBox.StandardButton.Yes), patch("energy_gui.controller.prepare_run", side_effect=AssertionError("No solve")):
            self.assertTrue(self.c.restoreAnalysis(0))
        self.assertEqual(self.c.workspace.active.chart_types, {"p0":"dot"})
        self.assertEqual(self.c.workspace.active.view, 1)
        self.assertEqual(self.c.project.name, "Live edited model")
        self.assertEqual(before, self.bytes())

    def test_multi_card_order_pin_active_and_different_runs(self):
        self.c.pinQueryTab(self.c.workspace.active_id)
        self.assertTrue(self.c.openRun(str(self.b)))
        self.assertTrue(self.c.queryResults("Line",["L"],["p1"],"",""))
        saved = self.saved()
        self.assertEqual([c["run"] for c in saved["cards"]], ["left","right"])
        with patch.object(QMessageBox,"question",return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(self.c.restoreAnalysis(0))
        self.assertEqual(len(self.c.workspace.tabs),2)
        self.assertTrue(self.c.workspace.tabs[0].pinned)
        self.assertEqual(self.c.workspace.active.criteria["properties"],["p1"])

    def test_restore_missing_or_corrupt_second_card_preserves_prior_tabs_and_source(self):
        saved=self.saved()
        self.c.project.analysis_workspace[0]["cards"].append({**deepcopy(saved["cards"][0]), "run":"missing"})
        active, repo = self.c.workspace.active_id, self.c.repository
        before=self.bytes()
        self.assertFalse(self.c.restoreAnalysis(0))
        self.assertEqual(self.c.workspace.active_id,active)
        self.assertIs(self.c.repository,repo)
        self.assertEqual(self.bytes(),before)

    def test_restore_cancel_and_invalid_index_are_nonmutating(self):
        self.saved()
        active=self.c.workspace.active_id
        with patch.object(QMessageBox,"question",return_value=QMessageBox.StandardButton.No):
            self.assertFalse(self.c.restoreAnalysis(0))
        self.assertFalse(self.c.restoreAnalysis(-1))
        self.assertEqual(self.c.workspace.active_id,active)

    def test_malformed_saved_card_state_is_rejected_before_workspace_replacement(self):
        saved = self.saved()
        active, repository = self.c.workspace.active_id, self.c.repository
        before = self.bytes()
        variants = []
        for field, value in [("pinned", "false"), ("view", True), ("view", 2),
                             ("chart_types", {"p1": "dot"}),
                             ("chart_types", {"p0": "horizontal bar"})]:
            candidate = deepcopy(saved)
            candidate["cards"][0][field] = value
            variants.append(candidate)
        duplicate_preview = deepcopy(saved)
        duplicate_preview["cards"].append(deepcopy(saved["cards"][0]))
        variants.append(duplicate_preview)
        for candidate in variants:
            with self.subTest(candidate=candidate):
                self.c.project.analysis_workspace = [candidate]
                self.assertFalse(self.c.restoreAnalysis(0))
                self.assertEqual(self.c.workspace.active_id, active)
                self.assertIs(self.c.repository, repository)
        self.assertEqual(self.bytes(), before)

    def test_portable_paths_reject_escape_and_external_source(self):
        for value in ["../left","C:\\run",".","..","left/right","left\\right",""]:
            with self.subTest(value=value),self.assertRaises(ValueError):run_path(self.c.path,value)
        self.c.workspace.active.run_path=str(self.root/"external")
        self.assertFalse(self.c.saveAnalysis("External"))

    def test_saved_definitions_survive_model_and_legacy_history_steps(self):
        self.c.project.upsert("Carrier","extra",{})
        self.c.selectType("Bus")
        self.assertTrue(self.c.storeObject("Extra",'{}'))
        saved=self.saved()
        self.assertTrue(self.c.modelHistory(False))
        self.assertEqual(self.c.project.analysis_workspace,[saved])
        self.assertTrue(self.c.modelHistory(True))
        self.assertEqual(self.c.project.analysis_workspace,[saved])

    def test_arrangement_and_removal_never_delete_runs(self):
        self.saved();self.assertTrue(self.c.saveAnalysis("Second"))
        before=self.bytes()
        self.assertTrue(self.c.arrangeAnalysis(1,-1))
        self.assertEqual(self.c.savedAnalyses[0]["title"],"Second")
        self.assertTrue(self.c.arrangeAnalysis(0,0))
        self.assertEqual(len(self.c.project.analysis_workspace),1)
        self.assertEqual(before,self.bytes())

    def test_optional_workspace_metadata_is_outside_core_payload(self):
        self.saved()
        with closing(sqlite3.connect(self.c.path)) as conn, conn:
            payload=json.loads(conn.execute("select value from metadata where key='project'").fetchone()[0])
            self.assertNotIn("analysis_workspace",payload)
            conn.execute("delete from metadata where key='analysis_workspace'")
        self.assertEqual(load_project(self.c.path).analysis_workspace,[])

    def test_comparison_uses_captured_criteria_and_correct_signed_delta(self):
        path=self.b/"tables"/"Line_p0.csv"
        frame=pd.read_csv(path);frame["L"]+=3;frame.to_csv(path,index=False)
        text=self.c.compareRuns("left","right")
        self.assertIn("right",text)
        self.assertEqual(self.c._comparison_frame["delta_right_minus_left"].tolist(),[3,3])
        self.assertEqual(self.c.workspace.active.criteria["properties"],["p0"])

    def test_comparison_refuses_currency_axes_and_weights_mismatch(self):
        baseline=load_project(self.b/"inputs.sqlite")
        for change in ["currency","snapshots","weights"]:
            p=deepcopy(baseline)
            if change=="currency":p.currency="OTHER"
            elif change=="snapshots":p.snapshots=["2027-01-01T00:00:00","2027-01-01T01:00:00"]
            else:p.advanced_inputs={"weights":[dict(objective=2,stores=1,generators=1)]*2}
            save_project(p,self.b/"inputs.sqlite")
            result=self.c.compareRuns("left","right")
            self.assertIn("unavailable",result)
            self.assertIsNone(self.c._comparison_frame)
        save_project(baseline,self.b/"inputs.sqlite")

    def test_comparison_missing_numeric_values_refused_without_query_mutation(self):
        path=self.b/"tables"/"Line_p0.csv"
        frame=pd.read_csv(path);frame["L"]=frame["L"].astype(float);frame.loc[0,"L"]=float("nan");frame.to_csv(path,index=False)
        active=self.c.workspace.active_id
        self.assertIn("unavailable",self.c.compareRuns("left","right"))
        self.assertEqual(self.c.workspace.active_id,active)

    def test_comparison_refuses_changed_bus_units_and_formulation(self):
        project = load_project(self.b / "inputs.sqlite")
        project.object("Bus", "A")["attributes"]["unit"] = "kW"
        save_project(project, self.b / "inputs.sqlite")
        self.assertIn("unavailable", self.c.compareRuns("left", "right"))
        self.assertIn("units differ", self.notices[-1])
        project.object("Bus", "A")["attributes"].pop("unit")
        save_project(project, self.b / "inputs.sqlite")
        metadata_path = self.b / "run_config.json"
        metadata = json.loads(metadata_path.read_text())
        metadata["formulation"] = "different formulation"
        metadata_path.write_text(json.dumps(metadata))
        self.assertIn("unavailable", self.c.compareRuns("left", "right"))
        self.assertIn("formulations differ", self.notices[-1])

    def test_static_comparison_full_csv_and_all_frozen_destination_guards(self):
        self.assertTrue(self.c.queryResults("Line", ["L"], ["s_nom_opt"], "", ""))
        self.assertNotIn("unavailable", self.c.compareRuns("left", "right"))
        destination = self.root / "comparison.csv"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(destination), "CSV")):
            self.c.exportComparison()
        frame = pd.read_csv(destination)
        self.assertEqual(frame["delta_right_minus_left"].tolist(), [0])
        self.assertEqual(frame["left_run"].tolist(), ["left"])
        self.assertNotIn("snapshot", frame)
        before, database = self.bytes(), self.c.path.read_bytes()
        for protected in [self.c.path, self.b / "tables" / "Line_static.csv"]:
            with self.subTest(protected=protected), patch.object(
                QFileDialog, "getSaveFileName", return_value=(str(protected), "CSV")
            ):
                self.c.exportComparison()
                self.assertFalse(self.c.exportAnalysis("report"))
        self.assertEqual(before, self.bytes())
        self.assertEqual(database, self.c.path.read_bytes())

    def test_svg_png_html_escape_and_frozen_source_export(self):
        tab=self.c.workspace.active
        charts=query_charts(tab.frame,tab.specs,tab.temporal)
        tab.title="<script>unsafe</script>"
        svg=self.root/"chart.svg";png=self.root/"chart.png";html=self.root/"report.html"
        write_chart(svg,charts);write_chart(png,charts);write_report(html,tab,charts,{"objective":10})
        self.assertTrue(svg.read_text().startswith("<svg"))
        self.assertEqual(png.read_bytes()[:8],b"\x89PNG\r\n\x1a\n")
        content=html.read_text(encoding="utf-8")
        self.assertNotIn("<script>",content)
        self.assertIn("&lt;script&gt;",content)
        before=self.bytes()
        with patch.object(QFileDialog,"getSaveFileName",return_value=(str(self.a/"evil.svg"),"SVG")):
            self.assertFalse(self.c.exportAnalysis("chart"))
        self.assertEqual(before,self.bytes())

    def test_report_controller_selects_active_not_current_run(self):
        self.c.pinQueryTab(self.c.workspace.active_id)
        active=self.c.workspace.active_id
        self.assertTrue(self.c.openRun(str(self.b)))
        self.c.selectQueryTab(active)
        destination=self.root/"chart.svg"
        with patch.object(QFileDialog,"getSaveFileName",return_value=(str(destination),"SVG")):
            self.assertTrue(self.c.exportAnalysis("chart"))
        self.assertTrue(destination.exists())

    def test_annotated_formulation_exact_tokens_not_numeric_coefficients(self):
        (self.a/"model.lp").write_text("min\nobj: +2 x0\ns.t.\nc0: +1 x0 >= 3\nend\n")
        (self.a/"symbols.csv").write_text('kind,symbol,block,coordinates\nvariable,x0,Generator-p,"{}"\nconstraint,c0,Bus-balance,"{}"\n')
        dest=self.root/"readable.txt"
        before=self.bytes();annotate_formulation(self.a,dest)
        self.assertIn("+2 Generator-p[{}]",dest.read_text())
        self.assertIn(">= 3",dest.read_text())
        self.assertEqual(before,self.bytes())
        with self.assertRaises(ValueError):annotate_formulation(self.b,dest)

    def test_background_backup_completion_and_no_gui_thread_save(self):
        destination=self.root/"background.zip"
        with patch.object(QFileDialog,"getSaveFileName",return_value=(str(destination),"ZIP")):
            self.assertTrue(self.c.startBackup())
        self.assertTrue(self.c.state["backupBusy"])
        self.assertFalse(self.c.saveProject())
        self.wait_backup()
        self.assertIsNone(self.c._backup_thread, str(self.notices)+" progress="+str(self.c.backup_progress))
        self.assertTrue(destination.exists())
        with zipfile.ZipFile(destination) as archive:self.assertIn("backup_manifest.json",archive.namelist())

    def test_background_cancel_before_publication_preserves_original(self):
        destination=self.root/"cancel.zip"
        before=self.c.path.read_bytes()
        with patch.object(QFileDialog,"getSaveFileName",return_value=(str(destination),"ZIP")):
            self.assertTrue(self.c.startBackup())
            self.c.cancelBackup()
        self.wait_backup()
        self.assertFalse(destination.exists())
        self.assertEqual(self.c.path.read_bytes(),before)

    def test_sync_backup_cancel_and_progress_preserve_exclusive_publication(self):
        progress=[]
        destination=self.root/"cancel-sync.zip"
        with self.assertRaises(InterruptedError):
            create_backup(self.c.path,destination,progress.append,lambda: bool(progress))
        self.assertFalse(destination.exists())
        self.assertTrue(progress)

    def test_profile_grid_reorders_explicit_timestamps_and_undo(self):
        text=self.c.profileGrid("Bus","A","v_mag_pu_set")
        before=self.c.project.to_dict()
        self.assertTrue(text.startswith("snapshot\tvalue"))
        rows=text.strip().splitlines();rows[1:]=list(reversed(rows[1:]))
        self.assertTrue(self.c.applyProfileGrid("Bus","A","v_mag_pu_set","\n".join(rows)))
        self.assertTrue(self.c.modelHistory(False))
        self.assertEqual(self.c.project.to_dict(),before)

    def test_profile_grid_missing_duplicate_output_and_invalid_value_atomic(self):
        before=self.c.project.to_dict()
        for text in ["snapshot\tvalue\n2026-01-01\t1\n", "snapshot\tvalue\n2026-01-01\tNaN\n2026-01-01T01:00\t2\n"]:
            self.assertFalse(self.c.applyProfileGrid("Bus","A","v_mag_pu_set",text))
        self.assertFalse(self.c.applyProfileGrid("Line","L","p0","snapshot\tvalue\n"))
        self.assertEqual(self.c.project.to_dict(),before)

    def test_invalid_advanced_inputs_does_not_apply_or_add_history(self):
        before=self.c.project.to_dict()
        self.assertFalse(self.c.applyAdvancedInputs('{"weights":[{"objective":-1}]}'))
        self.assertEqual(self.c.project.to_dict(),before)
        self.assertEqual(self.c.model_history.undo,[])


class AdvancedNumericsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="advanced_numeric_",dir=Path(os.environ["LOCALAPPDATA"])/"Temp"/"opencode")
        self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def solve(self,project,label):
        path=self.root/label/"project.sqlite"
        save_project(project,path)
        self.assertEqual(load_project(path).to_dict(),project.to_dict())
        run=prepare_run(path,export_format="lp")
        meta=execute_run(run)
        repo=ResultsRepository(run,json.loads((run/"metadata/catalog.json").read_text()))
        return run,meta,repo

    def test_custom_weights_objective_and_generator_energy_and_emissions(self):
        p=simple_project();p.advanced_inputs={"weights":[dict(objective=2,stores=1,generators=3)]*2}
        run,meta,repo=self.solve(p,"weights")
        self.assertAlmostEqual(meta["objective"],3000)
        metrics=run_metrics(repo,meta)
        self.assertAlmostEqual(metrics["weighted_generation_MWh"],450)
        self.assertAlmostEqual(metrics["weighted_operational_CO2_t"],90)

    def test_period_weights_query_and_exported_period_identity(self):
        p=simple_project();p.advanced_inputs={"periods":[dict(period=2030,objective=1,years=1),dict(period=2040,objective=2,years=2)],"snapshot_periods":[2030,2040]}
        run,meta,repo=self.solve(p,"periods")
        self.assertAlmostEqual(meta["objective"],2250)
        frame=repo.query("Generator",["G"],["p"])[0]
        self.assertEqual(frame["p"].tolist(),[75,75])
        self.assertEqual(frame["period"].tolist(), [2030, 2040])
        self.assertTrue(query_charts(frame, [{"name": "p", "unit": "MW"}], True)[0]["labels"][0].startswith("2030 · "))
        self.assertEqual(pd.read_csv(run/"tables"/"generators__p.csv").columns[:2].tolist(),["period","snapshot"])
        self.assertAlmostEqual(run_metrics(repo,meta)["weighted_operational_CO2_t"],45)

    def test_multi_period_extendable_capacity_and_cost_analytic(self):
        p=simple_project()
        p.object("Generator","G")["attributes"].update(p_nom=0,p_nom_extendable=True,capital_cost=5,build_year=2030,lifetime=20)
        p.profiles=[dict(component="Load",name="D",attribute="p_set",values=[10,20],unit="MW",source="analytic")]
        p.advanced_inputs={"periods":[dict(period=2030,objective=1,years=1),dict(period=2040,objective=2,years=2)],"snapshot_periods":[2030,2040]}
        _,meta,repo=self.solve(p,"investment")
        self.assertAlmostEqual(meta["objective"],800)
        self.assertAlmostEqual(repo.query("Generator",["G"],["p_nom_opt"])[0]["p_nom_opt"].iloc[0],20)

    def test_piecewise_native_curve_keeps_all_attributes_and_matches_integral(self):
        p=simple_project();p.advanced_inputs={"piecewise":[dict(component="Generator",name="G",attribute="marginal_cost",points=[[0,0],[.5,20],[1,50]])]}
        network=build_network(p)
        self.assertEqual(network.generators.at["G","bus"],"B")
        self.assertEqual(network.generators.at["G","p_nom"],100)
        run,meta,repo=self.solve(p,"piecewise")
        self.assertAlmostEqual(meta["objective"],4500)
        self.assertEqual(repo.query("Generator",["G"],["p"])[0]["p"].tolist(),[75,75])
        annotate_formulation(run,self.root/"piecewise-readable.txt")
        self.assertIn("Generator",(self.root/"piecewise-readable.txt").read_text())

    def test_advanced_invalid_shapes_and_unsupported_curve_capabilities(self):
        p=simple_project()
        cases=[{"weights":{}},{"weights":[dict(objective=1,stores=0,generators=1)]*2},
               {"periods":[dict(period=2040,objective=1,years=1)],"snapshot_periods":[2030,2040]},
               {"piecewise":[dict(component="Link",name="L",attribute="efficiency",points=[[0,0],[1,1]])]},
               {"piecewise":[dict(component="Generator",name="G",attribute="marginal_cost",points=[[0,0],[.5,40],[1,20]])]}]
        for case in cases:
            with self.subTest(case=case),self.assertRaises(ValueError):checked_advanced(p,case)

    def test_piecewise_follows_rename_delete_and_core_fails_closed_for_old_readers(self):
        p=simple_project();p.advanced_inputs={"piecewise":[dict(component="Generator",name="G",attribute="marginal_cost",points=[[0,0],[1,20]])]}
        renamed,_=rename_candidate(p,"Generator","G","New")
        self.assertEqual(renamed.advanced_inputs["piecewise"][0]["name"],"New")
        deleted=delete_candidate(renamed,[dict(component="Generator",name="New")])
        self.assertEqual(deleted.advanced_inputs["piecewise"],[])
        path=self.root/"advanced.sqlite";save_project(p,path)
        with closing(sqlite3.connect(path)) as conn:
            payload=json.loads(conn.execute("select value from metadata where key='project'").fetchone()[0])
        self.assertIn("advanced_inputs",payload)  # Older constructor cannot silently drop it.

    def test_scale_factory_deterministic_and_hundreds_of_buses_build(self):
        a,b=scale_project(200,24),scale_project(200,24)
        first,second=a.to_dict(),b.to_dict();first.pop("project_id");second.pop("project_id")
        self.assertEqual(first,second)
        network=build_network(a)
        self.assertEqual(len(network.buses),200)
        self.assertEqual(len(network.snapshots),24)

    def test_batched_builder_matches_previous_scalar_static_and_profile_tables(self):
        import pypsa
        p=scale_project(20,24)
        expected=pypsa.Network(name=p.name)
        expected.set_snapshots(pd.DatetimeIndex(p.snapshots,name="snapshot"),default_snapshot_weightings=1.0)
        order={"Carrier":0,"Bus":2}
        for record in sorted(p.objects,key=lambda r:order.get(r["component"],5)):
            add_component(expected,record)
        for profile in p.profiles:
            expected.components[profile["component"]].dynamic[profile["attribute"]][profile["name"]]=pd.Series(profile["values"],index=expected.snapshots)
        actual=build_network(p)
        pd.testing.assert_frame_equal(actual.snapshot_weightings,expected.snapshot_weightings)
        for key in actual.components.keys():
            pd.testing.assert_frame_equal(actual.components[key].static,expected.components[key].static)
            for attr in actual.components[key].dynamic:
                pd.testing.assert_frame_equal(actual.components[key].dynamic[attr],expected.components[key].dynamic[attr])

    def test_custom_storage_elapsed_weights_independent_energy_balance(self):
        p=simple_project();p.upsert("Carrier","battery",{})
        p.object("Load","D")["attributes"]["p_set"]=0
        p.upsert("StorageUnit","Battery",dict(bus="B",carrier="battery",p_nom=10,max_hours=1,cyclic_state_of_charge=True))
        p.profiles=[dict(component="Load",name="D",attribute="p_set",values=[0,5],unit="MW",source="analytic"),
                    dict(component="Generator",name="G",attribute="p_max_pu",values=[1,0],unit="per unit",source="analytic")]
        p.advanced_inputs={"weights":[dict(objective=.5,stores=.5,generators=.5),dict(objective=1,stores=1,generators=1)]}
        _,meta,repo=self.solve(p,"elapsed")
        self.assertAlmostEqual(meta["objective"],50)
        energy=repo.query("StorageUnit",["Battery"],["state_of_charge"])[0]["state_of_charge"].tolist()
        self.assertEqual(energy,[5,0])
