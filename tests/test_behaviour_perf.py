# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Speed of the behaviour simulator (plain Python, no bpy), and proof that making it faster did not change what it
sends. The synthetic graphs come from tools/behaviour_bench.py::

    cd tests && python -m unittest test_behaviour_perf
"""

from __future__ import annotations

import hashlib
import statistics
import sys
import time
import tempfile
import unittest
from pathlib import Path

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source"))
sys.path.insert(0, str(ROOT / "tools"))

import behaviour_bench as bench   # noqa: E402
import behaviour_sim as bs        # noqa: E402


class SameEventsTests(unittest.TestCase):

    # SHA-256 of the whole log and every change returned, for the "mixed" graph with 50 copies over 120 steps of
    # 1/60 s (tools/behaviour_bench.py: digest). Computed from the simulator as it was BEFORE the performance work
    # (commit 91d6ad3 plus the benchmark), so a faster simulator must send exactly the same events in the same order
    # with the same values.
    MIXED_50_120 = "9591869b7099e9baba1c6842fb0d8a9ba9deaafa1868a3b8752dcafc2987dfaa"
    FAN_20_120 = "60bc0d981c35cc99702264fc9a69066c9f952cf9aab40d569fa00ee66e8bff43"
    CHAINS_20_120 = "e6e53b0e53ed116bfd4d2377631719bcd4b44fc8cea49c93155376fadc055efc"   # floats rounded to 9 places (exp)

    def test_mixed_graph_sends_the_same_events_as_before(self):
        self.assertEqual(bench.digest("mixed", 50, 120), self.MIXED_50_120)

    def test_fan_sends_the_same_events_as_before(self):
        self.assertEqual(bench.digest("fan", 20, 120), self.FAN_20_120)

    def test_chains_send_the_same_events_as_before(self):
        self.assertEqual(bench.digest("chains", 20, 120, places=9), self.CHAINS_20_120)

    def test_the_digest_sees_a_difference(self):
        self.assertNotEqual(bench.digest("mixed", 50, 120), bench.digest("mixed", 50, 119))


class SpeedTests(unittest.TestCase):

    # "fan" with 1000 interpolators measured a median of 1.66 ms per step after the performance work (2.41 ms before):
    # tools/behaviour_bench.py, Intel Xeon 2.1 GHz, Python 3.13.18. The budget is about 5 times that, so a slow or busy
    # machine does not trip it but an accidentally quadratic step (every node looked at for every event) does.
    FAN_1000_BUDGET_MS = 8.0

    def test_fan_of_1000_steps_inside_its_budget(self):
        sim = bs.Simulation(bench.build("fan", 1000))
        sim.start(0.0)
        times = []
        for k in range(1, 61):
            began = time.perf_counter()
            sim.step(k * bench.DT)
            times.append(time.perf_counter() - began)
        median = statistics.median(times[10:]) * 1e3          # the middle of 50 steps, not one step
        self.assertLess(median, self.FAN_1000_BUDGET_MS, f"median {median:.2f} ms per step")

    def test_an_idle_graph_costs_next_to_nothing(self):
        sim = bs.Simulation(bench.build("mixed", 1000))       # nothing is clicked: every timer waits
        sim.start(0.0)
        began = time.perf_counter()
        for k in range(1, 31):
            sim.step(k * bench.DT)
        self.assertLess((time.perf_counter() - began) / 30 * 1e3, 10.0)


def canonical_tree_dump(tree) -> str:
    """Everything apply builds, as text: per node its class, name, label, place, stored fields (in order), bindings,
    width and colour switch, key-row count and every socket (name, class, type, enabled, hidden, link limit) in order;
    per link its two ends. Floats are rounded to 4 places."""
    lines = []
    for node in tree.nodes:
        lines.append(repr((
            node.bl_idname, node.name, node.label, round(node.location.x, 4) + 0.0, round(node.location.y, 4) + 0.0,
            getattr(node, "x3d_def", None), tuple((f.name, f.value) for f in getattr(node, "x3d_fields", ())),
            getattr(node.x3d_parent, "name", None) if hasattr(node, "x3d_parent") else None,
            getattr(node.x3d_object, "name", None) if hasattr(node, "x3d_object") else None,
            getattr(node.x3d_material, "name", None) if hasattr(node, "x3d_material") else None,
            getattr(node, "x3d_type", None), len(getattr(node, "x3d_rows", ())),
            round(node.width, 3), node.use_custom_color, tuple(round(c, 4) for c in node.color) if node.use_custom_color else None,
            tuple((s.name, s.bl_idname, s.enabled, s.hide, s.link_limit) for s in node.inputs),
            tuple((s.name, s.bl_idname, s.enabled, s.hide, s.link_limit) for s in node.outputs))))
    for link in tree.links:
        lines.append(repr((link.from_node.name, link.from_socket.name, link.to_node.name, link.to_socket.name,
                           link.is_valid, link.is_muted)))
    return "\n".join(lines)


def tree_digest(tree) -> str:
    return hashlib.sha256(canonical_tree_dump(tree).encode()).hexdigest()


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class SameTreeTests(unittest.TestCase):
    """behaviour_nodes.apply must build the same node tree it built before it was made fast. The digests were computed
    from apply as it was BEFORE the performance work (commit 8e4f4fb plus the benchmark's --tree mode)."""

    # apply of "fan" with 100 interpolators (201 nodes) measured 0.74 s after the performance work (0.83 s before; the
    # cost is inside Blender, see docs/BEHAVIOUR_GRAPH.md): tools/behaviour_bench.py --tree, bpy 5.3.0, Intel Xeon
    # 2.1 GHz, load average about 2. The budget is 5 times that, so a busy machine does not trip it.
    FAN_100_BUDGET_S = 3.7

    DOOR = "103ce95551519f301c72b9a9ebfd575c285e37430f9f4e11a21302bbc5b68902"
    PROBE = "9a9aadd3a4845e095578aa7c22e2e46a03aec7dde71dec983e700630cc7705d6"
    MIXED_20 = "37081ee4b5519d99e6c623884eb552089a4e8e54d7477f4c7116231796bf0728"

    def setUp(self):
        import importlib
        from test_roundtrip_bpy import _register_extension
        _register_extension(tempfile.mkdtemp(prefix="x3d_sametree_"))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.bn = importlib.import_module("io_scene_x3d.behaviour_nodes")
        self.bg = importlib.import_module("io_scene_x3d.behaviour_graph")
        self.bn.ensure_registered()
        self.scene = bpy.context.scene

    def _no_difference(self, graph):
        self.assertEqual(self.bg.difference(graph, self.bn.read(self.scene)),
                         {"nodes_lost": [], "nodes_added": [], "fields_changed": {}, "routes_lost": [],
                          "routes_added": []})

    def test_door_world(self):
        bpy.ops.mesh.primitive_cube_add()
        door = bpy.context.active_object
        door.name = "Door"
        b = self.bg.Behaviour()
        click = b.add("TouchSensor", "Click", parent="Door")
        timer = b.add("TimeSensor", "Timer", cycleInterval=2)
        slide = b.add("PositionInterpolator", "Slide", key=[0, 1], keyValue=[(0, 0, 0), (0, 2, 0)])
        target = self.bn.target(b, door)
        click.touchTime >> timer.startTime
        timer.fraction_changed >> slide.set_fraction
        slide.value_changed >> target.translation
        tree = self.bn.apply(b, self.scene)
        self.assertEqual(tree_digest(tree), self.DOOR, canonical_tree_dump(tree))
        self._no_difference(b)

    def test_probe_world(self):
        path = ROOT / "tests" / "behaviour" / "probe.x3d"
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=str(path), use_behaviour_graph=True), {"FINISHED"})
        tree = self.scene.x3d_behaviour_tree
        self.assertGreater(len(tree.nodes), 5)
        self.assertEqual(tree_digest(tree), self.PROBE, canonical_tree_dump(tree))
        again = self.bn.read(self.scene)
        self.bn.apply(again, self.scene)                      # a second apply onto the existing tree: same tree
        self.assertEqual(tree_digest(self.scene.x3d_behaviour_tree), self.PROBE)

    def test_mixed_20(self):
        graph = bench.build("mixed", 20)
        bench.bind_targets(bpy, self.scene, graph)
        tree = self.bn.apply(graph, self.scene)
        self.assertEqual(tree_digest(tree), self.MIXED_20, canonical_tree_dump(tree))
        self._no_difference(graph)
        self.bn.apply(graph, self.scene)
        self.assertEqual(tree_digest(self.scene.x3d_behaviour_tree), self.MIXED_20)

    def test_a_route_between_two_types_is_not_drawn_but_an_editor_link_is_removed_as_before(self):
        graph = self.bg.Behaviour()
        graph.add("TimeSensor", "Clock")
        graph.add("PositionInterpolator", "Move")
        graph.route("Clock", "fraction_changed", "Move", "set_fraction", check=False)
        graph.route("Clock", "cycleTime", "Move", "keyValue", check=False)          # SFTime into MFVec3f: wrong
        tree = self.bn.apply(graph, self.scene)
        self.assertEqual([(l.from_socket.name, l.to_socket.name) for l in tree.links],
                         [("fraction_changed", "set_fraction")])
        tree.links.new(tree.nodes["Clock"].outputs["cycleTime"], tree.nodes["Move"].inputs["keyValue"])
        self.assertEqual(len(tree.links), 1)                 # the callback is live again after apply

    def test_a_failed_apply_leaves_the_callback_and_the_sockets_working(self):
        graph = bench.build("mixed", 2)
        bench.bind_targets(bpy, self.scene, graph)
        graph.nodes["Slide0"].node_type = "NoSuchNode"
        with self.assertRaises(Exception):
            self.bn.apply(graph, self.scene)
        self.assertEqual(self.bn._SOCKETS_LATER, [])
        self.assertEqual(self.bn._BUILDING, set())
        tree = self.bn.apply(bench.build("mixed", 2), self.scene)
        self.assertGreater(len(tree.nodes["Timer0"].inputs), 3)

    def test_apply_of_a_fan_of_100_stays_inside_its_budget(self):
        graph = bench.build("fan", 100)
        bench.bind_targets(bpy, self.scene, graph)
        began = time.perf_counter()
        self.bn.apply(graph, self.scene)
        seconds = time.perf_counter() - began
        self.assertLess(seconds, self.FAN_100_BUDGET_S, f"{seconds:.2f} s")

    def test_the_dump_sees_a_difference(self):
        graph = bench.build("mixed", 3)
        bench.bind_targets(bpy, self.scene, graph)
        tree = self.bn.apply(graph, self.scene)
        before = tree_digest(tree)
        tree.nodes["Slide0"].location.x += 1
        self.assertNotEqual(tree_digest(tree), before)
        tree.nodes["Slide0"].location.x -= 1
        tree.nodes["Slide0"].inputs[0].hide = True
        self.assertNotEqual(tree_digest(tree), before)


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class PlayerFollowsEditsTests(unittest.TestCase):
    """The player remembers the object it moved, so it must notice when the user deletes or renames it mid-play."""

    def setUp(self):
        import importlib
        from test_roundtrip_bpy import _register_extension
        _register_extension(tempfile.mkdtemp(prefix="x3d_perf_"))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.bn = importlib.import_module("io_scene_x3d.behaviour_nodes")
        self.bp = importlib.import_module("io_scene_x3d.behaviour_play")
        self.bn.ensure_registered()
        self.bp.ensure_axes_properties()
        self.scene = bpy.context.scene
        self.graph = bench.build("fan", 3)
        for node in self.graph.nodes.values():
            if node.role == bench.bg.TARGET:
                self.scene.collection.objects.link(bpy.data.objects.new(node.id, None))
        self.player = self.bp.Player(self.scene, self.graph)
        self.player.start(0.0)

    def test_a_deleted_object_is_skipped_not_an_error(self):
        self.player.step(0.5)
        bpy.data.objects.remove(bpy.data.objects["Thing1"])
        self.player.step(1.0)                       # must not raise
        self.assertIn("Thing0", bpy.data.objects)

    def test_a_renamed_object_stops_following_its_old_name(self):
        self.player.step(0.5)
        bpy.data.objects["Thing1"].name = "Moved"
        before = tuple(bpy.data.objects["Moved"].matrix_basis.translation)
        self.player.step(1.0)
        self.assertEqual(tuple(bpy.data.objects["Moved"].matrix_basis.translation), before)

    def test_a_running_graph_moves_every_object(self):
        self.player.step(1.0)
        for i in range(3):
            self.assertNotEqual(tuple(bpy.data.objects[f"Thing{i}"].matrix_basis.translation), (0.0, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
