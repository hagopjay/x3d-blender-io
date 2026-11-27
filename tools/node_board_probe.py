# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Measure the node board's read and written rungs in a real Blender (needs ``bpy``).

    python tools/node_board_probe.py [--out tools/node_board_measured.json] [--only Node ...]

READ. For every concrete node of X3DUOM 4.0 the probe builds a small file that holds the node in a place the standard lets
it sit (found from the object model's acceptableNodeTypes: Scene -> Shape -> Appearance -> Material, and so on), imports it
with the add-on's operator, and imports the same file without the node (the control). The difference between the two
Blender states is the node's effect: ``builds`` when Blender data differ (objects, meshes, materials, lights, cameras,
worlds, actions, images, curves, node trees, point clouds, volumes, speakers, particle systems), ``carries`` when only custom
properties, text blocks or collections of kept XML differ, ``none`` when nothing differs. A node whose chain the object model
cannot give is ``unprobed``.

WRITTEN. An element is ``observed`` when a file the exporter wrote contains it and the file validates against
x3d-4.0.xsd: the exports of every .x3d fixture of this repository after an import (X3D 4.0 and the behaviour graph on), of
the swatch book and the scene fixture, plus, for the event nodes, the behaviour graph's own emitter (one graph per node:
ROUTE-less, wrapped in a Full-profile file). ``writable`` is an element named in source/emit_x3d40.py that no run observed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "source"))
sys.path.insert(0, str(ROOT / "tests"))

XSD = Path(os.environ.get("X3D_XSD", "/home/user/x3d_mcp/src/validation/schemas/x3d-4.0.xsd"))
HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n<X3D profile="Full" version="4.0" xmlns:xsd="http://www.w3.org/2001/XMLSchema-instance" xsd:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd"><head/><Scene>\n'
TAIL = "\n</Scene></X3D>\n"
TRI = "0 0 0 1 0 0 0 1 0"
import base64
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

# What the object model cannot say: a node that does nothing until it has points, a face or a string.
NODE_ATTRS = {
    "Coordinate": f'point="{TRI}"', "Normal": 'vector="0 0 1 0 0 1 0 0 1"', "Color": 'color="1 0 0 0 1 0 0 0 1"',
    "ColorRGBA": 'color="1 0 0 1 0 1 0 1 0 0 1 1"', "TextureCoordinate": 'point="0 0 1 0 0 1"',
    "TextureCoordinate3D": 'point="0 0 0 1 0 0 0 1 0"', "TextureCoordinate4D": 'point="0 0 0 1 1 0 0 1 0 1 0 1"',
    "CoordinateDouble": f'point="{TRI}"', "Text": 'string="hello"',
    "IndexedFaceSet": 'coordIndex="0 1 2 -1"', "IndexedLineSet": 'coordIndex="0 1 2 -1"',
    "IndexedTriangleSet": 'index="0 1 2"', "IndexedTriangleStripSet": 'index="0 1 2 -1"',
    "IndexedTriangleFanSet": 'index="0 1 2 -1"', "IndexedQuadSet": 'index="0 1 2 0"', "LineSet": 'vertexCount="3"',
    "TriangleStripSet": 'stripCount="3"', "TriangleFanSet": 'fanCount="3"',
    "Polyline2D": 'lineSegments="0 0 1 0 1 1"', "Polypoint2D": 'point="0 0 1 0 1 1"', "TriangleSet2D": 'vertices="0 0 1 0 0 1"',
    "ElevationGrid": 'xDimension="2" zDimension="2" height="0 0 0 1"',
    "ArcClose2D": 'endAngle="3"', "Arc2D": 'endAngle="3"',
    "Billboard": "", "ImageTexture": 'url="&quot;x.png&quot;"', "PixelTexture": 'image="1 1 3 0xff0000"',
    "AudioClip": 'url="&quot;x.wav&quot;"', "MovieTexture": 'url="&quot;x.mp4&quot;"',
    "Viewpoint": 'position="0 1 5"', "DirectionalLight": 'direction="0 -1 0"',
}
NODE_INNER = {
    "IndexedFaceSet": f'<Coordinate point="{TRI}"/>', "IndexedLineSet": f'<Coordinate point="{TRI}"/>',
    "PointSet": f'<Coordinate point="{TRI}"/>', "LineSet": f'<Coordinate point="{TRI}"/>',
    "IndexedTriangleSet": f'<Coordinate point="{TRI}"/>', "TriangleSet": f'<Coordinate point="{TRI}"/>',
    "IndexedTriangleStripSet": f'<Coordinate point="{TRI}"/>', "TriangleStripSet": f'<Coordinate point="{TRI}"/>',
    "IndexedTriangleFanSet": f'<Coordinate point="{TRI}"/>', "TriangleFanSet": f'<Coordinate point="{TRI}"/>',
    "IndexedQuadSet": f'<Coordinate point="0 0 0 1 0 0 1 1 0 0 1 0"/>', "QuadSet": f'<Coordinate point="0 0 0 1 0 0 1 1 0 0 1 0"/>',
    "HAnimHumanoid": "", "Text": "",
}
# What a parent needs so that its child has somewhere to take effect.
PARENT_ATTRS = {"IndexedFaceSet": 'coordIndex="0 1 2 -1"', "IndexedLineSet": 'coordIndex="0 1 2 -1"',
                "IndexedTriangleSet": 'index="0 1 2"', "IndexedTriangleStripSet": 'index="0 1 2 -1"',
                "IndexedTriangleFanSet": 'index="0 1 2 -1"', "IndexedQuadSet": 'index="0 1 2 0"',
                "LineSet": 'vertexCount="3"', "TriangleStripSet": 'stripCount="3"', "TriangleFanSet": 'fanCount="3"'}
