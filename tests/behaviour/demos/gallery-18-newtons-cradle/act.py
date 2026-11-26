# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-18-newtons-cradle. The eye test's own click on the first sensed ball started one run just
before the act. The act lets it finish, then makes three more choices with real clicks (ball 1: lift two from the left;
ball 5: lift one from the right; ball 2: lift three from the left) and, for each, reads the six pivots' angles from Blender
data to see which balls swung, when, and how far. Times come from the simulator's clock (`player.now`)."""
import math

from mathutils import Euler

EXPECT = {1: {0, 1, 4, 5}, 5: {0, 5}, 2: {0, 1, 2, 3, 4, 5}}      # clicked ball -> pivots that must swing
MOVED = 0.08                                                        # radians: more than this counts as swinging


def act(rig, ctx):
    scene, name, player = ctx["scene"], ctx["name"], ctx["player"]
    by_def = lambda d: [o for o in scene.objects if o.get("x3d_def") == d]
    pivots = [by_def(f"Pivot{i}") for i in range(6)]
    balls = [by_def(f"Ball{i}") for i in range(6)]
    # The importer's Z-up conversion leaves each pivot an EMPTY (quaternion mode) resting at 90 degrees about X; the DEF also sits
    # on the string meshes, which never turn. The swing is the turn away from that rest pose, whatever axis it is about.
    rest = Euler((math.pi / 2, 0.0, 0.0)).to_quaternion()
    angle = lambda os: max((o.matrix_basis.to_quaternion().rotation_difference(rest).angle for o in os if o.type == "EMPTY"), default=0.0)
    angles = lambda: [angle(os) for os in pivots]

    def quiet():
        return all(abs(a) < 0.02 for a in angles())

    def watch(seconds, shots=()):
        """Sample the six swing angles (unsigned) for `seconds` of simulator time; returns per-pivot first move time and the largest swing."""
        start = player.now
        first, hi, shots = [None] * 6, [0.0] * 6, list(shots)
        while player.now - start < seconds:
            yield 0.05
            t = player.now - start
            a = angles()
            for i in range(6):
                hi[i] = max(hi[i], a[i])
                if first[i] is None and abs(a[i]) > MOVED:
                    first[i] = round(t, 2)
            if shots and t >= shots[0][0]:
                rig.shot(f"{name}-act-{shots[0][1]}")
                shots.pop(0)
        return {"first_move_s": first, "max": [round(v, 2) for v in hi]}

    def swung(r):
        return {i for i in range(6) if r["max"][i] > MOVED}

    # the eye test's click: let that run finish (8 s clock) and note which balls it swung
    r0 = yield from watch(9.0)
    settled0 = quiet()
    results, ok = {}, settled0
    for ball, label in ((1, "lift2-left"), (5, "lift1-right"), (2, "lift3-left")):
        point = next((rig.screen_point(o) for o in balls[ball] if rig.screen_point(o)), None)
        if point is None:
            rig.note(name, "act_ok", False)
            return
        rig.mouse(*point)
        yield 0.2
        rig.mouse(*point, "LEFTMOUSE", "PRESS")
        yield 0.1
        rig.mouse(*point, "LEFTMOUSE", "RELEASE")
        # shots: the lifted group high (t about 0.9 s), then the kicked group (t about 3 s)
        r = yield from watch(9.5, shots=[(0.9, f"{label}-1-lifted"), (3.0, f"{label}-2-kicked")])
        got = swung(r)
        lifted = set(range(ball + 1)) if ball < 3 else set(range(ball, 6))
        kicked = got - lifted
        # lifted balls move first; the kicked ones only after the lifted group has fallen (about 2 s into the run)
        late = all(r["first_move_s"][i] is not None and r["first_move_s"][i] >= 1.4 for i in kicked) if kicked else False
        early = all(r["first_move_s"][i] is not None and r["first_move_s"][i] <= 1.4 for i in lifted)
        good = got == EXPECT[ball] and late and early and quiet() and max(r["max"][i] for i in lifted) > 0.45
        results[label] = {"swung": sorted(got), "expected": sorted(EXPECT[ball]), "first_move_s": r["first_move_s"], "max": r["max"],
                          "kicked_after_fall": late, "lifted_first": early, "settled": quiet(), "ok": good}
        ok = ok and good
        yield 0.3
    distinct = len({tuple(v["swung"]) for v in results.values()}) == 3
    rig.note(name, "act_numbers", {"eye_test_click_swung": sorted(swung(r0)), "eye_test_run_settled": settled0, "choices": results, "three_distinct_outcomes": distinct,
                                   "player_now": round(player.now, 2)})
    rig.note(name, "act_ok", bool(ok and distinct))
