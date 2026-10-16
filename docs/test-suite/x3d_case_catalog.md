# X3D test-suite catalogue (suite 2.0.0, 194 cases)

Tier: **CORE** = the exporter claims it, failure is a bug; **FIDELITY** = a faithful exporter should do it, failure is a known approximation; **ROADMAP** = not implemented yet, `MISSING` is the expected state.

## Z00 doc - Document, header, world and integrity

| case | tier | what a correct export looks like |
|---|---|---|
| `Z00.header` | CORE | **X3D 4.0 document header**. A well-formed XML file whose root is <X3D version='4.0' profile='Immersive'> with the X3D 4.0 DOCTYPE and a <head> that declares component Shape level 2 (PhysicalMaterial needs it) and a generator <meta>. |
| `Z00.header41` | CORE | **X3D 4.1 draft document header** *(profile x41)*. Same file written with version 4.1: root version='4.1' and the 4.1 DOCTYPE. |
| `Z00.navinfo` | CORE | **NavigationInfo mirrors the scene lighting**. The scene contains Blender lights, so NavigationInfo must switch the headlight OFF (headlight='false') or the scene would be double-lit; navigation type lists EXAMINE. |
| `Z00.background` | CORE | **World colour becomes Background skyColor**. The world's Background node colour x strength (0.10 0.20 0.40 x 0.5) appears as <Background skyColor='0.05 0.1 0.2'>.  A decoy 'viewport colour' is set on the world to a different value to prove the exporter reads the node tree. |
| `Z00.diag.reuse` | CORE | **Geometry reuse is reported in the head**. Because many objects share a mesh, a <meta name='info'> says 'Reused geometry (DEF/USE)'. |
| `Z00.integrity.xml_wellformed` | CORE | **File parses as XML**. No XML syntax errors, no duplicated attributes, UTF-8. |
| `Z00.integrity.def_unique` | CORE | **Every DEF is unique**. No two nodes share a DEF name (X3D requires scene-wide uniqueness). |
| `Z00.integrity.use_resolves` | CORE | **Every USE resolves to an earlier DEF**. Each USE='x' names a DEF that appears EARLIER in document order (X3D forbids forward references). |
| `Z00.integrity.route_targets` | CORE | **Every ROUTE endpoint exists**. Each ROUTE fromNode/toNode names a DEF'd node and the fields are valid for those node types (fraction_changed -> set_fraction, value_changed -> set_translation/set_rotation/set_scale). |
| `Z00.integrity.numbers_finite` | CORE | **No NaN/Inf/overflow in any numeric attribute**. Every numeric attribute parses as a finite float. |
| `Z00.integrity.coordindex_valid` | CORE | **All IndexedFaceSet indices are in range**. Every coordIndex entry is -1 or a valid index into its Coordinate (or the shared skinCoord); every face has >= 3 vertices; TextureCoordinate / Normal / ColorRGBA arrays, when present, have exactly one entry per Coordinate. |
| `Z00.integrity.interp_valid` | CORE | **Interpolators are well-formed**. key is strictly increasing within [0,1] and len(keyValue) == len(key) x width. |
| `Z00.integrity.sfcolor_range` | CORE | **All SFColor values are within [0,1]**. baseColor / emissiveColor / light color etc. never exceed 1 (the X3D 4.0 XSD enforces this). |
| `Z00.world.fog` | ROADMAP | **Mist / world fog -> Fog node**. Blender's Mist pass distance maps to an X3D <Fog visibilityRange=...>.  NOT implemented in the exporter at HEAD; expect MISSING until someone adds it. |
| `Z00.world.hdri` | ROADMAP | **World environment -> EnvironmentLight / Background textures**. An HDRI-lit world should become an <EnvironmentLight> (needed for any PBR metal to look right in X_ITE).  Not implemented: only a flat skyColor is written. |

## Z01 prims - Geometry: primitives, topology and robustness

| case | tier | what a correct export looks like |
|---|---|---|
| `Z01.cube.geometry` | CORE | **cube: faces, vertices, bounds and winding**. One IndexedFaceSet with exactly 6 faces (8 distinct vertex positions); local bounds match Blender's; for convex solids every face winds counter-clockwise seen from outside.  Browser: the solid looks correct and evenly lit, no inside-out shading. |
| `Z01.uvsphere.geometry` | CORE | **uvsphere: faces, vertices, bounds and winding**. One IndexedFaceSet with exactly 128 faces (114 distinct vertex positions); local bounds match Blender's; for convex solids every face winds counter-clockwise seen from outside.  Browser: the solid looks correct and evenly lit, no inside-out shading. |
| `Z01.icosphere.geometry` | CORE | **icosphere: faces, vertices, bounds and winding**. One IndexedFaceSet with exactly 80 faces (42 distinct vertex positions); local bounds match Blender's; for convex solids every face winds counter-clockwise seen from outside.  Browser: the solid looks correct and evenly lit, no inside-out shading. |
| `Z01.cylinder.geometry` | CORE | **cylinder: faces, vertices, bounds and winding**. One IndexedFaceSet with exactly 26 faces (48 distinct vertex positions); local bounds match Blender's; for convex solids every face winds counter-clockwise seen from outside.  Browser: the solid looks correct and evenly lit, no inside-out shading. |
| `Z01.cone.geometry` | CORE | **cone: faces, vertices, bounds and winding**. One IndexedFaceSet with exactly 25 faces (25 distinct vertex positions); local bounds match Blender's; for convex solids every face winds counter-clockwise seen from outside.  Browser: the solid looks correct and evenly lit, no inside-out shading. |
| `Z01.torus.geometry` | CORE | **torus: faces, vertices, bounds and winding**. One IndexedFaceSet with exactly 288 faces (288 distinct vertex positions); local bounds match Blender's; for convex solids every face winds counter-clockwise seen from outside.  Browser: the solid looks correct and evenly lit, no inside-out shading. |
| `Z01.monkey.geometry` | CORE | **monkey: faces, vertices, bounds and winding**. One IndexedFaceSet with exactly 500 faces (505 distinct vertex positions); local bounds match Blender's; for convex solids every face winds counter-clockwise seen from outside.  Browser: the solid looks correct and evenly lit, no inside-out shading. |
| `Z01.grid.geometry` | CORE | **grid: faces, vertices, bounds and winding**. One IndexedFaceSet with exactly 25 faces (36 distinct vertex positions); local bounds match Blender's; for convex solids every face winds counter-clockwise seen from outside.  Browser: the solid looks correct and evenly lit, no inside-out shading. |
| `Z01.ngon12.geometry` | CORE | **12-sided n-gon is written as ONE face**. A single 12-vertex face (X3D IndexedFaceSet supports n-gons natively), not a fan of triangles. |
| `Z01.ngon12.triangulated` | CORE | **12-gon with 'Triangulate' on becomes 10 triangles** *(profile crease)*. Export option Triangulate: the n-gon turns into 10 triangles. |
| `Z01.concave.geometry` | CORE | **Concave L-shaped polygon survives**. One 6-vertex concave face; X_ITE tessellates it, so the L renders as an L (not a filled convex hull). |
| `Z01.concave.triangulated` | CORE | **Concave polygon triangulated with Blender's tessellator** *(profile crease)*. With Triangulate on, 4 triangles cover the L exactly (area preserved). |
| `Z01.tri.geometry` | CORE | **A single triangle**. One 3-vertex face. |
| `Z01.wire.robust` | CORE | **Edge-only mesh is handled gracefully**. No crash.  The object keeps its Transform but has no Shape; a head <meta name='info'> explains "Object 'Z01_wire' has no exportable faces."  Browser: nothing visible (X3D has no wireframe geometry without IndexedLineSet). |
| `Z01.wire.lines` | ROADMAP | **Edge-only mesh -> IndexedLineSet**. A faithful exporter would write loose edges as <IndexedLineSet> (useful for scientific wireframes, graphs, streamlines).  Not implemented. |
| `Z01.empty.robust` | CORE | **Mesh with zero vertices**. No crash; Transform without Shape. |
| `Z01.loose.geometry` | CORE | **Loose vertices are ignored, the quad is kept**. Only the quad's 4 vertex positions appear; the two stray vertices at (3,3,3) and (-4,-4,-4) must NOT inflate the bounds. |
| `Z01.degenerate.geometry` | CORE | **Zero-area faces do not break indexing**. Two degenerate triangles (collinear / coincident corners) are exported verbatim; indices stay valid. |
| `Z01.micro.precision` | FIDELITY | **Sub-micron geometry keeps its size (nanoscale science)**. A 0.5 micrometre cube (half-extent 2.5e-7 m).  The exporter prints coordinates with 6 decimals, so vertices collapse to 0.000000 and the cube degenerates unless the artist rescales.  Expectation: bbox within 5% of the original. |
| `Z01.macro.range` | CORE | **Planet-scale geometry prints without exponents**. A 5000 km cube (half-extent 2.5e6 m): numbers are written as plain decimals (no '1e+06'), bounds preserved. |
| `Z01.flipped.winding` | CORE | **Inside-out mesh keeps its (inverted) winding**. Faces wound clockwise-from-outside must be exported unchanged (no silent re-orientation); the validator sees every face normal pointing INTO the body. |
| `Z01.solid.culling` | CORE | **Backface culling -> solid**. Material with 'Backface Culling' ON gives an IndexedFaceSet without solid='false' (X3D default solid=true -> back faces culled); materials without it get solid='false' (two-sided). |

