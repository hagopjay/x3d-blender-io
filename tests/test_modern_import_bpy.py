# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The modern import path (BLENDER_X3D_IMPORT_TARGET=MODERN: parse_x3d40 -> IR -> populate), the node registry and
the X3D 3.3 emitter scaffold, which had no tests (populate.py, x3d_registry.py and emit_x3d33.py at 0 % coverage).

    cd tests && python -m unittest test_modern_import_bpy
"""

from __future__ import annotations

import dataclasses
import io
import math
import os
import tempfile
import unittest
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parents[1] / "source"

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

if HAVE_BPY:
    from test_roundtrip_bpy import _register_extension


def _package(tmpdir):
    """The add-on as the io_scene_x3d package (its modules use relative imports)."""
    module = _register_extension(tmpdir)
    return module.__name__


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class RegistryAndScaffoldTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_modern_")
        self.pkg = _package(self.tmpdir)

    def test_registry_is_consistent(self):
        reg = __import__(self.pkg + ".x3d_registry", fromlist=["x3d_registry"])
        self.assertIn("PhysicalMaterial", reg.REGISTRY)
        for key, spec in reg.REGISTRY.items():
            self.assertEqual(key, spec.name)
            self.assertTrue(spec.version.startswith(("3.", "4.")))
            names = [f.name for f in spec.fields]
            self.assertEqual(len(names), len(set(names)), key)            # no field twice
            for f in spec.fields:
                self.assertRegex(f.field_type, r"^(SF|MF)[A-Z][A-Za-z0-9]+$")
                if f.field_type == "SFNode":
                    self.assertIsNone(f.default)
        pm = {f.name: f.default for f in reg.REGISTRY["PhysicalMaterial"].fields}
        self.assertEqual((pm["metallic"], pm["roughness"]), (0.0, 0.5))    # X3D 4.0's PhysicalMaterial defaults
        with self.assertRaises(dataclasses.FrozenInstanceError):
            reg.REGISTRY["PhysicalMaterial"].name = "x"                     # frozen

    def test_x3d33_scaffold_writes_a_valid_head(self):
        ir = __import__(self.pkg + ".ir", fromlist=["ir"])
        emit = __import__(self.pkg + ".emit_x3d33", fromlist=["emit_x3d33"])
        out = io.StringIO()
        emit.export_ir_scene(out, ir.IRScene(name="s", metadata=ir.IRMetadata(title="Still life")), generator="t")
        text = out.getvalue()
        self.assertIn('<X3D version="3.3" profile="Immersive">', text)
        self.assertIn('<meta name="generator" content="t" />', text)
        self.assertIn('<meta name="title" content="Still life" />', text)
        import xml.etree.ElementTree as ET
        root = ET.fromstring(text.split("\n", 2)[2])                         # past the XML and DOCTYPE lines
        self.assertEqual(root.find("Scene/WorldInfo").get("title"), "Legacy Scaffold Export")
        bare = io.StringIO()
        emit.export_ir_scene(bare, ir.IRScene(name="s"))
        self.assertNotIn('name="title"', bare.getvalue())


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ModernImportTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_modern_")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.pkg = _package(self.tmpdir)
        self._target = os.environ.get("BLENDER_X3D_IMPORT_TARGET")
        os.environ["BLENDER_X3D_IMPORT_TARGET"] = "MODERN"
        # a cube as glTF, the Inline asset the modern importer brings in
        bpy.ops.mesh.primitive_cube_add(size=1.0)
        mat = bpy.data.materials.new("CubeMat")
        bpy.context.object.data.materials.append(mat)
        self.glb = os.path.join(self.tmpdir, "cube.glb")
        bpy.ops.export_scene.gltf(filepath=self.glb, export_format="GLB")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _package(self.tmpdir)

    def tearDown(self):
        if self._target is None:
            os.environ.pop("BLENDER_X3D_IMPORT_TARGET", None)
        else:
            os.environ["BLENDER_X3D_IMPORT_TARGET"] = self._target

    def write(self, body, head=""):
        path = os.path.join(self.tmpdir, "scene.x3d")
        with open(path, "w", encoding="utf-8") as f:
            f.write("<?xml version='1.0' encoding='UTF-8'?>\n<X3D profile='Immersive' version='4.0'>"
                    "<head>%s</head><Scene>%s</Scene></X3D>\n" % (head, body))
        return path

    def test_viewpoints_inline_gltf_and_metadata(self):
        path = self.write(
            "<NavigationInfo type='\"EXAMINE\" \"ANY\"'/>"
            "<Viewpoint description='Front' position='0 1 6' fieldOfView='0.6'/>"
            "<Viewpoint position='3 0 0' orientation='0 1 0 1.5708'/>"
            "<Transform translation='1 2 3' scale='2 2 2'><Inline url='\"cube.glb\"'/></Transform>"
            "<Inline url='\"elsewhere.wrl\"'/>",
            head="<meta name='title' content='Modern'/><meta name='creator' content='tests'/>"
                 "<meta name='description' content='a cube'/>")
        self.assertIn("FINISHED", bpy.ops.import_scene.x3d(filepath=path))
        cams = [o for o in bpy.data.objects if o.type == 'CAMERA']
        self.assertEqual(sorted(o.name for o in cams), ["Front", "X3DViewpoint_001"])
        front = bpy.data.objects["Front"]
        self.assertAlmostEqual(front["x3d_viewpoint_fov"], 0.6, places=6)
        self.assertEqual(tuple(round(c, 4) for c in front.location), (0.0, 1.0, 6.0))
        self.assertIs(bpy.context.scene.camera, front)                     # the first Viewpoint is bound
        self.assertEqual(bpy.context.scene["x3d_navigation_types"], "EXAMINE|ANY")
        roots = [o for o in bpy.data.objects if o.get("x3d_inline_url")]
        self.assertEqual(len(roots), 1)                                     # the .wrl Inline is not a glTF asset
        root = roots[0]
        self.assertEqual(root["x3d_inline_asset_type"], "gltf")
        self.assertEqual(tuple(round(c, 4) for c in root.location), (1.0, 2.0, 3.0))
        self.assertEqual(tuple(round(c, 4) for c in root.scale), (2.0, 2.0, 2.0))
        children = [o for o in bpy.data.objects if o.parent is root]
        self.assertTrue(children and all(o["x3d_inline_source"] == "cube.glb" for o in children))
        self.assertEqual(root.users_collection[0]["x3d_scene_title"], "Modern")
        self.assertEqual(root["x3d_scene_creator"], "tests")
        tagged = [m for m in bpy.data.materials if m.get("x3d_inline_source") == "cube.glb"]
        self.assertTrue(tagged)

    def test_populate_reports_unsupported_inline_types(self):
        parse = __import__(self.pkg + ".parse_x3d40", fromlist=["parse_x3d40"])
        populate = __import__(self.pkg + ".populate", fromlist=["populate"])
        ir_scene = parse.parse_file(self.write("<Inline url='\"model.obj\"'/>"))
        result = populate.populate_scene(bpy.context, ir_scene)
        self.assertEqual(result["imported_assets"], [])
        self.assertTrue(any("Unsupported Inline asset type" in d for d in ir_scene.diagnostics))
        self.assertEqual(result["viewpoints"], [])

    def test_inline_paths_and_names(self):
        populate = __import__(self.pkg + ".populate", fromlist=["populate"])
        self.assertEqual(populate._resolve_inline_path("/a/b/scene.x3d", "m/c.glb"), os.path.normpath("/a/b/m/c.glb"))
        self.assertEqual(populate._resolve_inline_path(None, "c.glb"), "c.glb")
        self.assertEqual(populate._resolve_inline_path("/a/scene.x3d", "/abs/c.glb"), "/abs/c.glb")
        self.assertEqual(populate._safe_name("9 lives.glb"), "__lives_glb")
        self.assertEqual(populate._safe_name(""), "InlineAsset")

    def test_transform_rotation_lands_as_axis_angle(self):
        path = self.write("<Transform rotation='0 0 1 1.5708'><Inline url='\"cube.glb\"'/></Transform>")
        bpy.ops.import_scene.x3d(filepath=path)
        root = next(o for o in bpy.data.objects if o.get("x3d_inline_url"))
        self.assertEqual(root.rotation_mode, "AXIS_ANGLE")
        angle, _x, _y, z = root.rotation_axis_angle
        self.assertAlmostEqual(angle, math.pi / 2, places=4)
        self.assertAlmostEqual(z, 1.0, places=4)


if __name__ == "__main__":
    unittest.main()
