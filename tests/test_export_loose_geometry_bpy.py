# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Loose edges next to faces, and meshes of vertices only, are exported.

The exporter wrote a mesh's faces, or (for a mesh with no faces) its edges, and nothing else: an edge no face uses
on a mesh that has faces was dropped, and a mesh of only vertices (a point cloud kept as a mesh) exported as an empty
Transform. Loose edges now become an IndexedLineSet beside the faces, and a vertices-only mesh a PointSet. Stray
vertices beside faces or edges stay unwritten, as the conformance suite's Z01.loose.geometry case requires (they must
not inflate the object's bounds).

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_export_loose_geometry_bpy
"""

from __future__ import annotations

import math
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension, SOURCE_DIR

FACE = [(0, 0, 0), (1, 0, 0), (1, 1, 0)]
EDGE = [(3, 0, 0), (4, 0, 1), (5, 1, 1)]
POINTS = [(7, 7, 7), (-2, 5, 1)]


def _object(name, vertices, edges, faces):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, edges, faces)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _points_in_scene():
    """World positions of every vertex of every imported mesh and curve point."""
    bpy.context.view_layer.update()
    found = []
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            found.extend(tuple(obj.matrix_world @ v.co) for v in obj.data.vertices)
        elif obj.type == "CURVE":
            for spline in obj.data.splines:
                found.extend(tuple(obj.matrix_world @ p.co.xyz) for p in list(spline.points) + list(spline.bezier_points))
    return found


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ExportLooseGeometryTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_loose_")
        _register_extension(self.tmpdir)
        sys.path.insert(0, str(SOURCE_DIR))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmpdir)

    def _export(self, name):
        from validate import validate_xml_file, validate_with_x3d_py
        path = os.path.join(self.tmpdir, name + ".x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False), {"FINISHED"})
        result = validate_xml_file(path)
        self.assertTrue(result.valid, result.errors)
        semantic = validate_with_x3d_py(path)
        if semantic is not None:
            self.assertEqual(semantic.errors, [])
        return path, ET.parse(path).getroot()

    def _geometry_tags(self, root, name):
        transform = root.find(f".//Transform[@DEF='OB_{name}']")
        return sorted(child.tag for shape in transform.findall("Shape") for child in shape if child.tag != "Appearance")

    def _round_trip(self, path, want):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmpdir)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
        got = _points_in_scene()
        for point in want:
            # the exporter writes Y-up; the import turns it back
            nearest = min((math.dist(point, other) for other in got), default=math.inf)
            self.assertLess(nearest, 1e-4, f"{point} is missing after the round trip")

    def test_faces_with_loose_edges(self):
        _object("Mixed", FACE + EDGE + POINTS, [(3, 4), (4, 5)], [(0, 1, 2)])
        path, root = self._export("mixed")
        self.assertEqual(self._geometry_tags(root, "Mixed"), ["IndexedFaceSet", "IndexedLineSet"])
        line = root.find(".//Transform[@DEF='OB_Mixed']//IndexedLineSet")
        self.assertEqual(len(line.find("Coordinate").attrib["point"].split()), 9)
        self._round_trip(path, FACE + EDGE)

    def test_stray_vertices_are_not_written(self):
        """Suite case Z01.loose.geometry: stray vertices beside faces or edges must not inflate the bounds."""
        _object("Stray", FACE + POINTS, [], [(0, 1, 2)])
        _object("WireStray", EDGE + POINTS[:1], [(0, 1), (1, 2)], [])
        _path, root = self._export("stray")
        self.assertEqual(self._geometry_tags(root, "Stray"), ["IndexedFaceSet"])
        self.assertEqual(self._geometry_tags(root, "WireStray"), ["IndexedLineSet"])
        self.assertIsNone(root.find(".//PointSet"))

    def test_vertices_only(self):
        _object("Cloud", POINTS + [(0.5, 0.25, 0.125)], [], [])
        path, root = self._export("cloud")
        self.assertEqual(self._geometry_tags(root, "Cloud"), ["PointSet"])
        self._round_trip(path, POINTS + [(0.5, 0.25, 0.125)])

    def test_point_colours_are_kept(self):
        obj = _object("Dots", POINTS, [], [])
        colours = obj.data.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
        colours.data[0].color = (1, 0, 0, 1)
        colours.data[1].color = (0, 0, 1, 1)
        _path, root = self._export("dots")
        colour = root.find(".//Transform[@DEF='OB_Dots']//PointSet/Color")
        self.assertIsNotNone(colour)
        self.assertEqual([float(v) for v in colour.attrib["color"].split()], [1, 0, 0, 0, 0, 1])

    def test_closed_mesh_is_unchanged(self):
        """Edges that belong to faces are not loose: a cube is still one IndexedFaceSet."""
        bpy.ops.mesh.primitive_cube_add()
        bpy.context.active_object.name = "Box"
        bpy.context.active_object.data.name = "BoxMesh"   # not the importer's primitive name, so it stays a mesh
        _path, root = self._export("box")
        self.assertEqual(self._geometry_tags(root, "Box"), ["IndexedFaceSet"])


if __name__ == "__main__":
    unittest.main()
