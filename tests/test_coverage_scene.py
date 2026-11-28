# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""docs/coverage/node-board.x3d, the coverage observatory, is generated from the node board (tools/coverage_scene.py):
it must be current, hold every X3DUOM 4.0 node once with the rung the board measured, and count what the board counts.
No Blender needed::

    cd tests && python -m unittest test_coverage_scene
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCENE = ROOT / "docs" / "coverage" / "node-board.x3d"


class CoverageSceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ET.parse(SCENE).getroot()
        cls.anchors = [a.get("description") for a in cls.root.iter("Anchor")]
        board = json.loads((ROOT / "tools" / "node_board_measured.json").read_text(encoding="utf-8"))["nodes"]
        cls.board = board if isinstance(board, dict) else {r["node"]: r for r in board}

    def test_the_committed_scene_is_current(self):
        result = subprocess.run([sys.executable, str(ROOT / "tools" / "coverage_scene.py"), "--check"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + " (run python3 tools/coverage_scene.py)")

    def test_every_node_is_a_column_once(self):
        names = [d.split(" · ")[0] for d in self.anchors if "not in X3DUOM 4.0" not in d]
        self.assertEqual(sorted(names), sorted(self.board), "one column per X3DUOM 4.0 node, no more")

    def test_each_column_says_what_the_board_measured(self):
        written = 0
        for desc in self.anchors:
            if "not in X3DUOM 4.0" in desc:
                continue
            name = desc.split(" · ")[0]
            row = self.board[name]
            says_written = "written by the X3D 4.0 export" in desc
            read = row.get("read", "none")
            label = {"builds": "builds Blender data", "graph": "behaviour graph", "carries": "kept as written (carry)",
                     "structural": "structural (children read)", "reported": "reported, not read",
                     "unprobed": "not probed", "none": "not read"}[read]
            self.assertIn(f"read: {label} ·", desc, name)
            self.assertEqual(says_written, row["written"] == "observed", name)
            written += says_written
        core = " ".join(t.get("string", "") for t in self.root.iter("Text"))
        self.assertIn(f'"{written} of {len(self.board)}"', core, "the core shows the board's written count")

    def test_each_rung_has_its_own_look(self):
        # the column's Appearance is the rung's (R_<rung>, DEF'd once and USE'd after): its colour is the board's rung
        for anchor in self.root.iter("Anchor"):
            desc = anchor.get("description")
            if "not in X3DUOM 4.0" in desc:
                continue
            app = next(anchor.iter("Appearance"))
            look = app.get("DEF") or app.get("USE")
            rung = self.board[desc.split(" · ")[0]].get("read", "none")
            self.assertEqual(look, f"R_{rung}", desc.split(" · ")[0])

    def test_a_written_node_has_a_cap_and_the_others_do_not(self):
        caps = 0
        for anchor in self.root.iter("Anchor"):
            if "not in X3DUOM 4.0" in anchor.get("description"):
                continue
            boxes = [t for t in anchor.iter("Transform")]
            caps += len(boxes) == 2
            self.assertEqual(len(boxes) == 2, "written by the X3D 4.0 export" in anchor.get("description"),
                             anchor.get("description").split(" · ")[0])
        self.assertEqual(caps, sum(1 for r in self.board.values() if r["written"] == "observed"))

    def test_every_column_links_to_its_tooltip(self):
        for anchor in self.root.iter("Anchor"):
            name = anchor.get("description").split(" · ")[0]
            self.assertEqual(anchor.get("url"), f'"https://www.web3d.org/x3d/content/X3dTooltips.html#{name}"')


if __name__ == "__main__":
    unittest.main()
