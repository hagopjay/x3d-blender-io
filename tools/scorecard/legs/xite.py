# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Leg xite: X_ITE on the X3D file, headless Chromium (SwiftShader), the first Viewpoint, 512 x 512, via the rig's render.mjs."""
from __future__ import annotations

from .. import common, schema
from . import failed, ok, webrender

ID = "xite"


def available(ctx):
    return ctx.node_ok()


def run(ctx, scenes):
    jobs = [dict(scene=s, glb=None, headlight=None) for s in scenes]
    res, meta = webrender.render(ctx, "xite", "xite", jobs)
    ctx.tools["browser"] = meta["browser"] or ctx.tools.get("browser")
    ctx.tools["x_ite"] = meta["x_ite"] or ctx.tools.get("x_ite")
    out = {}
    for s in scenes:
        r = res[s.name]
        inp = dict(kind="x3d", path=s.rel, sha256=s.sha256, producer="the scene file itself")
        if not r["png"]:
            out[s.name] = failed(r["error"], input=inp, validator=schema.x3d_verdict(s.wellformed), tool="render.mjs")
            continue
        out[s.name] = ok(engine_version=f"X_ITE {meta['x_ite'] or 'unknown'}", input=inp, validator=schema.x3d_verdict(s.wellformed),
                         image_src=r["png"], seconds=dict(render=(r["ms"] / 1000.0 if r["ms"] is not None else None)),
                         config=dict(size=ctx.size, settle_wait_ms=s.spec.get("wait", 1500), straighten_horizon=False),
                         notes=["render seconds = page load + loadURL until the scene is loaded, excluding the fixed settle wait"]
                               + [f"page error: {e}" for e in r["page_errors"][:3]], tool=f"render.mjs ({meta['browser'] or 'Chromium'})")
    return out
