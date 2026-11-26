# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The World (source/behaviour_world.py) and the three sensors that read it: TransformSensor, VisibilitySensor and
Collision (its collideTime), against X_ITE 16.8.1's own recording of tests/behaviour/probe-world.x3d. No Blender.

    python -m unittest tests.test_behaviour_world
"""

from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source"))
sys.path.insert(0, str(ROOT / "tools"))

import behaviour_graph as bg            # noqa: E402
import behaviour_sim as bs              # noqa: E402
import behaviour_sim_judge as judge     # noqa: E402
import behaviour_world as bw            # noqa: E402

WORLDS = ROOT / "tests" / "behaviour"


def x3d(body, head=""):
    return f'<X3D profile="Immersive" version="4.0"><head/><Scene>{head}{body}</Scene></X3D>'


def run(text, seconds, fps=60.0, world=True, setup=None):
    """The Simulation of ``text`` stepped to ``seconds``; returns (sim, [(time, node, field, value)])."""
    graph = bg.Behaviour.from_x3d(text)
    sim = bs.Simulation(graph, log_size=10 ** 6, world=bw.World.from_x3d(text) if world else None)
    if setup:
        setup(sim)
    sim.start(0.0)
    for frame in range(1, int(seconds * fps) + 1):
        sim.step(frame / fps)
    return sim, list(sim.log)


def sent(log, node, field):
    return [(round(when, 4), value) for when, n, f, value in log if n == node and f == field]


class MathTests(unittest.TestCase):

    def test_a_transform_is_t_c_r_sr_s_inverse_sr_inverse_c(self):
        m = bw.m_transform((1, 2, 3), (0, 0, 1, math.pi / 2), (2, 1, 1), (1, 0, 0), (0, 0, 1, 0))
        # centre (1,0,0), turn a quarter about z, scale x by 2: the point (2,0,0) is 1 right of the centre -> scaled to 2
        # right -> turned up to (0,2,0) from the centre -> plus the centre and the translation
        x, y, z = bw.m_point(m, (2, 0, 0))
        self.assertAlmostEqual(x, 1 + 1, places=12)
        self.assertAlmostEqual(y, 2 + 2, places=12)
        self.assertAlmostEqual(z, 3, places=12)

    def test_the_inverse_undoes_a_matrix_and_a_flat_one_has_none(self):
        m = bw.m_transform((1, 2, 3), (1, 1, 0, 0.7), (2, 3, 4))
        back = bw.m_mul(bw.m_inverse(m), m)
        self.assertTrue(all(abs(a - b) < 1e-12 for a, b in zip(back, bw.IDENTITY)))
        self.assertIsNone(bw.m_inverse(bw.m_transform(scale=(1, 0, 1))))

    def test_the_rotation_of_a_matrix_has_scale_and_shear_taken_out(self):
        turn = (0.3, 0.5, 0.8, 1.1)
        m = bw.m_mul(bw.m_rotate(turn), bw.m_mul(bw.m_rotate((0, 0, 1, 0.5)), bw.m_mul(bw.m_scale((3, 1, 0.5)),
                                                                                    bw.m_rotate((0, 0, 1, -0.5)))))
        self.assertLess(bs._rotation_distance(bw.rotation_of(m), turn), 1e-9)
        self.assertEqual(bw.rotation_of(bw.IDENTITY), (0.0, 0.0, 1.0, 0.0))
        half = bw.rotation_of(bw.m_rotate((0, 1, 0, math.pi)))
        self.assertAlmostEqual(abs(half[1]), 1.0, places=6)
        self.assertAlmostEqual(half[3], math.pi, places=6)

    def test_a_box_holds_its_edges_and_size_minus_one_holds_everything(self):
        self.assertTrue(bw.box_contains((0, 0, 0), (2, 2, 2), (1, -1, 1)))
        self.assertFalse(bw.box_contains((0, 0, 0), (2, 2, 2), (1.0000001, 0, 0)))
        self.assertTrue(bw.box_contains((0, 0, 0), (-1, -1, -1), (1e9, 0, 0)))
        self.assertTrue(bw.box_contains((1, 0, 0), (0, 0, 0), (1, 0, 0)))          # a box of no width holds its centre

    def test_a_hostile_value_is_not_finite_and_is_refused(self):
        world = bw.World.from_x3d(x3d('<Transform DEF="T"><Shape><Box/></Shape></Transform>'))
        self.assertFalse(world.apply("T", "translation", (math.nan, 0, 0)))
        self.assertFalse(world.apply("T", "translation", (1, 2)))
        self.assertFalse(world.apply("T", "rotation", (0, 0, 1)))
        self.assertTrue(world.apply("T", "translation", (1, 2, 3)))
        self.assertEqual(bw.m_point(world.matrix("T"), (0, 0, 0)), (1, 2, 3))


class BuildTests(unittest.TestCase):

    def setUp(self):
        self.text = (WORLDS / "probe-world.x3d").read_text(encoding="utf-8")
        self.world = bw.World.from_x3d(self.text)

    def test_the_scene_is_read_into_frames_sensors_targets_and_collisions(self):
        w = self.world
        self.assertEqual(w.sensors["Gauge"], "Slot")
        self.assertIsNone(w.sensors["Always"])                           # at the scene root
        self.assertEqual(w.sensor_target, {"Gauge": "Ball", "Everywhere": "Ball", "Skew": "Crate"})
        self.assertEqual(sorted(w.collisions), ["Pillar", "Wall"])
        self.assertEqual(w.viewpoint, "Eye")
        self.assertEqual(w.viewer.position, (0.0, 1.6, 12.0))
        self.assertEqual(w.avatar_size, (0.25, 1.6, 0.75))

    def test_a_frame_matrix_follows_the_hierarchy_and_a_route_moves_only_what_it_moves(self):
        w = self.world
        slot = w.matrix("Slot")
        self.assertEqual(bw.m_point(slot, (0, 0, 0)), (-4.0, 0.0, -2.0))
        self.assertIs(w.matrix("Slot"), slot)                              # not worked out again
        w.apply("Ball", "translation", (1, 2, 3))
        self.assertIs(w.matrix("Slot"), slot)
        self.assertEqual(bw.m_point(w.matrix("Ball"), (0, 0, 0)), (1.0, 2.0, 3.0))

    def test_moving_a_parent_moves_what_hangs_below(self):
        world = bw.World.from_x3d(x3d('<Transform DEF="A"><Transform DEF="B" translation="0 1 0">'
                                      '<ProximitySensor DEF="S" size="1 1 1"/></Transform></Transform>'))
        self.assertEqual(bw.m_point(world.sensor_matrix("S"), (0, 0, 0)), (0.0, 1.0, 0.0))
        world.apply("A", "translation", (5, 0, 0))
        self.assertEqual(bw.m_point(world.sensor_matrix("S"), (0, 0, 0)), (5.0, 1.0, 0.0))

    def test_a_frame_handed_in_from_outside_is_used_as_it_is(self):
        world = bw.World()
        world.set_frame_matrix("S", bw.m_translate((1, 2, 3)))
        world.sensors["S"] = "S"
        self.assertEqual(world.to_local("S", (1, 2, 4)), (0.0, 0.0, 1.0))
        with self.assertRaises(ValueError):
            world.set_frame_matrix("S", [math.nan] * 16)

    def test_what_the_scene_does_not_say_is_noted(self):
        world = bw.World.from_x3d(x3d('<Collision DEF="C"><Shape><Sphere/></Shape></Collision>'
                                      '<Transform DEF="G"><Transform DEF="H"/></Transform><Group DEF="U"/>'
                                      '<TransformSensor DEF="Lost" size="1 1 1"><Transform USE="Missing" containerField="targetObject"/>'
                                      '</TransformSensor>'))
        self.assertEqual(world.noted.get("bounds-for-geometry"), 1)
        self.assertEqual(world.noted.get("no-target"), 1)
        self.assertNotIn("Lost", world.sensor_target)


class ProximityOnTheWorldTests(unittest.TestCase):
    """The ProximitySensor reads the viewer from the World: ``Simulation.view`` (world coordinates) must give the events
    ``Simulation.viewer`` (the sensor's own coordinates, worked out by hand) gave, on X_ITE's own flight."""

    def test_the_same_events_from_the_world_as_from_the_hand_made_coordinates(self):
        trace = json.loads((WORLDS / "x_ite_traces" / "probe-proximity.json").read_text(encoding="utf-8"))
        logs = []
        original = bs.Simulation
        try:
            for world_viewer in (False, True):
                captured = []

                class Capture(original):
                    def __init__(self, *args, **kwargs):
                        super().__init__(*args, **kwargs)
                        captured.append(self)

                bs.Simulation = Capture
                result = judge.judge(WORLDS / "probe-proximity.x3d", trace, world_viewer=world_viewer)
                self.assertEqual([s["source"] for s in result["streams"] if not s["agree"]], [])
                self.assertEqual(len(result["streams"]), 13)
                logs.append(list(captured[0].log))
        finally:
            bs.Simulation = original
        by_hand, from_world = (sorted(log, key=lambda e: (e[0], e[1], e[2], repr(e[3]))) for log in logs)
        # Cam is the driver (a root sensor of size -1 that reports the viewer): X_ITE's events are replayed in one run and
        # the world runs it in the other, so it and GateEcho (fed only by its first centre of rotation) are left out
        by_hand = [e for e in by_hand if e[1] not in ("Cam", "GateEcho")]
        from_world = [e for e in from_world if e[1] not in ("Cam", "GateEcho")]
        self.assertGreater(len(by_hand), 1000)
        self.assertEqual([(w, n, f) for w, n, f, _ in by_hand], [(w, n, f) for w, n, f, _ in from_world])
        for (_w, n, f, a), (_w2, _n2, _f2, b) in zip(by_hand, from_world):
            if isinstance(a, tuple):
                self.assertTrue(all(abs(x - y) < 1e-9 for x, y in zip(a, b)), (n, f, a, b))
            else:
                self.assertEqual(a, b, (n, f))

    def test_view_without_a_world_or_a_frame_sends_nothing_and_says_so(self):
        text = x3d('<Transform DEF="T"><ProximitySensor DEF="P" size="2 2 2"/></Transform>')
        sim = bs.Simulation(bg.Behaviour.from_x3d(text))
        self.assertEqual(sim.view((0, 0, 0), (0, 0, 1, 0), 0.0), [])
        self.assertEqual(sim.noted["no-world"], 1)
        sim = bs.Simulation(bg.Behaviour.from_x3d(text), world=bw.World())
        self.assertEqual(sim.view((0, 0, 0), (0, 0, 1, 0), 0.0), [])
        self.assertEqual(sim.noted["no-frame"], 1)

    def test_view_moves_the_sensor_with_its_frame(self):
        text = x3d('<Transform DEF="T" translation="10 0 0"><ProximitySensor DEF="P" size="2 2 2"/></Transform>')
        sim = bs.Simulation(bg.Behaviour.from_x3d(text), world=bw.World.from_x3d(text))
        sim.start(0.0)
        sim.view((0, 0, 0), (0, 0, 1, 0), 0.1)
        self.assertNotIn(("P", "isActive"), sim.outputs)
        sim.view((10, 0.5, 0), (0, 0, 1, 0), 0.2)
        self.assertIs(sim.outputs[("P", "isActive")], True)
        self.assertEqual(sim.outputs[("P", "position_changed")], (0.0, 0.5, 0.0))


class FrustumTests(unittest.TestCase):

    def setUp(self):
        self.volume = bw.view_volume(math.pi / 4, 1.6, 0.125, 1e5)

    def meets(self, center, size=(1, 1, 1), turn=(0, 0, 1, 0)):
        m = bw.m_rotate(turn)
        half = tuple(bw.m_dir(m, tuple(size[k] / 2 if j == k else 0.0 for k in range(3))) for j in range(3))
        return bw.frustum_meets_box(self.volume, center, half)

    def test_a_box_ahead_is_in_and_one_behind_or_far_aside_is_out(self):
        self.assertTrue(self.meets((0, 0, -10)))
        self.assertFalse(self.meets((0, 0, 10)))
        self.assertFalse(self.meets((50, 0, -10)))
        self.assertFalse(self.meets((0, 20, -10)))

    def test_the_field_of_view_is_the_smaller_angle_of_the_window(self):
        # 45 degrees across the height: at 10 m ahead the view is 4.14 m high and 6.63 m wide (aspect 1.6)
        self.assertTrue(self.meets((0, 3.0, -10)))
        self.assertFalse(self.meets((0, 5.0, -10)))
        self.assertTrue(self.meets((5.0, 0, -10)))
        self.assertFalse(self.meets((8.0, 0, -10)))

    def test_a_box_that_is_a_point_is_in_when_the_point_is(self):
        self.assertTrue(self.meets((0, 0, -10), (0, 0, 0)))
        self.assertFalse(self.meets((0, 0, 10), (0, 0, 0)))

    def test_x_ite_s_edge_axis_table_is_replicated_and_differs_from_the_exact_test(self):
        # X_ITE fills its 24 cross-product axes at i1 * 3 + i2, so only 14 slots survive; the box below is separated from
        # the frustum on an axis that is lost, and X_ITE (and so this function) says it meets the frustum. The recorded
        # probe (Tilt1 to Tilt3) fails with the exact test and passes with this one.
        center = (8.631316465059008, 4.928101777844059, -10.6240057606209)
        turn = (0.10736909890728152, -0.17561050934733058, 0.4312866688319401, 0.8435011118533233)
        m = bw.m_rotate(turn)
        size = (0.36960700697205084, 2.7627097636551996, 3.5885882632767694)
        half = tuple(bw.m_dir(m, tuple(size[k] / 2 if j == k else 0.0 for k in range(3))) for j in range(3))
        self.assertTrue(bw.frustum_meets_box(self.volume, center, half))
        points = bw._box_corners(center, half)
        p = self.volume
        edges = [bw._sub(p[0], p[1]), bw._sub(p[1], p[2]), bw._sub(p[2], p[3]), bw._sub(p[3], p[0]), bw._sub(p[0], p[4]),
                 bw._sub(p[1], p[5]), bw._sub(p[2], p[6]), bw._sub(p[3], p[7])]
        exact = [bw._cross(axis, edge) for axis in half for edge in edges]
        self.assertTrue(bw._separated(exact, points, list(p)))


class CollisionTests(unittest.TestCase):

    def world(self, viewer=(0, 1.6, 0), enabled="true"):
        world = bw.World.from_x3d(x3d(
            f'<Collision DEF="Wall" enabled="{enabled}"><Transform translation="0 1 -6.2">'
            '<Shape><Box size="6 3 0.4"/></Shape></Transform></Collision>'
            '<Viewpoint DEF="Eye" position="0 1.6 0"/>'))
        world.viewer.position = viewer
        return world

    def test_the_viewer_touches_a_wall_within_the_avatar_radius_times_root_two(self):
        self.assertEqual(self.world((0, 1.6, -5.60)).collision_hits(), set())          # 0.40 off: not yet
        self.assertEqual(self.world((0, 1.6, -5.70)).collision_hits(), {"Wall"})       # 0.30 off
        self.assertEqual(self.world((0, 1.6, -5.50)).collision_hits(), set())          # 0.50 off
        self.assertEqual(self.world((0, 1.6, -5.65)).collision_hits(), {"Wall"})       # 0.35 off, inside 0.3536
        self.assertEqual(self.world((0, 1.6, -5.64)).collision_hits(), set())          # 0.36 off

    def test_a_wall_beside_the_viewer_is_not_a_wall_ahead(self):
        # standing 0.2 from the wall's end face but looking along it: the wall's face is edge on to the look straight ahead
        # (-z), yet the look sideways (+x) sees it
        world = self.world((-3.2, 1.6, -6.2))
        self.assertEqual(world.collision_hits(), {"Wall"})                              # its end face is 0.2 along +x
        far = self.world((-5.0, 1.6, -6.2))
        self.assertEqual(far.collision_hits(), set())

    def test_a_disabled_collision_is_never_touched(self):
        self.assertEqual(self.world((0, 1.6, -5.8), enabled="false").collision_hits(), set())
        world = self.world((0, 1.6, -5.8))
        world.apply("Wall", "enabled", False)
        self.assertEqual(world.collision_hits(), set())

    def test_the_slab_is_below_the_eye_not_above_it(self):
        # the slab reaches 0.85 below the eye and 0.25 above: a low obstacle is hit, a high one 0.5 up is not
        low = bw.World.from_x3d(x3d('<Collision DEF="C"><Transform translation="0 0.9 -1"><Shape><Box size="1 0.2 0.2"/></Shape>'
                                    '</Transform></Collision><Viewpoint position="0 1.6 -0.7"/>'))
        high = bw.World.from_x3d(x3d('<Collision DEF="C"><Transform translation="0 2.5 -1"><Shape><Box size="1 0.2 0.2"/></Shape>'
                                     '</Transform></Collision><Viewpoint position="0 1.6 -0.7"/>'))
        self.assertEqual(low.collision_hits(), {"C"})
        self.assertEqual(high.collision_hits(), set())

    def test_the_closest_shape_decides_and_every_collision_above_it_is_active(self):
        world = bw.World.from_x3d(x3d(
            '<Collision DEF="Outer"><Collision DEF="Inner"><Transform translation="0 0 -1"><Shape><Box size="2 2 0.2"/></Shape>'
            '</Transform></Collision></Collision><Collision DEF="Behind"><Transform translation="0 0 -1.5">'
            '<Shape><Box size="2 2 0.2"/></Shape></Transform></Collision><Viewpoint position="0 0 -0.7"/>'))
        self.assertEqual(world.collision_hits(), {"Inner", "Outer"})

    def test_a_viewer_in_a_frame_looks_along_that_frame_s_axes(self):
        world = bw.World.from_x3d(x3d(
            '<Transform DEF="Room" translation="10 0 0"><Collision DEF="C"><Transform translation="0 0 -1">'
            '<Shape><Box size="2 2 0.2"/></Shape></Transform></Collision><Viewpoint DEF="Eye" position="0 0 -0.7"/></Transform>'))
        self.assertEqual(world.collision_hits(), {"C"})
        world.apply("Room", "translation", (50, 0, 0))                                  # both move: still touching
        self.assertEqual(world.collision_hits(), {"C"})


class SensorTests(unittest.TestCase):
    """The three sensors in small worlds the test builds itself (the recorded one is judged below)."""

    BALL = ('<Transform DEF="Ball" translation="-3 0 0"><Shape><Sphere radius="0.1"/></Shape></Transform>'
            '<Transform DEF="Slot"><TransformSensor DEF="Gauge" size="2 2 2" center="0 0 0">'
            '<Transform USE="Ball" containerField="targetObject"/></TransformSensor></Transform>'
            '<TimeSensor DEF="Clock" cycleInterval="2" loop="true"/>'
            '<PositionInterpolator DEF="Path" key="0 1" keyValue="-3 0 0  3 0 0"/>'
            '<ROUTE fromNode="Clock" fromField="fraction_changed" toNode="Path" toField="set_fraction"/>'
            '<ROUTE fromNode="Path" fromField="value_changed" toNode="Ball" toField="translation"/>'
            '<Transform DEF="Sink"/>'
            '<ROUTE fromNode="Gauge" fromField="isActive" toNode="Sink" toField="visible"/>')

    def test_a_target_driven_through_the_box_enters_reports_and_leaves(self):
        sim, log = run(x3d(self.BALL), 2.0)
        active = sent(log, "Gauge", "isActive")
        self.assertEqual([v for _t, v in active], [True, False])
        self.assertAlmostEqual(active[0][0], 2 / 3, delta=1 / 60)         # x = -1 at a third of the way
        self.assertAlmostEqual(active[1][0], 4 / 3 + 1 / 60, delta=1 / 60)
        self.assertEqual(sent(log, "Gauge", "enterTime")[0][0], active[0][0])
        positions = sent(log, "Gauge", "position_changed")
        self.assertEqual(positions[0][1][1:], (0.0, 0.0))
        self.assertGreater(len(positions), 30)
        self.assertEqual(sent(log, "Gauge", "exitTime")[0][0], active[1][0])
        self.assertEqual(sim.values[("Sink", "visible")], False)

    def test_orientation_is_the_targets_turn_in_the_sensors_coordinates(self):
        text = x3d('<Transform DEF="Frame" rotation="0 1 0 0.5"><TransformSensor DEF="Gauge" size="-1 -1 -1">'
                   '<Transform USE="Ball" containerField="targetObject"/></TransformSensor></Transform>'
                   '<Transform DEF="Ball" rotation="0 1 0 0.75"/><Transform DEF="Sink"/>'
                   '<ROUTE fromNode="Gauge" fromField="orientation_changed" toNode="Sink" toField="rotation"/>')
        # the Ball is declared after the sensor that names it: the target is a name, found when the scene is read
        world = bw.World.from_x3d(text)
        self.assertEqual(world.sensor_target["Gauge"], "Ball")
        sim, log = run(text, 0.1)
        turn = sent(log, "Gauge", "orientation_changed")[0][1]
        self.assertLess(bs._rotation_distance(turn, (0, 1, 0, 0.25)), 1e-9)

    def test_size_zero_or_a_disabled_sensor_is_off_and_size_minus_one_is_always_in(self):
        for fields, expect in ((' size="0 0 0"', []), (' size="2 2 2" enabled="false"', []), (' size="-1 -1 -1"', [True])):
            with self.subTest(fields=fields):
                text = x3d(self.BALL.replace(' size="2 2 2" center="0 0 0"', fields))
                _sim, log = run(text, 0.1)
                self.assertEqual([v for _t, v in sent(log, "Gauge", "isActive")], expect)

    def test_a_sensor_switched_off_while_in_the_box_leaves_at_once(self):
        text = x3d(self.BALL + '<BooleanSequencer DEF="Gate" key="0 0.5 1" keyValue="true false true"/>'
                   '<TimeSensor DEF="Off" cycleInterval="2"/>'
                   '<ROUTE fromNode="Off" fromField="fraction_changed" toNode="Gate" toField="set_fraction"/>'
                   '<ROUTE fromNode="Gate" fromField="value_changed" toNode="Gauge" toField="enabled"/>')
        graph = bg.Behaviour.from_x3d(text)
        sim = bs.Simulation(graph, log_size=10 ** 5, world=bw.World.from_x3d(text))
        sim.start(0.0)
        sim.step(0.001)
        sim.send("Off", "startTime", 0.0, 0.0)
        for frame in range(1, 121):
            sim.step(frame / 60)
        events = [(round(t, 3), v) for t, n, f, v in sim.log if n == "Gauge" and f == "isActive"]
        self.assertEqual(events[:2], [(0.667, True), (1.0, False)])       # in at x = -1; the gate shuts at half of 2 s
        self.assertEqual([v for _t, v in events], [True, False])           # it opens again at 2 s, the ball is by then at 3

    def test_no_world_no_target_no_frame_send_nothing_and_say_so(self):
        text = x3d(self.BALL)
        sim, log = run(text, 0.5, world=False)
        self.assertEqual(sent(log, "Gauge", "isActive"), [])
        self.assertEqual(sim.noted["no-world"], 1)
        orphan = x3d('<Transform><TransformSensor DEF="Gauge" size="2 2 2"/></Transform><Transform DEF="Sink"/>'
                     '<ROUTE fromNode="Gauge" fromField="isActive" toNode="Sink" toField="visible"/>')
        sim, log = run(orphan, 0.2)
        self.assertEqual(sent(log, "Gauge", "isActive"), [])
        self.assertEqual(sim.noted, {"no-target": 1})          # it has a frame, and no targetObject
        self.assertEqual(sim.dropped, {})
        sim = bs.Simulation(bg.Behaviour.from_x3d(text), world=bw.World())              # a world that knows nothing of it
        sim.start(0.0)
        sim.step(0.1)
        self.assertEqual(sim.noted, {"no-frame": 1})

    def test_a_visibility_sensor_sends_a_frame_after_the_picture_that_showed_it(self):
        text = x3d('<Viewpoint DEF="Eye" position="0 0 10"/><Transform translation="0 0 0">'
                   '<VisibilitySensor DEF="Seen" size="2 2 2"/></Transform>'
                   '<Transform DEF="Sink"/><ROUTE fromNode="Seen" fromField="isActive" toNode="Sink" toField="visible"/>'
                   '<TimeSensor DEF="Turn" cycleInterval="1" loop="true"/><OrientationInterpolator DEF="Look" key="0 1" '
                   'keyValue="0 1 0 0  0 1 0 3.1"/><ROUTE fromNode="Turn" fromField="fraction_changed" toNode="Look" '
                   'toField="set_fraction"/><ROUTE fromNode="Look" fromField="value_changed" toNode="Eye" toField="orientation"/>')
        sim, log = run(text, 1.0)
        entered = sent(log, "Seen", "isActive")
        self.assertEqual([v for _t, v in entered], [True, False])
        self.assertEqual(entered[0][0], round(1 / 60, 4))                 # drawn at start, sent at the next step
        # it leaves one frame after the camera stopped seeing it: the box turns out of view at an angle of about 0.47
        sees = [t for t, v in entered if v is False][0]
        angle = 0.0 + sees * 3.1 - 1 / 60 * 3.1
        self.assertGreater(angle, math.atan2(1.414, 10))

    def test_a_disabled_visibility_sensor_enters_on_what_it_last_saw(self):
        text = x3d('<Viewpoint position="0 0 10"/><VisibilitySensor DEF="Seen" size="2 2 2"/>'
                   '<Transform DEF="Sink"/><ROUTE fromNode="Seen" fromField="isActive" toNode="Sink" toField="visible"/>')
        graph = bg.Behaviour.from_x3d(text)
        sim = bs.Simulation(graph, world=bw.World.from_x3d(text))
        sim.start(0.0)
        sim.step(0.1)
        self.assertIs(sim.outputs.get(("Seen", "isActive")), True)
        sim.send("Seen", "enabled", False, 0.15)
        sim.step(0.2)
        self.assertIs(sim.outputs.get(("Seen", "isActive")), False)
        sim.world.set_viewer((0, 0, 10), (0, 1, 0, 3.0))           # the viewer turns its back while the sensor is off
        sim.step(0.25)
        sim.send("Seen", "enabled", True, 0.3)
        sim.step(0.3)
        self.assertIs(sim.outputs.get(("Seen", "isActive")), True)   # on what it last saw, not on what is there now
        sim.step(0.35)
        self.assertIs(sim.outputs.get(("Seen", "isActive")), False)

    def test_collideTime_is_sent_when_the_viewer_arrives_and_not_again_while_it_stays(self):
        text = x3d('<Collision DEF="Wall"><Transform translation="0 0 -2"><Shape><Box size="4 4 0.2"/></Shape></Transform></Collision>'
                   '<Viewpoint DEF="Eye" position="0 0 5"/><TimeSensor DEF="Fly" cycleInterval="3"/>'
                   '<PositionInterpolator DEF="Path" key="0 0.7 1" keyValue="0 0 5  0 0 -1.6  0 0 -1.6"/>'
                   '<ROUTE fromNode="Fly" fromField="fraction_changed" toNode="Path" toField="set_fraction"/>'
                   '<ROUTE fromNode="Path" fromField="value_changed" toNode="Eye" toField="position"/>'
                   '<TimeSensor DEF="Hit" cycleInterval="1"/><Transform DEF="Sink"/>'
                   '<ROUTE fromNode="Wall" fromField="collideTime" toNode="Hit" toField="startTime"/>'
                   '<ROUTE fromNode="Wall" fromField="isActive" toNode="Sink" toField="visible"/>')

        def go(sim):
            sim.send("Fly", "startTime", 0.0, 0.0)

        sim, log = run(text, 3.0, setup=go)
        self.assertEqual(len(sent(log, "Wall", "collideTime")), 1)
        self.assertEqual([v for _t, v in sent(log, "Wall", "isActive")], [True])
        self.assertIn(("Wall", "isActive"), sim.outputs)
        self.assertGreater(sent(log, "Wall", "collideTime")[0][0], 2.0)
        self.assertEqual(sim.values[("Sink", "visible")], True)

    def test_hostile_input_never_raises(self):
        text = x3d(self.BALL)
        sim = bs.Simulation(bg.Behaviour.from_x3d(text), world=bw.World.from_x3d(text))
        sim.start(0.0)
        for value in ((math.nan, 0, 0), (math.inf, 0, 0), (1e300, 1e300, 1e300), (0, 0, 0)):
            sim.post("Path", "value_changed", value, 0.1)            # a Transform moved by what a ROUTE could carry
        sim.world.apply("Slot", "scale", (0.0, 0.0, 0.0))             # a sensor frame with no inverse
        for frame in range(1, 30):
            sim.step(0.1 + frame / 60)
        sim.world.apply("Eye", "position", (math.nan, 0, 0))          # a frame or viewpoint the world does not know
        self.assertEqual(sim.faults, [])
        self.assertEqual(sim.dropped.get("non-finite"), 2)            # the NaN and the infinity never left Path
        self.assertEqual(sim.noted.get("singular-frame"), 1)          # said once, not once a step
        self.assertEqual(sim.world.collision_hits(), set())


class JudgedTests(unittest.TestCase):
    """The simulator against X_ITE 16.8.1 on tests/behaviour/probe-world.x3d: TransformSensor, VisibilitySensor and
    Collision, stream for stream, with the sensors switched off and on, a box resized to nothing and a skewed frame."""

    @classmethod
    def setUpClass(cls):
        cls.trace = json.loads((WORLDS / "x_ite_traces" / "probe-world.json").read_text(encoding="utf-8"))
        cls.result = judge.judge(WORLDS / "probe-world.x3d", cls.trace)

    def test_the_trace_is_a_clean_recording_on_16_8_1(self):
        self.assertEqual(self.trace["browser"], "X_ITE 16.8.1")
        self.assertEqual(self.trace["pageErrors"], [])
        self.assertEqual(self.trace["missing"], [])

    def test_every_stream_agrees_and_none_is_silent(self):
        failed = [s["source"] for s in self.result["streams"] if not s["agree"]]
        self.assertEqual(failed, [])
        self.assertEqual(len(self.result["streams"]), 59)
        self.assertEqual([s["source"] for s in self.result["streams"] if s["x_ite_events"] == 0], [])
        self.assertEqual(self.result["not_simulated"], [])

    def test_each_of_the_three_nodes_sent_something_that_was_compared(self):
        sent_by = {s["node"] for s in self.result["streams"] if s["compared"] > 0}
        self.assertLessEqual({"TransformSensor", "VisibilitySensor", "Collision"}, sent_by)

    def test_the_edge_axis_quirk_matters_to_the_tilted_boxes(self):
        original = bw.frustum_meets_box

        def exact(volume, center, half_axes):
            x, y, z = half_axes
            ok = original(volume, center, half_axes)
            if not ok:
                return False
            r1, r2 = bw._add(y, z), bw._sub(z, y)
            points = bw._box_corners(center, half_axes)
            p = volume
            edges = [bw._sub(p[0], p[1]), bw._sub(p[1], p[2]), bw._sub(p[2], p[3]), bw._sub(p[3], p[0]),
                     bw._sub(p[0], p[4]), bw._sub(p[1], p[5]), bw._sub(p[2], p[6]), bw._sub(p[3], p[7])]
            return not bw._separated([bw._cross(a, e) for a in (x, y, z) for e in edges], points, list(p))

        bw.frustum_meets_box = exact
        try:
            result = judge.judge(WORLDS / "probe-world.x3d", self.trace)
        finally:
            bw.frustum_meets_box = original
        failed = {s["source"].split(".")[0] for s in result["streams"] if not s["agree"]}
        self.assertTrue({"Tilt1", "Tilt2", "Tilt3"} <= failed, failed)


class CatalogueTests(unittest.TestCase):

    def test_what_is_simulated_from_a_world_is_named(self):
        self.assertIn("TransformSensor", bs.SIMULATED)
        self.assertIn("VisibilitySensor", bs.SIMULATED)
        self.assertEqual(bs.SIMULATED_IN_PLACE, ("Collision",))
        self.assertNotIn("Collision", bs.SIMULATED)             # scene content: not a machine, see test_behaviour_wired

    def test_the_old_api_is_unchanged(self):
        for name in ("start", "step", "press", "drag", "release", "click", "hover", "send", "post", "viewer"):
            self.assertTrue(callable(getattr(bs.Simulation, name)))
        for name in ("values", "outputs", "log", "not_simulated"):
            self.assertTrue(hasattr(bs.Simulation(bg.Behaviour()), name))


if __name__ == "__main__":
    unittest.main()
