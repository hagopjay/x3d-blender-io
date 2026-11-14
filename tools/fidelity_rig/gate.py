"""Export gate: every Blender export of the add-on is checked against the Khronos glTF Validator and against X_ITE.

For each scene of one or more scenes JSONs (same format as probes.json; paths relative to this folder) one command runs both
exports of the add-on and compares the result with gate-baseline.json:

  A. glb leg  (blender_leg.py -> Khronos glTF Validator -> Babylon.js on the glb, X_ITE on the X3D; the compare.py pieces)
  B. X3D leg  (roundtrip_leg.py: import with defaults, export X3D 4.0 with defaults -> source/validate.py + x3d.py ->
               X_ITE on the original and on the re-export; the roundtrip.py pieces)

and prints PASS / FAIL per scene with the reasons. Five checks per scene:
  validator        glTF-Validator errors == 0 and warnings <= baseline (a scene with no glb fails)
  glb_content      the glb is not EMPTY: the validator accepts an empty glb, so triangles > 0 when the X3D has surfaces, points or
                   lines when it has only those; a points-only or lines-only glb is classified separately; a known empty glb needs
                   an "allow_empty" entry with a written reason; triangles, points and lines primitives must not fall below the baseline by more than the tolerance
  geometry_delta   Babylon.js-on-glb against X_ITE-on-X3D mean |delta| over the pixels Babylon.js drew <= baseline + tolerance; what
                   Babylon.js did NOT draw is gated too (the delta cannot see it): the share of the frame it covers must not fall below
                   the baseline's, and the share where X_ITE shows foreground (a mask taken from X_ITE's own render) while Babylon.js
                   shows only its clear colour must not rise above the baseline's; a VACUOUS render (X_ITE's render of the original
                   shows only background, or Babylon.js draws nothing of the glb) fails unless the baseline entry has an "allow_blank" entry
                   with a written reason
  reexport         the re-export is well-formed, x3d.py reports 0 errors, the number of node types lost <= baseline
  roundtrip_delta  X_ITE on the original against X_ITE on the re-export: mean |delta| (0-255) and FLIP <= baseline + tolerance (a FLIP
                   that could not be computed fails when the baseline has one; an all-background render is vacuous, as above)
Tolerance rule (written in the baseline header): allowed = baseline + max(abs, rel * baseline). A measurement better than the
baseline by more than the same margin is reported as IMPROVED so the baseline can be tightened.

Usage (from this folder, after `npm install`; BPY_PYTHON is a Python with bpy):
    python3 gate.py [--scenes probes.json scenes-repo.json ...] [--only a,b] [--json out.json]        check, exit 1 on any FAIL
    python3 gate.py --scenes ... --update-baseline [--allow-worse]                                    rewrite measured values
Results are written to out/LABEL/gate_results.json before the exit code is decided. See README.md ("Export gate").
Measured with the rig named in the baseline header (X_ITE 16.7.1, Babylon.js 9.32.0, Chromium 153 SwiftShader, Blender 5.3.0,
gltf-validator 2.0.0-dev.3.10, flip-evaluator 1.7)."""
from __future__ import annotations

import argparse
import json
import os
import re
import struct
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

RIG = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RIG)

BASELINE_SCHEMA = "x3d-blender-io.gate-baseline/v1"
RESULTS_SCHEMA = "x3d-blender-io.gate-results/v1"
DEFAULT_BASELINE = os.path.join(RIG, "gate-baseline.json")
DEFAULT_TOLERANCE = {
    "image_delta": {"abs": 0.5, "rel": 0.05},   # mean |delta| of two renders, 0-255
    "flip": {"abs": 0.01, "rel": 0.05},         # mean FLIP, 0-1
    "triangles": {"rel": 0.01},                  # the glb may lose at most this share of the baseline's triangles (and points / lines
                                                 # primitives): the counts are deterministic for one Blender, so this only absorbs noise
    "geometry_share": {"abs": 0.002, "rel": 0.10},   # the share of the frame Babylon.js covers with the glb may fall by at most this, and the
                                                     # share where X_ITE draws and Babylon.js shows only its clear colour may rise by at most this
}
CHECKS = ("validator", "glb_content", "geometry_delta", "reexport", "roundtrip_delta")
STATUS_FAIL, STATUS_PASS, STATUS_IMPROVED, STATUS_SKIP = "FAIL", "PASS", "IMPROVED", "SKIP"
MOVE_EPS = 0.01          # an update ignores a float that moved by less than this (re-render noise), so a rerun does not churn the file

SURFACE_TAGS = {
    "Box", "Cone", "Cylinder", "Sphere", "IndexedFaceSet", "IndexedTriangleSet", "TriangleSet", "IndexedTriangleFanSet",
    "IndexedTriangleStripSet", "TriangleFanSet", "TriangleStripSet", "IndexedQuadSet", "QuadSet", "ElevationGrid",
    "GeoElevationGrid", "Extrusion", "Rectangle2D", "TriangleSet2D", "Disk2D", "Text", "NurbsPatchSurface",
    "NurbsTrimmedSurface", "NurbsSweptSurface", "NurbsSwungSurface", "GeoElevationGrid", "Teapot"}
LINE_TAGS = {"IndexedLineSet", "LineSet", "Polyline2D", "Arc2D", "ArcClose2D", "Circle2D", "NurbsCurve", "NurbsCurve2D"}
POINT_TAGS = {"PointSet", "Polypoint2D", "GeoPoint"}
SPLAT_TAGS = {"GaussianSplats"}


# ------------------------------------------------------------------ pure logic (no Blender, no browser)

def allowed_max(base, rule):
    """Highest value that still passes: base + max(abs, rel * base)."""
    return base + max(rule.get("abs", 0.0), rule.get("rel", 0.0) * abs(base))


def improved_below(base, rule):
    """A value under this is better than the baseline by more than the tolerance (IMPROVED)."""
    return base - max(rule.get("abs", 0.0), rule.get("rel", 0.0) * abs(base))


def classify_glb(triangles, points, lines):
    """triangles: the validator's totalTriangleCount; points / lines: primitives drawn as points / lines in the glb."""
    if triangles and triangles > 0:
        return "triangles"
    if points and lines:
        return "points+lines"
    if points:
        return "points"
    if lines:
        return "lines"
    return "empty"


def glb_primitive_counts(glb_path):
    """(points, lines, triangles) primitive counts from a .glb's JSON chunk (mode 0 points, 1-3 lines, 4-6 triangles)."""
    with open(glb_path, "rb") as f:
        head = f.read(12)
        if len(head) < 12 or head[:4] != b"glTF":
            raise ValueError("not a glb")
        clen, ctype = struct.unpack("<II", f.read(8))
        if ctype != 0x4E4F534A:
            raise ValueError("first glb chunk is not JSON")
        js = json.loads(f.read(clen).decode("utf-8"))
    points = lines = tris = 0
    for mesh in js.get("meshes", []):
        for prim in mesh.get("primitives", []):
            mode = prim.get("mode", 4)
            if mode == 0:
                points += 1
            elif mode in (1, 2, 3):
                lines += 1
            else:
                tris += 1
    return points, lines, tris


