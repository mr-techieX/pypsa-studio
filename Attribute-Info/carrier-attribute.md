# PyPSA Carrier Attribute Reference

A **Carrier** is a shared label and property record for an energy source or technology. Components refer to it through their `carrier` attribute. Defining a carrier does not create a generator, a fuel supply, or a fuel-price calculation.

Total attributes covered for **Carrier**: **6**.

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `name` | String; required | No default | Unique carrier identifier, such as `gas`, referenced by other components. A generator's name alone does not assign its carrier. |
| `co2_emissions` | Float | Tonnes/MWh of primary energy; `0` | CO2 intensity of the primary energy input, not necessarily of electrical output. With `0.2` tonnes/MWh of fuel and generator efficiency `0.4`, 1 MWh of electricity corresponds to 0.5 tonnes of CO2. An applicable global constraint is needed to impose an emissions budget. |
| `color` | String | Unset | Plotting colour, for example `"orange"` or `"#AB9812"`. Does not affect dispatch or investment. |
| `nice_name` | String | Unset | Human-readable label for statistics and visualisations, for example `"Natural Gas"` for the identifier `gas`. References still use the identifier. |
| `max_growth` | Float | MW in schema; `inf` | Absolute limit on newly installed capacity per investment period in multi-investment optimisation. The installed implementation activates carrier growth constraints only for finite values. Use consistent nominal-capacity units when grouping technologies. |
| `max_relative_growth` | Float | Dimensionless ratio; `0` | Additional relative-growth term used with finite `max_growth`. In the installed implementation, new capacity in the current period is limited by the absolute allowance plus this ratio times the previous period's new capacity. It is not a percentage applied automatically to all existing capacity. `0` leaves the absolute allowance alone. |

## Interpretation notes

- `co2_emissions` describes physical intensity; it does not automatically add a carbon price to `marginal_cost`.
- Bus carriers can describe energy forms such as AC electricity; generator carriers often describe technologies or fuels such as wind or gas.
- `max_growth` and `max_relative_growth` concern investment periods, not ramping between operating snapshots.
- The CSV gives no meaningful unit label for `max_relative_growth`; it is a ratio. Its implementation was checked in `pypsa/optimization/global_constraints.py`.
