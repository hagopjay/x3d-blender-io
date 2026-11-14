# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Leg modules. Each defines

    ID                          the leg id (a key of schema.LEGS)
    available(ctx) -> (bool, reason)   whether the leg can run here; an unavailable leg is recorded as status not-run with the reason
    run(ctx, scenes) -> {scene name: result}   one result per scene given; never raises for a scene, records failed instead

A result is a dict with: status (ok | failed | not-applicable), reason, engine_version, input {kind, path, sha256, producer},
validator, image_src (absolute path of the PNG the leg made), extra_images {name: path}, seconds, config, notes, tool.
run.py completes it into a schema record and does the scoring."""
from __future__ import annotations

import importlib

# execution order: the reference first (everything is scored against it), then the engines
ORDER = ("blender_cycles", "xite", "babylon_addon_glb", "babylon_castle_glb", "castle_native", "blender_eevee")


def load(leg_id):
    return importlib.import_module(f"{__name__}.{leg_id}")


def ok(**kw):
    kw.setdefault("reason", None)
    return dict(status="ok", **kw)


def failed(reason, **kw):
    return dict(status="failed", reason=reason, **kw)


def not_applicable(reason, **kw):
    return dict(status="not-applicable", reason=reason, **kw)
