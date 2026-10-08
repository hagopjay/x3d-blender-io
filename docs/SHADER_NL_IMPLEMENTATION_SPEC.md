# Shader NL Implementation Spec

## Objective

Add a new subsystem to `io_scene_x3d` that can turn natural-language or voice-derived prompts into Blender shaders, with optional GLSL/WGSL-style code export for compatible materials.

This subsystem is not a replacement for the X3D modernization work.
It is a parallel authoring capability that fits the same strategic direction:

- modern material semantics
- structured intermediate representations
- explainable outputs
- deployable previews

The first release target is:

- prompt -> Blender node graph
- prompt refinement loop
- plain-language explanation
- serializable shader IR

The second release target is:

- prompt -> Blender node graph + GLSL/WGSL subset export

## Non-Goals

The first implementation must not attempt:

- arbitrary full graph synthesis for every Blender node family
- perfect Cycles/Eevee/WebGL parity
- full speech recognition stack embedded inside Blender
- general node-group reverse engineering of all existing materials
- full graph-to-GLSL compilation for unsupported features

Voice is an input transport, not the architectural center.
The architecture should assume text is already available.

## Product Model

The system should support three user modes:

1. Generate from prompt
2. Refine from follow-up prompt
3. Export technical artifact

Example user flow:

1. user types or speaks:
   - "make this look like glossy blue ceramic with subtle gold cracks"
2. system parses intent
3. system produces shader IR
4. system compiles IR to a Blender node tree
5. system shows explanation and editable controls
6. user refines:
   - "less gold, more teal, add faint animated glow"
7. IR is updated
8. node tree is rebuilt or patched
9. optional GLSL/WGSL export is generated for supported subset

## Architecture

The subsystem should be IR-first.

Prompt text must not be compiled directly into Blender nodes or GLSL without an intermediate representation.

Recommended modules:

- `io_scene_x3d/source/shader_ir.py`
- `io_scene_x3d/source/shader_nl.py`
- `io_scene_x3d/source/shader_plan.py`
- `io_scene_x3d/source/shader_nodes.py`
- `io_scene_x3d/source/shader_glsl.py`
- `io_scene_x3d/source/shader_explain.py`
- `io_scene_x3d/source/shader_store.py`
- `io_scene_x3d/source/shader_voice.py`
- `io_scene_x3d/source/shader_ui.py`

### Module Responsibilities

#### `shader_ir.py`

Defines the structured shader model.

Responsibilities:

- dataclasses or typed models for shader intent
- serialization/deserialization
- validation and versioning

#### `shader_nl.py`

Natural-language ingestion layer.

Responsibilities:

- prompt normalization
- prompt packaging for the LLM
- parsing LLM response into IR
- storing parse diagnostics

This module should not know Blender node APIs.

#### `shader_plan.py`

Transforms raw intent into an executable shader plan.

Responsibilities:

- choose a supported preset topology
- map user intent to available backend features
- resolve fallback behavior
- mark unsupported requests

This is the policy layer between vague language and real implementation.

#### `shader_nodes.py`

Blender material compiler.

Responsibilities:

- build node tree from IR
- preserve/update generated node metadata
- support regeneration and patching

This is the primary compiler for MVP.

#### `shader_glsl.py`

Code export compiler.

Responsibilities:

- convert supported IR subset into GLSL/WGSL-like source
- emit uniforms/parameters
- emit technical notes about unsupported features

This module is secondary to Blender node generation.

#### `shader_explain.py`

User-facing explanation layer.

Responsibilities:

- produce plain-language summaries
- produce terse technical summaries
- report compromises and unsupported requests

#### `shader_store.py`

Persistence layer.

Responsibilities:

- store prompt history on the material
- store IR JSON
- store generated backend metadata
- version generated materials

#### `shader_voice.py`

Input adapter for voice-derived text.

Responsibilities:

- ingest transcript text from external speech systems
- normalize voice-specific artifacts
- optional live prompt session support

Do not block on native speech capture in Blender.

#### `shader_ui.py`

Blender UI layer.

Responsibilities:

- operator registration
- panel layout
- prompt entry
- refine entry
- explanation display
- export buttons

## Core Design Rule

The system should compile a constrained supported shader language, not “anything the user says.”

That means the LLM is allowed to interpret user goals, but final execution must map into supported patterns.

Examples of supported patterns for MVP:

- glossy ceramic
- metallic painted surface
- frosted glass approximation
- emissive sci-fi panel
- pearlescent plastic
- brushed metal approximation
- layered procedural noise
- texture-driven Principled material

Examples of unsupported or phase-2 patterns:

- arbitrary volumetrics
- full OSL authoring
- path-traced caustic-specific materials
- arbitrary NPR shader stacks
- custom BSDF authoring

