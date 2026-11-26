# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-16-haunted-gallery: no clicks, the camera drifts by itself. Watch one full 40 s loop, a
screenshot every three seconds; check the camera travelled the hall and that each pair's haunted canvas woke (a rising
edge) while the calm canvas went out, and that the two are never both shown."""
import math


def act(rig, ctx):
    scene, name, player = ctx["scene"], ctx["name"], ctx["player"]
    by_def = lambda d: [o for o in scene.objects if o.get("x3d_def") == d]
    shown = lambda objs: any(not (o.hide_viewport or o.hide_get()) for o in objs)
    pairs = 8
    wake = [by_def(f"Wake{i}L") + by_def(f"Wake{i}R") for i in range(pairs)]
    calm = [by_def(f"Calm{i}L") + by_def(f"Calm{i}R") for i in range(pairs)]
    found = all(wake) and all(calm)
    was, edges, calm_dark, both = [False] * pairs, [], set(), 0
    cam, cam_path, t0 = scene.camera, [], player.now
    tick = -1
    while player.now - t0 < 42.0:                   # a little over one 40 s loop, on the player clock
        yield 0.1
        tick += 1
        for i in range(pairs):
            w, c = shown(wake[i]), shown(calm[i])
            if w and not was[i]:
                edges.append(i)
            if w and not c:
                calm_dark.add(i)
            both += (w and c)
            was[i] = w
        cam_path.append(tuple(cam.matrix_world.translation))
        if tick % 12 == 11:
            rig.shot(f"{name}-act-hall-{tick // 12:02d}")
    zs = [p[1] for p in cam_path]               # Blender is Z-up: the hall runs along Y
    travelled = max(max(zs) - min(zs), max(p[0] for p in cam_path) - min(p[0] for p in cam_path), max(p[2] for p in cam_path) - min(p[2] for p in cam_path))
    cyclic = all(b == (a + 1) % pairs for a, b in zip(edges, edges[1:]))
    rig.note(name, "act_numbers", {"objects_found": found, "pairs_woken_in_order": edges, "calm_went_dark": sorted(calm_dark),
                                   "both_shown_samples": both, "total_samples": len(cam_path) * pairs, "player_seconds": round(player.now - t0, 1), "camera_travelled_m": round(travelled, 1)})
    rig.note(name, "act_ok", found and len(set(edges)) >= 7 and len(calm_dark) >= 7 and cyclic and travelled > 40)
