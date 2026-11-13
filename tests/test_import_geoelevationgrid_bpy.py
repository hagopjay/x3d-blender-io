# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Importer: GeoElevationGrid (X3D 4.0 Geospatial component) and GeoViewpoint.

The importer skipped a GeoElevationGrid with "unsupported type", so the Showcase's ellipsoid-earth and ellipsoid-moon
imported as an empty scene (a 132-byte glb). It now builds the grid as X_ITE 16.7.1 does: geoGridOrigin plus
xSpacing in longitude (easting) and zSpacing in latitude (northing), heights times yScale along the ellipsoid
normal, two triangles per cell, in geocentric metres.

Blender keeps vertices as float32, 0.5 m apart near the Earth's radius, so a test that wants 1e-3 m puts a small patch
under a geoOrigin (its coordinates are then a few km) and compares against textbook geodetic formulas in float64.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_import_geoelevationgrid_bpy
"""

from __future__ import annotations

import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension, SOURCE_DIR

sys.path.insert(0, str(SOURCE_DIR))
import geospatial  # noqa: E402

SCENES = Path(__file__).resolve().parents[1] / "docs" / "showcase" / "scenes"
WGS_A, WGS_F = 6378137.0, 1 / 298.257223563
Y_UP_TO_Z_UP = ((1, 0, 0), (0, 0, -1), (0, 1, 0))   # the import's global matrix: Blender = this @ X3D


def analytic(lat, lon, height=0.0, a=WGS_A, f=WGS_F):
    """Geodetic degrees and metres to geocentric metres by the textbook parametric form, not the module's."""
    c = a * (1 - f)
    p, l = math.radians(lat), math.radians(lon)
    d = math.hypot(a * math.cos(p), c * math.sin(p))
    ring, z0 = a * a * math.cos(p) / d, c * c * math.sin(p) / d
    up = np.array((math.cos(p) * math.cos(l), math.cos(p) * math.sin(l), math.sin(p)))
    return np.array((ring * math.cos(l), ring * math.sin(l), z0)) + height * up


def scene(body, head=""):
    return ("<?xml version='1.0' encoding='UTF-8'?>\n<X3D profile='Immersive' version='4.0'><head>"
            "<component name='Geospatial' level='1'/></head><Scene>%s%s</Scene></X3D>\n" % (head, body))


def grid(attrs="", children="", appearance=""):
    return ("<Shape>%s<GeoElevationGrid %s>%s</GeoElevationGrid></Shape>" % (appearance, attrs, children))


# 3 x 3 grid of 0.05 degrees around 45 N 3 E, under a geoOrigin there: the coordinates are metres from the origin
ORIGIN = "<GeoOrigin geoSystem='\"GD\" \"WE\"' geoCoords='45 3 0'/>"
PATCH = ("geoGridOrigin='44.95 2.95 0' xDimension='3' zDimension='3' xSpacing='0.05' zSpacing='0.05' "
         "height='0 0 0  0 1500 0  0 0 0' yScale='2' ")


