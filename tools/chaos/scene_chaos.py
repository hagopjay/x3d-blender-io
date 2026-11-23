"""Export-side chaos: break a Blender scene in one way, export it with random options, and judge what comes out.

Round 1 (differential.py) broke files going in. This breaks scenes going out, since the exporter writes what users
ship. Each case builds one frozen scene (tests/frozen_scenes.py), applies one scene operator (below), and exports with
a random set of export options. Then:

  export      FINISHED, CANCELLED (the gate refused, with its reason) or the exception
  own, x3dpy  the add-on's validator and x3d.py strict on the written file
  xsd         the Web3D X3D XML Schema through xmllint (with --xsd DIR)
  tokens      no nan or inf token in a numeric attribute
  reimport    the importer on the written file
  fixed point import, export (defaults), import, export: the 2nd and 3rd exports must be equal in canonical form
              (tools/io_sync/x3d_c14n.py). Any difference is a value that drifts on every round trip.

Run with the bpy wheel's Python or inside Blender:

    python tools/chaos/scene_chaos.py --out /tmp/scene-chaos [--per-op 12] [--rng 7] [--xsd DIR] [--fail-on-crash]

Cases and logs stay under --out; nothing is written to the repository.
"""
from __future__ import annotations

import argparse
import contextlib
import faulthandler
import io
import json
import math
import random
import re
import signal
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "tools" / "io_sync"))

from differential import SOURCE, _signature, judge_own_and_x3dpy, judge_xsd  # noqa: E402

sys.path.insert(0, str(SOURCE))

NAMES = ["Ünïcødé", "名前", "שלום", "a<b>&'\"c", "--", "1st", "two words", "x" * 63, "é", "\U0001F600",
         "tab\there", "new\nline", "", " ", "DEF", "USE", "a b", "a_b", "​", "﻿"]
STEP_SECONDS = 120                 # one export or import
EXTREMES = [float("nan"), float("inf"), -float("inf"), 1e39, -1e39, 1e-45, 0.0, -0.0, 1e30]


# -- scene operators: each breaks one thing and returns a one-line description -------------------------------------

