# X3D lighting in EEVEE (import option "X3D Lighting")

Classic X3D materials (`Material`, `TwoSidedMaterial`) and `PhysicalMaterial` can now be lit by X3D 4.0's own equations (ISO/IEC 19775-1:2023: Phong, 17.2.2.5; physical, 17.2.2.6) instead of by Blender's lights. It works in EEVEE through Blender 5.3's Material Lighting nodes. It is **opt-in**, and Cycles keeps the Principled BSDF it always had (the plain fallback).

| Option | What the file's colour numbers are | Who draws it that way (measured) |
|---|---|---|
| Off (default, also what Auto gives without `BLENDER_X3D_LIGHTING`) | the import as before: Principled BSDF lit by Blender's lights | (none) |
| **X3D, linear values (X3DOM)** | linear values: lit as they are, the sum encoded for the display (view transform Standard) | X3DOM 1.8.3 as shipped; X_ITE 16.8.1 with `ColorSpace LINEAR` |
| X3D, display values (X_ITE) | display values: lit as they are and shown as they are (view transform Raw) | X_ITE 16.8.1 as shipped; X3DOM 1.8.3 with `gammaCorrectionDefault none` |
| X3D, sRGB-decoded | sRGB-coded: decoded, lit, encoded | no browser measured |

## What the option makes

- **Per classic material:** a second Material Output targeted at EEVEE, driven by the shared node group **X3D Phong**. The Principled output is re-targeted to Cycles.
  - The group runs once per light (Light Evaluation, Light Accumulation). Each light's X3D fields come from custom properties on the light object, read by the Attribute node in Light mode. `source/x3d_phong.py` lists them.
  - A texture or per-vertex colour that feeds the Principled base colour also feeds X3D's diffuse colour.
- **Per light:** the properties `x3d_phong_kind`, `intensity`, `ambient`, `on`, `color`, `attenuation`, `radius`, `frame`, `axis`, `beam` and `cutoff`.
  - A light without them, such as one you add in Blender, adds nothing to an X3D Phong material.
  - A depsgraph handler keeps `x3d_phong_axis` (the cone direction) up to date when a spot light is turned.
- **The headlight** (NavigationInfo `headlight`, on unless the file turns it off) becomes a sun called "X3D headlight", parented to the first Viewpoint's camera and carrying the same properties.
  - Its energy is 1e-6 W/m². EEVEE leaves a light of energy 0 out of its light loop (measured), and Cycles does not see a microwatt.
  - Neither X3D writer exports it. The file's headlight goes back out through NavigationInfo, as before.
- **The scene's view transform** becomes Standard (Raw for display values), with no look, exposure 0 and gamma 1. Blender's default AgX would tone-map X3D's colours.

## How it was judged (receipt: `tests/lighting/receipts.json`)

**The oracle.** `tools/lighting_oracle.py` is X3D 4.0's equation as plain numpy, evaluated at every pixel centre of a 64 × 64 view of one lit quad. That gives the exact surface point, N and V for every pixel.

**The probes.** Seven probe scenes, one term each, plus the headlight. The headlight probe was added after the first Blender run, outside the committed ladder.

**The limits.** `tests/lighting/limits.json` was committed before any run, in commit `40172db`. The `linear-values` reading and its Blender gate followed in commit `d811367`, after the browser recording and before any Blender run, because both browsers' gamma-correct modes landed on neither of the two readings first written down.

**The witnesses.**
- X_ITE 16.8.1 and X3DOM 1.8.3 (npm, build 7482, 03da6d3870), each in two or three settings, in headless Chromium 158.0.8127.36. WebGL there is ANGLE → Vulkan 1.4.335 → llvmpipe (LLVM 20.1.2). Recorder: `tools/lighting_record.cjs`.
- Blender 5.3.0 (02f0899d78e3), EEVEE with 1 sample and no pixel filter, and Cycles CPU with 64 samples. Recorder: `tools/lighting_blender_record.py`.

**The judge.** `tools/lighting_judge.py` measures |witness − oracle| in 8-bit levels, leaving out pixels next to a radius edge. Each cell below is mean / p99, in the reading the witness lands on (browsers on the pow 2.2 curve they use, Blender on sRGB):

