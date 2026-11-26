import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "NetworkIcons.js" as NetworkIcons

Rectangle {
    id: network
    required property var theme
    required property var topology
    required property string projectKey
    property var context: backend.networkState
    property var positions: ({})
    property var sessionLayouts: ({})
    property string loadedKey: ""
    property bool restoring: false
    property bool layoutPending: false
    property bool fitOnShow: false
    property var pendingCamera: null
    property var activeDrag: null
    readonly property real workspaceLimit: 100000
    property real canvasWidth: 900
    property real canvasHeight: 520
    property string activeObject: ""
    // Navigation is session-only UI state, never a topology/layout mutation.
    property string searchText: ""
    property string kindFilter: ""
    property var carrierFilter: null
    property bool congestionEnabled: false
    readonly property var objectLookup: {
        var result={}
        ;(topology.objects || []).forEach(function(o) { result[o.key]=o })
        return result
    }
    readonly property var kindOptions: ["All kinds"].concat(Object.keys((topology.objects || []).reduce(function(kinds,o) { kinds[o.kind]=true; return kinds },{})).sort())
    readonly property var carrierValues: Object.keys((topology.objects || []).reduce(function(carriers,o) { carriers[o.carrier || ""]=true; return carriers },Object.create(null))).sort()
    readonly property var carrierOptions: ["All carriers"].concat(carrierValues.map(function(c) { return c || "(no carrier)" }))
    readonly property var filteredObjects: (topology.objects || []).filter(function(o) { return matchesObject(o) })
    readonly property var visibleKeys: {
        var result={}
        filteredObjects.forEach(function(o) { result[o.key]=true })
        return result
    }
    readonly property var focusKeys: {
        var result={}
        if (activeObject) {
            result[activeObject]=true
            ;(topology.wires || []).forEach(function(w) {
                if (w.a === activeObject) result[w.b]=true
                if (w.b === activeObject) result[w.a]=true
            })
        }
        return result
    }
    readonly property var iconTypes: Object.keys(NetworkIcons.icons)
    property real zoomFactor: 1
    // Every visible blank area is usable at every zoom, not a scaled 900×520 box.
    readonly property real sceneWidth: Math.max(900, viewport.width/zoomFactor, canvasWidth)
    readonly property real sceneHeight: Math.max(520, viewport.height/zoomFactor, canvasHeight)
    readonly property real paperMargin: Math.max(viewport.width,viewport.height)*0.75
    signal inspect(string kind, string name)
    objectName: "networkView"
    color: theme.panel; border.color: theme.border; radius: 14

    function layoutData() {
        return {positions:positions, zoom:zoomFactor, panX:Math.max(0,viewport.contentX),
                panY:Math.max(0,viewport.contentY), width:sceneWidth, height:sceneHeight, paperVersion:1}
    }
    function matchesObject(object) {
        if (kindFilter && object.kind !== kindFilter) return false
        if (carrierFilter !== null && (object.carrier || "") !== carrierFilter) return false
        var text=(object.name+" "+object.kind+" "+(object.carrier || "")).toLowerCase()
        return searchText.toLowerCase().trim().split(/\s+/).every(function(word) { return text.indexOf(word) >= 0 })
    }
    function clearFilters() { searchText=""; kindFilter=""; carrierFilter=null }
    function clearFocus() { activeObject="" }
    function wireIsVisible(wire) { return !!visibleKeys[wire.a] && !!visibleKeys[wire.b] }
    function focusObject(key) {
        if (!objectLookup[key] || !positions[key]) return false
        // Locate reveals the full neighbourhood; filters never move any nodes.
        clearFilters(); activeObject=key
        zoomFactor=Math.max(0.1,Math.min(3,viewport.width/140,viewport.height/160,Math.max(1.25,zoomFactor*1.4)))
        Qt.callLater(function() {
            var point=network.positions[key]
            if (!point || network.activeObject !== key) return
            viewport.contentX=Math.max(0,Math.min(viewport.contentWidth-viewport.width,point.x*network.zoomFactor+scene.x-viewport.width/2))
            viewport.contentY=Math.max(0,Math.min(viewport.contentHeight-viewport.height,point.y*network.zoomFactor+scene.y-viewport.height/2))
        })
        return true
    }
    function locateObject(kind, name) {
        var object=(topology.objects || []).find(function(o) { return o.kind === kind && o.name === name })
        return object ? focusObject(object.key) : false
    }
    function stepSnapshot(delta) {
        var index=context.snapshotIndex+delta
        return context.frozen && (delta === -1 || delta === 1) && index >= 0 && index < context.snapshots.length
                ? backend.setNetworkSnapshot(index) : false
    }
    function passiveUtilisation(wire) {
        var object=objectLookup[wire.a]
        // Only the actual exported passive bus0/p0 payload has this meaning.
        // In particular, do not copy a percentage to p1 or infer converter bounds.
        if (!context.frozen || !object || (object.kind !== "Line" && object.kind !== "Transformer")
                || wire.port !== "bus0" || wire.attribute !== "p0" || wire.unit !== "MW"
                || typeof wire.flow !== "number" || !isFinite(wire.flow)
                || typeof wire.utilisation !== "number" || !isFinite(wire.utilisation) || wire.utilisation < 0) return null
        return wire.utilisation
    }
    function wireAppearance(wire) {
        var available=context.frozen && wire.flow !== null && wire.flow !== undefined
        var focused=!!activeObject && (wire.a === activeObject || wire.b === activeObject)
        var percent=congestionEnabled ? passiveUtilisation(wire) : null
        var congested=percent !== null && percent >= 90
        var color=congested ? (percent >= 100 ? theme.danger : theme.warning)
                            : focused ? theme.focus : (available ? theme.accent : theme.muted)
        return {visible:wireIsVisible(wire), available:available, focused:focused, congested:congested,
                color:color.toString(), width:focused ? 4.5 : congested ? 4 : available ? 3 : 1.5,
                alpha:activeObject && !focused && !congested ? 0.28 : 1}
    }
    function readableGridLayout() {
        var objects=(topology.objects || []).slice()
        if (!objects.length) return false
        // Stable breadth-first bus order keeps connected areas near each other.
        // Group assets under their earliest bus; every object gets its own cell.
        var buses=objects.filter(function(o) { return o.kind === "Bus" }).sort(function(a,b) { return a.name.localeCompare(b.name) })
        var neighbours={}, visited={}, ordered=[], rank={}, groups={}, unconnected=[]
        buses.forEach(function(o) { neighbours[o.key]=[] })
        objects.forEach(function(o) {
            var ports=o.buses.filter(function(key) { return !!neighbours[key] })
            for (var i=1;i<ports.length;i++) {
                neighbours[ports[0]].push(ports[i]); neighbours[ports[i]].push(ports[0])
            }
        })
        buses.forEach(function(bus) {
            if (visited[bus.key]) return
            var queue=[bus.key]; visited[bus.key]=true
            for (var i=0;i<queue.length;i++) {
                var key=queue[i]; rank[key]=ordered.length; ordered.push(key); groups[key]=[]
                neighbours[key].sort().forEach(function(other) {
                    if (!visited[other]) { visited[other]=true; queue.push(other) }
                })
            }
        })
        objects.sort(function(a,b) { return (a.kind+"\n"+a.name).localeCompare(b.kind+"\n"+b.name) }).forEach(function(o) {
            if (o.kind === "Bus") return
            var ports=o.buses.filter(function(key) { return rank[key] !== undefined }).sort(function(a,b) { return rank[a]-rank[b] })
            if (ports.length) groups[ports[0]].push(o.key)
            else unconnected.push(o.key)
        })
        var keys=[]
        ordered.forEach(function(key) { keys.push(key); keys=keys.concat(groups[key]) })
        keys=keys.concat(unconnected)
        var columns=Math.max(1,Math.ceil(Math.sqrt(keys.length*164/144))), rows=Math.ceil(keys.length/columns)
        // Stay inside checked_layout's canvas bounds, including very dense views.
        var spacing=Math.min(1,7640/Math.max(1,(columns-1)*144),7620/Math.max(1,(rows-1)*164),Math.sqrt(14000000/(columns*144*rows*164)))
        var next={}
        keys.forEach(function(key,i) { next[key]={x:80+(i%columns)*144*spacing,y:82+Math.floor(i/columns)*164*spacing} })
        canvasWidth=Math.max(900,160+(columns-1)*144*spacing)
        canvasHeight=Math.max(520,180+(rows-1)*164*spacing)
        positions=next; layoutPending=true
        Qt.callLater(function() { network.fitView() })
        return true
    }
    function restoreLayout() {
        if (loadedKey && loadedKey !== projectKey) sessionLayouts[loadedKey]=pendingCamera || layoutData()
        restoring=true; fitOnShow=false
        var saved=sessionLayouts[projectKey] || context.layout || {}
        loadedKey=projectKey; activeObject=""; clearFilters(); congestionEnabled=false
        canvasWidth=saved.width || 900; canvasHeight=saved.height || 520
        zoomFactor=saved.zoom || 1; positions=saved.positions || {}
        arrange(false)
        pendingCamera=saved
        Qt.callLater(network.finishInitialFit)
    }
    function restoreCamera(saved) {
            // Old layouts have no surrounding-paper offset; convert in memory,
            // without rewriting the stored project until explicit Save layout.
            var offsetX=saved.paperVersion === 1 ? 0 : paperMargin-Math.max(0,(viewport.width-(saved.width || 900)*zoomFactor)/2)
            var offsetY=saved.paperVersion === 1 ? 0 : paperMargin-Math.max(0,(viewport.height-(saved.height || 520)*zoomFactor)/2)
            viewport.contentX=Math.max(0,Math.min((saved.panX || 0)+offsetX,Math.max(0,viewport.contentWidth-viewport.width)))
            viewport.contentY=Math.max(0,Math.min((saved.panY || 0)+offsetY,Math.max(0,viewport.contentHeight-viewport.height)))
        restoring=false; layoutPending=false
    }
    function fitView() {
        if (!network.visible || viewport.width < 1 || viewport.height < 1) {
            fitOnShow=true
            return
        }
        fitOnShow=false
        var values=Object.keys(positions).map(function(k) { return positions[k] })
        if (!values.length) return
        var left=Math.min.apply(null,values.map(function(p) { return p.x-65 })), right=Math.max.apply(null,values.map(function(p) { return p.x+65 }))
        var top=Math.min.apply(null,values.map(function(p) { return p.y-65 })), bottom=Math.max.apply(null,values.map(function(p) { return p.y+85 }))
        // Frozen views reserve space for snapshots/details. Allow an overview
        // below 25% so a 20-bus diagram still fits the minimum-height viewport.
        zoomFactor=Math.max(0.1,Math.min(1,viewport.width/(right-left+20),viewport.height/(bottom-top+20)))
        Qt.callLater(function() {
            viewport.contentX=Math.max(0,Math.min(viewport.contentWidth-viewport.width,(left+right)/2*zoomFactor+scene.x-viewport.width/2))
            viewport.contentY=Math.max(0,Math.min(viewport.contentHeight-viewport.height,(top+bottom)/2*zoomFactor+scene.y-viewport.height/2))
        })
    }
    function finishInitialFit() {
        if (!network.visible || viewport.width < 1 || viewport.height < 1) return
        if (pendingCamera !== null) {
            var saved=pendingCamera
            pendingCamera=null
            restoreCamera(saved)
            if (!saved.positions) fitOnShow=true
        }
        if (fitOnShow) fitView()
    }
    function syncGraph() {
        Qt.callLater(function() {
            if (loadedKey !== projectKey) restoreLayout()
            else arrange(false)
            snapshotPicker.currentIndex=context.snapshotIndex
            wires.requestPaint()
        })
    }
    function resetLayout() {
        canvasWidth=900; canvasHeight=520; zoomFactor=1
        viewport.contentX=paperMargin; viewport.contentY=paperMargin
        arrange(true); layoutPending=true
    }
    function flowText(wire) {
        if (wire.flow === null || wire.flow === undefined) return wire.attribute + " unavailable"
        return wire.attribute + " " + (wire.flow > 0 ? "+" : "") + wire.flow.toFixed(1) + " MW"
    }

    function arrange(reset) {
        var old = reset ? {} : Object.assign({}, (context.layout || {}).positions || {}, positions), next = {}, objects = topology.objects || []
        var buses = objects.filter(function(o) { return o.kind === "Bus" })
        // Initial geometry must not feed back on a hidden tab's zoom/camera:
        // logical paper can grow, but default placement starts in a window-sized
        // frame. Otherwise repeated hidden loads at 10% inflate node coordinates.
        var layoutWidth=Math.max(900,viewport.width), layoutHeight=Math.max(520,viewport.height)
        var radius = Math.min(layoutWidth,layoutHeight)*0.20, centerY=layoutHeight*0.47
        buses.forEach(function(o,i) {
            var angle = 2*Math.PI*i/Math.max(1,buses.length)-Math.PI/2
            next[o.key] = old[o.key] || {x:layoutWidth/2+radius*Math.cos(angle), y:centerY+radius*Math.sin(angle)}
        })
        var counts = {}, shelf = 0
        objects.forEach(function(o) {
            if (o.kind === "Bus") return
            var ports = o.buses.filter(function(key) { return !!next[key] })
            if (ports.length > 1) {
                var a=next[ports[0]], b=next[ports[1]], group=ports.slice().sort().join("|")
                var offset=(counts[group] || 0)*48; counts[group]=(counts[group] || 0)+1
                next[o.key]={x:(a.x+b.x)/2+offset,y:(a.y+b.y)/2+offset}
            } else if (ports.length) {
                var p=next[ports[0]], n=counts[ports[0]] || 0
                counts[ports[0]]=n+1
                var total=objects.filter(function(asset) { return asset.buses.length === 1 && asset.buses[0] === ports[0] }).length
                var theta=Math.atan2(p.y-centerY,p.x-layoutWidth/2)+(n-(total-1)/2)*0.8
                next[o.key]={x:p.x+105*Math.cos(theta), y:p.y+105*Math.sin(theta)}
            } else {
                next[o.key]={x:90+(shelf%8)*110,y:layoutHeight-50-Math.floor(shelf/8)*85}; shelf++
            }
            if (old[o.key]) next[o.key]=old[o.key]
        })
        var wasRestoring=restoring
        restoring=true; positions=next; restoring=wasRestoring
    }
    function moveObject(key, x, y) {
        if (!positions[key] || !isFinite(x) || !isFinite(y)) return false
        if (Math.abs(positions[key].x-x) < 0.001 && Math.abs(positions[key].y-y) < 0.001) return true
        // Grow on the left/top by translating logical coordinates and camera
        // equally. Screen positions of the other nodes stay unchanged.
        var dx=x < 80 ? 80-x : 0, dy=y < 90 ? 90-y : 0
        var maxX=x+dx+160, maxY=y+dy+180
        Object.keys(positions).forEach(function(k) {
            if (k !== key) { maxX=Math.max(maxX,positions[k].x+dx+160); maxY=Math.max(maxY,positions[k].y+dy+180) }
        })
        var width=Math.max(canvasWidth+dx,maxX), height=Math.max(canvasHeight+dy,maxY)
        if (width > workspaceLimit || height > workspaceLimit) return false
        var panX=viewport.contentX+dx*zoomFactor, panY=viewport.contentY+dy*zoomFactor
        var next=Object.assign({},positions)
        if (dx || dy) Object.keys(next).forEach(function(k) { next[k]={x:next[k].x+dx,y:next[k].y+dy} })
        next[key]={x:x+dx,y:y+dy}
        canvasWidth=width; canvasHeight=height; positions=next
        if (dx || dy) { viewport.contentX=panX; viewport.contentY=panY }
        return true
    }
    function zoomAt(value, x, y) {
        var old=zoomFactor, next=Math.max(0.1,Math.min(3,value))
        var wx=(viewport.contentX+x-scene.x)/old, wy=(viewport.contentY+y-scene.y)/old
        zoomFactor=next
        viewport.contentX=Math.max(0,Math.min(viewport.contentWidth-viewport.width,scene.x+wx*next-x))
        viewport.contentY=Math.max(0,Math.min(viewport.contentHeight-viewport.height,scene.y+wy*next-y))
    }
    Timer {
        interval: 25; repeat: true; running: network.activeDrag !== null
        onTriggered: if (network.activeDrag) network.activeDrag.edgeScroll()
    }
    onTopologyChanged: syncGraph()
    onProjectKeyChanged: syncGraph()
    onContextChanged: syncGraph()
    onVisibleChanged: if (visible && (fitOnShow || pendingCamera !== null)) Qt.callLater(network.finishInitialFit)
    Component.onCompleted: syncGraph()
    onPositionsChanged: { wires.requestPaint(); if (!restoring) layoutPending=true }
    onZoomFactorChanged: { wires.requestPaint(); if (!restoring) layoutPending=true }
    onVisibleKeysChanged: wires.requestPaint()
    onActiveObjectChanged: wires.requestPaint()
    onCongestionEnabledChanged: wires.requestPaint()

    Popup {
        id: navigationPopup; objectName: "networkNavigationPopup"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(520,network.width-32); padding: 14; focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onOpened: searchField.forceActiveFocus()
        background: Rectangle { color: network.theme.panel; border.color: network.theme.border; radius: 10 }
        contentItem: ColumnLayout {
            spacing: 6
            RowLayout {
                Layout.fillWidth: true
                Label { text: "Find / filter network"; color: network.theme.ink; font.bold: true; Layout.fillWidth: true }
                ToolButton { objectName: "networkNavigationClose"; text: "×"; implicitHeight: 26; implicitWidth: 30; onClicked: navigationPopup.close() }
            }
            TextField {
                id: searchField; objectName: "networkSearchField"
                Layout.fillWidth: true; implicitHeight: 32; selectByMouse: true
                text: network.searchText; onTextChanged: network.searchText=text
                placeholderText: "Name, kind or carrier…"; placeholderTextColor: network.theme.muted; color: network.theme.ink
                background: Rectangle { color: network.theme.field; radius: 6; border.color: searchField.activeFocus ? network.theme.accent : network.theme.border }
                onAccepted: {
                    var key=network.visibleKeys[network.activeObject] ? network.activeObject : network.filteredObjects.length ? network.filteredObjects[0].key : ""
                    if (network.focusObject(key)) navigationPopup.close()
                }
            }
            RowLayout {
                Layout.fillWidth: true
                ThemedSelect {
                    objectName: "networkKindFilter"; theme: network.theme; implicitHeight: 32; Layout.fillWidth: true
                    model: network.kindOptions; currentIndex: Math.max(0,model.indexOf(network.kindFilter))
                    onActivated: network.kindFilter=currentIndex > 0 ? currentText : ""
                }
                ThemedSelect {
                    objectName: "networkCarrierFilter"; theme: network.theme; implicitHeight: 32; Layout.fillWidth: true
                    model: network.carrierOptions; currentIndex: network.carrierFilter === null ? 0 : Math.max(0,network.carrierValues.indexOf(network.carrierFilter)+1)
                    onActivated: network.carrierFilter=currentIndex > 0 ? network.carrierValues[currentIndex-1] : null
                }
            }
            Label { objectName: "networkFilterCount"; text: network.filteredObjects.length+" / "+(network.topology.objects || []).length+" objects · view-only filters"; color: network.theme.muted; font.pixelSize: 11 }
            ListView {
                id: searchResults; objectName: "networkSearchResults"
                Layout.fillWidth: true; Layout.preferredHeight: 132; clip: true
                model: network.filteredObjects
                ScrollBar.vertical: ScrollBar { }
                delegate: ItemDelegate {
                    id: result
                    required property var modelData
                    objectName: "networkSearchResult-"+modelData.kind+"-"+modelData.name
                    width: searchResults.width; height: 33
                    highlighted: network.activeObject === modelData.key
                    onClicked: network.activeObject=modelData.key
                    contentItem: Text {
                        text: result.modelData.kind+" · "+result.modelData.name+(result.modelData.carrier ? " · "+result.modelData.carrier : "")
                        color: result.highlighted || result.hovered ? network.theme.primaryText : network.theme.ink
                        elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter
                    }
                    background: Rectangle { radius: 5; color: result.highlighted || result.hovered ? network.theme.primary : network.theme.alternate }
                    ToolTip.visible: hovered; ToolTip.text: modelData.kind+" · "+modelData.name+"\nSelect, then Locate selected (or press Enter in search)."
                }
                Label { visible: !network.filteredObjects.length; anchors.centerIn: parent; text: "No matching objects. Clear filters to restore the view."; color: network.theme.muted; font.pixelSize: 11 }
            }
            RowLayout {
                Layout.fillWidth: true
                Button {
                    objectName: "networkLocateSelected"; text: "Locate selected"; implicitHeight: 32
                    enabled: !!network.objectLookup[network.activeObject]
                    onClicked: if (network.focusObject(network.activeObject)) navigationPopup.close()
                    ToolTip.visible: hovered; ToolTip.text: "Clear filters, zoom in and centre the selected object and highlight its connections."
                }
                Button { objectName: "networkClearFilters"; text: "Clear filters"; implicitHeight: 32; onClicked: network.clearFilters() }
                Button { objectName: "networkClearFocus"; text: "Clear focus"; implicitHeight: 32; onClicked: network.clearFocus() }
            }
            AtlasCheckBox { theme: network.theme
                objectName: "networkCongestionToggle"; text: "Highlight passive p0 bounds (≥ 90%)"
                enabled: network.context.frozen; checked: network.congestionEnabled
                onToggled: network.congestionEnabled=checked
            }
            Label {
                objectName: "networkCongestionLegend"; Layout.fillWidth: true; wrapMode: Text.WordWrap; font.pixelSize: 11; color: network.theme.muted
                text: "Opt-in: amber ≥ 90%, red ≥ 100% of the exported Line/Transformer p0 active-flow bound; NOT AC MVA loading. Missing bounds, p1 and converters stay uncoloured. Frozen runs only."
            }
            Button { objectName: "networkReadableGridLayout"; text: "Readable grid layout"; implicitHeight: 32; Layout.fillWidth: true; enabled: (network.topology.objects || []).length > 0; onClicked: { network.readableGridLayout(); navigationPopup.close() } }
            Label { Layout.fillWidth: true; text: "Explicitly rearrange all objects in bus-grouped grid cells. Replaces this session's positions only; Save layout persists it."; wrapMode: Text.WordWrap; color: network.theme.muted; font.pixelSize: 11 }
        }
    }

    ColumnLayout {
        anchors.fill: parent; anchors.margins: 18; spacing: 6
        RowLayout {
            Layout.fillWidth: true
            Label { text: network.context.frozen ? "Frozen-run flow schematic" : "Network schematic · live inputs"; color: network.theme.ink; font.pixelSize: 17; font.bold: true; Layout.fillWidth: true; elide: Text.ElideRight }
            Button {
                objectName: "networkNavigate"; text: "Find / filter"; implicitHeight: 32
                highlighted: !!network.searchText || !!network.kindFilter || network.carrierFilter !== null
                onClicked: navigationPopup.open()
                ToolTip.visible: hovered; ToolTip.text: "Find, filter, locate, highlight p0 bounds or apply a readable grid layout."
            }
            Button { objectName: "networkSaveLayout"; text: "Save layout"; implicitHeight: 32; enabled: !backend.uiState.busy; onClicked: if (backend.saveNetworkLayout(network.projectKey,network.layoutData())) network.layoutPending=false
                ToolTip.visible: hovered; ToolTip.text: "Save this view's layout and the project to SQLite"
            }
            Button { objectName: "networkResetLayout"; text: "Reset layout"; implicitHeight: 32; onClicked: network.resetLayout() }
            Button { objectName: "networkFitView"; text: "Fit"; implicitHeight: 32; implicitWidth: 44; onClicked: network.fitView() }
            Button { objectName: "networkZoomOut"; text: "−"; implicitHeight: 32; implicitWidth: 32; onClicked: network.zoomAt(network.zoomFactor-0.2,viewport.width/2,viewport.height/2) }
            Label { text: Math.round(network.zoomFactor*100)+"%"; color: network.theme.muted }
            Button { objectName: "networkZoomIn"; text: "+"; implicitHeight: 32; implicitWidth: 32; onClicked: network.zoomAt(network.zoomFactor+0.2,viewport.width/2,viewport.height/2) }
        }
        RowLayout {
            Layout.fillWidth: true
            Button { objectName: "networkLiveView"; text: "Live inputs"; implicitHeight: 32; highlighted: !network.context.frozen; onClicked: backend.showLiveNetwork() }
            ThemedSelect { id: runPicker; objectName: "networkRunSelect"; theme: network.theme; implicitHeight: 32; Layout.fillWidth: true; model: network.context.runs.map(function(r) { return r.name }); ToolTip.visible: hovered; ToolTip.text: currentText || "No successful runs saved here" }
            Button { objectName: "networkLoadFlows"; text: "Load flows"; implicitHeight: 32; enabled: runPicker.currentIndex >= 0; onClicked: backend.loadNetworkRun(network.context.runs[runPicker.currentIndex].path) }
            Button { objectName: "networkBrowseRun"; text: "Browse run…"; implicitHeight: 32; onClicked: backend.browseNetworkRun() }
        }
        RowLayout {
            visible: network.context.frozen; Layout.fillWidth: true
            Label { text: "Snapshot"; color: network.theme.muted }
            Button { objectName: "networkPreviousSnapshot"; text: "‹"; implicitHeight: 32; implicitWidth: 32; enabled: network.context.snapshotIndex > 0; onClicked: network.stepSnapshot(-1); ToolTip.visible: hovered; ToolTip.text: "Previous frozen snapshot (does not change Results)" }
            ThemedSelect { id: snapshotPicker; objectName: "networkSnapshotSelect"; theme: network.theme; implicitHeight: 32; Layout.fillWidth: true; model: network.context.snapshots; onActivated: backend.setNetworkSnapshot(currentIndex) }
            Button { objectName: "networkNextSnapshot"; text: "›"; implicitHeight: 32; implicitWidth: 32; enabled: network.context.snapshotIndex+1 < network.context.snapshots.length; onClicked: network.stepSnapshot(1); ToolTip.visible: hovered; ToolTip.text: "Next frozen snapshot (does not change Results)" }
            Label { text: (network.context.snapshotIndex+1)+" / "+network.context.snapshots.length; color: network.theme.muted; font.pixelSize: 11 }
            AtlasCheckBox { theme: network.theme; id: valuesVisible; text: "Show values"; checked: true }
        }
        Label {
            objectName: "networkSourceCaption"
            Layout.fillWidth: true; wrapMode: Text.WordWrap; color: network.theme.muted; font.pixelSize: 11
            // Filters and "layout saved" wording must not resize the viewport
            // after Fit/Locate and thereby move the camera or dirty a layout.
            Layout.minimumHeight: network.context.frozen ? 66 : 42
            Layout.maximumHeight: network.context.frozen ? 66 : 42
            text: network.context.source + " · " + (network.layoutPending ? "Layout not saved" : "Explicit Save layout persists this view")
                  + (network.context.frozen ? "\nArrows: bus → branch for positive p_i; branch → bus for negative p_i. MW only; dashed = unavailable. % bound is passive p0 active-flow utilisation, NOT AC MVA loading. Click for frozen details; Ctrl-click opens only an unchanged live object." : "\nExpandable workspace · drag icons to arrange · drag blank space or use scrollbars to pan · Ctrl+wheel to zoom · Ctrl-click for properties. Layout changes do not change model inputs.")
                  + (network.filteredObjects.length !== (network.topology.objects || []).length ? " · Filter: "+network.filteredObjects.length+" objects visible (Find / filter to clear)." : "")
        }
        Flickable {
            id: viewport; objectName: "networkViewport"
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            // Desktop schematic panning should stop on release, not coast and
            // bounce after the pointer has stopped (especially on Windows).
            maximumFlickVelocity: 0
            boundsBehavior: Flickable.StopAtBounds
            contentWidth: network.sceneWidth*network.zoomFactor+2*network.paperMargin
            contentHeight: network.sceneHeight*network.zoomFactor+2*network.paperMargin
            onWidthChanged: if (network.fitOnShow || network.pendingCamera !== null) Qt.callLater(network.finishInitialFit)
            onHeightChanged: if (network.fitOnShow || network.pendingCamera !== null) Qt.callLater(network.finishInitialFit)
            onContentXChanged: if (!network.restoring) network.layoutPending=true
            onContentYChanged: if (!network.restoring) network.layoutPending=true
            ScrollBar.horizontal: ScrollBar { objectName: "networkHorizontalScroll"; policy: ScrollBar.AlwaysOn }
            ScrollBar.vertical: ScrollBar { objectName: "networkVerticalScroll"; policy: ScrollBar.AlwaysOn }
            WheelHandler {
                acceptedModifiers: Qt.ControlModifier
                onWheel: function(event) {
                    // Flickable reparents handlers into its content item; map
                    // the wheel position back to visible viewport coordinates.
                    network.zoomAt(network.zoomFactor*(event.angleDelta.y > 0 ? 1.15 : 1/1.15),
                                   event.x-viewport.contentX,event.y-viewport.contentY)
                    event.accepted=true
                }
            }
            Canvas {
                    id: wires; objectName: "networkTopologyCanvas"
                    // Viewport-sized texture, irrespective of logical paper size.
                    x: viewport.contentX; y: viewport.contentY
                    width: viewport.width; height: viewport.height
                    onWidthChanged: requestPaint()
                    onHeightChanged: requestPaint()
                    onVisibleChanged: if (visible) requestPaint()
                    onAvailableChanged: if (available) requestPaint()
                    Connections { target: network.theme; function onDarkChanged() { wires.requestPaint() } }
                    Connections {
                        target: viewport
                        function onContentXChanged() { wires.requestPaint() }
                        function onContentYChanged() { wires.requestPaint() }
                    }
                    onPaint: {
                        var ctx=getContext("2d"); ctx.reset(); ctx.clearRect(0,0,width,height)
                        var zoom=network.zoomFactor, ox=scene.x-viewport.contentX, oy=scene.y-viewport.contentY
                        ctx.fillStyle=network.theme.grid
                        var spacing=24*zoom*Math.max(1,Math.ceil(10/(24*zoom)))
                        for (var gx=((ox%spacing)+spacing)%spacing;gx<width;gx+=spacing)
                            for (var gy=((oy%spacing)+spacing)%spacing;gy<height;gy+=spacing) ctx.fillRect(gx,gy,1,1)
                        ;(network.topology.wires || []).forEach(function(w) {
                            var a=network.positions[w.a], b=network.positions[w.b]
                            var style=network.wireAppearance(w)
                            if (!a || !b || !style.visible) return
                            var available=style.available
                            ctx.globalAlpha=style.alpha; ctx.strokeStyle=style.color; ctx.lineWidth=style.width*zoom
                            ctx.setLineDash(network.context.frozen && w.attribute && !available ? [5*zoom,4*zoom] : [])
                            ctx.beginPath(); ctx.moveTo(ox+a.x*zoom,oy+a.y*zoom); ctx.lineTo(ox+b.x*zoom,oy+b.y*zoom); ctx.stroke()
                            if (available && Math.abs(w.flow) > 1e-8) {
                                // a is branch, b is bus: positive withdrawal points b -> a.
                                var dx=(a.x-b.x)*(w.flow > 0 ? 1 : -1), dy=(a.y-b.y)*(w.flow > 0 ? 1 : -1)
                                var angle=Math.atan2(dy,dx), x=ox+(a.x+b.x)/2*zoom, y=oy+(a.y+b.y)/2*zoom
                                ctx.setLineDash([]); ctx.beginPath()
                                ctx.moveTo(x+8*zoom*Math.cos(angle),y+8*zoom*Math.sin(angle))
                                ctx.lineTo(x-6*zoom*Math.cos(angle)+5*zoom*Math.sin(angle),y-6*zoom*Math.sin(angle)-5*zoom*Math.cos(angle))
                                ctx.lineTo(x-6*zoom*Math.cos(angle)-5*zoom*Math.sin(angle),y-6*zoom*Math.sin(angle)+5*zoom*Math.cos(angle))
                                ctx.closePath(); ctx.fillStyle=style.color; ctx.fill()
                            }
                        })
                    }
            }
            Item {
                id: scene
                x: network.paperMargin; y: network.paperMargin
                width: network.sceneWidth; height: network.sceneHeight
                scale: network.zoomFactor; transformOrigin: Item.TopLeft
                Repeater {
                    model: network.context.frozen && valuesVisible.checked ? (network.topology.wires || []).filter(function(w) { return !!w.attribute }) : []
                    delegate: Rectangle {
                        required property var modelData
                        objectName: "flowLabel-" + modelData.a + "-" + modelData.port
                        visible: network.wireIsVisible(modelData)
                        property var a: network.positions[modelData.a] || {x:0,y:0}
                        property var b: network.positions[modelData.b] || {x:0,y:0}
                        property string referenceComponent: JSON.parse(modelData.a)[0]
                        property string referenceProperty: modelData.attribute
                        property real length: Math.max(1,Math.sqrt(Math.pow(b.x-a.x,2)+Math.pow(b.y-a.y,2)))
                        property real nx: (b.y-a.y)/length
                        property real ny: -(b.x-a.x)/length
                        property real side: nx*((a.x+b.x)/2-network.sceneWidth/2)+ny*((a.y+b.y)/2-network.sceneHeight*0.47) >= 0 ? 1 : -1
                        x: (a.x+b.x)/2-width/2+nx*32*side; y: (a.y+b.y)/2-height/2+ny*32*side
                        width: flowLabel.implicitWidth+10; height: 20; radius: 4
                        color: network.activeObject === modelData.a ? network.theme.callout : network.theme.panel
                        border.color: network.activeObject === modelData.a ? network.theme.focus : network.theme.border
                        Label { id: flowLabel; anchors.centerIn: parent; text: network.flowText(modelData); color: network.activeObject === modelData.a ? network.theme.calloutInk : network.theme.ink; font.pixelSize: 10 }
                        MouseArea { anchors.fill: parent; onClicked: { parent.forceActiveFocus(); network.activeObject=parent.modelData.a } }
                    }
                }
                Repeater {
                    id: nodes; objectName: "networkObjectRepeater"
                    model: network.topology.objects || []
                    delegate: Item {
                        id: node
                        required property var modelData
                        property string referenceComponent: modelData.kind
                        property string referenceProperty: "name"
                        objectName: "networkObject-" + modelData.kind + "-" + modelData.name
                        visible: !!network.visibleKeys[modelData.key]
                        readonly property bool selected: network.activeObject === modelData.key
                        readonly property bool connected: !!network.activeObject && !selected && !!network.focusKeys[modelData.key]
                        // Keep wires anchored to the icon centre; reserve enough
                        // hit area below the name for a draggable carrier badge.
                        width: 100; height: modelData.carrier ? 124 : 88
                        x: (network.positions[modelData.key] || {x:50}).x-width/2
                        y: (network.positions[modelData.key] || {y:50}).y-height/2
                        z: network.activeObject === modelData.key ? 2 : 1
                        Rectangle {
                            objectName: "networkFocusRing-"+node.modelData.kind+"-"+node.modelData.name
                            anchors.centerIn: parent; width: 60; height: 60; radius: node.modelData.kind === "Bus" ? 30 : 14
                            visible: node.selected || node.connected; color: "transparent"
                            border.color: network.theme.focus; border.width: node.selected ? 3 : 1.5
                        }
                        Rectangle {
                            anchors.centerIn: parent
                            width: 44; height: 44; radius: node.modelData.kind === "Bus" ? 22 : 9
                            color: node.selected ? network.theme.callout : gesture.containsMouse ? network.theme.hover : network.theme.field
                            border.color: node.selected ? network.theme.focus : network.theme.technologyColor(node.modelData.carrier,node.modelData.kind)
                            Image {
                                anchors.centerIn: parent; width: 26; height: 26
                                source: NetworkIcons.source(node.modelData.kind, node.selected ? network.theme.calloutInk : network.theme.technologyColor(node.modelData.carrier,node.modelData.kind))
                            }
                        }
                        Label {
                            anchors.top: parent.top; anchors.topMargin: node.height/2+25; width: parent.width
                            text: node.modelData.name; elide: Text.ElideRight
                            horizontalAlignment: Text.AlignHCenter; color: network.theme.ink; font.pixelSize: 11
                        }
                        Rectangle {
                            objectName: "carrierBadge-" + node.modelData.kind + "-" + node.modelData.name
                            visible: !!node.modelData.carrier
                            anchors.horizontalCenter: parent.horizontalCenter
                            y: node.height/2+43
                            width: Math.min(node.width, carrierLabel.implicitWidth+14); height: 18; radius: 9
                            color: network.theme.alternate; border.color: network.theme.border
                            Label {
                                id: carrierLabel
                                anchors.fill: parent; anchors.leftMargin: 7; anchors.rightMargin: 7
                                text: node.modelData.carrier; textFormat: Text.PlainText
                                color: network.theme.ink; font.pixelSize: 9; elide: Text.ElideRight
                                horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                            }
                        }
                        MouseArea {
                            id: gesture; anchors.fill: parent; hoverEnabled: true; preventStealing: true
                            cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                            property bool moving: false
                            property bool updating: false
                            property point pointer: Qt.point(0,0)
                            property point initialPointer: Qt.point(0,0)
                            property point grabOffset: Qt.point(0,0)
                            function updatePosition() {
                                if (!moving || updating) return
                                updating=true
                                network.moveObject(node.modelData.key,
                                    (viewport.contentX+pointer.x-scene.x)/network.zoomFactor-grabOffset.x,
                                    (viewport.contentY+pointer.y-scene.y)/network.zoomFactor-grabOffset.y)
                                updating=false
                            }
                            function edgeScroll() {
                                if (!pressed || !moving) return
                                var dx=pointer.x < 28 ? -12 : pointer.x > viewport.width-28 ? 12 : 0
                                var dy=pointer.y < 28 ? -12 : pointer.y > viewport.height-28 ? 12 : 0
                                viewport.contentX=Math.max(0,Math.min(viewport.contentWidth-viewport.width,viewport.contentX+dx))
                                viewport.contentY=Math.max(0,Math.min(viewport.contentHeight-viewport.height,viewport.contentY+dy))
                                updatePosition()
                            }
                            onPressed: function(mouse) {
                                node.forceActiveFocus(); network.activeObject=node.modelData.key
                                moving=false
                                pointer=mapToItem(viewport,mouse.x,mouse.y); initialPointer=pointer
                                var world=mapToItem(scene,mouse.x,mouse.y), point=network.positions[node.modelData.key]
                                grabOffset=Qt.point(world.x-point.x,world.y-point.y)
                            }
                            onPositionChanged: function(mouse) {
                                if (!pressed || updating) return
                                pointer=mapToItem(viewport,mouse.x,mouse.y)
                                if (!moving && (Math.abs(pointer.x-initialPointer.x) > Qt.styleHints.startDragDistance
                                               || Math.abs(pointer.y-initialPointer.y) > Qt.styleHints.startDragDistance)) {
                                    moving=true; network.activeDrag=gesture
                                }
                                updatePosition()
                            }
                            onReleased: {
                                updatePosition(); network.activeDrag=null
                            }
                            onCanceled: { network.activeDrag=null; moving=false }
                            Component.onDestruction: if (network.activeDrag === gesture) network.activeDrag=null
                            onClicked: function(mouse) {
                                if (!moving && (mouse.modifiers & Qt.ControlModifier)) network.inspect(node.modelData.kind,node.modelData.name)
                            }
                            ToolTip.visible: containsMouse && !pressed
                            ToolTip.text: node.modelData.kind + " · " + node.modelData.name
                                          + (node.modelData.carrier ? "\nCarrier: " + node.modelData.carrier : "")
                                          + "\nDrag to move · Ctrl-click object properties"
                        }
                    }
                }
                Label {
                    visible: !(network.topology.objects || []).length
                    anchors.centerIn: parent; text: "Add objects to see your network."; color: network.theme.muted
                }
            }
            Label {
                objectName: "networkNoMatches"; visible: (network.topology.objects || []).length > 0 && !network.filteredObjects.length
                x: viewport.contentX+(viewport.width-width)/2; y: viewport.contentY+(viewport.height-height)/2
                text: "No matching objects · Find / filter → Clear filters"; color: network.theme.muted
            }
        }
        ScrollView {
            visible: network.context.frozen
            Layout.fillWidth: true; Layout.preferredHeight: 70
            TextArea {
                objectName: "networkObjectDetails"; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap
                color: network.theme.ink; font.pixelSize: 11
                text: ((network.topology.objects || []).find(function(o) { return o.key === network.activeObject }) || {}).detail || "Select an object for frozen-run details."
            }
        }
    }
}