def x3d_renderables(path, _depth=0, _seen=None):
    """Which kinds of geometry an X3D file holds: {"surface", "lines", "points", "splats"} booleans. Inline files are followed
    (three levels deep); ProtoDeclare bodies are not counted."""
    kinds = dict(surface=False, lines=False, points=False, splats=False)
    _seen = _seen if _seen is not None else set()
    real = os.path.realpath(path)
    if real in _seen or _depth > 3 or not os.path.exists(path):
        return kinds
    _seen.add(real)
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return kinds   # a classic-encoded or broken file: no claim
    skip = set()
    for decl in root.iter("ProtoDeclare"):
        skip.update(id(e) for e in decl.iter())
    for e in root.iter():
        if id(e) in skip:
            continue
        tag = e.tag
        if tag in SURFACE_TAGS:
            kinds["surface"] = True
        elif tag in LINE_TAGS:
            kinds["lines"] = True
        elif tag in POINT_TAGS:
            kinds["points"] = True
        elif tag in SPLAT_TAGS:
            kinds["splats"] = True
        elif tag == "Inline" and (e.get("load") or "true").lower() != "false":
            for u in re.findall(r'"([^"]*)"', e.get("url") or "") or [(e.get("url") or "").strip()]:
                if u and "://" not in u and not u.startswith("data:"):
                    sub = x3d_renderables(os.path.join(os.path.dirname(path), u.split("#")[0]), _depth + 1, _seen)
                    for k, v in sub.items():
                        kinds[k] = kinds[k] or v
                    break
    return kinds


def describe_kinds(kinds):
    names = [k for k in ("surface", "lines", "points", "splats") if kinds.get(k)]
    return "+".join(names) if names else "nothing"


def rule_for(entry, tol, check, kind):
    """The tolerance rule for `check` of this scene: the baseline header's rule for `kind` ("image_delta" or "flip"), overridden
    per scene by entry["tolerance"][check] (animated scenes are sampled at run-dependent moments; the override carries a reason)."""
    rule = dict(tol[kind])
    over = ((entry or {}).get("tolerance") or {}).get(check)
    if over and kind == "image_delta":
        rule.update(over)
    return rule


def share_rule(entry, tol):
    """The tolerance rule for the frame-share checks of geometry_delta (what Babylon.js covers, what it leaves empty where X_ITE draws):
    the baseline header's, overridden per scene by entry["tolerance"]["geometry_share"] (animated scenes cover a run-dependent share)."""
    rule = dict(tol["geometry_share"])
    rule.update(((entry or {}).get("tolerance") or {}).get("geometry_share") or {})
    return rule


def _known_for(entry, check):
    return [k["defect"] for k in (entry or {}).get("known", []) if check in k.get("checks", [])]


def _result(check, status, detail, entry):
    return dict(check=check, status=status, detail=detail, known=_known_for(entry, check))


def _skip_reason(entry, check):
    return ((entry or {}).get("skip") or {}).get(check)


def _allow_blank(entry):
    """The written reason that lets the render checks of a scene measure nothing (all-background X_ITE render, or Babylon.js
    drawing nothing of the glb): an allow_blank entry, or an allow_empty one (an empty glb has nothing to draw)."""
    e = entry or {}
    return ((e.get("allow_blank") or {}).get("reason") or (e.get("allow_empty") or {}).get("reason"))


def vacuous_renders(m):
    """{"geometry_delta": why, "roundtrip_delta": why} for the render checks that cannot measure anything in this measurement:
    X_ITE's render of the original shows only its background (xite_foreground_share == 0), or Babylon.js drew no pixel of the glb
    (geometry_delta None). A check that passes on such a render passes without looking at anything."""
    out = {}
    xblank = m.get("xite_foreground_share") == 0
    if m.get("glb_leg", {}).get("ok") and m.get("glb_render_ok"):
        nt = (m.get("glb") or {}).get("triangles", 0)
        if xblank and m.get("geometry_delta") is None:
            out["geometry_delta"] = "X_ITE and Babylon.js both render only the background"
        elif xblank:
            out["geometry_delta"] = "X_ITE renders only the background"
        elif m.get("geometry_delta") is None:
            out["geometry_delta"] = "Babylon.js draws no geometry" + (f" (the glb holds {nt} triangles that Babylon.js did not draw)" if nt else "")
    if m.get("reexport", {}).get("leg_ok") and (m.get("roundtrip") or {}).get("render_ok") and xblank:
        out["roundtrip_delta"] = "X_ITE renders only the background, so both renders are identical by construction"
    return out


