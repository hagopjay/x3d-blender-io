# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Geometry Nodes instances (Instance on Points and the like) are written when modifiers are applied.

An object whose Geometry Nodes output is instances (a scatter) evaluates to a mesh with no faces: the instances live
in the depsgraph, not in the object's mesh. The exporter wrote an empty Transform and nothing else. Each instance is
now a child Transform of its object, and the instanced geometry is written once and USE'd by the others.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_export_geometry_node_instances_bpy
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


def _scatter(realize=False):
    """A cube at (1, 2, 3) whose 8 corners each get a small ico sphere, rotated and scaled per instance."""
    bpy.ops.mesh.primitive_cube_add(location=(1, 2, 3))
    host = bpy.context.active_object
    host.name = "Host"
    tree = bpy.data.node_groups.new("Scatter", "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes, links = tree.nodes, tree.links
    group_in, group_out = nodes.new("NodeGroupInput"), nodes.new("NodeGroupOutput")
    points = nodes.new("GeometryNodeMeshToPoints")
    sphere = nodes.new("GeometryNodeMeshIcoSphere")
    sphere.inputs["Radius"].default_value = 0.2
    place = nodes.new("GeometryNodeInstanceOnPoints")
    place.inputs["Rotation"].default_value = (0.3, 0.6, 0.9)
    place.inputs["Scale"].default_value = (1.0, 2.0, 0.5)
    material = bpy.data.materials.new("Pebble")
    paint = nodes.new("GeometryNodeSetMaterial")
    paint.inputs["Material"].default_value = material
    links.new(group_in.outputs[0], points.inputs["Mesh"])
    links.new(sphere.outputs[0], paint.inputs["Geometry"])
    links.new(points.outputs[0], place.inputs["Points"])
    links.new(paint.outputs[0], place.inputs["Instance"])
    last = place.outputs[0]
    if realize:
        realize_node = nodes.new("GeometryNodeRealizeInstances")
        links.new(last, realize_node.inputs[0])
        last = realize_node.outputs[0]
    links.new(last, group_out.inputs[0])
    host.modifiers.new("Scatter", "NODES").node_group = tree
    return host


def _world_points():
    depsgraph = bpy.context.evaluated_depsgraph_get()
    points = []
    for instance in depsgraph.object_instances:
        if instance.object.type == "MESH":
            matrix = instance.matrix_world.copy()
            points.extend(tuple(matrix @ vertex.co) for vertex in instance.object.data.vertices)
    return points


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ExportGeometryNodeInstancesTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_gn_instances_")
        _register_extension(self.tmpdir)
        sys.path.insert(0, str(SOURCE_DIR))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmpdir)

    def _export(self, name, **options):
        from validate import validate_xml_file
        path = os.path.join(self.tmpdir, name + ".x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False, **options),
                         {"FINISHED"})
        result = validate_xml_file(path)
        self.assertTrue(result.valid, result.errors)
        return path, ET.parse(path).getroot()

    def test_instances_are_written_once_and_used(self):
        _scatter()
        _path, root = self._export("scatter", use_mesh_modifiers=True)
        host = root.find(".//Transform[@DEF='OB_Host']")
        children = host.findall("Transform")
        self.assertEqual(len(children), 8)
        geometry = [node for node in root.iter("IndexedFaceSet")]
        self.assertEqual(sum(1 for node in geometry if "DEF" in node.attrib), 1, "the sphere is written once")
        self.assertEqual(sum(1 for node in geometry if "USE" in node.attrib), 7)
        materials = {node.attrib.get("DEF") for node in root.iter("PhysicalMaterial")} | \
                    {node.attrib.get("DEF") for node in root.iter("Material")}
        self.assertIn("MA_Pebble", materials)

    def test_instances_round_trip_to_the_same_world_positions(self):
        _scatter()
        want = _world_points()
        self.assertEqual(len(want), 8 * 12)
        for hierarchy in (True, False):
            with self.subTest(use_hierarchy=hierarchy):
                bpy.ops.wm.read_factory_settings(use_empty=True)
                _register_extension(self.tmpdir)
                _scatter()
                path, _root = self._export(f"scatter_{hierarchy}", use_mesh_modifiers=True, use_hierarchy=hierarchy)
                bpy.ops.wm.read_factory_settings(use_empty=True)
                _register_extension(self.tmpdir)
                self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
                got = _world_points()
                self.assertEqual(len(got), len(want))
                for point in want:
                    nearest = min(math.dist(point, other) for other in got)
                    self.assertLess(nearest, 1e-4, f"instance vertex {point} is {nearest:.4f} from any imported one")

    def test_without_modifiers_the_host_mesh_is_written(self):
        _scatter()
        _path, root = self._export("unmodified", use_mesh_modifiers=False)
        host = root.find(".//Transform[@DEF='OB_Host']")
        self.assertEqual(host.findall("Transform"), [])
        self.assertEqual(len(host.findall("Shape")), 1)

    def test_realized_instances_stay_one_mesh(self):
        _scatter(realize=True)
        _path, root = self._export("realized", use_mesh_modifiers=True)
        host = root.find(".//Transform[@DEF='OB_Host']")
        self.assertEqual(host.findall("Transform"), [])
        coordinate = host.find("Shape/IndexedFaceSet/Coordinate")
        self.assertEqual(len(coordinate.attrib["point"].split()), 8 * 12 * 3)


if __name__ == "__main__":
    unittest.main()
