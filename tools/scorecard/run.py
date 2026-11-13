#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Cross-engine scorecard driver: ONE run, ONE results.json, every scene through every engine leg.

    python3 tools/scorecard/run.py --scenes SCENES.json --out DIR [--legs LIST] [--resume] [--spp 256] [--only a,b]

SCENES.json is the fidelity rig's format (a list of {name, x3d, ...}; paths relative to --base, default tools/fidelity_rig).
--legs: comma list of leg ids (blender_cycles, xite, babylon_addon_glb, babylon_castle_glb, castle_native, blender_eevee) or `all`
(default). Environment: BPY_PYTHON (a Python with bpy), CASTLE_CONVERT and CASTLE_RENDER (optional legs; absent means the leg is
recorded `not-run` with that reason, never faked and never dropped), X3D_BLENDER_IO_SOURCE is not needed (the add-on is this checkout).

Per scene and leg it records engine + version, the input it read, status (ok / failed / not-applicable / not-run, with the reason),
the validator verdict (Khronos glTF-Validator on every glb, X3D well-formedness on the X3D inputs), FLIP against the Cycles reference
and against X_ITE, mean |delta| against X_ITE and the render time; the top of results.json has the rig fingerprint. Then report.py
turns results.json into scorecard.md and scorecard.html. The scoring is idempotent: --resume keeps every record that is ok (or
not-applicable) for the same scene bytes and the same settings, re-runs failed and not-run ones, and recomputes a metric only when
the images behind it changed.

Layout of --out: results.json, scorecard.md, scorecard.html, scenes/<scene>/<leg>.png (the renders), scenes/<scene>/flip_<leg>.png
(FLIP error maps against the reference), logs/ (one log per subprocess), work/ (glbs, validator reports, job files)."""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sys
import time

sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scorecard import common, legs as legs_pkg, schema  # noqa: E402

CYCLES_BOUNCES = 12


# ---------------------------------------------------------------------------------------------------- pure helpers
def parse_legs(text: str) -> list[str]:
    """The legs a --legs value selects, in execution order. Unknown ids are an error."""
    if text.strip().lower() in ("", "all"):
        return list(legs_pkg.ORDER)
    want = [t.strip() for t in text.split(",") if t.strip()]
    bad = [t for t in want if t not in schema.LEGS]
    if bad:
        raise ValueError(f"unknown leg id(s) {bad}; known: {', '.join(schema.LEG_IDS)}")
    return [l for l in legs_pkg.ORDER if l in want]


def config_key(ctx, leg: str) -> dict:
    """The settings whose change makes an earlier record stale for --resume."""
    key = dict(size=ctx.size)
    if leg == "blender_cycles":
        key.update(spp=ctx.spp, seeds=list(ctx.seeds), max_bounces=CYCLES_BOUNCES, denoise="none")
    if leg in ("babylon_addon_glb", "blender_cycles", "blender_eevee"):
        key["addon_source"] = list(ctx.addon_rev) if getattr(ctx, "addon_rev", None) else None
    return key


def reusable(rec: dict | None, scene_sha256: str, key: dict, out_dir) -> bool:
    """--resume rule: an earlier record is kept when it is ok or not-applicable, was made for the same scene bytes and settings, and
    its image is still on disk. failed and not-run records are always retried."""
    if not rec or rec.get("status") not in (schema.OK, schema.NOT_APPLICABLE):
        return False
    if rec.get("scene_sha256") != scene_sha256 or rec.get("config_key") != key:
        return False
    if rec["status"] == schema.OK:
        img = rec.get("image")
        if not img or not os.path.exists(os.path.join(out_dir, img)):
            return False
    return True


def metrics_sig(*paths) -> str:
    import hashlib
    h = hashlib.sha256()
    for p in paths:
        h.update((common.sha256_file(p) if p and os.path.exists(p) else "-").encode())
    return h.hexdigest()[:16]


def blank_scene_record(scene, base) -> dict:
    rec = scene.record_header(base)
    rec["legs"] = {}
    for leg in schema.LEG_IDS:
        r = schema.new_leg_record(leg, schema.NOT_RUN, "not run yet")
        r["scene_sha256"] = scene.sha256
        rec["legs"][leg] = r
    return rec


def complete_record(ctx, leg, scene, partial: dict, key: dict) -> dict:
    """A schema record from a leg module's result, with the image copied under scenes/<scene>/."""
    rec = schema.new_leg_record(leg, partial["status"], partial.get("reason"))
    for k in ("engine_version", "input", "validator", "seconds", "config", "notes", "tool"):
        if partial.get(k) is not None:
            rec[k] = partial[k]
    rec["config_key"], rec["scene_sha256"] = key, scene.sha256
    scene.sdir.mkdir(parents=True, exist_ok=True)
    src = partial.get("image_src")
    if rec["status"] == schema.OK and src and os.path.exists(src):
        dst = scene.sdir / f"{leg}.png"
        shutil.copyfile(src, dst)
        rec["image"] = ctx.rel(dst)
        for name, p in (partial.get("extra_images") or {}).items():
            if os.path.exists(p):
                d = scene.sdir / f"{leg}_{name}.png"
                shutil.copyfile(p, d)
                rec["extra_images"][name] = ctx.rel(d)
    elif rec["status"] == schema.OK:
        rec["status"], rec["reason"] = schema.FAILED, "the leg reported ok but wrote no image"
    if rec["status"] == schema.OK and not rec["engine_version"]:
        rec["engine_version"] = "unknown"
    return rec


