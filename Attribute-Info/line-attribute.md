# PyPSA Line Attribute Reference

A **Line** is a passive electrical connection between two buses. Its flow follows network electrical laws rather than being independently controlled like a Link. Electrical parameters and thermal capacity are separate inputs.

Total attributes covered for **Line**: **43**.

## 1. Endpoints and electrical parameters

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `name` | String; required | No default | Unique line identifier, such as `north_south_line`. |
| `bus0` | String; required | No default | First endpoint, which defines the reference direction for reporting flows. It does not make the line unidirectional. |
| `bus1` | String; required | No default | Second endpoint. A Line normally connects buses at the same nominal voltage; use a Transformer to connect voltage levels. |
| `type` | String | Unset | Name of a LineType. When supplied, catalogue parameters, `length`, and `num_parallel` determine electrical values and override manually entered `r`, `x`, and `b`. With an empty type, supply total branch parameters directly. |
| `x` | Float; required | Ohm; `0` | Total series reactance, not reactance per kilometre. Must be non-zero for an AC branch in linear power flow. For inductance `L`, `x = 2πfL`. Ignored when a standard type determines it. |
| `r` | Float; required | Ohm; `0` | Total series resistance. The general branch formulation requires non-zero resistance for a DC branch in linear power flow; the installed Line schema identifies AC as the valid Line carrier. Nonlinear power flow requires non-zero total impedance `r + jx`. Ignored when determined by a standard type. |
| `g` | Float | Siemens; `0` | Total shunt conductance, the real part of admittance `g + jb`, representing leakage-related active losses. |
| `b` | Float | Siemens; `0` | Total shunt susceptance, the imaginary part of shunt admittance. For capacitance `C`, `b = 2πfC`. Derived from the standard type when one is selected. |

## 2. Capacity, investment, and availability

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `s_nom` | Float | MVA; `0` | Nominal apparent-power capacity in either direction. In standard linear optimisation, this provides the active-flow bound rather than a full nonlinear apparent-power constraint. Ignored as a fixed capacity if extendable. |
| `s_nom_mod` | Float | MVA; `0` | Expansion module size, such as the fixed rating of an additional circuit. Introduces integer variables for discrete capacity choices. |
| `s_nom_extendable` | Boolean | `False` | Allows optimisation of nominal apparent-power capacity. A basic capacity decision does not by itself guarantee a physically consistent redesign of line impedance. |
| `s_nom_min` | Float | MVA; `0` | Lower bound on nominal capacity when extendable. |
| `s_nom_max` | Float | MVA; `inf` | Upper bound on nominal capacity when extendable. |
| `s_nom_set` | Float | MVA; unset | Fixes nominal capacity to this value within the extendable formulation. |
| `s_max_pu` | Static/series | Per unit; `1` | Maximum allowed flow magnitude relative to nominal capacity. For `s_nom=100`, `0.7` gives a 70-unit flow limit in the relevant formulation. Can represent derating or dynamic ratings. A fixed contingency margin is an approximation, not a full N-1 analysis. |
| `capital_cost` | Float | Currency/MVA; `0` | Fixed-period investment cost per MVA. Include any route-length factor in this value yourself. Used directly unless `overnight_cost` is specified. |
| `overnight_cost` | Float | Currency/MVA; `NaN` | Upfront investment cost per MVA; annualised with discount rate and lifetime. Takes precedence over `capital_cost`. |
| `discount_rate` | Float | Per unit; `NaN` | Annualisation rate for overnight cost. `0.07` means 7%; zero is supported. |
| `fom_cost` | Float | Currency/MVA; `0` | Fixed-period O&M per MVA, added to the investment-cost component. |
| `active` | Boolean | `True` | Whether to include the Line in optimisation. |
| `build_year` | Integer | Year; `0` | Build year used for investment-period activity. |
| `lifetime` | Float | Years; `inf` | Asset lifetime; also used for annualisation where applicable. |

## 3. Route, circuits, and angle limits

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `length` | Float | km; `0` | Physical line length. Used to calculate electrical parameters when a standard type is selected. Useful for preparing costs, but does not automatically multiply `capital_cost`. |
| `carrier` | String | Empty | Current type. The installed schema states `"AC"` is the valid Line carrier. Use an appropriate controllable component for an HVDC representation. |
| `terrain_factor` | Float | Per unit; `1` | Terrain multiplier available for constructing route-based cost assumptions. It does not replace explicitly calculating the final cost input. |
| `num_parallel` | Float | Circuit count; `1` | Number of equivalent parallel circuits used with a standard type; can be fractional. Series impedance decreases and shunt admittance increases with circuit count. Ignored for manually specified electrical parameters when `type` is empty. |
| `v_ang_min` | Float | Degrees; `-inf` | Deprecated and ignored. It does not set an independent lower angle bound in this installation. |
| `v_ang_max` | Float | Degrees; `inf` | Symmetric cap on the magnitude of the voltage-angle difference across the Line in optimisation. For `30`, the allowed difference is between -30° and +30°. Ignored when infinite. |

## 4. Outputs

| Attribute | Type | Unit / initial default | Description |
|---|---|---|---|
| `sub_network` | Static string | Unset | Passive connected-network identifier assigned by topology determination. Do not set manually. |
| `p0` | Series | MW; `0` | Active power withdrawn from `bus0` into the Line. Positive means the Line takes power from that bus. |
| `q0` | Series | MVAr; `0` | Reactive power withdrawn from `bus0` into the Line. |
| `p1` | Series | MW; `0` | Active power withdrawn from `bus1` into the Line. For lossless flow from bus0 to bus1, `p0` is positive and `p1` negative. |
| `q1` | Series | MVAr; `0` | Reactive power withdrawn from `bus1` into the Line. |
| `x_pu` | Static float | Per unit; `0` | Series reactance converted from Ohm using nominal bus voltage and PyPSA's internal base. Calculated from inputs. |
| `r_pu` | Static float | Per unit; `0` | Series resistance converted from Ohm using nominal voltage and the internal base. |
| `g_pu` | Static float | Per unit; `0` | Shunt conductance converted using nominal voltage and the internal base. |
| `b_pu` | Static float | Per unit; `0` | Shunt susceptance converted using nominal voltage and the internal base. |
| `x_pu_eff` | Static float | Per unit; `0` | Effective series reactance used by linear power-flow calculations. Derived, not a separate physical design input. |
| `r_pu_eff` | Static float | Per unit; `0` | Effective series resistance used by the applicable linear branch formulation. |
| `s_nom_opt` | Static float | MVA; `0` | Nominal apparent-power capacity reported after optimisation. |
| `mu_lower` | Series | Currency/MVA; `0` | Non-negative shadow price of the lower signed-flow bound, corresponding to flow in the reverse reference direction. It is not simply the dual of the investment lower bound `s_nom_min`. |
| `mu_upper` | Series | Currency/MVA; `0` | Non-negative shadow price of the upper signed-flow bound in the forward reference direction. |
| `capital_cost_piecewise_opt` | Static float | Currency/MVA; `0` | Optimised capital-cost value when the relevant piecewise formulation is used. |

## Interpretation notes

- In a lossless calculation, `p0 + p1 = 0`; with active losses represented, their sum is the loss.
- Line `r` and `x` use Ohm. Transformer `r` and `x` use per-unit values on the transformer's rating base.
- MVA is apparent power; MW is active power. Standard linear dispatch does not solve the full AC voltage/reactive-power problem.
- Derived values and solver output defaults are not evidence that a calculation has run. Shadow prices depend on the solved formulation and weighting.
