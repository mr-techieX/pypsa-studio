import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: root
    width: 1440; height: 920
    minimumWidth: 1140; minimumHeight: 760
    visible: true
    title: (root.s.dirty ? "• " : "") + root.s.projectName + " — PyPSA Studio v1.3.1"
    color: theme.window
    Theme { id: theme }
    readonly property var appTheme: theme
    font.family: "Segoe UI"
    font.pixelSize: 13
    property int page: 0
    property var s: backend.uiState
    property string inspectorKey: ""
    property bool syncingInspector: false
    property bool helpersReady: false
    property bool syncingHelpers: false
    property var profileObjectNames: []
    property var profileAttributeNames: []
    property var csvColumnNames: []
    function syncHelpers() {
        syncingHelpers=true
        var helpers=backend.helperState, settings=helpers.settings, csv=helpers.csv, state=backend.uiState
        projectName.text=settings.name; currency.text=settings.currency; startTime.text=settings.start
        periods.value=settings.count; interval.value=settings.minutes
        profileType.currentIndex=profileType.model.indexOf(csv.component || state.component)
        csvColumnNames=state.csv.columns
        refreshProfileOptions()
        profileObject.currentIndex=Math.max(0,profileObjectNames.indexOf(csv.name || ""))
        profileAttr.currentIndex=Math.max(0,profileAttributeNames.indexOf(csv.attribute || ""))
        timeColumn.currentIndex=Math.max(0,csvColumnNames.indexOf(csv.timestamp || ""))
        valueColumn.currentIndex=csv.value ? csvColumnNames.indexOf(csv.value) : (csvColumnNames.length > 1 ? 1 : 0)
        syncingHelpers=false
    }
    function refreshProfileOptions() {
        var choices=backend.profileOptions(profileType.currentText || root.s.component)
        profileObjectNames=choices.objects; profileAttributeNames=choices.attributes
    }
    function trackSettings() {
        if (helpersReady && !syncingHelpers)
            backend.updateSettingsDraft(projectName.text,currency.text,startTime.text,periods.value,interval.value)
    }
    function trackCsv() {
        if (helpersReady && !syncingHelpers)
            backend.updateCsvDraft(profileType.currentText,profileObject.currentText,profileAttr.currentText,timeColumn.currentText,valueColumn.currentText)
    }
    Component.onCompleted: {
        // The class list is schema-static; do not reset CSV selections on every
        // unrelated backend notification (run refresh, validation, etc.).
        profileType.model=backend.uiState.types.map(function(t) { return t.name })
        syncHelpers(); helpersReady=true
    }
    property var valueSpec: { var selection = root.s; return backend.propertyInfo(propertyName.currentText) }
    function syncInspector() {
        syncingInspector = true
        propertiesJson.text = backend.uiState.attributesJson
        objectNameField.text = backend.uiState.selected
        syncingInspector = false
    }
    function navigatePage(index) {
        if (index !== page && !backend.resolveDraft()) return
        page = index
    }
    function showContextHelp() {
        var item=root.activeFocusItem
        while (item) {
            if (item.referenceProperty !== undefined && item.referenceProperty) {
                references.showReference(item.referenceComponent || root.s.component,item.referenceProperty)
                return
            }
            item=item.parent
        }
        references.showReference(root.s.component,"")
    }
    Shortcut { sequence: "F1"; context: Qt.WindowShortcut; enabled: !references.visible; onActivated: root.showContextHelp() }
    // Window-scoped commands reuse the same guarded paths as the ribbon.
    // Never intercept keys owned by a modal tool or a busy operation.
    readonly property bool commandShortcutsEnabled: !root.s.busy
        && !noticeDialog.visible && !references.visible && !demos.visible
        && !studyTools.visible && !extendedTools.visible
    function editingText() {
        var item=root.activeFocusItem
        while (item) {
            if (item instanceof TextInput || item instanceof TextEdit)
                return !item.readOnly
            item=item.parent
        }
        return false
    }
    Shortcut {
        objectName: "shortcutNew"; sequences: [StandardKey.New]; context: Qt.WindowShortcut
        autoRepeat: false; enabled: root.commandShortcutsEnabled
        onActivated: backend.newProject()
    }
    Shortcut {
        objectName: "shortcutOpen"; sequences: [StandardKey.Open]; context: Qt.WindowShortcut
        autoRepeat: false; enabled: root.commandShortcutsEnabled
        onActivated: backend.openProject()
    }
    Shortcut {
        objectName: "shortcutSave"; sequences: [StandardKey.Save]; context: Qt.WindowShortcut
        autoRepeat: false; enabled: root.commandShortcutsEnabled
        onActivated: backend.saveProject()
    }
    Shortcut {
        objectName: "shortcutUndo"; sequences: [StandardKey.Undo]; context: Qt.WindowShortcut
        autoRepeat: false
        enabled: root.commandShortcutsEnabled && root.s.modelCanUndo && !root.editingText()
        onActivated: backend.modelHistory(false)
    }
    Shortcut {
        objectName: "shortcutRedo"; sequences: ["Ctrl+Y", "Ctrl+Shift+Z"]; context: Qt.WindowShortcut
        autoRepeat: false
        enabled: root.commandShortcutsEnabled && root.s.modelCanRedo && !root.editingText()
        onActivated: backend.modelHistory(true)
    }
    ReferenceHelp { id: references; theme: root.appTheme }
    DemoLibrary { id: demos; theme: root.appTheme }
    StudyTools { id: studyTools; theme: root.appTheme }
    function openStudyTools() { studyTools.open() }
    ExtendedTools { id: extendedTools; theme: root.appTheme }
    function openExtendedTools() { extendedTools.open() }
    function openDemoLibrary() {
        var index=demos.catalogue.findIndex(function(s) { return s.id === (root.s.demoInfo || {}).id })
        if (index >= 0) demos.selection=index
        demos.open()
    }
    property color ink: theme.ink
    property color muted: theme.muted
    property color accent: theme.accent
    property var pages: ["Overview", "Objects", "Profiles", "Network", "Runs", "Results", "Configuration"]
    property var subtitles: [
        "Define your system. Keep every decision local.",
        "Schema-driven components, properties and connections.",
        "Align CSV inputs with your model's snapshots.",
        "Inspect the topology before you optimize.",
        "Frozen inputs. Transparent execution. Reproducible results.",
        "Explore the attributes behind your optimized system.",
        "Choose visible categories and properties without changing model participation."
    ]
    palette.window: theme.window
    palette.base: theme.field
    palette.button: theme.button
    palette.text: ink
    palette.windowText: ink
    palette.buttonText: ink
    palette.highlight: theme.primary
    palette.highlightedText: theme.primaryText
    palette.mid: theme.border
    palette.dark: theme.border
    palette.light: theme.panel
    palette.alternateBase: theme.alternate
    palette.placeholderText: theme.muted
    palette.link: theme.accent
    palette.toolTipBase: theme.panel
    palette.toolTipText: theme.ink
    onClosing: function(close) { close.accepted = backend.canClose() }
    DropArea {
        id: fileDrop; objectName: "modelFileDrop"
        anchors.fill: parent; z: 1000
        enabled: !root.s.busy && !noticeDialog.visible && !demos.visible && !studyTools.visible && !extendedTools.visible && !references.visible
        onEntered: function(drag) {
            drag.accepted=drag.hasUrls && backend.acceptsModelFiles(drag.urls.map(function(url) { return String(url) }))
        }
        onDropped: function(drop) {
            if (drop.hasUrls && !root.s.busy)
                backend.dropModelFiles(drop.urls.map(function(url) { return String(url) }))
        }
        Rectangle {
            anchors.fill: parent; visible: fileDrop.containsDrag
            color: theme.panel; opacity: 0.94; border.color: theme.focus; border.width: 3
            Label {
                anchors.centerIn: parent
                text: "Drop one Studio .sqlite model or PyPSA .nc result"
                color: theme.ink; font.pixelSize: 20; horizontalAlignment: Text.AlignHCenter
            }
        }
    }

    component Panel: Rectangle {
        color: theme.panel; radius: 14
        border.color: theme.border; border.width: 1
    }
    component Heading: Label { color: root.ink; font.pixelSize: 18; font.weight: Font.DemiBold }
    component Hint: Label { color: root.muted; wrapMode: Text.WordWrap }
    component Action: Button {
        id: action
        implicitHeight: 38
        leftPadding: 16; rightPadding: 16
        contentItem: Text {
            text: action.text; color: action.enabled ? root.ink : root.muted
            font: action.font; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 7; color: action.down ? theme.buttonDown : action.hovered ? theme.hover : theme.button
            border.color: theme.border
        }
    }
    component Go: Action {
        id: go
        background: Rectangle { radius: 7; color: go.enabled ? (go.hovered ? theme.primaryHover : theme.primary) : theme.button }
        contentItem: Text {
            text: go.text; color: go.enabled ? theme.primaryText : theme.muted; font: go.font
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
        }
    }
    component Field: TextField {
        selectByMouse: true; implicitHeight: 38; color: root.ink
        placeholderTextColor: root.muted
        background: Rectangle { color: theme.field; radius: 7; border.color: parent.activeFocus ? root.accent : theme.border }
    }
    component Select: ThemedSelect { theme: root.appTheme }

    Connections {
        target: backend
        function onNotice(message) { noticeText.text = message; noticeDialog.open() }
        function onRunCompleted() { root.page = 5 }
        function onResultsOpened() { root.page = 5 }
        function onEditorReset() { root.syncInspector() }
        function onHelpersReset() { if (root.helpersReady) root.syncHelpers() }
        function onChanged() {
            var state = backend.uiState
            var key = state.projectId + "/" + state.component + "/" + state.selected
            if (objectPage.selectionProject !== state.projectId) {
                objectPage.deleteSelection=[]; objectPage.selectionProject=state.projectId
            }
            objectPage.deleteSelection=objectPage.deleteSelection.filter(function(r) {
                return backend.objectExists(r.component,r.name)
            })
            if (key !== root.inspectorKey) {
                root.syncInspector()
                root.inspectorKey = key
            }
        }
    }
    Dialog {
        id: noticeDialog
        anchors.centerIn: parent; width: Math.min(700, root.width - 100)
        title: "Workbench message"; modal: true; standardButtons: Dialog.Ok
        contentItem: ScrollView {
            implicitHeight: Math.min(400, noticeText.implicitHeight + 20)
            TextArea { id: noticeText; readOnly: true; wrapMode: TextEdit.Wrap; color: root.ink; selectByMouse: true }
        }
    }

    RowLayout {
        anchors.fill: parent; spacing: 0
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 0
            Rectangle {
                objectName: "atlasHeader"
                Layout.fillWidth: true; Layout.preferredHeight: 60; color: theme.header
                RowLayout {
                    anchors.fill: parent; anchors.leftMargin: 26; anchors.rightMargin: 26; spacing: 10
                    Image {
                        objectName: "studioAppIcon"
                        Layout.preferredWidth: 30; Layout.preferredHeight: 30
                        source: Qt.resolvedUrl("../assets/pypsa-studio.svg")
                        sourceSize.width: Math.round(width * Screen.devicePixelRatio)
                        sourceSize.height: Math.round(height * Screen.devicePixelRatio)
                        fillMode: Image.PreserveAspectFit
                        Accessible.name: "PyPSA Studio"
                        Accessible.role: Accessible.Graphic
                    }
                    ColumnLayout {
                        spacing: 3; Layout.fillWidth: true
                        Label { objectName: "atlasProjectTitle"; text: root.s.projectName; color: theme.headerInk; font.pixelSize: 16; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
                        Label { text: root.s.path; color: theme.headerMuted; font.pixelSize: 11; elide: Text.ElideMiddle; Layout.fillWidth: true }
                    }
                    Select {
                        id: themeSelect; objectName: "themeSelect"; headerMode: true
                        implicitWidth: 105; model: ["Light", "Dark", "System"]
                        currentIndex: model.indexOf(appearance.mode)
                        onActivated: appearance.setMode(currentText)
                        ToolTip.visible: hovered
                        ToolTip.text: "Theme · System follows your OS appearance"
                    }
                    Rectangle { width: 1; height: 24; color: theme.border }
                    RibbonButton { objectName: "quickSave"; theme: root.appTheme; headerMode: true; symbol: "save"; text: "Save project"; compact: true; hint: "Save project · Ctrl+S · resolves pending object edits first"; enabled: !root.s.busy; onClicked: backend.saveProject() }
                }
            }
            StudioRibbon {
                theme: root.appTheme; pages: root.pages; page: root.page
                Layout.fillWidth: true; Layout.preferredHeight: 84
                onNavigate: function(index) { root.navigatePage(index) }
                onSpreadsheet: { if (backend.beginSheet()) { objectPage.bulkMode=true; root.page=1 } }
                onInspector: { if (backend.resolveDraft()) { objectPage.bulkMode=false; root.page=1 } }
                onExitRequested: root.close()
                onHelpRequested: references.showReference(root.s.component,"")
                onRunRequested: { if (!backend.resolveDraft()) return; root.page = 4 }
                onStudyRequested: root.openStudyTools()
                onExtendedRequested: root.openExtendedTools()
            }
            ColumnLayout {
                Layout.fillWidth: true; Layout.fillHeight: true; Layout.margins: 24; spacing: 16
                RowLayout {
                    Layout.fillWidth: true
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 5
                        Label { text: root.pages[root.page]; color: root.ink; font.pixelSize: 28; font.weight: Font.DemiBold }
                        Hint { text: root.subtitles[root.page] }
                    }
                    Label { text: root.s.busy ? "●  " + root.s.stage.toUpperCase() : "●  LOCAL SESSION"; color: root.accent; font.pixelSize: 11; font.letterSpacing: 1 }
                }

                StackLayout {
                    currentIndex: root.page; Layout.fillWidth: true; Layout.fillHeight: true

                    // 0 — Project and horizon.
                    ColumnLayout {
                        spacing: 18
                        RowLayout {
                            Layout.fillWidth: true; spacing: 14
                            Repeater {
                                model: [{title: "OBJECTS", value: root.s.objectCount}, {title: "NODES", value: root.s.busCount}, {title: "SNAPSHOTS", value: root.s.snapshotCount}, {title: "INPUT PROFILES", value: root.s.profileCount}]
                                delegate: Panel {
                                    required property var modelData
                                    Layout.fillWidth: true; Layout.preferredHeight: 110
                                    Column { anchors.left: parent.left; anchors.leftMargin: 20; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                                        Label { text: modelData.title; color: root.muted; font.pixelSize: 10; font.letterSpacing: 1.5 }
                                        Label { text: modelData.value; color: root.ink; font.pixelSize: 30; font.weight: Font.DemiBold }
                                    }
                                }
                            }
                        }
                        RowLayout {
                            Layout.fillHeight: true; Layout.fillWidth: true; spacing: 18
                            Panel {
                                Layout.fillWidth: true; Layout.fillHeight: true
                                ColumnLayout {
                                    anchors.fill: parent; anchors.margins: 24; spacing: 13
                                    Heading { text: "Project settings" }
                                    Hint { text: "Uniform snapshots for this first build. Interval weights explicitly apply to costs, energy and storage."; Layout.fillWidth: true }
                                    Label { text: "PROJECT NAME"; color: root.muted; font.pixelSize: 10 }
                                    Field { id: projectName; objectName: "projectNameInput"; property string referenceComponent: "Network"; property string referenceProperty: "name"; Layout.fillWidth: true; enabled: !root.s.busy; onTextChanged: root.trackSettings() }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        ColumnLayout { Layout.fillWidth: true
                                            Hint { text: "Start timestamp (local, no timezone)"; font.pixelSize: 11 }
                                            Field { id: startTime; objectName: "projectStartInput"; property string referenceComponent: "Network"; property string referenceProperty: "snapshots"; Layout.fillWidth: true; enabled: !root.s.busy; onTextChanged: root.trackSettings() }
                                        }
                                        ColumnLayout { Layout.preferredWidth: 110
                                            Hint { text: "Currency label"; font.pixelSize: 11 }
                                            Field { id: currency; objectName: "projectCurrencyInput"; Layout.fillWidth: true; enabled: !root.s.busy; onTextChanged: root.trackSettings() }
                                        }
                                    }
                                    RowLayout {
                                        ColumnLayout { Hint { text: "Snapshots"; font.pixelSize: 11 } SpinBox { id: periods; objectName: "projectPeriodsInput"; property string referenceComponent: "Network"; property string referenceProperty: "snapshots"; from: 1; to: 100000; editable: true; live: true; enabled: !root.s.busy; onValueChanged: root.trackSettings() } }
                                        ColumnLayout { Hint { text: "Minutes per snapshot"; font.pixelSize: 11 } SpinBox { id: interval; property string referenceComponent: "Network"; property string referenceProperty: "snapshot_weightings"; from: 1; to: 10080; editable: true; live: true; enabled: !root.s.busy; onValueChanged: root.trackSettings() } }
                                    }
                                    Item { Layout.fillHeight: true }
                                    Hint { text: backend.helperState.settingsDirty ? "Pending settings · Apply changes the project; Save writes SQLite." : "Settings applied · edits are protected on navigation, save and run."; font.pixelSize: 10; Layout.fillWidth: true }
                                    RowLayout {
                                        Go { objectName: "applySettings"; text: "Apply settings"; enabled: !root.s.busy && backend.helperState.settingsDirty; onClicked: backend.applySettingsDraft() }
                                        Action { objectName: "discardSettings"; text: "Discard"; enabled: !root.s.busy && backend.helperState.settingsDirty; onClicked: backend.discardSettingsDraft() }
                                        Action { text: "Validate inputs"; onClicked: backend.validate() }
                                    }
                                }
                            }
                            Panel {
                                Layout.preferredWidth: 340; Layout.fillHeight: true; color: theme.feature; border.color: theme.border
                                ColumnLayout {
                                    anchors.fill: parent; anchors.margins: 24; spacing: 18
                                    Label { text: "YOUR MODEL, YOUR MACHINE"; color: root.accent; font.pixelSize: 10; font.letterSpacing: 1.5 }
                                    Heading { text: "From objects\nto optimized dispatch"; font.pixelSize: 24 }
                                    Hint { text: "1   Define nodes and assets\n\n2   Import time-varying CSV data\n\n3   Save a portable SQLite project\n\n4   Run HiGHS and inspect each step\n\n5   Query your solution attributes"; color: root.muted; Layout.fillWidth: true }
                                    Item { Layout.fillHeight: true }
                                    Action { objectName: "openDemoLibrary"; text: "Load demo model…"; enabled: !root.s.busy; onClicked: root.openDemoLibrary() }
                                    Hint { text: "Choose 2–20 buses · congestion, campus, wind, district heat, public DC reference or regional renewables."; font.pixelSize: 11; Layout.fillWidth: true }
                                }
                            }
                        }
                    }

                    // 1 — Schema-driven object catalogue and inspector.
                    RowLayout {
                        id: objectPage
                        property bool bulkMode: false
                        property var deleteSelection: []
                        property string selectionProject: ""
                        function marked(kind,name) {
                            return deleteSelection.some(function(r) { return r.component === kind && r.name === name })
                        }
                        function mark(kind,name,checked) {
                            deleteSelection=deleteSelection.filter(function(r) { return r.component !== kind || r.name !== name })
                            if (checked) deleteSelection=deleteSelection.concat([{component:kind,name:name}])
                        }
                        spacing: 14
                        Panel {
                            Layout.preferredWidth: 170; Layout.fillHeight: true
                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: 12; spacing: 10
                                Label { text: "COMPONENTS"; color: root.muted; font.pixelSize: 10; font.letterSpacing: 1 }
                                ListView {
                                    Layout.fillHeight: true; Layout.fillWidth: true; clip: true; spacing: 3
                                    model: root.s.visibleTypes
                                    delegate: Rectangle {
                                        required property var modelData
                                        width: ListView.view.width; height: 34; radius: 5
                                        color: modelData.name === root.s.component ? theme.selected : "transparent"
                                        RowLayout { anchors.fill: parent; anchors.margins: 7
                                            Label { text: modelData.name; color: modelData.editable ? root.ink : root.muted; font.pixelSize: 11; Layout.fillWidth: true }
                                            Label { text: modelData.count; color: root.accent; font.pixelSize: 11 }
                                        }
                                        MouseArea { anchors.fill: parent; onClicked: backend.selectType(modelData.name); cursorShape: Qt.PointingHandCursor }
                                    }
                                }
                            }
                        }
                        Panel {
                            Layout.fillWidth: true; Layout.fillHeight: true
                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: 18; spacing: 12
                                RowLayout { Layout.fillWidth: true
                                    Heading { text: root.s.componentVisible ? root.s.component : "No visible categories · use Configuration"; Layout.fillWidth: true }
                                    Action {
                                        objectName: "objectEditorToggle"
                                        text: objectPage.bulkMode ? "Inspector" : "Spreadsheet"
                                        onClicked: if (backend.beginSheet()) objectPage.bulkMode=!objectPage.bulkMode
                                    }
                                    Action { text: "+ New"; visible: !objectPage.bulkMode; enabled: root.s.editable && !root.s.busy; onClicked: backend.selectObject("") }
                                }
                                ListView {
                                    visible: !objectPage.bulkMode
                                    objectName: "objectList"
                                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 6
                                    model: root.s.componentVisible ? root.s.objects : []
                                    delegate: Rectangle {
                                        required property var modelData
                                        width: ListView.view.width; height: 58; radius: 7
                                        color: modelData.name === root.s.selected ? theme.selected : theme.alternate
                                        Column { anchors.left: parent.left; anchors.leftMargin: 42; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 54; spacing: 3
                                            Label { text: modelData.name; color: root.ink; font.bold: true }
                                            Label { text: modelData.summary; color: root.muted; font.pixelSize: 10; elide: Text.ElideRight; width: parent.width }
                                        }
                                        MouseArea { anchors.fill: parent; onClicked: backend.selectObject(modelData.name) }
                                        AtlasCheckBox { theme: root.appTheme
                                            objectName: "deleteMark-" + modelData.name
                                            anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                                            checked: objectPage.marked(root.s.component,modelData.name)
                                            enabled: root.s.editable && !root.s.busy
                                            Accessible.name: "Select " + modelData.name + " for deletion"
                                            onClicked: objectPage.mark(root.s.component,modelData.name,checked)
                                            ToolTip.visible: hovered; ToolTip.text: "Select for dependency-aware bulk deletion"
                                        }
                                    }
                                    Label { visible: !root.s.componentVisible || root.s.objects.length === 0; anchors.centerIn: parent; text: !root.s.componentVisible ? "No categories selected. Enable categories in Configuration." : root.s.editable ? "No objects yet. Add your first one." : "Derived by PyPSA; retained in raw run files, not model-only Results."; color: root.muted; font.pixelSize: 11; wrapMode: Text.WordWrap; width: parent.width }
                                }
                                RowLayout {
                                    visible: !objectPage.bulkMode && objectPage.deleteSelection.length > 0
                                    Action { objectName: "deleteSelectedObjects"; text: "Delete selected ("+objectPage.deleteSelection.length+")"; enabled: !root.s.busy; onClicked: if (backend.deleteObjects(objectPage.deleteSelection)) objectPage.deleteSelection=[] }
                                    Action { text: "Clear selection"; onClicked: objectPage.deleteSelection=[] }
                                }
                                ObjectSpreadsheet { theme: root.appTheme; visible: objectPage.bulkMode && root.s.componentVisible; Layout.fillWidth: true; Layout.fillHeight: true }
                            }
                        }
                        Panel {
                            visible: !objectPage.bulkMode && root.s.componentVisible
                            Layout.preferredWidth: 340; Layout.fillHeight: true
                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: 18; spacing: 10
                                Heading { text: root.s.selected ? "Object properties" : "New object" }
                                 Field { id: objectNameField; objectName: "objectNameEditor"; text: root.s.selected; placeholderText: "Unique object name"; readOnly: root.s.selected !== ""; Layout.fillWidth: true
                                    property string referenceComponent: root.s.component
                                    property string referenceProperty: "name"
                                    onTextChanged: if (!root.syncingInspector) backend.updateDraft(text, propertiesJson.text)
                                }
                                Hint { text: "Add properties below, or edit JSON directly. Omitted attributes use PyPSA defaults. Outputs are read-only."; Layout.fillWidth: true; font.pixelSize: 11 }
                                Select {
                                    id: propertyName; objectName: "inspectorPropertySelect"; model: root.s.inputNames; Layout.fillWidth: true
                                    property string referenceComponent: root.s.component
                                    property string referenceProperty: popup.visible && highlightedIndex >= 0 ? String(model[highlightedIndex]) : currentText
                                }
                                Hint { text: "Unit: " + (root.valueSpec.unit || "—") + " · default: " + root.valueSpec.default; Layout.fillWidth: true; font.pixelSize: 10 }
                                RowLayout { Layout.fillWidth: true
                                    Field { id: propertyValue; objectName: "inspectorPropertyValue"; property string referenceComponent: root.s.component; property string referenceProperty: propertyName.currentText; text: root.valueSpec.value || ""; visible: !root.valueSpec.busReference && !root.valueSpec.boolean; placeholderText: "Value in displayed units"; Layout.fillWidth: true }
                                    Select { id: busReference; property string referenceComponent: root.s.component; property string referenceProperty: propertyName.currentText; visible: !!root.valueSpec.busReference; Layout.fillWidth: true; model: root.s.busNames; currentIndex: Math.max(0, model.indexOf(root.valueSpec.value)) }
                                    Select { id: booleanValue; property string referenceComponent: root.s.component; property string referenceProperty: propertyName.currentText; visible: !!root.valueSpec.boolean; Layout.fillWidth: true; model: ["false", "true"]; currentIndex: root.valueSpec.value === "true" ? 1 : 0 }
                                    Action { text: "+"; enabled: root.s.editable && !root.s.busy && propertyName.currentIndex >= 0; onClicked: propertiesJson.text = backend.editAttribute(propertiesJson.text, propertyName.currentText, root.valueSpec.busReference ? busReference.currentText : root.valueSpec.boolean ? booleanValue.currentText : propertyValue.text) }
                                }
                                AtlasCheckBox { theme: root.appTheme
                                    id: rawJsonToggle
                                    visible: root.s.propertyFilterActive
                                    text: "Advanced JSON · includes hidden fields"
                                }
                                Hint {
                                    visible: root.s.propertyFilterActive && !rawJsonToggle.checked
                                    text: "Hidden input values are preserved. Edit selected properties with the helper or Spreadsheet; enable Advanced JSON to inspect all stored values."
                                    Layout.fillWidth: true; Layout.fillHeight: true; font.pixelSize: 11
                                }
                                ScrollView {
                                    visible: !root.s.propertyFilterActive || rawJsonToggle.checked
                                    Layout.fillWidth: true; Layout.fillHeight: true
                                    TextArea { id: propertiesJson; objectName: "objectJsonEditor"; text: root.s.attributesJson; color: root.ink; font.family: "Consolas"; font.pixelSize: 12; selectByMouse: true; wrapMode: TextEdit.Wrap; enabled: root.s.editable && !root.s.busy
                                        property string referenceComponent: root.s.component
                                        property string referenceProperty: propertyUnderCursor()
                                        function propertyUnderCursor() {
                                            var start=text.lastIndexOf("\n",Math.max(0,cursorPosition-1))+1
                                            var end=text.indexOf("\n",cursorPosition)
                                            var line=text.slice(start,end < 0 ? text.length : end)
                                            var pattern=/"([^"\\]*(?:\\.[^"\\]*)*)"\s*:/g, match, selected=""
                                            while ((match=pattern.exec(line)) !== null) {
                                                if (match.index <= cursorPosition-start || !selected) selected=match[1]
                                                else break
                                            }
                                            return selected
                                        }
                                        onTextChanged: if (!root.syncingInspector) backend.updateDraft(objectNameField.text, text)
                                        background: Rectangle { color: theme.field; radius: 7; border.color: theme.border }
                                    }
                                }
                                Hint { text: "Unapplied changes are protected by Apply/Discard/Cancel prompts. Extra ports can be entered in JSON. Reactive-power inputs and control mode do not set DC-OPF dispatch."; Layout.fillWidth: true; font.pixelSize: 10 }
                                RowLayout {
                                    Go { text: "Apply object"; enabled: root.s.editable && !root.s.busy; onClicked: backend.storeObject(objectNameField.text, propertiesJson.text) }
                                    Action { text: "Delete"; enabled: root.s.selected !== "" && !root.s.busy; onClicked: backend.deleteObject() }
                                    Action { objectName: "renameObject"; text: "Rename"; enabled: root.s.selected !== "" && !root.s.busy; leftPadding: 10; rightPadding: 10; onClicked: backend.renameSelected() }
                                }
                            }
                        }
                    }

                    // 2 — CSV mapping and profile management.
                    RowLayout {
                        id: profilesPage
                        onVisibleChanged: if (visible && root.helpersReady) root.syncHelpers()
                        spacing: 18
                        Panel {
                            Layout.fillWidth: true; Layout.fillHeight: true
                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: 22; spacing: 12
                                Heading { text: "Import a time series" }
                                Hint { text: "Choose a component type, object and varying input. Timestamps must exactly match the horizon. No resampling or unit conversion is guessed."; Layout.fillWidth: true }
                                RowLayout { Layout.fillWidth: true
                                    Select { id: profileType; objectName: "profileComponentSelect"; model: []; enabled: !root.s.busy; Layout.fillWidth: true
                                        onActivated: { root.syncingHelpers=true; root.refreshProfileOptions(); root.syncingHelpers=false; root.trackCsv() }
                                    }
                                    Select { id: profileObject; objectName: "profileObjectSelect"; model: root.profileObjectNames; enabled: !root.s.busy; onActivated: root.trackCsv(); Layout.fillWidth: true }
                                    Select { id: profileAttr; objectName: "profilePropertySelect"; property string referenceComponent: profileType.currentText; property string referenceProperty: popup.visible && highlightedIndex >= 0 ? String(model[highlightedIndex]) : currentText; model: root.profileAttributeNames; enabled: !root.s.busy; onActivated: root.trackCsv(); Layout.fillWidth: true }
                                }
                                Action { text: "Choose CSV file…"; enabled: !root.s.busy; onClicked: backend.chooseCsv() }
                                Hint { text: root.s.csv.path || "No CSV selected"; Layout.fillWidth: true; elide: Text.ElideMiddle; wrapMode: Text.NoWrap }
                                Hint { text: backend.helperState.csvDirty ? "Pending import selections · not yet stored in the model." : "Linked profiles below are stored values, independent of this helper."; font.pixelSize: 10; Layout.fillWidth: true }
                                RowLayout {
                                    ColumnLayout { Hint { text: "Timestamp column" } Select { id: timeColumn; objectName: "csvTimestampSelect"; model: root.csvColumnNames; enabled: !root.s.busy; onActivated: root.trackCsv() } }
                                    ColumnLayout { Hint { text: "Value column (PyPSA units)" } Select { id: valueColumn; objectName: "csvValueSelect"; model: root.csvColumnNames; enabled: !root.s.busy; onActivated: root.trackCsv() } }
                                }
                                ScrollView {
                                    Layout.fillHeight: true; Layout.fillWidth: true
                                    TextArea { text: root.s.csv.preview; readOnly: true; font.family: "Consolas"; font.pixelSize: 11; color: root.muted; selectByMouse: true }
                                }
                                RowLayout {
                                    Go { objectName: "importCsvDraft"; text: "Import / replace profile"; enabled: !root.s.busy && root.s.csv.path !== "" && profileObject.currentIndex >= 0 && profileAttr.currentIndex >= 0; onClicked: { root.trackCsv(); backend.applyCsvDraft() } }
                                    Action { objectName: "discardCsvDraft"; text: "Discard selections"; enabled: !root.s.busy && backend.helperState.csvDirty; onClicked: backend.discardCsvDraft() }
                                }
                            }
                        }
                        Panel {
                            Layout.preferredWidth: 330; Layout.fillHeight: true
                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: 18; spacing: 13
                                Heading { text: "Linked profiles" }
                                Hint { text: "Imported values live inside SQLite. The original CSV is not needed to reopen a saved project."; Layout.fillWidth: true; font.pixelSize: 11 }
                                ListView {
                                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 8
                                    model: root.s.profiles
                                    delegate: Rectangle {
                                        required property var modelData
                                        required property int index
                                        width: ListView.view.width; height: 100; color: theme.alternate; radius: 8
                                        Column { anchors.fill: parent; anchors.margins: 10; spacing: 5
                                            Label { text: modelData.name + " · " + modelData.attribute; color: root.accent; font.bold: true; elide: Text.ElideRight; width: parent.width }
                                            Hint { text: modelData.component + " · " + modelData.length + " values · " + modelData.unit; font.pixelSize: 11 }
                                            Action { text: "Remove"; implicitHeight: 28; enabled: !root.s.busy; onClicked: backend.removeProfile(index) }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // 3 — Visual arrangement only; dragging never rewires the model.
                    NetworkView {
                        theme: root.appTheme; topology: backend.networkState.topology; projectKey: backend.networkState.viewKey
                        onInspect: function(kind, name) {
                            if (backend.inspectNetworkObject(kind,name)) root.page=1
                        }
                    }

                    // 4 — Run lifecycle and logs.
                    ScrollView {
                        id: runPage
                        objectName: "runPage"
                        clip: true
                        contentWidth: availableWidth
                        ColumnLayout {
                        width: runPage.availableWidth
                        height: Math.max(runPage.availableHeight, implicitHeight)
                        spacing: 16
                        Panel {
                            Layout.fillWidth: true; Layout.preferredHeight: 112
                            RowLayout {
                                anchors.fill: parent; anchors.margins: 20; spacing: 14
                                ColumnLayout { Layout.fillWidth: true; Heading { text: "Run configuration" } Hint { text: "HiGHS · linear nodal dispatch · frozen inputs per run"; font.pixelSize: 11 } }
                                Field { id: runLabel; text: "basecase"; placeholderText: "Run label"; Layout.preferredWidth: 170 }
                                Select { id: exportFormat; model: ["lp", "mps", "none"]; Layout.preferredWidth: 100 }
                                 Go {
                                     objectName: "configuredRunStart"; text: "Start"
                                     enabled: !root.s.busy && horizonSettings.valid
                                     onClicked: {
                                          backend.startRunWithReports(runLabel.text, exportFormat.currentText,
                                              horizonSettings.custom ? horizonSettings.specification : "",
                                               reportingSettings.specification,
                                                pythonScript.checked)
                                     }
                                 }
                                Action { text: "Stop"; enabled: root.s.busy; onClicked: backend.cancelRun() }
                            }
                        }
                         HorizonSettings {
                             id: horizonSettings; objectName: "horizonSettings"
                             theme: root.appTheme; busy: root.s.busy; projectStart: root.s.start
                             Layout.fillWidth: true; Layout.preferredHeight: implicitHeight
                          }
                          AtlasCheckBox {
                              id: pythonScript
                              objectName: "exportPythonScript"
                              theme: root.appTheme
                               enabled: !root.s.busy
                                text: "Save as Python run"
                          }
                          ReportingSettings {
                             id: reportingSettings; objectName: "reportingSettings"
                             theme: root.appTheme; enabled: !root.s.busy
                             Layout.fillWidth: true; Layout.preferredHeight: implicitHeight
                         }
                         RowLayout {
                             spacing: 16; Layout.fillWidth: true; Layout.fillHeight: true
                             Layout.minimumHeight: 280
                            Panel {
                                Layout.fillWidth: true; Layout.fillHeight: true
                                ColumnLayout {
                                    anchors.fill: parent; anchors.margins: 20; spacing: 13
                                    RowLayout { Heading { objectName: "executionTimeline"; text: "Execution timeline"; Layout.fillWidth: true } BusyIndicator { running: root.s.busy; visible: running; implicitWidth: 28; implicitHeight: 28 } }
                                    Hint { text: "Stage: " + root.s.stage + " · " + root.s.runStatus; Layout.fillWidth: true }
                                    ScrollView {
                                        Layout.fillHeight: true; Layout.fillWidth: true
                                        TextArea { text: root.s.messages || "No runs started. Validate your project, then click Start."; color: root.ink; font.family: "Consolas"; font.pixelSize: 12; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap }
                                    }
                                    Hint { text: root.s.runPath; Layout.fillWidth: true; font.pixelSize: 10 }
                                }
                            }
                            Panel {
                                Layout.preferredWidth: 300; Layout.fillHeight: true
                                ColumnLayout {
                                    anchors.fill: parent; anchors.margins: 18; spacing: 13
                                    Heading { text: "Run history" }
                                    RowLayout {
                                        Action { text: "Refresh"; onClicked: backend.refreshRuns() }
                                        Action { text: "Browse…"; enabled: !root.s.busy; onClicked: backend.browseRun() }
                                    }
                                    ListView {
                                        Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 6; model: root.s.runs
                                        delegate: Rectangle {
                                            required property var modelData
                                            width: ListView.view.width; height: 100; radius: 7; color: theme.alternate
                                            Column { anchors.fill: parent; anchors.margins: 10; spacing: 5
                                                Label { text: modelData.name; color: root.ink; font.pixelSize: 10; elide: Text.ElideMiddle; width: parent.width }
                                                Label { text: modelData.status; color: modelData.status === "succeeded" ? theme.success : theme.warning; font.pixelSize: 11 }
                                                Label { text: modelData.created; color: root.muted; font.pixelSize: 10 }
                                                Label { text: "Objective: " + modelData.objective; color: root.muted; font.pixelSize: 10 }
                                            }
                                            MouseArea { anchors.fill: parent; enabled: !root.s.busy; onClicked: if (backend.openRun(modelData.path) && modelData.status === "succeeded") root.page = 5 }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    }

                    // 5 — Explicit selection → Query → separate data and charts.
                    ResultsExplorer { theme: root.appTheme }
                    EditorConfiguration { theme: root.appTheme }
                }
            }
        }
    }
}
