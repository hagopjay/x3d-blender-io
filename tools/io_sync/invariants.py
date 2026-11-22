# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Round-trip invariants: what an import and re-export must keep, measured as scene facts, not text (plain Python).

    python tools/io_sync/invariants.py E0.x3d E1.x3d                         # print the invariants that break
    python tools/io_sync/invariants.py --fixed-point FP_OUT [--budget FILE] [--write-budget FILE]

fixed_point.py already holds E0 -> E1 to a per-(element, field) text budget and E1 -> E2 to zero. That budget counts
spellings: a renamed DEF and a lost material both count 1. This judge asks the v3 plan's Gate 2 questions instead, each
one a number or a multiset computed the same way from both files:

  faces              polygons of IndexedFaceSet, triangles of IndexedTriangleSet / TriangleSet, lines of IndexedLineSet
  bbox               world-space bounding box of every Coordinate point, through Transform / HAnim nesting and USE
  materials          multiset of (node, rounded colour and scalar fields) over Material, PhysicalMaterial, UnlitMaterial
  lights             multiset of (node, on, intensity, colour) per light node
  viewpoints         count of Viewpoint + OrthoViewpoint, and the first one's world position (the one X3D binds)
  instancing         count of USE per node type (shared data stays shared: DEF/USE isomorphism up to names)
  routes             multiset of (from node type.field -> to node type.field)
  textures           multiset of ImageTexture url basenames

--budget FILE (tools/io_sync/invariant_budget.json): an invariant that breaks and is not listed, or breaks with other
values than listed, fails (exit 1); a listed one that now holds is reported so the budget can shrink. A budget may only
shrink, so a new round-trip loss of any of these facts turns CI red even when fixed_point's text budget absorbs it.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

GROUPING = {"Transform", "HAnimHumanoid", "HAnimJoint", "HAnimSite"}
MATERIALS = {"Material": ("diffuseColor", "emissiveColor", "specularColor", "shininess", "transparency"),
             "PhysicalMaterial": ("baseColor", "emissiveColor", "metallic", "roughness", "transparency"),
             "UnlitMaterial": ("emissiveColor", "transparency")}
LIGHTS = ("DirectionalLight", "PointLight", "SpotLight", "EnvironmentLight")
DIGITS = 3


def _floats(text, default):
    if text is None:
        return list(default)
    return [float(t) for t in text.replace(",", " ").split()]


def _round(values):
    return tuple(0.0 if abs(round(float(v), DIGITS)) == 0 else round(float(v), DIGITS) for v in values)


def _matmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _local(el):
    tx, ty, tz = _floats(el.get("translation"), (0, 0, 0))
    ax, ay, az, angle = _floats(el.get("rotation"), (0, 0, 1, 0))
    sx, sy, sz = _floats(el.get("scale"), (1, 1, 1))
    n = math.sqrt(ax * ax + ay * ay + az * az) or 1.0
    x, y, z = ax / n, ay / n, az / n
    c, s, t = math.cos(angle), math.sin(angle), 1 - math.cos(angle)
    r = [[t * x * x + c, t * x * y - s * z, t * x * z + s * y],
         [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
         [t * x * z - s * y, t * y * z + s * x, t * z * z + c]]
    return [[r[0][0] * sx, r[0][1] * sy, r[0][2] * sz, tx],
            [r[1][0] * sx, r[1][1] * sy, r[1][2] * sz, ty],
            [r[2][0] * sx, r[2][1] * sy, r[2][2] * sz, tz],
            [0, 0, 0, 1]]


def _identity():
    return [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]


def _apply(m, p):
    return tuple(m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] + m[i][3] for i in range(3))


def _faces(el):
    tag = el.tag
    if tag in ("IndexedFaceSet", "IndexedLineSet"):
        idx = [int(t) for t in (el.get("coordIndex") or "").replace(",", " ").split()]
        count, open_run = 0, False
        for i in idx:
            if i < 0:
                count += open_run
                open_run = False
            else:
                open_run = True
        return count + open_run
    if tag == "IndexedTriangleSet":
        return len((el.get("index") or "").split()) // 3
    if tag == "TriangleSet":
        coord = el.find("Coordinate")
        return len(_floats(coord.get("point"), ())) // 9 if coord is not None else 0
    return 0