## Shader IR

The IR must be explicit, versioned, and serializable.

Recommended top-level schema:

```python
@dataclass
class ShaderIR:
    version: str
    prompt: str
    refinement_prompts: list[str]
    target_backends: list[str]
    style_tags: list[str]
    surface_model: str
    base: BaseLayer
    overlays: list[OverlayLayer]
    textures: list[TextureSpec]
    procedural: list[ProceduralSpec]
    normal: NormalSpec | None
    displacement: DisplacementSpec | None
    emission: EmissionSpec | None
    transparency: TransparencySpec | None
    animation: list[AnimationSpec]
    parameters: list[ParameterSpec]
    backend_notes: list[str]
    unsupported_requests: list[str]
```

Recommended core concepts:

- `surface_model`
  - `principled_pbr`
  - `unlit`
  - `glass_approx`
  - `emissive`
- `base`
  - primary color/value information
- `overlays`
  - tint layers, cracks, edge glow, masks
- `textures`
  - image-based inputs
- `procedural`
  - noise, voronoi, wave, gradient, musgrave-like patterns
- `parameters`
  - user-exposed controls

### Parameter Model

Every generated shader should expose a compact parameter set.

Recommended parameter fields:

- id
- label
- type
- default
- min
- max
- description
- backend binding

Example:

```json
{
  "id": "roughness_bias",
  "label": "Roughness",
  "type": "float",
  "default": 0.34,
  "min": 0.0,
  "max": 1.0,
  "description": "Overall surface softness",
  "backend_binding": "principled.roughness"
}
```

## Prompt Contract

The LLM layer should not output free-form prose as the primary artifact.
It should output structured JSON that conforms to the Shader IR schema.

Recommended LLM outputs:

1. `shader_ir`
2. `summary`
3. `unsupported_requests`
4. `assumptions`

### Prompting Policy

The LLM should be instructed to:

- prefer supported Blender-node-compatible materials
- avoid inventing unavailable node types
- state uncertainty explicitly
- preserve user style intent even when approximating
- avoid unsupported claims of exact physical correctness

### Example User Prompt

Input:

- "Create an iridescent black ceramic with warm gold cracks and a faint animated pulse."

Structured interpretation:

- surface model: principled PBR
- base: dark ceramic
- overlay: gold crack mask
- emission: low pulse
- animation: slow emissive modulation
- unsupported exactness: none if implemented as approximation

## Blender Compiler

`shader_nodes.py` should compile the IR into a generated node tree.

### MVP Node Families

Support these first:

- Material Output
- Principled BSDF
- Image Texture
- Mapping
- Texture Coordinate
- RGB
- Value
- MixRGB
- Math
- ColorRamp
- Noise Texture
- Voronoi Texture
- Wave Texture
- Bump
- Normal Map
- Hue/Saturation
- Clamp
- Map Range
- Reroute

### Generated Node Policy

Generated nodes should be tagged.

Recommended metadata:

- node name prefix: `NLShader_`
- material custom props:
  - `nl_shader_prompt`
  - `nl_shader_ir`
  - `nl_shader_version`
  - `nl_shader_backend`

This enables later refinement and regeneration.

### Rebuild vs Patch

For MVP, rebuild the generated shader subtree instead of attempting fine-grained graph patching.

Recommended approach:

1. create or identify generated material
2. remove prior generated nodes tagged by the system
3. rebuild from current IR
4. preserve output connection and material assignment

Patch-in-place can come later.

## GLSL/WGSL Export

`shader_glsl.py` should compile only a supported subset.

Initial target:

- fragment-shader-oriented material export
- no full vertex deformation requirement in MVP
- uniform block from `parameters`

### Supported GLSL Features for MVP

- base color blending
- scalar roughness/metallic logic
- normal intensity approximation
- emissive modulation
- procedural noise approximation
- time-driven pulsing

### Unsupported in First Pass

- arbitrary Blender node parity
- full texture packing parity
- displacement parity
- advanced BSDF semantics

The exporter must emit a compatibility note when lowering from Blender semantics to shader-code approximation.

## Voice Input Strategy

Voice should be modular.

MVP:

- accept transcript text pasted into Blender UI
- optional helper operator to pull transcript from an external file or clipboard

Phase 2:

- live microphone capture
- integrated STT provider adapter

Do not block the system on live speech integration.

## Blender UI

Recommended UI location:

- Material Properties panel
- optional N-panel tool shelf

Recommended controls:

- prompt text field
- refine text field
- `Generate Shader`
- `Refine Shader`
- `Explain Shader`
- `Export Shader IR`
- `Export GLSL`
- `Apply To Active Material`
- `Create New Generated Material`

### Display Regions

The panel should show:

