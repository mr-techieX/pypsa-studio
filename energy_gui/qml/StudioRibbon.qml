import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: ribbon
    required property var theme
    required property var pages
    required property int page
    property var state: backend.uiState
    property var helpers: backend.helperState
    signal navigate(int index)
    signal spreadsheet()
    signal inspector()
    signal exitRequested()
    signal helpRequested()
    signal runRequested()
    signal studyRequested()
    signal extendedRequested()
    objectName: "studioRibbon"
    implicitHeight: 84; color: theme.panel
    component Divider: Rectangle {
        implicitWidth: 1; implicitHeight: 20; color: ribbon.theme.border; opacity: 0.65
        Layout.leftMargin: 9; Layout.rightMargin: 9
    }
    component CommandMenu: Menu {
        padding: 6
        implicitWidth: 370
        background: Rectangle { radius: 7; color: ribbon.theme.panel; border.color: ribbon.theme.border }
    }
    component CommandItem: MenuItem {
        id: command
        property string shortcutLabel: ""
        hoverEnabled: true
        readonly property bool emphasized: enabled && (highlighted || hovered || down)
        contentItem: Text {
            text: command.text + (command.shortcutLabel ? "    " + command.shortcutLabel : ""); font: command.font
            // Bind foreground and background to the same state. The platform
            // MenuItem style can otherwise retain dark text on its dark highlight.
            color: !command.enabled ? ribbon.theme.muted
                   : command.emphasized ? ribbon.theme.primaryText : ribbon.theme.ink
            verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 4
            color: command.emphasized ? ribbon.theme.primary : ribbon.theme.panel
        }
    }
    ColumnLayout {
        anchors.fill: parent; anchors.leftMargin: 24; anchors.rightMargin: 24; spacing: 0
        RowLayout {
            Layout.fillWidth: true; Layout.preferredHeight: 38; spacing: 3
            RibbonButton { id: fileButton; objectName: "ribbonFile"; theme: ribbon.theme; symbol: "file"; text: "File"; menuButton: true; hint: "New, open and save projects"; onClicked: fileMenu.popup(fileButton,0,height) }
            Divider { }
            Repeater {
                model: ribbon.pages
                delegate: Button {
                    required property int index
                    required property string modelData
                    objectName: "ribbonPage-" + index
                    text: modelData; flat: true; implicitHeight: 38
                    leftPadding: 13; rightPadding: 13; focusPolicy: Qt.StrongFocus
                    Accessible.name: modelData + " workspace"
                    Accessible.role: Accessible.PageTab
                    contentItem: Label {
                        text: modelData; color: ribbon.page === index ? ribbon.theme.ink : ribbon.theme.muted
                        font.pixelSize: 12; font.weight: ribbon.page === index ? Font.DemiBold : Font.Normal
                        verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignHCenter
                    }
                    background: Rectangle {
                        radius: 4
                        color: ribbon.page === index ? ribbon.theme.selected : parent.hovered || parent.activeFocus ? ribbon.theme.hover : "transparent"
                        Rectangle {
                            anchors.bottom: parent.bottom; anchors.horizontalCenter: parent.horizontalCenter
                            width: parent.width - 20; height: 3; radius: 1
                            color: ribbon.theme.focus; visible: ribbon.page === index
                        }
                        border.color: parent.activeFocus ? ribbon.theme.accent : "transparent"
                    }
                    onClicked: ribbon.navigate(index)
                }
            }
            Item { Layout.fillWidth: true }
            RibbonButton { id: helpButton; objectName: "ribbonHelp"; theme: ribbon.theme; symbol: "help"; text: "Help"; menuButton: true; hint: "Local references · F1 for the focused property"; onClicked: helpMenu.popup(helpButton,width-helpMenu.width,height) }
        }
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: ribbon.theme.border; opacity: 0.6 }
        RowLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 4
            RibbonButton { id: modelButton; objectName: "ribbonModel"; theme: ribbon.theme; symbol: "model"; text: "Model"; menuButton: true; hint: "Model editors and visibility configuration"; onClicked: modelMenu.popup(modelButton,0,height) }
            RibbonButton { id: dataButton; objectName: "ribbonData"; theme: ribbon.theme; symbol: "data"; text: "Data"; menuButton: true; hint: "Spreadsheet, profiles and batch history"; onClicked: dataMenu.popup(dataButton,0,height) }
            Divider { }
            RibbonButton { objectName: "ribbonValidate"; theme: ribbon.theme; symbol: "check"; text: "Validate"; enabled: !ribbon.state.busy; hint: "Check current model inputs"; onClicked: backend.validate() }
            RibbonButton { id: solveButton; objectName: "ribbonSolve"; theme: ribbon.theme; symbol: "results"; text: "Run tools"; menuButton: true; hint: "Run configuration, history and saved results"; onClicked: solveMenu.popup(solveButton,0,height) }
            Item { Layout.fillWidth: true }
            Rectangle {
                implicitWidth: status.implicitWidth + 22; implicitHeight: 26; radius: 13
                color: ribbon.theme.field
                Label {
                    id: status; anchors.centerIn: parent; color: ribbon.theme.muted; font.pixelSize: 11
                    text: ribbon.state.busy ? "Run in progress" : ribbon.state.sheetDirty || ribbon.helpers.settingsDirty || ribbon.helpers.csvDirty ? "Draft pending" : ribbon.state.dirty ? "Unsaved changes" : "All changes saved"
                }
            }
            Divider { }
            RibbonButton { objectName: "ribbonRun"; theme: ribbon.theme; symbol: "run"; text: "Run model"; primary: true; enabled: !ribbon.state.busy; hint: "Run the current model with HiGHS"; onClicked: ribbon.runRequested() }
        }
    }
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: ribbon.theme.border }
    CommandMenu {
        id: fileMenu
        objectName: "ribbonFileMenu"
        CommandItem { text: "New project"; shortcutLabel: "Ctrl+N"; enabled: !ribbon.state.busy; onTriggered: backend.newProject() }
        CommandItem { text: "Open project…"; shortcutLabel: "Ctrl+O"; enabled: !ribbon.state.busy; onTriggered: backend.openProject() }
        CommandItem { objectName: "openNetcdfResults"; text: "Open results (.nc)…"; enabled: !ribbon.state.busy; onTriggered: backend.browseNetcdfResults() }
        CommandItem { objectName: "saveProjectCommand"; text: "Save project"; shortcutLabel: "Ctrl+S"; enabled: !ribbon.state.busy; onTriggered: backend.saveProject() }
        CommandItem { objectName: "backupProjectCommand"; text: "Backup saved project + runs…"; enabled: !ribbon.state.busy; onTriggered: backend.backupProject() }
        CommandItem { objectName: "recoverProjectCommand"; text: "Recover applied changes…"; enabled: !ribbon.state.busy; onTriggered: backend.recoverProject() }
        MenuSeparator { }
        CommandItem { text: "Exit"; onTriggered: ribbon.exitRequested() }
        MenuSeparator { }
        CommandItem { objectName: "backgroundBackupCommand"; text: "Background backup…"; enabled: !ribbon.state.busy; onTriggered: backend.startBackup() }
        CommandItem { text: "Cancel background backup"; enabled: ribbon.state.backupBusy; onTriggered: backend.cancelBackup() }
    }
    CommandMenu {
        id: modelMenu
        objectName: "ribbonModelMenu"
        CommandItem { text: "Project and snapshots"; onTriggered: ribbon.navigate(0) }
        CommandItem { text: "Object inspector"; onTriggered: ribbon.inspector() }
        CommandItem { text: "Network schematic"; onTriggered: ribbon.navigate(3) }
        CommandItem { text: "Configure visible categories / properties…"; onTriggered: ribbon.navigate(6) }
        MenuSeparator { }
        CommandItem { text: "Validate model"; onTriggered: backend.validate() }
    }
    CommandMenu {
        id: dataMenu
        objectName: "ribbonDataMenu"
        CommandItem { text: "Open object spreadsheet"; onTriggered: ribbon.spreadsheet() }
        CommandItem { text: "Profiles / CSV import"; onTriggered: ribbon.navigate(2) }
        MenuSeparator { }
        CommandItem { text: "Copy object table as TSV"; onTriggered: backend.copySheet() }
        CommandItem { text: "Undo applied spreadsheet batch"; enabled: ribbon.state.sheetCanUndo; onTriggered: backend.sheetHistory(false) }
        CommandItem { text: "Redo spreadsheet batch"; enabled: ribbon.state.sheetCanRedo; onTriggered: backend.sheetHistory(true) }
        MenuSeparator { }
        CommandItem { objectName: "modelUndoCommand"; text: "Undo model edit" + (ribbon.state.modelUndoLabel ? " · " + ribbon.state.modelUndoLabel : ""); shortcutLabel: "Ctrl+Z"; enabled: ribbon.state.modelCanUndo; onTriggered: backend.modelHistory(false) }
        CommandItem { objectName: "modelRedoCommand"; text: "Redo model edit" + (ribbon.state.modelRedoLabel ? " · " + ribbon.state.modelRedoLabel : ""); shortcutLabel: "Ctrl+Y / Ctrl+Shift+Z"; enabled: ribbon.state.modelCanRedo; onTriggered: backend.modelHistory(true) }
    }
    CommandMenu {
        id: solveMenu
        objectName: "ribbonSolveMenu"
        CommandItem { text: "Run configuration and history"; onTriggered: ribbon.navigate(4) }
        CommandItem { text: "Stop active run"; enabled: ribbon.state.busy; onTriggered: backend.cancelRun() }
        MenuSeparator { }
        CommandItem { text: "Results explorer"; onTriggered: ribbon.navigate(5) }
        CommandItem { text: "Browse saved run…"; enabled: !ribbon.state.busy; onTriggered: backend.browseRun() }
        CommandItem { text: "Refresh run history"; onTriggered: backend.refreshRuns() }
        MenuSeparator { }
        CommandItem { objectName: "studyToolsCommand"; text: "Saved analysis / comparison / advanced inputs…"; onTriggered: ribbon.studyRequested() }
        CommandItem { objectName: "extendedToolsCommand"; text: "Scenarios / modeling / diagnostics / analytics…"; onTriggered: ribbon.extendedRequested() }
    }
    CommandMenu {
        id: helpMenu; objectName: "ribbonHelpMenu"
        CommandItem { text: "All references · F1 for a focused property"; onTriggered: ribbon.helpRequested() }
    }
}
