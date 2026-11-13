"""Round-trip audit: X3D -> add-on import (defaults) -> add-on X3D 4.0 export (defaults) -> compare with the original.

For every scene in a scenes JSON (same format as probes.json; paths relative to this folder):
  1. roundtrip_leg.py (Blender): import with the add-on's defaults, export X3D 4.0 with its defaults to
     out/LABEL/<scene>/roundtrip.x3d, and the Blender glTF export of the same imported scene (roundtrip.glb). A second
     pass with BLENDER_X3D_COLOR_SPACE=AS_IS writes out/LABEL/<scene>/asis/ for the AS_IS colour audit.
  2. validate the re-export (source/validate.py: well-formed X3D, the x3d python package when installed) and count nodes by
     type, original against re-export.
  3. render X_ITE on the original (twice: the second render is the noise floor of timers and animation) and on the
     re-export, 512 x 512, each at its own first Viewpoint (the camera round trip is part of the test), report the mean
     |delta| per pixel (0-255), the share of pixels off by more than 16, the foreground delta and FLIP (flip-evaluator).
  4. colour audit (numeric): see roundtrip_audit.py; the glb baseColorFactor / emissiveFactor / COLOR_0 against the original
     colour converted sRGB -> linear.
Writes out/LABEL/<scene>/audit.json and out/LABEL/roundtrip_results.json; prints one line per scene and the per field
class colour table.

Usage (from this folder, after `npm install`):
    BPY_PYTHON=/path/to/python-with-bpy python3 roundtrip.py LABEL ../../source SCENES.json [--only a,b] [--no-render]
Measured with the tools named in README.md (Blender 5.3 bpy, X_ITE 16.7.1, Chromium 153 with SwiftShader, flip-evaluator 1.7).
"""
import json, os, subprocess, sys, time
import numpy as np
from PIL import Image

RIG = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RIG)
import roundtrip_audit as ra


def log(*a):
    print(*a, flush=True)


def run_leg(py, src, x3d, outdir, as_is):
    env = dict(os.environ)
    env.pop("BLENDER_X3D_COLOR_SPACE", None)
    if as_is:
        env["BLENDER_X3D_COLOR_SPACE"] = "AS_IS"
    t0 = time.time()
    try:
        r = subprocess.run([py, os.path.join(RIG, "roundtrip_leg.py"), src, x3d, outdir, "--glb"], capture_output=True,
                           text=True, timeout=900, env=env)
    except subprocess.TimeoutExpired:
        return None, "timed out after 900 s", 900.0
    line = next((l for l in r.stdout.splitlines() if l.startswith("RTLEG ")), None)
    if not line:
        return None, (r.stderr or r.stdout)[-1200:], time.time() - t0
    return json.loads(line[6:]), None, time.time() - t0


def validate_reexport(path, src):
    """Well-formed X3D (source/validate.py) and the x3d python package's field checks; returns a dict."""
    sys.path.insert(0, src)
    import validate as v   # source/validate.py: plain Python, no Blender
    out = {}
    try:
        res = v.validate_xml_file(path)
        out["well_formed"] = res.valid
        out["structural_errors"] = res.errors[:5]
        out["structural_warnings"] = res.warnings[:5]
    except Exception as e:
        out["well_formed"], out["structural_errors"] = False, [str(e)]
    try:
        res = v.validate_with_x3d_py(path)
        if res is None:
            out["x3d_py"] = "not installed"
        else:
            out["x3d_py"] = dict(valid=res.valid, errors=len(res.errors), warnings=len(res.warnings),
                                 error_sample=res.errors[:5], warning_sample=sorted(set(res.warnings))[:8])
            try:
                import x3d
                out["x3d_py"]["package"] = getattr(x3d, "__version__", None) or "x3d.py"
            except Exception:
                pass
    except Exception as e:
        out["x3d_py"] = dict(error=str(e)[:300])
    return out


