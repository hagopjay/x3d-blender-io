# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""An image used by several materials is written as one ImageTexture and USE'd by the others.

Each material wrote its own ImageTexture, so a texture shared by N materials appeared N times with the same url (the
conformance suite's main file has T_base_uvtest.png five times). Web3D's X3D Schematron warns about it ("consider
DEF/USE to reduce download delays and memory requirements"). The first use now carries a DEF and later uses a USE
with their own containerField, so a texture shared across roles (base colour in one material, emissive in another)
keeps each role.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_export_texture_def_use_bpy
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension, SOURCE_DIR


def _upstream_image(socket):
    """File path of the first image texture feeding ``socket``, through any nodes the import put in between."""
    seen, queue = set(), [link.from_node for link in socket.links]
    while queue:
        node = queue.pop(0)
        if node.as_pointer() in seen:
            continue
        seen.add(node.as_pointer())
        if node.type == "TEX_IMAGE" and node.image is not None:
            return node.image.filepath
        queue.extend(link.from_node for entry in node.inputs for link in entry.links)
    return None


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ExportTextureDefUseTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_texture_use_")
        _register_extension(self.tmpdir)
        sys.path.insert(0, str(SOURCE_DIR))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmpdir)
        image = bpy.data.images.new("Shared", 4, 4)
        image.filepath_raw = os.path.join(self.tmpdir, "src", "shared.png")
        os.makedirs(os.path.dirname(image.filepath_raw))
        image.file_format = "PNG"
        image.save()
        self.image = image
        for index, (name, socket) in enumerate((("BaseA", "Base Color"), ("BaseB", "Base Color"),
                                                ("Glow", "Emission Color"))):
            bpy.ops.mesh.primitive_cube_add(location=(index * 3, 0, 0))
            obj = bpy.context.active_object
            obj.name = name
            material = bpy.data.materials.new(name)
            material.use_nodes = True
            tree = material.node_tree
            bsdf = next(node for node in tree.nodes if node.type == "BSDF_PRINCIPLED")
            texture = tree.nodes.new("ShaderNodeTexImage")
            texture.image = image
            tree.links.new(texture.outputs[0], bsdf.inputs[socket])
            if socket == "Emission Color":
                bsdf.inputs["Emission Strength"].default_value = 1.0
            obj.data.materials.append(material)

    def _export(self, version):
        from validate import validate_xml_file, validate_with_x3d_py
        path = os.path.join(self.tmpdir, f"shared_{version}.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version=version, use_selection=False),
                         {"FINISHED"})
        if version == "X3D40":
            result = validate_xml_file(path)
            self.assertTrue(result.valid, result.errors)
            semantic = validate_with_x3d_py(path)
            if semantic is not None:
                self.assertEqual(semantic.errors, [])
        return path, ET.parse(path).getroot()

    def test_shared_image_is_written_once_and_used(self):
        _path, root = self._export("X3D40")
        textures = list(root.iter("ImageTexture"))
        defined = [node for node in textures if "url" in node.attrib]
        used = [node for node in textures if "USE" in node.attrib]
        self.assertEqual(len(defined), 1, [node.attrib for node in textures])
        self.assertEqual(len(used), 2)
        self.assertTrue(all(node.attrib["USE"] == defined[0].attrib["DEF"] for node in used))
        roles = sorted(node.attrib.get("containerField") for node in textures)
        self.assertEqual(roles, ["baseTexture", "baseTexture", "emissiveTexture"])

    def test_roles_survive_the_round_trip(self):
        path, _root = self._export("X3D40")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmpdir)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
        found = {}
        for obj in bpy.context.scene.objects:
            if obj.type != "MESH" or not obj.data.materials:
                continue
            tree = obj.data.materials[0].node_tree
            bsdf = next(node for node in tree.nodes if node.type == "BSDF_PRINCIPLED")
            linked = {socket: _upstream_image(bsdf.inputs[socket]) for socket in ("Base Color", "Emission Color")}
            found[obj.name.split(".")[0]] = linked
        self.assertTrue(found["BaseA"]["Base Color"] and found["BaseA"]["Base Color"].endswith("shared.png"), found)
        self.assertTrue(found["BaseB"]["Base Color"] and found["BaseB"]["Base Color"].endswith("shared.png"), found)
        self.assertTrue(found["Glow"]["Emission Color"] and found["Glow"]["Emission Color"].endswith("shared.png"), found)
        self.assertIsNone(found["Glow"]["Base Color"])

    def test_classic_material_path_shares_the_texture_too(self):
        from validate import validate_xml_file
        path = os.path.join(self.tmpdir, "classic.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False,
                                                  material_model="CLASSIC"), {"FINISHED"})
        result = validate_xml_file(path)
        self.assertTrue(result.valid, result.errors)
        textures = list(ET.parse(path).getroot().iter("ImageTexture"))
        self.assertEqual(sum(1 for node in textures if "url" in node.attrib), 1, [n.attrib for n in textures])
        self.assertEqual(sum(1 for node in textures if "USE" in node.attrib), len(textures) - 1)

if __name__ == "__main__":
    unittest.main()