def measure(data: str | bytes) -> dict:
    """The invariants of one X3D XML file, as JSON-friendly values."""
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    data = re.sub(r"<!DOCTYPE[^>]*>", "", data, count=1)
    scene = ET.fromstring(data).find("Scene")
    if scene is None:
        raise ValueError("no <Scene>")
    defs = {el.get("DEF"): el for el in scene.iter() if el.get("DEF")}
    facts = {"faces": Counter(), "materials": Counter(), "lights": Counter(), "routes": Counter(),
             "instancing": Counter(), "textures": Counter(), "viewpoints": 0, "first_viewpoint": None}
    lo, hi = [math.inf] * 3, [-math.inf] * 3

    for el in scene.iter():
        if el.get("USE"):
            target = defs.get(el.get("USE"))
            facts["instancing"][target.tag if target is not None else el.tag] += 1
        if el.tag == "ROUTE":
            a, b = defs.get(el.get("fromNode")), defs.get(el.get("toNode"))
            facts["routes"][f"{a.tag if a is not None else '?'}.{el.get('fromField')} -> "
                            f"{b.tag if b is not None else '?'}.{el.get('toField')}"] += 1

    def walk(el, matrix, depth):
        if depth > 64:
            return
        if el.get("USE") and el.get("USE") in defs:
            el = defs[el.get("USE")]
        tag = el.tag
        if tag in GROUPING:
            matrix = _matmul(matrix, _local(el))
        if tag in ("Viewpoint", "OrthoViewpoint"):
            facts["viewpoints"] += 1
            if facts["first_viewpoint"] is None:
                facts["first_viewpoint"] = _round(_apply(matrix, _floats(el.get("position"), (0, 0, 10))))
        if tag in ("IndexedFaceSet", "IndexedTriangleSet", "TriangleSet", "IndexedLineSet"):
            facts["faces"][tag] += _faces(el)
            coord = el.find("Coordinate")
            if coord is not None and coord.get("USE"):
                coord = defs.get(coord.get("USE"))
            if coord is not None:
                pts = _floats(coord.get("point"), ())
                for i in range(0, len(pts) - 2, 3):
                    p = _apply(matrix, pts[i:i + 3])
                    for k in range(3):
                        lo[k], hi[k] = min(lo[k], p[k]), max(hi[k], p[k])
        if tag in MATERIALS:
            facts["materials"][f"{tag}{_round([v for f in MATERIALS[tag] for v in _floats(el.get(f), _MAT_DEFAULTS[f])])}"] += 1
        if tag in LIGHTS:
            facts["lights"][f"{tag} on={el.get('on', 'true')} intensity={_round(_floats(el.get('intensity'), (1,)))} "
                            f"color={_round(_floats(el.get('color'), (1, 1, 1)))}"] += 1
        if tag == "ImageTexture":
            urls = re.findall(r'"([^"]+)"', el.get("url") or "") or (el.get("url") or "").split()
            facts["textures"][Path(urls[0]).name if urls else ""] += 1
        for child in el:
            if isinstance(child.tag, str) and child.tag not in ("ROUTE",):
                walk(child, matrix, depth + 1)

    for child in scene:
        if isinstance(child.tag, str):
            walk(child, _identity(), 0)
    facts["bbox"] = None if lo[0] == math.inf else [_round(lo), _round(hi)]
    return json.loads(json.dumps({k: (dict(sorted(v.items())) if isinstance(v, Counter) else v)
                                  for k, v in facts.items()}))


_MAT_DEFAULTS = {"diffuseColor": (0.8, 0.8, 0.8), "emissiveColor": (0, 0, 0), "specularColor": (0, 0, 0),
                 "shininess": (0.2,), "transparency": (0,), "baseColor": (1, 1, 1), "metallic": (1,),
                 "roughness": (1,)}


