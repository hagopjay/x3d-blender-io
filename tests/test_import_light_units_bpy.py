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

import base64
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
# A classic scene's lights are fitted to what X_ITE draws on the faces the first Viewpoint (here X3D's default view,
# from 0 0 10 down -z) sees: on one face of sRGB albedo a lit at level S (the sum of what each light gives there, and 1
# for a headlight that is on) that is f = pi lin(a S) / (A S), A = lin(a) for sRGB colours, while a S < 1.


def lin(value):
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def factor(total, albedo=0.8, srgb=True):
    return math.pi * lin(albedo * total) / ((lin(albedo) if srgb else albedo) * total)


def srgb(value):
    value = max(0.0, value)
    return 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1.0 / 2.4) - 0.055


def window(distance, reach):
    # the range window Babylon.js 9.32 draws a KHR_lights_punctual range with: computeDistanceLightFalloff_GLTF
    # (babylon.max.js) squares saturate(1 - (d / r)^4), where the extension's recommended formula does not; this helper
    # was unsquared, so the range test below could not see Babylon draw a light near its radius darker than X_ITE
    return max(0.0, min(1.0, 1.0 - (distance / reach) ** 4)) ** 2


def face_means(candela, depth, reach, albedo=0.8, cells=32):
    """(X_ITE, Babylon) mean display value over a 1 m x 1 m face `depth` below a point light of `candela` (in glTF):
    X_ITE draws albedo x cos within the radius with no falloff (x_ite.js line 66922), Babylon srgb(lin(albedo) x
    candela x cos x window / d^2 / pi), with its squared range window."""
    xite = gltf = 0.0
    for row in range(cells):
        for column in range(cells):
            x, y = (column + 0.5) / cells - 0.5, (row + 0.5) / cells - 0.5
            distance = math.sqrt(x * x + y * y + depth * depth)
            cosine = depth / distance
            xite += albedo * cosine if distance <= reach else 0.0
            gltf += srgb(lin(albedo) * candela * cosine * window(distance, reach) / distance ** 2 / math.pi)
    return xite / cells ** 2, gltf / cells ** 2


