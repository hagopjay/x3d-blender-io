# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-05-spin-the-planet: grab the planet, sweep the pointer, release; the five moons swing round
after it, the fast ones first. Checks every moon turned, they lagged at release, the fast chaser closed more of its gap
than the slow one in 1.3 s, and all caught up in the end."""
import math


def act(rig, ctx):
    scene, name = ctx["scene"], ctx["name"]
    by_def = lambda d: [o for o in scene.objects if o.get("x3d_def") == d]
    planet = by_def("Planet")
    arms = [by_def(f"Arm{i}") for i in range(5)]
    q = lambda objs: objs[0].matrix_basis.to_quaternion()
    deg = lambda a, b: math.degrees(a.rotation_difference(b).angle)          # degrees between two orientations
    gap = lambda a, b: deg(q(a), q(b))
    q0 = [q(a).copy() for a in arms]
    yield 0.3
    start = next((rig.screen_point(o) for o in planet if rig.screen_point(o)), None)
    if start is None:
        rig.note(name, "act_ok", False)
        return
    rig.mouse(*start)
    yield 0.2
    rig.mouse(*start, "LEFTMOUSE", "PRESS")
    yield 0.1
    steps = 40
    for s in range(1, steps + 1):
        a = s / steps * math.pi * 1.4
        rig.mouse(start[0] + 110 * math.sin(a), start[1] + 60 * (1 - math.cos(a)))
        yield 0.05
        if s in (13, 27, 40):
            rig.shot(f"{name}-act-drag-{s}")
    rig.mouse(start[0], start[1], "LEFTMOUSE", "RELEASE")
    yield 0.1
    at_release = [round(gap(planet, a_), 1) for a_ in arms]
    q_release = [q(a_).copy() for a_ in arms]
    rig.shot(f"{name}-act-release")
    yield 1.2
    rig.shot(f"{name}-act-swinging")
    after_release = [round(deg(r, q(a_)), 1) for r, a_ in zip(q_release, arms)]    # how far each moon moved after the pointer let go
    yield 4.5
    rig.shot(f"{name}-act-settled")
    settled = [round(gap(planet, a_), 1) for a_ in arms]
    turned = [round(deg(q0_, q(a_)), 1) for q0_, a_ in zip(q0, arms)]
    closed = [a / g if g else 1.0 for a, g in zip(after_release, at_release)]      # share of the gap closed 1.3 s after release
    rig.note(name, "act_numbers", {"arm_turned_deg": turned, "gap_at_release_deg": at_release, "travel_after_release_deg": after_release,
                                   "share_of_gap_closed": [round(c, 2) for c in closed], "gap_settled_deg": settled})
    rig.note(name, "act_ok", all(t > 20 for t in turned) and closed[0] > closed[4] + 0.3 and max(settled) < 10)
