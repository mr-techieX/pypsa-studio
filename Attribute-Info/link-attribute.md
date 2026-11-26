# PyPSA Link Attribute Reference

A **Link** represents a controllable transfer or conversion between buses, such as HVDC transmission, an electrolyser, or a heat pump. Unlike a passive Line, its flow is not determined by an electrical impedance law. Nominal capacity and dispatch costs refer to the input at `bus0`.

Total attributes covered for **Link**: **61 base attributes**. Additional ports can introduce more attributes.

## 1. Connections, conversion, and capacity

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `name` | String; required | No default | Unique identifier, for example `electrolyser`. |
| `bus0` | String; required | No default | Origin/input bus. Positive Link dispatch withdraws energy from this bus. Its units define the capacity and operating-cost reference. |
| `bus1` | String; required | No default | First destination/output bus. Additional destinations `bus2`, `bus3`, etc. can be added as needed. |
| `type` | String | Unset | Unimplemented placeholder; does not configure a technology. |
| `carrier` | String | Empty | Technology label such as `electrolyser`, `gas_boiler`, or `HVDC`. It does not create fuel prices or efficiencies automatically. |
| `efficiency` | Static/piecewise/series | Per unit; `1` | Output at bus1 per unit of bus0 input. With 100 MW input and `0.7`, output is 70 MW. For a heat pump it can represent a COP above 1 because ambient heat is implicit. Additional outputs use `efficiency2`, `efficiency3`, etc. |
| `active` | Boolean | `True` | Whether to include the Link in the applicable functionality. |
| `build_year` | Integer | Year; `0` | Build year used with lifetime for activity across investment periods. |
| `lifetime` | Float | Years; `inf` | Asset lifetime, also used in annualisation where applicable. |
| `p_nom` | Float | MW at bus0; `0` | Nominal input/transfer capacity. An electrolyser with `p_nom=100` and efficiency 0.7 has 100 MW electrical input capacity and 70 MW hydrogen output at full input. Ignored as fixed capacity when extendable. |
| `p_nom_mod` | Float | MW at bus0; `0` | Investment module size, for example 100 MW converter blocks. Supports discrete module-based capacity choices. |
| `p_nom_extendable` | Boolean | `False` | Allows optimisation of nominal input capacity. |
| `p_nom_min` | Float | MW at bus0; `0` | Lower bound on extendable capacity, not a minimum operating input. |
| `p_nom_max` | Float | MW at bus0; `inf` | Upper bound on extendable capacity. |
| `p_nom_set` | Float | MW at bus0; unset | Fixes nominal capacity within the extendable formulation. |
| `p_set` | Static/series | MW at bus0; unset | Fixed Link dispatch set point for optimisation and power flow, referenced to bus0. |
| `p_init` | Static numeric | MW at bus0; unset | Dispatch immediately before the first optimised snapshot, used to constrain the initial ramp. |
| `p_min_pu` | Static/series | Per unit of `p_nom`; `0` | Lower signed dispatch limit. Default zero disallows reverse dispatch. Negative values permit reverse flow under the same Link equations; for a lossless bidirectional connection, `-1` is a common lower bound. |
| `p_max_pu` | Static/series | Per unit of `p_nom`; `1` | Upper signed dispatch limit. For 100 MW capacity, `0.8` caps forward input at 80 MW. Can be time-varying or negative for specialised configurations. |

## 2. Costs and route information

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `capital_cost` | Float | Currency/MW at bus0; `0` | Fixed-period investment cost per MW of input capacity. Include any length factor in the supplied cost. Used directly unless overnight cost is specified. |
| `overnight_cost` | Float | Currency/MW at bus0; `NaN` | Upfront investment cost per MW of input capacity, annualised with discount rate and lifetime. Overrides `capital_cost`. |
| `discount_rate` | Float | Per unit; `NaN` | Rate used to annualise overnight cost. `0.07` means 7%; zero is supported. |
| `fom_cost` | Float | Currency/MW at bus0; `0` | Fixed-period O&M per MW of input capacity, added to the investment-cost component. |
| `marginal_cost` | Static/piecewise/series | Currency/MWh at bus0; `0` | Operating cost per MWh withdrawn from bus0, not per MWh delivered at bus1. Usually represents converter variable O&M; energy input costs are already accounted for by supplying the input bus. |
| `marginal_cost_quadratic` | Static/series | Schema: currency/MWh; `0` | Coefficient of quadratic input-dispatch cost. Multiplies squared dispatch, so it is not interchangeable with the linear marginal-cost input despite the CSV's simplified unit label. |
| `stand_by_cost` | Static/series | Currency/hour; `0` | Cost incurred whenever commitment status is 1, including at zero dispatch. Separate from the energy-throughput cost. |
| `length` | Float | km; `0` | Route length, useful for preparing HVDC investment costs. Does not automatically multiply `capital_cost`. |
| `terrain_factor` | Float | Per unit; `1` | Terrain multiplier useful when constructing length-based costs. Supply the resulting total per-MW cost consistently. |

