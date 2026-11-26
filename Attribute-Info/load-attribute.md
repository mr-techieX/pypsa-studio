# PyPSA Load Attribute Reference

A **Load** represents specified demand at a bus. In ordinary optimisation it is a fixed requirement to be supplied, not a generator whose output the optimiser freely chooses.

Total attributes covered for **Load**: **10**.

## Inputs

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `name` | String; required | No default | Unique load identifier. Your notebook uses `electricity_demand`. |
| `bus` | String; required | No default | Bus from which demand is withdrawn. Your load connects to `electricity_bus`. |
| `carrier` | String | Unset | Label describing the demand carrier or category, useful for statistics and grouping. |
| `type` | String | Unset | Unimplemented placeholder; does not automatically configure a demand model. |
| `p_set` | Static/series | MW; `0` | Specified active-power consumption. Positive values mean demand. Your value of `50` requires 50 MW at each snapshot unless a time-varying profile overrides it. A profile such as 50, 80, and 60 represents changing demand across three snapshots. |
| `q_set` | Static/series | MVAr; `0` | Specified reactive-power consumption for applicable power-flow calculations. Positive values represent inductive demand. Not an additional active-energy requirement in ordinary linear dispatch. |
| `sign` | Float | Dimensionless; `-1` | Sign applied when the load enters the bus balance. With the default `-1`, a positive `p_set` withdraws power. Opposite to the usual Generator sign. |
| `active` | Boolean | `True` | Whether to include the load in optimisation. `False` excludes it without deleting its data row. |

## Outputs

| Attribute | Type | Unit / initial default | Description |
|---|---|---|---|
| `p` | Series | MW; `0` | Active-power demand represented at each snapshot; positive for net consumption. This is not a record of unserved demand. |
| `q` | Series | MVAr; `0` | Reactive-power consumption at each snapshot; positive for net load. |

## Interpretation notes

- Generator `p_set` specifies generation; Load `p_set` specifies consumption. Interpret an attribute in its component context.
- MW is a rate. A 50 MW load consumes 50 MWh over one hour, or 12.5 MWh over 15 minutes.
- If supply cannot meet fixed demand and no flexibility is modelled, optimisation can be infeasible. A Load does not automatically provide demand shedding.
- Results are time-dependent; initial output defaults do not demonstrate that a model has been solved.
