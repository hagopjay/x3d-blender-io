# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The node board's twelfth batch: the CAD product structure (CADLayer, CADAssembly, CADPart, CADFace) and
StaticGroup (docs/NODE_BOARD_PRIORITIES.md, batch 12).

Before this batch a CADPart's pose was ignored, so every part of an assembly sat at its parent's origin, and the export
wrote the parts as plain Transforms. Now:

* a CADPart places its children like a Transform (its translation, rotation, scale, center and scaleOrientation), and
  a ROUTE can animate it (an exploded view);
* each CADLayer, CADAssembly and CADPart is an object in the hierarchy, named by its ``name`` field (part numbers in the
  Outliner), with its DEF and fields kept in ``x3d_cad``; a CADFace marks the object of the node it holds;
* the X3D 4.0 export writes the structure back: a part's pose from Blender, everything inside a part in a CADFace (the
  only node x3d-4.0.xsd allows there), parts in the file's order. StaticGroup is regrouped like batch 3's groups.

tests/node_board/gap_batch_12.x3d is an articulated desk lamp: every part is placed only by its CADPart, so a misread
part shows at once.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_node_board_batch12_bpy
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import bpy
    from mathutils import Vector
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "node_board" / "gap_batch_12.x3d"
HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n<X3D profile="Full" version="4.0"><head/><Scene>\n'
TAIL = "</Scene></X3D>\n"

if HAVE_BPY:
    from test_roundtrip_bpy import _register_extension
    from test_node_board_batch_bpy import _valid


def _floats(text):
    return [round(float(v), 4) for v in text.split()]


def _tree(element):
    """The CAD structure of an export: (tag, DEF, name) nested, Shapes and Transforms left out."""
    kept = ("CADLayer", "CADAssembly", "CADPart", "CADFace", "StaticGroup")
    out = []
    for child in element:
        if child.tag in kept:
            out.append((child.tag, child.get("DEF"), child.get("name"), _tree(child)))
        else:
            out.extend(_tree(child))
    return out


