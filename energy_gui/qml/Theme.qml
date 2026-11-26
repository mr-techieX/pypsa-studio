import QtQuick

QtObject {
    readonly property bool dark: appearance.dark
    // Atlas palette: cartographic parchment, deep ink, map teal and solar ochre.
    readonly property color window: dark ? "#0e202e" : "#f1ebdd"
    readonly property color panel: dark ? "#172d3c" : "#fbf8f0"
    readonly property color sidebar: dark ? "#122735" : "#e8e2d4"
    readonly property color field: dark ? "#102532" : "#fffdf7"
    readonly property color border: dark ? "#526a77" : "#a7aa9d"
    readonly property color ink: dark ? "#f3f4ed" : "#192c35"
    readonly property color muted: dark ? "#bccbd0" : "#4f605f"
    // The branded header stays navy in both modes, independently of page surfaces.
    readonly property color header: dark ? "#0b1e2b" : "#183e50"
    readonly property color headerInk: "#f7f5eb"
    readonly property color headerMuted: "#c5d7d9"
    readonly property color headerHover: "#2d5361"
    readonly property color accent: dark ? "#65b9ac" : "#236b66"
    readonly property color selected: dark ? "#665222" : "#acd0c2"
    readonly property color hover: dark ? "#284553" : "#dce8df"
    readonly property color button: dark ? "#233e4b" : "#e8e2d5"
    readonly property color buttonDown: dark ? "#375764" : "#c4d5c7"
    readonly property color primaryText: dark ? "#152c38" : "#ffffff"
    readonly property color primary: dark ? "#e6b552" : "#245d5a"
    readonly property color primaryHover: dark ? "#f0c875" : "#194c49"
    readonly property color alternate: dark ? "#142936" : "#f2eee5"
    readonly property color grid: dark ? "#334e5c" : "#d8d0c0"
    readonly property color feature: dark ? "#1f3c40" : "#e7eadf"
    // Selection is gold; alerts use orange/red so selection never implies a fault.
    readonly property color focus: dark ? "#e6b552" : "#80601c"
    readonly property color callout: "#edbf50"
    readonly property color calloutInk: "#152c38"
    readonly property color warning: dark ? "#ffb087" : "#8d461c"
    readonly property color danger: dark ? "#f09188" : "#a33f3b"
    readonly property color success: dark ? "#87cfb0" : "#28684f"
    readonly property color wind: dark ? "#65c6b2" : "#23756b"
    readonly property color solar: dark ? "#f0c350" : "#8c6517"
    readonly property color hydro: dark ? "#80c6df" : "#346f8e"
    readonly property color gas: dark ? "#e79c8b" : "#a45143"
    readonly property color biomass: dark ? "#a7d18b" : "#4b7538"
    readonly property color storage: dark ? "#a6bcd4" : "#526d89"
    readonly property color neutral: dark ? "#c2cdd0" : "#53666a"
    // Explicit carrier labels only: never infer a technology from an object's name.
    function technologyColor(carrier, kind) {
        var value=String(carrier || "").toLowerCase()
        if (/wind/.test(value)) return wind
        if (/solar|photovoltaic/.test(value)) return solar
        if (/hydro|water|ror/.test(value)) return hydro
        if (/biomass|biogas/.test(value)) return biomass
        if (/gas|ccgt|ocgt|coal|oil|lignite/.test(value)) return gas
        if (/battery|storage/.test(value) || kind === "StorageUnit" || kind === "Store") return storage
        return neutral
    }
    // Ordered series slots remain stable during live theme switches.
    readonly property var chartColors: dark
        ? ["#e6b552", "#65c6b2", "#80c6df", "#a7d18b", "#e79c8b", "#a6bcd4"]
        : ["#236b66", "#8c6517", "#346f8e", "#4b7538", "#a45143", "#526d89"]
}
