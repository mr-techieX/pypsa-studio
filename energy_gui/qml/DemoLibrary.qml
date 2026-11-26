import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: library
    required property var theme
    property var catalogue: backend.demoCatalogue()
    property int selection: 1
    readonly property var chosen: catalogue[selection] || ({})
    objectName: "demoLibrary"
    title: "Demo model library · deterministic, use-case-led studies"
    modal: true; focus: true
    anchors.centerIn: parent
    width: Math.min(parent.width-60,1060); height: Math.min(parent.height-60,680)
    enter: Transition { }
    exit: Transition { }
    contentItem: ColumnLayout {
        spacing: 12
        Label { Layout.fillWidth: true; color: library.theme.muted; wrapMode: Text.WordWrap
            text: "Choose a model to replace the current project (normal draft/unsaved-change prompts apply). No solve starts automatically. Synthetic cases demonstrate real-world use cases, not real utility assets. The attributed IEEE/PGLib case is a lossless DC adaptation."
        }
        RowLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 18
            ListView {
                objectName: "demoModelList"; Layout.preferredWidth: 355; Layout.fillHeight: true; clip: true
                model: library.catalogue; spacing: 6
                ScrollBar.vertical: ScrollBar { }
                delegate: ItemDelegate {
                    required property int index
                    required property var modelData
                    objectName: "demoModel-" + modelData.id
                    width: ListView.view.width; height: 58
                    highlighted: library.selection === index
                    contentItem: Label { text: modelData.title + "\n" + modelData.hours + " hourly snapshot(s)"; color: library.theme.ink; wrapMode: Text.WordWrap; font.pixelSize: 12 }
                    background: Rectangle { radius: 6; color: parent.highlighted ? library.theme.selected : parent.hovered ? library.theme.hover : library.theme.field; border.color: library.theme.border }
                    onClicked: library.selection=index
                }
            }
            ScrollView {
                id: demoDetails
                Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth
                ColumnLayout {
                    width: demoDetails.availableWidth; spacing: 14
                    Label { Layout.fillWidth: true; text: library.chosen.title || ""; color: library.theme.ink; font.pixelSize: 20; font.bold: true; wrapMode: Text.WordWrap }
                    Label { Layout.fillWidth: true; text: library.chosen.summary || ""; color: library.theme.ink; wrapMode: Text.WordWrap }
                    Label { text: "WHAT TO TEST"; color: library.theme.accent; font.bold: true }
                    Label { Layout.fillWidth: true; text: library.chosen.expected || ""; color: library.theme.ink; wrapMode: Text.WordWrap }
                    Label { text: "ASSUMPTIONS & PROVENANCE"; color: library.theme.accent; font.bold: true }
                    Label { Layout.fillWidth: true; text: library.chosen.assumptions || ""; color: library.theme.muted; wrapMode: Text.WordWrap }
                    Label { Layout.fillWidth: true; text: "All profiles are fixed and reproducible. Loaded models include study notes in SQLite/frozen inputs. Save to your own project file before running. For larger schematics, use Network → Fit, then zoom/pan to inspect individual objects."; color: library.theme.muted; wrapMode: Text.WordWrap }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Button { objectName: "demoLoadSelected"; text: "Load selected model"; enabled: !backend.uiState.busy; onClicked: if (backend.loadDemoModel(library.chosen.id)) library.close() }
            Item { Layout.fillWidth: true }
            Button { objectName: "demoCancel"; text: "Cancel"; onClicked: library.close() }
        }
    }
}
