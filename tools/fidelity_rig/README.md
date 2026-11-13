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
(Blender 5.3, X_ITE 16.7.1, Babylon.js 9.32.0, Chromium 153, SwiftShader; centre patch, X_ITE / Babylon.js):

| Probe | X_ITE | light units BLENDER | light units X_ITE |
|---|---|---|---|
| p1 PhysicalMaterial, PointLight 1 | 74 | 30 | 74 |
| p2 classic Material, PointLight 1 | 204 | 27 | 207 |
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

What it checks: the glb is well-formed glTF 2.0 (container, JSON schema, accessor and buffer-view bounds, indices,
references, material and animation rules) and that the extensions it uses are valid *where this validator version knows
them*. What it does not: an extension the validator does not know is reported by the validator at INFO only
(`UNSUPPORTED_EXTENSION`, "cannot validate an extension as it is not supported"), so the gate passes such a glb even when
the file *requires* that extension; `extensionsNotValidated` lists them, the gate prints `NOT VALIDATED:` and their content
is unchecked; a valid glb can still be empty (an unsupported X3D node
imports to nothing and the glb is valid), look wrong, or use an extension an engine ignores. Visual correctness (the
deltas above) and engine support (what Babylon.js, three.js or X_ITE actually draw) are separate gates.