class MathTests(unittest.TestCase):
    def test_geo_system_codes(self):
        gs = geospatial.parse_geo_system(["GD", "WE"])
        self.assertEqual((gs.kind, gs.a, gs.standard_order), ("GD", WGS_A, True))
        self.assertAlmostEqual(gs.c, WGS_A * (1 - WGS_F), places=6)
        self.assertEqual(geospatial.parse_geo_system([]), gs)   # GD WE by default
        self.assertEqual(geospatial.parse_geo_system(["GD", "WGS84"]), gs)
        self.assertFalse(geospatial.parse_geo_system(["GD", "WE", "longitude_first"]).standard_order)
        self.assertEqual(geospatial.parse_geo_system(["GD", "MOON"]).a, 1738140.0)
        self.assertEqual(geospatial.parse_geo_system(["GD", "IN"]).a, 6378388.0)
        utm = geospatial.parse_geo_system(["UTM", "Z33", "S", "easting_first"])
        self.assertEqual((utm.kind, utm.zone, utm.south, utm.standard_order), ("UTM", 33, True, False))
        self.assertEqual(geospatial.parse_geo_system(["GCC"]).kind, "GC")

    def test_geodetic_to_geocentric_matches_the_textbook_formula_to_a_millimetre(self):
        gs = geospatial.parse_geo_system(["GD", "WE"])
        for lat, lon, h in ((0.0, 0.0, 0.0), (45.0, 0.0, 0.0), (-33.8688, 151.2093, 58.0), (51.5, -0.12, 9000.0),
                            (89.9, 10.0, -400.0)):
            got = np.array(geospatial.to_geocentric(gs, lat, lon, h))
            self.assertLess(np.abs(got - analytic(lat, lon, h)).max(), 1e-3, (lat, lon, h))

    def test_the_poles_and_the_equator(self):
        gs = geospatial.parse_geo_system(["GD", "WE"])
        c = WGS_A * (1 - WGS_F)
        self.assertEqual([float(v) for v in geospatial.to_geocentric(gs, 0, 0, 0)], [WGS_A, 0.0, 0.0])
        x, y, z = (float(v) for v in geospatial.to_geocentric(gs, 90, 0, 0))
        self.assertLess(math.hypot(x, y), 1e-6)
        self.assertAlmostEqual(z, c, places=6)
        self.assertAlmostEqual(float(geospatial.to_geocentric(gs, -90, 0, 100)[2]), -(c + 100), places=6)

    def test_longitude_first_swaps_the_first_two_coordinates(self):
        a = geospatial.to_geocentric(geospatial.parse_geo_system(["GD", "WE"]), 20, -40, 500)
        b = geospatial.to_geocentric(geospatial.parse_geo_system(["GD", "WE", "longitude_first"]), -40, 20, 500)
        self.assertEqual([float(v) for v in a], [float(v) for v in b])

    def test_geocentric_to_geodetic_undoes_it(self):
        gs = geospatial.parse_geo_system(["GD", "WE"])
        for lat, lon, h in ((10.0, 20.0, 30.0), (-60.0, -170.0, 25e6), (89.0, 5.0, 100.0)):
            point = [float(v) for v in geospatial.to_geocentric(gs, lat, lon, h)]
            la, lo, he = geospatial.geocentric_to_geodetic(gs, *point)
            self.assertAlmostEqual(math.degrees(la), lat, places=7)
            self.assertAlmostEqual(math.degrees(lo), lon, places=7)
            self.assertAlmostEqual(he, h, delta=2e-3)

    def test_utm_central_meridian_northing(self):
        # zone 31's central meridian is 3 E; 45 N is 4,982,950.4 m north there (k0 0.9996 times 4,984,944.4 m of arc)
        gs = geospatial.parse_geo_system(["UTM", "Z31"])
        lat, lon = geospatial._utm_to_geodetic(gs, 4982950.4, 500000.0)
        self.assertAlmostEqual(math.degrees(lat), 45.0, delta=1e-6)
        self.assertAlmostEqual(math.degrees(lon), 3.0, delta=1e-9)
        south = geospatial.parse_geo_system(["UTM", "Z31", "S"])
        lat, _ = geospatial._utm_to_geodetic(south, 1e7 - 4982950.4, 500000.0)
        self.assertAlmostEqual(math.degrees(lat), -45.0, delta=1e-6)

    def test_utm_inverse_is_good_to_a_millimetre(self):
        # (lat, lon, northing, easting) from Karney's Krueger series (order 6, mm-exact), zone 31 (central meridian 3 E)
        for lat, lon, northing, easting, south in ((45.0, 4.5, 4984044.798, 618222.966, False),
                                                   (20.0, 2.0, 2211793.556, 395390.676, False),
                                                   (70.0, 1.5, 7766577.415, 442748.110, False),
                                                   (-33.0, 4.0, 6348269.026, 593417.778, True)):
            utm = geospatial.parse_geo_system(["UTM", "Z31"] + (["S"] if south else []))
            got = np.array([float(v) for v in geospatial.to_geocentric(utm, northing, easting, 0.0)])
            self.assertLess(np.linalg.norm(got - analytic(lat, lon)), 1e-3, (lat, lon))


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class GeoElevationGridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_geo_grid_")
        _register_extension(cls.tmpdir)

    def load(self, text=None, path=None):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        if path is None:
            path = os.path.join(self.tmpdir, "geo.x3d")
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
        meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
        return meshes[0] if meshes else None

    @staticmethod
    def verts(mesh):
        co = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", co)
        return co.reshape(-1, 3).astype(np.float64)

    @staticmethod
    def triangles(mesh):
        corner = np.empty(len(mesh.loops), dtype=np.int32)
        mesh.loops.foreach_get("vertex_index", corner)
        return corner.reshape(-1, 3)

    def facing(self, mesh):
        """Dot of each triangle's normal with the direction from the Earth's centre, sign only (0 for a sliver)."""
        co, tri = self.verts(mesh), self.triangles(mesh)
        normal = np.cross(co[tri[:, 1]] - co[tri[:, 0]], co[tri[:, 2]] - co[tri[:, 0]])
        out = np.einsum("ij,ij->i", normal, co[tri].mean(axis=1))
        return np.where(np.linalg.norm(normal, axis=1) > 1e-3, np.sign(out), 0)

    # ------------------------------------------------------------------------------------------- the Showcase scenes
    def test_the_showcase_earth_is_a_globe_not_an_empty_scene(self):
        mesh = self.load(path=str(SCENES / "ellipsoid-earth.x3d")).data
        self.assertEqual(len(mesh.vertices), 37 * 19)
        self.assertEqual(len(mesh.polygons), 2 * 36 * 18)
        r = np.linalg.norm(self.verts(mesh), axis=1)
        self.assertAlmostEqual(r.max(), WGS_A, delta=0.5)                    # the equator
        self.assertAlmostEqual(r.min(), WGS_A * (1 - WGS_F), delta=0.5)      # the poles
        self.assertFalse(mesh.validate())   # nothing to correct

    def test_every_vertex_of_the_globe_is_on_the_ellipsoid_to_float32(self):
        mesh = self.load(path=str(SCENES / "ellipsoid-earth.x3d")).data
        co = self.verts(mesh)
        for k in range(len(co)):
            z, x = divmod(k, 37)
            # float32 holds 6.4e6 to 0.5 m, so up to 0.25 m a coordinate and 0.43 m in all
            self.assertLess(np.linalg.norm(co[k] - analytic(-90 + 10 * z, -180 + 10 * x)), 0.45, k)

    def test_the_moon_scene_uses_the_moon_ellipsoid(self):
        mesh = self.load(path=str(SCENES / "ellipsoid-moon.x3d")).data
        r = np.linalg.norm(self.verts(mesh), axis=1)
        self.assertAlmostEqual(r.max(), 1738140.0, delta=0.2)
        self.assertAlmostEqual(r.min(), 1735970.0, delta=0.2)

    def test_the_poles_are_rows_of_one_point_and_the_other_triangles_face_out(self):
        mesh = self.load(path=str(SCENES / "ellipsoid-earth.x3d")).data
        co = self.verts(mesh)
        for row, z in ((0, -1), (18, 1)):
            pole = co[row * 37:(row + 1) * 37]
            self.assertLess(np.abs(pole[:, :2]).max(), 1e-6)     # all 37 are the pole to a nanometre
            self.assertAlmostEqual(pole[0, 2], z * WGS_A * (1 - WGS_F), delta=0.5)
        facing = self.facing(mesh)
        self.assertEqual(int((facing == 0).sum()), 2 * 36)       # a degenerate triangle per cell at each pole
        self.assertEqual(int((facing < 0).sum()), 0)

    def test_the_globe_has_a_camera_that_sees_it(self):
        self.load(path=str(SCENES / "ellipsoid-earth.x3d"))
        camera = next(o for o in bpy.context.scene.objects if o.type == "CAMERA")
        to_blender = np.array(Y_UP_TO_Z_UP, dtype=float)
        expected = to_blender @ analytic(20, -40, 25e6)
        self.assertLess(np.abs(np.array(camera.matrix_world.translation) - expected).max(), 4.0)   # float32 at 3e7
        self.assertGreater(camera.data.clip_end, np.linalg.norm(expected))
        self.assertLess(camera.data.clip_start, np.linalg.norm(expected) - WGS_A)

    # ------------------------------------------------------------------------------------------------ grid structure
    def test_grid_counts_and_vertex_order(self):
        ob = self.load(scene(grid("xDimension='5' zDimension='3' xSpacing='2' zSpacing='3' geoGridOrigin='10 20 0' "
                                  "height='%s'" % " ".join(str(10 * x + z) for z in range(3) for x in range(5)))))
        mesh = ob.data
        self.assertEqual((len(mesh.vertices), len(mesh.polygons)), (15, 2 * 4 * 2))
        self.assertEqual(len(mesh.loops), 3 * 16)
        co = self.verts(mesh)
        gs = geospatial.parse_geo_system(["GD", "WE"])
        for z in range(3):
            for x in range(5):   # vertex z * xDimension + x: x runs east (longitude), z north (latitude)
                want = np.array(geospatial.to_geocentric(gs, 10 + 3 * z, 20 + 2 * x, 10 * x + z))
                self.assertLess(np.abs(co[z * 5 + x] - want).max(), 0.3)

    def test_a_patch_is_on_the_ellipsoid_to_a_millimetre_with_heights_along_the_normal(self):
        mesh = self.load(scene(grid(PATCH, ORIGIN))).data
        co = self.verts(mesh)
        origin = analytic(45, 3)
        for k in range(9):
            z, x = divmod(k, 3)
            height = 3000.0 if k == 4 else 0.0   # 1500 m times yScale 2
            want = analytic(44.95 + 0.05 * z, 2.95 + 0.05 * x, height) - origin
            self.assertLess(np.abs(co[k] - want).max(), 1e-3, k)
        normal = analytic(45, 3, 1.0) - analytic(45, 3)   # the ellipsoid normal there, a unit vector
        self.assertLess(np.abs(co[4] - 3000.0 * normal).max(), 1e-3)

    def test_rotate_y_up_makes_the_local_frame_east_up_south(self):
        origin = "<GeoOrigin geoSystem='\"GD\" \"WE\"' geoCoords='45 3 0' rotateYUp='true'/>"
        co = self.verts(self.load(scene(grid(PATCH, origin))).data)
        centre = co[4]
        self.assertLess(np.abs(centre - np.array([0.0, 3000.0, 0.0])).max(), 1e-3)   # up is +Y, the height is on it
        east = co[5] - co[3]       # x runs east: +X
        north = co[7] - co[1]      # z runs north: -Z (X3D's Z points south)
        self.assertGreater(east[0], 7000.0)
        self.assertLess(abs(east[2]), 1.0)
        self.assertLess(north[2], -10000.0)
        self.assertLess(abs(north[0]), 1.0)

    def test_longitude_first_order(self):
        a = self.verts(self.load(scene(grid("geoGridOrigin='10 20 0' xDimension='3' zDimension='2' xSpacing='1' "
                                            "zSpacing='2'"))).data)
        b = self.verts(self.load(scene(grid("geoSystem='\"GD\" \"WE\" \"longitude_first\"' geoGridOrigin='20 10 0' "
                                            "xDimension='3' zDimension='2' xSpacing='1' zSpacing='2'"))).data)
        self.assertEqual(a.tolist(), b.tolist())

    def test_utm_grid(self):
        # zone 31 north, the origin of the grid at 45 N 3 E (the central meridian), 100 m cells
        attrs = ("geoSystem='\"UTM\" \"Z31\"' geoGridOrigin='4982950.4 500000 0' xDimension='3' zDimension='3' "
                 "xSpacing='100' zSpacing='100'")
        co = self.verts(self.load(scene(grid(attrs, ORIGIN))).data)
        self.assertLess(np.abs(co[0]).max(), 0.05)    # the series is good to centimetres
        east_step = np.linalg.norm(co[1] - co[0])
        north_step = np.linalg.norm(co[3] - co[0])
        self.assertAlmostEqual(east_step, 100 / 0.9996, delta=0.01)    # grid metres are 0.9996 of ground metres here
        self.assertAlmostEqual(north_step, 100 / 0.9996, delta=0.01)
        swapped = ("geoSystem='\"UTM\" \"Z31\" \"easting_first\"' geoGridOrigin='500000 4982950.4 0' xDimension='3' "
                   "zDimension='3' xSpacing='100' zSpacing='100'")
        self.assertLess(np.abs(self.verts(self.load(scene(grid(swapped, ORIGIN))).data) - co).max(), 1e-3)

    def test_geocentric_grid_follows_x_ite(self):
        attrs = "geoSystem='\"GC\"' geoGridOrigin='1000 2000 3000' xDimension='3' zDimension='2' xSpacing='10' " \
                "zSpacing='20' height='0 1 2 3 4 5' yScale='2'"
        co = self.verts(self.load(scene(grid(attrs))).data)
        # X_ITE 16.7.1 steps zSpacing along the first geocentric axis, xSpacing along the second, height on the third
        self.assertEqual(co[0].tolist(), [1000, 2000, 3000])
        self.assertEqual(co[2].tolist(), [1000, 2020, 3004])
        self.assertEqual(co[5].tolist(), [1020, 2020, 3010])

    # ---------------------------------------------------------------------- faces: a strip, ccw and solid
    def flat_strip(self, attrs=""):
        return self.load(scene(grid("geoGridOrigin='0 0 0' xDimension='3' zDimension='2' xSpacing='1' zSpacing='1' "
                                    + attrs)))

    def test_a_one_row_grid_is_a_strip_of_four_triangles_facing_out(self):
        mesh = self.flat_strip().data
        self.assertEqual((len(mesh.vertices), len(mesh.polygons)), (6, 4))
        tri = self.triangles(mesh).tolist()
        # cell (x, z) has corners p1 = z * 3 + x, p2 = p1 + 3, p3 = p2 + 1, p4 = p1 + 1: p1 p3 p2 and p1 p4 p3
        self.assertEqual(tri, [[0, 4, 3], [0, 1, 4], [1, 5, 4], [1, 2, 5]])
        self.assertEqual(self.facing(mesh).tolist(), [1, 1, 1, 1])
        gs = geospatial.parse_geo_system(["GD", "WE"])
        for k, point in enumerate(self.verts(mesh)):      # 0 0, 0 1, 0 2 on the equator, then 1 0, 1 1, 1 2
            z, x = divmod(k, 3)
            self.assertLess(np.abs(point - np.array(geospatial.to_geocentric(gs, z, x, 0.0))).max(), 0.3)

    def test_ccw_false_turns_every_triangle_over(self):
        mesh = self.flat_strip("ccw='false'").data
        self.assertEqual(self.facing(mesh).tolist(), [-1, -1, -1, -1])
        self.assertEqual(self.triangles(mesh).tolist(), [[0, 3, 4], [0, 4, 1], [1, 4, 5], [1, 5, 2]])

    def test_solid_sets_back_face_culling_of_a_physical_material(self):
        appearance = "<Appearance><PhysicalMaterial/></Appearance>"
        for solid, culled in (("", True), ("solid='false'", False)):
            ob = self.load(scene(grid("geoGridOrigin='0 0 0' xDimension='2' zDimension='2' " + solid,
                                      appearance=appearance)))
            self.assertEqual(ob.data.materials[0].use_backface_culling, culled, solid)

    # ------------------------------------------------------------------------- texture, colour, normals
    def test_default_texture_coordinates_run_over_the_grid(self):
        mesh = self.flat_strip().data
        uv = np.array([d.uv for d in mesh.uv_layers.active.data])
        for corner, vertex in enumerate(self.triangles(mesh).reshape(-1)):
            z, x = divmod(int(vertex), 3)
            self.assertAlmostEqual(uv[corner][0], x / 2, places=6)
            self.assertAlmostEqual(uv[corner][1], z / 1, places=6)

    def test_texture_coordinates_of_the_file_are_used(self):
        points = ", ".join("%g %g" % (0.1 * i, 0.9 - 0.1 * i) for i in range(6))
        mesh = self.load(scene(grid("geoGridOrigin='0 0 0' xDimension='3' zDimension='2'",
                                    "<TextureCoordinate point='%s'/>" % points))).data
        uv = np.array([d.uv for d in mesh.uv_layers.active.data])
        for corner, vertex in enumerate(self.triangles(mesh).reshape(-1)):
            self.assertAlmostEqual(uv[corner][0], 0.1 * vertex, places=6)
            self.assertAlmostEqual(uv[corner][1], 0.9 - 0.1 * vertex, places=6)

    def test_colour_per_vertex_and_per_face(self):
        colours = "1 0 0, 0 1 0, 0 0 1, 1 1 0, 0 1 1, 1 0 1"
        mesh = self.load(scene(grid("geoGridOrigin='0 0 0' xDimension='3' zDimension='2'",
                                    "<Color color='%s'/>" % colours))).data
        rgb = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 0], [0, 1, 1], [1, 0, 1]], dtype=float)
        got = np.array([c.color[:3] for c in mesh.color_attributes.active_color.data])
        self.assertEqual(got.tolist(), rgb[self.triangles(mesh).reshape(-1)].tolist())
        mesh = self.load(scene(grid("geoGridOrigin='0 0 0' xDimension='3' zDimension='2' colorPerVertex='false'",
                                    "<Color color='1 0 0, 0 0 1'/>"))).data
        got = np.array([c.color[:3] for c in mesh.color_attributes.active_color.data]).reshape(4, 3, 3)
        self.assertEqual(got[:2].tolist(), [[[1, 0, 0]] * 3] * 2)   # the two triangles of cell 0
        self.assertEqual(got[2:].tolist(), [[[0, 0, 1]] * 3] * 2)

    def test_normals_of_the_file_are_used_and_the_default_ones_face_out(self):
        # Blender stores a custom normal relative to its faces' own, to about 0.3 degrees (0.0054 here) on cells this
        # steep, and clamps one far from them, so these are the ellipsoid's normals, not 0 1 0
        def up(lat, lon):
            return analytic(lat, lon, 1.0) - analytic(lat, lon)
        attrs = "geoGridOrigin='0 0 0' xDimension='3' zDimension='2' xSpacing='1' zSpacing='1' "
        vectors = [up(z, x) for z in range(2) for x in range(3)]
        mesh = self.load(scene(grid(attrs, "<Normal vector='%s'/>" % ", ".join("%.9f %.9f %.9f" % tuple(v)
                                                                               for v in vectors)))).data
        got = np.array([n.vector for n in mesh.corner_normals])
        self.assertLess(np.abs(got - np.array(vectors)[self.triangles(mesh).reshape(-1)]).max(), 0.01)
        cells = [up(0.5, 0.5), up(0.5, 1.5)]
        mesh = self.load(scene(grid(attrs + "normalPerVertex='false'", "<Normal vector='%s'/>" % ", ".join(
            "%.9f %.9f %.9f" % tuple(v) for v in cells)))).data
        got = np.array([n.vector for n in mesh.corner_normals]).reshape(4, 3, 3)
        for cell in range(4):    # triangles 0, 1 are cell 0 and 2, 3 are cell 1
            self.assertLess(np.abs(got[cell] - cells[cell // 2]).max(), 0.01)
        flat = self.flat_strip().data    # no Normal, creaseAngle 0: each triangle flat and facing out of the Earth
        for corner, n in zip(self.triangles(flat).reshape(-1), flat.corner_normals):
            self.assertGreater(np.dot(n.vector, self.verts(flat)[corner]) / np.linalg.norm(self.verts(flat)[corner]),
                               0.99)

    # ----------------------------------------------------------------------------------------- odd input
    def test_missing_heights_are_zero_and_a_grid_without_cells_imports_nothing(self):
        mesh = self.load(scene(grid("xDimension='3' zDimension='2' height='5'"))).data
        co = self.verts(mesh)
        self.assertAlmostEqual(np.linalg.norm(co[0]), WGS_A + 5.0, delta=0.5)   # the one height given
        self.assertAlmostEqual(np.linalg.norm(co[1]), WGS_A, delta=0.5)
        self.assertIsNone(self.load(scene(grid("xDimension='1' zDimension='4'"))))
        self.assertIsNone(self.load(scene(grid(""))))

    def test_a_texture_coordinate_node_with_too_few_points_falls_back_to_the_default(self):
        mesh = self.load(scene(grid("xDimension='3' zDimension='2'", "<TextureCoordinate point='0 0, 1 1'/>"))).data
        self.assertEqual(len(mesh.uv_layers.active.data), 12)


    # ------------------------------------------------------------------------- a malformed vector does not abort the import
    def test_a_vector_with_the_wrong_number_of_values_is_replaced_by_its_default(self):
        # geoGridOrigin and geoCoords are three-value vectors. getFieldAsFloatTuple returned None for two values, which
        # the node unpacked: "TypeError: 'NoneType' object is not subscriptable" aborted the whole import.
        body = "xDimension='3' zDimension='3' xSpacing='1' zSpacing='1' height='0 0 0  0 0 0  0 0 0'"
        mesh = self.load(scene(grid("geoGridOrigin='1 2' " + body)))   # origin 0 0 0: on the equator at the prime meridian
        self.assertEqual(len(mesh.data.vertices), 9)
        self.assertAlmostEqual(float(np.linalg.norm(self.verts(mesh.data)[0])), WGS_A, delta=1.0)
        mesh = self.load(scene(grid("geoGridOrigin='1 2 0' " + body, "<GeoOrigin geoCoords='1 2'/>")))   # geoOrigin 0 0 0
        self.assertEqual(len(mesh.data.vertices), 9)
        self.assertAlmostEqual(float(np.linalg.norm(self.verts(mesh.data)[0])),
                               float(np.linalg.norm(analytic(1, 2, 0) - analytic(0, 0, 0))), delta=1.0)

    def test_a_non_geo_vector_of_the_wrong_length_uses_its_default_too(self):
        text = scene("<DirectionalLight direction='1 2'/><Shape><Box/></Shape>")
        self.assertIsNotNone(self.load(text))   # a two-value direction aborted the import the same way


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class GeoViewpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_geo_view_")
        _register_extension(cls.tmpdir)

    def camera(self, viewpoint):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        path = os.path.join(self.tmpdir, "view.x3d")
        with open(path, "w", encoding="utf-8") as f:
            f.write(scene(viewpoint))
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
        return next(o for o in bpy.context.scene.objects if o.type == "CAMERA")

    @staticmethod
    def x3d_pose(camera):
        """Camera position, forward (-Z) and up (+Y) in X3D space, undoing the import's Y-up to Z-up matrix."""
        m = np.array(camera.matrix_world)
        to_x3d = np.array(Y_UP_TO_Z_UP, dtype=float).T
        return to_x3d @ m[:3, 3], to_x3d @ -m[:3, 2], to_x3d @ m[:3, 1]

    def test_the_default_orientation_looks_north_with_up_away_from_the_earth(self):
        camera = self.camera("<GeoViewpoint position='30 50 1000000'/>")
        position, forward, up = self.x3d_pose(camera)
        self.assertLess(np.abs(position - analytic(30, 50, 1e6)).max(), 0.3)
        lat, lon = math.radians(30), math.radians(50)
        north = np.array((-math.sin(lat) * math.cos(lon), -math.sin(lat) * math.sin(lon), math.cos(lat)))
        normal = np.array((math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)))
        self.assertLess(np.abs(forward - north).max(), 1e-3)
        self.assertLess(np.abs(up - normal).max(), 1e-3)

    def test_orientation_is_relative_to_the_local_frame_and_the_clip_range_holds_the_globe(self):
        camera = self.camera("<GeoViewpoint position='0 0 2000000' orientation='1 0 0 -1.5707963'/>")
        position, forward, up = self.x3d_pose(camera)
        self.assertLess(np.abs(forward - (-position / np.linalg.norm(position))).max(), 1e-3)   # looking down
        self.assertLess(np.abs(up - np.array([0.0, 0.0, 1.0])).max(), 1e-3)                     # north is up
        self.assertGreater(camera.data.clip_end, np.linalg.norm(position) + WGS_A * 0.99)
        near_far = self.camera("<GeoViewpoint position='0 0 2000000' nearDistance='10' farDistance='5e7'/>").data
        self.assertEqual((near_far.clip_start, near_far.clip_end), (10.0, 5e7))

    def test_a_position_with_two_values_falls_back_to_the_default_position(self):
        position, _, _ = self.x3d_pose(self.camera("<GeoViewpoint position='1 2'/>"))
        self.assertLess(np.abs(position - analytic(0, 0, 100000)).max(), 0.3)

if __name__ == "__main__":
    unittest.main()
