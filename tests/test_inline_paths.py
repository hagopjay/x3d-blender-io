# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Inline urls written from the export's own folder (round-trip audit D3). Plain Python."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parents[1] / "source"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from inline_paths import is_remote, rebase_inline_url


class InlinePathTests(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="x3d_inline_paths_"))
        (self.root / "scenes").mkdir()
        (self.root / "out" / "deeper").mkdir(parents=True)
        self.target = self.root / "scenes" / "base.x3d"
        self.target.write_text("<X3D/>")
        self.export_dir = str(self.root / "out" / "deeper")

    def test_relative_url_is_rebased_to_the_export_folder(self):
        url, warning = rebase_inline_url("base.x3d", self.export_dir, source_path=str(self.target))
        self.assertEqual(url, "../../scenes/base.x3d")
        self.assertIsNone(warning)
        self.assertTrue(os.path.isfile(os.path.join(self.export_dir, url)))

    def test_a_target_beside_the_export_keeps_its_url(self):
        (self.root / "out" / "deeper" / "base.x3d").write_text("<X3D/>")
        self.assertEqual(rebase_inline_url("base.x3d", self.export_dir), ("base.x3d", None))

    def test_fragment_and_modes(self):
        url, _ = rebase_inline_url("base.x3d#Part", self.export_dir, source_path=str(self.target))
        self.assertEqual(url, "../../scenes/base.x3d#Part")
        url, _ = rebase_inline_url("base.x3d", self.export_dir, source_path=str(self.target), path_mode="STRIP")
        self.assertEqual(url, "base.x3d")
        url, _ = rebase_inline_url("base.x3d", self.export_dir, source_path=str(self.target), path_mode="ABSOLUTE")
        self.assertEqual(url, str(self.target).replace("\\", "/"))

    def test_the_blend_folder_is_a_fallback(self):
        url, warning = rebase_inline_url("base.x3d", self.export_dir, blend_dir=str(self.root / "scenes"))
        self.assertEqual((url, warning), ("../../scenes/base.x3d", None))

    def test_a_missing_target_keeps_the_url_and_warns(self):
        url, warning = rebase_inline_url("gone.x3d", self.export_dir, source_path=str(self.root / "gone.x3d"))
        self.assertEqual(url, "gone.x3d")
        self.assertIn("gone.x3d", warning)
        self.assertIn("not found", warning)

    def test_urls_with_a_scheme_are_left_alone(self):
        for url in ("https://example.org/a.x3d", "data:model/x3d+xml,x", "file:///tmp/a.x3d"):
            self.assertTrue(is_remote(url))
            self.assertEqual(rebase_inline_url(url, self.export_dir), (url, None))
        self.assertFalse(is_remote("C:/models/a.x3d"))


if __name__ == "__main__":
    unittest.main()
