# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Import and export agree: a file this add-on writes comes back the same after import -> export.

Each case was found by tools/io_sync/fixed_point.py on the export test suite (import the suite's files, export them
again with the same options, diff the two) and fails on the code before its fix:

- custom normals: the importer set the file's normals while from_pydata had made every face flat, so each corner of a
  shared vertex was its own fan and was quantised on its own; the re-export split each such vertex (1908 -> 2828 on a label mesh).
- AS_IS colour space: PointSet / IndexedLineSet colours were converted sRGB -> linear even under AS_IS, which the
  export writes as Blender holds them, so each AS_IS round trip darkened them again (0.5 -> 0.214 -> 0.038).
- timeline: a 2 s animation imported into the default 1..250 timeline was exported as a 10.4 s cycle (the export
  samples frame_start..frame_end), holding still for its last 8.4 s.
- shared geometry: a USE of an IndexedFaceSet became a copy of the mesh, so the re-export wrote it out again.
- texture wrap: repeatS / repeatT of a PhysicalMaterial texture were not read, so a clamped texture came back repeating.
- names: the export prefixes and suffixes DEFs (OB_, LA_, CA_, MA_, APP_, _colour, _lines, _skin); the import kept
  them in the Blender names, so every round trip added one more (OB_LA_LA_Lamp, MA_MA_MA_Paint) and broke any ROUTE or
  Script that named the node.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_io_sync_bpy
