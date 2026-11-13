"""Blender leg of the round-trip audit: X3D -> add-on import (default options) -> add-on X3D 4.0 export (default
options) [-> Blender glTF export of the same imported scene]. Usage:
    python roundtrip_leg.py ADDON_SOURCE_DIR in.x3d OUT_DIR [--glb]
Writes OUT_DIR/roundtrip.x3d (and OUT_DIR/roundtrip.glb with --glb) and prints one `RTLEG {json}` line.
The colour space comes from the add-on's own defaults (AUTO -> scene -> BLENDER_X3D_COLOR_SPACE -> SRGB); the audit
sets BLENDER_X3D_COLOR_SPACE=AS_IS in the environment for the AS_IS pass. Nothing here sets frame_start, light units or
any export option: this is what a user who clicks Import then Export gets."""
import json, os, sys, tempfile, time
from pathlib import Path
src, x3d, outdir = sys.argv[1:4]
want_glb = "--glb" in sys.argv[4:]
os.makedirs(outdir, exist_ok=True)
tmp = tempfile.mkdtemp(prefix="rtleg_")
(Path(tmp) / "io_scene_x3d").symlink_to(Path(src).resolve(), target_is_directory=True)
sys.path.insert(0, tmp)
import bpy, importlib
importlib.import_module("io_scene_x3d").register()
bpy.ops.wm.read_factory_settings(use_empty=True)
try:
    importlib.import_module("io_scene_x3d").register()
except ValueError:
    pass
t0 = time.time()
r = bpy.ops.import_scene.x3d(filepath=x3d)
assert r == {"FINISHED"}, r
t1 = time.time()
sc = bpy.context.scene
opts = {}
if os.environ.get("RT_EXPORT_ANIMATION") == "1":   # off by default in the operator; the audit's --animation flag turns it on
    opts["use_animation"] = True
info = {"blender": bpy.app.version_string, "x3d": x3d, "color_space": sc.get("x3d_color_space"),
        "lighting_model": sc.get("x3d_lighting_model"), "objects": len(sc.objects),
        "meshes": sum(1 for o in sc.objects if o.type == "MESH"), "lights": sum(1 for o in sc.objects if o.type == "LIGHT"),
        "export_options": opts, "frame_start": sc.frame_start, "frame_end": sc.frame_end, "import_s": round(t1 - t0, 2)}
out_x3d = os.path.join(outdir, "roundtrip.x3d")
r = bpy.ops.export_scene.x3d(filepath=out_x3d, x3d_version="X3D40", **opts)   # everything else at the operator's defaults
assert r == {"FINISHED"}, r
info["export_s"] = round(time.time() - t1, 2)
if want_glb:
    glb = os.path.join(outdir, "roundtrip.glb")
    r = bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB", export_lights=True, export_cameras=True,
                                  export_import_convert_lighting_mode="COMPAT", use_renderable=True, export_yup=True,
                                  export_extras=True, export_apply=True, use_mesh_edges=True, use_mesh_vertices=True)
    assert r == {"FINISHED"}, r
    info["glb"] = glb
print("RTLEG", json.dumps(info))
