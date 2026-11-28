# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""X3D lighting import option (source/x3d_phong.py): X3D 4.0 Phong lighting in EEVEE, held to the spec oracle.

The ladder (tests/lighting/limits.json): every probe scene in tests/lighting/fixtures rendered by EEVEE at 64 x 64 must
land on tools/lighting_oracle.py's picture, in the reading it was imported with, within blender_exact's limits; the
default import (the wrong twin) must miss it; the headlight is a sun on the camera that neither X3D writer exports.
docs/LIGHTING.md has the browsers' side (X_ITE 16.8.1, X3DOM 1.8.3).

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_x3d_phong_bpy
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
FIXTURES = ROOT / "tests" / "lighting" / "fixtures"
LIMITS = json.loads((ROOT / "tests" / "lighting" / "limits.json").read_text())
VERSIONS = ("X3D33", "X3D40")
READING_OF = {"LINEAR_VALUES": "linear-values", "DISPLAY": "display", "SRGB_DECODED": "linear"}


def _render(scene_name, option, engine="BLENDER_EEVEE"):
    import lighting_blender_record as recorder
    import numpy as np
    from PIL import Image
    out = Path(tempfile.mkdtemp(prefix="x3d_phong_")) / f"{scene_name}.png"
    recorder.render(FIXTURES / f"{scene_name}.x3d", option, engine, out)
    return np.asarray(Image.open(out).convert("RGB"))


@unittest.skipUnless(HAVE_BPY, "bpy not importable")
class Ladder(unittest.TestCase):
    """Each committed probe scene, in each reading, against the oracle (gates blender_linear_values, blender_display,
    blender_exact)."""

    @classmethod
    def setUpClass(cls):
        import lighting_blender_record as recorder
        recorder._register()

    def check(self, option, gate):
        import lighting_judge as judge
        limits = LIMITS["gates"][gate]
        for scene_name in LIMITS["scenes"] + ["headlight"]:
            with self.subTest(scene=scene_name, reading=option):
                result = judge.compare(_render(scene_name, option), scene_name, READING_OF[option], "srgb")
                self.assertLessEqual(result["mean"], limits["mean_max"], result)
                self.assertLessEqual(result["p99"], limits["p99_max"], result)

    def test_linear_values(self):
        self.check("LINEAR_VALUES", "blender_linear_values")

    def test_display(self):
        self.check("DISPLAY", "blender_display")

    def test_srgb_decoded(self):
        self.check("SRGB_DECODED", "blender_exact")

    def test_physical_material(self):
        """PhysicalMaterial (X3D 4.0 17.2.2.6): the spec reading, in every Phong reading (its colours are linear)."""
        import lighting_judge as judge
        import lighting_oracle as oracle
        part = LIMITS["physical"]
        gate = part["gates"]["blender_physical"]
        for option in ("LINEAR_VALUES", "SRGB_DECODED"):
            for scene_name in part["scenes"]:
                with self.subTest(scene=scene_name, reading=option):
                    result = judge.physical_compare(_render(scene_name, option), scene_name, oracle.SPEC_KNOBS, "srgb")
                    self.assertLessEqual(result["mean"], gate["mean_max"], result)
                    self.assertLessEqual(result["p99"], gate["p99_max"], result)


@unittest.skipUnless(HAVE_BPY, "bpy not importable")
class WrongTwin(unittest.TestCase):
    """The default import must miss the oracle on falloff and cone scenes, or the probes catch nothing."""

    @classmethod
    def setUpClass(cls):
        import lighting_blender_record as recorder
        recorder._register()

    def test_default_import_misses_physical(self):
        import lighting_judge as judge
        import lighting_oracle as oracle
        gate = LIMITS["physical"]["gates"]["wrong_twin_physical_default"]
        worst = max(judge.physical_compare(_render(scene_name, "OFF"), scene_name, oracle.SPEC_KNOBS, "srgb")["p99"]
                    for scene_name in gate["scenes"])
        self.assertGreaterEqual(worst, gate["p99_min"])

    def test_default_import_misses(self):
        import lighting_judge as judge
        gate = LIMITS["gates"]["wrong_twin_default_import"]
        for scene_name in gate["scenes"]:
            with self.subTest(scene=scene_name):
                result = judge.compare(_render(scene_name, "OFF"), scene_name, "linear-values", "srgb")
                self.assertGreaterEqual(result["mean"], gate["mean_min"], result)