# ----------------------------------------------------------------------------------------------------- scoring
def score_scene(ctx, scene, srec: dict, heat: bool = True) -> int:
    """FLIP and mean |delta| for every ok leg of one scene. Returns the number of metric blocks (re)computed."""
    from scorecard import metrics
    L = srec["legs"]

    def img(leg):
        r = L[leg]
        return os.path.join(ctx.out, r["image"]) if r["status"] == schema.OK and r.get("image") else None

    ref, xit = img(schema.REFERENCE_LEG), img(schema.XITE_LEG)
    done = 0
    for leg, r in L.items():
        p = img(leg)
        if not p:
            r["metrics"] = {}
            r["metrics_sig"] = None
            continue
        seed1 = os.path.join(ctx.out, r["extra_images"]["seed" + str(ctx.seeds[1])]) if (leg == schema.REFERENCE_LEG and len(ctx.seeds) > 1 and r.get("extra_images", {}).get("seed" + str(ctx.seeds[1]))) else None
        sig = metrics_sig(p, ref, xit, seed1)
        heat_path = scene.sdir / f"flip_{leg}.png"
        if r.get("metrics_sig") == sig and r.get("metrics") and (not heat or leg == schema.REFERENCE_LEG or heat_path.exists()):
            continue
        m: dict = {}
        try:
            if leg != schema.REFERENCE_LEG and ref:
                d = metrics.pair_metrics(ref, p, str(heat_path) if heat else None)
                m["flip_vs_reference"] = {k: v for k, v in d.items() if not k.startswith("mean_abs")} | dict(
                    reference_leg=schema.REFERENCE_LEG, tool="flip-evaluator " + str(common.pkg_version("flip-evaluator")) + " LDR",
                    heat=(ctx.rel(heat_path) if heat else None))
            if leg != schema.XITE_LEG and xit:
                d = metrics.pair_metrics(xit, p)
                m["flip_vs_xite"] = {k: v for k, v in d.items() if not k.startswith("mean_abs")} | dict(reference_leg=schema.XITE_LEG)
                m["mean_abs_vs_xite"] = dict(mean_abs=d["mean_abs"], mean_abs_geometry=d["mean_abs_geometry"], scale="0..255, whole frame")
            if seed1:
                d = metrics.pair_metrics(p, seed1)
                m["noise_floor"] = {k: v for k, v in d.items() if not k.startswith("mean_abs")} | dict(
                    seeds=[ctx.seeds[0], ctx.seeds[1]], what="FLIP between two Cycles seeds, seed %d as reference" % ctx.seeds[0])
        except (ValueError, OSError) as e:
            r["notes"] = list(r["notes"]) + [f"metrics failed: {e}"]
        r["metrics"], r["metrics_sig"] = m, sig
        done += 1
    return done


