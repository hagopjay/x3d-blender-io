# Blender Modern X3D Technical Deep Dive

## Purpose

This document is the authoritative checkpoint record for the current modernized `io_scene_x3d` technical preview.
It explains what was built, how it works, what is proven, what was fixed, and where the system still has hard limits.

The preview now demonstrates three connected tracks:

1. Blender -> modern X3D 4.0 direct export
2. Blender -> glTF/GLB -> X3D `Inline` -> X_ITE runtime
3. X3D `Inline` wrapper -> Blender re-import through a native modern import path

This is not yet a production-complete addon rewrite.
It is a serious technical preview with working infrastructure, validated runtime compatibility, and proof artifacts.

## Repo Areas

Primary addon code:

- `io_scene_x3d/source/`

Design/roadmap docs:

- `io_scene_x3d/docs/IMPLEMENTATION_GUIDELINES.md`
- `io_scene_x3d/docs/PHASED_ROADMAP.md`
- `io_scene_x3d/docs/TASK_BREAKDOWN.md`

Preview bundle:

- `demo/investor_poc/`

Blender automation:

- `io_scene_x3d/tools/blender_modern_export_demo.py`
- `io_scene_x3d/tools/blender_modern_import_demo.py`
- `io_scene_x3d/tools/blender_modern_multi_inline_import_demo.py`

Regression coverage:

- `io_scene_x3d/tests/test_emit_x3d40.py`
- `io_scene_x3d/tests/test_parse_x3d40.py`
- `io_scene_x3d/tests/test_material_analysis.py`

## Guiding Authorities

The implementation strategy intentionally borrows from two external codebases:

- `x_ite-main`
- `x3d-edit`

They serve different roles.

### X_ITE

`x_ite-main` is treated as the runtime-semantic authority.
It is the strongest practical reference for:

- `PhysicalMaterial` semantics
- glTF material mapping
- X3D `Inline` loading behavior
- runtime expectations for X3D 4.x documents
- texture/mapping behavior

This preview bundle uses X_ITE directly in `demo/investor_poc/x_ite/`.

### X3D-Edit

`x3d-edit` is treated as the authoring/validation authority.
It reinforces which modern X3D nodes should be treated as canonical authoring targets, especially:

- `PhysicalMaterial`
- `UnlitMaterial`
- `Inline`
- HAnim family nodes
- modern texture transform nodes

### Architecture Decision

The Blender addon rewrite is not XML/XSLT-driven.
The core runtime architecture is Python-first and IR-driven.
XML/XSLT-style assets remain useful for validation and schema alignment, but not for scene extraction or business logic.

## Current Architecture

The addon is now split into clearer responsibilities.

### Scene IR

File:

- `io_scene_x3d/source/ir.py`

This module defines the internal representation used by modern export/import code.

Key dataclasses:

- `IRMetadata`
- `IRTransform`
- `IRTextureTransform`
- `IRTextureRef`
- `IRMeshGeometry`
- `IRPBRMaterial`
- `IRInlineAsset`
- `IRViewpoint`
- `IRInstance`
- `IRScene`

Important `IRPBRMaterial` fields:

- `base_color`
- `emissive_color`
- `metallic`
- `roughness`
- `normal_scale`
- `occlusion_strength`
- `alpha_mode`
- `alpha_cutoff`
- `double_sided`
- `unlit`
- `base_color_texture`
- `metallic_roughness_texture`
- `normal_texture`
- `occlusion_texture`
- `emissive_texture`

Important `IRScene` fields:

- scene metadata
- source path/version
- extracted geometries
- analyzed materials
- scene instances
- inline assets
- viewpoints
- navigation types
- diagnostics

This IR boundary is the key architectural change.
The emitter no longer needs to inspect Blender node trees directly, and the importer no longer needs to create Blender content while parsing raw XML.

### Extraction

File:

- `io_scene_x3d/source/extract.py`

Responsibilities:

- iterate scene objects
- collect mesh geometry payloads
- detect reusable geometry/material sources
- build `IRInstance` records with transforms
- analyze unique Blender materials

