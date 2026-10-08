# Blender X3D import/export: upstream state and the gap to "cutting edge"

Written 2026-10-08 for the x3d.io project. Everything below is cited; items marked *(inferred)* were not verified directly.

## 1. Where Blender's X3D support lives today

| Item | State | Source |
|---|---|---|
| Distribution | Dropped from Blender core in 4.2 (it shipped bundled through 4.1). Now the community extension **"Web3D X3D/VRML2 format"** (id `web3d_x3d_vrml2_format`) on extensions.blender.org, installed via Preferences > Get Extensions. | [extension page](https://extensions.blender.org/add-ons/web3d-x3d-vrml2-format/), [Marchetti, Dec 2025](https://web3d.org/pipermail/x3d-ecosystem_web3d.org/2025-December/000662.html) |
| Source repo | `https://projects.blender.org/extensions/io_scene_x3d` (Blender's Gitea). Issues and wiki live there too. | [manifest](https://projects.blender.org/extensions/io_scene_x3d/raw/branch/main/source/blender_manifest.toml) |
| Maintainer | Cedric Steiert ("Bujus_Krachus"), self-described junior developer and student. Copyright lines also credit Vincent Marchetti (2024-25), Hombre57 (2024), and the original authors Campbell Barton, Bart, Bastien Montagne, Seva Alekseyev. | manifest, [issue #21](https://projects.blender.org/extensions/io_scene_x3d/issues/21) |
| Latest release | **2.5.1, 2025-03-18**. No release since (19 months as of today). ~57k downloads. GPL-3.0-or-later. | [version history](https://extensions.blender.org/add-ons/web3d-x3d-vrml2-format/versions/) |
| Blender compatibility | Manifest says `blender_version_min = "4.2.0"` with no max, so it installs on 4.2 LTS, 4.5 LTS, and 5.x. Don Brutzman reported seeing it in Blender 5.0.1 (Dec 2025). Nobody has published a 5.0/5.1 test result. *(inferred)* The code touches no API that 5.0 removed (it has no compositor, Action, or Grease Pencil code), and 5.1's Python 3.13 switch only breaks compiled add-ons, so it very likely runs on 5.x. Must be tested. | manifest, [Blender 5.0 breakages](https://devtalk.blender.org/t/upcoming-blender-5-0-release-compatibility-breakages/37078), [5.1 Python 3.13 note](https://www.strayspark.studio/blog/blender-5-1-addon-compatibility-python-313-guide) |
| Consortium's own repo | `github.com/Web3DConsortium/BlenderX3DSupport` is **retired**: its README now points to the extension repo, and Marchetti wrote in Sept 2024 that PRs to it cannot reach Blender. Its three stated goals (image textures on export, X3D 3.3 Appearance/Material, X3D v4 PhysicalMaterial export) were never finished there. | [repo](https://github.com/Web3DConsortium/BlenderX3DSupport), [Carlson/Marchetti, Sept 2024](https://web3d.org/pipermail/x3d-ecosystem_web3d.org/2024-September/000066.html) |
| Who is working on it | The Web3D **X3D-Ecosystem Working Group** (Vincent Marchetti, John Carlson, Aaron Bergstrom, Don Brutzman, Michalis Kamburelis of Castle Game Engine) contributes through the extension repo. Marchetti restored ImageTexture export and fixed Text/MFString in 2024-25; the Dec 2024 Blender teleconference set the roadmap below. | [Dec 2024 telecon](https://web3d.org/pipermail/x3d-public_web3d.org/2024-December/020973.html), [Marchetti, Mar 2025](https://web3d.org/pipermail/x3d-ecosystem_web3d.org/2025-March/000284.html) |

### Release history (all versions require Blender 4.2+)

- 2.3.x (May-Aug 2024): migration to the extensions platform, VRML import fixes, GPL-3 relicense. H3D exporter extension temporarily disabled.
- 2.4.0 (Nov 2024): scale/unit controls, import-as-collection, drag-and-drop and multi-file import, movie textures, materials on curves, default forward axis changed to -Z. 2.4.1-2.4.4 fixed Blender 4.3 API deprecations and **restored image texture export** (lost since 2.80) with COPY/RELATIVE/STRIP path modes and web-hosted texture download.
- 2.5.0 (Feb 2025): batch export, collection exporter UI, `.x3dv`/`.x3dz` import, Sound/speaker round-trip, optional `<meta>` fields, Blender 4.4 deprecation fixes.
- 2.5.1 (Mar 2025): import fixes (per-face colour, Text quoting, tolerant IndexedFaceSet).

### Open work in the repo

Issue #21 ("improve x3d import/export: review changes on Web3DConsortium/BlenderX3DSupport", opened Sept 2024, still open, "help wanted") is the merge point for Consortium work. The maintainer's conditions: Blender 4.2+ only, don't break basic import/export, ship user docs plus docstrings, and GitHub forks are fine. John Carlson listed x3dv/x3dj import-export, HAnim parsing, and VRML import changes as candidates. I could not read the full issue list (the Gitea API and issue pages are blocked from this container), so counts of open bugs are missing.

## 2. What the exporter and importer actually do (from the main-branch source)

**Exporter (`export_x3d.py`)** writes `<X3D profile="Immersive" version="3.0">` with the 3.0 DTD. Nodes written: Transform, Group, Shape, Appearance, **Material (legacy Phong only)**, one ImageTexture or MovieTexture per material, TextureTransform, IndexedFaceSet/IndexedTriangleSet with Coordinate/Normal/TextureCoordinate/ColorRGBA, PointLight/SpotLight/DirectionalLight, Viewpoint, NavigationInfo, Background (flat colour, optional skybox), Fog, Sound/AudioClip, Collision, `<meta>` tags in `<head>`. Gzip to `.x3dz`. Materials: diffuse and alpha come from a Principled BSDF search, but specular comes from legacy `specular_intensity`, ambient is hard-coded 0, and emissive is effectively always black (multiplied by the zero ambient). Header comments admit: one material per mesh, one UV layer, no texture array.

**Importer (`import_x3d.py`)** parses XML X3D with `xml.dom.minidom` and VRML/x3dv with a hand-written parser (PROTO/EXTERNPROTO handled for VRML, with TODOs). Geometry: all Geometry3D and Rendering nodes (IndexedFaceSet, triangle sets, strips, fans, LineSet, PointSet, ElevationGrid, Extrusion, primitives). Lights, Viewpoint, image/pixel textures, TextureTransform (Seva Alekseyev's 2015 work). TODOs in code: X3D Inline not implemented, PROTO instances with Inline "won't work", no ROUTE/interpolator logic despite a `getRouteIpoDict` stub.

## 3. Feature gap: extension 2.5.1 vs X3D 4.0 vs Blender's glTF add-on

X3D 4.0 (ISO/IEC 19775-1:2023) deliberately aligned its Shape component with glTF 2.0: `PhysicalMaterial` (baseColor, metallic, roughness, emissiveColor, normalScale, occlusionStrength, transparency, plus baseTexture, metallicRoughnessTexture, normalTexture, occlusionTexture, emissiveTexture, each with a `...TextureMapping`), `UnlitMaterial`, texture slots on legacy `Material`, and `alphaMode`/`alphaCutoff` on `Appearance` ([spec](https://www.web3d.org/specifications/X3Dv4/ISO-IEC19775-1v4-IS/Part01/components/shape.html)). Blender's bundled glTF add-on already covers all of that from the Principled BSDF ([glTF add-on manual](https://docs.blender.org/manual/en/latest/addons/import_export/scene_gltf2.html)). So "cutting edge" has a concrete meaning: **X3D parity with what Blender already does for glTF, plus the X3D-only features glTF lacks.**

| Capability | glTF add-on (Blender core) | X3D extension 2.5.1 | X3D 4.0 target |
|---|---|---|---|
| Output version/profile | glTF 2.0 | X3D **3.0** Immersive | X3D 4.0 (Interchange or Immersive), 3.3 fallback option |
| PBR material | Principled BSDF <-> metallic-roughness | legacy Material only, emissive broken | PhysicalMaterial both ways; Material and UnlitMaterial as options |
| Texture slots | baseColor, metallicRoughness (packed), normal, occlusion, emissive, plus clearcoat/sheen/transmission/volume/IOR/specular/anisotropy extensions | one diffuse ImageTexture | the five PhysicalMaterial textures with per-slot UV mapping; alphaMode/alphaCutoff; emissive strength |
| Texture transform | KHR_texture_transform | rotation/scale/translation from a Mapping node (export only) | TextureTransform with the same five parameters (Dec 2024 decision) |
| Multiple materials per mesh | yes | **no** (one material, one UV layer) | split Shape per material index |
| Vertex colour | yes | yes (export ColorRGBA) | ColorPerVertex with premultiplied material colour (Dec 2024 phase 1) |
| Animation | object transforms, shape keys, skinning, NLA actions, sampling | **none** (sound start/stop only) | TimeSensor + Position/Orientation/Scalar/Coordinate interpolators + ROUTE; layered Actions in Blender 5.0 |
| Skeletal / humanoid | glTF skins | none | **HAnim 2.0** (HAnimHumanoid/Joint/Segment/Site/Motion), LOA levels; Carlson's prototype loaders exist outside the extension |
| Lights | KHR_lights_punctual | Point/Spot/Directional both ways | same plus X3D 4.0 light attenuation fields and EnvironmentLight |
| Camera | yes | Viewpoint both ways | Viewpoint, OrthoViewpoint, NavigationInfo |
| Scene structure | nodes, instancing | Transform/Group; no Inline, Switch, LOD | Inline (import TODO), Switch, LOD, Collision, DEF/USE instancing |
| Metadata | extras/custom properties | `<meta>` in head | `<meta>` plus MetadataSet/MetadataString on nodes from custom properties |
| Encodings | .glb, .gltf, embedded | XML .x3d, gzip .x3dz; import .x3dv | XML, Classic VRML, **JSON (19776-5, draft)**, .x3dz; Python binding 19777-6 / X3DPSAIL |
| Compression | Draco | gzip | gzip; glTF-style binary buffers are out of scope for X3D 4.0 |
| Gaussian splats | none in core glTF add-on yet (KHR_gaussian_splatting ratified 2026) | none | X3D 4.1 CD `GaussianSplats` node (positions, scales, orientations, opacities, SH degree 0-3 coefficient arrays, colorSpace; inline data only, no url). Blender 5.3 (alpha, release scheduled 2026-11-10) imports PLY and SPZ splats natively via PR #163102 but has **no export**, so a 5.3 scene could be written to X3D 4.1 splats; the node is in no X3D browser yet. *(verified from two secondary reports of the Blender PR and release notes; the release-notes page itself did not load)* |
| Collection exporter | yes | yes (2.5.0) | keep |
| Tests | Khronos sample assets, CI | none visible | round-trip suite on the X3D Example Archives (Basic, HAnim, X3D4 PBR examples) |
| Blender versions | core | 4.2+, untested on 5.x | 4.2 LTS, 4.5 LTS, 5.0, 5.1 CI matrix |

Round-trip fidelity on the X3D example archives is unmeasured anywhere; no published test results exist for the extension.

## 4. What the Working Group is doing right now (so we don't collide)

- Nov-Dec 2025: Aaron Bergstrom polled the list on prioritising PBR export; Marchetti answered with a plan: translate the shader-node tree to Material/PhysicalMaterial, use the glTF exporter as the guide, start with a "swatch book" of one-material-per-16:9-quad test .blend files, hand-author the expected X3D for each ([Dec 4 2025](https://web3d.org/pipermail/x3d-ecosystem_web3d.org/2025-December/000626.html)).
- Dec 16 2025: Marchetti published early PhysicalMaterial results, so far via a two-step glTF -> Castle Game Engine conversion plus hand edits, validated in three viewers; direct export is "in progress" and texture-driven metallic/roughness was untested ([Dec 16 2025](https://web3d.org/pipermail/x3d-ecosystem_web3d.org/2025-December/000655.html)).
- John Carlson's HAnim import/export work lives in his own repos (coderextreme/X3DJSONLD `blend/` scripts, his yottzumm fork of io_scene_x3d last touched Nov 2024) and is still "not working well or organised" for animation ([Dec 2025 reply](https://web3d.org/pipermail/x3d-ecosystem_web3d.org/2025-December/000658.html), [July 2024](https://web3d.org/pipermail/x3d-ecosystem_web3d.org/2024-July/000024.html)).
- X3D JSON encoding (19776-5) and Python binding (19777-6) are still drafts targeted 2026-27 ([standards progress](https://www.web3d.org/x3d/progress)).

I could not read the 2026 list archives (rate-limited), so anything merged after Dec 2025 is unconfirmed.

## 5. What "cutting edge" should mean for this project

1. **PBR parity, both directions**, driven by the same Principled BSDF mapping the glTF add-on uses, with X3D 4.0 output and a 3.3 fallback. This is also the WG's top priority, so it is the natural place to contribute rather than fork.
2. **Animation and HAnim**: the biggest X3D-only gap. Blender 5.0's layered Actions are the right moment to design it.
3. **Multi-material and multi-UV meshes**, Inline/Switch/LOD, node metadata.
4. **JSON and Python-binding output** via X3DPSAIL once 19776-5 settles.
5. **A test harness**: round-trip the X3D Example Archives and the Khronos glTF sample assets on 4.2/4.5/5.0/5.1 in CI. Nothing like this exists today.
6. **Gaussian splats**: once Blender 5.3 ships, exporting its new splat object to the X3D 4.1 `GaussianSplats` node would make the extension the first X3D splat writer anywhere. Cheap to prototype because the draft node mirrors KHR_gaussian_splatting field for field.
7. **AI-era extras** (where this project differentiates): an MCP tool surface over the importer/exporter so an agent can author, validate and view X3D scenes from Blender; a validator pass against the X3D 4.0 schema on export.

A first milestone small enough to prove: the extension installs cleanly on Blender 4.5 LTS and 5.0/5.1, and a swatch-book of five materials round-trips Blender -> X3D 4.0 PhysicalMaterial -> Blender with matching base colour, metallic, roughness, normal and emissive, validated with the X3D schema and viewed in X_ITE and Castle Game Engine. That overlaps Marchetti's swatch-book plan, so it should be coordinated with him.

Sources for the splat row: [cinevva](https://app.cinevva.com/news/2026-09-16-blender-5-3-gaussian-splats), [radiancefields](https://radiancefields.com/blender-5.3-will-bring-native-3d-gaussian-splat-import-and-rendering), [X3D 4.1 schema doc](https://www.web3d.org/specifications/X3dSchemaDocumentation4.1/x3d-4.1_GaussianSplats.html).

## 6. Open questions for HagopJay

- Where the prior Blender module work sits (device folder, zip, Drive) and whether it was built on the old bundled `io_scene_x3d` or on something else.
- Which Blender versions matter (4.5 LTS is the safe target; 5.x is where new users are).
- Whether to work upstream (PRs to the extension repo, coordinated with Marchetti) or in a separate `hagopjay/x3d-blender-io` repo that tracks upstream. Recommendation: upstream for PBR, a separate repo only for the AI/MCP layer.
