import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: tools
    required property var theme
    objectName: "studyTools"
    title: "Study tools · saved analysis, comparison and advanced inputs"
    modal: true; focus: true
    anchors.centerIn: parent
    width: Math.min(parent.width-40,1120); height: Math.min(parent.height-40,760)
    property bool inputDirty: false
    property string draftProject: ""
    property bool loading: false
    property string advancedBaseline: ""
    property string profileBaseline: ""
    property string profileOwner: ""
    component StudyField: TextField {
        color: tools.theme.ink
        placeholderTextColor: tools.theme.muted
    }
    component StudyTab: TabButton {
        id: tab
        contentItem: Label { text: tab.text; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; color: tab.hovered || tab.down ? tools.theme.primaryText : tools.theme.ink }
        background: Rectangle { color: tab.hovered || tab.down ? tools.theme.primary : tab.checked ? tools.theme.selected : tools.theme.field; border.color: tab.activeFocus ? tools.theme.accent : tools.theme.border }
    }
    function refresh() {
        if (draftProject !== backend.uiState.projectId) {
            // A new project must never inherit an old advanced-input draft.
            inputDirty=false
            profileText.text=""; profileName.text=""; profileBaseline=""; profileOwner=""
        }
        if (!inputDirty) {
            loading=true; advanced.text=backend.advancedInputs(); advancedBaseline=advanced.text; loading=false
            draftProject=backend.uiState.projectId
        }
    }
    onOpened: refresh()
    contentItem: ColumnLayout {
        TabBar { id: sections; objectName: "studySections"; Layout.fillWidth: true
            StudyTab { text: "Saved analysis"; objectName: "studyTab0" }
            StudyTab { text: "Compare runs"; objectName: "studyTab1" }
            StudyTab { text: "Time / curves"; objectName: "studyTab2" }
            StudyTab { text: "Profile grid"; objectName: "studyTab3" }
            StudyTab { text: "Export / backup"; objectName: "studyTab4" }
        }
        StackLayout {
            currentIndex: sections.currentIndex; Layout.fillWidth: true; Layout.fillHeight: true
            ColumnLayout {
                Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: tools.theme.muted; text: "Save the ordered session query cards, source run names, chart styles, active card and Data/Charts views. Save project persists these definitions, not copied results. Restoring validates every card before replacing tabs and never solves. Copy matching runs when moving a project." }
                RowLayout {
                    StudyField { id: dashboardName; objectName: "analysisName"; placeholderText: "Dashboard title"; Layout.fillWidth: true }
                    Button { objectName: "saveAnalysisButton"; text: "Capture session dashboard"; enabled: !backend.uiState.busy; onClicked: backend.saveAnalysis(dashboardName.text) }
                    Button { text: "Save project"; enabled: !backend.uiState.busy; onClicked: backend.saveProject() }
                }
                ListView { id: saved; objectName: "savedAnalysisList"; Layout.fillWidth: true; Layout.fillHeight: true; model: backend.savedAnalyses; clip: true; spacing: 6
                    ScrollBar.vertical: ScrollBar { }
                    delegate: RowLayout {
                        required property int index
                        required property var modelData
                        width: ListView.view.width
                        Label { text: modelData.title; textFormat: Text.PlainText; color: tools.theme.ink; Layout.fillWidth: true; elide: Text.ElideRight }
                        Button { text: "Restore"; objectName: "restoreAnalysis-"+index; enabled: !backend.uiState.busy; onClicked: backend.restoreAnalysis(index) }
                        Button { text: "↑"; enabled: index>0 && !backend.uiState.busy; onClicked: backend.arrangeAnalysis(index,-1) }
                        Button { text: "↓"; enabled: index<saved.count-1 && !backend.uiState.busy; onClicked: backend.arrangeAnalysis(index,1) }
                        Button { text: "Remove definition"; enabled: !backend.uiState.busy; onClicked: backend.arrangeAnalysis(index,0) }
                    }
                }
                Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: tools.theme.muted; text: "Definitions are optional project metadata. Their order is the dashboard library order; session tab order is captured inside each dashboard. Removing a definition never deletes runs. Model Undo does not revert analysis definitions." }
            }
            ColumnLayout {
                Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: tools.theme.muted; text: "Compare the active executed query's captured criteria, not draft selections. Choose successful run folder names from this project. Axes, period/snapshot weights, property kinds, units and selected identities must match. Delta = right − left; no automatic unit/currency conversion or missing-value filling." }
                RowLayout {
                    ThemedSelect { id: leftRun; objectName: "compareLeft"; theme: tools.theme; Layout.fillWidth: true; model: backend.uiState.runs.filter(function(r) { return r.status==='succeeded' }).map(function(r) { return r.name }) }
                    ThemedSelect { id: rightRun; objectName: "compareRight"; theme: tools.theme; Layout.fillWidth: true; model: leftRun.model }
                    Button { objectName: "compareRunsButton"; text: "Compare"; onClicked: comparison.text=backend.compareRuns(leftRun.currentText,rightRun.currentText) }
                    Button { text: "Export full CSV…"; onClicked: backend.exportComparison() }
                }
                ScrollView { Layout.fillWidth: true; Layout.fillHeight: true
                    TextArea { id: comparison; objectName: "comparisonReadout"; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; color: tools.theme.ink; font.family: "Consolas"; font.pixelSize: 11 }
                }
            }
            ColumnLayout {
                Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: tools.theme.muted; text: "Advanced JSON is data, never code. weights: one row per timestamp (objective cost, stores elapsed hours, generators energy). periods: ordered integer period/objective/years rows; snapshot_periods: one ordered assignment per unique timestamp. No repeated timestamps or implicit discount/replication. Empty arrays restore interval defaults. Save project after Apply." }
                RowLayout {
                    Label { text: "Fill all snapshot weights:"; color: tools.theme.ink }
                    StudyField { id: objectiveWeight; placeholderText: "objective"; text: "1"; Layout.preferredWidth: 90 }
                    StudyField { id: storageWeight; placeholderText: "stores (h)"; text: "1"; Layout.preferredWidth: 90 }
                    StudyField { id: energyWeight; placeholderText: "generators"; text: "1"; Layout.preferredWidth: 90 }
                    Button { text: "Stage weights"; onClicked: { try { var a=JSON.parse(advanced.text); a.weights=Array.from({length:backend.uiState.snapshotCount},function() { return {objective:Number(objectiveWeight.text),stores:Number(storageWeight.text),generators:Number(energyWeight.text)} }); advanced.text=JSON.stringify(a,null,2) } catch(e) { inputMessage.text=String(e) } } }
                }
                ScrollView { Layout.fillWidth: true; Layout.fillHeight: true
                    TextArea { id: advanced; objectName: "advancedInputsEditor"; selectByMouse: true; color: tools.theme.ink; font.family: "Consolas"; font.pixelSize: 12; onTextChanged: if (!tools.loading) tools.inputDirty=true }
                }
                Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: tools.theme.muted; text: 'Curves: fixed Generator marginal_cost; extendable Generator/Line/Link capital_cost; fixed forward two-port Link efficiency. Cost y values are preceding-segment prices, not total costs. Dispatch x=p/p_nom; investment x=total nominal capacity (Line: native MVA). Capital curves need a finite maximum and prices including fixed O&M. Efficiency points interpolate output power x*eta*p_nom, NOT eta. Example dispatch: {"component":"Generator","name":"Thermal","attribute":"marginal_cost","points":[[0,0],[0.5,20],[1,50]]}. Exact restrictions/examples: stage guide; other types are rejected.' }
                RowLayout {
                    Button { objectName: "applyAdvancedButton"; text: "Apply advanced inputs"; enabled: !backend.uiState.busy; onClicked: { if (tools.advancedBaseline!==backend.advancedInputs()) { inputMessage.text="Stale draft: copy it, then Discard/reload before applying."; return } if (backend.applyAdvancedInputs(advanced.text)) { tools.inputDirty=false; tools.refresh(); inputMessage.text="Applied. Save persists; model Undo is available." } } }
                    Button { text: "Discard this draft"; onClicked: { tools.inputDirty=false; tools.refresh() } }
                    Label { id: inputMessage; Layout.fillWidth: true; wrapMode: Text.WordWrap; color: tools.theme.muted }
                }
            }
            ColumnLayout {
                Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: tools.theme.muted; text: "Tabular time-series editing: snapshot/value TSV, copied from a spreadsheet or edited here. Exact timestamps, explicit numeric units, atomic Apply; no resampling. This draft stays inside this dialog until Apply or Discard. Profile values override scalar inputs." }
                RowLayout {
                    StudyField { id: profileClass; objectName: "gridProfileClass"; text: "Load"; placeholderText: "Component"; Layout.preferredWidth: 130 }
                    StudyField { id: profileName; objectName: "gridProfileName"; placeholderText: "Existing object name"; Layout.fillWidth: true }
                    StudyField { id: profileAttribute; objectName: "gridProfileAttribute"; text: "p_set"; placeholderText: "Varying attribute"; Layout.preferredWidth: 150 }
                    Button { objectName: "loadProfileGridButton"; text: "Load values"; onClicked: { profileText.text=backend.profileGrid(profileClass.text,profileName.text,profileAttribute.text); tools.profileBaseline=profileText.text; tools.profileOwner=JSON.stringify([profileClass.text,profileName.text,profileAttribute.text]) } }
                }
                ScrollView { Layout.fillWidth: true; Layout.fillHeight: true
                    TextArea { id: profileText; objectName: "profileGridEditor"; color: tools.theme.ink; selectByMouse: true; font.family: "Consolas"; font.pixelSize: 12 }
                }
                Button { objectName: "applyProfileGridButton"; text: "Apply complete profile"; enabled: !backend.uiState.busy; onClicked: { if (tools.profileOwner!==JSON.stringify([profileClass.text,profileName.text,profileAttribute.text]) || tools.profileBaseline!==backend.profileGrid(profileClass.text,profileName.text,profileAttribute.text)) { profileMessage.text="Load values first; this draft is stale or belongs to another object."; return } if (backend.applyProfileGrid(profileClass.text,profileName.text,profileAttribute.text,profileText.text)) { tools.profileBaseline=backend.profileGrid(profileClass.text,profileName.text,profileAttribute.text); profileMessage.text="Applied. Save persists; model Undo is available." } } }
                Label { id: profileMessage; color: tools.theme.muted; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            }
            ColumnLayout {
                Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: tools.theme.muted; text: "Exports use the active executed query and its frozen source, not current draft selections. HTML is self-contained with escaped data; charts use the same bounded preview as the GUI. Full numeric data remains available through CSV. Readable formulation annotates the actual saved LP/MPS with symbols.csv; choose an exported run first." }
                Button { text: "Export charts SVG / PNG…"; onClicked: backend.exportAnalysis("chart") }
                Button { text: "Export local HTML study report…"; onClicked: backend.exportAnalysis("report") }
                Button { text: "Export readable LP/MPS annotation…"; onClicked: backend.exportAnalysis("formulation") }
                Button { text: "Start background SAVED-project backup…"; enabled: !backend.uiState.busy; onClicked: backend.startBackup() }
                ProgressBar { Layout.fillWidth: true; from: 0; to: 100; value: backend.uiState.backupProgress; visible: backend.uiState.backupBusy }
                Button { text: "Cancel backup"; enabled: backend.uiState.backupBusy; onClicked: backend.cancelBackup() }
                Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: tools.theme.muted; text: "Backup stays off the GUI thread, streams ZIP entries and supports cancellation before publication. It includes saved inputs and matching runs, not pending edits. Wait for completion/cancellation before saving, closing, replacing or solving. Recovery remains separate." }
                Item { Layout.fillHeight: true }
            }
        }
        Button { Layout.alignment: Qt.AlignRight; text: "Close (retain this session's drafts)"; onClicked: tools.close() }
    }
}
