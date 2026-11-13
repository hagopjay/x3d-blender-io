# Cross-engine scorecard

One driver, one results schema: the same X3D scenes through X_ITE, Babylon.js, Castle and Blender, with the validator verdict and
FLIP per scene and engine. It sits beside the fidelity rig (`tools/fidelity_rig`, which it imports and calls, never copies) and the
Castle repo's 15-scene quality run: it does not replace them, it puts every leg of every engine into one `results.json`.

```
python3 tools/scorecard/run.py --scenes SCENES.json --out out/scorecard [--legs all] [--resume] [--spp 256] [--only a,b]
python3 tools/scorecard/report.py out/scorecard        # run.py already does this; report.py re-renders from results.json
```

`SCENES.json` is the rig's format (`[{"name", "x3d", ...}]`, paths relative to `--base`, default `tools/fidelity_rig`).
Needs what the rig needs (`npm install` in `tools/fidelity_rig`, `BPY_PYTHON` pointing at a Python with `bpy`, flip-evaluator,
numpy, Pillow) plus `xvfb-run` for EEVEE and Castle. Heavy jobs: run it under `nice`; Chromium and Blender are not run in parallel by the driver.

## Legs

| id | what it is | needs |
|---|---|---|
| `blender_cycles` | **the reference.** Cycles CPU on the add-on's import of the X3D: 256 spp, 12 bounces, no denoise, ideal lights, camera / clear colour / headlight as the rig gives them to the web engines. Two seeds: seed 0 is the image, seed 1 gives the reference's noise floor | bpy |
| `xite` | X_ITE on the X3D (`render.mjs`, headless Chromium, SwiftShader) | node |
| `babylon_addon_glb` | Babylon.js on the glb the add-on writes (`blender_leg.py`), at the rig's headlight | node, bpy |
| `babylon_castle_glb` | Babylon.js on the glb the Castle exporter writes | `CASTLE_CONVERT=/path/to/x3d-castle-convert` |
| `castle_native` | `castle-render`: the X3D drawn by Castle itself | `CASTLE_RENDER=/path/to/castle-render`, xvfb |
| `blender_eevee` | Blender EEVEE (engine id `BLENDER_EEVEE`) on the same import, a rasteriser scored against the Cycles image. All scenes go through **one** Blender process under `xvfb-run -a` (first render about 66 s of shader compile) | bpy, xvfb-run |

A leg that cannot run (`CASTLE_*` unset, binary missing, no xvfb) is recorded for every scene as `status: "not-run"` with the reason;
a leg not in `--legs` is `not-run` with "not selected"; nothing is omitted and nothing is faked. `failed` carries the tool's error,
`not-applicable` is for a tool that refuses an input.

`cycles_ref.py` (Blender side, also `eevee_ref.py`) is this repo's own implementation of the Cycles reference conventions of the Castle
quality leg (read for it, nothing imported): SRGB colour space, add-on light units, ideal point and sun lights, a clear-colour world seen only by camera rays,
Standard view transform, 8-bit sRGB PNG.

## What a record holds (schema `x3d-blender-io.scorecard/v1`, `schema.py`)

Per scene and leg: leg id, engine and version, the input it read (x3d or which glb, with sha256 and producer), status and reason, the
validator verdict (Khronos glTF-Validator on every glb: errors, warnings, triangles and the EMPTY flag; X3D well-formedness on the X3D inputs),
FLIP against the Cycles reference (whole frame and geometry-only) and against X_ITE (secondary), mean |delta| against X_ITE, render seconds
and, for Cycles, the seed-to-seed FLIP. The top of the file holds the run parameters and the rig fingerprint (browser and flags,
SwiftShader / llvmpipe, vCPU count, every tool version, git revisions of the add-on, this repo and the Castle exporter inputs).
`schema.check_results(doc)` lists every way a document departs from the schema.

The validator mark (`✓` valid, `✓w` valid with warnings, `✗` errors, `∅` EMPTY, `x✓` well-formed X3D) appears after every FLIP
number. EMPTY is a glb with 0 triangles that the validator passes while the X3D declares geometry: the validator proves structure only.

## Outputs

`results.json`; `scorecard.md` (per-scene FLIP with marks; engine means over the **common scene set**, which the report states, and over each leg's own set;
paired difference against X_ITE with a bootstrap interval; the secondary X_ITE table; validator counts; failures; fingerprint; a footnote naming the tool
behind every kind of number); `scorecard.html` (the same, self-contained, dark and light, plus a contact sheet per scene with every leg's downscaled render and
FLIP error map); `scenes/<scene>/<leg>.png` and `flip_<leg>.png`; `logs/`; `work/` (glbs, validator reports, job files).

`--resume` keeps every record that is ok or not-applicable for the same scene bytes, the same settings (spp, seeds, size, add-on revision) and an image still on
disk; it re-runs failed and not-run records and recomputes a metric only when the images behind it changed. Tests (no browser, no Blender, fake legs for the driver):
`tests/test_scorecard_*.py`, run by `python3 .github/scripts/run_tests_in_blender.py`.

## Reading it honestly

- The reference is Cycles on the add-on's reading of the file, not truth. `babylon_addon_glb` and `blender_eevee` share that reading and are not independent of it;
  where the add-on drops a node or flattens a Background, the reference does too (FLIP then rewards leaving content out). The add-on's default light units are calibrated
  to what X_ITE draws.
- Means over different scene sets are not comparable; use the common-set column. Frame-level FLIP of a small object is tiny: read the geometry column.
- Render seconds are software GL wall clock on shared vCPUs, not frame rates; the X_ITE and Babylon times exclude the rig's fixed settle wait; the first EEVEE scene includes the shader compile.
- Castle legs are written against the command lines of the Castle repo's `tools/run_quality.py` (`leg_castle_export`, `leg_castle_render`) and have not been run here: the Castle build was not available (Suspected until a run).

## Dry run (13 Nov 2026, spp 32, 5 rig probes, legs xite, babylon_addon_glb, blender_cycles)

Blender 5.3.0 (bpy 5.3.0) Cycles CPU 32 spp as the reference, X_ITE 16.7.1, Babylon.js 9.32.0, Chromium 153 (SwiftShader), flip-evaluator 1.7 LDR, add-on ab99988,
4 shared vCPUs. Mean FLIP over the 5 probes: X_ITE 0.0126, Babylon on the add-on glb 0.0063 (paired difference -0.0063, 95% bootstrap [-0.0218, +0.0024], 2 wins 3 losses);
reference seed-to-seed floor 0.0004 to 0.0009 (mean 0.0006). All five add-on glbs: 0 validator errors, 0 warnings, 36 triangles. Per scene (X_ITE / Babylon): p1 0.0054 / 0.0060,
p2 0.0435 / 0.0067, p3 0.0040 / 0.0078, p4 0.0085 / 0.0085, p5 0.0016 / 0.0023: within 0.0001 of the Castle quality leg's 256 spp numbers for the same probes (0.0053 / 0.0060, 0.0436 / 0.0068, 0.0039 / 0.0077, 0.0085 / 0.0085, 0.0015 / 0.0022), so the 32 spp reference is already
close to it on these flat probes. EEVEE on p2 alone (32 spp Cycles reference): FLIP 0.0013, 61 s for that one render (first render of the process, shader compile included). These are dry-run numbers
for the harness, not the scorecard: the full-spp sweep over the scene list is a separate run.
