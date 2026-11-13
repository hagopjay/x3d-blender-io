# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Importer: the file's DEF names are kept as ``x3d_def`` custom properties, and reach glTF node extras.

Blender suffixes a duplicate name (a USE'd Shape becomes ``BoxShape.001``) and the flat import makes no object for
a Transform, so the object name alone is not the DEF. ``x3d_def`` (the node's DEF, or the nearest DEF'd Transform
above it), ``x3d_def_path`` (the DEF'd ancestors) and ``x3d_use`` (the DEF a USE points at) keep it; the glTF
exporter copies custom properties to extras when ``export_extras`` is set.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_import_identity_bpy
"""

from __future__ import annotations

import json
import os
import struct
import tempfile
import unittest

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension

X3D = """<?xml version='1.0' encoding='UTF-8'?>
<X3D profile='Immersive' version='4.0'><Scene>
  <Viewpoint DEF='CamMain' position='0 1 10'/>
  <PointLight DEF='LampKey' location='2 4 2'/>
  <Transform DEF='Outer' translation='1 0 0'>
    <Transform DEF='Inner' translation='0 2 0'>
      <Shape DEF='BoxShape'>
        <Appearance DEF='RedApp'><Material DEF='RedMat' diffuseColor='1 0 0'/></Appearance>
        <Box DEF='BoxGeom'/>
      </Shape>
    </Transform>
    <Transform DEF='Sibling' translation='3 0 0'><Shape USE='BoxShape'/></Transform>
  </Transform>
  <Transform DEF='Third' translation='-3 0 0'><Shape><Appearance USE='RedApp'/><Sphere/></Shape></Transform>
</Scene></X3D>
"""


def _glb_json(path: str) -> dict:
    with open(path, "rb") as f:
        data = f.read()
    length = struct.unpack("<I", data[12:16])[0]
    return json.loads(data[20:20 + length])


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class IdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_identity_")
        _register_extension(cls.tmpdir)
        cls.path = os.path.join(cls.tmpdir, "identity.x3d")
        with open(cls.path, "w", encoding="utf-8") as f:
            f.write(X3D)

    def _import(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=self.path), {"FINISHED"})
        return {o.name: o for o in bpy.data.objects}

    def test_objects_carry_their_def(self):
        objs = self._import()
        self.assertEqual(objs["CamMain"]["x3d_def"], "CamMain")
        self.assertEqual(objs["LampKey"]["x3d_def"], "LampKey")
        self.assertEqual(objs["BoxShape"]["x3d_def"], "BoxShape")
        self.assertEqual(objs["BoxShape"]["x3d_def_path"], "Outer/Inner")   # the Transforms flat import drops
        self.assertNotIn("x3d_use", objs["BoxShape"])
        self.assertEqual(objs["Third"]["x3d_def"], "Third")                 # a Shape without a DEF: its Transform's

    def test_use_instance_is_its_own_def_not_the_blender_suffix(self):
        objs = self._import()
        use = objs["BoxShape.001"]
        self.assertEqual(use["x3d_def"], "Sibling")
        self.assertEqual(use["x3d_def_path"], "Outer/Sibling")
        self.assertEqual(use["x3d_use"], "BoxShape")
        self.assertIs(use.data, objs["BoxShape"].data)                      # still one shared mesh

    def test_data_blocks_carry_their_def(self):
        objs = self._import()
        self.assertEqual(objs["BoxShape"].data["x3d_def"], "BoxGeom")
        self.assertEqual(bpy.data.materials["RedMat"]["x3d_def"], "RedMat")

    def test_two_imports_name_things_alike(self):
        def snapshot():
            return sorted((n, o.get("x3d_def"), o.get("x3d_def_path"), o.get("x3d_use")) for n, o in self._import().items())
        self.assertEqual(snapshot(), snapshot())

    def test_def_reaches_gltf_extras(self):
        self._import()
        out = os.path.join(self.tmpdir, "identity.glb")
        bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_cameras=True, export_lights=True,
                                  export_extras=True, use_renderable=True)
        gltf = _glb_json(out)
        by_name = {n["name"]: n.get("extras", {}) for n in gltf["nodes"]}
        self.assertEqual(by_name["BoxShape"]["x3d_def"], "BoxShape")
        self.assertEqual(by_name["BoxShape.001"]["x3d_def"], "Sibling")
        self.assertEqual(by_name["BoxShape.001"]["x3d_use"], "BoxShape")
        self.assertEqual(by_name["CamMain"]["x3d_def"], "CamMain")
        self.assertEqual(by_name["LampKey"]["x3d_def"], "LampKey")
        self.assertEqual(gltf["meshes"][0]["extras"]["x3d_def"], "BoxGeom")
        self.assertEqual(gltf["materials"][0]["extras"]["x3d_def"], "RedMat")
        self.assertEqual(len(gltf["meshes"]), 2)    # the USE'd Box is one mesh on two nodes
        self.assertEqual(sum(1 for n in gltf["nodes"] if n.get("mesh") == 0), 2)


if __name__ == "__main__":
    unittest.main()
