# PyPSA Transformer Attribute Reference

A **Transformer** is a passive two-winding connection, typically between different voltage levels. It can include off-nominal tap ratios and phase shifts. Its flows follow the electrical network equations.

Total attributes covered for **Transformer**: **47**.

## 1. Connection and electrical model

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `name` | String; required | No default | Unique transformer identifier. |
| `bus0` | String; required | No default | First endpoint, usually the high-voltage side. Defines side 0 for taps and output signs. |
| `bus1` | String; required | No default | Second endpoint, usually the low-voltage side. Power may flow in either direction. |
| `type` | String | Unset | TransformerType catalogue identifier. With `num_parallel`, overrides manual `r`, `x`, `g`, `b`, `s_nom`, `tap_ratio`, `tap_side`, and `phase_shift`. With an empty type, manual values are used. |
| `model` | String; required | `"t"` | Equivalent-circuit model for the admittance matrix: `"t"` or `"pi"`. The default T model represents the transformer physics before internal conversion as needed. |
| `x` | Float; required | Per unit; `0` | Series reactance on the transformer's own `s_nom` and nominal-voltage base. Non-zero reactance is needed for an AC branch in linear power flow. Unlike a Line's `x`, this is not in Ohm. Ignored when determined by a standard type. |
| `r` | Float; required | Per unit; `0` | Series resistance on the transformer's own rating base. Nonlinear power flow requires non-zero `r + jx`. Ignored when determined by a standard type. |
| `g` | Float | Per unit; `0` | Shunt conductance on the transformer's own rating base, representing active core-loss effects. Ignored if determined by the selected type. |
| `b` | Float | Per unit; `0` | Shunt susceptance on the transformer's own rating base, representing magnetising effects. Ignored if determined by the selected type. |

## 2. Capacity and costs

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `s_nom` | Float | MVA; `0` | Nominal apparent-power rating in either direction. Provides the flow-capacity scale in optimisation; ignored as a fixed capacity when extendable and may be derived from a standard type. |
| `s_nom_mod` | Float | MVA; `0` | Module size for discrete capacity investment, introducing integer variables. |
| `s_nom_extendable` | Boolean | `False` | Allows optimisation of nominal capacity. Does not by itself represent every physical change that accompanies replacement or parallel installation. |
| `s_nom_min` | Float | MVA; `0` | Lower bound on nominal capacity when extendable. |
| `s_nom_max` | Float | MVA; `inf` | Upper bound on nominal capacity when extendable. |
| `s_nom_set` | Float | MVA; unset | Fixes nominal capacity within the extendable formulation. |
| `s_max_pu` | Static/series | Per unit; `1` | Maximum allowed absolute flow relative to nominal capacity. For a 100 MVA rating, `0.8` gives an 80-unit flow limit in the relevant formulation. |
| `capital_cost` | Float | Currency/MVA; `0` | Fixed-period investment cost per MVA, commonly annualised on an annual basis. Used directly unless overnight cost is provided. |
| `overnight_cost` | Float | Currency/MVA; `NaN` | Upfront cost per MVA; annualised with discount rate and lifetime. Overrides `capital_cost`. |
| `discount_rate` | Float | Per unit; `NaN` | Rate for overnight-cost annualisation. `0.07` is 7%; zero is supported. |
| `fom_cost` | Float | Currency/MVA; `0` | Fixed-period O&M per MVA, added to the investment-cost component. |

