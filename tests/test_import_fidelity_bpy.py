# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Importer fidelity: what X3D draws, as Blender, Cycles and the glTF read by Unreal and Babylon.js draw it.

Found by rendering the x3d.demo scenes (92 scenes: 496 Spheres, 152 Cylinders, 588 Materials, 458 IndexedLineSets,
110 PointSets) through this add-on, glTF and Unreal Engine (12 Nov 2026):

* Sphere, Cylinder and Cone came in faceted (no creaseAngle field, so every face was flat). Now Sphere is smooth,
  Cylinder and Cone are smooth on the side, with flat caps behind sharp rims.
* Their tessellation was fixed at 16; ``circle_divisions`` (the import option, or BLENDER_X3D_CIRCLE_DIV) sets it.
* A Material's specularColor was ignored: every Material got Blender's default dielectric specular, which X3D's
  default (black) specularColor does not draw, and shininess 1 became a mirror (roughness = 1 - shininess). Now the
  Blinn-Phong term maps to roughness, specular IOR level and tint (phong_to_principled).
* Lines and points were lit with the diffuse colour; X3D draws them unlit in emissiveColor.
* TwoSidedMaterial was ignored (grey); its front fields now map like Material's.
* IndexedQuadSet, QuadSet, ArcClose2D, TriangleSet2D, Arc2D, Circle2D, Polyline2D and Polypoint2D were skipped
  ("unsupported type").

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_import_fidelity_bpy
"""

from __future__ import annotations

import json
import math
import os
import struct
import tempfile
import unittest

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

if HAVE_BPY:
    from test_roundtrip_bpy import _register_extension

HEADER = ("<?xml version='1.0' encoding='UTF-8'?>\n"
          "<X3D profile='Full' version='4.0'><Scene>\n")
FOOTER = "</Scene></X3D>\n"


def _shape(geometry, appearance="<Appearance><Material/></Appearance>", name=None):
    def_attr = " DEF='%s'" % name if name else ""
    return "<Shape%s>%s%s</Shape>" % (def_attr, appearance, geometry)


def _glb_json(path):
    with open(path, "rb") as f:
        raw = f.read()
    length = struct.unpack("<I", raw[12:16])[0]
    return json.loads(raw[20:20 + length])


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ImportFidelityTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_fidelity_")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.module = _register_extension(self.tmpdir)
        self.ix = __import__(self.module.__name__ + ".import_x3d", fromlist=["import_x3d"])
        self._env = os.environ.pop("BLENDER_X3D_CIRCLE_DIV", None)

    def tearDown(self):
        os.environ.pop("BLENDER_X3D_CIRCLE_DIV", None)
        if self._env is not None:
            os.environ["BLENDER_X3D_CIRCLE_DIV"] = self._env

    def load(self, body, **options):
        path = os.path.join(self.tmpdir, "scene.x3d")
        with open(path, "w", encoding="utf-8") as f:
            f.write(HEADER + body + FOOTER)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmpdir)
        result = bpy.ops.import_scene.x3d(filepath=path, **options)
        self.assertIn("FINISHED", result)
        return path

    def meshes(self):
        return [o for o in bpy.data.objects if o.type == 'MESH']

    def only_mesh(self):
        found = self.meshes()
        self.assertEqual(len(found), 1, [o.name for o in bpy.data.objects])
        return found[0].data

    def bsdf(self, material):
        return next(n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')

    def export_glb(self, name="scene.glb", **extra):
        out = os.path.join(self.tmpdir, name)
        bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", **extra)
        return _glb_json(out)

    # ------------------------------------------------------------ smooth primitives
    def test_sphere_is_smooth_and_its_glb_shares_vertices(self):
        self.load(_shape("<Sphere radius='1'/>"))
        mesh = self.only_mesh()
        self.assertEqual(sum(p.use_smooth for p in mesh.polygons), len(mesh.polygons))
        gltf = self.export_glb()
        count = gltf["accessors"][gltf["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]["count"]
        # smooth: vertices shared between faces (only the UV seam splits them); faceted it was 992
        self.assertLess(count, 2 * len(mesh.vertices))

    def test_cylinder_and_cone_have_smooth_sides_flat_caps_and_sharp_rims(self):
        for geometry, caps in (("<Cylinder radius='1' height='2'/>", 2), ("<Cone bottomRadius='1' height='2'/>", 1)):
            with self.subTest(geometry=geometry):
                self.load(_shape(geometry))
                mesh = self.only_mesh()
                flat = [p for p in mesh.polygons if not p.use_smooth]
                self.assertEqual(len(flat), caps)
                for p in flat:
                    self.assertAlmostEqual(abs(p.normal.y), 1.0, places=5)
                sharp = sum(e.use_edge_sharp for e in mesh.edges)
                self.assertEqual(sharp, 16 * caps)              # every rim edge, at the default 16 divisions
                # the caps keep their own normal at every corner
                for p in flat:
                    for li in p.loop_indices:
                        n = mesh.corner_normals[li].vector
                        self.assertAlmostEqual(abs(n.y), 1.0, places=4)

    def test_box_stays_flat_and_crease_angle_still_rules_face_sets(self):
        self.load(_shape("<Box/>"))
        self.assertEqual(sum(p.use_smooth for p in self.only_mesh().polygons), 0)
        self.load(_shape("<IndexedFaceSet creaseAngle='1.6' coordIndex='0 1 2 -1 0 2 3 -1'>"
                         "<Coordinate point='0 0 0 1 0 0 1 1 0.3 0 1 0'/></IndexedFaceSet>"))
        self.assertEqual(sum(p.use_smooth for p in self.only_mesh().polygons), 2)

    # ------------------------------------------------------------ tessellation
    def test_circle_divisions_from_the_option_the_environment_or_the_default(self):
        self.load(_shape("<Sphere/>"))
        self.assertEqual(len(self.only_mesh().polygons), 16 * 16)
        os.environ["BLENDER_X3D_CIRCLE_DIV"] = "64"
        self.load(_shape("<Sphere/>"))
        self.assertEqual(len(self.only_mesh().polygons), 64 * 64)
        self.load(_shape("<Cylinder/>"), circle_divisions=24)                  # the option wins over the variable
        self.assertEqual(len(self.only_mesh().polygons), 24 + 2)
        os.environ["BLENDER_X3D_CIRCLE_DIV"] = "lots"
        with self.assertLogs(level="WARNING"):
            self.load(_shape("<Cone/>"))
        self.assertEqual(len(self.only_mesh().polygons), 16 + 1)

    def test_resolve_circle_divisions_clamps(self):
        resolve = self.ix.resolve_circle_divisions
        self.assertEqual(resolve(1), 3)
        self.assertEqual(resolve(10000), 512)
        self.assertEqual(resolve(None), 16)
        os.environ["BLENDER_X3D_CIRCLE_DIV"] = " 48 "
        self.assertEqual(resolve(None), 48)
        self.assertEqual(resolve(32), 32)

    # ------------------------------------------------------------ Material: X3D's Blinn-Phong
    def test_phong_to_principled_follows_the_x3d_lighting_model(self):
        f = self.ix.phong_to_principled
        r, level, tint = f(0.2, (0, 0, 0))                       # X3D's default Material: no highlight at all
        self.assertAlmostEqual(r, (2 / 27.6) ** 0.25, places=6)
        self.assertEqual((level, tint), (0.0, (1.0, 1.0, 1.0)))
        r, level, tint = f(0.9, (1, 1, 1))
        n = 128 * 0.9
        self.assertAlmostEqual(r, (2 / (n + 2)) ** 0.25, places=6)
        self.assertAlmostEqual(level, 8 / (n + 2) / 0.08, places=6)    # F0 = 8 s / (n + 2) at IOR 1.5
        _r, _level, tint = f(0.5, (1.0, 0.5, 0.0))
        self.assertEqual(tint, (1.0, 0.5, 0.0))
        self.assertAlmostEqual(f(0.0, (1, 1, 1))[0], 1.0)              # exponent 0: the widest lobe
        self.assertEqual(f(0.0, (1, 1, 1))[1], 1.0)                     # F0 capped at a dielectric's 0.08
        self.assertEqual(f(7.0, (2, 2, 2)), f(1.0, (1, 1, 1)))          # out-of-range fields are clamped

    def test_default_material_has_no_specular_and_says_so_in_gltf(self):
        self.load(_shape("<Box/>"))
        mat = self.only_mesh().materials[0]
        self.assertEqual(self.bsdf(mat).inputs["Specular IOR Level"].default_value, 0.0)
        gltf = self.export_glb()
        self.assertEqual(gltf["materials"][0]["extensions"]["KHR_materials_specular"]["specularFactor"], 0)

    def test_shiny_material_keeps_a_glossy_tinted_highlight(self):
        self.load(_shape("<Box/>", "<Appearance><Material diffuseColor='0.2 0.4 0.8' specularColor='1 0.5 0' "
                                   "shininess='0.9'/></Appearance>"))
        b = self.bsdf(self.only_mesh().materials[0])
        self.assertAlmostEqual(b.inputs["Roughness"].default_value, (2 / (128 * 0.9 + 2)) ** 0.25, places=5)
        self.assertGreater(b.inputs["Specular IOR Level"].default_value, 0.5)
        self.assertEqual([round(c, 3) for c in b.inputs["Specular Tint"].default_value[:3]], [1.0, 0.5, 0.0])

    # ------------------------------------------------------------ lines and points: unlit, emissive
    def test_lines_and_points_are_unlit_in_their_emissive_colour(self):
        mat = "<Appearance><Material DEF='Ink' diffuseColor='0.1 0.9 0.1' emissiveColor='1 0 0'/></Appearance>"
        use = "<Appearance><Material USE='Ink'/></Appearance>"
        self.load(_shape("<IndexedLineSet coordIndex='0 1 2 -1'><Coordinate point='0 0 0 1 0 0 1 1 0'/></IndexedLineSet>", mat)
                  + _shape("<PointSet><Coordinate point='0 0 1 1 0 1'/></PointSet>", use)
                  + _shape("<Box/>", use))
        by_type = {}
        for o in bpy.data.objects:
            by_type.setdefault(o.type, []).append(o)
        line_mat = by_type['CURVE'][0].data.materials[0]
        b = self.bsdf(line_mat)
        self.assertEqual(list(b.inputs["Base Color"].default_value[:3]), [0.0, 0.0, 0.0])
        self.assertEqual([round(c, 3) for c in b.inputs["Emission Color"].default_value[:3]], [1.0, 0.0, 0.0])
        self.assertEqual(b.inputs["Specular IOR Level"].default_value, 0.0)
        meshes = {len(o.data.polygons) > 0: o for o in by_type['MESH']}
        self.assertIs(meshes[False].data.materials[0], line_mat)         # the point set shares the unlit copy
        surface = self.bsdf(meshes[True].data.materials[0])                # the box keeps the lit material
        self.assertEqual([round(c, 3) for c in surface.inputs["Base Color"].default_value[:3]], [0.1, 0.9, 0.1])
        gltf = self.export_glb(use_mesh_edges=True, use_mesh_vertices=True)
        modes = sorted(p.get("mode", 4) for m in gltf["meshes"] for p in m["primitives"])
        self.assertEqual(modes, [0, 1, 4])
        unlit = [m for m in gltf["materials"] if m.get("emissiveFactor") == [1, 0, 0]]
        self.assertEqual(unlit[0]["pbrMetallicRoughness"]["baseColorFactor"][:3], [0, 0, 0])

    def test_coloured_lines_carry_their_colours_on_the_emission(self):
        self.load(_shape("<IndexedLineSet coordIndex='0 1 -1'><Coordinate point='0 0 0 1 0 0'/>"
                         "<Color color='1 0 0 0 0 1'/></IndexedLineSet>"))
        curve = next(o for o in bpy.data.objects if o.type == 'CURVE')
        b = self.bsdf(curve.data.materials[0])
        self.assertFalse(b.inputs["Base Color"].links)
        if b.inputs["Emission Color"].links:                              # vertex colours, where the import makes them
            self.assertEqual(b.inputs["Emission Color"].links[0].from_node.type, 'VERTEX_COLOR')

    # ------------------------------------------------------------ TwoSidedMaterial
    def test_two_sided_material_uses_its_front_fields(self):
        self.load(_shape("<IndexedFaceSet solid='false' coordIndex='0 1 2 -1'><Coordinate point='0 0 0 1 0 0 0 1 0'/>"
                         "</IndexedFaceSet>",
                         "<Appearance><TwoSidedMaterial diffuseColor='1 0 0' specularColor='0.5 0.5 0.5' shininess='0.5'/>"
                         "</Appearance>"))
        b = self.bsdf(self.only_mesh().materials[0])
        self.assertEqual([round(c, 3) for c in b.inputs["Base Color"].default_value[:3]], [1.0, 0.0, 0.0])
        self.assertGreater(b.inputs["Specular IOR Level"].default_value, 0.0)

    def test_two_sided_material_says_the_back_is_not_carried(self):
        with self.assertLogs(level="WARNING") as logs:
            self.load(_shape("<IndexedFaceSet solid='false' coordIndex='0 1 2 -1'><Coordinate point='0 0 0 1 0 0 0 1 0'/>"
                             "</IndexedFaceSet>",
                             "<Appearance><TwoSidedMaterial DEF='TS' diffuseColor='1 0 0' backDiffuseColor='0 1 0' "
                             "separateBackColor='true'/></Appearance>"))
        self.assertTrue(any("back colours are not imported" in line for line in logs.output))

    # ------------------------------------------------------------ CADGeometry quads
    def test_indexed_quad_set(self):
        pts = "<Coordinate point='0 0 0 1 0 0 1 1 0 0 1 0 2 0 0 2 1 0'/>"
        self.load(_shape("<IndexedQuadSet index='0 1 2 3 1 4 5 2 9'>%s</IndexedQuadSet>" % pts))
        mesh = self.only_mesh()
        self.assertEqual([len(p.vertices) for p in mesh.polygons], [4, 4])   # the trailing 9 is a remainder
        self.assertGreater(mesh.polygons[0].normal.z, 0.99)
        self.load(_shape("<IndexedQuadSet ccw='false' index='0 1 2 3 0 1 2 77'>%s</IndexedQuadSet>" % pts))
        mesh = self.only_mesh()
        self.assertEqual(len(mesh.polygons), 1)                               # a quad naming coordinate 77 is skipped
        self.assertLess(mesh.polygons[0].normal.z, -0.99)                      # ccw false: wound the other way

    def test_quad_set_and_an_empty_one(self):
        self.load(_shape("<QuadSet><Coordinate point='0 0 0 1 0 0 1 1 0 0 1 0 5 5 5'/></QuadSet>"))
        self.assertEqual(len(self.only_mesh().polygons), 1)
        self.load(_shape("<QuadSet/>"))
        self.assertEqual(self.meshes(), [])

    # ------------------------------------------------------------ Geometry2D
    def test_arc_close_2d_pie_chord_and_full(self):
        self.load(_shape("<ArcClose2D radius='2' startAngle='0' endAngle='1.5708'/>"))
        pie = self.only_mesh()
        self.assertEqual(len(pie.polygons), 1)
        self.assertTrue(any(v.co.length < 1e-6 for v in pie.vertices))         # PIE closes through the centre
        self.assertAlmostEqual(max(v.co.length for v in pie.vertices), 2.0, places=5)
        self.load(_shape("<ArcClose2D radius='2' startAngle='0' endAngle='3' closureType='CHORD'/>"))
        self.assertFalse(any(v.co.length < 1e-6 for v in self.only_mesh().vertices))
        self.load(_shape("<ArcClose2D radius='1' startAngle='1' endAngle='1'/>"))  # equal angles: the full circle
        full = self.only_mesh()
        self.assertEqual(len(full.vertices), 2 * 16)
        self.assertAlmostEqual(sum(p.area for p in full.polygons), math.pi, places=1)
        self.assertEqual(len(full.uv_layers), 1)

    def test_arc_circle_and_polyline_2d_are_lines(self):
        self.load(_shape("<Arc2D radius='1' startAngle='0' endAngle='3.14159'/>"))
        spline = next(o for o in bpy.data.objects if o.type == 'CURVE').data.splines[0]
        self.assertFalse(spline.use_cyclic_u)
        self.assertEqual(len(spline.points), 16 + 1)                            # half of 2 x 16 segments, plus the end
        self.load(_shape("<Arc2D radius='1' startAngle='2' endAngle='1'/>"))   # end before start: wraps counterclockwise
        spline = next(o for o in bpy.data.objects if o.type == 'CURVE').data.splines[0]
        first, last = spline.points[0].co, spline.points[len(spline.points) - 1].co
        self.assertAlmostEqual(math.atan2(first.y, first.x), 2.0, places=4)
        self.assertAlmostEqual(math.atan2(last.y, last.x), 1.0, places=4)
        self.load(_shape("<Circle2D radius='3'/>"))
        spline = next(o for o in bpy.data.objects if o.type == 'CURVE').data.splines[0]
        self.assertTrue(spline.use_cyclic_u)
        self.assertAlmostEqual(spline.points[0].co.length, math.sqrt(9 + 1), places=4)  # (x, y, 0, w=1)
        self.load(_shape("<Polyline2D lineSegments='0 0 1 0 1 1'/>"))
        spline = next(o for o in bpy.data.objects if o.type == 'CURVE').data.splines[0]
        self.assertEqual([tuple(round(c, 3) for c in p.co[:3]) for p in spline.points], [(0, 0, 0), (1, 0, 0), (1, 1, 0)])

    def test_polypoint_and_triangle_set_2d(self):
        self.load(_shape("<Polypoint2D point='0 0 1 1 2 0'/>"))
        pts = self.only_mesh()
        self.assertEqual((len(pts.vertices), len(pts.polygons)), (3, 0))
        self.load(_shape("<TriangleSet2D vertices='0 0 4 0 2 1 0 0 2 1 0 1 9 9'/>"))
        tris = self.only_mesh()
        self.assertEqual(len(tris.polygons), 2)                                 # the lone 7th vertex is a remainder
        uvs = [tuple(round(c, 3) for c in d.uv) for d in tris.uv_layers[0].data]
        self.assertIn((0.5, 1.0), uvs)                                           # (2, 1) in the 4 x 1 bounding box
        self.assertIn((1.0, 0.0), uvs)
        self.load(_shape("<Polypoint2D/>") + _shape("<TriangleSet2D vertices='0 0'/>") + _shape("<Polyline2D/>"))
        self.assertEqual(len(bpy.data.objects), 0)


if __name__ == "__main__":
    unittest.main()
