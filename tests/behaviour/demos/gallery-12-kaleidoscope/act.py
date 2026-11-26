# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-12-kaleidoscope. The eye test's own click has already pressed the hub (which pauses it), so:
watch it paused, click the hub to run it, watch 12 s (screenshots), click again to pause. Checks that it moves only
while running, and that all 12 sectors keep exactly the same distance from the centre (the 6 turns and the mirrors
agree), which fails if any ROUTE did not reach its petal."""
import math


def act(rig, ctx):
    scene, name = ctx["scene"], ctx["name"]
    by_def = lambda d: [o for o in scene.objects if o.get("x3d_def") == d]
    petals = [[by_def(f"Petal{i}{j}{s}")[0] for i in range(6) for j in (0, 1)] for s in range(8)]    # [petal type][12 sectors]
    radius = lambda o: math.hypot(o.matrix_world.translation.x, o.matrix_world.translation.z)           # X3D x, y are Blender x, z
    point = next((rig.screen_point(o) for o in by_def("Hub") if rig.screen_point(o)), None)

    def click():
        rig.mouse(*point)
        yield 0.2
        rig.mouse(*point, "LEFTMOUSE", "PRESS")
        yield 0.1
        rig.mouse(*point, "LEFTMOUSE", "RELEASE")

    def watch(seconds):
        poses, worst = set(), 0.0
        for _ in range(int(seconds * 10)):
            yield 0.1
            poses.add(tuple(round(radius(p[0]), 2) for p in petals))
            for p in petals:
                rs = [radius(o) for o in p]
                worst = max(worst, max(rs) - min(rs))
        return len(poses), worst

    yield 1.0
    paused, _ = yield from watch(2)
    rig.shot(f"{name}-act-1-paused")
    yield from click()
    running, spread = yield from watch(12)
    rig.shot(f"{name}-act-2-running")
    yield from click()
    yield 0.5
    paused_again, _ = yield from watch(2)
    rig.shot(f"{name}-act-3-paused-again")
    rig.note(name, "act_numbers", {"distinct_poses_paused": paused, "running": running, "paused_again": paused_again, "largest_radius_spread_across_12_sectors_m": round(spread, 4)})
    rig.note(name, "act_ok", paused <= 2 and running > 40 and paused_again <= 3 and spread < 0.05)
