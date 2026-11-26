"""Offline, escaped HTML/SVG reports and solver-symbol annotation."""

import csv
from html import escape
import json
import math
from pathlib import Path
import re


def chart_svg(charts):
    if not charts:
        raise ValueError("The query has no numeric charts to export.")
    if len(charts) > 30:
        raise ValueError("Export at most 30 numeric chart properties at once.")
    width, panel = 1100, 340
    # Exports deliberately use the Atlas print/light palette regardless of OS mode.
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{panel*len(charts)}" viewBox="0 0 {width} {panel*len(charts)}" fill="#192c35">', '<rect width="100%" height="100%" fill="#fffdf7"/>']
    colors = ["#236b66", "#8c6517", "#346f8e", "#4b7538", "#a45143", "#526d89"]
    for ci, chart in enumerate(charts):
        top = ci*panel
        parts.append(f'<g transform="translate(0,{top})"><text x="20" y="25" fill="#192c35" font-size="16">{escape(chart["title"])} [{escape(chart["unit"])}] · {escape(chart["kind"])}</text>')
        series = chart["series"]
        values = [v for s in series for v in s["values"] if v is not None]
        if not values:
            parts.append('<text x="20" y="60">No finite values</text></g>')
            continue
        n = max(len(s["values"]) for s in series)
        numeric_x = any("x_values" in s for s in series)
        coordinates = []
        if numeric_x:
            if chart["kind"] not in {"line", "dot"}:
                raise ValueError("Numeric chart coordinates support line/dot only.")
            for s in series:
                xs = s.get("x_values", [])
                if len(xs) != len(s["values"]) or any(type(v) not in (int, float) or not math.isfinite(v) for v in xs):
                    raise ValueError("Numeric x coordinates must align with finite chart values.")
                if any(a > b for a, b in zip(xs, xs[1:])):
                    raise ValueError("Numeric chart x coordinates must be increasing (step ties allowed).")
                coordinates.extend(xs)
        x_low, x_high = (min(0, min(coordinates)), max(coordinates)) if coordinates else (0, 1)
        stacked = chart["kind"] == "stacked area"
        maxima = [sum(s["values"][i] for s in series) for i in range(n)] if stacked else values
        low, high = min(0, min(values)), max(0, max(maxima))
        span = high-low or 1
        def x(i): return 85 + i*980/max(1, n-1)
        def point_x(i, s):
            return 85 + (s["x_values"][i]-x_low)*980/(x_high-x_low or 1) if numeric_x else x(i)
        def y(v): return 280 - (v-low)*210/span
        parts.append('<path d="M85 60 V280 H1065" fill="none" stroke="#a7aa9d"/>')
        if chart["kind"] == "horizontal bar":
            parts.append(f'<text x="85" y="305">{low:.5g}</text><text x="1065" y="305" text-anchor="end">{high:.5g}</text>')
        else:
            parts.append(f'<text x="12" y="65">{high:.5g}</text><text x="12" y="280">{low:.5g}</text>')
        base = [0.0]*n
        for si, s in enumerate(series):
            color = colors[si % len(colors)]
            parts.append(f'<text x="{85+si*155}" y="48" fill="{color}">{escape(s["name"][:24])}</text>')
            if stacked:
                upper = [base[i]+v for i, v in enumerate(s["values"])]
                coords = [(x(i), y(v)) for i,v in enumerate(upper)] + [(x(i), y(base[i])) for i in reversed(range(n))]
                parts.append(f'<polygon points="{" ".join(f"{a:.2f},{b:.2f}" for a,b in coords)}" fill="{color}" fill-opacity="0.7"/>')
                base = upper
            elif chart["kind"] == "horizontal bar":
                # Static horizontal previews are categorical; preserve signs and
                # identity labels, with a chart-height bound inherited upstream.
                for i,v in enumerate(s["values"]):
                    if v is None: continue
                    py = 65+i*205/max(n, 1)
                    zero = 85+(0-low)*980/span
                    end = 85+(v-low)*980/span
                    parts.append(f'<rect x="{min(zero,end):.2f}" y="{py:.2f}" width="{abs(end-zero):.2f}" height="{max(1,180/max(1,n)):.2f}" fill="{color}"/><text x="2" y="{py+8:.2f}" font-size="8">{escape(chart["labels"][i][:12])}</text>')
            else:
                segments = []
                for i,v in enumerate(s["values"]):
                    if v is None:
                        if segments:
                            parts.append(f'<polyline points="{" ".join(segments)}" fill="none" stroke="{color}"/>')
                            segments = []
                        continue
                    if chart["kind"] == "bar":
                        bw = max(1, min(25, 900/max(1,n)/max(1,len(series))))
                        parts.append(f'<rect x="{x(i)+(si-len(series)/2)*bw:.2f}" y="{min(y(0),y(v)):.2f}" width="{bw:.2f}" height="{max(0.5,abs(y(v)-y(0))):.2f}" fill="{color}"/>')
                    elif chart["kind"] == "dot":
                        parts.append(f'<circle cx="{point_x(i,s):.2f}" cy="{y(v):.2f}" r="3" fill="{color}"/>')
                    else:
                        segments.append(f"{point_x(i,s):.2f},{y(v):.2f}")
                        if n == 1:
                            parts.append(f'<circle cx="{x(i):.2f}" cy="{y(v):.2f}" r="3" fill="{color}"/>')
                if segments:
                    parts.append(f'<polyline points="{" ".join(segments)}" fill="none" stroke="{color}" stroke-width="2"/>')
        if chart["labels"] and chart["kind"] != "horizontal bar":
            parts.append(f'<text x="85" y="305" font-size="10">{escape(chart["labels"][0])}</text><text x="1065" y="305" text-anchor="end" font-size="10">{escape(chart["labels"][-1])}</text>')
        if numeric_x:
            parts.append(f'<text x="575" y="328" text-anchor="middle" font-size="10">{escape(chart.get("x_label", "Numeric x"))}</text>')
        parts.append('</g>')
    parts.append('</svg>')
    return "".join(parts)


