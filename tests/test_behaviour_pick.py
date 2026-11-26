# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The four pick sensors (source/behaviour_pick.py) against X_ITE 16.8.1's own recordings of
tests/behaviour/probe-pick.x3d (BOUNDS) and probe-pick-geometry.x3d (GEOMETRY), stream for stream, plus the geometry
helpers and hostile input. No Blender.

    python -m unittest tests.test_behaviour_pick
"""

from __future__ import annotations

import json
import math
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source"))
sys.path.insert(0, str(ROOT / "tools"))

import behaviour_graph as bg            # noqa: E402
import behaviour_pick as bp             # noqa: E402
import behaviour_pick_judge as pj       # noqa: E402
import behaviour_sim as bs              # noqa: E402
import behaviour_world as bw            # noqa: E402

WORLDS = ROOT / "tests" / "behaviour"
IDENTITY = bw.m_transform((0, 0, 0), (0, 0, 1, 0), (1, 1, 1), (0, 0, 0), (0, 0, 1, 0))


def run(text, seconds, fps=60.0):
    graph = bg.Behaviour.from_x3d(text)
    sim = bs.Simulation(graph, log_size=10 ** 6, world=bw.World.from_x3d(text))
    sim.start(0.0)
    for frame in range(1, int(seconds * fps) + 1):
        sim.step(frame / fps)
    return sim, list(sim.log)


def scene(body):
    return f'<X3D profile="Full" version="4.0"><head/><Scene>{body}</Scene></X3D>'


def pair(kind="BOUNDS", picker_at="0 0 0", sensor="VolumePickSensor", extra=""):
    """A box sensor picker at ``picker_at`` beside a unit box target at the origin."""
    return scene(f'''
      <Group DEF="T"><Shape><Box DEF="Target" size="2 2 2"/></Shape></Group>
      <Transform translation="{picker_at}"><Shape><Box size="0.1 0.1 0.1"/></Shape>
        <{sensor} DEF="P" intersectionType="{kind}" {extra}><Box containerField="pickingGeometry" size="1 1 1"/>
          <Group USE="T" containerField="pickTarget"/></{sensor}></Transform>''')


class HelperTests(unittest.TestCase):

    def box(self, center, half, turn=0.0):
        m = bw.m_transform((0, 0, 0), (0, 0, 1, turn), (1, 1, 1), (0, 0, 0), (0, 0, 1, 0))
        return bp.obb_of(center, half, m)

    def test_touching_boxes_meet_and_separated_ones_do_not(self):
        a = self.box((0, 0, 0), (1, 1, 1))
        self.assertTrue(bp.boxes_meet(a, self.box((2, 0, 0), (1, 1, 1))))
        self.assertFalse(bp.boxes_meet(a, self.box((2.01, 0, 0), (1, 1, 1))))

    def test_a_turned_box_meets_across_a_corner(self):
        a = self.box((0, 0, 0), (1, 1, 1))
        b = self.box((2.3, 0, 0), (1, 1, 1), turn=math.pi / 4)
        self.assertTrue(bp.boxes_meet(a, b))
        self.assertFalse(bp.boxes_meet(a, self.box((2.5, 0, 0), (1, 1, 1), turn=math.pi / 4)))

    def test_distance_between_boxes(self):
        a = self.box((0, 0, 0), (1, 1, 1))
        self.assertAlmostEqual(bp.distance_box_box(a, self.box((5, 0, 0), (1, 1, 1))), 3.0, places=9)
        self.assertAlmostEqual(bp.distance_box_box(a, self.box((4, 4, 0), (1, 1, 1))), math.sqrt(8), places=9)
        self.assertEqual(bp.distance_box_box(a, self.box((1.5, 0, 0), (1, 1, 1))), 0.0)

    def test_distance_from_a_point_to_a_box(self):
        a = self.box((0, 0, 0), (1, 1, 1))
        self.assertEqual(bp.distance_point_box((0.5, 0.5, 0.5), a), 0.0)
        self.assertAlmostEqual(bp.distance_point_box((3, 0, 0), a), 2.0, places=12)
        self.assertAlmostEqual(bp.distance_point_box((2, 2, 0), a), math.sqrt(2), places=12)

    def test_the_quick_box_test_agrees_with_the_exact_one_or_declines(self):
        rng = random.Random(5)

        def random_box():
            matrix = bw.m_transform((rng.uniform(-3, 3), rng.uniform(-3, 3), rng.uniform(-3, 3)),
                                    (rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-4, 4)),
                                    tuple(rng.choice([1, 1, 2, 0.5]) for _ in range(3)), (0, 0, 0), (0, 0, 1, 0))
            return bp.obb_of((0, 0, 0), tuple(rng.choice([0.5, 1, 2]) for _ in range(3)), matrix)

        def exact(a, b):
            pa, pb = bp._corners(a), bp._corners(b)
            return not (bp._apart(bw._box_normals(*a.axes), pa, pb) or bp._apart(bw._box_normals(*b.axes), pa, pb)
                        or bp._apart([bw._cross(p, q) for p in a.axes for q in b.axes], pa, pb))

        answered = 0
        for _ in range(3000):
            a, b = random_box(), random_box()
            quick = bp.boxes_meet_quick(a, b)
            if quick is not None:
                answered += 1
                self.assertEqual(quick, exact(a, b))
        self.assertGreater(answered, 2900)

    def test_a_flat_box_is_left_to_the_exact_test(self):
        flat = bp.obb_of((0, 0, 0), (1, 1, 0), IDENTITY)
        self.assertIsNone(bp.boxes_meet_quick(flat, self.box((0.5, 0, 0), (1, 1, 1))))
        self.assertTrue(bp.boxes_meet(flat, self.box((0.5, 0, 0), (1, 1, 1))))

    def test_quicksort_sorts(self):
        rng = random.Random(4)
        items = [rng.random() for _ in range(200)]
        self.assertEqual(bp.quicksort(items, lambda a, b: a < b), sorted(items))
        self.assertEqual(bp.quicksort([], lambda a, b: a < b), [])

    def test_rigid_refuses_shear_and_mirror(self):
        self.assertTrue(bp.rigid(IDENTITY))
        self.assertTrue(bp.rigid(bw.m_transform((1, 2, 3), (0, 1, 0, 0.7), (1, 1, 1), (0, 0, 0), (0, 0, 1, 0))))
        self.assertFalse(bp.rigid(bw.m_transform((0, 0, 0), (0, 1, 0, 0), (-1, 1, 1), (0, 0, 0), (0, 0, 1, 0))))


class BehaviourTests(unittest.TestCase):

    def active(self, log):
        return [(round(t, 3), v) for t, n, f, v in log if n == "P" and f == "isActive"]

    def test_bounds_touching_is_active_and_names_the_geometry(self):
        _sim, log = run(pair("BOUNDS", "1.5 0 0"), 0.2)
        self.assertEqual([v for _t, v in self.active(log)], [True])
        picked = [v for _t, n, f, v in log if n == "P" and f == "pickedGeometry"]
        self.assertEqual([list(v) for v in picked], [["Target"]])

    def test_bounds_apart_is_silent(self):
        _sim, log = run(pair("BOUNDS", "3 0 0"), 0.2)
        self.assertEqual(self.active(log), [])

    def test_geometry_sphere_picker_against_box_uses_the_rounded_corner(self):
        text = scene('''
          <Group DEF="T"><Shape><Box DEF="Target" size="2 2 2"/></Shape></Group>
          <Transform translation="1.6 1.6 0"><Shape><Box size="0.1 0.1 0.1"/></Shape>
            <PrimitivePickSensor DEF="P" intersectionType="GEOMETRY"><Sphere containerField="pickingGeometry" radius="0.5"/>
              <Group USE="T" containerField="pickTarget"/></PrimitivePickSensor></Transform>''')
        _sim, log = run(text, 0.2)
        # BOUNDS would meet (the sphere's box reaches the corner), the sphere itself, 0.85 from the corner centre line, does not
        self.assertEqual(self.active(log), [])

    def test_geometry_that_is_not_simulated_falls_back_and_says_so(self):
        text = scene('''
          <Group DEF="T"><Shape><Cone DEF="Target"/></Shape></Group>
          <Transform><Shape><Box size="0.1 0.1 0.1"/></Shape>
            <PrimitivePickSensor DEF="P" intersectionType="GEOMETRY"><Sphere containerField="pickingGeometry" radius="0.5"/>
              <Group USE="T" containerField="pickTarget"/></PrimitivePickSensor></Transform>''')
        sim, log = run(text, 0.2)
        self.assertEqual(sim.noted.get("bounds-for-geometry"), 1)
        self.assertEqual([v for _t, v in self.active(log)], [True])

    def test_a_sensor_that_is_alone_in_its_group_is_never_picked(self):
        text = scene('''
          <Group DEF="T"><Shape><Box DEF="Target" size="2 2 2"/></Shape></Group>
          <Group><VolumePickSensor DEF="P" intersectionType="BOUNDS"><Box containerField="pickingGeometry" size="1 1 1"/>
            <Group USE="T" containerField="pickTarget"/></VolumePickSensor></Group>''')
        sim, log = run(text, 0.2)
        self.assertEqual(self.active(log), [])
        self.assertEqual(sim.noted.get("pick-lone-sensor"), 1)

    def test_a_hidden_pickable_group_hides_the_target(self):
        text = scene('''
          <PickableGroup DEF="T" pickable="false"><Shape><Box DEF="Target" size="2 2 2"/></Shape></PickableGroup>
          <Transform><Shape><Box size="0.1 0.1 0.1"/></Shape>
            <VolumePickSensor DEF="P" intersectionType="BOUNDS"><Box containerField="pickingGeometry" size="1 1 1"/>
              <PickableGroup USE="T" containerField="pickTarget"/></VolumePickSensor></Transform>''')
        _sim, log = run(text, 0.2)
        self.assertEqual(self.active(log), [])


class MemoTests(unittest.TestCase):

    def test_a_sensor_whose_frames_did_not_move_is_not_asked_again(self):
        text = pair("BOUNDS", "1.5 0 0")
        sim, _log = run(text, 0.1)
        machine = sim.machines["P"]
        calls = []
        original = machine.hits
        machine.hits = lambda *a, **k: calls.append(1) or original(*a, **k)
        for frame in range(10, 20):
            sim.step(frame / 60.0)
        self.assertEqual(calls, [])

    def test_a_moved_target_is_noticed(self):
        text = scene('''
          <Transform DEF="Mover" translation="5 0 0"><Shape><Box DEF="Target" size="2 2 2"/></Shape></Transform>
          <Group><Shape><Box size="0.1 0.1 0.1"/></Shape>
            <VolumePickSensor DEF="P" intersectionType="BOUNDS"><Box containerField="pickingGeometry" size="1 1 1"/>
              <Transform USE="Mover" containerField="pickTarget"/></VolumePickSensor></Group>''')
        graph = bg.Behaviour.from_x3d(text)
        world = bw.World.from_x3d(text)
        sim = bs.Simulation(graph, log_size=1000, world=world)
        sim.start(0.0)
        sim.step(1 / 60)
        self.assertEqual([r for r in sim.log if r[1] == "P" and r[2] == "isActive"], [])
        world.apply("Mover", "translation", (0.5, 0.0, 0.0))
        sim.step(2 / 60)
        self.assertEqual([r[3] for r in sim.log if r[1] == "P" and r[2] == "isActive"], [True])


class HostileTests(unittest.TestCase):

    def test_hostile_values_never_raise(self):
        junk = ["", "nan nan nan", "1e999 0 0", "-1 -1 -1", "x y z", "0 0 0 0", "inf", "1" * 400, "[]", "NONE", "ALL ALL"]
        for i, bad in enumerate(junk):
            for sensor in bp.SENSORS:
                for kind in ("BOUNDS", "GEOMETRY", bad):
                    text = scene(f'''
                      <Group DEF="T"><Shape><Box DEF="Target" size="{bad}"/></Shape>
                        <Shape><IndexedFaceSet coordIndex="{bad}"><Coordinate point="{bad}"/></IndexedFaceSet></Shape></Group>
                      <Transform translation="{bad}" scale="{bad}"><Shape><Box size="0.1 0.1 0.1"/></Shape>
                        <{sensor} DEF="P" intersectionType="{kind}" sortOrder="{bad}" objectType="{bad}" enabled="{bad}"
                          matchCriterion="{bad}"><Box containerField="pickingGeometry" size="{bad}"/>
                          <Group USE="T" containerField="pickTarget"/></{sensor}></Transform>''')
                    run(text, 0.1)

    def test_a_world_without_a_pick_scene_blinds_the_sensor(self):
        text = pair("BOUNDS", "1 0 0")
        graph = bg.Behaviour.from_x3d(text)
        world = bw.World.from_x3d(text)
        world.pick = None
        sim = bs.Simulation(graph, log_size=1000, world=world)
        sim.start(0.0)
        for frame in range(1, 10):
            sim.step(frame / 60.0)
        self.assertEqual([r for r in sim.log if r[1] == "P"], [])


class JudgeTests(unittest.TestCase):
    """The simulator against X_ITE 16.8.1, every stream: same events, same order, same values, within a frame (the judge's rule)."""

    def judged(self, name):
        trace = json.loads((WORLDS / "x_ite_traces" / f"{name}.json").read_text(encoding="utf-8"))
        return pj.judge(WORLDS / f"{name}.x3d", trace)

    def check(self, name):
        result = self.judged(name)
        self.assertTrue(result["streams"])
        for s in result["streams"]:
            self.assertTrue(s["agree"], f"{name}: {s['source']} {s['x_ite_events']} vs {s['simulator_events']}")
        self.assertTrue(result["agree"])
        self.assertEqual(result["not_simulated"], [])

    def test_bounds_probe_agrees_stream_for_stream(self):
        self.check("probe-pick")

    def test_geometry_probe_agrees_stream_for_stream(self):
        result = self.judged("probe-pick-geometry")
        sources = {s["source"] for s in result["streams"]}
        for needed in ("P0.isActive", "P1.pickedGeometry", "P3.pickedPoint", "P4.pickedNormal", "P5.pickedTextureCoordinate",
                       "P8.pickedPoint"):
            self.assertIn(needed, sources)
        self.check("probe-pick-geometry")

    def test_the_fallback_probe_is_not_judged(self):
        """Cone, cylinder, IndexedFaceSet and ellipsoid targets, and a line against a non-box, are BOUNDS in the simulator and
        X_ITE's contact is not: the recording disagrees, and the simulator says it fell back."""
        folder = WORLDS / "pick-fallback"
        trace = json.loads((folder / "x_ite.json").read_text(encoding="utf-8"))
        result = pj.judge(folder / "probe-pick-fallback.x3d", trace)
        self.assertFalse(result["agree"])
        graph = bg.Behaviour.from_x3d((folder / "probe-pick-fallback.x3d").read_text(encoding="utf-8"))
        text = (folder / "probe-pick-fallback.x3d").read_text(encoding="utf-8")
        sim = bs.Simulation(graph, log_size=1000, world=bw.World.from_x3d(text))
        sim.start(0.0)
        for frame in range(1, 241):
            sim.step(frame / 60.0)
        self.assertGreaterEqual(sim.noted.get("bounds-for-geometry", 0), 1)


if __name__ == "__main__":
    unittest.main()
