"""Analysis half of the round-trip audit (plain Python + numpy, no Blender, no browser): node counts, the numeric colour
audit between an original X3D and the add-on's X3D 4.0 re-export, the glb baseColorFactor / COLOR_0 check, image deltas.

Colour model. Every colour is brought to one comparison space, "display sRGB" (what X_ITE 16.7.1 puts on screen from the
number): Material, TwoSidedMaterial and UnlitMaterial colours, and a Color node under any of them or under no material,
are already display sRGB; PhysicalMaterial colours, and a Color node under a PhysicalMaterial, are linear factors and are
encoded with the sRGB curve (measured 12 Nov 2026, X_ITE 16.7.1, see tests/test_colour_round_trip_bpy.py). The error
reported is the max over colours of |original - re-export| per channel in that space, 0..1, so a classic
Material diffuseColor 0.8 that comes back as PhysicalMaterial baseColor 0.6038 (linear) is an error of about 0.
"""
from __future__ import annotations

import json
import re
import struct
import xml.etree.ElementTree as ET
from collections import Counter

import numpy as np

CLASSIC_FIELDS = {
    "Material": ("diffuseColor", "emissiveColor", "specularColor"),
    "TwoSidedMaterial": ("diffuseColor", "emissiveColor", "specularColor", "backDiffuseColor", "backEmissiveColor",
                         "backSpecularColor"),
    "UnlitMaterial": ("emissiveColor",),
    "PhysicalMaterial": ("baseColor", "emissiveColor"),
}
DEFAULTS = {  # X3D 4.0 field defaults (used when the attribute is absent, so a missing field is still compared)
    "diffuseColor": (0.8, 0.8, 0.8), "emissiveColor": (0.0, 0.0, 0.0), "specularColor": (0.0, 0.0, 0.0),
    "backDiffuseColor": (0.8, 0.8, 0.8), "backEmissiveColor": (0.0, 0.0, 0.0), "backSpecularColor": (0.0, 0.0, 0.0),
    "baseColor": (1.0, 1.0, 1.0),
}
UNLIT_EMISSIVE_DEFAULT = (1.0, 1.0, 1.0)
# which channel each field belongs to, so a classic diffuseColor is compared with a PhysicalMaterial baseColor
CHANNEL = {"diffuseColor": "base", "baseColor": "base", "emissiveColor": "emissive", "specularColor": "specular",
           "backDiffuseColor": "back-base", "backEmissiveColor": "back-emissive", "backSpecularColor": "back-specular"}
MATERIAL_TAGS = tuple(CLASSIC_FIELDS)
# geometry that draws only its emissive colour (a diffuse or base colour never shows; the glb writes such a Material as an unlit "_lines" material)
LINE_POINT_GEOMETRY = {"IndexedLineSet", "LineSet", "PointSet", "Polyline2D", "Polypoint2D", "Arc2D", "ArcClose2D", "Circle2D", "Disk2D"}


def srgb_to_linear(c):
    c = np.asarray(c, dtype=np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c):
    c = np.asarray(c, dtype=np.float64)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.maximum(c, 0.0) ** (1 / 2.4) - 0.055)


def floats(text):
    try:
        return [float(v) for v in (text or "").replace(",", " ").split()]
    except ValueError:
        return []


# ---------------------------------------------------------------- structure

def parse(path_or_text, text=False):
    return ET.fromstring(path_or_text) if text else ET.parse(path_or_text).getroot()


def node_counts(root):
    """Counter of element tags (the X3D wrapper elements head, meta, component and X3D itself are left out)."""
    skip = {"X3D", "head", "meta", "component", "unit", "Scene"}
    return Counter(e.tag for e in root.iter() if e.tag not in skip)


# Nodes the default X3D 4.0 export does not write, by design, with the reason and the way out. `lost` still lists them (the
# node really is absent from the re-export); `by_design` says which of those are known and why, so a reader does not take
# them for a defect.
BY_DESIGN = {
    "GaussianSplats": "X3D 4.0 has no GaussianSplats node, so the 4.0 export writes the splat centres as a PointSet (scale, "
                      "opacity and anisotropy are lost) and says so in a meta info; choose X3D Version 'X3D 4.1 draft "
                      "(GaussianSplats)' to write the node",
}


