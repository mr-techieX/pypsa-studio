# PyPSA TransformerType Attribute Reference

A **TransformerType** is a reusable catalogue entry describing a two-winding transformer. A Transformer refers to it through `type`. It is not itself a connection between two buses.

Total attributes covered for **TransformerType**: **16**.

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `name` | String; required | No default | Unique catalogue identifier referenced by a Transformer's `type`. |
| `f_nom` | Float; required | Hz; `50` | Nominal operating frequency of the transformer type. |
| `s_nom` | Float; required | MVA; `0` | Rated apparent power of one transformer of this type. Parallel units are represented on the Transformer through `num_parallel`. |
| `v_nom_0` | Float; required | kV; `0` | Rated voltage on side 0, usually the high-voltage winding. |
| `v_nom_1` | Float; required | kV; `0` | Rated voltage on side 1, usually the low-voltage winding. The rated voltage ratio provides the nominal winding ratio. |
| `vsc` | Float; required | Percent; `0` | Short-circuit voltage: voltage needed in a short-circuit test to drive rated current, as a percentage of rated voltage. Determines the magnitude of series impedance. Enter `10` for 10%, not `0.10`. |
| `vscr` | Float; required | Percent; `0` | Resistive component of short-circuit voltage. Used with `vsc` to separate resistance and reactance. It is not the complete impedance magnitude. |
| `pfe` | Float; required | kW; `0` | No-load iron losses from the open-circuit test. Used to derive the shunt conductance representing core losses. |
| `i0` | Float; required | Percent; `0` | No-load current as a percentage of rated current. Used with iron losses to derive the magnetising branch. |
| `phase_shift` | Float; required | Degrees; `0` | Nominal voltage phase displacement introduced by the transformer type. Separate from tap-related voltage-magnitude adjustment. |
| `tap_side` | Integer; required | Side identifier; `0` | Side carrying the tap changer: `0` for primary, usually high voltage; `1` for secondary, usually low voltage. |
| `tap_neutral` | Integer; required | Tap position; `0` | Position at which the winding ratio matches the rated-voltage ratio. The Transformer's off-nominal tap ratio is 1 when `tap_position` equals this value. |
| `tap_min` | Integer; required | Tap position; `0` | Minimum tap position specified for the type. Describes the available tap range; it does not by itself introduce tap-position optimisation. |
| `tap_max` | Integer; required | Tap position; `0` | Maximum tap position specified for the type. |
| `tap_step` | Float; required | Percent; `0` | Voltage-ratio change per tap step. For `1.25`, each step changes the off-nominal ratio by 1.25 percentage points relative to neutral. |
| `references` | String | Unset | Source or citation for the electrical parameters. |

## Interpretation notes

- See [Transformer attributes](transformer-attribute.md) for endpoints, operating tap position, expansion, and results.
- Percent inputs here differ from per-unit inputs: 10% is entered as `10`, whereas a per-unit value of 10% is `0.1`.
- Selecting a standard type overrides several manually entered Transformer parameters; consult the Transformer's `type` description.
