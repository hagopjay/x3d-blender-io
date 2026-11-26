# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-17-ripple-city. The eye test's own click has already pressed the pedestal (diagonal sweep
is on). Watch 8 s, click (back to rings), watch 8 s, click again. In ring mode all towers of one ring must share a height
(and not all rings the same); in diagonal mode all towers of one diagonal must; both modes must move."""
import math

N = 10


def act(rig, ctx):
    scene, name = ctx["scene"], ctx["name"]
    by_def = lambda d: [o for o in scene.objects if o.get("x3d_def") == d]
    towers = {(i, j): by_def(f"Tower{i}_{j}") for i in range(N) for j in range(N)}
    height = lambda os: max(sum(o.scale) for o in os)                     # the importer swaps X3D y into a Blender axis; the sum is axis-agnostic (the other two stay 1)
    c = (N - 1) / 2
    classes = {"ring": lambda i, j: int(round(math.hypot(i - c, j - c))), "diag": lambda i, j: i + j}
    point = next((rig.screen_point(o) for o in by_def("Pedestal") if rig.screen_point(o)), None)

    def click():
        rig.mouse(*point)
        yield 0.2
        rig.mouse(*point, "LEFTMOUSE", "PRESS")
        yield 0.1
        rig.mouse(*point, "LEFTMOUSE", "RELEASE")

    def watch(seconds, kind):
        """returns (distinct poses, worst height spread inside a class, spread of class means at last sample)"""
        poses, worst, means = set(), 0.0, 0.0
        for _ in range(int(seconds * 5)):
            yield 0.2
            hs = {k: height(o) for k, o in towers.items()}
            poses.add(tuple(round(hs[(i, 0)], 2) for i in range(N)))
            groups = {}
            for (i, j), h in hs.items():
                groups.setdefault(classes[kind](i, j), []).append(h)
            worst = max(worst, max(max(g) - min(g) for g in groups.values()))
            ms = [sum(g) / len(g) for g in groups.values()]
            means = max(ms) - min(ms)
        return len(poses), worst, means

    yield 1.0
    d_poses, d_in, d_between = yield from watch(8, "diag")
    rig.shot(f"{name}-act-1-diagonal")
    yield from click()
    yield 1.0
    r_poses, r_in, r_between = yield from watch(8, "ring")
    rig.shot(f"{name}-act-2-rings")
    yield from click()
    yield 1.0
    d2_poses, d2_in, _ = yield from watch(3, "diag")
    rig.shot(f"{name}-act-3-diagonal-again")
    rig.note(name, "act_numbers", {"diag_poses": d_poses, "diag_spread_in_class": round(d_in, 3), "diag_between_classes": round(d_between, 3),
                                   "ring_poses": r_poses, "ring_spread_in_class": round(r_in, 3), "ring_between_classes": round(r_between, 3),
                                   "diag_again_poses": d2_poses, "diag_again_spread": round(d2_in, 3)})
    rig.note(name, "act_ok", d_poses > 10 and r_poses > 10 and d2_poses > 3 and d_in < 0.05 and r_in < 0.05 and d2_in < 0.05 and d_between > 0.3 and r_between > 0.3)
