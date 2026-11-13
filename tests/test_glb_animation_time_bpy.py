# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""glb animation time: X3D time 0 must be glTF time 0.

The importer puts X3D time 0 on ``scene.frame_start`` (1 in a factory scene) and Blender's glTF exporter writes
``frame / fps``, so a glb exported straight after the import runs one frame (1/24 s) late against the X3D. The fidelity
rig's Blender leg sets ``frame_start = 0`` before importing; this test pins both halves, measured with Blender's own
exporter so a change in either shows up here.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_glb_animation_time_bpy
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension

X3D = """<?xml version='1.0' encoding='UTF-8'?>
<X3D profile='Immersive' version='4.0'><Scene>
<Transform DEF='TR'><Shape><Appearance><Material diffuseColor='0.8 0.2 0.2'/></Appearance><Box size='1 1 1'/></Shape></Transform>
<TimeSensor DEF='TS' cycleInterval='2' loop='true'/>
<PositionInterpolator DEF='PI' key='0 0.5 1' keyValue='0 0 0, 2 0 0, 4 0 0'/>
<ROUTE fromNode='TS' fromField='fraction_changed' toNode='PI' toField='set_fraction'/>
<ROUTE fromNode='PI' fromField='value_changed' toNode='TR' toField='set_translation'/>
</Scene></X3D>
"""


def _glb_json_and_bin(path):
    data = Path(path).read_bytes()
    (json_len,) = struct.unpack_from("<I", data, 12)
    doc = json.loads(data[20:20 + json_len])
    return doc, data[28 + json_len:]


def _sampler_times(path):
    """Input (time) values of the first animation sampler in the glb."""
    doc, blob = _glb_json_and_bin(path)
    acc = doc["accessors"][doc["animations"][0]["samplers"][0]["input"]]
    view = doc["bufferViews"][acc["bufferView"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    return list(struct.unpack_from("<%df" % acc["count"], blob, start))


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class GlbAnimationTimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_glb_time_")
        _register_extension(cls.tmpdir)
        cls.x3d = os.path.join(cls.tmpdir, "anim.x3d")
        Path(cls.x3d).write_text(X3D)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _glb(self, frame_start):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.context.scene.frame_start = frame_start
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=self.x3d), {"FINISHED"})
        path = os.path.join(self.tmpdir, "anim_%d.glb" % frame_start)
        # blender_leg.py's glTF settings
        self.assertEqual(bpy.ops.export_scene.gltf(
            filepath=path, export_format="GLB", export_lights=True, export_cameras=True,
            export_import_convert_lighting_mode="COMPAT", use_renderable=True, export_yup=True,
            export_apply=True, use_mesh_edges=True, use_mesh_vertices=True), {"FINISHED"})
        return path, 1.0 / bpy.context.scene.render.fps

    def test_frame_start_0_puts_x3d_time_0_at_glb_time_0(self):
        path, frame = self._glb(0)
        times = _sampler_times(path)
        self.assertAlmostEqual(times[0], 0.0, places=6)
        self.assertAlmostEqual(times[-1], 2.0, places=3)   # cycleInterval 2

    def test_frame_start_1_runs_one_frame_late(self):
        path, frame = self._glb(1)
        times = _sampler_times(path)
        self.assertAlmostEqual(times[0], frame, places=6)   # 1/24 s: the importer's default offset


if __name__ == "__main__":
    unittest.main()
