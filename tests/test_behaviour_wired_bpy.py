# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The twelve wired event nodes (docs/BEHAVIOUR_EVENT_NODES.md, P0) through Blender: imported with the graph, shown as
nodes with typed sockets, read back, and exported. Plain-Python counterpart: tests/test_behaviour_wired.py.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_behaviour_wired_bpy
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension, SOURCE_DIR

sys.path.insert(0, str(SOURCE_DIR))
WORLDS = Path(__file__).resolve().parent / "behaviour"
NAMES = ("wired-geo", "wired-pick", "wired-media", "wired-script", "wired-collision")


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class WiredNodeTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_wired_")
        _register_extension(self.tmpdir)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.scene = bpy.context.scene
        self.bn = importlib.import_module("io_scene_x3d.behaviour_nodes")
        self.bg = importlib.import_module("io_scene_x3d.behaviour_graph")
        self.bn.ensure_registered()

    def _import(self, name):
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=str(WORLDS / f"{name}.x3d"), use_behaviour_graph=True), {"FINISHED"})
        return self.scene.x3d_behaviour_tree

    def _apply(self, name):
        """The tree of a world's graph made straight from the file (``from_x3d``), with no importer: scene nodes the
        importer does not keep (Collision, AudioClip, MovieTexture) are bound by name there."""
        graph = self.bg.Behaviour.from_x3d((WORLDS / f"{name}.x3d").read_text(encoding="utf-8"))
        for node in graph.nodes.values():            # an empty object for each Transform the graph sits in or drives
            wanted = node.parent if node.role == "behaviour" else node.id if node.binding and node.binding[0] == "transform" else None
            if node.role == "target" and node.binding and node.binding[0] == "material":
                bpy.data.materials.new(node.binding[1])
            if wanted and wanted not in bpy.data.objects:
                self.scene.collection.objects.link(bpy.data.objects.new(wanted, None))
        return graph, self.bn.apply(graph, self.scene)

    def _export(self, name):
        path = os.path.join(self.tmpdir, f"{name}.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40"), {"FINISHED"})
        text = Path(path).read_text(encoding="utf-8")
        return text, ET.fromstring(text)

    def test_every_world_comes_back_from_the_tree_with_no_difference(self):
        for name in NAMES:
            with self.subTest(world=name):
                bpy.ops.wm.read_factory_settings(use_empty=True)
                self.bn.ensure_registered()
                self.scene = bpy.context.scene
                parsed, _tree = self._apply(name)
                back = self.bn.read(self.scene)
                difference = self.bg.difference(parsed, back)
                self.assertEqual({k: v for k, v in difference.items() if v}, {})
                self.assertEqual(len(back.routes), len(parsed.routes))
                self.assertEqual({n.id: n.binding for n in back.nodes.values() if n.role == "target"},
                                 {n.id: n.binding for n in parsed.nodes.values() if n.role == "target"})

    def test_an_import_with_the_graph_keeps_every_route_between_nodes_the_importer_keeps(self):
        for name in ("wired-script", "wired-pick", "wired-geo"):
            with self.subTest(world=name):
                self._import_again(name)
                parsed = self.bg.Behaviour.from_x3d((WORLDS / f"{name}.x3d").read_text(encoding="utf-8"))
                back = self.bn.read(self.scene)
                self.assertEqual({k: v for k, v in self.bg.difference(parsed, back).items() if v}, {})

    def test_a_script_shows_its_declared_fields_as_typed_sockets(self):
        tree = self._import("wired-script")
        brain = tree.nodes["Brain"]
        self.assertEqual(brain.x3d_type, "Script")
        inputs = {socket.name: socket.x3d_type for socket in brain.inputs}
        outputs = {socket.name: socket.x3d_type for socket in brain.outputs}
        self.assertEqual({k: inputs[k] for k in ("touched", "fraction", "on", "where", "things")},
                         {"touched": "SFTime", "fraction": "SFFloat", "on": "SFBool", "where": "SFVec3d", "things": "MFNode"})
        self.assertEqual({k: outputs[k] for k in ("place", "on", "names")}, {"place": "SFVec3f", "on": "SFBool", "names": "MFString"})
        for name in ("place", "names", "steps", "thing"):         # an outputOnly field has no input; initializeOnly has neither
            self.assertNotIn(name, inputs)
        for name in ("steps", "thing", "touched"):
            self.assertNotIn(name, outputs)
        self.assertIn("url", inputs)                              # the node's own fields are still there
        self.assertTrue(brain.x3d_content.startswith("<field "))

    def test_a_double_vector_is_not_a_float_vector_in_the_editor(self):
        tree = self._import("wired-geo")
        route, plotter = tree.nodes["Route"], tree.nodes["Plotter"]
        self.assertEqual(route.outputs["geovalue_changed"].x3d_type, "SFVec3d")
        self.assertEqual(plotter.inputs["where"].x3d_type, "SFVec3d")
        marker = next(n for n in tree.nodes if n.x3d_role == "target" and n.x3d_def == "Marker")
        before = len(tree.links)
        tree.links.new(route.outputs["geovalue_changed"], marker.inputs["translation"])      # SFVec3d into SFVec3f
        tree.remove_mismatched_links()
        self.assertEqual(len(tree.links), before)

    def test_node_valued_sockets_join_only_their_own_kind(self):
        tree = self._import("wired-pick")
        ray, tally = tree.nodes["Ray"], tree.nodes["Tally"]
        self.assertEqual(ray.outputs["pickedGeometry"].x3d_type, "MFNode")
        self.assertEqual(tally.inputs["picked"].x3d_type, "MFNode")
        before = len(tree.links)
        tree.links.new(ray.outputs["pickedGeometry"], tally.inputs["points"])      # MFNode into MFVec3f
        tree.remove_mismatched_links()
        self.assertEqual(len(tree.links), before)

    def test_the_scene_nodes_are_target_nodes_with_outputs(self):
        _graph, tree = self._apply("wired-collision")
        wall = tree.nodes["Wall"]
        self.assertEqual((wall.x3d_role, wall.x3d_type, wall.x3d_bone), ("target", "Collision", "Wall"))
        self.assertEqual(wall.outputs["collideTime"].x3d_type, "SFTime")
        self.assertEqual(wall.outputs["isActive"].x3d_type, "SFBool")
        self.assertEqual(len([link for link in tree.links if link.from_node == wall]), 2)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.bn.ensure_registered()
        self.scene = bpy.context.scene
        _graph, media = self._apply("wired-media")
        self.assertEqual(media.nodes["Film"].outputs["duration_changed"].x3d_type, "SFTime")
        self.assertEqual(media.nodes["Tone"].inputs["startTime"].x3d_type, "SFTime")

    def _import_again(self, name):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.bn.ensure_registered()
        self.scene = bpy.context.scene
        return self._import(name)

    def test_export_keeps_the_scripts_and_every_route_between_nodes_the_file_has(self):
        for name, written in (("wired-script", 8), ("wired-geo", 8), ("wired-pick", 10)):
            with self.subTest(world=name):
                self._import_again(name)
                text, root = self._export(name)
                original = ET.fromstring((WORLDS / f"{name}.x3d").read_text(encoding="utf-8"))
                self.assertEqual(len(list(root.iter("ROUTE"))), written)
                for script in original.iter("Script"):
                    exported = next(e for e in root.iter("Script") if e.get("DEF") == script.get("DEF"))
                    self.assertEqual([f.attrib for f in exported.findall("field")], [f.attrib for f in script.findall("field")])
                    self.assertEqual(exported.get("url"), script.get("url"))
                    # the source: every text run with a character in it, to the character (layout between fields aside)
                    self.assertEqual([t for t in exported.itertext() if t.strip()], [t for t in script.itertext() if t.strip()])

    def test_a_reference_the_file_cannot_hold_is_left_out_and_said(self):
        self._import_again("wired-pick")
        text, root = self._export("wired-pick")
        defs = {e.get("DEF") for e in root.iter() if e.get("DEF")}
        for use in {e.get("USE") for e in root.iter() if e.get("USE")}:
            self.assertIn(use, defs, f"USE {use!r} refers to nothing")
        self.assertIn("referred to 'World' by USE", text)
        ray = next(e for e in root.iter("LinePickSensor"))
        self.assertEqual([c.get("DEF") for c in ray], ["RayGeometry"])         # what the sensor defines itself stays

    def test_a_scene_node_the_file_does_not_hold_is_named_and_its_routes_counted(self):
        for name, left_out, written, named in (("wired-collision", 2, 3, "Wall"), ("wired-media", 6, 0, "Film")):
            with self.subTest(world=name):
                bpy.ops.wm.read_factory_settings(use_empty=True)
                self.bn.ensure_registered()
                self.scene = bpy.context.scene
                self._apply(name)
                text, root = self._export(name)
                self.assertEqual(len(list(root.iter("ROUTE"))), written)
                self.assertIn(f"Target '{named}'", text)
                self.assertIn(f"{left_out} ROUTE(s) left out because an end is not in the exported file; {written} written.", text)


if __name__ == "__main__":
    unittest.main()
