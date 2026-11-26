import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: config
    required property var theme
    property var state: backend.uiState
    property var categories: []
    property var properties: ({})
    property var catalogue: ({})
    property string category: "Bus"
    property bool pending: false
    property string loadedProject: ""
    objectName: "editorConfiguration"
    color: theme.panel; border.color: theme.border; radius: 12
    function reload() {
        var settings=backend.editorConfiguration()
        categories=settings.categories; properties=settings.properties; catalogue=settings.catalogue
        loadedProject=state.projectId; pending=false
    }
    function toggleCategory(name, checked) {
        categories=checked ? categories.concat([name]) : categories.filter(function(n) { return n !== name })
        pending=true
    }
    function toggleProperty(name, checked) {
        var next=Object.assign({},properties), values=next[category] || []
        next[category]=checked ? values.concat([name]) : values.filter(function(n) { return n !== name })
        properties=next; pending=true
    }
    onVisibleChanged: if (visible && (!pending || loadedProject !== state.projectId)) reload()
    onStateChanged: if (visible && loadedProject !== state.projectId) reload()
    Component.onCompleted: reload()
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 18; spacing: 10
        Label { text: "Objects workspace configuration"; color: config.theme.ink; font.pixelSize: 18; font.bold: true }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap; color: config.theme.muted
            text: "Display only: hidden categories, properties and their existing values still participate in the model. Apply changes these display settings; Save persists them with the project. Results and Profiles are not filtered here."
        }
        RowLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 18
            ColumnLayout {
                Layout.minimumWidth: 240; Layout.preferredWidth: 280; Layout.maximumWidth: 320; Layout.fillHeight: true
                Label { text: "Component categories"; color: config.theme.ink; font.bold: true }
                TextField { id: categorySearch; objectName: "configCategorySearch"; Layout.fillWidth: true; placeholderText: "Search categories"; color: config.theme.ink; placeholderTextColor: config.theme.muted }
                ListView {
                    objectName: "configCategoryList"
                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                    model: config.state.types.filter(function(t) { return t.name.toLowerCase().indexOf(categorySearch.text.toLowerCase()) >= 0 })
                    ScrollBar.vertical: ScrollBar { }
                    delegate: RowLayout {
                        required property var modelData
                        width: ListView.view.width; height: 36
                        AtlasCheckBox { theme: config.theme
                            objectName: "configCategory-" + modelData.name
                            checked: config.categories.indexOf(modelData.name) >= 0
                            enabled: !config.state.busy
                            onClicked: config.toggleCategory(modelData.name,checked)
                        }
                        Button {
                            text: modelData.name; Layout.fillWidth: true; flat: true
                            highlighted: config.category === modelData.name
                            contentItem: Label { text: parent.text; color: config.theme.ink; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                            background: Rectangle { radius: 5; color: config.category === modelData.name ? config.theme.selected : "transparent" }
                            onClicked: config.category=modelData.name
                        }
                    }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true; Layout.fillHeight: true
                Label { text: "Properties · " + config.category; color: config.theme.ink; font.bold: true }
                TextField { id: propertySearch; objectName: "configPropertySearch"; Layout.fillWidth: true; placeholderText: "Search name, description or unit"; color: config.theme.ink; placeholderTextColor: config.theme.muted }
                RowLayout {
                    Button { text: "Select all properties"; enabled: !config.state.busy; onClicked: { var next=Object.assign({},config.properties); next[config.category]=(config.catalogue[config.category] || []).map(function(p) { return p.name }); config.properties=next; config.pending=true } }
                    Button { objectName: "configNameOnly"; text: "Name only"; enabled: !config.state.busy; onClicked: { var next=Object.assign({},config.properties); next[config.category]=["name"]; config.properties=next; config.pending=true } }
                }
                ListView {
                    objectName: "configPropertyList"
                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                    model: (config.catalogue[config.category] || []).filter(function(p) { return (p.name+" "+p.description+" "+p.unit).toLowerCase().indexOf(propertySearch.text.toLowerCase()) >= 0 })
                    ScrollBar.vertical: ScrollBar { }
                    delegate: AtlasCheckBox { theme: config.theme
                        required property var modelData
                        property string referenceComponent: config.category
                        property string referenceProperty: modelData.name
                        objectName: "configProperty-" + modelData.name
                        width: ListView.view.width; height: 34
                        checked: (config.properties[config.category] || []).indexOf(modelData.name) >= 0
                        enabled: modelData.name !== "name" && !config.state.busy
                        text: modelData.name + (modelData.unit ? " ["+modelData.unit+"]" : "") + (modelData.input ? " · input" : " · output / reference only")
                        onClicked: { forceActiveFocus(); config.toggleProperty(modelData.name,checked) }
                        ToolTip.visible: hovered; ToolTip.text: modelData.description
                    }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Button { objectName: "configApply"; text: "Apply configuration"; enabled: config.pending && !config.state.busy; onClicked: if (backend.applyEditorConfiguration(config.categories,config.properties)) config.reload() }
            Button { text: "Discard selections"; enabled: config.pending; onClicked: config.reload() }
            Button { objectName: "configShowAll"; text: "Show everything"; enabled: !config.state.busy; onClicked: { config.categories=config.state.types.map(function(t) { return t.name }); var next={}; Object.keys(config.catalogue).forEach(function(c) { next[c]=config.catalogue[c].map(function(p) { return p.name }) }); config.properties=next; config.pending=true } }
            Label { Layout.fillWidth: true; color: config.theme.muted; text: config.pending ? "Unapplied display selections" : "Configuration applied · Save stores it in SQLite" }
        }
    }
}
