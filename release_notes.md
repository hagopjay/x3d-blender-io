## Unreleased (x3d-blender-io fork)
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



