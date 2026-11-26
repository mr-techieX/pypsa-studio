# PyPSA GlobalConstraint Attribute Reference

A **GlobalConstraint** imposes a restriction across multiple assets, such as a system-wide CO2 budget or a transmission-expansion budget. It does not represent a physical device.

Total attributes covered for **GlobalConstraint**: **8**.

## Inputs

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `name` | String; required | No default | Unique identifier, for example `co2_budget`. This names the constraint, not its mathematical type. |
| `type` | String | `"primary_energy"` | Selects a supported built-in constraint formulation. Examples include `primary_energy`, `tech_capacity_expansion_limit`, `operational_limit`, `transmission_volume_expansion_limit`, and `transmission_expansion_cost_limit`. Use exact identifiers with underscores, not descriptive labels containing spaces. |
| `investment_period` | Float | Period identifier; `NaN` | Restricts the applicable constraint to one investment period where supported. Unset means periods are considered together according to the selected formulation. Not an ordinary operating-snapshot timestamp. |
| `bus` | String | Unset | Optional bus scope for `tech_capacity_expansion_limit` in the installed implementation. Empty means all buses. The CSV's shorter label `tech_expansion_limit` is inconsistent with the implementation; use the full identifier above. |
| `carrier_attribute` | String | `"co2_emissions"` | Meaning depends on `type`. For `primary_energy`, names a coefficient column in `network.carriers`, typically `co2_emissions`. For technology capacity limits it identifies the carrier to select, rather than a carrier-table column. Do not assume one interpretation applies to every type. |
| `sense` | String | `"=="` | Mathematical relationship: `"<="`, `"=="`, or `">="`. A maximum CO2 budget normally uses `"<="`; the default equality would require the exact specified total. |
| `constant` | Float | Constraint-dependent; `0` | Right-hand-side value. For a CO2 budget, this is tonnes of CO2 over the applicable accounting horizon. For other types it may represent capacity, capacity-distance, energy, or money. Match the unit to the selected formulation. |

## Output

| Attribute | Type | Unit / initial default | Description |
|---|---|---|---|
| `mu` | Static float | Currency per unit of `constant`; `0` | Shadow price of the global constraint. For a CO2 budget, it relates to the marginal economic value of changing the emissions limit. Sign conventions and weights matter; interpret against the exact constraint rather than treating it automatically as a positive carbon price. |

## Example interpretation: CO2 budget

For a `primary_energy` constraint with `carrier_attribute="co2_emissions"`, `sense="<="`, and `constant=1000`, the applicable weighted emissions may not exceed 1,000 tonnes. Generator fuel input is derived using efficiency, then multiplied by the carrier emissions factor. Relevant storage boundary terms can also matter in the full formulation.

## Interpretation notes

- Defining carrier emissions factors alone does not impose a budget; the global constraint supplies the restriction.
- Snapshot and investment-period weights affect accounting totals. A budget must use the same horizon and units as the model.
- Shadow prices require valid solved dual values. Integer models do not automatically supply LP-style marginal prices.