Current geometry behavior:

- extracts real `IndexedFaceSet`-style mesh payloads
- supports DEF/USE-like reuse through shared geometry naming
- still conservative
- still not a full production mesh serializer

### Material Analysis

File:

- `io_scene_x3d/source/material.py`

This is the main modern material walker.

It now supports more than raw Principled defaults.
The current analyzer can evaluate:

- direct Principled sockets
- direct Emission shaders
- `Mix Shader` branches containing Principled and Emission
- image textures
- mapping transforms
- `Normal Map`
- `Separate Color` / `Separate RGB`
- `NodeReroute`
- `Value`
- `Math`
- `MixRGB`
- `Clamp`
- `Map Range`

That means scalar and color values can now survive simple node processing chains rather than collapsing to defaults.

Examples of values that are now resolvable through graph logic:

- metallic multiplied by a factor
- roughness remapped and clamped
- base color tinted through `MixRGB`
- normal strength carried from a `Normal Map` node
- AO strength found from a labeled value node

Texture channel handling currently targets:

- base color
- metallic/roughness
- normal
- emissive
- occlusion

Current heuristics:

- texture discovery follows links upstream from relevant Principled sockets
- AO texture/value can also be found through label/name heuristics such as `ao` and `occlusion_strength`
- texture transform comes from upstream `Mapping`

Legacy compatibility was preserved.
`material_node_search.py` now acts as a compatibility surface over the modern analyzer so the old exporter code path does not break.

### Modern Emitter

File:

- `io_scene_x3d/source/emit_x3d40.py`

This is the dedicated X3D 4.0 emitter.
It is now a real modern-path module instead of a placeholder.

Responsibilities:

- write X3D 4.0 XML
- emit scene metadata
- emit diagnostics
- emit material gallery for inspected materials
- emit geometry library
- emit scene instances
- emit `PhysicalMaterial` / `UnlitMaterial`
- emit texture fields
- emit texture transforms
- reuse material and geometry defs

Current direct export characteristics:

- X3D version `4.0`
- profile `Immersive`
- `Appearance` reuse through `DEF/USE`
- reusable geometry library through hidden `Switch`
- `IndexedFaceSet` mesh reuse through `DEF/USE`

### Modern Import Path

Files:

- `io_scene_x3d/source/import_x3d.py`
- `io_scene_x3d/source/parse_x3d40.py`
- `io_scene_x3d/source/populate.py`
- `io_scene_x3d/source/bridge_gltf.py`

This path is gated by:

- `BLENDER_X3D_IMPORT_TARGET=MODERN_INLINE`

Responsibilities:

- parse X3D 4.0 wrapper scenes
- collect metadata, viewpoints, navigation modes
- collect `Inline` assets with nested transform composition
- dispatch GLB/GLTF assets into Blender’s glTF importer
- wrap imported assets with provenance-aware roots/collections
- create cameras from `Viewpoint`

This is not yet a general full X3D importer rewrite.
It is a modern focused import path centered on `Inline` interop and scene metadata/viewpoint recovery.

## Export Flow

### Legacy vs Modern Routing

File:

- `io_scene_x3d/source/export_x3d.py`

The public exporter still exists, but now routes through a shared orchestration layer.

Current control switch:

- `BLENDER_X3D_EXPORT_TARGET=MODERN_SCAFFOLD`

When enabled:

1. `export_x3d.save()` creates shared `ExportSettings`
2. `export_pipeline.save()` extracts IR from the scene
3. the modern writer calls `emit_x3d40.export_ir_scene()`
4. the result is XML-validated

When not enabled:

- the legacy exporter remains the default behavior

This means the rewrite can advance without breaking the old operator contract.

### Export Orchestration

File:

- `io_scene_x3d/source/export_pipeline.py`

Responsibilities:

- unify path planning
- gather scene metadata
- handle batch modes
- ensure Blender object mode
- run extraction once per export target
- dispatch to legacy or modern writer

## Direct X3D Document Structure

The direct export file is:

