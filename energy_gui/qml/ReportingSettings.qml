import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: reports
    required property var theme
    property var resolutions: []
    readonly property string specification: JSON.stringify(resolutions)
    implicitHeight: 84
    color: theme.panel; border.color: theme.border; radius: 10
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 10; spacing: 2
        RowLayout {
            Label { text: "Reports after run"; color: reports.theme.ink; font.pixelSize: 12 }
            Repeater {
                model: ["native","hourly","daily","weekly","monthly","yearly"]
                delegate: AtlasCheckBox {
                    required property string modelData
                    objectName: "reportResolution-"+modelData; theme: reports.theme
                    text: modelData; checked: reports.resolutions.indexOf(modelData) >= 0
                    onClicked: reports.resolutions=checked ? reports.resolutions.concat([modelData]) : reports.resolutions.filter(function(r) { return r !== modelData })
                }
            }
            Item { Layout.fillWidth: true }
        }
        Label {
            text: "Optional calendar CSVs + HTML index in the run's reports folder. Native data retained; unsupported quantities listed, not guessed."
            color: reports.theme.muted; font.pixelSize: 11; wrapMode: Text.WordWrap; Layout.fillWidth: true
        }
    }
}