| Witness | lands on | directional | point-attenuation | point-radius | spot | specular | ambient-emissive | two-lights | headlight |
|---|---|---|---|---|---|---|---|---|---|
| X_ITE 16.8.1 as shipped | display | 0.16 / 0.22 | 0.25 / 0.49 | 0.05 / 0.48 | 0.09 / 0.49 | 0.24 / 0.49 | 0.25 / 0.49 | 0.20 / 0.49 | 0.15 / 0.50 |
| X_ITE, Shading PHONG | display | 0.16 / 0.22 | 0.25 / 0.49 | 0.05 / 0.48 | 0.09 / 0.49 | 0.24 / 0.49 | 0.25 / 0.49 | 0.20 / 0.49 | 0.15 / 0.50 |
| X_ITE, PHONG + ColorSpace LINEAR | linear values | 0.25 / 0.35 | 0.25 / 0.49 | 0.05 / 0.48 | 0.09 / 0.49 | 0.24 / 0.49 | 0.25 / 0.49 | 0.20 / 0.49 | 0.16 / 0.49 |
| X3DOM 1.8.3 as shipped | linear values | 0.25 / 0.35 | 0.25 / 0.49 | 0.05 / 0.48 | 0.09 / 0.49 | 0.24 / 0.49 | 0.25 / 0.49 | 0.20 / 0.49 | 0.16 / 0.49 |
| X3DOM, gammaCorrectionDefault none | display | 0.16 / 0.22 | 0.25 / 0.49 | 0.05 / 0.48 | 0.09 / 0.49 | 0.24 / 0.49 | 0.25 / 0.49 | 0.20 / 0.49 | 0.15 / 0.50 |
| **Blender: X3D lighting, linear values** | linear values | 0.23 / 0.37 | 0.25 / 0.51 | 0.06 / 0.49 | 0.09 / 0.50 | 0.25 / 0.51 | 0.25 / 0.53 | 0.20 / 0.52 | 0.16 / 0.52 |
| **Blender: display values** | display | 0.16 / 0.22 | 0.25 / 0.51 | 0.05 / 0.51 | 0.09 / 0.50 | 0.24 / 0.52 | 0.25 / 0.57 | 0.20 / 0.55 | 0.16 / 0.56 |
| **Blender: sRGB-decoded** | sRGB-decoded | 0.21 / 0.43 | 0.25 / 0.51 | 0.05 / 0.49 | 0.09 / 0.49 | 0.25 / 0.51 | 0.25 / 0.52 | 0.24 / 0.52 | 0.25 / 0.52 |
| Blender: default import (off), vs linear values | (none) | 62.77 / 72.75 | 74.43 / 80.79 | 18.32 / 144.69 | 13.12 / 67.95 | 74.72 / 94.11 | 128.95 / 147.45 | 71.44 / 110.55 | 238.53 / 255.00 |
| Blender: Cycles fallback, vs linear values | (none) | 59.77 / 72.75 | 68.39 / 76.38 | 59.79 / 156.00 | 11.45 / 73.83 | 70.27 / 87.35 | 125.98 / 142.25 | 72.52 / 108.36 | 238.53 / 255.00 |

What the table says:
- **Every implementation of X3D's equation is exact.** Attenuation, the radius cut-off, the spot ramp (linear in the angle), Blinn-Phong specular, attenuated ambient and the headlight all land within 8-bit rounding (mean ≤ 0.25, p99 ≤ 0.57) in all three of X_ITE, X3DOM and Blender.
- **Colour space is where they differ.** Of all the lighting maths, only the colour space is left open by the spec: X3D 4.0 17.2.2 and 12 never mention gamma or sRGB, and Don Brutzman wrote on x3d-public on 27 Nov 2020 that the specification is silent about gamma correction. The readings are 47–68 levels apart, so the probes tell them apart without doubt.
- **The two browsers ship different defaults, and each offers the other's default as an option.**
- **The sRGB-decoded reading has no witness.**
- **X_ITE's `Shading GOURAUD` default draws exactly what PHONG draws here** (16.8.1, classic Material).
- **Neither Blender path makes a headlight** without the option (238.5 levels off on the headlight probe).

Max error per witness in each reading, over the seven ladder scenes:

| Witness | display | linear values | sRGB-decoded |
|---|---|---|---|
| X_ITE 16.8.1 as shipped | **0.25** | 67.92 | 47.73 |
| X_ITE, PHONG + ColorSpace LINEAR | 67.92 | **0.25** | 60.05 |
| X3DOM 1.8.3 as shipped | 67.92 | **0.25** | 60.05 |
| X3DOM, gammaCorrectionDefault none | **0.25** | 67.92 | 47.73 |
| Blender: linear values | 68.27 | **0.25** | 60.16 |
| Blender: display values | **0.25** | 68.30 | 46.48 |
| Blender: sRGB-decoded | 46.44 | 60.21 | **0.25** |

