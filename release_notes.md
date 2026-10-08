## Unreleased (x3d-blender-io fork)
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