## Z02 shading - Normals, smoothing and creaseAngle

| case | tier | what a correct export looks like |
|---|---|---|
| `Z02.flat.normals` | CORE | **Flat cube: one normal per corner, axis-aligned, unit length**. <Normal vector=...> present with one unit vector per Coordinate; each is +/-X, +/-Y or +/-Z; no creaseAngle. |
| `Z02.smooth.normals` | CORE | **Smooth sphere: interpolated normals pointing away from the centre**. Normals are unit length and (for a sphere centred at the origin) parallel to their vertex positions; browser: smooth shading, no faceting. |
| `Z02.custom.normals` | CORE | **Custom split normals are exported (Blender 4.1+)**. All normals equal (0,0,1) although the sphere is smooth: browser shows a sphere lit like a flat disc (top bright, uniformly shaded). |
| `Z02.xform.normals` | CORE | **Normals stay in object space under rotation and negative scale**. Normals are written in local space; the Transform (rotation + mirrored X scale) carries the rest.  Radial test on the cone's rim: still consistent with positions in local space. |
| `Z02.crease.flat` | CORE | **Without explicit normals a flat mesh has creaseAngle 0** *(profile crease)*. Export option 'Normals' OFF: smooth/flat intent is carried by creaseAngle.  Flat cube -> attribute absent (default 0). |
| `Z02.crease.smooth` | CORE | **Without explicit normals a smooth mesh has creaseAngle pi** *(profile crease)*. Smooth sphere -> creaseAngle='3.141593' (full smoothing).  Browser computes the normals itself. |
| `Z02.crease.mixed` | FIDELITY | **Mixed smooth/flat sphere keeps its hard edge** *(profile crease)*. A sphere whose northern half is smooth and southern half flat.  creaseAngle is per-geometry, so the exporter has to choose one value: it picks pi (smooth) as soon as ANY face is smooth, which silently smooths the flat half.  Faithful export = explicit normals (main profile does this correctly) or splitting by smoothing group. |
| `Z02.mixed.normals` | CORE | **With explicit normals the mixed sphere is exact**. Main profile: normals preserve the hard edge between the smooth upper and flat lower hemisphere (more distinct normals than a purely smooth sphere would give at the equator seam). |

## Z03 uv_color - UV sets, seams and vertex colours

| case | tier | what a correct export looks like |
|---|---|---|
| `Z03.seams` | CORE | **UV seams split vertices, arrays stay parallel**. The cube's cross-shaped UV unwrap needs more than 8 Coordinates (vertices are duplicated along seams); TextureCoordinate has exactly as many entries as Coordinate; coordIndex indexes all of them. |
| `Z03.nouv` | CORE | **Mesh without UVs: no TextureCoordinate node**. No TextureCoordinate element is written (an empty or fabricated one would break X_ITE texturing). |
| `Z03.twouv` | CORE | **Only the ACTIVE UV map is exported**. TextureCoordinate holds the values of the layer named 'Second' (e.g. 0.125 0.875), not the default 'UVMap'. |
| `Z03.twouv.extra` | ROADMAP | **Second UV set -> multi-texturing / TextureCoordinate for lightmaps**. X3D 4 supports per-texture texCoord mapping ('TEXCOORD1' etc.); glTF-style TEXCOORD_1 is dropped today. |
| `Z03.vcol.point` | CORE | **Per-vertex float colours with alpha -> ColorRGBA**. <ColorRGBA color=...> with one RGBA entry per Coordinate; alpha 0.75 everywhere; values are Blender's linear floats verbatim.  Browser: a red/green gradient plate (the colours multiply the base colour in X_ITE). |
| `Z03.vcol.corner` | CORE | **Per-face (corner) colours split vertices**. Each cube face has its own flat colour, so the 8 positions become >= 24 Coordinate entries with 24 matching colours; browser: a six-coloured cube. |

## Z04 mat_pbr - PBR scalar materials: metallic x roughness grid, colour, emission

