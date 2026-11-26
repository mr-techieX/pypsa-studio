import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: navigator
    objectName: "chartTimelineNavigator"
    required property var theme
    required property var info
    color: theme.alternate; radius: 7; border.color: theme.border
    function commit() { if (info.count > 0) backend.setChartRange(Math.round(range.first.value), Math.round(range.second.value)) }
    function moveBy(delta) {
        var span=range.second.value-range.first.value
        var first=Math.max(0,Math.min(info.count-1-span,range.first.value+delta))
        range.setValues(first,first+span); delayed.restart()
    }
    // Wait for `to` to reflect the new count before assigning values; otherwise
    // Qt clamps the right handle to the previous (often empty-query) maximum.
    onInfoChanged: Qt.callLater(function() {
        if (!range.first.pressed && !range.second.pressed && !pan.pressed)
            range.setValues(info.first,info.last)
    })
    Timer { id: delayed; interval: 100; onTriggered: navigator.commit() }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 7; spacing: 0
        RowLayout {
            Label { text: "Chart window · "+(navigator.info.first+1)+"–"+(navigator.info.last+1)+" / "+navigator.info.count; color: navigator.theme.ink; font.pixelSize: 11; Layout.fillWidth: true }
            Button { objectName: "timelinePrevious"; text: "‹"; implicitWidth: 32; implicitHeight: 24; onClicked: navigator.moveBy(-Math.max(1,Math.round((range.second.value-range.first.value+1)/2))) }
            Button { objectName: "timelineNext"; text: "›"; implicitWidth: 32; implicitHeight: 24; onClicked: navigator.moveBy(Math.max(1,Math.round((range.second.value-range.first.value+1)/2))) }
            Button { objectName: "timelineReset"; text: "Full range"; implicitHeight: 24; onClicked: { range.setValues(0,navigator.info.count-1); navigator.commit() } }
        }
        RangeSlider {
            id: range; objectName: "chartTimelineRange"
            Layout.fillWidth: true; Layout.preferredHeight: 30
            from: 0; to: Math.max(1,navigator.info.count-1); stepSize: 1
            enabled: navigator.info.count > 1
            first.value: navigator.info.first; second.value: navigator.info.last
            first.onMoved: delayed.restart()
            second.onMoved: delayed.restart()
            first.handle: Rectangle {
                objectName: "timelineLeftHandle"; x: range.leftPadding+range.first.visualPosition*(range.availableWidth-width)
                y: (range.height-height)/2; width: 18; height: 28; radius: 4
                color: navigator.theme.focus; border.color: navigator.theme.ink
                Accessible.name: "Chart window start"
            }
            second.handle: Rectangle {
                objectName: "timelineRightHandle"; x: range.leftPadding+range.second.visualPosition*(range.availableWidth-width)
                y: (range.height-height)/2; width: 18; height: 28; radius: 4
                color: navigator.theme.focus; border.color: navigator.theme.ink
                Accessible.name: "Chart window end"
            }
            background: Rectangle {
                x: range.leftPadding; y: range.height/2-7; width: range.availableWidth; height: 14; radius: 4
                color: navigator.theme.field; border.color: navigator.theme.border
                Rectangle {
                    x: range.first.position*parent.width
                    width: (range.second.position-range.first.position)*parent.width
                    height: parent.height; color: navigator.theme.selected
                }
            }
        }
        Label {
            text: navigator.info.fromLabel+" → "+navigator.info.toLabel+" · drag either handle to zoom; drag the selection to pan"
            color: navigator.theme.muted; font.pixelSize: 10; Layout.fillWidth: true; elide: Text.ElideMiddle
        }
    }
    // A sibling overlay avoids RangeSlider interpreting selection dragging as
    // another nearest-handle gesture. Keep both end handles exposed.
    MouseArea {
        id: pan; objectName: "timelinePan"
        x: range.mapToItem(navigator,range.leftPadding,0).x+range.first.position*range.availableWidth+18
        y: range.mapToItem(navigator,0,range.height/2).y-7
        width: Math.max(0,(range.second.position-range.first.position)*range.availableWidth-36)
        height: 14; enabled: width > 8 && navigator.info.count > 1
        z: 5; cursorShape: Qt.SizeHorCursor
        property real original: 0
        property real first: 0
        property real last: 0
        onPressed: function(mouse) { original=mapToItem(range,mouse.x,0).x; first=range.first.value; last=range.second.value }
        onPositionChanged: function(mouse) {
            if (!pressed) return
            var delta=Math.round((mapToItem(range,mouse.x,0).x-original)/range.availableWidth*(navigator.info.count-1))
            var next=Math.max(0,Math.min(navigator.info.count-1-(last-first),first+delta))
            range.setValues(next,next+last-first); delayed.restart()
        }
    }
}