def evaluate_scene(m, entry, tol):
    """Compare one scene's measurements `m` with its baseline `entry` (None when the scene has none).
    Returns a list of {check, status, detail, known}. m's shape is documented in measure_scene()."""
    out = []
    base = entry or {}
    glb_ok = m.get("glb_leg", {}).get("ok", False)
    re_ok = m.get("reexport", {}).get("leg_ok", False)

    # 1. validator
    chk = "validator"
    sk = _skip_reason(entry, chk)
    v = m.get("validator") or {}
    if sk and not glb_ok:
        out.append(_result(chk, STATUS_SKIP, f"no glb, baseline reason: {sk}", entry))
    elif not glb_ok:
        out.append(_result(chk, STATUS_FAIL, "no glb: " + (m.get("glb_leg", {}).get("error") or "the Blender glb leg failed")[:300], entry))
    elif not v.get("ok_ran", True):
        out.append(_result(chk, STATUS_FAIL, "validator did not run: " + str(v.get("error"))[:300], entry))
    else:
        why = []
        if v["errors"] > 0:
            why.append(f"{v['errors']} validator errors")
        bw = (base.get("validator") or {}).get("warnings")
        if entry is not None and bw is not None and v["warnings"] > bw:
            why.append(f"{v['warnings']} warnings > baseline {bw}")
        if why:
            out.append(_result(chk, STATUS_FAIL, ", ".join(why), entry))
        elif bw is not None and v["warnings"] < bw:
            out.append(_result(chk, STATUS_IMPROVED, f"{v['warnings']} warnings < baseline {bw}", entry))
        else:
            out.append(_result(chk, STATUS_PASS, f"{v['errors']}E {v['warnings']}W", entry))

    # 2. glb content
    chk = "glb_content"
    g = m.get("glb") or {}
    kinds = m.get("x3d") or {}
    if not glb_ok:
        out.append(_result(chk, STATUS_SKIP, "no glb", entry))
    else:
        cls, tris = g.get("class", "empty"), g.get("triangles", 0)
        has_any = any(kinds.get(k) for k in ("surface", "lines", "points", "splats"))
        has_surface = kinds.get("surface", False)
        allow = (base.get("allow_empty") or {}).get("reason")
        problem = None
        if cls == "empty" and has_any:
            problem = f"EMPTY glb (the validator accepts it) but the X3D has {describe_kinds(kinds)}"
        elif cls in ("points", "lines", "points+lines") and has_surface:
            problem = f"{cls}-only glb (0 triangles) but the X3D has surfaces"
        if problem and allow:
            out.append(_result(chk, STATUS_PASS, f"{problem}; allowed: {allow}", entry))
        elif problem:
            out.append(_result(chk, STATUS_FAIL, problem, entry))
        else:
            detail = f"{cls}, {tris} triangles" if cls == "triangles" else (
                f"{cls}-only glb, X3D has {describe_kinds(kinds)}" if cls != "empty" else "empty glb, X3D has nothing renderable")
            btris = (base.get("glb") or {}).get("triangles")
            st = STATUS_PASS
            if allow:
                st, detail = STATUS_IMPROVED, detail + "; the allow_empty entry is no longer needed"
            elif cls == "triangles" and btris and tris < btris * (1 - tol["triangles"]["rel"]):
                st, detail = STATUS_FAIL, f"{tris} triangles < baseline {btris} by more than {tol['triangles']['rel']:.0%}"
            else:   # a glb that loses its points or lines but keeps its triangles is still the same class
                lost = [f"{g.get(k, 0)} {k} primitives < baseline {(base.get('glb') or {}).get(k)}" for k in ("points", "lines")
                        if (base.get("glb") or {}).get(k) and g.get(k, 0) < (base.get("glb") or {})[k] * (1 - tol["triangles"]["rel"])]
                if lost:
                    st, detail = STATUS_FAIL, "; ".join(lost)
            out.append(_result(chk, st, detail, entry))

    # 3. geometry delta (Babylon on the glb against X_ITE on the X3D)
    chk = "geometry_delta"
    sk = _skip_reason(entry, chk)
    gd = m.get("geometry_delta")
    if not glb_ok:
        out.append(_result(chk, STATUS_SKIP, "no glb", entry))
    elif sk:   # a skip entry (with its written reason) takes the check out of the gate; the measurement is still reported
        out.append(_result(chk, STATUS_SKIP, f"not gated ({sk}); measured {gd}", entry))
    elif not m.get("glb_render_ok", False):
        out.append(_result(chk, STATUS_FAIL, "X_ITE or Babylon.js render missing", entry))
    elif entry is None:
        out.append(_result(chk, STATUS_SKIP, f"measured {gd}, no baseline", entry))
    else:
        bg = base.get("geometry_delta")
        vac = vacuous_renders(m).get(chk)
        allow_blank = _allow_blank(entry)
        if gd is None and bg is not None:
            out.append(_result(chk, STATUS_FAIL, f"no geometry visible in Babylon.js (baseline {bg})", entry))
        elif vac and allow_blank:
            out.append(_result(chk, STATUS_PASS, f"not measured: {vac}; allowed: {allow_blank}", entry))
        elif vac:
            out.append(_result(chk, STATUS_FAIL, f"vacuous render, nothing was measured: {vac}. Fix the render, or record an "
                               "allow_blank entry with a written reason in the baseline", entry))
        else:
            b = bg if bg is not None else 0.0
            rule = rule_for(entry, tol, chk, "image_delta")
            lim = allowed_max(b, rule)
            srule = share_rule(entry, tol)
            bs, gs = base.get("geometry_share"), m.get("geometry_share")
            share_floor = improved_below(bs, srule) if bs is not None else None
            bm, gm = base.get("geometry_missing_share"), m.get("geometry_missing_share")
            missing_ceiling = allowed_max(bm, srule) if bm is not None else None
            if gd > lim:
                out.append(_result(chk, STATUS_FAIL, f"{gd} > baseline {bg} + tolerance (limit {lim:.2f})", entry))
            elif share_floor is not None and gs is not None and gs < share_floor:
                out.append(_result(chk, STATUS_FAIL, f"Babylon.js covers {gs} of the frame < baseline {bs} (floor {share_floor:.3f}): "
                                   "geometry of the glb is missing, which the delta over the drawn pixels cannot see", entry))
            elif missing_ceiling is not None and gm is not None and gm > missing_ceiling:
                out.append(_result(chk, STATUS_FAIL, f"X_ITE draws {gm} of the frame where Babylon.js shows only its clear colour > baseline {bm} "
                                   f"(limit {missing_ceiling:.3f}): geometry of the glb is missing, which the delta over the drawn pixels cannot see", entry))
            elif gd < improved_below(b, rule):
                out.append(_result(chk, STATUS_IMPROVED, f"{gd} < baseline {bg}", entry))
            else:
                out.append(_result(chk, STATUS_PASS, f"{gd} (baseline {bg}, limit {lim:.2f})", entry))

    # 4. re-export
    chk = "reexport"
    r = m.get("reexport") or {}
    sk = _skip_reason(entry, chk)
    if not re_ok:
        if sk:
            out.append(_result(chk, STATUS_SKIP, f"no re-export, baseline reason: {sk}", entry))
        else:
            out.append(_result(chk, STATUS_FAIL, "no re-export: " + (r.get("error") or "the X3D leg failed")[:300], entry))
    else:
        why = []
        if not r.get("well_formed"):
            why.append("not well-formed X3D: " + "; ".join(r.get("structural_errors") or [])[:200])
        xp = r.get("x3d_py")
        if xp is None:
            why.append("x3d.py not installed (pip install x3d) so the re-export was not validated")
        elif r.get("x3d_py_errors", 0) > 0:
            why.append(f"x3d.py reports {r['x3d_py_errors']} errors")
        elif xp != "ok":
            why.append(f"x3d.py check failed: {xp}")
        bl = (base.get("reexport") or {}).get("nodes_lost")
        lost = r.get("nodes_lost", 0)
        if entry is not None and bl is not None and lost > bl:
            why.append(f"{lost} node types lost > baseline {bl} ({', '.join(r.get('lost_types') or [])})")
        if why:
            out.append(_result(chk, STATUS_FAIL, "; ".join(why), entry))
        elif bl is not None and lost < bl:
            out.append(_result(chk, STATUS_IMPROVED, f"{lost} node types lost < baseline {bl}", entry))
        else:
            out.append(_result(chk, STATUS_PASS, f"well-formed, x3d.py 0 errors, {lost} node types lost"
                               + (f" ({', '.join(r.get('lost_types') or [])})" if lost else ""), entry))

    # 5. X_ITE original vs X_ITE re-export
    chk = "roundtrip_delta"
    sk = _skip_reason(entry, chk)
    rt = m.get("roundtrip") or {}
    if not re_ok:
        out.append(_result(chk, STATUS_SKIP, "no re-export", entry))
    elif sk:
        out.append(_result(chk, STATUS_SKIP, f"not gated ({sk}); measured mean|delta| {rt.get('mean_abs_delta')}, FLIP {rt.get('flip')}", entry))
    elif not rt.get("render_ok"):
        out.append(_result(chk, STATUS_FAIL, "X_ITE render of the original or the re-export missing", entry))
    elif entry is None:
        out.append(_result(chk, STATUS_SKIP, f"measured mean|delta| {rt['mean_abs_delta']}, FLIP {rt.get('flip')}, no baseline", entry))
    elif vacuous_renders(m).get(chk) and _allow_blank(entry):
        out.append(_result(chk, STATUS_PASS, f"not measured: {vacuous_renders(m)[chk]}; allowed: {_allow_blank(entry)}", entry))
    elif vacuous_renders(m).get(chk):
        out.append(_result(chk, STATUS_FAIL, f"vacuous render, nothing was measured: {vacuous_renders(m)[chk]}. Fix the render, or record "
                           "an allow_blank entry with a written reason in the baseline", entry))
    else:
        bd = (base.get("roundtrip") or {}).get("mean_abs_delta")
        bf = (base.get("roundtrip") or {}).get("flip")
        d, f = rt["mean_abs_delta"], rt.get("flip")
        why, better = [], []
        b0 = bd if bd is not None else 0.0
        rule = rule_for(entry, tol, chk, "image_delta")
        if d > allowed_max(b0, rule):
            why.append(f"mean|delta| {d} > baseline {bd} + tolerance (limit {allowed_max(b0, rule):.2f})")
        elif bd is not None and d < improved_below(bd, rule):
            better.append(f"mean|delta| {d} < baseline {bd}")
        if f is None and bf is not None:   # a FLIP that could not be computed must not switch its gate off
            why.append(f"FLIP not measured ({rt.get('flip_error') or 'no value'}) but the baseline has FLIP {bf}")
        if f is not None:
            f0 = bf if bf is not None else 0.0
            if f > allowed_max(f0, tol["flip"]):
                why.append(f"FLIP {f} > baseline {bf} + tolerance (limit {allowed_max(f0, tol['flip']):.4f})")
            elif bf is not None and f < improved_below(bf, tol["flip"]):
                better.append(f"FLIP {f} < baseline {bf}")
        if why:
            out.append(_result(chk, STATUS_FAIL, "; ".join(why), entry))
        elif better:
            out.append(_result(chk, STATUS_IMPROVED, "; ".join(better), entry))
        else:
            out.append(_result(chk, STATUS_PASS, f"mean|delta| {d} (baseline {bd}), FLIP {f} (baseline {bf})", entry))

    if entry is None:
        out.append(dict(check="baseline", status=STATUS_FAIL, detail="no baseline entry for this scene (run with --update-baseline)", known=[]))
    elif (entry.get("allow_blank") and glb_ok and re_ok and m.get("glb_render_ok") and rt.get("render_ok") and not vacuous_renders(m)):
        out.append(dict(check="baseline", status=STATUS_IMPROVED, known=[],
                        detail="the allow_blank entry is no longer needed: both renders show geometry now"))
    return out