@unittest.skipUnless(HAVE_BPY, "bpy not importable")
class Import(unittest.TestCase):
    """What the option makes, and what it leaves alone."""

    @classmethod
    def setUpClass(cls):
        import lighting_blender_record as recorder
        recorder._register()

    def load(self, scene_name, option):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=str(FIXTURES / f"{scene_name}.x3d"), x3d_lighting=option),
                         {'FINISHED'})
        return bpy.context.scene

    def test_off_by_default(self):
        scene = self.load("spot", "AUTO")
        self.assertNotIn("X3D Phong", bpy.data.node_groups)
        self.assertFalse(any(key.startswith("x3d_phong") for ob in scene.objects for key in ob.keys()))
        self.assertNotIn("x3d_phong_reading", scene)

    def test_outputs_and_light_fields(self):
        scene = self.load("spot", "LINEAR_VALUES")
        material = bpy.data.materials["Shape"]
        targets = sorted(node.target for node in material.node_tree.nodes if node.bl_idname == 'ShaderNodeOutputMaterial')
        self.assertEqual(targets, ['CYCLES', 'EEVEE'])   # Cycles keeps the Principled BSDF
        spot = next(ob for ob in scene.objects if ob.type == 'LIGHT' and not ob.get("x3d_phong_headlight"))
        self.assertEqual(spot["x3d_phong_kind"], 3)
        self.assertAlmostEqual(spot["x3d_phong_cutoff"], 0.5)
        self.assertAlmostEqual(spot["x3d_phong_beam"], 0.25)
        self.assertEqual(list(spot["x3d_phong_color"]), [1.0, 0.8, 0.5])     # linear values: the file's numbers
        self.assertEqual(scene.view_settings.view_transform, 'Standard')

    def test_display_is_raw_and_decoded_is_linear(self):
        scene = self.load("spot", "DISPLAY")
        self.assertEqual(scene.view_settings.view_transform, 'Raw')
        scene = self.load("spot", "SRGB_DECODED")
        spot = next(ob for ob in scene.objects if ob.type == 'LIGHT' and not ob.get("x3d_phong_headlight"))
        self.assertAlmostEqual(spot["x3d_phong_color"][1], ((0.8 + 0.055) / 1.055) ** 2.4, places=6)

    def test_turned_spot_follows(self):
        """The cone direction is a property: the depsgraph handler keeps it where the light points."""
        from mathutils import Vector
        scene = self.load("spot", "LINEAR_VALUES")
        spot = next(ob for ob in scene.objects if ob.type == 'LIGHT' and not ob.get("x3d_phong_headlight"))
        spot.rotation_euler.x += 0.3
        bpy.context.view_layer.update()
        axis = (spot.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
        for got, want in zip(spot["x3d_phong_axis"], axis):
            self.assertAlmostEqual(got, want, places=5)

    def test_headlight_is_a_camera_sun_the_writers_skip(self):
        scene = self.load("headlight", "LINEAR_VALUES")
        suns = [ob for ob in scene.objects if ob.get("x3d_phong_headlight")]
        self.assertEqual(len(suns), 1)
        self.assertEqual(suns[0].parent.type, 'CAMERA')
        self.assertGreater(suns[0].data.energy, 0.0)        # EEVEE drops a light of energy 0 from its loop
        self.assertLess(suns[0].data.energy, 1e-5)          # and Cycles must not see it
        for version in VERSIONS:
            with self.subTest(version=version):
                path = Path(tempfile.mkdtemp(prefix="x3d_phong_rt_")) / "out.x3d"
                self.assertEqual(bpy.ops.export_scene.x3d(filepath=str(path), use_selection=False,
                                                          x3d_version=version), {'FINISHED'})
                text = path.read_text()
                self.assertEqual(re.findall(r"<(?:Directional|Point|Spot)Light\b", text), [])
                self.assertNotIn("x3d_phong", text)

    def test_no_headlight_when_the_file_turns_it_off(self):
        scene = self.load("two-lights", "LINEAR_VALUES")
        self.assertFalse(any(ob.get("x3d_phong_headlight") for ob in scene.objects))


if __name__ == "__main__":
    unittest.main()
