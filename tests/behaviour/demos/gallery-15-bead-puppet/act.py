# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-15-bead-puppet: grab the crossbar through the event queue, sweep it sideways and let go.
Checks the six beads trail the bar (the feet, on the slowest chasers, furthest), the stage glow shows only while the bar is held, and every bead has caught up with the bar after the pointer rests."""
import math

BEADS = ["Head", "Torso", "HandL", "HandR", "FootL", "FootR"]


def act(rig, ctx):
    scene, name = ctx["scene"], ctx["name"]
    by_def = lambda d: [o for o in scene.objects if o.get("x3d_def") == d]      # a DEF'd Transform's unnamed children carry the DEF too
    bar, glow = by_def("Pull"), by_def("Glow")
    beads = {b: by_def(b) for b in BEADS}
    yield 2.0                                              # the eye test's own drag came first: let the slowest chaser (1.5 s) finish before the baseline
    x0 = {id(o): o.matrix_world.translation.x for objs in [bar, *beads.values()] for o in objs}
    shift = lambda objs: max((o.matrix_world.translation.x - x0[id(o)] for o in objs), key=abs)     # how far the DEF'd node moved sideways
    shown = lambda: any(not o.hide_viewport and not o.hide_get() and not getattr(o, "hide_render", False) for o in glow)
    yield 0.3
    start = next((rig.screen_point(o) for o in bar if rig.screen_point(o)), None)
    if start is None:
        rig.note(name, "act_ok", False)
        return
    rig.mouse(*start)
    yield 0.2
    rig.mouse(*start, "LEFTMOUSE", "PRESS")
    yield 0.1
    glow_held, peak, steps = [], {b: -9.0 for b in BEADS}, 24
    side = -1 if bar[0].matrix_world.translation.x > 0 else 1        # the eye test left the bar to one side: sweep toward the other
    for s in range(1, steps + 1):                          # a quick sweep, 24 pointer moves, 1.2 s
        rig.mouse(start[0] + side * 150 * s / steps, start[1])
        yield 0.05
        for b in BEADS:                                    # how far each bead trails the bar, in the direction of travel
            peak[b] = max(peak[b], round(side * (shift(bar) - shift(beads[b])), 2))
        if s == 12:
            glow_held.append(shown())
            rig.shot(f"{name}-act-drag-{s}")
    lag_mid = peak
    bar_right = shift(bar)
    yield 0.8
    rig.shot(f"{name}-act-held")
    end = (start[0] + side * 150, start[1])
    rig.mouse(*end, "LEFTMOUSE", "RELEASE")               # let go where the pointer is, so the bar stays where the drag put it
    yield 0.1
    glow_after = shown()
    gap_release = {b: round(shift(bar) - shift(beads[b]), 2) for b in BEADS}
    rig.shot(f"{name}-act-release")
    yield 2.5                                              # the slowest chaser takes 1.5 s
    rig.shot(f"{name}-act-settled")
    gap_settled = {b: round(shift(bar) - shift(beads[b]), 2) for b in BEADS}
    rig.note(name, "act_numbers", {"bar_shift": round(bar_right, 2), "peak_lag_while_dragging": lag_mid, "gap_at_release": gap_release,
                                   "gap_settled": gap_settled,
                                   "shift_settled": {k: round(shift(v), 2) for k, v in {"Pull": bar, **beads}.items()}, "glow_visible_while_held": glow_held, "glow_visible_after": glow_after})
    ok = (abs(bar_right) > 0.5 and lag_mid["FootR"] > lag_mid["Head"] + 0.1 and lag_mid["FootR"] > 0.3
          and all(glow_held) and not glow_after and all(abs(g) < 0.15 for g in gap_settled.values()))
    rig.note(name, "act_ok", bool(ok))