PARENT_INNER = {"IndexedFaceSet": f'<Coordinate point="{TRI}"/>', "IndexedLineSet": f'<Coordinate point="{TRI}"/>',
                "PointSet": f'<Coordinate point="{TRI}"/>', "LineSet": f'<Coordinate point="{TRI}"/>',
                "IndexedTriangleSet": f'<Coordinate point="{TRI}"/>', "TriangleSet": f'<Coordinate point="{TRI}"/>',
                "IndexedTriangleStripSet": f'<Coordinate point="{TRI}"/>', "TriangleStripSet": f'<Coordinate point="{TRI}"/>',
                "IndexedTriangleFanSet": f'<Coordinate point="{TRI}"/>', "TriangleFanSet": f'<Coordinate point="{TRI}"/>',
                "Shape": '<Box containerField="geometry"/>'}
GROUPING = {"Group", "Transform", "Anchor", "Billboard", "Collision", "LOD", "Switch", "StaticGroup", "CADAssembly",
            "CADPart", "CADLayer", "GeoLocation", "GeoTransform", "ViewpointGroup", "LayoutGroup", "ScreenGroup",
            "Layer", "LayerSet", "GeoLOD", "HAnimSite", "HAnimSegment", "HAnimJoint", "HAnimHumanoid"}
BOX = "<Shape><Box/></Shape>"
TIMER = '<TimeSensor DEF="T" cycleInterval="2" loop="true"/>'
MOVER = '<Transform DEF="X"><Shape><Appearance><Material DEF="M"/></Appearance><Box/></Shape></Transform>'


def _animated(node, key_value, field, target, out="value_changed", fraction="set_fraction"):
    body = f'<{node} DEF="I" key="0 1" keyValue="{key_value}"/>'
    routes = (f'<ROUTE fromNode="T" fromField="fraction_changed" toNode="I" toField="{fraction}"/>'
              f'<ROUTE fromNode="I" fromField="{out}" toNode="{target}" toField="{field}"/>')
    return TIMER + MOVER, TIMER + MOVER + body + routes


