import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: horizon
    required property var theme
    property bool busy: false
    property string projectStart: "2027-01-01T00:00:00"
    property bool custom: mode.currentIndex === 1
    property string specification: JSON.stringify({
        start: start.text, duration: duration.value, duration_unit: durationUnit.currentText,
        snapshot_size: snapshotSize.value, snapshot_unit: snapshotUnit.currentText,
        step_count: count.value, step_size: stepSize.value, step_unit: stepUnit.currentText,
        profile_policy: repeatDaily.checked ? "repeat_daily" : "exact"
    })
    property var preview: custom ? backend.previewHorizon(specification, false) : ({valid:true, summary:"Use the existing project snapshots in one optimization.", steps:[]})
    property bool valid: !!preview.valid
    signal startRequested()
    implicitHeight: custom ? 330 : 64
    color: theme.panel; border.color: custom && !valid ? theme.danger : theme.border; radius: 10
    enabled: !busy
    function sync() {
        var result = backend.previewHorizon(specification, true)
        if (result.valid) count.value = result.count
        else backend.showHorizonMessage(result.summary)
    }
    onProjectStartChanged: start.text = projectStart
    component Caption: Label { color: horizon.theme.muted; font.pixelSize: 11 }
    component Input: TextField {
        color: horizon.theme.ink; selectByMouse: true
        background: Rectangle { color: horizon.theme.field; border.color: parent.activeFocus ? horizon.theme.focus : horizon.theme.border; radius: 5 }
    }
    component Number: SpinBox { from: 1; to: 100000; editable: true; live: true; implicitWidth: 116 }
    component Units: ThemedSelect { theme: horizon.theme; model: ["hour","day","week","month","year"]; implicitWidth: 108; implicitHeight: 32 }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 12; spacing: 6
        RowLayout {
            Caption { text: "Execution"; Layout.preferredWidth: 110 }
            ThemedSelect {
                id: mode; objectName: "horizonMode"; theme: horizon.theme
                model: ["Project snapshots · one solve", "Configured sequential steps"]
                Layout.fillWidth: true; implicitHeight: 32
            }
        }
        GridLayout {
            visible: horizon.custom; columns: 5; columnSpacing: 8; rowSpacing: 5
            Layout.fillWidth: true
            Caption { text: "Start (ISO date/time)"; Layout.preferredWidth: 140 }
            Input { id: start; objectName: "horizonStart"; text: horizon.projectStart; Layout.columnSpan: 4; Layout.fillWidth: true }
            Caption { text: "Overall upper bound" }
            Number { id: duration; objectName: "horizonDuration"; value: 1 }
            Units { id: durationUnit; objectName: "horizonDurationUnit"; currentIndex: 3 }
            Caption { text: "Snapshot interval"; Layout.preferredWidth: 112 }
            RowLayout {
                Number { id: snapshotSize; objectName: "horizonSnapshotSize"; value: 1 }
                Units { id: snapshotUnit; objectName: "horizonSnapshotUnit"; currentIndex: 0 }
            }
            Caption { text: "Optimization step size" }
            Number { id: stepSize; objectName: "horizonStepSize"; value: 1 }
            Units { id: stepUnit; objectName: "horizonStepUnit"; currentIndex: 1 }
            Caption { text: "Number of solves" }
            RowLayout {
                Number { id: count; objectName: "horizonStepCount"; to: 10000; value: 1 }
                Button { objectName: "horizonSync"; text: "Sync Horizon"; onClicked: horizon.sync() }
            }
        }
        AtlasCheckBox {
            id: repeatDaily; objectName: "horizonRepeatDaily"
            visible: horizon.custom; theme: horizon.theme
            text: "Repeat daily profiles (one complete input day, matching snapshot interval)"
            ToolTip.visible: hovered
            ToolTip.text: "Repeat all imported input profiles by time of day, even on new run dates. Original inputs are unchanged; storage states still carry forward."
        }
        Label {
            objectName: "horizonPreview"; visible: horizon.custom; Layout.fillWidth: true
            text: horizon.preview.summary || ""; color: horizon.valid ? horizon.theme.success : horizon.theme.danger
            wrapMode: Text.WordWrap; font.pixelSize: 11
        }
        RowLayout {
            visible: horizon.custom
            Caption { text: "Separate solves · state carried forward · no look-ahead · free terminal energy"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            Button {
                objectName: "horizonSchedule"; text: "View schedule"
                enabled: horizon.valid
                onClicked: backend.showHorizonMessage(horizon.preview.steps.map(function(s) {
                    return s.number + ": " + s.start + " → " + s.end + " (exclusive)"
                }).join("\n"))
            }
        }
    }
}