| case | tier | what a correct export looks like |
|---|---|---|
| `Z04.grid.metal0` | CORE | **Metallic 0.0 row: five roughness steps**. Five spheres with metallic=0.0 and roughness 0, .25, .5, .75, 1 written verbatim as <PhysicalMaterial baseColor='0.9 0.55 0.2' metallic roughness>; no stray emissive/transparency attributes.  Browser: roughness blurs highlights left->right; metals need an environment to look right (see ROADMAP/EnvironmentLight). |
| `Z04.grid.metal1` | CORE | **Metallic 0.25 row: five roughness steps**. Five spheres with metallic=0.25 and roughness 0, .25, .5, .75, 1 written verbatim as <PhysicalMaterial baseColor='0.9 0.55 0.2' metallic roughness>; no stray emissive/transparency attributes.  Browser: roughness blurs highlights left->right; metals need an environment to look right (see ROADMAP/EnvironmentLight). |
| `Z04.grid.metal2` | CORE | **Metallic 0.5 row: five roughness steps**. Five spheres with metallic=0.5 and roughness 0, .25, .5, .75, 1 written verbatim as <PhysicalMaterial baseColor='0.9 0.55 0.2' metallic roughness>; no stray emissive/transparency attributes.  Browser: roughness blurs highlights left->right; metals need an environment to look right (see ROADMAP/EnvironmentLight). |
| `Z04.grid.metal3` | CORE | **Metallic 0.75 row: five roughness steps**. Five spheres with metallic=0.75 and roughness 0, .25, .5, .75, 1 written verbatim as <PhysicalMaterial baseColor='0.9 0.55 0.2' metallic roughness>; no stray emissive/transparency attributes.  Browser: roughness blurs highlights left->right; metals need an environment to look right (see ROADMAP/EnvironmentLight). |
| `Z04.grid.metal4` | CORE | **Metallic 1.0 row: five roughness steps**. Five spheres with metallic=1.0 and roughness 0, .25, .5, .75, 1 written verbatim as <PhysicalMaterial baseColor='0.9 0.55 0.2' metallic roughness>; no stray emissive/transparency attributes.  Browser: roughness blurs highlights left->right; metals need an environment to look right (see ROADMAP/EnvironmentLight). |
| `Z04.basecolor.edges` | CORE | **Base colour extremes incl. HDR (>1) values**. Black/white/pure red verbatim.  A base colour with a channel above 1.0 (2.0 0.5 0.1) is scaled so the peak is 1.0 (hue kept) because SFColor is limited to [0,1] -> '1 0.25 0.05'. |
| `Z04.emission.scaling` | CORE | **Emission colour x strength -> emissiveColor (clamped into [0,1])**. strength 1 -> '1 0.5 0.1'; strength 0.25 -> '0.25 0.125 0.025'; strength 4 -> channels above 1 are rescaled by the peak so it lands on the same '1 0.5 0.1' (hue kept).  Browser: orange glow, first and third sphere look identical. |
| `Z04.emission.strength` | ROADMAP | **Emission strength above 1 -> EmissiveStrengthMaterialExtension**. The strength-4 sphere should keep its 4x via <EmissiveStrengthMaterialExtension emissiveStrength='4'> (X_ITE implements it, glTF KHR_materials_emissive_strength has the same meaning).  Exporter currently normalises it away. |
| `Z04.emission.default` | CORE | **A default Principled BSDF emits nothing**. Blender >= 4.0 defaults Emission Strength to 0, so no emissiveColor attribute is written. |
| `Z04.unlit` | CORE | **Pure Emission shader -> UnlitMaterial**. An Emission-only material becomes <UnlitMaterial emissiveColor='0.1 0.45 0.2'> (colour x 0.5): shape glows flat, independent of lights (X3D 4.0 UnlitMaterial). |

## Z05 mat_alpha - Transparency, blend modes and culling

| case | tier | what a correct export looks like |
|---|---|---|
| `Z05.blend50` | CORE | **alpha 0.5 with BLENDED render method**. Appearance alphaMode=BLEND; PhysicalMaterial transparency = 1 - alpha = 0.5.  Browser: the plate is see-through; the checker backdrop shows through proportionally. |
| `Z05.dither50` | CORE | **alpha 0.5 with DITHERED render method**. Appearance alphaMode=absent (AUTO); PhysicalMaterial transparency = 1 - alpha = 0.5.  Browser: the plate is see-through; the checker backdrop shows through proportionally. |
| `Z05.blend100` | CORE | **alpha 1.0 with BLENDED render method**. Appearance alphaMode=BLEND; PhysicalMaterial transparency = 1 - alpha = 0.0 (attribute omitted when 0).  Browser: the plate is opaque; the checker backdrop shows through proportionally. |
| `Z05.blend25` | CORE | **alpha 0.25 with BLENDED render method**. Appearance alphaMode=BLEND; PhysicalMaterial transparency = 1 - alpha = 0.75.  Browser: the plate is see-through; the checker backdrop shows through proportionally. |
| `Z05.texalpha` | CORE | **RGBA texture drives alpha**. baseTexture points at T_alpha_cutout.png (copied next to the .x3d); alphaMode BLEND.  Browser: a blue disc, the corners fully transparent (texture alpha channel). |
| `Z05.clip` | ROADMAP | **Alpha cutout -> alphaMode='MASK' with alphaCutoff**. Blender 4.2+ removed the 'Alpha Clip' blend mode and Material.blend_method can no longer be set to CLIP (it silently becomes HASHED), so the exporter's MASK branch is unreachable on current Blender.  A convention (custom property or a Math>Greater Than node feeding Alpha) is needed.  Expect MISSING. |

## Z06 mat_tex - Textures: the glTF-style PBR set, mapping, wrapping, formats

| case | tier | what a correct export looks like |
|---|---|---|
| `Z06.base` | CORE | **Base colour texture -> baseTexture**. PhysicalMaterial has baseColor='1 1 1' and a child <ImageTexture containerField='baseTexture' url='"T_base_uvtest.png"'>; the PNG is copied next to the .x3d.  Browser orientation test: RED top-left, GREEN top-right, BLUE bottom-left, YELLOW bottom-right, white diagonal rising to the right, black dot in the red quadrant.  If red is bottom-left the V axis is flipped. |
| `Z06.normal` | CORE | **Normal map + strength -> normalTexture + normalScale**. normalScale='0.7' and <ImageTexture containerField='normalTexture'> referencing T_normal.png.  Browser (with light): a 4x4 grid of bumps. |
| `Z06.orm` | CORE | **Packed metallic/roughness image -> metallicRoughnessTexture**. The Separate Color node feeding Roughness(G) and Metallic(B) is followed back to its image: <ImageTexture containerField='metallicRoughnessTexture'> with T_orm.png. |
| `Z06.factors` | FIDELITY | **Linked sockets must not leak their default values into the glTF-style factors**. In X3D/glTF the factor MULTIPLIES the texture.  Blender's unlinked default values (Base Color 0.8, Metallic 0.0, Roughness 0.5) are irrelevant once a texture is linked, so a faithful export writes factors 1/1/1.  Writing metallic='0' silently kills the metalness map (0 x texture = 0); baseColor 0.8 darkens the texture by 20%. |
| `Z06.emissive` | CORE | **Emission image -> emissiveTexture**. emissiveColor='1 1 1' (factor) plus <ImageTexture containerField='emissiveTexture'> with T_emissive.png.  Browser: orange grid lines glowing on black. |
| `Z06.occlusion` | CORE | **Occlusion texture (labelled node) + strength**. Blender's Principled BSDF has no AO input, so the exporter recognises an image node whose name/label contains 'occlusion' and a Value node named 'occlusion_strength': occlusionStrength='0.6' + <ImageTexture containerField='occlusionTexture'>. |
| `Z06.all` | CORE | **Complete five-texture PBR set on one material**. One <PhysicalMaterial> carries baseTexture, normalTexture, metallicRoughnessTexture, emissiveTexture and occlusionTexture, each pointing at its own file; the Appearance is DEF'd once. |
| `Z06.wrap` | CORE | **Texture extension: REPEAT vs CLIP -> repeatS/repeatT**. UVs run 0..2 on both planes.  REPEAT: no repeat attributes (X3D default TRUE): the image tiles 2x2.  CLIP: repeatS='false' repeatT='false': a single image, edge texels stretched (X3D has no transparent border). |
| `Z06.wrap.mirror` | ROADMAP | **MIRROR / EXTEND extension modes**. Only CLIP is mapped.  X3D 4.0 has mirrored repeat via TextureProperties (boundaryModeS='MIRRORED_REPEAT'); Blender's MIRROR extension is exported as plain repeat. |
| `Z06.mapping` | CORE | **Mapping node -> TextureTransform**. <TextureTransform translation='0.25 0.1' rotation='0.5' scale='2 3'> inside the Appearance.  Browser: texture tiled 2x3, rotated ~29 deg. |
| `Z06.decoy.ao` | CORE | **A texture called 'kaolin' is NOT an occlusion map**. Detection of occlusion maps by keyword must not fire on the substring 'ao' inside unrelated words/folders such as 'kaolin' or '/home/Naomi/'.  Expected: baseTexture only, NO occlusionTexture.  (Bug hunt: the exporter matches bare substrings against name, label, image name AND the full file path.) |
| `Z06.jpeg` | CORE | **JPEG texture keeps its format**. url ends in .jpg and the file exists next to the .x3d (browsers decode it natively). |
| `Z06.webformat` | FIDELITY | **Browser-decodable texture formats only**. WebGL/X_ITE cannot decode TGA/TIFF/BMP/EXR.  A web-ready export converts such images to PNG/JPEG (or KTX2) while copying; today the file is copied verbatim and the browser shows a missing texture. |
| `Z06.packed` | CORE | **Packed / generated image has no file: exporter writes one**. The image only lives inside the .blend; the exporter must write it (as PNG) next to the .x3d and reference it; the URL is never an empty string and never a Blender-internal path. |