- `demo/investor_poc/blender_modern_poc.x3d`

Important structure:

1. `head` metadata
2. `WorldInfo` for export note
3. `WorldInfo` for diagnostics
4. `Transform DEF="MaterialGallery"`
5. `Switch DEF="GeometryLibrary" whichChoice="-1"`
6. `Group DEF="SceneInstances"`

### Why the Hidden Geometry Library Exists

X3D DEF/USE reuse for geometry requires valid node placement.
Earlier iterations incorrectly placed raw `IndexedFaceSet DEF`s under a `Group`, which X_ITE rejected.

The current fix:

- wrap each geometry definition inside a `Shape`
- keep them under a hidden `Switch` with `whichChoice="-1"`

That keeps geometry defs valid while still allowing later `USE` references from visible scene instances.

## Material Emission Details

### Current Material Nodes

The emitter currently uses:

- `PhysicalMaterial`
- `UnlitMaterial` when `unlit=True`
- `ImageTexture`
- `TextureTransform`

### Current Texture Fields

The direct exporter now emits:

- `baseTexture`
- `metallicRoughnessTexture`
- `normalTexture`
- `emissiveTexture`
- `occlusionTexture`

### Scalar Fields

The direct exporter also emits:

- `baseColor`
- `metallic`
- `roughness`
- `normalScale`
- `occlusionStrength`
- `emissiveColor`
- `transparency`

### Texture URL Policy

The emitter normalizes texture URLs relative to the exported X3D file.

This was an explicit runtime fix.
Earlier versions emitted absolute Windows paths such as:

- `C:/Users/.../textures/hero_base.png`

That is wrong for a static deployment bundle.
The current emitter rewrites them to:

- `textures/hero_base.png`

This makes the preview bundle portable across local HTTP serving and static hosting.

## Runtime/X_ITE Issues That Were Found and Fixed

Two important X_ITE runtime incompatibilities were discovered during live browser testing.

### 1. Wrong Container Field Placement

Earlier emitted XML placed texture nodes in a way X_ITE interpreted as children of `Appearance`.
That produced warnings like:

- unknown field `baseTexture` in `Appearance`
- unknown field `normalTexture` in `Appearance`

Fix:

- emit those `ImageTexture` nodes as children of `PhysicalMaterial`
- keep `TextureTransform` as an `Appearance` child

### 2. Invalid Geometry Definition Placement

Earlier emitted XML placed `IndexedFaceSet DEF` nodes under `Group`.
That produced warnings about invalid `geometry` placement.

Fix:

- wrap geometry defs inside `Shape`
- place the shapes under a hidden `Switch`

### 3. Local `file://` Browser Errors

This was not an XML bug.
It is a browser origin/security issue.

If the bundle is opened directly from disk:

- `file:///.../direct_x3d.html`

then `fetch()` and texture/asset loading can be blocked by browser origin rules.

Correct local preview flow:

```bash
python3 -m http.server 8000
```

Then open:

```text
http://localhost:8000/demo/investor_poc/
```

## Modern Import Flow

### Parser

File:

- `io_scene_x3d/source/parse_x3d40.py`

Current parser capabilities:

- metadata from `<head><meta ...>`
- `Inline` URLs
- `Transform` recursion
- nested transform composition
- `Viewpoint`
- `NavigationInfo`

The transform logic composes nested X3D transforms and decomposes them back into:

- translation
- axis-angle rotation
- scale

This matters because `Inline` wrappers can be nested or authored under transform hierarchies.

### Population

File:

- `io_scene_x3d/source/populate.py`

Current import-side behaviors:

- create a global `X3DInlineAssets` collection
- create one collection per inline asset
- create one root empty per imported asset
- apply accumulated X3D transforms to that root
- reparent imported GLB content under the root
- move imported objects into the asset collection
- tag objects and materials with provenance
- create `X3DViewpoints` collection
- create Blender cameras from `Viewpoint`
- set first viewpoint camera active
- write scene metadata to collections/roots
- store navigation types on the Blender scene

### Provenance Fields