### Gates (limits.json as committed)

| Gate | Result | Expected | Note |
|---|---|---|---|
| blender_linear_values | pass | pass | worst: point-attenuation, 0.25 / 0.51 |
| blender_display | pass | pass | worst: ambient-emissive, 0.25 / 0.57 |
| blender_exact (sRGB-decoded) | pass | pass | worst: ambient-emissive, 0.25 / 0.52 |
| browser_agrees, X_ITE | pass | pass | display |
| browser_agrees, X3DOM | pass | pass | linear values |
| expected_fail_cycles_plain | fail | **fail** | Cycles renders the Principled fallback: 65.8 / 107 at worst |
| wrong_twin_default_import | **fail** | pass | see below |
| blender_physical | pass | pass | worst: physical-directional, 0.25 / 0.51 |
| browser_physical, X_ITE | pass | pass | with its two switches (range window, glTF spot) |
| browser_physical, X3DOM | **fail** | pass | X3DOM 1.8.3 has no X3D 4.0 PhysicalMaterial (see PhysicalMaterial) |
| wrong_twin_physical_default | pass | pass | the default import misses by p99 35.7 (spot) |

**The wrong twin failed as written.**
- I wrote the gate against the `linear` (sRGB-decoded) reading, the only gamma-correct reading on the list when it was committed. Against that reading the default import misses spot by a mean of only 4.93 levels (p99 28.8), under the 8 required. Most of that picture is black outside the cone, which dilutes the mean.
- Against `linear-values`, the option's default reading, it misses by 13.1 (spot) and 74.4 (point-attenuation).
- The probes do catch the default import's errors (p99 28.8 to 147). The gate's metric (a mean over the whole picture) was the weak part. It stays failed in the receipt rather than being rewritten after the run.

## Why "linear values" is the option's first reading

The spec leaves the choice open, so this is a choice, written down, with the other readings one option away.

- The lighting equations come from radiometry (Foley, OpenGL). Summing lights is only right on linear values.
- X3D 4.0's PhysicalMaterial and glTF read a colour factor as a linear value. With this reading, a scene that mixes Material and PhysicalMaterial means the same thing by "0.8".
- Two independent implementations draw it identically: X3DOM's default and X_ITE's `LINEAR` mode.
- It is Blender's own model, numbers lit linearly and encoded by the Standard view transform, so it needs no Raw view.
- **Display values** is the classic look most existing X3D content was tuned for, X_ITE's default. Choose it to see a file as X_ITE shows it.

## PhysicalMaterial (X3D 4.0 17.2.2.6)

The same option gives a PhysicalMaterial an EEVEE output with the node group **X3D Physical**. It reads the same light properties as X3D Phong and computes:
- X3D's `on_i × color × attenuation_i × spot_i` (hard radius, Table 17.4's linear spot ramp);
- around glTF 2.0 Appendix B's BRDF: the mix of the dielectric (f0 0.04) and metal BRDFs, GGX, separable Smith;
- E = intensity, divided by d² for a point or spot light (candela), not for a DirectionalLight (lux). Distances are measured in the light's own frame.

PhysicalMaterial colours are linear values in every reading. With the display-values reading (Raw view) a PhysicalMaterial is therefore not drawn as any browser draws it: X_ITE lights it linearly and encodes it while it shows Phong as display values, and one view transform cannot do both.

**The spec.** 17.2.2.6 gives the per-light frame (o_i, attenuation_i, spot_i) and hands the BRDF to glTF. Units are candela and lux, the radius cut-off is hard, Table 17.4 covers every light, and KHR_lights_punctual is not cited. The oracle (`evaluate_physical`) carries four switches for where readers could differ. The spec reading (`SPEC_KNOBS`) and the gates were committed before any PhysicalMaterial run, in `902f39b`.

**One correction to the oracle, made after the X_ITE run.** I first coded the common shortcut `(1 − F) c_diff / π`, with F from the mixed f0. Appendix B as written weights the dielectric's diffuse by its own Fresnel: `(1 − metallic)(1 − F_dielectric) base / π`. The two differ by about 11 % at metallic 0.2 (the spot probe). The oracle now uses Appendix B's form, and the shortcut is the switch `mix: shortcut`. The limits were not changed.

Mean / p99, 8-bit levels (`tests/lighting/receipts.json`, key `physical`):

