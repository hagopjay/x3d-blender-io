# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The orrery demo (tests/behaviour/demos/orrery) in Blender without a window: a ROUTE into a TextureTransform reaches
Play (the graph binds it to the material of its Appearance), Play shows translation, rotation and scale on a Mapping node
it makes (or finds) in front of the material's Image Textures, and Stop takes it all away again.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_behaviour_demo_orrery_bpy
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension, SOURCE_DIR

sys.path.insert(0, str(SOURCE_DIR))
ORRERY = Path(__file__).resolve().parent / "behaviour" / "demos" / "orrery" / "orrery.x3d"


def _mappings(material):
    return [n for n in material.node_tree.nodes if n.type == "MAPPING"]


def _fed_by_mapping(material):
    images = [n for n in material.node_tree.nodes if n.type == "TEX_IMAGE"]
    return [bool(n.inputs["Vector"].links) and n.inputs["Vector"].links[0].from_node.type == "MAPPING" for n in images]


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class OrreryChartTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_orrery_")
        _register_extension(self.tmpdir)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.bn = importlib.import_module("io_scene_x3d.behaviour_nodes")
        self.bp = importlib.import_module("io_scene_x3d.behaviour_play")
        self.bg = importlib.import_module("io_scene_x3d.behaviour_graph")
        self.bn.ensure_registered()

    def load(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.bn.ensure_registered()
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=str(ORRERY), use_behaviour_graph=True), {"FINISHED"})
        return bpy.context.scene

    def test_the_route_into_the_texture_transform_reaches_the_graph(self):
        scene = self.load()
        graph = self.bn.read(scene)
        target = graph.nodes["ChartMap"]
        self.assertEqual((target.role, target.binding), (self.bg.TARGET, ("texture", "ChartPaint")))
        self.assertIn(("ChartSmooth", "value_changed", "ChartMap", "translation"),
                      [route.key() for route in graph.routes])
        self.assertEqual(bpy.data.materials["ChartPaint"]["x3d_def"], "ChartPaint")

    def test_play_pans_the_chart_through_a_mapping_node_and_stop_removes_it(self):
        scene = self.load()
        chart = bpy.data.materials["ChartPaint"]
        before = sorted(n.name for n in chart.node_tree.nodes)
        images = sum(n.type == "TEX_IMAGE" for n in chart.node_tree.nodes)
        self.assertGreaterEqual(images, 1)
        self.assertEqual(_mappings(chart), [])                  # the importer baked the transform into the UVs
        player = self.bp.Player(scene, flash=False)
        player.start(0.0)
        seen = []
        for step in range(1, 301):                              # 15 s: the year clock ticks the chart at 1, 4, 7 and 10 s
            player.step(step * 0.05)
            if step < 19:
                for mapping in _mappings(chart):                # X_ITE's chaser repeats a value at rest: nothing has moved yet
                    self.assertEqual(tuple(mapping.inputs["Location"].default_value), (0.0, 0.0, 0.0))
                    self.assertEqual(tuple(mapping.inputs["Scale"].default_value), (1.0, 1.0, 1.0))
            elif step >= 60 and step % 20 == 0:
                seen.append(tuple(round(v, 4) for v in _mappings(chart)[0].inputs["Location"].default_value))
        self.assertEqual(player.not_applied, [])
        self.assertEqual(len(_mappings(chart)), 1)              # one Mapping node feeds every Image Texture
        self.assertTrue(all(_fed_by_mapping(chart)))
        self.assertGreater(len({loc[0] for loc in seen}), 3)    # the chart really glides
        self.assertTrue(all(loc[2] == 0.0 for loc in seen))
        player.stop()
        self.assertEqual(sorted(n.name for n in chart.node_tree.nodes), before)
        self.assertFalse(any(_fed_by_mapping(chart)))

    def test_a_chart_that_never_moves_gets_no_mapping_node(self):
        scene = self.load()
        chart = bpy.data.materials["ChartPaint"]
        player = self.bp.Player(scene, flash=False)
        player.stop()                                           # nothing started: nothing made, nothing to undo
        self.assertEqual(_mappings(chart), [])

    def test_translation_rotation_and_scale_land_on_the_mapping_node(self):
        scene = self.load()
        chart = bpy.data.materials["ChartPaint"]
        player = self.bp.Player(scene, flash=False)
        player._apply([("ChartMap", "translation", (0.25, -0.5)), ("ChartMap", "rotation", 0.5),
                       ("ChartMap", "scale", (2.0, 3.0))])
        mapping = _mappings(chart)[0]
        self.assertEqual(tuple(round(v, 4) for v in mapping.inputs["Location"].default_value), (0.25, -0.5, 0.0))
        self.assertEqual(tuple(round(v, 4) for v in mapping.inputs["Rotation"].default_value), (0.0, 0.0, 0.5))
        self.assertEqual(tuple(round(v, 4) for v in mapping.inputs["Scale"].default_value), (2.0, 3.0, 1.0))
        player._apply([("ChartMap", "translation", (1.0, 0.0))])      # one field at a time keeps the others
        self.assertEqual(tuple(round(v, 4) for v in mapping.inputs["Scale"].default_value), (2.0, 3.0, 1.0))
        player._apply([("ChartMap", "center", (0.5, 0.5))])
        self.assertEqual(player.not_applied, ["TextureTransform.center"])
        player.stop()
        self.assertEqual(_mappings(chart), [])

    def test_a_mapping_node_that_is_already_there_is_driven_and_put_back(self):
        scene = self.load()
        chart = bpy.data.materials["ChartPaint"]
        tree = chart.node_tree
        image = next(n for n in tree.nodes if n.type == "TEX_IMAGE")
        mapping = tree.nodes.new("ShaderNodeMapping")
        mapping.inputs["Location"].default_value = (0.1, 0.2, 0.0)
        mapping.inputs["Scale"].default_value = (4.0, 4.0, 1.0)
        tree.links.new(mapping.outputs["Vector"], image.inputs["Vector"])
        count = len(tree.nodes)
        player = self.bp.Player(scene, flash=False)
        player._apply([("ChartMap", "translation", (0.7, 0.0))])        # the new Mapping change comes before the old one
        self.assertEqual(tuple(round(v, 4) for v in mapping.inputs["Location"].default_value), (2.9, 0.2, 0.0))
        self.assertEqual(tuple(round(v, 4) for v in mapping.inputs["Scale"].default_value), (4.0, 4.0, 1.0))
        self.assertIn(mapping, [n for n in tree.nodes if n.type == "MAPPING"])
        player.stop()
        self.assertEqual(len(tree.nodes), count)
        self.assertEqual(tuple(round(v, 4) for v in mapping.inputs["Location"].default_value), (0.1, 0.2, 0.0))

    SHARED = ("<?xml version='1.0'?><X3D profile='Immersive' version='4.0'><Scene>"
              "<Viewpoint position='0 0 8'/>"
              "<Transform DEF='A'><Shape><Appearance DEF='Look'><PhysicalMaterial DEF='Paint'>"
              "<PixelTexture containerField='baseTexture' image='2 2 3 0xff0000 0x00ff00 0x0000ff 0xffffff'/></PhysicalMaterial>"
              "<TextureTransform DEF='Map' translation='0.25 0' scale='2 2'/></Appearance><Box/></Shape></Transform>"
              "<Transform DEF='B' translation='3 0 0'><Shape><Appearance USE='Look'/><Sphere/></Shape></Transform>"
              "<TimeSensor DEF='Clock' loop='true' cycleInterval='2'/><PositionInterpolator2D DEF='Pan' key='0 1' keyValue='0 0 1 0'/>"
              "<ROUTE fromNode='Clock' fromField='fraction_changed' toNode='Pan' toField='set_fraction'/>"
              "<ROUTE fromNode='Pan' fromField='value_changed' toNode='Map' toField='translation'/>"
              "</Scene></X3D>")

    def load_text(self, text):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.bn.ensure_registered()
        path = os.path.join(self.tmpdir, "shared.x3d")
        Path(path).write_text(text, encoding="utf-8")
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path, use_behaviour_graph=True), {"FINISHED"})
        return bpy.context.scene

    @staticmethod
    def snapshot(material):
        tree = material.node_tree
        nodes = sorted((n.name, n.bl_idname, tuple(
            (i.name, tuple(i.default_value) if hasattr(i, "default_value") and hasattr(i.default_value, "__len__")
             else getattr(i, "default_value", None)) for i in n.inputs)) for n in tree.nodes)
        links = sorted((l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier) for l in tree.links)
        return nodes, links

    def test_the_authored_transform_is_recorded_and_the_mapping_holds_only_the_change(self):
        scene = self.load_text(self.SHARED)
        paint = bpy.data.materials["Paint"]
        self.assertEqual(json.loads(paint["x3d_texture_transform"]), {"translation": "0.25 0", "scale": "2 2"})
        player = self.bp.Player(scene, flash=False)
        player._apply([("Map", "translation", (0.25, 0.0)), ("Map", "scale", (2.0, 2.0))])   # the authored values again
        mapping = _mappings(paint)[0]
        self.assertEqual(tuple(round(v, 4) for v in mapping.inputs["Location"].default_value), (0.0, 0.0, 0.0))
        self.assertEqual(tuple(round(v, 4) for v in mapping.inputs["Scale"].default_value), (1.0, 1.0, 1.0))
        self.assertEqual(tuple(round(v, 4) for v in mapping.inputs["Rotation"].default_value), (0.0, 0.0, 0.0))
        player._apply([("Map", "translation", (0.75, 0.0))])                                   # 0.5 further along
        self.assertEqual(tuple(round(v, 4) for v in mapping.inputs["Location"].default_value), (0.5, 0.0, 0.0))
        self.assertEqual(tuple(round(v, 4) for v in mapping.inputs["Scale"].default_value), (1.0, 1.0, 1.0))
        player.stop()

    def test_stop_restores_the_material_exactly_and_a_shared_material_gets_one_mapping_node(self):
        scene = self.load_text(self.SHARED)
        paint = bpy.data.materials["Paint"]
        users = [o for o in scene.objects if o.type == "MESH" and o.active_material == paint]
        self.assertEqual(len(users), 2)                                       # one material, two objects
        before = self.snapshot(paint)
        player = self.bp.Player(scene, flash=False)
        player.start(0.0)
        for step in range(1, 61):
            player.step(step * 0.05)
        self.assertEqual(len(_mappings(paint)), 1)
        self.assertNotEqual(self.snapshot(paint), before)
        player.stop()
        self.assertEqual(self.snapshot(paint), before)

    def test_a_texture_coordinate_link_that_is_already_there_is_kept_in_front_and_put_back(self):
        scene = self.load_text(self.SHARED)
        paint = bpy.data.materials["Paint"]
        tree = paint.node_tree
        image = next(n for n in tree.nodes if n.type == "TEX_IMAGE")
        coords = tree.nodes.new("ShaderNodeTexCoord")
        tree.links.new(coords.outputs["Object"], image.inputs["Vector"])
        before = self.snapshot(paint)
        player = self.bp.Player(scene, flash=False)
        player._apply([("Map", "translation", (0.75, 0.0))])
        mapping = _mappings(paint)[0]
        self.assertEqual([(l.from_node, l.from_socket.name) for l in mapping.inputs["Vector"].links], [(coords, "Object")])
        self.assertEqual(image.inputs["Vector"].links[0].from_node, mapping)
        player.stop()
        self.assertEqual(self.snapshot(paint), before)

    def test_a_texture_transform_whose_material_has_no_def_is_named_not_guessed(self):
        graph = self.bg.parse_x3d(self.SHARED.replace("PhysicalMaterial DEF='Paint'", "PhysicalMaterial"))
        self.bg.bind(graph, lambda name, node_type: ("texture", "Paint"))
        self.assertNotIn("Map", graph.nodes)                                  # not bound to some other material
        self.assertEqual([r for r in graph.routes if r.to_id == "Map"], [])
        self.assertTrue(any("no DEF" in line and "Map" in line for line in graph.diagnostics))

    def test_what_export_does_with_the_route_is_named_not_silent(self):
        """Today the exporter (emit_x3d40.py, not part of the demo) has no DEF for a TextureTransform: the ROUTE into it
        is counted and named in the file's head, never dropped without a word. The orrery README lists it as a finding."""
        self.load()
        path = os.path.join(self.tmpdir, "orrery-out.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40"), {"FINISHED"})
        text = Path(path).read_text(encoding="utf-8")
        self.assertIn("ChartMap", text)
        self.assertIn("left out", text)
        self.assertNotIn('toNode="ChartMap"', text)


if __name__ == "__main__":
    unittest.main()
