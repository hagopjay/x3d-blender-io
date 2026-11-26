# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Speed of the behaviour simulator (plain Python, no bpy), and proof that making it faster did not change what it
sends. The synthetic graphs come from tools/behaviour_bench.py::

    cd tests && python -m unittest test_behaviour_perf
"""

from __future__ import annotations

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