def count_diff(orig, re_):
    """Per tag: original count, re-export count. Lost = in the original and not in the re-export; `by_design` = the
    lost tags that are expected (BY_DESIGN), each with its reason."""
    rows = {t: (orig.get(t, 0), re_.get(t, 0)) for t in sorted(set(orig) | set(re_))}
    return dict(rows=rows,
                by_design={t: BY_DESIGN[t] for t, v in rows.items() if t in BY_DESIGN and v[0] > 0 and v[1] == 0},
                lost={t: v for t, v in rows.items() if v[0] > 0 and v[1] == 0},
                added={t: v for t, v in rows.items() if v[0] == 0 and v[1] > 0},
                reduced={t: v for t, v in rows.items() if 0 < v[1] < v[0]},
                increased={t: v for t, v in rows.items() if v[0] > 0 and v[1] > v[0]})


def _defs(root):
    d = {}
    for e in root.iter():
        name = e.get("DEF")
        if name and name not in d:
            d[name] = e
    return d


def _resolve(e, defs):
    seen = 0
    while e is not None and e.get("USE") and seen < 20:
        e = defs.get(e.get("USE"))
        seen += 1
    return e


def _shape_material(shape, defs):
    app = None
    for child in shape:
        if child.tag == "Appearance":
            app = _resolve(child, defs)
    if app is None:
        return None
    for child in app:
        if child.tag in MATERIAL_TAGS or (child.get("USE") and _resolve(child, defs) is not None
                                           and _resolve(child, defs).tag in MATERIAL_TAGS):
            return _resolve(child, defs)
    return None


def _display(rgb, convention):
    """Colour -> display sRGB triple. convention 'linear' (PhysicalMaterial) is encoded, 'display' is kept."""
    a = np.asarray(rgb, dtype=np.float64)
    return linear_to_srgb(a) if convention == "linear" else a


