# X3D export test suite: what you should see

One Blender scene, 194 test cases, 18 zones laid out in a grid 12 m apart. You export it, and three tools check the result:

| tool | proves |
|---|---|
| `validate_x3d_export.py` | the **file** is right (numbers, structure, animation maths, skinning maths) |
| `x3d_browser_check.py` | a **real X3D browser** (X_ITE 16.5.1) loads it without errors, animates it, and shows each zone |
| this document | the plain-English answer key |

> Counts and findings in this document are the original calibration. For the current state of `main` (31 commits later: line
> meshes, shape keys, shadows implemented; AO bug fixed; phantom sphere fixed here) see `SUITE_COMMENTARY.md`.

Calibrated against exporter **X3D Blender I/O v2.6.1** (`hagopjay/x3d-blender-io` @ `a4238a6`), Blender **5.2.2**, X_ITE **16.5.1**.

---

## 1. Run it

```bash
# Blender with the exporter registered (headless, one command; --repo registers <repo>/source as io_scene_x3d)
blender -b --python x3d_test_suite.py -- --out ./out --repo /path/to/x3d-blender-io --export
#   (or in the GUI: run the script, then File > Export > X3D with "Selection Only" OFF, Hierarchy ON,
#    Animation ON, Normals ON, Apply Modifiers ON  ->  out/x3d_suite_main.x3d)

python3 validate_x3d_export.py out --html out/report.html     # exit code 1 if any CORE case fails
python3 x3d_browser_check.py  out --report out/browser_report.html   # needs: pip install playwright
```

Three exports are made, because some behaviours only show with different options:
`main` (X3D 4.0, hierarchy, animation, normals, modifiers applied), `crease` (no normals, flat, triangulated), `x41` (X3D 4.1).
Other flags: `--zones Z04,Z11`, `--stress` (2000 instances + an 80k-face mesh), `--list`.

## 2. How to read a verdict

| tier | meaning | verdicts |
|---|---|---|
| **CORE** (147) | the exporter claims this; failing is a bug | `PASS` / `FAIL` |
| **FIDELITY** (21) | a faithful exporter should do this; failing is a known approximation | `PASS` / `WARN` |
| **ROADMAP** (26) | not implemented yet; `MISSING` is expected | `MISSING` / `NEW` (someone implemented it) |

A `FAIL` or `WARN` prints a one-line reason (what was found vs wanted) and, for the known defects, a `known issue` line pointing at the code.

## 3. Calibration run (the answer to "did it come back a success?")

| | result |
|---|---|
| CORE | **143 / 147** pass. The 4 failures are 2 real exporter bugs (section 6). |
| FIDELITY | 2 pass, **19 warn** (approximations, listed in section 6) |
| ROADMAP | **26 missing** (shaders, material extensions, fog, shape keys ...) |
| X_ITE | loads (290 root nodes, X3D 4.0 Immersive); `SceneTimer` active, 2 s loop; Z13 changes ~34 % of its pixels in 1.1 s; **1 console error**: the `.tga` texture cannot be decoded by a browser (Z06.webformat) |
| Skinning | Blender's deformation reproduced by an LBS emulation on the *exported* joint data to < 2 mm (Z14.pose) |
| Golden GLSL | `reference/glsl_golden.x3d` compiles in X_ITE with no console messages, and a ROUTE drives two shader uniforms |

## 4. What the `.x3d` file must look like (the invariants)

1. **Header**: `<X3D version='4.0' profile='Immersive'>`, X3D 4.0 DOCTYPE, `<component name='Shape' level='2'>` (PhysicalMaterial), `HAnim` component when an armature exists.
2. **Axes**: Blender Z-up becomes X3D Y-up by `Rx(-90°)`: (x, y, z) → (x, z, -y). With Hierarchy ON it is applied **only on top-level Transforms**; child Transforms are local (`parent⁻¹ · world`). Mesh coordinates stay in Blender object space.
3. **Names**: `OB_<object>` Transform, `ME_<mesh>` geometry, `MA_/APP_<material>`, `CA_<camera>`; illegal characters become `_`, a leading digit becomes `_`. All DEFs unique; every USE comes after its DEF.
4. **Reuse**: 13 objects sharing one mesh give one `IndexedFaceSet DEF` + 12 `USE`; shared materials give one `Appearance DEF` + `USE`.
5. **Geometry**: always `IndexedFaceSet`; vertices are split on (position, UV, colour, normal) so one `coordIndex` serves all arrays; loose vertices are dropped; `creaseAngle` π if any face is smooth (or `Normal` when Normals ON).
6. **Materials**: `PhysicalMaterial` with `baseColor`, `metallic`, `roughness`, `emissiveColor`, `transparency`/`alphaMode`; glTF-style maps become `baseTexture`, `normalTexture`, `occlusionRoughnessMetallicTexture`, `emissiveTexture`. A field that is not written takes the **X3D default** (metallic 1, roughness 1), not Blender's.
7. **Lights**: point → `PointLight`, sun → `DirectionalLight`, spot → `SpotLight` (`beamWidth`, `cutOffAngle`, `radius`); `NavigationInfo headlight='false'` because lights exist.
8. **World**: node-tree Background colour × strength → `<Background skyColor>`.
9. **Cameras**: each becomes a `Viewpoint` (identity position inside its Transform, `fieldOfView` across the **smaller** display side).
10. **Animation** (every frame sampled): one `TimeSensor DEF='SceneTimer'` (49 frames @ 24 fps = 2 s, loop); per object a `PositionInterpolator` (`PI_`), `OrientationInterpolator` (`OI_`), scale interpolator (`SI_`) with ROUTEs `fraction_changed → set_fraction` and `value_changed → set_translation / set_rotation / set_scale`. Keyed-but-constant and unanimated objects get none.
11. **HAnim**: one `HAnimHumanoid` per armature (`skeletalConfiguration='BLENDER'`), joint tree = bone tree, `center` = bone head, skin vertices in armature space pooled into one `skinCoord`, weights per joint, per-joint rotation interpolators.
12. **Diagnostics**: skipped or empty objects are explained in `<meta name='info'>` in the head (`Skipped 1 CURVES object(s) ...`, `Reused geometry (DEF/USE)`).

