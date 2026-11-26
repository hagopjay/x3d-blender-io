# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-08-spirograph-chain: watch 20 s. Checks, every 0.1 s: the pen (three nested Transforms)
agrees with bead 0 (a replayed curve) in x and y; the 60 beads form a connected snake (neighbours close together) that
spans several metres, and the whole snake moves."""
import math


def act(rig, ctx):
    scene, name = ctx["scene"], ctx["name"]
    by_def = lambda d: [o for o in scene.objects if o.get("x3d_def") == d]
    pen, beads = by_def("Pen")[0], [by_def(f"Bead{i}")[0] for i in range(60)]
    xy = lambda o: (o.matrix_world.translation.x, o.matrix_world.translation.z)      # X3D x, y in Blender's x, z
    pen_err, joins, spans, tail_pos = [], [], [], []
    for tick in range(200):
        yield 0.1
        if tick < 20:
            continue                                  # the chain fills in during the first 2 s
        pen_err.append(math.dist(xy(pen), xy(beads[0])))
        pts = [xy(b) for b in beads]
        joins.append(max(math.dist(a, b) for a, b in zip(pts, pts[1:])))
        spans.append(math.dist(pts[0], pts[-1]))
        tail_pos.append(pts[-1])
        if tick % 25 == 24:
            rig.shot(f"{name}-act-draw-{tick // 25:02d}")
    tail_travel = max(math.dist(p, tail_pos[0]) for p in tail_pos)
    rig.note(name, "act_numbers", {"pen_vs_bead0_max_xy_error_m": round(max(pen_err), 3), "largest_gap_between_neighbour_beads_m": round(max(joins), 2),
                                   "head_to_tail_distance_m": [round(min(spans), 2), round(max(spans), 2)], "tail_travel_m": round(tail_travel, 2)})
    rig.note(name, "act_ok", max(pen_err) < 0.2 and max(joins) < 3.0 and max(spans) > 3 and tail_travel > 3)
