# Fidelity rig: X_ITE on the X3D against Babylon.js on the glb

Runs X3D scenes through this add-on to a glb (the Foundry convert's settings: COMPAT light units, renderable objects only,
cameras, lights, loose edges and points), then renders X_ITE on the X3D and Babylon.js on the glb in the same headless
Chromium, 512 x 512, from the X3D's first Viewpoint, and reports the mean |delta| per pixel (0-255):

- `mean_abs_delta`: the whole frame (Babylon.js clears to the first Background's first skyColor);
- `geometry_delta`: only where the glb draws geometry (a second Babylon.js render cleared to magenta is the mask), so
  backgrounds, gradients and missing text do not dilute a lighting change;
- `patches`: 5 x 5 means at listed pixels, for the probe scenes.

```
npm install                       # x_ite 16.7.1, babylonjs 9.32.0, playwright 1.63.0, gltf-validator 2.0.0-dev.3.10 (pinned)
npx playwright install chromium   # Chromium 153, the browser the numbers below were measured in
pip install bpy==5.3.0 pillow numpy   # or point BPY_PYTHON at a Python that has bpy
python3 compare.py after ../../source probes.json   # sRGB colours and X_ITE light units are the add-on's default
```

X_ITE renders with StraightenHorizon off, so a rolled Viewpoint is drawn as authored in both legs; an
OrthoViewpoint becomes an orthographic Babylon.js camera with the same extents, and a GeoViewpoint is placed in the
geocentric space the glb is in (its geoOrigin applied) with a clip range that holds the globe. The geometry mask takes two Babylon.js
renders, cleared to magenta and to green, so magenta geometry is not mistaken for background. compare.py deletes a
scene's old images before rendering and stops when render.mjs fails.

`probes/` holds five light probes (a 0.8 grey under one light, three boxes at 1.8, 2.0 and 4.2 m). Measured 12 Nov 2026
(Blender 5.3, X_ITE 16.7.1, Babylon.js 9.32.0, Chromium 153, SwiftShader; centre patch, X_ITE / Babylon.js; the p2 "light units X_ITE" cell re-measured 13 Nov 2026 at main 9fbc3ca as 203, it read 207 before):

| Probe | X_ITE | light units BLENDER | light units X_ITE |
|---|---|---|---|
| p1 PhysicalMaterial, PointLight 1 | 74 | 30 | 74 |
| p2 classic Material, PointLight 1 | 204 | 27 | 203 |
| p3 classic Material, DirectionalLight 1 | 204 | 120 | 203 |
| p4 PhysicalMaterial, PointLight 1, attenuation 1 0 0.2 | 57 | 30 | 56 |
| p5 PhysicalMaterial, DirectionalLight 0.3 | 78 | 78 | 78 |

The X3D headlight (on unless a NavigationInfo turns it off) is added in Babylon.js at the scene's `x3d_headlight_lux`.
Heavy scenes can time out in SwiftShader (the x3d.demo library hall did at 30 s).

## glTF validator gate and manifest

Every glb the rig makes goes through the Khronos glTF Validator (`gltf-validator` 2.0.0-dev.3.10, pinned in `package.json`)
right after the Blender leg: `node validate_glb.mjs scene.glb [--max-warnings N]` writes `scene.glb.validation.json`
(validator version, error / warning / info / hint counts, every issue with code, severity, pointer and message, triangle,
vertex, draw-call and material counts, `extensionsUsed` / `extensionsRequired`, the extensions the validator does not know,
and the file's size and sha256) and exits 1 on any error (or on more than N warnings), 2 when the validator cannot be loaded.
`compare.py` puts the summary in each `results.json` row (`validator_ok`, `validator`), writes
`out/LABEL/<scene>/manifest.json` (schema `x3d-blender-io.glb-manifest/v1`: the x3d's path and sha256, the add-on's git
revision, the Blender version, the `BLENDER_X3D_*` options and `X3D_SPLAT_IMPORT`, the glb's sha256 and size, the validator summary, extensions and
counts) and, if any glb failed, prints it and exits 1 after `results.json` is written; the other scenes still render.
`RIG_VALIDATOR_MAX_WARNINGS=N` makes warnings fail too. `tests/test_glb_validator_bpy.py` runs the gate without a browser
(it skips when node or gltf-validator is missing, unless `GLTF_VALIDATOR_REQUIRED=1`, which CI sets, makes that a failure;
`GLTF_VALIDATOR_DIR` points it at another install). A scene whose Blender leg produces no glb is recorded in `results.json`
with `validator_ok` false and also exits 1.

Measured 13 Nov 2026 (gltf-validator 2.0.0-dev.3.10) on the glb of two Blender scenes exported with this add-on, the LUMEN Interference Atelier and Asterion (X3D 4.0, 89,568 and 93,682 triangles, measured in the Blender-lab thread's validator step, 64d93de): 0 errors and 0 warnings each; the same two through this rig: mean |delta| 3.32 and 3.48. Across the repo's 34 scenes (5 probes, 29 others): 33 export a glb, all with 0 errors and 0 warnings (Blender 5.3.0 bpy).

What it checks: the glb is well-formed glTF 2.0 (container, JSON schema, accessor and buffer-view bounds, indices,
references, material and animation rules) and that the extensions it uses are valid *where this validator version knows
them*. What it does not: an extension the validator does not know is reported by the validator at INFO only
(`UNSUPPORTED_EXTENSION`, "cannot validate an extension as it is not supported"), so the gate passes such a glb even when
the file *requires* that extension; `extensionsNotValidated` lists them, the gate prints `NOT VALIDATED:` and their content
is unchecked; a valid glb can still be empty (an unsupported X3D node
imports to nothing and the glb is valid), look wrong, or use an extension an engine ignores. Visual correctness (the
deltas above) and engine support (what Babylon.js, three.js or X_ITE actually draw) are separate gates.

## Time and identity in the glb

- **Animation time.** The importer puts X3D time 0 on `scene.frame_start` and the glTF exporter writes `frame / fps`, so with the factory frame 1 a glb's animation runs one frame late (first sampler time 0.041667 s at 24 fps, Blender 5.3.0). `blender_leg.py` sets `frame_start = 0` before the import: first sample 0.0 s, last 2.0 s for a 2 s cycle. `export_anim_slide_to_zero` is not used: it is ignored when `export_force_sampling` is False and slides each action by its own first key. Integer-frame sampling still drops a key that falls between frames (a key at 0.3 of a 2 s cycle is frame 14.4: 0.125 units of position error at that key), and a cycle that is not a whole number of frames stops a frame early (0.7 s ends at 0.6667 s); `export_force_sampling=False` gives exact keys for Transform animation, but HAnim joint animation was not tested with it.
- **export_apply.** `export_apply=True` does not drop the add-on's morphs: with and without it the glb is byte-identical on 34 of 34 repo scenes and on two CoordinateInterpolator scenes (Blender 5.3.0). The exporter's own help text says it prevents shape keys; that holds only for a mesh with shape keys and a non-armature modifier, which the add-on makes only with its Solidify import option (off by default; then the glb carries a weights channel with no targets and fails the validator with `ANIMATION_CHANNEL_TARGET_NODE_WEIGHTS_NO_MORPHS`).
- **Identity.** The importer tags each Blender object it creates with `x3d_def` (the node's DEF, else the nearest DEF'd Transform), `x3d_def_path` (DEF'd ancestors, outermost first) and `x3d_use` (the DEF a USE points at), and the mesh and material with their DEF, and the rig exports with `export_extras=True`, so they reach the glb's node, mesh and material `extras`. Object names alone are not the DEF: Blender suffixes duplicates (`BoxShape.001`) and flat import drops Transforms. Two anonymous Shapes under one DEF'd Transform share that `x3d_def`. The glb is byte-identical across two separate imports of the same file.

## Round-trip audit (X3D -> add-on -> X3D 4.0 -> X_ITE)

`roundtrip.py` checks what the add-on does to a scene that goes in and comes out again, with every option at its default
(sRGB colour space, AUTO light units, X3D 4.0 export, animation off, the operator's other defaults):

```
BPY_PYTHON=$(which python3) python3 roundtrip.py LABEL ../../source probes.json            # or scenes-demo.json, or any scenes list
python3 roundtrip.py LABEL ../../source scenes-demo.json --only demo-chirp --no-render     # one scene, no browser
python3 roundtrip.py LABEL ../../source scenes-demo.json --animation                       # export with use_animation=True
python3 roundtrip.py LABEL ../../source scenes-demo.json --reuse                           # redo only the analysis
```

Per scene it writes `out/LABEL/<scene>/roundtrip.x3d` (+ `roundtrip.glb`, the Blender glTF export of the same imported scene,
and `asis/` with the same pair imported and exported under `BLENDER_X3D_COLOR_SPACE=AS_IS`), `audit.json`, and under
`orig/`, `reexp/`, `orig2/` the X_ITE renders of the original, the re-export and a second render of the original (the
noise floor of timers and animation); `render.mjs` renders only X_ITE for those (`xiteOnly` jobs; it also keeps X_ITE's
console errors in `xite_console.txt`). `out/LABEL/roundtrip_results.json` has every row. The audit reports:

- the re-export's validity (`source/validate.py` well-formedness, and the `x3d` Python package's field checks when installed);
- node counts by type, original against re-export (`lost`, `added`, `reduced`, `increased`; `by_design` names a lost node the default X3D 4.0 export does not write on purpose, today `GaussianSplats`, with the way out, X3D 4.1);
- X_ITE original against X_ITE re-export, each at its own first Viewpoint (so the camera round trip is part of the number):
  mean |delta| per pixel (0-255) over the frame, the share of pixels with any channel off by more than 16, the delta over the
  foreground (pixels that differ from the frame's border colour in either image), and FLIP (flip-evaluator, LDR, 67 ppd);
- a numeric colour audit. Every Material, TwoSidedMaterial, UnlitMaterial and PhysicalMaterial colour field and every
  per-vertex Color / ColorRGBA is brought to display sRGB (classic and Unlit colours already are; PhysicalMaterial colours are
  linear and are encoded) and compared with its re-export counterpart, paired by Shape order when the Shape counts match and
  by nearest colour (reorder-safe) otherwise. A classic Material `diffuseColor 0.8` that comes back as PhysicalMaterial
  `baseColor 0.6038` is an error of 0. The same pass is run with AS_IS, and the glb's `baseColorFactor`, `emissiveFactor`
  (an Unlit or line colour sits in `baseColorFactor` under `KHR_materials_unlit`) and `COLOR_0` are compared with the original
  colour converted sRGB -> linear.

`roundtrip_audit.py` holds the analysis (plain Python and numpy; `tests/test_roundtrip_audit.py` runs it without Blender or a
browser, `tests/test_roundtrip_audit_bpy.py` runs the p2 probe through the real import and export). `scenes-demo.json` lists
ten public x3d.demo scenes (classic Material, PhysicalMaterial, UnlitMaterial, textures, vertex colours, lights, Transform and
coordinate animation); its paths assume x3d.demo is cloned next to this checkout (`../../../x3d.demo`). Limits: a still frame
cannot show a lost animation (the animated scenes agree at time 0; read `nodes.lost` for TimeSensor and interpolators); X_ITE in
SwiftShader crashed the page on the 1.2 MB UnlitMaterial + shader scene (no number) and renders the 876 KB 62-light scene
differently on every run (noise floor above the delta, so no usable number).

## Export gate (glTF validator + render diff against X_ITE, both exports)

`gate.py` gates every Blender export of the add-on on the Khronos glTF Validator **and** on a render diff against X_ITE. One
command runs, per scene of one or more scenes JSONs, both exports and compares the numbers with `gate-baseline.json`:

```
BPY_PYTHON=$(which python3) python3 gate.py                                   # the 5 probes (probes.json), exit 1 on any FAIL
python3 gate.py --scenes probes.json scenes-repo.json scenes-demo.json        # the 43 scenes the baseline was seeded from
python3 gate.py --scenes scenes-gate-ci.json --jobs 2                         # the CI subset: 5 probes + lights-after, lod-control, stars-splats, stilllife-x3d40
python3 gate.py --only p2-point-classic --json one.json                       # one scene, results copied to one.json
python3 gate.py --scenes ... --reuse                                          # re-evaluate the last run's measurements (no Blender, no browser)
python3 gate.py --scenes ... --update-baseline [--allow-worse]                # rewrite measured values (see below)
```

Leg A is the glb leg (`blender_leg.py`, `manifest.validate`, Babylon.js on the glb against X_ITE on the X3D from the first
Viewpoint, the same pieces and the same masks as `compare.py`); leg B is the X3D re-export leg (`roundtrip_leg.py` with the
add-on's defaults, `roundtrip.validate_reexport`, node counts, X_ITE on the original against X_ITE on the re-export with
`roundtrip_audit.image_deltas` and FLIP). X_ITE on the original is rendered once and serves both legs. Per scene it prints PASS,
FAIL (with the reasons) or IMPROVED, and writes `out/LABEL/gate_results.json` (default LABEL `gate`; before the exit code is decided),
`out/LABEL/<scene>/measured.json`, `manifest.json`, `scene.glb`, the renders, `diff_x4.png` (glb leg) and
`diff_roundtrip_x4.png` plus `reexp/` (the re-export and its X_ITE render). `compare.py` keeps its CLI and outputs; its
first-Viewpoint helpers moved to `viewpoint.py`, which `gate.py` shares.

| # | Check | Fails when |
|---|---|---|
| 1 | `validator` | the glb is missing, the validator did not run, errors > 0 (always, whatever the baseline says), or warnings > the baseline's |
| 2 | `glb_content` | the glb is EMPTY (the validator accepts an empty glb) while the X3D has geometry; or it has no triangles while the X3D has surfaces (a points-only or lines-only glb); or its triangles fall below the baseline by more than 5%. A points-only / lines-only glb of an X3D that is only points / lines / splats passes and is reported as `points` / `lines` / `points+lines` |
| 3 | `geometry_delta` | Babylon.js-on-glb against X_ITE-on-X3D mean \|delta\| over the glb's geometry exceeds baseline + tolerance (or the geometry is no longer visible) |
| 4 | `reexport` | the re-export is not well-formed X3D, `x3d` (x3d.py) reports an error or is not installed, or more node types were lost than the baseline's count |
| 5 | `roundtrip_delta` | X_ITE original against X_ITE re-export: mean \|delta\| (0-255) or FLIP (flip-evaluator 1.7, LDR) exceeds baseline + tolerance |

**Tolerance** (written in the baseline header and used by the code): allowed = baseline + max(abs, rel x baseline), with
abs 0.5 and rel 5% for mean \|delta\|, abs 0.01 and rel 5% for FLIP, and 5% for the triangle floor. A value better than the
baseline by more than the same margin is flagged IMPROVED (the scene still passes; `--fail-on-improvement` makes it exit 1) so
the baseline gets tightened with `--update-baseline`.

**`gate-baseline.json`** holds the header (`rig`: X_ITE, Babylon.js, Chromium, the renderer, Blender, the validator, flip-evaluator,
the add-on git revision of the seeding run; X_ITE, Babylon.js, the Chromium major version, Blender, the validator and flip-evaluator are compared on every run and a difference
prints `FINGERPRINT differs` and fails under `--strict-fingerprint`, which CI uses), the `tolerance` rule and per scene:
`validator.warnings`, `glb.class` and `glb.triangles`, `geometry_delta`, `reexport.nodes_lost`, `roundtrip.mean_abs_delta` and
`flip`, plus the entries a person writes, every one with a reason (an entry whose reason is empty or still starts with
`UNEXPLAINED` fails the run):

- `known`: `{defect, reason, checks}` names the round-trip audit's defect id (D1-D14, H1: the defects the round-trip audit at commit acd6882 found; see
  the "Round-trip audit" section above) that explains why the baseline value is high. It annotates the report line (`[known D4]`) and
  excuses nothing: the baseline value is still the limit, so a known defect cannot get worse unnoticed and its fix shows as IMPROVED.
- `allow_empty`: the only way a glb with no triangles passes while the X3D has geometry.
- `skip`: a check that cannot be gated (a page crash, a scene that renders differently on every run).
- `tolerance`: a per-scene override for `geometry_delta` / `roundtrip_delta` for animated scenes that X_ITE samples at a run-dependent moment.

**`--update-baseline`** runs the scenes and records what it measured. It never loosens a threshold silently: a new value that is
worse than the baseline (higher delta, FLIP, warnings or nodes lost; fewer triangles) is printed as `REFUSED` and the old value
stays, unless `--allow-worse` is given (printed as `LOOSENED`). Float moves under 0.01 are ignored so a rerun does not churn the
file. Measurements a baseline must never absorb (validator errors, an EMPTY glb, no re-export, x3d.py errors) are not recorded;
with `--allow-worse` they are recorded as `skip` / `allow_empty` entries whose reason is `UNEXPLAINED` and which fail the next
check until a person writes the real reason. Scenes not run are left alone, and the update ends by printing the verdict of the run
against the baseline it just wrote. Seed or re-baseline from a full run, then commit the diff.

### Seed run (13 Nov 2026, add-on at 54e85e4, no source change since the audit commit acd6882)

Rig: Khronos glTF-Validator 2.0.0-dev.3.10, X_ITE 16.7.1, Babylon.js 9.32.0, Chromium 153.0.8010.12 (SwiftShader), Blender 5.3.0 (bpy
5.3.0), FLIP flip-evaluator 1.7 (LDR, 67 ppd), Python 3.13, 4 shared vCPUs, no GPU. Scenes: `probes.json`, `scenes-repo.json` (33 with
the probes) and `scenes-demo.json` (10 public x3d.demo scenes): 43 scenes, `--jobs 2`, 638 s (a second identical run) to 663 s (the seed run).

- Validator: 43 of 43 glbs have 0 errors; 41 have 0 warnings, `demo-materials-textures` 11 and `demo-material-odyssey` 203, all
  `MESH_PRIMITIVE_GENERATED_TANGENT_SPACE` (a normal map without tangents; the first 10 are kept in the results).
- Content: 38 glbs hold triangles, 4 are `points` only (`stars-view`, `stars-splats`, `stars-view-poc1`, `stilllife-splats-24k`: splats
  become points with POSITION only), and 1 is `empty`: `demo-living-heart`, whose only Shape is an empty placeholder (allowed with
  that reason in the baseline). The gate fails an empty glb of a scene that has geometry; before the baseline entry it failed
  `demo-living-heart`.
- Re-export: 43 of 43 well-formed, x3d.py 0 errors, node types lost between 0 and 20 per scene (baseline).
- Determinism: a second full run against the seeded baseline passed 43 of 43. 36 scenes reproduced every number to within 0.01 (mean
  |delta|) and 0.0001 (FLIP); the 7 that moved are all animated or unstable, and all but two stayed inside the tolerance: `demo-cannonball`
  (geometry 17.83, then 17.60), `demo-double-pendulum` (39.31, then 40.85; round trip 0.47, then 0.76), `demo-ode-integrators`,
  `demo-materials-textures` (round trip 10.52, then 10.73), `repair-0-written` (round trip 1.36, then 0.98), `repair-1-validator`
  (geometry 42.57, then 24.67) and `demo-material-odyssey` (round trip 29.05, then 39.49; the audit measured 44.36). The last three carry a
  `tolerance` (the two `repair-*`) or `skip` entry with those numbers as the reason.
  `demo-wedgwood-unlit-textures` has no X_ITE render (page crash, H1), so its two render checks are skipped with that reason.
- Known defects annotated: D1 1 scene, D2 2, D3 3, D4 4, D5 25, D6 7, D7 4, D8 11, D9 1, D10 2, D11 14, D12 3, D13 25, H1 2 (check
  lines carry `[known Dn]`).

What the gate is not: it proves structure (validator), non-emptiness and a bounded visual distance to X_ITE on a few dozen scenes in
one headless rig. It does not prove that Babylon.js, three.js or Unreal draw the glb the way X_ITE draws the X3D beyond those
scenes, it does not measure quality (a path-traced reference is separate), and a still frame cannot show lost animation (the node count
does). A baseline measured on this rig applies to this rig: another Blender, Chromium or SwiftShader build can move the numbers
(the fingerprint says so).

### CI (`fidelity-gate` job in `.github/workflows/ci.yml`)

Runs after `unit` on ubuntu-latest (Python 3.13, `bpy==5.3.0 x3d numpy pillow flip-evaluator==1.7`, `npm install` in this folder, `npx
playwright install --with-deps chromium`) on `scenes-gate-ci.json`: the 5 probes plus `lights-after`, `lod-control`, `stars-splats`
and `stilllife-x3d40`, with `--strict-fingerprint`. A manual run (`workflow_dispatch`, input `gate_full`) takes the 33 scenes of
`scenes-repo.json`. The artifact `fidelity-gate-results` holds `gate_results.json`, each scene's `measured.json`, manifest, validator
report, renders, `diff_x4.png`, `diff_roundtrip_x4.png` and the re-export. `tests/test_gate_logic.py` (thresholds, EMPTY
classification, baseline update refusals, report formatting, exit codes; synthetic measurements, no browser) and
`tests/test_gate_baseline.py` (the committed baseline lints clean, matches the pins and covers every scene list) run in the `unit` job.
