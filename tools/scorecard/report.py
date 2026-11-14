#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""results.json -> scorecard.md and scorecard.html (self-contained).

    python3 tools/scorecard/report.py RESULTS_DIR            # writes RESULTS_DIR/scorecard.md and scorecard.html

Tables: per-scene FLIP against the Cycles reference with the validator mark in each cell; the same against X_ITE (secondary, with
mean |delta|); engine means over the COMMON scene set (every compared leg has a usable result there; the set is stated) and over each
leg's own set; the paired difference against X_ITE (mean, bootstrap interval, wins); validator verdict counts; not-run legs and
failures. Every number's tool is named in the footnotes. The HTML adds a contact sheet per scene (downscaled thumbnails of every
leg and its FLIP error map). The aggregation functions are pure (no images, no browser) and unit-tested."""
from __future__ import annotations

import base64
import html
import json
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scorecard import schema  # noqa: E402

OK = schema.OK
REF = schema.REFERENCE_LEG
XITE = schema.XITE_LEG
BOOT_N, BOOT_SEED = 5000, 1


# ------------------------------------------------------------------------------------------------ aggregation (pure)
def flip_of(rec, against="reference"):
    """Mean FLIP of a leg record against the reference (or `xite`), or None when the leg is not ok or has no metric."""
    if not rec or rec.get("status") != OK:
        return None
    m = (rec.get("metrics") or {}).get("flip_vs_" + against)
    return None if not m else m.get("mean")


def metric_of(rec, block, key):
    if not rec or rec.get("status") != OK:
        return None
    m = (rec.get("metrics") or {}).get(block)
    return None if not m else m.get(key)


def seconds_of(rec):
    if not rec or rec.get("status") != OK:
        return None
    return (rec.get("seconds") or {}).get("render")


def scene_legs(doc):
    """{scene name: {leg: record}} in file order."""
    return {s["name"]: s["legs"] for s in doc["scenes"]}


def compared_legs(doc):
    """The engine legs that have at least one scored result (they become table columns), in registry order."""
    legs = []
    for leg in schema.ENGINE_LEGS:
        if any(flip_of(s["legs"].get(leg)) is not None for s in doc["scenes"]):
            legs.append(leg)
    return legs


def not_run_legs(doc):
    """{leg: reason} for registry legs with no ok record in any scene: not-run reasons, or the failure summary."""
    out = {}
    for leg in schema.LEG_IDS:
        recs = [s["legs"].get(leg) for s in doc["scenes"]]
        if any(r and r.get("status") == OK for r in recs):
            continue
        reasons = [r.get("reason") for r in recs if r and r.get("reason")]
        status = sorted({r["status"] for r in recs if r})
        out[leg] = dict(statuses=status, reason=(statistics.mode(reasons) if reasons else "no records"))
    return out


def common_set(doc, legs, need_reference=True):
    """Scenes where every leg in `legs` has a usable FLIP against the reference (and the reference itself is ok)."""
    names = []
    for s in doc["scenes"]:
        if need_reference and (s["legs"].get(REF) or {}).get("status") != OK:
            continue
        if all(flip_of(s["legs"].get(l)) is not None for l in legs):
            names.append(s["name"])
    return names


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def engine_means(doc, legs, common):
    """Per leg: n_common / mean over the common set, n_own / mean over every scene the leg scored on, geometry mean, mean |delta| vs
    X_ITE, FLIP vs X_ITE and median render seconds (over the leg's own scenes)."""
    by = {s["name"]: s["legs"] for s in doc["scenes"]}
    out = {}
    for leg in legs:
        own = [(n, by[n][leg]) for n in by if flip_of(by[n].get(leg)) is not None]
        com = [by[n][leg] for n in common]
        out[leg] = dict(
            n_common=len(com), mean_common=mean([flip_of(r) for r in com]),
            n_own=len(own), mean_own=mean([flip_of(r) for _, r in own]),
            geometry_common=mean([metric_of(r, "flip_vs_reference", "geometry_mean") for r in com]),
            flip_vs_xite_common=mean([flip_of(r, "xite") for r in com]),
            mean_abs_vs_xite_common=mean([metric_of(r, "mean_abs_vs_xite", "mean_abs") for r in com]),
            median_seconds=median([seconds_of(r) for _, r in own]))
    return out


def noise_floor(doc):
    vals = [metric_of(s["legs"].get(REF), "noise_floor", "mean") for s in doc["scenes"]]
    vals = [v for v in vals if v is not None]
    return dict(n=len(vals), mean=mean(vals), max=max(vals) if vals else None, min=min(vals) if vals else None)


def bootstrap_ci(diffs, n=BOOT_N, seed=BOOT_SEED, alpha=0.05):
    """Percentile bootstrap interval of the mean of `diffs` (resampling scenes, deterministic). Returns (lo, hi) or (None, None)."""
    if len(diffs) < 2:
        return None, None
    rng = random.Random(seed)
    k = len(diffs)
    means = sorted(sum(diffs[rng.randrange(k)] for _ in range(k)) / k for _ in range(n))
    return means[int(n * alpha / 2)], means[min(n - 1, int(n * (1 - alpha / 2)))]


def paired_vs_xite(doc, legs, metric="mean"):
    """Per leg other than X_ITE: the per-scene difference (leg FLIP minus X_ITE FLIP, both against the reference; negative means the
    leg is closer to the reference than X_ITE is) over the scenes where both are scored."""
    out = {}
    for leg in legs:
        if leg == XITE:
            continue
        diffs, names = [], []
        for s in doc["scenes"]:
            a, b = flip_of(s["legs"].get(leg)), flip_of(s["legs"].get(XITE))
            if a is not None and b is not None:
                diffs.append(a - b)
                names.append(s["name"])
        lo, hi = bootstrap_ci(diffs)
        out[leg] = dict(n=len(diffs), mean_diff=mean(diffs), ci=(lo, hi), wins=sum(1 for d in diffs if d < 0), losses=sum(1 for d in diffs if d > 0),
                        ties=sum(1 for d in diffs if d == 0), scenes=names)
    return out


def validator_summary(doc):
    """Per leg: counts of verdicts over the scenes where the leg produced a record with a validator, plus the flagged scenes."""
    out = {}
    for leg in schema.LEG_IDS:
        counts, flagged, kind = {}, [], None
        for s in doc["scenes"]:
            r = s["legs"].get(leg)
            v = r.get("validator") if r else None
            if not v:
                continue
            kind = v.get("kind")
            counts[v["verdict"]] = counts.get(v["verdict"], 0) + 1
            if v["verdict"] not in ("pass",) or (v.get("warnings") or 0) > 0:
                flagged.append((s["name"], schema.mark(v), schema.mark_title(v)))
        if counts:
            out[leg] = dict(kind=kind, counts=counts, flagged=flagged,
                            warnings_total=sum((s["legs"][leg].get("validator") or {}).get("warnings") or 0 for s in doc["scenes"] if s["legs"].get(leg)))
    return out


def failures(doc):
    """[(scene, leg, status, reason)] for every leg that failed or is not-applicable."""
    rows = []
    for s in doc["scenes"]:
        for leg in schema.LEG_IDS:
            r = s["legs"].get(leg)
            if r and r["status"] in (schema.FAILED, schema.NOT_APPLICABLE):
                rows.append((s["name"], leg, r["status"], r.get("reason") or ""))
    return rows


def engine_version_of(doc, leg):
    for s in doc["scenes"]:
        r = s["legs"].get(leg)
        if r and r.get("status") == OK and r.get("engine_version"):
            return r["engine_version"]
    return None


# ------------------------------------------------------------------------------------------------------- formatting
def f4(x):
    return "—" if x is None else f"{x:.4f}"


def f2(x):
    return "—" if x is None else f"{x:.2f}"


def sgn4(x):
    return "—" if x is None else f"{x:+.4f}"


def secs(x):
    if x is None:
        return "—"
    return f"{x:.1f}" if x < 100 else f"{x:.0f}"


def cell(rec, with_mark=True):
    """Table cell text for a leg record: FLIP + mark, or the status word."""
    if not rec:
        return "—"
    st = rec["status"]
    if st == OK:
        v = flip_of(rec)
        m = schema.mark(rec.get("validator")) if with_mark else ""
        return (f4(v) + (" " + m if m else "")) if v is not None else ("no metric" + (" " + m if m else ""))
    return {schema.FAILED: "failed", schema.NOT_APPLICABLE: "n/a", schema.NOT_RUN: "not run"}[st]


def tool_line(doc):
    t = doc["rig"]["tools"]
    b = doc["rig"]["browser"]
    return dict(
        flip=f"flip-evaluator {t.get('flip_evaluator')} (LDR, default 67 ppd)", validator=f"Khronos glTF-Validator {t.get('gltf_validator')}",
        xite="X_ITE " + (t.get("x_ite_runtime") or "(no X_ITE leg in this run)"), babylon="Babylon.js " + (t.get("babylon_runtime") or "(no Babylon leg in this run)"),
        browser=f"Chromium {b.get('version') or '?'} ({b.get('gl') or 'GL unknown'})", blender=f"Blender {t.get('blender') or '?'} (bpy {t.get('bpy')})",
        castle=(f"Castle {t.get('castle_version')}" if t.get("castle_version") else None))


def footnotes(doc):
    """[(id, text)] naming the tool behind every kind of number in the report."""
    p, rig, t = doc["params"], doc["rig"], tool_line(doc)
    host = rig["host"]
    out = [
        ("F", f"FLIP = {t['flip']}: sRGB 8-bit {p['size']}x{p['size']} frames as float32, mean of the per-pixel error map over the whole frame, 0 = identical, "
              f"lower is better. Reference = {t['blender']} Cycles CPU, {p['spp']} spp, {p['bounces']} bounces, no denoise, seed {p['seeds'][0]}, ideal lights "
              f"(cycles_ref.py). FLIP is not symmetric: the reference is the first image."),
        ("G", f"Geometry FLIP = the same {t['flip']} error map averaged over pixels that are not background in both images "
              f"(background = the reference's most frequent corner colour, exact match; a backdrop that differs between renderers counts as geometry)."),
        ("X", f"Secondary: FLIP and mean |delta| with the {t['xite']} image as the reference ({t['flip']}). Mean |delta| = mean |a-b| over all pixels and "
              f"channels on the 8-bit scale 0..255, whole frame (the fidelity rig's definition; Python/numpy {rig['tools'].get('numpy')})."),
        ("V", f"Validator marks: {t['validator']} on every glb. ✓ 0 errors, 0 warnings; ✓w 0 errors with warnings; ✗ errors; ∅ EMPTY = valid but 0 triangles while the X3D "
              f"declares geometry (the validator proves structure only, an empty glb passes it); ? the validator did not run. x✓ / x✗ / x? = the X3D file parses "
              f"as XML with root X3D and a Scene (Python {rig['tools'].get('python')} xml.etree) / does not / is not an XML .x3d file."),
        ("T", f"Render seconds, wall clock, {host.get('vcpu_count')} shared vCPUs, no GPU. {t['xite']}: page load + loadURL until loaded, excluding a fixed settle wait. "
              f"{t['babylon']}: page load + glb load + first 5 frames. Both in {t['browser']}. Cycles: render of seed {p['seeds'][0]} ({t['blender']}, CPU, "
              f"{p.get('threads', 2)} threads). EEVEE: the first scene of the process includes the one-off shader compile (about 66 s). "
              f"Castle: castle-render in-process seconds. Not a frame rate: software GL."),
        ("D", f"Paired difference = per scene (leg FLIP minus X_ITE FLIP), both against the Cycles reference ({t['flip']}); negative = closer to the reference than X_ITE. "
              f"Interval = percentile bootstrap of the scene mean, {BOOT_N} resamples, seed {BOOT_SEED}, 95%; scenes are not independent, so it is indicative. "
              f"wins/losses = scenes where the leg is below/above X_ITE."),
        ("N", f"Noise floor = FLIP between the Cycles reference at seed {p['seeds'][0]} and at seed {p['seeds'][1]} ({t['flip']}): the spread of the reference image itself; "
              f"it is not the error bar of a leg-against-leg comparison."),
        ("R", "The reference is Cycles on the add-on's reading of the file, not truth: where the add-on drops a node or flattens a Background, the reference does too. "
              "Babylon (add-on glb) and Blender EEVEE share that reading and are NOT independent of the reference; X_ITE, Babylon (Castle glb) and Castle native read the file "
              "themselves. The add-on's default light units are calibrated to what X_ITE draws, so X_ITE-against-reference agreement on lit scenes is partly built in."),
    ]
    return out


def version_suffix(doc, leg):
    """The engine version for a column header, without repeating the label when the version string starts with it."""
    v = engine_version_of(doc, leg) or ""
    label = schema.LEGS[leg]["label"]
    return v[len(label):].strip() if v.startswith(label) else v


def mean_row(doc, legs, common):
    """The per-scene table's closing row: mean FLIP over the common scene set per leg, and the mean noise floor."""
    by = {s["name"]: s["legs"] for s in doc["scenes"]}
    return [f4(mean([flip_of(by[n][l]) for n in common])) for l in legs], f4(noise_floor(doc)["mean"])


def leg_header(doc, leg):
    spec = schema.LEGS[leg]
    ver = engine_version_of(doc, leg)
    return spec["label"], ver


def table_rows_flip(doc, legs):
    """Rows for the per-scene FLIP table: [(scene, [cell text...], noise floor text)]."""
    rows = []
    for s in doc["scenes"]:
        rows.append((s["name"], [cell(s["legs"].get(l)) for l in legs], f4(metric_of(s["legs"].get(REF), "noise_floor", "mean"))))
    return rows


def table_rows_xite(doc, legs):
    rows = []
    for s in doc["scenes"]:
        cells = []
        for l in legs:
            r = s["legs"].get(l)
            if l == XITE:
                cells.append("reference")
            elif not r or r["status"] != OK:
                cells.append(cell(r, with_mark=False))
            else:
                cells.append(f"{f4(flip_of(r, 'xite'))} / {f2(metric_of(r, 'mean_abs_vs_xite', 'mean_abs'))}")
        rows.append((s["name"], cells))
    return rows


def md_table(headers, rows, align=None):
    align = align or ["l"] + ["r"] * (len(headers) - 1)
    sep = ["---:" if a == "r" else ":---" for a in align]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(sep) + " |"]
    for r in rows:
        lines.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(lines)


