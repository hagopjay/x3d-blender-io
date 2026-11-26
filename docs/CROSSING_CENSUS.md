# Crossing census: which Blender features survive an X3D export (26 Nov 2026)

`tools/crossing_census.py` builds the smallest scene that has each feature, exports it with this add-on (animation on
where the feature moves), reads the X3D back as XML, re-imports it, and gives a verdict: **carried**, **approximated**
(something stands in for it, named in the evidence), **dropped** (nothing in the file carries it) or **error**. Every
check also runs against an empty X3D file and must not answer carried (negative control: 0 failures).

    Blender -b --factory-startup --python tools/crossing_census.py -- --out DIR

Run: Blender 5.3.0, macOS arm64, main 5537e87. **29 probes: 18 carried, 5 approximated, 6 dropped, 0 errors.**
Raw results: `docs/crossing-census-2026-11-26.json`.

| Area | Feature | Verdict | Evidence | Receipt dropped/approximated/clamped |
|---|---|---|---|---|
| geometry | mesh (a cube) | **carried** | IndexedFaceSet, 14 points (8 corners, split at UV seams) | 0/0/0 |
| geometry | smooth shading | **approximated** | creaseAngle [3.141593] | 0/0/0 |
| geometry | subdivision modifier (evaluated) | **carried** | 125 points (cube has 8) | 0/0/0 |
| geometry | UV map | **carried** | TextureCoordinate | 0/0/0 |
| geometry | colour attribute (vertex colours) | **carried** | Color/ColorRGBA | 0/0/0 |
| geometry | linked duplicates (shared mesh) | **carried** | 1 USE | 0/0/0 |
| geometry | parent and child | **carried** | nested Transform | 0/0/0 |
| geometry | Geometry Nodes instances | **carried** | 8 Shape, the instance mesh defined once and 7 USE | 0/0/0 |
| geometry | text object | **approximated** | converted to a mesh | 0/0/0 |
| geometry | bevelled curve | **approximated** | meshed | 0/0/0 |
| geometry | Grease Pencil drawing | **dropped** | nothing in the file | 0/0/0 |
| material | Principled base colour, metallic, roughness | **carried** | baseColor [0.8, 0.3, 0.1] metallic 0.7 roughness 0.25 | 0/0/0 |
| material | emission (strength 5) | **approximated** | emissiveColor [0.2, 0.9, 1.0]: strength folded or clamped to [0, 1] | 0/0/0 |
| material | alpha 0.5 | **carried** | transparency 0.5 | 0/0/0 |
| material | glass transmission | **dropped** | opaque: X3D 4.0 has no transmission | 1/0/0 |
| material | image texture | **carried** | ImageTexture url "census-checker.png" | 0/0/0 |
| material | procedural texture (noise) | **dropped** | flat baseColor 0.800000 0.800000 0.800000 | 0/0/0 |
| animation | keyframed location | **carried** | 1 PositionInterpolator, 2 ROUTE | 0/0/0 |
| animation | keyframed rotation | **carried** | 1 OrientationInterpolator | 0/0/0 |
| animation | keyframed scale | **carried** | 1 ROUTE to scale | 0/0/0 |
| animation | keyframes, exported with the default options | **dropped** | use_animation is off by default: a still | 0/0/0 |
| animation | driver (expression) | **carried** | baked: 1 OrientationInterpolator | 0/0/0 |
| animation | shape key animation | **carried** | 1 CoordinateInterpolator | 0/0/0 |
| animation | shape key moved by a driver | **dropped** | no CoordinateInterpolator: keyed shape keys cross, driven ones do not | 0/0/0 |
| animation | armature (skinned) | **carried** | 1 HAnimHumanoid, 2 joints | 0/0/0 |
| scene | point, sun, spot and area lights | **approximated** | {'PointLight': 1, 'DirectionalLight': 2, 'SpotLight': 1}: the area light became a DirectionalLight | 1/4/3 |
| scene | camera field of view | **carried** | fieldOfView 0.5632, camera angle 0.9500 | 0/0/0 |
| scene | world colour | **carried** | skyColor [0.1, 0.2, 0.4] | 0/0/0 |
| scene | custom property | **dropped** | no Metadata node | 0/0/0 |

## The loss receipt admits the loss in 2 of 11 cases

Every export carries `x3d-blender-io.receipt` in its head. Of the 11 probes that lost or approximated something, the
receipt counted it in 2 (glass transmission, the area light). Grease Pencil, a procedural texture, emission strength,
a driven shape key, keyframes under the default options and a custom property leave a receipt of 0/0/0.

## Heuristics, ranked by what they would carry for the effort

1. **Sample what is evaluated, not what is keyed.** Transforms already cross this way (drivers arrive as baked
   OrientationInterpolators), but shape keys cross only when keyframed: a shape key moved by a driver exports as a
   still. Sampling `key_blocks[i].value` (or the evaluated mesh) per frame, as the transform path does, would carry it.
2. **No silent losses.** Each case in the table above where the receipt reads 0/0/0 should count: a Grease Pencil
   object skipped, a node texture flattened to its default colour, an emission strength above 1, a driven value not
   sampled, a custom property not written. The census can then be a test: every non-carried verdict must move the receipt.
3. **Animation on when the scene moves.** `use_animation` defaults to off, so the first export of an animated scene is
   a still with a 0/0/0 receipt. Defaulting it on when any object has an action or a driver (or counting the skipped
   animation in the receipt) fixes the most common surprise.
4. **Custom properties as metadata.** `MetadataString` / `MetadataDouble` under the object's Transform (or its Shape)
   would carry ids and tags both ways; the importer already reads metadata.
5. **Transmission as an approximation, said out loud.** X3D 4.0's PhysicalMaterial has no transmission; writing
   `transparency` from it (counted as approximated) keeps glass from becoming opaque.
6. **Area lights as SpotLights, not DirectionalLights.** A DirectionalLight loses the light's position and lights the
   whole scene; a SpotLight at the area light's position, pointing the same way with a wide `cutOffAngle`, keeps where
   the light is. (Counted as approximated either way.)
7. **Bake what is procedural, on request.** A node texture can cross as an `ImageTexture` only after a bake to an
   image; an opt-in bake step, with the image beside the file, is the general bridge (the same one Geometry Nodes needs).
8. **Grease Pencil as lines.** Strokes are polylines with colours: `IndexedLineSet` with `Color` would carry a drawing.

Ownership: the exporter (`extract.py`, `emit_x3d40.py`, `ir.py`) belongs to its owner; this census only calls the
operators. Each heuristic above is a proposal with the probe that would prove it.

## Not checked

Only Blender 5.3 on one Mac; one smallest scene per feature (not large or combined scenes); how anything looks (the
checks read the XML, not pixels; the demo `docs/demos/blender-tour/v1` in x3d.demo has the X_ITE pictures); X3D
validity of the exports (`validate.py` was not run here).
