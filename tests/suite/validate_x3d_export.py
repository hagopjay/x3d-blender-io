#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
validate_x3d_export.py  -  judge an exported .x3d against the test-suite manifest
==================================================================================

Pure standard library (Python >= 3.9).  No Blender, no third-party packages.

    python validate_x3d_export.py OUT_DIR                    # uses OUT_DIR/x3d_suite_manifest.json
    python validate_x3d_export.py OUT_DIR --html report.html --json report.json --md report.md
    python validate_x3d_export.py OUT_DIR --only Z04,Z11 --tier CORE --verbose
    python validate_x3d_export.py OUT_DIR --profile main=/path/to/other.x3d
    python validate_x3d_export.py --selftest

VERDICTS
    PASS      every check of the case holds
    FAIL      a CORE case failed                      -> exporter bug / regression   (exit code 1)
    WARN      a FIDELITY case failed                  -> known approximation, reported only
    MISSING   a ROADMAP case failed                   -> feature not implemented yet (expected)
    NEW       a ROADMAP case passed                   -> somebody implemented it: celebrate, then promote it to CORE
    SKIP      the profile's file is missing, or the case needs something this Blender build lacks
    ERROR     the validator itself raised (a bug in THIS file, please report)
"""
from __future__ import annotations

import argparse
import html as _html
import json
import math
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import OrderedDict

VERSION = "2.0.0"

# --------------------------------------------------------------------------------------
# small linear-algebra kit (row-major 4x4 as list of 16 floats, column-vector convention)
# --------------------------------------------------------------------------------------


def m_ident():
    return [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def m_mul(a, b):
    return [sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4)) for r in range(4) for c in range(4)]


def m_apply(m, p):
    x, y, z = p[0], p[1], p[2]
    return (m[0] * x + m[1] * y + m[2] * z + m[3], m[4] * x + m[5] * y + m[6] * z + m[7], m[8] * x + m[9] * y + m[10] * z + m[11])


def m_apply_dir(m, v):
    x, y, z = v[0], v[1], v[2]
    return (m[0] * x + m[1] * y + m[2] * z, m[4] * x + m[5] * y + m[6] * z, m[8] * x + m[9] * y + m[10] * z)


def m_translate(t):
    m = m_ident(); m[3], m[7], m[11] = t[0], t[1], t[2]; return m


def m_scale(s):
    m = m_ident(); m[0], m[5], m[10] = s[0], s[1], s[2]; return m


def m_axis_angle(axis, angle):
    x, y, z = axis
    n = math.sqrt(x * x + y * y + z * z)
    if n < 1e-12 or abs(angle) < 1e-15:
        return m_ident()
    x, y, z = x / n, y / n, z / n
    c, s, t = math.cos(angle), math.sin(angle), 1 - math.cos(angle)
    return [t * x * x + c, t * x * y - s * z, t * x * z + s * y, 0,
            t * x * y + s * z, t * y * y + c, t * y * z - s * x, 0,
            t * x * z - s * y, t * y * z + s * x, t * z * z + c, 0, 0, 0, 0, 1.0]


def trs_matrix(t=(0, 0, 0), r=(0, 0, 1, 0), s=(1, 1, 1), center=(0, 0, 0)):
    """X3D Transform: T * C * R * SR * S * -SR * -C   (scaleOrientation not used by the exporter)."""
    m = m_translate(t)
    if any(center):
        m = m_mul(m, m_translate(center))
    m = m_mul(m, m_axis_angle(r[:3], r[3]))
    m = m_mul(m, m_scale(s))
    if any(center):
        m = m_mul(m, m_translate((-center[0], -center[1], -center[2])))
    return m


def aa_to_quat(a):
    x, y, z, ang = a
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    s = math.sin(ang / 2) / n
    return (x * s, y * s, z * s, math.cos(ang / 2))


def quat_to_aa(q):
    x, y, z, w = q
    w = max(-1.0, min(1.0, w))
    ang = 2 * math.acos(w)
    s = math.sqrt(max(0.0, 1 - w * w))
    if s < 1e-9:
        return (0.0, 0.0, 1.0, 0.0)
    return (x / s, y / s, z / s, ang)


def slerp(q0, q1, t):
    d = sum(a * b for a, b in zip(q0, q1))
    if d < 0:
        q1 = tuple(-c for c in q1); d = -d
    if d > 0.9995:
        q = tuple(a + t * (b - a) for a, b in zip(q0, q1))
        n = math.sqrt(sum(c * c for c in q)) or 1.0
        return tuple(c / n for c in q)
    th = math.acos(max(-1.0, min(1.0, d)))
    s0, s1 = math.sin((1 - t) * th) / math.sin(th), math.sin(t * th) / math.sin(th)
    return tuple(s0 * a + s1 * b for a, b in zip(q0, q1))


def m_close(a, b, tol):
    worst = 0.0
    for x, y in zip(a, b):
        worst = max(worst, abs(x - y) / max(1.0, abs(y)))
    return worst <= tol, worst


def v_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def v_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def v_cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def v_len(a):
    return math.sqrt(v_dot(a, a))


def safe_name(name: str, fallback: str = "Node") -> str:
    out = []
    for i, ch in enumerate(name or fallback):
        out.append(ch if (ch.isalnum() or ch == "_") else "_")
        if i == 0 and out[-1].isdigit():
            out[-1] = "_"
    return "".join(out) or fallback


# --------------------------------------------------------------------------------------
# X3D document model
# --------------------------------------------------------------------------------------

_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|nan|inf", re.I)


def floats(text):
    if text is None:
        return []
    return [float(t) for t in _NUM.findall(text)]


def mfstring(text):
    return re.findall(r'"((?:[^"\\]|\\.)*)"', text or "")


class Doc:
    def __init__(self, path):
        self.path = path
        self.dir = os.path.dirname(os.path.abspath(path))
        self.text = open(path, encoding="utf-8").read()
        self.tree = ET.parse(path)
        self.root = self.tree.getroot()
        self.scene = self.root.find("Scene")
        self.head = self.root.find("head")
        self.parent = {}
        self.order = {}
        self.defs = OrderedDict()
        self.dup_defs = []
        for i, el in enumerate(self.root.iter()):
            self.order[el] = i
            for ch in el:
                self.parent[ch] = el
            d = el.get("DEF")
            if d is not None:
                if d in self.defs:
                    self.dup_defs.append(d)
                self.defs.setdefault(d, el)
        self.infos = [m.get("content", "") for m in (self.head.findall("meta") if self.head is not None else []) if m.get("name") == "info"]
        self.routes = [r for r in self.root.iter("ROUTE")]
        self._anim = None

    # -- resolution ---------------------------------------------------------------
    def res(self, el):
        if el is None:
            return None
        u = el.get("USE")
        return self.defs.get(u, el) if u else el

    def obj_transform(self, name):
        d = "OB_" + safe_name(name)
        el = self.defs.get(d)
        if el is not None:
            return el
        key = safe_name(name)
        for k, v in self.defs.items():
            if v.tag == "Transform" and (k == key or k.endswith("_" + key)):
                return v
        return None

    def shapes(self, tr):
        return [c for c in tr if c.tag == "Shape"] if tr is not None else []

    def appearance(self, shape):
        return self.res(shape.find("Appearance")) if shape is not None else None

    def material(self, shape):
        app = self.appearance(shape)
        if app is None:
            return None
        for tag in ("PhysicalMaterial", "UnlitMaterial", "Material"):
            m = app.find(tag)
            if m is not None:
                return self.res(m)
        return None

    def geometry(self, shape):
        if shape is None:
            return None
        for ch in shape:
            if ch.tag in ("IndexedFaceSet", "IndexedTriangleSet", "PointSet", "IndexedLineSet"):
                return self.res(ch)
        return None

    # -- transforms ---------------------------------------------------------------
    def local_matrix(self, el, fraction=None):
        t = floats(el.get("translation")) or [0, 0, 0]
        r = floats(el.get("rotation")) or [0, 0, 1, 0]
        s = floats(el.get("scale")) or [1, 1, 1]
        c = floats(el.get("center")) or [0, 0, 0]
        if fraction is not None:
            anim = self.anim_map().get(el.get("DEF"))
            if anim:
                if "set_translation" in anim:
                    t = interp(anim["set_translation"], fraction, 3) or t
                if "set_rotation" in anim:
                    r = interp(anim["set_rotation"], fraction, 4, rotation=True) or r
                if "set_scale" in anim:
                    s = interp(anim["set_scale"], fraction, 3) or s
        return trs_matrix(t, r, s, c)

    def world_matrix(self, el, fraction=None):
        chain = []
        cur = el
        while cur is not None:
            if cur.tag in ("Transform", "HAnimHumanoid", "HAnimJoint", "HAnimSite", "Group") and cur.tag != "Group":
                chain.append(cur)
            cur = self.parent.get(cur)
        m = m_ident()
        for node in reversed(chain):
            m = m_mul(m, self.local_matrix(node, fraction))
        return m

    # -- animation wiring ---------------------------------------------------------
    def anim_map(self):
        """{target DEF: {field: interpolator element}}"""
        if self._anim is None:
            self._anim = {}
            for r in self.routes:
                src, sf, dst, df = r.get("fromNode"), r.get("fromField"), r.get("toNode"), r.get("toField")
                if sf == "value_changed" and df in ("set_translation", "set_rotation", "set_scale") and src in self.defs:
                    self._anim.setdefault(dst, {})[df] = self.defs[src]
        return self._anim


def interp(node, fraction, width, rotation=False):
    keys = floats(node.get("key"))
    vals = floats(node.get("keyValue"))
    if not keys or len(vals) < len(keys) * width:
        return None
    pts = [vals[i * width:(i + 1) * width] for i in range(len(keys))]
    if fraction <= keys[0]:
        return pts[0]
    if fraction >= keys[-1]:
        return pts[-1]
    lo, hi = 0, len(keys) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if keys[mid] <= fraction:
            lo = mid
        else:
            hi = mid
    span = keys[hi] - keys[lo]
    t = 0.0 if span <= 0 else (fraction - keys[lo]) / span
    if rotation:
        q = slerp(aa_to_quat(pts[lo]), aa_to_quat(pts[hi]), t)
        return list(quat_to_aa(q))
    return [a + t * (b - a) for a, b in zip(pts[lo], pts[hi])]


# --------------------------------------------------------------------------------------
# check result helpers
# --------------------------------------------------------------------------------------


class R:
    """Result of one check: ok flag + human-readable message (+ optional observed value)."""

    def __init__(self, ok, msg, obs=None):
        self.ok, self.msg, self.obs = bool(ok), msg, obs

    def __repr__(self):
        return f"{'ok' if self.ok else 'FAIL'}: {self.msg}"


def ok(msg="ok", obs=None):
    return R(True, msg, obs)


def bad(msg, obs=None):
    return R(False, msg, obs)


def fnum(x, nd=6):
    if isinstance(x, (list, tuple)):
        return "[" + ", ".join(fnum(v, nd) for v in x) + "]"
    if isinstance(x, float):
        return f"{x:.{nd}g}"
    return str(x)


X3D_DEFAULTS = {
    "PhysicalMaterial": {"baseColor": [1, 1, 1], "metallic": 1.0, "roughness": 1.0, "emissiveColor": [0, 0, 0],
                         "transparency": 0.0, "normalScale": 1.0, "occlusionStrength": 1.0},
    "UnlitMaterial": {"emissiveColor": [1, 1, 1], "transparency": 0.0, "normalScale": 1.0},
    "DirectionalLight": {"color": [1, 1, 1], "intensity": 1.0, "ambientIntensity": 0.0, "direction": [0, 0, -1], "global": "false"},
    "PointLight": {"color": [1, 1, 1], "intensity": 1.0, "ambientIntensity": 0.0, "location": [0, 0, 0], "radius": 100.0, "global": "true"},
    "SpotLight": {"color": [1, 1, 1], "intensity": 1.0, "ambientIntensity": 0.0, "location": [0, 0, 0], "direction": [0, 0, -1],
                  "radius": 100.0, "beamWidth": 0.7854, "cutOffAngle": 1.5708, "global": "true"},
    "Viewpoint": {"position": [0, 0, 10], "orientation": [0, 0, 1, 0], "fieldOfView": 0.7854},
}


def attr_value(el, name, tag=None):
    """Attribute as float list / float / str, falling back to the X3D default.  Returns (value, was_default)."""
    raw = el.get(name)
    if raw is None:
        d = X3D_DEFAULTS.get(tag or el.tag, {}).get(name)
        return d, True
    if name in ("global", "solid", "loop", "alphaMode", "description", "name", "url", "type"):
        return raw, False
    f = floats(raw)
    if len(f) == 1:
        return f[0], False
    return f, False


def compare_value(got, exp, tol):
    if isinstance(exp, str):
        return str(got) == exp
    if isinstance(exp, (int, float)) and not isinstance(exp, bool):
        return isinstance(got, (int, float)) and abs(got - exp) <= tol * max(1.0, abs(exp))
    if isinstance(exp, (list, tuple)):
        return isinstance(got, (list, tuple)) and len(got) == len(exp) and all(abs(a - b) <= tol * max(1.0, abs(b)) for a, b in zip(got, exp))
    return got == exp


def ifs_data(doc, geo):
    """Parsed arrays of an IndexedFaceSet (resolving USE)."""
    g = doc.res(geo)
    if g is None:
        return None
    ci = [int(v) for v in floats(g.get("coordIndex"))]
    coord_el = g.find("Coordinate")
    coord_el = doc.res(coord_el) if coord_el is not None else None
    pts = floats(coord_el.get("point")) if coord_el is not None else []
    P = [tuple(pts[i:i + 3]) for i in range(0, len(pts) - 2, 3)]
    faces, cur = [], []
    for i in ci:
        if i < 0:
            if cur:
                faces.append(cur)
            cur = []
        else:
            cur.append(i)
    if cur:
        faces.append(cur)
    return {"el": g, "P": P, "faces": faces, "ci": ci, "coord_el": coord_el}


def newell(P, face):
    nx = ny = nz = 0.0
    for i in range(len(face)):
        a, b = P[face[i]], P[face[(i + 1) % len(face)]]
        nx += (a[1] - b[1]) * (a[2] + b[2]); ny += (a[2] - b[2]) * (a[0] + b[0]); nz += (a[0] - b[0]) * (a[1] + b[1])
    return (nx, ny, nz)


# --------------------------------------------------------------------------------------
# CHECK IMPLEMENTATIONS   (each:  fn(ck, doc, env) -> R)
# --------------------------------------------------------------------------------------

CHECKS = {}


def check(name):
    def deco(fn):
        CHECKS[name] = fn
        return fn
    return deco


class Env:
    def __init__(self, manifest, profile, out_dir):
        self.m = manifest
        self.profile = profile
        self.out_dir = out_dir
        self.prof_opts = manifest.get("profiles", {}).get(profile, {}).get("export", {})

    @property
    def triangulated(self):
        return bool(self.prof_opts.get("use_triangulate"))

    def obj(self, name):
        return self.m["objects"].get(name)


def _tr(doc, ck):
    tr = doc.obj_transform(ck["obj"])
    return tr


def _need_tr(doc, ck):
    tr = _tr(doc, ck)
    if tr is None:
        return None, bad(f"no <Transform> for object '{ck['obj']}' (looked for DEF 'OB_{safe_name(ck['obj'])}')")
    return tr, None


def _shape(doc, tr, idx=0):
    sh = doc.shapes(tr)
    return sh[idx] if idx < len(sh) else None


# -- document-level ------------------------------------------------------------------

@check("doc")
def c_doc(ck, doc, env):
    msgs = []
    if "version" in ck and doc.root.get("version") != ck["version"]:
        msgs.append(f"version={doc.root.get('version')} (want {ck['version']})")
    if "profile" in ck and doc.root.get("profile") != ck["profile"]:
        msgs.append(f"profile={doc.root.get('profile')} (want {ck['profile']})")
    if "doctype" in ck and ck["doctype"] not in doc.text[:600]:
        msgs.append(f"DOCTYPE lacks '{ck['doctype']}'")
    return bad("; ".join(msgs)) if msgs else ok(f"X3D {doc.root.get('version')} / {doc.root.get('profile')}")


@check("component")
def c_component(ck, doc, env):
    comps = [(c.get("name"), int(c.get("level", "0"))) for c in (doc.head.findall("component") if doc.head is not None else [])]
    for n, l in comps:
        if n == ck["name"] and l >= ck["level"]:
            return ok(f"component {n} level {l}")
    return bad(f"component {ck['name']} level >= {ck['level']} not declared (have {comps})")


@check("meta")
def c_meta(ck, doc, env):
    for m in doc.head.findall("meta") if doc.head is not None else []:
        if m.get("name") == ck["name"] and ck.get("contains", "") in m.get("content", ""):
            return ok(f"meta {ck['name']}={m.get('content')!r}")
    return bad(f"<meta name='{ck['name']}'> missing")


@check("diag")
def c_diag(ck, doc, env):
    hit = [i for i in doc.infos if ck["contains"] in i]
    if ck.get("absent"):
        return bad(f"unexpected diagnostic: {hit[0]!r}") if hit else ok("no such diagnostic")
    return ok(hit[0]) if hit else bad(f"no <meta name='info'> containing {ck['contains']!r}")


@check("navinfo")
def c_navinfo(ck, doc, env):
    n = doc.scene.find("NavigationInfo")
    if n is None:
        return bad("no NavigationInfo")
    msgs = []
    if "headlight" in ck and (n.get("headlight", "true") == "true") != ck["headlight"]:
        msgs.append(f"headlight={n.get('headlight', 'true')}")
    if "type_has" in ck and ck["type_has"] not in (n.get("type") or "EXAMINE"):
        msgs.append(f"type={n.get('type')}")
    return bad("; ".join(msgs)) if msgs else ok(f"headlight={n.get('headlight')} type={n.get('type')}")


@check("background")
def c_background(ck, doc, env):
    b = doc.scene.find("Background")
    if b is None:
        return bad("no <Background>")
    got = floats(b.get("skyColor"))
    good = len(got) >= 3 and all(abs(a - e) <= ck.get("tol", 1e-4) for a, e in zip(got, ck["sky"]))
    return (ok if good else bad)(f"skyColor={fnum(got)} (want {fnum(ck['sky'])})")


# -- transforms ----------------------------------------------------------------------

@check("xf")
def c_xf(ck, doc, env):
    tr, err = _need_tr(doc, ck)
    if err:
        return err
    exp = env.obj(ck["obj"])
    if exp is None:
        return bad(f"object '{ck['obj']}' missing from manifest")
    got = doc.world_matrix(tr)
    good, worst = m_close(got, exp["world"], ck.get("tol", 2e-4))
    if good:
        return ok(f"world matrix matches (max dev {worst:.1e})")
    return bad(f"world matrix differs (max dev {worst:.2e}); got translation {fnum(got[3::4][:3])} want {fnum(exp['world'][3::4][:3])}")


@check("shapes")
def c_shapes(ck, doc, env):
    tr, err = _need_tr(doc, ck)
    if err:
        return err
    ignore = set(ck.get("ignore_geometry", ()))
    shapes = [sh for sh in doc.shapes(tr) if not ignore or getattr(doc.geometry(sh), "tag", None) not in ignore]
    n = len(shapes)
    note = f" (ignoring {', '.join(sorted(ignore))})" if ignore else ""
    return (ok if n == ck["n"] else bad)(f"{n} <Shape> child(ren){note} (want {ck['n']})")


@check("parent")
def c_parent(ck, doc, env):
    tr, err = _need_tr(doc, ck)
    if err:
        return err
    p = doc.parent.get(tr)
    if ck.get("parent") is None:
        return (ok if p is doc.scene else bad)(f"parent is <{p.tag if p is not None else None}>" + ("" if p is doc.scene else " (want top level)"))
    want = doc.obj_transform(ck["parent"])
    return (ok if (p is want and want is not None) else bad)(
        f"parent DEF={p.get('DEF') if p is not None else None} (want {want.get('DEF') if want is not None else ck['parent']})")


# -- mesh ----------------------------------------------------------------------------

def _gather_mesh(doc, tr):
    P_all, nfaces, area, faces_out = [], 0, 0.0, []
    for sh in doc.shapes(tr):
        d = ifs_data(doc, doc.geometry(sh))
        if d is None:
            continue
        for f in d["faces"]:
            if any(i >= len(d["P"]) for i in f):
                continue
            pts = [d["P"][i] for i in f]
            P_all.extend(pts)
            nfaces += 1
            n = newell(d["P"], f)
            area += 0.5 * v_len(n)
            faces_out.append((f, d["P"]))
    return P_all, nfaces, area, faces_out


@check("mesh")
def c_mesh(ck, doc, env):
    tr, err = _need_tr(doc, {"obj": ck["facts"]["obj"]})
    if err:
        return err
    f = ck["facts"]
    P, nfaces, area, faces = _gather_mesh(doc, tr)
    msgs, notes = [], []
    want_faces = f.get("faces")
    if ck.get("faces_eq") == "tris" or (env.triangulated and "tris" in f):
        want_faces = f["tris"]
    if "faces_min" in f:
        if nfaces < f["faces_min"]:
            msgs.append(f"{nfaces} faces (want >= {f['faces_min']})")
    elif want_faces is not None and nfaces != want_faces:
        msgs.append(f"{nfaces} faces (want {want_faces})")
    notes.append(f"{nfaces} faces")
    if "positions" in f and not f.get("rel"):
        got = len({tuple(round(c, 4) for c in p) for p in P})
        if got != f["positions"]:
            msgs.append(f"{got} distinct vertex positions (want {f['positions']})")
    if f.get("bbox") and P:
        lo = [min(p[i] for p in P) for i in range(3)]; hi = [max(p[i] for p in P) for i in range(3)]
        elo, ehi = f["bbox"]
        if f.get("rel"):
            for i in range(3):
                span_e, span_g = ehi[i] - elo[i], hi[i] - lo[i]
                if span_e > 0 and abs(span_g - span_e) > 0.05 * span_e:
                    msgs.append(f"bbox span[{i}]={span_g:.3g} (want {span_e:.3g}, >5% off)")
                    break
        else:
            tol = 1e-4 + 1e-6 * max(abs(v) for v in elo + ehi)
            if any(abs(a - b) > tol for a, b in zip(lo + hi, elo + ehi)):
                msgs.append(f"bbox {fnum(lo)}..{fnum(hi)} (want {fnum(elo)}..{fnum(ehi)})")
    elif f.get("bbox") and not P:
        msgs.append("no geometry")
    if "area" in f and nfaces and not f.get("rel"):
        if abs(area - f["area"]) > 1e-3 * max(1e-6, f["area"]) + 1e-5:
            msgs.append(f"surface area {area:.5g} (want {f['area']:.5g})")
        else:
            notes.append("area ok")
    if f.get("convex") and faces:
        cen = [sum(p[i] for p in {tuple(q) for q in P}) / max(1, len({tuple(q) for q in P})) for i in range(3)]
        wrong = 0
        for face, pts in faces:
            n = newell(pts, face)
            if v_len(n) < 1e-12:
                continue
            fc = [sum(pts[i][k] for i in face) / len(face) for k in range(3)]
            d = v_dot(n, v_sub(fc, cen))
            if (d < 0) != bool(f.get("inward")):
                wrong += 1
        if wrong:
            msgs.append(f"{wrong}/{len(faces)} faces wound the wrong way ({'inward' if f.get('inward') else 'outward'} expected)")
        else:
            notes.append("winding ok")
    # texture / colour presence follows the Blender data
    sh = _shape(doc, tr)
    if sh is not None and "has_uv" in f:
        d = ifs_data(doc, doc.geometry(sh))
        has = d is not None and d["el"].find("TextureCoordinate") is not None
        if has != f["has_uv"]:
            msgs.append(f"TextureCoordinate {'present' if has else 'absent'} but Blender mesh {'has' if f['has_uv'] else 'has no'} active UVs")
        has = d is not None and (d["el"].find("ColorRGBA") is not None or d["el"].find("Color") is not None)
        if f.get("has_color") is not None and has != f["has_color"]:
            msgs.append(f"vertex colours {'present' if has else 'absent'} but Blender mesh {'has' if f['has_color'] else 'has no'} an active colour attribute")
    return bad("; ".join(msgs)) if msgs else ok(", ".join(notes))


def _ifs(doc, ck):
    tr, err = _need_tr(doc, ck)
    if err:
        return None, err
    sh = _shape(doc, tr, ck.get("shape", 0))
    if sh is None:
        return None, bad(f"object '{ck['obj']}' has no Shape #{ck.get('shape', 0)}")
    d = ifs_data(doc, doc.geometry(sh))
    if d is None:
        return None, bad("no geometry node")
    return d, None


NODE_FIELD = {"TextureCoordinate": ("point", 2), "Normal": ("vector", 3), "ColorRGBA": ("color", 4), "Color": ("color", 3)}


@check("geo_attr")
def c_geo_attr(ck, doc, env):
    d, err = _ifs(doc, ck)
    if err:
        return err
    el, a = d["el"], ck["attr"]
    raw = el.get(a)
    if ck.get("absent"):
        return (ok if raw is None else bad)(f"{a}={raw!r}" if raw is not None else f"{a} absent (default)")
    if raw is None:
        return bad(f"{a} absent")
    if "equals" in ck:
        return (ok if raw == ck["equals"] else bad)(f"{a}={raw!r} (want {ck['equals']!r})")
    if "approx" in ck:
        v = floats(raw)
        return (ok if v and abs(v[0] - ck["approx"]) <= ck.get("tol", 1e-4) else bad)(f"{a}={raw} (want {ck['approx']:.6f})")
    return ok(f"{a}={raw}")


@check("geo_node")
def c_geo_node(ck, doc, env):
    d, err = _ifs(doc, ck)
    if err:
        return err
    node = d["el"].find(ck["node"])
    if not ck.get("present", True):
        return (ok if node is None else bad)(f"<{ck['node']}> " + ("absent" if node is None else "present"))
    if node is None:
        return bad(f"<{ck['node']}> absent")
    field, width = NODE_FIELD[ck["node"]]
    n = len(floats(node.get(field))) // width
    if ck.get("count") == "coord" and n != len(d["P"]):
        return bad(f"{n} {ck['node']} entries but {len(d['P'])} Coordinates")
    return ok(f"{n} entries")


@check("geo_more_coords")
def c_more_coords(ck, doc, env):
    d, err = _ifs(doc, ck)
    if err:
        return err
    used = {tuple(round(c, 4) for c in d["P"][i]) for f in d["faces"] for i in f}
    n = len(d["P"])
    if n <= len(used):
        return bad(f"{n} Coordinates for {len(used)} distinct positions (no vertex splitting)")
    if n < ck.get("min_coords", 0):
        return bad(f"{n} Coordinates (want >= {ck['min_coords']})")
    return ok(f"{n} Coordinates for {len(used)} positions")


@check("value_set")
def c_value_set(ck, doc, env):
    d, err = _ifs(doc, ck)
    if err:
        return err
    node = d["el"].find(ck["node"])
    if node is None:
        return bad(f"<{ck['node']}> absent")
    w = ck["width"]
    vals = floats(node.get(ck["field"]))
    vecs = [tuple(vals[i:i + w]) for i in range(0, len(vals) - w + 1, w)]
    tol = ck.get("tol", 1e-4)
    miss = [c for c in ck.get("contains", []) if not any(all(abs(a - b) <= tol for a, b in zip(v, c)) for v in vecs)]
    extra = [c for c in ck.get("excludes", []) if any(all(abs(a - b) <= tol for a, b in zip(v, c)) for v in vecs)]
    msgs = []
    if miss:
        msgs.append(f"missing {fnum(miss)}")
    if extra:
        msgs.append(f"unexpected {fnum(extra)}")
    return bad("; ".join(msgs) + f" among {len(vecs)} values") if msgs else ok(f"{len(vecs)} values, all expected present")


@check("normals")
def c_normals(ck, doc, env):
    d, err = _ifs(doc, ck)
    if err:
        return err
    node = d["el"].find("Normal")
    if node is None:
        return bad("<Normal> absent")
    vals = floats(node.get("vector"))
    N = [tuple(vals[i:i + 3]) for i in range(0, len(vals) - 2, 3)]
    P = d["P"]
    if len(N) != len(P):
        return bad(f"{len(N)} normals for {len(P)} points")
    msgs = []
    if ck.get("unit") and any(abs(v_len(n) - 1) > 2e-3 for n in N):
        msgs.append("non-unit normals")
    if ck.get("axis_aligned") and any(max(abs(c) for c in n) < 0.998 for n in N):
        msgs.append("normals not axis-aligned")
    if ck.get("radial"):
        worst = min(v_dot(n, p) / (v_len(p) or 1) for n, p in zip(N, P) if v_len(p) > 1e-6)
        if worst < 0.97:
            msgs.append(f"normals not radial (min cos {worst:.3f})")
    if "all_equal" in ck:
        e = ck["all_equal"]
        if any(max(abs(a - b) for a, b in zip(n, e)) > 2e-3 for n in N):
            msgs.append(f"normals not all equal to {fnum(e)}")
    if ck.get("hard_edge"):
        used = {tuple(round(c, 4) for c in P[i]) for f in d["faces"] for i in f}
        if len(P) <= len(used):
            msgs.append("no vertex split along the hard edge")
    return bad("; ".join(msgs)) if msgs else ok(f"{len(N)} normals")


# -- materials -----------------------------------------------------------------------

@check("mat")
def c_mat(ck, doc, env):
    tr, err = _need_tr(doc, ck)
    if err:
        return err
    sh = _shape(doc, tr, ck.get("shape", 0))
    mat = doc.material(sh)
    if mat is None:
        return bad("no material element")
    msgs, notes = [], []
    if "tag" in ck and mat.tag != ck["tag"]:
        msgs.append(f"<{mat.tag}> (want <{ck['tag']}>)")
    tol = ck.get("tol", 1e-4)
    for name, exp in ck.get("attrs", {}).items():
        val, was_default = attr_value(mat, name)
        if val is None:
            msgs.append(f"{name} absent")
            continue
        if not compare_value(val, exp, tol):
            msgs.append(f"{name}={fnum(val)}{' (X3D default)' if was_default else ''} want {fnum(exp)}")
        else:
            notes.append(f"{name}={fnum(val)}")
    for name in ck.get("absent", []):
        if mat.get(name) is not None:
            msgs.append(f"{name}='{mat.get(name)}' should be absent")
    for name in ck.get("present", []):
        if mat.get(name) is None:
            msgs.append(f"{name} not written (X3D default {X3D_DEFAULTS.get(mat.tag, {}).get(name)} applies)")
    return bad("; ".join(msgs)) if msgs else ok(", ".join(notes) or f"<{mat.tag}>")


@check("app")
def c_app(ck, doc, env):
    tr, err = _need_tr(doc, ck)
    if err:
        return err
    app = doc.appearance(_shape(doc, tr, ck.get("shape", 0)))
    if app is None:
        return bad("no Appearance")
    got = app.get("alphaMode")
    return (ok if got == ck.get("alphaMode") else bad)(f"alphaMode={got!r} (want {ck.get('alphaMode')!r})")


@check("tex")
def c_tex(ck, doc, env):
    tr, err = _need_tr(doc, ck)
    if err:
        return err
    mat = doc.material(_shape(doc, tr, ck.get("shape", 0)))
    if mat is None:
        return bad("no material")
    tex = None
    for ch in mat:
        if ch.get("containerField") == ck["field"]:
            tex = doc.res(ch)
    if ck.get("absent"):
        return (ok if tex is None else bad)(f"no {ck['field']}" if tex is None else f"unexpected {ck['field']}: {tex.get('url')}")
    if tex is None:
        return bad(f"no <ImageTexture containerField='{ck['field']}'>")
    urls = mfstring(tex.get("url"))
    url = urls[0] if urls else ""
    msgs = []
    if not url:
        return bad("empty url")
    low = url.lower()
    if "name_has" in ck and ck["name_has"].lower() not in low:
        msgs.append(f"url {url!r} lacks {ck['name_has']!r}")
    if "ext" in ck and not low.endswith(ck["ext"]):
        msgs.append(f"url {url!r} does not end with {ck['ext']}")
    if "ext_in" in ck and os.path.splitext(low)[1] not in ck["ext_in"]:
        msgs.append(f"{os.path.splitext(low)[1]} is not browser-decodable (want one of {ck['ext_in']})")
    if ck.get("exists"):
        p = os.path.join(doc.dir, url)
        if not os.path.exists(p):
            msgs.append(f"file {url!r} not found next to the .x3d")
    if "repeat" in ck:
        rs, rt = tex.get("repeatS", "true") == "true", tex.get("repeatT", "true") == "true"
        if not (rs == rt == ck["repeat"]):
            msgs.append(f"repeatS={rs} repeatT={rt} (want {ck['repeat']})")
    return bad("; ".join(msgs)) if msgs else ok(f"url={url}")


@check("ttf")
def c_ttf(ck, doc, env):
    tr, err = _need_tr(doc, ck)
    if err:
        return err
    app = doc.appearance(_shape(doc, tr, ck.get("shape", 0)))
    t = app.find("TextureTransform") if app is not None else None
    if t is None:
        return bad("no <TextureTransform>")
    got = {"translation": floats(t.get("translation")), "rotation": (floats(t.get("rotation")) or [0.0])[0], "scale": floats(t.get("scale"))}
    msgs = []
    for k in ("translation", "rotation", "scale"):
        if k in ck and not compare_value(got[k], ck[k], 1e-4):
            msgs.append(f"{k}={fnum(got[k])} want {fnum(ck[k])}")
    return bad("; ".join(msgs)) if msgs else ok(f"translation={fnum(got['translation'])} rotation={got['rotation']:.4g} scale={fnum(got['scale'])}")


# -- lights, cameras -----------------------------------------------------------------

def _child(tr, tags):
    for c in tr:
        if c.tag in tags:
            return c
    return None


@check("light")
def c_light(ck, doc, env):
    tr, err = _need_tr(doc, ck)
    if err:
        return err
    li = _child(tr, ("DirectionalLight", "PointLight", "SpotLight"))
    if li is None:
        return bad("no light node under the Transform")
    msgs = []
    if "tag" in ck and li.tag != ck["tag"]:
        msgs.append(f"<{li.tag}> (want <{ck['tag']}>)")
    tol = ck.get("tol", 1e-4)
    for name, exp in ck.get("attrs", {}).items():
        val, dflt = attr_value(li, name)
        if val is None or not compare_value(val, exp, tol):
            msgs.append(f"{name}={fnum(val)}{' (default)' if dflt else ''} want {fnum(exp)}")
    if "world_dir" in ck:
        loc = floats(li.get("direction")) or [0, 0, -1]
        w = m_apply_dir(doc.world_matrix(tr), loc)
        n = v_len(w) or 1
        w = tuple(c / n for c in w)
        if max(abs(a - b) for a, b in zip(w, ck["world_dir"])) > 2e-3:
            msgs.append(f"world direction {fnum(w)} want {fnum(ck['world_dir'])}")
    return bad("; ".join(msgs)) if msgs else ok(f"<{li.tag}>")


def _light_attr(doc, spec):
    tr = doc.obj_transform(spec["obj"])
    li = _child(tr, ("DirectionalLight", "PointLight", "SpotLight")) if tr is not None else None
    if li is None:
        return None
    v, _ = attr_value(li, spec["attr"])
    return v


@check("light_differs")
def c_light_differs(ck, doc, env):
    a, b = _light_attr(doc, ck["a"]), _light_attr(doc, ck["b"])
    if a is None or b is None:
        return bad("light(s) not found")
    return (ok if abs(a - b) > 1e-6 else bad)(f"{ck['a']['obj']}.{ck['a']['attr']}={a:.6g} vs {ck['b']['obj']}.{ck['b']['attr']}={b:.6g}")


@check("view")
def c_view(ck, doc, env):
    tr, err = _need_tr(doc, ck)
    if err:
        return err
    vp = _child(tr, ("Viewpoint", "OrthoViewpoint"))
    if vp is None:
        return bad("no <Viewpoint> under the Transform")
    msgs = []
    tol = ck.get("tol", 1e-4)
    for name, exp in ck.get("attrs", {}).items():
        val, dflt = attr_value(vp, name, "Viewpoint")
        if val is None or not compare_value(val, exp, tol):
            msgs.append(f"{name}={fnum(val)}{' (default)' if dflt else ''} want {fnum(exp)}")
    if "description" in ck and vp.get("description") != ck["description"]:
        msgs.append(f"description={vp.get('description')!r}")
    return bad("; ".join(msgs)) if msgs else ok(f"<{vp.tag}> fov={vp.get('fieldOfView')}")


@check("first_viewpoint")
def c_first_view(ck, doc, env):
    for el in doc.root.iter("Viewpoint"):
        p = doc.parent.get(el)
        want = doc.obj_transform(ck["obj"])
        return (ok if p is want else bad)(f"first Viewpoint belongs to {p.get('DEF') if p is not None else '?'} (scene camera: {ck['obj']})")
    return bad("no Viewpoint at all")


# -- generic ---------------------------------------------------------------------------

def _count_ok(n, spec):
    return all(((k == "eq" and n == v) or (k == "min" and n >= v) or (k == "max" and n <= v)) for k, v in spec.items())


@check("xpath")
def c_xpath(ck, doc, env):
    try:
        found = doc.root.findall(ck["path"])
    except SyntaxError as exc:
        return bad(f"bad xpath {ck['path']!r}: {exc}")
    n = len(found)
    spec = ck.get("n", {"min": 1})
    msgs = [] if _count_ok(n, spec) else [f"{n} match(es) for {ck['path']} (want {spec})"]
    for k, exp in ck.get("attrs", {}).items():
        for el in found:
            if el.get(k) != exp:
                msgs.append(f"{k}={el.get(k)!r} want {exp!r}")
                break
    return bad("; ".join(msgs)) if msgs else ok(f"{n} match(es)")


@check("attr")
def c_attr(ck, doc, env):
    found = doc.root.findall(ck["path"])
    if not found:
        return bad(f"{ck['path']} not found")
    vals = [el.get(ck["attr"], "") for el in found]
    return (ok if any(ck["contains"] in v for v in vals) else bad)(f"{ck['attr']}={vals[0]!r}")


@check("count_floats")
def c_count_floats(ck, doc, env):
    found = doc.root.findall(ck["path"])
    if not found:
        return bad(f"{ck['path']} not found")
    n = len(floats(found[0].get(ck["attr"])))
    return (ok if n == ck["count"] else bad)(f"{ck['attr']} has {n} numbers (want {ck['count']})")


@check("splat_orientation")
def c_splat_orient(ck, doc, env):
    g = doc.root.find(".//GaussianSplats")
    if g is None:
        return bad("no GaussianSplats")
    v = floats(g.get("orientations"))
    i = ck["index"]
    q = v[i * 4:i * 4 + 4]
    good = len(q) == 4 and all(abs(a - b) <= ck.get("tol", 1e-5) for a, b in zip(q, ck["expected"]))
    return (ok if good else bad)(f"orientation[{i}]={fnum(q)} want {fnum(ck['expected'])}")


@check("def_names_valid")
def c_def_names(ck, doc, env):
    rx = re.compile(r"^[^\s\"'#,.\[\]\\{}()<>&0-9+\-\x00-\x1f][^\s\"'#,.\[\]\\{}()<>&\x00-\x1f]*$")
    badn = [d for d in doc.defs if not rx.match(d)]
    return bad(f"invalid DEF names: {badn[:5]}") if badn else ok(f"{len(doc.defs)} DEF names valid")


# -- animation -------------------------------------------------------------------------

KIND_FIELD = {"position": "set_translation", "orientation": "set_rotation", "scale": "set_scale"}


@check("timer")
def c_timer(ck, doc, env):
    t = doc.root.find(".//TimeSensor")
    if t is None:
        return bad("no TimeSensor")
    ci = floats(t.get("cycleInterval"))
    msgs = []
    if not ci or abs(ci[0] - ck["cycle"]) > 1e-4:
        msgs.append(f"cycleInterval={ci} want {ck['cycle']}")
    if ck.get("loop") and t.get("loop") != "true":
        msgs.append(f"loop={t.get('loop')}")
    return bad("; ".join(msgs)) if msgs else ok(f"cycleInterval={ci[0]} loop={t.get('loop')}")


@check("anim_nodes")
def c_anim_nodes(ck, doc, env):
    tr, err = _need_tr(doc, ck)
    if err:
        return err
    amap = doc.anim_map().get(tr.get("DEF"), {})
    msgs, notes = [], []
    for kind in ck.get("kinds", []):
        f = KIND_FIELD[kind]
        node = amap.get(f)
        if node is None:
            msgs.append(f"no interpolator routed to {f}")
            continue
        n = len(floats(node.get("key")))
        notes.append(f"{kind}:{n} keys")
        if "keys" in ck and n != ck["keys"]:
            msgs.append(f"{kind} interpolator has {n} keys (want {ck['keys']})")
        timer_ok = any(r.get("toNode") == node.get("DEF") and r.get("toField") == "set_fraction" and r.get("fromField") == "fraction_changed"
                       for r in doc.routes)
        if not timer_ok:
            msgs.append(f"{node.get('DEF')} is not fed by a TimeSensor fraction_changed ROUTE")
    return bad("; ".join(msgs)) if msgs else ok(", ".join(notes))


@check("anim_absent")
def c_anim_absent(ck, doc, env):
    tr, err = _need_tr(doc, ck)
    if err:
        return err
    amap = doc.anim_map().get(tr.get("DEF"))
    return (ok if not amap else bad)("no interpolators routed" if not amap else f"unexpected interpolators: {sorted(amap)}")


@check("anim_world")
def c_anim_world(ck, doc, env):
    tr, err = _need_tr(doc, ck)
    if err:
        return err
    fr = env.m["frame"]
    span = float(fr["end"] - fr["start"])
    worst, where = 0.0, None
    for s in ck["samples"]:
        frac = (s["frame"] - fr["start"]) / span
        got = doc.world_matrix(tr, frac)
        good, dev = m_close(got, s["m"], ck.get("tol", 2e-4))
        if dev > worst:
            worst, where = dev, s["frame"]
    tol = ck.get("tol", 2e-4)
    return (ok if worst <= tol else bad)(f"max deviation {worst:.2e} over {len(ck['samples'])} frames" + ("" if worst <= tol else f" (worst at frame {where}, tol {tol})"))


# -- HAnim -----------------------------------------------------------------------------

def _humanoid(doc, name):
    for el in doc.root.iter("HAnimHumanoid"):
        if el.get("name") == name:
            return el
    return None


def _joint_list(h):
    out = []

    def walk(el, parent):
        for ch in el:
            if ch.tag == "HAnimJoint" and not ch.get("USE") and ch.get("containerField", "children") in ("skeleton", "children"):
                out.append({"el": ch, "name": ch.get("name"), "parent": parent, "center": floats(ch.get("center"))})
                walk(ch, ch.get("name"))
    walk(h, None)
    return out


def _skin_points(doc, h):
    c = None
    for ch in h:
        if ch.tag == "Coordinate" and ch.get("containerField") == "skinCoord":
            c = ch
    if c is None:
        return []
    p = floats(c.get("point"))
    return [tuple(p[i:i + 3]) for i in range(0, len(p) - 2, 3)]


@check("hanim")
def c_hanim(ck, doc, env):
    h = _humanoid(doc, ck["armature"])
    if h is None:
        return bad(f"no <HAnimHumanoid name='{ck['armature']}'>")
    joints = _joint_list(h)
    msgs = []
    want = {b["name"]: b for b in ck["bones"]}
    got = {j["name"]: j for j in joints}
    if set(want) != set(got):
        msgs.append(f"joints {sorted(got)} != bones {sorted(want)}")
    for n, b in want.items():
        j = got.get(n)
        if not j:
            continue
        if j["parent"] != b["parent"]:
            msgs.append(f"joint {n} parent={j['parent']} want {b['parent']}")
        if len(j["center"]) != 3 or max(abs(a - c) for a, c in zip(j["center"], b["head"])) > 1e-4:
            msgs.append(f"joint {n} center={fnum(j['center'])} want {fnum(b['head'])}")
    uses = [c for c in h if c.tag == "HAnimJoint" and c.get("USE") and c.get("containerField") == "joints"]
    if len(uses) != len(want):
        msgs.append(f"{len(uses)} joints[] entries (want {len(want)})")
    sp = _skin_points(doc, h)
    nuniq = len({tuple(round(c, 4) for c in p) for p in sp})
    if ck.get("skin_vertices", 0) == 0:
        if sp:
            msgs.append("unexpected skinCoord")
    elif nuniq != ck["skin_vertices"]:
        msgs.append(f"skinCoord has {nuniq} distinct points (want {ck['skin_vertices']})")
    return bad("; ".join(msgs)) if msgs else ok(f"{len(joints)} joints, {len(sp)} skin points")


def _weights(doc, h):
    per = {}
    for j in _joint_list(h):
        idx = [int(v) for v in floats(j["el"].get("skinCoordIndex"))]
        w = floats(j["el"].get("skinCoordWeight"))
        if len(idx) != len(w):
            return None, f"joint {j['name']}: {len(idx)} indices but {len(w)} weights"
        for i, ww in zip(idx, w):
            per.setdefault(i, []).append((j["el"], ww))
    return per, None


@check("hanim_weights")
def c_hanim_weights(ck, doc, env):
    h = _humanoid(doc, ck["armature"])
    if h is None:
        return bad("no humanoid")
    per, err = _weights(doc, h)
    if err:
        return bad(err)
    n = len(_skin_points(doc, h))
    if n == 0:
        return bad("no skin points")
    uncovered = [i for i in range(n) if i not in per]
    off = [i for i, lst in per.items() if abs(sum(w for _, w in lst) - 1.0) > 2e-3]
    msgs = []
    if uncovered:
        msgs.append(f"{len(uncovered)} skin points without any joint")
    if off:
        msgs.append(f"{len(off)} skin points whose weights do not sum to 1 (e.g. #{off[0]}: {sum(w for _, w in per[off[0]]):.3f})")
    return bad("; ".join(msgs)) if msgs else ok(f"{n} skin points, weights normalised")


def _joint_world(doc, jel, fraction, humanoid):
    chain = []
    cur = jel
    while cur is not None and cur is not humanoid:
        if cur.tag == "HAnimJoint":
            chain.append(cur)
        cur = doc.parent.get(cur)
    m = m_ident()
    for j in reversed(chain):
        m = m_mul(m, doc.local_matrix(j, fraction))
    return m


@check("hanim_pose")
def c_hanim_pose(ck, doc, env):
    h = _humanoid(doc, ck["armature"])
    if h is None:
        return bad("no humanoid")
    per, err = _weights(doc, h)
    if err:
        return bad(err)
    sp = _skin_points(doc, h)
    fr = env.m["frame"]
    span = float(fr["end"] - fr["start"])
    base = doc.world_matrix(h)
    worst, where, tested = 0.0, None, 0
    cache = {}
    for pr in ck["probes"]:
        frac = (pr["frame"] - fr["start"]) / span
        rest = pr["rest"]
        idxs = [i for i, p in enumerate(sp) if max(abs(a - b) for a, b in zip(p, rest)) < 2e-4]
        if not idxs:
            return bad(f"no skinCoord point at rest position {fnum(rest)}")
        for i in idxs:
            acc = [0.0, 0.0, 0.0]
            for jel, w in per.get(i, []):
                key = (id(jel), frac)
                if key not in cache:
                    cache[key] = _joint_world(doc, jel, frac, h)
                q = m_apply(cache[key], sp[i])
                acc = [acc[k] + w * q[k] for k in range(3)]
            world = m_apply(base, acc)
            dev = max(abs(a - b) for a, b in zip(world, pr["world"]))
            tested += 1
            if dev > worst:
                worst, where = dev, (pr["frame"], i)
    tol = ck.get("tol", 2e-3)
    return (ok if worst <= tol else bad)(f"max vertex deviation {worst:.2e} m over {tested} skinned vertices x frames" +
                                          ("" if worst <= tol else f" (worst at frame {where[0]}, skin point #{where[1]})"))


# -- integrity ---------------------------------------------------------------------------

SFCOLOR_ATTRS = {"baseColor", "emissiveColor", "color", "skyColor", "attenuationColor", "specularColor", "diffuseColor", "sheenColor"}


@check("integrity")
def c_integrity(ck, doc, env):
    what = ck["what"]
    if what == "xml_wellformed":
        return ok(f"parsed {len(doc.order)} elements, {len(doc.text) / 1e6:.1f} MB")
    if what == "def_unique":
        return bad(f"duplicate DEF names: {doc.dup_defs[:5]}") if doc.dup_defs else ok(f"{len(doc.defs)} unique DEFs")
    if what == "use_resolves":
        badu = []
        for el in doc.root.iter():
            u = el.get("USE")
            if u is None:
                continue
            tgt = doc.defs.get(u)
            if tgt is None or doc.order[tgt] > doc.order[el]:
                badu.append(u)
        return bad(f"{len(badu)} unresolved/forward USE (e.g. {badu[:3]})") if badu else ok("all USE resolve to an earlier DEF")
    if what == "route_targets":
        msgs = []
        for r in doc.routes:
            a, b = doc.defs.get(r.get("fromNode")), doc.defs.get(r.get("toNode"))
            if a is None or b is None:
                msgs.append(f"ROUTE {r.get('fromNode')}->{r.get('toNode')}: undefined node")
                continue
            ff, tf = r.get("fromField"), r.get("toField")
            if ff == "fraction_changed" and (a.tag != "TimeSensor" or tf != "set_fraction"):
                msgs.append(f"bad fraction ROUTE {a.tag}.{ff}->{b.tag}.{tf}")
            if ff == "value_changed":
                good = ((a.tag == "PositionInterpolator" and tf in ("set_translation", "set_scale")) or
                        (a.tag == "OrientationInterpolator" and tf == "set_rotation") or
                        a.tag in ("ScalarInterpolator", "ColorInterpolator", "CoordinateInterpolator"))
                if not good:
                    msgs.append(f"field mismatch {a.tag}.{ff}->{b.tag}.{tf}")
        return bad("; ".join(msgs[:4])) if msgs else ok(f"{len(doc.routes)} ROUTEs valid")
    if what == "numbers_finite":
        m = re.search(r'="[^"]*\b(nan|inf|-inf)\b', doc.text, re.I)
        return bad(f"non-finite number near {doc.text[max(0, m.start() - 40):m.end() + 10]!r}") if m else ok("all numbers finite")
    if what == "coordindex_valid":
        msgs, n = [], 0
        for el in doc.root.iter("IndexedFaceSet"):
            if el.get("USE"):
                continue
            n += 1
            d = ifs_data(doc, el)
            if d is None or not d["P"]:
                msgs.append(f"{el.get('DEF')}: no Coordinate")
                continue
            if any(i >= len(d["P"]) for i in d["ci"]):
                msgs.append(f"{el.get('DEF')}: index out of range")
            if any(len(f) < 3 for f in d["faces"]):
                msgs.append(f"{el.get('DEF')}: face with <3 vertices")
            if d["el"].find("Coordinate") is not None and not d["el"].find("Coordinate").get("USE"):
                for node, (field, w) in NODE_FIELD.items():
                    sub = d["el"].find(node)
                    if sub is not None and len(floats(sub.get(field))) // w != len(d["P"]):
                        msgs.append(f"{el.get('DEF')}: {node} count != Coordinate count")
        return bad("; ".join(msgs[:4])) if msgs else ok(f"{n} IndexedFaceSets consistent")
    if what == "interp_valid":
        msgs, n = [], 0
        widths = {"PositionInterpolator": 3, "OrientationInterpolator": 4, "ScalarInterpolator": 1, "ColorInterpolator": 3}
        for el in doc.root.iter():
            w = widths.get(el.tag)
            if w is None:
                continue
            n += 1
            k, v = floats(el.get("key")), floats(el.get("keyValue"))
            if len(v) != len(k) * w:
                msgs.append(f"{el.get('DEF')}: {len(v)} values for {len(k)} keys")
            if any(b <= a for a, b in zip(k, k[1:])) or (k and (k[0] < 0 or k[-1] > 1)):
                msgs.append(f"{el.get('DEF')}: keys not strictly increasing within [0,1]")
        return bad("; ".join(msgs[:4])) if msgs else ok(f"{n} interpolators valid")
    if what == "sfcolor_range":
        badc = []
        for el in doc.root.iter():
            for a in SFCOLOR_ATTRS:
                v = el.get(a)
                if v is not None and any(c < -1e-9 or c > 1 + 1e-6 for c in floats(v)):
                    badc.append(f"{el.tag}.{a}")
        return bad(f"{len(badc)} colour values outside [0,1] (e.g. {badc[:3]})") if badc else ok("all colours within [0,1]")
    return bad(f"unknown integrity check {what!r}")


# -- roadmap probes ----------------------------------------------------------------------

@check("roadmap")
def c_roadmap(ck, doc, env):
    found = []
    tags = set(ck.get("any_tags", []))
    if tags:
        for el in doc.root.iter():
            if el.tag in tags:
                found.append(f"<{el.tag}>")
                break
    attrs = ck.get("any_attrs", [])
    if attrs:
        for el in doc.root.iter():
            for a in attrs:
                if el.get(a) is not None:
                    found.append(f"{el.tag}@{a}")
                    break
            if found and found[-1].count("@"):
                break
    for a, v in ck.get("any_values", {}).items():
        for el in doc.root.iter():
            if el.get(a) == v:
                found.append(f"{el.tag}@{a}={v}")
                break
    for pre in ck.get("route_into", []):
        for r in doc.routes:
            if (r.get("toNode") or "").startswith(pre):
                found.append(f"ROUTE->{r.get('toNode')}")
                break
    return ok("implemented: " + ", ".join(found[:3])) if found else bad(f"not found ({ck.get('feature', '')})")


# --------------------------------------------------------------------------------------
# RUNNER
# --------------------------------------------------------------------------------------

VERDICT_FOR = {"CORE": ("PASS", "FAIL"), "FIDELITY": ("PASS", "WARN"), "ROADMAP": ("NEW", "MISSING")}
ORDER = ["FAIL", "ERROR", "WARN", "MISSING", "NEW", "SKIP", "PASS"]


def run_case(case, docs, manifest, out_dir):
    prof = case.get("profile", "main")
    doc = docs.get(prof)
    if isinstance(doc, str) or doc is None:
        return {"verdict": "SKIP", "results": [], "note": doc or f"profile '{prof}' not exported"}
    env = Env(manifest, prof, out_dir)
    results = []
    for ck in case["checks"]:
        fn = CHECKS.get(ck["k"])
        if fn is None:
            results.append({"ok": False, "msg": f"validator has no check '{ck['k']}'", "kind": ck["k"], "error": True})
            continue
        try:
            r = fn(ck, doc, env)
            results.append({"ok": r.ok, "msg": r.msg, "kind": ck["k"]})
        except Exception as exc:  # a bug in the validator, never in the exporter
            import traceback
            results.append({"ok": False, "msg": f"validator exception {exc!r}", "kind": ck["k"], "error": True,
                            "trace": traceback.format_exc(limit=4)})
    if any(r.get("error") for r in results):
        verdict = "ERROR"
    else:
        passed, failed = VERDICT_FOR[case["tier"]]
        verdict = passed if all(r["ok"] for r in results) else failed
    return {"verdict": verdict, "results": results}


def load_docs(manifest, base_dir, overrides):
    docs = {}
    used = {c.get("profile", "main") for c in manifest["cases"]}
    for prof in used:
        path = overrides.get(prof) or os.path.join(base_dir, manifest["profiles"][prof]["file"])
        if not os.path.exists(path):
            docs[prof] = f"file not found: {path}"
            continue
        try:
            docs[prof] = Doc(path)
        except ET.ParseError as exc:
            docs[prof] = f"XML parse error in {path}: {exc}"
    return docs


def run(manifest_path, overrides=None, only=None, tiers=None):
    base_dir = os.path.dirname(os.path.abspath(manifest_path))
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    docs = load_docs(manifest, base_dir, overrides or {})
    out = []
    t0 = time.time()
    for case in manifest["cases"]:
        if only and not any(case["id"].lower().startswith(o.lower()) or case["zone"].lower() == o.lower() for o in only):
            continue
        if tiers and case["tier"] not in tiers:
            continue
        res = run_case(case, docs, manifest, base_dir)
        out.append({**{k: case[k] for k in ("id", "zone", "tier", "title", "expect", "profile")}, "known": case.get("known"), **res})
    return {"manifest": {k: manifest[k] for k in ("suite_version", "blender", "created", "frame", "zones", "skipped_zones", "profiles",
                                                  "build_log", "exporter_available") if k in manifest},
            "docs": {p: (d if isinstance(d, str) else d.path) for p, d in docs.items()},
            "generator": next((m.get("content") for d in docs.values() if not isinstance(d, str) and d.head is not None
                               for m in d.head.findall("meta") if m.get("name") == "generator"), None),
            "results": out, "seconds": round(time.time() - t0, 2), "validator": VERSION}


def summarize(report):
    from collections import Counter
    c = Counter(r["verdict"] for r in report["results"])
    by_zone = OrderedDict()
    for r in report["results"]:
        z = by_zone.setdefault(r["zone"], Counter())
        z[r["verdict"]] += 1
    by_tier = OrderedDict()
    for r in report["results"]:
        by_tier.setdefault(r["tier"], Counter())[r["verdict"]] += 1
    return c, by_zone, by_tier


# --------------------------------------------------------------------------------------
# REPORTS
# --------------------------------------------------------------------------------------

COL = {"PASS": "\033[32m", "FAIL": "\033[1;31m", "WARN": "\033[33m", "MISSING": "\033[36m", "NEW": "\033[1;35m", "SKIP": "\033[90m",
       "ERROR": "\033[1;41m"}
RST = "\033[0m"


def paint(v, text, tty):
    return f"{COL.get(v, '')}{text}{RST}" if tty else text


def print_console(report, verbose=False, tty=None):
    tty = sys.stdout.isatty() if tty is None else tty
    c, by_zone, by_tier = summarize(report)
    zmeta = {z["id"]: z for z in report["manifest"]["zones"]}
    print(f"\nX3D export validation   suite {report['manifest']['suite_version']}  validator {report['validator']}  Blender {report['manifest']['blender']}")
    print(f"exporter: {report.get('generator')}    files: " + ", ".join(f"{p}={os.path.basename(d)}" for p, d in report["docs"].items()))
    print("-" * 100)
    print(f"{'zone':<5}{'name':<13}" + "".join(f"{v:>9}" for v in ORDER[::-1]))
    for z, cc in by_zone.items():
        print(f"{z:<5}{zmeta.get(z, {}).get('name', ''):<13}" + "".join(
            (paint(v, f"{cc.get(v, 0):>9}", tty) if cc.get(v) else f"{'.':>9}") for v in ORDER[::-1]))
    print("-" * 100)
    for tier, cc in by_tier.items():
        label = {"CORE": "CORE      (exporter must pass)", "FIDELITY": "FIDELITY  (should pass; gaps reported)",
                 "ROADMAP": "ROADMAP   (MISSING expected; NEW = implemented)"}[tier]
        print(f"{label:<52}" + "  ".join(paint(v, f"{v}={cc[v]}", tty) for v in ORDER if cc.get(v)))
    print()
    show = ("FAIL", "ERROR") if not verbose else ("FAIL", "ERROR", "WARN", "NEW", "MISSING")
    for r in report["results"]:
        if r["verdict"] in show:
            print(f"{paint(r['verdict'], r['verdict'].ljust(7), tty)} {r['id']}  {r['title']}")
            for x in r["results"]:
                if not x["ok"]:
                    print(f"          x {x['kind']}: {x['msg']}")
                    if x.get("trace"):
                        print("            " + x["trace"].replace("\n", "\n            "))
            if r.get("known") and r["verdict"] in ("FAIL", "ERROR"):
                print(f"          ! known issue: {r['known']}")
    if not verbose and any(v in c for v in ("WARN", "MISSING", "NEW")):
        print("\n(re-run with --verbose to list WARN / MISSING / NEW details)")
    n_core = sum(v for k, v in by_tier.get("CORE", {}).items())
    core_pass = by_tier.get("CORE", {}).get("PASS", 0)
    print(f"\nCORE conformance: {core_pass}/{n_core} passed"
          + (f"   |   NEW features detected: {c['NEW']}" if c.get("NEW") else ""))


def write_json(report, path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)


def write_catalog(manifest_path, path):
    """Plain-English catalogue of every case straight from the manifest: what a correct export must contain."""
    m = json.load(open(manifest_path, encoding="utf-8"))
    L = [f"# X3D test-suite catalogue (suite {m['suite_version']}, {len(m['cases'])} cases)", "",
         "Tier: **CORE** = the exporter claims it, failure is a bug; **FIDELITY** = a faithful exporter should do it, failure is a known approximation; "
         "**ROADMAP** = not implemented yet, `MISSING` is the expected state.", ""]
    for z in m["zones"]:
        cs = [c for c in m["cases"] if c["zone"] == z["id"]]
        if not cs:
            continue
        L += [f"## {z['id']} {z['name']} - {z['title']}", "", "| case | tier | what a correct export looks like |", "|---|---|---|"]
        for c in cs:
            exp = c["expect"].replace("|", "\\|").replace("\n", " ")
            prof = "" if c.get("profile", "main") == "main" else f" *(profile {c['profile']})*"
            L.append(f"| `{c['id']}` | {c['tier']} | **{c['title']}**{prof}. {exp} |")
        L.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")


def write_markdown(report, path):
    c, by_zone, by_tier = summarize(report)
    zmeta = {z["id"]: z for z in report["manifest"]["zones"]}
    L = ["# X3D export validation report", "",
         f"Suite {report['manifest']['suite_version']} · validator {report['validator']} · Blender {report['manifest']['blender']} · exporter `{report.get('generator')}`", "",
         "| verdict | count |", "|---|---:|"] + [f"| {v} | {c[v]} |" for v in ORDER if c.get(v)] + ["", "## By zone", "",
         "| zone | name | " + " | ".join(ORDER[::-1]) + " |", "|---|---|" + "---:|" * len(ORDER)]
    for z, cc in by_zone.items():
        L.append(f"| {z} | {zmeta.get(z, {}).get('name', '')} | " + " | ".join(str(cc.get(v, "")) for v in ORDER[::-1]) + " |")
    for title, verdicts in (("CORE failures (bugs)", ("FAIL", "ERROR")), ("FIDELITY gaps (approximations)", ("WARN",)),
                            ("ROADMAP: not implemented yet", ("MISSING",)), ("ROADMAP: newly implemented", ("NEW",))):
        rows = [r for r in report["results"] if r["verdict"] in verdicts]
        if not rows:
            continue
        L += ["", f"## {title}", ""]
        for r in rows:
            L.append(f"- **{r['id']}** — {r['title']}")
            for x in r["results"]:
                if (not x["ok"]) or r["verdict"] == "NEW":
                    L.append(f"  - `{x['kind']}`: {x['msg']}")
            if r.get("known") and r["verdict"] in ("FAIL", "ERROR"):
                L.append(f"  - **known issue:** {r['known']}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")


HTML_TMPL = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>X3D Export Scoreboard</title><style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#14181f;--mute:#5b6573;--line:#dfe3e8;--pass:#1a7f4b;--fail:#c62828;--warn:#b26a00;--miss:#0b6d8f;--new:#7b2cbf;--skip:#6b7280;--err:#c62828}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0f1317;--card:#171c22;--ink:#e8ecf1;--mute:#9aa5b3;--line:#2a323b;--pass:#4cc38a;--fail:#ff6b6b;--warn:#f2b04c;--miss:#5ec2e6;--new:#c08bff;--skip:#8b95a3;--err:#ff6b6b}}
:root[data-theme=dark]{--bg:#0f1317;--card:#171c22;--ink:#e8ecf1;--mute:#9aa5b3;--line:#2a323b;--pass:#4cc38a;--fail:#ff6b6b;--warn:#f2b04c;--miss:#5ec2e6;--new:#c08bff;--skip:#8b95a3;--err:#ff6b6b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:20px 16px 60px}h1{font-size:1.5rem;margin:.2rem 0}.sub{color:var(--mute);font-size:.9rem}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin:18px 0}.tile{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;cursor:pointer}
.tile b{display:block;font-size:1.7rem;line-height:1.1}.tile span{font-size:.78rem;color:var(--mute);letter-spacing:.04em;text-transform:uppercase}
.tile.on{outline:2px solid var(--ink)}.bar{display:flex;height:10px;border-radius:6px;overflow:hidden;background:var(--line);margin:6px 0 14px}.bar i{display:block}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}.chip{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;padding:4px 11px;font-size:.82rem;cursor:pointer}
.chip.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}input[type=search]{width:100%;padding:9px 12px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--ink);font-size:.95rem}
.case{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--skip);border-radius:10px;margin:8px 0;padding:0}
.case summary{list-style:none;cursor:pointer;padding:10px 14px;display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}.case summary::-webkit-details-marker{display:none}
.v{font-weight:700;font-size:.72rem;letter-spacing:.05em;padding:2px 8px;border-radius:6px;color:#fff;background:var(--skip)}
.PASS{border-left-color:var(--pass)}.PASS .v{background:var(--pass)}.FAIL{border-left-color:var(--fail)}.FAIL .v{background:var(--fail)}.ERROR{border-left-color:var(--err)}.ERROR .v{background:var(--err)}
.WARN{border-left-color:var(--warn)}.WARN .v{background:var(--warn)}.MISSING{border-left-color:var(--miss)}.MISSING .v{background:var(--miss)}.NEW{border-left-color:var(--new)}.NEW .v{background:var(--new)}
.id{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.82rem;color:var(--mute)}.tier{font-size:.7rem;color:var(--mute);border:1px solid var(--line);border-radius:5px;padding:0 6px}
.body{padding:0 14px 12px;color:var(--ink)}.exp{color:var(--mute);margin:2px 0 8px;font-size:.92rem}.chk{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.8rem;margin:2px 0;word-break:break-word}
.chk.bad{color:var(--fail)}.chk.good{color:var(--pass)}.theme{float:right}button.theme{background:none;border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:4px 10px;cursor:pointer}
</style></head><body><main>
<button class="theme" onclick="var r=document.documentElement;r.dataset.theme=r.dataset.theme==='dark'?'light':'dark'">theme</button>
<h1>X3D export scoreboard</h1><div class="sub" id="sub"></div>
<div class="tiles" id="tiles"></div><div class="bar" id="bar"></div>
<div class="chips" id="tierchips"></div><div class="chips" id="zonechips"></div>
<input type="search" id="q" placeholder="Filter cases (id, title, message)…"><div id="list" style="margin-top:12px"></div>
<script>const DATA=__DATA__;
const ORDER=["FAIL","ERROR","WARN","MISSING","NEW","PASS","SKIP"],NAMES={FAIL:"CORE fail",ERROR:"validator error",WARN:"fidelity gap",MISSING:"roadmap: missing",NEW:"roadmap: NEW",PASS:"pass",SKIP:"skipped"};
const COLORS={PASS:"var(--pass)",FAIL:"var(--fail)",ERROR:"var(--err)",WARN:"var(--warn)",MISSING:"var(--miss)",NEW:"var(--new)",SKIP:"var(--skip)"};
const S={v:new Set(),t:new Set(),z:new Set(),q:""};const R=DATA.results;
document.getElementById("sub").textContent=`suite ${DATA.manifest.suite_version} · Blender ${DATA.manifest.blender} · exporter ${DATA.generator||"?"} · ${R.length} cases`;
function counts(){const c={};R.forEach(r=>c[r.verdict]=(c[r.verdict]||0)+1);return c}
const C=counts();const tiles=document.getElementById("tiles");
ORDER.forEach(v=>{if(!C[v])return;const d=document.createElement("div");d.className="tile";d.innerHTML=`<b style="color:${COLORS[v]}">${C[v]}</b><span>${NAMES[v]}</span>`;d.onclick=()=>{S.v.has(v)?S.v.delete(v):S.v.add(v);render()};d.dataset.v=v;tiles.appendChild(d)});
document.getElementById("bar").innerHTML=ORDER.filter(v=>C[v]).map(v=>`<i style="width:${100*C[v]/R.length}%;background:${COLORS[v]}" title="${v} ${C[v]}"></i>`).join("");
function chips(id,vals,set,label){const el=document.getElementById(id);vals.forEach(x=>{const b=document.createElement("button");b.className="chip";b.textContent=label(x);b.onclick=()=>{set.has(x)?set.delete(x):set.add(x);render()};b.dataset.k=x;el.appendChild(b)})}
chips("tierchips",["CORE","FIDELITY","ROADMAP"],S.t,x=>x);const zones=[...new Set(R.map(r=>r.zone))];
const zn={};DATA.manifest.zones.forEach(z=>zn[z.id]=z.name);chips("zonechips",zones,S.z,x=>x+" "+(zn[x]||""));
document.getElementById("q").oninput=e=>{S.q=e.target.value.toLowerCase();render()};
function esc(s){return String(s).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]))}
function render(){document.querySelectorAll(".tile").forEach(t=>t.classList.toggle("on",S.v.has(t.dataset.v)));
document.querySelectorAll(".chip").forEach(c=>c.classList.toggle("on",S.t.has(c.dataset.k)||S.z.has(c.dataset.k)));
const rows=R.filter(r=>(!S.v.size||S.v.has(r.verdict))&&(!S.t.size||S.t.has(r.tier))&&(!S.z.size||S.z.has(r.zone))&&(!S.q||(r.id+" "+r.title+" "+r.results.map(x=>x.msg).join(" ")).toLowerCase().includes(S.q)));
rows.sort((a,b)=>ORDER.indexOf(a.verdict)-ORDER.indexOf(b.verdict)||a.id.localeCompare(b.id));
document.getElementById("list").innerHTML=rows.map(r=>`<details class="case ${r.verdict}" ${(r.verdict==="FAIL"||r.verdict==="ERROR")?"open":""}><summary><span class="v">${r.verdict}</span><span class="id">${r.id}</span><b>${esc(r.title)}</b><span class="tier">${r.tier}</span></summary><div class="body"><div class="exp">${esc(r.expect)}</div>${r.results.map(x=>`<div class="chk ${x.ok?"good":"bad"}">${x.ok?"✓":"✗"} ${esc(x.kind)} — ${esc(x.msg)}</div>`).join("")}${r.known&&(r.verdict==="FAIL"||r.verdict==="ERROR")?`<div class="chk bad">⚠ known issue — ${esc(r.known)}</div>`:""}${r.note?`<div class="chk">${esc(r.note)}</div>`:""}</div></details>`).join("")||"<p class=sub>No cases match.</p>"}
render();</script></main></body></html>"""


