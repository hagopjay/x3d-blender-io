# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-09-clockwork-bird: let the bird fly, click the music box, watch the notes. Checks the bird
flew a loop, both wings flapped through several poses, the gears turned, and the notes showed after the click."""
import math


def act(rig, ctx):
    scene, name = ctx["scene"], ctx["name"]
    by_def = lambda d: [o for o in scene.objects if o.get("x3d_def") == d]
    bird, gear_a, notes = by_def("Bird")[0], by_def("GearA")[0], [by_def(f"Note{i}")[0] for i in range(3)]
    shown = lambda o: not (o.hide_viewport or o.hide_get())
    quat = lambda o: tuple(round(v, 2) for v in o.matrix_basis.to_quaternion())
    wings = by_def("WingR") + by_def("WingL")       # a DEF'd Transform's unnamed child carries the DEF too: watch every object that has it
    flight, wing_poses, gear_poses = [], set(), set()
    yield 0.5
    point = next((rig.screen_point(o) for o in by_def("MusicBox") if rig.screen_point(o)), None)
    if point:
        rig.mouse(*point)
        yield 0.2
        rig.mouse(*point, "LEFTMOUSE", "PRESS")
        yield 0.1
        rig.mouse(*point, "LEFTMOUSE", "RELEASE")
    notes_seen = 0
    for tick in range(150):                       # 15 s: a bit more than one lap
        yield 0.1
        flight.append(tuple(bird.matrix_world.translation))
        wing_poses.update((o.name, quat(o)) for o in wings)
        gear_poses.add(quat(gear_a))
        if tick < 30:
            notes_seen = max(notes_seen, sum(shown(n) for n in notes))
        if tick % 20 == 5:
            rig.shot(f"{name}-act-fly-{tick // 20:02d}")
    span = max(math.dist(a, b) for a in flight[::10] for b in flight[::10])
    rig.note(name, "act_numbers", {"bird_span_m": round(span, 1), "wing_poses": len(wing_poses), "gear_poses": len(gear_poses),
                                   "notes_shown_after_click": notes_seen, "clicked": point is not None})
    rig.note(name, "act_ok", span > 6 and len(wing_poses) >= 6 and len(gear_poses) >= 3 and notes_seen == 3)
