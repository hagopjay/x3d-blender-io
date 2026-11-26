# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The half-turn warning: two consecutive rotation keys that are pi apart have no shortest way round.

``behaviour_graph.warnings`` names the node and the key indices. The cases are the spellings of a half turn that must
warn and the keys that must not; the demo tests read the two gallery worlds that wrote a full turn with three keys.
::

    python -m unittest tests.test_behaviour_halfturn
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source"))

sys.path.insert(0, str(ROOT / "tools"))

import json                                      # noqa: E402
import math                                      # noqa: E402

import behaviour_graph as bg                     # noqa: E402
import behaviour_sim as bs                       # noqa: E402
import behaviour_sim_judge as judge              # noqa: E402

DEMOS = ROOT / "tests" / "behaviour" / "demos"


def keyed(*rotations, kind="OrientationInterpolator"):
    b = bg.Behaviour()
    n = len(rotations)
    b.add(kind, "Turn", key=[i / (n - 1) for i in range(n)], keyValue=list(rotations))
    return b


class HalfTurnTests(unittest.TestCase):
    WARN = {
        "0 then 3.1416": [(0, 0, 1, 0), (0, 0, 1, 3.1416)],
        "0 then 3.14159265": [(0, 0, 1, 0), (0, 0, 1, 3.14159265)],
        "0 then -3.1416": [(0, 0, 1, 0), (0, 0, 1, -3.1416)],
        "3.1416 then 6.2832": [(0, 0, 1, 3.1416), (0, 0, 1, 6.2832)],
        "axis flipped, same angle sign": [(0, 0, 1, 1.5708), (0, 0, -1, 1.5708)],
        "0 then 3.1415, inside the band": [(0, 0, 1, 0), (0, 0, 1, 3.1415)],
        "9.4248 against 6.2832": [(0, 0, 1, 6.2832), (0, 0, 1, 9.4248)],
        "non-normalised axis": [(0, 0, 1, 0), (0, 0, 2, 3.1416)],
    }
    QUIET = {
        "0 then 3.0": [(0, 0, 1, 0), (0, 0, 1, 3.0)],
        "four keys": [(0, 0, 1, 0), (0, 0, 1, 2.0944), (0, 0, 1, 4.1888), (0, 0, 1, 6.2832)],
        "identical keys": [(0, 0, 1, 1.0), (0, 0, 1, 1.0)],
    }

    def test_every_spelling_warns_naming_node_and_keys(self):
        for label, keys in self.WARN.items():
            for kind in ("OrientationInterpolator", "SquadOrientationInterpolator"):
                with self.subTest(case=label, node=kind):
                    found = keyed(*keys, kind=kind).warnings()
                    self.assertEqual([w["code"] for w in found], ["half-turn"])
                    self.assertEqual(found[0]["where"], "Turn")
                    self.assertIn("keys 0 and 1", found[0]["message"])
                    self.assertIn("four keys", found[0]["message"])

    def test_quiet_keys_do_not_warn(self):
        for label, keys in self.QUIET.items():
            with self.subTest(case=label):
                self.assertEqual(keyed(*keys).warnings(), [])

    def test_a_full_turn_in_three_steps_warns_twice(self):
        found = keyed((0, 0, 1, 0), (0, 0, 1, 3.1416), (0, 0, 1, 6.2832)).warnings()
        self.assertEqual([w["message"].split("keys ")[1].split(" are")[0] for w in found], ["0 and 1", "1 and 2"])

    def test_it_never_blocks_a_write_and_is_not_an_error(self):
        b = keyed((0, 0, 1, 0), (0, 0, 1, 3.1416))
        self.assertEqual(b.check(), [])
        self.assertEqual(b.diagnostics, [])

    def test_a_key_without_a_direction_or_bad_text_is_left_alone(self):
        self.assertEqual(keyed((0, 0, 0, 0), (0, 0, 0, 3.1416)).warnings(), [])
        b = bg.Behaviour()
        b.add("OrientationInterpolator", "Turn", key=[0, 1], keyValue=[(0, 0, 1, 0), (0, 0, 1, 1)])
        b.nodes["Turn"].fields["keyValue"] = "0 0 1 zero 0 0 1 3"
        self.assertEqual(b.warnings(), [])

    def test_the_two_gallery_demos_that_wrote_a_full_turn_in_three_steps(self):
        for name, prefix, count in (("gallery-05-spin-the-planet", "Tum", 5), ("gallery-06-solar-gauntlet", "Arc", 6)):
            graph = bg.Behaviour.from_x3d((DEMOS / name / f"{name}.x3d").read_text(encoding="utf-8"))
            self.assertEqual(sorted({w["where"] for w in graph.warnings()}), [f"{prefix}{i}" for i in range(count)])

    def test_the_corrected_copies_are_quiet(self):
        for name in ("gallery-05-spin-the-planet-v2", "gallery-06-solar-gauntlet-v2"):
            graph = bg.Behaviour.from_x3d((DEMOS / name / f"{name}.x3d").read_text(encoding="utf-8"))
            self.assertEqual(graph.warnings(), [])


def _quaternion(x, y, z, angle):
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    s = math.sin(angle / 2) / n
    return (x * s, y * s, z * s, math.cos(angle / 2))


def turn_steps(values):
    """The signed turn about +z (radians) from each rotation to the next, the short way round: the demos turn about z."""
    steps = []
    for a, b in zip(values, values[1:]):
        (ax, ay, az, aw), (bx, by, bz, bw) = _quaternion(*a), _quaternion(*b)
        # relative = b * conjugate(a)
        rz = bw * -az + bz * aw + bx * -ay - by * -ax
        rw = bw * aw + bx * ax + by * ay + bz * az
        if rw < 0:
            rw, rz = -rw, -rz
        steps.append(2 * math.atan2(rz, rw) if abs(rz) > 1e-12 else 0.0)
    return steps


