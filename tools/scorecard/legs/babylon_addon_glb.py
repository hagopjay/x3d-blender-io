# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Leg babylon_addon_glb: Babylon.js on the glb the x3d-blender-io add-on writes (the rig's blender_leg.py), the rig's headlight."""
from __future__ import annotations

from . import addon_glb, babylon

ID = "babylon_addon_glb"


def available(ctx):
    ok_, why = ctx.node_ok()
    if not ok_:
        return ok_, why
    ok_, why = ctx.bpy_available()
    return (True, "ok") if ok_ else (False, why)


def make_glb(ctx, scene):
    p = addon_glb.ensure(ctx, scene)
    notes = [f"glb from the add-on at {ctx.manifest.git_revision(str(ctx.addon))[0][:12]}"]
    return dict(glb=p["glb"], validator=p["validator"], error=p["error"], producer="x3d-blender-io add-on (blender_leg.py, sRGB, COMPAT light units)",
                seconds=p["seconds"], notes=notes)


def run(ctx, scenes):
    return babylon.run_leg(ctx, scenes, ID, make_glb, tool="render.mjs + blender_leg.py + validate_glb.mjs")