Imported objects and materials currently receive fields such as:

- `x3d_inline_source`
- `x3d_inline_resolved_path`
- `x3d_inline_asset_index`

Roots/collections/cameras also receive scene metadata fields like:

- title
- creator
- description
- source path

This gives the import path a real audit trail.

## Demo Bundle Contents

Directory:

- `demo/investor_poc/`

Key files:

- `index.html`
- `styles.css`
- `app.js`
- `direct_x3d.html`
- `gltf_inline.html`
- `gltf_multi_inline.html`
- `blender_modern_poc.x3d`
- `blender_scene.glb`
- `blender_scene_alt.glb`
- `xite_gltf_inline_poc.x3d`
- `xite_gltf_multi_inline_poc.x3d`
- `demo_manifest.json`
- `single_inline_import_report.json`
- `multi_inline_import_report.json`
- `x_ite/`
- `textures/`

### Viewer Roles

`direct_x3d.html`

- loads the modern direct-export X3D file in X_ITE

`gltf_inline.html`

- loads the single-inline wrapper scene

`gltf_multi_inline.html`

- loads the heterogeneous multi-inline wrapper scene

### Dashboard

`index.html` is no longer a plain list.
It is a technical-preview dashboard that surfaces:

- pre/post asset flow
- live embedded viewers
- manifest-driven proof points
- import report content

## Hero Scene Technical Details

File:

- `io_scene_x3d/tools/blender_modern_export_demo.py`

The primary direct scene is intentionally more than a geometry smoke test.

### Hero Material Graph

The main material uses:

- generated texture assets
- Mapping transform
- Base color texture
- `MixRGB` tint layer
- ORM texture
- `Separate Color` or `Separate RGB`
- `Math` nodes for metallic/roughness shaping
- `Map Range`
- `Clamp`
- `Normal Map`
- `NodeReroute`
- emissive texture
- occlusion texture
- labeled AO strength value node

This graph was intentionally deepened so the analyzer has to deal with common real-world node patterns rather than only trivial direct links.

### Hero Geometry

The scene now includes:

- `InvestorCube`
- `InvestorCubeInstance`
- `InvestorPedestalLeft`
- `InvestorPedestalRight`
- `InvestorRing`
- `InvestorHalo`
- `InvestorBridge`
- `InvestorPlinthLeft`
- `InvestorPlinthRight`
- `InvestorGround`
- `InvestorBackdrop`
- `InvestorFinLeft`
- `InvestorFinRight`
- `InvestorWingLeft`
- `InvestorWingRight`

Notable choices:

- the hero pair now uses Suzanne-based forms for better silhouette
- bevel modifiers are applied to several hard-surface stage objects
- lighting includes sun, warm rim, cool fill, and a spot key
- the world background is darkened to improve contrast

### Why The Scene Looks More Intentional Now

The geometry and lighting were adjusted toward:

- stronger silhouette layering
- more depth
- better midground/background separation
- better reflective/emissive read on the hero material
- less “test fixture” energy

## Alternate GLB Scene

The secondary GLB is still intentionally simpler.
Its purpose is heterogeneous inline composition rather than hero lookdev.

It includes:

- `InvestorSphere`
- `InvestorColumn`
- `InvestorAltGround`
- `InvestorAltWall`

This keeps the multi-inline scene readable while clearly proving asset heterogeneity.

## Proof Scripts

### Export

File:

- `io_scene_x3d/tools/blender_modern_export_demo.py`

Responsibilities:

- build primary hero scene
- export direct modern X3D
- export primary GLB
- build alternate scene
- export alternate GLB
- write single-inline X3D wrapper
- write multi-inline X3D wrapper
- copy X_ITE runtime
- generate viewer pages
- generate dashboard
- generate manifest

### Single Inline Import Proof

File:

- `io_scene_x3d/tools/blender_modern_import_demo.py`

Validates:

- inline asset collection creation
- viewpoint collection creation
- root transform fidelity
- root metadata
- scene camera from `Viewpoint`
- scene navigation types
- expected imported objects

