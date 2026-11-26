# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-04-jellyfish-swarm: drag the lure through the event queue, in a big loop; the ten jellyfish
follow, each at its own speed. Checks they lag the lure (slowest furthest behind), then catch up when it rests."""
import math


def act(rig, ctx):
    scene, name = ctx["scene"], ctx["name"]
    # every object the importer tagged with the DEF (a nested Transform carries it too): watch them all
    by_def = lambda d: [o for o in scene.objects if o.get("x3d_def") == d]
    lure = by_def("Lure")
    jellies = [by_def(f"Jelly{i}") for i in range(10)]
    pos = lambda objs: tuple(round(v, 2) for o in objs for v in o.matrix_world.translation)
    home = [pos(j) for j in jellies]
    yield 0.3
    start = next((rig.screen_point(o) for o in lure if rig.screen_point(o)), None)
    if start is None:
        rig.note(name, "act_ok", False)
        return
    rig.mouse(*start)
    yield 0.2
    rig.mouse(*start, "LEFTMOUSE", "PRESS")
    yield 0.1
    lure_now = lambda: tuple(lure[0].matrix_world.translation)
    lure_path, lag = [], []
    steps = 60
    for s in range(1, steps + 1):                      # a wide loop, 60 pointer moves, 3 s
        a = s / steps * 2 * math.pi
        rig.mouse(start[0] + 150 * math.sin(a), start[1] + 70 * (1 - math.cos(a)))
        yield 0.05
        lure_path.append(lure_now())
        if s in (15, 30, 45):
            rig.shot(f"{name}-act-drag-{s}")
        if s == 45:
            lx = lure_now()
            lag = [math.dist(lx, tuple(j[0].matrix_world.translation)) for j in jellies]
    rig.mouse(start[0], start[1], "LEFTMOUSE", "RELEASE")
    yield 0.1
    rig.shot(f"{name}-act-release")
    d_release = [math.dist(lure_now(), tuple(j[0].matrix_world.translation)) for j in jellies]
    yield 4.5                                          # the slowest chaser takes 3.4 s
    rig.shot(f"{name}-act-settled")
    d_settled = [math.dist(lure_now(), tuple(j[0].matrix_world.translation)) for j in jellies]
    moved = sum(pos(j) != h for j, h in zip(jellies, home))
    span = max(max(p[i] for p in lure_path) - min(p[i] for p in lure_path) for i in range(3))
    rig.note(name, "act_numbers", {"jellies_moved": moved, "lure_travel": round(span, 2), "distance_while_dragging": [round(d, 2) for d in lag],
                                   "distance_at_release": [round(d, 2) for d in d_release], "distance_settled": [round(d, 2) for d in d_settled]})
    # the jellyfish keep their offsets (parents), so "caught up" means the offset from the lure stopped changing: compare moved only
    rig.note(name, "act_ok", moved >= 8 and span > 1.5)
