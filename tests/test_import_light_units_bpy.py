# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Importer: light units, so a glTF viewer lights an X3D scene the way X_ITE does.

X_ITE 16.7.1 lights a PhysicalMaterial the glTF way (1/d^2, colour / pi) and a classic Material without
falloff, in display space. The 'X_ITE' light units give each light the energy that draws the same in a
glTF viewer; 'BLENDER' keeps the old 1.75 W per unit. Measured in headless Chrome 153 (SwiftShader),
X_ITE 16.7.1 on the X3D against Babylon.js 9.32.0 on the glb (centre patch, 0-255):

    classic DirectionalLight i=1     204 vs 120 (BLENDER)  ->  204 vs 203 (X_ITE)
    physical PointLight 1, 1 0 0      74 vs  30             ->   74 vs  74

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_import_light_units_bpy
"""

from __future__ import annotations

import json
import math
import os
import struct
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension

HEADER = ("<?xml version='1.0' encoding='UTF-8'?>\n"
          "<X3D profile='Immersive' version='4.0'><Scene>\n<NavigationInfo headlight='false'/>\n")
FOOTER = "</Scene></X3D>\n"
PHYSICAL = "<PhysicalMaterial baseColor='0.8 0.8 0.8' metallic='0' roughness='1'/>"
CLASSIC = "<Material diffuseColor='0.8 0.8 0.8'/>"
K = 4.0 * math.pi                     # Blender watts per COMPAT candela (io_scene_gltf2, point and spot)


def lin(value):
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _box(material, x=0.0, y=0.0, z=0.0, name="Box"):
    return (f"<Transform translation='{x} {y} {z}'><Shape DEF='{name}'><Appearance>{material}</Appearance>"
            f"<Box size='1 1 0.1'/></Shape></Transform>\n")


def _glb_lights(path):
    """KHR_lights_punctual lights of a glb, by name."""
    data = Path(path).read_bytes()
    length = struct.unpack_from("<I", data, 12)[0]
    gltf = json.loads(data[20:20 + length])
    return {light.get("name"): light for light in gltf.get("extensions", {}).get("KHR_lights_punctual", {}).get("lights", [])}


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ImportLightUnitsTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_light_units_")
        _register_extension(self.tmpdir)
        self._env = {key: os.environ.pop(key, None) for key in ("BLENDER_X3D_LIGHT_UNITS", "BLENDER_X3D_COLOR_SPACE")}

    def tearDown(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _import(self, body, **options):
        import bpy
        path = os.path.join(self.tmpdir, "scene.x3d")
        Path(path).write_text(HEADER + body + FOOTER, encoding="utf-8")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path, **options), {"FINISHED"})
        return {obj.name: obj.data for obj in bpy.context.scene.objects if obj.type == "LIGHT"}

    # --- physical scenes: X_ITE already falls off as 1/d^2, so the candela is the intensity ---------------------

    def test_physical_point_light_is_intensity_candela(self):
        lights = self._import("<PointLight DEF='Lamp' location='0 0 5' intensity='1.2' radius='40' global='true'/>\n"
                              + _box(PHYSICAL, z=3), light_units='X_ITE')
        lamp = lights["Lamp"]
        self.assertAlmostEqual(lamp.energy, K * 1.2, places=4)
        self.assertTrue(lamp.use_custom_distance)
        self.assertAlmostEqual(lamp.cutoff_distance, 40.0, places=4)
        import bpy
        self.assertEqual(bpy.context.scene["x3d_lighting_model"], "physical")
        self.assertAlmostEqual(bpy.context.scene["x3d_headlight_lux"], 1.0, places=6)

    def test_physical_quadratic_attenuation_matches_at_the_reference_distance(self):
        lights = self._import("<PointLight DEF='Lamp' location='0 0 5' intensity='1' attenuation='1 0 0.2' "
                              "global='true'/>\n" + _box(PHYSICAL, z=3), light_units='X_ITE')
        lamp = lights["Lamp"]
        self.assertAlmostEqual(lamp["x3d_reference_distance"], 2.0, places=4)
        self.assertAlmostEqual(lamp.energy, K / (1.0 + 0.2 * 4.0), places=4)
        self.assertEqual(list(lamp["x3d_attenuation"]), [1.0, 0.0, 0.2])

    def test_physical_directional_light_is_unchanged(self):
        lights = self._import("<DirectionalLight DEF='Sun' intensity='0.3' global='true'/>\n" + _box(PHYSICAL),
                              light_units='X_ITE')
        self.assertAlmostEqual(lights["Sun"].energy, 0.3, places=6)

    # --- classic scenes: no falloff, lit in display space ---------------------------------------------------------

    def test_classic_directional_light_at_one_is_pi(self):
        lights = self._import("<DirectionalLight DEF='Sun' intensity='1' global='true'/>\n"
                              "<DirectionalLight DEF='Dim' intensity='0.5' global='true'/>\n" + _box(CLASSIC),
                              light_units='X_ITE')
        self.assertAlmostEqual(lights["Sun"].energy, math.pi, places=5)
        self.assertAlmostEqual(lights["Dim"].energy, math.pi * lin(0.5), places=5)
        import bpy
        self.assertEqual(bpy.context.scene["x3d_lighting_model"], "classic")
        self.assertAlmostEqual(bpy.context.scene["x3d_headlight_lux"], math.pi, places=5)

    def test_classic_point_light_is_matched_at_the_median_distance(self):
        # boxes 1, 3 and 6 m away (centres): the median is 3 m
        body = ("<PointLight DEF='Lamp' location='0 0 0' intensity='0.8' global='true'/>\n"
                + _box(CLASSIC, z=-1, name="A") + _box(CLASSIC, z=-3, name="B") + _box(CLASSIC, z=-6, name="C"))
        lamp = self._import(body, light_units='X_ITE')["Lamp"]
        self.assertAlmostEqual(lamp["x3d_reference_distance"], 3.0, places=4)
        self.assertAlmostEqual(lamp.energy, K * math.pi * lin(0.8) * 9.0, places=3)

    def test_reference_distance_skips_surfaces_beyond_the_radius(self):
        body = ("<PointLight DEF='Lamp' location='0 0 0' intensity='1' radius='5' global='true'/>\n"
                + _box(CLASSIC, z=-2, name="Near") + _box(CLASSIC, z=-50, name="Far1") + _box(CLASSIC, z=-60, name="Far2"))
        lamp = self._import(body, light_units='X_ITE')["Lamp"]
        self.assertAlmostEqual(lamp["x3d_reference_distance"], 2.0, places=4)

    def test_majority_decides_the_lighting_model(self):
        body = ("<DirectionalLight DEF='Sun' intensity='1' global='true'/>\n" + _box(PHYSICAL, name="P1")
                + _box(PHYSICAL, x=2, name="P2") + _box(CLASSIC, x=4, name="C1"))
        self.assertAlmostEqual(self._import(body, light_units='X_ITE')["Sun"].energy, 1.0, places=6)

    def test_dark_light_keeps_its_scale(self):
        # the material odyssey starts its lights at 0 and a script raises them
        lamp = self._import("<PointLight DEF='Lamp' location='0 0 5' intensity='0' global='true'/>\n"
                            + _box(PHYSICAL, z=3), light_units='X_ITE')["Lamp"]
        self.assertEqual(lamp.energy, 0.0)
        self.assertAlmostEqual(lamp["x3d_energy_per_intensity"], K, places=4)

    # --- option resolution --------------------------------------------------------------------------------------

    def test_blender_units_are_the_old_scale(self):
        lights = self._import("<PointLight DEF='Lamp' intensity='2' global='true'/>\n"
                              "<DirectionalLight DEF='Sun' intensity='1' global='true'/>\n" + _box(CLASSIC),
                              light_units='BLENDER')
        self.assertAlmostEqual(lights["Lamp"].energy, 3.5, places=5)
        self.assertAlmostEqual(lights["Sun"].energy, 1.0, places=6)
        self.assertNotIn("x3d_energy_per_intensity", lights["Lamp"])
        self.assertFalse(lights["Lamp"].use_custom_distance)

    def test_auto_follows_the_colour_space(self):
        body = "<DirectionalLight DEF='Sun' intensity='1' global='true'/>\n" + _box(CLASSIC)
        self.assertAlmostEqual(self._import(body)["Sun"].energy, 1.0, places=6)              # AS_IS -> BLENDER
        self.assertAlmostEqual(self._import(body, color_space='SRGB')["Sun"].energy, math.pi, places=5)
        os.environ["BLENDER_X3D_COLOR_SPACE"] = "SRGB"
        self.assertAlmostEqual(self._import(body)["Sun"].energy, math.pi, places=5)
        os.environ["BLENDER_X3D_LIGHT_UNITS"] = "BLENDER"                                   # explicit wins
        self.assertAlmostEqual(self._import(body)["Sun"].energy, 1.0, places=6)

    # --- what leaves Blender ------------------------------------------------------------------------------------

    def test_glb_carries_the_x_ite_intensities_and_the_radius_as_range(self):
        import bpy
        self._import("<PointLight DEF='Lamp' location='0 0 5' intensity='1.2' radius='40' global='true'/>\n"
                     "<DirectionalLight DEF='Sun' intensity='0.3' global='true'/>\n" + _box(PHYSICAL, z=3),
                     light_units='X_ITE')
        glb = os.path.join(self.tmpdir, "scene.glb")
        bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB", export_lights=True,
                                  export_import_convert_lighting_mode="COMPAT")
        lights = _glb_lights(glb)
        self.assertAlmostEqual(lights["Lamp"]["intensity"], 1.2, places=4)
        self.assertAlmostEqual(lights["Lamp"]["range"], 40.0, places=4)
        self.assertAlmostEqual(lights["Sun"]["intensity"], 0.3, places=4)

    def test_x3d_exports_write_the_file_values_back(self):
        import bpy
        self._import("<PointLight DEF='Lamp' location='0 0 0' intensity='0.8' attenuation='1 0 0.02' radius='14' "
                     "global='true'/>\n<SpotLight DEF='Spot' location='0 0 0' intensity='0.6' global='true'/>\n"
                     "<DirectionalLight DEF='Sun' intensity='0.9' global='true'/>\n"
                     + _box(CLASSIC, z=-2) + _box(CLASSIC, z=-4, name="B"), light_units='X_ITE')
        for version in ("X3D40", "X3D33"):
            path = os.path.join(self.tmpdir, "back_%s.x3d" % version)
            self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version=version, use_selection=False),
                             {"FINISHED"})
            root = ET.parse(path).getroot()
            point = root.find(".//PointLight").attrib
            self.assertAlmostEqual(float(point["intensity"]), 0.8, places=3, msg=version)
            self.assertEqual([round(float(v), 4) for v in point["attenuation"].replace(",", " ").split()],
                             [1.0, 0.0, 0.02], msg=version)
            self.assertAlmostEqual(float(point["radius"]), 14.0, places=3, msg=version)
            self.assertAlmostEqual(float(root.find(".//SpotLight").attrib["intensity"]), 0.6, places=3, msg=version)
            self.assertAlmostEqual(float(root.find(".//DirectionalLight").attrib["intensity"]), 0.9, places=3,
                                   msg=version)


if __name__ == "__main__":
    unittest.main()
