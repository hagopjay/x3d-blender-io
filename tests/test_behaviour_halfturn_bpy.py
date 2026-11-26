# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The half-turn warning reaches the Player and its sidebar listing (headless: no window, a recording stand-in for the
layout). Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_behaviour_halfturn_bpy
"""

from __future__ import annotations

import importlib
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
DEMOS = Path(__file__).resolve().parent / "behaviour" / "demos"


class _Layout:
    """Records every label put on it; any other call (a property, an operator, a row) is accepted and ignored."""

    def __init__(self, labels=None):
        self.labels = labels if labels is not None else []
        self.enabled = True

    def label(self, text="", icon="NONE", **_kw):
        self.labels.append((text, icon))

    def __getattr__(self, name):
        return lambda *a, **k: _Layout(self.labels)


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class HalfTurnPlayerTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_halfturn_")
        _register_extension(self.tmpdir)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.bn = importlib.import_module("io_scene_x3d.behaviour_nodes")
        self.bp = importlib.import_module("io_scene_x3d.behaviour_play")
        self.bn.ensure_registered()
        self.bp.ensure_axes_properties()

    def play(self, name):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.bn.ensure_registered()
        bpy.ops.import_scene.x3d(filepath=str(DEMOS / name / f"{name}.x3d"), use_behaviour_graph=True)
        return self.bp.Player(bpy.context.scene)

    def test_the_player_carries_the_warning_for_every_three_key_turn(self):
        player = self.play("gallery-05-spin-the-planet")
        self.assertEqual(sorted({w["where"] for w in player.warnings}), [f"Tum{i}" for i in range(5)])

    def test_the_corrected_copy_has_none(self):
        self.assertEqual(self.play("gallery-05-spin-the-planet-v2").warnings, [])

    def test_the_sidebar_lists_them_while_playing(self):
        player = self.play("gallery-05-spin-the-planet")
        context = type("Ctx", (), {"scene": bpy.context.scene, "space_data": None})()
        layout = _Layout()
        self.bp._running["player"] = player
        try:
            self.bp.X3D_PT_behaviour_play.draw(type("Self", (), {"layout": layout})(), context)
        finally:
            self.bp._running["player"] = None
        shown = [text for text, icon in layout.labels if text.startswith("Warning: ")]
        self.assertEqual(len(shown), 10)         # two steps of pi in each of five turns
        self.assertIn("half a turn", shown[0])


if __name__ == "__main__":
    unittest.main()
