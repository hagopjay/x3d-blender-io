# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Carry: X3D child nodes the import has no handler for (import_x3d.CARRY_SPECS: the audio graph, volume data,
particle systems, clip planes, local fog...) are kept as the file wrote them and written back in place by the X3D 4.0
export. Blender does nothing with them; nothing is lost on a round trip.

The rules pinned here: a carried node rides on its nearest Transform's object (or the scene) and comes back inside that
Transform; a subtree holding anything the import builds (a Shape...) is not carried, so nothing is written twice; every
carried DEF is reserved before the writer names anything; an item that USEs a name no carried node defines is left out
and reported (it would dangle); a ROUTE between carried nodes is carried, one with a single carried end is not; a carried
node under a USE'd Transform is written once and USE'd after. Edits: an object deleted in Blender takes its carried
nodes with it.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_node_board_carry_bpy
"""

from __future__ import annotations

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
FIXTURE = ROOT / "tests" / "node_board" / "carry.x3d"
HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n<X3D profile="Full" version="4.0"><head/><Scene>\n'
TAIL = "</Scene></X3D>\n"


class ReservedNamesTests(unittest.TestCase):
    """No Blender needed: a reserved (carried) DEF is never handed out to the writer's own nodes."""

    def test_a_reserved_name_is_avoided(self):
        sys.path.insert(0, str(ROOT / "source"))
        try:
            from emit_x3d40 import _DefNames
        except ImportError as error:      # pragma: no cover - the module needs its package
            self.skipTest(f"emit_x3d40 not importable alone: {error}")
        defs = _DefNames()
        defs.reserve("Haze")
        self.assertEqual(defs.get("transform", "Haze", "", label="Haze"), "Haze_2")


if HAVE_BPY:
    from test_roundtrip_bpy import _register_extension
    from test_node_board_batch_bpy import _valid


@unittest.skipUnless(HAVE_BPY, "bpy not available")
class CarryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="x3d_carry_")
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

    def _import(self, path=FIXTURE):
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=str(path)), {"FINISHED"})

    def _import_text(self, body):
        src = os.path.join(self.tmp, "in.x3d")
        Path(src).write_text(HEAD + body + TAIL, encoding="utf-8")
        self._import(src)

    def test_carried_nodes_come_back_as_written_in_place(self):
        self._import()
        root = self._export()[1]
        scene = root.find("Scene")
        top = {e.tag: e for e in scene}
        self.assertEqual((top["LocalFog"].get("DEF"), top["LocalFog"].get("visibilityRange")), ("Haze", "30"))
        self.assertEqual(top["ClipPlane"].get("plane"), "0 1 0 -1")
        self.assertEqual((top["OscillatorSource"].get("frequency"), top["Gain"].get("gain")), ("440", "0.5"))
        self.assertEqual(top["WaveShaper"].get("oversample"), "2X")
        rig = next(t for t in scene.iter("Transform") if t.find("Shape") is not None)
        inside = {e.tag: e for e in rig}
        self.assertEqual(inside["ParticleSystem"].find("PointEmitter").get("speed"), "0.5",
                         "inside the Transform it was in, children and all")
        self.assertEqual(inside["VolumeData"].find("ImageTexture3D").get("url"), '"scan.nrrd"')

    def test_every_carried_node_type_comes_back(self):
        # tests/node_board/carry_all.x3d: each type in CARRY_SPECS that may sit at the top of a scene (CADFace, Layout,
        # PeriodicWave and Viewport only live inside other nodes)
        source = ROOT / "tests" / "node_board" / "carry_all.x3d"
        wanted = set(re.findall(r'DEF="(C_\w+)"', source.read_text(encoding="utf-8")))
        self.assertGreaterEqual(len(wanted), 30)
        self._import(source)
        root = self._export()[1]
        self.assertEqual({e.get("DEF") for e in root.iter() if (e.get("DEF") or "").startswith("C_")}, wanted)

    def test_routes_between_carried_nodes_are_kept_and_others_are_not(self):
        self._import()
        root = self._export()[1]
        routes = [(r.get("fromNode"), r.get("toNode")) for r in root.iter("ROUTE")]
        self.assertIn(("Cut", "Haze"), routes)
        self.assertNotIn(("Clock", "Haze"), routes, "one end is not carried: not guessed at")

    def test_with_the_behaviour_graph_on_nothing_is_written_twice(self):
        # the graph keeps a ROUTE's scene-node ends in place itself (ClipPlane Cut, LocalFog Haze) and writes their ROUTE:
        # carry steps aside for those (the node board probe imports with the graph on and caught DEF="Cut" twice)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=str(FIXTURE), use_behaviour_graph=True), {"FINISHED"})
        out, root = self._export()
        defs = [e.get("DEF") for e in root.iter() if e.get("DEF")]
        self.assertEqual(sorted(d for d in set(defs) if defs.count(d) > 1), [])
        self.assertEqual(sum(1 for r in root.iter("ROUTE") if (r.get("fromNode"), r.get("toNode")) == ("Cut", "Haze")), 1)

    def test_a_carried_node_that_would_dangle_is_left_out_and_reported(self):
        self._import()
        out, root = self._export()
        self.assertIsNone(root.find(".//TextureProjector"), "it USEs Wood, a texture of a built Shape")
        self.assertIn("Carried TextureProjector uses Wood", Path(out).read_text(encoding="utf-8"))

    def test_a_subtree_with_a_shape_is_built_not_carried(self):
        self._import_text('<ParticleSystem DEF="Fire"><Shape DEF="Hull" containerField="geometry"><Box/></Shape></ParticleSystem>')
        self.assertIsNone(bpy.context.scene.get("x3d_carried"), "the Shape is built, so the subtree is not carried")
        root = self._export()[1]
        self.assertIsNone(root.find(".//ParticleSystem"))
        self.assertEqual(len(list(root.iter("Shape"))), 1, "the hull once, not twice")

    def test_a_carried_node_under_a_used_transform_is_written_once(self):
        self._import_text('<Transform DEF="A"><Shape DEF="S"><Box/></Shape><LocalFog DEF="F" visibilityRange="5"/></Transform>'
                          '<Transform DEF="B" translation="3 0 0"><Transform USE="A"/></Transform>')
        root = self._export()[1]
        fogs = list(root.iter("LocalFog"))
        self.assertGreaterEqual(len(fogs), 1)
        self.assertEqual([f.get("DEF") for f in fogs].count("F"), 1, "one DEF; any other copy is a USE")
        self.assertTrue(all(f.get("USE") == "F" for f in fogs if f.get("DEF") is None))

    def test_deleting_the_object_takes_its_carried_nodes(self):
        self._import()
        crate = next(o for o in bpy.data.objects if o.get("x3d_carried"))
        bpy.data.objects.remove(crate, do_unlink=True)
        root = self._export()[1]
        self.assertIsNone(root.find(".//ParticleSystem"))
        self.assertIsNotNone(root.find(".//LocalFog"), "the top-level ones ride on the scene")

    def test_a_second_round_trip_writes_the_same_file(self):
        self._import()
        first, _ = self._export()
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmp)
        self._import(first)
        second, _ = self._export("out2.x3d")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmp)
        self._import(second)
        third, _ = self._export("out3.x3d")
        strip = lambda text: re.sub(r'<meta name="(created|modified|generator|filename)"[^>]*>', "", text)
        self.assertEqual(strip(Path(third).read_text(encoding="utf-8")), strip(Path(second).read_text(encoding="utf-8")),
                         "after the first export (which drops what would dangle) the file is a fixed point")


if __name__ == "__main__":
    unittest.main()