### Multi Inline Import Proof

File:

- `io_scene_x3d/tools/blender_modern_multi_inline_import_demo.py`

Validates:

- two independent inline roots
- expected transforms
- expected source URLs
- child object sets per root
- tagged imported materials
- active camera from `Viewpoint`
- scene navigation types

## Current Regression Coverage

### `test_emit_x3d40.py`

Covers:

- valid X3D 4.0 structure
- `PhysicalMaterial`
- `UnlitMaterial`
- texture field emission
- `TextureTransform`
- geometry defs and geometry reuse
- primitive fallback

### `test_parse_x3d40.py`

Covers:

- MFString URL parsing
- inline extraction
- inline transform preservation
- nested transform composition
- viewpoint extraction
- navigation extraction

### `test_material_analysis.py`

Covers:

- chained math evaluation
- `MixRGB` color evaluation
- reroute image discovery
- `Map Range` plus `Clamp` scalar evaluation

## Environment Variables

Current runtime switches:

- `BLENDER_X3D_EXPORT_TARGET=MODERN_SCAFFOLD`
- `BLENDER_X3D_IMPORT_TARGET=MODERN_INLINE`

These are deliberate gating controls.
The modern path is still being developed and should not silently replace the legacy path for all users yet.

## What Is Proven Right Now

The current preview proves:

- Blender can export a modern X3D 4.0 scene through the new path
- the direct document loads in X_ITE
- `PhysicalMaterial` and modern texture channels are emitted
- reusable geometry is emitted and reused
- Blender can export GLB assets used in the interop track
- X3D `Inline` wrapper scenes can reference those GLBs
- X_ITE can load the wrapped assets
- Blender can import those wrapper scenes back through a modern native path
- imported content retains transform fidelity
- imported content retains provenance
- `Viewpoint` and `NavigationInfo` survive import
- the preview bundle is static-hosting-safe when served over HTTP

## Known Limits

This is still not full glTF parity or a complete production addon.

Important current limitations:

- no full general X3D 4.x export coverage
- no full importer-side `PhysicalMaterial` reconstruction into Blender node graphs
- no full skeletal/HAnim pipeline
- no animation parity beyond current scoped work
- no full arbitrary node-group graph compilation
- direct exporter still uses a controlled scaffold-style modern path
- material analyzer supports several practical graph patterns, not all possible Blender shading graphs
- glTF export side still relies on Blender’s built-in glTF exporter for the GLB track

## Why This Checkpoint Matters

Before this work, the addon was still fundamentally a legacy X3D/VRML material pipeline.

At this checkpoint, the project now has:

- a real IR boundary
- a real X3D 4.0 emitter module
- a modern material analyzer
- a working modern import path for inline interop
- browser/runtime proof through X_ITE
- Blender proof through headless automation
- validation and regression scaffolding
- a deployable technical-preview bundle

That changes the nature of the project.
It is no longer a speculative rewrite plan.
It is an implemented preview with concrete interop proof.

## Recommended Next Technical Moves

Highest-value follow-ups:

1. importer-side `PhysicalMaterial` reconstruction into Blender node trees
2. broader material graph support, especially more utility/math node combinations
3. targeted geometry fidelity improvements for the direct exporter
4. animation-focused phase work
5. validation expansion beyond XML well-formedness into deeper semantic checks
6. deployment automation once the target hosting environment is finalized

## Operational Notes

Local preview:

```bash
python3 -m http.server 8000
```

Then open:

```text
http://localhost:8000/demo/investor_poc/
```

Do not judge runtime behavior from `file://` URLs.
Serve the bundle over HTTP.

## Checkpoint Summary

This technical preview currently consists of:

- a gated modern X3D 4.0 export path
- a modern material analyzer with real node-chain evaluation
- a native `Inline`-aware import path
- direct X3D and glTF-inline runtime proof in X_ITE
- Blender roundtrip-side proof through headless scripts
- a polished bundle suitable for technical review

It is a strong checkpoint.
The system still has real unfinished areas, but the core viability question has been answered.
