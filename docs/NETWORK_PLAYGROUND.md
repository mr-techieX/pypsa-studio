# Expandable network playground

This RawBuild-only follow-up removes the bottom “No AI · no cloud · SQLite
project storage · Saved / unchanged” status strip and uses that space for the
active workspace. Existing header/ribbon save-state indicators remain.

## Using the network area

- Drag a node anywhere in the visible playground; it is no longer confined to
  the old 900×520 scene. All visible blank space is usable at different zooms.
- The logical paper grows with moved nodes. Moving beyond the top/left extends
  the paper by rebasing view coordinates and camera together, without making
  other nodes jump on screen.
- Drag blank space to pan or use either always-available scrollbar. Holding a
  dragged node near a viewport edge scrolls in that direction; release stops it.
- Use + / − to zoom around the viewport centre, or **Ctrl+wheel** to zoom around
  the pointer. Fit and Find/Locate remain available.
- Save layout explicitly to persist these view changes. Reset remains an
  explicit session change until saved. None of these actions changes electrical
  bus coordinates, model attributes, profiles, optimization or queried values.

The workspace is large but bounded: logical width/height up to 100,000 units,
at most 10,000 saved positions and zoom 10%–300%. A diagram too large for the
minimum Fit zoom can be explored with panning/Locate. This is not an unlimited
GIS map or a new automatic-layout algorithm.

## Rendering and layout compatibility

The grid and wires are painted into a **viewport-sized Canvas**, not a bitmap
the size of the logical paper. Large layouts therefore do not request giant Qt
textures. The old 16-million-pixel logical-area restriction is no longer needed;
finite coordinate/count/zoom bounds are still validated.

The dotted grid covers the entire visible area, including surrounding paper.
Node/port identities, flow direction/signs, congestion semantics, selection and
frozen-versus-live boundaries are unchanged. Flow labels and nodes stay aligned
while panning, zooming and expanding.

New saved layouts add optional `paperVersion: 1` to the existing layout metadata,
describing the surrounding-paper camera convention. Old unversioned layouts are
read and their camera converted **in memory**. Files are not rewritten merely
by opening them; explicit Save layout writes the new convention. There is no
core SQLite schema migration. The v1.0.0 application copy is not modified and
is not claimed to understand new large-workspace camera metadata.

Camera restoration and initial Fit wait until a previously hidden Network tab
has a real viewport size. Initial node placement is independent of zoom so
repeated project loads while in Overview cannot inflate the schematic off-screen.
The source caption reserves stable height so “saved” wording or filters do not
move the camera after Fit/Locate.

## Verification

```powershell
& '..\..\EnEx\Scripts\python.exe' tools/validate_network_playground.py
```

Evidence: `docs/network-playground-validation/`. The runner performs the full
regression suite, Light/Dark UI matrices, native Windows navigation/gesture
checks, Light/Dark/System real solve/renders, compilation, and read-only hashes
of v1.0.0 and pre-existing RawBuild project/run artifacts.

New tests exercise low-zoom dragging into formerly unusable space; real
top/left expansion and unchanged neighbouring screen positions; blank-space
panning; both scrollbar thumbs; edge-drag auto-scroll and release; cursor-centred
wheel zoom; a 42,000×26,000 layout with a viewport-sized renderer; old/new saved
layouts; hidden-tab initialization; and frozen-flow/query/artifact isolation.

Native gestures use a multi-move pointer stream and nonoverlapping hit areas at
low zoom. The initial test pass exposed timing/ambiguous-hit test-fixture issues,
and screenshot inspection additionally caught hidden-tab initialization; both
are covered in the final regression. Upstream pandas/Qt warnings and untested
display-scaling/OS combinations remain separate limitations.

Final verification: **437 regression tests passed**, with **56 UI tests in each
theme** and **16 native Windows navigation/playground tests**. Light/Dark/System
actual solve/renders and compilation passed. Fingerprints found no changes to
348 v1.0.0 files or 527 existing RawBuild project/run files. Final evidence:
`network-playground-validation/summary.json` (`all_passed: true`).

Native testing exposed inertial scroll settling after release; desktop schematic
panning now stops on release without coasting/bouncing. Hidden-tab initialization
and old saved-camera restoration were also checked before the final complete run.