def x_ite_rotations(trace, name):
    return [tuple(float(c) for c in e[3].split()) for e in trace["events"] if e[1] == name and e[2] == "value_changed"]


def simulated_rotations(x3d, name, seconds):
    sim = bs.Simulation(bg.Behaviour.from_x3d(x3d.read_text(encoding="utf-8")), log_size=10 ** 7)
    sim.start(0.0)
    t = 0.0
    while t < seconds:
        t += 1 / 60
        sim.step(t)
    return [v for _w, n, f, v in sim.log if n == name and f == "value_changed" and isinstance(v, tuple) and len(v) == 4]


class DirectionTests(unittest.TestCase):
    """Which way each turn goes. The originals are measured on the simulator (their X_ITE 16.8.1 recordings, made once in
    scratch space for the report, are not kept: a demo folder is never overwritten); the corrected copies carry their
    own recordings."""

    def test_original_05_turns_every_moon_backwards_two_pi_per_cycle(self):
        x3d = DEMOS / "gallery-05-spin-the-planet" / "gallery-05-spin-the-planet.x3d"
        for i, cycle in enumerate((2, 3, 4, 5, 6)):
            steps = turn_steps(simulated_rotations(x3d, f"Tum{i}", cycle))
            with self.subTest(interpolator=f"Tum{i}"):
                self.assertEqual([s for s in steps if s > 1e-9], [])
                self.assertAlmostEqual(sum(steps), -2 * math.pi, delta=0.1)

    def test_original_06_arcs_go_forward_half_a_cycle_and_back_the_other_half(self):
        x3d = DEMOS / "gallery-06-solar-gauntlet" / "gallery-06-solar-gauntlet.x3d"
        for i, cycle in enumerate((7.0, 8.3, 9.6, 10.9, 12.2, 13.5)):
            steps = turn_steps(simulated_rotations(x3d, f"Arc{i}", cycle))
            with self.subTest(interpolator=f"Arc{i}"):
                self.assertGreater(sum(1 for s in steps if s > 1e-9), 100)
                self.assertGreater(sum(1 for s in steps if s < -1e-9), 100)
                self.assertAlmostEqual(sum(steps), 0.0, delta=0.1)

    def test_corrected_copies_turn_forward_a_full_turn_per_cycle_in_the_simulator(self):
        for name, prefix, cycles in (("gallery-05-spin-the-planet-v2", "Tum", (2, 3, 4, 5, 6)),
                                     ("gallery-06-solar-gauntlet-v2", "Arc", (7.0, 8.3, 9.6, 10.9, 12.2, 13.5))):
            for i, cycle in enumerate(cycles):
                steps = turn_steps(simulated_rotations(DEMOS / name / f"{name}.x3d", f"{prefix}{i}", cycle))
                with self.subTest(demo=name, interpolator=f"{prefix}{i}"):
                    self.assertEqual([s for s in steps if s < -1e-9], [])
                    self.assertAlmostEqual(sum(steps), 2 * math.pi, delta=0.1)

    def test_corrected_copies_turn_forward_in_x_ite(self):
        for name, prefix, count, file in (("gallery-05-spin-the-planet-v2", "Tum", 5, "x_ite_turns.json"),
                                          ("gallery-06-solar-gauntlet-v2", "Arc", 6, "x_ite.json")):
            trace = json.loads((DEMOS / name / file).read_text(encoding="utf-8"))
            self.assertEqual(trace["pageErrors"], [])
            for i in range(count):
                steps = turn_steps(x_ite_rotations(trace, f"{prefix}{i}"))
                with self.subTest(demo=name, interpolator=f"{prefix}{i}"):
                    self.assertGreater(len(steps), 50)
                    self.assertEqual([s for s in steps if s < -1e-9], [])
                    self.assertGreater(sum(steps), 2 * math.pi)

    def test_simulator_and_x_ite_agree_on_every_turn_of_the_corrected_copies(self):
        for name, prefix, file in (("gallery-05-spin-the-planet-v2", "Tum", "x_ite_turns.json"),
                                   ("gallery-06-solar-gauntlet-v2", "Arc", "x_ite.json")):
            trace = json.loads((DEMOS / name / file).read_text(encoding="utf-8"))
            result = judge.judge(DEMOS / name / f"{name}.x3d", trace)
            turns = [s for s in result["streams"] if s["source"].startswith(prefix)]
            self.assertGreaterEqual(len(turns), 5)
            self.assertEqual([s["source"] for s in turns if not s["agree"]], [], name)

    def test_gallery_05_v2_differs_from_x_ite_only_where_a_looping_clock_wraps(self):
        """X_ITE sends fraction 1 and then the new fraction in one time stamp when a looping TimeSensor wraps inside a frame;
        the simulator sends the new fraction only. A BooleanSequencer behind such a clock sees one event less. A known
        difference, outside this package: only the star timers show it."""
        name = "gallery-05-spin-the-planet-v2"
        trace = json.loads((DEMOS / name / "x_ite_turns.json").read_text(encoding="utf-8"))
        result = judge.judge(DEMOS / name / f"{name}.x3d", trace)
        differing = [s["source"] for s in result["streams"] if not s["agree"]]
        self.assertTrue(differing)
        self.assertEqual([d for d in differing if not d.startswith(("Blink", "Twinkle"))], [])


if __name__ == "__main__":
    unittest.main()
