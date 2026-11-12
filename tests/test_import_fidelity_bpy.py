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
* Lines and points were lit with the diffuse colour; X3D draws them unlit, in the colours of their Color node, else
  in emissiveColor (black when unset), else white without a material. Their material is now the unlit shape the
  glTF exporter writes as KHR_materials_unlit, and point and line sets keep their Color as COLOR_0.
* Per-vertex face colours went from sRGB to linear twice (0.5 became 0.04, not 0.21), and every ColorRGBA alpha
  went through the sRGB curve too (0.5 became 0.21).
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


def _write_png(path, rgb=(250, 200, 150), size=2):
    """A tiny opaque RGB PNG, written without Pillow."""
    import zlib

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _shape(geometry, appearance="<Appearance><Material/></Appearance>", name=None):
    def_attr = " DEF='%s'" % name if name else ""
    return "<Shape%s>%s%s</Shape>" % (def_attr, appearance, geometry)


def _glb_json(path):
    with open(path, "rb") as f:
        raw = f.read()
    length = struct.unpack("<I", raw[12:16])[0]
    return json.loads(raw[20:20 + length])


def _glb(path):
    """(json, binary chunk) of a .glb."""
    with open(path, "rb") as f:
        raw = f.read()
    length = struct.unpack("<I", raw[12:16])[0]
    gltf = json.loads(raw[20:20 + length])
    rest = raw[20 + length:]
    blob = rest[8:8 + struct.unpack("<I", rest[:4])[0]] if len(rest) >= 8 else b""
    return gltf, blob