# Whole files for the nodes that do nothing alone: (control, test).
OVERRIDES = {
    "Transform": (BOX, '<Transform translation="1 2 3" rotation="0 1 0 1">' + BOX + "</Transform>"),
    "Shape": ("", BOX),
    "Appearance": (BOX, "<Shape><Box/><Appearance><Material diffuseColor=\"1 0 0\"/></Appearance></Shape>"),
    "LOD": (BOX, '<LOD range="5">' + BOX + BOX + "</LOD>"),
    "PositionInterpolator": _animated("PositionInterpolator", "0 0 0 1 1 1", "translation", "X"),
    "OrientationInterpolator": _animated("OrientationInterpolator", "0 1 0 0 0 1 0 1.5", "rotation", "X"),
    "ScalarInterpolator": _animated("ScalarInterpolator", "0 1", "transparency", "M"),
    "ColorInterpolator": _animated("ColorInterpolator", "0 0 0 1 0 0", "diffuseColor", "M"),
    "TextureCoordinate": ('<Shape><Appearance><Material/><ImageTexture url="&quot;x.png&quot;"/></Appearance><IndexedFaceSet coordIndex="0 1 2 -1"><Coordinate point="0 0 0 1 0 0 0 1 0"/></IndexedFaceSet></Shape>',
                          '<Shape><Appearance><Material/><ImageTexture url="&quot;x.png&quot;"/></Appearance><IndexedFaceSet coordIndex="0 1 2 -1"><Coordinate point="0 0 0 1 0 0 0 1 0"/><TextureCoordinate point="0 0 1 0 0 1"/></IndexedFaceSet></Shape>'),
    "Normal": ('<Shape><IndexedFaceSet coordIndex="0 1 2 -1"><Coordinate point="0 0 0 1 0 0 0 1 0"/></IndexedFaceSet></Shape>',
               '<Shape><IndexedFaceSet coordIndex="0 1 2 -1"><Coordinate point="0 0 0 1 0 0 0 1 0"/><Normal vector="1 0 0 1 0 0 1 0 0"/></IndexedFaceSet></Shape>'),
    "TextureTransform": ('<Shape><Appearance><Material/><ImageTexture url="&quot;x.png&quot;"/></Appearance><Box/></Shape>',
                         '<Shape><Appearance><Material/><ImageTexture url="&quot;x.png&quot;"/><TextureTransform translation="0.5 0.25" scale="2 2"/></Appearance><Box/></Shape>'),
    "Fog": ("", '<Fog color="1 0 0" visibilityRange="10"/>'),
    "NavigationInfo": ("", '<NavigationInfo headlight="false" speed="9" type=\'"WALK" "ANY"\'/>'),
    "WorldInfo": ("", '<WorldInfo title="probe" info=\'"one" "two"\'/>'),
    "Sound": ("", '<Sound><AudioClip url="&quot;x.wav&quot;"/></Sound>'),
    "AudioClip": ("", '<Sound><AudioClip url="&quot;x.wav&quot;"/></Sound>'),
    "FillProperties": (BOX, "<Shape><Appearance><FillProperties filled=\"false\"/></Appearance><Box/></Shape>"),
    "LineProperties": ('<Shape><Appearance><Material/></Appearance><IndexedLineSet coordIndex="0 1 -1"><Coordinate point="0 0 0 1 0 0"/></IndexedLineSet></Shape>',
                       '<Shape><Appearance><Material/><LineProperties linewidthScaleFactor="5"/></Appearance><IndexedLineSet coordIndex="0 1 -1"><Coordinate point="0 0 0 1 0 0"/></IndexedLineSet></Shape>'),
    "ImageTexture": ('<Shape><Appearance><Material/></Appearance><Box/></Shape>',
                     '<Shape><Appearance><Material/><ImageTexture url="&quot;x.png&quot;"/></Appearance><Box/></Shape>'),
    "PixelTexture": ('<Shape><Appearance><Material/></Appearance><Box/></Shape>',
                     '<Shape><Appearance><Material/><PixelTexture image="1 1 3 0xff0000"/></Appearance><Box/></Shape>'),
    "MovieTexture": ('<Shape><Appearance><Material/></Appearance><Box/></Shape>',
                     '<Shape><Appearance><Material/><MovieTexture url="&quot;x.mp4&quot;"/></Appearance><Box/></Shape>'),
}
# When the node is itself the Coordinate (etc.) the parent must not already carry one.
PREFER = ("Shape", "Appearance", "Transform", "Group", "IndexedFaceSet", "Switch", "HAnimHumanoid", "HAnimJoint", "Scene")


