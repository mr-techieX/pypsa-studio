import QtQuick
import QtQuick.Controls

CheckBox {
    id: control
    required property var theme
    hoverEnabled: true
    spacing: 8
    implicitHeight: 30
    indicator: Rectangle {
        x: control.leftPadding
        y: (control.height-height)/2
        width: 18; height: 18; radius: 3
        color: control.checked || control.checkState === Qt.PartiallyChecked
               ? (control.enabled ? control.theme.primary : control.theme.buttonDown)
               : control.theme.field
        border.color: control.activeFocus ? control.theme.focus : control.theme.border
        border.width: control.activeFocus ? 2 : 1
        Text {
            anchors.centerIn: parent
            text: control.checkState === Qt.PartiallyChecked ? "−" : control.checked ? "✓" : ""
            color: control.enabled ? control.theme.primaryText : control.theme.ink
            font.pixelSize: 14; font.bold: true
        }
    }
    contentItem: Text {
        text: control.text; font: control.font
        color: control.enabled ? control.theme.ink : control.theme.muted
        leftPadding: control.indicator.width+control.spacing
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Rectangle {
        radius: 4
        color: control.down ? control.theme.buttonDown
               : control.hovered && control.enabled ? control.theme.hover : "transparent"
    }
}
