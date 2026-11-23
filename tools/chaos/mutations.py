"""Mutation operators for differential chaos testing (tools/chaos/differential.py).

Each operator takes the X3D text and a random.Random and returns (mutated_text, description) or None when it does
not apply to this file. One operator makes one change, so a finding names the one edit that caused it. Some mutants
stay valid X3D (reordering siblings, wrapping a node in a Transform, a legal extreme number); most do not. A judge
disagreement is interesting either way.
"""
from __future__ import annotations

import copy
import re
from xml.etree import ElementTree as ET

NUMERIC = re.compile(r"^[\s,+\-0-9.eE]+$")
EXTREMES = ["NaN", "INF", "-INF", "-0", "1e39", "-1e39", "3.4e38", "1e-45", "0", "-1", "2147483648", "-2147483649",
            "0x10", "1.", ".5", "+1", "1e", "--1"]
INDEX_ATTRS = ("coordIndex", "normalIndex", "colorIndex", "texCoordIndex", "index")
STRUCTURAL = {"X3D", "head", "Scene"}


def _parse(text: str):
    try:
        return ET.fromstring(text)
    except ET.ParseError:
        return None


def _dump(root) -> str:
    import sys
    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(limit, 20000))   # deep_nest writes 1,200 levels; ElementTree serialises recursively
    try:
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")
    finally:
        sys.setrecursionlimit(limit)


def _elements(root, skip_structural=True):
    return [e for e in root.iter() if not (skip_structural and e.tag in STRUCTURAL) and e.tag not in ("meta", "component")]


def _parents(root):
    return {child: parent for parent in root.iter() for child in parent}


def _path(e, parents) -> str:
    names = []
    while e is not None:
        names.append(e.get("DEF") and f"{e.tag}#{e.get('DEF')}" or e.tag)
        e = parents.get(e)
    return "/".join(reversed(names))


def attr_drop(text, rng):
    root = _parse(text)
    cands = [(e, a) for e in _elements(root) for a in e.attrib if a not in ("DEF",)]
    if not cands:
        return None
    e, a = rng.choice(cands)
    parents = _parents(root)
    del e.attrib[a]
    return _dump(root), f"removed {a} from {_path(e, parents)}"


def num_extreme(text, rng):
    root = _parse(text)
    cands = [(e, a) for e in _elements(root) for a, v in e.attrib.items() if NUMERIC.match(v) and a not in INDEX_ATTRS]
    if not cands:
        return None
    e, a = rng.choice(cands)
    tokens = e.get(a).replace(",", " ").split()
    i = rng.randrange(len(tokens))
    new = rng.choice(EXTREMES)
    old = tokens[i]
    tokens[i] = new
    parents = _parents(root)
    e.set(a, " ".join(tokens))
    return _dump(root), f"{_path(e, parents)} {a}: token {i} {old} -> {new}"


def mf_truncate(text, rng):
    root = _parse(text)
    cands = [(e, a) for e in _elements(root) for a, v in e.attrib.items() if NUMERIC.match(v) and len(v.split()) > 3]
    if not cands:
        return None
    e, a = rng.choice(cands)
    tokens = e.get(a).split()
    keep = rng.randrange(0, len(tokens))
    parents = _parents(root)
    e.set(a, " ".join(tokens[:keep]))
    return _dump(root), f"{_path(e, parents)} {a}: {len(tokens)} tokens -> {keep}"


def index_oob(text, rng):
    root = _parse(text)
    cands = [(e, a) for e in _elements(root) for a in e.attrib if a in INDEX_ATTRS and e.get(a).split()]
    if not cands:
        return None
    e, a = rng.choice(cands)
    tokens = e.get(a).split()
    i = rng.randrange(len(tokens))
    new = rng.choice(["-2", "999999", "2147483647", "-1", "-1 -1", "0 0 0 -1"])
    old = tokens[i]
    tokens[i] = new
    parents = _parents(root)
    e.set(a, " ".join(tokens))
    return _dump(root), f"{_path(e, parents)} {a}: token {i} {old} -> {new}"


def bool_spelling(text, rng):
    root = _parse(text)
    cands = [(e, a) for e in _elements(root) for a, v in e.attrib.items() if v in ("true", "false")]
    if not cands:
        return None
    e, a = rng.choice(cands)
    new = rng.choice(["TRUE", "FALSE", "1", "0", "yes", "", "true false"])
    parents = _parents(root)
    old = e.get(a)
    e.set(a, new)
    return _dump(root), f"{_path(e, parents)} {a}: {old} -> {new!r}"


