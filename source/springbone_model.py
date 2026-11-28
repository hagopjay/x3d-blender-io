# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""SpringBoneChain and SpringBoneCollider (x3d.loom ``x3d.springbone``), read from and written to X3D XML. No bpy here.

The two PROTOs are declared in ``springbone/SpringBone.x3d`` (shipped with the add-on, MIT, own code) and used through
ExternProtoDeclare. Reading takes every ``ProtoInstance name='SpringBoneChain'`` outside a ProtoDeclare, its typed
``fieldValue``s (every field at the PROTO default when the file does not set it), and the DEF names its MFNode fields
point at (roots, ancestors, reference, exclusions; colliders resolved to their own fields and ancestors). Writing makes
the same text back from plain data. Nothing here runs code from the file.
"""

from __future__ import annotations

import json
from xml.sax.saxutils import quoteattr

# name -> (X3D type, default as Python value); the same table as x3d.springbone/tools/build.mjs
CHAIN_FIELDS = {
    "enabled": ("SFBool", True), "clock": ("SFBool", True),
    "roots": ("MFNode", None), "ancestors": ("MFNode", None), "reference": ("MFNode", None),
    "colliders": ("MFNode", None), "exclusions": ("MFNode", None), "boneTypes": ("MFString", ["HAnimJoint", "Transform"]),
    "updateRate": ("SFFloat", 60.0), "timeMode": ("SFString", "FIXED"), "maxSubsteps": ("SFInt32", 3),
    "interpolate": ("SFBool", False), "springModel": ("SFString", "POSITION"),
    "damping": ("SFFloat", 0.1), "elasticity": ("SFFloat", 0.1), "stiffness": ("SFFloat", 0.1), "inert": ("SFFloat", 0.0),
    "friction": ("SFFloat", 0.0), "radius": ("SFFloat", 0.0), "angleLimit": ("SFFloat", 0.0), "stretch": ("SFFloat", 0.0),
    "dampingCurve": ("MFVec2f", []), "elasticityCurve": ("MFVec2f", []), "stiffnessCurve": ("MFVec2f", []),
    "inertCurve": ("MFVec2f", []), "frictionCurve": ("MFVec2f", []), "radiusCurve": ("MFVec2f", []),
    "angleLimitCurve": ("MFVec2f", []), "stretchCurve": ("MFVec2f", []),
    "frequency": ("SFFloat", 0.0), "dampingRatio": ("SFFloat", 0.2),
    "endLength": ("SFFloat", 0.0), "endOffset": ("SFVec3f", [0.0, 0.0, 0.0]),
    "gravity": ("SFVec3f", [0.0, 0.0, 0.0]), "force": ("SFVec3f", [0.0, 0.0, 0.0]), "forceUnits": ("SFString", "PER_STEP"),
    "gravityRestCompensation": ("SFBool", True), "wind": ("SFVec3f", [0.0, 0.0, 0.0]), "windTurbulence": ("SFFloat", 0.0),
    "windFrequency": ("SFFloat", 1.0), "seed": ("SFInt32", 1), "freezeAxis": ("SFString", "NONE"),
    "branchMode": ("SFString", "SKIP"), "weight": ("SFFloat", 1.0), "resetDistance": ("SFFloat", 0.0),
    "substepRoots": ("SFBool", True),
}
CHAIN_OUTPUTS = {"stateHash": "SFString", "steps": "SFInt32", "droppedTime": "SFTime", "collided": "SFBool",
                 "positions": "MFVec3f", "equivalentFrequency": "SFFloat", "equivalentDampingRatio": "SFFloat"}
COLLIDER_FIELDS = {
    "enabled": ("SFBool", True), "shape": ("SFString", "SPHERE"), "bound": ("SFString", "OUTSIDE"),
    "center": ("SFVec3f", [0.0, 0.0, 0.0]), "radius": ("SFFloat", 0.5), "radius2": ("SFFloat", 0.0),
    "height": ("SFFloat", 0.0), "direction": ("SFString", "Y"), "axis": ("SFVec3f", [0.0, 0.0, 0.0]),
    "ancestors": ("MFNode", None),
}
NODE_LISTS = ("roots", "ancestors", "reference", "colliders", "exclusions")
LIBRARY = "SpringBone.x3d"
LIBRARY_ONLINE = "https://hagopjay.github.io/x3d.demo/demos/spring-bone/v1/x3d/SpringBone.x3d"


def _elements(el):
    return [c for c in el.childNodes if c.nodeType == c.ELEMENT_NODE]


def _floats(text):
    return [float(x) for x in text.replace(",", " ").split()]


def _mfstring(text):
    import shlex
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def parse_value(x3d_type, text):
    """One fieldValue's text as a Python value."""
    text = (text or "").strip()
    if x3d_type == "SFBool":
        return text.lower() == "true"
    if x3d_type in ("SFFloat", "SFTime"):
        return float(text)
    if x3d_type == "SFInt32":
        return int(float(text))
    if x3d_type == "SFString":
        return text[1:-1] if len(text) > 1 and text[0] == text[-1] == '"' else text
    if x3d_type == "SFVec3f":
        v = _floats(text)
        return (v + [0.0, 0.0, 0.0])[:3]
    if x3d_type == "MFVec2f":
        v = _floats(text)
        return [[v[i], v[i + 1]] for i in range(0, len(v) - 1, 2)]
    if x3d_type == "MFString":
        return _mfstring(text)
    return text


