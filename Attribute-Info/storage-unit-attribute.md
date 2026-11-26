# PyPSA StorageUnit Attribute Reference

A **StorageUnit** combines charging, discharging, and stored energy in one component. Its energy capacity is tied to nominal power: **energy capacity = `p_nom × max_hours`**. For example, 50 MW with `max_hours=4` gives 200 MWh.

Total attributes covered for **StorageUnit**: **52**.

## 1. Connection, power capacity, and operating limits

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `name` | String; required | No default | Unique identifier, for example `battery`. |
| `bus` | String; required | No default | Bus from which the unit charges and to which it discharges. |
| `control` | String | `"PQ"` | PQ, PV, or Slack control strategy for power-flow calculations. Not a priority rule for charging or dispatch in optimisation. |
| `type` | String | Unset | Unimplemented placeholder; does not select battery chemistry or efficiencies. |
| `p_nom` | Float | MW; `0` | Nominal power used for charging/discharging limits. Also sets energy capacity through `max_hours`. Ignored as a fixed input when capacity is extendable. |
| `p_nom_mod` | Float | MW; `0` | Module size for nominal-power investment; introduces integer variables. With a fixed `max_hours`, energy capacity grows in corresponding blocks too. |
| `p_nom_extendable` | Boolean | `False` | Allows optimisation of nominal power and therefore the associated energy capacity. |
| `p_nom_min` | Float | MW; `0` | Lower bound on nominal power when extendable, not a minimum operating output. |
| `p_nom_max` | Float | MW; `inf` | Upper bound on nominal power when extendable. |
| `p_nom_set` | Float | MW; unset | Fixes the nominal-power decision to this value in the extendable formulation. |
| `p_min_pu` | Static/series | Per unit; `-1` | Lower output limit relative to nominal power. Negative output means charging. For 50 MW capacity, `-0.5` permits charging up to 25 MW. |
| `p_max_pu` | Static/series | Per unit; `1` | Upper output limit relative to nominal power. Positive output means discharging. For 50 MW capacity, `0.8` permits discharge up to 40 MW. |
| `p_set` | Static/series | MW; unset | Net-power set point. In optimisation it fixes `p_dispatch - p_store`; positive means net discharge and negative means net charging. It does not separately fix each gross flow. |
| `q_set` | Static/series | MVAr; `0` | Reactive-power set point for power flow only. |
| `p_dispatch_set` | Static/series | MW; `NaN` | Fixes gross discharging power in optimisation. For example, `10` requires 10 MW discharge where specified. |
| `p_store_set` | Static/series | MW; `NaN` | Fixes gross charging power in optimisation. Charging here is entered as a positive magnitude, unlike a negative net `p_set`. |
| `sign` | Float | Dimensionless; `1` | Dispatch orientation in the bus balance. With the default, net positive dispatch supplies the bus. |
| `carrier` | String | Unset | Carrier or technology label used for grouping and relevant carrier-based accounting. |

## 2. Costs and asset life

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `spill_cost` | Static/series | Currency/MWh; `0` | Cost per MWh of spilled energy, for example unused reservoir inflow. The `spill` output itself is a power rate in MW and must be weighted by time for energy. |
| `marginal_cost` | Static/piecewise/series | Currency/MWh; `0` | Operating cost per MWh discharged, not per MWh charged or per MWh held in storage. Charging also incurs the cost of obtaining energy through the network. |
| `marginal_cost_quadratic` | Static/series | Schema: currency/MWh; `0` | Coefficient of quadratic discharging cost. Multiplies squared dispatch, so do not interpret it like a linear currency-per-MWh input; the CSV unit label is simplified. |
| `marginal_cost_storage` | Static/series | Currency/MWh/hour; `0` | Cost of holding 1 MWh in storage for one hour. Separate from discharging and spill costs. |
| `capital_cost` | Float | Currency/MW; `0` | Fixed-period cost per MW of nominal power. Account consistently for the bundled energy capacity implied by `max_hours` when preparing this cost. Used directly unless `overnight_cost` is given. |
| `overnight_cost` | Float | Currency/MW; `NaN` | Upfront investment cost per MW, annualised with `discount_rate` and `lifetime`. Takes precedence over `capital_cost`. |
| `discount_rate` | Float | Per unit; `NaN` | Annualisation rate for overnight cost. `0.07` is 7%; zero is supported. |
| `fom_cost` | Float | Currency/MW; `0` | Fixed-period O&M per MW of nominal power, added to the investment-cost component. |
| `active` | Boolean | `True` | Whether to include the StorageUnit in optimisation. |
| `build_year` | Integer | Year; `0` | Asset build year, used with lifetime for investment-period activity. |
| `lifetime` | Float | Years; `inf` | Operating lifetime and, where relevant, the annuity calculation lifetime. |