## 3. Commitment, maintenance, and ramping

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `committable` | Boolean | `False` | Enables commitment constraints, including on/off decisions and applicable start/stop and minimum-time settings. |
| `maintainable` | Boolean | `False` | Enables maintenance scheduling constraints. |
| `maintenance_duration` | Float | Hours; `0` | Required elapsed time per maintenance event. Each event spans consecutive snapshots whose relevant weightings sum to at least this duration. Used only when maintainable. |
| `maintenance_pu` | Float | Per unit; `1` | Fraction of capacity unavailable during maintenance. `1` means fully unavailable; `0.3` means 30% unavailable. Used only when maintainable. |
| `maintenance_events` | Integer | Count; `1` | Required number of maintenance events over one optimisation horizon when maintenance is enabled. |
| `start_up_cost` | Static/series | Currency/event; `0` | Cost of changing from off to on. Used only when committable. |
| `shut_down_cost` | Static/series | Currency/event; `0` | Cost of changing from on to off. Used only when committable. |
| `min_up_time` | Integer | Snapshots; `0` | Minimum consecutive on-snapshots after starting. Counts snapshots, not weighted hours; applies only when committable. |
| `min_down_time` | Integer | Snapshots; `0` | Minimum consecutive off-snapshots after stopping. Counts snapshots, not weighted hours; applies only when committable. |
| `up_time_before` | Integer | Snapshots; `1` | Consecutive on-snapshots before the first optimised snapshot. Determines remaining minimum-up-time obligations. Previously optimised status replaces it where applicable. |
| `down_time_before` | Integer | Snapshots; `0` | Consecutive off-snapshots before the first optimised snapshot. Positive values take precedence over `up_time_before`; previously solved status replaces supplied history where applicable. |
| `ramp_limit_up` | Static/series | Per unit; `NaN` | Maximum dispatch increase between adjacent snapshots relative to `p_nom`. For 100 MW capacity, `0.2` permits a 20 MW increase. Not automatically duration-scaled; ignored when unset. |
| `ramp_limit_down` | Static/series | Per unit; `NaN` | Maximum dispatch decrease between adjacent snapshots relative to `p_nom`. Not automatically duration-scaled; ignored when unset. |
| `ramp_limit_start_up` | Float | Per unit; `NaN` | Maximum upward dispatch change on starting, relative to nominal capacity. Applies only when committable; ignored when unset. |
| `ramp_limit_shut_down` | Float | Per unit; `NaN` | Maximum downward dispatch change on stopping, relative to nominal capacity. Restricts output immediately before shutdown. Applies only when committable; ignored when unset. |

## 4. Delivery delay

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `delay` | Integer | Generator snapshot-weight units; `0` | Delay in delivery to bus1, measured using `network.snapshot_weightings.generators`, not simply a fixed count of snapshots. Delivery occurs at the first snapshot whose cumulative weighting start is at least the requested delay later. Additional ports use `delay2`, `delay3`, etc. |
| `cyclic_delay` | Boolean | `True` | Whether delayed delivery wraps from the end to the start of the optimisation period. With `False`, tail deliveries beyond the horizon are lost and initial snapshots receive no wrapped delivery. Additional ports use matching numbered attributes. |

## 5. Outputs

| Attribute | Type | Unit / initial default | Description |
|---|---|---|---|
| `p` | Series | MW; `0` | Internal dispatch, positive when withdrawing from bus0. |
| `p0` | Series | MW; `0` | Power withdrawn from bus0. Positive means consumption at that port. |
| `p1` | Series | MW; `0` | Power withdrawn from bus1. Negative means delivery to bus1. Without delay or piecewise complications, `p1 = -efficiency × p0`. |
| `p_nom_opt` | Static float | MW at bus0; `0` | Nominal input capacity reported after optimisation. |
| `status` | Series | Dimensionless; `1` | On/off status for committable Links: 1 is on, 0 is off in binary commitment. Relaxed formulations may have fractional values. |
| `start_up` | Series | Dimensionless; `1` | Start-up indicator for the snapshot when commitment is enabled. Initial schema values are placeholders. |
| `shut_down` | Series | Dimensionless; `1` | Shut-down indicator for the snapshot when commitment is enabled. |
| `maintenance` | Series | Dimensionless; `0` | Maintenance status: 1 means in maintenance. Returned for maintainable Links. |
| `maintenance_start` | Series | Dimensionless; `0` | Indicator that a maintenance event begins in this snapshot. |
| `mu_lower` | Series | Currency/MW; unset | Non-negative shadow price of the lower signed-dispatch bound, not simply the lower investment bound. |
| `mu_upper` | Series | Currency/MW; unset | Non-negative shadow price of the upper signed-dispatch bound. |
| `mu_p_set` | Series | Currency/MWh; unset | Shadow price of the fixed dispatch set point. |
| `mu_ramp_limit_up` | Series | Currency/MWh; unset | Shadow price of the upward ramp constraint. |
| `mu_ramp_limit_down` | Series | Currency/MWh; unset | Shadow price of the downward ramp constraint. |
| `capital_cost_piecewise_opt` | Static float | Currency/MW; `0` | Optimised capital-cost value in the relevant piecewise formulation. |
| `marginal_cost_piecewise_opt` | Series | Currency/MWh; `0` | Optimised marginal-cost value in the relevant piecewise formulation. |

## Interpretation notes

- **Flow signs:** 100 MW consumed at bus0 and 70 MW supplied at bus1 are reported as `p0=100`, `p1=-70`.
- **Additional ports:** supplying `bus2` adds the corresponding `efficiency2`, `p2`, `delay2`, and `cyclic_delay2` fields as needed. These are schema extensions rather than separate base CSV rows.
- **Reverse conversion:** allowing negative dispatch with an efficiency below 1 does not create a physically correct independently lossy reverse converter. Configure directional conversion explicitly when required.
- **Time:** minimum up/down times count snapshots; normal ramp limits apply per transition; maintenance uses elapsed weighted time. These are different conventions.
- Fixed-period costs require a consistent time basis. Output defaults are placeholders; valid dual interpretation depends on the solved formulation and weighting.
