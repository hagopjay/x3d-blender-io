# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The lineage report over scenes made in Blender, and what the writers do with provenance head meta (needs ``bpy``).

Run with the ``bpy`` wheel or inside Blender: ``python .github/scripts/run_tests_in_blender.py -- test_lineage_bpy``.
"""

from __future__ import annotations

import io
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
        pass   # already registered by an earlier test in the same interpreter
    return module


def _head(path):
    return [(m.attrib["name"], m.attrib["content"]) for m in ET.parse(path).getroot().iter("meta")]


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class LineageOverBlenderScene(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_lineage_")
        _register_extension(self.tmpdir)
        if str(SOURCE_DIR) not in sys.path:
            sys.path.insert(0, str(SOURCE_DIR))

    def _build(self):
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene
        scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
        bpy.ops.mesh.primitive_cube_add(size=2.0, location=(1.0, 3.0, 2.0))
        cube = bpy.context.object
        cube.name = "Cube.001"
        material = bpy.data.materials.new("Paint")
        material.use_nodes = True
        bsdf = material.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = (0.2, 0.4, 0.6, 1.0)
        cube.data.materials.append(material)
        bpy.ops.object.light_add(type="POINT", location=(0.0, 0.0, 5.0))
        lamp = bpy.context.object
        lamp.name = "Lamp"
        lamp.data.energy = 0.7
        bpy.ops.object.camera_add(location=(7.0, -7.0, 5.0))
        cam = bpy.context.object
        cam.name = "Cam"
        cam.data.angle = 1.2
        scene.camera = cam
        return scene, cube, lamp, cam

    def test_report_agrees_with_the_blender_side_numbers(self):
        import bpy
        import emit_x3d40
        import extract
        import lineage
        from bpy_extras.io_utils import axis_conversion
        from mathutils import Matrix
        from viewpoint_fov import render_size

        scene, cube, lamp, cam = self._build()
        global_matrix = axis_conversion(to_forward="-Z", to_up="Y").to_4x4() @ Matrix.Scale(1.0, 4)
        ir = extract.extract_scene(scene, view_layer=bpy.context.view_layer, depsgraph=bpy.context.evaluated_depsgraph_get(),
                                   global_matrix=global_matrix, use_selection=False, metadata={"filename": "e2e.x3d"},
                                   material_model="classic", colour_space="SRGB")
        buffer = io.StringIO()
        emit_x3d40.export_ir_scene(buffer, ir, generator="test", version="4.0", colour_space="SRGB")
        text = buffer.getvalue()
        width, height = render_size(scene)
        snapshot = {"LA_Lamp/intensity": [lamp.data.energy, extract.light_energy_per_intensity(lamp.data), 1],
                    "CA_Cam/fieldOfView": [cam.data.angle, 0 if width >= height else 1, width, height]}
        report = lineage.build_report(ir, text, colour_space="SRGB", source_values=snapshot)
        by = {(r["def"], r["field"]): r for r in report["records"]}

        # Blender's (1, 3, 2) is X3D's (1, 2, -3): the Z-up to Y-up conversion, and a 90 degree turn about -X on an unturned cube
        self.assertEqual(by[("OB_Cube_001", "translation")]["file_value"], "1.000000 2.000000 -3.000000")
        self.assertEqual(by[("OB_Cube_001", "rotation")]["file_value"], "-1.000000 0.000000 0.000000 1.570796")
        self.assertIn("axis_conversion", [step["id"] for step in by[("OB_Cube_001", "rotation")]["derivation"]])
        self.assertTrue(by[("LA_Lamp", "intensity")]["source_ok"])
        self.assertTrue(by[("CA_Cam", "fieldOfView")]["source_ok"])
        self.assertEqual(report["summary"]["unchecked"], 0)
        self.assertEqual(lineage.reverify(report, text), [])
        self.assertEqual(by[("MA_Paint", "specularColor")]["verdict"], "check")       # the Blinn-Phong fit is never "verified"

    def test_unknown_head_meta_is_kept_by_the_4_0_writer_only(self):
        import bpy
        source = Path(self.tmpdir) / "prov.x3d"
        source.write_text(
            '<?xml version="1.0" encoding="UTF-8"?><X3D profile="Immersive" version="4.0"><head>'
            '<meta name="x3dprov.step" content="3"/><meta name="x3dprov.sha256" content="abc123"/></head>'
            '<Scene><Shape><Appearance><Material diffuseColor="0.8 0.2 0.2"/></Appearance><Box size="1 1 1"/></Shape></Scene></X3D>',
            encoding="utf-8")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=str(source)), {"FINISHED"})
        new, legacy = Path(self.tmpdir) / "new.x3d", Path(self.tmpdir) / "legacy.x3d"
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=str(new), x3d_version="X3D40", use_selection=False), {"FINISHED"})
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=str(legacy), x3d_version="X3D33", use_selection=False), {"FINISHED"})
        self.assertEqual([m for m in _head(new) if m[0].startswith("x3dprov.")], [("x3dprov.step", "3"), ("x3dprov.sha256", "abc123")])
        self.assertEqual([m for m in _head(legacy) if m[0].startswith("x3dprov.")], [])   # the 3.3 writer has a fixed list of meta
        self.assertIn("created", [name for name, _ in _head(legacy)])                   # and stamps the time, so it is never byte-stable

    def test_a_blender_scene_ignores_a_head_meta_property_unless_it_holds_imported_content(self):
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_cube_add(size=1.0)
        bpy.context.scene["x3d_head_meta"] = [{"name": "x3dprov.step", "content": "7"}]
        path = Path(self.tmpdir) / "native.x3d"
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=str(path), x3d_version="X3D40", use_selection=False), {"FINISHED"})
        self.assertEqual([name for name, _ in _head(path)], ["generator", "filename"])

    def test_object_metadata_needs_no_import(self):
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_cube_add(size=1.0)
        bpy.context.object["x3d_metadata"] = {"node": "MetadataSet", "name": "x3dprov", "reference": "cube.lineage.json",
                                              "value": [{"node": "MetadataString", "name": "sha256", "value": '"abc"'}]}
        path = Path(self.tmpdir) / "meta.x3d"
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=str(path), x3d_version="X3D40", use_selection=False), {"FINISHED"})
        node = ET.parse(path).getroot().find(".//Transform/Shape/MetadataSet")
        self.assertEqual(node.attrib, {"containerField": "metadata", "name": "x3dprov", "reference": "cube.lineage.json"})


if __name__ == "__main__":
    unittest.main()
