# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""The workbench demo's folder agrees with what build.py writes, and the simulator code it added (a PlaneSensor run
from the pointer's ray, X_ITE's buffered ColorChaser and OrientationChaser) does what X_ITE does where it is easy to
say in a few numbers. The judge against X_ITE's own trace is DemoJudgeTests in test_behaviour_sim.py."""

import importlib.util
import json
import math
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source"))
import behaviour_graph as bg          # noqa: E402
import behaviour_sim as bs            # noqa: E402

DEMO = ROOT / "tests" / "behaviour" / "demos" / "workbench"
FOCAL = 600 / (2 * math.tan(math.pi / 8))                  # a 960 x 600 window, 45 degrees across the height
CAMERA = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))                 # right and up, the camera's axes in the sensor's coordinates


def build_module():
    spec = importlib.util.spec_from_file_location("workbench_build", DEMO / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ray_through(pixel_x, pixel_y, eye=(0.0, 0.0, 10.0)):
    """The ray from ``eye`` (looking down -z) through a pixel offset from the middle of the window, y up."""
    return eye, bs._v_unit((pixel_x / FOCAL, pixel_y / FOCAL, -1.0))


class FolderTests(unittest.TestCase):
    def test_the_world_and_the_drag_plan_are_what_build_py_writes(self):
        build = build_module()
        self.assertEqual((DEMO / "workbench.x3d").read_text(encoding="utf-8"), build.behaviour().weave(build.SCENE))
        self.assertEqual(json.loads((DEMO / "drags.json").read_text(encoding="utf-8")),
                         json.loads(json.dumps(build.drag_plan())))

    def test_the_contract_names_what_the_world_judges(self):
        contract = json.loads((DEMO / "demo.json").read_text(encoding="utf-8"))
        graph = bg.Behaviour.from_x3d((DEMO / "workbench.x3d").read_text(encoding="utf-8"))
        senders = {graph.nodes[r.from_id].node_type for r in graph.routes}
        self.assertEqual(contract["judges"], ["PlaneSensor", "ColorChaser"])
        self.assertLessEqual(set(contract["judges"]), senders)


class PlaneSensorTests(unittest.TestCase):
    def sensor(self, **fields):
        graph = bg.Behaviour()
        graph.add("PlaneSensor", "Slide", **fields)
        sim = bs.Simulation(graph)
        sim.start(0.0)
        return sim

    def test_a_sensor_limited_to_one_axis_follows_the_pointers_screen_position_along_its_line(self):
        sim = self.sensor(minPosition=(-1, 0), maxPosition=(1, 0))
        sim.press("Slide", 1.0, (0.0, 0.0, 0.0), ray=ray_through(0, 0), screen=CAMERA)
        sim.drag("Slide", None, 1.1, ray=ray_through(40, 25))              # 40 px right, and up: up is ignored
        self.assertAlmostEqual(sim.outputs[("Slide", "translation_changed")][0], 40 / FOCAL * 10, places=6)
        self.assertEqual(sim.outputs[("Slide", "translation_changed")][1:], (0.0, 0.0))

    def test_the_line_is_followed_by_screen_position_not_by_where_the_ray_meets_a_plane(self):
        # a rail turned 1 rad about y runs away from the camera; its picture is a horizontal line, so the point the
        # pointer's picture is nearest has the same screen x as the pointer: F s cos 1 / (10 + s sin 1) = 60 px.
        # (Where the pointer's ray meets the plane through the press point would be 60 / F * 10 = 0.83 m instead.)
        sim = self.sensor(minPosition=(-9, 0), maxPosition=(9, 0), axisRotation=(0, 1, 0, 1.0))
        sim.press("Slide", 1.0, (0.0, 0.0, 0.0), ray=ray_through(0, 0), screen=CAMERA)
        sim.drag("Slide", None, 1.1, ray=ray_through(60, 0))
        want = 600 / (FOCAL * math.cos(1.0) - 60 * math.sin(1.0))
        self.assertAlmostEqual(sim.outputs[("Slide", "translation_changed")][0], want, places=6)
        self.assertGreater(abs(want - 60 / FOCAL * 10), 0.3)

    def test_a_sensor_stops_at_its_limits_and_the_next_drag_starts_where_this_one_ended(self):
        sim = self.sensor(minPosition=(-1, 0), maxPosition=(1, 0))
        sim.press("Slide", 1.0, (0.0, 0.0, 0.0), ray=ray_through(0, 0), screen=CAMERA)
        sim.drag("Slide", None, 1.1, ray=ray_through(400, 0))                # 5.5 m: far past the limit
        self.assertEqual(sim.outputs[("Slide", "translation_changed")], (1.0, 0.0, 0.0))
        sim.drag("Slide", None, 1.2, ray=ray_through(-400, 0))
        self.assertEqual(sim.outputs[("Slide", "translation_changed")], (-1.0, 0.0, 0.0))
        sim.drag("Slide", None, 1.3, ray=ray_through(30, 0))
        sim.release("Slide", 1.4)                                            # autoOffset: the offset becomes where it ended
        stopped = sim.outputs[("Slide", "translation_changed")][0]
        self.assertAlmostEqual(stopped, 30 / FOCAL * 10, places=6)
        sim.press("Slide", 2.0, (stopped, 0.0, 0.0), ray=ray_through(30, 0), screen=CAMERA)
        sim.drag("Slide", None, 2.1, ray=ray_through(40, 0))
        self.assertAlmostEqual(sim.outputs[("Slide", "translation_changed")][0], stopped + 10 / FOCAL * 10, places=6)

    def test_a_sensor_with_both_axes_free_meets_the_ray_with_the_plane_square_to_its_z(self):
        sim = self.sensor()
        sim.press("Slide", 1.0, (0.0, 0.0, 0.0), ray=ray_through(0, 0), screen=CAMERA)
        sim.drag("Slide", None, 1.1, ray=ray_through(FOCAL / 10, -FOCAL / 5))
        for got, want in zip(sim.outputs[("Slide", "translation_changed")], (1.0, -2.0, 0.0)):
            self.assertAlmostEqual(got, want, places=6)

    def test_only_what_changed_is_sent_after_the_first_motion(self):
        sim = self.sensor(minPosition=(-1, 0), maxPosition=(1, 0))
        sim.press("Slide", 1.0, (0.0, 0.0, 0.0), ray=ray_through(0, 0), screen=CAMERA)
        sim.drag("Slide", None, 1.1, ray=ray_through(400, 0))
        before = len(sim.log)
        sim.drag("Slide", None, 1.2, ray=ray_through(500, 0))                # still past the limit: the track point moves
        sent = [(n, f) for _t, n, f, _v in list(sim.log)[before:]]
        self.assertEqual(sent, [("Slide", "trackPoint_changed")])            # translation_changed stays at the limit


class ChaserTests(unittest.TestCase):
    def follow(self, node_type, start, destination, duration=0.6, until=1.0):
        graph = bg.Behaviour()
        graph.add(node_type, "Chase", duration=duration, initialValue=start, initialDestination=start)
        sim = bs.Simulation(graph)
        sim.start(0.0)
        sim.send("Chase", "set_destination", destination, 0.0)
        seen, t = [], 0.0
        while t < until:
            t += 1 / 60
            sim.step(t)
            seen.append((t, sim.outputs.get(("Chase", "value_changed")), sim.outputs.get(("Chase", "isActive"))))
        return seen

    def test_a_colour_chaser_goes_through_hsv_not_straight_through_rgb(self):
        seen = self.follow("ColorChaser", (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
        middle = min(seen, key=lambda row: abs(row[0] - 0.3))[1]
        self.assertGreater(middle[0] + middle[1], 1.3)                 # red to green by hue passes through yellow (1, 1, 0)
        self.assertGreater(min(middle[:2]), 0.4)                        # an RGB blend would be a dull (0.5, 0.5, 0)

    def test_a_colour_chaser_settles_on_its_destination_and_says_so(self):
        seen = self.follow("ColorChaser", (1.0, 0.62, 0.12), (0.1, 0.75, 0.7), until=2.0)
        t, value, active = seen[-1]
        for got, want in zip(value, (0.1, 0.75, 0.7)):
            self.assertAlmostEqual(got, want, places=5)
        self.assertIs(active, False)

    def test_an_orientation_chaser_that_is_given_a_new_destination_every_frame_keeps_up_with_a_steady_turn(self):
        graph = bg.Behaviour()
        graph.add("OrientationChaser", "Chase", duration=0.5)
        sim = bs.Simulation(graph)
        sim.start(0.0)
        gaps = []
        for frame in range(1, 121):
            t = frame / 60
            sim.send("Chase", "set_destination", (0.0, 0.0, 1.0, t * 1.5), t)      # 1.5 rad a second
            sim.step(t)
            got = sim.outputs[("Chase", "value_changed")]
            gaps.append(bs._rotation_distance(got, (0.0, 0.0, 1.0, t * 1.5)))
        # a steady turn is followed at a constant lag of half the duration: 1.5 rad/s x 0.25 s
        self.assertAlmostEqual(gaps[-1], 1.5 * 0.25, delta=0.05)
        self.assertLess(max(gaps[60:]) - min(gaps[60:]), 0.03)


if __name__ == "__main__":
    unittest.main()
