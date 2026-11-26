# Atlas interface: scope and verification

## Reference and scope

Reference: workspace `sample-ui-template/atlas-light-dark.png`.
This revision implements its **color roles** across the existing Qt Quick
workflows, not its invented geography, sidebar structure or integrated map
dashboard. No geographical map, regional boundaries, additional comparison
panel, electrical model changes or new solver functionality are introduced.
Originally developed in the isolated v1.0.0 copy, then ported to RawBuild by user
authorization before H01–H05. The historical v1.0.0 copy remains unchanged.

The mockup is a generated image, not a pixel-perfect design specification.
The values below deliberately use readable foreground/background pairs rather
than reproducing anti-aliased screenshot pixels.

## Color contract

| Role | Light | Dark |
| --- | --- | --- |
| Branded header | `#183e50` | `#0b1e2b` |
| Header text | `#f7f5eb` | `#f7f5eb` |
| Workspace | `#f1ebdd` | `#0e202e` |
| Panels | `#fbf8f0` | `#172d3c` |
| Inputs | `#fffdf7` | `#102532` |
| Body text | `#192c35` | `#f3f4ed` |
| Selected rows / tabs / table headers | `#acd0c2` | `#665222` |
| Checked controls / primary actions | `#245d5a` | `#e6b552` |
| Text on primary actions | white | `#152c38` |
| Network focus | `#80601c` | `#e6b552` |
| Selected-network callout | `#edbf50` | `#edbf50` |
| Warning | `#8d461c` | `#ffb087` |
| Critical | `#a33f3b` | `#f09188` |
| Success | `#28684f` | `#87cfb0` |
| Default chart series | teal | gold |

`energy_gui/qml/Theme.qml` is the on-screen token source. The header dropdown
and quick-save action use dedicated header colors; their popup/tooltip content
uses the normal page palette. This avoids white-on-paper or dark-on-navy labels.
All application checkboxes use `AtlasCheckBox.qml`, including Results, which
previously used its own indicator.

### Networks and charts

- Network icons/borders use explicit carrier labels for wind, solar, hydro,
  biomass and thermal technologies, plus storage component kinds. Unknown
  carriers remain neutral. Names are not used to infer technology.
- Colors are presentation-only; stored Carrier colors, electrical parameters,
  projects and frozen result data are not rewritten.
- Selecting an object highlights its connections and focus ring in gold.
  Selected flow callouts use gold with dark ink. With congestion enabled,
  orange/red alerts take precedence over selection. Existing line widths,
  labels and electrical meaning are retained.
- Chart slots keep their existing series order. Live theme changes recolor
  these slots without replacing queries, series, values or selected chart
  types. Slots are not a new carrier-aware chart classification system.
- Exported SVG/PNG and HTML use the **print/light** Atlas palette regardless of
  current desktop mode. This is intentional; existing saved exports are not
  rewritten. Print CSS retains a white page background.

## Automated verification

From this application's directory, using the existing workspace interpreter:

```powershell
& '..\..\EnEx\Scripts\python.exe' -m unittest discover -s tests
```

The original v1.0.0 `tools/validate_atlas.py` runner wrote evidence to that copy's
`docs/atlas-validation/`. It ran the following matrix. For the RawBuild port and
new horizon work use `docs/horizon-validation/` and `HORIZON_EXECUTION.md`; historical
screenshots/results are not copied and represented as a fresh RawBuild test run.

1. Full discovered unit/integration regression suite.
2. The real QML-control, network-navigation and Atlas suites, starting in Light.
3. The same UI suite starting in Dark.
4. Offscreen smoke/real-demo-solve workflows in both themes.
5. On Windows, the same smoke/real-demo-solve workflows on Qt's native
   `windows` platform, not just the offscreen plugin.

The smoke workflow captures all seven pages, the spreadsheet, queried data and
charts, frozen network flows and selected-flow details, minimum-size views,
reference help, ribbon menus, demo library, all five Study Tools sections and
all four extended-tool sections.

New Atlas tests additionally assert:

- Reviewed header, tab, checkbox and chart-role values, including rendered
  header and chart-series pixels.
- Text contrast of at least 4.5:1 for the tested text pairs and at least 3:1
  for tested network technology/focus colors against panels.
- Pointer/keyboard semantics through existing UI tests and checkbox keyboard
  toggling through the Atlas tests.
- Light/Dark/System switching preserves draft settings, project input values,
  frozen network state, layout, active object and executed query frame.
- Selected connections do not suppress warning/critical colors.
- SVG XML validity, PNG rendering, print palette and escaped HTML content.

Native automated smoke launches are **not** a human usability certification:
OS-managed title bars/file dialogs, other display scaling settings, Linux/WSLg,
screen readers and every possible project dataset remain outside this run.
No automated pixel-diff against the mockup's unrelated map layout is claimed.

## Results

See `atlas-validation/summary.json` for the recorded run, per-job exit codes,
test counts, screenshot counts and read-only RawBuild hash comparison.