def chains(uom):
    """{node: (parent, field)}: the shortest way down from Scene to every node the object model lets sit somewhere."""
    nodes = uom["nodes"]
    accepts = {name: info["accepts"] for name, info in nodes.items()}
    accepts["Scene"] = [["children", ["X3DChildNode"]]]
    bases = {name: set(info["bases"]) | {name} for name, info in nodes.items()}
    reach = {"Scene": None}
    queue = ["Scene"]
    force = {"Coordinate": ("IndexedFaceSet", "coord"), "Normal": ("IndexedFaceSet", "normal"),
             "Color": ("IndexedFaceSet", "color"), "ColorRGBA": ("IndexedFaceSet", "color"),
             "TextureCoordinate": ("IndexedFaceSet", "texCoord"), "TextureCoordinate3D": ("IndexedFaceSet", "texCoord"),
             "CoordinateDouble": ("IndexedFaceSet", "coord")}
    while queue:
        nxt = []
        for parent in sorted(queue, key=lambda p: (PREFER.index(p) if p in PREFER else len(PREFER), p)):
            for fname, types in accepts[parent]:
                for name in sorted(nodes):
                    if name not in reach and (set(types) - {"X3DNode", "*"}) & bases[name]:
                        reach[name] = (parent, fname)
                        nxt.append(name)
        queue = nxt
        for name, step in force.items():
            if name in nodes:
                reach[name] = step
    for name, info in nodes.items():         # the usual home of a node several fields accept
        for base, field in (("X3DMaterialNode", "material"), ("X3DTextureNode", "texture"),
                            ("X3DTextureTransformNode", "textureTransform"), ("X3DShaderNode", "shaders"),
                            ("X3DMetadataObject", "metadata")):
            if base in info["bases"] and name not in ("MultiTexture", "MultiTextureTransform") and \
                    base in ("X3DMaterialNode", "X3DTextureNode", "X3DTextureTransformNode", "X3DShaderNode"):
                reach[name] = ("Appearance", field)
    reach.update({"Layer": ("LayerSet", "layers"), "LayoutLayer": ("LayerSet", "layers"), "LayerSet": ("Scene", "children")})
    for name in nodes:
        if name.startswith("Metadata") and name != "MetadataSet" or name == "MetadataSet":
            reach[name] = ("Transform", "metadata")
    return reach


def snippet(name, reach, with_node=True, bases=()):
    """The file body that holds ``name`` (or, with_node False, the same file without it)."""
    def element(node, field, inner, attrs=""):
        return f'<{node} containerField="{field}" {attrs}>{inner}</{node}>' if inner else f'<{node} containerField="{field}" {attrs}/>'
    inner = NODE_INNER.get(name, "")
    if name in GROUPING:
        inner = "<Shape><Box/></Shape>"
    body = element(name, "children", inner, NODE_ATTRS.get(name, "")) if with_node else ""
    node, step = name, reach.get(name)
    if step is None:
        return None
    field = step[1]
    body = body.replace('containerField="children"', f'containerField="{field}"', 1) if with_node else ""
    while True:
        parent, pfield = reach[node]
        if parent == "Scene":
            return body
        extra = PARENT_INNER.get(parent, "")
        if parent == "Shape" and (node == name and "X3DGeometryNode" in bases or 'containerField="geometry"' in body):
            extra = ""
        if node in ("Coordinate", "Normal", "Color", "ColorRGBA", "TextureCoordinate", "TextureCoordinate3D", "CoordinateDouble") and parent in PARENT_INNER:
            extra = ""                       # the node itself is what the parent lacks
        pfield2 = reach[parent][1] if reach[parent] else "children"
        body = element(parent, pfield2, extra + body, PARENT_ATTRS.get(parent, ""))
        node = parent


