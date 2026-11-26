# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The crossing census: which Blender features survive an X3D export, and the trip back in.

    Blender -b --factory-startup --python tools/crossing_census.py -- --out DIR

For each probe: build the smallest scene that has the feature, export it with the add-on (animation on where the
feature moves), read the X3D back as XML, check what a faithful export would contain, re-import it into an empty scene,
and record a verdict:

    carried       the X3D holds it, with the value the scene had
    approximated  something stands in for it (named in the evidence)
    dropped       nothing in the file carries it
    error         the probe or the export failed (the traceback is kept)

Writes DIR/census.json and DIR/census.md. Read-only towards the add-on: it calls the operators, it changes nothing.
"""

import json
import math
import sys
import tempfile
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path

import addon_utils
import bpy

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = Path(ARGS[ARGS.index("--out") + 1] if "--out" in ARGS else tempfile.mkdtemp(prefix="x3d_census_"))
OUT.mkdir(parents=True, exist_ok=True)
SOURCE = Path(__file__).resolve().parents[1] / "source"
PROBES = []


def probe(area, feature, animated=False):
    def wrap(fn):
        PROBES.append((area, feature, animated, fn))
        return fn
    return wrap


def load_addon():
    shelf = Path(tempfile.mkdtemp(prefix="x3d_census_pkg_"))
    (shelf / "x3d_blender_io").symlink_to(SOURCE, target_is_directory=True)
    sys.path.insert(0, str(shelf))
    if addon_utils.enable("x3d_blender_io", default_set=True, handle_error=None) is None:
        raise RuntimeError("the add-on did not enable")


def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    load_addon()
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, 24
    return scene


def principled(name, **inputs):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    for k, v in inputs.items():
        bsdf.inputs[k.replace("_", " ")].default_value = v
    return mat, bsdf


def cube(name="Probe", size=1.0, location=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=size, location=location)
    obj = bpy.context.object
    obj.name = name
    return obj


def floats(text):
    return [float(v) for v in (text or "").replace(",", " ").split()]


class X:
    """The exported file, as XML, with the few lookups the checks need."""

    def __init__(self, path):
        self.text = path.read_text(encoding="utf-8", errors="replace")
        self.root = ET.fromstring(self.text)
        self.receipt = {}
        for meta in self.root.iter("meta"):
            if meta.get("name") == "x3d-blender-io.receipt":
                for part in (meta.get("content") or "").split():
                    if "=" in part:
                        k, v = part.split("=", 1)
                        self.receipt[k] = v

    def all(self, tag):
        return list(self.root.iter(tag))

    def one(self, tag):
        found = self.all(tag)
        return found[0] if found else None

    def count(self, tag):
        return len(self.all(tag))

    def material(self):
        """The first PhysicalMaterial, else Material. Not `a or b`: an Element with no children is falsy."""
        m = self.one("PhysicalMaterial")
        return m if m is not None else self.one("Material")


# -- geometry ---------------------------------------------------------------------------------------------------------

@probe("geometry", "mesh (a cube)")
def _():
    cube()
    def check(x, back):
        c = x.one("Coordinate")
        n = len(floats(c.get("point"))) // 3 if c is not None else 0
        return ("carried", f"IndexedFaceSet, {n} points (8 corners, split at UV seams)") if n >= 8 else ("dropped", "no Coordinate")
    return check


@probe("geometry", "smooth shading")
def _():
    bpy.ops.mesh.primitive_uv_sphere_add()
    bpy.ops.object.shade_smooth()

    def check(x, back):
        if x.one("Normal") is not None:
            return "carried", "per-vertex Normal node"
        crease = [float(n.get("creaseAngle", 0)) for n in x.all("IndexedFaceSet")]
        return ("approximated", f"creaseAngle {crease}") if any(crease) else ("dropped", "no normals, creaseAngle 0")
    return check


@probe("geometry", "subdivision modifier (evaluated)")
def _():
    obj = cube()
    obj.modifiers.new("Subsurf", "SUBSURF").levels = 2
    return lambda x, back: ("carried", f"{len(floats(x.one('Coordinate').get('point'))) // 3} points (cube has 8)") \
        if len(floats(x.one("Coordinate").get("point"))) // 3 > 50 else ("dropped", "base cage exported")


@probe("geometry", "UV map")
def _():
    cube()
    return lambda x, back: ("carried", "TextureCoordinate") if x.one("TextureCoordinate") is not None \
        else ("dropped", "no TextureCoordinate")


@probe("geometry", "colour attribute (vertex colours)")
def _():
    obj = cube()
    attr = obj.data.color_attributes.new("Col", "BYTE_COLOR", "CORNER")
    for i, d in enumerate(attr.data):
        d.color = (i % 3 == 0, i % 3 == 1, i % 3 == 2, 1.0)
    return lambda x, back: ("carried", "Color/ColorRGBA") if (x.one("Color") is not None or x.one("ColorRGBA") is not None) \
        else ("dropped", "no Color node")


@probe("geometry", "linked duplicates (shared mesh)")
def _():
    a = cube("A")
    b = a.copy()
    b.location.x = 3
    bpy.context.collection.objects.link(b)

    def check(x, back):
        uses = [e for e in x.root.iter() if e.get("USE")]
        return ("carried", f"{len(uses)} USE") if uses else ("dropped", "mesh written twice")
    return check


@probe("geometry", "parent and child")
def _():
    p = cube("Parent")
    c = cube("Child", 0.5, (2, 0, 0))
    c.parent = p

    def check(x, back):
        for t in x.all("Transform"):
            if any(ch.tag == "Transform" for ch in t):
                return "carried", "nested Transform"
        return "dropped", "flat"
    return check


@probe("geometry", "Geometry Nodes instances")
def _():
    obj = cube()
    tree = bpy.data.node_groups.new("Inst", "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    gi, go = tree.nodes.new("NodeGroupInput"), tree.nodes.new("NodeGroupOutput")
    pts = tree.nodes.new("GeometryNodeMeshToPoints")
    ico = tree.nodes.new("GeometryNodeMeshIcoSphere")
    ico.inputs["Radius"].default_value = 0.1
    inst = tree.nodes.new("GeometryNodeInstanceOnPoints")
    tree.links.new(gi.outputs[0], pts.inputs["Mesh"])
    tree.links.new(pts.outputs["Points"], inst.inputs["Points"])
    tree.links.new(ico.outputs["Mesh"], inst.inputs["Instance"])
    tree.links.new(inst.outputs["Instances"], go.inputs[0])
    obj.modifiers.new("GN", "NODES").node_group = tree

    def check(x, back):
        shapes, uses = x.count("Shape"), len([e for e in x.root.iter() if e.get("USE")])
        return ("carried", f"{shapes} Shape, the instance mesh defined once and {uses} USE") if shapes >= 8 else \
            ("dropped", f"{shapes} Shape")
    return check


@probe("geometry", "text object")
def _():
    bpy.ops.object.text_add()
    bpy.context.object.data.body = "X3D"
    return lambda x, back: ("carried", "Text node") if x.one("Text") is not None else \
        (("approximated", "converted to a mesh") if x.one("Coordinate") is not None else ("dropped", "nothing"))


@probe("geometry", "bevelled curve")
def _():
    bpy.ops.curve.primitive_bezier_circle_add()
    bpy.context.object.data.bevel_depth = 0.1
    return lambda x, back: ("approximated", "meshed") if x.one("Coordinate") is not None else \
        (("carried", "Extrusion") if x.one("Extrusion") is not None else ("dropped", "nothing"))


@probe("geometry", "Grease Pencil drawing")
def _():
    gp = bpy.data.grease_pencils.new("Ink")
    obj = bpy.data.objects.new("Ink", gp)
    bpy.context.collection.objects.link(obj)
    d = gp.layers.new("L").frames.new(1).drawing
    d.add_strokes([4])
    for i, p in enumerate(d.strokes[0].points):
        p.position = (i, 0, i % 2)
    return lambda x, back: ("carried", "line set") if (x.one("LineSet") is not None or x.one("IndexedLineSet") is not None) \
        else ("dropped", "nothing in the file")


# -- materials --------------------------------------------------------------------------------------------------------

@probe("material", "Principled base colour, metallic, roughness")
def _():
    obj = cube()
    obj.data.materials.append(principled("M", Base_Color=(0.8, 0.3, 0.1, 1), Metallic=0.7, Roughness=0.25)[0])

    def check(x, back):
        m = x.one("PhysicalMaterial")
        if m is None:
            return ("approximated", "Material (Blinn-Phong)") if x.one("Material") is not None else ("dropped", "no material")
        bc, me, ro = floats(m.get("baseColor")), float(m.get("metallic", -1)), float(m.get("roughness", -1))
        ok = all(abs(a - b) < 0.02 for a, b in zip(bc, (0.8, 0.3, 0.1))) and abs(me - 0.7) < 0.02 and abs(ro - 0.25) < 0.02
        return ("carried" if ok else "approximated"), f"baseColor {bc} metallic {me} roughness {ro}"
    return check


@probe("material", "emission (strength 5)")
def _():
    obj = cube()
    obj.data.materials.append(principled("E", Emission_Color=(0.2, 0.9, 1.0, 1), Emission_Strength=5.0)[0])

    def check(x, back):
        m = x.material()
        e = floats(m.get("emissiveColor")) if m is not None else []
        if not e or max(e) == 0:
            return "dropped", "no emissiveColor"
        return ("approximated", f"emissiveColor {e}: strength folded or clamped to [0, 1]") if max(e) <= 1.0 else \
            ("carried", f"emissiveColor {e}")
    return check


@probe("material", "alpha 0.5")
def _():
    obj = cube()
    obj.data.materials.append(principled("A", Alpha=0.5)[0])

    def check(x, back):
        m = x.material()
        t = float(m.get("transparency", 0)) if m is not None else 0
        return ("carried", f"transparency {t}") if abs(t - 0.5) < 0.02 else ("dropped", f"transparency {t}")
    return check


@probe("material", "glass transmission")
def _():
    obj = cube()
    obj.data.materials.append(principled("G", Transmission_Weight=1.0, Roughness=0.0)[0])

    def check(x, back):
        m = x.material()
        t = float(m.get("transparency", 0)) if m is not None else 0
        return ("approximated", f"transparency {t}") if t > 0 else ("dropped", "opaque: X3D 4.0 has no transmission")
    return check


@probe("material", "image texture")
def _():
    obj = cube()
    img = bpy.data.images.new("checker", 32, 32)
    img.generated_type = "COLOR_GRID"
    path = OUT / "census-checker.png"
    img.filepath_raw = str(path)
    img.file_format = "PNG"
    img.save()
    mat, bsdf = principled("T")
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = img
    mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    obj.data.materials.append(mat)
    return lambda x, back: ("carried", f"ImageTexture url {x.one('ImageTexture').get('url')}") \
        if x.one("ImageTexture") is not None else ("dropped", "no ImageTexture")


@probe("material", "procedural texture (noise)")
def _():
    obj = cube()
    mat, bsdf = principled("N")
    noise = mat.node_tree.nodes.new("ShaderNodeTexNoise")
    mat.node_tree.links.new(noise.outputs["Color"], bsdf.inputs["Base Color"])
    obj.data.materials.append(mat)

    def check(x, back):
        if x.one("ImageTexture") is not None:
            return "carried", "baked to an ImageTexture"
        m = x.one("PhysicalMaterial")
        return "dropped", f"flat baseColor {m.get('baseColor') if m is not None else None}"
    return check


# -- animation --------------------------------------------------------------------------------------------------------

def keyed(obj, path, values):
    for frame, value in zip((1, 12, 24), values):
        setattr(obj, path, value)
        obj.keyframe_insert(path, frame=frame)


@probe("animation", "keyframed location", animated=True)
def _():
    keyed(cube(), "location", [(0, 0, 0), (2, 0, 1), (0, 0, 0)])
    return lambda x, back: ("carried", f"{x.count('PositionInterpolator')} PositionInterpolator, {x.count('ROUTE')} ROUTE") \
        if x.count("PositionInterpolator") else ("dropped", "static")


@probe("animation", "keyframed rotation", animated=True)
def _():
    keyed(cube(), "rotation_euler", [(0, 0, 0), (0, 0, math.pi), (0, 0, 2 * math.pi)])
    return lambda x, back: ("carried", f"{x.count('OrientationInterpolator')} OrientationInterpolator") \
        if x.count("OrientationInterpolator") else ("dropped", "static")


@probe("animation", "keyframed scale", animated=True)
def _():
    keyed(cube(), "scale", [(1, 1, 1), (2, 2, 2), (1, 1, 1)])

    def check(x, back):
        routes = [r for r in x.all("ROUTE") if r.get("toField") in ("set_scale", "scale")]
        return ("carried", f"{len(routes)} ROUTE to scale") if routes else ("dropped", "static")
    return check


@probe("animation", "keyframes, exported with the default options")
def _():
    keyed(cube(), "location", [(0, 0, 0), (2, 0, 1), (0, 0, 0)])
    return lambda x, back: ("carried", "interpolators by default") if x.count("PositionInterpolator") else \
        ("dropped", "use_animation is off by default: a still")


@probe("animation", "driver (expression)", animated=True)
def _():
    obj = cube()
    d = obj.driver_add("rotation_euler", 2).driver
    d.type, d.expression = "SCRIPTED", "frame * 0.2"
    return lambda x, back: ("carried", f"baked: {x.count('OrientationInterpolator')} OrientationInterpolator") \
        if x.count("OrientationInterpolator") else ("dropped", "static")


@probe("animation", "shape key animation", animated=True)
def _():
    obj = cube()
    obj.shape_key_add(name="Basis")
    sk = obj.shape_key_add(name="Tall")
    for p in sk.data:
        p.co.z *= 2.5
    sk.value = 0.0
    sk.keyframe_insert("value", frame=1)
    sk.value = 1.0
    sk.keyframe_insert("value", frame=24)
    return lambda x, back: ("carried", f"{x.count('CoordinateInterpolator')} CoordinateInterpolator") \
        if x.count("CoordinateInterpolator") else ("dropped", "no CoordinateInterpolator: the mesh is a still")


@probe("animation", "shape key moved by a driver", animated=True)
def _():
    obj = cube()
    obj.shape_key_add(name="Basis")
    sk = obj.shape_key_add(name="Tall")
    for p in sk.data:
        p.co.z *= 2.5
    d = sk.driver_add("value").driver
    d.type, d.expression = "SCRIPTED", "frame / 24"
    return lambda x, back: ("carried", f"baked: {x.count('CoordinateInterpolator')} CoordinateInterpolator") \
        if x.count("CoordinateInterpolator") else ("dropped", "no CoordinateInterpolator: keyed shape keys cross, driven ones do not")


@probe("animation", "armature (skinned)", animated=True)
def _():
    bpy.ops.object.armature_add()
    arm = bpy.context.object
    obj = cube(location=(0, 0, 0.5))
    obj.parent, obj.parent_type = arm, "OBJECT"
    mod = obj.modifiers.new("Arm", "ARMATURE")
    mod.object = arm
    vg = obj.vertex_groups.new(name="Bone")
    vg.add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")
    pb = arm.pose.bones["Bone"]
    pb.rotation_mode = "XYZ"
    for f, a in ((1, 0.0), (24, 1.2)):
        pb.rotation_euler = (a, 0, 0)
        pb.keyframe_insert("rotation_euler", frame=f)
    return lambda x, back: ("carried", f"{x.count('HAnimHumanoid')} HAnimHumanoid, {x.count('HAnimJoint')} joints") \
        if x.count("HAnimHumanoid") else ("dropped", "no HAnim")


# -- scene ------------------------------------------------------------------------------------------------------------

@probe("scene", "point, sun, spot and area lights")
def _():
    for kind, loc in (("POINT", (0, 0, 3)), ("SUN", (0, 0, 5)), ("SPOT", (2, 0, 3)), ("AREA", (-2, 0, 3))):
        bpy.ops.object.light_add(type=kind, location=loc)

    def check(x, back):
        got = {t: x.count(t) for t in ("PointLight", "DirectionalLight", "SpotLight")}
        total = sum(got.values())
        if total == 4 and got["DirectionalLight"] == 2:
            return "approximated", f"{got}: the area light became a DirectionalLight"
        return ("carried" if total == 4 else "dropped"), str(got)
    return check


@probe("scene", "camera field of view")
def _():
    bpy.ops.object.camera_add(location=(0, -5, 0))
    cam = bpy.context.object
    cam.data.lens = 35
    want = cam.data.angle

    def check(x, back):
        v = x.one("Viewpoint")
        if v is None:
            return "dropped", "no Viewpoint"
        fov = float(v.get("fieldOfView", 0.785398))
        return ("carried" if abs(fov - min(want, 2 * math.atan(math.tan(want / 2) * 9 / 16))) < 0.02 or abs(fov - want) < 0.02
                else "approximated"), f"fieldOfView {fov:.4f}, camera angle {want:.4f}"
    return check


@probe("scene", "world colour")
def _():
    world = bpy.data.worlds.new("W")
    bpy.context.scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.1, 0.2, 0.4, 1)
    cube()

    def check(x, back):
        b = x.one("Background")
        sky = floats(b.get("skyColor")) if b is not None else []
        return ("carried", f"skyColor {sky}") if sky and abs(sky[2] - 0.4) < 0.05 else ("dropped", f"skyColor {sky}")
    return check


@probe("scene", "custom property")
def _():
    obj = cube()
    obj["census_note"] = "keep me"

    def check(x, back):
        hits = [m for m in x.root.iter() if m.tag.startswith("Metadata") and "keep me" in (m.get("value") or "")]
        return ("carried", f"{hits[0].tag}") if hits else ("dropped", "no Metadata node")
    return check


# -- the run ----------------------------------------------------------------------------------------------------------

def run_probe(area, feature, animated, build):
    record = {"area": area, "feature": feature}
    try:
        empty_scene()
        check = build()
        path = OUT / f"{len(RESULTS):02d}.x3d"
        options = {"use_animation": True} if animated else {}
        result = bpy.ops.export_scene.x3d(filepath=str(path), **options)
        record["export"] = sorted(result)
        x = X(path)
        record["receipt"] = {k: v for k, v in x.receipt.items() if k in ("dropped", "approximated", "clamped")}
        bpy.ops.wm.read_factory_settings(use_empty=True)
        load_addon()
        back = {"import": sorted(bpy.ops.import_scene.x3d(filepath=str(path)))}
        back["objects"] = len(bpy.data.objects)
        back["animated"] = sum(1 for o in bpy.data.objects if o.animation_data and o.animation_data.action)
        record["round_trip"] = back
        record["verdict"], record["evidence"] = check(x, back)
    except Exception:
        record["verdict"], record["evidence"] = "error", traceback.format_exc()[-600:]
    print(f"[census] {record['verdict']:12} {area:9} {feature}: {str(record.get('evidence'))[:90]}")
    return record


def negative_controls():
    """Every check must be able to say no: on an empty X3D file none may answer carried (a census whose checks only say
    yes measures nothing; four checks of the first run said no wrongly, so they are held to both sides)."""
    empty = OUT / "empty.x3d"
    empty.write_text("<?xml version='1.0' encoding='UTF-8'?><X3D profile='Immersive' version='4.0'><head/><Scene/></X3D>")
    bad = []
    for area, feature, animated, build in PROBES:
        empty_scene()
        check = build()
        try:
            verdict, _ = check(X(empty), {})
        except Exception as error:
            verdict = f"raised {type(error).__name__}"
        if verdict == "carried":
            bad.append(feature)
    return bad


RESULTS = []
for area, feature, animated, build in PROBES:
    RESULTS.append(run_probe(area, feature, animated, build))
CONTROL_FAILURES = negative_controls()
print("[census] negative controls: checks that said carried on an empty file:", CONTROL_FAILURES)

summary = {v: sum(1 for r in RESULTS if r["verdict"] == v) for v in ("carried", "approximated", "dropped", "error")}
meta = {"blender": bpy.app.version_string, "probes": len(RESULTS), "summary": summary,
        "negative_control_failures": CONTROL_FAILURES}
(OUT / "census.json").write_text(json.dumps({"meta": meta, "results": RESULTS}, indent=1))
lines = [f"| Area | Feature | Verdict | Evidence | Back in Blender |", "|---|---|---|---|---|"]
for r in RESULTS:
    rt = r.get("round_trip", {})
    lines.append(f"| {r['area']} | {r['feature']} | **{r['verdict']}** | {str(r['evidence']).splitlines()[-1][:110]} | "
                 f"{rt.get('objects', '-')} objects, {rt.get('animated', '-')} animated |")
(OUT / "census.md").write_text(f"Blender {meta['blender']}: {summary}\n\n" + "\n".join(lines) + "\n")
print("[census] done", meta)
