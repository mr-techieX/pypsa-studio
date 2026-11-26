# H06–H10 — Calendar reports, result listings and chart navigation

Implemented in **RawBuild**, retaining the v1.0.0 copy and historical run files.
This is a development increment, not a v1.1.0 package. All targets, including the
new H10, require user confirmation before building v1.1.0.

## H06: reports chosen before a run

In Runs, **Reports after run** offers Native, Hourly, Daily, Weekly, Monthly and
Yearly checkboxes. These are reporting resolutions, not optimization settings.
They work with the original project-axis single solve and configured sequential
solves. Invalid finer-than-native or nonchronological requests fail before worker
creation. A stepped run generates reports once from its assembled results, not
once per child step.

Saved outputs under the new run:

```text
reports/
  index.html
  manifest.json
  daily/
    Generator__p__auto.csv
    Generator__p__energy.csv
    StorageUnit__state_of_charge__auto.csv
  monthly/...
```

Only requested/supported combinations are generated. The manifest identifies
units, metrics, criteria, row counts and any skipped/unavailable quantities with
reasons. Native means the original `tables/` files, not duplicate copies. The
offline HTML index links full CSVs and lists exclusions; it does not require a
browser service or network access. Missing values are not replaced with zero.

## H07–H08: query and listing controls

The Results query pane now has four controls:

1. **Resolution:** native/hourly/daily/weekly/monthly/yearly. Choices finer than the
   run's native intervals are unavailable. Existing dated runs can be queried at
   supported resolutions without solving again or having preselected reports.
2. **Metric:** Auto, Mean, Energy, End, Min, Max, Total, Operating hours, Fraction.
   A metric must be valid for every selected property. Auto uses the verified
   rule for each property independently; invalid requests preserve the prior tab
   and show an actionable message. Select static properties separately when
   requesting calendar aggregation.
3. **Object grouping:** object/carrier/component. Carrier grouping requires an
   explicit frozen carrier. Grouping is allowed for additive power, energy states
   and event counts, not prices/status fractions/unrelated units.
4. **Week start:** Monday or Sunday for interactive weekly buckets. Pre-run
   reports use Monday weeks.

Selections are drafts until **Query**. An existing displayed query is never
relabelled because a selector changed. Captured criteria include versioned
aggregation options, and output specs carry resulting units/metric/weighting.
For example, a selected native `p [MW]` queried using Energy produces **MWh**,
not summed MW. The Data pane explicitly shows the output quantities.

The Data pane provides snapshot-first, object-first and property-first listings,
wide/long forms, text filtering, and ascending/descending sorting by clicking a
column heading. Property-first is a long listing regardless of the wide setting.
Presentation never sums facts. Static values appear once per object rather than
being multiplied across temporal rows; they also use categorical charts. Long
listings include property/unit/kind columns. Grouping is a query operation and is
separate from listing order.

The table preview remains bounded to 1000 rows. **Export queried CSV** writes
the full filtered listing, plus a `.csv.metadata.json` sidecar recording source,
criteria, units, listing, filter and sort. Chart zoom does not trim the CSV.
Exports cannot target the project database or its frozen runs.

Saved analyses retain the query, styles, listing/form/sort and chart viewport.
Legacy cards without these fields keep their original Native/default behavior.
Compatible-run comparisons accept matching calendar criteria/coverage and
preserve resulting units. Existing weighted energy/duration analytics deliberately
require Native queries so already-aggregated energy is not integrated twice.

## Quantity and time semantics

`energy_gui/temporal.py` is the shared read-only engine for queries and reports.
Its explicit version-1 rules are:

| Quantity | Auto | Other supported choices |
| --- | --- | --- |
| Active power MW, including branch pN and storage charge/discharge/spill | physical-duration-weighted mean MW | integrated MWh, min/max/end MW |
| Store/StorageUnit energy state | last selected endpoint MWh | min/max/duration-weighted endpoint-sample mean |
| Commitment status | duration-weighted fraction | operating hours, end/min/max |
| Startup/shutdown decision | sum of native decisions, labelled count | total only |
| Verified intensive inputs/prices/voltage values | duration-weighted mean in original units | min/max/end |
| Static or unknown property semantics | Native only | no guessed aggregation |