def scene_verdict(results):
    if any(r["status"] == STATUS_FAIL for r in results):
        return "FAIL"
    return "IMPROVED" if any(r["status"] == STATUS_IMPROVED for r in results) else "PASS"


def lint_baseline(baseline):
    """Problems with the baseline file itself: the tolerance header must be the code's rules (a loosened header is a loosened gate,
    and a PR that edits it must edit the code constant too); an allow_empty / allow_blank / skip / known entry needs a written reason (an
    update that had to invent one writes UNEXPLAINED, which fails here until a person replaces it)."""
    problems = []
    if baseline.get("tolerance") not in (None, DEFAULT_TOLERANCE):
        problems.append("tolerance header differs from gate.DEFAULT_TOLERANCE (a baseline cannot loosen the rules; change the code constant in review)")
    for name, e in sorted((baseline.get("scenes") or {}).items()):
        reasons = ([("allow_empty", (e.get("allow_empty") or {}).get("reason"))] if "allow_empty" in e else []) + \
            ([("allow_blank", (e.get("allow_blank") or {}).get("reason"))] if "allow_blank" in e else []) + \
            [(f"skip.{k}", v) for k, v in (e.get("skip") or {}).items()] + \
            [(f"known {k.get('defect')}", k.get("reason")) for k in e.get("known", [])]
        for what, reason in reasons:
            if not reason or not str(reason).strip():
                problems.append(f"{name}: {what} has no reason")
            elif str(reason).upper().startswith("UNEXPLAINED"):
                problems.append(f"{name}: {what} reason is still UNEXPLAINED, write one")
        for k in e.get("known", []):
            if not re.fullmatch(r"[DH]\d+", str(k.get("defect", ""))):
                problems.append(f"{name}: known entry has no defect id like D4 ({k.get('defect')!r})")
            for c in k.get("checks", []):
                if c not in CHECKS:
                    problems.append(f"{name}: known {k.get('defect')} names an unknown check {c!r}")
        for c in (e.get("skip") or {}):
            if c not in CHECKS:
                problems.append(f"{name}: skip names an unknown check {c!r}")
        over = e.get("tolerance")
        if over is not None:
            if not str(over.get("reason", "")).strip():
                problems.append(f"{name}: tolerance override has no reason")
            elif str(over["reason"]).upper().startswith("UNEXPLAINED"):
                problems.append(f"{name}: tolerance override reason is still UNEXPLAINED, write one")
            for c in over:
                if c != "reason" and c not in ("geometry_delta", "roundtrip_delta", "geometry_share"):
                    problems.append(f"{name}: tolerance override names {c!r}; only geometry_delta, roundtrip_delta and geometry_share can be overridden")
    return problems


def baseline_entry_from(m):
    """The baseline values a clean measurement would record (no known / skip / allow_empty: those are written by people)."""
    e = {}
    if m.get("glb_leg", {}).get("ok") and m.get("validator", {}).get("ok_ran", True):
        e["validator"] = dict(warnings=m["validator"]["warnings"])
        e["glb"] = dict(**{"class": m["glb"]["class"]}, triangles=m["glb"]["triangles"],
                        **{k: m["glb"][k] for k in ("points", "lines") if m["glb"].get(k) is not None})
        if m.get("glb_render_ok"):
            e["geometry_delta"] = m.get("geometry_delta")
            for k in ("geometry_share", "geometry_missing_share"):
                if m.get(k) is not None:
                    e[k] = m[k]
    r = m.get("reexport") or {}
    if r.get("leg_ok"):
        e["reexport"] = dict(nodes_lost=r["nodes_lost"])
        rt = m.get("roundtrip") or {}
        if rt.get("render_ok"):
            e["roundtrip"] = dict(mean_abs_delta=rt["mean_abs_delta"], **({"flip": rt["flip"]} if rt.get("flip") is not None else {}))
    return e


def hard_failures(m, entry=None):
    """Things a baseline must never absorb: the update refuses to record them (the check mode fails them whatever the baseline says).
    `entry` (the scene's current baseline entry, if any) supplies the written exceptions: skip and allow_blank / allow_empty."""
    why = []
    skip = (entry or {}).get("skip") or {}
    if m.get("glb_leg", {}).get("ok"):
        v = m.get("validator") or {}
        if not v.get("ok_ran", True):
            why.append("validator did not run")
        elif v.get("errors", 0) > 0:
            why.append(f"{v['errors']} glTF validator errors")
        g, kinds = m.get("glb") or {}, m.get("x3d") or {}
        allowed_empty = bool(((entry or {}).get("allow_empty") or {}).get("reason"))   # written down by a person: the gate passes it too
        if allowed_empty:
            pass
        elif g.get("class") == "empty" and any(kinds.get(k) for k in ("surface", "lines", "points", "splats")):
            why.append(f"EMPTY glb (X3D has {describe_kinds(kinds)})")
        elif g.get("class") in ("points", "lines", "points+lines") and kinds.get("surface"):
            why.append(f"{g['class']}-only glb (X3D has surfaces)")
        if "geometry_delta" not in skip:
            if not m.get("glb_render_ok"):
                why.append("render missing (X_ITE or Babylon.js)")
            elif "geometry_delta" in vacuous_renders(m) and not _allow_blank(entry):
                why.append("VACUOUS geometry render: " + vacuous_renders(m)["geometry_delta"])
    else:
        why.append("no glb: " + (m.get("glb_leg", {}).get("error") or "")[:120])
    r = m.get("reexport") or {}
    if not r.get("leg_ok"):
        why.append("no re-export: " + (r.get("error") or "")[:120])
    else:
        if not r.get("well_formed"):
            why.append("re-export is not well-formed")
        if r.get("x3d_py") is None:
            why.append("x3d.py not installed")
        elif r.get("x3d_py_errors", 0) > 0:
            why.append(f"x3d.py reports {r['x3d_py_errors']} errors")
        if "roundtrip_delta" not in skip:
            if not (m.get("roundtrip") or {}).get("render_ok"):
                why.append("render missing (X_ITE on the original or the re-export)")
            elif "roundtrip_delta" in vacuous_renders(m) and not _allow_blank(entry):
                why.append("VACUOUS round-trip render: " + vacuous_renders(m)["roundtrip_delta"])
    return why


def _worse(path, old, new):
    """(worse, moved) for the metric at `path`: is `new` a looser threshold than `old`, and did it move beyond noise.
    Counts (warnings, nodes lost) are exact; floats ignore a move under MOVE_EPS; triangles are a floor, so fewer is worse."""
    key = path[-1]
    if key == "geometry_delta":   # None = no geometry visible: the checks read that as 0.0, and losing it all is worse
        if old is None and new is None:
            return False, False
        if new is None:
            return True, True
        old = 0.0 if old is None else old
    if old is None or new is None:
        return False, old != new
    if key == "class":   # fewer kinds of geometry is worse, so the class follows the decision on the counts beside it
        rank = {"triangles": 3, "points+lines": 2, "points": 1, "lines": 1, "empty": 0}
        return rank.get(new, 0) < rank.get(old, 0), old != new
    if isinstance(old, str):
        return False, old != new
    if key in ("triangles", "points", "lines"):   # floors: fewer is worse
        rel = DEFAULT_TOLERANCE["triangles"]["rel"]
        return new < old * (1 - rel), abs(new - old) > old * rel if old else new != old
    if key in ("geometry_share", "geometry_missing_share"):   # a floor (Babylon.js covering less of the frame is worse) and a ceiling
        rule = DEFAULT_TOLERANCE["geometry_share"]
        margin = max(rule["abs"], rule["rel"] * abs(old))
        return (new < old - margin if key == "geometry_share" else new > old + margin), abs(new - old) > margin
    if isinstance(old, int) and isinstance(new, int):
        return new > old, new != old
    return new > old + MOVE_EPS, abs(new - old) > MOVE_EPS


