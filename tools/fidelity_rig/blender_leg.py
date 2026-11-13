"""X3D -> add-on (this checkout) -> glb, the way the Foundry convert does it: COMPAT light units, renderable
objects only, cameras and lights on. Usage: python blender_leg.py ADDON_SOURCE_DIR in.x3d out.glb
Options come from the environment (BLENDER_X3D_COLOR_SPACE, BLENDER_X3D_LIGHT_UNITS, BLENDER_X3D_CIRCLE_DIV)."""
import json, os, sys, tempfile
from pathlib import Path
src, x3d, glb = sys.argv[1:4]
tmp = tempfile.mkdtemp(prefix="leg_")
(Path(tmp) / "io_scene_x3d").symlink_to(Path(src).resolve(), target_is_directory=True)
sys.path.insert(0, tmp)
import bpy, importlib
importlib.import_module("io_scene_x3d").register()
bpy.ops.wm.read_factory_settings(use_empty=True)
try:
    importlib.import_module("io_scene_x3d").register()
except ValueError:
    pass  # still registered
bpy.context.scene.frame_start = 0  # the importer puts X3D time 0 on frame_start; the glTF exporter writes frame/fps, so 1 would be 1/24 s late
assert bpy.ops.import_scene.x3d(filepath=x3d) == {"FINISHED"}
lights = []
for ob in bpy.context.scene.objects:
    if ob.type == "LIGHT":
        d = ob.data
        lights.append(dict(name=ob.name, type=d.type, energy=round(d.energy, 5),
                           range=(round(d.cutoff_distance, 4) if d.use_custom_distance else None),
                           ref=d.get("x3d_reference_distance"), factor=d.get("x3d_energy_per_intensity")))
assert bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB", export_lights=True, export_cameras=True,
                          export_import_convert_lighting_mode="COMPAT", use_renderable=True, export_yup=True, export_extras=True,
                          export_apply=True, use_mesh_edges=True, use_mesh_vertices=True) == {"FINISHED"}
sc = bpy.context.scene
print("LEG", json.dumps({"blender": bpy.app.version_string, "x3d": x3d, "lights": lights, "model": sc.get("x3d_lighting_model"), "headlight_lux": sc.get("x3d_headlight_lux")}))