## 3. Taps, phase shift, and asset limits

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `num_parallel` | Float | Unit count; `1` | Number of equivalent parallel transformers when using a standard type. Can be fractional; ignored for empty `type`. |
| `tap_ratio` | Float | Per unit; `1` | Off-nominal voltage ratio relative to the buses' nominal-voltage ratio. `1` means no off-nominal adjustment, not equal physical kV on both sides. Derived from the type when one is selected. |
| `tap_side` | Integer | Side identifier; `0` | Side containing the tap changer: `0` or `1`. Derived from the type if specified. |
| `tap_position` | Integer | Tap position; `0` | Absolute position on the type's tap scale. Neutral operation occurs at the type's `tap_neutral`, which need not be zero. Used with `tap_step` to derive the off-nominal ratio. |
| `phase_shift` | Static/series | Degrees; `0` | Fixed voltage phase-angle shift. With the installed sign convention, linear flow follows `(theta0 - theta1 - phase_shift) / x` on consistent units. Derived from a standard type when selected; ignored as a fixed target when phase shift is optimised. |
| `phase_shift_min` | Float | Degrees; `0` | Lower bound for optimised per-snapshot phase shift. The shift becomes a decision variable only when this is less than `phase_shift_max`. Otherwise `phase_shift` remains the fixed setting. |
| `phase_shift_max` | Float | Degrees; `0` | Upper bound for the phase-shift decision. For example, bounds of -10 and +10 degrees allow controlled phase shifting over that range. |
| `active` | Boolean | `True` | Whether to include the transformer in optimisation. |
| `build_year` | Integer | Year; `0` | Build year used with lifetime to determine investment-period activity. |
| `lifetime` | Float | Years; `inf` | Asset lifetime, also used for annualisation where applicable. |
| `v_ang_min` | Float | Degrees; `-inf` | Deprecated and ignored. Does not establish an independent lower angle bound. |
| `v_ang_max` | Float | Degrees; `inf` | Symmetric bound on the magnitude of the angle difference in optimisation, including the phase-shift contribution as defined by the formulation. Infinite means this bound is not applied. |

## 4. Outputs

| Attribute | Type | Unit / initial default | Description |
|---|---|---|---|
| `sub_network` | Static string | Unset | Connected passive-network identifier assigned by topology determination. Do not set manually. |
| `p0` | Series | MW; `0` | Active power withdrawn from bus0 into the transformer. |
| `q0` | Series | MVAr; `0` | Reactive power withdrawn from bus0 into the transformer. |
| `p1` | Series | MW; `0` | Active power withdrawn from bus1. Negative means supply from the transformer to bus1. |
| `q1` | Series | MVAr; `0` | Reactive power withdrawn from bus1. |
| `x_pu` | Static float | Per unit; `0` | Reactance converted to PyPSA's 1 MVA base: initially `x / s_nom`, with equivalent-circuit conversion where applicable. |
| `r_pu` | Static float | Per unit; `0` | Resistance converted to the internal base: initially `r / s_nom`, with equivalent-circuit conversion where applicable. |
| `g_pu` | Static float | Per unit; `0` | Shunt conductance converted to the internal base: initially `g × s_nom`, with equivalent-circuit conversion where applicable. |
| `b_pu` | Static float | Per unit; `0` | Shunt susceptance converted to the internal base: initially `b × s_nom`, with equivalent-circuit conversion where applicable. |
| `x_pu_eff` | Static float | Per unit; `0` | Effective reactance for linear flow, calculated from `x_pu × tap_ratio`. |
| `r_pu_eff` | Static float | Per unit; `0` | Effective resistance for the applicable linear formulation, calculated from `r_pu × tap_ratio`. |
| `s_nom_opt` | Static float | MVA; `0` | Nominal apparent-power capacity reported after optimisation. |
| `mu_lower` | Series | Currency/MVA; `0` | Non-negative shadow price of the lower signed-flow bound, not simply the lower investment-capacity bound. |
| `mu_upper` | Series | Currency/MVA; `0` | Non-negative shadow price of the upper signed-flow bound. |
| `phase_shift_opt` | Series | Degrees; `0` | Realised phase shift: the fixed setting for fixed-shift transformers or the optimiser's choice when phase-shift bounds enable control. |

## Interpretation notes

- Selecting a standard type overrides several manual inputs. Do not assume conflicting manual values remain effective.
- Ordinary linear optimisation does not solve the full AC voltage/reactive-power problem or automatically optimise voltage tap positions.
- In a lossless calculation, `p0 = -p1`. If active losses are represented, `p0 + p1` is the loss.
- Output defaults are placeholders. Shadow-price interpretation depends on formulation, weights, and the availability of valid dual results.
