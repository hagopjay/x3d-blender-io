# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Leg babylon_castle_glb (optional: needs CASTLE_CONVERT): Babylon.js on the glb the Castle exporter (x3d-castle-convert) writes.

Command line (from the Castle quality leg, tools/run_quality.py leg_castle_export):
    $CASTLE_CONVERT SCENE.x3d OUT.glb --no-headlight --verbose
--no-headlight: the rig adds the headlight at the job's lux, as for the add-on's glb. Default colour space of the exporter is srgb."""
from __future__ import annotations

import os

from .. import common, schema
from . import babylon

ID = "babylon_castle_glb"


def available(ctx):
    exe = ctx.castle_convert
    if not exe:
        return False, "CASTLE_CONVERT is not set (path of the x3d-castle-convert binary)"
    if not os.path.isfile(exe) or not os.access(exe, os.X_OK):
        return False, f"CASTLE_CONVERT does not point at an executable file: {os.path.basename(exe)}"
    return ctx.node_ok()


def make_glb(ctx, scene):
    scene.work.mkdir(parents=True, exist_ok=True)
    glb = scene.work / "castle.glb"
    for stale in (glb, str(glb) + ".validation.json"):
        if os.path.exists(stale):
            os.remove(stale)
    r = ctx.run([ctx.castle_convert, scene.x3d, str(glb), "--no-headlight", "--verbose"], ctx.timeouts["convert"], tag=f"castle_convert_{scene.name}")
    producer = "Castle exporter x3d-castle-convert --no-headlight (colour space srgb)"
    if r["timeout"] or r["rc"] != 0 or not glb.exists():
        err = (f"x3d-castle-convert timed out after {ctx.timeouts['convert']} s" if r["timeout"]
               else f"x3d-castle-convert exit {r['rc']}, no glb: {common.tail(r['out'], 240)}")
        return dict(glb=None, validator=None, error=err, producer=producer, seconds=r["seconds"], notes=[])
    validation = ctx.manifest.validate(str(glb))
    verdict = schema.gltf_verdict(validation.get("validator"), validation.get("validator_error"), scene.has_geometry)
    return dict(glb=str(glb), validator=verdict, error=None, producer=producer, seconds=r["seconds"], notes=[])


def run(ctx, scenes):
    return babylon.run_leg(ctx, scenes, ID, make_glb, tool="x3d-castle-convert + render.mjs + validate_glb.mjs")
