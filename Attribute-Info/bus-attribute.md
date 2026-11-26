# PyPSA Bus Attribute Reference

A **Bus** is a connection point where supply, demand, storage, and flows must balance. It can represent electricity, heat, gas, or another carrier; it is not necessarily a physical electrical substation.

Total attributes covered for **Bus**: **19**.

## Inputs

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `name` | String; required | No default | Unique bus identifier, such as `electricity_bus`. Other components refer to this exact name to establish their connection. |
| `v_nom` | Float | kV; `1` | Nominal electrical voltage, used to convert physical impedances to per-unit values. For a 220 kV bus, use `220`, not `220000`. This is not the solved voltage magnitude. |
| `type` | String | Unset | Unimplemented placeholder; does not configure bus behaviour. |
| `x` | Float | Coordinate; `0` | Longitude in the default spatial reference system. The coordinate system is identified by `network.srid`; this is not electrical reactance. |
| `y` | Float | Coordinate; `0` | Latitude in the default spatial reference system. Used with `x` for geographic positioning. |
| `carrier` | String | `"AC"` | Carrier represented by the bus, such as `"AC"`, `"DC"`, `"heat"`, or `"gas"`. Conversions between carriers are typically represented by Links or Processes connecting different buses. |
| `unit` | String | `None` | Descriptive label if the implicit MW unit is inappropriate, for example `"t/h"`. Does not convert values or change PyPSA calculations; consistent units remain the modeller's responsibility. |
| `location` | String | Unset | Location label useful for aggregation in statistics, for example grouping electricity and heat buses belonging to the same city. Does not change optimisation constraints. |
| `v_mag_pu_set` | Static/series | Per unit; `1` | Voltage magnitude target for applicable power-flow controls. On a 220 kV bus, `1.02` corresponds to 224.4 kV. A target is not necessarily enforced at a PQ bus. |
| `v_mag_pu_min` | Float | Per unit; `0` | Desired lower voltage limit. The installed schema marks this as a placeholder unused by functions; setting it does not enforce a voltage constraint. |
| `v_mag_pu_max` | Float | Per unit; `inf` | Desired upper voltage limit. Also an unused placeholder in this schema, not an automatically enforced bound. |

## Outputs

| Attribute | Type | Unit / initial default | Description |
|---|---|---|---|
| `control` | Static string | `"PQ"` | Power-flow control mode inherited from attached generators: PQ, PV, or Slack. Do not set this output directly to choose generator control. |
| `generator` | Static string | Unset | Name of the slack generator associated with a slack bus. |
| `sub_network` | Static string | Unset | Connected passive-network identifier assigned by topology determination. Do not assign it manually. |
| `p` | Series | MW; `0` | Net active-power injection at the bus, positive for net generation. It is not the sum of all gross generation regardless of local demand. |
| `q` | Series | MVAr; `0` | Net reactive-power injection, positive for net generation. Relevant to reactive-power calculations, not ordinary linear economic dispatch. |
| `v_mag_pu` | Series | Per unit; `1` | Calculated voltage magnitude relative to `v_nom`. Multiply by nominal kV to obtain voltage in kV. |
| `v_ang` | Series | Radians; `0` | Calculated voltage angle relative to the network reference. Do not confuse radians with the degree-based angle inputs of Lines and Transformers. |
| `marginal_price` | Series | Currency/MWh; `0` | Shadow price of the bus energy-balance constraint: the local marginal value of energy in the solved formulation. Weights, degeneracy, and integer decisions affect interpretation; an unsolved default is not an economic result. |

## Interpretation notes

- Your notebook's `electricity_bus` is where the generator's supply and the load's demand meet.
- A snapshot is one modelled time step. Snapshot labels alone do not determine elapsed hours.
- `inf` means no finite limit, but unused placeholder bounds remain unused regardless of their value.
- Output defaults are placeholders until the relevant calculation runs.