def _flatten(e, prefix=()):
    for k, v in sorted(e.items()):
        if isinstance(v, dict) and k not in ("allow_empty", "allow_blank", "skip"):
            yield from _flatten(v, prefix + (k,))
        elif k not in ("allow_empty", "allow_blank", "skip", "known"):
            yield prefix + (k,), v


_MISSING = object()


def _get(e, path):
    for p in path:
        if not isinstance(e, dict) or p not in e:
            return _MISSING
        e = e[p]
    return e


def _set(e, path, value):
    for p in path[:-1]:
        e = e.setdefault(p, {})
    e[path[-1]] = value


def merge_baseline(old, measurements, allow_worse=False, scenes_run=None):
    """Update `old` (a baseline dict) with `measurements` {scene: m}. Returns (new_baseline, moves, refusals):
    moves are lines describing what changed (new scene, tightened, or loosened with allow_worse); refusals are lines for
    values that got worse and were NOT recorded (the old value stays), and for measurements a baseline must never absorb.
    Floats that moved by less than MOVE_EPS are left alone. known / skip / allow_empty / allow_blank entries are never touched, except that
    allow_worse lets a leg or render that failed, a vacuous render, or an EMPTY glb, be recorded with an UNEXPLAINED reason the person must then replace."""
    new = json.loads(json.dumps(old))
    scenes = new.setdefault("scenes", {})
    moves, refusals = [], []
    for name, m in measurements.items():
        entry = scenes.get(name)
        fresh = baseline_entry_from(m)
        bad = hard_failures(m, entry)
        if bad:
            tag = "; ".join(bad)
            if not allow_worse:
                refusals.append(f"{name}: not recorded, {tag} (fix it, or --allow-worse to record it with an UNEXPLAINED reason you then replace)")
                continue   # the measured values of a failing scene are not recorded either
            entry = entry if entry is not None else {}
            scenes[name] = entry
            if not m.get("glb_leg", {}).get("ok") and "validator" not in (entry.get("skip") or {}):
                entry.setdefault("skip", {})["validator"] = "UNEXPLAINED: " + tag
                moves.append(f"{name}: skip.validator recorded (UNEXPLAINED) because {tag}")
            if ("EMPTY" in tag or "-only glb" in tag) and "allow_empty" not in entry:
                entry["allow_empty"] = dict(reason="UNEXPLAINED: " + tag)
                moves.append(f"{name}: allow_empty recorded (UNEXPLAINED) because {tag}")
            if "VACUOUS" in tag and "allow_blank" not in entry:
                entry["allow_blank"] = dict(reason="UNEXPLAINED: " + tag)
                moves.append(f"{name}: allow_blank recorded (UNEXPLAINED) because {tag}")
            for chk_, what in (("geometry_delta", "render missing (X_ITE or Babylon.js)"), ("roundtrip_delta", "render missing (X_ITE on the original")):
                if what in tag and chk_ not in (entry.get("skip") or {}):
                    entry.setdefault("skip", {})[chk_] = "UNEXPLAINED: " + tag
                    moves.append(f"{name}: skip.{chk_} recorded (UNEXPLAINED) because {tag}")
            if not (m.get("reexport") or {}).get("leg_ok") and "reexport" not in (entry.get("skip") or {}):
                entry.setdefault("skip", {})["reexport"] = "UNEXPLAINED: " + tag
                moves.append(f"{name}: skip.reexport recorded (UNEXPLAINED) because {tag}")
        if entry is None:
            scenes[name] = fresh
            moves.append(f"{name}: new scene recorded")
            continue
        for path, nv in _flatten(fresh):
            ov = _get(entry, path)
            key = ".".join(path)
            if ov is _MISSING:
                _set(entry, path, nv)
                moves.append(f"{name}: {key} recorded {nv}")
                continue
            worse, moved = _worse(path, ov, nv)
            if not moved:
                continue
            if worse and not allow_worse:
                refusals.append(f"{name}: {key} {ov} -> {nv} is worse; not recorded (--allow-worse to loosen)")
                continue
            _set(entry, path, nv)
            moves.append(f"{name}: {key} {ov} -> {nv}" + (" (LOOSENED with --allow-worse)" if worse else " (tightened)"))
        if (entry.get("allow_empty")) and (m.get("glb") or {}).get("class") == "triangles":
            moves.append(f"{name}: allow_empty is no longer needed (glb now has triangles); remove the entry by hand")
    return new, moves, refusals


def format_report(rows, fingerprint_note=None, elapsed=None):
    """rows: [{scene, verdict, checks:[{check,status,detail,known}]}]. Plain text."""
    lines = []
    for r in rows:
        lines.append(f"{r['verdict']:<8} {r['scene']}")
        for c in r["checks"]:
            if c["status"] == STATUS_PASS and not c["known"]:
                continue
            tag = f" [known {','.join(c['known'])}]" if c["known"] else ""
            lines.append(f"           {c['status']:<8} {c['check']:<16} {c['detail']}{tag}")
    n = len(rows)
    npass = sum(1 for r in rows if r["verdict"] in ("PASS", "IMPROVED"))
    fails = [r["scene"] for r in rows if r["verdict"] == "FAIL"]
    imp = [r["scene"] for r in rows if r["verdict"] == "IMPROVED"]
    lines.append("")
    lines.append(f"GATE {'FAIL' if fails else 'PASS'}: {npass}/{n} scenes pass" + (f", {len(fails)} fail: {', '.join(fails)}" if fails else "")
                 + (f"; {len(imp)} improved (tighten the baseline with --update-baseline): {', '.join(imp)}" if imp else "")
                 + (f"  [{elapsed:.0f} s]" if elapsed is not None else ""))
    if fingerprint_note:
        lines.append(fingerprint_note)
    return "\n".join(lines)


def compare_fingerprint(base_fp, now_fp):
    """Keys whose value differs (chromium compared on the major version, add-on revision never): {key: (baseline, now)}. A key the
    baseline header lacks is not compared; one it has but this run reports as None (a missing flip-evaluator) is a difference."""
    diff = {}
    for k in ("x_ite", "babylon", "chromium", "blender", "validator", "flip_evaluator", "x3d_py", "numpy", "pillow"):
        a, b = (base_fp or {}).get(k), (now_fp or {}).get(k)
        if k == "chromium":
            a, b = (str(a).split(".")[0] if a else a), (str(b).split(".")[0] if b else b)
        if a and a != b:   # a tool the baseline recorded but this run could not report (None) is a difference too
            diff[k] = (a, b)
    return diff


# ------------------------------------------------------------------ measuring (Blender, node, browser)

def log(*a):
    print(*a, flush=True)


def _read_json(path):
    with open(path) as f:
        return json.load(f)


def _write_json(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=1, default=float)


def _py():
    return os.environ.get("BPY_PYTHON", sys.executable)


def _pkg_version(name):
    p = os.path.join(RIG, "node_modules", name, "package.json")
    try:
        return _read_json(p)["version"]
    except (OSError, ValueError, KeyError):
        return None


def _scene_path(sc):
    return sc["x3d"] if os.path.isabs(sc["x3d"]) else os.path.abspath(os.path.join(RIG, sc["x3d"]))


def _short_err(text, n=400):
    return (text or "").strip()[-n:]


def blender_glb_leg(src, x3d, glb):
    """compare.py's Blender leg. Returns (leg dict or None, error)."""
    try:
        r = subprocess.run([_py(), os.path.join(RIG, "blender_leg.py"), src, x3d, glb], capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return None, "timed out after 900 s"
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith("LEG ")), None)
    if not line or not os.path.exists(glb):
        return None, _short_err(r.stderr or r.stdout)
    return json.loads(line[4:]), None


