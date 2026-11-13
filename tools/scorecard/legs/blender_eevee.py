# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Leg blender_eevee: Blender EEVEE (engine id BLENDER_EEVEE) on the add-on's import of the X3D, scored against the Cycles image.

EEVEE needs an OpenGL context: headless it runs only under `xvfb-run -a` (Mesa llvmpipe). The first render of a Blender process
pays about 66 s of shader compile, so every scene goes through ONE process (eevee_ref.py) and the first scene's time carries that
compile; the later scenes' times do not."""
from __future__ import annotations

from .. import schema
from . import blender_worker, failed, ok

ID = "blender_eevee"


def available(ctx):
    if not blender_worker.have_xvfb():
        return False, "xvfb-run is not installed (EEVEE needs a GL context; Mesa llvmpipe under Xvfb)"
    good, why = ctx.bpy_available()
    return (True, "ok") if good else (False, why)


def run(ctx, scenes):
    recs, meta, errors = blender_worker.run_worker(
        ctx, "eevee_ref.py", "eevee", scenes, ["--engine", "eevee"], xvfb=True,
        per_scene=ctx.timeouts["per_scene_eevee"], startup=ctx.timeouts["eevee_startup"])
    if meta.get("blender"):
        ctx.tools.setdefault("blender", meta["blender"])
    if meta.get("gl_renderer"):
        ctx.tools["eevee_gl_renderer"] = meta["gl_renderer"]
    out = {}
    for i, s in enumerate(scenes):
        inp = dict(kind="x3d", path=s.rel, sha256=s.sha256, producer="imported by the add-on (colour space SRGB, light units X_ITE)")
        base = dict(input=inp, validator=schema.x3d_verdict(s.wellformed), tool="eevee_ref.py (bpy, xvfb-run)")
        rec = recs.get(s.name)
        if rec is None:
            out[s.name] = failed(errors.get(s.name, "no record from the Blender worker"), **base)
        elif not rec["ok"]:
            out[s.name] = failed(rec.get("error") or "render failed", **base)
        else:
            cfg = rec["settings"]
            first = bool(rec.get("first_render_of_process"))
            notes = ["EEVEE is a rasteriser: scored against the Cycles image like any other engine leg"]
            if first:
                notes.append("first render of the Blender process: this time includes the one-off shader compile (about 66 s)")
            if rec.get("importer_warnings"):
                notes.append(f"importer warnings: {len(rec['importer_warnings'])}; first: {rec['importer_warnings'][0][:160]}")
            out[s.name] = ok(engine_version=f"Blender {meta.get('blender', 'unknown')} EEVEE ({cfg['engine']})",
                             image_src=str(s.work / "eevee" / "eevee.png"),
                             seconds=dict(render=rec["seconds_render"], import_=rec.get("seconds_import"), includes_shader_compile=first),
                             config=dict(engine=cfg["engine"], taa_render_samples=cfg["taa_render_samples"], size=cfg["size"],
                                         shadows=cfg["use_shadows"], raytracing=cfg["raytracing"]), notes=notes, **base)
    return out