# --------------------------------------------------------------------------------------------------------- driver
def write_json(path, doc):
    tmp = str(path) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def load_existing(path):
    try:
        with open(path) as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and doc.get("schema") == schema.SCHEMA else None


def finalize_rig(ctx, rig: dict, old: dict | None) -> dict:
    t = ctx.tools
    if t.get("browser"):
        rig["browser"]["version"] = t["browser"]
    rig["tools"].update({k: v for k, v in dict(
        x_ite_runtime=t.get("x_ite"), babylon_runtime=t.get("babylon"), blender=t.get("blender"), addon_commit_seen_by_blender=t.get("addon_commit"),
        castle_render=t.get("castle_render"), castle_version=t.get("castle_version")).items() if v})
    if t.get("castle_gl_renderer"):
        rig["blender_gl"]["castle_gl_renderer"] = t["castle_gl_renderer"]
    if t.get("eevee_gl_renderer"):
        rig["blender_gl"]["eevee_gl_renderer"] = t["eevee_gl_renderer"]
    if old:   # a resumed run keeps what an earlier run learned and this one did not touch
        def fill(new, prev):
            for k, v in (prev or {}).items():
                if isinstance(v, dict) and isinstance(new.get(k), dict):
                    fill(new[k], v)
                elif new.get(k) is None and v is not None:
                    new[k] = v
        fill(rig, old.get("rig"))
    return rig


def run(args) -> int:
    t_start = time.time()
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    ctx = common.Ctx(out, base=args.base, addon=args.addon, spp=args.spp, seeds=[int(x) for x in args.seeds.split(",")], size=args.size,
                     threads=args.threads, verbose=not args.quiet, timeouts=dict(per_scene_web=args.timeout_web, per_scene_cycles=args.timeout_cycles,
                                                         per_scene_eevee=args.timeout_eevee))
    if len(ctx.seeds) < 2:
        raise SystemExit("--seeds needs two seeds (the second gives the reference's noise floor)")
    ctx.addon_rev = ctx.manifest.git_revision(str(ctx.addon))
    selected = parse_legs(args.legs)
    only = set(args.only.split(",")) if args.only else None
    scenes = common.load_scenes(args.scenes, ctx.base, out, ctx.addon, only)
    ctx.log(f"scorecard: {len(scenes)} scenes, legs {selected}, spp {ctx.spp}, seeds {ctx.seeds}, size {ctx.size}, out {out}")
    results_path = os.path.join(out, "results.json")
    old = load_existing(results_path) if args.resume else None
    old_scenes = {s["name"]: s for s in (old or {}).get("scenes", [])}

    doc = dict(schema=schema.SCHEMA, created=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               params=dict(spp=ctx.spp, seeds=list(ctx.seeds), size=ctx.size, threads=ctx.threads, bounces=CYCLES_BOUNCES, legs_selected=selected,
                           scenes_file=os.path.basename(args.scenes), flip="flip-evaluator LDR, default 67 ppd", resumed=bool(old),
                           reference="blender_cycles", leg_wall_seconds={}),
               rig=common.collect_fingerprint(ctx), legs={k: dict(v) for k, v in schema.LEGS.items()}, scenes=[])
    recs = {}
    for s in scenes:
        r = blank_scene_record(s, ctx.base)
        prev = old_scenes.get(s.name)
        if prev and prev.get("x3d", {}).get("sha256") == s.sha256:
            for leg, lr in prev.get("legs", {}).items():
                if leg in r["legs"]:
                    r["legs"][leg] = lr
        recs[s.name] = r
        doc["scenes"].append(r)
    if old and old.get("params", {}).get("leg_wall_seconds"):
        doc["params"]["leg_wall_seconds"].update(old["params"]["leg_wall_seconds"])

    def save():
        doc["rig"] = finalize_rig(ctx, doc["rig"], old)
        write_json(results_path, doc)

    # which legs run, which are not-run, which are reused
    for leg in schema.LEG_IDS:
        if leg not in selected:
            for s in scenes:
                lr = recs[s.name]["legs"][leg]
                if lr["status"] == schema.NOT_RUN or not reusable(lr, s.sha256, config_key(ctx, leg), out):
                    recs[s.name]["legs"][leg] = _not_run(leg, s, "not selected in --legs")
    for leg in selected:
        mod = legs_pkg.load(leg)
        key = config_key(ctx, leg)
        todo = [s for s in scenes if not reusable(recs[s.name]["legs"][leg], s.sha256, key, out)]
        ctx.log(f"== leg {leg}: {len(todo)} to run, {len(scenes) - len(todo)} reused")
        if not todo:
            continue
        good, why = mod.available(ctx)
        if not good:
            ctx.log(f"   {leg} not run: {why}")
            for s in todo:
                recs[s.name]["legs"][leg] = _not_run(leg, s, why)
            save()
            continue
        t0 = time.time()
        results = mod.run(ctx, todo)
        doc["params"]["leg_wall_seconds"][leg] = round(time.time() - t0, 1)
        for s in todo:
            partial = results.get(s.name) or legs_pkg.failed("the leg returned no result for this scene")
            recs[s.name]["legs"][leg] = complete_record(ctx, leg, s, partial, key)
            r = recs[s.name]["legs"][leg]
            ctx.log(f"   {s.name:32s} {leg:20s} {r['status']:14s} {(r['reason'] or '')[:100]}")
        save()

    ctx.log("== scoring")
    n = 0
    for s in scenes:
        n += score_scene(ctx, s, recs[s.name], heat=not args.no_heat)
    ctx.log(f"   metric blocks (re)computed: {n}")
    doc["params"]["wall_seconds_this_run"] = round(time.time() - t_start, 1)
    save()
    problems = schema.check_results(doc)
    for p in problems:
        ctx.log("SCHEMA PROBLEM: " + p)
    if not args.no_report:
        from scorecard import report
        report.build(out)
        ctx.log("report: scorecard.md and scorecard.html written")
    counts: dict = {}
    for s in scenes:
        for leg, r in recs[s.name]["legs"].items():
            counts.setdefault(leg, {}).setdefault(r["status"], 0)
            counts[leg][r["status"]] += 1
    for leg in schema.LEG_IDS:
        ctx.log(f"   {leg:20s} {counts.get(leg)}")
    failed = sum(c.get(schema.FAILED, 0) for c in counts.values())
    ctx.log(f"done in {round(time.time() - t_start, 1)} s; results {results_path}")
    if problems:
        return 1
    return 1 if (args.strict and failed) else 0


