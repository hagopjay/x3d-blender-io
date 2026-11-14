# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Babylon.js on a glb, shared by the two Babylon legs (the add-on's glb and the Castle exporter's glb): the glb comes from
`make_glb(ctx, scene) -> dict(glb, validator, error, producer, seconds, notes)`."""
from __future__ import annotations

from .. import schema
from . import failed, ok, webrender


def run_leg(ctx, scenes, leg_id, make_glb, tool):
    made, jobs = {}, []
    for s in scenes:
        g = made[s.name] = make_glb(ctx, s)
        if g["glb"]:
            jobs.append(dict(scene=s, glb=g["glb"], headlight=s.headlight_lux()))
    res, meta = webrender.render(ctx, "babylon", leg_id, jobs) if jobs else ({}, dict(browser=None, babylon=None))
    ctx.tools["browser"] = meta.get("browser") or ctx.tools.get("browser")
    ctx.tools["babylon"] = meta.get("babylon") or ctx.tools.get("babylon")
    out = {}
    for s in scenes:
        g = made[s.name]
        inp = dict(kind="glb", path=(ctx.rel(g["glb"]) if g["glb"] else None), sha256=(g.get("validator") or {}).get("glb_sha256"), producer=g["producer"])
        if not g["glb"]:
            out[s.name] = failed(g["error"], input=inp, validator=g.get("validator"), tool=tool, seconds=dict(glb=g.get("seconds")))
            continue
        r = res[s.name]
        common = dict(input=inp, validator=g["validator"], tool=tool)
        if not r["png"]:
            out[s.name] = failed(r["error"], seconds=dict(glb=g.get("seconds")), **common)
            continue
        out[s.name] = ok(engine_version=f"Babylon.js {meta.get('babylon') or 'unknown'}", image_src=r["png"],
                         seconds=dict(render=(r["ms"] / 1000.0 if r["ms"] is not None else None), glb=g.get("seconds")),
                         config=dict(size=ctx.size, headlight_lux=s.headlight_lux()),
                         notes=list(g.get("notes", [])) + ["render seconds = page load + glb load + first 5 frames"] +
                               [f"page error: {e}" for e in r["page_errors"][:3]], **common)
    return out
