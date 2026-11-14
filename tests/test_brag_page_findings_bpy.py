# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Three round-trip bugs found while staging scenes for the brag page (docs/index.html, 13 Nov 2026).

1. An UnlitMaterial shape's Color came back from the X3D 4.0 export as linear values. The importer turns such a
   Color into linear (X_ITE reads it in display space), and the export wrote the linear values unchanged, so every
   round trip darkened it: PRISMATICA's aurora ribbon 0.456 0.086 0.599 came back as 0.176 0.008 0.317.
2. A glb exported from a scene with an Inline carried the importing machine's absolute path in node extras
   (``x3d_inline_resolved_path``), user and session folders included.
3. A PhysicalMaterial shape's Color reached the mesh but no node read it: Cycles drew the flat baseColor, and
   Blender's glTF exporter wrote no COLOR_0 for it (LUMEN's baked colour ramp came out white in the glb).

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_brag_page_findings_bpy
"""

from __future__ import annotations

import json
import os
import re
import struct
import tempfile
import unittest

try:
    import bpy
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension

HEAD = ('<?xml version="1.0" encoding="UTF-8"?>\n<X3D profile="Immersive" version="4.0"><head/><Scene>\n')
TAIL = "</Scene></X3D>\n"
QUAD = ('<IndexedFaceSet coordIndex="0 1 2 3 -1" colorPerVertex="true" colorIndex="0 1 2 3 -1">'
        '<Coordinate point="0 0 0 1 0 0 1 1 0 0 1 0"/>'
        '<Color color="0.456 0.086 0.599 0.9 0.5 0.1 0.2 0.7 0.3 1 1 1"/></IndexedFaceSet>')


def _glb_json(path):
    with open(path, "rb") as handle:
        data = handle.read()
    length = struct.unpack("<I", data[12:16])[0]
    return json.loads(data[20:20 + length]), data


def _accessor_floats(gltf, blob, index):
    accessor = gltf["accessors"][index]
    view = gltf["bufferViews"][accessor["bufferView"]]
    bin_start = 20 + struct.unpack("<I", blob[12:16])[0] + 8
    start = bin_start + view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    width = {"VEC3": 3, "VEC4": 4}[accessor["type"]]
    count = accessor["count"] * width
    if accessor["componentType"] == 5126:
        return struct.unpack_from(f"<{count}f", blob, start), width
    scale = 65535.0 if accessor["componentType"] == 5123 else 255.0
    fmt = "H" if accessor["componentType"] == 5123 else "B"
    return tuple(v / scale for v in struct.unpack_from(f"<{count}{fmt}", blob, start)), width


@unittest.skipUnless(HAVE_BPY, "bpy not available")
class BragPageFindingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="x3d_brag_findings_")
        _register_extension(self.tmp)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmp)

    def _write(self, name, body):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(HEAD + body + TAIL)
        return path

    def test_unlit_vertex_colours_survive_x3d40_round_trip(self):
        src = self._write("unlit.x3d", f'<Shape><Appearance><UnlitMaterial/></Appearance>{QUAD}</Shape>')
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=src), {"FINISHED"})
        out = os.path.join(self.tmp, "unlit_out.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False),
                         {"FINISHED"})
        with open(out, encoding="utf-8") as handle:
            text = handle.read()
        match = re.search(r'<Color(?:RGBA)? color="([^"]+)"', text)
        self.assertIsNotNone(match, "the export lost the Color node")
        values = [float(v) for v in match.group(1).split()]
        width = 4 if "<ColorRGBA" in match.group(0) else 3
        colours = {tuple(round(c, 3) for c in values[i:i + 3]) for i in range(0, len(values), width)}
        self.assertIn((0.456, 0.086, 0.599), colours)
        self.assertNotIn((0.176, 0.008, 0.317), colours)

    def test_physical_vertex_colours_drive_base_colour_and_reach_glb(self):
        src = self._write("physical.x3d",
                          '<Shape><Appearance><PhysicalMaterial baseColor="0.2 0.2 0.2"/></Appearance>'
                          f'{QUAD}</Shape>')
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=src), {"FINISHED"})
        mesh_objects = [o for o in bpy.data.objects if o.type == "MESH"]
        self.assertEqual(len(mesh_objects), 1)
        material = mesh_objects[0].active_material
        bsdf = next(n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        base = bsdf.inputs["Base Color"]
        self.assertTrue(base.links, "Base Color does not read the Color node")
        # the Color node multiplies baseColor (X_ITE 16.7.1 and glTF); before it replaced it: the old expectation here was
        # a Base Color fed by the colour attribute alone, which dropped the 0.2 from Blender and from the glb
        mix = base.links[0].from_node
        self.assertEqual(mix.bl_idname, "ShaderNodeMix")
        self.assertEqual(mix.blend_type, "MULTIPLY")
        color_a, color_b = (s for s in mix.inputs if s.type == "RGBA")
        self.assertEqual(color_a.links[0].from_node.bl_idname, "ShaderNodeVertexColor")
        self.assertAlmostEqual(color_b.default_value[0], 0.2, places=4)
        self.assertAlmostEqual(base.default_value[0], 0.2, places=4)  # baseColor kept for the X3D export
        glb = os.path.join(self.tmp, "physical.glb")
        self.assertEqual(bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB"), {"FINISHED"})
        gltf, blob = _glb_json(glb)
        attributes = gltf["meshes"][0]["primitives"][0]["attributes"]
        self.assertIn("COLOR_0", attributes)
        values, width = _accessor_floats(gltf, blob, attributes["COLOR_0"])
        self.assertTrue(any(abs(values[i] - 1.0) > 0.05 for i in range(0, len(values), width)),
                        "COLOR_0 is all white")
        # under a PhysicalMaterial the Color stays linear: 0.456 is kept as given
        reds = {round(values[i], 2) for i in range(0, len(values), width)}
        self.assertIn(0.46, reds)
        factor = gltf["materials"][0]["pbrMetallicRoughness"].get("baseColorFactor", [1, 1, 1, 1])
        self.assertAlmostEqual(factor[0], 0.2, places=3)   # baseColor reaches the glb beside COLOR_0, which multiplies it

    def test_glb_extras_carry_no_absolute_inline_path(self):
        child = os.path.join(self.tmp, "parts", "child.x3d")
        os.makedirs(os.path.dirname(child))
        with open(child, "w", encoding="utf-8") as handle:
            handle.write(HEAD + '<Shape><Appearance><PhysicalMaterial/></Appearance><Box/></Shape>' + TAIL)
        src = self._write("parent.x3d", '<Inline url=\'"parts/child.x3d"\'/>')
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=src), {"FINISHED"})
        glb = os.path.join(self.tmp, "parent.glb")
        self.assertEqual(bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB", export_extras=True),
                         {"FINISHED"})
        gltf, _ = _glb_json(glb)
        text = json.dumps(gltf)
        self.assertNotIn(self.tmp, text)
        self.assertNotIn(os.path.dirname(self.tmp), text)
        stored = [n["extras"]["x3d_inline_resolved_path"] for n in gltf["nodes"]
                  if "x3d_inline_resolved_path" in (n.get("extras") or {})]
        self.assertTrue(stored, "the Inline's resolved path is no longer recorded")
        self.assertEqual(set(stored), {"parts/child.x3d"})


if __name__ == "__main__":
    unittest.main()