def measure_legs(sc, label, src, reuse=False):
    """Phase 1 for one scene: both Blender legs, the validator, the structural checks. Returns the partial measurement dict
    (no renders yet) and writes nothing outside out/LABEL/<scene>/."""
    import manifest   # compare.py's glb helpers
    import roundtrip, roundtrip_audit as ra   # noqa: E401  (roundtrip.py's main() is guarded; its pieces are reused)
    name, x3d = sc["name"], _scene_path(sc)
    out = f"{RIG}/out/{label}/{name}"
    os.makedirs(out, exist_ok=True)
    m = dict(scene=name, x3d_file=sc["x3d"], glb_leg=dict(ok=False), reexport=dict(leg_ok=False),
             x3d=x3d_renderables(x3d) if os.path.exists(x3d) else {})
    if not os.path.exists(x3d):
        m["glb_leg"] = dict(ok=False, error="scene file missing")
        m["reexport"] = dict(leg_ok=False, error="scene file missing")
        return m
    # A. glb leg
    glb = f"{out}/scene.glb"
    for stale in (glb, glb + ".validation.json", f"{out}/manifest.json", *(f"{out}/{n}.png" for n in ("xite", "babylon", "babylon_mask", "babylon_mask_green", "diff_x4"))):
        if os.path.exists(stale):
            os.remove(stale)
    t0 = time.time()
    leg, err = blender_glb_leg(src, x3d, glb)
    if leg is None:
        m["glb_leg"] = dict(ok=False, error=err)
    else:
        val = manifest.validate(glb, None)
        manifest.write_manifest(out, name, x3d, glb, val, leg, src)
        v = val.get("validator")
        m["glb_leg"] = dict(ok=True, blender=leg.get("blender"), lights=leg.get("lights"), model=leg.get("model"),
                            headlight_lux=leg.get("headlight_lux"), secs=round(time.time() - t0, 1))
        if v is None:
            m["validator"] = dict(ok_ran=False, error=val.get("validator_error"))
        else:
            points, lines, _ = glb_primitive_counts(glb)
            m["validator"] = dict(ok_ran=True, errors=v["errors"], warnings=v["warnings"], infos=v["infos"], hints=v["hints"],
                                  version=v["version"], not_validated=v["extensionsNotValidated"], issues=v["issues"][:10])
            m["glb"] = dict(triangles=v["triangles"], points=points, lines=lines, draw_calls=v["drawCalls"],
                            materials=v["materials"], bytes=v["bytes"], **{"class": classify_glb(v["triangles"], points, lines)})
    # B. X3D leg (roundtrip.py's pieces: run_leg with the default options, validate_reexport, count_diff)
    rdir = f"{out}/reexp"
    if os.path.isdir(rdir):
        for stale in ("roundtrip.x3d", "xite.png", "xite_console.txt"):
            if os.path.exists(f"{rdir}/{stale}"):
                os.remove(f"{rdir}/{stale}")
    t0 = time.time()
    rleg, why = _roundtrip_leg(src, x3d, rdir)
    if rleg is None:
        m["reexport"] = dict(leg_ok=False, error=why)
        return m
    re_path = f"{rdir}/roundtrip.x3d"
    val = roundtrip.validate_reexport(re_path, os.path.abspath(src))
    diff = ra.count_diff(ra.node_counts(ra.parse(x3d)), ra.node_counts(ra.parse(re_path)))
    xp = val.get("x3d_py")
    m["reexport"] = dict(leg_ok=True, well_formed=bool(val.get("well_formed")), structural_errors=val.get("structural_errors", []),
                         x3d_py=("ok" if isinstance(xp, dict) and "errors" in xp else None if xp == "not installed" else str(xp)[:200]),
                         x3d_py_errors=(xp.get("errors", 0) if isinstance(xp, dict) else 0),
                         x3d_py_warnings=(xp.get("warnings", 0) if isinstance(xp, dict) else 0),
                         nodes_lost=len(diff["lost"]), lost_types=sorted(diff["lost"]), color_space=rleg.get("color_space"),
                         secs=round(time.time() - t0, 1))
    return m


def _roundtrip_leg(src, x3d, outdir):
    """roundtrip_leg.py with the add-on's defaults (the sRGB pass only; the AS_IS colour audit is roundtrip.py's job)."""
    env = dict(os.environ)
    env.pop("BLENDER_X3D_COLOR_SPACE", None)
    try:
        r = subprocess.run([_py(), os.path.join(RIG, "roundtrip_leg.py"), src, x3d, outdir], capture_output=True, text=True, timeout=900, env=env)
    except subprocess.TimeoutExpired:
        return None, "timed out after 900 s"
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith("RTLEG ")), None)
    if not line or not os.path.exists(f"{outdir}/roundtrip.x3d"):
        return None, _short_err(r.stderr or r.stdout)
    return json.loads(line[6:]), None


def _render_params(x3d, sc, m, src):
    """The clear colour, headlight and first viewpoint compare.py gives Babylon.js for this scene."""
    from viewpoint import first_viewpoint
    txt = open(x3d, errors="ignore").read()
    mt = re.search(r"<Background\b[^>]*skyColor=['\"]([^'\"]+)", txt)
    clear = [float(v) for v in mt.group(1).replace(",", " ").split()[:3]] if mt else [0, 0, 0]
    nav = re.search(r"<NavigationInfo\b[^>]*headlight=['\"](\w+)", txt)
    head_on = not (nav and nav.group(1).lower() == "false")
    head = (sc.get("headlight_lux") or m["glb_leg"].get("headlight_lux") or 1.0) if head_on else None
    return clear, head, first_viewpoint(x3d, src)


RENDER_JOB_BUDGET_S = 200   # render.mjs gives X_ITE and Babylon.js 90 s each to load a scene, plus the settle wait and the screenshots


def run_renders(todo, label, chunk=8):
    """One render.mjs process per chunk of jobs (a page crash in SwiftShader must not cost the other scenes). render.mjs --strict
    exits 1 and prints `FAILED <json list of job names>` when a job failed inside its own try/catch (a crashed page, a load timeout):
    only those jobs are rerun once, each alone. A chunk that died without that line is rerun job by job. Each process gets a timeout
    of 60 s plus RENDER_JOB_BUDGET_S per job, so a hang cannot outlast the CI job. Returns the Chromium version string."""
    chromium = None

    def run(jobs, tag):
        """True when every job rendered; else the list of names that did not (None when the whole process failed)."""
        nonlocal chromium
        jf = f"{RIG}/out/{label}/gate_jobs_{tag}.json"
        _write_json(jf, jobs)
        try:
            r = subprocess.run(["node", f"{RIG}/render.mjs", jf, "--strict"], capture_output=True, text=True,
                               timeout=60 + RENDER_JOB_BUDGET_S * len(jobs))
        except subprocess.TimeoutExpired:
            log(f"   render.mjs timed out on {len(jobs)} jobs ({tag})")
            return None
        mt = re.search(r"BROWSER (Chrome/[\d.]+)", r.stdout)
        if mt:
            chromium = mt.group(1).split("/")[1]
        for ln in r.stdout.splitlines():
            if "fail" in ln or "pageerror" in ln:
                log("   render:", ln[:240])
        if r.returncode == 0:
            return True
        log(f"   render.mjs exit {r.returncode} ({tag}): {_short_err(r.stderr, 300)}")
        mf = re.search(r"^FAILED (\[.*\])\s*$", r.stdout, re.M)
        return json.loads(mf.group(1)) if mf else None

    for i in range(0, len(todo), chunk):
        part = todo[i:i + chunk]
        res = run(part, f"c{i // chunk}")
        if res is True:
            continue
        redo = part if res is None else [j for j in part if j["name"] in set(res)]
        for j, job in enumerate(redo):
            log(f"   rerunning {job['name']} alone")
            run([job], f"c{i // chunk}_{j}")
    return chromium