def text_garbage(text, rng):
    root = _parse(text)
    cands = [(e, a) for e in _elements(root) for a in e.attrib if a not in ("DEF", "USE")]
    if not cands:
        return None
    e, a = rng.choice(cands)
    new = rng.choice(["", "abc", "1,,2", "1 2 3 4 5 6 7", '"unterminated', " ", "1;2", "&#0;"[:0] or "\t\n"])
    parents = _parents(root)
    e.set(a, new)
    return _dump(root), f"{_path(e, parents)} {a} -> {new!r}"


def dup_def(text, rng):
    root = _parse(text)
    defs = [e for e in _elements(root) if e.get("DEF")]
    others = [e for e in _elements(root) if not e.get("USE")]
    if not defs or len(others) < 2:
        return None
    src = rng.choice(defs)
    dst = rng.choice([e for e in others if e is not src])
    parents = _parents(root)
    dst.set("DEF", src.get("DEF"))
    return _dump(root), f"{_path(dst, parents)} given DEF {src.get('DEF')} (already on {src.tag})"


def use_dangling(text, rng):
    root = _parse(text)
    cands = [e for e in _elements(root) if e.get("DEF")]
    if not cands:
        return None
    e = rng.choice(cands)
    parents = _parents(root)
    where = _path(e, parents)
    for child in list(e):
        e.remove(child)
    e.attrib.clear()
    e.set("USE", rng.choice(["NoSuchNode", "", "has space"]))
    return _dump(root), f"{where} replaced by USE {e.get('USE')!r}"


def use_before_def(text, rng):
    root = _parse(text)
    parents = _parents(root)
    defs = [e for e in _elements(root) if e.get("DEF") and parents.get(e) is not None]
    if not defs:
        return None
    e = rng.choice(defs)
    parent = parents[e]
    use = ET.Element(e.tag, {"USE": e.get("DEF")})
    if e.get("containerField"):
        use.set("containerField", e.get("containerField"))
    parent.insert(list(parent).index(e), use)
    return _dump(root), f"USE of {e.get('DEF')} inserted before its DEF in {_path(parent, parents)}"


def use_wrong_type(text, rng):
    root = _parse(text)
    parents = _parents(root)
    defs = [e for e in _elements(root) if e.get("DEF")]
    targets = [e for e in _elements(root) if not e.get("USE") and parents.get(e) is not None]
    if not defs or not targets:
        return None
    d = rng.choice(defs)
    t = rng.choice([x for x in targets if x.tag != d.tag] or targets)
    parent = parents[t]
    use = ET.Element(t.tag, {"USE": d.get("DEF")})
    parent.insert(list(parent).index(t) + 1, use)
    return _dump(root), f"<{t.tag} USE={d.get('DEF')}> (a {d.tag}) added after {_path(t, parents)}"


def node_drop(text, rng):
    root = _parse(text)
    parents = _parents(root)
    cands = [e for e in _elements(root) if parents.get(e) is not None]
    if not cands:
        return None
    e = rng.choice(cands)
    where = _path(e, parents)
    parents[e].remove(e)
    return _dump(root), f"removed {where}"


def node_dup(text, rng):
    root = _parse(text)
    parents = _parents(root)
    cands = [e for e in _elements(root) if parents.get(e) is not None]
    if not cands:
        return None
    e = rng.choice(cands)
    parent = parents[e]
    twin = copy.deepcopy(e)
    if rng.random() < 0.5:
        for x in twin.iter():
            x.attrib.pop("DEF", None)
        what = "without DEFs"
    else:
        what = "with its DEFs (duplicates)"
    parent.insert(list(parent).index(e) + 1, twin)
    return _dump(root), f"duplicated {_path(e, parents)} {what}"


def child_swap(text, rng):
    root = _parse(text)
    cands = [e for e in root.iter() if len(e) >= 2]
    if not cands:
        return None
    parent = rng.choice(cands)
    i, j = rng.sample(range(len(parent)), 2)
    kids = list(parent)
    a, b = kids[i], kids[j]
    parent.remove(a)
    parent.remove(b)
    lo, hi = sorted((i, j))
    first, second = (b, a) if i < j else (a, b)
    parent.insert(lo, first)
    parent.insert(hi, second)
    parents = _parents(root)
    return _dump(root), f"swapped children {i} ({a.tag}) and {j} ({b.tag}) of {_path(parent, parents)}"


