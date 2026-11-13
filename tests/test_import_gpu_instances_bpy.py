# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Group instances: objects that share one mesh are parented to an Empty so the glTF exporter writes EXT_mesh_gpu_instancing.

The import is flat, so a Group (or a Transform with a USE under it) left its instances as scene roots, and Blender's
glTF exporter (``export_gpu_instances``) only turns *children of one Empty that share a mesh* into an instance list: the
THALASSA scene (1,719 instances of 8 shapes) came out of the exporter as 1,721 nodes and no extension. With the
option the Empty is the holder and the glb has one node per mesh with TRANSLATION / ROTATION / SCALE accessors; world
matrices do not change (the Empty is the identity).

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_import_gpu_instances_bpy
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

N = 5
SCENE = ("<?xml version='1.0' encoding='UTF-8'?>\n<X3D profile='Full' version='4.0'><Scene><Group>"
         + "".join("<Transform translation='%d 0 0' rotation='0 1 0 %.3f' scale='1 %d 1'><Shape %s>"
                   "<Appearance><Material diffuseColor='0.2 0.4 0.6'/></Appearance><Box size='1 1 1'/></Shape></Transform>"
                   % (i * 2, 0.2 * i, i + 1, "DEF='Cube'" if i == 0 else "USE='Cube'") for i in range(N))
         + "</Group><Transform translation='0 5 0'><Shape><Appearance><Material diffuseColor='1 0 0'/></Appearance>"
           "<Sphere radius='0.5'/></Shape></Transform></Scene></X3D>\n")


def _glb_json(path):
    with open(path, "rb") as f:
        raw = f.read()
    return json.loads(raw[20:20 + struct.unpack("<I", raw[12:16])[0]])


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class GpuInstancesTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_gpu_instances_")
        _register_extension(cls.tmpdir)
        cls.path = os.path.join(cls.tmpdir, "in.x3d")
        with open(cls.path, "w", encoding="utf-8") as handle:
            handle.write(SCENE)

    def load(self, **options):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmpdir)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=self.path, **options), {"FINISHED"})
        return {ob.name: ob for ob in bpy.data.objects}

    def export(self, name, gpu):
        out = os.path.join(self.tmpdir, name + ".glb")
        bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_gpu_instances=gpu)
        return _glb_json(out)

    def test_off_by_default_leaves_every_instance_a_root(self):
        objects = self.load()
        self.assertEqual([ob.name for ob in objects.values() if ob.type == "EMPTY"], [])
        self.assertTrue(all(ob.parent is None for ob in objects.values()))
        gltf = self.export("off", True)
        self.assertNotIn("EXT_mesh_gpu_instancing", gltf.get("extensionsUsed", []))   # the exporter alone finds nothing

    def test_the_option_parents_a_shared_mesh_to_one_empty_and_moves_nothing(self):
        flat = {n: ob.matrix_world.copy() for n, ob in self.load().items()}
        objects = self.load(gpu_instances=True)
        holders = [ob for ob in objects.values() if ob.type == "EMPTY"]
        self.assertEqual([h.name for h in holders], [holders[0].name])
        self.assertTrue(holders[0].name.endswith(".instances"))
        self.assertEqual(holders[0].get("x3d_instance_group"), holders[0].name[:-len(".instances")])
        members = [ob for ob in objects.values() if ob.parent is holders[0]]
        self.assertEqual(len(members), N)                          # the sphere is a single instance: left alone
        self.assertIsNone(objects["Shape"].parent if "Shape" in objects else None)
        for name, matrix in flat.items():
            for row_a, row_b in zip(objects[name].matrix_world, matrix):
                for a, b in zip(row_a, row_b):
                    self.assertAlmostEqual(a, b, places=5, msg=name)

    def test_the_environment_variable_turns_it_on(self):
        os.environ["BLENDER_X3D_GPU_INSTANCES"] = "1"
        try:
            objects = self.load()
        finally:
            del os.environ["BLENDER_X3D_GPU_INSTANCES"]
        self.assertEqual(len([ob for ob in objects.values() if ob.type == "EMPTY"]), 1)

    def test_blenders_exporter_writes_one_instance_list(self):
        self.load(gpu_instances=True)
        gltf = self.export("on", True)
        self.assertIn("EXT_mesh_gpu_instancing", gltf["extensionsUsed"])
        holders = [n for n in gltf["nodes"] if "EXT_mesh_gpu_instancing" in n.get("extensions", {})]
        self.assertEqual(len(holders), 1)
        attributes = holders[0]["extensions"]["EXT_mesh_gpu_instancing"]["attributes"]
        self.assertEqual({gltf["accessors"][a]["count"] for a in attributes.values()}, {N})
        self.assertEqual(len([n for n in gltf["nodes"] if "mesh" in n]), 2)   # the holder and the lone sphere


if __name__ == "__main__":
    unittest.main()
