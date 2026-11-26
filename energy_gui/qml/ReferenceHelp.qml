import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: help
    required property var theme
    property var catalogue: ({})
    property string componentName: "Generator"
    property string propertyName: ""
    property var info: ({})
    readonly property var classNames: Object.keys(catalogue)
    objectName: "referenceHelp"
    title: "PyPSA 1.4.0 · Reference help"
    modal: true; focus: true; standardButtons: Dialog.Close
    enter: Transition { }
    exit: Transition { }
    width: Math.min(parent.width-60,1120); height: Math.min(parent.height-60,760)
    anchors.centerIn: parent
    function showReference(component, property) {
        catalogue=backend.referenceCatalogue()
        componentName=classNames.indexOf(component) >= 0 ? component : "Generator"
        search.text=""
        propertyName=property || ""
        info=backend.propertyReference(componentName,propertyName)
        classes.currentIndex=classNames.indexOf(componentName)
        open()
        Qt.callLater(function() {
            var index=(catalogue[componentName] || []).findIndex(function(p) { return p.name === propertyName })
            properties.currentIndex=index
            if (index >= 0) properties.positionViewAtIndex(index,ListView.Contain)
            detailScroll.contentItem.contentY=0
        })
    }
    function selectProperty(name) {
        propertyName=name
        info=backend.propertyReference(componentName,name)
        detailScroll.contentItem.contentY=0
    }
    contentItem: ColumnLayout {
        spacing: 10
        Label { Layout.fillWidth: true; color: help.theme.muted; wrapMode: Text.WordWrap; text: "Local references for all classes, including hidden properties and outputs. Read-only help; opening it does not apply or discard model drafts." }
        RowLayout {
            Layout.fillWidth: true
            ThemedSelect {
                id: classes; objectName: "helpClassSelect"; theme: help.theme
                Layout.preferredWidth: 230; model: help.classNames
                onActivated: { help.componentName=currentText; search.text=""; help.selectProperty("") }
            }
            TextField { id: search; objectName: "helpPropertySearch"; Layout.fillWidth: true; color: help.theme.ink; placeholderTextColor: help.theme.muted; placeholderText: "Search property, description or unit" }
        }
        RowLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 14
            ListView {
                id: properties; objectName: "helpPropertyList"
                Layout.preferredWidth: 265; Layout.fillHeight: true; clip: true
                model: (help.catalogue[help.componentName] || []).filter(function(p) { return (p.name+" "+p.description+" "+p.unit).toLowerCase().indexOf(search.text.toLowerCase()) >= 0 })
                ScrollBar.vertical: ScrollBar { }
                delegate: ItemDelegate {
                    required property var modelData
                    objectName: "helpProperty-" + modelData.name
                    width: ListView.view.width; height: 34
                    highlighted: modelData.name === help.propertyName
                    contentItem: Label { text: modelData.name; color: help.theme.ink; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
                    background: Rectangle { radius: 4; color: parent.highlighted ? help.theme.selected : "transparent" }
                    onClicked: help.selectProperty(modelData.name)
                }
            }
            ScrollView {
                id: detailScroll; objectName: "helpDetailScroll"
                Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth
                ColumnLayout {
                    width: detailScroll.availableWidth; spacing: 10
                    Label { objectName: "helpPropertyTitle"; Layout.fillWidth: true; text: help.componentName + (help.propertyName ? "."+help.propertyName : " · class reference"); textFormat: Text.PlainText; color: help.theme.ink; font.pixelSize: 21; font.bold: true; wrapMode: Text.WrapAnywhere }
                    Label { Layout.fillWidth: true; visible: help.info.type !== undefined; text: (help.info.type || "") + (help.info.unit ? " · Unit: "+help.info.unit : "") + (help.info.default !== undefined ? " · Default: "+help.info.default : ""); textFormat: Text.PlainText; color: help.theme.accent; wrapMode: Text.WordWrap }
                    Label { Layout.fillWidth: true; visible: help.componentName !== "Network" && help.info.input !== undefined; text: (help.info.input ? "Input" : "Output / read-only") + (help.info.required ? " · required" : "") + (help.info.static ? " · static" : "") + (help.info.varying ? " · time-dependent" : ""); color: help.theme.muted; wrapMode: Text.WordWrap }
                    Label { objectName: "helpPropertyDescription"; Layout.fillWidth: true; text: help.info.description || ""; textFormat: Text.PlainText; color: help.theme.ink; wrapMode: Text.WordWrap }
                    Rectangle { Layout.fillWidth: true; height: 1; color: help.theme.border }
                    Label { text: "Full local class guide"; color: help.theme.ink; font.bold: true }
                    TextArea {
                        objectName: "helpClassGuide"; Layout.fillWidth: true
                        text: help.info.guide || ""; textFormat: TextEdit.MarkdownText
                        readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap
                        color: help.theme.ink; font.pixelSize: 12
                        background: Rectangle { color: "transparent" }
                    }
                }
            }
        }
    }
}
