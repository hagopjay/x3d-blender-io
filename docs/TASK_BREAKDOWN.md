# Blender X3D IO Rewrite: Task Breakdown

## Usage

This document is intended for implementation agents. Pick a task bundle, honor its dependencies, own the listed files, and do not improvise architecture outside the rules in `IMPLEMENTATION_GUIDELINES.md`.

## Workstream A: Core Refactor

### A1. Introduce IR module

Owner files:

- `io_scene_x3d/source/ir.py`

Tasks:

- define dataclasses for scene, transform, mesh, material, texture, texture transform, instance, inline asset, animation track
- keep module free of `bpy`
- add JSON-serializable helpers for debug snapshots

Done when:

- unit tests can construct and serialize representative scene fragments

### A2. Add extraction shell

Owner files:

- `io_scene_x3d/source/extract.py`

Tasks:

- collect export target objects
- traverse hierarchy
- produce IR scene shell
- detect instances at object/data-block level

Dependencies:

- A1

### A3. Add emit orchestration shell

Owner files:

- `io_scene_x3d/source/export_x3d.py`
- `io_scene_x3d/source/emit_x3d40.py`
- `io_scene_x3d/source/emit_x3d33.py`

Tasks:

- keep operator entry points stable
- route modern export to new emitter
- route compatibility export to legacy emitter path

Dependencies:

- A1
- A2

## Workstream B: Material System

### B1. Replace material graph guessing

Owner files:

- `io_scene_x3d/source/material.py`
- `io_scene_x3d/source/material_node_search.py`

Tasks:

- deprecate first-image-node search pattern
- implement graph walker from Material Output
- classify Principled, Principled+Emission, Unlit, fallback

Dependencies:

- A1

### B2. Add IR material model

Owner files:

- `io_scene_x3d/source/ir.py`
- `io_scene_x3d/source/material.py`

Tasks:

- represent base color, metallic, roughness, normal, occlusion, emissive, alpha, sidedness, texture references, mapping references

Dependencies:

- A1
- B1

### B3. Emit PhysicalMaterial

Owner files:

- `io_scene_x3d/source/emit_x3d40.py`

Tasks:

- emit `Appearance`
- emit `PhysicalMaterial`
- emit `UnlitMaterial`
- route unsupported graphs to explicit fallback

Dependencies:

- B2
- A3

### B4. Parse modern material nodes

Owner files:

- `io_scene_x3d/source/parse_x3d40.py`
- `io_scene_x3d/source/populate.py`

Tasks:

- parse `PhysicalMaterial`
- parse `UnlitMaterial`
- reconstruct Blender Principled materials with acceptable fidelity

Dependencies:

- B2

## Workstream C: Texture Semantics

### C1. Add texture and transform IR

Owner files:

- `io_scene_x3d/source/ir.py`

Tasks:

- represent texture asset separately from usage semantics
- represent mapping identity and transform separately

Dependencies:

- A1

### C2. Extract mapping node transforms

Owner files:

- `io_scene_x3d/source/material.py`

Tasks:

- capture translation, rotation, scale
- preserve texture semantic slot
- preserve texcoord source if available

Dependencies:

- B1
- C1

### C3. Emit texture transforms

Owner files:

- `io_scene_x3d/source/emit_x3d40.py`

Tasks:

- emit `TextureTransform` or more advanced transform forms as needed
- keep transform attached to correct texture usage

Dependencies:

- C2

### C4. Improve importer texture reconstruction

Owner files:

- `io_scene_x3d/source/parse_x3d40.py`
- `io_scene_x3d/source/populate.py`

Tasks:

- reconstruct texture nodes intentionally
- preserve alpha textures
- preserve mapping transforms as Blender nodes where practical

Dependencies:

- C3

## Workstream D: glTF Bridge

### D1. Add inline-asset IR

Owner files:

- `io_scene_x3d/source/ir.py`

Tasks:

- represent external inline assets with URL, type, transform, and import policy metadata

Dependencies:

- A1

### D2. Add `Inline` dispatch

Owner files:

- `io_scene_x3d/source/parse_x3d40.py`
- `io_scene_x3d/source/import_x3d.py`

Tasks:

- dispatch `.x3d`, `.x3dv`, `.wrl` to native parser
- dispatch `.gltf`, `.glb`, `.vrm` to bridge

