# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The fifth batch of gaps the node board ranked (docs/NODE_BOARD.md, docs/NODE_BOARD_PRIORITIES.md): the triangle-set
family, TriangleSet, TriangleFanSet, TriangleStripSet, IndexedTriangleFanSet and IndexedTriangleStripSet, each imported
and written back by the X3D 4.0 export in Blender.

The import names the node on the mesh (``x3d_geometry``, as batch 2 did for IndexedTriangleSet) and the writer writes
that node while every face is a triangle. The fans and strips are read off the mesh's own triangles at export time
(emit_x3d40._fan_strip_runs) and must unroll to exactly those triangles, so an edited mesh still writes arrays that
match it: a moved vertex keeps the node, triangles that no longer chain start a new fan or strip, and a face that is
not a triangle writes an IndexedFaceSet. Every export validates against x3d-4.0.xsd when lxml and the
schema are on the machine (X3D_XSD names it), and the add-on's structural validator always.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_node_board_batch5_bpy
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

from test_roundtrip_bpy import _register_extension
from test_node_board_batch_bpy import _valid

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "node_board" / "gap_batch_5.x3d"
SETS = ("TriangleSet", "TriangleFanSet", "TriangleStripSet", "IndexedTriangleFanSet", "IndexedTriangleStripSet")


def _triangles(obj):
    """The object's triangles as world-space corner positions, in face order (rounded)."""
    mesh = obj.data
    out = []
    for polygon in mesh.polygons:
        out.append(tuple(tuple(round(v, 4) for v in obj.matrix_world @ mesh.vertices[i].co) for i in polygon.vertices))
    return out


def _scene_triangles():
    return {o.name.split(".")[0]: _triangles(o) for o in bpy.context.scene.objects if o.type == "MESH"}


