import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ToolButton {
    id: control
    required property var theme
    property string symbol: "file"
    property string hint: text
    property bool menuButton: false
    property bool primary: false
    property bool compact: false
    property bool headerMode: false
    implicitHeight: 32
    implicitWidth: body.implicitWidth + 20
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.name: text
    ToolTip.visible: hovered
    ToolTip.delay: 600
    ToolTip.text: hint
    contentItem: RowLayout {
        id: body
        spacing: 7
        RibbonIcon {
            symbol: control.symbol
            ink: control.headerMode ? control.theme.headerInk : !control.enabled ? control.theme.muted : control.primary ? control.theme.primaryText : control.theme.accent
            Layout.preferredWidth: 17; Layout.preferredHeight: 17
            opacity: control.enabled ? 1 : 0.45
        }
        Label {
            visible: !control.compact
            text: control.text
            font.pixelSize: 12; font.weight: control.primary ? Font.DemiBold : Font.Medium
            color: control.headerMode ? control.theme.headerInk : !control.enabled ? control.theme.muted : control.primary ? control.theme.primaryText : control.theme.ink
            opacity: control.enabled ? 1 : 0.55
        }
        RibbonIcon {
            visible: control.menuButton
            symbol: "chevron"; ink: control.theme.muted
            Layout.preferredWidth: 12; Layout.preferredHeight: 12
        }
    }
    background: Rectangle {
        radius: 5
        color: control.primary && control.enabled
               ? (control.down || control.hovered ? control.theme.primaryHover : control.theme.primary)
               : control.headerMode ? (control.hovered || control.down ? control.theme.headerHover : "transparent")
               : control.down ? control.theme.buttonDown : control.hovered ? control.theme.hover : "transparent"
        border.width: control.activeFocus ? 2 : control.primary ? 0 : 1
        border.color: control.activeFocus ? control.theme.focus : "transparent"
    }
}
