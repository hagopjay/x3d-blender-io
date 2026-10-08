# Blender X3D IO Rewrite: Phased Roadmap

## Objective

Sequence work so the addon becomes useful early while still converging on the full X3D 4.0-first target.

## Phase 0: Stabilization Baseline

### Goals

- freeze current behavior understanding
- prevent regression during restructuring
- add fixture-based characterization tests for current importer/exporter

### Deliverables

- baseline fixtures for simple mesh, image texture, movie texture, vertex color, transform animation
- current output snapshots
- issue ledger describing known legacy gaps

### Exit Criteria

- baseline tests run locally
- current exporter/importer behavior is documented

## Phase 1: Architecture Split

### Goals

- introduce IR and module separation
- isolate Blender extraction from XML emission
- isolate parsing from Blender population

### Deliverables

- `ir.py`
- extractor module
- mapping module skeleton
- new emitter/parser entry points
- compatibility wrapper around old operators

### Exit Criteria

- legacy exporter still works through new orchestration path
- no direct Blender node-tree access inside new emitter

## Phase 2: X3D 4.0 Primary Export Shell

### Goals

- switch primary export target to X3D 4.0
- create dedicated legacy emitter path

### Deliverables

- `emit_x3d40.py`
- explicit legacy emitter module
- exporter UI labels for primary vs compatibility targets
- X3D 4.0 header/meta output

### Exit Criteria

- default export emits X3D 4.0
- compatibility export remains available
- generated files validate structurally at XML level

## Phase 3: Principled -> PhysicalMaterial

### Goals

- replace shallow material search with real graph walker
- emit `PhysicalMaterial`
- support `UnlitMaterial`

### Deliverables

- material walker
- IR material representation
- `PhysicalMaterial` emission
- `UnlitMaterial` emission
- fallback downgrade warnings

### Exit Criteria

- base color, alpha, metallic, roughness, emissive, normal, occlusion all survive export
- unsupported graphs warn explicitly

## Phase 4: Texture Mapping and UV Semantics

### Goals

- preserve mapping-node transforms
- handle texture channel identity properly
- stop conflating image identity with texture usage

### Deliverables

- IR texture-transform model
- mapping extraction
- texture transform emission
- active-UV support with warnings for unsupported cases

### Exit Criteria

- texture transform fixtures pass
- multi-texture materials no longer degrade into one-image guessing

## Phase 5: Importer Modernization

### Goals

- parse `PhysicalMaterial` and `UnlitMaterial`
- reconstruct Blender Principled materials with better fidelity

### Deliverables

- `parse_x3d40.py`
- population-side material reconstruction updates
- improved alpha / emissive / texture import handling

### Exit Criteria

- exported modern fixtures re-import with acceptable fidelity
- importer no longer assumes only legacy `Material`

## Phase 6: glTF Inline Bridge

### Goals

- treat glTF as first-class `Inline` target
- bridge glTF import/export workflows

### Deliverables

- `bridge_gltf.py`
- URL/extension dispatch logic
- import path for `.gltf` / `.glb` `Inline`
- initial export-side external reference policy

### Exit Criteria

- `Inline` glTF fixtures import intentionally
- bridge behavior is documented and test-covered

## Phase 7: DEF/USE Instancing

### Goals

- improve file size and scene fidelity for repeated content

### Deliverables

- instance detection in extractor
- IR source-instance separation
- DEF naming utility
- USE emission for repeated geometry and collections

### Exit Criteria

- repeated-instance fixture demonstrates smaller output and correct structure

## Phase 8: Validation Harness

### Goals

- add structured conformance checks

### Deliverables

- XML schema validation script/module
- semantic validation checks
- optional schematron integration hooks
- CI-ready validation interface

### Exit Criteria

- modern export fixtures pass validation gate

## Phase 9: Profiling and Benchmarks

### Goals

- make performance visible

### Deliverables

- timing instrumentation
- benchmark fixtures
- timing report format

### Exit Criteria

- export/import timings available for developer runs
- repeated regressions can be detected

## Phase 10: HAnim Foundation

### Goals

- build the first serious HAnim-capable path

### Deliverables

- armature-to-HAnim mapping layer
- canonical joint mapping table
- `HAnimHumanoid` skeleton emission
- metadata preservation for non-canonical names

### Exit Criteria

- simple armature fixture can export HAnim structure

## Phase 11: Advanced Animation

### Goals

- improve animation parity

### Deliverables

- transform animation polish
- NLA bake support
- morph target / shape key pathway
- importer-side route/interpolator improvements

### Exit Criteria

- animation fixtures survive export/import with bounded error

## Deferred Phases

These should not block the main modernization:

- gaussian splat passthrough
- full glTF material-extension parity
- deeper scene scripting scaffolds
- generalized code generation from X3DUOM

