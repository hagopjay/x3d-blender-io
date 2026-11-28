# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The eighth batch of gaps the node board ranked (docs/NODE_BOARD.md, docs/NODE_BOARD_PRIORITIES.md): LineSet,
PointProperties, CoordinateDouble, QuadSet and IndexedQuadSet, each imported and written back by the X3D 4.0 export in
Blender.

LineSet, QuadSet and IndexedQuadSet ride on batch 5's ``x3d_geometry`` tag: a LineSet is written with ``vertexCount``
read off the object's own polylines (so an edited curve still writes arrays that match it), a quad set while every
face is still a quad (else an IndexedFaceSet). CoordinateDouble: the import keeps the file's point text when the
vertices are its points one to one, and the export writes those tokens for as long as every vertex still has exactly
that value in float32; a moved vertex writes a Coordinate from the mesh. PointProperties: kept on the point object
(``x3d_point_properties``) as LineProperties is, and written in the point shape's Appearance. Every export validates
against x3d-4.0.xsd when lxml and the schema are on the machine (X3D_XSD names it), and the add-on's structural
validator always.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_node_board_batch8_bpy
"""

from __future__ import annotations

import json
import os
import re
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
FIXTURE = ROOT / "tests" / "node_board" / "gap_batch_8.x3d"
DOUBLES = ("0.1234567890123 0 0 1.0000000001 0 0 1.0000000001 1.25 0 0.1234567890123 1.25 0 "
           "2.5000000000001 0 0 2.5000000000001 1.25 0")


def _rounded(matrix, co):
    return tuple(round(v, 4) for v in matrix @ co)


def _shape_of(obj):
    """What the object draws, in world space: a mesh's faces and loose edges, a curve's spline points."""
    if obj.type == "CURVE":
        return [[_rounded(obj.matrix_world, p.co.xyz) for p in spline.points] for spline in obj.data.splines]
    mesh = obj.data
    faces = [[_rounded(obj.matrix_world, mesh.vertices[i].co) for i in p.vertices] for p in mesh.polygons]
    edges = [[_rounded(obj.matrix_world, mesh.vertices[i].co) for i in e.vertices] for e in mesh.edges if e.is_loose]
    points = [_rounded(obj.matrix_world, v.co) for v in mesh.vertices] if not faces and not edges else []
    return faces, edges, points


def _scene_shapes():
    return {o.name.split(".")[0]: _shape_of(o) for o in bpy.context.scene.objects if o.type in ("MESH", "CURVE")}


@unittest.skipUnless(HAVE_BPY, "bpy not available")
class NodeBoardBatch8Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="x3d_node_board8_")
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
    def _object(name):
        return next(o for o in bpy.context.scene.objects if o.name.split(".")[0] == name)

    @staticmethod
    def _components(root):
        return {c.get("name"): c.get("level") for c in root.iter("component")}

    def test_each_node_is_written_back(self):
        self._import()
        root = self._export()[1]
        line_sets = list(root.iter("LineSet"))
        self.assertEqual(sorted(s.get("vertexCount") for s in line_sets), ["3 2", "4"])
        self.assertEqual(list(root.iter("IndexedLineSet")), [])
        coloured = next(s for s in line_sets if s.get("vertexCount") == "4")
        self.assertEqual(len(coloured.find("Color").get("color").split()), 12)
        point_set = next(root.iter("PointSet"))
        shape = next(s for s in root.iter("Shape") if s.find("PointSet") is not None)
        props = shape.find("Appearance/PointProperties")
        self.assertIsNotNone(props, "the PointProperties is in the point shape's Appearance")
        self.assertEqual((props.get("attenuation"), props.get("pointSizeMaxValue"), props.get("pointSizeMinValue"),
                          props.get("pointSizeScaleFactor")), ("1 0.5 0", "8", "2", "4"))
        self.assertEqual(len(point_set.find("Coordinate").get("point").split()), 9)
        quads = next(root.iter("QuadSet"))
        self.assertIsNone(quads.get("index"))
        self.assertEqual(quads.get("solid"), "false")
        self.assertEqual(len(quads.find("Coordinate").get("point").split()), 24)
        self.assertEqual(len(quads.find("TextureCoordinate").get("point").split()), 16)
        indexed = next(root.iter("IndexedQuadSet"))
        self.assertEqual(indexed.get("index"), "0 1 2 3 1 4 5 2")
        self.assertIsNone(indexed.find("Coordinate"))
        self.assertEqual(indexed.find("CoordinateDouble").get("point"), DOUBLES, "the file's doubles, not float32's")
        self.assertEqual(list(root.iter("IndexedFaceSet")), [])
        self.assertEqual(self._components(root).get("CADGeometry"), "1")
        self.assertEqual(self._components(root).get("Shape"), "5")

    def test_the_written_nodes_give_back_the_same_shapes(self):
        self._import()
        before = _scene_shapes()
        self.assertEqual(len(before), 5)
        point_properties = self._object("Points").get("x3d_point_properties")
        out = self._export()[0]
        self._reimport(out)
        self.assertEqual(_scene_shapes(), before)
        self.assertEqual(json.loads(self._object("Points").get("x3d_point_properties")), json.loads(point_properties))

    def test_an_edited_curve_writes_its_own_vertex_counts(self):
        self._import()
        spline = self._object("Lines").data.splines[1]
        spline.points.add(1)
        spline.points[2].co = (3.0, -2.0, 0.0, 1.0)
        before = _scene_shapes()
        out, root = self._export()
        self.assertEqual(sorted(s.get("vertexCount") for s in root.iter("LineSet")), ["3 3", "4"])
        self._reimport(out)
        self.assertEqual(_scene_shapes(), before)

    def test_a_moved_vertex_writes_a_coordinate_from_the_mesh(self):
        self._import()
        self._object("IndexedQuads").data.vertices[0].co.y -= 0.5
        before = _scene_shapes()
        out, root = self._export()
        indexed = next(root.iter("IndexedQuadSet"))
        self.assertIsNone(indexed.find("CoordinateDouble"), "the doubles no longer match the mesh")
        self.assertIsNotNone(indexed.find("Coordinate"))
        self._reimport(out)
        self.assertEqual(_scene_shapes(), before)

    def test_a_quad_set_with_a_triangle_falls_back_to_a_face_set(self):
        for node in ("QuadSet", "IndexedQuadSet"):
            mesh = bpy.data.meshes.new(node)
            mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (2, 0, 0)], [], [(0, 1, 2, 3), (1, 4, 2)])
            mesh["x3d_geometry"] = node
            bpy.context.scene.collection.objects.link(bpy.data.objects.new(node, mesh))
        root = self._export()[1]
        self.assertEqual(list(root.iter("QuadSet")) + list(root.iter("IndexedQuadSet")), [])
        self.assertEqual(len(list(root.iter("IndexedFaceSet"))), 2)
        self.assertNotIn("CADGeometry", self._components(root))

    def test_triangulate_writes_a_quad_set_as_an_indexed_triangle_set(self):
        self._import()
        out = os.path.join(self.tmp, "tri.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False,
                                                  use_triangulate=True), {"FINISHED"})
        root = ET.parse(out).getroot()
        self.assertEqual(list(root.iter("QuadSet")) + list(root.iter("IndexedQuadSet")), [])
        self.assertEqual(len(list(root.iter("IndexedTriangleSet"))), 2)

    def test_untagged_lines_and_points_are_written_as_before(self):
        mesh = bpy.data.meshes.new("Edges")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0)], [(0, 1), (1, 2)], [])
        bpy.context.scene.collection.objects.link(bpy.data.objects.new("Edges", mesh))
        cloud = bpy.data.meshes.new("Cloud")
        cloud.from_pydata([(0, 0, 0), (1, 0, 0)], [], [])
        obj = bpy.data.objects.new("Cloud", cloud)
        obj["x3d_point_properties"] = "not json"
        bpy.context.scene.collection.objects.link(obj)
        root = self._export()[1]
        self.assertEqual(list(root.iter("LineSet")), [])
        self.assertEqual(len(list(root.iter("IndexedLineSet"))), 1)
        self.assertEqual(list(root.iter("PointProperties")), [], "a property that is not the import's record is ignored")
        self.assertEqual(self._components(root).get("Shape"), "2")

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
