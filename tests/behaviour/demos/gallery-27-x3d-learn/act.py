# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-27-x3d-learn. The eye test's own click on the green TouchSensor button has already started
the relay (T1 runs just before the act). The act watches the one run, one station after another, sampling 4 times a
second for at most 62 s: which stage lamp is lit and in which order, which wire beads ride, and the station effects
(fill bar scale, cube height, spinner turn, bulbs, chased ball, finale sparks). Success means each effect STARTED from
rest (a 3 s effect is never traced as an arc). After the run it picks a point on the button whose own ray hits it
(at most 10 candidate points, one click) and checks that stage 1 lights again. Screenshots at stations 1, 3, 4, 6, 7, 8."""
import math


def act(rig, ctx):
    scene, name = ctx["scene"], ctx["name"]
    by_def = lambda d: [o for o in scene.objects if o.get("x3d_def") == d]
    shown = lambda o: not (o.hide_viewport or o.hide_get())
    lamps = {k: by_def(f"Lamp{k}") for k in range(1, 9)}
    beads = {k: by_def(f"Bead{k}") for k in range(1, 8)}
    fill, cube, ball = by_def("Fill3"), by_def("Cube4"), by_def("Ball7")
    spin = by_def("Spin5")
    bulbs = {i: by_def(f"Bulb6_{i}") for i in range(6)}
    sparks = [by_def(f"Spark8_{i}") for i in range(8)]
    lit = lambda objs: any(shown(o) for o in objs)
    fill_x = lambda: max(o.matrix_world.to_scale().x for o in fill)
    cube_z = lambda: max(o.matrix_world.translation.z for o in cube)
    ball_x = lambda: max(o.matrix_world.translation.x for o in ball)
    q0 = spin[0].matrix_world.to_quaternion() if spin else None
    turn = lambda: spin[0].matrix_world.to_quaternion().rotation_difference(q0).angle if spin else 0.0
    rest = {"fill": fill_x(), "cube": cube_z(), "ball": ball_x()}
    order, bead_seen, bulbs_seen = [], set(), set()
    fill_max, cube_max, turn_max, ball_min, ball_max, spark_max = rest["fill"], rest["cube"], 0.0, rest["ball"], rest["ball"], 0
    shots = {1, 3, 4, 6, 7, 8}
    done_at = None
    for tick in range(248):
        yield 0.25
        for k, objs in lamps.items():
            if lit(objs):
                if k not in order:
                    order.append(k)
                    if k in shots:
                        rig.shot(f"{name}-act-stage{k}")
        for k, objs in beads.items():
            if lit(objs):
                bead_seen.add(k)
        for i, objs in bulbs.items():
            if lit(objs):
                bulbs_seen.add(i)
        fill_max, cube_max = max(fill_max, fill_x()), max(cube_max, cube_z())
        turn_max = max(turn_max, turn())
        ball_min, ball_max = min(ball_min, ball_x()), max(ball_max, ball_x())
        spark_max = max(spark_max, sum(lit(s) for s in sparks))
        if 8 in order and not lit(lamps[8]):
            done_at = done_at if done_at is not None else tick
            if tick - done_at >= 4:
                break
    rig.shot(f"{name}-act-after-run")
    # a second click, only on a point whose own ray hits the button
    second_started, tried, hit_name = False, 0, None
    try:
        import bpy
        from bpy_extras import view3d_utils
        view = ctx["view"]
        region = next(r for r in view.regions if r.type == "WINDOW")
        r3d = view.spaces.active.region_3d
        target = by_def("Start")
        point = rig.screen_point(target[0]) if target else None
        names = {o.name for o in target}
        names |= {c.name for o in target for c in o.children_recursive}
        good = None
        if point:
            for dx, dy in ((0, 0), (10, 0), (-10, 0), (0, 10), (0, -10), (18, 0), (-18, 0), (0, 18), (0, -18), (6, 6)):
                if tried >= 10:
                    break
                tried += 1
                px, py = point[0] + dx, point[1] + dy
                co = (px - region.x, py - region.y)
                origin = view3d_utils.region_2d_to_origin_3d(region, r3d, co)
                direction = view3d_utils.region_2d_to_vector_3d(region, r3d, co)
                ok, loc, nrm, idx, obj, mat = scene.ray_cast(bpy.context.evaluated_depsgraph_get(), origin, direction)
                if ok and obj is not None and (obj.name in names or obj.get("x3d_def") == "Start"):
                    good, hit_name = (px, py), obj.name
                    break
        if good:
            rig.mouse(*good)
            yield 0.2
            rig.mouse(*good, "LEFTMOUSE", "PRESS")
            yield 0.1
            rig.mouse(*good, "LEFTMOUSE", "RELEASE")
            for _ in range(24):
                yield 0.25
                if lit(lamps[1]):
                    second_started = True
                    break
    except Exception as error:                     # the second click is a bonus; its failure is reported, not hidden
        rig.note(name, "second_click_error", repr(error))
    rig.shot(f"{name}-act-second-click")
    rig.note(name, "act_numbers", {
        "stage_order": order, "beads_seen": sorted(bead_seen), "bulbs_seen": sorted(bulbs_seen),
        "fill_scale_rest_max": [round(rest["fill"], 3), round(fill_max, 3)],
        "cube_height_rest_max_m": [round(rest["cube"], 2), round(cube_max, 2)],
        "spinner_max_turn_rad": round(turn_max, 2), "ball_x_min_max": [round(ball_min, 2), round(ball_max, 2)],
        "sparks_at_once": spark_max, "second_click_ray_tries": tried, "second_click_hit": hit_name,
        "second_click_restarted_stage1": second_started})
    ascending = order == sorted(order)
    rig.note(name, "act_ok", ascending and len(order) == 8 and len(bead_seen) >= 6 and fill_max > rest["fill"] + 0.5
             and cube_max > rest["cube"] + 0.5 and turn_max > 0.5 and len(bulbs_seen) >= 4 and ball_max - ball_min > 1.0 and spark_max >= 4)
