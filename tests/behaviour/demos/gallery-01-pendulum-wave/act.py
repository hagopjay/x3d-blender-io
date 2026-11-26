# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-01-pendulum-wave: let it drift, click the beam, watch them realign."""

import math


def act(rig, ctx):
    scene, name = ctx["scene"], ctx["name"]
    # the eye test imports the world more than once, so Blender suffixes names (.001, .002): the live copy is the last
    named = lambda n: max((o for o in scene.objects if o.name == n or o.name.startswith(n + ".")), key=lambda o: o.name)
    pivots = [named(f"Pivot{i}") for i in range(15)]
    # X3D z (swing axis) is Blender -y: read the signed angle of the pivot's rotation
    angle = lambda: [round((lambda q: 2 * math.atan2(q.y, abs(q.w) if q.w else 1e-9) * (1 if q.w >= 0 else -1))(p.matrix_basis.to_quaternion()), 3) for p in pivots]
    first = angle()
    yield 1.0
    rig.shot(f"{name}-act-drift-1")
    second = angle()
    yield 2.0
    rig.shot(f"{name}-act-drift-2")
    third = angle()
    beam = named("Beam")
    point = rig.screen_point(beam)
    rig.mouse(*point)
    yield 0.2
    rig.mouse(*point, "LEFTMOUSE", "PRESS")
    yield 0.1
    rig.mouse(*point, "LEFTMOUSE", "RELEASE")
    together = None                       # after the 0.05 s gap every clock restarts at once: all bobs swing out the same way
    for _ in range(40):
        yield 0.03
        now = angle()
        if all(v > 0 for v in now) or all(v < 0 for v in now):
            together = now
            break
    synced = together or angle()
    rig.shot(f"{name}-act-restart")
    yield 3.0
    rig.shot(f"{name}-act-after")
    spread = lambda a: max(a) - min(a)
    rig.note(name, "act_spread", [spread(first), spread(second), spread(third), spread(synced)])
    moved = any(abs(a - b) > 0.05 for a, b in zip(first, third))
    rig.note(name, "act_ok", moved and spread(third) > 0.8 and together is not None)
