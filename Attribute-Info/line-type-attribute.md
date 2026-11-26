# PyPSA LineType Attribute Reference

A **LineType** is a reusable catalogue entry for electrical line parameters per unit length. A Line refers to it through `type`; the Line's length and number of parallel circuits determine its resulting electrical parameters. A LineType is not a physical line by itself.

Total attributes covered for **LineType**: **9**.

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `name` | String; required | No default | Unique catalogue identifier referenced by a Line's `type`. |
| `f_nom` | Float; required | Hz; `50` | Nominal frequency associated with the type's parameters, including conversion of capacitance to susceptance. |
| `r_per_length` | Float; required | Ohm/km; `0` | Series resistance per kilometre for one circuit. At 0.05 Ohm/km, a 100 km single circuit has 5 Ohm series resistance. Parallel circuits reduce the equivalent series resistance. |
| `x_per_length` | Float; required | Ohm/km; `0` | Series reactance per kilometre for one circuit. Multiplied by length and adjusted for parallel circuits when calculating the Line's reactance. AC linear power flow needs non-zero series reactance. |
| `c_per_length` | Float | nF/km; `0` | Shunt capacitance per kilometre. Converted to line shunt susceptance using frequency and length; parallel circuits increase total capacitance. |
| `i_nom` | Float | kA; `0` | Nominal current rating of the type. Useful for deriving a physical apparent-power rating with voltage and circuit count; do not assume merely selecting a LineType assigns the Line's `s_nom`. |
| `mounting` | String | `"ol"` | Construction category: `"ol"` for overhead line or `"cs"` for cable. Describes the catalogue entry. |
| `cross_section` | Float | mm²; `0` | Conductor cross-sectional area. Descriptive physical information, not a substitute for specifying appropriate electrical parameters. |
| `references` | String | Unset | Source or citation for the type's electrical parameters. Useful for tracing assumptions to manufacturer data or literature. |

## Interpretation notes

- See [Line attributes](line-attribute.md) for actual line endpoints, capacity, costs, and flows.
- The Line's `type` is functional, unlike the unimplemented `type` placeholders on Generator and Load.
- Catalogue impedance parameters are per kilometre; manually entered Line `r` and `x` are total branch values in Ohm.
