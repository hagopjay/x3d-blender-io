# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""source/sound_graph.py without Blender: parsing, the plan, the XML round trip, the biquad prediction::

    cd tests && python -m unittest test_sound_graph
"""

from __future__ import annotations

import math
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source"))

import sound_graph as sg  # noqa: E402

FIX = ROOT / "tests" / "sound"


def graphs(name):
    return sg.find_graphs(ET.parse(FIX / name).getroot())


def shape(e):
    return (e.tag, sorted(e.attrib.items()), [shape(c) for c in e])


class Parse(unittest.TestCase):
    def test_lowpass_chain(self):
        (g,) = graphs("osc_lowpass_gain.x3d")
        self.assertEqual(g.tag, "AudioDestination")
        gain = g.inputs[0]
        self.assertEqual((gain.tag, gain.num("gain")), ("Gain", 0.5))
        lp = gain.inputs[0]
        self.assertEqual((lp.raw("type"), lp.num("frequency"), lp.num("qualityFactor")), ("LOWPASS", 1000.0, 0.0))
        self.assertEqual([oscillator_hz for oscillator_hz in map(sg.oscillator_frequency, lp.inputs)], [440.0, 4000.0])

    def test_defaults_from_xsd(self):
        n = sg.AudioNode("OscillatorSource")
        self.assertEqual((n.num("frequency"), n.num("gain"), sg.waveform(n)[0]), (440.0, 1.0, "SINE"))
        self.assertEqual(sg.AudioNode("BiquadFilter").num("frequency"), 350.0)
        self.assertEqual(sg.AudioNode("PeriodicWave").raw("type"), "SQUARE")

    def test_detune_cents(self):
        n = sg.AudioNode("OscillatorSource", {"frequency": "440", "detune": "1200"})
        self.assertAlmostEqual(sg.oscillator_frequency(n), 880.0)

    def test_periodicwave_is_not_an_input(self):
        e = ET.fromstring('<OscillatorSource frequency="220"><PeriodicWave type="SAWTOOTH"/></OscillatorSource>')
        n = sg.parse_graph(e)
        self.assertEqual((n.inputs, sg.waveform(n)[0]), ([], "SAWTOOTH"))

    def test_splitter_outputs_not_inputs(self):
        e = ET.fromstring('<ChannelSplitter><OscillatorSource/><Gain containerField="outputs"/></ChannelSplitter>')
        n = sg.parse_graph(e)
        self.assertEqual([c.tag for c in n.inputs], ["OscillatorSource"])

    def test_nested_graph_found_once_under_transform(self):
        gs = graphs("spatial_delay_window.x3d")
        self.assertEqual([g.tag for g in gs], ["SpatialSound"])


class Plan(unittest.TestCase):
    def kinds(self, name):
        s = sg.summary(sg.plan(graphs(name)[0]))
        return {k: s[k] for k in ("aud", "numpy", "pass", "none")}, s["notes"]

    def test_lowpass_chain_all_aud(self):
        self.assertEqual(self.kinds("osc_lowpass_gain.x3d"), ({"aud": 5, "numpy": 0, "pass": 0, "none": 0}, []))

    def test_merger_uses_numpy(self):
        self.assertEqual(self.kinds("merger_two_osc.x3d")[0], {"aud": 3, "numpy": 1, "pass": 0, "none": 0})

    def test_spatial_notes_dry(self):
        notes = self.kinds("spatial_delay_window.x3d")[1]
        self.assertTrue(any("Speaker" in n for n in notes))

    def test_every_node_has_a_kind(self):
        self.assertEqual(set(sg.KIND), set(sg.AUDIO_NODES))
        for tag in sg.AUDIO_NODES:
            if tag == "PeriodicWave":
                continue
            step = sg.plan(sg.AudioNode(tag))
            self.assertIn(step.kind, ("aud", "numpy", "pass", "none"), tag)

    def test_live_sources_are_none(self):
        for tag in ("MicrophoneSource", "StreamAudioSource", "ListenerPointSource"):
            self.assertEqual(sg.plan(sg.AudioNode(tag)).kind, "none")


class RoundTrip(unittest.TestCase):
    def test_xml_model_xml(self):
        for f in sorted(FIX.glob("*.x3d")):
            for g in graphs(f.name):
                original = next(e for e in ET.parse(f).getroot().iter(g.tag))
                back = sg.to_xml(g)
                self.assertEqual(shape(back), shape(original), f.name)
                self.assertEqual(list(back.attrib), list(original.attrib), "attribute order")

    def test_raw_strings_kept(self):
        e = ET.fromstring('<Gain gain="0.50" DEF="g"><OscillatorSource frequency="4.4e2"/></Gain>')
        back = ET.tostring(sg.to_xml(sg.parse_graph(e)), encoding="unicode")
        self.assertIn('gain="0.50"', back)
        self.assertIn('frequency="4.4e2"', back)

    def test_non_audio_child_kept(self):
        e = ET.fromstring('<Sound><MetadataString name="k" value=\'"v"\'/><AudioClip url=\'"a.wav"\'/></Sound>')
        back = sg.to_xml(sg.parse_graph(e))
        self.assertEqual([c.tag for c in back], ["MetadataString", "AudioClip"])


class Biquad(unittest.TestCase):
    def test_lowpass_prediction(self):
        b, a = sg.biquad_coefficients("LOWPASS", 1000, 0, 0, 48000)
        self.assertAlmostEqual(sg.biquad_magnitude(b, a, 0.001, 48000), 1.0, places=4)   # unity at DC
        rel = 20 * math.log10(sg.biquad_magnitude(b, a, 4000, 48000) / sg.biquad_magnitude(b, a, 440, 48000))
        self.assertAlmostEqual(rel, -24.9, delta=0.1)

    def test_q_db_for_lowpass(self):   # Web Audio: Q in dB for lowpass, so Q=0 dB is |H(f0)| = 1
        b, a = sg.biquad_coefficients("LOWPASS", 1000, 0, 0, 48000)
        self.assertAlmostEqual(sg.biquad_magnitude(b, a, 1000, 48000), 1.0, places=3)

    def test_all_types_build(self):
        for t in ("LOWPASS", "HIGHPASS", "BANDPASS", "LOWSHELF", "HIGHSHELF", "PEAKING", "NOTCH", "ALLPASS"):
            b, a = sg.biquad_coefficients(t, 1000, 1, 0, 48000)
            self.assertEqual((len(b), len(a), a[0]), (3, 3, 1.0))

    def test_notch_kills_f0(self):
        b, a = sg.biquad_coefficients("NOTCH", 1000, 1, 0, 48000)
        self.assertLess(sg.biquad_magnitude(b, a, 1000, 48000), 1e-9)


class Speaker(unittest.TestCase):
    def test_spatialsound_fields(self):
        st = sg.speaker_settings(graphs("spatial_delay_window.x3d")[0])
        self.assertEqual((st["volume"], st["distance_max"], st["cone_volume_outer"]), (0.5, 50.0, 0.25))
        self.assertAlmostEqual(st["cone_angle_inner"], 90.0, places=2)


if __name__ == "__main__":
    unittest.main()
