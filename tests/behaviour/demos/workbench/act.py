# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for the workbench demo (run by tools/behaviour_eyetest.py after its standard steps).

`act(rig, ctx)` is a generator: yield seconds to wait, Blender keeps drawing between yields. Every drag goes through
Blender's event queue (rig.mouse), a screenshot is taken in the middle of each, and the checks read Blender data:

    fader   drag the knob end to end and back past both limits; the car must start moving after the knob, lag it,
            and catch up
    dial    turn the pointer three quarters of a turn about the dial; the lamp (the shade's emission and the bench light)
            must change colour, sweep, and settle on teal
    globe   sweep across the globe; the globe must turn and the moon must follow it a little later

Objects are found by the DEF the importer recorded, never by type or by name (the importer names the Transform's
empty "Knob.001" and gives the mesh the plain name).
"""

import math
import time

import bpy
from bpy_extras import view3d_utils
from mathutils import Vector


def by_def(scene, def_name, kind=None):
    """The outermost object carrying the DEF (the Transform itself, as the behaviour graph binds it)."""
    found = [o for o in scene.objects if o.get("x3d_def") == def_name and (kind is None or o.type == kind)]
    outer = [o for o in found if o.parent is None or o.parent not in found]
    return (outer or found)[0]


def mesh_of(scene, def_name):
    """The first mesh carrying the DEF (what the pointer lands on)."""
    return next(o for o in scene.objects if o.type == "MESH" and o.get("x3d_def") == def_name)


def lamp_colours(scene):
    """(the shade's emission, the bench light's colour), as Blender has them now."""
    paint = next(m for m in bpy.data.materials if m.get("x3d_def") == "ShadePaint")
    shader = next(n for n in paint.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    return tuple(shader.inputs["Emission Color"].default_value[:3]), tuple(by_def(scene, "BenchLight", "LIGHT").data.color)


def turned(a, b):
    """The angle between two orientations, the short way round (0 to pi)."""
    return 2 * math.acos(min(1.0, abs(a.dot(b))))


def act(rig, ctx):
    scene, name, view = ctx["scene"], ctx["name"], ctx["view"]
    region, r3d = rig.region_of(view), view.spaces.active.region_3d

    def px(world):
        where = view3d_utils.location_3d_to_region_2d(region, r3d, Vector(world))
        return region.x + where.x, region.y + where.y

    def world(obj):
        bpy.context.view_layer.update()
        return obj.matrix_world.translation.copy()

    def drag(path, shot_at, label):
        """Press at path[0], move through the rest one step at a time, shoot at step ``shot_at``, release at the end.
        Yields after each step; ``steps`` collects what each step saw."""
        rig.mouse(*path[0])
        yield 0.12
        rig.mouse(*path[0], "LEFTMOUSE", "PRESS")
        yield 0.06
        for index, point in enumerate(path[1:], 1):
            rig.mouse(*point)
            pointer["at"] = point
            yield 0.04
            if index == shot_at:
                rig.shot(f"{name}-act-{label}-mid-drag", view)
            for watcher in watchers:
                watcher(index)
        rig.mouse(*path[-1], "LEFTMOUSE", "RELEASE")
        yield 0.1

    watchers, pointer = [], {}
    checks = {}

    # the lamp's colours only show in Material Preview, and the pictures read best without the selection outlines
    shading = view.spaces.active.shading
    shading.type = "MATERIAL"
    shading.use_scene_lights = shading.use_scene_world = True              # lit by the bench's own lamps, not Blender's studio
    view.spaces.active.overlay.show_overlays = False
    for obj in scene.objects:
        obj.select_set(False)
    yield 6.0                                                              # EEVEE compiles its shaders on the first draw

    # -- the fader and the car ------------------------------------------------------------------------------------
    knob, car, cap = by_def(scene, "Knob"), by_def(scene, "Car"), mesh_of(scene, "Knob")
    base = world(by_def(scene, "FaderBase"))
    start_x = world(knob).x
    seen = {"knob": None, "car": None}
    first = {"knob": world(knob).x, "car": world(car).x}

    def watch(index):
        for key, obj in (("knob", knob), ("car", car)):
            if seen[key] is None and abs(world(obj).x - first[key]) > 1e-3:
                seen[key] = (index, time.perf_counter())

    drift = []

    def watch_drift(_index):
        # how far the knob's picture is from the pointer sideways, beyond where it was at the press (a PlaneSensor that
        # slides along a line, as X_ITE's does, keeps it at zero; Play's own drag meets the ray with a plane instead)
        drift.append(px(world(cap))[0] - pointer["at"][0])

    watchers.extend([watch, watch_drift])
    grab = world(cap)
    right = [px(grab + Vector((dx, 0, 0))) for dx in (k * 2.6 / 14 for k in range(15))]      # 2.6 m: past +1
    yield from drag(right, 9, "fader-right")
    watchers.clear()
    inside = [d for d, p in zip(drift, right[1:]) if abs(p[0] - right[0][0]) < 1.9 * (px(grab + Vector((1, 0, 0)))[0] - px(grab)[0])]
    rig.note(name, "act_fader_pointer_drift_px", {"largest_before_the_limit": round(max(map(abs, inside), default=0.0), 1),
                                                 "pixels_per_metre_at_the_knob": round(px(grab + Vector((1, 0, 0)))[0] - px(grab)[0], 1)})
    far = world(knob).x
    checks["fader_reached_the_limit"] = abs(far - (base.x + 1.0)) < 0.02                   # clamped at maxPosition
    checks["car_followed_the_fader"] = seen["car"] is not None and seen["knob"] is not None and \
        (seen["car"][0], seen["car"][1]) >= (seen["knob"][0], seen["knob"][1])
    checks["car_lags_then_catches_up"] = False
    left_start = world(cap)
    left = [px(left_start + Vector((-k * 3.4 / 26, 0, 0))) for k in range(27)]               # 3.4 m: past -1
    lag = []

    def watch_lag(index):
        lag.append((index, abs(world(knob).x - world(car).x)))

    watchers.append(watch_lag)
    yield from drag(left, 17, "fader-left")        # the car is well behind the knob here
    watchers.clear()
    yield 1.4
    near = world(knob).x
    checks["fader_reached_both_limits"] = abs(near - (base.x - 1.0)) < 0.02
    checks["car_lags_then_catches_up"] = max(gap for _i, gap in lag) > 0.15 and abs(world(car).x - near) < 0.03
    rig.note(name, "act_fader", {"start_x": round(start_x - base.x, 3), "right_limit": round(far - base.x, 3),
                                 "left_limit": round(near - base.x, 3), "worst_lag_m": round(max(g for _i, g in lag), 3),
                                 "car_settled": round(world(car).x - base.x, 3)})
    rig.shot(f"{name}-act-fader-settled", view)

    # -- the dial and the lamp ---------------------------------------------------------------------------------------
    pivot = by_def(scene, "DialBase")
    axes = pivot.matrix_world.to_3x3()
    ex, ez, ey = ((axes @ Vector(v)).normalized() for v in ((1, 0, 0), (0, 0, 1), (0, 1, 0)))
    face = world(pivot) + ey * 0.15
    around = lambda angle, r=0.32: px(face + (ex * math.cos(angle) + ez * math.sin(angle)) * r)   # noqa: E731
    colours = [lamp_colours(scene)]
    path = [around(0.8 + 0.12 * k) for k in range(40)]                                          # 3/4 of a turn
    dial = by_def(scene, "Dial")
    before, peak = dial.matrix_basis.to_quaternion(), [0.0]

    def watch_colour(_index):
        colours.append(lamp_colours(scene))
        peak[0] = max(peak[0], turned(before, dial.matrix_basis.to_quaternion()))

    watchers.append(watch_colour)
    yield from drag(path, 20, "dial")
    watchers.clear()
    for _ in range(26):                                                    # the 2 s sweep and the 3 s chaser, to the end
        yield 0.25
        colours.append(lamp_colours(scene))
        if _ == 5:
            rig.shot(f"{name}-act-dial-sweep", view)
            rig.shot(f"{name}-act-dial-sweep-window")                      # with the node editor glowing beside it
    spin = peak[0]                                          # the furthest the dial was from where it began, in radians
    shade = [c[0] for c in colours]
    drift = max(max(abs(a - b) for a, b in zip(c, shade[0])) for c in shade)
    final, light = colours[-1]
    checks["dial_turned"] = spin > 2.0
    checks["lamp_changed_colour"] = drift > 0.2
    checks["lamp_settled_on_teal"] = final[2] > final[0] + 0.3 and light[2] > light[0] + 0.3
    rig.note(name, "act_dial", {"furthest_from_start_rad": round(spin, 3), "shade_first": [round(c, 3) for c in shade[0]],
                                "shade_last": [round(c, 3) for c in final], "light_last": [round(c, 3) for c in light],
                                "largest_change": round(drift, 3), "samples": len(colours)})
    rig.shot(f"{name}-act-dial-settled", view)

    # -- the globe and the moon ------------------------------------------------------------------------------------
    globe, moon = by_def(scene, "Globe"), by_def(scene, "MoonArm")
    globe_before, moon_before = globe.matrix_basis.to_quaternion(), moon.matrix_basis.to_quaternion()
    middle = world(mesh_of(scene, "Globe"))
    press = Vector(px(middle)) + Vector((-14, 10))
    sweep = [tuple(press + Vector((9 * k, -6 * k))) for k in range(17)] + \
        [tuple(press + Vector((144 - 7 * k, -96 + 9 * k))) for k in range(1, 17)]
    trail = []

    def watch_moon(_index):
        trail.append((turned(globe_before, globe.matrix_basis.to_quaternion()),
                      turned(moon_before, moon.matrix_basis.to_quaternion())))

    watchers.append(watch_moon)
    yield from drag(sweep, 14, "globe")
    watchers.clear()
    after_globe = turned(globe_before, globe.matrix_basis.to_quaternion())
    moon_now = turned(moon_before, moon.matrix_basis.to_quaternion())
    yield 3.5
    moon_late = turned(moon_before, moon.matrix_basis.to_quaternion())
    gap_late = turned(globe.matrix_basis.to_quaternion(), moon.matrix_basis.to_quaternion())
    checks["globe_turned"] = after_globe > 0.3
    checks["moon_turned"] = moon_late > 0.3
    checks["moon_trails_the_globe"] = any(m < g - 0.05 for g, m in trail) and gap_late < 0.05
    rig.note(name, "act_globe", {"globe_turned_rad": round(after_globe, 3), "moon_turned_rad_at_release": round(moon_now, 3),
                                 "moon_turned_rad_3_5s_later": round(moon_late, 3),
                                 "moon_to_globe_gap_rad": round(gap_late, 3),
                                 "largest_trail_rad": round(max(g - m for g, m in trail), 3)})
    rig.shot(f"{name}-act-globe-settled", view)

    rig.note(name, "act_checks", checks)
    rig.note(name, "act_ok", all(checks.values()))