def summary(doc):
    """All aggregates the two renderers show, computed once."""
    legs = compared_legs(doc)
    cs = common_set(doc, legs)
    return dict(legs=legs, common=cs, means=engine_means(doc, legs, cs), paired=paired_vs_xite(doc, legs), floor=noise_floor(doc),
                validators=validator_summary(doc), not_run=not_run_legs(doc), failures=failures(doc), notes=footnotes(doc))


# ---------------------------------------------------------------------------------------------------------- markdown
def render_markdown(doc) -> str:
    sm = summary(doc)
    legs, p, rig = sm["legs"], doc["params"], doc["rig"]
    n_scenes = len(doc["scenes"])
    L = []
    L.append("# Cross-engine scorecard")
    L.append("")
    L.append(f"Run {doc.get('created', '?')}: {n_scenes} scenes, {len(legs)} engine legs scored against the Blender Cycles reference "
             f"({p['spp']} spp, seeds {p['seeds'][0]} and {p['seeds'][1]}, {p['size']} x {p['size']}). FLIP is mean LDR-FLIP, lower is better [^F]. "
             f"Marks after a number are the validator verdict of what that engine read [^V].")
    L.append("")
    if sm["not_run"]:
        L.append("Legs without a usable result (recorded, never faked):")
        for leg, d in sm["not_run"].items():
            L.append(f"- `{leg}` ({schema.LEGS[leg]['label']}): {'/'.join(d['statuses'])}: {d['reason']}")
        L.append("")
    # table 1
    L.append("## 1. FLIP against the Cycles reference, per scene")
    L.append("")
    heads = ["scene"] + [("**" + schema.LEGS[l]["label"] + "**" + (f"<br>{version_suffix(doc, l)}" if version_suffix(doc, l) else "")) for l in legs] + ["Cycles floor [^N]"]
    mr, mf = mean_row(doc, legs, sm["common"])
    L.append(md_table(heads, [[n] + c + [fl] for n, c, fl in table_rows_flip(doc, legs)] +
                      [[f"**mean, common set ({len(sm['common'])})**"] + [f"**{x}**" for x in mr] + [mf]]))
    L.append("")
    L.append("Cells: FLIP [^F] then the validator mark [^V]; `failed` / `n/a` are leg statuses (reasons in section 6). The last column is the reference's own seed-to-seed FLIP [^N].")
    L.append("")
    # table 2
    L.append("## 2. Engine means")
    L.append("")
    cs = sm["common"]
    L.append(f"**Common scene set: {len(cs)} of {n_scenes} scenes**, those where every compared leg ({', '.join(schema.LEGS[l]['label'] for l in legs)}) has a scored result"
             + (": " + ", ".join(f"`{n}`" for n in cs) if cs else ". The common set is empty, so only the own-set means are given") + ". "
             "A mean over different scene sets is not comparable between legs; the own-set column is for completeness.")
    L.append("")
    rows = []
    for l in legs:
        m = sm["means"][l]
        rows.append([schema.LEGS[l]["label"], m["n_common"], f4(m["mean_common"]), f4(m["geometry_common"]), f4(m["flip_vs_xite_common"]),
                     f2(m["mean_abs_vs_xite_common"]), m["n_own"], f4(m["mean_own"]), secs(m["median_seconds"])])
    fl = sm["floor"]
    rows.append(["Cycles seed-to-seed floor", fl["n"], "—", "—", "—", "—", fl["n"], f4(fl["mean"]), "—"])
    L.append(md_table(["leg", "n (common)", "mean FLIP, common [^F]", "geometry FLIP, common [^G]", "FLIP vs X_ITE, common [^X]", "mean abs vs X_ITE, common (0..255) [^X]",
                       "n (own)", "mean FLIP, own set [^F]", "median render s [^T]"], rows))
    L.append("")
    if fl["n"]:
        L.append(f"Noise floor of the reference [^N]: mean {f4(fl['mean'])}, min {f4(fl['min'])}, max {f4(fl['max'])} over {fl['n']} scenes.")
        L.append("")
    # table 3
    L.append("## 3. Paired difference against X_ITE")
    L.append("")
    L.append("Per scene, leg FLIP minus X_ITE FLIP, both against the Cycles reference; negative = closer to the reference than X_ITE [^D].")
    L.append("")
    rows = []
    for l, d in sm["paired"].items():
        ci = "—" if d["ci"][0] is None else f"[{sgn4(d['ci'][0])}, {sgn4(d['ci'][1])}]"
        rows.append([schema.LEGS[l]["label"], d["n"], sgn4(d["mean_diff"]), ci, d["wins"], d["losses"], d["ties"]])
    if rows:
        L.append(md_table(["leg minus X_ITE", "n scenes", "mean difference", "95% bootstrap interval", "wins", "losses", "ties"], rows))
    else:
        L.append("No other leg has a scored scene in common with X_ITE.")
    L.append("")
    # table 4
    L.append("## 4. Against X_ITE (secondary): FLIP / mean |delta|")
    L.append("")
    L.append("Each cell: FLIP with the X_ITE image as reference / mean |delta| on 0..255 [^X]. The Cycles column is the reference image against X_ITE.")
    L.append("")
    legs_x = [l for l in schema.LEG_IDS if l != XITE and any((s["legs"].get(l) or {}).get("status") == OK for s in doc["scenes"])]
    if XITE in legs or any((s["legs"].get(XITE) or {}).get("status") == OK for s in doc["scenes"]):
        L.append(md_table(["scene"] + [schema.LEGS[l]["label"] for l in legs_x], [[n] + c for n, c in table_rows_xite(doc, legs_x)]))
    else:
        L.append("X_ITE has no scored scene in this run.")
    L.append("")
    # validator
    L.append("## 5. Validator verdicts")
    L.append("")
    rows = []
    for l, d in sm["validators"].items():
        what = "glTF-Validator" if d["kind"] == "gltf-validator" else "X3D well-formed"
        rows.append([schema.LEGS[l]["label"], what, ", ".join(f"{k} {v}" for k, v in sorted(d["counts"].items())), d["warnings_total"] if d["kind"] == "gltf-validator" else "—",
                     "; ".join(f"`{n}` {m}" for n, m, _ in d["flagged"][:8]) + (" ..." if len(d["flagged"]) > 8 else "") or "none"])
    L.append(md_table(["leg", "checker", "verdicts (scenes)", "warnings", "flagged scenes [^V]"], rows, ["l", "l", "l", "r", "l"]))
    L.append("")
    # timing/seconds already in 2; failures
    L.append("## 6. Failures and not-applicable")
    L.append("")
    if sm["failures"]:
        L.append(md_table(["scene", "leg", "status", "reason"], [[a, b, c, d.replace("|", "/")[:200]] for a, b, c, d in sm["failures"]], ["l", "l", "l", "l"]))
    else:
        L.append("None: every selected leg produced a result for every scene.")
    L.append("")
    # rig
    L.append("## 7. Rig fingerprint")
    L.append("")
    t, h, g, b = rig["tools"], rig["host"], rig["git"], rig["browser"]
    L.append(f"- Host: {h.get('vcpu_count')} vCPU ({h.get('cpu_model')}), {h.get('memory_gb')} GB, {h.get('gpu')}.")
    L.append(f"- Browser: Chromium {b.get('version')}, GL {b.get('gl')}; launch flags {', '.join(b.get('launch_flags') or [])}.")
    L.append(f"- Blender GL: {rig['blender_gl'].get('engine_leg')}; Mesa package {rig['blender_gl'].get('mesa_dri_package')}" +
             (f"; EEVEE GL renderer {rig['blender_gl']['eevee_gl_renderer']}" if rig["blender_gl"].get("eevee_gl_renderer") else "") + ".")
    L.append("- Tools: " + ", ".join(f"{k} {v}" for k, v in t.items() if v) + ".")
    L.append(f"- Git: add-on {str(g['addon'].get('revision'))[:12]}{' (dirty)' if g['addon'].get('dirty') else ''}; scorecard repo "
             f"{str(g['scorecard_repo'].get('revision'))[:12]}{' (dirty)' if g['scorecard_repo'].get('dirty') else ''}; Castle exporter inputs: "
             + ("; ".join(f"{k} {str((v or {}).get('git_revision', 'no git revision'))[:12]} sha256 {str((v or {}).get('sha256'))[:12]}" if v else f"{k} not set"
                          for k, v in g["castle"].items())) + ".")
    L.append(f"- Wall time of the legs (s): " + ", ".join(f"{k} {v}" for k, v in p.get("leg_wall_seconds", {}).items()) + ".")
    L.append("")
    L.append("## Reading notes")
    L.append("")
    for k, text in sm["notes"]:
        L.append(f"[^{k}]: {text}")
        L.append("")
    return "\n".join(L).rstrip() + "\n"


