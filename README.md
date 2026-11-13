# X3D Blender I/O — X3D 4.0/4.1 fork of the Web3D X3D/VRML2 add-on

This repository is HagopJay's working fork of the Blender extension
[Web3D X3D/VRML2 format](https://extensions.blender.org/add-ons/web3d-x3d-vrml2-format)
(upstream: [projects.blender.org/extensions/io_scene_x3d](https://projects.blender.org/extensions/io_scene_x3d)).
Its purpose is to bring the exporter and importer up to **X3D 4.0** (ISO/IEC 19775-1:2023)
so Blender can trade physically based scenes with X3D 4 browsers (X_ITE, X3DOM, Castle, FreeWRL)
and with AI tooling built on the Web3D Consortium's validated encodings. Everything upstream
still works unchanged; the new path is opt-in.

**Installs alongside the official extension.** Since 2.6.0 this fork ships under its own extension id
`x3d_blender_io` (name "X3D Blender I/O") instead of upstream's `web3d_x3d_vrml2_format`, so Blender
no longer treats the two as one extension and an upstream update cannot replace it. Both register the
`import_scene.x3d` / `export_scene.x3d` operators, so enable one of them at a time.

## What the fork adds (Milestones 1 to 4: PBR materials, scene structure, animation, HAnim, asset bridge)

Export dialog, **Include** panel, new **X3D Version** selector:

| Option | What you get |
| --- | --- |
| **X3D 3.3 (Material, classic)** — default | The upstream exporter, unchanged: Phong `Material`, lights, cameras, hierarchy, text, curves. |
| **X3D 4.0 (PhysicalMaterial, PBR)** | Principled BSDF → `PhysicalMaterial` (baseColor, metallic, roughness, emissiveColor, transparency, normalScale, occlusionStrength) with glTF-style `baseTexture` / `metallicRoughnessTexture` / `normalTexture` / `emissiveTexture` / `occlusionTexture` children; Emission-only trees → `UnlitMaterial`; `Appearance alphaMode="BLEND|MASK"`; `IndexedFaceSet` with `Coordinate`, `Normal` (when *Normals* is on), `TextureCoordinate` (active UV map) and `ColorRGBA` (active colour attribute); one `Shape` per material slot; `solid` from *Backface Culling*; `creaseAngle` from smooth shading; modifiers and triangulation honoured; shared mesh data and materials written once with `DEF` and reused with `USE`; texture paths follow the *Path Mode* setting exactly as the 3.3 exporter does. Nested `Transform` hierarchy (*Hierarchy* on) or flat world transforms; lights as `PointLight` / `SpotLight` / `DirectionalLight` (headlight off when present); cameras as `Viewpoint`; curves, surfaces and text objects as meshes; world colour as `Background`; optional **Animation** sampling of object transforms over the frame range into one `TimeSensor` with `PositionInterpolator` / `OrientationInterpolator` nodes and `ROUTE`s. Object types the path cannot write yet are listed in `<meta name="info">`. |

| **X3D 4.1 draft (GaussianSplats)** | Everything the 4.0 option writes, plus Gaussian-splat objects as the draft `GaussianSplats` node (component `GaussianSplats` level 1): `positions`, `scales`, `orientations`, `opacities` and the `sphericalHarmonicsDegree*Coef*` arrays. With the 4.0 option the same objects degrade to a coloured `PointSet` and a `<meta name="info">` says so. X_ITE 16.4.3 renders the node, including a 500,000-splat scene written by this exporter. Blender 5.3's native splat PointClouds (what its PLY, SPZ, glTF and USD importers create) export the same way, and on 5.3+ the importer reads the node back into one. |

Import: `PhysicalMaterial` and `UnlitMaterial` now become Principled BSDF node trees
(metallic/roughness texture split into G and B channels, normal map with strength, occlusion kept as a labelled node,
`alphaMode` → *Blended* / *Dithered* with an alpha-cutoff node; an `UnlitMaterial`'s `emissiveTexture` is multiplied by
its `emissiveColor` in a Mix node, as X_ITE draws it; the colour texture's alpha times `1 - transparency` feeds *Alpha*,
with the default `alphaMode` AUTO only when the image has a pixel that is not opaque), `solid` → *Backface Culling*,
and object and mesh names survive the round trip (`OB_` / `ME_` / `MA_` prefixes are stripped).

The X3D 4.0 writer validates its own output: XML well-formedness always, and field types and
ranges through the Web3D `x3d` Python package when it is installed (`pip install x3d`).
The header declares `<component name="Shape" level="2" />` whenever it writes PhysicalMaterial or UnlitMaterial:
X3D 4.0 Table E.2 gives Immersive Shape level 2, but the Table E.3 node list and X3DUOM leave both nodes out, and the
statement is correct under either reading.

### Inline bridge: glTF, Gaussian splats and other X3D files

An **Empty** with a custom property `x3d_inline_url` (for example `parts/wheel.glb`, `cloud.ply`, `room.x3d`) exports as an
`<Inline url=…>` inside its `Transform`; nothing under it is re-exported. On import an `Inline` becomes such an Empty with the
referenced asset loaded underneath it: `.x3d` / `.x3dv` / `.wrl` go through this importer recursively, `.gltf` / `.glb` through
Blender's glTF importer, and `.ply` / `.splat` Gaussian-splat files become splat meshes. The Empty's local frame is Blender's
(Z-up), so the asset sits under it exactly as Blender's own importer would place it; the Inline's `Transform` carries the Y-up
rotation so an X3D browser sees the asset in its native frame. Everything loaded from an Inline is tagged `x3d_inline_source`
and stays behind the reference when the scene is exported again, so a file that inlines other files round-trips as references.

A **splat mesh** is an ordinary mesh with only vertices, the custom property `x3d_gaussian_splats`, and per-point attributes
`splat_scale` (linear, per axis), `splat_rotation` (quaternion), `splat_opacity` (0..1), `splat_sh0_0` (the DC colour
coefficient) and optional `splat_sh1_0` … `splat_sh3_6`; a `Color` attribute carries the reconstructed base colour for the
viewport. `source/splat_io.py` reads and writes the reference 3DGS PLY layout and the 32-byte `.splat` layout without `bpy`,
`tools/splat_fixture.py` builds a test helix. Quaternions are written as `x y z w`, the glTF `KHR_gaussian_splatting` order the
draft node mirrors. The draft text does not state the order; X_ITE 16.4.3 reads `x y z w`, and the same data written
`w x y z` renders as streaks. Blender 5.3's native splat objects are not read yet (that API is still in alpha).

### X3D fields kept as custom properties

Some X3D fields have no Blender setting. The importer keeps them as custom properties, and the X3D 4.0 and 4.1 export
writes them back, so an imported scene keeps them through export (the X3D 3.3 writer does not use them):

| Property | On | Holds | Written back as |
|---|---|---|---|
| `x3d_head_meta` | scene | every `<head>` `meta` name/content pair of the imported file, in order, repeated names such as two `reference` entries included | `meta` after the export's own `generator` and `filename`; a title, creator, description, keywords or licence set in the export dialog replaces the imported one, a dialog reference is added to the imported ones |
| `x3d_background` | scene | the first Background's `skyColor`, `skyAngle`, `groundColor`, `groundAngle` and `transparency` | that Background, in place of one made from the world colour (delete the property to get the world colour back) |
| `x3d_metadata` | object | the Shape's `Metadata*` node: nested `node`, `name`, `reference` and `value` (the field's X3D text, or the member list of a MetadataSet) | the `metadata` field of the object's first Shape |
| `x3d_viewpoint_description` | camera object | the Viewpoint `description` | `description` (the camera name when there is none) |
| `x3d_ambient_intensity`, `x3d_shadow_intensity` | light data | the light's `ambientIntensity` and `shadowIntensity` | the same fields |
| `x3d_intensity` | light data | the light's `intensity` in the file; it marks the light as imported | nothing by itself: the light's energy is written as `intensity` without the cap at 1 that lights made in Blender get |
| `x3d_attenuation` | light data | a point or spot light's `attenuation`, when the file sets it | `attenuation` (also by the X3D 3.3 writer) |
| `x3d_energy_per_intensity` | light data | Blender energy per unit of intensity, set by an import in **X_ITE** light units (below) | the divisor that turns the energy back into `intensity` (also in the X3D 3.3 writer); without it, 1.75 for point and spot lights and 1 for a sun |
| `x3d_radius` | light data | a point or spot light's `radius` as the file set it (-1 for unlimited), in Blender units of the light's own frame | `radius` (also by the X3D 3.3 writer); Blender's cutoff distance holds the world-space glTF range |
| `x3d_color` | light data | a light's `color` as the file gave it, when an import with Colour Space **sRGB** read a classic scene's light colour as sRGB and made the Blender colour linear (whatever the Light Units) | `color` in the X3D 3.3 writer under Colour Space **sRGB**, while the Blender colour is unchanged (an edited colour is written sRGB-encoded); the X3D 4.0 writer, whose PhysicalMaterials X_ITE lights in linear space, and **As Is** write the Blender colour |
| `x3d_reference_distance` | light data | the distance (m) at which an **X_ITE**-units import anchors a point or spot light's falloff | nothing |
| `x3d_lighting_model`, `x3d_headlight_lux` | scene | from an **X_ITE**-units import: `physical` when any lit shape has a PhysicalMaterial, else `classic`, and the lux an X3D headlight (a DirectionalLight of 1 along the view) should get in a glTF viewer (fitted with the other lights below; 1 for a physical scene) | nothing |
| `x3d_color_space` | scene | the import's Colour Space, `AS_IS` or `SRGB` | nothing by itself: an export with Colour Space **Auto** writes colours back the same way (below) |

Two fields map onto Blender settings instead: a light's `shadows` (X3D default `false`) is its *Cast Shadow* switch, and a
Shape's `castShadow` is the object's shadow visibility. A light imported from X3D keeps an `intensity` above 1 on the
X3D 4.0 path, whose schema sets no upper limit. A light made in Blender is still capped at 1 (1.75 W for point and spot
lights, strength 1 for a sun): watts have no fixed X3D scale and the writer emits no attenuation, so Blender's default
1000 W point light would otherwise white out the scene. The X3D 3.3 writer caps every light at 1, as the 3.x schemas require.

### Colour space

X_ITE 16.7.1 reads a colour in one of two ways (measured in headless Chrome 153, SwiftShader):

| Colour | X_ITE reads it | 0.5 draws |
|---|---|---|
| `Material`, `TwoSidedMaterial`, `UnlitMaterial` colours | display space (sRGB values) | 128 |
| a `Color` node under those materials | display space, in place of the material colour | 128 |
| `PhysicalMaterial` colours | linear (glTF) | `baseColor` 0.5 under a light of 1: 110; `emissiveColor` 0.5: 187 |
| a `Color` node under `PhysicalMaterial` | a linear factor on `baseColor` | a Color of 0.5 on a `baseColor` of 1: 110, as a `baseColor` of 0.5 |

Castle Game Engine reads them the same way (its 5.3.0 tools on Mesa llvmpipe drew the same 128, 186 and 108 to 110,
Nov 2026), so two independent X3D engines agree.

Blender holds linear colours. The import's **Colour Space** decides how the classic colours come in: **sRGB, as X_ITE
draws** (the default) converts them to linear, so Blender and glTF viewers show what X_ITE shows; **As Is** keeps the
numbers. A `Color`
node is converted to linear under the classic materials and kept as it is under `PhysicalMaterial`, in either mode, and it
becomes the mesh's active colour attribute, so the exports write it again.

The export's **Colour Space** writes them back. **Auto** (the default) uses the colour space the scene was imported with
(`x3d_color_space`), else the `BLENDER_X3D_COLOR_SPACE` environment variable, else sRGB. Under **sRGB** the X3D 3.3
writer sRGB-encodes a Material's `diffuseColor`, `specularColor` and `emissiveColor`, and the X3D 4.0 writer an
`UnlitMaterial`'s `emissiveColor`; `PhysicalMaterial` colours are always written linear. A light's `color` goes the
same way: sRGB-encoded by the X3D 3.3 writer under sRGB (the file's value while the colour is unchanged, `x3d_color`; as is
when no exported mesh has a material, since such a file re-imports as a physical scene),
linear by the X3D 4.0 writer, which X_ITE lights with the PhysicalMaterials it writes. So an import and export with
the same colour space give the file's numbers back, and a material made in Blender exported under sRGB shows in X_ITE
as Blender renders it.

### Light units

X3D gives a light an `intensity`, not watts or candela, and X_ITE 16.7.1 draws it two ways: a `PhysicalMaterial` is lit
the glTF way (falloff 1/d² times the X3D `attenuation`, the colour over pi, in linear space), a `Material` or
`TwoSidedMaterial` the classic way (only the X3D `attenuation`, so the default `1 0 0` does not fall off at all, in
display space). Blender, glTF, Babylon.js and Unreal light every surface the first way. The import option
**Light Units** (`light_units`) picks the mapping:

| Light Units | DirectionalLight (sun, lux) | PointLight, SpotLight (COMPAT glTF candela; Blender watts = 4 pi cd) |
|---|---|---|
| **Blender** (`BLENDER`) | `i` | `1.75 i / 4 pi` = 0.139 `i` (the exporters' round trip) |
| **As X_ITE draws** (`X_ITE`), physical scene | `i` | `i · att(d / s) · s²`: exact at every distance for `attenuation 1 0 0` |
| **As X_ITE draws** (`X_ITE`), classic scene | `f · i` | `f · i · att(d / s) · d² / w(d)` |

`s` is the light's frame: the Blender length of one unit of its X3D coordinate system (the file unit times its
Transforms' scale). X_ITE measures a light's distances, `attenuation` and `radius` in that frame, so a centimetre file
or a scaled Transform lights the same in both. `att(x) = 1 / max(a0 + a1 x + a2 x², 1)`. `d` is the light's reference
distance, where its 1/d² falloff is anchored: the median distance from the light to the shapes it reaches (within its
`radius`, inside a spot light's cone), taken to a shape's bounding-box centre, or to the nearest point of its box when
the light is within its bounding sphere (a light above a large floor). A shape whose box holds the light (a bulb around
it, the room it hangs in) counts only when nothing else is in reach, and a black, emissive-only shape not at all; 1 m
when the light reaches nothing. Every USE of a shape counts, and an Inlined glTF counts as PhysicalMaterial, as X_ITE
draws it. `w(d) = clamp(1 - (d / r)⁴, 0, 1)²` (at least 0.1) is the range window Babylon.js 9.32 draws a glTF `range`
with (it squares the window KHR_lights_punctual recommends, which X_ITE applies to PhysicalMaterial); X_ITE cuts classic
Materials off hard at the radius, so a classic light makes up for it.

A classic scene has no exact glTF match. X_ITE shades it in display space: `emissiveColor + diffuseColor · L`, where
`L` adds up each light's `intensity · color · att · cos · spot` (and the headlight's `cos`) as sRGB values, with no
falloff but the `attenuation`; X_ITE's classic spot factor falls off linearly in the angle from `beamWidth` to
`cutOffAngle`, a glTF viewer's as the square of a ramp in its cosine. A glTF viewer adds linear light that falls off as
1/d². So the import fits the classic lights to what X_ITE draws where it matters, on the surfaces the first Viewpoint
sees: it casts a 64 × 64 grid of rays over that view (X3D's default view when the file has none; a Transform's scale
on the Viewpoint changes neither the view nor the headlight), and at each surface a ray meets first, per colour channel,
compares X_ITE's `min(e + b · L, 1)` (`e` and `b` the sRGB emissive and diffuse colours) with what the glTF lights draw
there, `srgb(min(E + B · lux / pi, 1))` (`E` and `B` the linear colours Blender renders with). Each light's factor
`f` makes the mean difference least: first one factor for every light (so the lights keep their ratios), then each
light's own factor by least squares near the display, pulled towards the shared one and kept only when it draws closer
(a light no face in view sees keeps the shared one). Where X_ITE clips to white, the dimmest factor that reaches white
wins. Hidden faces, lines, text and emissive-only shapes do not count. On one face lit at level `S` this is
`f = pi · lin(a · S) / (A · S)` for an sRGB albedo `a` (`A = lin(a)`, or `a` when the colours were imported As Is),
which is also the fallback when nothing lit is in view (`a` the median albedo, `S` what the lights give at their
reference distances). Read as sRGB, a classic scene's light `color` becomes linear in Blender too, as its Material
colours do (the file's value is kept in `x3d_color` for the X3D 3.3
export). A scene is classic when its lit shapes have a
`Material` or `TwoSidedMaterial` and none has a `PhysicalMaterial`: classic units would light a PhysicalMaterial
several times too bright (a key light of 2.4 gave a gold sphere 23.9 lux and blew it out), while a classic surface lit
physically is only darker.

In **X_ITE** units the light's `radius · s` becomes its glTF `range`; a `radius` of -1 (unlimited in X_ITE) or 0 leaves
it without one, since glTF has no range 0. X_ITE lights nothing with a `radius` of 0 (a face only when its distance is
at most the radius, or the radius is negative), so such a light gets energy 0 (its scale is kept, as for a light that
starts dark) and leaves the fit of the others alone. A SpotLight's `beamWidth` becomes Blender's and glTF's inner cone
(`spot_blend = 1 - beamWidth / cutOffAngle`, 0 for X3D's hard edge when `beamWidth >= cutOffAngle`), as X_ITE falls off
between the two. **Auto**, the default, reads the `BLENDER_X3D_LIGHT_UNITS` environment variable, else follows the
Colour Space: **X_ITE** with **sRGB, as X_ITE draws** (the default), **Blender** with **As Is**. The X3D export writes the
file's `intensity`, `color` (the X3D 3.3 writer; the X3D 4.0 writer writes it linear, see Colour Space above),
`attenuation`, `radius`, `beamWidth` and `cutOffAngle` back with either units. A round trip
that starts in Blender (export, then import) keeps its light energies only with Light Units **Blender**; by default the
import draws the file's intensities as X_ITE does.

Measured on 12 Nov 2026, X_ITE 16.7.1 on the X3D against Babylon.js 9.32.0 on the glb (Blender 5.3, COMPAT light units),
headless Chrome 153 with SwiftShader, centre of a 0.8 grey patch, 0-255:

| Probe | X_ITE | Blender units | X_ITE units |
|---|---|---|---|
| classic Material, DirectionalLight 1 | 204 | 120 | 203 |
| PhysicalMaterial, DirectionalLight 0.3 | 78 | 78 | 78 |
| PhysicalMaterial, PointLight 1 at 2 m | 74 | 30 | 74 |
| PhysicalMaterial, PointLight 1, attenuation `1 0 0.2` | 57 | 30 | 56 |
| classic Material, PointLight 1 at 2 m | 204 | 27 | 203 |

Nine x3d.demo scenes with lights, mean |delta| (0-255) over the glb's geometry, all on the same rig
(`tools/fidelity_rig`, colour space sRGB). Blender units are the importer's old scale; *first X_ITE units* is the first
version of these units (one curve per light from the scene's median albedo, PR #28):

| Scene | lights | Blender units | first X_ITE units | X_ITE units |
|---|---|---|---|---|
| gobbler-worlds-within materials shelf | 3 SpotLight + sun, 11 PhysicalMaterial | 37.3 | 14.2 | **13.7** |
| ontology constellation | PointLight 1.2 + headlight, 151 Material | 40.5 | 28.5 | **25.3** |
| blender-x3d-io lights-after | PointLight + sun, PhysicalMaterial | 1.2 | 0.12 | 0.12 |
| blender-x3d-io annotation | 2 suns, 2 PointLights, Material | 22.6 | 21.9 | **14.8** |
| blender-x3d-io profile tables | same rig, one PhysicalMaterial | 14.4 | 14.3 | 14.3 |
| blender-x3d-io still life | 3 suns, PhysicalMaterial | 0.41 | 0.41 | 0.41 |
| blender-x3d-io repair-2 | PointLight, PhysicalMaterial | 17.0 | 17.2 | 17.2 |
| blender-x3d-io NURBS weights | 2 suns, 2 PointLights, Material | 18.4 | 24.1 | **15.6** |
| blender-x3d-io quaternion | 2 suns, 2 PointLights, Material | 19.0 | 24.2 | **17.0** |

What a glTF light cannot copy: a classic scene's point lights fall off as 1/d², so a surface nearer or further than the
fitted ones is lit more or less than in X_ITE; X_ITE's display-space Lambert makes oblique light darker than a linear one
(a 0.8 grey at 58° from a classic point light: 109 in X_ITE, 167 in Babylon.js); the sRGB toe makes very dark albedos
(below about 0.04) brighter than X_ITE draws them; and X_ITE's shadows (`shadows` on a light) and classic specular
highlights are not carried by the glb. The X3D headlight is not imported; `x3d_headlight_lux` says what a viewer should
give it.

An X3D `Switch` imports every child, so nothing is lost, but shows only the one its `whichChoice` names, as an X3D
browser does: the others are hidden in the viewport and the render and tagged `x3d_switch_hidden` (-1, the default,
shows none). The export does not write a Switch back yet: by default it writes every child as a sibling, and with
*Visible Only* only the chosen one.

### Tests

```
cd tests
python -m unittest test_emit_x3d40 test_parse_x3d40 test_material_analysis   # no Blender needed
python -m unittest test_roundtrip_bpy   # needs Blender's `bpy` module (pip install bpy) or run inside Blender
```

Armatures export as **HAnim 2.0**: each armature becomes an `HAnimHumanoid` (inside its object Transform), every bone an `HAnimJoint` nested like the bone hierarchy with `center` at the bone head, meshes deformed by the armature (Armature modifier or armature parenting) become `skin` Shapes sharing one `skinCoord` Coordinate in armature space, and vertex groups become `skinCoordIndex` / `skinCoordWeight`. With *Animation* on, posed bones get `OrientationInterpolator` (and `PositionInterpolator` for translated bones) nodes routed to the joints' `set_rotation` / `set_translation`, computed relative to the rest pose so the skin follows exactly. `tools/hanim_fixture.py` builds the two-bone test arm. Importing HAnim goes the other way: an `HAnimHumanoid` becomes an armature (each `HAnimJoint` a bone whose head sits at the joint `center`, tail toward its children), `skin` Shapes become meshes parented to the armature with an Armature modifier and one vertex group per joint from `skinCoordIndex` / `skinCoordWeight` (coincident skin points with identical weights are welded back into one vertex), and `OrientationInterpolator` / `PositionInterpolator` ROUTEs into joints become pose-bone keyframes, so a rigged, animated arm round-trips.

`tools/scene_fixture.py` builds a parented cube, three lights, a camera, a text object and a keyframed cube; its round-trip test checks nesting, light types, viewpoint, text geometry, interpolators and ROUTEs, and that everything lands back in world space on import. On import, XML `ROUTE` chains (TimeSensor → PositionInterpolator / OrientationInterpolator / scale → Transform) become linear keyframes on every object under the animated Transform, in world space, so animated files round-trip; the TimeSensor `loop` flag is not turned into a cycle modifier.

`tools/swatch_book.py` builds the seven-swatch fixture scene (dielectric, metal, glass, unlit, textured,
two-material smooth sphere with vertex colours, shared-mesh cubes) that the round-trip test exports,
validates, and reimports. Verified on Blender 5.2 (`bpy` wheel). Blender 4.2 is the minimum.

### Architecture of the 4.0 path

`extract.py` (Blender → IR) → `ir.py` (plain dataclasses, no `bpy`) → `emit_x3d40.py` (IR → XML) → `validate.py`.
The legacy exporter is untouched; `export_pipeline.py` chooses the writer from the version option.
Planning notes live in `docs/planning/`.

## Upstream README


## Features & Documentation
see [Web3D X3D/VRML2 Documentation](https://projects.blender.org/extensions/io_scene_x3d/wiki)

### Import file formats
- .x3d
- .x3dz
- .x3dv
- .wrl

### Export file formats
- .x3d
- .x3dz (compression enabled)

## Guides

This add-on was part of [Blender 4.1 bundled add-ons](https://docs.blender.org/manual/en/4.1/addons/). This is now available as an extension on the [Extensions platform](https://extensions.blender.org/add-ons/web3d-x3d-vrml2-format).

To build a new version of the extension:
* `<path_to_blender.exe> --command extension build --source-dir=./source --output-dir=./output`

For more information about building extensions refer to the [documentation](https://docs.blender.org/manual/en/4.2/advanced/extensions/index.html).

## Contribute

This add-on is offered as it is and maintained by @Bujus_Krachus and the community, no support expected.

Contributions in form of [bug reports/feature requests](https://projects.blender.org/extensions/io_scene_x3d/issues), bug fixes, improvements, new features, etc. are always welcome as I don't have the time to do or know it all.

Code contributions:
- fork the repository, do your changes and create a Pull-Request to https://projects.blender.org/extensions/io_scene_x3d/src/branch/main. 
- It is best practice to keep the fork up-to-date with the main repo, follow the guidelines in ["Step-by-Step Workflow for merging two repos"](https://projects.blender.org/extensions/io_scene_x3d/issues/42) to do so.
- Describe as detailed as possible what this PR does and why it's good to have. Ideally include sample files for testing and demonstrating. Also make sure, that a merge of the PR does not break other features. 
- Code contributions by contributors with write permissions can also be done directly on the main branch of the main repo or for larger changes on a seperate branch inside the main repo.
- Pull Requests shall be created as early as possible as a WIP PR. Communication regarding the implemenation will happen there.

Checklist for PRs to get accpeted:
- The code follows the general python guidelines as much as possible: [Pep-8](https://peps.python.org/pep-0008/)
- The code shall be well documented, use docstrings where possible, add comments if needed and add as much details as possible to the PR message.
- Dead/commented out code shall be avoided or documented on when it shall be uncommented.
- Simplify the code. This improves readability and can imporve performance as well.
- The code has to be well tested, it should throw no python errors and work under different circumstances. Other code parts shall not break.
- Known limitations and future tasks should get mentioned.
- The newest blender version should work with the suggested changes. If a eralier version (4.2+) breaks, document it.
- And last but not least: keep the users in mind. As engineers we tend to overcomplicate, keep it simple, keep it straight-forward.

Fellow active maintainers are also always very welcome. If you're interested, reach out.

Releases will happen regularly after some code changes are done. We try to follow semantic versioning as much as possible.

Original authors: Campbell Barton, Bart, Bastien Montagne, Seva Alekseyev

## Specifications
For deeper understanding of both file formats supported by this extension, refer to:
- [VRML (.wrl)](https://graphcomp.com/info/specs/sgi/vrml/)
- [X3D (.x3d)](https://www.web3d.org/specifications/) and [X3D V3.3(.x3d)](https://www.web3d.org/documents/specifications/19775-1/V3.3/index.html)
- [TODO: X3D V4.0](https://www.web3d.org/documents/specifications/19775-1/V4.0/index.html)

Comparison software:
- [FreeWRL](https://freewrl.sourceforge.io/)
- [x3dom](https://www.x3dom.org/)
- [x_ite](https://create3000.github.io/x_ite/)
- [Castle Engine/Castle Model Viewer](https://castle-engine.io/castle-model-viewer) by @Michalis-Kamburelis

## Test Files
- [Import: Demo Files by Web3D Consortium](https://www.web3d.org/x3d/content/examples/Basic/index.html)
- [Import: Castle Engine Demo Models - X3D/VRML folder by Michalis-Kamburelis](https://castle-engine.io/demo_models.php)
- [Export: Blender Tests by Michalis-Kamburelis](https://github.com/michaliskambi/x3d-tests/tree/master/blender_tests)
- Export: TODO

## License
[GPL-3.0](LICENSE.txt)