| Witness | directional | metal | dielectric | spot | radius | closest setting |
|---|---|---|---|---|---|---|
| X_ITE 16.8.1 as shipped | 0.25 / 0.49 | 0.24 / 0.49 | 0.25 / 0.49 | 4.20 / 25.40 | 5.73 / 49.88 | spec reading, but range window (radius) and glTF t² (spot) |
| X_ITE, ColorSpace LINEAR | 0.25 / 0.49 | 0.24 / 0.49 | 0.25 / 0.49 | 4.20 / 25.40 | 5.73 / 49.88 | spec reading, but range window (radius) and glTF t² (spot) |
| X3DOM 1.8.3 as shipped | 135.51 / 164.18 | 220.43 / 246.40 | 92.61 / 134.13 | 52.37 / 192.36 | 26.62 / 151.48 | none within 14 levels |
| X3DOM, fields renamed to X3DOM's | 75.07 / 98.04 | 30.36 / 108.71 | 63.97 / 84.05 | 48.21 / 178.44 | 14.58 / 97.45 | none within 14 levels |
| **Blender: X3D lighting** | 0.25 / 0.51 | 0.25 / 0.50 | 0.25 / 0.50 | 0.10 / 0.50 | 0.05 / 0.47 | the spec reading |
| Blender: X3D lighting, sRGB-decoded reading | 0.25 / 0.51 | 0.25 / 0.50 | 0.25 / 0.50 | 0.10 / 0.50 | 0.05 / 0.47 | the spec reading |
| Blender: default import (off) | 1.43 / 4.72 | 6.86 / 39.00 | 5.80 / 14.39 | 5.14 / 35.72 | 11.26 / 91.39 | none |
| Blender: Cycles fallback | 0.30 / 0.85 | 0.35 / 2.23 | 4.40 / 8.07 | 5.33 / 36.08 | 38.94 / 92.00 | none (Principled BSDF) |

Each cell is the error against the spec reading (browsers on the pow 2.2 curve, Blender on sRGB). With X_ITE's two switches set (range window, glTF spot), X_ITE is 0.05 / 0.47 on radius and 0.09 / 0.48 on spot.

What the table says:
- **X_ITE 16.8.1 matches the spec reading exactly where the spec and glTF agree:** the BRDF, 1/d² on top of X3D's attenuation, and lux for a DirectionalLight.
- **It departs where the spec is clear and glTF differs.** X_ITE's physical shader uses KHR_lights_punctual's range window `clamp(1 − (d/r)⁴)` for the radius, and `t²` in the cosine for the spot (`getRangeAttenuation` and `getSpotAttenuation` in x_ite.js). With those two switches it lands within rounding.
- **X_ITE uses two cone and radius rules.** Its Phong shader follows X3D's hard radius and linear angle ramp.
- **Blender follows the spec** (the flowchart's "browser departs from a clear spec" branch), as the gate says.
- **X3DOM 1.8.3 is no witness here.** Its PhysicalMaterial is its own older node with glTF's field names (`baseColorFactor`, `metallicFactor`, `roughnessFactor`, `emissiveFactor`), so X3D 4.0's fields are ignored and every probe draws white. Even with the fields renamed it is 15–75 levels off. The directional probe is about π times too bright, as if glTF's 1/π were missing.
- **The probes cannot separate the two Smith visibility forms.** They differ by under 0.0001 of a level at these roughnesses, and the metal highlight clips at 255.

## Not covered yet

- **PhysicalMaterial textures** (metallicRoughness, occlusion, normal), **UnlitMaterial, fog, shadows, light scoping** (`global FALSE` lights only their siblings: Blender has light linking, not wired here) and `occlusionTexture`.
- **Back faces:** the probes see front faces only.
- **Textures:** passed through untested. With display values a texture is re-encoded with gamma 1/2.2.
- **Headlight:** with no Viewpoint (no camera) there is none. It stays on the first Viewpoint's camera when you switch cameras.
- **SpotLight defaults by version:** a SpotLight's `beamWidth` and `cutOffAngle` defaults changed in X3D 4.0 (3π/16 and π/2; X3D 3.x and VRML97: π/2 and π/4). The option picks them by the file's `version`. The importer's Blender spot cone still uses the 3.x defaults for every file, and what the browsers do with an X3D 4.0 file that omits them was not measured.

## Rerun

```sh
python tools/lighting_oracle.py --write-fixtures
NODE_PATH=$(npm root -g) node tools/lighting_record.cjs --xite=<x_ite dist> --x3dom=<x3dom 1.8.3 dir> --out=rec/browsers
python tools/lighting_blender_record.py rec/blender
python tools/lighting_judge.py rec/browsers rec/blender > tests/lighting/receipts.json
cd tests && python -m unittest test_x3d_phong_bpy
```