def format_value(x3d_type, value):
    def num(x):
        return repr(round(float(x), 9)).rstrip("0").rstrip(".") if float(x) != int(float(x)) else str(int(float(x)))
    if x3d_type == "SFBool":
        return "true" if value else "false"
    if x3d_type in ("SFFloat", "SFTime"):
        return num(value)
    if x3d_type == "SFInt32":
        return str(int(value))
    if x3d_type == "SFString":
        return str(value)
    if x3d_type == "SFVec3f":
        return " ".join(num(x) for x in value)
    if x3d_type == "MFVec2f":
        return " ".join(f"{num(a)} {num(b)}" for a, b in value)
    if x3d_type == "MFString":
        return " ".join(json.dumps(s) for s in value)
    return str(value)


def _node_refs(field_value):
    """DEF names that an MFNode fieldValue holds (USE or DEF), in order."""
    out = []
    for child in _elements(field_value):
        name = child.getAttribute("USE") or child.getAttribute("DEF")
        out.append(name or None)
    return out


def _defs(root):
    found = {}
    stack = [root]
    while stack:
        el = stack.pop()
        if el.tagName in ("ProtoDeclare", "ExternProtoDeclare"):
            continue
        d = el.getAttribute("DEF") if el.hasAttribute("DEF") else ""
        if d:
            found.setdefault(d, el)
        stack.extend(_elements(el))
    return found


def _read_fields(instance, table):
    values = {name: (list(d) if isinstance(d, list) else d) for name, (_t, d) in table.items() if d is not None}
    refs, set_names = {}, set()
    for fv in _elements(instance):
        if fv.tagName != "fieldValue":
            continue
        name = fv.getAttribute("name")
        if name not in table:
            continue
        x3d_type = table[name][0]
        set_names.add(name)
        if x3d_type == "MFNode":
            refs[name] = fv
        else:
            values[name] = parse_value(x3d_type, fv.getAttribute("value"))
    return values, refs, set_names


def read_springbones(root):
    """Every SpringBoneChain under ``root`` (a DOM element). Returns (chains, losses)."""
    defs = _defs(root)
    chains, losses = [], []
    stack = [root]
    found = []
    while stack:
        el = stack.pop()
        if el.tagName in ("ProtoDeclare", "ExternProtoDeclare"):
            continue
        if el.tagName == "ProtoInstance" and el.getAttribute("name") == "SpringBoneChain" and not el.hasAttribute("USE"):
            found.append(el)
        stack.extend(reversed(_elements(el)))
    for index, el in enumerate(found):
        name = el.getAttribute("DEF") or f"SpringBoneChain{index + 1}"
        params, refs, explicit = _read_fields(el, CHAIN_FIELDS)
        chain = {"name": name, "params": params, "explicit": sorted(explicit)}
        for list_name in NODE_LISTS:
            chain[list_name] = _node_refs(refs[list_name]) if list_name in refs else []
        colliders = []
        for ref in chain["colliders"]:
            target = defs.get(ref) if ref else None
            if target is None or target.tagName != "ProtoInstance" or target.getAttribute("name") != "SpringBoneCollider":
                losses.append((f"SpringBoneChain {name}", "colliders", f"{ref!r} is not a SpringBoneCollider this file defines"))
                continue
            cparams, crefs, _x = _read_fields(target, COLLIDER_FIELDS)
            cparams["name"] = ref
            cparams["ancestors"] = _node_refs(crefs["ancestors"]) if "ancestors" in crefs else []
            colliders.append(cparams)
        chain["colliders"] = colliders
        if None in chain["roots"]:
            losses.append((f"SpringBoneChain {name}", "roots", "a root without DEF or USE cannot be followed"))
        chains.append(chain)
    return chains, losses


