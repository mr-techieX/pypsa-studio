# PyPSA Process Attribute Reference

A **Process** represents a controllable conversion involving multiple buses. Unlike a Link, it explicitly defines a signed transfer rate at every port relative to internal dispatch `p`. Negative rates consume energy; positive rates supply energy for positive internal dispatch.

For example, `rate0=-1`, `rate1=0.7`, and internal dispatch of 100 MW consume 100 MW at bus0 and supply 70 MW at bus1. Nominal capacity and costs refer to the internal dispatch basis, which need not equal the flow at bus0 when its rate differs from -1.

Total attributes covered for **Process**: **64 base attributes**. Additional ports can introduce more attributes.

## 1. Ports, rates, and nominal capacity

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `name` | String; required | No default | Unique process identifier. |
| `bus0` | String; required | No default | First connected bus. Its rate determines whether it is an input or output; the name alone does not force consumption. |
| `bus1` | String; required | No default | Second connected bus. Further buses can be supplied as `bus2`, `bus3`, etc. |
| `type` | String | Unset | Unimplemented placeholder; does not select conversion behaviour. |
| `carrier` | String | Empty | Process technology label, such as an electrolyser or boiler category. |
| `rate0` | Static/piecewise/series | Per unit of internal dispatch; `-1` | Signed energy transfer to bus0 per unit of `p`. At `-1`, 100 MW internal dispatch consumes 100 MW from bus0. Can vary with time or use the supported piecewise formulation. |
| `rate1` | Static/piecewise/series | Per unit of internal dispatch; `1` | Signed energy transfer to bus1 per unit of `p`. At `0.7`, 100 MW internal dispatch supplies 70 MW to bus1. Additional ports use `rate2`, `rate3`, etc. |
| `active` | Boolean | `True` | Whether to include the Process in applicable functionality. |
| `build_year` | Integer | Year; `0` | Build year used with lifetime for investment-period activity. |
| `lifetime` | Float | Years; `inf` | Operating lifetime, also used for annualisation where applicable. |
| `p_nom` | Float | MW of internal dispatch; `0` | Nominal internal-power capacity. Equals a port's flow magnitude only when that port's rate magnitude is 1. Ignored as fixed capacity when extendable. |
| `p_nom_mod` | Float | MW of internal dispatch; `0` | Module size for discrete capacity choices, for example 100 MW internal-dispatch blocks. |
| `p_nom_extendable` | Boolean | `False` | Allows optimisation of nominal internal-power capacity. |
| `p_nom_min` | Float | MW; `0` | Lower capacity bound when extendable. |
| `p_nom_max` | Float | MW; `inf` | Upper capacity bound when extendable. |
| `p_nom_set` | Float | MW; unset | Fixes nominal capacity within the extendable formulation. |
| `p_set` | Static/series | MW; unset | Fixed dispatch set point. The CSV describes this as a `p0` set point, but the installed fixed-operation optimisation constraint fixes the internal variable `Process-p`. It matches bus0 withdrawal only for `rate0=-1`. |
| `p_init` | Static numeric | MW of internal dispatch; unset | Internal dispatch before the first optimised snapshot, used for the initial ramp constraint. |
| `p_min_pu` | Static/series | Per unit of `p_nom`; `0` | Lower signed internal-dispatch bound. A negative value permits reverse internal operation under the configured port rates. |
| `p_max_pu` | Static/series | Per unit of `p_nom`; `1` | Upper signed internal-dispatch bound. At 100 MW nominal capacity, `0.8` caps internal dispatch at 80 MW. |

## 2. Costs and route information

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `capital_cost` | Float | Currency/MW of internal capacity; `0` | Fixed-period investment cost per MW of internal capacity. Any length factor must already be included. Used directly unless overnight cost is specified. |
| `overnight_cost` | Float | Currency/MW of internal capacity; `NaN` | Upfront investment cost, annualised with discount rate and lifetime. Overrides `capital_cost`. |
| `discount_rate` | Float | Per unit; `NaN` | Annualisation rate for overnight cost. Enter `0.07` for 7%; zero is supported. |
| `fom_cost` | Float | Currency/MW of internal capacity; `0` | Fixed-period O&M added to the investment-cost component. |
| `marginal_cost` | Static/piecewise/series | Currency/MWh of internal dispatch; `0` | Operating cost on internal throughput, not automatically on any particular port's output. Equals cost per MWh consumed at bus0 when `rate0=-1`. Input energy costs are represented by supplying the input buses. |
| `marginal_cost_quadratic` | Static/series | Schema: currency/MWh; `0` | Quadratic internal-dispatch cost coefficient. Multiplies squared dispatch and is not interchangeable with a linear per-MWh cost; the CSV unit label is simplified. |
| `stand_by_cost` | Static/series | Currency/hour; `0` | Cost incurred whenever commitment status is 1, including zero dispatch. |
| `length` | Float | km; `0` | Route-length information useful for preparing costs in transport-like processes. Does not automatically multiply capital cost. |
| `terrain_factor` | Float | Per unit; `1` | Terrain multiplier available for constructing length-based costs. |

