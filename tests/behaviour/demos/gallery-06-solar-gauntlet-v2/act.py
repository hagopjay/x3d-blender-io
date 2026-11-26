# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-06-solar-gauntlet: no clicks, the camera flies by itself. Watch for 26 s, a screenshot every
two seconds; check the camera travelled down the gauntlet and that gate glows lit and went out as it passed."""
import math


def act(rig, ctx):
    scene, name = ctx["scene"], ctx["name"]
    by_def = lambda d: [o for o in scene.objects if o.get("x3d_def") == d]
    glows = [by_def(f"Glow{i}") for i in range(10)]
    shown = lambda objs: any(not (o.hide_viewport or o.hide_get()) for o in objs)
    seen = [set() for _ in glows]
    lit_order, cam_path, was = [], [], [False] * 10      # lit_order: every rising edge of a glow, in time
    cam = scene.camera
    for tick in range(260):                          # 26 s, 10 samples a second
        yield 0.1
        for i, g in enumerate(glows):
            on = shown(g)
            seen[i].add(on)
            if on and not was[i]:
                lit_order.append(i)
            was[i] = on
        cam_path.append(tuple(cam.matrix_world.translation))
        if tick % 20 == 19:
            rig.shot(f"{name}-act-flight-{tick // 20:02d}")
    travelled = math.dist(cam_path[0], max(cam_path, key=lambda p: math.dist(p, cam_path[0])))
    toggled = [i for i, s in enumerate(seen) if len(s) == 2]
    rig.note(name, "act_numbers", {"gates_lit_then_dark": toggled, "lit_in_order": lit_order, "camera_travelled_m": round(travelled, 1)})
    rig.note(name, "act_ok", len(toggled) >= 8 and travelled > 40 and all(b == (a + 1) % 10 for a, b in zip(lit_order, lit_order[1:])))   # the eye test's 9 s flight has already run: the order is cyclic, one gate after the next
