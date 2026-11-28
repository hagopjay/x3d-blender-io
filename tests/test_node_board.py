# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The node board (tools/node_board.py, docs/NODE_BOARD.md) in plain Python.

The headline counts are pinned on purpose: a change to what the importer reads or the exporter writes has to change them,
and the measured file (tools/node_board_probe.py, in Blender), in the same commit. ::

    python -m unittest tests.test_node_board
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import node_board as nb   # noqa: E402

X3DUOM = Path("/home/user/x3d_mcp/src/validation/schemas/X3dUnifiedObjectModel-4.0.xml")

# PINNED. Re-measure with tools/node_board_probe.py in Blender, then tools/node_board.py --write.
PINNED = {"nodes": 260, "read_builds": 65, "read_graph": 2, "read_carries": 15, "read_structural": 15, "read_reported": 17,
          "read_none": 145, "read_unprobed": 1, "written": 119, "writable": 1, "events": 57,
          "event_wired": 57, "event_simulated": 57, "event_judged": 56, "event_played": 50}
PINNED_COMPONENTS = 36


class TheBoardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = nb.board()
        cls.summary = nb.summary(cls.data)

    def test_headline_counts_are_pinned(self):
        self.assertEqual({k: self.summary[k] for k in PINNED}, PINNED)

    def test_every_node_has_one_read_rung_and_the_rungs_add_up(self):
        s = self.summary
        self.assertEqual(sum(s[k] for k in ("read_builds", "read_graph", "read_carries", "read_structural", "read_reported",
                                            "read_none", "read_unprobed")), s["nodes"])
        self.assertEqual(sum(s["round_trip"].values()), s["nodes"])

    def test_component_subtotals_add_up_to_the_whole(self):
        comps = nb.by_component(self.data)
        self.assertEqual(len(comps), PINNED_COMPONENTS)
        self.assertEqual(sum(c["nodes"] for c in comps.values()), 260)
        self.assertEqual(sum(c["written"] for c in comps.values()), self.summary["written"])

    def test_the_event_nodes_are_the_57_of_the_behaviour_table(self):
        events = [r for r in self.data["rows"] if r["event"]]
        self.assertEqual(len(events), 57)

    def test_a_written_node_is_never_not_supported_and_an_unwritten_one_never_has_a_round_trip_class(self):
        for r in self.data["rows"]:
            if r["written"] == "observed":
                self.assertNotIn(r["class"], ("not_supported", "import_only"), r["node"])
            else:
                self.assertIn(r["class"], ("not_supported", "import_only"), r["node"])

    def test_everything_the_3_file_corpus_writes_was_also_observed(self):
        for r in self.data["rows"]:
            if r["corpus"]:
                self.assertEqual(r["written"], "observed", r["node"])

    def test_the_mapping_table_has_every_concrete_node_and_the_extras_are_the_documented_8(self):
        uom = set(self.data["uom"]["nodes"])
        mapping = set(self.data["mapping"]["nodes"])
        self.assertTrue(uom <= mapping)
        self.assertEqual(sorted(mapping - uom), ["EnvironmentLight", "FontLibrary", "GaussianSplats", "HAnimPose",
                                                 "InlineGeometry", "RenderedTexture", "Tangent", "X3D"])

    def test_the_ranking_lists_only_unwritten_nodes_best_first(self):
        gaps = nb.gaps(self.data)
        self.assertTrue(all(self.data["measured"]["nodes"][g["node"]]["written"] != "observed" for g in gaps))
        self.assertEqual([g["score"] for g in gaps], sorted((g["score"] for g in gaps), reverse=True))
        self.assertEqual(len(gaps), 260 - self.summary["written"])

    def test_the_document_is_current(self):
        self.assertFalse(nb.is_stale(), "run tools/node_board.py --write")

    def test_the_committed_node_list_is_what_the_object_model_gives(self):
        if not X3DUOM.is_file():
            self.skipTest("X3DUOM not on this machine; the committed list is what CI reads")
        fresh = nb.nodes_from_x3duom(X3DUOM)
        self.assertEqual(fresh, nb.load_nodes())

    def test_frequency_counts_are_over_the_files_the_task_names(self):
        freq = self.data["freq"]
        self.assertEqual(set(freq["repositories"]), {"x3d.demo", "x3d.loom"})
        self.assertGreater(freq["files"], 1000)
        self.assertEqual(freq["elements"]["Shape"] >= freq["files_with"]["Shape"], True)


if __name__ == "__main__":
    unittest.main()
