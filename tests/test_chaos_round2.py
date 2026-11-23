# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The plain-Python guards the second chaos round (2.7.3) added: file_safety and budget. No ``bpy``.

    cd tests && python -m unittest test_chaos_round2
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))

import budget  # noqa: E402
import file_safety  # noqa: E402


class FileSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="x3d_fs_")

    def test_devices_and_pipes_are_not_regular_files(self):
        self.assertTrue(file_safety.special_file_reason("/dev/zero").startswith("it is a device"))
        fifo = os.path.join(self.tmp, "pipe")
        os.mkfifo(fifo)
        self.assertIn("pipe", file_safety.special_file_reason(fifo))
        self.assertIn("folder", file_safety.special_file_reason(self.tmp))
        plain = os.path.join(self.tmp, "a.png")
        Path(plain).write_bytes(b"png")
        self.assertIsNone(file_safety.special_file_reason(plain))
        self.assertIsNone(file_safety.special_file_reason(os.path.join(self.tmp, "missing.png")))

    def test_copy_skips_dev_zero_and_copies_a_file(self):
        """The 2.7.2 re-export copied /dev/zero until a 50 GB disk was full."""
        src = os.path.join(self.tmp, "a.png")
        Path(src).write_bytes(b"x" * 10)
        reports = []
        copied = file_safety.path_reference_copy({("/dev/zero", os.path.join(self.tmp, "out", "zero.png")),
                                                  (src, os.path.join(self.tmp, "out", "a.png"))}, report=reports.append)
        self.assertEqual(copied, 1)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "out", "zero.png")))
        self.assertEqual(Path(self.tmp, "out", "a.png").read_bytes(), b"x" * 10)
        self.assertTrue(any("device" in r for r in reports), reports)

    def test_copy_stops_at_the_budget(self):
        src = os.path.join(self.tmp, "big.bin")
        Path(src).write_bytes(b"y" * 5000)
        reports = []
        copied = file_safety.path_reference_copy({(src, os.path.join(self.tmp, "big-copy.bin"))},
                                                 report=reports.append, limit=1000)
        self.assertEqual(copied, 0)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "big-copy.bin")))
        self.assertTrue(any("budget" in r for r in reports), reports)


class BudgetTests(unittest.TestCase):
    def test_counts_from_the_file(self):
        self.assertEqual(budget.count(5, "x"), 5)
        self.assertEqual(budget.count(-3, "x"), 0)
        self.assertEqual(budget.count(float("nan"), "x"), 0)
        self.assertEqual(budget.count("abc", "x"), 0)

    def test_elements_over_the_budget_are_refused(self):
        self.assertTrue(budget.within(100, "small"))
        self.assertFalse(budget.within(100000 * 100000, "ElevationGrid 100000 x 100000"))

    def test_divisions_are_clamped(self):
        self.assertEqual(budget.divisions(0, 16, "Cylinder"), 3)            # 2 pi / 0 raised ZeroDivisionError
        self.assertEqual(budget.divisions(-5, 16, "Cone"), 3)
        self.assertEqual(budget.divisions(50_000_000, 16, "Cylinder"), 1024)
        self.assertEqual(budget.divisions(float("inf"), 16, "Sphere"), 16)
        self.assertEqual(budget.divisions(24, 16, "Sphere"), 24)

    def test_thin_keys_keeps_the_ends(self):
        keys = list(range(100001))
        kept = budget.thin_keys(keys, 1000, "test")
        self.assertEqual(len(kept), 1000)
        self.assertEqual((kept[0], kept[-1]), (0, 100000))
        self.assertEqual(budget.thin_keys([1, 2, 3], 1000, "test"), [1, 2, 3])

    def test_environment_overrides(self):
        old = os.environ.get(budget.ELEMENTS_ENV)
        try:
            os.environ[budget.ELEMENTS_ENV] = "10"
            self.assertFalse(budget.within(11, "x"))
            os.environ[budget.ELEMENTS_ENV] = "junk"
            self.assertEqual(budget.element_limit(), budget.MAX_ELEMENTS)
        finally:
            if old is None:
                os.environ.pop(budget.ELEMENTS_ENV, None)
            else:
                os.environ[budget.ELEMENTS_ENV] = old


if __name__ == "__main__":
    unittest.main()
