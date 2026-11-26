import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

RowLayout {
    id: explorer
    required property var theme
    property var state: backend.uiState
    property var options: backend.queryOptions
    property string category: ""
    property var selectedObjects: []
    property var selectedProperties: []
    property var expanded: ({})
    property bool pending: false
    property string loadedRun: ""
    property int resultView: 0
    onResultViewChanged: backend.setAnalysisView(resultView)
    readonly property var categories: options.categories
    readonly property var categoryInfo: categories.find(function(c) { return c.name === category }) || {objects: [], properties: []}
    spacing: 16
    objectName: "resultsExplorer"

    function chooseCategory(name) {
        if (category === name) return
        category = name
        selectedObjects = []
        selectedProperties = []
        pending = true
    }
    function toggleObject(name, object) {
        chooseCategory(name)
        selectedObjects = selectedObjects.indexOf(object) >= 0 ? selectedObjects.filter(function(n) { return n !== object }) : selectedObjects.concat([object])
        pending = true
    }
    function toggleProperty(name) {
        selectedProperties = selectedProperties.indexOf(name) >= 0 ? selectedProperties.filter(function(p) { return p !== name }) : selectedProperties.concat([name])
        pending = true
    }
    function resetForRun() {
        category = ""; selectedObjects = []; selectedProperties = []; expanded = ({}); pending = false
        // ComboBox resets its index when a new model arrives. Set these only
        // after that reset, and never reset them merely because a query ran.
        Qt.callLater(function() {
            fromSnapshot.currentIndex = options.snapshots.length ? 0 : -1
            toSnapshot.currentIndex = options.snapshots.length-1
            resolutionPicker.currentIndex=0; metricPicker.currentIndex=0; groupPicker.currentIndex=0; weekPicker.currentIndex=0
        })
    }
    onOptionsChanged: resetForRun()
    Connections {
        target: backend
        function onAnalysisViewRequested(view) { explorer.resultView=view }
        function onQuerySelectionChanged(criteria) {
            explorer.category = criteria.component
            explorer.selectedObjects = criteria.objects
            explorer.selectedProperties = criteria.properties
            var next = {}; next[criteria.component]=true; explorer.expanded=next
            Qt.callLater(function() {
                fromSnapshot.currentIndex = Math.max(0, explorer.options.snapshots.indexOf(criteria.start))
                toSnapshot.currentIndex = criteria.end ? explorer.options.snapshots.indexOf(criteria.end) : explorer.options.snapshots.length-1
                var a=criteria.aggregation || {resolution:"native",metric:"auto",week_start:"Monday",group_by:"object"}
                resolutionPicker.currentIndex=resolutionPicker.model.indexOf(a.resolution)
                metricPicker.currentIndex=metricPicker.model.indexOf(a.metric)
                weekPicker.currentIndex=weekPicker.model.indexOf(a.week_start)
                groupPicker.currentIndex=groupPicker.model.indexOf(a.group_by)
                explorer.pending=false
            })
        }
    }
    component Caption: Label { color: explorer.theme.ink; font.pixelSize: 14; font.weight: Font.DemiBold }
    component Small: Label { color: explorer.theme.muted; font.pixelSize: 11; wrapMode: Text.WordWrap }
    component Box: Rectangle { color: explorer.theme.panel; border.color: explorer.theme.border; radius: 12 }
    component Check: AtlasCheckBox {
        theme: explorer.theme
        id: check
        implicitHeight: 29
        font.pixelSize: 11
    }

    Box {
        Layout.preferredWidth: 460; Layout.minimumWidth: 420; Layout.fillHeight: true
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 12; spacing: 8
            Caption { text: "Query selection"; font.pixelSize: 17 }
            Small {
                text: explorer.options.sourceLoaded && explorer.categories.length === 0
                      ? "No queryable outputs are stored in this source."
                      : "Query solved outputs only. View model inputs in Objects or Profiles."
                Layout.fillWidth: true
            }
            GridLayout {
                columns: 2; Layout.fillWidth: true; columnSpacing: 6; rowSpacing: 3
                ThemedSelect {
                    id: resolutionPicker; objectName: "queryResolution"; theme: explorer.theme
                    model: explorer.options.resolutions || ["native"]; Layout.fillWidth: true; implicitHeight: 28
                    onActivated: { if (currentText === "native") { metricPicker.currentIndex=0; groupPicker.currentIndex=0 }; explorer.pending=true }
                    ToolTip.visible: hovered; ToolTip.text: "Calendar resolution; finer-than-native choices are unavailable."
                }
                ThemedSelect {
                    id: metricPicker; objectName: "queryMetric"; theme: explorer.theme
                    model: ["auto","mean","energy","end","min","max","total","operating_hours","fraction"]
                    Layout.fillWidth: true; implicitHeight: 28; enabled: resolutionPicker.currentText !== "native"
                    onActivated: explorer.pending=true
                    ToolTip.visible: hovered; ToolTip.text: "Auto: mean power/price, end storage energy, status fraction, event count. Invalid quantity/metric combinations are rejected."
                }
                ThemedSelect {
                    id: groupPicker; objectName: "queryGroup"; theme: explorer.theme
                    model: ["object","carrier","component"]; Layout.fillWidth: true; implicitHeight: 28
                    enabled: resolutionPicker.currentText !== "native"; onActivated: explorer.pending=true
                    ToolTip.visible: hovered; ToolTip.text: "Aggregate synchronous objects before time statistics; additive quantities only."
                }
                ThemedSelect {
                    id: weekPicker; objectName: "queryWeekStart"; theme: explorer.theme
                    model: ["Monday","Sunday"]; Layout.fillWidth: true; implicitHeight: 28
                    enabled: resolutionPicker.currentText === "weekly"; onActivated: explorer.pending=true
                    ToolTip.visible: hovered; ToolTip.text: "Calendar week starts on this day."
                }
            }
            RowLayout {
                Layout.fillWidth: true; Layout.fillHeight: true; spacing: 12
                ColumnLayout {
                    id: criteriaColumn; objectName: "snapshotPropertyColumn"
                    Layout.fillWidth: true; Layout.fillHeight: true; Layout.preferredWidth: 220
                    spacing: 8
                    Item {
                        objectName: "snapshotPane"
                        Layout.fillWidth: true
                        Layout.preferredHeight: (criteriaColumn.height-criteriaColumn.spacing)/3
                        Layout.minimumHeight: 95
                        ColumnLayout {
                            anchors.fill: parent; spacing: 4
                            Caption { text: "Snapshots · inclusive" }
                            RowLayout {
                                Small { text: "From"; Layout.preferredWidth: 30 }
                                ThemedSelect {
                                    id: fromSnapshot; objectName: "queryFromSnapshot"
                                    Layout.fillWidth: true; implicitHeight: 28
                                    theme: explorer.theme; model: explorer.options.snapshots
                                    onActivated: explorer.pending=true
                                    ToolTip.visible: hovered; ToolTip.text: currentText + " · inclusive · time series only"
                                }
                            }
                            RowLayout {
                                Small { text: "To"; Layout.preferredWidth: 30 }
                                ThemedSelect {
                                    id: toSnapshot; objectName: "queryToSnapshot"
                                    Layout.fillWidth: true; implicitHeight: 28
                                    theme: explorer.theme; model: explorer.options.snapshots
                                    onActivated: explorer.pending=true
                                    ToolTip.visible: hovered; ToolTip.text: currentText + " · inclusive · time series only"
                                }
                            }
                            Item { Layout.fillHeight: true }
                        }
                    }
                    Rectangle { Layout.fillWidth: true; height: 1; color: explorer.theme.border }
                    ColumnLayout {
                        objectName: "propertiesPane"
                        Layout.fillWidth: true; Layout.fillHeight: true; spacing: 4
                        Caption { text: "Properties" }
                        Small { text: explorer.category || "Select an object category"; Layout.fillWidth: true }
                        Check {
                            text: "All · " + explorer.selectedProperties.length + " selected"
                            enabled: explorer.categoryInfo.properties.length > 0
                            checked: explorer.selectedProperties.length > 0 && explorer.selectedProperties.length === explorer.categoryInfo.properties.length
                            onClicked: { explorer.selectedProperties = checked ? explorer.categoryInfo.properties.map(function(p) { return p.name }) : []; explorer.pending=true }
                        }
                        ListView {
                            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                            model: explorer.categoryInfo.properties
                            ScrollBar.vertical: ScrollBar { }
                            delegate: Check {
                                required property var modelData
                                property string referenceComponent: explorer.category
                                property string referenceProperty: modelData.name
                                objectName: "resultProperty-" + modelData.name
                                width: ListView.view.width
                                text: modelData.name + (modelData.unit ? " ["+modelData.unit+"]" : "")
                                checked: explorer.selectedProperties.indexOf(modelData.name) >= 0
                                onClicked: { forceActiveFocus(); explorer.toggleProperty(modelData.name) }
                                ToolTip.visible: hovered
                                ToolTip.text: modelData.kind + " · " + (modelData.unit || "no unit")
                            }
                        }
                    }
                }
                Rectangle { Layout.fillHeight: true; width: 1; color: explorer.theme.border }
                ColumnLayout {
                    objectName: "objectsPane"
                    Layout.fillWidth: true; Layout.fillHeight: true; Layout.preferredWidth: 200
                    Caption { text: "Objects" }
                    Small { text: "Defined in this run only · one category per query"; Layout.fillWidth: true }
                    ScrollView {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        contentWidth: availableWidth
                        Column {
                            width: parent.width
                            Repeater {
                                model: explorer.categories
                                delegate: Column {
                                    id: branch
                                    required property var modelData
                                    width: parent.width
                                    Rectangle {
                                        width: parent.width; height: 31; radius: 5
                                        color: explorer.category === branch.modelData.name ? explorer.theme.selected : "transparent"
                                        Label {
                                            anchors.fill: parent; anchors.margins: 6
                                            text: (explorer.expanded[branch.modelData.name] ? "▾  " : "▸  ") + branch.modelData.name + " (" + branch.modelData.objects.length + ")"
                                            color: explorer.theme.ink; font.pixelSize: 11; font.bold: true
                                        }
                                        MouseArea {
                                            anchors.fill: parent
                                            onClicked: {
                                                explorer.chooseCategory(branch.modelData.name)
                                                var next = Object.assign({}, explorer.expanded)
                                                next[branch.modelData.name] = !next[branch.modelData.name]
                                                explorer.expanded = next
                                            }
                                        }
                                    }
                                    Column {
                                        width: parent.width; visible: !!explorer.expanded[branch.modelData.name]
                                        Check {
                                            x: 12; width: parent.width-12; text: "All " + branch.modelData.name + " objects"
                                            checked: explorer.category === branch.modelData.name && explorer.selectedObjects.length === branch.modelData.objects.length
                                            onClicked: {
                                                var selectAll = checked
                                                explorer.chooseCategory(branch.modelData.name)
                                                explorer.selectedObjects = selectAll ? branch.modelData.objects.slice() : []
                                                explorer.pending = true
                                            }
                                        }
                                        Repeater {
                                            model: branch.modelData.objects
                                            delegate: Check {
                                                required property string modelData
                                                x: 24; width: parent.width-24; text: modelData
                                                checked: explorer.category === branch.modelData.name && explorer.selectedObjects.indexOf(modelData) >= 0
                                                onClicked: explorer.toggleObject(branch.modelData.name, modelData)
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            Button {
                id: queryButton; objectName: "executeQuery"; text: "Query selected objects & properties"
                Layout.fillWidth: true; implicitHeight: 40
                enabled: explorer.selectedObjects.length > 0 && explorer.selectedProperties.length > 0 && !explorer.state.busy
                background: Rectangle { color: queryButton.enabled ? (queryButton.hovered ? explorer.theme.primaryHover : explorer.theme.primary) : explorer.theme.button; radius: 7 }
                contentItem: Label { text: queryButton.text; color: queryButton.enabled ? explorer.theme.primaryText : explorer.theme.muted; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                onClicked: {
                    var settings={version:1,resolution:resolutionPicker.currentText,metric:metricPicker.currentText,week_start:weekPicker.currentText,group_by:groupPicker.currentText}
                    if (backend.queryTemporalResults(explorer.category, explorer.selectedObjects, explorer.selectedProperties, fromSnapshot.currentText, toSnapshot.currentText, JSON.stringify(settings))) explorer.pending=false
                }
            }
        }
    }

    ColumnLayout {
        Layout.fillWidth: true; Layout.fillHeight: true; spacing: explorer.resultView === 1 ? 6 : 12
        RowLayout {
            Layout.fillWidth: true
            Small { text: "Query source" }
            ThemedSelect {
                objectName: "queryRunSelect"; theme: explorer.theme; Layout.fillWidth: true
                model: explorer.state.runs.map(function(r) { return r.name + " · " + r.status })
                currentIndex: explorer.options.externalPath ? -1 : explorer.state.runs.findIndex(function(r) { return r.path === explorer.state.runPath })
                onActivated: if (currentIndex >= 0) backend.openRun(explorer.state.runs[currentIndex].path)
                ToolTip.visible: hovered; ToolTip.text: "Load previous run without solving"
            }
            Button { text: "Browse…"; enabled: !explorer.state.busy; onClicked: backend.browseRun() }
            Button { text: "Refresh"; onClicked: backend.refreshRuns() }
        }
        Small {
            objectName: "netcdfSourceBanner"
            visible: !!explorer.options.externalPath
            Layout.fillWidth: true
            textFormat: Text.PlainText
            elide: Text.ElideMiddle; maximumLineCount: 2
            text: "External NetCDF (read-only) · " + explorer.options.externalName + "\n" + explorer.options.external
            ToolTip.visible: archiveHover.hovered
            ToolTip.text: explorer.options.externalPath
            HoverHandler { id: archiveHover }
        }
        ListView {
            id: tabStrip; objectName: "queryTabStrip"
            Layout.fillWidth: true; Layout.preferredHeight: explorer.state.queryTabs.length ? 40 : 0
            visible: explorer.state.queryTabs.length > 0
            orientation: ListView.Horizontal; spacing: 6; clip: true
            model: explorer.state.queryTabs
            ScrollBar.horizontal: ScrollBar { }
            delegate: Rectangle {
                required property var modelData
                width: 275; height: 36; radius: 6; clip: true
                color: modelData.id === explorer.state.activeTabId ? explorer.theme.selected : explorer.theme.alternate
                border.color: explorer.theme.border
                RowLayout {
                    anchors.fill: parent; anchors.margins: 3; spacing: 1
                    Button {
                        Layout.fillWidth: true; Layout.minimumWidth: 0
                        Layout.preferredHeight: 28; Layout.maximumHeight: 28
                        text: modelData.title; padding: 4
                        flat: true
                        contentItem: Label { text: parent.text; color: explorer.theme.ink; font.pixelSize: 11; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
                        onClicked: backend.selectQueryTab(modelData.id)
                        ToolTip.visible: hovered; ToolTip.text: modelData.run + "\n" + modelData.title
                    }
                    ToolButton {
                        id: pinButton
                        objectName: "pinQuery-" + modelData.id
                        Layout.minimumWidth: 26; Layout.preferredWidth: 26; Layout.maximumWidth: 26
                        Layout.minimumHeight: 26; Layout.preferredHeight: 26; Layout.maximumHeight: 26
                        Layout.alignment: Qt.AlignVCenter
                        implicitWidth: 26; implicitHeight: 26; padding: 5
                        text: modelData.pinned ? "Unpin query" : "Pin query"
                        icon.source: Qt.resolvedUrl("pin.svg"); icon.color: explorer.theme.accent
                        icon.width: 14; icon.height: 14
                        display: AbstractButton.IconOnly
                        // Rotate only the glyph; keep the hit area and highlight upright.
                        contentItem.rotation: modelData.pinned ? 0 : 45
                        background: Rectangle {
                            anchors.fill: parent; anchors.margins: 1; radius: 4
                            color: modelData.pinned || pinButton.hovered ? explorer.theme.hover : "transparent"
                        }
                        onClicked: backend.pinQueryTab(modelData.id)
                        ToolTip.visible: hovered; ToolTip.text: text
                    }
                    ToolButton {
                        Layout.minimumWidth: 26; Layout.preferredWidth: 26; Layout.maximumWidth: 26
                        Layout.minimumHeight: 26; Layout.preferredHeight: 26; Layout.maximumHeight: 26
                        Layout.alignment: Qt.AlignVCenter
                        implicitWidth: 26; implicitHeight: 26; padding: 4
                        text: "×"; onClicked: backend.closeQueryTab(modelData.id)
                        ToolTip.visible: hovered; ToolTip.text: "Close query tab (does not delete saved results)"
                    }
                }
            }
        }
        Box {
            Layout.fillWidth: true; Layout.preferredHeight: explorer.resultView === 1 ? 42 : 91
            ColumnLayout {
                anchors.fill: parent; anchors.margins: explorer.resultView === 1 ? 8 : 14; spacing: 5
                Caption { text: "Solution explorer · " + (explorer.options.externalPath ? "external NetCDF" : explorer.state.runStatus); visible: explorer.resultView !== 1 }
                Small { text: explorer.state.queryDescription; visible: explorer.resultView !== 1; Layout.fillWidth: true; elide: Text.ElideRight; maximumLineCount: 2 }
                Small { text: explorer.pending ? "Selections changed — click Query. Displayed results still belong to the active tab." : "Source: " + (explorer.state.queryRun || "No query yet") + (explorer.options.externalPath ? " · reported objective " : " · objective ") + explorer.state.queryObjective; textFormat: Text.PlainText; color: explorer.pending ? explorer.theme.warning : explorer.theme.muted; Layout.fillWidth: true; elide: Text.ElideMiddle; maximumLineCount: 1 }
            }
        }
        TabBar {
            id: resultTabs; objectName: "resultViewTabs"
            Layout.fillWidth: true; currentIndex: explorer.resultView
            onCurrentIndexChanged: explorer.resultView = currentIndex
            TabButton {
                id: dataToggle; objectName: "dataViewToggle"; text: "Data"
                contentItem: Label { text: dataToggle.text; color: dataToggle.checked ? explorer.theme.primaryText : explorer.theme.ink; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                background: Rectangle { color: dataToggle.checked ? explorer.theme.primary : explorer.theme.button; radius: 6 }
            }
            TabButton {
                id: chartsToggle; objectName: "chartsViewToggle"; text: "Charts"
                contentItem: Label { text: chartsToggle.text; color: chartsToggle.checked ? explorer.theme.primaryText : explorer.theme.ink; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                background: Rectangle { color: chartsToggle.checked ? explorer.theme.primary : explorer.theme.button; radius: 6 }
            }
        }
        StackLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            currentIndex: explorer.resultView
            Box {
                objectName: "queriedDataPane"
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 12; spacing: 6
                    RowLayout {
                        Layout.fillWidth: true
                        Caption { text: "Data"; Layout.fillWidth: true }
                        Button { text: "Export queried CSV"; enabled: explorer.state.resultRows > 0; onClicked: backend.exportResults() }
                    }
                    Small { text: explorer.state.resultShown + " of " + explorer.state.resultRows + " rows · preview ≤1000 · click headers to sort · CSV includes all filtered rows"; Layout.fillWidth: true }
                    Small { text: "Output quantities: "+explorer.state.queryUnits; Layout.fillWidth: true; maximumLineCount: 2; elide: Text.ElideRight }
                    RowLayout {
                        ThemedSelect {
                            id: listingPicker; objectName: "resultListing"; theme: explorer.theme
                            model: ["snapshot","object","property"]; Layout.fillWidth: true; implicitHeight: 28
                            currentIndex: model.indexOf(explorer.state.resultListing)
                            onActivated: backend.setResultListing(currentText, formPicker.currentText)
                            ToolTip.visible: hovered; ToolTip.text: "Snapshot-first, object-first or property-first listing."
                        }
                        ThemedSelect {
                            id: formPicker; objectName: "resultForm"; theme: explorer.theme
                            model: ["wide","long"]; implicitWidth: 90; implicitHeight: 28
                            currentIndex: model.indexOf(explorer.state.resultForm)
                            onActivated: backend.setResultListing(listingPicker.currentText,currentText)
                        }
                        TextField {
                            objectName: "resultSearch"; placeholderText: "Filter table"; Layout.fillWidth: true
                            color: explorer.theme.ink; onTextChanged: backend.filterResults(text)
                            ToolTip.visible: hovered; ToolTip.text: "Filters the table/CSV only; not the query or chart timeline."
                        }
                    }
                    HorizontalHeaderView {
                        syncView: resultTable; Layout.fillWidth: true; clip: true
                        delegate: Rectangle {
                            required property var display
                            implicitHeight: 32; implicitWidth: 155; color: explorer.theme.selected
                            Label { anchors.fill: parent; anchors.margins: 7; text: display + (explorer.state.resultSort === display ? (explorer.state.resultSortDescending ? " ▾" : " ▴") : ""); color: explorer.theme.ink; elide: Text.ElideRight; font.pixelSize: 11 }
                            MouseArea { anchors.fill: parent; onClicked: backend.sortResultTable(parent.display) }
                        }
                    }
                    TableView {
                        id: resultTable; objectName: "queriedDataTable"
                        Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                        model: backend.resultModel; columnSpacing: 1; rowSpacing: 1
                        ScrollBar.vertical: ScrollBar { }
                        ScrollBar.horizontal: ScrollBar { }
                        delegate: Rectangle {
                            required property var display
                            required property int row
                            implicitWidth: 155; implicitHeight: 31; color: row%2 ? explorer.theme.alternate : explorer.theme.field
                            Label { anchors.fill: parent; anchors.margins: 7; text: display; color: explorer.theme.ink; font.pixelSize: 11; elide: Text.ElideRight }
                        }
                    }
                }
            }
            Box {
                objectName: "queriedChartsPane"
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 12; spacing: 7
                    Caption { text: "Charts · active query only" }
                    Small { text: "One chart per numeric property · ≤1000 sampled points / 6 objects · zoom for detail · missing values are gaps"; Layout.fillWidth: true }
                    TimelineNavigator {
                        theme: explorer.theme; info: explorer.state.chartRange
                        Layout.fillWidth: true; Layout.preferredHeight: 94
                        visible: info.count > 0
                    }
                    ScrollView {
                        id: chartScroll
                        objectName: "queryChartsScroll"
                        Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth
                        Column {
                            width: parent.width; spacing: 12
                            Repeater {
                                model: explorer.state.charts
                                delegate: Column {
                                    required property var modelData
                                    width: parent.width; spacing: 4
                                    objectName: "queryChartCard-" + modelData.title
                                    ThemedSelect {
                                        objectName: "chartType-" + modelData.title
                                        width: 155; theme: explorer.theme; model: modelData.options
                                        currentIndex: modelData.options.indexOf(modelData.kind)
                                        onActivated: backend.setChartType(modelData.title, currentText)
                                    }
                                    Small { width: parent.width; text: modelData.hint }
                                    QueryChart {
                                        objectName: "queryChart-" + modelData.title
                                        width: parent.width
                                        height: modelData.kind === "horizontal bar" ? Math.max(210,modelData.labels.length*23+65) : Math.max(150,Math.min(260,chartScroll.availableHeight-70))
                                        chart: modelData; theme: explorer.theme
                                    }
                                }
                            }
                            Small { visible: explorer.state.charts.length === 0; text: "Run a query with numeric properties to display charts."; width: parent.width }
                        }
                    }
                }
            }
        }
    }
}