def fingerprint(bpy):
    """What Blender holds, as plain data, for comparing two imports."""
    d = bpy.data
    out = {}

    def props(idb):
        return sorted(k for k in idb.keys() if not k.startswith("_"))
    for coll in ("objects", "meshes", "materials", "lights", "cameras", "worlds", "actions", "images", "curves",
                 "node_groups", "collections", "speakers", "pointclouds", "volumes", "armatures", "lattices",
                 "particles", "texts", "fonts", "grease_pencils", "sounds", "movieclips", "scenes"):
        if not hasattr(d, coll):
            continue
        items = []
        for idb in getattr(d, coll):
            row = {"props": props(idb)}
            if coll == "objects":
                row.update(type=idb.type, m=[round(v, 4) for r in idb.matrix_world for v in r], parent=bool(idb.parent),
                           hide=idb.hide_viewport, mods=[m.type for m in idb.modifiers], data=idb.data.name if idb.data else None)
            elif coll == "meshes":
                row.update(v=len(idb.vertices), p=len(idb.polygons), e=len(idb.edges), uv=len(idb.uv_layers),
                           attrs=sorted(a.name for a in idb.attributes), mats=len(idb.materials))
            elif coll == "materials":
                row.update(c=[round(v, 4) for v in idb.diffuse_color], nodes=_tree(idb.node_tree), blend=getattr(idb, "blend_method", ""))
            elif coll == "lights":
                row.update(t=idb.type, e=round(idb.energy, 4), c=[round(v, 4) for v in idb.color])
            elif coll == "cameras":
                row.update(t=idb.type, lens=round(idb.lens, 4), ortho=round(idb.ortho_scale, 4), clip=round(idb.clip_start, 5))
            elif coll == "worlds":
                row.update(c=[round(v, 4) for v in idb.color], nodes=_tree(idb.node_tree))
            elif coll == "actions":
                row.update(f=len(list(_fcurves(idb))))
            elif coll == "node_groups":
                row.update(nodes=_tree(idb))
            elif coll == "texts":
                row.update(len=len(idb.as_string()))
            elif coll == "scenes":
                row.update(f=[idb.frame_start, idb.frame_end, idb.render.fps, idb.unit_settings.scale_length])
            items.append((idb.name, row))
        out[coll] = items
    return out


def _fcurves(action):
    try:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    yield from bag.fcurves
    except AttributeError:
        pass
    try:
        yield from action.fcurves
    except AttributeError:
        pass


def _tree(tree):
    if tree is None:
        return None
    rows = []
    for n in tree.nodes:
        vals = []
        for i in n.inputs:
            v = getattr(i, "default_value", None)
            try:
                v = [round(x, 4) for x in v]
            except TypeError:
                v = round(v, 4) if isinstance(v, float) else v if isinstance(v, (int, str, bool)) else None
            vals.append(v)
        rows.append((n.bl_idname, getattr(getattr(n, "image", None), "name", None), vals))
    return rows


def difference(base, test):
    """Which collections differ, and whether only through custom properties and texts."""
    data, carry = [], []
    for coll in sorted(set(base) | set(test)):
        a, b = base.get(coll, []), test.get(coll, [])
        if a == b:
            continue
        if coll in ("texts",):
            carry.append(coll)
            continue
        if len(a) != len(b):
            data.append(f"{coll} {len(b) - len(a):+d}")
            continue
        for (na, ra), (nb, rb) in zip(a, b):
            ra2, rb2 = {k: v for k, v in ra.items() if k != "props"}, {k: v for k, v in rb.items() if k != "props"}
            if ra2 != rb2:
                data.append(f"{coll} changed")
                break
            if ra["props"] != rb["props"]:
                carry.append(f"{coll} props {sorted(set(rb['props']) - set(ra['props']))[:3]}")
    return data, carry


