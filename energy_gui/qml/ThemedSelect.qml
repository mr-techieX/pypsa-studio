import QtQuick
import QtQuick.Controls
import QtQml.Models

ComboBox {
    id: control
    required property var theme
    property bool headerMode: false
    implicitHeight: 38; implicitWidth: 180
    // Popups live in the window overlay, outside their owner's clipping tree.
    // Close rather than let one float over unrelated content after scrolling.
    property var watchedAncestors: []
    function watchAncestors() {
        var items = [], item = parent
        while (item) { items.push(item); item = item.parent }
        watchedAncestors = items
    }
    function checkFocus() {
        if (!popup.visible || !control.Window.window) return
        if (popup.activeFocus) return
        var item = control.Window.window.activeFocusItem
        while (item) {
            if (item === control || item === popup.contentItem) return
            item = item.parent
        }
        popup.close()
    }
    Component.onCompleted: watchAncestors()
    onParentChanged: { popup.close(); watchAncestors() }
    onVisibleChanged: if (!visible) popup.close()
    onEnabledChanged: if (!enabled) popup.close()
    onModelChanged: popup.close()
    onXChanged: popup.close()
    onYChanged: popup.close()
    onWidthChanged: popup.close()
    onHeightChanged: popup.close()
    Instantiator {
        model: control.watchedAncestors
        delegate: Connections {
            required property var modelData
            target: modelData; ignoreUnknownSignals: true
            function onContentXChanged() { control.popup.close() }
            function onContentYChanged() { control.popup.close() }
            function onMovingChanged() { control.popup.close() }
            function onXChanged() { control.popup.close() }
            function onYChanged() { control.popup.close() }
            function onWidthChanged() { control.popup.close() }
            function onHeightChanged() { control.popup.close() }
            function onVisibleChanged() { control.popup.close() }
            function onParentChanged() { control.popup.close(); Qt.callLater(control.watchAncestors) }
        }
    }
    Connections {
        target: control.Window.window
        function onActiveFocusItemChanged() { Qt.callLater(control.checkFocus) }
        function onActiveChanged() { if (!control.Window.window.active) control.popup.close() }
    }
    contentItem: Text {
        text: control.displayText; color: control.headerMode ? control.theme.headerInk : control.enabled ? control.theme.ink : control.theme.muted; font: control.font
        leftPadding: 10; rightPadding: 26
        verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
    }
    background: Rectangle { color: control.headerMode ? control.theme.header : control.theme.field; radius: 7; border.color: control.activeFocus ? control.theme.focus : control.headerMode ? control.theme.headerMuted : control.theme.border }
    indicator: Text { text: "▾"; color: control.headerMode ? control.theme.headerMuted : control.theme.muted; x: control.width-22; y: 10 }
    delegate: ItemDelegate {
        id: option
        required property int index
        required property var modelData
        objectName: "dropdownOption" + index
        width: control.width-8; height: 36; hoverEnabled: true
        highlighted: control.highlightedIndex === index
        contentItem: Text {
            text: String(option.modelData); font: control.font
            color: option.highlighted || option.hovered ? control.theme.primaryText : control.theme.ink
            verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
        }
        background: Rectangle { radius: 5; color: option.highlighted || option.hovered ? control.theme.primary : control.theme.panel }
    }
    popup: Popup {
        // Keep keyboard focus on ComboBox so arrows/Enter retain native behavior.
        focus: false
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
        enter: Transition { }
        exit: Transition { }
        y: control.height+4; width: control.width; padding: 4
        implicitHeight: Math.min(contentItem.implicitHeight+8, 320)
        background: Rectangle { color: control.theme.panel; radius: 7; border.color: control.theme.border }
        contentItem: ListView {
            clip: true; implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator { }
        }
    }
}
