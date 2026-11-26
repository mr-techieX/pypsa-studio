# PyPSA Network Attribute Reference

A **Network** is the container for the model: component data, time steps, weights, topology, and calculated results. It is not an individual asset like a Generator or Line.

Total entries covered for **Network**: **16**, including two methods. This is not an exhaustive list of Network properties and methods.

## 1. Identity, time, and spatial metadata

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `name` | String input | Unset | Descriptive network name. Distinct from the Python variable name: the variable `network` can refer to a Network with any descriptive name. |
| `snapshots` | pandas Index | Time-step labels; `["now"]` | Index defining the modelled operating time steps. Every time-dependent component table uses this axis. Labels can be timestamps, but their spacing alone does not establish all duration weights. The default `"now"` is a placeholder label, not the current wall-clock time. |
| `snapshot_weightings` | pandas DataFrame | Typically hours; `1` | Separate weights for each snapshot. `objective` weights operating-cost contributions; `stores` supplies elapsed time for storage balances and standing losses; `generators` weights relevant energy/global-constraint accounting. For a straightforward 15-minute chronological model, all three are commonly `0.25`; advanced representative-time models can require different values. |
| `investment_periods` | pandas Index | Year identifiers; empty | Ordered investment periods for multi-investment modelling, such as 2025, 2030, and 2035. These are distinct from the operating snapshots within each period. |
| `investment_period_weightings` | pandas DataFrame | Formulation-dependent; `1` | Period-level weights. `objective` weights the period's objective contribution, including any chosen social-discount treatment. `years` represents years associated with the period for relevant accounting constraints. Different roles mean these columns need not have equal values. |
| `now` | Snapshot label | `"now"` | Current/default snapshot used by applicable methods when no explicit snapshot is supplied. It is not a live clock or an automatically advancing simulation cursor. |
| `srid` | Integer | Spatial identifier; `4326` | Spatial reference identifier for bus `x` and `y`. Default 4326 corresponds to geographic longitude and latitude. Setting metadata does not itself transform existing coordinates. |
| `crs` | CRS-like | Defaults from spatial reference | Coordinate reference system for Shape geometry. Use consistent spatial metadata when combining geographic data. |

## 2. Component data access

These entries describe data containers. Although the CSV labels them outputs, they hold user inputs as well as calculated values.

| Attribute | Type | Default | Description |
|---|---|---|---|
| `buses` | pandas DataFrame | Empty if no buses | Static bus data: rows are bus names and columns are attributes. Under the default API, refers to `network.components["Bus"].static`. |
| `buses_t` | Mapping of DataFrames | Empty data initially | Time-dependent bus data. Keys are attributes such as `v_ang` or `marginal_price`; each table has snapshots as rows and buses as columns. Corresponds to the Bus component's `.dynamic` store. |
| `lines` | pandas DataFrame | Empty if no lines | Static Line inputs and derived attributes, with line names as the index. |
| `lines_t` | Mapping of DataFrames | Empty data initially | Time-dependent Line data, including calculated flows such as `p0`. |
| `components` | ComponentsStore | Component containers | Current PyPSA 1.4.0 interface for all component types. For example, `network.components["Generator"].static` is the generator table, and `.dynamic` contains time-dependent attribute tables. The CSV's description as a single DataFrame is outdated. |
| `components_t` | Legacy schema entry | No current generic accessor | Older CSV description for generic time-dependent component access. In the current implementation use `network.components[component_name].dynamic`, or a specific accessor such as `network.generators_t`; do not assume `network.components_t` is available. |

## 3. Methods listed in the CSV

| Schema entry | Kind / return | Description |
|---|---|---|
| `branches()` | Method; pandas DataFrame | Returns a merged copy of branch tables. The installed implementation includes Lines, Transformers, Links, and Processes; the CSV's list predates Process. Editing the returned copy does not update the original component tables. |
| `graph()` | Method; NetworkX graph | Builds a graph of network connectivity, with buses as nodes and selected branches as edges. This describes the energy network, not a graph of Python source code. |

### Simplified method call patterns

| Call pattern | Arguments | Return and mutation |
|---|---|---|
| `network.set_snapshots(snapshots, default_snapshot_weightings=1.0, weightings_from_timedelta=False)` | Required: an index-like collection of time-step labels. Optional: default numeric weight; whether to derive weights from datetime differences. Use explicit weights when the modelling interpretation requires them. | Returns `None`; changes the Network's snapshot index and reindexes time-dependent data. |
| `network.branches()` | No arguments. | Returns a combined pandas DataFrame copy; does not change the Network. |
| `network.graph(branch_components=None, weight=None, inf_weight=False, include_inactive=True)` | Optional: collection of branch component names; edge-weight attribute name; handling of infinite weights; whether to include inactive assets. | Returns a NetworkX-compatible graph; does not change the Network's model data. |

## Interpretation notes

- **Power and energy:** 50 MW sustained for 0.25 hours is 12.5 MWh. A snapshot row alone does not tell you that duration.
- **Static is not constant dispatch:** a generator can have one static 100 MW capacity and different dispatch at every snapshot.
- Time-dependent inputs and calculated outputs share the same data-access structure. An existing result field does not prove optimisation has run.
- Python methods such as `branches()` need parentheses; data properties such as `buses` do not.
- The installed CSV is not an exhaustive API contract. Accessor clarifications above were checked in the installed Network/component implementation.