def extern_declarations(url_list=(LIBRARY, LIBRARY_ONLINE), indent="  "):
    """ExternProtoDeclare text for both PROTOs (the XML encoding lists every field)."""
    def urls(proto):
        return " ".join(json.dumps(f"{u}#{proto}") for u in url_list)
    lines = [f"{indent}<ExternProtoDeclare name='SpringBoneCollider' url={quoteattr(urls('SpringBoneCollider'))}>"]
    lines += [f"{indent}  <field name='{n}' type='{t}' accessType='inputOutput'/>" for n, (t, _d) in COLLIDER_FIELDS.items()]
    lines.append(f"{indent}</ExternProtoDeclare>")
    lines.append(f"{indent}<ExternProtoDeclare name='SpringBoneChain' url={quoteattr(urls('SpringBoneChain'))}>")
    lines += [f"{indent}  <field name='{n}' type='{t}' accessType='inputOutput'/>" for n, (t, _d) in CHAIN_FIELDS.items()]
    lines += [f"{indent}  <field name='set_reset' type='SFBool' accessType='inputOnly'/>",
              f"{indent}  <field name='set_time' type='SFTime' accessType='inputOnly'/>"]
    lines += [f"{indent}  <field name='{n}' type='{t}' accessType='outputOnly'/>" for n, t in CHAIN_OUTPUTS.items()]
    lines.append(f"{indent}</ExternProtoDeclare>")
    return "\n".join(lines) + "\n"


def _uses(refs, indent):
    """refs: [(tag, DEF)] -> USE elements"""
    return "".join(f"{indent}  <{tag} USE={quoteattr(d)}/>\n" for tag, d in refs)


def collider_xml(def_name, params, ancestors, indent="  "):
    """ancestors: [(tag, DEF)] outermost first."""
    out = [f"{indent}<ProtoInstance name='SpringBoneCollider' DEF={quoteattr(def_name)}>\n"]
    for name, (x3d_type, default) in COLLIDER_FIELDS.items():
        if x3d_type == "MFNode" or name not in params or params[name] == default:
            continue
        out.append(f"{indent}  <fieldValue name='{name}' value={quoteattr(format_value(x3d_type, params[name]))}/>\n")
    out.append(f"{indent}  <fieldValue name='ancestors'>\n{_uses(ancestors, indent + '  ')}{indent}  </fieldValue>\n")
    out.append(f"{indent}</ProtoInstance>\n")
    return "".join(out)


def chain_xml(def_name, params, roots, ancestors, collider_defs=(), exclusions=(), indent="  "):
    """roots, ancestors, exclusions: [(tag, DEF)]; collider_defs: [DEF] of SpringBoneCollider instances."""
    out = [f"{indent}<ProtoInstance name='SpringBoneChain' DEF={quoteattr(def_name)}>\n"]
    out.append(f"{indent}  <fieldValue name='roots'>\n{_uses(roots, indent + '  ')}{indent}  </fieldValue>\n")
    out.append(f"{indent}  <fieldValue name='ancestors'>\n{_uses(ancestors, indent + '  ')}{indent}  </fieldValue>\n")
    if collider_defs:
        uses = "".join(f"{indent}    <ProtoInstance name='SpringBoneCollider' USE={quoteattr(d)}/>\n" for d in collider_defs)
        out.append(f"{indent}  <fieldValue name='colliders'>\n{uses}{indent}  </fieldValue>\n")
    if exclusions:
        out.append(f"{indent}  <fieldValue name='exclusions'>\n{_uses(exclusions, indent + '  ')}{indent}  </fieldValue>\n")
    for name, (x3d_type, default) in CHAIN_FIELDS.items():
        if x3d_type == "MFNode" or name not in params:
            continue
        if params[name] == default:
            continue
        out.append(f"{indent}  <fieldValue name='{name}' value={quoteattr(format_value(x3d_type, params[name]))}/>\n")
    out.append(f"{indent}</ProtoInstance>\n")
    return "".join(out)
