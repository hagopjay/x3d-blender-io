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
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