# one triangle, so an Inline can load a glTF without a file on disk beside the test
TRIANGLE_GLTF = json.dumps({
    "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
    "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
    "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3",
                   "min": [0, 0, 0], "max": [1, 1, 0]}],
    "bufferViews": [{"buffer": 0, "byteLength": 36}],
    "buffers": [{"byteLength": 36, "uri": "data:application/octet-stream;base64,"
                 + base64.b64encode(struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)).decode()}]})


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

    def _import(self, body, header=HEADER, **options):
        import bpy
        path = os.path.join(self.tmpdir, "scene.x3d")
        Path(path).write_text(header + body + FOOTER, encoding="utf-8")
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
        lights = self._import("<DirectionalLight DEF='Sun' intensity='1' global='true'/>\n" + _box(CLASSIC))
        self.assertAlmostEqual(lights["Sun"].energy, math.pi, places=5)
        import bpy
        self.assertEqual(bpy.context.scene["x3d_lighting_model"], "classic")
        self.assertAlmostEqual(bpy.context.scene["x3d_headlight_lux"], math.pi, places=5)

    def test_classic_lights_share_one_factor_so_they_add_up(self):
        # X_ITE adds lights in display space: 0.8 lit by 0.6 + 0.3 shows 0.72. One factor for both lights draws that
        # sum and keeps their 2:1 ratio; a curve per light drew the pair much too dark.
        lights = self._import("<DirectionalLight DEF='Sun' intensity='0.6' global='true'/>\n"
                              "<DirectionalLight DEF='Dim' intensity='0.3' global='true'/>\n" + _box(CLASSIC))
        f = factor(0.9)
        self.assertAlmostEqual(lights["Sun"].energy, 0.6 * f, places=4)
        self.assertAlmostEqual(lights["Dim"].energy, 0.3 * f, places=4)
        import bpy
        self.assertAlmostEqual(bpy.context.scene["x3d_headlight_lux"], f, places=4)

    def test_a_level_x_ite_clips_gets_the_dimmest_factor_that_draws_white(self):
        # 0.8 lit by 1 + 0.5 is 1.2 in X_ITE, clipped to white; anything brighter than white draws the same, so the
        # lights get the least that reaches it, and keep their 2:1 ratio
        lights = self._import("<DirectionalLight DEF='Sun' intensity='1' global='true'/>\n"
                              "<DirectionalLight DEF='Dim' intensity='0.5' global='true'/>\n" + _box(CLASSIC))
        f = math.pi / (lin(0.8) * 1.5)
        self.assertAlmostEqual(lights["Sun"].energy, f, places=3)
        self.assertAlmostEqual(lights["Dim"].energy, 0.5 * f, places=3)

    def test_the_headlight_counts_in_the_classic_level(self):
        # no NavigationInfo: X3D's (and X_ITE's) headlight is on, a DirectionalLight of 1 along the view that adds to
        # the sun on the face the view sees
        header = "<?xml version='1.0' encoding='UTF-8'?>\n<X3D profile='Immersive' version='4.0'><Scene>\n"
        lights = self._import("<DirectionalLight DEF='Sun' intensity='0.1' global='true'/>\n" + _box(CLASSIC),
                              header=header)
        self.assertAlmostEqual(lights["Sun"].energy, 0.1 * factor(1.1), places=4)
        import bpy
        self.assertAlmostEqual(bpy.context.scene["x3d_headlight_lux"], factor(1.1), places=4)

    def test_emissive_colour_adds_in_display_space(self):
        # X_ITE shows emissive 0.3 + 0.5 x 0.4 = 0.5; a glTF viewer adds lin(0.3) to the lit linear albedo
        glowing = "<Material diffuseColor='0.5 0.5 0.5' emissiveColor='0.3 0.3 0.3'/>"
        lights = self._import("<DirectionalLight DEF='Sun' intensity='0.4' global='true'/>\n" + _box(glowing))
        self.assertAlmostEqual(lights["Sun"].energy, math.pi * (lin(0.5) - lin(0.3)) / lin(0.5), places=4)

    def test_classic_light_colour_is_read_as_srgb_and_written_back(self):
        import bpy
        lights = self._import("<DirectionalLight DEF='Sun' color='1 0.5 0.25' intensity='0.5' global='true'/>\n"
                              + _box(CLASSIC))
        self.assertEqual([round(c, 5) for c in lights["Sun"].color], [1.0, round(lin(0.5), 5), round(lin(0.25), 5)])
        self.assertEqual(list(lights["Sun"]["x3d_color"]), [1.0, 0.5, 0.25])
        # X3D 3.3 writes classic Materials: the file's value comes back. X3D 4.0 writes PhysicalMaterials, which
        # X_ITE 16.7.1 lights in linear space (dist/x_ite.js: Punctual2.glsl getLightIntensity, line 67903, returns
        # intensity * light.color, PBR2.glsl multiplies it by the linear baseColor, line 67826): Blender's colour.
        for version, expected in (("X3D40", [1.0, round(lin(0.5), 3), round(lin(0.25), 3)]),
                                  ("X3D33", [1.0, 0.5, 0.25])):
            path = os.path.join(self.tmpdir, "colour_%s.x3d" % version)
            bpy.ops.export_scene.x3d(filepath=path, x3d_version=version, use_selection=False)
            colour = ET.parse(path).getroot().find(".//DirectionalLight").attrib["color"]
            self.assertEqual([round(float(v), 3) for v in colour.replace(",", " ").split()], expected, msg=version)
        lights["Sun"].color = (lin(0.5), lin(0.5), lin(0.5))              # changed in Blender: written as sRGB
        path = os.path.join(self.tmpdir, "colour_changed.x3d")
        bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D33", use_selection=False)
        colour = ET.parse(path).getroot().find(".//DirectionalLight").attrib["color"]
        self.assertEqual([round(float(v), 3) for v in colour.replace(",", " ").split()], [0.5, 0.5, 0.5])

    def test_x3d40_export_writes_the_linear_light_colour_a_physical_import_keeps(self):
        import bpy
        lights = self._import("<PointLight DEF='Lamp' location='0 0 3' color='1 0.5 0.2' global='true'/>\n"
                              + _box(CLASSIC))
        held = tuple(lights["Lamp"].color)
        self.assertAlmostEqual(held[1], lin(0.5), places=5)
        path = os.path.join(self.tmpdir, "linear_light.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False),
                         {"FINISHED"})
        root = ET.parse(path).getroot()
        self.assertIsNotNone(root.find(".//PhysicalMaterial"))
        colour = [float(v) for v in root.find(".//PointLight").attrib["color"].replace(",", " ").split()]
        for got, want in zip(colour, held):
            self.assertAlmostEqual(got, want, places=5)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
        back = [obj.data for obj in bpy.context.scene.objects if obj.type == "LIGHT"]
        self.assertEqual(len(back), 1)
        for got, want in zip(back[0].color, held):
            self.assertAlmostEqual(got, want, places=5)

    def _blender_light_scene(self, colour=(1.0, 0.5, 0.2)):
        """A plane with a grey classic-exported material and a point light made in Blender (no x3d_color)."""
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_plane_add(size=4)
        material = bpy.data.materials.new("Grey")
        bpy.context.object.data.materials.append(material)
        data = bpy.data.lights.new("Lamp", 'POINT')
        data.color = colour
        data.energy = 100.0
        lamp = bpy.data.objects.new("Lamp", data)
        lamp.location = (0.0, 0.0, 3.0)
        bpy.context.scene.collection.objects.link(lamp)
        return data

    def test_blender_light_colour_survives_an_srgb_x3d33_round_trip(self):
        import bpy
        self._blender_light_scene()
        path = os.path.join(self.tmpdir, "blender_light.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D33", use_selection=False),
                         {"FINISHED"})
        colour = ET.parse(path).getroot().find(".//PointLight").attrib["color"]
        for got, want in zip(colour.replace(",", " ").split(), (1.0, srgb(0.5), srgb(0.2))):
            self.assertAlmostEqual(float(got), want, delta=1e-4)                   # sRGB-encoded, like the Material
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
        back = [obj.data for obj in bpy.context.scene.objects if obj.type == "LIGHT"]
        self.assertEqual(len(back), 1)
        for got, want in zip(back[0].color, (1.0, 0.5, 0.2)):
            self.assertAlmostEqual(got, want, places=3)

    def _x3d33_round_trip(self, name, **import_options):
        """Export the current scene as X3D 3.3 with the defaults and import it again: (the written colour, the light's
        Blender colour after the re-import)."""
        import bpy
        path = os.path.join(self.tmpdir, name)
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D33", use_selection=False),
                         {"FINISHED"})
        written = [float(v) for v in ET.parse(path).getroot().find(".//PointLight").attrib["color"].split()]
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path, **import_options), {"FINISHED"})
        back = [obj.data for obj in bpy.context.scene.objects if obj.type == "LIGHT"]
        self.assertEqual(len(back), 1)
        return written, tuple(back[0].color)

    def test_blender_light_units_read_a_classic_light_colour_as_srgb_too(self):
        # the colour space, not the light units, decides how a classic scene's light colours are read, so an sRGB
        # import and export with Light Units Blender gives the file's colour back, and so does a Blender-made light
        lights = self._import("<PointLight DEF='Lamp' location='0 0 3' color='1 0.5 0.2' global='true'/>\n"
                              + _box(CLASSIC), light_units='BLENDER')
        self.assertEqual([round(c, 5) for c in lights["Lamp"].color], [1.0, round(lin(0.5), 5), round(lin(0.2), 5)])
        self.assertEqual([round(c, 6) for c in lights["Lamp"]["x3d_color"]], [1.0, 0.5, 0.2])
        written, _back = self._x3d33_round_trip("blender_units.x3d", light_units='BLENDER')
        self.assertEqual([round(v, 4) for v in written], [1.0, 0.5, 0.2])
        self._blender_light_scene()
        _written, back = self._x3d33_round_trip("blender_units_made.x3d", light_units='BLENDER')
        for got, want in zip(back, (1.0, 0.5, 0.2)):
            self.assertAlmostEqual(got, want, places=3)

    def test_a_light_with_no_classic_material_to_light_is_written_as_is(self):
        # without a Material in the file the re-import is physical and keeps a light colour as given, so the X3D 3.3
        # writer leaves it unencoded and the Blender colour comes back
        import bpy
        self._blender_light_scene()
        plane = next(obj for obj in bpy.context.scene.objects if obj.type == "MESH")
        plane.data.materials.clear()
        written, back = self._x3d33_round_trip("no_material.x3d")
        self.assertEqual([round(v, 4) for v in written], [1.0, 0.5, 0.2])
        for got, want in zip(back, (1.0, 0.5, 0.2)):
            self.assertAlmostEqual(got, want, places=4)

    def test_as_is_x3d33_export_writes_the_blender_light_colour(self):
        import bpy
        self._blender_light_scene()
        path = os.path.join(self.tmpdir, "as_is_blender.x3d")
        bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D33", use_selection=False, color_space='AS_IS')
        colour = ET.parse(path).getroot().find(".//PointLight").attrib["color"]
        self.assertEqual([round(float(v), 4) for v in colour.replace(",", " ").split()], [1.0, 0.5, 0.2])
        # an imported classic light: the Blender (linear) colour, not the file's value kept in x3d_color
        lights = self._import("<PointLight DEF='Lamp' location='0 0 3' color='1 0.5 0.2' global='true'/>\n"
                              + _box(CLASSIC))
        self.assertIn("x3d_color", lights["Lamp"])
        path = os.path.join(self.tmpdir, "as_is_imported.x3d")
        bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D33", use_selection=False, color_space='AS_IS')
        colour = ET.parse(path).getroot().find(".//PointLight").attrib["color"]
        self.assertEqual([round(float(v), 4) for v in colour.replace(",", " ").split()],
                         [1.0, round(lin(0.5), 4), round(lin(0.2), 4)])

    def test_physical_light_colour_is_kept(self):
        lights = self._import("<DirectionalLight DEF='Sun' color='1 0.5 0.25' global='true'/>\n" + _box(PHYSICAL))
        self.assertEqual([round(c, 5) for c in lights["Sun"].color], [1.0, 0.5, 0.25])
        self.assertNotIn("x3d_color", lights["Sun"])

    def test_as_is_colours_use_the_raw_albedo(self):
        # Blender then renders the file's 0.8 as a linear albedo, so the level divides by 0.8, not by lin(0.8)
        lights = self._import("<DirectionalLight DEF='Sun' intensity='1' global='true'/>\n" + _box(CLASSIC),
                              color_space='AS_IS', light_units='X_ITE')
        self.assertAlmostEqual(lights["Sun"].energy, factor(1.0, srgb=False), places=4)

    def test_classic_point_light_is_fitted_on_the_faces_the_view_sees(self):
        # boxes 1, 3 and 6 m away (centres): the median is 3 m, but from X3D's default view box A hides the others,
        # so the light draws what X_ITE draws on A's face 0.95 m away (0.8 x 0.8 = 0.64), not on hidden faces
        body = ("<PointLight DEF='Lamp' location='0 0 0' intensity='0.8' global='true'/>\n"
                + _box(CLASSIC, z=-1, name="A") + _box(CLASSIC, z=-3, name="B") + _box(CLASSIC, z=-6, name="C"))
        lamp = self._import(body)["Lamp"]
        self.assertAlmostEqual(lamp["x3d_reference_distance"], 3.0, places=4)
        lux = lamp.energy / K / 0.95 ** 2 * window(0.95, 100.0)   # at the face's centre (its edges, further, are dimmer)
        self.assertAlmostEqual(srgb(lin(0.8) * lux / math.pi), 0.64, delta=0.03)
        self.assertLess(lamp.energy, K * factor(0.8) * 0.8 * 9.0 / 2.0)          # matched at 3 m, A was overexposed

    def test_classic_light_makes_up_for_the_range_window(self):
        # X_ITE's classic shader cuts off hard at the radius; Babylon fades the range out as (1 - (d / r)^4)^2. Over
        # the face (2.95 m away) that window falls from 0.50 at its centre to 0.45 at its corners, where X_ITE draws no
        # falloff, so the fit matches the face as a whole: Babylon's mean over it is X_ITE's
        body = ("<PointLight DEF='Lamp' location='0 0 0' intensity='1' radius='4' global='true'/>\n"
                + _box(CLASSIC, z=-3))
        lamp = self._import(body)["Lamp"]
        xite, gltf = face_means(lamp.energy / K, 2.95, 4.0)
        self.assertAlmostEqual(gltf, xite, delta=0.01)
        self.assertGreater(lamp.energy, 1.3 * K * math.pi * 2.95 ** 2)

    def test_classic_light_near_its_radius_draws_through_the_squared_window(self):
        # the face 2.95 m away sits near the radius 3.5 (Babylon's window there is 0.25, X_ITE draws it at full)
        body = ("<PointLight DEF='Lamp' location='0 0 0' intensity='1' radius='3.5' global='true'/>\n"
                + _box(CLASSIC, z=-3))
        lamp = self._import(body)["Lamp"]
        xite, gltf = face_means(lamp.energy / K, 2.95, 3.5)
        self.assertAlmostEqual(gltf, xite, delta=0.01)

    def test_classic_spot_light_falls_off_linearly_in_angle_as_x_ite_draws(self):
        # X_ITE's classic getSpotFactor is (angle - cutOffAngle) / (beamWidth - cutOffAngle); a glTF viewer's spot is
        # t^2, t linear in the cosine from the outer cone to the inner one. A patch 30 degrees off the axis of a spot of
        # cutOff 45 and beam 22.5 degrees: X_ITE draws 0.8 x cos x 0.65 there
        x = 3.0 * math.tan(math.radians(30.0))
        body = (f"<Viewpoint position='{x} 0 1' fieldOfView='0.2'/>\n"
                "<SpotLight DEF='Spot' location='0 0 0' direction='0 0 -1' cutOffAngle='0.785398' "
                "beamWidth='0.392699' intensity='1' global='true'/>\n"
                + _box(CLASSIC, x=x, z=-3, name="Patch").replace("1 1 0.1", "0.1 0.1 0.1"))
        spot = self._import(body)["Spot"]
        far = math.hypot(x, 2.95)
        angle, facing = math.atan2(x, 2.95), 2.95 / far
        cut, beam = 0.785398, 0.392699
        shown = 0.8 * facing * (angle - cut) / (beam - cut)
        inner, outer = math.cos(beam), math.cos(cut)
        cone = max(0.0, min(1.0, (math.cos(angle) - outer) / max(0.001, inner - outer))) ** 2
        lux = spot.energy / K / far ** 2 * facing * cone * window(far, 100.0)
        self.assertAlmostEqual(srgb(lin(0.8) * lux / math.pi), shown, delta=0.01)

    def test_radius_zero_lights_nothing_and_leaves_the_other_lights_alone(self):
        # X_ITE lights a face only when dL <= radius || radius < 0, so a light of radius 0 draws nothing: it gets no
        # energy (its scale is kept, as for a light that starts dark), and the sun keeps what it gets alone
        import bpy
        sun = "<DirectionalLight DEF='Sun' intensity='0.3' global='true'/>\n"
        zero = "<PointLight DEF='Zero' location='0 0 1' intensity='0.7' radius='0' global='true'/>\n"
        alone = self._import(sun + _box(CLASSIC))["Sun"].energy
        with self.assertLogs(level="WARNING"):
            lights = self._import(sun + zero + _box(CLASSIC))
        self.assertAlmostEqual(lights["Sun"].energy, alone, places=4)
        self.assertAlmostEqual(alone, 0.3 * factor(0.3), places=4)
        self.assertEqual(lights["Zero"].energy, 0.0)
        self.assertGreater(lights["Zero"]["x3d_energy_per_intensity"], 0.0)
        self.assertFalse(lights["Zero"].use_custom_distance)
        self.assertEqual(lights["Zero"]["x3d_radius"], 0.0)
        path = os.path.join(self.tmpdir, "zero.x3d")
        for version in ("X3D40", "X3D33"):                                   # both exports write the file's light back
            bpy.ops.export_scene.x3d(filepath=path, x3d_version=version, use_selection=False)
            written = ET.parse(path).getroot().find(".//PointLight").attrib
            self.assertEqual(float(written["radius"]), 0.0, version)
            self.assertAlmostEqual(float(written["intensity"]), 0.7, places=4, msg=version)
        with self.assertLogs(level="WARNING"):                                # X_ITE's PBR shader gates the same way
            self.assertEqual(self._import(zero + _box(PHYSICAL))["Zero"].energy, 0.0)

    def test_a_light_no_face_sees_keeps_the_shared_factor(self):
        from unittest import mock
        module = __import__("io_scene_x3d.import_x3d", fromlist=["fit_classic_lights"])
        fitted = []
        fit = module.fit_classic_lights

        def keep(*args):
            fitted.append(fit(*args))
            return fitted[-1]
        body = ("<DirectionalLight DEF='Front' intensity='0.5' direction='0 0 -1' global='true'/>\n"
                "<DirectionalLight DEF='Side' intensity='0.9' direction='-1 0 -0.3' global='true'/>\n"
                "<DirectionalLight DEF='Back' intensity='0.4' direction='0 0 1' global='true'/>\n"
                + _box("<Material diffuseColor='0.9 0.2 0.1'/>", x=-1.5, name="A").replace("1 1 0.1", "1 1 1")
                + _box("<Material diffuseColor='0.2 0.3 0.9'/>", x=1.5, name="B").replace("1 1 0.1", "1 1 1")
                + _box("<Material diffuseColor='0.5 0.5 0.5'/>", z=-1, name="C").replace("1 1 0.1", "2 2 2"))
        with mock.patch.object(module, "fit_classic_lights", keep):
            lights = self._import(body)
        f, own, _headlight = fitted[0]
        self.assertNotAlmostEqual(own[0], f, places=4)                   # the lights in view have their own factors
        self.assertAlmostEqual(lights["Back"].energy, 0.4 * f, places=5)  # the back light lights no face in view

    def test_a_scaled_viewpoint_sees_what_the_same_camera_unscaled_sees(self):
        # the headlight is a unit DirectionalLight along the view (X_ITE normalises its direction, x_ite.js 64123);
        # a Transform's scale on the Viewpoint changes neither the view nor the headlight
        header = "<?xml version='1.0' encoding='UTF-8'?>\n<X3D profile='Immersive' version='4.0'><Scene>\n"
        sun = "<DirectionalLight DEF='Sun' intensity='0.1' global='true'/>\n" + _box(CLASSIC)
        import bpy
        for view in ("<Viewpoint position='0 0 10'/>\n",
                     "<Transform scale='0.1 0.1 0.1'><Viewpoint position='0 0 100'/></Transform>\n",
                     "<Transform scale='3 3 3'><Viewpoint position='0 0 3.3333333'/></Transform>\n",
                     "<Transform scale='0.1 0.2 0.1'><Viewpoint position='0 0 100'/></Transform>\n"):
            lights = self._import(view + sun, header=header)
            self.assertAlmostEqual(lights["Sun"].energy, 0.1 * factor(1.1), places=4, msg=view)
            self.assertAlmostEqual(bpy.context.scene["x3d_headlight_lux"], factor(1.1), places=4, msg=view)

    def test_reference_distance_skips_surfaces_beyond_the_radius(self):
        body = ("<PointLight DEF='Lamp' location='0 0 0' intensity='1' radius='5' global='true'/>\n"
                + _box(CLASSIC, z=-2, name="Near") + _box(CLASSIC, z=-50, name="Far1") + _box(CLASSIC, z=-60, name="Far2"))
        lamp = self._import(body, light_units='X_ITE')["Lamp"]
        self.assertAlmostEqual(lamp["x3d_reference_distance"], 2.0, places=4)

    def test_one_physical_material_lights_the_scene_physically(self):
        # classic units would light the PhysicalMaterial pi times too bright; the classic boxes are only darker
        body = ("<DirectionalLight DEF='Sun' intensity='1' global='true'/>\n" + _box(PHYSICAL, name="P1")
                + _box(CLASSIC, x=2, name="C1") + _box(CLASSIC, x=4, name="C2") + _box(CLASSIC, x=6, name="C3"))
        self.assertAlmostEqual(self._import(body, light_units='X_ITE')["Sun"].energy, 1.0, places=6)
        import bpy
        self.assertEqual(bpy.context.scene["x3d_lighting_model"], "physical")

    def test_classic_level_follows_the_median_albedo(self):
        # the sRGB curve's linear toe: a dark 0.055 lit at 2.4 shows 0.132 at 11 lux, where pi lin(2.4) is 23.9
        dark = "<Material diffuseColor='0.055 0.055 0.055'/>"
        body = ("<DirectionalLight DEF='Key' intensity='2.4' global='true'/>\n" + _box(dark, name="A")
                + _box(dark, x=2, name="B") + _box(CLASSIC, x=4, name="C")
                + _box("<Material diffuseColor='0 0 0' emissiveColor='1 1 1'/>", x=6, name="Glow"))
        key = self._import(body)["Key"]
        self.assertAlmostEqual(key.energy, math.pi * lin(0.055 * 2.4) / lin(0.055), places=4)
        self.assertLess(key.energy, 12.0)

    def test_dark_light_keeps_its_scale(self):
        # the material odyssey starts its lights at 0 and a script raises them
        lamp = self._import("<PointLight DEF='Lamp' location='0 0 5' intensity='0' global='true'/>\n"
                            + _box(PHYSICAL, z=3), light_units='X_ITE')["Lamp"]
        self.assertEqual(lamp.energy, 0.0)
        self.assertAlmostEqual(lamp["x3d_energy_per_intensity"], K, places=4)

    # --- what a light is matched against ------------------------------------------------------------------------

    def test_transform_scale_is_the_frame_x_ite_measures_in(self):
        # X_ITE measures the light's distance, attenuation and radius in its own frame: here 4 m in the world is 2
        # units of the scaled frame, so attenuation 1 0 1 gives 1/5, and 1/d^2 in that frame is 4/d^2 in the world
        body = ("<Transform scale='2 2 2'><PointLight DEF='Lamp' location='0 0 0' intensity='1' attenuation='1 0 1' "
                "radius='10' global='true'/></Transform>\n" + _box(PHYSICAL, z=-4))
        lamp = self._import(body)["Lamp"]
        self.assertAlmostEqual(lamp["x3d_reference_distance"], 4.0, places=4)
        self.assertAlmostEqual(lamp.energy, K * 0.2 * 4.0, places=3)
        self.assertAlmostEqual(lamp.cutoff_distance, 20.0, places=4)        # the range, in world metres
        self.assertAlmostEqual(lamp["x3d_radius"], 10.0, places=6)          # the file's radius, for the exports

    def test_every_use_of_a_shape_is_a_surface(self):
        # one DEF 1 m away and two USEs about 6 m away: the median is 6 m, not the DEF's 1 m
        body = ("<PointLight DEF='Lamp' location='0 0 0' intensity='1' global='true'/>\n"
                "<Transform translation='0 0 -1'><Shape DEF='S'><Appearance>" + CLASSIC + "</Appearance>"
                "<Box size='1 1 0.1'/></Shape></Transform>\n"
                "<Transform translation='0 0 -6'><Shape USE='S'/></Transform>\n"
                "<Transform translation='0 1 -6'><Shape USE='S'/></Transform>\n")
        lamp = self._import(body)["Lamp"]
        self.assertAlmostEqual(lamp["x3d_reference_distance"], 6.0, places=4)

    def test_an_inlined_gltf_lights_the_scene_physically(self):
        # X_ITE draws a glTF Inline with PhysicalMaterial, so classic units would overexpose it
        Path(self.tmpdir, "tri.gltf").write_text(TRIANGLE_GLTF, encoding="utf-8")
        body = ("<DirectionalLight DEF='Sun' intensity='1' global='true'/>\n" + _box(CLASSIC)
                + "<Inline url='\"tri.gltf\"'/>\n")
        self.assertAlmostEqual(self._import(body)["Sun"].energy, 1.0, places=6)
        import bpy
        self.assertEqual(bpy.context.scene["x3d_lighting_model"], "physical")

    def test_glowing_and_enclosing_shapes_are_left_out(self):
        # a black, emissive bulb around the light and the room it hangs in are not what the light is matched at
        bulb = ("<Shape><Appearance><Material diffuseColor='0 0 0' emissiveColor='1 1 0.8'/></Appearance>"
                "<Sphere radius='0.2'/></Shape>\n")
        room = "<Shape><Appearance>" + CLASSIC + "</Appearance><Box size='20 20 20'/></Shape>\n"
        body = ("<PointLight DEF='Lamp' location='0 0 0' intensity='1' global='true'/>\n" + bulb + room
                + _box(CLASSIC, z=-3, name="Table"))
        lamp = self._import(body)["Lamp"]
        self.assertAlmostEqual(lamp["x3d_reference_distance"], 3.0, places=4)

    def test_a_light_above_a_large_floor_is_matched_where_the_floor_is_nearest(self):
        # not at the floor's far corner (its half diagonal, 14 m), which overexposed the whole floor
        body = ("<PointLight DEF='Lamp' location='0 2 0' intensity='1' global='true'/>\n"
                "<Shape><Appearance>" + CLASSIC + "</Appearance><Box size='20 0.1 20'/></Shape>\n")
        lamp = self._import(body)["Lamp"]
        self.assertAlmostEqual(lamp["x3d_reference_distance"], 1.95, places=4)

    def test_radius_minus_one_or_zero_leaves_no_range(self):
        import bpy
        body = ("<PointLight DEF='Free' location='0 0 0' intensity='1' radius='-1' global='true'/>\n"
                "<PointLight DEF='Zero' location='0 0 0' intensity='1' radius='0' global='true'/>\n"
                + _box(PHYSICAL, z=-3) + _box(PHYSICAL, z=-300, name="Far"))
        with self.assertLogs(level="WARNING"):
            lights = self._import(body)
        self.assertFalse(lights["Free"].use_custom_distance)
        self.assertFalse(lights["Zero"].use_custom_distance)
        self.assertAlmostEqual(lights["Free"]["x3d_reference_distance"], 151.5, places=3)  # unlimited: both boxes
        self.assertEqual(lights["Free"]["x3d_radius"], -1.0)
        glb = os.path.join(self.tmpdir, "radius.glb")
        bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB", export_lights=True,
                                  export_import_convert_lighting_mode="COMPAT")
        for light in _glb_lights(glb).values():
            self.assertNotIn("range", light)                                 # never the schema-invalid range 0

    def test_spot_cone_keeps_x3d_beam_width_as_the_inner_cone(self):
        import bpy
        body = ("<SpotLight DEF='Soft' location='0 0 0' beamWidth='0.3' cutOffAngle='0.6' global='true'/>\n"
                "<SpotLight DEF='Hard' location='0 0 0' global='true'/>\n" + _box(PHYSICAL, z=-3))
        lights = self._import(body)
        self.assertAlmostEqual(lights["Soft"].spot_size, 1.2, places=5)
        self.assertAlmostEqual(lights["Soft"].spot_blend, 0.5, places=5)
        self.assertAlmostEqual(lights["Hard"].spot_blend, 0.0, places=6)   # beamWidth pi/2 >= cutOffAngle pi/4
        glb = os.path.join(self.tmpdir, "spots.glb")
        bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB", export_lights=True,
                                  export_import_convert_lighting_mode="COMPAT")
        spots = {name: light["spot"] for name, light in _glb_lights(glb).items()}
        self.assertAlmostEqual(spots["Soft"]["innerConeAngle"], 0.3, places=4)
        self.assertAlmostEqual(spots["Soft"]["outerConeAngle"], 0.6, places=4)
        self.assertAlmostEqual(spots["Hard"]["innerConeAngle"], spots["Hard"]["outerConeAngle"], places=4)

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
        self.assertAlmostEqual(self._import(body)["Sun"].energy, math.pi, places=5)          # SRGB (default) -> X_ITE
        self.assertAlmostEqual(self._import(body, color_space='AS_IS')["Sun"].energy, 1.0, places=6)  # -> BLENDER
        os.environ["BLENDER_X3D_COLOR_SPACE"] = "AS_IS"
        self.assertAlmostEqual(self._import(body)["Sun"].energy, 1.0, places=6)
        os.environ["BLENDER_X3D_COLOR_SPACE"] = "SRGB"
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
        self._import("<PointLight DEF='Lamp' location='0 0 0' intensity='0.8' attenuation='1 0 0.00002' radius='14' "
                     "global='true'/>\n<SpotLight DEF='Spot' location='0 0 0' intensity='0.6' radius='12' "
                     "beamWidth='0.3' cutOffAngle='0.6' global='true'/>\n"
                     "<DirectionalLight DEF='Sun' intensity='0.9' global='true'/>\n"
                     + _box(CLASSIC, z=-2) + _box(CLASSIC, z=-4, name="B"), light_units='X_ITE')
        for version in ("X3D40", "X3D33"):
            path = os.path.join(self.tmpdir, "back_%s.x3d" % version)
            self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version=version, use_selection=False),
                             {"FINISHED"})
            root = ET.parse(path).getroot()
            point = root.find(".//PointLight").attrib
            self.assertAlmostEqual(float(point["intensity"]), 0.8, places=3, msg=version)
            # a small quadratic term survives (it was written as 0.0000)
            self.assertEqual([float(v) for v in point["attenuation"].replace(",", " ").split()],
                             [1.0, 0.0, 0.00002], msg=version)
            self.assertAlmostEqual(float(point["radius"]), 14.0, places=3, msg=version)
            spot = root.find(".//SpotLight").attrib
            self.assertAlmostEqual(float(spot["intensity"]), 0.6, places=3, msg=version)
            self.assertAlmostEqual(float(spot["radius"]), 12.0, places=4, msg=version)
            self.assertAlmostEqual(float(spot["beamWidth"]), 0.3, places=4, msg=version)
            self.assertAlmostEqual(float(spot["cutOffAngle"]), 0.6, places=4, msg=version)
            self.assertAlmostEqual(float(root.find(".//DirectionalLight").attrib["intensity"]), 0.9, places=3,
                                   msg=version)


if __name__ == "__main__":
    unittest.main()
