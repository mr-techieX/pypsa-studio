# Offline demo model library

Open **Overview → Load demo model…**, select a case, read its assumptions and
expected observations, then **Load selected model**. Normal pending-draft,
unsaved-project and pinned-tab prompts protect the previous project. Cancel
keeps it; merely selecting/loading a case does **not** start HiGHS. Save to your
own SQLite file before running. A new selection has a fresh project identity;
its runs are separate from runs of a previous selection, even of the same case.

All profiles are fixed functions/arrays, never random draws, downloaded weather
or live tariffs. All studies start 2026-01-01 with one-hour snapshot weights.
Costs are illustrative USD/MWh except the original `urban3` (INR/MWh); no currency
conversion is inferred. All are fixed-capacity, single-period, lossless linear
studies, with no reserve, N-1, AC voltage/reactive feasibility or certification
claim. Bus counts include heat buses where present.

| CLI id | Buses / hours | Use case and first checks |
|---|---|---|
| `congestion2` | 2 / 1 | City import congestion: 60 MW load, 40 MW corridor, remote/local offers 20/100. Remote 40 MW + peaker 20 MW; one-hour objective 2800. Query Bus prices and Line p0/p1. |
| `urban3` | 3 / 24 | Original urban solar/thermal dispatch lab: daylight PV, deterministic evening demand, three transfer paths. Compare Solar/Thermal/City peaker `p` and snapshot flows. Not an Odisha asset inventory. |
| `campus6` | 6 / 24 | Five electrical locations plus heat: rooftop PV, 12 MW/36 MWh battery, tariff blocks 30/70/150, heat pump COP 3. Query battery charge/discharge/energy and Link p0/p1; 9 MW heat requires 3 MW electrical input. |
| `wind10` | 10 / 24 | Coastal-to-inland wind export through a 30 MW bottleneck. Two 60 MW wind units and inland gas supply four demand areas. Inspect export saturation, unused available wind and local backup. |
| `pglib14` | 14 / 1 | Attributed public IEEE/PGLib DC adaptation: 20 branches, 259 MW load and linear offers. Cheapest feasible dispatch is bus-1 generation 259 MW; objective 2051.526309. Compare all branch flows with the independent nodal-matrix check. |
| `district14` | 14 / 24 | Twelve-bus electrical ring, LV bus, heat bus; 20 MVA transformer, daylight PV, COP-3 heat pump and 15 MW/45 MWh battery. Inspect transformer active-flow bounds and tariff-driven storage. |
| `regional20` | 20 / 24 | Meshed ring with four cross-ties, four industrial and sixteen residential demand areas, wind/PV, import/gas and 30 MW/90 MWh battery. Test larger spreadsheets, daily dispatch, layout persistence and source-isolated flows. |

## Suggested controlled experiments

Keep the baseline saved, change one input, then solve a new labelled run:

- **Congestion:** increase Import corridor `s_nom` from 40 to 60. Local generation
  can fall to zero and operating cost to 1200 for the hour. This is an active
  transfer limit in a DC study, not a claim of AC thermal security.
- **Campus:** lower Battery `p_nom` or set it to zero; compare tariff-period
  imports/objective. Both store/dispatch efficiencies are 0.9 (81% round-trip),
  with cyclic energy, three-hour duration and no degradation/comfort dynamics.
- **Wind:** raise Export bottleneck `s_nom`; compare wind generation/availability
  and Inland gas `p`. Curtailment here is available output minus actual dispatch,
  not a separately measured time series.
- **District:** change the import price profile or transformer rating; inspect
  both electrical and heat balances rather than summing unlike carrier demands.
- **Regional:** compare noon/evening generation and energy. Save a layout, edit
  a current-model object, then load an older run's flows: topology and values
  must still identify that run, not the edited model.

## Layouts, provenance and validation

The 6–20-bus cases ship deliberately spaced **non-geographic** schematic layouts.
Use **Network → Fit**, then zoom/pan for legible individual labels; the minimum
window has less diagram space in frozen-flow mode. Fit supports zoom down to
10%; very large/custom diagrams may still require panning. A historical view
without its own saved layout starts from the live layout captured in its own
`inputs.sqlite`, never today's edited coordinates. Save layout makes an explicit
per-run override without rewriting frozen inputs.

Factory notes/assumptions/provenance are retained in optional SQLite
`metadata.demo_info`, separate from electrical records and the core schema-v1
payload. They describe the **starting demo**, not a live certification of later
user edits. Older readers can ignore the key and older saves may discard it.

See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) for the pinned source,
CC BY 4.0 attribution and exact DC changes; [STAGE3E_VALIDATION.md](STAGE3E_VALIDATION.md)
for independent checks, measurement methodology and known limits. All runtime
data/help/icons are local; source/license links are provenance, not runtime
downloads. No new packages are required.
