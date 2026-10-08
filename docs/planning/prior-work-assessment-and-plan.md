# HagopJay's prior Blender X3D work: assessment and modernization plan

Written 2026-10-08. Source: `C:\Users\Consultant\Desktop\x3d_gltf` on the Windows PC, copied to `/mnt/project-files/blender-x3d/prior-work/`. Companion to [upstream-state-and-gap.md](upstream-state-and-gap.md).

## 1. What was found

| Item | Finding |
|---|---|
| Location | `Desktop\x3d_gltf\io_scene_x3d` (the module), `Desktop\x3d_gltf\demo\investor_poc` (X_ITE demo bundle), `Desktop\x3d_gltf\*.md` (PRD, upgrade notes), `Desktop\x3d_augmnt\*.md` (strategy memos, splat notes). Reference checkouts of x_ite, x3dom and x3d-edit sit beside it. |
| Base | A copy of upstream extension **2.5.1** (manifest and release notes identical to upstream), so it is on the current extension lineage, not the old 4.1 bundled add-on. |
| Date | Files dated 2026-04-04 to 04-05; the PRD says March 2026. No git history, so there is no commit trail. |
| Authorship | SPDX headers read "2026 OpenAI" and the demo's creator meta says "OpenAI Codex": the code was generated with Codex under HagopJay's direction. Headers must be corrected to HagopJay before anything goes upstream. |
| Size | ~1,900 new lines of Python across 11 new modules, 3 test files (12 tests), 3 Blender headless scripts, 4 design docs, plus a 42 KB PRD. Legacy exporter/importer kept with two small hooks. |
| Tests | All 12 unit tests pass on Python 3.13 without Blender (verified today). They cover the emitter, the parser and the material graph helpers. |

### Architecture (as built)

