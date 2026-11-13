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
OrthoViewpoint becomes an orthographic Babylon.js camera with the same extents. The geometry mask takes two Babylon.js
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