## Z07 mat_adv - Beyond scalar PBR: Principled extras and non-Principled shaders

| case | tier | what a correct export looks like |
|---|---|---|
| `Z07.ext.clearcoat` | ROADMAP | **Principled 'Coat Weight' -> <ClearcoatMaterialExtension>**. X_ITE 16 implements <ClearcoatMaterialExtension> inside PhysicalMaterial.extensions (verified in its X3DUOM).  The exporter writes only the five core PBR fields, so this extra surface response is dropped -> MISSING until implemented. |
| `Z07.ext.transmission` | ROADMAP | **Principled 'Transmission Weight' -> <TransmissionMaterialExtension>**. X_ITE 16 implements <TransmissionMaterialExtension> inside PhysicalMaterial.extensions (verified in its X3DUOM).  The exporter writes only the five core PBR fields, so this extra surface response is dropped -> MISSING until implemented. |
| `Z07.ext.sheen` | ROADMAP | **Principled 'Sheen Weight' -> <SheenMaterialExtension>**. X_ITE 16 implements <SheenMaterialExtension> inside PhysicalMaterial.extensions (verified in its X3DUOM).  The exporter writes only the five core PBR fields, so this extra surface response is dropped -> MISSING until implemented. |
| `Z07.ext.ior` | ROADMAP | **Principled 'IOR' -> <IORMaterialExtension>**. X_ITE 16 implements <IORMaterialExtension> inside PhysicalMaterial.extensions (verified in its X3DUOM).  The exporter writes only the five core PBR fields, so this extra surface response is dropped -> MISSING until implemented. |
| `Z07.ext.specular` | ROADMAP | **Principled 'Specular IOR Level' -> <SpecularMaterialExtension>**. X_ITE 16 implements <SpecularMaterialExtension> inside PhysicalMaterial.extensions (verified in its X3DUOM).  The exporter writes only the five core PBR fields, so this extra surface response is dropped -> MISSING until implemented. |
| `Z07.ext.aniso` | ROADMAP | **Principled 'Anisotropic' -> <AnisotropyMaterialExtension>**. X_ITE 16 implements <AnisotropyMaterialExtension> inside PhysicalMaterial.extensions (verified in its X3DUOM).  The exporter writes only the five core PBR fields, so this extra surface response is dropped -> MISSING until implemented. |
| `Z07.ext.thinfilm` | ROADMAP | **Principled 'Thin Film Thickness' -> <IridescenceMaterialExtension>**. X_ITE 16 implements <IridescenceMaterialExtension> inside PhysicalMaterial.extensions (verified in its X3DUOM).  The exporter writes only the five core PBR fields, so this extra surface response is dropped -> MISSING until implemented. |
| `Z07.shader.diffuse` | FIDELITY | **Non-Principled surface: diffuse**. Only Principled BSDF and Emission are understood; every other shader falls back to a neutral grey 0.8 and, worse, leaves metallic/roughness UNWRITTEN, which X3D 4.0 reads as metallic=1, roughness=1 (a dark mirror).  A faithful export maps Diffuse/Glossy/Glass/Mix to the nearest PBR values. |
| `Z07.shader.glossy` | FIDELITY | **Non-Principled surface: glossy**. Only Principled BSDF and Emission are understood; every other shader falls back to a neutral grey 0.8 and, worse, leaves metallic/roughness UNWRITTEN, which X3D 4.0 reads as metallic=1, roughness=1 (a dark mirror).  A faithful export maps Diffuse/Glossy/Glass/Mix to the nearest PBR values. |
| `Z07.shader.glass` | FIDELITY | **Non-Principled surface: glass**. Only Principled BSDF and Emission are understood; every other shader falls back to a neutral grey 0.8 and, worse, leaves metallic/roughness UNWRITTEN, which X3D 4.0 reads as metallic=1, roughness=1 (a dark mirror).  A faithful export maps Diffuse/Glossy/Glass/Mix to the nearest PBR values. |
| `Z07.shader.mix` | FIDELITY | **Non-Principled surface: mix**. Only Principled BSDF and Emission are understood; every other shader falls back to a neutral grey 0.8 and, worse, leaves metallic/roughness UNWRITTEN, which X3D 4.0 reads as metallic=1, roughness=1 (a dark mirror).  A faithful export maps Diffuse/Glossy/Glass/Mix to the nearest PBR values. |
| `Z07.implicit.metal` | FIDELITY | **Unwritten metallic/roughness default to 1.0 in X3D**. Whenever the exporter cannot find a Principled node it omits metallic/roughness; PhysicalMaterial's defaults are metallic=1, roughness=1.  Writing explicit values (0 and 0.5, as the no-material path does) avoids a black chrome look. |

## Z08 hier - Transforms, hierarchy and parenting

