# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Crashes, hangs and drift found by the second chaos round (2.7.3), kept fixed.

Hostile files (tools/chaos/hostile.py), each of which used to crash, hang or fill the disk:

* an ImageTexture url of ``/dev/zero``: the COPY re-export copied it until the disk was full;
* a file cut off mid-tag, or with an entity declaration: a traceback instead of a clean cancel;
* Latin-1 bytes in a DEF, a UTF-16 file: UnicodeEncodeError;
* every ClassicVRML Inline: the url list itself went to ``os.path.exists`` (TypeError);
* a ClassicVRML Inline cycle (a inlines b inlines a) and 5,000 nested VRML Groups: RecursionError;
* a count in the file that sets a size: an ElevationGrid of 10^10 points, a Sphere or Cylinder subdivision of 0,
  a PixelTexture of 10^10 pixels, and 100,000 Inline loads from ten Inlines over five levels;
* NaN and INF in a point list, and a zero-padded coordIndex entry (``010``).

Scenes going out (tools/chaos/scene_chaos.py):

* a triangulated two-material mesh, and a material_index past every slot, in the X3D 3.3 writer;
* Metallic 2.0 or Roughness 10^6, which the export gate refused with a traceback;
* a NaN vertex written as ``nan`` by the X3D 3.3 writer, which has no gate;
* 1,500 parented empties: RecursionError, then the import read the deep file as "not a valid document";
* a 48-key animation over 47,000 s, which one round trip made 1,048,574 keys.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_chaos_round2_bpy
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))

QUAD = ("<Shape><IndexedFaceSet solid='false' coordIndex='0 1 2 3 -1'>"
        "<Coordinate point='0 0 0 1 0 0 1 1 0 0 1 0'/></IndexedFaceSet></Shape>")
TRI_TEX = ("<Shape><Appearance><ImageTexture url='\"{url}\"'/></Appearance>"
           "<IndexedFaceSet coordIndex='0 1 2 -1'><Coordinate point='0 0 0 1 0 0 1 1 0'/></IndexedFaceSet></Shape>")


