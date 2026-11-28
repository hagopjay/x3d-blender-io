# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Render the tests/sound fixtures with Blender's aud and measure them (needs Blender's Python)::

    Blender -b --factory-startup --python-exit-code 1 --python .github/scripts/run_tests_in_blender.py -- test_sound_graph_bpy
"""

from __future__ import annotations

import math
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source"))
sys.path.insert(0, str(ROOT / "tools"))

try:
    import aud
    import numpy as np
    HAVE_AUD = True
except Exception:  # pragma: no cover
    HAVE_AUD = False

import sound_graph as sg  # noqa: E402

FIX = ROOT / "tests" / "sound"


@unittest.skipUnless(HAVE_AUD, "needs Blender's aud")
class Render(unittest.TestCase):
    def run_fixture(self, name, **kw):
        import sound_bridge_demo as demo
        g = sg.find_graphs(ET.parse(FIX / name).getroot())[0]
        r = sg.Renderer(aud, np, rate=demo.RATE, duration=2.0, **kw)
        path = str(Path(tempfile.mkdtemp()) / (name + ".wav"))
        demo.write_wav(r.array(r.render(g)), path)
        return demo.measure(path, (440, 660, 880, 4000))

    def test_lowpass_chain(self):
        m = self.run_fixture("osc_lowpass_gain.x3d")
        b, a = sg.biquad_coefficients("LOWPASS", 1000, 0, 0, 48000)
        h440, h4k = (sg.biquad_magnitude(b, a, f, 48000) for f in (440, 4000))
        self.assertEqual((m["duration_s"], m["dominant_hz"]), (2.0, [440.0]))
        self.assertAlmostEqual(m["probe_db"][0]["4000"], 20 * math.log10(h4k / h440), delta=0.5)
        self.assertLessEqual(m["peak"][0], 0.5 * (h440 + h4k) + 1e-3)
        self.assertGreater(m["peak"][0], 0.5 * h440)

    def test_merger_channels(self):
        m = self.run_fixture("merger_two_osc.x3d")
        self.assertEqual((m["channels"], m["dominant_hz"]), (2, [440.0, 660.0]))
        self.assertAlmostEqual(m["peak"][0], 1.0, delta=0.01)
        self.assertAlmostEqual(m["peak"][1], 0.5, delta=0.01)

    def test_delay_and_stop_window(self):
        m = self.run_fixture("spatial_delay_window.x3d")
        self.assertEqual(m["dominant_hz"], [880.0])
        self.assertAlmostEqual(m["peak"][0], 0.5, delta=0.01)
        self.assertAlmostEqual(m["onset_s"][0], 0.25, delta=0.002)
        self.assertAlmostEqual(m["offset_s"][0], 1.25, delta=0.002)

    def test_pause_resume_gap(self):
        e = ET.fromstring('<AudioDestination maxChannelCount="1"><OscillatorSource frequency="440" '
                          'pauseTime="0.5" resumeTime="1.0" stopTime="1.5"/></AudioDestination>')
        r = sg.Renderer(aud, np, rate=48000, duration=2.0)
        x = r.array(r.render(sg.parse_graph(e)))[:, 0]
        loud = np.abs(x) > 1e-3
        on = lambda a, b: loud[int(a * 48000):int(b * 48000)].any()   # noqa: E731
        self.assertTrue(on(0.0, 0.5))
        self.assertFalse(on(0.51, 0.99))
        self.assertTrue(on(1.0, 1.5))
        self.assertFalse(on(1.51, 1.99))   # stopTime is a clock time: the pause does not push it later
