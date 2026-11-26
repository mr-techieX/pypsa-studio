# PyPSA Generator Attribute Reference

Total attributes covered for **Generator**: **47 static attributes**.

The attributes appear below in their original column order. An attribute's presence in the table does not mean its associated modelling feature is enabled.

## 1. Connection, capacity, and operating limits

| Attribute | Unit / default | Description and example |
|---|---|---|
| `bus` | Bus name; required | Bus where the generator injects electricity. Your generator connects to `electricity_bus`, whose power balance receives its output. |
| `control` | Text; `"PQ"` | Power-flow control strategy: `"PQ"` specifies active and reactive power; `"PV"` specifies active power and voltage magnitude; `"Slack"` provides the reference and balances the remaining power mismatch. This concerns power-flow calculations, rather than economic dispatch priority. |
| `type` | Text; unset | Placeholder for a generator type. The schema explicitly says it is not implemented; assigning a value does not automatically configure technical characteristics. |
| `p_nom` | MW; `0` | Nominal electrical capacity used to calculate output limits. Your value of `100` means a 100 MW generator, not 100 MW of actual generation. When `p_nom_extendable=True`, capacity becomes an optimisation decision instead of being fixed by this input. |
| `p_nom_mod` | MW; `0` | Fixed module size for capacity investment. For example, `50` represents capacity built in 50 MW modules. Setting it introduces integer variables for discrete capacity choices. |
| `p_nom_extendable` | Boolean; `False` | Allows the optimiser to choose nominal capacity, subject to applicable capacity limits and costs. With `False`, capacity is fixed. |
| `p_nom_min` | MW; `0` | Lower bound on optimised capacity when capacity is extendable. For example, `50` requires at least 50 MW of capacity. It does not impose a minimum dispatch level. |
| `p_nom_max` | MW; `inf` | Upper bound on optimised capacity when capacity is extendable. For example, `500` limits investment to 500 MW. `inf` means no finite upper bound is specified through this attribute. |
| `p_nom_set` | MW; unset | Fixes the capacity decision to a specified value within the extendable-capacity formulation. For example, `p_nom_set=150` constrains an extendable generator to 150 MW. |
| `p_min_pu` | Per unit; `0` | Minimum output at each snapshot as a fraction of nominal capacity. For a 100 MW generator, `0.3` means 30 MW. With `committable=False`, a positive value creates a must-run requirement. With commitment enabled, the minimum applies when the unit is on. Can be constant or time-varying. |
| `p_max_pu` | Per unit; `1` | Maximum output at each snapshot as a fraction of nominal capacity. For a 100 MW generator, `0.8` limits output to 80 MW. Useful for renewable availability profiles and thermal derating. Can be constant or time-varying. |
| `p_set` | MW; unset | Active-power set point for optimisation or power flow. When used in optimisation, it fixes generation rather than leaving dispatch freely chosen within its limits. For a Generator, `p_set=50` specifies 50 MW of generation; for a Load, the same attribute represents demand. |
| `p_init` | MW; unset | Output immediately before the first optimised snapshot, used to constrain the initial ramp. For example, an initial output of 40 MW and an applicable 20 MW upward-ramp allowance limit the first snapshot's output to 60 MW. |
| `e_sum_min` | MWh; `-inf` | Minimum total electricity production over one optimisation horizon, using the relevant generator snapshot weightings. For example, `200` requires at least 200 MWh over that horizon. The default imposes no lower energy limit. |
| `e_sum_max` | MWh; `inf` | Maximum total electricity production over one optimisation horizon. For example, `1000` caps production at 1,000 MWh. This limits cumulative energy, unlike `p_nom` or `p_max_pu`, which limit power. |
| `q_set` | MVAr; `0` | Reactive-power set point for power-flow calculations, subject to the selected control mode. Reactive power supports voltage and differs from active power measured in MW. Can be constant or time-varying. |
| `sign` | Dimensionless; `1` | Determines how dispatch enters the bus power balance. The default `+1` represents injection into the bus; `-1` represents consumption. It is an orientation convention, not an efficiency setting. |

## 2. Technology, costs, lifetime, and efficiency

