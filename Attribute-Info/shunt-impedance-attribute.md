# PyPSA ShuntImpedance Attribute Reference

A **ShuntImpedance** is an electrical admittance connected at one bus, for example a capacitor, reactor, or conductance. Its power depends on voltage magnitude squared, unlike a fixed-power Load. It is primarily a power-flow component.

Total attributes covered for **ShuntImpedance**: **10**.

## Inputs

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `name` | String; required | No default | Unique identifier, such as `capacitor_bank`. |
| `bus` | String; required | No default | Bus at which the shunt is connected. Its nominal voltage is used in per-unit conversion. |
| `g` | Float | Siemens; `0` | Shunt conductance, the real part of admittance. With the default sign convention, positive conductance consumes active power. |
| `b` | Float | Siemens; `0` | Shunt susceptance, the imaginary part of admittance. Positive susceptance represents capacitive reactive supply; negative susceptance represents inductive behaviour. |
| `sign` | Float | Dimensionless; `-1` | Orientation convention chosen so positive conductance withdraws active power from the bus. Retain the default for conventional shunt representation. |
| `active` | Boolean | `True` | Whether the shunt is considered an active component in applicable calculations. |

## Outputs

| Attribute | Type | Unit / initial default | Description |
|---|---|---|---|
| `p` | Series | MW; `0` | Active power consumed at the bus, positive for net load. At voltage magnitude `v_mag_pu`, the standard calculation is `g_pu × v_mag_pu²`. |
| `q` | Series | MVAr; `0` | Reactive power, positive for net generation under this component's documented convention. The standard calculation is `b_pu × v_mag_pu²`. Note the different interpretation of positive `p` and positive `q`. |
| `g_pu` | Static float | Per unit; `0` | Conductance converted using `g` and bus nominal voltage. Calculated internally rather than specified as an independent physical parameter. |
| `b_pu` | Static float | Per unit; `0` | Susceptance converted using `b` and bus nominal voltage. |

## Interpretation notes

- For fixed admittance, raising voltage magnitude to 1.1 per unit multiplies the corresponding power magnitude by `1.1² = 1.21`.
- Shunts are not freely dispatchable reactive generators, and adding one does not introduce AC voltage optimisation into ordinary linear economic dispatch.
- Check the component's sign conventions rather than applying Generator or Load conventions blindly.
- Output defaults are placeholders until the relevant calculation runs.
