# Fidelity rig: X_ITE on the X3D against Babylon.js on the glb

Runs X3D scenes through this add-on to a glb (the Foundry convert's settings: COMPAT light units, renderable objects only,
cameras, lights, loose edges and points), then renders X_ITE on the X3D and Babylon.js on the glb in the same headless
Chromium, 512 x 512, from the X3D's first Viewpoint, and reports the mean |delta| per pixel (0-255):

- `mean_abs_delta`: the whole frame (Babylon.js clears to the first Background's first skyColor);
- `geometry_delta`: only where the glb draws geometry (a second Babylon.js render cleared to magenta is the mask), so
  backgrounds, gradients and missing text do not dilute a lighting change;
- `patches`: 5 x 5 means at listed pixels, for the probe scenes.

```
npm install                       # x_ite 16.7.1, babylonjs 9.32.0, playwright 1.63.0 (pinned)
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
