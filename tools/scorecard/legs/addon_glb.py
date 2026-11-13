# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""The add-on's glb for a scene (X3D -> add-on -> glb via the rig's blender_leg.py) and its Khronos validator verdict; made once per
scene and shared by the Babylon (add-on glb) leg and the headlight value the Castle legs need."""
from __future__ import annotations

import json
import os

from .. import common, schema


def ensure(ctx, scene):
    """Make (once) scene.work/addon.glb. Returns dict(glb, leg, validation, validator, error); error is None on success. Sets
    scene.addon_leg to blender_leg.py's LEG dict, which carries the headlight lux."""
    prep = getattr(scene, "_addon_prep", None)
    if prep is not None:
        return prep
    ok_, why = ctx.bpy_available()
    if not ok_:
        prep = dict(glb=None, leg=None, validation=None, validator=None, error=why, seconds=0)
        scene._addon_prep = prep
        return prep
    scene.work.mkdir(parents=True, exist_ok=True)
    glb = scene.work / "addon.glb"
    for stale in (glb, str(glb) + ".validation.json"):
        try:
            os.remove(stale)
        except OSError:
            pass
    r = ctx.run([ctx.py, str(ctx.rig / "blender_leg.py"), str(ctx.addon), scene.x3d, str(glb)], ctx.timeouts["glb"],
                tag=f"addon_glb_{scene.name}", env={"BLENDER_X3D_COLOR_SPACE": "SRGB"})
    line = next((l for l in r["out"].splitlines() if l.startswith("LEG ")), None)
    leg = None
    if line:
        try:
            leg = json.loads(line[4:])
        except ValueError:
            leg = None
    if leg:
        scene.addon_leg = leg
    if r["rc"] != 0 or not glb.exists():
        err = ("timed out after %s s" % ctx.timeouts["glb"]) if r["timeout"] else f"blender_leg.py exit {r['rc']}, no glb: {common.tail(r['out'], 240)}"
        prep = dict(glb=None, leg=leg, validation=None, validator=None, error=err, seconds=r["seconds"])
    else:
        validation = ctx.manifest.validate(str(glb))
        summary = validation.get("validator")
        verdict = schema.gltf_verdict(summary, validation.get("validator_error"), scene.has_geometry)
        prep = dict(glb=str(glb), leg=leg, validation=validation, validator=verdict, error=None, seconds=r["seconds"])
    scene._addon_prep = prep
    return prep