def container_field(text, rng):
    root = _parse(text)
    parents = _parents(root)
    cands = [e for e in _elements(root) if parents.get(e) is not None and parents[e].tag not in STRUCTURAL]
    if not cands:
        return None
    e = rng.choice(cands)
    new = rng.choice(["children", "geometry", "appearance", "material", "texture", "coord", "normal", "texCoord",
                      "color", "skin", "joints", "metadata", "proxy", "nonexistentField"])
    e.set("containerField", new)
    return _dump(root), f"{_path(e, parents)} containerField -> {new}"


def wrap_transform(text, rng):
    root = _parse(text)
    parents = _parents(root)
    cands = [e for e in _elements(root) if parents.get(e) is not None and parents[e].tag in ("Scene", "Transform", "Group")
             and e.tag not in ("ROUTE",)]
    if not cands:
        return None
    e = rng.choice(cands)
    parent = parents[e]
    scale = rng.choice(["0 0 0", "-1 1 1", "1e-30 1 1", "1 1 1"])
    wrap = ET.Element("Transform", {"scale": scale, "rotation": rng.choice(["0 0 0 0", "0 1 0 3.14159", "0 0 0 1"])})
    idx = list(parent).index(e)
    parent.remove(e)
    wrap.append(e)
    parent.insert(idx, wrap)
    return _dump(root), f"wrapped {_path(e, parents)} in Transform scale {scale} rotation {wrap.get('rotation')}"


def deep_nest(text, rng):
    root = _parse(text)
    scene = root.find("Scene")
    if scene is None or not len(scene):
        return None
    depth = rng.choice([50, 400, 1200])
    kids = list(scene)
    for k in kids:
        scene.remove(k)
    inner = scene
    for _ in range(depth):
        g = ET.SubElement(inner, "Group")
        inner = g
    for k in kids:
        inner.append(k)
    return _dump(root), f"scene content nested {depth} Groups deep"


def header_swap(text, rng):
    root = _parse(text)
    which = rng.choice(["version", "profile"])
    if which == "version":
        new = rng.choice(["3.0", "3.3", "4.1", "9.9", ""])
    else:
        new = rng.choice(["Core", "Interchange", "Full", "Bogus", ""])
    old = root.get(which)
    root.set(which, new)
    return _dump(root), f"X3D {which}: {old} -> {new!r}"


def def_unicode(text, rng):
    root = _parse(text)
    defs = [e for e in _elements(root) if e.get("DEF")]
    if not defs:
        return None
    e = rng.choice(defs)
    old = e.get("DEF")
    new = rng.choice(["Ժ_Armenian", "with space", "1leadingDigit", "a.b", "" , "x" * 300, "Ω'quote"])
    e.set("DEF", new)
    for u in root.iter():
        if u.get("USE") == old:
            u.set("USE", new)
    return _dump(root), f"DEF {old} -> {new!r} (USEs follow)"


def route_chaos(text, rng):
    root = _parse(text)
    scene = root.find("Scene")
    defs = [e.get("DEF") for e in _elements(root) if e.get("DEF")]
    if scene is None or not defs:
        return None
    routes = scene.findall("ROUTE")
    if routes and rng.random() < 0.6:
        r = rng.choice(routes)
        key = rng.choice(["fromNode", "fromField", "toNode", "toField"])
        new = rng.choice(defs + ["NoSuchNode", "set_fraction", "value_changed", "translation", "bogus_field"])
        old = r.get(key)
        r.set(key, new)
        return _dump(root), f"ROUTE {key}: {old} -> {new}"
    a, b = rng.choice(defs), rng.choice(defs)
    ET.SubElement(scene, "ROUTE", {"fromNode": a, "fromField": rng.choice(["value_changed", "translation_changed", "isActive"]),
                                   "toNode": b, "toField": rng.choice(["set_translation", "set_fraction", "set_scale"])})
    return _dump(root), f"ROUTE added {a} -> {b}"


OPERATORS = [attr_drop, num_extreme, mf_truncate, index_oob, bool_spelling, text_garbage, dup_def, use_dangling,
             use_before_def, use_wrong_type, node_drop, node_dup, child_swap, container_field, wrap_transform, deep_nest,
             header_swap, def_unicode, route_chaos]
