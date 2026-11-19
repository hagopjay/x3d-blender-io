# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A failed export never damages the file it would replace, on every writer, and a symlinked target stays a link.

* The X3D 3.0/3.3 writer streamed straight into the target: an error half way (disk full, a bug, Ctrl-C) left a
  truncated document where the previous one was. It now stages and publishes like the 4.0 writer.
* The 4.0 writer's ``os.replace`` swapped a symlinked target for a regular file, so the file the link pointed to was
  never updated (and the 3.3 writer, which wrote through the link, behaved differently). Both now write through.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_export_publish_bpy
"""

from __future__ import annotations

import errno
import importlib
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

PREVIOUS = b'<?xml version="1.0" encoding="UTF-8"?>\n<X3D version="4.0"><Scene/></X3D>\n'
VERSIONS = ("X3D40", "X3D33")


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ExportPublishTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_publish_")
        _register_extension(self.tmpdir)
        sys.path.insert(0, str(SOURCE_DIR))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_cube_add()

    def _previous(self, name):
        path = os.path.join(self.tmpdir, name)
        with open(path, "wb") as handle:
            handle.write(PREVIOUS)
        return path

    def _read(self, path):
        with open(path, "rb") as handle:
            return handle.read()

    def _stage_folders(self, folder=None):
        """Scratch left behind by either writer: the 4.0 stage folder or the 3.x temporary file."""
        return [n for n in os.listdir(folder or self.tmpdir) if n.startswith(".x3d-stage-") or n.endswith(".x3d-partial")]

    def _fail_mid_write(self, version):
        """Patch the writer of ``version`` so it writes a partial document and then fails like a full disk."""
        exporter = importlib.import_module("io_scene_x3d.export_x3d")
        emitter = importlib.import_module("io_scene_x3d.emit_x3d40")
        module, name = (emitter, "export_ir_scene") if version == "X3D40" else (exporter, "export")
        original = getattr(module, name)

        def partial(file, *args, **kwargs):
            file.write('<?xml version="1.0"?>\n<X3D version="3.3"><Scene><Transform')
            raise OSError(errno.ENOSPC, "No space left on device (injected)")

        setattr(module, name, partial)
        self.addCleanup(setattr, module, name, original)

    def test_interrupted_write_keeps_the_previous_file(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                path = self._previous(f"keep_{version}.x3d")
                self._fail_mid_write(version)
                with self.assertRaises(Exception):
                    bpy.ops.export_scene.x3d(filepath=path, x3d_version=version, use_selection=False)
                self.doCleanups()
                self.assertEqual(self._read(path), PREVIOUS)
                self.assertEqual(self._stage_folders(), [])

    def test_interrupted_compressed_write_keeps_the_previous_file(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                path = self._previous(f"keep_{version}.x3dz")
                self._fail_mid_write(version)
                with self.assertRaises(Exception):
                    bpy.ops.export_scene.x3d(filepath=path, x3d_version=version, use_selection=False,
                                             use_compress=True)
                self.doCleanups()
                self.assertEqual(self._read(path), PREVIOUS)
                self.assertEqual(self._stage_folders(), [])

    def test_successful_legacy_export_replaces_the_file_and_leaves_no_stage(self):
        path = self._previous("replace.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D33", use_selection=False),
                         {"FINISHED"})
        self.assertIn(b"<X3D", self._read(path))
        self.assertNotEqual(self._read(path), PREVIOUS)
        self.assertEqual(self._stage_folders(), [])

    @unittest.skipUnless(hasattr(os, "symlink") and os.name != "nt", "symlinks need a POSIX file system")
    def test_symlinked_target_stays_a_link_and_its_file_is_updated(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                real_dir = os.path.join(self.tmpdir, f"real_{version}")
                os.makedirs(real_dir)
                real = os.path.join(real_dir, "scene.x3d")
                with open(real, "wb") as handle:
                    handle.write(PREVIOUS)
                link = os.path.join(self.tmpdir, f"link_{version}.x3d")
                os.symlink(real, link)
                self.assertEqual(bpy.ops.export_scene.x3d(filepath=link, x3d_version=version, use_selection=False),
                                 {"FINISHED"})
                self.assertTrue(os.path.islink(link), "the export replaced the symlink with a regular file")
                self.assertEqual(os.path.realpath(link), os.path.realpath(real))
                self.assertIn(b"<X3D", self._read(real))
                self.assertNotEqual(self._read(real), PREVIOUS)
                self.assertEqual(self._stage_folders(), [])
                self.assertEqual(self._stage_folders(real_dir), [])

    @unittest.skipUnless(hasattr(os, "symlink") and os.name != "nt", "symlinks need a POSIX file system")
    def test_failed_export_through_a_symlink_keeps_link_and_file(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                real = self._previous(f"real_fail_{version}.x3d")
                link = os.path.join(self.tmpdir, f"link_fail_{version}.x3d")
                os.symlink(real, link)
                self._fail_mid_write(version)
                with self.assertRaises(Exception):
                    bpy.ops.export_scene.x3d(filepath=link, x3d_version=version, use_selection=False)
                self.doCleanups()
                self.assertTrue(os.path.islink(link))
                self.assertEqual(self._read(real), PREVIOUS)


if __name__ == "__main__":
    unittest.main()