def _meshes(bpy):
    found = [o for o in bpy.data.objects if o.type == "MESH" and o.data and len(o.data.vertices)]
    if found:
        return found
    mesh = bpy.data.meshes.new("Added")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    obj = bpy.data.objects.new("Added", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return [obj]


def op_vertex_extreme(bpy, rng):
    obj = rng.choice(_meshes(bpy))
    v = rng.randrange(len(obj.data.vertices))
    axis, value = rng.randrange(3), rng.choice(EXTREMES)
    obj.data.vertices[v].co[axis] = value
    obj.data.update()
    return f"{obj.name} vertex {v} axis {axis} = {value}"


def op_all_vertices_one_point(bpy, rng):
    obj = rng.choice(_meshes(bpy))
    for v in obj.data.vertices:
        v.co = (0.0, 0.0, 0.0)
    obj.data.update()
    return f"{obj.name}: every vertex at the origin (zero-area faces)"


def op_empty_mesh(bpy, rng):
    mesh = bpy.data.meshes.new(rng.choice(["Empty", "Nothing"]))
    obj = bpy.data.objects.new("EmptyMesh", mesh)
    bpy.context.scene.collection.objects.link(obj)
    if rng.random() < 0.5:
        mesh.materials.append(None)
    return "a mesh object with no vertices"


def op_single_vertex(bpy, rng):
    mesh = bpy.data.meshes.new("Dot")
    mesh.from_pydata([(0, 0, 0)], [], [])
    obj = bpy.data.objects.new("Dot", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return "a mesh with one vertex and nothing else"


def op_odd_names(bpy, rng):
    pool = list(bpy.data.objects) + list(bpy.data.materials) + list(bpy.data.meshes)
    picked = rng.sample(pool, min(len(pool), rng.randint(1, 4)))
    given = []
    for item in picked:
        name = rng.choice(NAMES)
        item.name = name
        given.append(repr(name))
    return "renamed to " + ", ".join(given)


def op_colliding_names(bpy, rng):
    objs = list(bpy.data.objects)
    a, b = rng.choice([("a b", "a_b"), ("x.001", "x_001"), ("Ä", "A"), ("1", "_1"), ("a-b", "a_b")])
    if len(objs) >= 2:
        objs[0].name, objs[1].name = a, b
    return f"two objects named {a!r} and {b!r}, one sanitised spelling"


def op_material_slots(bpy, rng):
    obj = rng.choice(_meshes(bpy))
    choice = rng.randrange(4)
    if choice == 0:
        obj.data.materials.append(None)
        for p in obj.data.polygons:
            p.material_index = len(obj.data.materials) - 1
        return f"{obj.name}: faces point at an empty material slot"
    if choice == 1:
        for p in obj.data.polygons:
            p.material_index = 30000
        return f"{obj.name}: material_index past every slot"
    if choice == 2:
        mat = bpy.data.materials.new("NoNodes")
        mat.use_nodes = False
        obj.data.materials.clear()
        obj.data.materials.append(mat)
        return f"{obj.name}: a material without nodes"
    mat = obj.data.materials[0] if len(obj.data.materials) and obj.data.materials[0] else bpy.data.materials.new("M")
    if not mat.use_nodes:
        mat.use_nodes = True
    for node in list(mat.node_tree.nodes):
        if node.type == "BSDF_PRINCIPLED":
            mat.node_tree.nodes.remove(node)
    if not len(obj.data.materials):
        obj.data.materials.append(mat)
    return f"{obj.name}: a material whose Principled BSDF was deleted"


def op_material_values(bpy, rng):
    obj = rng.choice(_meshes(bpy))
    mat = bpy.data.materials.new("Wild")
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    name = rng.choice(["Base Color", "Roughness", "Metallic", "Alpha", "Emission Strength", "IOR"])
    value = rng.choice(EXTREMES + [-1.0, 2.0, 1e6])
    socket = bsdf.inputs[name]
    if name == "Base Color":
        socket.default_value = (value, 0.5, 0.5, 1.0)
    else:
        socket.default_value = value
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return f"{obj.name}: {name} = {value}"


def op_texture_trouble(bpy, rng):
    obj = rng.choice(_meshes(bpy))
    mat = bpy.data.materials.new("Tex")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
    tex = nodes.new("ShaderNodeTexImage")
    choice = rng.randrange(4)
    if choice == 0:
        what = "an Image Texture node with no image"
    elif choice == 1:
        tex.image = bpy.data.images.new("Missing", 2, 2)
        tex.image.source = "FILE"
        tex.image.filepath = "/nonexistent/missing.png"
        what = "an image whose file does not exist"
    elif choice == 2:
        tex.image = bpy.data.images.new("Generated", 4, 4)
        what = "a generated image with no file"
    else:
        tex.image = bpy.data.images.new("Tiny", 1, 1, float_buffer=True)
        tex.image.filepath_raw = "//" + rng.choice(NAMES) + ".png"
        what = "a float image with an odd file name"
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if rng.random() < 0.5:
        noise = nodes.new("ShaderNodeTexNoise")
        links.new(noise.outputs[0], bsdf.inputs["Roughness"])
        what += ", plus a Noise Texture into Roughness"
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return f"{obj.name}: {what}"


def op_transform_extreme(bpy, rng):
    obj = rng.choice(list(bpy.data.objects))
    which = rng.choice(["location", "rotation_euler", "scale"])
    axis, value = rng.randrange(3), rng.choice(EXTREMES)
    getattr(obj, which)[axis] = value
    return f"{obj.name}.{which}[{axis}] = {value}"


def op_zero_scale(bpy, rng):
    obj = rng.choice(list(bpy.data.objects))
    obj.scale = rng.choice([(0, 0, 0), (0, 1, 1), (-1, 1, 1), (-1, -1, -1), (1e-30, 1, 1)])
    return f"{obj.name}.scale = {tuple(obj.scale)}"


def op_deep_parents(bpy, rng):
    depth = rng.choice([200, 1500])
    parent = None
    for i in range(depth):
        empty = bpy.data.objects.new(f"Chain{i}", None)
        bpy.context.scene.collection.objects.link(empty)
        empty.parent = parent
        empty.location = (0.0, 0.01, 0.0)
        parent = empty
    rng.choice(_meshes(bpy)).parent = parent
    return f"a mesh at the end of {depth} parented empties"


def op_shape_keys(bpy, rng):
    obj = rng.choice(_meshes(bpy))
    obj.shape_key_add(name="Basis")
    key = obj.shape_key_add(name=rng.choice(["Open", "名前"]))
    key.data[0].co = (rng.choice(EXTREMES), 0.0, 0.0)
    key.value = rng.choice([0.5, 1.0, 10.0, -1.0])
    return f"{obj.name}: a shape key with an extreme point, value {key.value}"


def op_modifiers(bpy, rng):
    obj = rng.choice(_meshes(bpy))
    choice = rng.randrange(5)
    if choice == 0:
        mod = obj.modifiers.new("Array", "ARRAY")
        mod.count = rng.choice([1, 64])
        what = f"an Array modifier, count {mod.count}"
    elif choice == 1:
        obj.modifiers.new("Bool", "BOOLEAN")
        what = "a Boolean modifier with no object"
    elif choice == 2:
        obj.modifiers.new("GN", "NODES")
        what = "an empty Geometry Nodes modifier (no node group)"
    elif choice == 3:
        mod = obj.modifiers.new("Weld", "WELD")
        mod.merge_threshold = 1e6
        what = "a Weld modifier that merges everything"
    else:
        mod = obj.modifiers.new("Decimate", "DECIMATE")
        mod.ratio = 0.0
        what = "a Decimate modifier with ratio 0"
    return f"{obj.name}: {what}"


def op_camera_extreme(bpy, rng):
    cam = bpy.data.cameras.new("Cam")
    obj = bpy.data.objects.new("Cam", cam)
    bpy.context.scene.collection.objects.link(obj)
    choice = rng.randrange(5)
    if choice == 0:
        cam.lens = 1.0
        what = "lens 1 mm"
    elif choice == 1:
        cam.type = "ORTHO"
        cam.ortho_scale = 0.001
        what = "ortho scale 0.001"
    elif choice == 2:
        cam.clip_start, cam.clip_end = 100.0, 1e-6
        what = "clip start past clip end"
    elif choice == 3:
        cam.type = "PANO"
        what = "a panoramic camera"
    else:
        cam.sensor_fit = "VERTICAL"
        cam.sensor_height = 1e-3
        what = "a 0.001 mm vertical sensor"
    bpy.context.scene.camera = obj
    return f"active camera with {what}"


def op_light_extreme(bpy, rng):
    kind = rng.choice(["POINT", "SPOT", "SUN", "AREA"])
    light = bpy.data.lights.new("L", kind)
    obj = bpy.data.objects.new("L", light)
    bpy.context.scene.collection.objects.link(obj)
    field = rng.choice(["energy", "color", "spot_size", "shadow_soft_size"])
    value = rng.choice(EXTREMES + [-5.0])
    if field == "color":
        light.color = (value if math.isfinite(value) and value >= 0 else 0.0, 0.5, 2.0)
    elif field == "spot_size" and kind == "SPOT":
        light.spot_size = rng.choice([0.0175, math.pi])
        value = light.spot_size
    elif field == "energy":
        light.energy = value
    else:
        light.shadow_soft_size = abs(value) if math.isfinite(value) else 1e30
        value = light.shadow_soft_size
    return f"a {kind} light with {field} = {value}"


def op_animation(bpy, rng):
    obj = rng.choice(list(bpy.data.objects))
    choice = rng.randrange(4)
    scene = bpy.context.scene
    if choice == 0:
        obj.location = (0, 0, 0)
        obj.keyframe_insert("location", frame=5)
        obj.location = (rng.choice(EXTREMES), 0, 0)
        obj.keyframe_insert("location", frame=10)
        what = "a location key with an extreme value"
    elif choice == 1:
        scene.frame_start, scene.frame_end = 50, 10
        obj.keyframe_insert("location", frame=1)
        what = "frame_end before frame_start"
    elif choice == 2:
        obj.keyframe_insert("rotation_euler", frame=1)
        action = obj.animation_data.action
        curves = getattr(action, "fcurves", None)
        if curves is not None:
            curves.new("does.not.exist", index=0).keyframe_points.insert(1, 1.0)
            what = "an F-curve on a data path that does not exist"
        else:
            what = "a rotation key (layered action)"
    else:
        scene.render.fps, scene.render.fps_base = 1, 1000.0
        obj.keyframe_insert("location", frame=1)
        obj.location = (1, 1, 1)
        obj.keyframe_insert("location", frame=2)
        what = "fps 1/1000"
    return f"{obj.name}: {what}"


def op_custom_props(bpy, rng):
    obj = rng.choice(list(bpy.data.objects))
    choice = rng.randrange(5)
    if choice == 0:
        obj["nested"] = {"a": {"b": {"c": [1, 2, 3]}}}
    elif choice == 1:
        obj["long"] = "z" * 200000
    elif choice == 2:
        obj["nan"] = float("nan")
    elif choice == 3:
        obj["big"] = 2 ** 31 - 1
        obj["<&>"] = "\"'<&>"
    else:
        obj["id"] = bpy.data.materials.new("Ref")
    return f"{obj.name}: custom property case {choice}"


def op_attributes(bpy, rng):
    obj = rng.choice(_meshes(bpy))
    mesh = obj.data
    choice = rng.randrange(5)
    if choice == 0:
        attr = mesh.color_attributes.new("Col", "BYTE_COLOR", "CORNER")
        for d in attr.data:
            d.color = (1.0, 0.0, 0.0, 0.0)
        what = "a byte colour attribute with alpha 0"
    elif choice == 1:
        attr = mesh.color_attributes.new("ColF", "FLOAT_COLOR", "POINT")
        attr.data[0].color = (rng.choice(EXTREMES), 0.0, 0.0, 1.0)
        what = "a float point colour with an extreme value"
    elif choice == 2:
        for i in range(8 - len(mesh.uv_layers)):
            mesh.uv_layers.new(name=f"UV{i}")
        what = "eight UV maps"
    elif choice == 3:
        uv = mesh.uv_layers.active or mesh.uv_layers.new(name="UV")
        uv.data[0].uv = (rng.choice(EXTREMES), 0.0)
        what = "a UV with an extreme value"
    else:
        mesh.color_attributes.new("A", "FLOAT_COLOR", "CORNER")
        mesh.color_attributes.new("B", "BYTE_COLOR", "POINT")
        what = "two colour attributes of different domains"
    return f"{obj.name}: {what}"


def op_other_types(bpy, rng):
    kind = rng.choice(["FONT", "CURVE", "META", "EMPTY", "POINTCLOUD", "LATTICE", "SURFACE", "VOLUME"])
    if kind == "FONT":
        data = bpy.data.curves.new("Text", "FONT")
        data.body = rng.choice(NAMES) or "x"
    elif kind == "CURVE":
        data = bpy.data.curves.new("Curve", "CURVE")
        spline = data.splines.new("BEZIER")
        spline.bezier_points.add(1)
        if rng.random() < 0.5:
            data.bevel_depth = 0.1
    elif kind == "SURFACE":
        data = bpy.data.curves.new("Surf", "SURFACE")
    elif kind == "META":
        data = bpy.data.metaballs.new("Meta")
        data.elements.new()
    elif kind == "POINTCLOUD":
        data = bpy.data.pointclouds.new("Points") if hasattr(bpy.data, "pointclouds") else None
    elif kind == "LATTICE":
        data = bpy.data.lattices.new("Lat")
    elif kind == "VOLUME":
        data = bpy.data.volumes.new("Vol")
    else:
        data = None
    obj = bpy.data.objects.new(kind.title(), data)
    bpy.context.scene.collection.objects.link(obj)
    if kind == "EMPTY":
        obj.empty_display_type = rng.choice(["IMAGE", "ARROWS", "SPHERE"])
    return f"a {kind} object"


def op_collections(bpy, rng):
    scene = bpy.context.scene
    choice = rng.randrange(4)
    if choice == 0:
        empty = bpy.data.collections.new("EmptyCol")
        inst = bpy.data.objects.new("InstEmpty", None)
        inst.instance_type, inst.instance_collection = "COLLECTION", empty
        scene.collection.objects.link(inst)
        what = "an instance of an empty collection"
    elif choice == 1:
        col = bpy.data.collections.new("Level0")
        col.objects.link(rng.choice(_meshes(bpy)))
        for i in range(1, 6):
            inst = bpy.data.objects.new(f"Inst{i}", None)
            inst.instance_type, inst.instance_collection = "COLLECTION", col
            inst.location = (i, 0, 0)
            col = bpy.data.collections.new(f"Level{i}")
            col.objects.link(inst)
        top = bpy.data.objects.new("Top", None)
        top.instance_type, top.instance_collection = "COLLECTION", col
        scene.collection.objects.link(top)
        what = "collection instances nested five deep"
    elif choice == 2:
        col = bpy.data.collections.new("Hidden")
        scene.collection.children.link(col)
        obj = rng.choice(_meshes(bpy))
        col.objects.link(obj)
        bpy.context.view_layer.layer_collection.children["Hidden"].exclude = True
        what = f"{obj.name} also linked into an excluded collection"
    else:
        obj = rng.choice(list(bpy.data.objects))
        obj.hide_render, obj.hide_viewport = rng.choice([(True, False), (False, True), (True, True)])
        what = f"{obj.name} hidden (render {obj.hide_render}, viewport {obj.hide_viewport})"
    return what


def op_linked_data(bpy, rng):
    src = rng.choice(_meshes(bpy))
    for i in range(rng.choice([2, 50])):
        dup = bpy.data.objects.new(f"Dup{i}", src.data)
        dup.location = (i * 0.1, 0, 0)
        if i % 3 == 0:
            dup.modifiers.new("Tri", "TRIANGULATE")
        bpy.context.scene.collection.objects.link(dup)
    return f"{src.name}'s mesh shared by many objects, some with a modifier"


def op_custom_normals(bpy, rng):
    obj = rng.choice(_meshes(bpy))
    mesh = obj.data
    normals = [(0.0, 0.0, 1.0)] * len(mesh.loops)
    if normals:
        normals[0] = (rng.choice(EXTREMES), 0.0, 0.0)
    with contextlib.suppress(Exception):
        mesh.normals_split_custom_set(normals)
    return f"{obj.name}: custom split normals, one extreme"


OPERATORS = {name[3:]: fn for name, fn in sorted(globals().items()) if name.startswith("op_") and callable(fn)}


def random_options(rng: random.Random, available: set[str]) -> dict:
    options = {
        "x3d_version": rng.choice(["X3D33", "X3D40", "X3D40", "X3D41"]),
        "color_space": rng.choice(["AUTO", "AS_IS", "SRGB"]),
        "material_model": rng.choice(["AUTO", "CLASSIC", "PHYSICAL"]),
        "use_animation": rng.random() < 0.4,
        "use_triangulate": rng.random() < 0.3,
        "use_normals": rng.random() < 0.3,
        "use_hierarchy": rng.random() < 0.8,
        "name_decorations": rng.random() < 0.8,
        "use_mesh_modifiers": rng.random() < 0.8,
        "file_unit": rng.choice(["M", "M", "CM", "MM", "IN"]),
        "global_scale": rng.choice([1.0, 1.0, 1e-4, 1000.0]),
        "path_mode": rng.choice(["RELATIVE", "STRIP", "COPY", "COPY"]),
    }
    return {k: v for k, v in options.items() if k in available}


# -- judging one written file --------------------------------------------------------------------------------------

NUMERIC_BAD = re.compile(r"(?<![A-Za-z_])(nan|inf|-inf|infinity)(?![A-Za-z_])", re.I)


def bad_tokens(path: Path) -> list[str]:
    """Numeric attributes holding nan or inf: x3d.py may take the text, but no browser reads it as a number."""
    import xml.etree.ElementTree as ET

    from x3d_c14n import numeric_fields

    hits = []
    fields = numeric_fields()
    for elem in ET.parse(path).iter():
        for name, value in elem.attrib.items():
            if name in fields.get(elem.tag, ()) and NUMERIC_BAD.search(value):
                hits.append(f"{elem.tag}.{name}={value[:40]}")
    return hits[:5]


_NUM = re.compile(r"-?\d+(?:\.\d+)?(?:e[-+]?\d+)?")


def float32_noise(a: list[str], b: list[str]) -> bool:
    """True when two canonical files differ only in numbers that agree to float32 precision (relative 1e-6).

    Blender keeps matrices and vertices in float32, so composing and decomposing a Transform of scale 1000 moves the
    last digit (1000.00012, then 1000.00024). That is measurement noise, listed as such; any other difference is
    drift."""
    return first_drift(a, b) is None


def _noise_pair(x: str, y: str) -> bool:
    if x == y:
        return True
    if _NUM.sub("#", x) != _NUM.sub("#", y):
        return False
    return all(abs(float(p) - float(q)) <= max(2e-5, 1e-6 * max(abs(float(p)), abs(float(q))))
               for p, q in zip(_NUM.findall(x), _NUM.findall(y)))


def first_drift(a: list[str], b: list[str]):
    """The first difference between two canonical files that is not float32 noise, as (line, second, third), or None.

    Lines are aligned first (difflib), so one added line (a texCoord the re-import made up) is reported as that line,
    not as every line after it; indentation is dropped from the report (a 1,500-deep export indents past 200 chars)."""
    import difflib

    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace" and i2 - i1 == j2 - j1 and all(_noise_pair(a[i], b[j])
                                                           for i, j in zip(range(i1, i2), range(j1, j2))):
            continue
        return (i1, a[i1].strip()[:200] if i1 < i2 else None, b[j1].strip()[:200] if j1 < j2 else None)
    return None


def _canon(path: Path) -> str:
    from x3d_c14n import canonical_file

    return canonical_file(path)


class Runner:
    def __init__(self, out: Path):
        import bpy

        from differential import ImportJudge

        self.bpy = bpy
        self.out = out
        self.judge = ImportJudge()          # registers the add-on from SOURCE
        self.available = set(bpy.ops.export_scene.x3d.get_rna_type().properties.keys())

    def _call(self, fn, **kwargs):
        sink = io.StringIO()
        faulthandler.dump_traceback_later(600, exit=True)     # the backstop: a hang in C ends the run with a trace

        def _too_slow(signum, frame):
            raise TimeoutError(f"over {STEP_SECONDS} s")

        previous = signal.signal(signal.SIGALRM, _too_slow)
        signal.alarm(STEP_SECONDS)                             # a hang in Python becomes this case's finding
        try:
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                result = fn(**kwargs)
            return {"result": sorted(result)[0] if result else "NONE", "log": sink.getvalue()[-300:]}
        except Exception as exc:
            frames = re.findall(r'File "[^"]*/([^"/]+)", line (\d+), in (\w+)', str(exc))
            return {"result": "EXCEPTION", "exception": _signature(exc), "message": str(exc)[-300:],
                    "frames": [f"{f}:{n} {fn}" for f, n, fn in frames if "scene_chaos" not in f][:12]}
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
            faulthandler.cancel_dump_traceback_later()

    def case(self, index: int, scene: str, op: str, rng: random.Random) -> dict:
        import frozen_scenes

        bpy = self.bpy
        stem = f"{scene}__{index:03d}__{op}"
        row = {"id": stem, "scene": scene, "op": op}
        with contextlib.redirect_stdout(io.StringIO()):
            frozen_scenes.build(scene)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                row["what"] = OPERATORS[op](bpy, rng)
        except Exception as exc:  # the operator could not apply: not a finding about the add-on
            row["what"] = f"operator failed: {_signature(exc)} {exc}"[:200]
            row["class"] = "op-failed"
            return row
        options = random_options(rng, self.available)
        row["options"] = options
        first = self.out / f"{stem}.x3d"
        t0 = time.time()
        row["export"] = self._call(bpy.ops.export_scene.x3d, filepath=str(first), **options)
        row["export"]["seconds"] = round(time.time() - t0, 2)
        if row["export"]["result"] != "FINISHED" or not first.exists():
            return row
        row["own"], row["x3dpy"] = judge_own_and_x3dpy(first)
        try:
            row["tokens"] = bad_tokens(first)
        except Exception as exc:
            row["tokens"] = [f"unparsable: {exc}"[:120]]
        # the fixed point: import 1, export 2 (defaults), import 2, export 3
        bpy.ops.wm.read_factory_settings(use_empty=True)
        row["reimport"] = self._call(bpy.ops.import_scene.x3d, filepath=str(first))
        if row["reimport"]["result"] != "FINISHED":
            return row
        second, third = self.out / f"{stem}.2.x3d", self.out / f"{stem}.3.x3d"
        row["export2"] = self._call(bpy.ops.export_scene.x3d, filepath=str(second))
        if row["export2"]["result"] != "FINISHED":
            return row
        bpy.ops.wm.read_factory_settings(use_empty=True)
        row["reimport2"] = self._call(bpy.ops.import_scene.x3d, filepath=str(second))
        if row["reimport2"]["result"] != "FINISHED":
            return row
        row["export3"] = self._call(bpy.ops.export_scene.x3d, filepath=str(third))
        if row["export3"]["result"] != "FINISHED":
            return row
        try:
            a = [line for line in _canon(second).splitlines() if line.strip()]  # the c14n keeps whitespace-only text
            b = [line for line in _canon(third).splitlines() if line.strip()]
        except Exception as exc:                 # the judge failed, not the add-on: say so and go on
            row["fixed_point"] = {"equal": None, "judge_error": f"{type(exc).__name__}: {exc}"[:200]}
            return row
        if a == b:
            row["fixed_point"] = {"equal": True}
            return row
        drift = first_drift(a, b)
        if drift is None:
            row["fixed_point"] = {"equal": True, "float32_noise": True}
        else:
            row["fixed_point"] = {"equal": False, "line": drift[0], "lines": [len(a), len(b)],
                                  "second": drift[1], "third": drift[2]}
        return row


def _beyond_float32(text: str) -> bool:
    """True when ``text`` names inf, nan, a number of magnitude 1e15 or more, or a non-zero one under 1e-15."""
    if re.search(r"\b-?(inf|nan)\b", text):
        return True
    for token in _NUM.findall(text):
        try:
            value = abs(float(token))
        except ValueError:
            continue
        if value >= 1e15 or 0.0 < value <= 1e-15:
            return True
    return False


def classify(row: dict) -> str:
    if row.get("class") == "op-failed":
        return "op-failed"
    exp = row["export"]["result"]
    if exp == "EXCEPTION":
        return "export-crash"
    if exp != "FINISHED":
        return "export-refused"
    if row["x3dpy"].get("valid") is None and "crash" in row["x3dpy"]:
        return "judge-crash"
    if row["own"]["valid"] is False or row["x3dpy"]["valid"] is False or (row.get("xsd") or {}).get("valid") is False:
        return "export-invalid"
    if row.get("tokens"):
        return "export-bad-number"
    for step in ("reimport", "export2", "reimport2", "export3"):
        if step in row and row[step]["result"] == "EXCEPTION":
            return f"{step}-crash"
        if step in row and row[step]["result"] != "FINISHED":
            return f"{step}-refused"
    if row.get("fixed_point", {}).get("equal") is False:
        if any("to stay within" in (row.get(step) or {}).get("log", "") for step in ("export", "export2", "export3")):
            # the export hit its animation sample budget (budget.py) and resampled: lossy by design, and said so
            return "budget-resampled"
        fp = row["fixed_point"]
        if all(line is None or (line.startswith("<meta ") and "name='info'" in line)
               for line in (fp.get("second"), fp.get("third"))):
            # the info meta lists Blender datablock names, which Blender suffixes on import (SplitMesh.001) and the
            # DEF spells SplitMesh_001: a log line, not scene data; listed, not gated
            return "info-meta-names"
        if row.get("op") in ("transform_extreme", "zero_scale") and _beyond_float32(row.get("what", "")):
            # a 1e30 location or scale, or a 1e-30 one under a parent: Blender holds object matrices in float32
            # (7 digits, products overflow past 3.4e38), so composing it with a child's matrix cannot round-trip;
            # listed, not gated (an exact 0 scale is gated: matrix_safety.decompose_exact keeps it)
            return "float32-range"
        return "fixed-point-drift"
    if row.get("fixed_point", {}).get("float32_noise"):
        return "float32-noise"          # listed, not gated
    return "ok"


NOT_GATED = ("ok", "op-failed", "float32-noise", "budget-resampled", "float32-range", "info-meta-names")   # listed in the summary
CRASH_CLASSES = {"export-crash", "judge-crash", "reimport-crash", "export2-crash", "reimport2-crash", "export3-crash"}
GATED = CRASH_CLASSES | {"export-invalid", "export-bad-number", "fixed-point-drift", "reimport-refused",
                         "export2-refused", "reimport2-refused", "export3-refused"}


def _signature_of(row: dict, cls: str) -> str:
    if cls.endswith("-crash"):
        return f"{cls}: {row[cls[:-6]].get('exception')}"
    if cls == "export-invalid":
        errors = ((row["own"].get("errors") or []) + (row["x3dpy"].get("errors") or [])
                  + ((row.get("xsd") or {}).get("errors") or []))
        first = errors[0] if errors else "?"
        return f"{cls}: " + re.sub(r"\d+(\.\d+)?", "N", str(first))[:120]
    if cls == "fixed-point-drift":
        line = row["fixed_point"].get("second") or row["fixed_point"].get("third") or ""
        return f"{cls}: " + re.sub(r"='[^']*'", "=…", line.strip())[:120]
    if cls == "export-bad-number":
        return f"{cls}: " + row["tokens"][0].split("=")[0]
    if cls.endswith("-refused"):
        return f"{cls}: {row['op']}"
    return cls


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--per-op", type=int, default=12, help="cases per scene operator")
    parser.add_argument("--rng", type=int, default=7)
    parser.add_argument("--only-op", action="append", default=[])
    parser.add_argument("--xsd", type=Path, help="directory holding x3d-4.0.xsd (and 4.1, 3.3) for xmllint")
    parser.add_argument("--fail-on-crash", action="store_true", help="exit 1 on any gated class")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 50000))   # the c14n walks a 1,500-deep export by recursion
    import frozen_scenes

    rng = random.Random(args.rng)
    runner = Runner(args.out)
    ops = args.only_op or sorted(OPERATORS)
    rows = []
    t0 = time.time()
    for op in ops:
        for _ in range(args.per_op):
            scene = rng.choice(frozen_scenes.SCENES)
            rows.append(runner.case(len(rows), scene, op, random.Random(rng.random())))
    if args.xsd:
        for version, name in (("X3D40", "x3d-4.0.xsd"), ("X3D41", "x3d-4.1.xsd"), ("X3D33", "x3d-3.3.xsd")):
            schema = args.xsd / name
            paths = [args.out / f"{r['id']}.x3d" for r in rows if r.get("export", {}).get("result") == "FINISHED"
                     and r.get("options", {}).get("x3d_version", "X3D40") == version]
            paths = [p for p in paths if p.exists()]
            if schema.exists() and paths:
                verdicts = judge_xsd(paths, schema)
                for r in rows:
                    v = verdicts.get(f"{r['id']}.x3d")
                    if v is not None:
                        r["xsd"] = v
    classes: Counter = Counter()
    signatures: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        cls = classify(row)
        row["class"] = cls
        classes[cls] += 1
        if cls not in NOT_GATED:
            signatures[_signature_of(row, cls)].append(row["id"])
    summary = {"cases": len(rows), "rng": args.rng, "seconds": round(time.time() - t0), "classes": dict(classes),
               "signatures": {k: {"count": len(v), "examples": v[:4]} for k, v in
                              sorted(signatures.items(), key=lambda kv: -len(kv[1]))}}
    (args.out / "rows.json").write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")
    (args.out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"[scene-chaos] {len(rows)} cases, rng {args.rng}, {summary['seconds']} s")
    print(f"[scene-chaos] classes: {dict(classes)}")
    for sig, data in summary["signatures"].items():
        print(f"[scene-chaos] x{data['count']:<4} {sig}   e.g. {data['examples'][0]}")
    gated = sum(n for c, n in classes.items() if c in GATED)
    if args.fail_on_crash and gated:
        print(f"[scene-chaos] FAIL: {gated} gated case(s)")
        return 1
    print(f"[scene-chaos] {'PASS' if not gated else 'done'}: {gated} gated case(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
