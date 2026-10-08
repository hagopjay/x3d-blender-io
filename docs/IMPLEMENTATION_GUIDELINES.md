# Blender X3D IO Rewrite: Implementation Guidelines

## Purpose

This document is the working engineering authority for upgrading `io_scene_x3d` from a legacy X3D 3.0 / VRML-oriented addon into a modern X3D 4.0-first Blender addon with glTF-aligned material semantics, `Inline` glTF bridging, validation gates, and measurable performance.

It is written so that a subordinate implementation agent can execute work packages without re-deriving architecture or semantics from scattered notes.

## Mission

Deliver a Blender addon that:

- emits X3D 4.0 by default
- maps Blender Principled BSDF to X3D `PhysicalMaterial`
- supports `UnlitMaterial`
- preserves texture transforms and texture channel intent
- supports glTF via `Inline` bridge semantics
- improves DEF/USE instancing
- establishes import/export roundtrip discipline
- adds schema and semantic validation
- instruments import/export performance

## Authority Hierarchy

When implementation choices conflict, apply this precedence order:

1. Normative X3D 4.x node and field model
2. `x_ite-main` runtime behavior and field naming
3. `x3d-edit` authoring-node inventory and validation posture
4. Existing `io_scene_x3d` behavior only for explicit backward compatibility

## External Reference Roles

### `x_ite-main`

Treat X_ITE as the runtime-semantic authority for:

- `PhysicalMaterial` field names and expected meanings
- glTF -> X3D material mapping
- `Inline` glTF behavior
- texture transform and texcoord mapping semantics
- material-extension modeling
- HAnim/glTF runtime alignment

Relevant examples in local sources:

- `x_ite-main/src/x_ite/Parser/GLTF2Parser.js`
- `x_ite-main/src/x_ite/LATEST_VERSION.js`
- `x_ite-main/src/x_ite/SUPPORTED_VERSIONS.js`

### `x3d-edit`

Treat X3D-Edit as the authoring and validation authority for:

- which X3D 4.x nodes are considered canonical authoring targets
- editor-facing naming conventions
- validation-first workflow expectations
- schema/schematron culture

Relevant examples in local sources:

- `x3d-edit/README.distribution.md`
- `x3d-edit/X3dSourceFilePalette/.../Bundle.properties`
- palette XML resources for `PhysicalMaterial`, `UnlitMaterial`, `Inline`, `HAnimHumanoid`, `TextureTransformMatrix3D`

## Architecture

The rewrite must use an intermediate representation. Do not continue to grow the monolithic exporter/importer pattern.

### Required Layers

#### 1. Extractor

Responsibility:

- traverse Blender scene and depsgraph
- resolve selection/visibility/filtering
- identify instancing
- collect mesh/material/light/camera/animation data
- hand off clean Blender-derived facts into IR

Rules:

- no XML generation
- no X3D field naming
- no stringly typed node emission logic

#### 2. IR

Responsibility:

- define pure Python dataclasses representing scene graph and asset semantics
- isolate Blender-specific data from X3D-specific syntax

Minimum IR domains:

- scene
- transform
- mesh
- geometry primitive
- material
- texture
- texture transform
- light
- camera
- instance
- animation track
- armature
- HAnim skeleton
- inline asset
- metadata

Rules:

- IR must be serializable for debugging and fixtures
- IR must not depend on `bpy`
- IR field names should be semantic, not emitter-specific

#### 3. Mapping Layer

Responsibility:

- map Blender node trees and data models into IR
- map X3D parse results into IR
- normalize alpha, textures, colorspaces, UV semantics

Rules:

- all special-case material logic lives here
- this is the only place where Blender shader graph topology is interpreted

#### 4. Emitters / Parsers

Responsibility:

- emit X3D 4.0 XML from IR
- parse X3D 4.x XML into IR
- support dedicated legacy emitter for X3D 3.3 / VRML-compatible output

Rules:

- primary emitter is X3D 4.0
- legacy emitter is separate, explicit, and approximation-based
- parser must not directly create Blender data