def read_probe(bpy, mod, tmp, only):
    uom = json.loads((ROOT / "tools" / "node_board_nodes.json").read_text())
    reach = chains(uom)
    logger = logging.getLogger()
    records = []

    class Catch(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())
    catch = Catch(level=logging.WARNING)
    logger.addHandler(catch)
    results = {}
    cache = {}
    (Path(tmp) / "x.png").write_bytes(PNG)
    import wave
    with wave.open(str(Path(tmp) / "x.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(b"\0\0" * 800)

    def run(body, graph=False):
        if (body, graph) in cache:
            return cache[(body, graph)]
        bpy.ops.wm.read_factory_settings(use_empty=True)
        path = Path(tmp) / "probe.x3d"
        path.write_text(HEAD + body + TAIL, encoding="utf-8")
        records.clear()
        try:
            res = bpy.ops.import_scene.x3d(filepath=str(path), use_behaviour_graph=graph)
            err = None if "FINISHED" in res else str(res)
        except Exception as exc:                    # a crash is a finding: the node breaks the import
            err = f"{type(exc).__name__}: {exc}"[:200]
        out = (fingerprint(bpy), err, list(records))
        cache[(body, graph)] = out
        return out
    for name in sorted(uom["nodes"]):
        if only and name not in only:
            continue
        bases = set(uom["nodes"][name]["bases"])
        test = snippet(name, reach, bases=bases)
        if test is None:
            results[name] = {"read": "unprobed", "read_evidence": "the object model gives no parent that accepts it"}
            continue
        if name in OVERRIDES:
            control, test = OVERRIDES[name]
        else:
            control = snippet(name, reach, with_node=False, bases=bases)
        if name in OVERRIDES:
            pass
        elif name in GROUPING and control is not None:      # the control is the content with the grouping node dissolved
            control = control + "<Shape><Box/></Shape>" if reach[name][0] == "Scene" else control
        base, _, _ = run(control)
        fp, err, warns = run(test)
        data, carry = difference(base, fp)
        if err and "FINISHED" not in err:
            results[name] = {"read": "none", "read_evidence": f"import failed: {err}"}
        elif data:
            results[name] = {"read": "builds", "read_evidence": ", ".join(data[:4])}
        elif name in GROUPING and name not in ("Transform", "Switch", "LOD") and not carry:
            results[name] = {"read": "structural", "read_evidence": "children are read, the node itself is not kept"}
        elif carry and all("x3d_import_losses" in c for c in carry):
            g_base, _, _ = run(control, True)
            g_fp, g_err, _ = run(test, True)
            g_data, g_carry = difference(g_base, g_fp)
            g_carry = [c for c in g_carry if "x3d_import_losses" not in c]
            if g_data or g_carry:
                results[name] = {"read": "graph", "read_evidence": "behaviour graph: " + ", ".join((g_data + g_carry)[:3])}
            else:
                results[name] = {"read": "reported", "read_evidence": "dropped, with a line in the import loss report"}
        elif carry:
            results[name] = {"read": "carries", "read_evidence": ", ".join(carry[:3])}
        else:
            note = next((w for w in warns if name in w), "")
            results[name] = {"read": "none", "read_evidence": note[:120]}
    logger.removeHandler(catch)
    return results


def validate(xsd, path_or_text):
    from lxml import etree
    doc = etree.fromstring(path_or_text.encode("utf-8") if isinstance(path_or_text, str) else path_or_text)
    ok = xsd.validate(doc)
    return ok, [str(e) for e in xsd.error_log][:3]


def elements_of(data):
    return {el.tag.split("}")[-1] for el in ET.fromstring(data).iter() if isinstance(el.tag, str)}


def written_probe(bpy, tmp):
    from lxml import etree
    xsd40 = etree.XMLSchema(etree.parse(str(XSD)))
    xsd41 = etree.XMLSchema(etree.parse(str(XSD).replace("4.0", "4.1")))
    observed = {}
    invalid = {}

    def note(label, data):
        xsd = xsd41 if b'version="4.1"' in (data if isinstance(data, bytes) else data.encode())[:400] else xsd40
        ok, errors = validate(xsd, data)
        if not ok:
            invalid[label] = errors
            return
        for tag in elements_of(data):
            observed.setdefault(tag, []).append(label)
    # 1. every fixture of the repository, imported and exported again
    fixtures = sorted(p for p in ROOT.rglob("*.x3d") if "node_modules" not in p.parts)
    for path in fixtures:
        label = str(path.relative_to(ROOT))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        try:
            bpy.ops.import_scene.x3d(filepath=str(path), use_behaviour_graph=True)
            out = Path(tmp) / "out.x3d"
            bpy.ops.export_scene.x3d(filepath=str(out), x3d_version="X3D40", use_selection=False, use_animation=True)
            note(label, out.read_bytes())
        except Exception as exc:
            invalid[label] = [f"{type(exc).__name__}: {exc}"[:150]]
    # 2. built scenes
    for label, build in (("tools/swatch_book.py", "swatch"), ("tools/scene_fixture.py", "scene")):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        try:
            if build == "swatch":
                from swatch_book import build_swatch_book
                build_swatch_book(texture_dir=tmp)
            else:
                import scene_fixture
                scene_fixture.build_scene_fixture()
            out = Path(tmp) / "built.x3d"
            bpy.ops.export_scene.x3d(filepath=str(out), x3d_version="X3D40", use_selection=False)
            note(label, out.read_bytes())
        except Exception as exc:
            invalid[label] = [f"{type(exc).__name__}: {exc}"[:150]]
    # 2b. the export suite's three corpus files (tests/suite/x3d_test_suite.py), which tools/mapping/build_mapping.py reads
    import subprocess
    suite = Path(tmp) / "suite"
    suite.mkdir()
    run = subprocess.run([sys.executable, str(ROOT / "tests" / "suite" / "x3d_test_suite.py"), "--", "--out", str(suite),
                          "--repo", str(ROOT), "--export"], capture_output=True, text=True, timeout=300)
    for path in sorted(suite.glob("x3d_suite_*.x3d")):
        note("tests/suite:" + path.name, path.read_bytes())
    # 3. the behaviour graph's emitter, one node per file
    import behaviour_catalogue as cat
    import behaviour_graph as bg
    for name in sorted(set(cat.NODES) - set(getattr(cat, "IN_PLACE", ()))):     # in-place nodes ride in the scene's own nodes
        graph = bg.Behaviour()
        try:
            graph.add(name, "Probe")
            emission = bg.emit(graph)
            text = HEAD + "".join(emission.root) + TAIL
            note(f"behaviour_graph:{name}", text)
        except Exception as exc:
            invalid[f"behaviour_graph:{name}"] = [f"{type(exc).__name__}: {exc}"[:150]]
    return observed, invalid


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out", default=str(ROOT / "tools" / "node_board_measured.json"))
    p.add_argument("--only", nargs="*")
    p.add_argument("--skip-written", action="store_true")
    args = p.parse_args(argv)
    import bpy
    tmp = tempfile.mkdtemp(prefix="node_board_")
    from test_roundtrip_bpy import _register_extension
    mod = _register_extension(tmp)
    read = read_probe(bpy, mod, tmp, set(args.only or ()))
    observed, invalid = ({}, {}) if args.skip_written else written_probe(bpy, tmp)
    shutil.rmtree(tmp, ignore_errors=True)
    uom = json.loads((ROOT / "tools" / "node_board_nodes.json").read_text())
    static = set(re.findall(r"<([A-Z][A-Za-z0-9]+)\b", (ROOT / "source" / "emit_x3d40.py").read_text()))
    nodes = {}
    for name in uom["nodes"]:
        row = dict(read.get(name, {"read": "unprobed", "read_evidence": ""}))
        if name in observed:
            row["written"] = "observed"
            row["written_by"] = sorted(set(observed[name]))[:3]
        elif name in static:
            row["written"] = "writable"
        else:
            row["written"] = "no"
        nodes[name] = row
    out = {"instrument": {"blender": bpy.app.version_string, "python": sys.version.split()[0],
                          "validator": "lxml XMLSchema over x3d-4.0.xsd (x3d-4.1.xsd for a version=\"4.1\" file)", "tool": "tools/node_board_probe.py",
                          "fixtures_invalid": invalid},
           "nodes": nodes}
    Path(args.out).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {len(nodes)} nodes; invalid files: {len(invalid)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
