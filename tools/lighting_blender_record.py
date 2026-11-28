# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Render each lighting probe scene (tests/lighting/fixtures) in Blender, the way tools/lighting_record.cjs draws them
in the browsers: 64 x 64, from the file's Viewpoint, 8-bit PNG through the scene's view transform, no dither, no pixel
filter. Each witness is one import setting:

    blender                X3D lighting, linear values (the option's default reading), EEVEE
    blender_display        X3D lighting, display values (view transform Raw), EEVEE
    blender_srgb_decoded   X3D lighting, sRGB-decoded, EEVEE
    blender_default        the import as before (Principled BSDF, light units Auto), EEVEE, view transform as made
    blender_cycles         X3D lighting, linear values, Cycles (renders the Principled fallback), 64 samples

    python tools/lighting_blender_record.py OUT_DIR [--witnesses a,b] [fixtures...]      (needs bpy)
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
SIZE = 64
WITNESSES = {
    "blender": ("LINEAR_VALUES", "BLENDER_EEVEE"),
    "blender_display": ("DISPLAY", "BLENDER_EEVEE"),
    "blender_srgb_decoded": ("SRGB_DECODED", "BLENDER_EEVEE"),
    "blender_default": ("OFF", "BLENDER_EEVEE"),
    "blender_cycles": ("LINEAR_VALUES", "CYCLES"),
}


def _register():
    from test_roundtrip_bpy import _register_extension
    return _register_extension(tempfile.mkdtemp(prefix="x3d_lighting_rec_"))


def render(path, reading, engine, out_png):
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    result = bpy.ops.import_scene.x3d(filepath=str(path), x3d_lighting=reading)
    if result != {"FINISHED"}:
        raise RuntimeError(f"import failed: {result}")
    cameras = [ob for ob in scene.objects if ob.type == 'CAMERA']
    if scene.camera is None and cameras:
        scene.camera = cameras[0]
    render = scene.render
    render.engine = engine
    # The import fits the camera to its render size (X3D's fieldOfView spans the smaller side); refit it to the
    # browsers' square canvas with the add-on's own conversion.
    from io_scene_x3d.viewpoint_fov import blender_camera_angle, x3d_field_of_view, render_size
    camera = scene.camera.data
    field_of_view = x3d_field_of_view(camera.angle, camera.sensor_fit, *render_size(scene))
    render.resolution_x = render.resolution_y = SIZE
    render.resolution_percentage = 100
    camera.angle = blender_camera_angle(field_of_view, camera.sensor_fit, *render_size(scene))
    render.filter_size = 0.0
    render.dither_intensity = 0.0
    render.film_transparent = False
    if engine == "CYCLES":
        scene.cycles.samples = 64
        scene.cycles.use_denoising = False
        scene.cycles.device = 'CPU'
    else:
        scene.eevee.taa_render_samples = 1
    render.image_settings.file_format = 'PNG'
    render.image_settings.color_mode = 'RGB'
    render.image_settings.color_depth = '8'
    render.filepath = str(out_png)
    bpy.ops.render.render(write_still=True)
    return {"view_transform": scene.view_settings.view_transform, "engine": engine, "reading": reading,
            "field_of_view": round(field_of_view, 6),
            "camera": scene.camera.name if scene.camera else None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("fixtures", nargs="*")
    parser.add_argument("--witnesses", default=",".join(WITNESSES))
    args = parser.parse_args()
    _register()
    import bpy
    fixtures = [Path(f) for f in args.fixtures] or sorted((ROOT / "tests/lighting/fixtures").glob("*.x3d"))
    notes = {"blender": bpy.app.version_string, "build": bpy.app.build_hash.decode() if isinstance(
        bpy.app.build_hash, bytes) else str(bpy.app.build_hash)}
    for witness in args.witnesses.split(","):
        reading, engine = WITNESSES[witness]
        folder = Path(args.out) / witness
        folder.mkdir(parents=True, exist_ok=True)
        for fixture in fixtures:
            notes[f"{witness}:{fixture.stem}"] = render(fixture, reading, engine, folder / f"{fixture.stem}.png")
            print(witness, fixture.stem, file=sys.stderr)
    (Path(args.out) / "versions.json").write_text(json.dumps(notes, indent=1))


if __name__ == "__main__":
    main()
