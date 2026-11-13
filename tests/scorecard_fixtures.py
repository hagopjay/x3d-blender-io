# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthetic scorecard results for the scorecard tests (no browser, no Blender): a results document built from a table of FLIP values."""
from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from scorecard import schema  # noqa: E402

PASS_GLB = dict(kind="gltf-validator", verdict="pass", errors=0, warnings=0, triangles=12, empty=False, version="2.0.0-dev.3.10")
X3D_OK = dict(kind="x3d-wellformed", verdict="pass")


def rig():
    return dict(
        host=dict(vcpu_count=4, vcpu_usable=4, cpu_model="test cpu", memory_gb=8, gpu="none (software GL)", os="test"),
        browser=dict(name="Chromium", version="Chrome/153.0.0.0", launch_flags=["--use-angle=swiftshader"], gl="ANGLE SwiftShader"),
        blender_gl=dict(engine_leg="BLENDER_EEVEE under xvfb-run", xvfb_run=True, mesa_dri_package="libgl1-mesa-dri test"),
        tools=dict(python="3.13", numpy="2.0", pillow="12", flip_evaluator="1.7", bpy="5.3.0", node="v22", x_ite="16.7.1", babylonjs="9.32.0",
                   playwright="1.63.0", gltf_validator="2.0.0-dev.3.10", x_ite_runtime="16.7.1", babylon_runtime="9.32.0", blender="5.3.0"),
        git=dict(addon=dict(revision="a" * 40, dirty=False), scorecard_repo=dict(revision="b" * 40, dirty=False),
                 castle=dict(castle_convert=None, castle_render=None)))


def ok_rec(leg, flip=None, xflip=None, mabs=None, validator=None, seconds=1.0, floor=None, image="scenes/s/x.png"):
    r = schema.new_leg_record(leg, schema.OK)
    r.update(engine_version={"xite": "X_ITE 16.7.1", "babylon_addon_glb": "Babylon.js 9.32.0", "blender_cycles": "Blender 5.3.0 Cycles (CPU)",
                             "blender_eevee": "Blender 5.3.0 EEVEE (BLENDER_EEVEE)", "babylon_castle_glb": "Babylon.js 9.32.0",
                             "castle_native": "Castle Game Engine 7.0"}[leg],
             input=dict(kind=schema.LEGS[leg]["input_kind"], path="p.x3d" if schema.LEGS[leg]["input_kind"] == "x3d" else "work/s/a.glb", sha256="0" * 64),
             validator=validator or (PASS_GLB if schema.LEGS[leg]["input_kind"] == "glb" else X3D_OK), image=image, seconds=dict(render=seconds))
    m = {}
    if flip is not None:
        m["flip_vs_reference"] = dict(mean=flip, geometry_mean=flip * 4, geometry_fraction=0.25, ppd=67.0)
    if xflip is not None:
        m["flip_vs_xite"] = dict(mean=xflip)
        m["mean_abs_vs_xite"] = dict(mean_abs=mabs if mabs is not None else 1.0, mean_abs_geometry=2.0)
    if floor is not None:
        m["noise_floor"] = dict(mean=floor)
    r["metrics"] = m
    return r


def doc_from(table, not_run=(), failed=None):
    """table: {scene: {leg: flip or (flip, validator) or None to skip}}; every scene gets all 6 legs (not_run ones as not-run, `failed`
    {(scene, leg): reason} as failed)."""
    failed = failed or {}
    scenes = []
    for name, row in table.items():
        legs = {}
        for leg in schema.LEG_IDS:
            val = row.get(leg)
            if (name, leg) in failed:
                legs[leg] = schema.new_leg_record(leg, schema.FAILED, failed[(name, leg)])
            elif leg in not_run or val is None and leg != schema.REFERENCE_LEG:
                legs[leg] = schema.new_leg_record(leg, schema.NOT_RUN, "CASTLE_RENDER is not set" if leg in not_run else "not run yet")
            elif leg == schema.REFERENCE_LEG:
                legs[leg] = ok_rec(leg, floor=0.001, xflip=row.get("xite") if row.get("xite") is not None else None)
            else:
                flip, validator = val if isinstance(val, tuple) else (val, None)
                legs[leg] = ok_rec(leg, flip=flip, xflip=0.01 if leg != "xite" else None, validator=validator)
        scenes.append(dict(name=name, x3d=dict(path=name + ".x3d", sha256="1" * 64, wellformed=X3D_OK, has_geometry=True), view=None, view_error=None,
                           clear=[0, 0, 0], headlight_on=True, legs=legs))
    return dict(schema=schema.SCHEMA, created="2026-11-13T00:00:00Z",
                params=dict(spp=256, seeds=[0, 1], size=512, bounces=12, threads=2, legs_selected=list(schema.LEG_IDS), leg_wall_seconds={}),
                rig=rig(), legs={k: dict(v) for k, v in schema.LEGS.items()}, scenes=scenes)
