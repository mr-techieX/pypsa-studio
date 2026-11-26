.pragma library

// Central icon dictionary. SVG paths are local, theme-tinted and dependency-free.
// New/unknown types get the fallback until a dedicated symbol is registered.
var icons = {
    Bus: '<path d="M5 5v14M10 5v14M15 5v14M20 5v14M3 12h19"/>',
    Generator: '<circle cx="12" cy="12" r="9"/><path d="M5 12q3-8 7 0t7 0"/>',
    Load: '<path d="M12 3v15m-6-6 6 7 6-7M4 22h16"/>',
    StorageUnit: '<rect x="3" y="6" width="18" height="15" rx="2"/><path d="M8 3h8M13 8l-4 6h6l-4 5"/>',
    Store: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',
    Line: '<path d="M3 20 10 3h4l7 17M5 10h14M4 15h16M8 20l8-10M16 20 8 10"/>',
    Transformer: '<circle cx="9" cy="12" r="6"/><circle cx="15" cy="12" r="6"/><path d="M1 12h2m18 0h2"/>',
    Link: '<path d="M3 8h17l-5-5M21 16H4l5 5"/>',
    Process: '<path d="m12 2 9 5v10l-9 5-9-5V7zM7 12h10m-4-4 4 4-4 4"/>',
    ShuntImpedance: '<path d="M12 2v7M5 9h14M5 13h14M12 13v8M6 22h12"/>',
    Carrier: '<path d="M13 2C9 8 4 10 5 16a7 7 0 0 0 14 0c0-4-3-7-3-7l-3 4z"/>',
    GlobalConstraint: '<path d="m12 2 9 4v7c0 5-9 9-9 9s-9-4-9-9V6zM7 12l3 3 7-7"/>',
    SubNetwork: '<rect x="8" y="2" width="8" height="6"/><rect x="2" y="17" width="7" height="5"/><rect x="15" y="17" width="7" height="5"/><path d="M12 8v5H5v4m7-4h7v4"/>',
    Shape: '<path d="m4 3 16 3 1 13-10 3-9-9z"/>',
    LineType: '<path d="M4 3h16v18H4zM7 7h10M7 12h10M7 17h6"/>',
    TransformerType: '<path d="M3 3h18v18H3z"/><circle cx="9" cy="12" r="4"/><circle cx="15" cy="12" r="4"/>'
}
var fallback = '<path d="m12 2 10 10-10 10L2 12zM8 12h8M12 8v8"/>'

function source(kind, color) {
    return "data:image/svg+xml;utf8," + encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="' +
        color + '" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' +
        (icons[kind] || fallback) + '</svg>')
}