FOREGROUND_DELTA = 16   # a pixel is foreground when it differs from the render's background by more than this (0-255)


def foreground_mask(img, thr=0):
    """Boolean H x W mask of the pixels of an H x W x 3 render that differ from the median colour of its border (the background)
    by more than `thr`. With thr 0 an empty mask means the render shows nothing but background: a check that compares such a
    render with anything compares nothing. A gradient or sky background is counted as foreground (the border is one colour)."""
    import numpy as np
    a = np.asarray(img, dtype=np.float64)
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    bg = np.median(border, axis=0)
    return np.abs(a - bg).max(axis=-1) > thr


def foreground_share(img, thr=0):
    """Share of the frame foreground_mask() marks."""
    return float(foreground_mask(img, thr).mean())


def finish_scene(m, job_out):
    """Phase 3: the image deltas from the renders under job_out. Fills geometry_delta, glb_render_ok and roundtrip."""
    import numpy as np
    from PIL import Image
    import roundtrip_audit as ra
    rd = lambda p: np.asarray(Image.open(p).convert("RGB"), dtype=np.float64)   # noqa: E731
    a, b = f"{job_out}/xite.png", f"{job_out}/babylon.png"
    m["glb_render_ok"] = False
    m.pop("xite_foreground_share", None)
    if os.path.exists(a):
        m["xite_foreground_share"] = round(foreground_share(rd(a)), 6)   # 0.0: an all-background reference render (vacuous checks)
    if m["glb_leg"].get("ok") and os.path.exists(a) and os.path.exists(b):
        A, B = rd(a), rd(b)
        d = np.abs(A - B)
        Image.fromarray(np.clip(d * 4, 0, 255).astype(np.uint8)).save(f"{job_out}/diff_x4.png")
        m["glb_render_ok"] = True
        m["mean_abs_delta_glb"] = round(float(d.mean()), 2)
        mk, mg = f"{job_out}/babylon_mask.png", f"{job_out}/babylon_mask_green.png"
        m["geometry_delta"], m["geometry_share"], m["geometry_missing_share"] = None, None, None
        if os.path.exists(mk) and os.path.exists(mg):
            Mk, Mg = np.asarray(Image.open(mk).convert("RGB"), dtype=np.int32), np.asarray(Image.open(mg).convert("RGB"), dtype=np.int32)
            clear = ((Mk[..., 0] == 255) & (Mk[..., 1] == 0) & (Mk[..., 2] == 255)) & ((Mg[..., 0] == 0) & (Mg[..., 1] == 255) & (Mg[..., 2] == 0))
            geo = ~clear
            m["geometry_share"] = round(float(geo.mean()), 3)
            m["geometry_delta"] = round(float(d[geo].mean()), 2) if geo.any() else None
            # What Babylon.js failed to draw: X_ITE shows foreground where Babylon.js shows its clear colour. The delta above is taken over
            # the pixels Babylon.js drew, so a glb that lost an object would not move it; this share does.
            m["geometry_missing_share"] = round(float((foreground_mask(A, FOREGROUND_DELTA) & clear).mean()), 3)
    m["roundtrip"] = dict(render_ok=False)
    c = f"{job_out}/reexp/xite.png"
    if m["reexport"].get("leg_ok") and os.path.exists(a) and os.path.exists(c):
        A, C = rd(a), rd(c)
        di = ra.image_deltas(A, C)
        Image.fromarray(np.clip(np.abs(A - C) * 4, 0, 255).astype(np.uint8)).save(f"{job_out}/diff_roundtrip_x4.png")
        try:
            flip = ra.flip_mean(A, C)
        except Exception as e:   # flip-evaluator missing or failing on this render: the check then fails when the baseline has a FLIP
            flip = None
            m["roundtrip"]["flip_error"] = str(e)[:120]
        m["roundtrip"].update(render_ok=True, mean_abs_delta=round(di["mean_abs_delta"], 2), share_gt16=di["share_gt16"], flip=flip)
    return m


def fingerprint(src, measurements, chromium):
    import manifest
    import importlib.metadata as md

    def ver(pkg):
        try:
            return md.version(pkg)
        except Exception:
            return None
    flip = ver("flip-evaluator")
    blender = next((m["glb_leg"].get("blender") for m in measurements.values() if m["glb_leg"].get("blender")), None)
    validator = next(((m.get("validator") or {}).get("version") for m in measurements.values() if (m.get("validator") or {}).get("version")), None)
    rev, dirty = manifest.git_revision(src)
    return dict(x_ite=_pkg_version("x_ite"), babylon=_pkg_version("babylonjs"), chromium=chromium,
                renderer="SwiftShader (--use-angle=swiftshader)", blender=blender, validator=validator, flip_evaluator=flip,
                x3d_py=ver("x3d"), numpy=ver("numpy"), pillow=ver("pillow"),
                addon_git_revision=rev, addon_source_dirty=dirty)


def load_scenes(files, only):
    seen, scenes = {}, []
    for f in files:
        path = f if os.path.isabs(f) or os.path.exists(f) else os.path.join(RIG, f)
        for sc in _read_json(path):
            if sc["name"] in seen:
                continue
            seen[sc["name"]] = True
            scenes.append(sc)
    if only:
        names = set(only.split(","))
        missing = names - set(seen)
        if missing:
            sys.exit(f"--only names no scene of the scenes files: {', '.join(sorted(missing))}")
        scenes = [s for s in scenes if s["name"] in names]
    return scenes


def run_gate(scenes, label, src, jobs=1, chunk=8, reuse=False):
    """Measure every scene. Returns ({scene: measurement}, chromium)."""
    t0 = time.time()
    measurements, todo_scenes = {}, []
    for sc in scenes:
        cache = f"{RIG}/out/{label}/{sc['name']}/measured.json"
        if reuse and os.path.exists(cache):
            measurements[sc["name"]] = _read_json(cache)
            log(f"== {sc['name']}: reusing {cache}")
        else:
            todo_scenes.append(sc)
    log(f"gate: {len(todo_scenes)} scenes to measure ({len(scenes) - len(todo_scenes)} reused), Blender legs with {jobs} worker(s)")
    def one(sc):
        t = time.time()
        m = measure_legs(sc, label, src)
        g, r = m["glb_leg"], m["reexport"]
        log(f"== {sc['name']}: glb leg {'ok' if g.get('ok') else 'FAIL ' + str(g.get('error'))[:200]}"
            + (f", validator {m['validator'].get('errors')}E {m['validator'].get('warnings')}W, glb {m['glb']['class']} {m['glb']['triangles']} tris" if m.get("glb") else "")
            + f"; X3D leg {'ok' if r.get('leg_ok') else 'FAIL ' + str(r.get('error'))[:200]}"
            + (f", well-formed {r['well_formed']}, x3d.py {r['x3d_py']}, {r['nodes_lost']} node types lost" if r.get("leg_ok") else "")
            + f"  [{time.time() - t:.0f} s]")
        return m
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        legs = list(ex.map(one, todo_scenes))
    jobs_list = []
    for sc, m in zip(todo_scenes, legs):
        measurements[sc["name"]] = m
        x3d = _scene_path(sc)
        out = f"{RIG}/out/{label}/{sc['name']}"
        wait = sc.get("wait", 2500)
        if m["glb_leg"].get("ok") or m["reexport"].get("leg_ok"):
            clear, head, view = _render_params(x3d, sc, m, src)
            if m["glb_leg"].get("ok"):
                jobs_list.append(dict(name=sc["name"], x3d=x3d, glb=os.path.abspath(f"{out}/scene.glb"), clear=clear, headlight=head,
                                      outdir=out, wait=wait, view=view))
            else:
                jobs_list.append(dict(name=sc["name"], x3d=x3d, outdir=out, wait=wait, xiteOnly=True))
        if m["reexport"].get("leg_ok"):
            jobs_list.append(dict(name=sc["name"] + "/reexp", x3d=os.path.abspath(f"{out}/reexp/roundtrip.x3d"), outdir=f"{out}/reexp", wait=wait, xiteOnly=True))
    for j in jobs_list:   # a render that fails must not leave an earlier run's image under this label
        for stale in ("xite.png", "babylon.png", "babylon_mask.png", "babylon_mask_green.png"):
            if os.path.exists(f"{j['outdir']}/{stale}"):
                os.remove(f"{j['outdir']}/{stale}")
    chromium = next((m.get("chromium") for m in measurements.values() if m.get("chromium")), None)   # a reused run remembers its browser
    if jobs_list:
        log(f"gate: rendering {len(jobs_list)} jobs (X_ITE on the X3D, Babylon.js on the glb, X_ITE on the re-export)")
        chromium = run_renders(jobs_list, label, chunk)
    for sc in todo_scenes:
        measurements[sc["name"]]["chromium"] = chromium
        m = finish_scene(measurements[sc["name"]], f"{RIG}/out/{label}/{sc['name']}")
        _write_json(f"{RIG}/out/{label}/{sc['name']}/measured.json", m)
    log(f"gate: measured {len(todo_scenes)} scenes in {time.time() - t0:.0f} s")
    return measurements, chromium


