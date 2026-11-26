# PyPSA Store Attribute Reference

A **Store** holds energy between snapshots. Its nominal capacity is measured in MWh, and it has no independent built-in charging/discharging power-capacity limit. To model energy capacity and converter power independently, combine a Store with appropriately configured Links or Processes.

Total attributes covered for **Store**: **40**.

## 1. Connection and energy capacity

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `name` | String; required | No default | Unique identifier, such as `hydrogen_tank`. |
| `bus` | String; required | No default | Bus at which the Store takes in or supplies energy. The bus carrier determines the energy form. |
| `type` | String | Unset | Unimplemented placeholder; does not select storage technology or performance. |
| `carrier` | String | Empty | Storage carrier or technology label, useful for grouping and relevant carrier-based accounting. |
| `e_nom` | Float | MWh; `0` | Nominal energy capacity, not power capacity. A 100 MWh Store can hold 100 MWh at its default upper limit. Ignored as a fixed capacity when `e_nom_extendable=True`. |
| `e_nom_mod` | Float | MWh; `0` | Module size for energy-capacity investment. For example, `25` allows capacity in 25 MWh blocks and introduces integer variables. |
| `e_nom_extendable` | Boolean | `False` | Allows the optimiser to choose energy capacity subject to the applicable bounds and costs. |
| `e_nom_min` | Float | MWh; `0` | Minimum optimised energy capacity when extendable. Not a minimum filling level. |
| `e_nom_max` | Float | MWh; `inf` | Maximum optimised energy capacity when extendable. `inf` means no finite bound through this attribute. |
| `e_nom_set` | Float | MWh; unset | Fixes the energy-capacity decision to this value within the extendable formulation. |
| `e_min_pu` | Static/series | Per unit; `0` | Lower energy-level bound relative to nominal energy capacity. For 100 MWh capacity, `0.2` requires at least 20 MWh stored. |
| `e_max_pu` | Static/series | Per unit; `1` | Upper energy-level bound relative to nominal energy capacity. For 100 MWh capacity, `0.9` permits at most 90 MWh stored. |

## 2. Boundary conditions and operating inputs

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `e_initial` | Float | MWh; `0` | Energy before the first modelled snapshot, rather than necessarily the end-of-first-snapshot energy. Ignored when the applicable cyclic boundary condition is used. |
| `e_initial_per_period` | Boolean | `False` | In multi-investment modelling, resets the starting energy to `e_initial` at each investment period when enabled. |
| `e_cyclic` | Boolean | `False` | Links initial energy to final energy over the optimised snapshot group instead of using `e_initial`. Prevents net depletion across that cycle, but does not fix a numerical initial filling level. |
| `e_cyclic_per_period` | Boolean | `False` | Applies cyclic energy boundary conditions separately within each investment period. |
| `p_set` | Static/series | MW; unset | Fixes active-power dispatch in optimisation or specifies it for power flow. Under the default sign, positive values mean supply to the bus and negative values mean charging. Unlike `e_set`, this specifies a power rate rather than stored energy. |
| `q_set` | Static/series | MVAr; `0` | Reactive-power set point for power flow only. |
| `e_set` | Static/series | MWh; `NaN` | Fixes the stored-energy level at selected snapshots in optimisation. For example, a 50 MWh target at the last snapshot enforces an end-level requirement. `NaN` leaves a snapshot without this fixed-level constraint. |
| `sign` | Float | Dimensionless; `1` | Orientation sign for the Store's energy/dispatch convention. Keep the default for ordinary storage: positive dispatch supplies the bus and reduces stored energy. |

## 3. Costs, losses, and asset life

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `marginal_cost` | Static/piecewise/series | Currency/MWh; `0` | Cost of net dispatch. Positive dispatch incurs cost; negative dispatch, meaning charging, receives a credit for a positive linear coefficient. It is not a symmetric cost on both charging and discharging. |
| `marginal_cost_quadratic` | Static/series | Schema: currency/MWh; `0` | Coefficient of a quadratic net-dispatch cost term. Multiplies squared dispatch, so it must not be interpreted like the linear per-MWh coefficient; the schema's unit label does not fully describe that distinction. |
| `marginal_cost_storage` | Static/series | Currency/MWh/hour; `0` | Cost of holding 1 MWh for one hour, separate from dispatch cost. For 50 MWh held over one weighted hour at `2`, the storage-holding cost is 100 currency units. |
| `capital_cost` | Float | Currency/MWh; `0` | Fixed-period cost per MWh of energy capacity, often an annualised cost on an annual basis. This is not a cost per MW of converter power. Used directly unless `overnight_cost` is supplied. |
| `overnight_cost` | Float | Currency/MWh; `NaN` | Upfront energy-capacity investment cost, annualised using `discount_rate` and `lifetime`. Takes precedence over `capital_cost`. |
| `discount_rate` | Float | Per unit; `NaN` | Rate used to annualise overnight investment cost. `0.07` means 7%; zero is supported. |
| `fom_cost` | Float | Currency/MWh; `0` | Fixed-period O&M per MWh of nominal energy capacity, added to the investment-cost component. Not a throughput cost. |
| `standing_loss` | Static/series | Fraction per hour; `0` | Fraction of stored energy lost per hour. Over an elapsed duration of `h`, the retained fraction is `(1 - standing_loss)^h`. This is a loss on the energy inventory, not a charging-efficiency factor. |
| `active` | Boolean | `True` | Whether to consider the Store in optimisation. |
| `build_year` | Integer | Year; `0` | Build year, used with lifetime to determine activity across investment periods. |
| `lifetime` | Float | Years; `inf` | Asset lifetime, also used for overnight-cost annualisation. |

## 4. Outputs

| Attribute | Type | Unit / initial default | Description |
|---|---|---|---|
| `p` | Series | MW; `0` | Net power at the bus: positive for discharge/supply, negative for charging/withdrawal under the default convention. |
| `q` | Series | MVAr; `0` | Reactive-power output, positive for net supply. Relevant to power flow. |
| `e` | Series | MWh; `0` | Stored-energy level calculated for each snapshot by optimisation. |
| `e_nom_opt` | Static float | MWh; `0` | Nominal energy capacity reported after optimisation. The initial zero is not a solved result. |
| `mu_upper` | Series | Currency/MWh; unset | Shadow price of the upper stored-energy bound associated with nominal capacity and `e_max_pu`. |
| `mu_lower` | Series | Currency/MWh; unset | Shadow price of the lower stored-energy bound associated with `e_min_pu`. |
| `mu_energy_balance` | Series | Currency/MWh; unset | Shadow price of the inter-temporal storage balance, often interpreted as the marginal value of stored energy or a water value. |
| `capital_cost_piecewise_opt` | Static float | Currency/MWh; `0` | Optimised capital-cost value when the relevant piecewise formulation is used. |
| `marginal_cost_piecewise_opt` | Series | Currency/MWh; `0` | Optimised marginal-cost value when the relevant piecewise formulation is used. |

## Interpretation notes

- For a lossless Store, the basic balance is `energy now = energy before - dispatch × elapsed hours`.
- Elapsed time in storage balances comes from the relevant snapshot weights, not timestamp spacing alone.
- Unlike a [StorageUnit](storage-unit-attribute.md), a Store does not couple energy capacity to a built-in nominal power through `max_hours`.
- Fixed-period costs require a consistent time basis. `inf` means no finite bound; `NaN` usually leaves an optional input unset, subject to that attribute's definition.
- Shadow prices require a solved model and careful interpretation of weighting and formulation. Integer models do not automatically provide equivalent LP marginal values.
