# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Importer paths no test reached (the coverage pass of 12 Nov 2026): Text, Extrusion, the triangle sets with
colours, normals and texture coordinates, TextureTransform, PixelTexture, interpolators driven by ROUTEs, the
classic VRML encoding, and PhysicalMaterial texture slots. Each test checks what the scene says, not only that the
import ran.

    cd tests && python -m unittest test_import_coverage_bpy
"""

from __future__ import annotations

import os
import tempfile
import unittest

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

if HAVE_BPY:
    from test_roundtrip_bpy import _register_extension
    from test_import_unlit_bpy import _write_png

HEADER = "<?xml version='1.0' encoding='UTF-8'?>\n<X3D profile='Full' version='4.0'><Scene>\n"
FOOTER = "</Scene></X3D>\n"


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ImportCoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_cov_")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmpdir)

    def load(self, body, name="scene.x3d", raw=False):
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body if raw else HEADER + body + FOOTER)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmpdir)
        self.assertIn("FINISHED", bpy.ops.import_scene.x3d(filepath=path))
        return path

    def objects(self, kind):
        return [o for o in bpy.data.objects if o.type == kind]

    # ------------------------------------------------------------ Text
    def test_text_carries_its_string_size_and_justification(self):
        self.load("<Shape><Appearance><Material diffuseColor='1 1 0'/></Appearance>"
                  "<Text string='\"Hello\" \"X3D\"'><FontStyle size='2' spacing='1.5' justify='\"MIDDLE\" \"MIDDLE\"' "
                  "style='BOLD'/></Text></Shape>")
        font = self.objects('FONT')
        self.assertEqual(len(font), 1)
        curve = font[0].data
        self.assertIn("Hello", curve.body)
        self.assertIn("X3D", curve.body)
        self.assertAlmostEqual(curve.size, 2.0, places=4)
        self.assertEqual(curve.align_x, 'CENTER')
        self.assertTrue(curve.materials and curve.materials[0] is not None)

    def test_text_without_font_style_uses_the_defaults(self):
        self.load("<Shape><Text string='\"A\"'/></Shape>")
        curve = self.objects('FONT')[0].data
        self.assertEqual(curve.body.strip(), "A")
        self.assertAlmostEqual(curve.size, 1.0, places=4)

    # ------------------------------------------------------------ Extrusion
    def test_extrusion_square_along_a_spine(self):
        self.load("<Shape><Extrusion crossSection='1 1 1 -1 -1 -1 -1 1 1 1' spine='0 0 0 0 2 0' "
                  "scale='1 1 0.5 0.5'/></Shape>")
        mesh = self.objects('MESH')[0].data
        ys = sorted({round(v.co.y, 4) for v in mesh.vertices})
        self.assertEqual(ys[0], 0.0)
        self.assertAlmostEqual(ys[-1], 2.0, places=4)
        top = [v for v in mesh.vertices if abs(v.co.y - 2.0) < 1e-4]
        self.assertAlmostEqual(max(abs(v.co.x) for v in top), 0.5, places=4)   # scaled by 0.5 at the top
        self.assertGreaterEqual(len(mesh.polygons), 4)

    # ------------------------------------------------------------ triangle sets
    def test_indexed_triangle_set_with_colours_normals_and_uvs(self):
        self.load("<Shape><IndexedTriangleSet index='0 1 2 0 2 3'>"
                  "<Coordinate point='0 0 0 1 0 0 1 1 0 0 1 0'/>"
                  "<Color color='1 0 0 0 1 0 0 0 1 1 1 1'/>"
                  "<TextureCoordinate point='0 0 1 0 1 1 0 1'/></IndexedTriangleSet></Shape>")
        mesh = self.objects('MESH')[0].data
        self.assertEqual(len(mesh.polygons), 2)
        self.assertTrue(mesh.color_attributes)
        self.assertEqual(len(mesh.uv_layers), 1)
        uvs = {tuple(round(c, 3) for c in d.uv) for d in mesh.uv_layers[0].data}
        self.assertEqual(uvs, {(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)})

    def test_triangle_set_strip_and_fan_sets(self):
        cases = {
            "<TriangleSet><Coordinate point='0 0 0 1 0 0 0 1 0 1 0 0 1 1 0 0 1 0'/></TriangleSet>": 2,
            "<TriangleSet ccw='false'><Coordinate point='0 0 0 1 0 0 0 1 0'/></TriangleSet>": 1,
            "<TriangleStripSet stripCount='4'><Coordinate point='0 0 0 1 0 0 0 1 0 1 1 0'/></TriangleStripSet>": 2,
            "<TriangleFanSet fanCount='4'><Coordinate point='0 0 0 1 0 0 1 1 0 0 1 0'/></TriangleFanSet>": 2,
            "<IndexedTriangleStripSet index='0 1 2 3 -1'><Coordinate point='0 0 0 1 0 0 0 1 0 1 1 0'/></IndexedTriangleStripSet>": 2,
            "<IndexedTriangleFanSet index='0 1 2 3 -1'><Coordinate point='0 0 0 1 0 0 1 1 0 0 1 0'/></IndexedTriangleFanSet>": 2,
        }
        for geometry, faces in cases.items():
            with self.subTest(geometry=geometry[:40]):
                self.load("<Shape>%s</Shape>" % geometry)
                self.assertEqual(len(self.objects('MESH')[0].data.polygons), faces)

    def test_ccw_false_flips_the_triangle_set(self):
        self.load("<Shape><TriangleSet ccw='false'><Coordinate point='0 0 0 1 0 0 0 1 0'/></TriangleSet></Shape>")
        self.assertLess(self.objects('MESH')[0].data.polygons[0].normal.z, -0.99)

    # ------------------------------------------------------------ textures
    def test_texture_transform_and_image_texture(self):
        png = os.path.join(self.tmpdir, "tex.png")
        _write_png(png, rgb=(10, 200, 30), size=4)
        self.load("<Shape><Appearance><Material/><ImageTexture url='\"tex.png\"'/>"
                  "<TextureTransform scale='2 2' rotation='0.5' translation='0.25 0'/></Appearance>"
                  "<IndexedFaceSet coordIndex='0 1 2 3 -1' texCoordIndex='0 1 2 3 -1'>"
                  "<Coordinate point='0 0 0 1 0 0 1 1 0 0 1 0'/><TextureCoordinate point='0 0 1 0 1 1 0 1'/>"
                  "</IndexedFaceSet></Shape>")
        mesh = self.objects('MESH')[0].data
        mat = mesh.materials[0]
        images = [n.image for n in mat.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image]
        self.assertTrue(images and os.path.basename(images[0].filepath) == "tex.png")
        uvs = [tuple(d.uv) for d in mesh.uv_layers[0].data]
        self.assertNotEqual(sorted(uvs), sorted([(0, 0), (1, 0), (1, 1), (0, 1)]))   # the transform moved them

    def test_pixel_texture_becomes_an_image_with_its_pixels(self):
        self.load("<Shape><Appearance><Material/><PixelTexture image='2 1 3 0xFF0000 0x00FF00'/></Appearance>"
                  "<IndexedFaceSet coordIndex='0 1 2 -1'><Coordinate point='0 0 0 1 0 0 0 1 0'/></IndexedFaceSet></Shape>")
        mat = self.objects('MESH')[0].data.materials[0]
        images = [n.image for n in mat.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image]
        self.assertTrue(images)
        img = images[0]
        self.assertEqual(tuple(img.size), (2, 1))
        px = list(img.pixels)
        self.assertGreater(px[0], 0.9)          # first pixel red
        self.assertGreater(px[5], 0.9)          # second pixel green

    def test_physical_material_texture_slots(self):
        for name, rgb in (("base.png", (200, 100, 50)), ("mr.png", (0, 128, 255)), ("nrm.png", (128, 128, 255)),
                          ("occ.png", (255, 255, 255)), ("emi.png", (255, 0, 0))):
            _write_png(os.path.join(self.tmpdir, name), rgb=rgb)
        self.load("<Shape><Appearance><PhysicalMaterial baseColor='1 1 1' metallic='1' roughness='1' "
                  "emissiveColor='1 1 1'>"
                  "<ImageTexture containerField='baseTexture' url='\"base.png\"'/>"
                  "<ImageTexture containerField='metallicRoughnessTexture' url='\"mr.png\"'/>"
                  "<ImageTexture containerField='normalTexture' url='\"nrm.png\"'/>"
                  "<ImageTexture containerField='occlusionTexture' url='\"occ.png\"'/>"
                  "<ImageTexture containerField='emissiveTexture' url='\"emi.png\"'/>"
                  "</PhysicalMaterial></Appearance>"
                  "<IndexedFaceSet coordIndex='0 1 2 -1'><Coordinate point='0 0 0 1 0 0 0 1 0'/>"
                  "<TextureCoordinate point='0 0 1 0 0 1'/></IndexedFaceSet></Shape>")
        mat = self.objects('MESH')[0].data.materials[0]
        names = {os.path.basename(n.image.filepath) for n in mat.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image}
        self.assertTrue({"base.png", "mr.png", "nrm.png", "emi.png"} <= names, names)
        self.assertTrue(any(n.type == 'NORMAL_MAP' for n in mat.node_tree.nodes))

    # ------------------------------------------------------------ animation
    def test_interpolators_routed_from_a_time_sensor_become_keyframes(self):
        self.load("<Transform DEF='Mover'><Shape><Box/></Shape></Transform>"
                  "<TimeSensor DEF='Clock' cycleInterval='4' loop='true'/>"
                  "<PositionInterpolator DEF='Path' key='0 0.5 1' keyValue='0 0 0 0 2 0 0 0 0'/>"
                  "<OrientationInterpolator DEF='Turn' key='0 1' keyValue='0 1 0 0 0 1 0 3.14159'/>"
                  "<ROUTE fromNode='Clock' fromField='fraction_changed' toNode='Path' toField='set_fraction'/>"
                  "<ROUTE fromNode='Path' fromField='value_changed' toNode='Mover' toField='set_translation'/>"
                  "<ROUTE fromNode='Clock' fromField='fraction_changed' toNode='Turn' toField='set_fraction'/>"
                  "<ROUTE fromNode='Turn' fromField='value_changed' toNode='Mover' toField='set_rotation'/>")
        animated = [o for o in bpy.data.objects if o.animation_data and o.animation_data.action]
        self.assertTrue(animated, [o.name for o in bpy.data.objects])
        action = animated[0].animation_data.action
        paths = set()
        if hasattr(action, "fcurves") and action.fcurves:
            paths = {fc.data_path for fc in action.fcurves}
        else:                                                    # Blender 5: slotted actions keep curves in channel bags
            for layer in getattr(action, "layers", []):
                for strip in layer.strips:
                    for bag in strip.channelbags:
                        paths |= {fc.data_path for fc in bag.fcurves}
        self.assertTrue({"location"} & paths or any("location" in p for p in paths), paths)

    # ------------------------------------------------------------ the classic VRML encoding
    def test_classic_vrml_encoding_parses_the_same_scene(self):
        wrl = ("#VRML V2.0 utf8\n# a comment line\n"
               "DEF Lamp PointLight { location 0 2 0 intensity 0.7 }\n"
               "Viewpoint { position 0 0 5 description \"Front view\" }\n"
               "Transform { translation 1 0 0 children [\n"
               "  DEF Ball Shape { appearance Appearance { material Material { diffuseColor 1 0 0 } }\n"
               "    geometry Sphere { radius 0.5 } }\n"
               "  Shape { geometry IndexedFaceSet { coord Coordinate { point [ 0 0 0, 1 0 0, 0 1 0 ] }\n"
               "    coordIndex [ 0 1 2 -1 ] } }\n"
               "] }\n"
               "Transform { translation -1 0 0 children USE Ball }\n")
        self.load(wrl, name="scene.wrl", raw=True)
        meshes = self.objects('MESH')
        self.assertEqual(len(meshes), 3)                                     # the ball twice (DEF and USE), the triangle
        self.assertTrue(self.objects('LIGHT'))
        cams = self.objects('CAMERA')
        self.assertTrue(cams)
        balls = [o for o in meshes if len(o.data.polygons) > 1]
        self.assertEqual(len(balls), 2)
        self.assertEqual(sorted(round(o.matrix_world.translation.x, 3) for o in balls), [-1.0, 1.0])
        red = balls[0].data.materials[0]
        bsdf = next(n for n in red.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        self.assertEqual([round(c, 3) for c in bsdf.inputs["Base Color"].default_value[:3]], [1.0, 0.0, 0.0])
        self.assertEqual(sum(p.use_smooth for p in balls[0].data.polygons), len(balls[0].data.polygons))

    def test_lights_and_viewpoint_fields(self):
        self.load("<DirectionalLight direction='0 -1 0' intensity='0.5' color='1 0.5 0.25'/>"
                  "<SpotLight location='0 3 0' direction='0 -1 0' beamWidth='0.3' cutOffAngle='0.6' intensity='1'/>"
                  "<PointLight location='1 1 1' radius='10'/>"
                  "<Viewpoint position='0 1 7' fieldOfView='0.5' description='Close'/>")
        lights = {o.data.type for o in self.objects('LIGHT')}
        self.assertEqual(lights, {'SUN', 'SPOT', 'POINT'})
        spot = next(o.data for o in self.objects('LIGHT') if o.data.type == 'SPOT')
        self.assertAlmostEqual(spot.spot_size, 2 * 0.6, places=3)
        sun = next(o.data for o in self.objects('LIGHT') if o.data.type == 'SUN')
        self.assertEqual([round(c, 3) for c in sun.color], [1.0, 0.5, 0.25])
        cam = self.objects('CAMERA')[0]
        # X3D's (0, 1, 7), Y up, in Blender's Z-up frame: (x, -z, y)
        self.assertEqual(tuple(round(c, 3) for c in cam.location), (0.0, -7.0, 1.0))


if __name__ == "__main__":
    unittest.main()