| case | tier | what a correct export looks like |
|---|---|---|
| `Z08.chain.xf` | CORE | **Five-deep parent chain keeps world transforms**. Each Transform is nested in its parent's Transform (hierarchy mode) and the composition of translation/rotation/scale up the chain equals Blender's matrix_world after the Y-up conversion.  Browser: a gently rising spiral of five cubes. |
| `Z08.chain.nesting` | CORE | **Hierarchy export nests Transforms; flat export does not**. Main profile: chain1 is a direct child of chain0, etc.  'crease' profile (Hierarchy OFF): every Transform is top-level (world matrices) yet world poses are still right. |
| `Z08.chain.flat` | CORE | **Flat (non-hierarchical) export keeps world transforms** *(profile crease)*. Hierarchy OFF: all five cubes are top-level Transforms with baked world matrices. |
| `Z08.shear.hier` | CORE | **Skew from non-uniform parent scale survives in hierarchy mode**. Parent scale (2,1,1) with a child rotated 45 deg produces a sheared world matrix.  Nested TRS Transforms reproduce it exactly. |
| `Z08.shear.flat` | FIDELITY | **Skew is lost when the hierarchy is flattened** *(profile crease)*. With Hierarchy OFF the sheared world matrix must be decomposed into translation/rotation/scale, which cannot hold shear: the child lands deformed.  A faithful flat export would bake the skew into the vertices or force hierarchy. |
| `Z08.rotation.modes` | CORE | **All rotation modes (Euler orders, quaternion, axis-angle, gimbal pole)**. Whatever the rotation mode, the Transform rotation equals the object's actual orientation (axis-angle in X3D space).  Includes a 90 deg gimbal-lock pitch. |
| `Z08.negative.scale` | CORE | **Mirrored (negative) scale**. Negative scales are written as such (X3D allows them); the composed matrix equals Blender's, including a full inversion (-1,-1,-1). |
| `Z08.delta.pinv` | CORE | **Delta transforms and a non-identity parent-inverse matrix**. Both are baked into matrix_world by Blender and therefore into the exported Transforms. |
| `Z08.parent.vertex.constraint` | CORE | **Vertex parenting and Track-To constraint resolve to world matrices**. matrix_world already contains the constraint / vertex-parent result, so both objects land exactly where Blender shows them. |
| `Z08.hidden.object` | CORE | **Viewport-disabled objects are exported unless 'Visible only' is chosen**. Default export options include hidden objects (use_visible=False): the Transform and its Shape are present. |
| `Z08.empties` | CORE | **Empties become bare Transforms**. Each empty is a <Transform> without children; X3D has no 'display type'.  Browser: nothing drawn. |

## Z09 instances - Instancing, DEF/USE, naming and collection instances

| case | tier | what a correct export looks like |
|---|---|---|
| `Z09.defuse.geometry` | CORE | **13 objects sharing one mesh -> 1 IndexedFaceSet + 12 USE**. Exactly one <IndexedFaceSet DEF='ME_Z09_shared_mesh'> and twelve <IndexedFaceSet USE='ME_Z09_shared_mesh'>; the file stays small. Browser: identical spheres, no extra memory. |
| `Z09.defuse.appearance` | CORE | **Shared material -> 1 Appearance + USE; per-object override gets its own**. Twelve instance objects plus slot 0 of the two-material cube share <Appearance DEF='APP_T_inst_a'>: 1 DEF + 12 USE (11 from the instances, 1 from Z09_multi); the object-linked override carries APP_T_inst_b while still re-using the geometry. |
| `Z09.multislot` | CORE | **Two material slots -> two Shapes, geometry split per slot**. Z09_multi has 6 faces on 2 slots: two <Shape> children, geometries DEF'd ME_Z09_multi_mesh_m0 / _m1 with 3 faces each. |
| `Z09.names.collision` | CORE | **Names that sanitise to the same DEF stay unique**. 'Dup.001' and 'Dup_001' both sanitise to Dup_001; the exporter must add a suffix (ME_Dup_001, ME_Dup_001_2) so DEFs never collide. |
| `Z09.names.unusual` | CORE | **Spaces, dots, accents and leading digits become valid X3D names**. 'Z09 weird name é.001' -> OB_Z09_weird_name_é_001; '9lives' -> OB__lives; mesh 'Mesh With Spaces' -> ME_Mesh_With_Spaces. All DEFs must stay valid XML names without spaces or dots. |
| `Z09.collection.instance` | FIDELITY | **Collection instances carry their geometry**. Two empties instancing a cone collection are the standard way scripts (and AI-generated bpy code) repeat objects.  The instance Transforms should contain the instanced Shapes (ideally as DEF/USE of one geometry).  Today an instancing empty is exported as a bare Transform, so the cones vanish. |
| `Z09.gn.realised` | CORE | **Geometry Nodes output (realised) is exported as a mesh**. Main profile applies modifiers: the 16 scattered cubes (96 faces) appear as ONE IndexedFaceSet - the usual route for procedurally generated scientific geometry. |
| `Z09.gn.nophantom` | CORE | **A mesh object whose evaluated geometry has no faces writes no placeholder shape**. Z09_gn_instances evaluates to instances only (no mesh faces).  Expected: the Transform is written without a Shape.  Browser: nothing at that spot - NOT a grey sphere. |
| `Z09.gn.instances` | FIDELITY | **Un-realised Geometry Nodes instances are exported**. 'Instance on Points' without 'Realize Instances' shows 16 cubes in Blender, but the evaluated mesh contains no instances, so nothing is written.  Expected: 96 faces (16 cubes x 6) or 16 USE references. |

## Z10 modifiers - Modifier stack: evaluated vs. base meshes

| case | tier | what a correct export looks like |
|---|---|---|
| `Z10.subsurf.applied` | CORE | **subsurf: modifier result exported (Apply Modifiers ON)**. With 'Apply Modifiers' the evaluated mesh (96 faces) is written - what the viewport shows, not the 6-face base. |
| `Z10.subsurf.base` | CORE | **subsurf: base mesh exported (Apply Modifiers OFF)** *(profile crease)*. With the option off the 6-face base mesh is written. |
| `Z10.array.applied` | CORE | **array: modifier result exported (Apply Modifiers ON)**. With 'Apply Modifiers' the evaluated mesh (18 faces) is written - what the viewport shows, not the 6-face base. |
| `Z10.array.base` | CORE | **array: base mesh exported (Apply Modifiers OFF)** *(profile crease)*. With the option off the 6-face base mesh is written. |
| `Z10.mirror.applied` | CORE | **mirror: modifier result exported (Apply Modifiers ON)**. With 'Apply Modifiers' the evaluated mesh (50 faces) is written - what the viewport shows, not the 25-face base. |
| `Z10.mirror.base` | CORE | **mirror: base mesh exported (Apply Modifiers OFF)** *(profile crease)*. With the option off the 25-face base mesh is written. |
| `Z10.solidify.applied` | CORE | **solidify: modifier result exported (Apply Modifiers ON)**. With 'Apply Modifiers' the evaluated mesh (16 faces) is written - what the viewport shows, not the 4-face base. |
| `Z10.solidify.base` | CORE | **solidify: base mesh exported (Apply Modifiers OFF)** *(profile crease)*. With the option off the 4-face base mesh is written. |
| `Z10.bevel.applied` | CORE | **bevel: modifier result exported (Apply Modifiers ON)**. With 'Apply Modifiers' the evaluated mesh (54 faces) is written - what the viewport shows, not the 6-face base. |
| `Z10.bevel.base` | CORE | **bevel: base mesh exported (Apply Modifiers OFF)** *(profile crease)*. With the option off the 6-face base mesh is written. |
| `Z10.triangulate.applied` | CORE | **triangulate: modifier result exported (Apply Modifiers ON)**. With 'Apply Modifiers' the evaluated mesh (12 faces) is written - what the viewport shows, not the 6-face base. |
| `Z10.triangulate.base` | CORE | **triangulate: base mesh exported (Apply Modifiers OFF)** *(profile crease)*. With the option off the 6-face base mesh is written. |
| `Z10.disabled.applied` | CORE | **disabled: modifier result exported (Apply Modifiers ON)**. With 'Apply Modifiers' the evaluated mesh (6 faces) is written - what the viewport shows, not the 6-face base. The disabled-in-viewport modifier is NOT applied. |
| `Z10.disabled.base` | CORE | **disabled: base mesh exported (Apply Modifiers OFF)** *(profile crease)*. With the option off the 6-face base mesh is written. |
| `Z10.boolean.applied` | CORE | **boolean: modifier result exported (Apply Modifiers ON)**. With 'Apply Modifiers' the evaluated mesh (6 faces) is written - what the viewport shows, not the 6-face base. |
| `Z10.boolean.base` | CORE | **boolean: base mesh exported (Apply Modifiers OFF)** *(profile crease)*. With the option off the 6-face base mesh is written. |
| `Z10.boolean.cutter` | CORE | **The boolean cutter is itself exported as a solid**. Helper objects displayed as wire/bounds are still ordinary meshes to the exporter; hide them (or use 'Visible Only') if unwanted. |