def compare(a: dict, b: dict, bbox_tol: float = 1e-3) -> dict:
    """{invariant: {"e0": value, "e1": value}} for every invariant that does not hold from a to b."""
    broken = {}
    for key in a:
        x, y = a[key], b.get(key)
        if key == "bbox" and x and y:
            if all(abs(p - q) <= bbox_tol * max(1.0, abs(p)) for xs, ys in zip(x, y) for p, q in zip(xs, ys)):
                continue
        if x != y:
            if isinstance(x, dict) and isinstance(y, dict):
                broken[key] = {"lost": dict(sorted((Counter(x) - Counter(y)).items())),
                               "gained": dict(sorted((Counter(y) - Counter(x)).items()))}
            else:
                broken[key] = {"e0": a[key], "e1": b.get(key)}
    return json.loads(json.dumps(broken))


def check_budget(results: dict, budget: dict) -> tuple[list[str], list[str]]:
    failures, tightened = [], []
    allowed = budget.get("profiles", {})
    for profile, broken in results.items():
        listed = allowed.get(profile, {})
        for key, values in broken.items():
            if key not in listed:
                failures.append(f"{profile}: round trip breaks '{key}' (not in the budget): {json.dumps(values)[:400]}")
            elif listed[key] != values:
                failures.append(f"{profile}: '{key}' breaks differently from the budget: now {json.dumps(values)[:300]}; "
                                f"budget {json.dumps(listed[key])[:300]}")
        for key in listed:
            if key not in broken:
                tightened.append(f"{profile}: '{key}' now holds; remove it from the budget")
    return failures, tightened


def fixed_point_pairs(folder: Path) -> dict:
    """{profile: (E0 path, E1 path)} from a fixed_point.py output folder."""
    summary = json.loads((folder / "summary.json").read_text())
    rows = summary.get("rows", summary)
    pairs = {}
    for profile, row in rows.items():
        if not isinstance(row, dict) or "artifacts" not in row:
            continue
        leg = Path(row["artifacts"])
        e0 = row.get("e0") or row.get("source")
        pairs[profile] = (Path(e0) if e0 else None, leg / "e1.x3d")
    return pairs


def main(argv):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("files", nargs="*")
    p.add_argument("--fixed-point", type=Path, help="a fixed_point.py OUT_DIR")
    p.add_argument("--suite", type=Path, help="the SUITE_OUT folder fixed_point.py read (E0 files)")
    p.add_argument("--budget", type=Path)
    p.add_argument("--write-budget", type=Path)
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)
    results, measured = {}, {}
    if args.fixed_point:
        for profile, (e0, e1) in sorted(fixed_point_pairs(args.fixed_point).items()):
            if e0 is None or not e0.exists():
                e0 = (args.suite or Path(".")) / f"x3d_suite_{profile}.x3d"
            a, b = measure(e0.read_bytes()), measure(e1.read_bytes())
            measured[profile] = {"e0": a, "e1": b}
            results[profile] = compare(a, b)
    elif len(args.files) == 2:
        a, b = (measure(Path(f).read_bytes()) for f in args.files)
        measured["pair"] = {"e0": a, "e1": b}
        results["pair"] = compare(a, b)
    else:
        p.error("give E0 E1, or --fixed-point OUT_DIR")
    for profile, broken in results.items():
        holds = [k for k in measured[profile]["e0"] if k not in broken]
        print(f"[invariants] {profile}: {len(holds)} hold ({', '.join(holds)}); {len(broken)} break"
              + (f" ({', '.join(broken)})" if broken else ""))
        for key, values in broken.items():
            for side, value in values.items():
                print(f"    {key:11} {side:6} {json.dumps(value)[:400]}")
    if args.out:
        args.out.write_text(json.dumps({"measured": measured, "broken": results}, indent=1))
    if args.write_budget:
        args.write_budget.write_text(json.dumps({
            "about": "Round-trip invariants (tools/io_sync/invariants.py) that break from E0 to E1 per suite profile, with "
                     "their values. A listed invariant may stop breaking (remove it); a new one, or other values, fails CI.",
            "profiles": results}, indent=1) + "\n")
        print(f"[invariants] wrote {args.write_budget}")
        return 0
    if args.budget:
        failures, tightened = check_budget(results, json.loads(args.budget.read_text()))
        for t in tightened:
            print(f"[invariants] tighten: {t}")
        for f in failures:
            print(f"[invariants] FAIL {f}")
        print(f"[invariants] budget: {'FAIL' if failures else 'PASS'} ({len(failures)} new or changed break(s))")
        return 1 if failures else 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