No general “sum everything” operation is offered. In particular, stored energy
is not integrated or summed over time, and a mean price is **not** advertised as
a volume-weighted effective price. Fractional commitment decisions retain their
native relaxation interpretation.

Calendar aggregation initially requires a contiguous single-period chronological
axis with objective/stores/generators weights equal to physical elapsed hours.
Representative/discounted/custom-accounting weights and multi-investment periods
continue to use Native/explicit existing weighted analytics. There are no
investment-year multipliers or implicit unit conversions in calendar summaries.
Declared non-MW object/bus units are rejected for MW-to-MWh integration.

Intervals use `[start,end)` and the existing timezone-naive convention. Months/
years have calendar lengths and leap days; weeks have the chosen anchor. Power
is assumed constant over its native interval, so an interval crossing a calendar
boundary contributes its overlap hours to each bucket. Finer disaggregation is
not allowed. States/events crossing a bucket boundary are rejected instead of
interpolated or split; pre-run reports record such exclusions.

Every calendar row includes `snapshot` (bucket start), `bucket_end`,
`coverage_hours`, `bucket_hours`, and `partial`. Selected dates are still inclusive
snapshot labels, selecting whole original intervals. First/last buckets can be
partial. Means divide by observed coverage, not a fabricated complete day/month.
Object totals are formed synchronously **before** temporal extrema/statistics.

## H10: chart timeline navigator

In Charts, the timeline covers the full executed query:

- Drag the **left or right handle** to shrink/expand the visible interval.
- Drag the **selected band** to pan without changing the interval's width.
- Use ‹ / › to move half a window, or **Full range** to reset.
- Handles support keyboard focus and arrow-key adjustment.
- Endpoint labels and point positions identify the selected range.

Only charts change. The captured query, table, CSV, model horizon and run files
stay unchanged. Pinned tabs have independent ranges; saved analyses restore them.
Static-only queries do not show a time navigator.

Charts are limited to six objects and 1000 plotted points. For larger visible
ranges the preview samples evenly across the **whole** chosen interval rather
than showing only its first 1000 snapshots. It is not a min/max envelope and can
miss short peaks: zoom for full local detail or export the uncapped table.
Hidden missing regions remain gaps. The default chart labels are ordered
snapshots/buckets, not a new continuous-time interpolation. Existing numeric-x
duration charts are unchanged.

Chart SVG/PNG and HTML exports use the captured viewport. HTML identifies its
zero-based range, units and listing; its table is the captured listing without
the interactive search filter. CSV retains the complete filtered listing.
At the minimum window size, chart cards can be scrolled to see their full axes.

## H09: verification and measured limits

Run from RawBuild with the existing environment:

```powershell
& '..\..\EnEx\Scripts\python.exe' tools/validate_temporal.py
```

Evidence lives in `docs/temporal-validation/`: full regression, Light/Dark
interaction matrices, native Windows horizon/navigator tests, Light/Dark/System
real solve/renders, compilation, benchmark, protected-file fingerprints and final
summary. No new packages or core SQLite migration are needed.

The tests retain the earlier horizon/storage/cancellation coverage and add
independent calendar/energy/state/status/price/partial-bucket/grouping checks,
pre-run report/query agreement, single/sequential actual solves, saved criteria,
sorting/CSV metadata, real drags of both handles and selected band, keyboard
adjustment, pinned state, restore and long timelines beyond snapshot 1000.

The benchmark compares a bounded 48-hour constant-demand full versus stepped
solve and an 8760-hour, two-object synthetic query. It checks numerical agreement,
records timings and isolated-process peak memory, and verifies a chart range
near the end of the year. It is not a realistic-grid performance certification
or a guarantee that sequential solves are faster. Upstream pandas deprecations
and the known Qt shutdown GC warning remain visible.

Final integrated verification: **428 regression tests passed in 798.400 s**;
Light/Dark UI matrices passed **56 each**; native Windows horizon/navigator checks
passed **9**. All solve/render, benchmark and compile jobs passed. Fingerprints
found no changes to the 348 protected v1.0.0 files or 527 pre-existing RawBuild
project/run files. The measured annual query had 17,520 native rows, a 101-point
far-end viewport and 730 daily energy rows; CSV/query energy totals reconciled.
See `benchmark.json` for hardware, timing and peak-memory scope. User acceptance,
Linux/WSLg and other display-scaling/accessibility configurations remain separate.
