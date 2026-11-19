# SPDX-License-Identifier: GPL-3.0-or-later
"""Verify resource policies through the legacy importer's actual entry points."""

import importlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.sax import SAXException

try:
    import bpy
    HAVE_BPY = True
except ImportError:
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ImportResourceBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="x3d-resource-tests-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        _register_extension(cls.temporary.name)
        cls.importer = importlib.import_module("io_scene_x3d.import_x3d")

    def test_external_x3d_doctype_imports_geometry(self):
        path = self.directory / "doctype.x3d"
        path.write_text('''<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN"
            "https://invalid.example/x3d.dtd"><X3D profile="Immersive" version="4.0">
            <Scene><Shape><Box/></Shape></Scene></X3D>''')
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.importer.load(bpy.context, str(path))
        self.assertEqual(len([obj for obj in bpy.context.scene.objects if obj.type == "MESH"]), 1)

    def test_internal_entity_fails_before_creating_objects(self):
        path = self.directory / "entity.x3d"
        path.write_text('''<!DOCTYPE X3D [<!ENTITY e "expanded">]><X3D>
            <Scene><WorldInfo title="&e;"/><Shape><Box/></Shape></Scene></X3D>''')
        bpy.ops.wm.read_factory_settings(use_empty=True)
        with self.assertRaisesRegex(SAXException, "entity declarations"):
            self.importer.load(bpy.context, str(path))
        self.assertEqual(len(bpy.context.scene.objects), 0)

    def test_actual_image_loader_callback_receives_shell_characters_literally(self):
        if __import__("os").sep == "\\":
            self.skipTest("the compatibility converter is used only on Unix")
        from bpy_extras.image_utils import load_image
        # Generate a valid PNG, then give its source the legacy GIF suffix. The
        # subprocess is mocked: this test invokes no ImageMagick or shell.
        seed = bpy.data.images.new("ResourceTest", 1, 1)
        seed.file_format = "PNG"
        png = self.directory / "seed.png"
        seed.save_render(str(png))
        source = self.directory / 'asset$(touch SHOULD_NOT_EXIST);".gif'
        source.write_bytes(png.read_bytes())

        def fake_convert(argv, **_kwargs):
            Path(argv[2]).write_bytes(png.read_bytes())

        with patch("io_scene_x3d.import_resources.subprocess.run", side_effect=fake_convert) as run:
            loaded = load_image(str(source), convert_callback=self.importer.imageConvertCompat, place_holder=False)
        converted = run.call_args.args[0][2]
        self.addCleanup(Path(converted).unlink, missing_ok=True)
        self.assertIsNotNone(loaded)
        self.assertEqual(run.call_args.args[0][1], str(source))
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_online_permission_prevents_download_even_with_cached_file(self):
        cached = self.directory / "cached.png"
        cached.write_bytes(b"image")
        url = "https://example.invalid/albedo.png"
        self.importer.download_cache[url] = str(cached)
        self.addCleanup(self.importer.download_cache.pop, url, None)
        fake_bpy = type("Bpy", (), {"app": type("App", (), {"online_access": False})})
        with patch.object(self.importer, "bpy", fake_bpy):
            self.assertIsNone(self.importer.download_image(url))

    def test_failed_remote_url_falls_back_to_next_mfstring_image(self):
        seed = bpy.data.images.new("FallbackImage", 1, 1)
        seed.file_format = "PNG"
        png = self.directory / "fallback.png"
        seed.save_render(str(png))
        document = str(self.directory / "document.x3d")
        node = type("Node", (), {"getFilename": lambda self: document})()
        with patch.object(self.importer, "current_file_path", document):
            with patch.object(self.importer, "download_image", return_value=None) as download:
                loaded = self.importer.appearance_LoadImageTextureFile(
                    ["https://invalid.example/missing.png", "fallback.png"], node)
        self.assertIsNotNone(loaded)
        self.assertEqual(Path(loaded.filepath).resolve(), png.resolve())
        download.assert_called_once()

    def test_inline_prefers_source_directory_over_process_working_directory(self):
        source = self.directory / "source"
        working = self.directory / "working"
        source.mkdir(exist_ok=True)
        working.mkdir(exist_ok=True)
        (source / "asset.x3d").write_text("source asset")
        (working / "asset.x3d").write_text("unrelated working-directory asset")
        document = str(source / "scene.x3d")
        node = type("Node", (), {"getFilename": lambda self: document})()
        # Use a real temporary CWD so os.path.isfile and abspath exercise the original bug.
        previous = os.getcwd()
        try:
            os.chdir(working)
            self.assertEqual(self.importer._resolve_inline_url(node, "asset.x3d"), str(source / "asset.x3d"))
            self.assertEqual(self.importer._resolve_inline_url(node, str(source / "asset.x3d")),
                             str(source / "asset.x3d"))
            (source / "asset.x3d").unlink()
            self.assertIsNone(self.importer._resolve_inline_url(node, "asset.x3d"))
        finally:
            os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