## 5. What the browser should show, zone by zone

Hop with the `CAM_Zxx` viewpoints (viewpoint menu in X_ITE) or run `x3d_browser_check.py` for one PNG per zone. The scene has no environment map, so **metals look dark and plastics look flat**: that is the exporter output, not a failure.

| zone | contents | in the `.x3d` | in X_ITE |
|---|---|---|---|
| Z00 doc | header, world, integrity | invariants 1, 3, 8, 12 | navy sky; one small test cube |
| Z01 prims | 8 primitives, n-gons, concave, degenerate, loose verts, micro/huge scale | exact face counts, bbox, area, winding | correct solids, no inside-out shading. **Today two extra grey spheres appear** (phantom-sphere bug) |
| Z02 shading | flat cube, smooth / flat / mixed spheres, cone | `creaseAngle` 0 or π, or `Normal` | flat objects show facets, smooth ones read as round. The mixed sphere should keep a hard edge but is written with `creaseAngle` π (smooth everywhere) |
| Z03 uv_color | UV seams, no-UV mesh, two UV sets, point and corner vertex colours | `TextureCoordinate` only for the active UV map; `ColorRGBA` iff Blender has colours | UV and colour test quads |
| Z04 mat_pbr | 5 × 5 grid (rows = metallic 0 → 1, columns = roughness), colour extremes, emission, unlit | scalar PBR fields; pure Emission → `UnlitMaterial` | glossy → matte across a row; the high-metallic rows are dark without an environment light |
| Z05 mat_alpha | alpha 0.25 / 0.5 / 1 blended, dithered 0.5, RGBA texture alpha | `transparency`, `solid` | tinted panes over a checker; a hard-edged cut-out is ROADMAP |
| Z06 mat_tex | glTF texture set, wrap, UV scale, PNG/JPG/TGA, packed | `ImageTexture` per slot, no `occlusionTexture` on the decoy | UV test chart, checkers; the normal-map plane looks plain grey; **TGA fails to load** |
| Z07 mat_adv | clearcoat, transmission, sheen ... and non-Principled shaders | scalar fallback only | plain spheres (extensions are ROADMAP) |
| Z08 hier | 5-deep chain, shear, rotation modes, hidden, empties | nested Transforms, exact world matrices | spiral of five cubes; empties draw nothing |
| Z09 instances | 13 shared spheres, 2-slot cube, GN scatter, collection instance | 1 DEF + 12 USE | identical blue spheres; **collection instance missing**; one phantom sphere for the unrealised GN object |
| Z10 modifiers | subsurf, array, mirror, solidify, bevel, triangulate, disabled, boolean | evaluated mesh with Apply Modifiers ON (`main`), base mesh with it OFF (`crease`) | the modified shapes, not the base cubes |
| Z11 lights | point, spot, sun, area (→ DirectionalLight), 10 W vs 100 W | light nodes | five lit balls; 10 W and 100 W look identical (intensity saturates at 1) |
| Z12 cameras | 4 lens / sensor-fit combinations, ortho | `Viewpoint` `fieldOfView` | the tour hops between them; ortho is exported as a perspective Viewpoint |
| Z13 anim | move, spin, scale, ease, orbit, constraint, driver, rigid body, fast spin | interpolators + ROUTEs | everything moves in a 2 s loop; **fast spin aliases** |
| Z14 hanim | 6-bone rig, tube skin | `HAnimHumanoid`, joints, skin weights | T-pose figure; arm, torso and head move |
| Z15 types | text, curves, surface, 8 skipped types | text/curve/surface meshes, `Skipped ...` meta | extruded text and bevelled curve; nothing for skipped types |
| Z16 splats | 4.0 point fallback, 4.1 splats, Inline | `PointSet`, `Inline` | ring of points, a magenta cube from `Inline` |
| Z17 shader_lab | 6 procedural materials | plain `PhysicalMaterial` fallback | grey spheres. Target look: `reference/glsl_golden.x3d` |

