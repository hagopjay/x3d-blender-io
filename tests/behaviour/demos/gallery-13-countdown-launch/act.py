# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-13-countdown-launch. The eye test's own click on the launch button starts the countdown just
before the act, so the act watches that one run, 19 s (the 10 s count, the 6 s flight and a bit), sampling 10 times a
second: it decodes the seven-segment digit, counts the pad lamps that are lit, watches the flame, the smoke and the rocket's
height, and the camera. Not covered: a second launch (after the flight the camera looks up and the button is out of view)."""
import math

DIGITS = {"abcdef": 0, "bc": 1, "abdeg": 2, "abcdg": 3, "bcfg": 4, "acdfg": 5, "acdefg": 6, "abc": 7, "abcdefg": 8, "abcdfg": 9}


def act(rig, ctx):
    scene, name = ctx["scene"], ctx["name"]
    by_def = lambda d: [o for o in scene.objects if o.get("x3d_def") == d]
    shown = lambda o: not (o.hide_viewport or o.hide_get())
    segs = {c: by_def(f"Seg{c}")[0] for c in "abcdefg"}
    lamps = [by_def(f"Lamp{i}")[0] for i in range(8)]
    flame, rocket = by_def("Flame")[0], by_def("Rocket")
    puffs = [by_def(f"Puff{p}")[0] for p in range(12)]
    cam = scene.camera
    seen_digits, lamp_edges, last_lamps, flame_times, height, puff_max, cam_path = [], 0, [False] * 8, [], 0.0, 0, []
    for tick in range(190):
        yield 0.1
        lit = "".join(c for c, o in segs.items() if shown(o))
        if lit in DIGITS and (not seen_digits or seen_digits[-1] != DIGITS[lit]):
            seen_digits.append(DIGITS[lit])
        states = [shown(o) for o in lamps]
        lamp_edges += sum(a != b for a, b in zip(last_lamps, states))
        last_lamps = states
        if shown(flame):
            flame_times.append(tick / 10)
        height = max(height, max(o.matrix_world.translation.z for o in rocket))      # X3D y is Blender z
        puff_max = max(puff_max, sum(shown(o) for o in puffs))
        cam_path.append(tuple(cam.matrix_world.translation) + tuple(cam.matrix_world.to_euler()))
        if tick % 20 == 5:
            rig.shot(f"{name}-act-{tick // 20:02d}")
    moved = max(math.dist(p[:3], cam_path[0][:3]) for p in cam_path)
    tilt = max(abs(p[3] - cam_path[0][3]) for p in cam_path)
    rig.note(name, "act_numbers", {"digits_seen": seen_digits, "lamp_changes": lamp_edges, "flame_first_last_s": [flame_times[0] if flame_times else None, flame_times[-1] if flame_times else None],
                                   "rocket_max_height_m": round(height, 1), "most_puffs_at_once": puff_max, "camera_moved_m": round(moved, 2), "camera_tilted_rad": round(tilt, 2)})
    descending = all(a > b for a, b in zip(seen_digits, seen_digits[1:]))
    rig.note(name, "act_ok", descending and len(seen_digits) >= 8 and lamp_edges > 30 and bool(flame_times) and height > 15 and puff_max >= 6 and tilt > 0.3)
