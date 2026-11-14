# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Leg castle_native (optional: needs CASTLE_RENDER): castle-render, the X3D loaded and drawn by Castle itself, default settings.

Command line (Castle quality leg, tools/run_quality.py leg_castle_render; written from that file's description, to be re-checked
against the built binary):
    xvfb-run -a $CASTLE_RENDER SCENE.x3d OUT.png --view-json VIEW.json --clear R,G,B --headlight off|LUX      (512 x 512 default)
VIEW.json is the bare {position, forward, up, fov (radians)} of the first Viewpoint (a scene without one: 0 0 10, down -Z, pi/4).
Exit codes: 0 ok, 2 usage, 3 an option is unsupported (recorded not-applicable), 4 input problem, 5 render failed. OUT.png.json
carries the options applied, the Castle version, the GL renderer and seconds."""
from __future__ import annotations

import json
import os

from .. import common, schema
from . import blender_worker, failed, not_applicable, ok

ID = "castle_native"
DEFAULT_VIEW = dict(position=[0, 0, 10], forward=[0, 0, -1], up=[0, 1, 0], fov=0.7854)


def available(ctx):
    exe = ctx.castle_render
    if not exe:
        return False, "CASTLE_RENDER is not set (path of the castle-render binary)"
    if not os.path.isfile(exe) or not os.access(exe, os.X_OK):
        return False, f"CASTLE_RENDER does not point at an executable file: {os.path.basename(exe)}"
    if not blender_worker.have_xvfb():
        return False, "xvfb-run is not installed (castle-render needs a GL context)"
    return True, "ok"


def rgb(c):
    return ",".join(repr(float(v)) for v in c[:3])


def command(ctx, scene, out_png, view_json, lux):
    return ["xvfb-run", "-a", ctx.castle_render, scene.x3d, out_png, "--view-json", view_json, "--clear", rgb(scene.clear),
            "--headlight", "off" if lux is None else repr(float(lux))]


def run(ctx, scenes):
    from . import addon_glb
    out = {}
    for s in scenes:
        inp = dict(kind="x3d", path=s.rel, sha256=s.sha256, producer="the scene file itself")
        base = dict(input=inp, validator=schema.x3d_verdict(s.wellformed), tool="castle-render")
        s.work.mkdir(parents=True, exist_ok=True)
        view = {k: (s.view or DEFAULT_VIEW)[k] for k in ("position", "forward", "up", "fov")}
        vj = s.work / "castle_view.json"
        json.dump(view, open(vj, "w"))
        png = s.work / "castle_native.png"
        for stale in (png, str(png) + ".json"):
            if os.path.exists(stale):
                os.remove(stale)
        if s.headlight_on and not (s.spec.get("headlight_lux") or s.addon_leg):
            addon_glb.ensure(ctx, s)    # the headlight lux comes from the add-on's import, as for the Babylon legs
        lux = s.headlight_lux()
        r = ctx.run(command(ctx, s, str(png), str(vj), lux), ctx.timeouts["castle"], tag=f"castle_native_{s.name}", env={"LP_NUM_THREADS": str(ctx.threads)})
        meta = {}
        try:
            meta = json.load(open(str(png) + ".json"))
        except (OSError, ValueError):
            pass
        if r["timeout"]:
            out[s.name] = failed(f"castle-render timed out after {ctx.timeouts['castle']} s", **base)
        elif r["rc"] == 3:
            out[s.name] = not_applicable("castle-render reports an unsupported option: " + str(meta.get("error") or common.tail(r["out"], 200)), **base)
        elif r["rc"] != 0 or not png.exists():
            out[s.name] = failed(f"castle-render exit {r['rc']}: " + str(meta.get("error") or common.tail(r["out"], 240)), **base)
        else:
            ver = f"Castle Game Engine {meta.get('castle_version', 'unknown')} (FPC {meta.get('fpc', '?')}, {meta.get('gl_renderer', 'GL renderer unknown')})"
            ctx.tools["castle_render"] = meta.get("tool")
            ctx.tools["castle_version"] = meta.get("castle_version")
            ctx.tools["castle_gl_renderer"] = meta.get("gl_renderer")
            w = meta.get("warnings") or []
            out[s.name] = ok(engine_version=ver, image_src=str(png), seconds=dict(render=(meta.get("seconds") or {}).get("total") if isinstance(meta.get("seconds"), dict)
                                                                                 else meta.get("seconds"), wall=r["seconds"]),
                             config=dict(size=ctx.size, headlight_lux=lux, clear=s.clear),
                             notes=[f"castle-render warning: {str(x)[:160]}" for x in w[:3]], **base)
    return out