def write_html(report, path):
    data = json.dumps(report).replace("</", "<\\/")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(HTML_TMPL.replace("__DATA__", data))


# --------------------------------------------------------------------------------------
# SELF-TEST  (proves the validator's own maths / parsing without Blender or an exporter)
# --------------------------------------------------------------------------------------

SELFTEST_X3D = """<?xml version="1.0" encoding="UTF-8"?>
<X3D version="4.0" profile="Immersive"><head><component name="Shape" level="2"/><meta name="info" content="hello world"/></head><Scene>
 <NavigationInfo headlight="false"/>
 <Transform DEF="OB_parent" translation="1 2 3" rotation="0 0 1 1.5707963" scale="2 2 2">
  <Transform DEF="OB_child" translation="1 0 0">
   <Shape><Appearance DEF="APP_a"><PhysicalMaterial baseColor="0.5 0.25 0.125" roughness="0.4"/></Appearance>
    <IndexedFaceSet DEF="ME_q" coordIndex="0 1 2 3 -1"><Coordinate point="0 0 0 1 0 0 1 1 0 0 1 0"/><Normal vector="0 0 1 0 0 1 0 0 1 0 0 1"/></IndexedFaceSet></Shape>
  </Transform></Transform>
 <Transform DEF="OB_mover"><Shape><Appearance USE="APP_a"/><IndexedFaceSet USE="ME_q"/></Shape></Transform>
 <TimeSensor DEF="SceneTimer" cycleInterval="2" loop="true"/>
 <PositionInterpolator DEF="PI_mover" key="0 0.5 1" keyValue="0 0 0 2 0 0 2 4 0"/>
 <OrientationInterpolator DEF="OI_mover" key="0 1" keyValue="0 0 1 0 0 0 1 3.14159265"/>
 <ROUTE fromNode="SceneTimer" fromField="fraction_changed" toNode="PI_mover" toField="set_fraction"/>
 <ROUTE fromNode="PI_mover" fromField="value_changed" toNode="OB_mover" toField="set_translation"/>
 <ROUTE fromNode="SceneTimer" fromField="fraction_changed" toNode="OI_mover" toField="set_fraction"/>
 <ROUTE fromNode="OI_mover" fromField="value_changed" toNode="OB_mover" toField="set_rotation"/>
</Scene></X3D>"""


