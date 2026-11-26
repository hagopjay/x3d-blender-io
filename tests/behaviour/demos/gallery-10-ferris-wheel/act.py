# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-10-ferris-wheel. The eye test's own click has already pressed the booth once (which stops
the wheel), so: watch the stopped wheel, click the booth to start it, watch it turn, click again to stop it. Checks the
wheel turns only while running, every cabin stays upright while it rides round, and the bulbs chase."""
import math


def act(rig, ctx):
    scene, name = ctx["scene"], ctx["name"]
    by_def = lambda d: [o for o in scene.objects if o.get("x3d_def") == d]
    wheel = by_def("Wheel")      # the importer copies a DEF onto the unnamed child Transforms: the rim bars and spokes turn with the real wheel
    cabs = [by_def(f"Cab{k}")[0] for k in range(12)]
    bulbs = [by_def(f"Bulb{b}")[0] for b in range(24)]
    shown = lambda o: not (o.hide_viewport or o.hide_get())
    pose = lambda: tuple(round(v, 2) for o in wheel for v in o.matrix_basis.to_quaternion())
    cab_rot = lambda: [c.matrix_world.to_quaternion() for c in cabs]
    cab_pos = lambda: [tuple(c.matrix_world.translation) for c in cabs]
    rot0, pos0 = cab_rot(), cab_pos()
    point = next((rig.screen_point(o) for o in by_def("Booth") if rig.screen_point(o)), None)

    def click():
        rig.mouse(*point)
        yield 0.2
        rig.mouse(*point, "LEFTMOUSE", "PRESS")
        yield 0.1
        rig.mouse(*point, "LEFTMOUSE", "RELEASE")

    def watch(seconds):
        poses, lit, tilt, travel = set(), set(), 0.0, 0.0
        for _ in range(int(seconds * 10)):
            yield 0.1
            poses.add(pose())
            lit.add(tuple(shown(b) for b in bulbs))
            tilt = max(tilt, max(math.degrees(a.rotation_difference(b).angle) for a, b in zip(rot0, cab_rot())))    # how far any cabin has turned from its first pose
            travel = max(travel, max(math.dist(a, b) for a, b in zip(pos0, cab_pos())))
        return len(poses), len(lit), tilt, travel

    yield 1.0
    stopped, _, _, _ = yield from watch(2)
    rig.shot(f"{name}-act-1-stopped")
    yield from click()                                 # start
    running, patterns, tilt, travel = yield from watch(9)
    rig.shot(f"{name}-act-2-running")
    yield from click()                                 # stop again
    yield 0.5
    stopped_again, _, _, _ = yield from watch(2)
    rig.shot(f"{name}-act-3-stopped-again")
    rig.note(name, "act_numbers", {"wheel_poses_while_stopped": stopped, "while_running": running, "stopped_again": stopped_again,
                                   "bulb_patterns_seen": patterns, "cabin_turned_max_deg": round(tilt, 1), "cabin_travel_max_m": round(travel, 1)})
    rig.note(name, "act_ok", stopped <= 2 and running > 30 and stopped_again <= 3 and patterns > 6 and tilt < 3 and travel > 5)