# -------------------------------------------------------------------------------------------------------------- HTML
CSS = """
:root{--bg:#fafaf8;--fg:#1d1f23;--mut:#62666d;--line:#d9dad5;--card:#fff;--accent:#c4501b;--ok:#1b7f4b;--bad:#b3261e;--warn:#9a6a00;--th:#eef0ec;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#15171a;--fg:#e4e6ea;--mut:#9aa0a8;--line:#2d3136;--card:#1c1f23;--accent:#ee8a55;--ok:#5fc98e;--bad:#ff7b72;--warn:#e3b341;--th:#23272c}}
:root[data-theme="dark"]{--bg:#15171a;--fg:#e4e6ea;--mut:#9aa0a8;--line:#2d3136;--card:#1c1f23;--accent:#ee8a55;--ok:#5fc98e;--bad:#ff7b72;--warn:#e3b341;--th:#23272c}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:13px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1500px;margin:0 auto;padding:16px}h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:26px 0 6px;border-bottom:1px solid var(--line);padding-bottom:3px}
p,li{max-width:110ch}.mut{color:var(--mut)}.kpis{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}.kpi{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:6px 10px;min-width:150px}
.kpi b{display:block;font-size:17px;font-variant-numeric:tabular-nums}.kpi span{color:var(--mut);font-size:11px}
.tw{overflow-x:auto;border:1px solid var(--line);border-radius:6px;background:var(--card)}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:3px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th{background:var(--th);font-weight:600;position:sticky;top:0}
th:first-child,td:first-child{text-align:left;position:sticky;left:0;background:var(--card);z-index:1}th:first-child{background:var(--th)}tr:last-child td{border-bottom:0}
td.h{background:color-mix(in srgb,var(--accent) calc(var(--h,0)*70%),transparent)}td.na{color:var(--mut)}td.bad{color:var(--bad)}
.m{font-family:var(--mono);font-size:11px;margin-left:3px}.m.ok{color:var(--ok)}.m.bad{color:var(--bad)}.m.warn{color:var(--warn)}
sup a{color:var(--accent);text-decoration:none}code{font-family:var(--mono);font-size:11.5px}
.sheet{margin:10px 0 14px;background:var(--card);border:1px solid var(--line);border-radius:6px;padding:8px}.sheet h3{margin:0 0 6px;font-size:13px}
.strip{display:flex;flex-wrap:wrap;gap:8px}.t{width:var(--tw,160px)}.t img{display:block;width:100%;height:auto;border:1px solid var(--line);background:#000;image-rendering:auto}
.t figcaption{font-size:11px;line-height:1.3;margin-top:2px;overflow-wrap:anywhere}.t figure{margin:0}.t .hm{margin-top:3px}
.noimg{width:100%;aspect-ratio:1;display:flex;align-items:center;justify-content:center;border:1px dashed var(--line);color:var(--mut);font-size:11px;text-align:center;padding:4px}
.legend{display:flex;flex-wrap:wrap;gap:4px 14px;margin:6px 0}.ctl{margin:6px 0}label{cursor:pointer}
body.nomaps .hm{display:none}ol.fn{padding-left:22px}ol.fn li{margin:3px 0}.scene-id{font-family:var(--mono)}
@media (max-width:640px){main{padding:12px 16px}.kpi{min-width:44%}}
"""


