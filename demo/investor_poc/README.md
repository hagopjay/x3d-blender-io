# Blender Modern X3D PoC

This directory holds a self-contained proof-of-concept for the upgraded `io_scene_x3d` pipeline.
It is now structured as a technical-preview bundle for static deployment.

Artifacts:

- `blender_modern_poc.x3d`: exported from Blender through the modern X3D 4.0 path
- `blender_scene.glb`: exported from Blender through the built-in glTF exporter when available
- `blender_scene_alt.glb`: second Blender-exported GLB used for heterogeneous inline composition
- `xite_gltf_inline_poc.x3d`: X3D wrapper that references the GLB through `Inline`
- `xite_gltf_multi_inline_poc.x3d`: X3D wrapper that references two distinct GLB assets through separate `Inline` nodes
- `single_inline_import_report.json`: report from the Blender single-inline import proof
- `multi_inline_import_report.json`: report from the Blender heterogeneous multi-inline import proof
- `index.html`: landing page for both demos
- `direct_x3d.html`: direct modern X3D viewer
- `gltf_inline.html`: glTF-through-Inline viewer
- `gltf_multi_inline.html`: multi-inline composition viewer
- `x_ite/`: local X_ITE runtime copied from `x_ite-main/dist`

Expected proof points:

- Blender Principled material emits `PhysicalMaterial`
- shared geometry emits once and is reused with `USE`
- output is valid X3D 4.0 XML
- X_ITE loads the scene directly from the generated `.x3d`
- X_ITE can also load the Blender-generated GLB through X3D `Inline`
- the addon can import a heterogeneous multi-inline wrapper scene back into Blender with separate roots, transforms, and provenance tags

Recommended local flow:

1. Regenerate the demo from Blender:
   `blender -b --python io_scene_x3d/tools/blender_modern_export_demo.py`
2. Serve the demo directory over HTTP:
   `python3 -m http.server 8000`
3. Open:
   `http://localhost:8000/demo/investor_poc/`

Static deployment:

- the bundle is relative-path safe
- it can be hosted from GitHub Pages, a static cloud bucket/CDN, or similar static-site infrastructure
- `index.html` is the technical-preview dashboard
- the viewer and report JSON files must remain in the same relative layout
- Google Cloud guidance is in `DEPLOY_GCP.md`
- full implementation and deployment detail is in `TECHNICAL_DEEP_DIVE.md`