## 3. Commitment, ramping, and maintenance

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `committable` | Boolean | `False` | Enables on/off commitment constraints and applicable start/stop and minimum-time settings. |
| `start_up_cost` | Static/series | Currency/event; `0` | Cost for changing from off to on. Applies only when committable. |
| `shut_down_cost` | Static/series | Currency/event; `0` | Cost for changing from on to off. Applies only when committable. |
| `min_up_time` | Integer | Snapshots; `0` | Minimum consecutive on-snapshots after starting. Does not use snapshot duration weights. |
| `min_down_time` | Integer | Snapshots; `0` | Minimum consecutive off-snapshots after stopping. Does not use snapshot duration weights. |
| `up_time_before` | Integer | Snapshots; `1` | Consecutive on-snapshots before the first optimised snapshot. Previously solved status replaces this history where applicable. Used with commitment. |
| `down_time_before` | Integer | Snapshots; `0` | Consecutive off-snapshots before the first optimised snapshot. Positive values take precedence over `up_time_before`; solved history replaces supplied history where applicable. |
| `ramp_limit_up` | Static/series | Per unit; `NaN` | Maximum internal-dispatch increase per adjacent snapshot relative to nominal capacity. Not automatically duration-scaled; ignored when unset. |
| `ramp_limit_down` | Static/series | Per unit; `NaN` | Maximum internal-dispatch decrease per adjacent snapshot relative to nominal capacity. Not automatically duration-scaled; ignored when unset. |
| `ramp_limit_start_up` | Float | Per unit; `NaN` | Maximum upward change on starting relative to nominal capacity. Applies only when committable; ignored when unset. |
| `ramp_limit_shut_down` | Float | Per unit; `NaN` | Maximum downward change on stopping relative to nominal capacity. Applies only when committable; ignored when unset. |
| `maintainable` | Boolean | `False` | Enables maintenance scheduling constraints. |
| `maintenance_duration` | Float | Hours; `0` | Required elapsed duration per event, spanning consecutive snapshots whose relevant weightings sum to at least this duration. Used when maintainable. |
| `maintenance_pu` | Float | Per unit; `1` | Fraction of capacity unavailable during maintenance. `1` is a full outage. |
| `maintenance_events` | Integer | Count; `1` | Required maintenance events per optimisation horizon when maintainable. |

## 4. Delivery delays

| Attribute | Type | Unit / default | Description |
|---|---|---|---|
| `delay0` | Integer | Generator snapshot-weight units; `0` | Delivery delay for bus0, measured using cumulative `network.snapshot_weightings.generators`. The first eligible snapshot at least this far later receives delivery. Matters when this port supplies energy. |
| `cyclic_delay0` | Boolean | `True` | Whether delayed deliveries at port 0 wrap from the end to the beginning of the optimisation period. If false, deliveries beyond the horizon are lost and there are no wrapped initial receipts. |
| `delay1` | Integer | Generator snapshot-weight units; `0` | Delivery delay for bus1, using the same weighted-time convention. Additional ports use `delay2`, `delay3`, etc. |
| `cyclic_delay1` | Boolean | `True` | Whether delayed deliveries at port 1 wrap cyclically. Additional ports use matching numbered attributes. |

## 5. Outputs

| Attribute | Type | Unit / initial default | Description |
|---|---|---|---|
| `p` | Series | MW; `0` | Internal dispatch on the Process's chosen capacity and cost basis. |
| `p0` | Series | MW; `0` | Withdrawal at bus0, positive for consumption. Without delay or piecewise complications, `p0 = -rate0 × p`. |
| `p1` | Series | MW; `0` | Withdrawal at bus1, positive for consumption and negative for supply. Without delay or piecewise complications, `p1 = -rate1 × p`. |
| `p_nom_opt` | Static float | MW of internal capacity; `0` | Nominal internal-power capacity reported after optimisation. |
| `status` | Series | Dimensionless; `1` | Commitment status when enabled. Binary 1 is on and 0 is off; relaxed formulations may give fractional values. |
| `start_up` | Series | Dimensionless; `1` | Start-up indicator when commitment is enabled. Initial values are placeholders. |
| `shut_down` | Series | Dimensionless; `1` | Shut-down indicator when commitment is enabled. |
| `maintenance` | Series | Dimensionless; `0` | Maintenance status, with 1 meaning in maintenance. |
| `maintenance_start` | Series | Dimensionless; `0` | Indicator that a maintenance event starts in this snapshot. |
| `mu_lower` | Series | Currency/MW; unset | Non-negative shadow price of the lower signed internal-dispatch bound. |
| `mu_upper` | Series | Currency/MW; unset | Non-negative shadow price of the upper signed internal-dispatch bound. |
| `mu_p_set` | Series | Currency/MWh; unset | Shadow price of the fixed dispatch constraint. |
| `mu_ramp_limit_up` | Series | Currency/MWh; unset | Shadow price of the upward ramp constraint. |
| `mu_ramp_limit_down` | Series | Currency/MWh; unset | Shadow price of the downward ramp constraint. |
| `capital_cost_piecewise_opt` | Static float | Currency/MW; `0` | Optimised capital-cost value in the relevant piecewise formulation. |
| `marginal_cost_piecewise_opt` | Series | Currency/MWh; `0` | Optimised marginal-cost value in the relevant piecewise formulation. |

## Interpretation notes

- For simple rates, injection to port `i` is `rate_i × p`, while the reported port withdrawal is its negative. A negative rate is an input for positive internal dispatch.
- Additional ports add matching bus, rate, output, and delay fields. No separate base CSV row is required for each new port.
- Rates describe the conversion relationship. Choose them and the internal capacity basis consistently; arbitrary rates do not automatically ensure physical energy conservation.
- A [Link](link-attribute.md) anchors capacity and costs to bus0 input; Process makes the internal reference explicit and gives all ports their own rates.
- Fixed-period costs require a consistent time basis. Defaults are not solved results; shadow prices depend on the solved formulation and weighting.