def _x3d(body: str) -> str:
    return ("<?xml version='1.0' encoding='UTF-8'?>\n<X3D profile='Interchange' version='4.0'><Scene>"
            f"{body}</Scene></X3D>\n")


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class HostileFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_chaos2_")
        _register_extension(cls.tmpdir)

    def _write(self, name, data):
        path = os.path.join(self.tmpdir, name)
        mode = "wb" if isinstance(data, bytes) else "w"
        with open(path, mode, **({} if isinstance(data, bytes) else {"encoding": "utf-8"})) as f:
            f.write(data)
        return path

    def _import(self, path):
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        result = bpy.ops.import_scene.x3d(filepath=path)
        return result, [o for o in bpy.data.objects if o.type == "MESH"]

    def test_dev_zero_texture_is_not_loaded_or_copied(self):
        import bpy
        path = self._write("zero.x3d", _x3d(TRI_TEX.format(url="/dev/zero")))
        result, meshes = self._import(path)
        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(len(meshes), 1)
        out_dir = os.path.join(self.tmpdir, "zero-out")
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, "zero.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, path_mode="COPY"), {"FINISHED"})
        total = sum(os.path.getsize(os.path.join(out_dir, n)) for n in os.listdir(out_dir))
        self.assertLess(total, 1 << 20)

    def test_malformed_files_cancel_cleanly(self):
        whole = _x3d(QUAD)
        cases = {
            "cut.x3d": whole[: whole.index("coordIndex") + 5],
            "entity.x3d": whole.replace("<X3D", "<!DOCTYPE X3D [<!ENTITY a 'b'>]><X3D", 1),
            "nul.x3d": whole.replace("solid='false'", "solid='fa\0lse'"),
            "png.x3d": b"\x89PNG\r\n\x1a\n" + bytes(range(256)),
        }
        for name, data in cases.items():
            with self.subTest(name=name):
                result, meshes = self._import(self._write(name, data))
                self.assertEqual(result, {"CANCELLED"})
                self.assertEqual(meshes, [])

    def test_latin1_and_utf16_files_import(self):
        whole = _x3d(f"<Transform DEF='Té'>{QUAD}</Transform>")
        for name, data in (("latin1.x3d", whole.encode("latin-1")),
                           ("utf16.x3d", "﻿".encode("utf-16-le") + whole.encode("utf-16-le"))):
            with self.subTest(name=name):
                result, meshes = self._import(self._write(name, data))
                self.assertEqual(result, {"FINISHED"})
                self.assertEqual(len(meshes), 1)

    def test_classic_vrml_inline_loads_and_a_cycle_stops(self):
        vquad = ("Shape { geometry IndexedFaceSet { coordIndex [ 0 1 2 3 -1 ] "
                 "coord Coordinate { point [ 0 0 0, 1 0 0, 1 1 0, 0 1 0 ] } } }")
        self._write("child.wrl", "#VRML V2.0 utf8\n" + vquad + "\n")
        parent = self._write("parent.wrl", '#VRML V2.0 utf8\nInline { url "child.wrl" }\n' + vquad + "\n")
        result, meshes = self._import(parent)
        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(len(meshes), 2)                     # every VRML Inline raised TypeError before
        self._write("cb.wrl", '#VRML V2.0 utf8\nInline { url "ca.wrl" }\n' + vquad + "\n")
        ca = self._write("ca.wrl", '#VRML V2.0 utf8\nInline { url "cb.wrl" }\n' + vquad + "\n")
        result, meshes = self._import(ca)
        self.assertEqual(result, {"FINISHED"})
        self.assertGreaterEqual(len(meshes), 2)

    def test_deep_classic_vrml_imports(self):
        vquad = ("Shape { geometry IndexedFaceSet { coordIndex [ 0 1 2 3 -1 ] "
                 "coord Coordinate { point [ 0 0 0, 1 0 0, 1 1 0, 0 1 0 ] } } }")
        body = "Group { children [ " * 5000 + vquad + " ] }" * 5000
        result, meshes = self._import(self._write("deep.x3dv", "#X3D V4.0 utf8\nPROFILE Interchange\n" + body))
        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(len(meshes), 1)

    def test_counts_that_set_a_size_are_bounded(self):
        cases = {
            "grid.x3d": ("<Shape><ElevationGrid xDimension='100000' zDimension='100000' height='0 0 0 0'/></Shape>", 1),
            "sphere0.x3d": ("<Shape><Sphere subdivision='0 0'/></Shape>", 2),
            "cyl0.x3d": ("<Shape><Cylinder subdivision='0'/></Shape><Shape><Cone subdivision='-5'/></Shape>", 3),
            "pixels.x3d": ("<Shape><Appearance><PixelTexture image='100000 100000 3 0xFF0000'/></Appearance>"
                           "<IndexedFaceSet coordIndex='0 1 2 -1'><Coordinate point='0 0 0 1 0 0 1 1 0'/>"
                           "</IndexedFaceSet></Shape>", 2),
        }
        for name, (body, mesh_count) in cases.items():
            with self.subTest(name=name):
                result, meshes = self._import(self._write(name, _x3d(body + QUAD)))
                self.assertEqual(result, {"FINISHED"})
                self.assertEqual(len(meshes), mesh_count)
                for mesh in meshes:
                    self.assertLess(len(mesh.data.vertices), 1 << 20)

    def test_inline_fan_out_is_bounded(self):
        import budget
        for level in range(4, 0, -1):
            body = "".join(f"<Inline url='\"fan{level + 1}.x3d\"'/>" for _ in range(10)) if level < 4 else QUAD
            self._write(f"fan{level}.x3d", _x3d(body))
        old = os.environ.get(budget.MAX_INLINES_ENV)
        os.environ[budget.MAX_INLINES_ENV] = "25"
        try:
            result, meshes = self._import(os.path.join(self.tmpdir, "fan1.x3d"))
        finally:
            if old is None:
                os.environ.pop(budget.MAX_INLINES_ENV, None)
            else:
                os.environ[budget.MAX_INLINES_ENV] = old
        self.assertEqual(result, {"FINISHED"})
        self.assertLessEqual(len(meshes), 25)

    def test_non_finite_numbers_and_zero_padded_indices(self):
        import math
        body = ("<Shape><IndexedFaceSet coordIndex='0 1 2 -1'><Coordinate point='0 0 0 NaN 0 0 1 INF 0'/>"
                "</IndexedFaceSet></Shape><Shape><IndexedFaceSet coordIndex='00 01 02 03 -1'>"
                "<Coordinate point='0 0 0 1 0 0 1 1 0 0 1 0'/></IndexedFaceSet></Shape>")
        result, meshes = self._import(self._write("nan.x3d", _x3d(body)))
        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(sorted(len(m.data.polygons) for m in meshes), [1, 1])
        for mesh in meshes:
            for v in mesh.data.vertices:
                self.assertTrue(all(math.isfinite(c) for c in v.co))


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class SceneChaosExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_chaos2_export_")
        _register_extension(cls.tmpdir)
        sys.path.insert(0, str(Path(__file__).resolve().parent))

    def _scene(self, name):
        import frozen_scenes
        frozen_scenes.build(name)
        import bpy
        return bpy

    def _export(self, name, **options):
        import bpy
        out = os.path.join(self.tmpdir, name)
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, **options), {"FINISHED"})
        with open(out, encoding="utf-8") as f:
            return out, f.read()

    def test_x3d33_triangulated_two_materials_and_a_far_material_index(self):
        bpy = self._scene("two_materials")
        self._export("tri.x3d", x3d_version="X3D33", use_triangulate=True)
        for p in bpy.data.objects["Split"].data.polygons:
            p.material_index = 30000
        self._export("far.x3d", x3d_version="X3D33")

    def test_out_of_range_factors_are_clamped_not_refused(self):
        bpy = self._scene("two_materials")
        mat = bpy.data.objects["Split"].data.materials[0]
        bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        bsdf.inputs["Metallic"].default_value = 2.0
        bsdf.inputs["Roughness"].default_value = 1e6
        _, text = self._export("factors.x3d", x3d_version="X3D40", material_model="PHYSICAL")
        self.assertIn('metallic="1', text.replace("'", '"'))

    def test_x3d33_never_writes_nan(self):
        bpy = self._scene("lit_cube")
        bpy.data.objects["Cube"].data.vertices[5].co[2] = float("nan")
        _, text = self._export("nan33.x3d", x3d_version="X3D33")
        import re
        self.assertIsNone(re.search(r"(?<![\w.])-?(nan|inf)(?![\w.])", text, re.I))

    def test_deep_parent_chain_exports_and_reimports(self):
        bpy = self._scene("lit_cube")
        parent = None
        for i in range(1500):
            empty = bpy.data.objects.new(f"Chain{i}", None)
            bpy.context.scene.collection.objects.link(empty)
            empty.parent = parent
            parent = empty
        bpy.data.objects["Cube"].parent = parent
        out, _ = self._export("deep.x3d")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=out), {"FINISHED"})
        self.assertEqual(len([o for o in bpy.data.objects if o.type == "MESH"]), 1)

    def test_long_animation_round_trip_stays_bounded(self):
        bpy = self._scene("lit_cube")
        scene = bpy.context.scene
        scene.render.fps, scene.render.fps_base = 1, 1000.0
        cube = bpy.data.objects["Cube"]
        cube.keyframe_insert("location", frame=1)
        cube.location = (1, 1, 1)
        cube.keyframe_insert("location", frame=48)
        out, _ = self._export("long.x3d", use_animation=True)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=out), {"FINISHED"})
        _, text = self._export("long2.x3d", use_animation=True)
        import re
        keys = re.search(r'PositionInterpolator[^>]*key="([^"]*)"', text)
        self.assertIsNotNone(keys)
        self.assertLessEqual(len(keys.group(1).split()), 10001)      # 1,048,574 before


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class FixedPointTests(unittest.TestCase):
    """The round-trip drifts the 2.7.3 scene chaos found: export, import, export again gives the same file."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_chaos2_fp_")
        _register_extension(cls.tmpdir)

    def _round(self, text, name, **options):
        """Import ``text``, export it (options), import that, export again; returns the two exports' text."""
        import bpy
        src = os.path.join(self.tmpdir, name + ".x3d")
        Path(src).write_text(text, encoding="utf-8")
        outs = []
        for i in (2, 3):
            bpy.ops.wm.read_factory_settings(use_empty=True)
            self.assertEqual(bpy.ops.import_scene.x3d(filepath=src), {"FINISHED"})
            dst = os.path.join(self.tmpdir, f"{name}.{i}.x3d")
            self.assertEqual(bpy.ops.export_scene.x3d(filepath=dst, **options), {"FINISHED"})
            outs.append(Path(dst).read_text(encoding="utf-8"))
            src = dst
        return outs

    def test_made_up_texture_coordinates_are_not_written(self):
        for version in ("X3D40", "X3D33"):
            second, third = self._round(_x3d(QUAD), "uv-" + version, x3d_version=version)
            self.assertNotIn("TextureCoordinate", second, version)
            self.assertNotIn("TextureCoordinate", third, version)

    def test_edited_default_texture_coordinates_are_written(self):
        import bpy
        src = os.path.join(self.tmpdir, "uv-edit.x3d")
        Path(src).write_text(_x3d(QUAD), encoding="utf-8")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.x3d(filepath=src)
        mesh = next(o for o in bpy.data.objects if o.type == "MESH").data
        mesh.uv_layers.active.data[0].uv = (0.25, 0.75)
        out = os.path.join(self.tmpdir, "uv-edit.out.x3d")
        bpy.ops.export_scene.x3d(filepath=out)
        self.assertIn("TextureCoordinate", Path(out).read_text(encoding="utf-8"))

    def test_half_turn_has_one_spelling(self):
        from extract import canonical_axis_angle
        import math
        self.assertEqual(canonical_axis_angle((0, -0.70711, -0.70711), math.pi), (0.0, 0.70711, 0.70711, math.pi))
        x, y, z, a = canonical_axis_angle((0, 0, 1), 1.5 * math.pi)
        self.assertEqual((x, y, z), (0.0, 0.0, -1.0))
        self.assertAlmostEqual(a, 0.5 * math.pi)
        self.assertEqual(canonical_axis_angle((1, 0, 0), 0.0), (0.0, 0.0, 1.0, 0.0))

    def test_zero_scale_keeps_its_rotation(self):
        body = ("<Transform rotation='1 0 0 2.19122' scale='0 1 1'>" + QUAD + "</Transform>")
        for version in ("X3D40", "X3D33"):
            second, third = self._round(_x3d(body), "flat-" + version, x3d_version=version)
            self.assertIn("2.19122", second.replace('"', "'"), version)
            self.assertIn("2.19122", third.replace('"', "'"), version)

    def test_odd_characters_in_names_are_spelled_once(self):
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        mesh = bpy.data.meshes.new("m")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        obj = bpy.data.objects.new("o", mesh)
        bpy.context.scene.collection.objects.link(obj)
        mesh.materials.append(bpy.data.materials.new("a<b>&'\"c"))
        out = os.path.join(self.tmpdir, "odd33.x3d")
        bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D33")
        text = Path(out).read_text(encoding="utf-8")
        self.assertIn("MA_a_b____c", text)
        self.assertNotIn("&lt;", text)

    def test_image_texture_node_without_an_image_exports(self):
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        mesh = bpy.data.meshes.new("m")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        obj = bpy.data.objects.new("o", mesh)
        bpy.context.scene.collection.objects.link(obj)
        mat = bpy.data.materials.new("textured")
        mat.use_nodes = True
        tex = mat.node_tree.nodes.new("ShaderNodeTexImage")       # no image
        bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        mesh.materials.append(mat)
        out = os.path.join(self.tmpdir, "noimage33.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D33"), {"FINISHED"})

    def test_x3d33_infinite_scale_is_written_finite(self):
        import re
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        mesh = bpy.data.meshes.new("m")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        obj = bpy.data.objects.new("o", mesh)
        bpy.context.scene.collection.objects.link(obj)
        obj.scale[2] = float("-inf")
        out = os.path.join(self.tmpdir, "inf33.x3d")
        bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D33")
        self.assertIsNone(re.search(r"(?<![\w.])-?(nan|inf)(?![\w.])", Path(out).read_text(encoding="utf-8"), re.I))


if __name__ == "__main__":
    unittest.main()
