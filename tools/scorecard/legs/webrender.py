# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Browser rendering through the fidelity rig's render.mjs (X_ITE on an X3D, Babylon.js on a glb), one engine per call.

render.mjs is the rig's own script, used as is (its optional job field `legs` selects the engine and it prints `TIME` lines).
Scenes go through in chunks so a scene that hangs in SwiftShader costs one chunk's timeout, not the whole run; the scenes of a
timed-out chunk that never produced an outcome are retried one by one."""
from __future__ import annotations

import json
import os
import re

from .. import common


def parse_render_log(text: str) -> dict:
    """Facts from render.mjs output: browser (Chrome/x.y.z.w), x_ite version, babylon version, times_ms {(engine, job): ms},
    fails {(engine, job): message} from `xite fail` / `babylon fail`, errors {(engine, job): [page errors]}."""
    info = dict(browser=None, x_ite=None, babylon=None, times_ms={}, fails={}, errors={})
    for ln in (text or "").splitlines():
        ln = ln.rstrip()
        if ln.startswith("BROWSER "):
            info["browser"] = ln.split(" ", 1)[1].strip()
        elif ln.startswith("X_ITE "):
            info["x_ite"] = ln.split(" ", 1)[1].strip()
        elif ln.startswith("BABYLON "):
            m = re.search(r'"version":"([^"]+)"', ln)
            if m:
                info["babylon"] = m.group(1)
        elif ln.startswith("TIME "):
            parts = ln.split()
            if len(parts) >= 4 and parts[3].isdigit():
                info["times_ms"][(parts[1], parts[2])] = int(parts[3])
        else:
            m = re.match(r"(xite|babylon) (fail|pageerror) (\S+) ?(.*)", ln)
            if m:
                key = (m.group(1), m.group(3))
                if m.group(2) == "fail":
                    info["fails"][key] = m.group(4)[:300]
                else:
                    info["errors"].setdefault(key, []).append(m.group(4)[:200])
    return info


def _png_name(engine):
    return "xite.png" if engine == "xite" else "babylon.png"


def render(ctx, engine: str, tag: str, jobs: list[dict], chunk: int = 6):
    """jobs: dicts with scene (a common.Scene), glb (path or None), headlight (lux or None). Returns ({scene name: dict(png, ms,
    error)}, meta dict with browser / x_ite / babylon). A scene without a PNG has `error` set."""
    results, meta = {}, dict(browser=None, x_ite=None, babylon=None)
    per = ctx.timeouts["per_scene_web"]

    def call(batch, n):
        specs = []
        for j in batch:
            sc = j["scene"]
            od = sc.work / f"web_{tag}"
            od.mkdir(parents=True, exist_ok=True)
            for stale in ("xite.png", "babylon.png", "babylon_mask.png", "babylon_mask_green.png"):
                if (od / stale).exists():
                    (od / stale).unlink()
            specs.append(dict(name=sc.name, x3d=sc.x3d, glb=j.get("glb"), clear=sc.clear, headlight=j.get("headlight"), outdir=str(od),
                              wait=sc.spec.get("wait", 1500), view=sc.view, legs=[engine]))
        jf = ctx.out / "work" / f"{tag}_jobs_{n}.json"
        jf.parent.mkdir(parents=True, exist_ok=True)
        json.dump(specs, open(jf, "w"), indent=1)
        r = ctx.run([ctx.node, str(ctx.rig / "render.mjs"), str(jf)], 60 + per * len(batch), tag=f"{tag}_{n}", cwd=str(ctx.rig))
        info = parse_render_log(r["out"])
        for k in ("browser", "x_ite", "babylon"):
            if info[k] and not meta[k]:
                meta[k] = info[k]
        return r, info

    def collect(batch, r, info, final):
        retry = []
        for j in batch:
            sc = j["scene"]
            png = sc.work / f"web_{tag}" / _png_name(engine)
            key = (engine, sc.name)
            if png.exists():
                results[sc.name] = dict(png=str(png), ms=info["times_ms"].get(key), error=None, page_errors=info["errors"].get(key, []))
            elif key in info["fails"]:
                results[sc.name] = dict(png=None, ms=None, error=f"{engine} render failed: {info['fails'][key]}")
            elif r["timeout"] and not final:
                retry.append(j)
            elif r["timeout"]:
                results[sc.name] = dict(png=None, ms=None, error=f"timed out after {per} s per scene in headless Chromium (SwiftShader)")
            else:
                results[sc.name] = dict(png=None, ms=None, error=f"render.mjs exit {r['rc']} wrote no image: {common.tail(r['out'], 200)}")
        return retry

    n = 0
    retry_all = []
    for i in range(0, len(jobs), chunk):
        batch = jobs[i:i + chunk]
        n += 1
        r, info = call(batch, n)
        retry_all += collect(batch, r, info, final=(len(batch) == 1))
    for j in retry_all:
        n += 1
        r, info = call([j], n)
        collect([j], r, info, final=True)
    return results, meta