def _not_run(leg, scene, reason):
    r = schema.new_leg_record(leg, schema.NOT_RUN, reason)
    r["scene_sha256"] = scene.sha256
    return r


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scenes", required=True, help="scenes JSON in the rig's format")
    p.add_argument("--out", required=True, help="results folder")
    p.add_argument("--legs", default="all", help="comma list of leg ids, or all")
    p.add_argument("--only", help="comma list of scene names to run (default all of --scenes)")
    p.add_argument("--resume", action="store_true", help="keep ok / not-applicable records for unchanged scenes and settings")
    p.add_argument("--base", help="folder the scene paths are relative to (default tools/fidelity_rig)")
    p.add_argument("--addon", help="the add-on source folder (default ./source of this checkout)")
    p.add_argument("--spp", type=int, default=256, help="Cycles samples per pixel (reference: 256)")
    p.add_argument("--seeds", default="0,1", help="two Cycles seeds; the second gives the noise floor")
    p.add_argument("--size", type=int, default=512)
    p.add_argument("--threads", type=int, default=2, help="Cycles / llvmpipe threads")
    p.add_argument("--timeout-web", type=int, default=150, help="seconds per scene in the browser legs")
    p.add_argument("--timeout-cycles", type=int, default=900, help="seconds per scene for the Cycles leg")
    p.add_argument("--timeout-eevee", type=int, default=300, help="seconds per scene for the EEVEE leg (its first render adds 300 s start-up)")
    p.add_argument("--no-heat", action="store_true", help="skip the FLIP error maps")
    p.add_argument("--no-report", action="store_true")
    p.add_argument("--quiet", action="store_true", help="log to logs/run.log only")
    p.add_argument("--strict", action="store_true", help="exit 1 when any leg of any scene failed")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(run(parse_args()))