- prompt history
- current summary
- active style tags
- unsupported request notes
- generated parameter controls

## Persistence

Generated materials should be self-describing.

Recommended storage:

- material custom properties for small metadata
- full IR JSON stored in material custom property or companion text block
- optional export to `.json`

Recommended persisted fields:

- original prompt
- refinement history
- IR version
- generation timestamp
- backend compiler version

## Preset Families

The planner should map prompts into a finite preset vocabulary.

Recommended initial preset families:

- `ceramic_gloss`
- `painted_metal`
- `emissive_panel`
- `pearlescent_polymer`
- `rough_stone`
- `frosted_glass_approx`
- `neon_fluid_approx`
- `cracked_surface`
- `layered_noise_surface`
- `image_driven_pbr`

Each preset should define:

- required node topology
- compatible parameter set
- optional texture inputs
- GLSL export support level

## Execution Flow

### Generate

1. user enters prompt
2. system normalizes input
3. `shader_nl.py` requests structured interpretation
4. IR validated by `shader_ir.py`
5. `shader_plan.py` resolves a supported preset topology
6. `shader_nodes.py` builds the node graph
7. `shader_store.py` persists metadata
8. `shader_explain.py` produces explanation text

### Refine

1. user enters refinement prompt
2. system loads prior IR
3. LLM receives prior IR + refinement text
4. revised IR generated
5. planner validates changes
6. node graph rebuilt
7. history updated

### Export GLSL

1. load current IR
2. verify supported GLSL subset
3. compile shader code
4. emit source file and notes

## Suggested File Outputs

Inside Blender session:

- generated material
- explanation text block
- IR JSON text block

Optional disk exports:

- `material_name.shader_ir.json`
- `material_name.glsl`
- `material_name.wgsl`
- `material_name.summary.md`

## Testing Strategy

### Unit Tests

Add tests for:

- prompt-response schema validation
- IR serialization
- planner fallback behavior
- parameter binding
- GLSL export subset

Recommended files:

- `io_scene_x3d/tests/test_shader_ir.py`
- `io_scene_x3d/tests/test_shader_plan.py`
- `io_scene_x3d/tests/test_shader_glsl.py`

### Blender Integration Tests

Add Blender-headless scripts that:

- generate a material from a canned IR
- confirm expected node types exist
- confirm Material Output is connected
- confirm parameter custom properties are stored

Recommended scripts:

- `io_scene_x3d/tools/blender_shader_generate_demo.py`
- `io_scene_x3d/tools/blender_shader_refine_demo.py`

### Golden Prompt Fixtures

Add a fixture set of prompts and expected planning outcomes.

Examples:

- “glossy cobalt ceramic”
- “brushed bronze with green oxidation”
- “soft pink translucent jelly”
- “dark alien membrane with blue pulse”

These should validate preset choice and parameter ranges, not exact node coordinates.

## MVP Phases

### Phase 0

Scaffold:

- `shader_ir.py`
- `shader_plan.py`
- `shader_nodes.py`
- `shader_ui.py`

### Phase 1

Text prompt to Blender nodes:

- static local prompt input
- no voice required
- no GLSL required
- 3 to 5 preset families

### Phase 2

Refinement and persistence:

- prompt history
- material metadata
- rebuild flow
- explanation layer

### Phase 3

GLSL/WGSL subset export:

- supported preset families only
- parameter uniform emission
- code export UI

### Phase 4

Voice adapter and richer presets:

- transcript ingestion
- optional live speech integration
- animation controls

## Risks

### Overpromising Expressivity

Natural language can imply infinite shader variety.
The implementation must constrain user expectations to supported preset families.

### Backend Mismatch

Blender node graphs and GLSL are not equivalent targets.
This is why the IR/compiler split is mandatory.

### Regeneration Drift

If generated nodes are not tagged and isolated, refinement will become unstable.

### Prompt Hallucination

LLM output must be schema-validated before execution.

## Recommended Immediate Next Step

Build the MVP around prompt -> shader IR -> Blender node graph only.

Do not start with live voice and do not start with arbitrary GLSL generation.

First concrete tranche:

1. create `shader_ir.py`
2. create `shader_plan.py`
3. create `shader_nodes.py`
4. create a simple Blender panel
5. implement 3 preset families:
   - ceramic gloss
   - emissive panel
   - layered noise surface
6. add one headless Blender demo script

## Deliverable Standard

The feature is “good” when:

- a user can type a prompt
- Blender builds a coherent material automatically
- the system explains what it made
- the material can be refined with a second prompt
- the result is stored as structured IR

The feature is “great” when:

- the same IR can also emit a clean shader-code artifact
- the user can drive it by voice-transcribed input
- the generated materials are visually strong enough for demos
