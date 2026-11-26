import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: tools
    required property var theme
    objectName: "extendedTools"
    title: "Scenarios, modeling controls, diagnostics and analytics"
    modal: true; focus: true; anchors.centerIn: parent
    width: Math.min(parent.width-40,1120); height: Math.min(parent.height-40,780)
    property string projectId: ""
    property string scenarioBaseline: ""
    property bool scenarioDirty: false
    property bool loading: false
    property string controlBaseline: ""
    property string controlOwner: ""
    property var state: backend.studyState
    component Field: TextField { color: tools.theme.ink; placeholderTextColor: tools.theme.muted }
    component Note: Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: tools.theme.muted; textFormat: Text.PlainText }
    component Section: TabButton {
        id: tab
        contentItem: Label { text: tab.text; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; color: tab.hovered || tab.down ? tools.theme.primaryText : tools.theme.ink }
        background: Rectangle { color: tab.hovered || tab.down ? tools.theme.primary : tab.checked ? tools.theme.selected : tools.theme.field; border.color: tools.theme.border }
    }
    function reloadScenarios() {
        loading=true; scenarioEditor.text=backend.scenarioDefinitions(); scenarioBaseline=scenarioEditor.text
        scenarioDirty=false; loading=false
    }
    onOpened: {
        if (projectId!==backend.uiState.projectId) {
            projectId=backend.uiState.projectId; scenarioDirty=false
            controls.text=""; controlBaseline=""; controlOwner=""; diagnostics.text=""
        }
        if (!scenarioDirty) reloadScenarios()
    }
    contentItem: ColumnLayout {
        TabBar { id: sections; objectName: "extensionSections"; Layout.fillWidth: true
            Section { text: "Scenarios / batch"; objectName: "extensionTab0" }
            Section { text: "Modeling controls"; objectName: "extensionTab1" }
            Section { text: "Diagnostics"; objectName: "extensionTab2" }
            Section { text: "Results analytics"; objectName: "extensionTab3" }
        }
        StackLayout { currentIndex: sections.currentIndex; Layout.fillWidth: true; Layout.fillHeight: true
            ColumnLayout {
                Note { text: "Scenarios are named changes to a saved base, not edits to it. Apply stores definitions; Save persists them. Start validates every variation, freezes separate inputs and queues one HiGHS worker at a time. Failed scenarios retain diagnostics; the queue continues. Stop cancels active and waiting scenarios. No automatic resume after restart." }
                Note { text: 'JSON example: [{"id":"base","name":"Base","changes":[]},{"id":"high","name":"High demand","changes":[{"component":"Load","name":"City demand","attribute":"p_set","operation":"scale","value":1.1}]}]. Scale applies to matching profiles too; no hidden scalar override.' }
                ScrollView { Layout.fillWidth: true; Layout.fillHeight: true
                    TextArea { id: scenarioEditor; objectName: "scenarioEditor"; selectByMouse: true; color: tools.theme.ink; font.family: "Consolas"; font.pixelSize: 12; onTextChanged: if (!tools.loading) tools.scenarioDirty=true }
                }
                RowLayout {
                    Button { objectName: "applyScenariosButton"; text: "Apply definitions"; enabled: !backend.uiState.busy; onClicked: { if (tools.scenarioBaseline!==backend.scenarioDefinitions()) { scenarioMessage.text="Stale definitions: copy draft, then reload."; return } if (backend.applyScenarios(scenarioEditor.text)) { tools.reloadScenarios(); scenarioMessage.text="Applied; Save persists definitions." } } }
                    Button { text: "Discard / reload"; onClicked: tools.reloadScenarios() }
                    ThemedSelect { id: batchExport; theme: tools.theme; model: ["none","lp","mps"]; implicitWidth: 90 }
                    Button { objectName: "startBatchButton"; text: "Save base + start batch"; enabled: !backend.uiState.busy && !tools.scenarioDirty; onClicked: backend.startScenarioBatch(batchExport.currentText) }
                    Button { objectName: "stopBatchButton"; text: "Stop batch"; enabled: tools.state.batchActive; onClicked: backend.cancelRun() }
                }
                Note { id: scenarioMessage }
                ScrollView { Layout.fillWidth: true; Layout.preferredHeight: 105
                    TextArea { objectName: "batchReadout"; readOnly: true; selectByMouse: true; color: tools.theme.ink; font.family: "Consolas"; font.pixelSize: 11; text: tools.state.batchRows.map(function(r) { return r.scenario+" | "+r.status+" | objective "+r.objective+" | "+r.run }).join("\n") }
                }
            }
            ColumnLayout {
                Note { text: "Load a curated subset of an existing object's controls, edit JSON and Apply atomically. Unlisted properties are retained; null restores native optional defaults. Units/defaults and full field explanations are in Help (F1). Profiles override scalar bounds; these controls do not remove profiles. Apply supports model Undo/recovery; closing retains this session draft only." }
                RowLayout {
                    ThemedSelect { id: controlClass; objectName: "controlClass"; theme: tools.theme; model: ["Generator","StorageUnit","GlobalConstraint"]; Layout.preferredWidth: 180 }
                    Field { id: controlName; objectName: "controlName"; placeholderText: "Existing object name"; Layout.fillWidth: true }
                    Button { objectName: "loadControlsButton"; text: "Load controls"; onClicked: { controls.text=backend.modelingControls(controlClass.currentText,controlName.text); tools.controlBaseline=controls.text; tools.controlOwner=JSON.stringify([controlClass.currentText,controlName.text]) } }
                }
                Note { text: "Generator: commitment, startup/shutdown/standby costs, minimum up/down steps and ramp limits. StorageUnit: MW capacity, max_hours (h), efficiencies/losses and initial/cyclic MWh. GlobalConstraint: native type, carrier coefficient, sense and bound. This is native linear/MILP modeling, not security or AC validation." }
                ScrollView { Layout.fillWidth: true; Layout.fillHeight: true
                    TextArea { id: controls; objectName: "modelingControlsEditor"; property string referenceComponent: controlClass.currentText; selectByMouse: true; color: tools.theme.ink; font.family: "Consolas"; font.pixelSize: 12 }
                }
                RowLayout {
                    Button { objectName: "applyControlsButton"; text: "Apply modeling controls"; enabled: !backend.uiState.busy; onClicked: { if (tools.controlOwner!==JSON.stringify([controlClass.currentText,controlName.text]) || tools.controlBaseline!==backend.modelingControls(controlClass.currentText,controlName.text)) { controlMessage.text="Load controls first; owner or values changed."; return } if (backend.applyModelingControls(controlClass.currentText,controlName.text,controls.text)) { tools.controlBaseline=backend.modelingControls(controlClass.currentText,controlName.text); controlMessage.text="Applied. Save persists; model Undo available." } } }
                    Note { id: controlMessage }
                }
                Note { text: "Native operating/investment/conversion curves remain in Saved analysis tools → Time / curves. Only validated curve classes are accepted; see the integrated stage guide for exact axes and restrictions." }
            }
            ColumnLayout {
                Note { text: "Structural and capacity screens explain likely problems; they are not an infeasibility proof, IIS, AC validation or automatic repair. Current-model checks and saved-run failure advice are separate, read-only operations." }
                RowLayout {
                    Button { objectName: "modelDiagnosticsButton"; text: "Inspect current model"; onClicked: diagnostics.text=backend.modelDiagnosticsText() }
                    Button { objectName: "runAdviceButton"; text: "Explain loaded run failure"; onClicked: diagnostics.text=backend.runFailureAdvice() }
                }
                ScrollView { Layout.fillWidth: true; Layout.fillHeight: true
                    TextArea { id: diagnostics; objectName: "diagnosticsReadout"; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; color: tools.theme.ink; font.family: "Consolas"; font.pixelSize: 12 }
                }
            }
            ColumnLayout {
                Note { text: "Uses the active executed Results query and its frozen run, never current model edits. Energy integrates temporal MW with the selected weights and period years; signed power stays signed. Duration ranks paired power/hours. Storage summarizes MWh levels without integration. Options are drafts until Compute; the captured output is described below." }
                RowLayout {
                    ThemedSelect { id: analyticMode; objectName: "analyticMode"; theme: tools.theme; model: ["energy","duration","storage","comparison"]; Layout.fillWidth: true }
                    ThemedSelect { id: grouping; objectName: "analyticGrouping"; theme: tools.theme; model: ["object","carrier","period","component"]; Layout.fillWidth: true }
                    ThemedSelect { id: weighting; objectName: "analyticWeighting"; theme: tools.theme; model: ["generators","stores"]; Layout.fillWidth: true }
                    Button { objectName: "computeAnalyticsButton"; text: "Compute"; onClicked: backend.analyzeQuery(analyticMode.currentText,grouping.currentText,weighting.currentText) }
                }
                ScrollView { id: analyticsScroll; objectName: "analyticsScroll"; Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth
                    ColumnLayout { width: analyticsScroll.availableWidth; spacing: 8
                        Note { text: tools.state.analyticsDescription }
                        Repeater { model: tools.state.analyticsCharts
                            QueryChart { required property var modelData; required property int index; objectName: "analyticsPlot-"+index; chart: modelData; theme: tools.theme; Layout.fillWidth: true; Layout.preferredHeight: 260 }
                        }
                        TextArea { objectName: "analyticsReadout"; Layout.fillWidth: true; readOnly: true; selectByMouse: true; color: tools.theme.ink; font.family: "Consolas"; font.pixelSize: 11; text: tools.state.analyticsPreview }
                    }
                }
                RowLayout {
                    Field { id: reportTitle; text: "Study analysis"; placeholderText: "Report title"; Layout.fillWidth: true }
                    SpinBox { id: reportRows; from: 1; to: 1000; value: 100; editable: true; implicitWidth: 115 }
                    AtlasCheckBox { theme: tools.theme; id: reportCharts; text: "Charts"; checked: true }
                    Button { text: "Full CSV…"; onClicked: backend.exportStudyResult("csv",reportTitle.text,reportRows.value,reportCharts.checked) }
                    Button { text: "SVG / PNG…"; onClicked: backend.exportStudyResult("chart",reportTitle.text,reportRows.value,reportCharts.checked) }
                    Button { text: "HTML report…"; onClicked: backend.exportStudyResult("report",reportTitle.text,reportRows.value,reportCharts.checked) }
                }
                Note { text: "Computed tables export fully to CSV. Screens show 100 rows; charts are bounded previews. Report title, row limit (1–1000) and chart inclusion are configurable. Exports cannot overwrite project/frozen runs." }
            }
        }
        Button { Layout.alignment: Qt.AlignRight; text: "Close (retain session drafts)"; onClicked: tools.close() }
    }
}
