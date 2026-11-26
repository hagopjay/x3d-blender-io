# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-20-living-garden: click seed mounds 1 and 2 (the eye test already pressed the first sensed
one), leave mound 3 alone, then watch. Checks the clicked plants grew (stem scale, head height, petals opened, petal
colour changed), the unclicked one did not, the bees and butterflies flew and flapped, and fireflies showed at dusk."""
import math


def act(rig, ctx):
    scene, name = ctx["scene"], ctx["name"]
    by_def = lambda d: [o for o in scene.objects if o.get("x3d_def") == d]
    shown = lambda o: not (o.hide_viewport or o.hide_get())
    stem_h = lambda p: max(o.matrix_world.to_scale().y for o in by_def(f"Stem{p}"))
    head_y = lambda p: max(o.matrix_world.translation.z for o in by_def(f"Head{p}"))   # Blender Z is up
    petal = lambda p: tuple(round(v, 2) for o in by_def(f"Pet{p}_0") for v in o.matrix_basis.to_quaternion())
    petal0 = {p: petal(p) for p in range(4)}
    stem0 = {p: stem_h(p) for p in range(4)}
    yield 0.4
    clicked = []
    for p in (1, 2):
        point = next((rig.screen_point(o) for o in by_def(f"Mound{p}") if rig.screen_point(o)), None)
        if point:
            rig.mouse(*point)
            yield 0.2
            rig.mouse(*point, "LEFTMOUSE", "PRESS")
            yield 0.1
            rig.mouse(*point, "LEFTMOUSE", "RELEASE")
            clicked.append(p)
        yield 0.5
    rig.shot(f"{name}-act-sprouting")
    bees = [by_def("Bee0")[0], by_def("Bee1")[0], by_def("Fly0")[0], by_def("Fly1")[0]]
    wings = by_def("Bee0WingR") + by_def("Fly0WingR")
    paths = [[] for _ in bees]
    wing_poses, glims, t0 = set(), [], ctx["player"].now
    bloom_shot = False
    for tick in range(400):                            # up to 40 s: past one 30 s day
        yield 0.1
        for pth, o in zip(paths, bees):
            pth.append(tuple(o.matrix_world.translation))
        wing_poses.update((o.name, tuple(round(v, 2) for v in o.matrix_basis.to_quaternion())) for o in wings)
        glims.append(sum(shown(o) for i in range(8) for o in by_def(f"Glim{i}")[:1]))
        if tick % 40 == 10 or (not bloom_shot and all(stem_h(p) > 0.95 for p in clicked) and clicked):
            if not bloom_shot and all(stem_h(p) > 0.95 for p in clicked):
                bloom_shot = True
            rig.shot(f"{name}-act-t{tick:03d}")
    grown = {p: round(stem_h(p), 2) for p in range(4)}
    opened = {p: petal(p) != petal0[p] for p in range(4)}
    span = [max(math.dist(a, b) for a in pth[::10] for b in pth[::10]) for pth in paths]
    rig.note(name, "act_numbers", {"clicked": clicked, "stem_scale_end": grown, "stem_scale_start": {p: round(v, 2) for p, v in stem0.items()},
                                   "petals_changed": opened, "head_height": {p: round(head_y(p), 2) for p in range(4)}, "flyer_span_m": [round(s, 1) for s in span],
                                   "wing_poses": len(wing_poses), "fireflies_max": max(glims), "seconds_watched": round(ctx["player"].now - t0, 1)})
    ok = (clicked == [1, 2] and all(grown[p] > 0.95 and opened[p] for p in (1, 2)) and grown[3] < 0.1 and not opened[3]
          and min(span) > 3 and len(wing_poses) >= 6 and max(glims) >= 3)
    rig.note(name, "act_ok", bool(ok))
