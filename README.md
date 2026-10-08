# Web3D X3D/VRML2 format Add-on — X3D 4.0 fork

This repository is HagopJay's working fork of the Blender extension
[Web3D X3D/VRML2 format](https://extensions.blender.org/add-ons/web3d-x3d-vrml2-format)
(upstream: [projects.blender.org/extensions/io_scene_x3d](https://projects.blender.org/extensions/io_scene_x3d)).
Its purpose is to bring the exporter and importer up to **X3D 4.0** (ISO/IEC 19775-1:2023)
so Blender can trade physically based scenes with X3D 4 browsers (X_ITE, X3DOM, Castle, FreeWRL)
and with AI tooling built on the X3D Consortium's validated encodings. Everything upstream
still works unchanged; the new path is opt-in.

## What the fork adds (Milestones 1 and 2: PBR materials and scene structure)

Export dialog, **Include** panel, new **X3D Version** selector:

| Option | What you get |
| --- | --- |
| **X3D 3.3 (Material, classic)** — default | The upstream exporter, unchanged: Phong `Material`, lights, cameras, hierarchy, text, curves. |
| **X3D 4.0 (PhysicalMaterial, PBR)** | Principled BSDF → `PhysicalMaterial` (baseColor, metallic, roughness, emissiveColor, transparency, normalScale, occlusionStrength) with glTF-style `baseTexture` / `metallicRoughnessTexture` / `normalTexture` / `emissiveTexture` / `occlusionTexture` children; Emission-only trees → `UnlitMaterial`; `Appearance alphaMode="BLEND|MASK"`; `IndexedFaceSet` with `Coordinate`, `Normal` (when *Normals* is on), `TextureCoordinate` (active UV map) and `ColorRGBA` (active colour attribute); one `Shape` per material slot; `solid` from *Backface Culling*; `creaseAngle` from smooth shading; modifiers and triangulation honoured; shared mesh data and materials written once with `DEF` and reused with `USE`; texture paths follow the *Path Mode* setting exactly as the 3.3 exporter does. Nested `Transform` hierarchy (*Hierarchy* on) or flat world transforms; lights as `PointLight` / `SpotLight` / `DirectionalLight` (headlight off when present); cameras as `Viewpoint`; curves, surfaces and text objects as meshes; world colour as `Background`; optional **Animation** sampling of object transforms over the frame range into one `TimeSensor` with `PositionInterpolator` / `OrientationInterpolator` nodes and `ROUTE`s. Object types the path cannot write yet are listed in `<meta name="info">`. |

Import: `PhysicalMaterial` and `UnlitMaterial` now become Principled BSDF node trees
(metallic/roughness texture split into G and B channels, normal map with strength, occlusion kept as a labelled node,
`alphaMode` → *Blended* / *Dithered* with an alpha-cutoff node), `solid` → *Backface Culling*,
and object and mesh names survive the round trip (`OB_` / `ME_` / `MA_` prefixes are stripped).

The X3D 4.0 writer validates its own output: XML well-formedness always, and field types and
ranges through the Web3D `x3d` Python package when it is installed (`pip install x3d`).

### Tests

```
cd tests
python -m unittest test_emit_x3d40 test_parse_x3d40 test_material_analysis   # no Blender needed
python -m unittest test_roundtrip_bpy   # needs Blender's `bpy` module (pip install bpy) or run inside Blender
```

`tools/scene_fixture.py` builds a parented cube, three lights, a camera, a text object and a keyframed cube; its round-trip test checks nesting, light types, viewpoint, text geometry, interpolators and ROUTEs, and that everything lands back in world space on import. Known gap: the importer does not yet rebuild keyframes from XML `ROUTE`s (its animation reader is VRML-only), so animation is export-only for now.

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
