# X3D test suite: run commentary

The suite works end to end. It builds a 194-case Blender scene, exports it with the real exporter, validates the
file, and loads it in X_ITE.

Against `x3d-blender-io` v2.6.1 (a4238a6), **143 of 147 core cases pass**. Two exporter bugs account for the four
failures:

* **Phantom sphere**: a mesh with no faces (edge-only, empty, or unrealised Geometry Nodes) logs "no exportable
  faces" but still exports a grey `<Sphere radius="0.75">`. These show up as extra grey spheres in the Z01 and Z09
  screenshots.
* **Occlusion false positive**: the exporter matches the keyword `ao` against the full texture path, so a file under
  a folder called `kaolin` becomes an `occlusionTexture`.

## Browser and skinning

* **X_ITE 16.5.1**: the scene loads, the 2 s animation loop runs, and all 18 zones were photographed and looked at.
  The only console error is the `.tga` texture, which no browser can decode.
* **Skinning**: the exported HAnim skinning matches Blender's deformation to under 2 mm.

## Other exporter gaps the suite flags (19 warnings; full list in `X3D_TEST_EXPECTATIONS.md`)

* Coordinates are written with `%.6f`, so a 500 nm object collapses to zero.
* Light intensity saturates at 1, so 10 W and 100 W look identical.
* The spot cone is about 4% too narrow, and `beamWidth` ignores spot blend.
* `scene.camera` is not the initial viewpoint.
* Collection instances don't export.

There are also 26 roadmap items the suite expects to be missing, such as GLSL shaders, material extensions and fog.

## Corrections and caveats

* An earlier claim that GLSL export was already complete was wrong. The 4.0 path has no shader output at this
  revision.
* The first run had 9 core failures, and 5 of them were mistakes in the suite, not the exporter (linear keyframes
  silently coming out Bezier, a doubled skin offset, a mis-ordered rigid-body cache, and two wrong expectations).
  The suite was fixed, not the exporter, and the remaining 4 are confirmed against the exporter source.
* Not tested in the original run: the Blender GUI export path, Blender 4.2 LTS, a real GPU. X_ITE ran on software
  rendering at about 1 frame per second.

## About `reference/glsl_golden.x3d`

A hand-written GLSL target for what the exporter should emit once it supports shaders. Fresnel is enhanced twice:
first, exact dielectric Fresnel, the formula behind Blender's Layer Weight node; second, the same Fresnel term also
weights a studio-gradient reflection and a Blinn-Phong highlight, and the `blend` value animates through a ROUTE. It
compiles in X_ITE with no console messages and the shader uniforms animate. The suite's generator writes an
identical copy (`out/reference/glsl_golden.x3d`); they are byte-for-byte equal.

## Status against current `main` (0c48976), Blender 5.1.0

The suite above was calibrated on `a4238a6`. `main` has since moved 31 commits; the suite was re-run on it (Blender 5.1.0,
exporter registered from the checkout via `--repo`):

| tier | `main` 0c48976 | `main` + phantom-sphere fix (this branch) |
|---|---|---|
| CORE | 143 / 147 | **147 / 147** |
| FIDELITY | 2 pass, 19 warn | 2 pass, 19 warn |
| ROADMAP | 21 missing, **5 NEW** | 21 missing, **5 NEW** |

* **Implemented upstream since the calibration (flipped to NEW):** edge-only meshes and curves written as
  `IndexedLineSet` (`Z01.wire.lines`, `Z15.curve.lines`), shape keys as `CoordinateInterpolator` (`Z13.shapekey`),
  per-frame mesh deformation (`Z13.meshdeform`), shadows (`Z11.shadow`).
* **Fixed upstream:** the occlusion false positive (`Z06.decoy.ao`, commit 35c4e63 takes an AO map by its own name only).
  Four regression tests for it are added in `tests/test_material_analysis.py`; they pass against upstream's fix.
* **Fixed here:** the phantom `<Sphere>` for mesh-like objects that evaluate to no faces (`Z01.empty.robust`,
  `Z09.gn.nophantom`). The extractor now sets `IRInstance.no_faces` and `iter_shapes()` yields no shape for it, so the
  object keeps its Transform with no placeholder. Hand-built IR without the flag keeps the primitive-hint fallback.
* **Suite expectations updated:** `Z01.wire.robust` and `Z15.curve.wire` previously required "no Shape at all". They now
  accept an `IndexedLineSet` (a faithful line export) and still reject a face shape or a placeholder primitive, via the
  new optional `ignore_geometry` argument of the validator's `shapes` check. Both pass on older and current exporters.
* **CI:** a `suite` job in `.github/workflows/ci.yml` builds the scene with Blender 5.1.2, exports it with the checkout
  under review, and fails the build if any CORE case fails; the scoreboard is uploaded as an artifact.

Reports: `reports/x3d_validation_report.html` (original, Blender 5.2.2), `..._blender51_origin_main_0c48976.html`
(upstream, 143/147), `..._blender51_with_phantom_fix.html` (this branch, 147/147). The X_ITE contact sheet is
`reports/browser_report.html`; the browser check was not re-run on Blender 5.1.0 (needs playwright, Chromium and X_ITE
from a CDN).

Sources: [hagopjay/x3d-blender-io](https://github.com/hagopjay/x3d-blender-io),
[hagopjay/x3d_mcp](https://github.com/hagopjay/x3d_mcp), [x_ite 16.5.1 on npm](https://www.npmjs.com/package/x_ite).