def _accessor(gltf, blob, index):
    """An accessor's values as lists of floats (normalized integers scaled to 0..1)."""
    acc = gltf["accessors"][index]
    view = gltf["bufferViews"][acc["bufferView"]]
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[acc["type"]]
    fmt, scale = {5126: ("f", 1.0), 5123: ("H", 65535.0), 5121: ("B", 255.0)}[acc["componentType"]]
    size = struct.calcsize("<" + fmt)
    stride = view.get("byteStride", size * width)
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    out = []
    for i in range(acc["count"]):
        values = struct.unpack_from("<%d%s" % (width, fmt), blob, start + i * stride)
        out.append([v / scale if fmt != "f" else v for v in values])
    return out


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

    # ------------------------------------------------------------ lines and points: unlit, as glTF can say it
    def line_material_source(self, material):
        """The node whose colour the unlit material draws, and the alpha mix (None without alpha). The shape:
        Output <- [alpha Mix(Transparent, .)] <- Mix(Light Path 'Is Camera Ray', Transparent, Emission) <- colour."""
        out = next(n for n in material.node_tree.nodes if n.type == 'OUTPUT_MATERIAL')
        node = out.inputs['Surface'].links[0].from_node
        self.assertEqual(node.type, 'MIX_SHADER')
        mix = None
        if not (node.inputs[0].links and node.inputs[0].links[0].from_node.type == 'LIGHT_PATH'):
            mix = node                                                  # the alpha mix
            self.assertEqual(mix.inputs[1].links[0].from_node.type, 'BSDF_TRANSPARENT')
            node = mix.inputs[2].links[0].from_node
        self.assertEqual(node.inputs[0].links[0].from_socket.name, 'Is Camera Ray')
        self.assertEqual(node.inputs[1].links[0].from_node.type, 'BSDF_TRANSPARENT')   # lights nothing, casts no shadow
        emission = node.inputs[2].links[0].from_node
        self.assertEqual((emission.type, emission.inputs['Strength'].default_value), ('EMISSION', 1.0))
        return emission.inputs['Color'].links[0].from_node, mix

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
        src, mix = self.line_material_source(line_mat)
        self.assertEqual(src.type, 'RGB')
        self.assertIsNone(mix)
        self.assertEqual([round(c, 3) for c in src.outputs[0].default_value[:3]], [1.0, 0.0, 0.0])
        meshes = {len(o.data.polygons) > 0: o for o in by_type['MESH']}
        self.assertIs(meshes[False].data.materials[0], line_mat)         # the point set shares the unlit material
        surface = self.bsdf(meshes[True].data.materials[0])                # the box keeps the lit material
        self.assertEqual([round(c, 3) for c in surface.inputs["Base Color"].default_value[:3]], [0.1, 0.9, 0.1])
        gltf = self.export_glb(use_mesh_edges=True, use_mesh_vertices=True)
        modes = sorted(p.get("mode", 4) for m in gltf["meshes"] for p in m["primitives"])
        self.assertEqual(modes, [0, 1, 4])
        unlit = [m for m in gltf["materials"] if "KHR_materials_unlit" in m.get("extensions", {})]
        self.assertEqual(len(unlit), 1, gltf["materials"])
        self.assertEqual(unlit[0]["pbrMetallicRoughness"]["baseColorFactor"], [1, 0, 0, 1])
        self.assertIn("KHR_materials_unlit", gltf["extensionsUsed"])

    def test_line_colour_survives_the_x3d_40_export(self):
        self.load(_shape("<IndexedLineSet coordIndex='0 1 2 -1'><Coordinate point='0 0 0 1 0 0 1 1 0'/></IndexedLineSet>",
                         "<Appearance><Material emissiveColor='1 0 0'/></Appearance>"))
        out = os.path.join(self.tmpdir, "lines_out.x3d")
        self.assertIn("FINISHED", bpy.ops.export_scene.x3d(filepath=out, x3d_version='X3D40'))
        with open(out, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("<IndexedLineSet", text)
        self.assertRegex(text, r"<UnlitMaterial[^>]*emissiveColor=\"1\.0+ 0\.0+ 0\.0+\"")

    def test_a_material_without_emissive_draws_its_lines_black_and_no_material_draws_them_white(self):
        self.load(_shape("<IndexedLineSet coordIndex='0 1 -1'><Coordinate point='0 0 0 1 0 0'/></IndexedLineSet>",
                         "<Appearance><Material diffuseColor='1 1 0'/></Appearance>")
                  + _shape("<PointSet><Coordinate point='0 0 1 1 0 1'/></PointSet>", ""))
        curve = next(o for o in bpy.data.objects if o.type == 'CURVE')
        points = next(o for o in bpy.data.objects if o.type == 'MESH')
        src, _ = self.line_material_source(curve.data.materials[0])
        self.assertEqual(list(src.outputs[0].default_value[:3]), [0.0, 0.0, 0.0])    # X3D's classic gotcha
        src, _ = self.line_material_source(points.data.materials[0])
        self.assertEqual(list(src.outputs[0].default_value[:3]), [1.0, 1.0, 1.0])    # lighting off: white
        gltf = self.export_glb(use_mesh_edges=True, use_mesh_vertices=True)
        factors = sorted(str(m.get("pbrMetallicRoughness", {}).get("baseColorFactor")) for m in gltf["materials"])
        self.assertEqual(factors, ["None", "[0, 0, 0, 1]"])               # white is glTF's default factor
        self.assertTrue(all("KHR_materials_unlit" in m["extensions"] for m in gltf["materials"]))

    def test_coloured_points_and_lines_keep_their_x3d_colours_into_the_glb(self):
        self.load(_shape("<PointSet><Coordinate point='0 0 0 1 0 0 2 0 0'/><Color color='1 0 0 0 1 0 0.5 0.5 0.5'/>"
                         "</PointSet>", name="Dots")
                  + _shape("<IndexedLineSet colorPerVertex='false' colorIndex='1 0' coordIndex='0 1 -1 1 2 -1'>"
                           "<Coordinate point='0 1 0 1 1 0 2 1 0'/><Color color='0 0 1 1 1 0'/></IndexedLineSet>",
                           name="Polylines")
                  + _shape("<IndexedLineSet coordIndex='0 1 2'><Coordinate point='0 2 0 1 2 0 2 2 0'/>"
                           "<Color color='1 0 0 0 1 0 0 0 1'/></IndexedLineSet>", name="Gradient")
                  + _shape("<LineSet vertexCount='2'><Coordinate point='0 3 0 1 3 0'/><Color color='0 1 1 1 0 1'/>"
                           "</LineSet>", name="Plain"))
        meshes = {o.name: o.data for o in bpy.data.objects if o.type == 'MESH'}
        self.assertEqual(len(meshes), 4, [o.name for o in bpy.data.objects])           # coloured lines are meshes
        for me in meshes.values():
            attr = me.color_attributes[self.ix.LINE_COLOUR_ATTRIBUTE]
            self.assertEqual(attr.domain, 'POINT')
            src, mix = self.line_material_source(me.materials[0])
            self.assertEqual((src.type, src.layer_name), ('VERTEX_COLOR', self.ix.LINE_COLOUR_ATTRIBUTE))
            self.assertIsNone(mix)
        dots = next(me for me in meshes.values() if not me.edges)
        lin = [round(c, 3) for c in dots.color_attributes["Color"].data[2].color]
        self.assertEqual(lin, [0.214, 0.214, 0.214, 1.0])          # sRGB 0.5 to linear, as face colours are
        poly = next(me for me in meshes.values() if len(me.vertices) == 4)
        self.assertEqual([tuple(round(c, 3) for c in d.color[:3]) for d in poly.color_attributes["Color"].data],
                         [(1, 1, 0), (1, 1, 0), (0, 0, 1), (0, 0, 1)])        # colorIndex 1 0, one per polyline
        out = os.path.join(self.tmpdir, "coloured.glb")
        bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_mesh_edges=True, use_mesh_vertices=True)
        gltf, blob = _glb(out)
        prims = [p for m in gltf["meshes"] for p in m["primitives"]]
        self.assertEqual(sorted(p.get("mode", 4) for p in prims), [0, 1, 1, 1])
        for p in prims:
            self.assertIn("COLOR_0", p["attributes"], p)
            material = gltf["materials"][p["material"]]
            self.assertIn("KHR_materials_unlit", material["extensions"])
        point_prim = next(p for p in prims if p.get("mode") == 0)
        colours = sorted(tuple(round(c, 2) for c in v[:3]) for v in _accessor(gltf, blob, point_prim["attributes"]["COLOR_0"]))
        self.assertEqual(colours, [(0.0, 1.0, 0.0), (0.21, 0.21, 0.21), (1.0, 0.0, 0.0)])

    def test_color_rgba_alpha_makes_points_translucent_and_stays_alpha(self):
        self.load(_shape("<PointSet><Coordinate point='0 0 0 1 0 0'/><ColorRGBA color='1 0 0 0.25 0 0 1 0.25'/>"
                         "</PointSet>"))
        me = self.only_mesh()
        self.assertEqual(round(me.color_attributes["Color"].data[0].color[3], 3), 0.25)    # not "linearised"
        src, mix = self.line_material_source(me.materials[0])
        self.assertIsNotNone(mix)
        self.assertEqual(mix.inputs[0].links[0].from_socket.name, 'Alpha')
        out = os.path.join(self.tmpdir, "rgba.glb")
        bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_mesh_vertices=True)
        gltf, blob = _glb(out)
        material = gltf["materials"][0]
        self.assertEqual(material.get("alphaMode"), "BLEND")
        prim = gltf["meshes"][0]["primitives"][0]
        alphas = [round(v[3], 2) for v in _accessor(gltf, blob, prim["attributes"]["COLOR_0"])]
        self.assertEqual(alphas, [0.25, 0.25])

    def test_transparency_reaches_unlit_lines(self):
        self.load(_shape("<IndexedLineSet coordIndex='0 1 -1'><Coordinate point='0 0 0 1 0 0'/></IndexedLineSet>",
                         "<Appearance><Material emissiveColor='0 1 0' transparency='0.75'/></Appearance>"))
        curve = next(o for o in bpy.data.objects if o.type == 'CURVE')
        _, mix = self.line_material_source(curve.data.materials[0])
        self.assertAlmostEqual(mix.inputs[0].default_value, 0.25, places=5)
        gltf = self.export_glb(use_mesh_edges=True)
        self.assertEqual(gltf["materials"][0].get("alphaMode"), "BLEND")
        self.assertEqual(gltf["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"], [0, 1, 0, 0.25])

    # ------------------------------------------------------------ colour space: as is, or sRGB as X_ITE draws
    COLOURS = ("<Appearance><Material DEF='M' diffuseColor='0.5 0.5 0.5' emissiveColor='0.5 0.5 0.5'/></Appearance>",
               "<Appearance><UnlitMaterial emissiveColor='0.5 0.5 0.5'/></Appearance>",
               "<Appearance><PhysicalMaterial baseColor='0.5 0.5 0.5' emissiveColor='0.5 0.5 0.5'/></Appearance>")

    def colour_scene(self, **options):
        tri = "<IndexedFaceSet coordIndex='0 1 2 -1'><Coordinate point='0 0 0 1 0 0 0 1 0'/></IndexedFaceSet>"
        self.load("".join(_shape(tri, app, name=n) for n, app in zip(("Classic", "Unlit", "Physical"), self.COLOURS))
                  + _shape("<IndexedLineSet coordIndex='0 1 -1'><Coordinate point='0 2 0 1 2 0'/></IndexedLineSet>",
                           "<Appearance><Material USE='M'/></Appearance>"), **options)
        objects = {o.name: o for o in bpy.data.objects}
        b = lambda name: self.bsdf(objects[name].data.materials[0])
        line = next(o for o in bpy.data.objects if o.type == 'CURVE').data.materials[0]
        src, _ = self.line_material_source(line)
        return {"diffuse": b("Classic").inputs["Base Color"].default_value[0],
                "emissive": b("Classic").inputs["Emission Color"].default_value[0],
                "unlit": b("Unlit").inputs["Emission Color"].default_value[0],
                "physical base": b("Physical").inputs["Base Color"].default_value[0],
                "physical emissive": b("Physical").inputs["Emission Color"].default_value[0],
                "line": src.outputs[0].default_value[0]}

    def test_colours_pass_as_they_are_by_default(self):
        self.assertEqual({k: round(v, 3) for k, v in self.colour_scene().items()},
                         {"diffuse": 0.5, "emissive": 0.5, "unlit": 0.5, "physical base": 0.5, "physical emissive": 0.5, "line": 0.5})

    def test_srgb_colour_space_converts_the_classic_materials_and_keeps_physical_ones(self):
        got = {k: round(v, 3) for k, v in self.colour_scene(color_space='SRGB').items()}
        self.assertEqual(got, {"diffuse": 0.214, "emissive": 0.214, "unlit": 0.214, "physical base": 0.5,
                               "physical emissive": 0.5, "line": 0.214})

    def test_colour_space_from_the_environment(self):
        os.environ["BLENDER_X3D_COLOR_SPACE"] = "x_ite"
        try:
            self.assertEqual(round(self.colour_scene()["emissive"], 3), 0.214)
            self.assertEqual(round(self.colour_scene(color_space='AS_IS')["emissive"], 3), 0.5)   # the option wins
        finally:
            os.environ.pop("BLENDER_X3D_COLOR_SPACE", None)
        self.assertEqual(self.ix.resolve_colour_space("srgb"), "SRGB")
        with self.assertLogs(level="WARNING"):
            self.assertEqual(self.ix.resolve_colour_space("bogus"), "AS_IS")

    # ------------------------------------------------------------ surfaces without a material: unlit
    def test_surfaces_without_a_material_are_unlit_in_their_colour_texture_or_white(self):
        png = os.path.join(self.tmpdir, "tex.png")
        _write_png(png, (250, 200, 150))
        tri = "<IndexedFaceSet coordIndex='0 1 2 -1'%s><Coordinate point='0 0 0 1 0 0 0 1 0'/>%s</IndexedFaceSet>"
        self.load(_shape(tri % ("", "<Color color='1 0 0 0 1 0 0 0 1'/>"), "<Appearance/>", name="Coloured")
                  + _shape(tri % ("", ""), "", name="Bare")
                  + _shape(tri % ("", "<TextureCoordinate point='0 0 1 0 0 1'/>"),
                           "<Appearance><ImageTexture url='\"tex.png\"'/></Appearance>", name="Textured")
                  + _shape(tri % ("", ""), "<Appearance><ComposedShader language='GLSL'/></Appearance>", name="Shaded"))
        mats = {o.name: o.data.materials[0] for o in bpy.data.objects if o.type == 'MESH'}
        self.assertEqual(set(mats), {"Coloured", "Bare", "Textured", "Shaded"})
        for name in ("Coloured", "Bare", "Textured"):
            self.assertFalse(any(n.type == 'BSDF_PRINCIPLED' for n in mats[name].node_tree.nodes), name)
        self.assertEqual(self.line_material_source(mats["Coloured"])[0].type, 'VERTEX_COLOR')
        self.assertEqual(list(self.line_material_source(mats["Bare"])[0].outputs[0].default_value[:3]), [1.0, 1.0, 1.0])
        self.assertEqual(self.line_material_source(mats["Textured"])[0].type, 'TEX_IMAGE')
        self.assertTrue(any(n.type == 'BSDF_PRINCIPLED' for n in mats["Shaded"].node_tree.nodes))   # left to the shader
        gltf = self.export_glb()
        by_name = {m["name"]: m for m in gltf["materials"]}
        unlit = [n for n, m in by_name.items() if "KHR_materials_unlit" in m.get("extensions", {})]
        self.assertEqual(len(unlit), 3, by_name)
        textured = next(m for n, m in by_name.items() if n in unlit and "baseColorTexture" in m.get("pbrMetallicRoughness", {}))
        self.assertIsNotNone(textured)
        prims = {gltf["materials"][p["material"]]["name"]: p for m in gltf["meshes"] for p in m["primitives"]}
        coloured = next(p for n, p in prims.items() if n in unlit and "COLOR_0" in p["attributes"])
        self.assertIsNotNone(coloured)

    # ------------------------------------------------------------ an ElevationGrid whose heights come later
    def test_elevation_grid_without_heights_is_flat_instead_of_stopping_the_import(self):
        with self.assertLogs(level="WARNING") as logs:
            self.load(_shape("<ElevationGrid xDimension='4' zDimension='3' xSpacing='0.5' zSpacing='0.5'/>")
                      + _shape("<Box/>"))
        self.assertTrue(any("missing ones are 0" in line for line in logs.output))
        grids = [o.data for o in bpy.data.objects if o.type == 'MESH' and len(o.data.vertices) == 12]
        self.assertEqual(len(grids), 1)                                   # the grid, flat
        self.assertTrue(all(abs(v.co.y) < 1e-9 for v in grids[0].vertices))      # X3D's height axis, in mesh space
        self.assertEqual(len(self.meshes()), 2)                           # and the rest of the scene

    # ------------------------------------------------------------ face colours: sRGB to linear once, alpha kept
    def test_face_colours_go_to_linear_once_and_keep_their_alpha(self):
        for per_vertex in ("true", "false"):
            self.load(_shape("<IndexedFaceSet colorPerVertex='%s' coordIndex='0 1 2 -1'>"
                             "<Coordinate point='0 0 0 1 0 0 0 1 0'/>"
                             "<ColorRGBA color='0.5 0.5 0.5 0.5 0.5 0.5 0.5 0.5 0.5 0.5 0.5 0.5'/></IndexedFaceSet>"
                             % per_vertex))
            value = [round(c, 3) for c in self.only_mesh().color_attributes["ColorPerCorner"].data[0].color]
            self.assertEqual(value, [0.214, 0.214, 0.214, 0.5], per_vertex)     # was 0.038 per vertex; alpha 0.214

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