class FanStripRunTests(unittest.TestCase):
    """emit_x3d40._fan_strip_runs, the part that decides fanCount, stripCount and the indexed runs (plain Python)."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "source"))
        try:
            import emit_x3d40
        except Exception as error:  # pragma: no cover - the package needs its relative imports
            raise unittest.SkipTest(f"emit_x3d40 not importable alone: {error}")
        cls.runs = staticmethod(emit_x3d40._fan_strip_runs)

    def test_a_fan_and_a_strip_come_back_as_one_run_each(self):
        self.assertEqual(self.runs([0, 1, 2, 0, 2, 3, 0, 3, 4], strip=False), [[0, 1, 2, 3, 4]])
        self.assertEqual(self.runs([0, 1, 2, 2, 1, 3, 2, 3, 4], strip=True), [[0, 1, 2, 3, 4]])

    def test_triangles_that_do_not_chain_start_new_runs(self):
        self.assertEqual(self.runs([0, 1, 2, 5, 6, 7], strip=False), [[0, 1, 2], [5, 6, 7]])
        # the second strip triangle with the wrong turn is not the strip's next triangle
        self.assertEqual(self.runs([0, 1, 2, 1, 2, 3], strip=True), [[0, 1, 2], [1, 2, 3]])


@unittest.skipUnless(HAVE_BPY, "bpy not available")
class NodeBoardBatch5Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="x3d_node_board5_")
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

    def _reimport(self, path):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmp)
        self._import(path)

    @staticmethod
    def _one(root, tag):
        found = list(root.iter(tag))
        assert len(found) == 1, f"{tag}: {len(found)} found"
        return found[0]

    def test_each_set_is_written_back_as_itself(self):
        self._import()
        root = self._export()[1]
        self.assertEqual([e.tag for e in root.iter() if e.tag in ("IndexedFaceSet", "IndexedTriangleSet")], [],
                         "no set fell back")
        tris = self._one(root, "TriangleSet")
        self.assertEqual(tris.get("solid"), "false")
        self.assertIsNone(tris.get("index"))
        self.assertEqual(len(tris.find("Coordinate").get("point").split()), 18, "two triangles, one point per corner")
        self.assertEqual(len(tris.find("TextureCoordinate").get("point").split()), 12)
        fans = self._one(root, "TriangleFanSet")
        self.assertEqual(fans.get("fanCount"), "5 3")
        self.assertEqual(len(fans.find("Coordinate").get("point").split()), 24)
        self.assertEqual(len(fans.find("ColorRGBA").get("color").split()), 32)
        strips = self._one(root, "TriangleStripSet")
        self.assertEqual(strips.get("stripCount"), "5 4")
        self.assertIsNotNone(strips.find("TextureCoordinate"))
        indexed_fans = self._one(root, "IndexedTriangleFanSet")
        self.assertEqual(indexed_fans.get("index"), "0 1 2 3 4 -1 5 6 7 8 -1")
        self.assertEqual(indexed_fans.get("solid"), "false")
        indexed_strips = self._one(root, "IndexedTriangleStripSet")
        self.assertEqual(indexed_strips.get("index"), "0 1 2 3 4 -1 5 6 7 -1")
        self.assertIsNotNone(indexed_strips.find("ColorRGBA"))

    def test_the_written_sets_give_back_the_same_triangles(self):
        self._import()
        before = _scene_triangles()
        self.assertEqual(sorted(len(t) for t in before.values()), [2, 4, 4, 5, 5])
        out = self._export()[0]
        self._reimport(out)
        self.assertEqual(_scene_triangles(), before)

    def test_a_moved_vertex_keeps_the_node_and_the_arrays_follow_the_mesh(self):
        self._import()
        for obj in bpy.context.scene.objects:
            if obj.type == "MESH":
                obj.data.vertices[0].co.z += 0.25
        before = _scene_triangles()
        out, root = self._export()
        for tag in SETS:
            self._one(root, tag)
        self._reimport(out)
        self.assertEqual(_scene_triangles(), before)

    def test_triangles_that_no_longer_chain_split_the_run(self):
        self._import()
        flipped = 0
        for obj in bpy.context.scene.objects:
            if obj.type == "MESH" and obj.data.get("x3d_geometry") in ("TriangleStripSet", "IndexedTriangleFanSet"):
                obj.data.polygons[1].flip()        # the second triangle's winding no longer follows its run
                flipped += 1
        self.assertEqual(flipped, 2)
        before = _scene_triangles()
        out, root = self._export()
        counts = [int(c) for c in self._one(root, "TriangleStripSet").get("stripCount").split()]
        self.assertGreater(len(counts), 2, "the first strip is cut where the flipped triangle sits")
        self.assertEqual(sum(c - 2 for c in counts), 5, "and still holds the five triangles")
        index = self._one(root, "IndexedTriangleFanSet").get("index")
        self.assertNotEqual(index, "0 1 2 3 4 -1 5 6 7 8 -1")
        self._reimport(out)
        self.assertEqual(_scene_triangles(), before, "the runs give back the edited triangles, windings included")

    def test_a_set_edited_to_have_a_quad_falls_back_to_a_face_set(self):
        for node in SETS:
            mesh = bpy.data.meshes.new(node)
            mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
            mesh["x3d_geometry"] = node
            bpy.context.scene.collection.objects.link(bpy.data.objects.new(node, mesh))
        root = self._export()[1]
        for node in SETS:
            self.assertEqual(list(root.iter(node)), [], node)
        self.assertEqual(len(list(root.iter("IndexedFaceSet"))), len(SETS))

    def test_triangulate_still_writes_indexed_triangle_sets_for_untagged_meshes(self):
        mesh = bpy.data.meshes.new("Quad")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
        bpy.context.scene.collection.objects.link(bpy.data.objects.new("Quad", mesh))
        self._import()
        out = os.path.join(self.tmp, "tri.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False,
                                                  use_triangulate=True), {"FINISHED"})
        root = ET.parse(out).getroot()
        self.assertEqual(len(list(root.iter("IndexedTriangleSet"))), 1)
        for node in SETS:
            self.assertEqual(len(list(root.iter(node))), 1, node)

    def test_a_second_round_trip_writes_the_same_file(self):
        self._import()
        first_path = self._export()[0]
        first_text = Path(first_path).read_text(encoding="utf-8")
        self._reimport(first_path)
        second_path, _ = self._export("out2.x3d")
        strip = lambda text: re.sub(r'<meta name="(created|modified|generator|filename)"[^>]*>', "", text)
        self.assertEqual(strip(Path(second_path).read_text(encoding="utf-8")), strip(first_text))


if __name__ == "__main__":
    unittest.main()
