# Contract and oracles (robustness plan v3, Gates 1 and 2)

What the export promises, how each promise is checked, and the planted fault that proves each check can fail.
Measured 22 Nov 2026 from main 47ed742 plus this change, with bpy 5.3.0 and the Blender binaries 4.5.14 LTS, 5.1.2 and
5.2.2 LTS, x3d.py 4.0.65.8, SaxonC-HE 13.1.1, X_ITE 16.7.1 in Playwright's Chromium (SwiftShader). Grades: Confirmed
(measured here), Likely, Suspected.

## Gate 1: the contract

| Piece | File | What it says | Measured |
|---|---|---|---|
| Mapping table, Blender half | `source/mapping/blender_rna.json` | every Blender property the probe scene reaches: carried, approximated, clamped, dropped or editor_only, with its receipt rule | 262 rows + 3 patterns; 0 undeclared on 4 Blender versions |
| Mapping table, X3D half | `mapping/x3d_fields.json`, `docs/MAPPING.md` | every node and field of X3D 4.0 (x3d.py), what the export writes and the import reads | 268 nodes, 3,363 fields; the export writes 31 nodes and 138 fields (2.7.1; 30 and 133 in 2.7.0) |
| Loss receipt v1 | `source/receipt.py` | a stable head line `x3d-blender-io.receipt` in every X3D 4.0 file, a `<file>.receipt.json` sidecar on request (export option or `BLENDER_X3D_RECEIPT=1`), a `prev` chain through re-imports | probe scene: 1 dropped, 4 approximated, 4 clamped; 0 disagreements with the sweep over about 8,800 exports |
| Structure | `tools/schematron/` | the Web3D Consortium's X3D Schematron (vendored, pinned by sha256) on every suite export; disagreements are listed with a suspect judge and a count that may only shrink | 12 listed disagreements (9 in 2.7.0), 0 unexplained errors |

## Gate 2: the oracles

| Judge | Command | Question | Planted fault (`tools/oracles/plants.json`) |
|---|---|---|---|
| Perturbation sweep | `tools/io_sync/perturb.py --check` | does each property behave as its row says? (silent loss, stale row, receipt disagreement) | `roughness-dropped`, `spot-blend-carried`, `receipt-forgets-clamp` |
| Golden files | `tools/io_sync/golden.py` | is each of 12 frozen scenes' export, in canonical form, byte-equal to `tests/golden/`? | `roughness-dropped-golden` |
| Metamorphic relations | `tests/test_metamorphic_bpy.py` | move, rename, reorder, scale, axis round trip, unused material: does the file change exactly as it should? | `translation-axes-swapped` |
| Round-trip invariants | `tools/io_sync/invariants.py --budget` | after import and re-export: same faces, world bbox, materials, lights, viewpoints, instancing, ROUTEs, textures? | 8 edits in `tests/test_invariants.py` |
| Same renderer, two exporters | `tools/fidelity_rig/same_renderer.py` | X_ITE on this add-on's X3D vs X_ITE on Blender's own glb: within the calibrated tolerance? | `basecolour-channels-swapped` |
| Structure | `tools/schematron/schematron.py --plants` | does the Schematron flag a ROUTE to nowhere, a USE before DEF, a wrong component level, a missing component? | `tests/plants/schematron-*.x3d` |
| Differential chaos | `tools/chaos/differential.py --fail-on-crash` | does any one-edit mutant of the frozen scenes crash the import, the re-export or a validator? (docs/CHAOS.md) | `import-bool-crash` |

`python tools/oracles/plant.py list` prints every plant; `make NAME DIR` writes a copy of `source/` with the one edit,
and `expect-fail NAME -- CMD` passes only when CMD fails and names the fault.

## Findings these judges made (22 Nov 2026)

1. **The bound camera followed the outliner, not `scene.camera`** (Confirmed, all 4 versions; fixed in 2.7.1). X3D
   binds the first Viewpoint in the file; the export wrote Viewpoints in outliner order, so reordering the outliner
   changed which camera a browser opened on (frozen scene `cameras`: Persp, the active camera, before; Ortho after).
   The export now writes the subtree holding the active camera first (`extract.bind_first`); `test_r3` asserts 0 of 12
   scenes move their binding.