## Z11 lights - Lights: type mapping, intensity, spot cone, direction

| case | tier | what a correct export looks like |
|---|---|---|
| `Z11.point` | CORE | **Point light: colour, intensity mapping, custom range**. <PointLight color='1 0.8 0.6' intensity='0.571429' radius='8' global='true'> inside the object's Transform; location 0 0 0 (the Transform places it).  intensity = min(energy_watts / 1.75, 1). |
| `Z11.point.saturation` | CORE | **Very bright point light clamps to intensity 1**. 1000 W -> intensity 1.0 (SFFloat intensity is limited to [0,1]). |
| `Z11.point.range` | FIDELITY | **Light radius follows the 'Custom Distance' switch**. When Custom Distance is OFF the light is unbounded in Blender; the exporter's documented fallback is radius 100.  It reads Blender's stored cutoff_distance (40 by default) even when the switch is off. |
| `Z11.point.dynamic_range` | FIDELITY | **10 W and 100 W lights stay distinguishable**. Both clamp to intensity 1.0, so a 10x brightness difference vanishes.  A tone-mapped or log mapping (or rescaling the whole scene's lights by the maximum) would keep the ratio. |
| `Z11.spot` | CORE | **Spot light: cone angles and range**. <SpotLight beamWidth='0.387463' cutOffAngle='0.503702' direction='0 0 -1' radius='9.2587'> (legacy-exporter formulae: beamWidth = size x 0.37, cutOffAngle = 1.3 x beamWidth).  intensity 0.875/1.75 = 0.5. |
| `Z11.spot.cone` | FIDELITY | **cutOffAngle is the cone's half angle**. A 60 deg Blender spot has a 30 deg (0.5236 rad) half angle.  The legacy empirical formula gives 0.5037 (-3.8%).  Tolerance 1%. |
| `Z11.spot.blend` | FIDELITY | **Spot blend influences beamWidth**. Blender's Blend value (0 hard edge .. 1 fully soft) has no counterpart in the formula, so two spots that differ only in blend export identical beamWidth.  Expected: beamWidth(blend 1.0) < beamWidth(blend 0.0). |
| `Z11.sun` | CORE | **Sun -> DirectionalLight with world direction**. <DirectionalLight direction='0 0 -1' intensity='0.6' global='true'> in a Transform that rotates it; the WORLD direction (Transform rotation applied to the local -Z) equals Blender's light direction after the Y-up conversion. |
| `Z11.sun.saturation` | CORE | **Sun strength above 1 clamps**. strength 3 -> intensity 1. |
| `Z11.area` | CORE | **Area light -> DirectionalLight (documented approximation)**. X3D has no area light; the exporter maps it to a DirectionalLight along the lamp's -Z.  Expect a DirectionalLight with the right world direction (no crash, no PointLight). |
| `Z11.global` | CORE | **Every light is global**. global='true' on all lights: lights inside a Transform would otherwise only light their siblings (nothing). |
| `Z11.shadow` | ROADMAP | **Shadows / soft size / specular factor**. Blender's shadow flags, light radius (soft shadows) and specular multiplier have no X3D equivalent in the exported subset; X_ITE supports shadows via the 'shadows' field of lights (X3D 4.0 'shadowIntensity').  Expect MISSING. |

## Z12 cameras - Cameras -> Viewpoints

| case | tier | what a correct export looks like |
|---|---|---|
| `Z12.persp50` | CORE | **Z12_persp50: FOV conversion (AUTO, 50.0 deg in Blender)**. <Viewpoint DEF='CA_Z12_persp50' fieldOfView='0.513039' position='0 0 0' orientation='0 0 1 0'> - X3D measures the FOV across the SMALLER display side, Blender across the fitted side (1280x720 render).  The camera pose lives in the parent Transform.  Browser: select this viewpoint from the viewpoint list; framing matches Blender's camera view. |
| `Z12.vfit40` | CORE | **Z12_vfit40: FOV conversion (VERTICAL, 40.0 deg in Blender)**. <Viewpoint DEF='CA_Z12_vfit40' fieldOfView='0.698132' position='0 0 0' orientation='0 0 1 0'> - X3D measures the FOV across the SMALLER display side, Blender across the fitted side (1280x720 render).  The camera pose lives in the parent Transform.  Browser: select this viewpoint from the viewpoint list; framing matches Blender's camera view. |
| `Z12.hfit90` | CORE | **Z12_hfit90: FOV conversion (HORIZONTAL, 90.0 deg in Blender)**. <Viewpoint DEF='CA_Z12_hfit90' fieldOfView='1.024779' position='0 0 0' orientation='0 0 1 0'> - X3D measures the FOV across the SMALLER display side, Blender across the fitted side (1280x720 render).  The camera pose lives in the parent Transform.  Browser: select this viewpoint from the viewpoint list; framing matches Blender's camera view. |
| `Z12.tele85` | CORE | **Z12_tele85: FOV conversion (AUTO, 23.9 deg in Blender)**. <Viewpoint DEF='CA_Z12_tele85' fieldOfView='0.237118' position='0 0 0' orientation='0 0 1 0'> - X3D measures the FOV across the SMALLER display side, Blender across the fitted side (1280x720 render).  The camera pose lives in the parent Transform.  Browser: select this viewpoint from the viewpoint list; framing matches Blender's camera view. |
| `Z12.ortho` | CORE | **Orthographic camera does not crash**. Exported as a Viewpoint (no fieldOfView).  Browser: shows with the default perspective FOV. |
| `Z12.ortho.viewpoint` | ROADMAP | **Orthographic camera -> OrthoViewpoint**. X3D 4.0 has OrthoViewpoint (fieldOfView = left/bottom/right/top box derived from ortho_scale).  Not mapped yet. |
| `Z12.initial.view` | FIDELITY | **The scene's active camera is the initial Viewpoint**. X3D binds the FIRST Viewpoint in the file on load.  Blender's active camera (here Z12_persp50) should therefore come first (or be bound explicitly) so the file opens exactly like the Blender camera view. |
| `Z12.pan` | ROADMAP | **Lens shift and clipping planes**. shift_x/shift_y and clip_start/clip_end have no Viewpoint fields; X3D carries clipping in NavigationInfo.visibilityLimit/avatarSize. Not exported (acceptable for most scenes). |
| `Z12.tour` | CORE | **One tour Viewpoint per zone**. Every zone has a camera 'CAM_Zxx' that frames it from the front and above; each becomes a <Viewpoint> with description = camera name and fieldOfView 0.750 (X3D measures the SMALLER display side: a 70 deg horizontal lens on a 16:9 render).  In X_ITE use the viewpoint menu (or the browser_check script) to hop from zone to zone. |

## Z13 anim - Animation: sampled transforms, hierarchy, constraints, drivers, physics

| case | tier | what a correct export looks like |
|---|---|---|
| `Z13.timer` | CORE | **One TimeSensor drives everything**. <TimeSensor DEF='SceneTimer' cycleInterval='2.000000' loop='true'>: frames 1..49 at 24 fps = 2.0 s.  Browser: animation starts by itself and loops seamlessly. |
| `Z13.move` | CORE | **Keyframed translation (linear, 3 keys)**. A PositionInterpolator with one key per frame (49 keys, 0..1) routed TimeSensor.fraction_changed -> set_fraction and value_changed -> Transform.set_translation.  Browser: the cube glides left->right rising to the middle and sinking again. |
| `Z13.spin` | CORE | **One full revolution (OrientationInterpolator)**. 49 orientation keys; angular velocity constant, so even mid-frame playback positions match Blender.  First and last orientation are identical (seamless loop). |
| `Z13.scale` | CORE | **Scale pulse**. A scale interpolator (PositionInterpolator DEF SI_*) routed to set_scale. |
| `Z13.ease` | CORE | **Bezier-eased motion is sampled, not approximated by two keys**. Because every frame is sampled, the ease-in/ease-out curve survives: mid-timeline positions match Blender (not a straight line). |
| `Z13.hierarchy` | CORE | **Animated parent with animated child (orbit + bob)**. Parent rotates (orientation interpolator), child bobs (position interpolator) in parent space; composed world position equals Blender's at every sample frame.  Browser: a cube circling its pivot while bobbing. |
| `Z13.constraint` | CORE | **Constraint-driven object animates without own keyframes**. Z13_follow has no keys, but follows Z13_move through a Copy Location constraint: the exporter samples matrix_world, so it still receives an interpolator. |
| `Z13.driver` | CORE | **Driver-based animation (rotation = frame x 7.5 deg)**. Drivers are evaluated by Blender before sampling, so Z13_driver turns 360 deg over the cycle. |
| `Z13.still` | CORE | **Keyed but unchanging objects get no interpolators**. Z13_still has keyframes with identical values -> no PositionInterpolator, no ROUTE. |
| `Z13.camera` | CORE | **Animated camera (Track-To) -> animated Viewpoint Transform**. The camera's Transform is animated with the constraint solved at every frame, so the Viewpoint swings along the path while always looking at the target. |
| `Z13.fastspin` | FIDELITY | **Spins faster than half a turn per frame are not aliased**. 24.3 turns in 48 frames = 182 deg per frame.  Interpolators take the SHORTEST rotation between consecutive keys, so the playback shows the cube creeping slowly BACKWARDS.  Faithful export subdivides keys (or uses more keys per frame).  Checked at mid-frame points. |
| `Z13.light` | ROADMAP | **Animated light colour / energy**. Animation sampling covers object transforms only.  Light energy/colour keyframes would need a ScalarInterpolator/ColorInterpolator routed to the light's intensity/color.  Expect MISSING. |
| `Z13.material` | ROADMAP | **Animated material colour**. Keyframed Base Color -> ColorInterpolator routed to the PhysicalMaterial.baseColor.  Not implemented. |
| `Z13.shapekey` | ROADMAP | **Shape keys (morph targets)**. Keyed shape-key value -> CoordinateInterpolator animating the Coordinate points (or morph weights).  Today the basis mesh is exported and the morph is lost. |
| `Z13.physics` | FIDELITY | **Baked rigid-body simulation becomes keyframe-like interpolators**. A ball dropped from 5 m bounces on a box (restitution 0.7).  The exporter steps the frame range sequentially, sampling matrix_world, so the dynamics become a PositionInterpolator.  This is the bridge from Blender simulations to X3D.  Marked FIDELITY because it relies on the rigid-body cache being deterministic across two sequential passes. |
| `Z13.meshdeform` | ROADMAP | **Per-frame mesh deformation (cloth, soft body, simulation output)**. Scientific/engineering simulations usually deform geometry over time.  X3D handles this with CoordinateInterpolator; the exporter samples transforms only. |

## Z14 hanim - Armature -> HAnim humanoid with skinning and pose animation

| case | tier | what a correct export looks like |
|---|---|---|
| `Z14.structure` | CORE | **Armature -> HAnimHumanoid with a joint tree**. One <HAnimHumanoid name='Z14_rig' version='2.0'> whose <HAnimJoint> tree mirrors the bone hierarchy (6 joints, names = bone names, 'center' = bone head in armature space), each joint also listed once in 'joints' via USE.  Component HAnim level 1 is declared. |
| `Z14.weights` | CORE | **Skin weights are complete and normalised**. Every skin vertex is attached to joints through skinCoordIndex/skinCoordWeight; the weights for each skinCoord point sum to 1. |
| `Z14.pose` | CORE | **Linear-blend skinning reproduces Blender's deformation**. Emulating HAnim's skinning (sum over joints of weight x joint matrix about 'center') with the exported joint interpolators reproduces the vertex positions Blender's Armature modifier produces at frames 1, 13, 25, 37, 49.  Browser: arm raises, torso bends, head turns. |
| `Z14.skinless` | CORE | **Armature without skin still exports a humanoid**. Z14_rig2 has two bones and no mesh: HAnimHumanoid with joints base and tip, no skinCoord, no crash. |
| `Z14.hanim.names` | ROADMAP | **Standard HAnim joint names / LOA**. The exporter writes Blender bone names and skeletalConfiguration='BLENDER'.  Standards-conformant avatars need the HAnim joint names (l_shoulder, vl5 ...) and a level of articulation; a mapping table would make Blender rigs interchangeable with other HAnim tools. |

## Z15 types - Object types: text, curves, surfaces and everything the exporter must skip gracefully

| case | tier | what a correct export looks like |
|---|---|---|
| `Z15.text` | CORE | **Text object is converted to a mesh**. A FONT object ('X3D', extruded) becomes an IndexedFaceSet of the glyph outlines (evaluated mesh).  Browser: extruded letters X 3 D. |
| `Z15.curve.bevel` | CORE | **Beveled curve is converted to a tube mesh**. A poly curve with bevel depth becomes a mesh tube (faces > 0). |
| `Z15.curve.wire` | CORE | **Un-beveled curve has no faces: handled gracefully**. A curve without thickness exports no Shape; the diagnostics say "Object 'Z15_curve_wire' has no exportable faces." |
| `Z15.curve.lines` | ROADMAP | **Curves -> IndexedLineSet / Polyline2D / NurbsCurve**. Scientific content (streamlines, trajectories, graphs) is naturally curves.  X3D has NurbsCurve and IndexedLineSet; neither is written. |
| `Z15.surface` | CORE | **NURBS surface is tessellated to a mesh**. A SURFACE object is evaluated to a mesh (resolution 8x8) and exported as an IndexedFaceSet. |
| `Z15.skip.meta` | CORE | **META object is skipped with a diagnostic, not a crash**. The exporter writes <meta name='info' content='Skipped 1 META object(s): not yet supported by the X3D 4.0 path.'>; the export still completes and the file validates.  (In hierarchy mode the object keeps an empty Transform.) |
| `Z15.skip.volume` | CORE | **VOLUME object is skipped with a diagnostic, not a crash**. The exporter writes <meta name='info' content='Skipped 1 VOLUME object(s): not yet supported by the X3D 4.0 path.'>; the export still completes and the file validates.  (In hierarchy mode the object keeps an empty Transform.) |
| `Z15.skip.lattice` | CORE | **LATTICE object is skipped with a diagnostic, not a crash**. The exporter writes <meta name='info' content='Skipped 1 LATTICE object(s): not yet supported by the X3D 4.0 path.'>; the export still completes and the file validates.  (In hierarchy mode the object keeps an empty Transform.) |
| `Z15.skip.speaker` | CORE | **SPEAKER object is skipped with a diagnostic, not a crash**. The exporter writes <meta name='info' content='Skipped 1 SPEAKER object(s): not yet supported by the X3D 4.0 path.'>; the export still completes and the file validates.  (In hierarchy mode the object keeps an empty Transform.) |
| `Z15.skip.probe` | CORE | **LIGHT_PROBE object is skipped with a diagnostic, not a crash**. The exporter writes <meta name='info' content='Skipped 1 LIGHT_PROBE object(s): not yet supported by the X3D 4.0 path.'>; the export still completes and the file validates.  (In hierarchy mode the object keeps an empty Transform.) |
| `Z15.skip.gpencil` | CORE | **GREASEPENCIL object is skipped with a diagnostic, not a crash**. The exporter writes <meta name='info' content='Skipped 1 GREASEPENCIL object(s): not yet supported by the X3D 4.0 path.'>; the export still completes and the file validates.  (In hierarchy mode the object keeps an empty Transform.) |
| `Z15.skip.hair` | CORE | **CURVES object is skipped with a diagnostic, not a crash**. The exporter writes <meta name='info' content='Skipped 1 CURVES object(s): not yet supported by the X3D 4.0 path.'>; the export still completes and the file validates.  (In hierarchy mode the object keeps an empty Transform.) |
| `Z15.skip.points` | CORE | **POINTCLOUD object is skipped with a diagnostic, not a crash**. The exporter writes <meta name='info' content='Skipped 1 POINTCLOUD object(s): not yet supported by the X3D 4.0 path.'>; the export still completes and the file validates.  (In hierarchy mode the object keeps an empty Transform.) |
| `Z15.meta.geometry` | FIDELITY | **Metaballs are exported as meshes**. Metaballs are common for blobs/molecular surfaces.  They evaluate to meshes, so an exporter could tessellate them like curves and text; today they are skipped. |
| `Z15.gpencil.geometry` | ROADMAP | **Grease Pencil strokes**. Strokes could become IndexedLineSet.  Skipped today. |

## Z16 splats - Gaussian splats (X3D 4.1) and Inline references

| case | tier | what a correct export looks like |
|---|---|---|
| `Z16.pointset` | CORE | **4.0 export degrades splats to a coloured PointSet**. X3D 4.0 has no splat node: the splat centres are written as <PointSet> with one ColorRGBA per point (48 points) and a head note 'Gaussian splat object(s) written as PointSet; choose X3D 4.1'.  Browser: a coloured helix of dots. |
| `Z16.gaussiansplats` | CORE | **4.1 export writes the GaussianSplats node** *(profile x41)*. <GaussianSplats positions scales orientations opacities sphericalHarmonicsDegree0Coef0 ...> with 48 splats (positions 144 floats, scales 144, orientations 192 (x,y,z,w), opacities 48, SH0 144) and component GaussianSplats level 1.  Browser support depends on the X_ITE version. |
| `Z16.splat.quaternion` | CORE | **Splat orientation order is (x, y, z, w)** *(profile x41)*. Blender stores (w,x,y,z); X3D carries (x,y,z,w).  Splat 1 (angle 4pi/47) must therefore read '0 0 sin(a/2) cos(a/2)' with the sine in the THIRD slot. |
| `Z16.inline` | CORE | **Empty with x3d_inline_url -> Inline node**. <Inline DEF='IN_Z16_inline' url='"reference/inline_target.x3d"'> inside a Transform whose matrix is G x M x G^-1 (the extra rotation keeps a Y-up asset upright).  Browser (served over http): a small magenta box with a white stripe appears. |

## Z17 shader_lab - Procedural / scalar-field materials: the GLSL ComposedShader roadmap

| case | tier | what a correct export looks like |
|---|---|---|
| `Z17.glsl.composedshader` | ROADMAP | **Procedural materials -> <ComposedShader> (GLSL)**. Noise/Wave/Checker/Voronoi/ColorRamp/Map Range node networks have no PBR-parameter equivalent.  The planned shader subsystem (docs/SHADER_NL_IMPLEMENTATION_SPEC.md in the exporter repo) is meant to emit ComposedShader + ShaderPart (GLSL ES 3.00 for X_ITE).  At repository HEAD only the legacy X3D 3.3/H3D writer emits shaders, so the 4.0 path gives MISSING.  This case flips to NEW when it lands.  Target output: reference/glsl_golden.x3d (hand-written, compiles in X_ITE 16.5.1 with no console messages; check it with x3d_browser_check.py --file reference/glsl_golden.x3d --zones Z17): a <ComposedShader language='GLSL'> with a VERTEX and a FRAGMENT <ShaderPart> (GLSL ES 3.00, data: URI), user parameters as <field>s, and a ROUTE-driven uniform.  Browser: viridis-banded sphere, cyan rim-lit sphere, 3D checker sphere. |
| `Z17.proc.fallback` | FIDELITY | **Procedural material at least exports a complete PBR fallback**. When shaders are not generated the PhysicalMaterial should still be a sensible, fully specified fallback (baseColor, metallic, roughness all written).  Only baseColor is guaranteed here; the validator also reports what colour was chosen. |
| `Z17.glsl.bake` | ROADMAP | **Baked-texture fallback for procedural materials**. Alternative to GLSL: bake the node network to a PNG (Cycles bake) and reference it as baseTexture, so every X3D browser shows the pattern. |