Dependencies:

- D1

### D3. Implement Blender glTF bridge

Owner files:

- `io_scene_x3d/source/bridge_gltf.py`

Tasks:

- wrap Blender glTF importer/exporter usage
- normalize results into local IR or controlled Blender-side handoff
- document known fidelity gaps

Dependencies:

- D2

## Workstream E: Instancing

### E1. Detect source-instance relationships

Owner files:

- `io_scene_x3d/source/extract.py`

Tasks:

- detect repeated mesh datablocks
- detect collection instances
- represent source node plus placements in IR

Dependencies:

- A2

### E2. Emit DEF/USE

Owner files:

- `io_scene_x3d/source/emit_x3d40.py`

Tasks:

- generate deterministic names
- avoid collisions
- emit shared definitions and repeated uses

Dependencies:

- E1

## Workstream F: Animation

### F1. Normalize transform animation extraction

Owner files:

- `io_scene_x3d/source/animation.py`
- `io_scene_x3d/source/extract.py`

Tasks:

- collect location/rotation/scale curves
- normalize to animation tracks in IR

Dependencies:

- A1
- A2

### F2. Emit interpolator graph

Owner files:

- `io_scene_x3d/source/emit_x3d40.py`

Tasks:

- emit `TimeSensor`
- emit position/orientation/scalar interpolators
- emit `ROUTE`

Dependencies:

- F1

### F3. Modernize importer route handling

Owner files:

- `io_scene_x3d/source/parse_x3d40.py`
- `io_scene_x3d/source/import_x3d.py`

Tasks:

- parse transform-animation routes cleanly
- improve action reconstruction

Dependencies:

- F2

## Workstream G: HAnim

### G1. Add skeleton mapping table

Owner files:

- `io_scene_x3d/source/hanim_mapping.py`

Tasks:

- define canonical HAnim joint-name map
- preserve original names where mapping is uncertain

Dependencies:

- none

### G2. Add HAnim IR

Owner files:

- `io_scene_x3d/source/ir.py`

Tasks:

- represent humanoid, joints, segments, sites, skin references

Dependencies:

- A1
- G1

### G3. Emit HAnim skeletons

Owner files:

- `io_scene_x3d/source/animation.py`
- `io_scene_x3d/source/emit_x3d40.py`

Tasks:

- convert armature topology into HAnim hierarchy
- emit names, transforms, and metadata

Dependencies:

- G2

## Workstream H: Validation

### H1. Add XML validation module

Owner files:

- `io_scene_x3d/source/validate.py`

Tasks:

- parse emitted XML
- perform schema validation
- return structured errors

Dependencies:

- A3

### H2. Add semantic checks

Owner files:

- `io_scene_x3d/source/validate.py`

Tasks:

- DEF/USE checks
- required-node/field checks
- unsupported fallback checks

Dependencies:

- H1

### H3. Add fixture runner

Owner files:

- `io_scene_x3d/tests/`

Tasks:

- define fixture inputs and expected outputs
- add golden assertions where practical

Dependencies:

- H1

## Workstream I: Profiling

### I1. Add timing instrumentation

Owner files:

- `io_scene_x3d/source/profile.py`
- exporter/importer orchestration modules

Tasks:

- timed context helpers
- per-stage totals
- developer-mode output

Dependencies:

- A2
- A3

### I2. Add benchmark fixtures

Owner files:

- `io_scene_x3d/tests/benchmarks/`

Tasks:

- repeated-instance scene
- PBR-heavy scene
- animation scene

Dependencies:

- I1

## Workstream J: Documentation

### J1. Keep implementation docs current

Owner files:

- `io_scene_x3d/docs/IMPLEMENTATION_GUIDELINES.md`
- `io_scene_x3d/docs/PHASED_ROADMAP.md`
- `io_scene_x3d/docs/TASK_BREAKDOWN.md`

Tasks:

- update when architectural decisions change
- record accepted deviations and rationale

Dependencies:

- none

## Rules For All Agents

- Do not add modern features directly into the legacy monolith unless it is a temporary adapter.
- Do not invent field names when X_ITE already demonstrates a working mapping.
- Do not silently drop material semantics.
- Do not bypass IR for convenience.
- Do not claim roundtrip support without fixtures.
- Do not merge profiling or validation late; keep them near the work.