"""

from __future__ import annotations

import collections
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension

# A smooth 3 x 3 grid of quads: 16 vertices, every inner vertex shared by four faces, one normal per vertex (the
# normals tilt with x so they are not all (0, 0, 1), which Blender would store exactly).
_GRID = 4
_POINTS = [(x, y, 0.1 * x * x) for y in range(_GRID) for x in range(_GRID)]
_NORMALS = []
for _x, _y, _z in _POINTS:
    _n = (-0.2 * _x, 0.0, 1.0)
    _l = sum(c * c for c in _n) ** 0.5
    _NORMALS.append(tuple(c / _l for c in _n))
_FACES = [(y * _GRID + x, y * _GRID + x + 1, (y + 1) * _GRID + x + 1, (y + 1) * _GRID + x)
          for y in range(_GRID - 1) for x in range(_GRID - 1)]


def _floats(values):
    return " ".join("%.6f" % v for p in values for v in p)


NORMALS_DOC = ('<X3D version="4.0"><Scene><Transform DEF="OB_Grid"><Shape>'
               '<Appearance><PhysicalMaterial/></Appearance>'
               '<IndexedFaceSet DEF="ME_Grid" coordIndex="%s"><Coordinate point="%s"/><Normal vector="%s"/>'
               '</IndexedFaceSet></Shape></Transform></Scene></X3D>'
               % (" ".join(" ".join(map(str, f)) + " -1" for f in _FACES), _floats(_POINTS), _floats(_NORMALS)))

POINT_COLOURS = [(0.0, 1.0, 0.5, 0.25), (0.021277, 0.978723, 0.5, 1.0), (0.8, 0.2, 0.1, 0.5)]
POINTS_DOC = ('<X3D version="4.0"><Scene><Transform DEF="OB_Dots"><Shape><Appearance><UnlitMaterial/></Appearance>'
              '<PointSet DEF="ME_Dots"><Coordinate point="0 0 0 1 0 0 0 1 0"/><ColorRGBA color="%s"/></PointSet>'
              '</Shape></Transform></Scene></X3D>' % _floats(POINT_COLOURS))

ANIMATION_DOC = ('<X3D version="4.0"><Scene>'
                 '<Transform DEF="OB_Mover"><Shape><Appearance><PhysicalMaterial/></Appearance><Box/></Shape></Transform>'
                 '<TimeSensor DEF="Clock" cycleInterval="2" loop="true"/>'
                 '<PositionInterpolator DEF="Path" key="0 0.5 1" keyValue="0 0 0 3 0 0 0 0 0"/>'
                 '<ROUTE fromNode="Clock" fromField="fraction_changed" toNode="Path" toField="set_fraction"/>'
                 '<ROUTE fromNode="Path" fromField="value_changed" toNode="OB_Mover" toField="set_translation"/>'
                 '</Scene></X3D>')

SHARED_DOC = ('<X3D version="4.0"><Scene>'
              '<Transform DEF="OB_A"><Shape><Appearance DEF="Look"><PhysicalMaterial baseColor="0.2 0.4 0.6"/>'
              '</Appearance><IndexedFaceSet DEF="ME_Quad" coordIndex="0 1 2 3 -1">'
              '<Coordinate point="0 0 0 1 0 0 1 1 0 0 1 0"/></IndexedFaceSet></Shape></Transform>'
              '<Transform DEF="OB_B" translation="3 0 0"><Shape><Appearance USE="Look"/>'
              '<IndexedFaceSet USE="ME_Quad"/></Shape></Transform>'
              '<Transform DEF="OB_C" translation="6 0 0"><Shape><Appearance><PhysicalMaterial baseColor="1 0 0"/>'
              '</Appearance><IndexedFaceSet USE="ME_Quad"/></Shape></Transform>'
              '</Scene></X3D>')

CLAMP_DOC = ('<X3D version="4.0"><Scene>'
             '<Transform DEF="OB_Clamped"><Shape><Appearance><PhysicalMaterial>'
             '<ImageTexture containerField="baseTexture" url=\'"tile.png"\' repeatS="false" repeatT="false"/>'
             '</PhysicalMaterial></Appearance><IndexedFaceSet coordIndex="0 1 2 3 -1">'
             '<Coordinate point="0 0 0 1 0 0 1 1 0 0 1 0"/><TextureCoordinate point="0 0 2 0 2 2 0 2"/>'
             '</IndexedFaceSet></Shape></Transform>'
             '<Transform DEF="OB_Tiled" translation="3 0 0"><Shape><Appearance><PhysicalMaterial>'
             '<ImageTexture containerField="baseTexture" url=\'"tile.png"\'/>'
             '</PhysicalMaterial></Appearance><IndexedFaceSet coordIndex="0 1 2 3 -1">'
             '<Coordinate point="0 0 0 1 0 0 1 1 0 0 1 0"/><TextureCoordinate point="0 0 2 0 2 2 0 2"/>'
             '</IndexedFaceSet></Shape></Transform>'
             '</Scene></X3D>')


_QUAD = '<Coordinate point="0 0 0 1 0 0 1 1 0 0 1 0"/>'
NAMES_DOC = ('<X3D version="4.0"><Scene>'
             '<Transform DEF="OB_Lamp" translation="0 3 0"><PointLight DEF="LA_Lamp"/></Transform>'
             '<Transform DEF="OB_Cam" translation="0 0 9"><Viewpoint DEF="CA_Cam" description="Cam"/></Transform>'
             '<Transform DEF="OB_Box"><Shape><Appearance DEF="APP_Paint"><PhysicalMaterial DEF="MA_Paint" baseColor="0.2 0.5 0.8"/>'
             '</Appearance><IndexedFaceSet DEF="ME_Box" coordIndex="0 1 2 3 -1">' + _QUAD + '</IndexedFaceSet></Shape></Transform>'
             '<Transform DEF="OB_Tinted" translation="3 0 0"><Shape><Appearance DEF="APP_Paint_colour">'
             '<PhysicalMaterial DEF="MA_Paint_colour" baseColor="0.2 0.5 0.8"/></Appearance>'
             '<IndexedFaceSet DEF="ME_Tinted" coordIndex="0 1 2 3 -1">' + _QUAD +
             '<Color color="1 0 0 0 1 0 0 0 1 1 1 1"/></IndexedFaceSet></Shape></Transform>'
             '<Transform DEF="OB_Wire" translation="6 0 0"><Shape><Appearance DEF="APP_Wire_lines">'
             '<UnlitMaterial DEF="MA_Wire_lines" emissiveColor="0 1 0"/></Appearance>'
             '<IndexedLineSet DEF="ME_Wire" coordIndex="0 1 2 3 -1">' + _QUAD + '</IndexedLineSet></Shape></Transform>'
             '</Scene></X3D>')
HAND_DOC = ('<X3D version="4.0"><Scene><Transform DEF="Holder"><PointLight DEF="LA_Lamp"/></Transform></Scene></X3D>')


def _defs(root):
    return {el.get("DEF") for el in root.iter() if el.get("DEF")}


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ImportExportSyncTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addon = tempfile.TemporaryDirectory()
        _register_extension(cls.addon.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        cls.addon.cleanup()

    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def _write(self, name, text):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('<?xml version="1.0" encoding="UTF-8"?>\n' + text)
        return path

    def _import(self, path, **options):
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path, **options), {"FINISHED"})

    def _export(self, name, **options):
        path = os.path.join(self.tmp.name, name)
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False, **options),
                         {"FINISHED"})
        return ET.parse(path).getroot()

    def _mesh_object(self):
        return next(ob for ob in bpy.context.scene.objects if ob.type == 'MESH')

    # -- custom normals ----------------------------------------------------------------------------------------------

    def test_file_normals_give_one_normal_per_shared_vertex(self):
        self._import(self._write("normals.x3d", NORMALS_DOC))
        mesh = self._mesh_object().data
        self.assertEqual(len(mesh.vertices), len(_POINTS))
        by_vertex = collections.defaultdict(set)
        for loop in mesh.loops:
            by_vertex[loop.vertex_index].add(tuple(round(c, 6) for c in mesh.corner_normals[loop.index].vector))
        split = {v: n for v, n in by_vertex.items() if len(n) > 1}
        self.assertEqual(split, {}, "corners of one vertex got different normals")
        for vertex, normals in by_vertex.items():
            got = next(iter(normals))
            for a, b in zip(got, _NORMALS[vertex]):
                self.assertAlmostEqual(a, b, delta=1e-3)

    def test_file_normals_re_export_without_splitting_vertices(self):
        self._import(self._write("normals.x3d", NORMALS_DOC))
        root = self._export("normals_again.x3d", use_normals=True)
        geometry = root.find(".//IndexedFaceSet")
        points = geometry.find("Coordinate").get("point").split()
        self.assertEqual(len(points) // 3, len(_POINTS))

    def test_file_normals_stay_smooth_on_a_crease_angle_re_export(self):
        # without use_normals the export writes creaseAngle from the faces' smooth flag; flat faces drew it faceted
        self._import(self._write("normals.x3d", NORMALS_DOC))
        self.assertTrue(all(p.use_smooth for p in self._mesh_object().data.polygons))

    # -- colour space -------------------------------------------------------------------------------------------------

    def _point_colours(self):
        mesh = self._mesh_object().data
        attribute = mesh.color_attributes[0]
        return [tuple(d.color) for d in attribute.data]

    def test_as_is_point_colours_are_kept_as_written(self):
        self._import(self._write("points.x3d", POINTS_DOC), color_space='AS_IS')
        for got, want in zip(self._point_colours(), POINT_COLOURS):
            for a, b in zip(got, want):
                self.assertAlmostEqual(a, b, places=5)

    def test_as_is_point_colours_round_trip_unchanged(self):
        self._import(self._write("points.x3d", POINTS_DOC), color_space='AS_IS')
        root = self._export("points_again.x3d", color_space='AS_IS')
        values = [float(v) for v in root.find(".//ColorRGBA").get("color").split()]
        want = [v for c in POINT_COLOURS for v in c]
        self.assertEqual(len(values), len(want))
        for a, b in zip(values, want):
            self.assertAlmostEqual(a, b, places=5)

    def test_srgb_point_colours_are_still_converted_to_linear(self):
        self._import(self._write("points.x3d", POINTS_DOC), color_space='SRGB')
        got = self._point_colours()[0]
        self.assertAlmostEqual(got[2], 0.214041, places=4)   # 0.5 display -> linear
        self.assertAlmostEqual(got[3], 0.25, places=6)       # alpha is not a colour

    # -- timeline -------------------------------------------------------------------------------------------------------

    def test_animation_sets_the_timeline_of_an_unanimated_scene(self):
        scene = bpy.context.scene
        fps = scene.render.fps / scene.render.fps_base
        self._import(self._write("anim.x3d", ANIMATION_DOC))
        self.assertEqual(scene.frame_end, scene.frame_start + round(2 * fps))
        root = self._export("anim_again.x3d", use_animation=True)
        timer = root.find(".//TimeSensor")
        self.assertAlmostEqual(float(timer.get("cycleInterval")), 2.0, places=3)

    def test_animation_never_shortens_an_animated_scene(self):
        scene = bpy.context.scene
        holder = bpy.data.objects.new("Holder", None)
        scene.collection.objects.link(holder)
        holder.keyframe_insert("location", frame=1)
        holder.location.x = 1
        holder.keyframe_insert("location", frame=400)
        scene.frame_end = 400
        self._import(self._write("anim.x3d", ANIMATION_DOC))
        self.assertEqual(scene.frame_end, 400)

    # -- shared geometry ----------------------------------------------------------------------------------------------

    def test_use_of_geometry_with_the_same_appearance_shares_the_mesh(self):
        self._import(self._write("shared.x3d", SHARED_DOC))
        objects = {ob.name: ob for ob in bpy.context.scene.objects if ob.type == 'MESH'}
        a, b, c = (next(ob for name, ob in objects.items() if name.endswith(k)) for k in ("A", "B", "C"))
        self.assertIs(a.data, b.data)
        self.assertIsNot(a.data, c.data, "a USE with another material needs its own material slot")
        self.assertEqual(len(a.data.materials), 1)
        self.assertIsNot(c.data.materials[0], a.data.materials[0])

    def test_shared_geometry_is_written_once_on_re_export(self):
        self._import(self._write("shared.x3d", SHARED_DOC))
        root = self._export("shared_again.x3d")
        faces = root.findall(".//IndexedFaceSet")
        self.assertEqual(sum(1 for f in faces if f.get("USE")), 1)
        self.assertEqual(sum(1 for f in faces if f.find("Coordinate") is not None), 2)

    # -- texture wrap -----------------------------------------------------------------------------------------------------

    def _tile(self):
        image = bpy.data.images.new("tile", 4, 4)
        image.filepath_raw = os.path.join(self.tmp.name, "tile.png")
        image.file_format = 'PNG'
        image.save()
        bpy.data.images.remove(image)

    def test_clamped_physical_texture_imports_as_clip(self):
        self._tile()
        self._import(self._write("clamp.x3d", CLAMP_DOC))
        extensions = {}
        for ob in bpy.context.scene.objects:
            if ob.type == 'MESH':
                nodes = ob.data.materials[0].node_tree.nodes
                extensions[ob.name] = {n.extension for n in nodes if n.type == 'TEX_IMAGE'}
        clamped = next(v for k, v in extensions.items() if k.endswith("Clamped"))
        tiled = next(v for k, v in extensions.items() if k.endswith("Tiled"))
        self.assertEqual(clamped, {"CLIP"})
        self.assertEqual(tiled, {"REPEAT"})

    def test_clamped_physical_texture_re_exports_clamped(self):
        self._tile()
        self._import(self._write("clamp.x3d", CLAMP_DOC))
        root = self._export("clamp_again.x3d")
        wraps = collections.Counter((t.get("repeatS"), t.get("repeatT")) for t in root.iter("ImageTexture")
                                    if not t.get("USE"))
        self.assertEqual(wraps, collections.Counter({("false", "false"): 1, (None, None): 1}))

    # -- names --------------------------------------------------------------------------------------------------------

    def _re_import(self, path, name):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self._import(path)
        return self._export(name)

    def test_exported_names_come_back_unchanged(self):
        self._import(self._write("names.x3d", NAMES_DOC))
        first = self._export("names_1.x3d")
        wanted = {"OB_Lamp", "LA_Lamp", "OB_Cam", "CA_Cam", "OB_Box", "APP_Paint", "MA_Paint", "OB_Tinted",
                  "MA_Paint_colour", "OB_Wire", "MA_Wire_lines"}
        self.assertEqual(wanted - _defs(first), set())
        self.assertEqual([d for d in _defs(first) if "MA_MA_" in d or "LA_LA_" in d or "CA_CA_" in d or
                          d.endswith("_colour_colour") or d.endswith("_lines_lines")], [])

    def test_names_do_not_drift_over_round_trips(self):
        self._import(self._write("names.x3d", NAMES_DOC))
        first = _defs(self._export("names_1.x3d"))
        second = _defs(self._re_import(os.path.join(self.tmp.name, "names_1.x3d"), "names_2.x3d"))
        self.assertEqual(first, second)

    def test_blender_names_drop_only_the_export_prefixes(self):
        self._import(self._write("names.x3d", NAMES_DOC))
        names = {ob.name for ob in bpy.context.scene.objects}
        self.assertTrue({"Lamp", "Cam", "Box"} <= names, names)
        self.assertIn("Paint", bpy.data.materials)

    def test_hand_written_prefix_is_kept(self):
        self._import(self._write("hand.x3d", HAND_DOC))
        lights = [ob for ob in bpy.context.scene.objects if ob.type == 'LIGHT']
        self.assertEqual([ob.name for ob in lights], ["LA_Lamp"])


if __name__ == "__main__":
    unittest.main()
