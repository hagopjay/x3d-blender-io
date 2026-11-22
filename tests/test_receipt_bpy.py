# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Loss receipt v1 through the real X3D 4.0 export: the head line, the sidecar, stability and the chain (needs ``bpy``).

    python .github/scripts/run_tests_in_blender.py -- test_receipt_bpy
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "source"
META = "x3d-blender-io.receipt"


def _register_extension(tmpdir: str):
    package_dir = Path(tmpdir) / "io_scene_x3d"
    if not package_dir.exists():
        try:
            package_dir.symlink_to(SOURCE_DIR, target_is_directory=True)
        except OSError:
            import shutil
            shutil.copytree(SOURCE_DIR, package_dir)
    if tmpdir not in sys.path:
        sys.path.insert(0, tmpdir)
    import importlib
    module = importlib.import_module("io_scene_x3d")
    try:
        module.register()
    except Exception:
        pass


def _head(path):
    root = ET.parse(path).getroot()
    return [(m.get("name"), m.get("content")) for m in root.iter("meta")]


def _scene():
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    mesh = bpy.data.meshes.new("M")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    obj = bpy.data.objects.new("Plane", mesh)
    bpy.context.scene.collection.objects.link(obj)
    spot = bpy.data.lights.new("Spot", "SPOT")
    spot.energy = 10.0
    spot.spot_blend = 0.5
    lamp = bpy.data.objects.new("Spot", spot)
    lamp.location = (0, 0, 3)
    bpy.context.scene.collection.objects.link(lamp)


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ReceiptThroughTheExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="x3d_receipt_")
        _register_extension(self.tmp)
        os.environ.pop("BLENDER_X3D_RECEIPT", None)

    def _export(self, name, **kw):
        import bpy

        path = os.path.join(self.tmp, name)
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False, **kw),
                         {"FINISHED"})
        return path

    def test_sidecar_lists_the_clamp_and_the_cone_and_matches_the_head_line(self):
        _scene()
        path = self._export("spot.x3d", use_receipt=True)
        doc = json.loads(Path(path + ".receipt.json").read_text())
        self.assertEqual(doc["schema"], "x3d-blender-io.loss-receipt/1")
        rows = {(e["kind"], e["row"]) for e in doc["entries"]}
        self.assertIn(("clamped", "light.spot:energy"), rows)
        self.assertIn(("dropped", "light.spot:spot_blend"), rows)
        self.assertIn(("approximated", "light.spot:spot_size"), rows)
        head = dict(_head(path))
        self.assertEqual(head[META], doc["line"])
        data = Path(path).read_bytes()
        self.assertEqual(doc["subject"]["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(doc["tools"]["blender"], bpy.app.version_string)

    def test_no_sidecar_unless_asked_but_the_line_is_always_there(self):
        _scene()
        path = self._export("plain.x3d")
        self.assertFalse(Path(path + ".receipt.json").exists())
        self.assertIn(META, dict(_head(path)))

    def test_environment_variable_asks_for_the_sidecar(self):
        _scene()
        os.environ["BLENDER_X3D_RECEIPT"] = "1"
        try:
            path = self._export("env.x3d")
        finally:
            os.environ.pop("BLENDER_X3D_RECEIPT", None)
        self.assertTrue(Path(path + ".receipt.json").exists())

    def test_the_line_is_stable_across_exports(self):
        _scene()
        a = dict(_head(self._export("a.x3d")))[META]
        b = dict(_head(self._export("b.x3d")))[META]
        self.assertEqual(a, b)

    def test_a_reimport_chains_the_receipt_and_writes_one_line(self):
        import bpy

        _scene()
        first = self._export("first.x3d")
        line = dict(_head(first))[META]
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=first), {"FINISHED"})
        second = self._export("second.x3d", use_receipt=True)
        self.assertEqual([name for name, _ in _head(second)].count(META), 1)
        doc = json.loads(Path(second + ".receipt.json").read_text())
        self.assertEqual(doc["prev"], line)
        # the imported light keeps its file intensity, so the second hop clamps nothing
        self.assertNotIn("light.spot:energy", [e["row"] for e in doc["entries"]])

    def test_the_legacy_writer_writes_no_receipt(self):
        import bpy

        _scene()
        path = os.path.join(self.tmp, "legacy.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D33", use_selection=False,
                                                  use_receipt=True), {"FINISHED"})
        self.assertNotIn(META, dict(_head(path)))
        self.assertFalse(Path(path + ".receipt.json").exists())


if __name__ == "__main__":
    unittest.main()