#### 5. Blender Population Layer

Responsibility:

- convert IR into Blender objects, materials, actions, armatures, and image references

Rules:

- importer parser and Blender scene creation remain separate

#### 6. Validation and Profiling Layer

Responsibility:

- XML validation
- semantic validation
- regression checks
- timing instrumentation
- benchmark logging

## Source Of Truth Strategy

### Direct Answer On XML/XSLT

X3D-Edit uses XML resources and an XSLT / Schematron ecosystem. That should influence our validation and metadata strategy, but not become the core addon implementation methodology.

### Required Local Source Of Truth

Maintain a compact machine-readable registry for supported X3D nodes and fields.

Recommended form:

- `io_scene_x3d/source/x3d_registry.py`
- or `io_scene_x3d/source/x3d_registry.json`

Each supported node entry should define:

- node name
- minimum X3D version
- field names
- field types
- default values
- import support level
- export support level
- legacy fallback behavior if unsupported

Seed this registry from:

- X_ITE implemented field usage
- X3D-Edit palette inventory
- X3DUOM later if helpful

### Non-Recommended Strategy

Do not attempt a full code-generated addon from XML or XSLT first.

Reasons:

- Blender graph walking is procedural and stateful
- import/export business logic depends on Blender API quirks
- most near-term risks are semantic, not syntax-generation related

### Recommended Strategy

Use XML/XSLT/Schematron assets for:

- validation
- normalization
- optional conversions
- fixture inspection
- optional metadata generation

Use Python IR for:

- runtime implementation
- extraction
- mapping
- import/export business logic

## Versioning Policy

### Export Defaults

- default export target: X3D 4.0
- optional compatibility targets: X3D 3.3 and legacy VRML-oriented fallback

### Import Support

- import X3D 3.x and 4.x
- import VRML with compatibility path
- import glTF through `Inline` bridge logic where applicable

### UI Policy

- primary path must clearly be X3D 4.0
- legacy modes must be visibly marked as compatibility modes

## Material System

This is the highest-priority subsystem.

### Required Material Output Classes

- `PhysicalMaterial`
- `UnlitMaterial`
- legacy `Material` fallback only in legacy mode or unsupported topology fallback

### Required Blender Topologies

- direct Principled BSDF
- Principled + Emission mixed setup
- emission-only / unlit setup
- alpha-bearing Principled materials
- image textures through mapping nodes

### Required PBR Coverage

The mapping layer must extract, preserve, and emit:

- base color factor
- base color texture
- metallic factor
- roughness factor
- metallic-roughness texture
- normal texture
- normal scale
- occlusion texture
- occlusion strength
- emissive color
- emissive texture
- alpha semantics
- sidedness / backface culling semantics
- texture mapping identity

### Canonical Naming Direction

When naming X3D-facing fields, prefer X_ITE-compatible field semantics already visible in its glTF parser and nodes, for example:

- base color / base texture
- metallic
- roughness
- metallic-roughness texture
- normal texture / normal scale
- occlusion texture / occlusion strength

### Material Walker Rules

- Start from Material Output `Surface`
- Walk upstream links intentionally
- Do not search for the first image texture in the tree and guess meaning
- Preserve which texture drives which semantic slot
- Preserve image colorspace intent where Blender exposes it
- Record texture transform independently from image identity

### Fallback Rules

Unsupported topology may fall back only if:

- warning is logged
- fallback is explicit in code
- PBR output is not silently downgraded without trace

## Texture and UV Rules

### Texture Identity

Separate these concerns in IR:

- image source
- sampler/repeat behavior
- texcoord source
- mapping transform
- semantic usage

### Texture Transform Rules

Adopt X_ITE-like semantics:

- texture mapping is not a loose afterthought
- mapping IDs matter
- texcoord channel identity matters
- transformed textures should not overwrite base UV semantics

### UV Policy

Phase 1 minimum:

- support active UV map
- preserve mapping node transforms
- warn when unsupported multi-UV semantics would lose meaning

Phase 2:

- explicit multi-UV / texcoord channel support