| Attribute | Unit / default | Description and example |
|---|---|---|
| `carrier` | Text; unset | Energy source or technology label, such as `"gas"`, `"coal"`, `"wind"`, or `"solar"`. Links the generator to carrier-level properties used in relevant global constraints, including primary-energy-related constraints. Naming the generator `gas_generator` does not automatically assign this label or fuel properties. |
| `marginal_cost` | Currency/MWh; `0` | Linear operating cost per MWh of electrical output. Your value of `60` means producing 50 MWh contributes 3,000 currency units to the linear operating cost. Include fuel, variable O&M, and carbon costs consistently if they should be represented. Supports constant, time-varying, or piecewise specifications. |
| `marginal_cost_quadratic` | Schema lists currency/MWh; `0` | Coefficient of the quadratic dispatch-cost term. A positive coefficient makes higher output progressively more expensive. It multiplies squared dispatch, so it should not be interpreted or entered like the ordinary linear `marginal_cost`. The schema's unit label alone does not fully express this distinction. |
| `active` | Boolean; `True` | Whether the generator is considered in optimisation. Setting it to `False` excludes the component without deleting its row. This differs from unit-commitment status, which can change between snapshots. |
| `build_year` | Year; `0` | Calendar year in which the generator is built. Used with `lifetime` to determine activity in investment-period modelling. It is not an operating-hours counter. |
| `lifetime` | Years; `inf` | Operating lifetime. Together with `build_year`, determines asset availability in investment-period modelling. Also used in annuity calculations when `overnight_cost` is supplied. |
| `capital_cost` | Currency/MW; `0` | Fixed cost per MW of capacity for the modelled cost period, commonly supplied as an annualised investment cost in an annual model. For example, 100 MW at 80,000 currency/MW contributes 8 million currency units before applicable investment-period weighting and additional fixed costs. Used directly unless `overnight_cost` is specified. |
| `overnight_cost` | Currency/MW; `NaN` | Upfront investment cost per MW, before annualisation. If specified, PyPSA calculates an annuity using `discount_rate` and `lifetime`. Takes precedence over `capital_cost`. |
| `discount_rate` | Per unit; `NaN` | Rate used to annualise `overnight_cost`. Enter `0.07` for 7%, not `7`. A zero rate spreads the upfront cost over the lifetime without a financing return. |
| `fom_cost` | Currency/MW; `0` | Fixed operation and maintenance cost per MW for the relevant cost period, added to the investment-cost component. Associated with installed capacity rather than MWh produced. |
| `efficiency` | Per unit; `1` | Ratio of electrical output to primary-energy input. At `0.4`, producing 1 MWh of electricity requires 2.5 MWh of fuel energy. Used in relevant primary-energy and emissions accounting. It does not automatically convert a fuel price into `marginal_cost`; avoid applying efficiency twice when calculating costs. Supports constant, time-varying, or piecewise specifications. |

## 3. Unit commitment and maintenance

| Attribute | Unit / default | Description and example |
|---|---|---|
| `committable` | Boolean; `False` | Enables unit-commitment constraints: on/off decisions, applicable start-up/shut-down costs, and minimum operating times. These commitment features are not activated by default. |
| `maintainable` | Boolean; `False` | Enables maintenance scheduling constraints. Associated duration, unavailable-capacity fraction, and event count apply only when this is `True`. |
| `maintenance_duration` | Hours; `0` | Required elapsed duration of each maintenance event. Each event covers consecutive snapshots whose relevant weightings sum to at least this duration. For example, 6 hours can correspond to three snapshots weighted at 2 hours each. |
| `maintenance_pu` | Per unit; `1.0` | Fraction of nominal capacity unavailable during maintenance. For a 100 MW generator, `0.4` makes 40 MW unavailable; `1.0` represents a full outage. Unlike `p_max_pu`, this describes an unavailable fraction. |
| `maintenance_events` | Count; `1` | Required number of maintenance events within one optimisation horizon. For example, `2` requires two events when maintenance scheduling is enabled. |
| `start_up_cost` | Currency/event; `0` | Cost incurred when the generator changes from off to on. For example, `5000` adds 5,000 currency units per start. Applies only with `committable=True`; can be constant or time-varying. |
| `shut_down_cost` | Currency/event; `0` | Cost incurred when the generator changes from on to off. Applies only with `committable=True`; can be constant or time-varying. |
| `stand_by_cost` | Currency/hour; `0` | Cost incurred whenever commitment status is `1`, whether output is positive or zero. Represents an online/no-load cost separate from energy-production costs. At 100 currency/hour, two appropriately weighted online hours contribute 200 currency units. Can be constant or time-varying. |
| `min_up_time` | Snapshots; `0` | Minimum consecutive snapshots the generator must remain on after starting. For example, `3` means three snapshots, not necessarily three hours. Applies only with commitment enabled and does not account for snapshot weightings. |
| `min_down_time` | Snapshots; `0` | Minimum consecutive snapshots the generator must remain off after shutting down. Counts snapshots rather than weighted hours. Applies only with commitment enabled. |
| `up_time_before` | Snapshots; `1` | Number of snapshots the generator had already been continuously on before the first optimised snapshot. Determines any remaining minimum-up-time obligation. Previously optimised status is used instead where applicable. Applies only with commitment enabled; snapshot weightings are not considered. |
| `down_time_before` | Snapshots; `0` | Number of snapshots the generator had already been continuously off before the first optimised snapshot. Determines any remaining minimum-down-time obligation. A positive value takes precedence over `up_time_before`; previously optimised status replaces supplied history where applicable. Applies only with commitment enabled; snapshot weightings are not considered. |

