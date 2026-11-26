# Third-party data notice

## PGLib OPF IEEE 14-bus numeric subset

`energy_gui/data/pglib14_dc.json` contains an adapted numeric subset of
**IEEE PES Power Grid Library – Optimal Power Flow, v23.07**, case
`pglib_opf_case14_ieee.m` (2023-07-23).

- Copyright (c) 1999 **Richard D. Christie, University of Washington**,
  Electrical Engineering; IEEE PES Power Grid Library contributors.
- Source case: <https://github.com/power-grid-lib/pglib-opf/blob/dc6be4b2f85ca0e776952ec22cbd4c22396ea5a3/pglib_opf_case14_ieee.m>
- Source data-license notice: <https://github.com/power-grid-lib/pglib-opf/blob/dc6be4b2f85ca0e776952ec22cbd4c22396ea5a3/LICENSE>
- Data license: **Creative Commons Attribution 4.0 International (CC BY 4.0)**,
  <https://creativecommons.org/licenses/by/4.0/>;
  legal terms: <https://creativecommons.org/licenses/by/4.0/legalcode>.
- Upstream conversion provenance: IEEE Common Data Format `ieee14cdf.txt`,
  converted 20 September 2004; header `08/19/93 UW ARCHIVE 100.0 1962 W IEEE
  14 Bus Test Case`. PGLib subsequently modified capacities, offers and ratings.

### Changes in this application

This is a **lossless DC adaptation**, not an unchanged AC case or reproduction
of a published AC-OPF optimum. We retain source active demands, generator active
maxima and linear offers, branch reactances, nonunity tap effects, rate-A values
and symmetric 30-degree angle-difference bounds. Source zero tap entries mean
unity. All retained generator minima and phase shifts are zero; the three
synchronous-condenser entries have zero active capacity.

All buses are normalized to 110 kV, not asserted physical voltage levels.
Branches, including source transformer branches, are represented as PyPSA Lines:
`x_ohm = source_x_pu * tap * 110**2 / 100`. Source resistance, shunts, reactive
power, voltage-magnitude constraints and AC losses are omitted. A nonzero
`r = x_ohm / 100` placeholder passes PyPSA strict consistency and is **unused**
by this lossless optimization. The one-hour study uses a USD cost label.
Schematic coordinates are newly authored and non-geographic.

The source ratings/capacities/offers include PGLib modeling estimates; they are
not measured equipment data. Nothing implies endorsement by the original
authors, IEEE, PGLib or the University of Washington. The adapted data are
provided without a fitness-for-engineering-use claim; consult the license's
disclaimer of warranties and limitation of liability. Retain this notice and
the embedded JSON attribution/license/change fields when redistributing the
adaptation. Those fields also travel in optional project/frozen-input demo notes.

Only data are extracted; no PGLib software is copied. MATPOWER's software BSD
license was **not** used to justify case-data redistribution: it explicitly
excludes its case files. The remaining demos are authored deterministic
synthetic use cases, not third-party utility datasets.

## Dependency distribution remains a separate review

The existing development environment supplies PyPSA, Linopy, HiGHS/highspy,
PySide6/Qt and their dependencies. This notice is not a complete dependency
license inventory or permission to package Qt without satisfying its license.
There is no installer/distribution bundle in this increment. A complete
dependency/license and clean-machine review remains required before packaging.