def _esc(x):
    return html.escape(str(x), quote=True)


def _mark_html(v):
    m = schema.mark(v)
    if not m:
        return ""
    cls = "bad" if m in ("✗", "∅", "?", "x✗") else ("warn" if m in ("✓w", "x?") else "ok")
    return f'<span class="m {cls}" title="{_esc(schema.mark_title(v))}">{_esc(m)}</span>'


def _fn(k):
    return f'<sup><a href="#fn-{k}">[{k}]</a></sup>'


def _td_flip(rec, scale=0.2):
    if not rec:
        return '<td class="na">—</td>'
    st = rec["status"]
    if st != OK:
        word = {schema.FAILED: "failed", schema.NOT_APPLICABLE: "n/a", schema.NOT_RUN: "not run"}[st]
        cls = "bad" if st == schema.FAILED else "na"
        return f'<td class="{cls}" title="{_esc(rec.get("reason") or "")}">{word}</td>'
    v = flip_of(rec)
    if v is None:
        return f'<td class="na">no metric {_mark_html(rec.get("validator"))}</td>'
    h = max(0.0, min(1.0, v / scale))
    fm = rec["metrics"]["flip_vs_reference"]
    tip = (f"FLIP {v:.4f}; geometry FLIP {f4(fm.get('geometry_mean'))} over {fm.get('geometry_fraction', 0):.1%} of pixels; "
           f"{rec.get('engine_version')}; reads {rec.get('input', {}).get('kind')}; render {secs(seconds_of(rec))} s")
    return f'<td class="h" style="--h:{h:.3f}" title="{_esc(tip)}">{v:.4f}{_mark_html(rec.get("validator"))}</td>'