2. **Blender 4.5.14 LTS round trip did not converge** (Confirmed, fixed here). A text object's degenerate face got a
   corner normal of length 4.8e-05; the export wrote it as is and the re-import normalised it, so E1 to E2 had 10
   Normal differences on the suite's `Z04_label`. The export now writes unit normals; E1 to E2 is 0 on 4.5.14, 5.1.2
   and 5.2.2.
3. **One round trip breaks 3 invariants, the same on all three binaries** (Confirmed, `tools/io_sync/invariant_budget.json`):
   collection instancing (`Group` USE 1 to 0: decision 3, A12, importer work), two line sets' grey PhysicalMaterial
   return as black UnlitMaterial (Likely faithful: an X3D line set without normals is unlit, so browsers already drew it
   with emissiveColor 0), and 2 PositionInterpolator ROUTE pairs are gained on `main`. Faces, world bbox, lights,
   viewpoints and textures hold.
4. **Same renderer, two exporters: 5 of 12 frozen scenes are pixel-identical** (Confirmed: lit_cube, two_materials,
   uv_grid, linked_instances, and emissive_glass within 0.12 where drawn). The rest differ for named reasons in
   `same-renderer-baseline.json`: vertex colours (the add-on writes a colour attribute no material reads; Blender's glb
   leaves it out), area light (the add-on approximates it as a DirectionalLight; glTF has none), objects with no
   material (the add-on writes Blender's 0.8 grey; the glb falls back to glTF's white metal), loose edges (Blender's glb
   omits an edge-only mesh).
5. **Blender's glTF exporter in its default lighting mode writes a 0.8 W/m2 sun as 546.4 lux** (0.8 x 683). X_ITE takes
   that as X3D intensity and saturates to white (mean delta 68 on lit_cube). The judge uses the COMPAT mode, the
   convention the rig's own glb leg uses.
6. **Schematron rule bug** (Confirmed): the HAnimJoint USE rule (`HAnimHumanoid[//*[@DEF=$USE]]`, .sch line 3674) uses
   an absolute `//` and fires whenever a scene has two humanoids. Report to Web3D held until the owner says send.
7. **Two exporter losses fixed in 2.7.1** (Confirmed by the sweep on 4.5.14, 5.1.2, 5.2.2 and 5.3.0: 63 carried, 54
   before). An ORTHO camera was written as a perspective Viewpoint; it is now an `OrthoViewpoint` (fieldOfView = the
   `ortho_scale` box at the render aspect, so the file declares Navigation level 3), and the import reads it back, so
   the suite's Viewpoint fieldOfView round trip is exact (first-trip budget 1 to 0 in each profile). A light's
   `use_temperature` tint was dropped; the colour is now `color x temperature_color`, as Blender's glTF exporter writes.
8. **A second Schematron rule bug** (Confirmed): the `Viewpoint | OrthoViewpoint` rule (.sch line 2495) reads
   `(OrthoViewpoint and not(Full or Navigation >= 3)) or count(preceding::OrthoViewpoint) > 0`, so every Viewpoint
   after the first OrthoViewpoint is reported as needing Navigation level 3 even when the head declares it. A two-node
   file with Navigation level 3 gives 1 error with the OrthoViewpoint first and 0 with it second; the suite lists 7
   per profile. Held with finding 6, not sent.

## Where they run

- Pull requests (`.github/workflows/ci.yml`): the Blender matrix (4.5.14, 5.1.2, 5.2.2) runs the sweep, the golden files
  and the metamorphic tests; the suite job, now on all three, adds the invariants, field parity, the mapping check and
  the Schematron; job `contract` (bpy 5.3.0) runs the sweep, the golden files and every code plant; the export gate
  job adds the same-renderer judge and its plant.
- Nightly (`.github/workflows/nightly.yml`, 03:17 UTC, and by hand): the slow set on every Blender line (decision 6).

## Decisions from the plan, as built

1. X3D 4.0 is the default export from 2.7.0 (`x3d_version` default `X3D40`).
2. The receipt line is always written; the sidecar stays opt-in until agreement is measured case by case on the 195-case
   suite (the sweep's agreement, 0 disagreements, is measured; the per-case count is not yet).
3. A12, collection instances as linked instances on import: importer work, queued; the invariant budget shows it.
4. Unity: unscheduled.
5. Behaviour node editor: owned by its own lane, not built here.
6. Long runs on GitHub Actions: the nightly workflow.
