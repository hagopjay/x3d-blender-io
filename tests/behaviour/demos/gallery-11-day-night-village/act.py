# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-11-day-night-village: no clicks, watch one 24 s day (26 s) with a screenshot every 2 s.
Checks the windows came on one by one at dusk and went out at dawn, the stars did the same, the sun light changed
colour, the sun rose and set, and the train went round."""
import math


def act(rig, ctx):
    scene, name = ctx["scene"], ctx["name"]
    by_def = lambda d: [o for o in scene.objects if o.get("x3d_def") == d]
    shown = lambda o: not (o.hide_viewport or o.hide_get())
    wins = [by_def(f"Win{i}")[0] for i in range(24)]
    stars = [by_def(f"Star{i}")[0] for i in range(20)]
    sun_light = next(o for o in scene.objects if o.get("x3d_def") == "SunLight")
    arm = by_def("SkyArm")
    car = by_def("Car0")[0]
    colours, lit_counts, star_counts, rising, was, track, arm_poses = set(), [], [], 0, [False] * 24, [], set()
    for tick in range(260):
        yield 0.1
        states = [shown(w) for w in wins]
        rising += sum(1 for a, b in zip(was, states) if b and not a)
        was = states
        lit_counts.append(sum(states))
        star_counts.append(sum(shown(s) for s in stars))
        colours.add(tuple(round(c, 1) for c in sun_light.data.color))
        track.append(tuple(car.matrix_world.translation))
        arm_poses.update(tuple(round(v, 1) for o in arm for v in o.matrix_basis.to_quaternion()) for _ in [0])
        if tick % 20 == 10:
            rig.shot(f"{name}-act-day-{tick // 20:02d}")
    loop = max(math.dist(a, b) for a in track[::5] for b in track[::5])
    rig.note(name, "act_numbers", {"windows_lit_min_max": [min(lit_counts), max(lit_counts)], "windows_switched_on_events": rising, "stars_min_max": [min(star_counts), max(star_counts)],
                                   "sun_light_colours_seen": len(colours), "sky_arm_poses": len(arm_poses), "train_span_m": round(loop, 1)})
    rig.note(name, "act_ok", min(lit_counts) <= 2 and max(lit_counts) >= 20 and rising >= 20 and max(star_counts) >= 15 and len(colours) >= 5 and loop > 12)
