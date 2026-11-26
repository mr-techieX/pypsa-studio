import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: sheet
    required property var theme
    property var state: backend.uiState
    spacing: 8
    objectName: "objectSpreadsheet"
    function revealCell(row, column) {
        Qt.callLater(function() {
            grid.forceLayout()
            if (row >= 0) grid.positionViewAtCell(Qt.point(column,row), TableView.Contain)
        })
    }
    RowLayout {
        Layout.fillWidth: true
        Button { text: "Add row"; objectName: "sheetAddRow"; enabled: sheet.state.editable && !sheet.state.busy; onClicked: if (backend.sheetModel.addRow()) sheet.revealCell(backend.sheetModel.rowCount()-1,0) }
        ThemedSelect {
            id: columnPicker; objectName: "sheetColumnPicker"; theme: sheet.theme; model: backend.sheetModel.availableColumns; Layout.fillWidth: true
            property string referenceComponent: sheet.state.component
            property string referenceProperty: popup.visible && highlightedIndex >= 0 ? String(model[highlightedIndex]) : currentText
        }
        Button { text: "Add column"; objectName: "sheetAddColumn"; enabled: columnPicker.currentIndex >= 0 && sheet.state.editable && !sheet.state.busy; onClicked: if (backend.sheetModel.addColumn(columnPicker.currentText)) sheet.revealCell(0,backend.sheetModel.columnCount()-1) }
        Button { text: "Copy TSV"; objectName: "sheetCopy"; onClicked: backend.copySheet() }
        Button { text: "Paste TSV"; objectName: "sheetPaste"; enabled: sheet.state.editable && !sheet.state.busy; onClicked: backend.pasteSheet() }
    }
    Label {
        Layout.fillWidth: true; wrapMode: Text.WordWrap; color: sheet.theme.muted; font.pixelSize: 11
        text: "Static inputs only · paste tab-separated data with name + attribute headers (no units in headers). Existing names are locked; pasted names update matching rows. Other properties/profiles are preserved."
    }
    HorizontalHeaderView {
        syncView: grid; Layout.fillWidth: true; clip: true
        delegate: Rectangle {
            id: header
            required property int column
            required property var display
            objectName: "sheetHeader-" + column
            property string referenceComponent: sheet.state.component
            property string referenceProperty: { var state=sheet.state; return backend.sheetModel.columnName(column) }
            implicitWidth: 165; implicitHeight: 36; color: sheet.theme.selected
            Label { anchors.fill: parent; anchors.margins: 6; text: display; color: sheet.theme.ink; font.pixelSize: 11; elide: Text.ElideRight }
            MouseArea { anchors.fill: parent; onClicked: header.forceActiveFocus() }
        }
    }
    TableView {
        id: grid; objectName: "objectSheetTable"
        Layout.fillWidth: true; Layout.fillHeight: true; clip: true
        model: backend.sheetModel; columnSpacing: 1; rowSpacing: 1
        ScrollBar.vertical: ScrollBar { }
        ScrollBar.horizontal: ScrollBar { }
        delegate: TextField {
            id: cell
            required property int row
            required property int column
            required property string cellText
            required property string cellHint
            required property bool locked
            property string referenceComponent: sheet.state.component
            property string referenceProperty: { var state=sheet.state; return backend.sheetModel.columnName(column) }
            objectName: "sheetCell-" + row + "-" + column
            implicitWidth: 165; implicitHeight: 38
            text: cellText; color: sheet.theme.ink; selectByMouse: true
            readOnly: locked || sheet.state.busy || !sheet.state.editable
            placeholderText: column === 0 ? "New object name" : "default"
            placeholderTextColor: sheet.theme.muted
            background: Rectangle {
                color: cell.locked ? sheet.theme.alternate : sheet.theme.field
                border.color: cell.activeFocus ? sheet.theme.accent : sheet.theme.border; radius: 3
            }
            onTextEdited: backend.sheetModel.editCell(row,column,text)
            ToolTip.visible: hovered; ToolTip.text: cellHint
        }
    }
    ScrollView {
        Layout.fillWidth: true; Layout.preferredHeight: 62
        TextArea {
            objectName: "sheetValidationReport"
            text: backend.sheetModel.validationReport; color: sheet.theme.ink
            readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; font.pixelSize: 11
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Button { text: "Validate draft"; objectName: "sheetValidate"; enabled: !sheet.state.busy; onClicked: backend.validateSheet() }
        Button { text: "Apply batch"; objectName: "sheetApply"; enabled: sheet.state.sheetDirty && !sheet.state.busy; onClicked: backend.applySheet() }
        Button { text: "Discard"; objectName: "sheetDiscard"; enabled: sheet.state.sheetDirty && !sheet.state.busy; onClicked: backend.discardSheet() }
        Item { Layout.fillWidth: true }
        Button { text: "Undo batch"; objectName: "sheetUndo"; enabled: sheet.state.sheetCanUndo; onClicked: backend.sheetHistory(false) }
        Button { text: "Redo batch"; objectName: "sheetRedo"; enabled: sheet.state.sheetCanRedo; onClicked: backend.sheetHistory(true) }
    }
}
