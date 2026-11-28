# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The sound bridge wired into the import and the X3D 4.0 export (source/sound_bridge.py, docs/SOUND_BRIDGE.md §8).

A SpatialSound graph becomes a Speaker under its Transform's object, playing the graph's render, and comes back as the
file wrote it, with only what was changed on the Speaker merged in; deleting the Speaker drops it. A destination graph
stays carried and gets a sound strip (a cache). A graph the bridge cannot render faithfully (a ROUTE into it, a USE in
it) is left to carry alone.

Skipped when ``bpy`` is not importable::

    Blender -b --factory-startup --python-exit-code 1 --python .github/scripts/run_tests_in_blender.py -- test_sound_bridge_bpy
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import bpy
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

ROOT = Path(__file__).resolve().parent.parent
SOUND = ROOT / "tests" / "sound"
HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n<X3D profile="Full" version="4.0"><head/><Scene>\n'
TAIL = "</Scene></X3D>\n"

if HAVE_BPY:
    from test_roundtrip_bpy import _register_extension
    from test_node_board_batch_bpy import _valid
    sys.path.insert(0, str(ROOT / "tools"))
    import sound_bridge_demo as demo


def _shape(element):
    """Tags, attributes and nesting: what the bridge must give back unchanged."""
    return (element.tag, dict(element.attrib), [_shape(c) for c in element])


