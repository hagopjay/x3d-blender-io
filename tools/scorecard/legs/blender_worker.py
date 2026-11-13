# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs tools/scorecard/cycles_ref.py (Cycles or EEVEE) over many scenes in one Blender process and reads its records back."""
from __future__ import annotations

import json
import shutil

from .. import common


def parse_worker_output(text: str) -> tuple[dict, dict]:
    """(meta, {scene name: record}) from the worker's `BLENDER_META` and `BLENDER_LEG` lines."""
    meta, recs = {}, {}
    for ln in (text or "").splitlines():
        if ln.startswith("BLENDER_META "):
            try:
                meta = json.loads(ln.split(" ", 1)[1])
            except ValueError:
                pass
        elif ln.startswith("BLENDER_LEG "):
            try:
                rec = json.loads(ln.split(" ", 1)[1])
            except ValueError:
                continue
            recs[rec["name"]] = rec
    return meta, recs


def job_for(scene, tag):
    lux = scene.spec.get("headlight_lux")
    headlight = None if not scene.headlight_on else (float(lux) if lux else "auto")
    return dict(name=scene.name, x3d=scene.x3d, outdir=str(scene.work / tag), view=scene.view, clear=scene.clear, headlight=headlight)


def run_worker(ctx, script, tag, scenes, extra_args, xvfb=False, per_scene=900, startup=120):
    """Returns ({scene name: record}, meta, {scene name: error text for scenes with no record}). The worker is run once for all
    scenes and once more for scenes it did not reach (a crash mid-run), so one bad scene cannot take the rest with it."""
    records, meta, errors = {}, {}, {}
    todo = list(scenes)
    for attempt in (1, 2):
        if not todo:
            break
        jobs = [job_for(s, tag) for s in todo]
        jf = ctx.out / "work" / f"{tag}_jobs_{attempt}.json"
        jf.parent.mkdir(parents=True, exist_ok=True)
        json.dump(jobs, open(jf, "w"), indent=1)
        rf = str(jf) + ".result.json"
        cmd = [ctx.py, str(common.HERE / script), "--jobs", str(jf), "--addon", str(ctx.addon), "--size", str(ctx.size),
               "--threads", str(ctx.threads), "--result", rf] + extra_args
        if xvfb:
            cmd = ["xvfb-run", "-a"] + cmd
        r = ctx.run(cmd, startup + per_scene * len(todo), tag=f"{tag}_{attempt}", env={"LP_NUM_THREADS": str(ctx.threads)} if xvfb else None)
        m, recs = parse_worker_output(r["out"])
        try:   # stdout is lost when the worker is killed on a timeout: the incremental result file keeps what was done
            data = json.load(open(rf))
            m = m or data.get("meta", {})
            for rec in data.get("results", []):
                recs.setdefault(rec["name"], rec)
        except (OSError, ValueError):
            pass
        meta = meta or m
        for s in todo:
            if s.name in recs:
                records[s.name] = recs[s.name]
        todo = [s for s in todo if s.name not in records]
        why = f"worker exited with code {r['rc']}" + (" (timed out)" if r["timeout"] else "") + f": {common.tail(r['out'], 240)}"
        for s in todo:
            errors[s.name] = why
        if not todo:
            errors.clear()
    return records, meta, errors


def have_xvfb():
    return shutil.which("xvfb-run") is not None