## 3. Stored energy, efficiency, and boundary conditions

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `state_of_charge_initial` | Float | MWh; `0` | Energy stored immediately before the first snapshot. It is an energy amount, not a percentage. Ignored under the applicable cyclic boundary condition. |
| `state_of_charge_initial_per_period` | Boolean | `False` | Resets initial state of charge to the specified initial value at each investment period when enabled. |
| `state_of_charge_set` | Static/series | MWh; `NaN` | Fixes state of charge at selected snapshots, for example an end-of-horizon target. Unset entries do not impose this fixed-energy condition. |
| `cyclic_state_of_charge` | Boolean | `False` | Makes initial and final energy equal over the optimised snapshot group instead of prescribing the initial amount. It does not require a full battery at either boundary. |
| `cyclic_state_of_charge_per_period` | Boolean | `False` | Applies cyclic state-of-charge constraints separately to each investment period. |
| `max_hours` | Float | Hours; `1` | Energy-to-power capacity ratio. For 50 MW and `4`, maximum energy is 200 MWh. This is a duration at nominal output, not the number of snapshots in the model. Actual delivered energy also depends on discharge efficiency. |
| `efficiency_store` | Static/series | Per unit; `1` | Charging efficiency. At `0.9`, taking 10 MWh from the bus adds 9 MWh to stored energy before other effects. |
| `efficiency_dispatch` | Static/series | Per unit; `1` | Discharging efficiency. At `0.9`, delivering 9 MWh to the bus removes 10 MWh from stored energy before other effects. |
| `standing_loss` | Static/series | Fraction per hour; `0` | Energy-inventory loss per hour. Over `h` elapsed hours, retained energy is multiplied by `(1 - standing_loss)^h`. |
| `inflow` | Static/series | MW; `0` | External inflow directly into the energy balance, such as river inflow in a reservoir. A 10 MW inflow over two hours contributes 20 MWh before spill and other effects. |

## 4. Outputs

| Attribute | Type | Unit / initial default | Description |
|---|---|---|---|
| `p` | Series | MW; `0` | Net power at the bus: `p_dispatch - p_store`. Positive is net supply, negative is net charging. |
| `p_dispatch` | Series | MW; `0` | Gross discharging power supplied to the bus, expressed as a non-negative magnitude. |
| `p_store` | Series | MW; `0` | Gross charging power withdrawn from the bus, expressed as a non-negative magnitude. |
| `q` | Series | MVAr; `0` | Reactive-power output, positive for net generation. |
| `state_of_charge` | Series | MWh; `NaN` | Stored energy calculated for each snapshot by optimisation. |
| `spill` | Series | MW; `0` | Spilled power rate, for example reservoir inflow allowed to bypass generation. Multiply by appropriate elapsed hours to obtain spilled MWh. |
| `p_nom_opt` | Static float | MW; `0` | Nominal power reported after optimisation; associated energy capacity is this value times `max_hours`. |
| `mu_upper` | Series | Currency/MWh; unset | Shadow price associated with the upper power bound described in the schema. Interpretation depends on the solved constraint and weighting. |
| `mu_lower` | Series | Currency/MWh; unset | Shadow price associated with the lower power bound described in the schema. |
| `mu_state_of_charge_set` | Series | Currency/MWh; unset | Shadow price of a fixed state-of-charge target. |
| `mu_energy_balance` | Series | Currency/MWh; unset | Shadow price of the storage energy-balance equation: marginal value of stored energy in the solved formulation. |
| `capital_cost_piecewise_opt` | Static float | Currency/MW; `0` | Optimised capital-cost value for the relevant piecewise formulation. |
| `marginal_cost_piecewise_opt` | Series | Currency/MWh; `0` | Optimised marginal-cost value for the relevant piecewise formulation. |

## Interpretation notes

- Ignoring standing loss, the balance is `energy now = energy before + hours × (efficiency_store × charging - discharge / efficiency_dispatch + inflow - spill)`.
- Storage elapsed hours come from storage snapshot weights. Timestamp spacing alone does not establish these weights.
- With constant efficiencies, charging and discharging efficiencies multiply to give round-trip efficiency before standing losses. Two efficiencies of `0.9` give `0.81`, or 81%.
- If power and energy capacities need independent investment decisions, use a [Store](store-attribute.md) with converters instead.
- Fixed-period costs require a consistent cost basis. Unsolved output defaults are placeholders. Dual values require an appropriate solved formulation; integer models do not automatically supply LP-style marginal values.
