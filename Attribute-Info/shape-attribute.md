# PyPSA Shape Attribute Reference

A **Shape** stores geographic geometry associated with network components, such as a region polygon or route. It supports spatial representation rather than providing an energy-balance or dispatch equation.

Total attributes covered for **Shape**: **5**.

| Attribute | Type | Unit / default | Description and example |
|---|---|---|---|
| `name` | String; required | No default | Unique shape identifier. It may differ from the name of the component it describes. |
| `geometry` | Geometry | Unset | Geographic geometry object, for example a point, line, or polygon. Coordinates must be interpreted in the shapes' coordinate reference system. |
| `component` | String | Unset | Component type associated with the shape, for example `Bus` or `Line`. Used with `idx` to identify the relevant asset. |
| `idx` | String | Unset | Name/index label of the associated component instance. For a bus shape, this could be `electricity_bus`. |
| `type` | String | Unset | Geometry-type or category label. This does not select an electrical or optimisation formulation. |

## Interpretation notes

- `network.crs` identifies the coordinate reference system for Shape geometry; bus `x` and `y` coordinates also have spatial-reference metadata through `network.srid`.
- A map polygon does not automatically aggregate demand, constrain construction, or establish network connectivity.
- Shapes describe geography; connectivity is established by component bus references.