def _thumb(out_dir, rel, size, fmt, cache):
    if not rel:
        return None
    path = os.path.join(out_dir, rel)
    if not os.path.exists(path):
        return None
    key = (path, size, fmt)
    if key not in cache:
        from scorecard import metrics
        data = metrics.thumbnail_bytes(path, size, fmt)
        cache[key] = f"data:image/{'jpeg' if fmt == 'JPEG' else 'png'};base64," + base64.b64encode(data).decode()
    return cache[key]


def render_html(doc, out_dir=None, thumb=160, heat_thumb=112) -> str:
    sm = summary(doc)
    legs, p, rig = sm["legs"], doc["params"], doc["rig"]
    n_scenes = len(doc["scenes"])
    cache: dict = {}
    t = tool_line(doc)
    H = []
    H.append("<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>")
    H.append("<title>Cross-engine scorecard</title><style>" + CSS + "</style></head><body><main>")
    H.append("<h1>Cross-engine scorecard</h1>")
    H.append(f"<p class='mut'>Run {_esc(doc.get('created', '?'))}. {n_scenes} scenes through {len(legs)} engine legs, each scored against a Blender Cycles reference "
             f"({p['spp']} spp, {p['bounces']} bounces, no denoise, seeds {p['seeds'][0]}/{p['seeds'][1]}, {p['size']}&times;{p['size']}). FLIP{_fn('F')}, lower is better; "
             f"marks after a number are the validator verdict of what that engine read{_fn('V')}.</p>")
    cs = sm["common"]
    kp = [("scenes", n_scenes, "in this run"), ("common set", f"{len(cs)} / {n_scenes}", "scenes every compared leg scored")]
    for l in legs:
        m = sm["means"][l]
        kp.append((schema.LEGS[l]["label"], f4(m["mean_common"]), f"mean FLIP, common set (n={m['n_common']})"))
    fl = sm["floor"]
    if fl["n"]:
        kp.append(("Cycles floor", f4(fl["mean"]), f"seed-to-seed FLIP, mean of {fl['n']}"))
    H.append("<div class='kpis'>" + "".join(f"<div class='kpi'><span>{_esc(a)}</span><b>{_esc(b)}</b><span>{_esc(c)}</span></div>" for a, b, c in kp) + "</div>")
    if sm["not_run"]:
        H.append("<p><b>Legs without a usable result</b> (recorded, never faked):</p><ul>" + "".join(
            f"<li><code>{_esc(l)}</code> ({_esc(schema.LEGS[l]['label'])}): {_esc('/'.join(d['statuses']))}: {_esc(d['reason'])}</li>" for l, d in sm["not_run"].items()) + "</ul>")
    # legend
    H.append("<div class='legend'>" + "".join(f"<span>{_mark_html(v)} {_esc(txt)}</span>" for v, txt in [
        (dict(kind="gltf-validator", verdict="pass", warnings=0, errors=0, triangles=1), "glb valid, 0 warnings"),
        (dict(kind="gltf-validator", verdict="pass", warnings=1, errors=0, triangles=1), "valid with warnings"),
        (dict(kind="gltf-validator", verdict="fail", errors=1), "validator errors"),
        (dict(kind="gltf-validator", verdict="empty", errors=0, warnings=0, triangles=0, empty=True), "EMPTY: valid, 0 triangles, X3D has geometry"),
        (dict(kind="x3d-wellformed", verdict="pass"), "X3D well-formed"),
        (dict(kind="x3d-wellformed", verdict="fail"), "X3D not well-formed")]) + "</div>")

    def table(head_cells, body):
        return "<div class='tw'><table><thead><tr>" + "".join(head_cells) + "</tr></thead><tbody>" + "".join(body) + "</tbody></table></div>"

    # 1 per-scene FLIP
    H.append(f"<h2>1. FLIP against the Cycles reference, per scene{_fn('F')}</h2>")
    hc = ["<th>scene</th>"] + [f"<th title='{_esc(schema.LEGS[l]['what'])}'>{_esc(schema.LEGS[l]['label'])}<br><span class='mut'>{_esc(version_suffix(doc, l))}</span></th>" for l in legs] + [f"<th>Cycles floor{_fn('N')}</th>"]
    body = []
    for s in doc["scenes"]:
        row = [f"<td class='scene-id'>{_esc(s['name'])}</td>"] + [_td_flip(s["legs"].get(l)) for l in legs]
        nf = metric_of(s["legs"].get(REF), "noise_floor", "mean")
        row.append(f"<td class='{'na' if nf is None else ''}'>{f4(nf)}</td>")
        body.append("<tr>" + "".join(row) + "</tr>")
    mr, mf = mean_row(doc, legs, cs)
    body.append(f"<tr><td><b>mean, common set ({len(cs)})</b></td>" + "".join(f"<td><b>{x}</b></td>" for x in mr) + f"<td>{mf}</td></tr>")
    H.append(table(hc, body))
    # 2 means
    H.append(f"<h2>2. Engine means</h2><p><b>Common scene set: {len(cs)} of {n_scenes} scenes</b> where every compared leg ({_esc(', '.join(schema.LEGS[l]['label'] for l in legs))}) has a scored result"
             + (": " + ", ".join(f"<code>{_esc(n)}</code>" for n in cs) if cs else "; it is empty, only own-set means exist") + ". Means over different scene sets are not comparable between legs.</p>")
    hc = [f"<th>leg</th>", "<th>n common</th>", f"<th>mean FLIP, common{_fn('F')}</th>", f"<th>geometry FLIP, common{_fn('G')}</th>", f"<th>FLIP vs X_ITE, common{_fn('X')}</th>",
          f"<th>mean |&Delta;| vs X_ITE, common (0..255){_fn('X')}</th>", "<th>n own</th>", f"<th>mean FLIP, own set{_fn('F')}</th>", f"<th>median render s{_fn('T')}</th>"]
    body = []
    for l in legs:
        m = sm["means"][l]
        body.append("<tr>" + f"<td>{_esc(schema.LEGS[l]['label'])}</td><td>{m['n_common']}</td><td>{f4(m['mean_common'])}</td><td>{f4(m['geometry_common'])}</td><td>{f4(m['flip_vs_xite_common'])}</td>"
                    f"<td>{f2(m['mean_abs_vs_xite_common'])}</td><td>{m['n_own']}</td><td>{f4(m['mean_own'])}</td><td>{secs(m['median_seconds'])}</td></tr>")
    body.append(f"<tr><td>Cycles seed-to-seed floor{_fn('N')}</td><td>{fl['n']}</td><td>—</td><td>—</td><td>—</td><td>—</td><td>{fl['n']}</td><td>{f4(fl['mean'])}</td><td>—</td></tr>")
    H.append(table(hc, body))
    # 3 paired
    H.append(f"<h2>3. Paired difference against X_ITE{_fn('D')}</h2><p class='mut'>Leg FLIP minus X_ITE FLIP per scene, both against the reference; negative = closer to the reference than X_ITE.</p>")
    body = []
    for l, d in sm["paired"].items():
        ci = "—" if d["ci"][0] is None else f"[{sgn4(d['ci'][0])}, {sgn4(d['ci'][1])}]"
        body.append(f"<tr><td>{_esc(schema.LEGS[l]['label'])}</td><td>{d['n']}</td><td>{sgn4(d['mean_diff'])}</td><td>{ci}</td><td>{d['wins']}</td><td>{d['losses']}</td><td>{d['ties']}</td></tr>")
    H.append(table(["<th>leg minus X_ITE</th>", "<th>n scenes</th>", "<th>mean difference</th>", "<th>95% bootstrap interval</th>", "<th>wins</th>", "<th>losses</th>", "<th>ties</th>"], body)
             if body else "<p class='mut'>No other leg has a scored scene in common with X_ITE.</p>")
    # 4 vs xite
    legs_x = [l for l in schema.LEG_IDS if l != XITE and any((s["legs"].get(l) or {}).get("status") == OK for s in doc["scenes"])]
    H.append(f"<h2>4. Against X_ITE (secondary): FLIP / mean |&Delta;|{_fn('X')}</h2>")
    if legs_x:
        body = ["<tr>" + f"<td class='scene-id'>{_esc(n)}</td>" + "".join(f"<td>{_esc(c)}</td>" for c in cells) + "</tr>" for n, cells in table_rows_xite(doc, legs_x)]
        H.append(table(["<th>scene</th>"] + [f"<th>{_esc(schema.LEGS[l]['label'])}</th>" for l in legs_x], body))
    else:
        H.append("<p class='mut'>No leg other than X_ITE has a scored result.</p>")
    # 5 validators
    H.append(f"<h2>5. Validator verdicts{_fn('V')}</h2>")
    body = []
    for l, d in sm["validators"].items():
        what = f"glTF-Validator {_esc(t['validator'].split()[-1])}" if d["kind"] == "gltf-validator" else "X3D well-formedness"
        fl_ = "; ".join(f"<code>{_esc(n)}</code> {_esc(m)}" for n, m, _ in d["flagged"][:10]) + (" ..." if len(d["flagged"]) > 10 else "")
        body.append(f"<tr><td>{_esc(schema.LEGS[l]['label'])}</td><td style='text-align:left'>{what}</td><td style='text-align:left'>{_esc(', '.join(f'{k} {v}' for k, v in sorted(d['counts'].items())))}</td>"
                    f"<td>{d['warnings_total'] if d['kind'] == 'gltf-validator' else '—'}</td><td style='text-align:left;white-space:normal'>{fl_ or 'none'}</td></tr>")
    H.append(table(["<th>leg</th>", "<th style='text-align:left'>checker</th>", "<th style='text-align:left'>verdicts (scenes)</th>", "<th>warnings</th>", "<th style='text-align:left'>flagged scenes</th>"], body))
    # 6 failures
    H.append("<h2>6. Failures and not-applicable</h2>")
    if sm["failures"]:
        body = [f"<tr><td class='scene-id'>{_esc(a)}</td><td style='text-align:left'>{_esc(b)}</td><td style='text-align:left'>{_esc(c)}</td><td style='text-align:left;white-space:normal'>{_esc(d[:300])}</td></tr>" for a, b, c, d in sm["failures"]]
        H.append(table(["<th>scene</th>"] + [f"<th style='text-align:left'>{x}</th>" for x in ("leg", "status", "reason")], body))
    else:
        H.append("<p class='mut'>None: every selected leg produced a result for every scene.</p>")
    # contact sheets
    H.append(f"<h2>7. Contact sheets</h2><p class='mut'>Every leg's 512&times;512 render downscaled to {thumb}px (reference first), with its FLIP error map{_fn('F')} below it "
             f"(magma, 0 dark to 1 bright). Caption: FLIP against the reference, validator mark, render seconds{_fn('T')}.</p>"
             "<div class='ctl'><label><input type='checkbox' id='maps' checked> show FLIP error maps</label></div>")
    order = [REF] + [l for l in schema.ENGINE_LEGS]
    for s in doc["scenes"]:
        strip = []
        for l in order:
            r = s["legs"].get(l)
            label = schema.LEGS[l]["label"]
            if not r or r["status"] != OK or not out_dir:
                reason = (r or {}).get("status", "—")
                if r and r["status"] == schema.NOT_RUN:
                    continue
                strip.append(f"<div class='t'><figure><div class='noimg' title='{_esc((r or {}).get('reason') or '')}'>{_esc(reason)}</div><figcaption><b>{_esc(label)}</b></figcaption></figure></div>")
                continue
            img = _thumb(out_dir, r.get("image"), thumb, "JPEG", cache)
            fm = (r.get("metrics") or {}).get("flip_vs_reference")
            heat = _thumb(out_dir, fm.get("heat") if fm else None, heat_thumb, "JPEG", cache)
            cap = f"<b>{_esc(label)}</b><br>" + (f"FLIP {f4(fm['mean'])}" if fm else ("reference" if l == REF else "no metric")) + _mark_html(r.get("validator")) + f" · {secs(seconds_of(r))} s"
            hm = f"<img class='hm' alt='FLIP error map' src='{heat}' style='width:70%'>" if heat else ""
            if l == REF:
                nf = (r.get("metrics") or {}).get("noise_floor")
                hm = f"<div class='mut hm' style='font-size:11px'>floor {f4(nf['mean'])}</div>" if nf else ""
            strip.append(f"<div class='t'><figure><img alt='{_esc(label)} on {_esc(s['name'])}' src='{img}'><figcaption>{cap}</figcaption></figure>{hm}</div>")
        H.append(f"<div class='sheet'><h3 class='scene-id'>{_esc(s['name'])}</h3><div class='strip' style='--tw:{thumb}px'>{''.join(strip)}</div></div>")
    # rig
    h, g, b = rig["host"], rig["git"], rig["browser"]
    H.append("<h2>8. Rig fingerprint</h2><ul>")
    H.append(f"<li>Host: {h.get('vcpu_count')} vCPU ({_esc(h.get('cpu_model'))}), {h.get('memory_gb')} GB, {_esc(h.get('gpu'))}.</li>")
    H.append(f"<li>Browser: Chromium {_esc(b.get('version'))}, GL {_esc(b.get('gl'))}; flags <code>{_esc(' '.join(b.get('launch_flags') or []))}</code>.</li>")
    H.append(f"<li>Blender GL: {_esc(rig['blender_gl'].get('engine_leg'))}; Mesa package {_esc(rig['blender_gl'].get('mesa_dri_package'))}.</li>")
    H.append("<li>Tools: " + _esc(", ".join(f"{k} {v}" for k, v in rig["tools"].items() if v)) + ".</li>")
    H.append(f"<li>Git: add-on <code>{_esc(str(g['addon'].get('revision'))[:12])}</code>{' (dirty)' if g['addon'].get('dirty') else ''}; scorecard repo "
             f"<code>{_esc(str(g['scorecard_repo'].get('revision'))[:12])}</code>{' (dirty)' if g['scorecard_repo'].get('dirty') else ''}; Castle exporter inputs: "
             + _esc("; ".join(f"{k} {str((v or {}).get('git_revision', 'no git revision'))[:12]} sha256 {str((v or {}).get('sha256'))[:12]}" if v else f"{k} not set" for k, v in g["castle"].items())) + ".</li>")
    H.append("<li>Leg wall seconds: " + _esc(", ".join(f"{k} {v}" for k, v in p.get("leg_wall_seconds", {}).items())) + ".</li></ul>")
    H.append("<h2>Footnotes: what each number is, and the tool behind it</h2><ol class='fn' style='list-style:none;padding-left:0'>" +
             "".join(f"<li id='fn-{k}'><b>[{k}]</b> {_esc(txt)}</li>" for k, txt in sm["notes"]) + "</ol>")
    H.append("<script>document.getElementById('maps').addEventListener('change',function(e){document.body.classList.toggle('nomaps',!e.target.checked)});</script>")
    H.append("</main></body></html>")
    return "".join(H)


def build(out_dir):
    """Write scorecard.md and scorecard.html next to results.json in out_dir."""
    with open(os.path.join(out_dir, "results.json")) as f:
        doc = json.load(f)
    problems = schema.check_results(doc)
    if problems:
        print("report: results.json has schema problems:\n  " + "\n  ".join(problems[:20]), file=sys.stderr)
    with open(os.path.join(out_dir, "scorecard.md"), "w") as f:
        f.write(render_markdown(doc))
    with open(os.path.join(out_dir, "scorecard.html"), "w") as f:
        f.write(render_html(doc, out_dir))
    return problems


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(1 if build(sys.argv[1]) else 0)
