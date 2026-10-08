# SPDX-FileCopyrightText: 2026 OpenAI
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import tempfile
import sys
import unittest
from pathlib import Path


SOURCE_DIR = Path(__file__).resolve().parents[1] / "source"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from parse_x3d40 import _parse_mfstring_urls, parse_file


class ParseX3D40Tests(unittest.TestCase):
    def assertTupleAlmostEqual(self, left, right, places=6):
        self.assertEqual(len(left), len(right))
        for actual, expected in zip(left, right):
            self.assertAlmostEqual(actual, expected, places=places)

    def test_parse_mfstring_urls_handles_quoted_lists(self):
        urls = _parse_mfstring_urls('"scene.glb" "fallback.x3d"')
        self.assertEqual(urls, ["scene.glb", "fallback.x3d"])

    def test_parse_file_extracts_inline_assets(self):
        x3d_text = """<?xml version="1.0" encoding="UTF-8"?>
<X3D version="4.0" profile="Immersive">
  <head>
    <meta name="title" content="Inline Demo" />
  </head>
  <Scene>
    <Inline url='"scene.glb" "fallback.x3d"' />
  </Scene>
</X3D>
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "inline_demo.x3d"
            filepath.write_text(x3d_text, encoding="utf-8")
            ir_scene = parse_file(str(filepath))

        self.assertEqual(ir_scene.name, "Inline Demo")
        self.assertEqual(ir_scene.source_path, str(filepath))
        self.assertEqual([asset.url for asset in ir_scene.inline_assets], ["scene.glb", "fallback.x3d"])
        self.assertEqual([asset.asset_type for asset in ir_scene.inline_assets], ["gltf", "x3d"])

    def test_parse_file_preserves_inline_transform(self):
        x3d_text = """<?xml version="1.0" encoding="UTF-8"?>
<X3D version="4.0" profile="Immersive">
  <Scene>
    <Transform translation="1 2 3" rotation="0 1 0 0.75" scale="2 3 4">
      <Inline url='"scene.glb"' />
    </Transform>
  </Scene>
</X3D>
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "inline_transform.x3d"
            filepath.write_text(x3d_text, encoding="utf-8")
            ir_scene = parse_file(str(filepath))

        self.assertEqual(len(ir_scene.inline_assets), 1)
        inline_asset = ir_scene.inline_assets[0]
        self.assertEqual(inline_asset.transform.translation, (1.0, 2.0, 3.0))
        self.assertTupleAlmostEqual(inline_asset.transform.rotation_axis_angle, (0.0, 1.0, 0.0, 0.75))
        self.assertEqual(inline_asset.transform.scale, (2.0, 3.0, 4.0))

    def test_parse_file_composes_nested_inline_transform_chain(self):
        x3d_text = """<?xml version="1.0" encoding="UTF-8"?>
<X3D version="4.0" profile="Immersive">
  <Scene>
    <Transform translation="1 0 0">
      <Transform translation="0 2 0" scale="2 2 2">
        <Inline url='"scene.glb"' />
      </Transform>
    </Transform>
  </Scene>
</X3D>
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "inline_nested_transform.x3d"
            filepath.write_text(x3d_text, encoding="utf-8")
            ir_scene = parse_file(str(filepath))

        self.assertEqual(len(ir_scene.inline_assets), 1)
        inline_asset = ir_scene.inline_assets[0]
        self.assertEqual(inline_asset.transform.translation, (1.0, 2.0, 0.0))
        self.assertEqual(inline_asset.transform.scale, (2.0, 2.0, 2.0))

    def test_parse_file_extracts_viewpoint_and_navigation(self):
        x3d_text = """<?xml version="1.0" encoding="UTF-8"?>
<X3D version="4.0" profile="Immersive">
  <Scene>
    <NavigationInfo type='"EXAMINE" "ANY"' />
    <Transform translation="1 2 3">
      <Viewpoint description="Investor View" position="0 -7 4" orientation="1 0 0 0.75" fieldOfView="0.9" />
    </Transform>
  </Scene>
</X3D>
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "viewpoint_demo.x3d"
            filepath.write_text(x3d_text, encoding="utf-8")
            ir_scene = parse_file(str(filepath))

        self.assertEqual(ir_scene.navigation_types, ["EXAMINE", "ANY"])
        self.assertEqual(len(ir_scene.viewpoints), 1)
        viewpoint = ir_scene.viewpoints[0]
        self.assertEqual(viewpoint.description, "Investor View")
        self.assertAlmostEqual(viewpoint.field_of_view, 0.9)
        self.assertTupleAlmostEqual(viewpoint.transform.translation, (1.0, -5.0, 7.0))
        self.assertTupleAlmostEqual(viewpoint.transform.rotation_axis_angle, (1.0, 0.0, 0.0, 0.75))


if __name__ == "__main__":
    unittest.main()