`extract.py` (Blender -> IR) -> `ir.py` (bpy-free dataclasses) -> `emit_x3d40.py` (IR -> X3D 4.0 XML) -> `validate.py` (well-formedness). Import side: `parse_x3d40.py` (XML -> IR, Inline/Viewpoint/NavigationInfo) -> `populate.py` (IR -> Blender, delegates `.glb`/`.gltf` Inlines to Blender's glTF importer via `bridge_gltf.py`). `material.py` walks the shader node tree from Material Output through Principled, Emission, Mix Shader, Mapping, Normal Map, Separate Color, Math, MixRGB, Clamp, Map Range and reroutes. Both new paths are gated behind environment variables (`BLENDER_X3D_EXPORT_TARGET=MODERN_SCAFFOLD`, `BLENDER_X3D_IMPORT_TARGET=MODERN_INLINE`) and are not wired to the UI.

## 2. Frank assessment

**Reusable as-is (keep):**
- The IR boundary and module split. It is exactly the shape the X3D-Ecosystem group's Dec 2024 call and Marchetti's Dec 2025 plan describe, and it is more complete than anything they have published.
- `material.py`. Resolving metallic/roughness through Math/MapRange/Clamp chains and tint through MixRGB is beyond what the glTF add-on's exporter attempts for scalars. Worth contributing on its own.
- `emit_x3d40.py` PhysicalMaterial/UnlitMaterial emission with the five texture slots as children of the material (correct `containerField`, verified against X_ITE after an earlier wrong placement). TextureTransform emission.
- `parse_x3d40.py` and `populate.py`: nested Transform composition, Inline-to-glTF bridge with provenance tags, Viewpoint to camera. The multi-Inline import report shows it working on two GLBs.
- Docs: `PHASED_ROADMAP.md` and `TASK_BREAKDOWN.md` are a sound work plan and are reused below.

**Not yet usable (must fix before anyone else runs it):**
- **Geometry fidelity is the blocker.** The modern extractor writes only `Coordinate` and `coordIndex`. No normals, no UVs, no vertex colors, no per-face material split, no modifier evaluation. The demo file has zero `TextureCoordinate` elements, so its five PBR textures have no UV mapping. The legacy exporter already does all of this; the modern path has to reach parity before it can replace it.
- **No lights, cameras, animation or HAnim on the export side.** `extract.py` explicitly skips LIGHT and CAMERA. Again, legacy has lights and viewpoints.
- **Scene layout hack.** Materials are emitted into a visible "MaterialGallery" of spheres and geometry into a hidden `Switch` library, with instances using `USE`. That pollutes every exported scene. Standard practice is DEF on first use, USE after.
- **Unlit detection misfired** in the demo: "GroundUnlit" came out as PhysicalMaterial.
- **Validation is well-formedness only**, not XSD or Schematron.
- **Never run on Blender 5.x.** Nothing in the new code uses APIs that 5.0 removed, and the legacy code already handles the 4.4 slotted-Action API, so it should load, but it is unproven. (The PRD targets 4.3/4.4, which is already behind.)
- **Blender was never driven from this container.** Everything above is from reading code and outputs; the headless demo scripts need a Blender install to re-run.

**Overlaps to manage:** Vincent Marchetti announced the same PhysicalMaterial export goal in Dec 2025 with a "swatch book" test plan. This work is further along in code. The right move is to bring it to him as a contribution, not a competitor.

**PRD realism:** the PRD proposes 8 to 12 senior engineers for 18 months. That is a vision document, not a plan this project can execute. The phased roadmap in the module is the executable version.

## 3. Modernization plan

Target Blender 4.5 LTS and 5.x (5.0 and 5.1), extension manifest `blender_version_min = "4.2.0"`. Output X3D 4.0 by default with a 3.3 compatibility option. Work in a GitHub repo (proposed `hagopjay/x3d-blender-io`) that tracks upstream `extensions/io_scene_x3d`, with PRs upstream once each milestone passes.

### Milestone 1: prove it (small, concrete)
1. Fix SPDX headers; add a README section describing the modern path; remove the env-var gate in favour of an "X3D version: 4.0 / 3.3" export option in the UI.
2. Geometry parity in the modern extractor: evaluated mesh (modifiers applied), normals, UVs (active layer), vertex colors, split by material index, triangulate option. Reuse the legacy exporter's mesh code via the IR.
3. Replace MaterialGallery/GeometryLibrary with DEF-on-first-use.
4. Swatch-book fixtures: five `.blend` files, one material each on a 16:9 quad (matching Marchetti's plan): plain PBR, base texture, metallic-roughness texture, normal map, emissive. Expected X3D hand-written.
5. Round-trip test: export -> XSD-validate (x3d-4.0.xsd) -> import -> compare base colour, metallic, roughness, normal scale, emissive, texture URLs. Importer side needs PhysicalMaterial -> Principled reconstruction (roadmap Phase 5), which is the one new feature in this milestone.
6. Install the built `.zip` on Blender 4.5 LTS and 5.1 on HagopJay's PC and run the fixtures headless. This needs a Remote Control session on the PC or HagopJay running one script.

Exit: a green test run on 4.5 and 5.x, five swatches round-tripping, files loading in X_ITE and Castle Model Viewer. That is the artifact to show Marchetti and Dr Polys.

### Milestone 2: scene parity with legacy
Lights, Viewpoint/NavigationInfo, Background, Sound, metadata and custom properties as MetadataSet, Inline for linked libraries, DEF/USE for linked duplicates and collection instances. Retire the legacy exporter for 4.0 output.

### Milestone 3: animation
Transform animation (TimeSensor, Position/Orientation/ScalarInterpolator, ROUTE) from Blender 5.0 slotted Actions; shape keys via CoordinateInterpolator; importer-side route reconstruction (the legacy importer has a stub). Fixtures from the X3D Basic example archive.

### Milestone 4: HAnim
Armature -> HAnimHumanoid/Joint/Segment/Site with the canonical LOA joint table; skin weights; coordinate with John Carlson, whose loader prototypes cover the import direction.

### Milestone 5: AI-era layer (this project's differentiator)
An MCP server wrapping the exporter/importer and validator so an agent can author, export, validate and preview X3D from Blender; X3D 4.1 GaussianSplats emission from Blender 5.3's native splat objects; X3D JSON output once 19776-5 settles.

## 4. Open decisions for HagopJay
- Create `hagopjay/x3d-blender-io` on GitHub now? (Recommended: yes, so the code has history and CI.)
- Google "data lake": copy `Desktop\x3d_gltf` and `Desktop\x3d_augmnt` to a Drive folder. Which folder?
- Who contacts Vincent Marchetti and the x3d-ecosystem list, and when: before or after Milestone 1?