## glTF Bridge Policy

### Why It Exists

The addon is not expected to become a full native glTF reimplementation inside X3D import/export paths. It should bridge intelligently.

### Import Rules

If `Inline.url` points to:

- `.x3d`, `.x3dv`, `.wrl`: parse through X3D/VRML path
- `.gltf`, `.glb`, `.vrm`: dispatch to glTF bridge

### Export Rules

Phase 1:

- preserve or emit external glTF references where appropriate
- do not claim embedded glTF roundtrip unless implemented and tested

Phase 2:

- support sidecar generation
- support higher-fidelity roundtrip workflows

### Blender Integration Rules

- glTF bridge implementation may call Blender’s glTF importer/exporter APIs
- bridge results must still be normalized into local IR
- do not let foreign importer output become opaque uncontrolled scene state

## Instancing Policy

### Required Forms

- shared mesh datablock instances
- collection instances

### IR Rules

Represent:

- source geometry / reusable node
- transform placements
- instance count
- reference identities

### Emission Rules

- emit stable deterministic DEF names
- emit USE references for repeated instances
- preserve transform differences per placement

## Animation Policy

### Phase 1

Support:

- translation animation
- rotation animation
- scale animation
- `TimeSensor` + interpolator + `ROUTE` graph generation

### Phase 2

Support:

- NLA bake export
- shape key / morph animation
- importer reconstruction improvements

### Phase 3

Support:

- armature export to HAnim structures
- deeper skeletal roundtrip

## HAnim Policy

### HAnim Is A First-Class Subsystem

Do not bolt HAnim into generic animation logic.

### Required Separation

- armature topology extraction
- canonical joint mapping
- original-name preservation
- HAnim hierarchy emission
- animation channel emission

### Naming Rules

- canonical HAnim names when confidently mapped
- preserve original Blender bone names as metadata where needed

## Validation Policy

Validation is mandatory in CI and available in developer workflows.

### Validation Layers

#### XML Layer

- well-formed XML
- schema validation for X3D 4.0

#### Rule Layer

- schematron where available
- local semantic rule checks

#### Semantic Layer

- no dangling DEF/USE
- no invalid field names
- expected node/field combinations only
- texture URL and inline URL sanity
- deterministic naming collisions handled

#### Regression Layer

- golden output comparison where appropriate
- targeted semantic assertions instead of only full-file equality

## Performance Policy

### Required Timings

Collect timings for:

- scene extraction
- material graph evaluation
- mesh preparation
- image serialization / path resolution
- XML emission
- XML parsing
- Blender population
- validation

### Required Benchmarks

- repeated-instance scene
- PBR-heavy material scene
- high-texture-count scene
- animation scene

### Logging

Provide a developer-mode timing report with stage totals and percentages.

## Logging and Warnings

### Logging Rules

- warnings must be actionable
- unsupported-topology warnings must include object/material identity
- compatibility downgrades must be explicit
- validation failures must surface precise node/field context

### Non-Acceptable Behavior

- silently dropping metallic/roughness/normal/occlusion
- silently reinterpreting unsupported topologies as diffuse-only without warning
- silently exporting X3D 3.0 under a modern workflow

## Compatibility Discipline

### Keep

- operator registration stability
- legacy import support
- compatibility export path

### Replace

- legacy default X3D 3.0 emission
- monolithic material guessing
- exporter functions that directly encode Blender assumptions into XML generation

## Explicit Non-Goals For Initial Upgrade

Do not block the main rewrite on:

- gaussian splat passthrough
- full glTF extension parity
- complete HAnim animation parity
- full code generation from X3DUOM
- arbitrary shader-graph compilation

## Engineering Quality Gates

No major feature is complete until:

- unit or fixture tests exist
- validation passes
- warnings are defined for downgrade cases
- timing is at least observed once
- import/export behavior is documented

## Required Deliverables Per Major Subsystem

For each subsystem deliver:

- code
- tests
- fixture assets or synthetic fixtures
- validation notes
- known limitations
- profiling result snapshot

