# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Leg blender_cycles: the path-traced reference. Cycles (CPU) on the add-on's import of the X3D, 256 spp, 12 bounces, no denoise,
two seeds (seed 0 is the reference image, seed 1 gives the reference's own noise floor). Runs cycles_ref.py, all scenes in one process."""
from __future__ import annotations

from .. import common, schema
from . import blender_worker, failed, ok

ID = "blender_cycles"


def available(ctx):
    good, why = ctx.bpy_available()
    return (True, "ok") if good else (False, why)


def run(ctx, scenes):
    seeds = [str(s) for s in ctx.seeds]
    recs, meta, errors = blender_worker.run_worker(
        ctx, "cycles_ref.py", "cycles", scenes,
        ["--engine", "cycles", "--samples", str(ctx.spp), "--seeds"] + seeds, per_scene=ctx.timeouts["per_scene_cycles"])
    if meta.get("blender"):
        ctx.tools["blender"] = meta["blender"]
        ctx.tools["addon_commit"] = meta.get("addon_commit")
    out = {}
    for s in scenes:
        inp = dict(kind="x3d", path=s.rel, sha256=s.sha256, producer="imported by the add-on (colour space SRGB, light units X_ITE)")
        base = dict(input=inp, validator=schema.x3d_verdict(s.wellformed), tool="cycles_ref.py (bpy)")
        rec = recs.get(s.name)
        if rec is None:
            out[s.name] = failed(errors.get(s.name, "no record from the Blender worker"), **base)
        elif not rec["ok"]:
            out[s.name] = failed(rec.get("error") or "render failed", **base)
        else:
            frames = {f["seed"]: f for f in rec["frames"]}
            extra = {f"seed{f['seed']}": str(s.work / "cycles" / f["file"]) for f in rec["frames"][1:]}
            notes = []
            if rec.get("importer_warnings"):
                notes.append(f"importer warnings: {len(rec['importer_warnings'])}; first: {rec['importer_warnings'][0][:160]}")
            notes += rec.get("notes", [])
            cfg = rec["settings"]
            out[s.name] = ok(engine_version=f"Blender {meta.get('blender', 'unknown')} Cycles (CPU)", image_src=str(s.work / "cycles" / rec["frames"][0]["file"]),
                             extra_images=extra, seconds=dict(render=rec["seconds_render"], import_=rec.get("seconds_import"),
                                                              **{f"render_seed{k}": v["seconds"] for k, v in frames.items() if k != ctx.seeds[0]}),
                             config=dict(samples=cfg["samples"], seeds=cfg["seeds"], max_bounces=cfg["max_bounces"], denoise=cfg["denoise"],
                                         adaptive=cfg["adaptive"], light_size=cfg["light_size"], size=cfg["size"], threads=cfg["threads"]),
                             notes=notes, **base)
    return out
