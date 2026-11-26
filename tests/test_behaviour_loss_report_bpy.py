# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The importer's loss report and the behaviour graph agree: a ROUTE the node tree holds is not reported as lost,
a ROUTE the tree could not keep still is.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_behaviour_loss_report_bpy
"""

from __future__ import annotations

import importlib
import json
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
WORLDS = Path(__file__).resolve().parent / "behaviour"
NOT_IMPORTED = "ROUTE not imported"


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class LossReportTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_loss_report_")
        _register_extension(self.tmpdir)
        self.bn = importlib.import_module("io_scene_x3d.behaviour_nodes")

    def route_losses(self, path, graph):
        """The ROUTE entries of ``scene["x3d_import_losses"]`` after importing ``path``."""
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.bn.ensure_registered()
        bpy.ops.import_scene.x3d(filepath=str(path), use_behaviour_graph=graph)
        raw = bpy.context.scene.get("x3d_import_losses")
        return [r["node"] for r in (json.loads(raw) if raw else []) if r["kind"] == "route"]

    def variant(self, name, extra_in_shape="", extra_route=""):
        """door.x3d with one more ROUTE (and optionally a node inside the Lamp) written to the temp directory."""
        text = (WORLDS / "door.x3d").read_text()
        text = text.replace("<Sphere radius=\"0.3\" />\n      </Shape>", "<Sphere radius=\"0.3\" />\n      </Shape>" + extra_in_shape)
        text = text.replace("</Scene>", extra_route + "\n  </Scene>")
        path = Path(self.tmpdir) / name
        path.write_text(text)
        return path

    def test_door_option_off_lists_its_one_route_as_today(self):
        # measured with bpy 5.3.0: door.x3d has 3 ROUTEs, the importer keeps 2 as keyframes and lists the touch ROUTE
        self.assertEqual(self.route_losses(WORLDS / "door.x3d", False), ["Click.touchTime -> Timer.startTime"])

    def test_door_option_on_lists_no_route_the_tree_holds(self):
        self.assertEqual(self.route_losses(WORLDS / "door.x3d", True), [])
        tree = bpy.context.scene.x3d_behaviour_tree
        self.assertTrue(any(l.from_node.name == "Click" and l.to_node.name == "Timer" for l in tree.links))

    def test_route_demo_lists_no_route_either_way(self):
        # measured with bpy 5.3.0: the importer consumes all 22 ROUTEs of route-demo.x3d itself, so nothing was listed
        self.assertEqual(self.route_losses(WORLDS / "route-demo.x3d", False), [])
        self.assertEqual(self.route_losses(WORLDS / "route-demo.x3d", True), [])
        self.assertEqual(len(bpy.context.scene.x3d_behaviour_tree.links), 22)

    def test_a_route_to_a_node_that_is_not_in_the_file_is_still_listed(self):
        path = self.variant("missing.x3d", extra_route='<ROUTE fromNode="Timer" fromField="isActive" toNode="Nowhere" toField="enabled" />')
        wanted = ["Timer.isActive -> Nowhere.enabled"]
        self.assertEqual(self.route_losses(path, True), wanted)
        self.assertIn("Nowhere", bpy.context.scene.x3d_behaviour_tree["x3d_diagnostics"])
        self.assertEqual(self.route_losses(path, False), ["Click.touchTime -> Timer.startTime"] + wanted)

    def test_a_route_into_a_nested_node_blender_did_not_import_is_still_listed(self):
        path = self.variant("nested.x3d", extra_in_shape='\n      <Collision DEF="Col"><Shape><Box/></Shape></Collision>',
                            extra_route='<ROUTE fromNode="Timer" fromField="isActive" toNode="Col" toField="enabled" />')
        self.assertEqual(self.route_losses(path, True), ["Timer.isActive -> Col.enabled"])
        self.assertIn("Col", bpy.context.scene.x3d_behaviour_tree["x3d_diagnostics"])


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class StrictLogTests(unittest.TestCase):
    """The log lines and ``X3D_IMPORT_STRICT=1`` agree with the loss report: a ROUTE the graph keeps is not called lost."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_strict_log_")
        _register_extension(self.tmpdir)
        self.bn = importlib.import_module("io_scene_x3d.behaviour_nodes")

    def run_import(self, path, graph, strict=False):
        """(log lines of the importer, losses of the scene, error text or None)."""
        import logging
        import os
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.bn.ensure_registered()
        lines = []

        class Catch(logging.Handler):
            def emit(self, record):
                lines.append(record.getMessage())
        logger = logging.getLogger("import_x3d")
        handler = Catch(level=logging.WARNING)
        logger.addHandler(handler)
        saved = os.environ.get("X3D_IMPORT_STRICT")
        if strict:
            os.environ["X3D_IMPORT_STRICT"] = "1"
        else:
            os.environ.pop("X3D_IMPORT_STRICT", None)
        error = None
        try:
            bpy.ops.import_scene.x3d(filepath=str(path), use_behaviour_graph=graph)
        except RuntimeError as exc:
            error = str(exc)
        finally:
            logger.removeHandler(handler)
            if saved is None:
                os.environ.pop("X3D_IMPORT_STRICT", None)
            else:
                os.environ["X3D_IMPORT_STRICT"] = saved
        raw = bpy.context.scene.get("x3d_import_losses")
        return [l for l in lines if "X3D import loss" in l], (json.loads(raw) if raw else []), error

    @staticmethod
    def routes(lines):
        return [l for l in lines if NOT_IMPORTED in l]

    def snake_with(self, name, extra_route=""):
        text = (WORLDS / "snake.x3d").read_text().replace("</Scene>", extra_route + "\n  </Scene>")
        path = Path(self.tmpdir) / name
        path.write_text(text)
        return path

    def test_option_off_logs_and_raises_as_today(self):
        lines, losses, error = self.run_import(WORLDS / "door.x3d", False)
        self.assertEqual(self.routes(lines), ["X3D import loss: route Click.touchTime -> Timer.startTime: ROUTE not imported"])
        self.assertEqual([r["node"] for r in losses if r["kind"] == "route"], ["Click.touchTime -> Timer.startTime"])
        _, _, error = self.run_import(WORLDS / "door.x3d", False, strict=True)
        self.assertIn("X3D_IMPORT_STRICT=1", error)
        lines, losses, error = self.run_import(WORLDS / "snake.x3d", False)
        self.assertEqual(len(self.routes(lines)), 2)
        self.assertEqual(len(losses), 2)
        _, _, error = self.run_import(WORLDS / "snake.x3d", False, strict=True)
        self.assertIn("route Head.translation -> Follow1.set_destination", error)

    def test_option_on_a_kept_route_is_not_logged_listed_or_strict(self):
        lines, losses, error = self.run_import(WORLDS / "door.x3d", True)
        self.assertEqual(self.routes(lines), [])
        self.assertEqual([r for r in losses if r["kind"] == "route"], [])
        lines, losses, error = self.run_import(WORLDS / "snake.x3d", True)
        self.assertEqual((lines, losses, error), ([], [], None))
        lines, losses, error = self.run_import(WORLDS / "snake.x3d", True, strict=True)
        self.assertEqual((lines, losses, error), ([], [], None))
        self.assertTrue(any(l.from_node.name == "Head" for l in bpy.context.scene.x3d_behaviour_tree.links))

    def test_option_on_strict_names_a_route_the_graph_cannot_keep(self):
        path = self.snake_with("lost.x3d", '<ROUTE fromNode="Seg1" fromField="translation" toNode="Nowhere" toField="set_destination" />')
        lines, losses, error = self.run_import(path, True)
        self.assertEqual(self.routes(lines), ["X3D import loss: route Seg1.translation -> Nowhere.set_destination: ROUTE not imported"])
        self.assertEqual([r["node"] for r in losses], ["Seg1.translation -> Nowhere.set_destination"])
        _, _, error = self.run_import(path, True, strict=True)
        self.assertIn("route Seg1.translation -> Nowhere.set_destination", error)
        self.assertNotIn("Follow1", error)

    def test_non_route_losses_do_not_depend_on_the_option(self):
        def others(path, graph, strict=False):
            lines, losses, error = self.run_import(path, graph, strict)
            return ([l for l in lines if NOT_IMPORTED not in l],
                    sorted(json.dumps(r, sort_keys=True) for r in losses if r["kind"] != "route"),
                    error is not None)
        for world in ("door.x3d", "probe-proximity.x3d", "counter.x3d"):
            for strict in (False, True):
                off, on = others(WORLDS / world, False, strict), others(WORLDS / world, True, strict)
                self.assertTrue(off[1], world)
                self.assertEqual(off, on, world)
        self.assertTrue(others(WORLDS / "door.x3d", True, True)[2])      # the TouchSensor and timer are lost either way


if __name__ == "__main__":
    unittest.main()