@unittest.skipUnless(HAVE_BPY, "bpy not available")
class NodeBoardBatch12Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="x3d_node_board12_")
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

    def _import(self, path=FIXTURE, **options):
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=str(path), **options), {"FINISHED"})

    def _import_text(self, body, **options):
        src = os.path.join(self.tmp, "in.x3d")
        Path(src).write_text(HEAD + body + TAIL, encoding="utf-8")
        self._import(src, **options)

    def _at(self, name):
        return [round(v, 3) for v in bpy.data.objects[name].matrix_world.translation]

    def _part(self, root, def_name):
        node = next((e for e in root.iter("CADPart") if e.get("DEF") == def_name), None)
        self.assertIsNotNone(node, def_name)
        return node

    # --- what Blender holds ---------------------------------------------------------------------------------------

    def test_each_part_stands_where_its_cad_part_puts_it(self):
        self._import()
        # X3D (x, y, z) is Blender (x, -z, y); the elbow is the lower link's tip, the shade the upper link's
        self.assertEqual(self._at("LMP112_UpperLink"), [0.206, 0.0, 0.589])
        self.assertEqual(self._at("LMP121_Shade"), [-0.186, 0.0, 0.9])
        self.assertEqual(self._at("LowerRod"), [0.103, 0.0, 0.307], "half way up the tilted lower link")
        lower = bpy.data.objects["LMP111_LowerLink"].matrix_world.to_euler()
        self.assertAlmostEqual(lower.y, 0.35, places=4, msg="X3D -0.35 rad about Z is Blender +0.35 about Y")

    def test_the_outliner_reads_like_the_cad_tree(self):
        self._import()
        parent = lambda name: bpy.data.objects[name].parent.name
        self.assertEqual(parent("LMP100_DeskLamp"), "Structure")
        self.assertEqual(parent("LMP110_Arm"), "LMP100_DeskLamp")
        self.assertEqual(parent("LMP111_LowerLink"), "LMP110_Arm")
        self.assertEqual(parent("LowerRod"), "LMP111_LowerLink")
        self.assertEqual(parent("LMP121_Shade"), "LMP120_Head")
        record = json.loads(bpy.data.objects["LMP112_UpperLink"]["x3d_cad"])
        self.assertEqual((record["node"], record["def"], record["fields"]["name"]),
                         ("CADPart", "UpperArm", "LMP112_UpperLink"))
        self.assertEqual(record["face"]["fields"]["name"], "ElbowKnuckle", "its Shape is the knuckle face")
        self.assertEqual(json.loads(bpy.data.objects["LowerRod"]["x3d_cad"])["face"]["def"], "LowerRod")

    # --- what is written back -------------------------------------------------------------------------------------

    def test_the_product_structure_is_written_back(self):
        self._import()
        root = self._export()[1]
        source = ET.parse(FIXTURE).getroot()
        self.assertEqual(_tree(root.find("Scene")), _tree(source.find("Scene")),
                         "the same layers, assemblies, parts, faces and StaticGroup, with their DEFs and names, in order")
        upper = self._part(root, "UpperArm")
        self.assertEqual((_floats(upper.get("translation")), _floats(upper.get("rotation"))),
                         ([0.2057, 0.5888, 0.0], [0.0, 0.0, 1.0, 0.9]))
        self.assertEqual(_floats(self._part(root, "Shade").get("scale")), [1.0, 1.2, 1.0])
        self.assertEqual({c.tag for p in root.iter("CADPart") for c in p}, {"CADFace"}, "a part holds only faces")
        # the XSD does not check containerField: X_ITE 16.7.0 drops a face whose node says children (measured)
        self.assertEqual({c.get("containerField") for f in root.iter("CADFace") for c in f}, {"shape"})
        components = {c.get("name"): c.get("level") for c in root.iter("component")}
        self.assertEqual((components.get("CADGeometry"), components.get("Grouping")), ("2", "3"))

    def test_a_part_moved_in_blender_is_written_where_it_now_is(self):
        self._import()
        shade = bpy.data.objects["LMP121_Shade"]
        shade.location.x += 0.1
        bpy.context.view_layer.update()
        root = self._export()[1]
        self.assertEqual(_floats(self._part(root, "Shade").get("translation")), [-0.086, 0.8996, 0.0])

    def test_a_mesh_added_to_a_part_is_written_in_a_new_face(self):
        self._import()
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.02)
        bulb = bpy.context.active_object
        bulb.name = "Bulb"
        bulb.parent = bpy.data.objects["LMP121_Shade"]
        root = self._export()[1]
        faces = self._part(root, "Shade").findall("CADFace")
        self.assertEqual([f.get("DEF") for f in faces], ["ShadeShell", "Bulb", None], "the new one has no face of its own yet")
        self.assertEqual(faces[2][0].tag, "Transform")

    def test_a_cad_node_dragged_under_a_part_is_still_valid(self):
        self._import()
        bpy.data.objects["LMP120_Head"].parent = bpy.data.objects["LMP101_Base"]
        out, root = self._export()          # _export asserts the file is valid
        self.assertIsNone(next((a for a in root.iter("CADAssembly") if a.get("DEF") == "Head"), None),
                          "an assembly cannot stand in a CADFace: written as a Transform there")
        self.assertIsNotNone(self._part(root, "Shade"), "nor can its part; but the part's shapes are all still there")

    def test_a_part_used_twice_is_placed_twice(self):
        # a bolt DEF'd once and USE'd in a second place: both copies stand where their parents put them
        self._import_text(
            '<CADAssembly DEF="Plate" name="Plate">'
            '<Transform translation="-1 0 0"><CADPart DEF="Bolt" name="M6 bolt" translation="0 0.5 0">'
            '<CADFace name="Shank"><Shape><Cylinder radius="0.05" height="1"/></Shape></CADFace></CADPart></Transform>'
            '<Transform translation="1 0 0"><CADPart USE="Bolt"/></Transform></CADAssembly>')
        heights = sorted(round(o.matrix_world.translation.z, 3) for o in bpy.data.objects if o.type == "MESH")
        xs = sorted(round(o.matrix_world.translation.x, 3) for o in bpy.data.objects if o.type == "MESH")
        self.assertEqual((heights, xs), ([0.5, 0.5], [-1.0, 1.0]))
        root = self._export()[1]
        self.assertEqual(len(list(root.iter("CADPart"))), 2)
        self.assertEqual(len({p.get("DEF") for p in root.iter("CADPart")}), 2, "each copy its own DEF: no duplicate")

    def test_an_exploded_view_animates_the_part(self):
        self._import_text(
            '<CADAssembly name="Box"><CADPart DEF="Lid" name="Lid" translation="0 1 0">'
            '<CADFace name="Top"><Shape><Box size="1 0.1 1"/></Shape></CADFace></CADPart></CADAssembly>'
            '<TimeSensor DEF="Clock" cycleInterval="2" loop="true"/>'
            '<PositionInterpolator DEF="Lift" key="0 1" keyValue="0 1 0 0 2 0"/>'
            '<ROUTE fromNode="Clock" fromField="fraction_changed" toNode="Lift" toField="set_fraction"/>'
            '<ROUTE fromNode="Lift" fromField="value_changed" toNode="Lid" toField="set_translation"/>')
        lid = bpy.data.objects["Lid"]
        self.assertIsNotNone(lid.animation_data, "the ROUTE to a CADPart is imported as animation")
        scene = bpy.context.scene
        heights = []
        for frame in (scene.frame_start, scene.frame_start + int(scene.render.fps)):
            scene.frame_set(frame)
            heights.append(round(lid.matrix_world.translation.z, 2))
        self.assertEqual(heights, [1.0, 1.5])
        root = self._export()[1]
        targets = {r.get("toNode") for r in root.iter("ROUTE")}
        self.assertIn(self._part(root, "Lid").get("DEF"), targets, "the animation drives the CADPart itself")

    def test_a_flat_import_still_places_every_part(self):
        self._import(keep_hierarchy=False)
        # the shell's apex is on the shade's hinge: its centre 0.09 below it, scaled by 1.2, turned -0.6 rad about Z
        self.assertEqual(self._at("ShadeShell"), [-0.247, 0.0, 0.81])

    def test_a_second_round_trip_writes_the_same_file(self):
        self._import()
        first_path, _ = self._export()
        first_text = Path(first_path).read_text(encoding="utf-8")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmp)
        self._import(first_path)
        second_path, _ = self._export("out2.x3d")
        strip = lambda text: re.sub(r'<meta name="(created|modified|generator|filename)"[^>]*>', "", text)
        self.assertEqual(strip(Path(second_path).read_text(encoding="utf-8")), strip(first_text))


if __name__ == "__main__":
    unittest.main()