def write_chart(path, charts):
    path = Path(path)
    svg = chart_svg(charts)
    if path.suffix.lower() == ".svg":
        path.write_text(svg, encoding="utf-8")
    elif path.suffix.lower() == ".png":
        from PySide6.QtCore import QByteArray, Qt
        from PySide6.QtGui import QImage, QPainter
        from PySide6.QtSvg import QSvgRenderer
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        image = QImage(renderer.defaultSize(), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.white)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        if not image.save(str(path)):
            raise OSError("Could not save PNG chart.")
    else:
        raise ValueError("Choose .svg or .png.")


def write_report(path, tab, charts, metrics, row_limit=1000, accounting_note=None):
    if type(row_limit) is not int or not 1 <= row_limit <= 1000:
        raise ValueError("Report preview rows must be an integer from 1 to 1000.")
    chart = chart_svg(charts) if charts else "<p>No numeric charts.</p>"
    content = ("<!doctype html><html><meta charset='utf-8'><title>Local PyPSA study report</title>"
        "<style>body{font:14px sans-serif;max-width:1200px;margin:30px auto;color:#192c35;background:#fffdf7}"
        "h1{color:#183e50}td,th{padding:5px;border:1px solid #a7aa9d}"
        "th{background:#acd0c2}tr:nth-child(even){background:#f2eee5}"
        "svg{max-width:100%;height:auto}@media print{body{background:white}}</style>"
        f"<h1>{escape(tab.title)}</h1><p>Frozen run: {escape(Path(tab.run_path).name)}</p>"
        f"<p>{escape(tab.description)}</p><h2>Criteria / provenance</h2><pre>{escape(json.dumps(tab.criteria, indent=2))}</pre>"
        f"<p>Listing: {escape(getattr(tab, 'listing', 'snapshot'))} / {escape(getattr(tab, 'table_form', 'wide'))}. Chart range (zero-based, inclusive; -1 = end): {escape(str(getattr(tab, 'chart_range', [0, -1])))}. Chart zoom does not trim the data table.</p>"
        f"<h2>Property metrics / units</h2><pre>{escape(json.dumps(getattr(tab, 'specs', []), indent=2))}</pre>"
        f"<h2>Run metrics</h2><pre>{escape(json.dumps(metrics, indent=2, allow_nan=False))}</pre>"
        f"<p>{escape(accounting_note or 'Weighted energy/emissions use generator snapshot weights and period years. Null emissions mean incomplete explicit factors. Objective is the saved formulation objective, not a reconstructed cost claim.')}</p>"
        "<p>Table: captured query listing, without the interactive table-search filter. Charts use the captured chart viewport; CSV exports the full filtered listing separately.</p>"
        "<h2>Charts (same bounded preview as the GUI)</h2>" + chart +
        f"<h2>Data preview: {min(len(tab.frame),row_limit)} of {len(tab.frame)} rows</h2>" + tab.frame.head(row_limit).to_html(index=False, escape=True) +
        "<p>Export queried CSV for the full table. Local linear study; not AC/security certification. No external scripts, fonts or network resources.</p></html>")
    Path(path).write_text(content, encoding="utf-8")


def annotate_formulation(directory, destination):
    directory = Path(directory)
    from .run_layout import formulation_directory
    directory = formulation_directory(directory)
    source = next((directory/name for name in ["model.lp", "model.mps"] if (directory/name).exists()), None)
    if source is None or not (directory/"symbols.csv").exists():
        raise ValueError("This run has no mathematical export/symbol map. Solve a new labelled run with LP or MPS enabled; existing artifacts are never regenerated or changed.")
    mapping = {}
    with (directory/"symbols.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            mapping[row["symbol"]] = row["block"] + "[" + row["coordinates"] + "]"
    token = re.compile(r"\b[xc]\d+\b")
    with source.open(encoding="utf-8") as handle, Path(destination).open("w", encoding="utf-8") as output:
        output.write("READABLE ANNOTATION OF ACTUAL EXPORTED " + source.name + "\nNot solver input syntax. Coefficients/signs/bounds follow that artifact; x/c labels expand via symbols.csv.\n\n")
        for line in handle:
            output.write(token.sub(lambda match: mapping.get(match[0], match[0]), line))
