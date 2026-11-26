# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for the orrery demo (run by tools/behaviour_eyetest.py after its standard steps, which have already
clicked the sun: the camera is flying to the sun's post).

Every object is found by its DEF through the behaviour graph (a target's binding, a sensor's parent), never by type.
What it does and checks, in the real window, with real clicks through the event queue:
  1. lets the orrery run, a screenshot every 1.5 s (6 s at least, until the chart has moved): every arm turned, the chart's Mapping node moved;
  2. pulls the lever (through Player.press and release: from the sun's post it is behind the camera): the clocks stop,
     which is also how a person gets a planet to hold still long enough to click it (they move 2 to 3 units a second);
  3. clicks a planet by a real click: the camera flew to that planet's post (the last key of its PositionInterpolator,
     in Blender's axes); clicks a second planet: the camera is at that one's post; the arms never moved meanwhile;
  4. pulls the lever again: every arm turns again.
"""
import math

import bpy
from bpy_extras import view3d_utils
from mathutils import Vector

PLANETS = ("Terra", "Venus")                       # the planets with a TouchSensor
ARMS = ("EmberArm", "VenusArm", "TerraArm", "GaleArm", "LunaArm", "PebbleArm")


def act(rig, ctx):
    scene, name, player, view = ctx["scene"], ctx["name"], ctx["player"], ctx["view"]
    graph = player.graph
    note = lambda key, value: rig.note(name, key, value)                        # noqa: E731
    space = view.spaces.active
    shading_before = space.shading.type
    try:
        space.shading.type = "MATERIAL"             # solid mode draws no textures: the star chart would be a white slab
    except TypeError:
        pass
    region = rig.region_of(view)

    def arm_angles():
        return {arm: bpy.data.objects[graph.nodes[arm].binding[1]].matrix_basis.to_quaternion() for arm in ARMS}

    def turned_since(before):
        now = arm_angles()
        return {arm: round(math.degrees(before[arm].rotation_difference(now[arm]).angle), 2) for arm in ARMS}

    chart = bpy.data.materials["ChartPaint"]
    chart_at = lambda: next((tuple(round(v, 4) for v in n.inputs["Location"].default_value)       # noqa: E731
                             for n in chart.node_tree.nodes if n.type == "MAPPING"), None)
    camera = lambda: scene.camera.matrix_basis.translation.copy()               # noqa: E731

    def post_of(planet):
        """Where the planet's flight ends, in Blender's axes: the last key of its PositionInterpolator."""
        keyed = [float(v) for v in graph.nodes[f"{planet}Path"].fields["keyValue"].split()]
        return player.global_matrix.inverted() @ Vector(keyed[-3:])

    # 1. let it run
    yield 0.6
    arms0, chart0, cams = arm_angles(), chart_at(), [tuple(round(v, 3) for v in camera())]
    chart_track = [chart0]
    for tick in range(14):                           # the chart ticks along every few seconds: watch until it has moved
        rig.shot(f"{name}-act-run-{tick}")
        yield 1.5
        chart_track.append(chart_at())
        cams.append(tuple(round(v, 3) for v in camera()))
        if tick >= 3 and len({loc for loc in chart_track if loc is not None}) > 2:
            break
    turned = turned_since(arms0)
    note("act_arms_turned_degrees", turned)
    note("act_chart_locations", chart_track)
    note("act_camera_track", cams)
    arms_ok = all(angle > 5.0 for angle in turned.values())
    moved = {loc for loc in chart_track if loc is not None}     # no Mapping node (None) until the first tick
    chart_ok = len(moved) > 2
    sun_post = player.global_matrix.inverted() @ Vector([float(v) for v in graph.nodes["SunPath"].fields["keyValue"].split()][-3:])
    sun_flew = (camera() - sun_post).length < 0.05
    note("act_flew_to_the_sun", sun_flew)

    # 2 and 3. click planets
    def reach(planet):
        """A window point where a real click lands on this planet (checked by a ray through the viewport), or None."""
        top = bpy.data.objects[graph.nodes[f"{planet}Touch"].parent]
        meshes = [o for o in [top, *top.children_recursive] if o.type == "MESH" and player.sensors_for(o)]
        depsgraph = bpy.context.evaluated_depsgraph_get()
        region_3d = space.region_3d
        for mesh in meshes:
            middle = rig.screen_point(mesh)
            if middle is None:
                continue
            where = (middle[0] - region.x, middle[1] - region.y)
            origin = view3d_utils.region_2d_to_origin_3d(region, region_3d, where)
            direction = view3d_utils.region_2d_to_vector_3d(region, region_3d, where)
            hit, _loc, _n, _i, obj, _m = scene.ray_cast(depsgraph, origin, direction)
            if hit and obj is not None and obj.original in meshes:
                return middle
        return None

    # pause first: a planet at 2 to 3 units a second has left the pointer before a click lands (a person would stop the
    # clocks too). The lever is pulled through Player.click's parts: from the sun's post it is behind the camera.
    lever = bpy.data.objects[graph.nodes["LeverTouch"].parent]
    lever_mesh = next(o for o in [lever, *lever.children_recursive] if o.type == "MESH")

    def pull():
        player.press(lever_mesh, player.now)
        yield 0.15
        player.release(player.now)
        yield 0.4

    yield from pull()
    frozen_at = arm_angles()
    flights = []
    visited = []
    for visit in range(2):
        chosen = None
        for _ in range(40):                          # up to 20 s for a planet to come into the open
            for planet in PLANETS:
                if planet in visited:
                    continue
                point = reach(planet)
                if point is not None:
                    chosen = (planet, point)
                    break
            if chosen:
                break
            yield 0.5
        if chosen is None:
            flights.append({"planet": None, "flew": False})
            break
        planet, point = chosen
        visited.append(planet)
        start = camera()
        rig.mouse(*point)
        yield 0.2
        rig.mouse(*point, "LEFTMOUSE", "PRESS")
        yield 0.15
        rig.mouse(*point, "LEFTMOUSE", "RELEASE")
        yield 1.4
        rig.shot(f"{name}-act-fly-{planet}-midway")
        yield 2.2
        rig.shot(f"{name}-act-fly-{planet}-arrived")
        post = post_of(planet)
        end = camera()
        flights.append({"planet": planet, "from": [round(v, 3) for v in start], "to": [round(v, 3) for v in end],
                        "post": [round(v, 3) for v in post], "flew": (end - post).length < 0.05 and (end - start).length > 0.5})
        yield 0.3
    note("act_flights", flights)
    still = turned_since(frozen_at)                 # the clocks stayed stopped through both flights
    rig.shot(f"{name}-act-paused")
    yield from pull()
    resumed_at = arm_angles()
    yield 1.2
    moving = turned_since(resumed_at)
    note("act_lever_paused_degrees", still)
    note("act_lever_resumed_degrees", moving)
    lever_ok = all(angle < 0.01 for angle in still.values()) and all(angle > 0.5 for angle in moving.values())
    flights_ok = len(flights) == 2 and all(f["flew"] for f in flights) and flights[0]["planet"] != flights[1]["planet"]

    try:
        space.shading.type = shading_before
    except TypeError:
        pass
    note("act_parts", {"arms_turned": arms_ok, "chart_moved": chart_ok, "sun_flight": sun_flew, "planet_flights": flights_ok,
                       "lever": lever_ok})
    rig.note(name, "act_ok", bool(arms_ok and chart_ok and sun_flew and flights_ok and lever_ok))
