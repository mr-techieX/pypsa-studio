import QtQuick

// Small local SVG line icons: no fonts, remote assets or platform glyphs.
Image {
    required property string symbol
    required property color ink
    width: 18; height: 18
    sourceSize.width: 36; sourceSize.height: 36
    readonly property var paths: ({
        file: "M5 3h9l5 5v13H5z M14 3v6h5 M8 13h8 M8 17h6",
        save: "M4 3h14l3 3v15H3V3z M7 3v7h10V3 M7 21v-7h10v7",
        model: "M3 4h6v6H3z M15 14h6v6h-6z M6 10v7h9 M9 7h9v7",
        data: "M3 4h18v16H3z M3 9h18 M9 4v16 M15 9v11 M3 14h18",
        check: "M4 12l5 5L20 6",
        run: "M7 4l13 8-13 8z",
        results: "M4 3v18h17 M8 16v-5 M13 16V7 M18 16v-8",
        help: "M9 8a3 3 0 1 1 4 3c-1 1-1 1-1 3 M12 17v.1 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
        chevron: "M8 10l4 4 4-4"
    })
    source: "data:image/svg+xml," + encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
        + '<path d="' + (paths[symbol] || paths.file) + '" fill="none" stroke="'
        + ink + '" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>')
}
