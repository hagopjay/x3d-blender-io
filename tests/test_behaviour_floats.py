# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Floats in the behaviour graph's own text: the shortest text that reads back exactly (plain Python)::

    cd tests && python -m unittest test_behaviour_floats
"""

from __future__ import annotations

import math
import random
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source"))

import behaviour_graph as bg   # noqa: E402
import behaviour_sim as bs     # noqa: E402

JUST_UNDER_PI = 3.14159265
DOC = "<X3D profile=\"Immersive\" version=\"4.0\"><Scene></Scene></X3D>"


def samples(graph, name="Spin", steps=(0.1, 0.25, 0.5, 0.75, 0.9)):
    sim = bs.Simulation(graph, log_size=10_000)
    sim.start(0.0)
    out = []
    for fraction in steps:
        sim.send(name, "set_fraction", fraction, 0.0)
        out.append(sim.outputs[(name, "value_changed")])
    return out


class TurntableAgreesAfterTheTrip(unittest.TestCase):

    def graph(self):
        b = bg.Behaviour()
        b.add("OrientationInterpolator", "Spin", key=[0, 1], keyValue=[(0, 1, 0, 0), (0, 1, 0, JUST_UNDER_PI)])
        return b

    def test_the_field_text_is_exact(self):
        b = self.graph()
        self.assertEqual(b.nodes["Spin"].fields["keyValue"], "0 1 0 0 0 1 0 3.14159265")

    def test_samples_agree_before_and_after_weave_and_read_back(self):
        b = self.graph()
        reference = bg.Graph()
        reference.nodes["Spin"] = bg.Node(id="Spin", node_type="OrientationInterpolator", role=bg.BEHAVIOUR,
                                          fields={"key": "0 1", "keyValue": "0 1 0 0 0 1 0 3.14159265"})
        text = b.weave(DOC)
        again = bg.Behaviour.from_x3d(text)
        self.assertEqual(again.nodes["Spin"].fields["keyValue"], "0 1 0 0 0 1 0 3.14159265")
        want = samples(reference)
        self.assertEqual(samples(b), want)
        self.assertEqual(samples(again), want)
        # the old six-decimal text sat just over pi and turned the other way
        old = bg.Graph()
        old.nodes["Spin"] = bg.Node(id="Spin", node_type="OrientationInterpolator", role=bg.BEHAVIOUR,
                                    fields={"key": "0 1", "keyValue": "0 1 0 0 0 1 0 3.141593"})
        self.assertNotEqual(samples(old), want)


class RoundTrip(unittest.TestCase):

    def check(self, x):
        text = bg.format_float(x)
        self.assertEqual(float(text), x, (x, text))
        self.assertEqual(math.copysign(1.0, float(text)) > 0, math.copysign(1.0, x) > 0 or x == 0, (x, text))
        self.assertNotIn("0.0e", text)
        self.assertFalse(text.endswith(".0"), text)
        self.assertNotEqual(text, "-0")

    def test_every_finite_float_reads_back_exactly(self):
        rng = random.Random(20261126)
        values = [0.0, -0.0, 1.0, -1.0, 0.1, 0.5, 1e308, -1e308, 5e-324, 2.2250738585072014e-308,
                  1.7976931348623157e308, math.pi, math.nextafter(math.pi, 4), math.nextafter(math.pi, 3), JUST_UNDER_PI,
                  1e-5, 1e16, 1e15, 123456789012345.0, 0.30000000000000004, 1 / 3]
        values += [struct.unpack("d", struct.pack("Q", rng.getrandbits(64)))[0] for _ in range(5000)]      # any bit pattern
        values += [rng.uniform(-10, 10) for _ in range(3000)]
        values += [math.pi + rng.uniform(-1e-6, 1e-6) for _ in range(2000)]
        for x in values:
            if math.isfinite(x):
                self.check(x)
        self.assertGreaterEqual(len(values), 10_000)

    def test_the_style(self):
        self.assertEqual(bg.format_float(1.0), "1")
        self.assertEqual(bg.format_float(-0.0), "0")
        self.assertEqual(bg.format_float(0.5), "0.5")
        self.assertEqual(bg.format_float(2), "2")
        self.assertEqual(bg.to_lexical((0, 1.5, -0.0)), "0 1.5 0")
        self.assertEqual(bg.to_lexical(True), "true")
        self.assertEqual(bg.to_lexical(7), "7")

    def test_a_32_bit_value_prints_short_and_reads_back_as_the_same_float32(self):
        rng = random.Random(7)
        for x in [0.3, 0.1, 1 / 3, 3.14159265, 0.7, 100.25, 1e-5, 16777217.0] + [rng.uniform(-100, 100) for _ in range(2000)]:
            single = struct.unpack("f", struct.pack("f", x))[0]
            text = bg.format_float32(single)
            self.assertEqual(struct.unpack("f", struct.pack("f", float(text)))[0], single, (single, text))
            self.assertLessEqual(len(text), 12, text)
        self.assertEqual(bg.format_float32(struct.unpack("f", struct.pack("f", 0.3))[0]), "0.3")
        self.assertEqual(bg.to_lexical((struct.unpack("f", struct.pack("f", 0.1))[0],), single=True), "0.1")
        # a double that is not a float32 is not shortened
        self.assertEqual(bg.format_float32(0.1), "0.1")
        self.assertEqual(bg.format_float32(1 / 3), repr(1 / 3))

    def test_the_xml_value_reads_in_the_graphs_own_parser(self):
        for x in (1e-5, 1e16, 5e-324, 1.7976931348623157e308):
            b = bg.Behaviour()
            b.add("ScalarInterpolator", "S", key=[0, 1], keyValue=[x, 2.0])
            self.assertEqual(float(b.nodes["S"].fields["keyValue"].split()[0]), x)
            self.assertEqual(bg.Behaviour.from_x3d(b.weave(DOC)).nodes["S"].fields["keyValue"],
                             b.nodes["S"].fields["keyValue"])


if __name__ == "__main__":
    unittest.main()
