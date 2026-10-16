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

## Suggested next step (from the original run)

Fix the phantom-sphere bug: one small change to the fallback in `iter_shapes()`. The suite would flip those three
cases to PASS.

---

## Reproduction on Blender 5.1.0 (this integration)

Run on macOS with Blender **5.1.0** (build 2026-03-17), repo at `5da2707` (the original calibration was Blender 5.2.2
at `a4238a6`), headless, `--factory-startup`, exporter registered from `<repo>/source` via `--repo`.

| tier | result on 5.1.0 | original (5.2.2) |
|---|---|---|
| CORE | **143 / 147** pass, 4 FAIL | 143 / 147 |
| FIDELITY | 2 PASS, **19 WARN** | 2 PASS, 19 WARN |
| ROADMAP | **26 MISSING**, 0 NEW | 26 MISSING |

The four failures are identical to the original run: `Z01.wire.robust`, `Z01.empty.robust`, `Z09.gn.nophantom`
(phantom sphere) and `Z06.decoy.ao` (occlusion false positive). Three exports (`main`, `crease`, `x41`) took about
15 s each. The full scoreboard is in `reports/x3d_validation_report_blender51.html`; the original 5.2.2 scoreboard
and the X_ITE contact sheet are alongside it.

Not re-run on 5.1.0: the X_ITE browser check (needs playwright, a Chromium download and X_ITE from a CDN).

Sources: [hagopjay/x3d-blender-io](https://github.com/hagopjay/x3d-blender-io),
[hagopjay/x3d_mcp](https://github.com/hagopjay/x3d_mcp), [x_ite 16.5.1 on npm](https://www.npmjs.com/package/x_ite).
