# PyPSA SubNetwork Attribute Reference

A **SubNetwork** is a connected group of buses and passive branches, primarily Lines and Transformers. It represents a passive connected area used in topology and power-flow calculations. A controllable Link between two areas does not automatically make them one synchronous AC area.

Total attributes covered for **SubNetwork**: **3**.

| Attribute | Type | Unit / initial default | Description |
|---|---|---|---|
| `name` | String; index output | Assigned | Unique identifier assigned according to the subnetwork ordering during topology determination. It is an internal topology label, not a user-defined geographic region. |
| `carrier` | Static string output | `"AC"` | Carrier determined from the buses belonging to the connected subnetwork. |
| `slack_bus` | Static string output | Unset | Name of the reference/slack bus for the subnetwork's applicable power-flow calculation. Its voltage angle provides the reference for other buses. |

## Interpretation notes

- Topology-derived labels appear on Buses, Lines, and Transformers as `sub_network`. Do not set these labels by hand to force connectivity.
- A bus may form an isolated subnetwork if it has no passive connection to other buses.
- This file covers schema attributes, not the full set of methods on a `SubNetwork` object. Runtime tables may also contain object references added by topology processing.
