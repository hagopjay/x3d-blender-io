# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-07-spirograph: watch the pen draw for 22 s. The key check compares two independent things:
the pen's world position, from three nested Transforms each turned by its own interpolator, against bead 0, which is
replayed from a precomputed curve by a PositionInterpolator. They must agree all along the figure."""
import math


def act(rig, ctx):
    scene, name = ctx["scene"], ctx["name"]
    by_def = lambda d: [o for o in scene.objects if o.get("x3d_def") == d]
    pen = by_def("Pen")
    bead0 = by_def("Bead0")
    bead39 = by_def("Bead39")
    world = lambda objs: tuple(objs[0].matrix_world.translation)
    errors, pen_path, tail_gap = [], [], []
    for tick in range(220):
        yield 0.1
        p, b = world(pen), world(bead0)
        errors.append(math.dist(p, b))
        pen_path.append(p)
        tail_gap.append(math.dist(p, world(bead39)))
        if tick % 25 == 24:
            rig.shot(f"{name}-act-draw-{tick // 25:02d}")
    reach = max(math.dist(p, pen_path[0]) for p in pen_path)
    rig.note(name, "act_numbers", {"pen_vs_bead0_max_error_m": round(max(errors), 3), "pen_vs_bead0_mean_error_m": round(sum(errors) / len(errors), 3),
                                   "pen_reach_m": round(reach, 2), "tail_end_gap_range_m": [round(min(tail_gap), 2), round(max(tail_gap), 2)]})
    rig.note(name, "act_ok", reach > 3 and max(errors) < 0.35 and max(tail_gap) > 1)