## 4. Ramping, clustering, and static outputs

| Attribute | Unit / default | Description and example |
|---|---|---|
| `ramp_limit_up` | Per unit; `NaN` | Maximum output increase between adjacent snapshots as a fraction of nominal capacity. For a 100 MW generator, `0.2` allows a 20 MW increase. Not automatically rescaled by snapshot duration. Ignored when `NaN`; can be constant or time-varying. |
| `ramp_limit_down` | Per unit; `NaN` | Maximum output decrease between adjacent snapshots. For a 100 MW generator, `0.3` allows a 30 MW decrease. Not automatically rescaled by snapshot duration. Ignored when `NaN`; can be constant or time-varying. |
| `ramp_limit_start_up` | Per unit; `NaN` | Maximum upward output change when starting from off, relative to nominal capacity. For a 100 MW unit, `0.4` permits up to 40 MW on start-up under the applicable commitment constraints. Used only with `committable=True`; ignored when `NaN`. |
| `ramp_limit_shut_down` | Per unit; `NaN` | Maximum downward output change when shutting down, relative to nominal capacity. For a 100 MW unit, `0.4` permits a drop of at most 40 MW to zero, restricting output immediately before shutdown. Used only with commitment enabled; ignored when `NaN`. |
| `weight` | Dimensionless; `1` | Weight used for network clustering, where generators may be aggregated. Does not represent snapshot duration, probability, or generator availability. |
| `p_nom_opt` | MW; initial `0` | Output: nominal capacity reported by optimisation, particularly relevant when investment is enabled. The initial zero in an unsolved network is a placeholder, not evidence that your 100 MW generator has no capacity. |
| `capital_cost_piecewise_opt` | Currency/MW; initial `0` | Output: optimised capital-cost value when piecewise linearisation is used. Relevant to that specialised formulation; its initial zero does not mean an investment calculation has been performed. |

## Current notebook example

| Explicit input | Value | Meaning |
|---|---|---|
| `bus` | `"electricity_bus"` | Injects electricity into this bus. |
| `p_nom` | `100` MW | Has 100 MW of nominal capacity. |
| `marginal_cost` | `60` currency/MWh | Each MWh of electrical output costs 60 currency units in the linear operating-cost term. |

With the default `p_min_pu=0` and `p_max_pu=1`, the basic output range is 0–100 MW. The notebook's 50 MW load would require 50 MW from this generator in the simple one-bus dispatch case, but no optimisation has been solved in the recorded notebook state.

## Interpretation notes

- **Power versus energy:** MW measures output rate or capacity; MWh measures energy produced over time.
- **Per unit:** `0.8` means 80% of the relevant reference quantity, usually nominal capacity for output and ramp limits.
- **Period costs:** `capital_cost` and `fom_cost` are not automatically annual costs; use a consistent modelling period and cost basis.
- **Unset values:** `inf` means no finite bound. `NaN` or an unset value has an attribute-specific meaning, such as disabling an optional constraint.
- **Static versus dynamic data:** These 47 columns belong to the static generator table. Time-varying inputs can be stored separately, and outputs such as dispatch `p`, reactive power `q`, and commitment `status` belong to `network.generators_t`.
- **Defaults versus results:** Default values in output fields are placeholders until the relevant optimisation has run.