@unittest.skipUnless(HAVE_BPY, "bpy not available")
class SoundBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="x3d_sound_bridge_")
        _register_extension(self.tmp)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmp)

    def _export(self, name="out.x3d"):
        out = os.path.join(self.tmp, name)
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False), {"FINISHED"})
        structural, errors = _valid(out)
        self.assertTrue(structural.valid, structural.errors)
        self.assertEqual(errors or [], [], "does not validate against x3d-4.0.xsd")
        return out, ET.parse(out).getroot()

    def _import(self, path):
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=str(path)), {"FINISHED"})

    def _import_text(self, body):
        src = os.path.join(self.tmp, "in.x3d")
        Path(src).write_text(HEAD + body + TAIL, encoding="utf-8")
        self._import(src)

    def _speakers(self):
        return [o for o in bpy.data.objects if o.type == "SPEAKER"]

    # --- import -----------------------------------------------------------------------------------------------------

    def test_a_spatial_sound_becomes_a_speaker_you_can_hear(self):
        self._import(SOUND / "spatial_delay_window.x3d")
        (ob,) = self._speakers()
        self.assertEqual(ob.name, "Beep")
        self.assertIsNotNone(ob.parent, "under the object of the Transform it was in")
        self.assertEqual([round(v, 4) for v in ob.matrix_world.translation], [2.0, 0.0, 0.0])
        speaker = ob.data
        self.assertEqual((round(speaker.volume, 4), round(speaker.distance_max, 4), round(speaker.cone_volume_outer, 4)),
                         (0.5, 50.0, 0.25))
        self.assertAlmostEqual(speaker.cone_angle_inner, 90.0, places=2)
        self.assertAlmostEqual(speaker.cone_angle_outer, 180.0, places=2)
        self.assertIsNotNone(speaker.sound.packed_file, "the render is in the .blend")
        self.assertNotIn("SpatialSound", ob.parent.get("x3d_carried", ""), "the Speaker keeps it, not carry")
        heard = demo.measure(bpy.path.abspath(speaker.sound.filepath), [880])
        self.assertEqual(heard["dominant_hz"], [880.0])
        self.assertEqual((heard["peak"], heard["onset_s"], heard["offset_s"]), ([0.5], [0.25], [1.25]),
                         "Delay 0.25 s on a tone that stops at 1 s, at gain 0.5 (the render is dry; the Speaker spatialises)")

    def test_a_destination_graph_stays_carried_and_gets_a_strip(self):
        self._import(SOUND / "osc_lowpass_gain.x3d")
        self.assertEqual(self._speakers(), [])
        editor = bpy.context.scene.sequence_editor
        strips = list((editor.strips if hasattr(editor, "strips") else editor.sequences))
        self.assertEqual([(s.type, s.get("x3d_sound_cache")) for s in strips], [("SOUND", True)])
        heard = demo.measure(bpy.path.abspath(strips[0].sound.filepath), [440, 4000])
        self.assertEqual(heard["dominant_hz"], [440.0])
        self.assertAlmostEqual(heard["probe_db"][0]["4000"], -24.9, delta=0.2)
        root = self._export()[1]
        source = ET.parse(SOUND / "osc_lowpass_gain.x3d").getroot().find(".//AudioDestination")
        self.assertEqual(_shape(root.find(".//AudioDestination")), _shape(source))

    # --- export -----------------------------------------------------------------------------------------------------

    def test_the_graph_comes_back_as_written(self):
        self._import(SOUND / "spatial_delay_window.x3d")
        root = self._export()[1]
        source = ET.parse(SOUND / "spatial_delay_window.x3d").getroot().find(".//SpatialSound")
        written = root.find(".//Transform/SpatialSound")
        self.assertIsNotNone(written, "inside its Transform again")
        self.assertEqual(_shape(written), _shape(source))
        self.assertEqual(len(list(root.iter("Transform"))), 1, "the Speaker is not written as a Transform")

    def test_edits_on_the_speaker_reach_only_their_fields(self):
        self._import(SOUND / "spatial_delay_window.x3d")
        ob = self._speakers()[0]
        ob.data.distance_max = 20.0
        ob.data.volume = 0.25
        ob.location.x += 1.0                     # the Transform is at x=2; the sound goes to x=1 inside it
        root = self._export()[1]
        written = root.find(".//Transform/SpatialSound")
        self.assertEqual((written.get("maxDistance"), written.get("intensity"), written.get("gain")), ("20", "0.5", "0.5"),
                         "volume 0.25 at gain 0.5 is intensity 0.5; the gain string stays as written")
        self.assertEqual([round(float(v), 4) for v in written.get("location").split()], [1.0, 0.0, 0.0])
        self.assertEqual((written.get("referenceDistance"), written.get("coneOuterGain")), ("1", "0.25"))
        self.assertIsNone(written.get("direction"), "not turned: not written")
        self.assertEqual(written.find("Delay").get("delayTime"), "0.25")

    def test_turning_the_speaker_writes_its_direction(self):
        self._import(SOUND / "spatial_delay_window.x3d")
        ob = self._speakers()[0]
        ob.rotation_mode = "XYZ"
        ob.rotation_euler = (0.0, 0.0, 0.0)      # no turn against its parent, whose matrix holds the axis change: the
        root = self._export()[1]                 # speaker's -Z is the Transform's own -Z (the file's default is +Z)
        direction = [round(float(v), 4) for v in root.find(".//SpatialSound").get("direction").split()]
        self.assertEqual(direction, [0.0, 0.0, -1.0])

    def test_a_clamped_volume_is_not_an_edit(self):
        self._import_text('<SpatialSound DEF="Loud" gain="2"><OscillatorSource frequency="220"/></SpatialSound>')
        self.assertEqual(round(self._speakers()[0].data.volume, 4), 1.0, "Blender's volume stops at 1")
        written = self._export()[1].find(".//SpatialSound")
        self.assertEqual((written.get("gain"), written.get("intensity")), ("2", None), "gain 2 x intensity 1, as written")

    def test_deleting_the_speaker_drops_the_graph(self):
        self._import(SOUND / "spatial_delay_window.x3d")
        bpy.data.objects.remove(self._speakers()[0], do_unlink=True)
        root = self._export()[1]
        self.assertIsNone(root.find(".//SpatialSound"))
        self.assertIsNone(root.find(".//OscillatorSource"))

    # --- left to carry ----------------------------------------------------------------------------------------------

    def test_a_routed_graph_is_carried_not_bridged(self):
        self._import_text('<SpatialSound DEF="S"><Gain DEF="G"><OscillatorSource/></Gain></SpatialSound>'
                          '<SpatialSound DEF="T"><Gain DEF="H"><OscillatorSource/></Gain></SpatialSound>'
                          '<ROUTE fromNode="G" fromField="gain" toNode="H" toField="gain"/>')
        self.assertEqual(self._speakers(), [], "a ROUTE into the graph: a render would freeze it")
        root = self._export()[1]
        self.assertEqual({s.get("DEF") for s in root.iter("SpatialSound")}, {"S", "T"})
        self.assertIn(("G", "H"), [(r.get("fromNode"), r.get("toNode")) for r in root.iter("ROUTE")])

    def test_a_graph_with_a_use_is_carried_not_bridged(self):
        self._import_text('<SpatialSound DEF="S"><OscillatorSource DEF="O"/><Gain><OscillatorSource USE="O"/></Gain>'
                          '</SpatialSound>')
        self.assertEqual(self._speakers(), [])
        self.assertIsNotNone(self._export()[1].find(".//SpatialSound"))

    def test_a_second_round_trip_writes_the_same_file(self):
        self._import(SOUND / "spatial_delay_window.x3d")
        first, _ = self._export()
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmp)
        self._import(first)
        self.assertEqual(len(self._speakers()), 1)
        second, _ = self._export("out2.x3d")
        strip = lambda text: re.sub(r'<meta name="(created|modified|generator|filename)"[^>]*>', "", text)
        self.assertEqual(strip(Path(second).read_text(encoding="utf-8")), strip(Path(first).read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
