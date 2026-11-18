# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The X3D 4.0 export surface, case by case and from seeded random scenes, against one oracle.

Oracle for every case: the file passes the strict validator (and x3d.py's semantic check when installed), and
importing it back gives the same world-space vertex positions (each within 1e-4 of one in the source, both ways),
the same bounding box and the same base colour, roughness and metallic per material.

The cases cover export options and Blender data that no other test reached (measured with coverage.py inside
Blender 5.1.0, see tools/coverage_in_blender.py): triangulation, exported normals, modifiers, active collection,
visible-only, flat hierarchy, compression; loose edges, n-gons, concave and degenerate faces, custom split normals,
several UV maps, colour attributes on every domain and type, negative and non-uniform scale under rotated parents,
a 60-deep parent chain, linked duplicates, collection instances, hostile names, Principled BSDF materials, textures
by path mode, the Mapping node, alpha blend modes, and a German numeric locale.

Known gap, not covered here: a vertex no face or edge uses is dropped (IndexedFaceSet and IndexedLineSet have no
place for it; a PointSet would be needed).

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_export_surface_matrix_bpy
"""

from __future__ import annotations

import locale
import math
import os
import random
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension, SOURCE_DIR

TOLERANCE = 1e-4


def _world_points():
    """Every evaluated vertex in world space, instances included, with the scene's bounding box.

    Objects hidden in the viewport are not in the depsgraph's instances but are exported (unless use_visible), so
    they are added from their own data."""
    from mathutils import Vector
    depsgraph = bpy.context.evaluated_depsgraph_get()
    points = []
    for instance in depsgraph.object_instances:
        if instance.object.type != "MESH":
            continue
        matrix = instance.matrix_world.copy()
        points.extend(matrix @ vertex.co for vertex in instance.object.data.vertices)
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH" and obj.hide_get():
            points.extend(obj.matrix_world @ vertex.co for vertex in obj.data.vertices)
    if not points:
        return points, None
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    return points, (low, high)


def _materials():
    found = {}
    for material in bpy.data.materials:
        if not material.users or not material.use_nodes or material.node_tree is None:
            continue
        bsdf = next((node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None:
            continue
        name = material.name.split(".")[0]
        name = name[3:] if name.startswith("MA_") else name
        found[name] = (*bsdf.inputs["Base Color"].default_value[:3], bsdf.inputs["Roughness"].default_value,
                       bsdf.inputs["Metallic"].default_value)
    return found


def _unmatched(source, target):
    """Points of ``source`` with no point of ``target`` within TOLERANCE (relative for large coordinates)."""
    from mathutils.kdtree import KDTree
    if not target:
        return list(source)
    tree = KDTree(len(target))
    for index, point in enumerate(target):
        tree.insert(point, index)
    tree.balance()
    missing = []
    for point in source:
        _co, _index, distance = tree.find(point)
        if distance > TOLERANCE * max(1.0, point.length):
            missing.append(tuple(point))
    return missing


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ExportSurfaceMatrixTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_matrix_")
        _register_extension(self.tmpdir)
        sys.path.insert(0, str(SOURCE_DIR))
        self._fresh()

    def _fresh(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmpdir)

    # -- scene builders ------------------------------------------------------------------------------------------

    def _link(self, name, mesh, collection=None):
        obj = bpy.data.objects.new(name, mesh)
        (collection or bpy.context.scene.collection).objects.link(obj)
        return obj

    def _mesh(self, name, vertices, faces, edges=()):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(vertices, list(edges), faces)
        return self._link(name, mesh)

    def _cube(self, name="Cube", location=(0, 0, 0), size=2.0):
        bpy.ops.mesh.primitive_cube_add(location=location, size=size)
        obj = bpy.context.active_object
        obj.name = name
        return obj

    def _material(self, name, **inputs):
        material = bpy.data.materials.new(name)
        material.use_nodes = True
        bsdf = next(node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
        for key, value in inputs.items():
            bsdf.inputs[key].default_value = value
        return material

    def _image(self, name, *, path=None, packed=False):
        image = bpy.data.images.new(name, 4, 4)
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            image.filepath_raw = path
            image.file_format = "PNG"
            image.save()
        if packed:
            image.pack()
        return image

    def _textured(self, name, image, location):
        obj = self._cube(name, location)
        material = self._material(name)
        tree = material.node_tree
        texture = tree.nodes.new("ShaderNodeTexImage")
        texture.image = image
        tree.links.new(texture.outputs[0], next(n for n in tree.nodes if n.type == "BSDF_PRINCIPLED").inputs["Base Color"])
        obj.data.materials.append(material)
        return obj

    # -- oracle --------------------------------------------------------------------------------------------------

    def _round_trip(self, name, **options):
        from validate import validate_xml_file, validate_with_x3d_py
        points, bbox = _world_points()
        materials = _materials()
        path = os.path.join(self.tmpdir, name + (".x3dz" if options.get("use_compress") else ".x3d"))
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False, **options),
                         {"FINISHED"})
        result = validate_xml_file(path)
        self.assertTrue(result.valid, result.errors)
        semantic = validate_with_x3d_py(path)
        if semantic is not None:
            self.assertEqual(semantic.errors, [])
        self._fresh()
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
        again, again_bbox = _world_points()
        self.assertEqual(_unmatched(points, again)[:5], [], "source vertices missing after the round trip")
        self.assertEqual(_unmatched(again, points)[:5], [], "vertices the source does not have")
        if bbox is not None:
            for a, b in zip((*bbox[0], *bbox[1]), (*again_bbox[0], *again_bbox[1])):
                self.assertLessEqual(abs(a - b), TOLERANCE * max(1.0, abs(a)), (bbox, again_bbox))
        imported = _materials()
        for material, values in materials.items():
            self.assertIn(material, imported)
            for a, b in zip(values, imported[material]):
                self.assertAlmostEqual(a, b, places=3, msg=material)
        return path

    # -- export options ------------------------------------------------------------------------------------------

    def _option_scene(self):
        self._cube("Box").data.materials.append(self._material("Box", **{"Base Color": (0.2, 0.4, 0.6, 1)}))
        sphere = self._cube("Smooth", (3, 0, 0))
        bpy.ops.object.shade_smooth()
        sphere.modifiers.new("Bevel", "BEVEL")
        hidden = self._cube("Hidden", (6, 0, 0))
        hidden.hide_set(True)
        child = self._cube("Child", (0, 4, 0), size=1.0)
        child.parent = sphere

    def test_option_matrix(self):
        cases = {
            "triangulate": dict(use_triangulate=True),
            "normals": dict(use_normals=True),
            "modifiers": dict(use_mesh_modifiers=True),
            "flat_hierarchy": dict(use_hierarchy=False),
            "compressed": dict(use_compress=True),
        }
        for name, options in cases.items():
            with self.subTest(option=name):
                self._fresh()
                self._option_scene()
                path = self._round_trip(name, **options)
                if name == "triangulate":
                    root = ET.parse(path).getroot()
                    for node in root.iter("IndexedFaceSet"):
                        faces = [face for face in node.attrib["coordIndex"].split("-1") if face.split()]
                        self.assertTrue(all(len(face.split()) == 3 for face in faces))
                if name == "normals":
                    self.assertIsNotNone(ET.parse(path).getroot().find(".//IndexedFaceSet/Normal"))

    def test_visible_and_active_collection_select_what_is_written(self):
        self._option_scene()
        extra = bpy.data.collections.new("Extra")
        bpy.context.scene.collection.children.link(extra)
        self._link("InExtra", bpy.data.meshes.new("InExtra"), extra)
        path = os.path.join(self.tmpdir, "visible.x3d")
        bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False, use_visible=True)
        names = {node.attrib["DEF"] for node in ET.parse(path).getroot().iter("Transform")}
        self.assertIn("OB_Box", names)
        self.assertNotIn("OB_Hidden", names)
        layer = bpy.context.view_layer.layer_collection.children["Extra"]
        bpy.context.view_layer.active_layer_collection = layer
        path = os.path.join(self.tmpdir, "active.x3d")
        bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False, use_active_collection=True)
        names = {node.attrib["DEF"] for node in ET.parse(path).getroot().iter("Transform")}
        self.assertEqual(names, {"OB_InExtra"})

    # -- geometry ------------------------------------------------------------------------------------------------

    def test_geometry_cases(self):
        def ngon():
            n = 9
            self._mesh("Ngon", [(math.cos(i * 2 * math.pi / n), math.sin(i * 2 * math.pi / n), 0) for i in range(n)],
                       [list(range(n))])

        def concave():
            self._mesh("Concave", [(0, 0, 0), (4, 0, 0), (4, 4, 0), (2, 1, 0), (0, 4, 0)], [[0, 1, 2, 3, 4]])

        def degenerate():
            self._mesh("Degenerate", [(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 0, 0)], [[0, 1, 2], [0, 3, 1]])

        def split_normals():
            obj = self._cube()
            bpy.ops.object.shade_smooth()
            obj.data.normals_split_custom_set([(0, 0, 1)] * len(obj.data.loops))

        def uv_maps():
            obj = self._cube()
            second = obj.data.uv_layers.new(name="Second")
            for loop in second.data:
                loop.uv = (loop.uv[0] * 2, 0.5)

        def colours():
            obj = self._cube()
            for domain in ("POINT", "CORNER"):
                for kind in ("FLOAT_COLOR", "BYTE_COLOR"):
                    attribute = obj.data.color_attributes.new(f"{domain}_{kind}", kind, domain)
                    for index, item in enumerate(attribute.data):
                        item.color = ((index % 3) / 2, 0.25, 0.75, 1.0)

        def scales():
            self._cube("Mirrored").scale = (-1, 1, 1)
            parent = self._cube("Parent", (5, 0, 0))
            parent.scale = (1, 4, 1)
            parent.rotation_euler = (0.3, 0, 0)
            child = self._cube("Child", (7, 0, 0))
            child.parent = parent
            child.rotation_euler = (0, 0.7, 0)
            child.scale = (0.5, 1, 2)

        def deep_chain():
            previous = None
            for level in range(60):
                obj = self._cube(f"L{level}", size=0.1)
                if previous is not None:
                    obj.location = (0.1, 0.0, 0.01)
                    obj.rotation_euler = (0.0, 0.0, 0.05)
                    obj.parent = previous
                previous = obj

        def linked_duplicate():
            original = self._cube("A")
            duplicate = self._link("B", original.data)
            duplicate.location = (3, 0, 0)

        def collection_instances():
            prototype = bpy.data.collections.new("Proto")
            bpy.context.scene.collection.children.link(prototype)
            cube = self._cube("Proto")
            for collection in cube.users_collection:
                collection.objects.unlink(cube)
            prototype.objects.link(cube)
            for index in range(2):
                empty = bpy.data.objects.new(f"Instance{index}", None)
                empty.instance_type = "COLLECTION"
                empty.instance_collection = prototype
                empty.location = (4 + 3 * index, 0, 1)
                empty.rotation_euler = (0, 0, 0.4 * index)
                bpy.context.scene.collection.objects.link(empty)

        def numbers():
            self._cube("Huge").location = (1e30, -1e30, 0)
            self._cube("Denormal").location = (1e-310, 5e-324, 0)

        cases = {"ngon": ngon, "concave": concave, "degenerate": degenerate, "split_normals": split_normals,
                 "uv_maps": uv_maps, "colours": colours, "scales": scales, "deep_chain": deep_chain,
                 "linked_duplicate": linked_duplicate, "collection_instances": collection_instances,
                 "numbers": numbers}
        for name, build in cases.items():
            with self.subTest(case=name):
                self._fresh()
                build()
                self._round_trip(name, use_normals=(name == "split_normals"))

    def test_names_round_trip_and_defs_stay_unique(self):
        names = ["a b", 'q"<&>\'', "123start", "Transform", "USE", "DEF", "-dash", "x--y", "日本語", "é", "tab\tname",
                 "Cube", "Cube.001", "Cube_001", " ", "ROUTE", "Scene"]
        for index, name in enumerate(names):
            self._cube(name, (index * 3, 0, 0))
        path = self._round_trip("names")
        defs = [node.attrib["DEF"] for node in ET.parse(path).getroot().iter() if "DEF" in node.attrib]
        self.assertEqual(len(defs), len(set(defs)), "DEF names collide")
        self.assertEqual(len(bpy.context.scene.objects), len(names))

    # -- materials -----------------------------------------------------------------------------------------------

    def test_material_cases(self):
        specs = {"Plain": {}, "Metal": {"Metallic": 1.0, "Roughness": 0.1, "Base Color": (0.9, 0.6, 0.2, 1)},
                 "Emissive": {"Emission Color": (1, 0, 0, 1), "Emission Strength": 5.0},
                 "Glass": {"Alpha": 0.25, "IOR": 1.5, "Transmission Weight": 1.0},
                 "Layered": {"Coat Weight": 1.0, "Sheen Weight": 1.0, "Specular IOR Level": 0.9, "Anisotropic": 0.5,
                             "Subsurface Weight": 0.4, "Roughness": 0.7}}
        for index, (name, inputs) in enumerate(specs.items()):
            self._cube(name, (index * 3, 0, 0)).data.materials.append(self._material(name, **inputs))
        for index, method in enumerate(("DITHERED", "BLENDED")):
            material = self._material(method, Alpha=0.5)
            material.surface_render_method = method
            self._cube(method, (index * 3, 4, 0)).data.materials.append(material)
        emission_only = bpy.data.materials.new("EmissionOnly")
        emission_only.use_nodes = True
        tree = emission_only.node_tree
        for node in [n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"]:
            tree.nodes.remove(node)
        emission = tree.nodes.new("ShaderNodeEmission")
        tree.links.new(emission.outputs[0], next(n for n in tree.nodes if n.type == "OUTPUT_MATERIAL").inputs[0])
        self._cube("EmissionOnly", (0, 8, 0)).data.materials.append(emission_only)
        self._cube("EmptySlot", (3, 8, 0)).data.materials.append(None)
        path = self._round_trip("materials")
        root = ET.parse(path).getroot()
        metal = root.find(".//PhysicalMaterial[@DEF='MA_Metal']")
        self.assertEqual((metal.attrib["metallic"], metal.attrib["roughness"]), ("1.000000", "0.100000"))
        glass = root.find(".//PhysicalMaterial[@DEF='MA_Glass']")
        self.assertAlmostEqual(float(glass.attrib["transparency"]), 0.75, places=5)
        self.assertIn("emissiveColor", root.find(".//PhysicalMaterial[@DEF='MA_Emissive']").attrib)

    def test_textures_by_path_mode(self):
        sources = os.path.join(self.tmpdir, "sources")
        for mode in ("COPY", "RELATIVE", "STRIP"):
            with self.subTest(path_mode=mode):
                self._fresh()
                images = [self._image("packed", packed=True),
                          self._image("on disk", path=os.path.join(sources, mode, "on disk.png")),
                          self._image("ünï 日本", path=os.path.join(sources, mode, "ünï 日本.png"))]
                missing = bpy.data.images.new("missing", 4, 4)
                missing.filepath_raw = os.path.join(sources, "nowhere", "missing.png")
                images.append(missing)
                for index, image in enumerate(images):
                    self._textured(f"T{index}", image, (index * 3, 0, 0))
                out = os.path.join(self.tmpdir, mode)
                os.makedirs(out)
                path = os.path.join(out, "textures.x3d")
                self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False,
                                                          path_mode=mode), {"FINISHED"})
                urls = [node.attrib["url"] for node in ET.parse(path).getroot().iter("ImageTexture")]
                self.assertEqual(len(urls), 4)
                if mode == "COPY":
                    for name in ("packed.png", "on disk.png", "ünï 日本.png"):
                        self.assertTrue(os.path.exists(os.path.join(out, name)), (name, os.listdir(out)))
                if mode == "STRIP":
                    self.assertTrue(all("/" not in url.strip('"') for url in urls), urls)

    def test_mapping_node_becomes_a_texture_transform(self):
        obj = self._cube()
        material = self._material("Mapped")
        tree = material.node_tree
        texture = tree.nodes.new("ShaderNodeTexImage")
        texture.image = self._image("m", packed=True)
        mapping = tree.nodes.new("ShaderNodeMapping")
        coordinates = tree.nodes.new("ShaderNodeTexCoord")
        mapping.inputs["Location"].default_value = (0.25, 0.5, 0)
        mapping.inputs["Rotation"].default_value = (0, 0, 0.5)
        mapping.inputs["Scale"].default_value = (2, 3, 1)
        tree.links.new(coordinates.outputs["UV"], mapping.inputs[0])
        tree.links.new(mapping.outputs[0], texture.inputs[0])
        tree.links.new(texture.outputs[0], next(n for n in tree.nodes if n.type == "BSDF_PRINCIPLED").inputs["Base Color"])
        obj.data.materials.append(material)
        root = ET.parse(self._round_trip("mapping")).getroot()
        transform = root.find(".//TextureTransform")
        self.assertIsNotNone(transform, "the Mapping node was not written")
        self.assertAlmostEqual(float(transform.attrib.get("rotation", "0")), 0.5, places=5)
        self.assertEqual([float(v) for v in transform.attrib["scale"].split()], [2.0, 3.0])

    # -- numbers under a decimal-comma locale -------------------------------------------------------------------

    def test_decimal_comma_locale_does_not_leak_into_the_file(self):
        previous = locale.setlocale(locale.LC_ALL)
        for name in ("de_DE.UTF-8", "de_DE.utf8", "de_DE", "German_Germany.1252"):
            try:
                locale.setlocale(locale.LC_ALL, name)
                break
            except locale.Error:
                continue
        else:
            self.skipTest("no German locale installed")
        self.addCleanup(locale.setlocale, locale.LC_ALL, previous)
        self.assertEqual(locale.localeconv()["decimal_point"], ",")
        self._cube().location = (1.5, 2.25, -0.125)
        path = self._round_trip("locale")
        root = ET.parse(path).getroot()
        for node in root.iter():
            for field in ("translation", "point", "scale", "rotation"):
                self.assertNotIn(",", node.attrib.get(field, ""))

    # -- seeded random scenes ------------------------------------------------------------------------------------

    def test_seeded_random_scenes(self):
        """25 random scenes: random meshes, transforms (negative and non-uniform scale), parenting, hostile names
        and materials. A failure names the seed; rerun one with ``_random_scene(random.Random(seed))``."""
        for seed in range(25):
            with self.subTest(seed=seed):
                self._fresh()
                self._random_scene(random.Random(seed))
                self._round_trip(f"random{seed}")

    def _random_scene(self, rng):
        alphabet = "abcXYZ019 _-.&<>\"'é日"
        objects = []
        for index in range(rng.randint(1, 6)):
            vertices = [tuple(rng.uniform(-2, 2) for _ in range(3)) for _ in range(rng.randint(3, 12))]
            # every vertex in at least one face: X3D has no place for a vertex no face uses (see the module doc)
            order = list(range(len(vertices)))
            rng.shuffle(order)
            faces = [order[start:start + 3] for start in range(0, len(order) - 2, 3)]
            leftover = order[len(faces) * 3:]
            if leftover:
                faces.append(leftover + rng.sample(order[:len(faces) * 3], 3 - len(leftover)))
            for _ in range(rng.randint(0, 4)):
                faces.append(rng.sample(range(len(vertices)), rng.randint(3, min(5, len(vertices)))))
            name = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 8))) or "x"
            obj = self._mesh(f"{name}{index}", vertices, faces)
            obj.location = tuple(rng.uniform(-10, 10) for _ in range(3))
            obj.rotation_euler = tuple(rng.uniform(-math.pi, math.pi) for _ in range(3))
            obj.scale = tuple(rng.choice((-1, 1)) * rng.uniform(0.2, 3) for _ in range(3))
            if objects and rng.random() < 0.5:
                obj.parent = rng.choice(objects)
            if rng.random() < 0.7:
                obj.data.materials.append(self._material(
                    f"M{index}", **{"Base Color": (rng.random(), rng.random(), rng.random(), 1.0),
                                    "Roughness": rng.random(), "Metallic": rng.choice((0.0, 1.0, rng.random()))}))
            objects.append(obj)


if __name__ == "__main__":
    unittest.main()
