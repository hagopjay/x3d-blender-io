# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The event-node coverage table (tools/behaviour_coverage.py, docs/BEHAVIOUR_EVENT_NODES.md) in plain Python.

The summary counts are pinned here on purpose: any change to what is wired, simulated, judged or played must change this
file in the same commit, so the numbers in the document cannot drift from the code. ::

    python -m unittest tests.test_behaviour_coverage
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import behaviour_coverage as cov   # noqa: E402

X3DUOM = Path("/home/user/x3d.chess/vendor/x3d_mcp/src/validation/schemas/X3dUnifiedObjectModel-4.0.xml")

# PINNED. Change these, and the document's table (tools/behaviour_coverage.py --write), together with the code.
PINNED = {"nodes": 57, "wired": 57, "simulated": 45, "judged": 43, "played": 44}


class TheFiftySevenTests(unittest.TestCase):

    def test_there_are_57_in_the_components_the_document_states(self):
        data = cov.load_event_nodes()
        self.assertEqual(len(data["nodes"]), 57)
        counts = {}
        for row in data["nodes"]:
            counts[row["component"]] = counts.get(row["component"], 0) + 1
        self.assertEqual(counts, cov.EXPECTED_COUNTS)
        self.assertEqual(sum(cov.EXPECTED_COUNTS.values()), 57)

    def test_the_document_table_says_the_same_counts(self):
        text = (ROOT / "docs" / "BEHAVIOUR_EVENT_NODES.md").read_text(encoding="utf-8")
        for component, count in cov.EXPECTED_COUNTS.items():
            row = [line for line in text.splitlines() if line.startswith("| ") and line.rstrip().endswith(f"| {count} |")]
            self.assertTrue(row, f"no row of the document's table ends in {count} for {component}")

    def test_a_wrong_object_model_fails_loudly(self):
        data = cov.load_event_nodes()
        broken = dict(data, nodes=data["nodes"][:-1])
        with self.assertRaises(ValueError):
            cov._checked(broken)
        moved = json.loads(json.dumps(data))
        moved["nodes"][0]["component"] = "Time"
        with self.assertRaises(ValueError):
            cov._checked(moved)

    def test_the_committed_list_is_what_the_object_model_gives(self):
        if not X3DUOM.is_file():
            self.skipTest("X3DUOM not on this machine; the committed list is what CI reads")
        fresh = cov.event_nodes_from_x3duom(X3DUOM)
        self.assertEqual(fresh, cov.load_event_nodes())

    def test_every_class_names_one_of_the_57(self):
        names = {row["name"] for row in cov.load_event_nodes()["nodes"]}
        self.assertLessEqual(set(cov.CLASSES), names)
        self.assertLessEqual(set(cov.CLASSES.values()), {"A", "B", "C", "D", "E", "B+C"})
        self.assertEqual(len(cov.CLASSES), 19)       # A 4, B 7 (Geo sensors counted in B+C: 2), C 1, D 3, E 2


class TheTableTests(unittest.TestCase):

    def test_the_document_is_not_stale(self):
        self.assertFalse(cov.is_stale(), "run: python tools/behaviour_coverage.py --write docs/BEHAVIOUR_EVENT_NODES.md")

    def test_the_summary_counts_are_pinned(self):
        self.assertEqual(cov.coverage()["summary"], PINNED)

    def test_a_node_that_is_played_is_simulated_and_judged_nodes_are_simulated(self):
        for row in cov.coverage()["rows"]:
            with self.subTest(node=row["node"]):
                if row["played"] or row["judged"]:
                    self.assertTrue(row["simulated"])
                if row["judged"]:
                    self.assertTrue(row["probes"])

    def test_every_simulated_node_is_in_the_played_table_or_the_not_played_table(self):
        import behaviour_sim as bs
        for name in bs.SIMULATED:
            with self.subTest(node=name):
                self.assertTrue((name in cov.PLAYED) != (name in cov.NOT_PLAYED), f"{name} must be in exactly one of "
                                "PLAYED and NOT_PLAYED (tools/behaviour_coverage.py)")
        self.assertLessEqual(cov.PLAYED, set(bs.SIMULATED))

    def test_what_the_player_feeds_is_still_in_its_source(self):
        source = (ROOT / "source" / "behaviour_play.py").read_text(encoding="utf-8")
        for what, text in cov.PLAYER_FEEDS.items():
            self.assertIn(text, source, f"the Player no longer feeds {what}: update PLAYED in tools/behaviour_coverage.py")

    def test_the_judged_rule_is_the_one_the_simulator_test_states(self):
        # the seven named worlds and the demos that test uses are among the worlds this tool reads
        labels = {label for label, _graph in cov.recorded_worlds()}
        for name in ("probe", "snake", "probe-spline", "probe-drag", "probe-proximity", "probe-timer", "probe-coord"):
            self.assertIn(f"{name}.x3d", labels)
        self.assertIn("demos/hello-switch", labels)

    def test_markdown_replaces_only_between_the_markers(self):
        text = (ROOT / "docs" / "BEHAVIOUR_EVENT_NODES.md").read_text(encoding="utf-8")
        again = cov.written(text, "X\n")
        self.assertTrue(again.startswith(text[:text.index(cov.BEGIN)]))
        self.assertIn(cov.END, again)
        self.assertEqual(cov.written(again, cov.markdown()), text)


if __name__ == "__main__":
    unittest.main()
