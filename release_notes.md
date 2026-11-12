## Unreleased (x3d-blender-io fork)
- The X3D 4.0 export clamps per-vertex `ColorRGBA` channels to [0, 1], alpha included. A float colour attribute can hold channels just past 1 or below 0, and the validator refused the whole node for one of them: molecularnodes 520.2.0's pLDDT palette writes a red of 1.000169, which made 9,756 channels on AF-P04637-F1 and 17,326 on AF-P25490-F1 invalid (fork validator 13121b68e6d9). The X3D 3.3 writer reads only byte colours, which can't leave the range. New tests `tests/test_export_colour_range_bpy.py` and `test_vertex_colours_fit_the_sfcolorrgba_range`, failing on the old code.
- New import option **Light Units** (`light_units`; `AUTO` reads the `BLENDER_X3D_LIGHT_UNITS` environment variable, else follows the Colour Space: `X_ITE` with `SRGB`, `BLENDER` with `AS_IS`). X_ITE 16.7.1 lights a `PhysicalMaterial` with 1/d² falloff and a classic `Material` without falloff, in display space; glTF lights everything physically, and the old 1.75 W per unit came out of a COMPAT glb at 0.139 cd per unit. **As X_ITE draws** (`X_ITE`) gives each light the energy that draws in a glTF viewer what X_ITE draws: physical point and spot lights `i · att(d)` cd (exact for the default attenuation), classic ones `L(i · att(d)) · d²` cd at a reference distance `d`, classic suns `L(i)` lux, where `L(x) = pi · lin(min(a x, 1)) / lin(a)` at the scene's median classic albedo `a` (a scene with any PhysicalMaterial is lit physically), and the light's `radius` as its glTF `range`. Measured (X_ITE 16.7.1 vs Babylon.js 9.32.0 on the glb, headless Chrome 153, SwiftShader, 0.8 grey patch): a classic scene lit at 1 goes from 120 to 203 (X_ITE 204), a PhysicalMaterial under a PointLight from 30 to 74 (X_ITE 74). The light's `attenuation` is kept (`x3d_attenuation`) and both X3D exports write it back, and both divide by the recorded scale (`x3d_energy_per_intensity`), so the file's `intensity` survives either units. See "Light units" in the README. On nine x3d.demo scenes with lights the mean geometry |delta| goes from 19.1 to 16.0 (five better, two equal, two worse: dark floors under a strong key light). New test `tests/test_import_light_units_bpy.py` (13 tests, all failing on the old code); the comparison rig is in `tools/fidelity_rig`.
- New import option **Colour Space** (`color_space`; `AUTO` reads the `BLENDER_X3D_COLOR_SPACE` environment variable, else `AS_IS`). X_ITE and Castle Game Engine draw the colours of a `Material`, `TwoSidedMaterial` and `UnlitMaterial` as sRGB values, and those of a `PhysicalMaterial` as linear ones (their default colour space, `LINEAR_WHEN_PHYSICAL_MATERIAL`); Blender and glTF read every colour as linear. **sRGB, as X_ITE draws** (`SRGB`) converts the classic materials' colours, and the colours of lines and points drawn in them, from sRGB to linear, so Blender and every glTF viewer show what X_ITE shows. Measured with X_ITE 16.7 and Babylon.js 9.32 in headless Chrome: an `emissiveColor` of 0.5 is 128 in X_ITE, 186 from the glb made as is and 127 from the glb made with `SRGB`, in both X_ITE and Babylon.js. `AS_IS`, the default, keeps the importer's behaviour; the X3D export does not convert back yet, so `SRGB` is for imports that are rendered, not round-tripped.
- A surface whose Appearance has no material node (or that has no Appearance) imports unlit, as X3D draws it (lighting is off): in its texture, else its `Color` node, else white. Before, it was lit grey (0.8), and a `Color` node's surface came out black in a scene without lights. An Appearance with a shader is left as before.
- Unlit materials (lines and points, and the surfaces above) use the light-path mix Blender's glTF importer makes for `KHR_materials_unlit`: Emission for camera rays, Transparent BSDF for every other ray, so they light nothing and cast no shadow, as in X3D. The glTF exporter writes them as `KHR_materials_unlit`, and the X3D 4.0 export as an `UnlitMaterial` in their colour: a red line set now leaves as red (it left as a grey PhysicalMaterial).
- Sphere, Cylinder and Cone import smooth, as X3D browsers draw them: every face of a Sphere, and the side of a Cylinder and a Cone, with their flat caps behind sharp rim edges. Before, all three came in faceted (they have no `creaseAngle` field, so every face was set flat), and Cycles, Eevee and the glTF read by Unreal and Babylon.js showed the facets: a 16 x 16 sphere left as 992 glTF vertices instead of 287. Rendering the x3d.demo scenes found it (92 scenes with 496 Spheres, 152 Cylinders and 26 Cones). New test `tests/test_import_fidelity_bpy.py`.
- New import option **Circle Divisions** (`circle_divisions`): segments for Sphere, Cylinder, Cone and the Geometry2D circles. 0, the default, keeps 16, or reads the `BLENDER_X3D_CIRCLE_DIV` environment variable, so headless pipelines can ask for 64 or 128 for 4K and 8K renders; clamped to 3..512. X3D leaves the tessellation of its primitives to the browser, so the file's meaning is unchanged.
- A `Material`'s specular term follows X3D's Blinn-Phong model (`specularColor` x (N.H)^(128 x `shininess`)): the lobe width sets the roughness (exponent n matches a GGX alpha of sqrt(2 / (n + 2)); Blender's roughness is its square root) and the peak sets the Principled *Specular IOR Level* (reflectance 8 x specular / (n + 2), capped at a dielectric's 0.08) and *Specular Tint* (the colour of `specularColor`). X3D's default `specularColor` is black, which draws no highlight, so a default Material now has none in Blender and in glTF (`KHR_materials_specular` with `specularFactor` 0). Before, `specularColor` was ignored: every Material had Blender's default dielectric specular, and `shininess` 1 became a mirror (roughness = 1 - shininess). The default Material's roughness moves from 0.8 to 0.52. The X3D export is unchanged.
- Line and point geometry (`IndexedLineSet`, `LineSet`, `PointSet`, and the new 2D lines and points) imports unlit, as X3D draws it: in the colours of its `Color` or `ColorRGBA` node, else in the Material's `emissiveColor` (black when the Material doesn't set it, X3D's classic surprise), else white when the Appearance has no material. The material is the node shape Blender's glTF exporter writes as `KHR_materials_unlit` (a colour straight into the output, through a mix with Transparent BSDF for `transparency` or a `ColorRGBA` alpha), and point and line sets keep their colours as a per-vertex colour attribute (`Color`, which the glTF carries as `COLOR_0`). A coloured `IndexedLineSet` or `LineSet` imports as a mesh of edges, since Blender curves hold no per-vertex colour (`colorPerVertex`, `colorIndex` honoured); without colours it stays a curve. So X_ITE, Babylon.js and three.js draw the glb's lines and points as X3D does. Before, lines and points were lit grey with the diffuse colour, and a point set's `Color` was dropped. A surface sharing the same Material keeps the lit original.
- An `ElevationGrid` with fewer `height` values than `xDimension` x `zDimension` (a grid whose heights a Script or ROUTE sets later, such as the x3d.demo manifold's 97 x 97 grid with none) imports with the missing heights at 0, as X_ITE draws it before the script runs, and a warning. Before, the IndexError stopped the whole import.
- Per-vertex colours of an `IndexedFaceSet` (`colorPerVertex` true, the default) went from sRGB to linear twice, so a `Color` of 0.5 came in as 0.04 instead of 0.21 and per-vertex coloured meshes were far too dark; they now convert once, like per-face colours. The alpha of a `ColorRGBA` is no longer put through the sRGB curve (0.5 became 0.21, much more transparent).
- `TwoSidedMaterial` imports with its front fields (`diffuseColor`, `emissiveColor`, `shininess`, `specularColor`, `transparency`), as a Material; with `separateBackColor` the back colours are not imported (a warning says so). Before, it was ignored and the surface came in as a grey default.
- The importer reads `IndexedQuadSet` and `QuadSet` (CADGeometry; every four indices or coordinates make one quad, a remainder and a quad naming a missing coordinate are skipped, `ccw` honoured), `ArcClose2D` (PIE through the centre, or CHORD; equal angles or a span of 2 pi make the full circle; texture coordinates as for Disk2D), `TriangleSet2D` (texture coordinates over the bounding box), and `Arc2D`, `Circle2D`, `Polyline2D` and `Polypoint2D` as lines and points. All were skipped as "unsupported type".
- Tests for paths no test reached before: Text, Extrusion, the triangle sets (with colours and texture coordinates, and `ccw`), TextureTransform, PixelTexture, PhysicalMaterial texture slots, interpolators driven by ROUTEs, lights and viewpoints, the classic VRML encoding (`tests/test_import_coverage_bpy.py`), the modern import path, the node registry and the X3D 3.3 scaffold (`tests/test_modern_import_bpy.py`). Line coverage of `source/` goes from 59 % to 71 % (the importer from 52 % to 74 %; populate.py, x3d_registry.py and emit_x3d33.py from 0 % to 94-100 %).
- Export of a large mesh is linear in its size again. In Blender 5.x an indexed read of a corner attribute (`layer.uv[i].vector`, `corner_normals[i].vector`, `color_attributes.active_color.data[i].color`) costs time proportional to the size of the collection, and the extractor read them once per corner, so the export was quadratic: a 66,177-vertex relief grid took 315 s to export (extracting a 129 x 129 grid alone: 34 s). The three accessors now read everything with one `foreach_get` each (`_read_all`, `_tuple_accessor`) and fall back to the element-wise read when Blender refuses the bulk read; the relief exports in 0.67 s (the 129 x 129 extraction in 0.6 s) and the X3D is byte-identical apart from the file name in its meta. New test `tests/test_extract_bulk_reads_bpy.py` fails on the old code.
- X3D 4.0 export writes `creaseAngle` from the sharp edges of a smooth-shaded mesh (just under the smallest dihedral angle among them) instead of always pi, so a welded box imported with `creaseAngle 0.35` leaves with its edges sharp. A mesh with no sharp edge still exports fully smooth.
- X3D 4.0 export with **Export animation** writes an animated shape key as a `CoordinateInterpolator` routed into the mesh's `Coordinate` (`set_point`), so a morph survives X3D to Blender to X3D. The `Coordinate` holds the first sampled state, the interpolator's keys are the shape-key keyframes (every `animation_step` frame as well when a keyframe is not LINEAR) and its `TimeSensor` shares the scene timer; meshes with identical morphs share one interpolator, and keyValue is written without trailing zeros. Before, such a mesh was written as the pose at the current frame and the motion was lost: the Shroud 1532 fold went from 1.5 MB to 0.16 MB. Now it round-trips at 1.56 MB, valid X3D 4.0, and re-imports to the same positions at every sampled time. Meshes with modifiers still export the evaluated pose; without Export animation nothing changes.
- A `CoordinateInterpolator` routed into a `Coordinate`'s `set_point` imports as shape keys with keyframed values, so a deforming `IndexedFaceSet` moves in Blender and leaves as glTF morph targets. Each distinct state of the interpolator is one relative shape key (a state equal to the mesh's own points is the Basis); its value is 1 at its keys and 0 at the neighbouring keys, linear in between, which reproduces the interpolator's linear blend, and key times follow the `TimeSensor` (`cycleInterval` at the scene frame rate, end frame extended). Before, the ROUTE was ignored and the mesh stayed frozen at its rest points: the Shroud fold morph (63 keys over two 1,105-point cloths) lost about 93% of its motion. Matches the X3D text to 2e-6 at seven sampled times. Meshes whose unused points were culled keep their point mapping (`x3d_point_map`); the Coordinate DEF is kept as `x3d_coord_def`, and the object records `x3d_morph_coord`, `x3d_morph_interpolator` and `x3d_morph_states`. Not yet exported back to X3D (shape keys leave as glTF morph targets only).
- An `ElevationGrid` whose `xDimension` differs from its `zDimension` imports as the grid it is: the vertices were numbered x-outer, z-inner while the faces, the per-vertex colours and a default texture mapping all indexed them z-outer, x-inner, which only agree on a square grid. Before, a 151 x 121 terrain (the Giza Sphinx-site ground) came in as long vertical fins; square grids were never affected.
- Lines survive the X3D 4.0 export: a curve or a mesh that has edges and no faces (what an imported `IndexedLineSet` becomes in Blender) is written as an `IndexedLineSet` of polylines. Before, it produced no geometry, so line-based content (the twelve evidence-graded travel legs of the Shroud journey scene) vanished from the export.
- An `ElevationGrid` with a `Color` or `ColorRGBA` child imports instead of stopping the whole import with "internal error setting the array": the per-corner colour attribute holds four floats per corner and the importer gave it three. `ColorRGBA` keeps its alpha; `Color` gets an opaque one.
- A texture's alpha makes the imported surface transparent, as X_ITE draws it: the colour texture's alpha (an `UnlitMaterial`'s `emissiveTexture`, else the `baseTexture`) times `1 - transparency` (a Math node set to Multiply) feeds the Principled *Alpha*, and the material renders *Blended*. Before, texture alpha was read only for a `PhysicalMaterial` with `alphaMode` BLEND or MASK, and there without the material's `transparency`, so with AUTO (the default) an RGBA glow or halo on a quad, and any `UnlitMaterial`, rendered as an opaque rectangle. With AUTO only an image with a pixel that is not opaque counts (RGB images are not scanned; an image is scanned once per import), so files without texture alpha import as before; MASK cuts the product at `alphaCutoff`. The socket keeps `1 - transparency` as its value, so the export is unchanged.
- An `UnlitMaterial` with an `emissiveTexture` imports as the texture times its `emissiveColor` (a Mix node set to Multiply), as X_ITE draws it. Before, the texture alone fed Emission Color and the colour was lost: a warm lamp glass (`emissiveColor` 0.96 0.845 0.69 over a glow texture) rendered as the bare texture. A white colour (the default) adds no node, and the colour stays on the socket, so the export is unchanged.
- An X3D `Switch` imports every child, as before, but shows only the one its `whichChoice` names, as an X3D browser does: the others are hidden in the viewport and the render and tagged `x3d_switch_hidden` (-1, the default, shows none; nested Switches must all choose the branch; Metadata and ROUTE elements are not counted as children). Before, every child showed at once, so a scene's alternatives were drawn on top of each other.
- Importing ROUTE animation no longer stops at the second object under one animated Transform (it raised UnboundLocalError): every object under it is keyed, animated Transforms after it are keyed too, and the end frame follows the TimeSensor.
- Importer reads the Geometry2D nodes Rectangle2D (a quad) and Disk2D (a disc, an annulus or, with equal radii, a circle) in the local XY plane, with texture coordinates; both were skipped before.
- Importing an X3D 4.0 scene and exporting it again as X3D 4.0 keeps what used to be lost: light `intensity` above 1 (lights made in Blender stay capped at 1), `shadows`, `shadowIntensity` and `ambientIntensity`, Shape `castShadow`, Viewpoint `description`, every head `meta` (repeated names included; the dialog's "no licence" is no longer written as `license NONE`), Shape `Metadata*` nodes and the Background sky and ground gradients. See "X3D fields kept as custom properties" in the README.
- Light shadows follow X3D on import: a light without `shadows="true"` imports with Blender shadows off (X3D's default is false), and a Blender light with shadows on exports `shadows="true"`.
- The X3D 4.0 export no longer writes an image a second time as `occlusionTexture` because the letters "ao" appear somewhere in its path, for example in a folder such as /home/joao/ or in a file name such as chaos.png. The occlusion lookup now reads only the node, image and file name, and "ao" has to be a word of its own (`rock_AO.png`, `RockAO.png`).
- Importing a second file with textures in the same Blender session (for example after File > New) no longer fails with "StructRNA of type Image has been removed": the importer now clears its texture cache per import, as it already did for materials.
- Light strength round-trips: point and spot lights were exported as `energy / 1.75` (capped at 1.0) but imported without the factor, so each round trip dimmed them by 1.75. Import now multiplies back. Sun strength is written unscaled on both export paths (the legacy path used to divide it too) and imported 1:1. Energies above 1.75 (sun: above 1.0) are still clamped, with one exception: the X3D 4.0 path writes lights imported from X3D unclamped, since their file intensity is known. The X3D 3.3 path clamps every light, as its schema requires.
- Splat round trip is exact at any size: the importer no longer drops multi-megabyte elements (Expat 2.6+ deferred them past the point where minidom stops reading, so 4.1 files with about 18,000 or more splats imported nothing), and GaussianSplats arrays are written as the shortest text that reads back as the same float32 instead of `%.6f` (which zeroed small scales). 20,000 degree-3 splats now export and import bit-exact.
- Spherical harmonics are written and read in whole degrees only (a partial degree is dropped, as KHR_gaussian_splatting and X_ITE treat it); PLY files with degree-4 coefficients log a warning that degree 4 is dropped. Import scales splat `scales` by the unit factor, like `positions`. Non-finite splat values stop the export with a message instead of writing an invalid file.
- Blender 5.3 native splats: PointClouds in Blender's splat layout (`scale`, `rotation`, `radiance:base`, `radiance:sh_N`, type `GAUSSIAN_SPLAT`) export as the X3D 4.1 GaussianSplats node, so splats Blender 5.3 imports from PLY, SPZ, glTF or USD can leave Blender as X3D. On 5.3+ the importer builds that native PointCloud for GaussianSplats nodes and .ply/.splat Inlines; earlier versions keep the splat mesh (`X3D_SPLAT_IMPORT=mesh|pointcloud` overrides).
- Extension renamed for side-by-side installs: id `x3d_blender_io`, name "X3D Blender I/O", version 2.6.0 (upstream keeps `web3d_x3d_vrml2_format`). Enable one of the two at a time; both register `import_scene.x3d` and `export_scene.x3d`.
- New **X3D Version** export option: X3D 3.3 (unchanged upstream writer) or X3D 4.0 (PhysicalMaterial / UnlitMaterial, PBR textures, UVs, normals, vertex colours, per-material Shapes, DEF/USE sharing, path-mode texture handling, self-validation).
- Importer understands PhysicalMaterial and UnlitMaterial, Appearance alphaMode/alphaCutoff and IndexedFaceSet solid; object and mesh names survive round trips.
- X3D 4.0 path now writes nested Transform hierarchy, PointLight/SpotLight/DirectionalLight, Viewpoint, NavigationInfo, Background, curve/surface/text objects as meshes, and optional sampled animation (TimeSensor, interpolators, ROUTEs).
- Armatures export as HAnim 2.0 humanoids: joint hierarchy, skinned meshes with weights, and joint rotation animation relative to rest.
- HAnim import: HAnimHumanoid becomes an armature with bones, skinned meshes with vertex groups and an Armature modifier, and joint ROUTE animation becomes pose-bone keyframes.
- Inline bridge: an Empty with `x3d_inline_url` exports as Inline; Inline imports as that Empty with the asset underneath (X3D/VRML recursively, glTF via Blender's importer, .ply/.splat as splat meshes), and inlined content is not re-exported.
- New **X3D 4.1 draft** export option writes Gaussian-splat meshes as the draft GaussianSplats node; the 4.0 option degrades them to a coloured PointSet. The importer reads the node back into a splat mesh.
- Importer rebuilds keyframe animation from XML ROUTEs (TimeSensor + interpolators) as world-space keyframes on the affected objects.
- Importer reads plain SFString attributes (e.g. Viewpoint description) in the XML encoding.
- Swatch-book fixture (`tools/swatch_book.py`) and export → validate → reimport test under Blender 5.2.
- X3D 4.0 and 4.1 headers declare `<component name="Shape" level="2" />` when PhysicalMaterial or UnlitMaterial is written (the Immersive node lists in Annex E Table E.3 and X3DUOM leave both out), and Geometry2D level 2 when the Circle2D fallback is written.

# Release Notes

> Note: These release notes are also published on the extensions page and contain the most important changes of each release.
> For more detailed info view the commit history.

### v2.5.1
- fixes (import):
  - color per face is now a separate case again compared to vertex color
  - quotes, backslashes and leading spaces in text objects get parsed correctly, a new mfstring handler got implemented which also results in same results for x3d and vrml
  - IndexedShape Import is more fault tolerant: less points than coordIndex doesn't lead to an error anymore

### v2.5.0
- features:
  - batch export options
  - support drag/drop popup and collection exporter UI
  - enable import support of .x3dv and .x3dz
  - export support enhanced of basic material node setups of diffuse, emission, image/movie texture, texture transform, alpha
  - import/export support of sound node as speaker object
  - optional metadata and copyright export input fields
- fixes:
  - deprecated api for 4.4+
  - vertex color missing without x3d material node
  - fontstyle import improvements
  - minor issues

### v2.4.4
- add: download of web based image textures if url is valid
- fix: limit options of image export path, as the other options are invalid for x3d
- fix: single file import via load function (programmatically, not GUI)
- fix: update of global_scale export when file_unit changes via load function (programmatically, not GUI)
- refactor: minor code cleanups

### v2.4.3
- fix: re-add image texture export support with several file_path options
- fix: parsing of single value MFString for image texture url
- fix: image rotation by TexTransform node

### v2.4.2
- fix: blender 4.3 deprecated api usage: Transparent materials get now set via surface_render_method, because the old api is not supported anymore and import would fail

### v2.4.1
- fix: keyerror on text import if font style is not provided
- fix: update missed old api usage for spot lights export

### v2.4.0
- features import:
  - scale input field
  - file unit type selector for easier unit scale conversion
  - import as collection checkbox
  - solidify checkbox and value slider (adds a solidify modifier)
  - multi-file import (all selected files in the blender file explorer get imported at once)
  - basic drag-drop filehandler for single files
  - improved text import: font family, style, justify and spacing get now parsed
  - support for movie texture
  - curve objects can now have materials
- features export:
  - file unit type selector for easier unit scale conversion
  - limit to selected, visible, active collection checkbox; note: they influence each others export selection iteratively
- features general:
  - changed default forward axis to -Z (before was Z)
  - AI-based translation of display UI messages for multiple major languages
  - bug report button in addon settings
- bugfixes import:
  - vrml error on text import (text object of vrml can now get imported)
  - box inside out (flipped normals)
  - image texture rotated counterclockwise (added a mapping node to the shader nodes)
  - extrusion import error if length of scale less than spine (in this case the last value of scale gets now reused)
  - uv is not defined for elevation grid (was a typo, now import works)
  - emission strength was 0 (now is 1)

### v2.3.6
- fix: wrong color for per vertex color when no index is given for a specific case
- updated license to gpl 3.0 or later

### v2.3.5
- fixes wrl import:
  - better handle missing or invalid colorIndex node
  - ignoring empty shape nodes to fix import errors
  - better handle pixel image textures: update api usage, multiline support, ignore empty data
  - parsing of multiline VRMLscripts
  - add check if USE-based cache is set in IndexedFaceSet
  - fix per vertex normals (split normals) for custom smooth shading
  - improve vertex colors import: update api usage, fix inconsitencies, add colorAttribute node to material setup
- fixes x3d export:
  - disable h3d extensions support (broken since blender 2.8) temporarily

### v2.3.4
- Fix error importing files with one color for all faces



