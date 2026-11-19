# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The exported file's extension follows the compression option instead of being appended to the one given.

The export dialog's filename ends in ".x3d" (the operator's filename_ext), and the pipeline appended ".x3dz" for a
compressed export, so the file came out as "scene.x3d.x3dz"; "scene.x3dz" exported uncompressed became
"scene.x3dz.x3d". A trailing .x3d or .x3dz is now replaced by the one the option asks for.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_export_file_extension_bpy
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension, SOURCE_DIR

GZIP_MAGIC = b"\x1f\x8b"


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ExportFileExtensionTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_extension_")
        _register_extension(self.tmpdir)
        sys.path.insert(0, str(SOURCE_DIR))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmpdir)
        bpy.ops.mesh.primitive_cube_add()

    def _written(self, given, version, compress):
        folder = tempfile.mkdtemp(dir=self.tmpdir)
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=os.path.join(folder, given), x3d_version=version,
                                                  use_selection=False, use_compress=compress), {"FINISHED"})
        names = sorted(os.listdir(folder))
        self.assertEqual(len(names), 1, names)
        with open(os.path.join(folder, names[0]), "rb") as handle:
            self.assertEqual(handle.read(2) == GZIP_MAGIC, compress)
        return names[0]

    def test_extension_follows_the_compression_option(self):
        cases = [("scene.x3d", True, "scene.x3dz"), ("scene.X3D", True, "scene.x3dz"),
                 ("scene.x3dz", True, "scene.x3dz"), ("scene", True, "scene.x3dz"),
                 ("scene.x3dz", False, "scene.x3d"), ("scene.x3d", False, "scene.x3d"),
                 ("scene", False, "scene.x3d"), ("my.scene.v2.x3d", True, "my.scene.v2.x3dz")]
        for version in ("X3D40", "X3D33"):
            for given, compress, want in cases:
                with self.subTest(version=version, given=given, compress=compress):
                    self.assertEqual(self._written(given, version, compress), want)


if __name__ == "__main__":
    unittest.main()