def texture_files(root, base):
    """Image URLs under ImageTexture-like nodes that are plain relative files, and which of them are missing on disk."""
    urls = []
    for e in root.iter():
        if e.tag in ("ImageTexture", "MovieTexture", "AudioClip") and e.get("url"):
            import re
            urls += re.findall(r'"([^"]*)"', e.get("url")) or [e.get("url").strip()]
    rel = [u for u in urls if u and "://" not in u and not u.startswith("data:")]
    missing = [u for u in rel if not os.path.exists(os.path.join(base, u.split("#")[0]))]
    return dict(n=len(urls), missing=sorted(set(missing))[:10], n_missing=len(set(missing)))


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("label"); ap.add_argument("src"); ap.add_argument("scenes")
    ap.add_argument("--only", help="comma-separated scene names")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--reuse", action="store_true", help="keep the roundtrip files and renders already under out/LABEL and only redo the analysis")
    ap.add_argument("--animation", action="store_true", help="export with use_animation=True (the operator's default is off)")
    ns = ap.parse_args()
    label, src, scenes_file = ns.label, ns.src, ns.scenes
    only = set(ns.only.split(",")) if ns.only else None
    no_render = ns.no_render
    if ns.animation:
        os.environ["RT_EXPORT_ANIMATION"] = "1"
    py = os.environ.get("BPY_PYTHON", sys.executable)
    scenes = json.load(open(scenes_file if os.path.isabs(scenes_file) else os.path.join(os.getcwd(), scenes_file)))
    if only:
        scenes = [s for s in scenes if s["name"] in only]
    src = os.path.abspath(src)
    results, jobs = [], []
    for sc in scenes:
        name = sc["name"]
        x3d = sc["x3d"] if os.path.isabs(sc["x3d"]) else os.path.abspath(os.path.join(RIG, sc["x3d"]))
        out = f"{RIG}/out/{label}/{name}"
        os.makedirs(out, exist_ok=True)
        row = dict(scene=name, x3d=sc["x3d"])
        log(f"== {name}  ({os.path.getsize(x3d)} bytes)")
        if not os.path.exists(x3d):
            row["error"] = "scene file missing"; results.append(row); continue
        have_files = all(os.path.exists(f"{out}/{n}") for n in ("roundtrip.x3d", "roundtrip.glb", "asis/roundtrip.x3d", "asis/roundtrip.glb", "audit.json"))
        if ns.reuse and have_files:
            prev = json.load(open(f"{out}/audit.json"))
            leg = dict(prev["leg"], glb=f"{out}/roundtrip.glb")
            legA = dict(glb=f"{out}/asis/roundtrip.glb")
            log(f"   reusing the legs under out/{label}/{name}")
        else:
            for stale in (f"{out}/roundtrip.x3d", f"{out}/roundtrip.glb", f"{out}/asis/roundtrip.x3d", f"{out}/asis/roundtrip.glb"):
                if os.path.exists(stale):
                    os.remove(stale)
            leg, why, secs = run_leg(py, src, x3d, out, False)
            if leg is None:
                log(f"   LEG FAIL (sRGB) after {secs:.0f}s: {why}"); row["error"] = f"leg failed: {why[-300:]}"; results.append(row); continue
            legA, whyA, _ = run_leg(py, src, x3d, f"{out}/asis", True)
            if legA is None:
                log(f"   LEG FAIL (AS_IS): {whyA}"); row["asis_error"] = whyA[-300:]
        row["leg"] = dict(color_space=leg["color_space"], objects=leg["objects"], meshes=leg["meshes"], lights=leg["lights"],
                          import_s=leg["import_s"], export_s=leg["export_s"], blender=leg["blender"])
        log(f"   leg sRGB ok: colour space {leg['color_space']}, {leg['objects']} objects, import {leg['import_s']}s export {leg['export_s']}s")
        re_path = f"{out}/roundtrip.x3d"
        orig_root = ra.parse(x3d)
        re_root = ra.parse(re_path)
        row["validation"] = validate_reexport(re_path, src)
        row["nodes"] = ra.count_diff(ra.node_counts(orig_root), ra.node_counts(re_root))
        row["textures"] = dict(original=texture_files(orig_root, os.path.dirname(x3d)),
                               reexport=texture_files(re_root, out))
        audit = dict(srgb=ra.colour_audit(orig_root, re_root), srgb_glb=ra.glb_audit(orig_root, leg["glb"]))
        if legA is not None:
            re_as = ra.parse(f"{out}/asis/roundtrip.x3d")
            audit["as_is"] = ra.colour_audit(orig_root, re_as)
            audit["as_is_glb"] = ra.glb_audit(orig_root, legA["glb"])
        row["audit"] = audit
        row["viewpoint_pose_diff"] = ra.pose_difference(ra.viewpoint_pose(orig_root), ra.viewpoint_pose(re_root))
        v = row["validation"]
        log(f"   re-export: well-formed {v['well_formed']}, x3d.py {v['x3d_py'] if isinstance(v['x3d_py'], str) else (v['x3d_py'].get('errors'), v['x3d_py'].get('warnings'))}; "
            f"nodes lost {sorted(row['nodes']['lost'])}")
        json.dump(row, open(f"{out}/audit.json", "w"), indent=1, default=float)
        results.append(row)
        wait = sc.get("wait", 2500)
        for tag in ("orig", "reexp", "orig2"):
            if ns.reuse and os.path.exists(f"{out}/{tag}/xite.png"):
                continue
            jobs.append(dict(name=f"{name}/{tag}", x3d=x3d if tag != "reexp" else re_path, outdir=f"{out}/{tag}", wait=wait,
                             xiteOnly=True))
    if not no_render and jobs:
        jf = f"{RIG}/out/{label}/roundtrip_jobs.json"
        json.dump(jobs, open(jf, "w"), indent=1)
        for j in jobs:
            for stale in ("xite.png", "xite_console.txt"):
                if os.path.exists(f"{j['outdir']}/{stale}"):
                    os.remove(f"{j['outdir']}/{stale}")
        r = subprocess.run(["node", f"{RIG}/render.mjs", jf], capture_output=True, text=True, timeout=7200)
        log(r.stdout[-4000:], r.stderr[-1500:])
    if not no_render:
        for row in results:
            if "audit" not in row:
                continue
            out = f"{RIG}/out/{label}/{row['scene']}"
            ims = {t: f"{out}/{t}/xite.png" for t in ("orig", "reexp", "orig2")}
            if not all(os.path.exists(p) for p in ims.values()):
                row["render"] = dict(error="missing render", have=[t for t, p in ims.items() if os.path.exists(p)]); continue
            A, B, A2 = (np.asarray(Image.open(ims[t]).convert("RGB"), dtype=np.float64) for t in ("orig", "reexp", "orig2"))
            d = ra.image_deltas(A, B)
            noise = ra.image_deltas(A, A2)
            d.update(flip=ra.flip_mean(A, B), noise_mean_abs_delta=noise["mean_abs_delta"], noise_flip=ra.flip_mean(A, A2))
            Image.fromarray(np.clip(np.abs(A - B) * 4, 0, 255).astype(np.uint8)).save(f"{out}/diff_x4.png")
            console = {}
            for t in ("orig", "reexp"):
                p = f"{out}/{t}/xite_console.txt"
                console[t] = len([l for l in open(p).read().splitlines() if l.strip()]) if os.path.exists(p) else None
            d["console_lines"] = console
            row["render"] = d
            log(f"   render {row['scene']}: mean|d| {d['mean_abs_delta']} (noise {d['noise_mean_abs_delta']}), >16 {d['share_gt16']}, "
                f"fg {d['foreground_delta']} of {d['foreground_share']}, FLIP {d['flip']} (noise {d['noise_flip']})")
    json.dump(results, open(f"{RIG}/out/{label}/roundtrip_results.json", "w"), indent=1, default=float)
    # colour table
    for space in ("srgb", "as_is"):
        per = {r["scene"]: r["audit"][space] for r in results if "audit" in r and space in r["audit"]}
        agg = ra.aggregate_field_class(per)
        log(f"\nCOLOUR AUDIT ({'default sRGB' if space == 'srgb' else 'AS_IS'}): max abs error in display sRGB 0..1, per field class")
        for k, a in sorted(agg.items()):
            fmt = lambda v: "n/a" if v is None else f"{v:.2e}"
            log(f"  {k:34s} n={a['n']:6d} ordered_n={a['ordered_n']:6d} ordered_max={fmt(a['ordered_max_abs'])} hausdorff_max={fmt(a['hausdorff_max_abs'])} "
                f"dropped={a['dropped']} worst={a['worst_scene']}")
        vmax = {}
        for sc_, au in per.items():
            for tag, vd in au["vertex"].items():
                m = vmax.setdefault(tag, dict(orig_to_re_max=0.0, re_to_orig_max=0.0, scene=None))
                if vd["orig_to_re_max"] >= m["orig_to_re_max"]:
                    m.update(orig_to_re_max=vd["orig_to_re_max"], scene=sc_)
                m["re_to_orig_max"] = max(m["re_to_orig_max"], vd["re_to_orig_max"])
        for tag, m in vmax.items():
            log(f"  vertex {tag:28s} orig_to_re_max={m['orig_to_re_max']:.5f} re_to_orig_max={m['re_to_orig_max']:.5f} worst={m['scene']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