## 6. Findings (what the suite found in the exporter)

**Bugs (CORE failures)**

| case | symptom | cause | fix |
|---|---|---|---|
| `Z01.wire.robust`, `Z01.empty.robust`, `Z09.gn.nophantom` | a mesh with no faces (edge-only, empty, unrealised Geometry Nodes) exports a visible grey `<Sphere radius='0.75'>` although the head says "no exportable faces" | `ir.py IRInstance.iter_shapes()` falls back to `object_type == "MESH"` and `emit_x3d40._primitive_geometry_xml()` defaults to Sphere | emit no Shape when `shapes` is empty; keep the primitive hint only for objects that carry an explicit hint |
| `Z06.decoy.ao` | a texture inside a folder named `kaolin` becomes `occlusionTexture` | `material.py _find_labeled_image_node()` does `keyword in lowercased(name + label + image name + filepath)` with the keyword `"ao"` | match whole tokens on name/label/image name only, never the file path |

**Approximations (FIDELITY warnings)**

- **Precision**: coordinates are written with `%.6f`; a 500 nm object (5e-7 m) collapses to 0 (`Z01.micro.precision`). Matters for nanoscale science.
- **Mixed smooth/flat** meshes lose hard edges (`Z02.crease.mixed`).
- **Linked sockets leak defaults**: a texture-fed Principled still writes `metallic=0 roughness=0.5`, which multiplies (kills) the texture (`Z06.factors`). Non-Principled shaders write no metallic/roughness, so X3D's default of 1 applies (`Z07.implicit.metal`).
- **TGA** is copied as-is and no browser decodes it (`Z06.webformat`).
- **Lights**: radius ignores `use_custom_distance` (`Z11.point.range`); intensity saturates at 1 so 10 W = 100 W (`Z11.point.dynamic_range`); `cutOffAngle = 0.481 × spot_size` instead of 0.5 (`Z11.spot.cone`); `beamWidth` ignores `spot_blend` (`Z11.spot.blend`).
- **Cameras**: the first `Viewpoint` in file order wins; `scene.camera` is not bound (`Z12.initial.view`).
- **Animation** samples every frame, so rotation faster than half a turn per frame aliases (`Z13.fastspin`).
- **Unsupported**: collection instances, unrealised GN instances, metaballs, shear in flat mode.

**Roadmap (26 missing)**: GLSL `ComposedShader` (only the legacy 3.3 writer emits shaders), the X_ITE material extension nodes (`Clearcoat`, `Transmission`, `Sheen`, `IOR`, `Specular`, `Anisotropy`, `Iridescence`, `EmissiveStrength`), fog, environment light, shadows, alpha `MASK`, ortho viewpoints, `IndexedLineSet`, shape keys, light/material animation. All of these flip to `NEW` when implemented.

## 7. Triage

1. `FAIL` on a CORE case: read the `x` line (found vs wanted), then the `known issue` line if present. No known-issue line = new regression.
2. Many Z08/Z13 failures together: the axis conversion or the TRS composition order changed; start with `Z08.chain.xf`.
3. Z13 passes but motion looks wrong in X_ITE: check `Z00.integrity.route_targets` and `interp_valid`.
4. Everything passes but X_ITE shows an error: that is what `x3d_browser_check.py` is for (today: the TGA).
5. Re-run one zone while fixing: `validate_x3d_export.py out --only Z06 -v`.

## 8. What was and was not verified

- **Verified**: the real exporter ran headless on the Blender 5.2.2 pip `bpy` wheel; all 3 exports; 194 cases; the validator's own self-test (27 assertions) passes; X_ITE 16.5.1 loaded the main file in headless Chromium (software WebGL) and each zone was photographed and looked at.
- **Calibration honesty**: the first baseline had 9 CORE failures. Two were my expectation errors and three were generator bugs (Python `keyframe_insert` ignores the linear-interpolation preference, so "linear" keys were Bézier; a skinned mesh was parented with a doubled offset; a rigid-body cache was filled out of order). I fixed the suite, not the exporter. The 4 remaining failures were confirmed against the exporter source.
- **Not verified**: Blender's GUI export path and 4.2 LTS; a real GPU (software rendering is slow, ~1 frame/s, so judge shapes, not frame rate); X_ITE's own skinning of the humanoid (checked by emulation on the exported joint data, plus a still image); Windows/macOS.
- Case-by-case answer key: `x3d_case_catalog.md` (generated from the manifest).