def selftest():
    import tempfile
    fails = []

    def expect(name, cond, detail=""):
        print(f"  {'ok ' if cond else 'FAIL'} {name} {detail}")
        if not cond:
            fails.append(name)

    print("validator self-test")
    # --- maths
    p = m_apply(m_axis_angle((0, 0, 1), math.pi / 2), (1, 0, 0))
    expect("axis-angle rotates +X to +Y", abs(p[0]) < 1e-9 and abs(p[1] - 1) < 1e-9)
    q = quat_to_aa(slerp(aa_to_quat((0, 0, 1, 0)), aa_to_quat((0, 0, 1, math.pi)), 0.5))
    expect("slerp midpoint of 0..180 deg is 90 deg", abs(q[3] - math.pi / 2) < 1e-9 and abs(q[2] - 1) < 1e-9)
    m = trs_matrix((1, 2, 3), (0, 0, 1, math.pi / 2), (2, 2, 2))
    p = m_apply(m, (1, 0, 0))
    expect("TRS composition order T*R*S", max(abs(a - b) for a, b in zip(p, (1, 4, 3))) < 1e-9, str(p))
    expect("safe_name mirrors the exporter", safe_name("9lives") == "_lives" and safe_name("a b.c") == "a_b_c")
    # --- document model
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "t.x3d")
        open(path, "w").write(SELFTEST_X3D)
        doc = Doc(path)
        manifest = {"frame": {"start": 1, "end": 3, "fps": 1, "current": 1}, "objects": {}, "profiles": {"main": {"export": {}}}}
        env = Env(manifest, "main", d)
        wc = doc.world_matrix(doc.obj_transform("child"))
        expect("nested Transform world matrix", max(abs(a - b) for a, b in zip(wc[3::4][:3], (1, 4, 3))) < 1e-6, str(wc[3::4][:3]))
        manifest["objects"]["child"] = {"world": wc}
        expect("xf check passes for the true matrix", CHECKS["xf"]({"k": "xf", "obj": "child"}, doc, env).ok)
        wrong = list(wc); wrong[3] += 0.5; manifest["objects"]["child"] = {"world": wrong}
        expect("xf check fails for a wrong matrix", not CHECKS["xf"]({"k": "xf", "obj": "child"}, doc, env).ok)
        facts = {"obj": "child", "faces": 1, "positions": 4, "bbox": [[0, 0, 0], [1, 1, 0]], "area": 1.0, "has_uv": False}
        expect("mesh check passes", CHECKS["mesh"]({"k": "mesh", "facts": facts}, doc, env).ok)
        expect("mesh check fails on wrong face count", not CHECKS["mesh"]({"k": "mesh", "facts": dict(facts, faces=2)}, doc, env).ok)
        expect("mesh check fails on wrong area", not CHECKS["mesh"]({"k": "mesh", "facts": dict(facts, area=2.0)}, doc, env).ok)
        expect("normals check", CHECKS["normals"]({"k": "normals", "obj": "child", "unit": True, "all_equal": [0, 0, 1]}, doc, env).ok)
        expect("mat check with X3D default fallback",
               CHECKS["mat"]({"k": "mat", "obj": "child", "attrs": {"baseColor": [0.5, 0.25, 0.125], "roughness": 0.4, "metallic": 1.0}}, doc, env).ok)
        expect("mat 'present' flags an omitted field",
               not CHECKS["mat"]({"k": "mat", "obj": "child", "present": ["metallic"]}, doc, env).ok)
        # animation: at fraction 0.75 translation is (2,2,0) and rotation 1.5*pi/2... = 0.75*pi
        wm = doc.world_matrix(doc.obj_transform("mover"), 0.75)
        expect("animated world matrix", max(abs(a - b) for a, b in zip(wm[3::4][:3], (2, 2, 0))) < 1e-9)
        expect("anim_world check", CHECKS["anim_world"]({"k": "anim_world", "obj": "mover", "samples": [{"frame": 2, "m": doc.world_matrix(doc.obj_transform("mover"), 0.5)}]}, doc, env).ok)
        expect("anim_nodes check", CHECKS["anim_nodes"]({"k": "anim_nodes", "obj": "mover", "kinds": ["position", "orientation"]}, doc, env).ok)
        expect("anim_absent check on a static object", CHECKS["anim_absent"]({"k": "anim_absent", "obj": "child"}, doc, env).ok)
        for what in ("def_unique", "use_resolves", "route_targets", "numbers_finite", "coordindex_valid", "interp_valid", "sfcolor_range"):
            expect(f"integrity.{what} passes on clean file", CHECKS["integrity"]({"k": "integrity", "what": what}, doc, env).ok)
        bad_text = SELFTEST_X3D.replace('<Appearance USE="APP_a"/>', '<Appearance USE="APP_zzz"/>').replace('keyValue="0 0 0 2 0 0 2 4 0"', 'keyValue="0 0 0 2 0 0"')
        open(path, "w").write(bad_text)
        doc2 = Doc(path)
        expect("integrity.use_resolves catches a dangling USE", not CHECKS["integrity"]({"k": "integrity", "what": "use_resolves"}, doc2, env).ok)
        expect("integrity.interp_valid catches a short keyValue", not CHECKS["integrity"]({"k": "integrity", "what": "interp_valid"}, doc2, env).ok)
        expect("diag check", CHECKS["diag"]({"k": "diag", "contains": "hello"}, doc, env).ok)
    print("self-test " + ("PASSED" if not fails else f"FAILED ({len(fails)}): {fails}"))
    return 0 if not fails else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate an exported X3D scene against the test-suite manifest.")
    ap.add_argument("target", nargs="?", help="output directory of x3d_test_suite.py, or the manifest .json")
    ap.add_argument("--profile", action="append", default=[], metavar="NAME=FILE", help="override an exported file, e.g. main=/tmp/x.x3d")
    ap.add_argument("--only", help="comma list of zone ids / case-id prefixes, e.g. Z04,Z11.spot")
    ap.add_argument("--tier", help="comma list: CORE,FIDELITY,ROADMAP")
    ap.add_argument("--json"); ap.add_argument("--html"); ap.add_argument("--md")
    ap.add_argument("--catalog", metavar="FILE.md", help="write the plain-English case catalogue from the manifest and exit")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--no-color", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.target:
        ap.error("target required (or --selftest)")
    mpath = a.target if a.target.endswith(".json") else os.path.join(a.target, "x3d_suite_manifest.json")
    if not os.path.exists(mpath):
        print(f"manifest not found: {mpath}", file=sys.stderr)
        return 2
    if a.catalog:
        write_catalog(mpath, a.catalog)
        print(f"catalogue -> {a.catalog}")
        return 0
    overrides = dict(p.split("=", 1) for p in a.profile)
    report = run(mpath, overrides, a.only.split(",") if a.only else None, a.tier.upper().split(",") if a.tier else None)
    print_console(report, a.verbose, tty=False if a.no_color else None)
    if a.json:
        write_json(report, a.json)
    if a.html:
        write_html(report, a.html)
    if a.md:
        write_markdown(report, a.md)
    c, _, _ = summarize(report)
    return 1 if (c.get("FAIL") or c.get("ERROR")) else 0


if __name__ == "__main__":
    sys.exit(main())
