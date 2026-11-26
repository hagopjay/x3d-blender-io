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
        for step in range(1, 301):                              # 15 s: the year clock ticks the chart at 2, 6, 10 and 14 s
            player.step(step * 0.05)
            if step < 40:
                self.assertEqual(_mappings(chart), [])          # nothing has moved yet: nothing is made
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
        player._apply([("ChartMap", "translation", (0.7, 0.0))])
        self.assertEqual(tuple(round(v, 4) for v in mapping.inputs["Location"].default_value), (0.7, 0.0, 0.0))
        self.assertEqual(tuple(round(v, 4) for v in mapping.inputs["Scale"].default_value), (4.0, 4.0, 1.0))
        self.assertIn(mapping, [n for n in tree.nodes if n.type == "MAPPING"])
        player.stop()
        self.assertEqual(len(tree.nodes), count)
        self.assertEqual(tuple(round(v, 4) for v in mapping.inputs["Location"].default_value), (0.1, 0.2, 0.0))

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