def load_baseline(path):
    if os.path.exists(path):
        return _read_json(path)
    return dict(schema=BASELINE_SCHEMA, tolerance=DEFAULT_TOLERANCE, scenes={})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenes", nargs="+", default=["probes.json"], help="scenes JSON files (default probes.json)")
    ap.add_argument("--only", help="comma-separated scene names")
    ap.add_argument("--src", default=os.path.join(RIG, "..", "..", "source"), help="the add-on's source folder (default ../../source)")
    ap.add_argument("--baseline", default=DEFAULT_BASELINE)
    ap.add_argument("--label", default="gate", help="output folder out/LABEL (default gate)")
    ap.add_argument("--json", help="also write the results JSON here")
    ap.add_argument("--update-baseline", action="store_true", help="record the measured values; never loosens a threshold unless --allow-worse")
    ap.add_argument("--allow-worse", action="store_true", help="with --update-baseline: let a threshold rise and record failures as UNEXPLAINED entries")
    ap.add_argument("--fail-on-improvement", action="store_true", help="exit 1 when a scene is better than baseline by more than the tolerance")
    ap.add_argument("--strict-fingerprint", action="store_true", help="exit 1 when the rig versions differ from the baseline header")
    ap.add_argument("--jobs", type=int, default=1, help="Blender legs in parallel (default 1)")
    ap.add_argument("--chunk", type=int, default=8, help="render jobs per render.mjs process (default 8)")
    ap.add_argument("--reuse", action="store_true", help="reuse out/LABEL/<scene>/measured.json from an earlier run (re-evaluate only)")
    ns = ap.parse_args(argv)
    src = os.path.abspath(ns.src)
    scenes = load_scenes(ns.scenes, ns.only)
    if not scenes:   # an emptied or truncated scenes file must not turn the gate green having tested nothing
        sys.exit("gate: no scenes to run: " + ", ".join(ns.scenes) + (f" with --only {ns.only}" if ns.only else "") + " resolve to an empty list")
    baseline = load_baseline(ns.baseline)
    tol = {**DEFAULT_TOLERANCE, **(baseline.get("tolerance") or {})}
    problems = lint_baseline(baseline)
    for p in problems:
        log("BASELINE LINT:", p)
    t0 = time.time()
    os.makedirs(f"{RIG}/out/{ns.label}", exist_ok=True)
    measurements, chromium = run_gate(scenes, ns.label, src, ns.jobs, ns.chunk, ns.reuse)
    fp = fingerprint(src, measurements, chromium)
    diff = compare_fingerprint(baseline.get("rig"), fp)
    note = None
    if diff:
        note = "FINGERPRINT differs from the baseline header (thresholds were measured on another rig): " + "; ".join(
            f"{k} {a} -> {b}" for k, (a, b) in diff.items())
    rows = []
    for sc in scenes:
        m = measurements[sc["name"]]
        entry = (baseline.get("scenes") or {}).get(sc["name"])
        checks = evaluate_scene(m, entry, tol)
        rows.append(dict(scene=sc["name"], verdict=scene_verdict(checks), checks=checks))
    elapsed = time.time() - t0
    report = format_report(rows, note, elapsed)
    log("\n" + ("Against the baseline before the update:\n" if ns.update_baseline else "") + report)
    res = dict(schema=RESULTS_SCHEMA, rig=fp, tolerance=tol, scenes=rows, measurements=measurements, baseline_lint=problems,
               fingerprint_differs=diff, seconds=round(elapsed, 1), update_baseline=ns.update_baseline)
    _write_json(f"{RIG}/out/{ns.label}/gate_results.json", res)   # before the exit code is decided
    if ns.json:
        _write_json(ns.json, res)
    if ns.update_baseline:
        return update(baseline, ns, measurements, fp, tol, scenes)
    code = 0
    if any(r["verdict"] == "FAIL" for r in rows) or problems:
        code = 1
    if ns.fail_on_improvement and any(r["verdict"] == "IMPROVED" for r in rows):
        code = 1
    if diff and ns.strict_fingerprint:
        log("FAIL: --strict-fingerprint and the rig differs from the baseline header")
        code = 1
    return code


def update(baseline, ns, measurements, fp, tol, scenes):
    # The header says which rig every threshold of the file was measured on. A run that covers only some of the baseline's scenes
    # on a different rig must not restamp it: the other scenes' thresholds would then claim the new rig.
    drift = compare_fingerprint(baseline.get("rig"), fp)
    partial = {sc["name"] for sc in scenes} != set((baseline.get("scenes") or {}))
    if drift and partial:
        log("\nBASELINE UPDATE REFUSED: the rig differs from the baseline header (" + "; ".join(f"{k} {a} -> {b}" for k, (a, b) in drift.items())
            + ") and this run does not cover every baseline scene. Re-baseline from a full run on the new rig; nothing was written.")
        return 1
    new, moves, refusals = merge_baseline(baseline, measurements, ns.allow_worse)
    new["schema"] = BASELINE_SCHEMA
    new["tolerance"] = tol
    new["rig"] = {k: (v if v is not None else (baseline.get("rig") or {}).get(k)) for k, v in fp.items()}   # a subset run that did not render keeps the old browser
    new["scenes"] = dict(sorted(new["scenes"].items()))
    log("\nBASELINE UPDATE" + (" (--allow-worse)" if ns.allow_worse else ""))
    for ln in moves:
        log("  moved  ", ln)
    for ln in refusals:
        log("  REFUSED", ln)
    if not moves and not refusals:
        log("  nothing moved")
    with open(ns.baseline, "w") as f:
        json.dump(new, f, indent=1, sort_keys=False)
        f.write("\n")
    log(f"wrote {ns.baseline}" + (f" with {len(refusals)} refused change(s)" if refusals else ""))
    problems = lint_baseline(new)
    for p in problems:
        log("BASELINE LINT:", p)
    rows = []   # the verdict of this run against the baseline just written
    for sc in scenes:
        checks = evaluate_scene(measurements[sc["name"]], new["scenes"].get(sc["name"]), tol)
        rows.append(dict(scene=sc["name"], verdict=scene_verdict(checks), checks=checks))
    log("\nAgainst the updated baseline:\n" + format_report(rows))
    failing = [r["scene"] for r in rows if r["verdict"] == "FAIL"]
    if failing:
        log(f"update leaves {len(failing)} scene(s) failing against the baseline just written: {', '.join(failing)}")
    return 1 if (refusals or problems or failing) else 0


if __name__ == "__main__":
    sys.exit(main())