def material_colours(root):
    """Per Shape in document order: {class.field: (display rgb, raw rgb, convention)} for its material (defaults filled in),
    plus the Shape's vertex Color / ColorRGBA nodes. Returns a list of dicts: shape index, DEF, material class, colours, vertex."""
    defs = _defs(root)
    out = []
    for shape in root.iter("Shape"):
        mat = _shape_material(shape, defs)
        geometry = [_resolve(c, defs).tag for c in shape if c.tag not in ("Appearance", "Metadata*") and _resolve(c, defs) is not None]
        kind = "lines" if any(t in LINE_POINT_GEOMETRY for t in geometry) else "surface"
        entry = dict(def_=shape.get("DEF"), material=mat.tag if mat is not None else None, colours={}, vertex=[], kind=kind)
        convention = "display"
        if mat is not None:
            convention = "linear" if mat.tag == "PhysicalMaterial" else "display"
            for f in CLASSIC_FIELDS[mat.tag]:
                v = floats(mat.get(f))
                if len(v) < 3:
                    v = list(UNLIT_EMISSIVE_DEFAULT if (mat.tag == "UnlitMaterial" and f == "emissiveColor") else DEFAULTS[f])
                v = v[:3]
                entry["colours"][f"{mat.tag}.{f}"] = (_display(v, convention).tolist(), v, convention, CHANNEL[f])
        for node in shape.iter():
            n = _resolve(node, defs) if node.get("USE") else node
            if n is not None and n.tag in ("Color", "ColorRGBA") and n.get("color") and node is not shape:
                width = 4 if n.tag == "ColorRGBA" else 3
                vals = floats(n.get("color"))
                vals = vals[:len(vals) // width * width]
                if vals:
                    arr = np.asarray(vals, dtype=np.float64).reshape(-1, width)
                    arr = arr.copy()
                    arr[:, :3] = _display(arr[:, :3], convention)
                    entry["vertex"].append((n.tag, convention, arr))
        out.append(entry)
    return out


def _nearest(a, b, chunk=2048):
    """For each row of a (N x k) the Euclidean-free max-abs distance to the closest row of b (M x k): returns (N,) array."""
    if len(b) == 0:
        return np.full(len(a), np.inf)
    out = np.empty(len(a))
    for i in range(0, len(a), chunk):
        d = np.abs(a[i:i + chunk, None, :] - b[None, :, :]).max(axis=2)
        out[i:i + chunk] = d.min(axis=1)
    return out


def _unique(a, places=4, cap=20000):
    u = np.unique(np.round(a, places), axis=0)
    if len(u) > cap:   # keep an even subsample so a million-vertex mesh stays tractable
        u = u[np.linspace(0, len(u) - 1, cap).astype(int)]
    return u


def colour_audit(orig_root, re_root):
    """Numeric colour audit original -> re-export (display sRGB, see the module doc). Returns dict:
    fields: {class.field: dict(n, ordered_max_abs, ordered_n, hausdorff_max_abs, convention_change, dropped)}
    vertex: {node: dict(n_orig_unique, n_re_unique, orig_to_re_max, re_to_orig_max, orig_to_re_mean)}
    shapes: {orig, re, ordered (bool)}."""
    A, B = material_colours(orig_root), material_colours(re_root)
    ordered = len(A) == len(B)
    fields = {}
    re_by_channel = {}
    for e in B:
        for key, (disp, raw, conv, ch) in e["colours"].items():
            re_by_channel.setdefault(ch, []).append(disp)
    re_by_channel = {k: np.asarray(v) for k, v in re_by_channel.items()}
    for i, e in enumerate(A):
        for key, (disp, raw, conv, ch) in e["colours"].items():
            if e["kind"] == "lines" and ch != "emissive":
                continue   # a line or point set draws its emissive colour only
            f = fields.setdefault(key, dict(n=0, ordered_n=0, ordered_max_abs=0.0, hausdorff_max_abs=0.0, convention_change=Counter(),
                                            dropped=0, worst=None, _orig=[]))
            f["n"] += 1
            f["_orig"].append(disp)
            if ordered:
                partner = B[i]["colours"]
                match = next((v for k, v in partner.items() if v[3] == ch), None)
                if match is None:
                    f["dropped"] += 1
                else:
                    err = float(np.abs(np.asarray(disp) - np.asarray(match[0])).max())
                    f["ordered_n"] += 1
                    if err >= f["ordered_max_abs"]:
                        f["ordered_max_abs"] = err
                        f["worst"] = dict(shape=i, def_=e["def_"], orig=[round(x, 4) for x in disp], reexport=[round(x, 4) for x in match[0]],
                                          orig_raw=[round(x, 4) for x in raw], reexport_raw=[round(x, 4) for x in match[1]],
                                          reexport_class=B[i]["material"])
                    f["convention_change"][f"{conv}->{match[2]}"] += 1
    for key, f in fields.items():
        ch = key.split(".")[1]
        ch = CHANNEL[ch]
        orig = _unique(np.asarray(f.pop("_orig")), 7)
        re_ = _unique(re_by_channel[ch], 7) if ch in re_by_channel else np.zeros((0, 3))
        if len(re_) == 0:
            f["hausdorff_max_abs"] = None
            f["dropped"] = f["dropped"] or f["n"]
        else:
            f["hausdorff_max_abs"] = float(_nearest(orig, re_).max())
        f["convention_change"] = dict(f["convention_change"])
        for k in ("ordered_max_abs", "hausdorff_max_abs"):
            if f[k] is not None:
                f[k] = round(f[k], 7)
    # vertex colours: reordering and splitting are legal, so compare the sets of colours
    vertex = {}
    for tag in ("Color", "ColorRGBA"):
        oa = [arr for e in A for (t, c, arr) in e["vertex"] if t == tag]
        ra = [arr for e in B for (t, c, arr) in e["vertex"] if t in ("Color", "ColorRGBA")]
        if not oa:
            continue
        o = _unique(np.concatenate([a[:, :3] for a in oa]), 6)
        r = _unique(np.concatenate([a[:, :3] for a in ra]), 6) if ra else np.zeros((0, 3))
        d_or = _nearest(o, r) if len(r) else np.array([np.inf])
        d_ro = _nearest(r, o) if len(r) else np.array([np.inf])
        alpha = None
        if tag == "ColorRGBA" and ra and any(a.shape[1] == 4 for a in ra):
            oal = np.unique(np.round(np.concatenate([a[:, 3] for a in oa]), 3))
            ral = np.unique(np.round(np.concatenate([a[:, 3] for a in ra if a.shape[1] == 4]), 3))
            alpha = float(_nearest(oal[:, None], ral[:, None]).max())
        vertex[tag] = dict(nodes_orig=len(oa), nodes_re=len(ra), n_orig_unique=len(o), n_re_unique=len(r),
                           orig_to_re_max=round(float(d_or.max()), 7), orig_to_re_mean=round(float(d_or.mean()), 7),
                           re_to_orig_max=round(float(d_ro.max()), 7), alpha_orig_to_re_max=alpha)
    return dict(fields=fields, vertex=vertex, shapes=dict(orig=len(A), re=len(B), ordered=ordered),
                material_classes=dict(orig=dict(Counter(e["material"] for e in A)), re=dict(Counter(e["material"] for e in B))))


def aggregate_field_class(per_scene):
    """Merge colour_audit()['fields'] of many scenes into per field-class maxima (key: class.field)."""
    agg = {}
    for scene, audit in per_scene.items():
        for key, f in audit["fields"].items():
            a = agg.setdefault(key, dict(n=0, ordered_n=0, ordered_max_abs=None, hausdorff_max_abs=None, worst_scene=None, worst=None, dropped=0))
            a["n"] += f["n"]
            a["ordered_n"] += f["ordered_n"]
            a["dropped"] += f.get("dropped", 0)
            if f["ordered_n"] and (a["ordered_max_abs"] is None or f["ordered_max_abs"] >= a["ordered_max_abs"]):
                a["ordered_max_abs"], a["worst_scene"], a["worst"] = f["ordered_max_abs"], scene, f["worst"]
            if f["hausdorff_max_abs"] is not None:
                a["hausdorff_max_abs"] = max(a["hausdorff_max_abs"] or 0.0, f["hausdorff_max_abs"])
    return agg


# ---------------------------------------------------------------- glb

def read_glb(path):
    with open(path, "rb") as fh:
        data = fh.read()
    magic, version, length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF":
        raise ValueError("not a glb")
    off, js, binchunk = 12, None, b""
    while off < len(data):
        n, kind = struct.unpack_from("<I4s", data, off)
        body = data[off + 8: off + 8 + n]
        if kind == b"JSON":
            js = json.loads(body.decode("utf-8"))
        elif kind == b"BIN\x00":
            binchunk = body
        off += 8 + n
    return js, binchunk


_COMP = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
_NORM = {5121: 255.0, 5123: 65535.0, 5120: 127.0, 5122: 32767.0}


def accessor(js, binchunk, index):
    acc = js["accessors"][index]
    view = js["bufferViews"][acc["bufferView"]]
    fmt, size = _COMP[acc["componentType"]]
    n = _NCOMP[acc["type"]]
    stride = view.get("byteStride") or size * n
    base = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    arr = np.empty((acc["count"], n), dtype=np.float64)
    for i in range(acc["count"]):
        arr[i] = struct.unpack_from("<" + fmt * n, binchunk, base + i * stride)
    if acc.get("normalized"):
        arr /= _NORM[acc["componentType"]]
    return arr


def glb_colours(path):
    """{'base': (N,3) baseColorFactor rgb per material, 'emissive': (N,3), 'vertex': (M,4) COLOR_0 values (linear), 'alpha': ..., 'unlit': n}."""
    js, binchunk = read_glb(path)
    base, em, alpha, unlit_base = [], [], [], []
    unlit = 0
    for m in js.get("materials", []):
        p = m.get("pbrMetallicRoughness", {})
        f = p.get("baseColorFactor", [1, 1, 1, 1])
        base.append(f[:3]); alpha.append(f[3])
        em.append(m.get("emissiveFactor", [0, 0, 0]))
        if "KHR_materials_unlit" in m.get("extensions", {}):
            unlit += 1
            unlit_base.append(f[:3])
    vert = []
    for mesh in js.get("meshes", []):
        for prim in mesh.get("primitives", []):
            if "COLOR_0" in prim.get("attributes", {}):
                a = accessor(js, binchunk, prim["attributes"]["COLOR_0"])
                if a.shape[1] == 3:
                    a = np.hstack([a, np.ones((len(a), 1))])
                vert.append(a)
    return dict(base=np.asarray(base).reshape(-1, 3), emissive=np.asarray(em).reshape(-1, 3), alpha=np.asarray(alpha),
                unlit_base=np.asarray(unlit_base).reshape(-1, 3),
                vertex=np.concatenate(vert) if vert else np.zeros((0, 4)), unlit=unlit, materials=len(js.get("materials", [])),
                extensions=js.get("extensionsUsed", []))


def glb_audit(orig_root, glb_path):
    """baseColorFactor / emissiveFactor / COLOR_0 in the glb against the original colour converted to linear: classic and
    Unlit colours go sRGB -> linear, PhysicalMaterial colours are already linear. Max abs error over originals of the
    nearest glb value (reorder-safe). Not-found means the glb has no value within the printed distance."""
    g = glb_colours(glb_path)
    A = material_colours(orig_root)
    want = {"base": [], "emissive": [], "unlit": []}
    for e in A:
        for key, (disp, raw, conv, ch) in e["colours"].items():
            lin = raw if conv == "linear" else srgb_to_linear(raw).tolist()
            if key == "UnlitMaterial.emissiveColor" or (e["kind"] == "lines" and ch == "emissive"):
                want["unlit"].append(lin)   # KHR_materials_unlit shows baseColorFactor: the glb carries an Unlit or line colour there
            elif e["kind"] == "lines":
                continue   # a diffuse / base colour that a line or point set never shows
            elif ch in want:
                want[ch].append(lin)
    out = dict(materials=g["materials"], unlit_materials=g["unlit"], extensions=g["extensions"])
    for ch in ("base", "emissive", "unlit"):
        w = _unique(np.asarray(want[ch]).reshape(-1, 3), 7) if want[ch] else np.zeros((0, 3))
        pool = g["emissive"] if ch == "emissive" else g["base"]
        if ch == "unlit":
            pool = np.concatenate([g["base"], g["emissive"]])   # an Unlit or line colour may sit in either place
        have = _unique(pool, 7) if len(pool) else np.zeros((0, 3))
        out[ch] = dict(n_orig_unique=len(w), n_glb_unique=len(have),
                       orig_to_glb_max=(round(float(_nearest(w, have).max()), 7) if len(w) and len(have) else None))
    vexp = [srgb_to_linear(arr[:, :3]) for e in A for (t, conv, arr) in e["vertex"]]
    if vexp:
        w = _unique(np.concatenate(vexp), 4)
        have = _unique(g["vertex"][:, :3], 4) if len(g["vertex"]) else np.zeros((0, 3))
        out["vertex"] = dict(n_orig_unique=len(w), n_glb_unique=len(have), glb_accessors_vertices=int(len(g["vertex"])),
                             orig_to_glb_max=(round(float(_nearest(w, have).max()), 7) if len(have) else None))
    return out


# ---------------------------------------------------------------- images

def image_deltas(a, b):
    """a, b: HxWx3 float arrays 0..255. Whole-frame mean |delta|, the share of pixels with any channel off by more than 16,
    and the mean over 'foreground' pixels (pixels that differ from the frame's own border-median colour in either image)."""
    d = np.abs(a - b)
    def fg(img):
        border = np.concatenate([img[0], img[-1], img[:, 0], img[:, -1]])
        bg = np.median(border, axis=0)
        return np.abs(img - bg).max(axis=2) > 6
    mask = fg(a) | fg(b)
    return dict(mean_abs_delta=round(float(d.mean()), 3), share_gt16=round(float((d.max(axis=2) > 16).mean()), 4),
                foreground_share=round(float(mask.mean()), 3),
                foreground_delta=(round(float(d[mask].mean()), 3) if mask.any() else None),
                max_abs=float(d.max()))


def flip_mean(a, b):
    """Mean FLIP error (flip-evaluator 1.7, LDR, 67 ppd) of test b against reference a; HxWx3 arrays 0..255."""
    import flip_evaluator as flip
    _, mean, _ = flip.evaluate((a / 255.0).astype(np.float32), (b / 255.0).astype(np.float32), "LDR", applyMagma=False)
    return round(float(mean), 5)


def viewpoint_pose(root):
    """(position, forward, up, fov) of the first Viewpoint in world space (same convention as compare.first_viewpoint:
    Transform chain above the Viewpoint applied), or None."""
    parents = {c: p for p in root.iter() for c in p}
    vp = next((e for e in root.iter() if e.tag == "Viewpoint"), None)
    if vp is None:
        return None
    def rot(v):
        x, y, z, a = (v + [0, 0, 1, 0])[:4] if len(v) < 4 else v[:4]
        n = np.linalg.norm([x, y, z]) or 1.0
        x, y, z = x / n, y / n, z / n
        c, s, C = np.cos(a), np.sin(a), 1 - np.cos(a)
        return np.array([[c + x*x*C, x*y*C - z*s, x*z*C + y*s], [y*x*C + z*s, c + y*y*C, y*z*C - x*s], [z*x*C - y*s, z*y*C + x*s, c + z*z*C]])
    chain, node = [], parents.get(vp)
    while node is not None:
        if node.tag == "Transform":
            chain.append(node)
        node = parents.get(node)
    M = np.eye(4)
    for t in reversed(chain):
        T = np.eye(4); T[:3, 3] = (floats(t.get("translation")) + [0, 0, 0])[:3] if floats(t.get("translation")) else [0, 0, 0]
        R = np.eye(4); R[:3, :3] = rot(floats(t.get("rotation")) or [0, 0, 1, 0])
        S = np.diag((floats(t.get("scale")) or [1, 1, 1])[:3] + [1])
        C = np.eye(4); C[:3, 3] = (floats(t.get("center")) or [0, 0, 0])[:3]
        SR = np.eye(4); SR[:3, :3] = rot(floats(t.get("scaleOrientation")) or [0, 0, 1, 0])
        M = M @ T @ C @ R @ SR @ S @ np.linalg.inv(SR) @ np.linalg.inv(C)
    pos = np.array((floats(vp.get("position")) or [0, 0, 10])[:3] + [1.0])
    r = M[:3, :3] @ rot(floats(vp.get("orientation")) or [0, 0, 1, 0])
    r = r / np.linalg.norm(r, axis=0)
    return dict(position=(M @ pos)[:3].tolist(), forward=(-r[:, 2]).tolist(), up=r[:, 1].tolist(),
                fov=(floats(vp.get("fieldOfView")) or [0.785398])[0])


def pose_difference(a, b):
    if a is None or b is None:
        return None
    return dict(position=round(float(np.linalg.norm(np.subtract(a["position"], b["position"]))), 5),
                forward_deg=round(float(np.degrees(np.arccos(np.clip(np.dot(a["forward"], b["forward"]), -1, 1)))), 4),
                up_deg=round(float(np.degrees(np.arccos(np.clip(np.dot(a["up"], b["up"]), -1, 1)))), 4),
                fov=round(abs(a["fov"] - b["fov"]), 6))
