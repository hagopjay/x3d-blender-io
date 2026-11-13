"""Run X3D scenes through the add-on to a glb, render X_ITE on the X3D and Babylon.js on the glb from the X3D's first
Viewpoint, and report the mean |delta| per pixel (0-255) over the frame and over the glb's geometry only, plus the
5x5 patches a scene lists. Writes out/LABEL/<scene>/{xite,babylon,babylon_mask,diff_x4}.png, validate_glb's
scene.glb.validation.json, manifest.json and results.json. Every glb goes through the Khronos glTF Validator
(validate_glb.mjs) right after the Blender leg; a validator error fails the run (exit 1) after results.json is written.

Usage (from this folder, after `npm install`):
    BPY_PYTHON=/path/to/python-with-bpy python3 compare.py LABEL ../../source probes.json
The environment reaches the Blender leg (BLENDER_X3D_COLOR_SPACE, BLENDER_X3D_LIGHT_UNITS, BLENDER_X3D_CIRCLE_DIV).
RIG_VALIDATOR_MAX_WARNINGS=N also fails a glb with more than N validator warnings (errors always fail it).
Measured with X_ITE 16.7.1, Babylon.js 9.32.0, Blender 5.3 (bpy), Playwright's Chromium 153 with SwiftShader."""
import json, os, re, subprocess, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import manifest


from viewpoint import _floats, _rot, geo_viewpoint, first_viewpoint  # noqa: F401  (moved to viewpoint.py so gate.py can import them)
from PIL import Image
RIG = os.path.dirname(os.path.abspath(__file__))
label, src, scenes_file = sys.argv[1:4]
scenes = json.load(open(scenes_file))
PY = os.environ.get("BPY_PYTHON", sys.executable)  # a Python with bpy installed
def lin(c): return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
jobs, legs, vals, leg_failed = [], {}, {}, []
max_warnings = int(os.environ["RIG_VALIDATOR_MAX_WARNINGS"]) if os.environ.get("RIG_VALIDATOR_MAX_WARNINGS") else None
def validator_failures():
    """Print every scene whose glb failed the validator gate; True when there were any."""
    bad = {n: v for n, v in vals.items() if not v["validator_ok"]}
    for n, v in bad.items():
        s_ = v.get("validator") or {}
        print(f"VALIDATOR FAIL {n}: " + (v.get("validator_error") or f"{s_['errors']} errors, {s_['warnings']} warnings (gltf-validator {s_['version']})"))
        for i in s_.get("issues", [])[:10]:
            print(f"  {i['severity']} {i['code']} {i['pointer']} {i['message']}")
    for n in leg_failed:
        print(f"VALIDATOR FAIL {n}: the Blender leg produced no glb to validate")
    return bool(bad) or bool(leg_failed)
for sc in scenes:
    name, x3d = sc["name"], sc["x3d"]
    out = f"{RIG}/out/{label}/{name}"; os.makedirs(out, exist_ok=True)
    glb = os.path.abspath(f"{out}/scene.glb")
    for stale in (glb, glb + ".validation.json", f"{out}/manifest.json",   # a failed leg must not leave an earlier run's outputs to read as this run's
                  *(f"{out}/{n}.png" for n in ("xite", "babylon", "babylon_mask", "babylon_mask_green", "diff_x4"))):
        if os.path.exists(stale):
            os.remove(stale)
    try:
        r = subprocess.run([PY, f"{RIG}/blender_leg.py", src, x3d, glb], capture_output=True, text=True, timeout=900)
        line, why = next((l for l in r.stdout.splitlines() if l.startswith("LEG ")), None), r.stderr[-800:]
    except subprocess.TimeoutExpired:
        line, why = None, "timed out after 900 s"
    if not line or not os.path.exists(glb):
        print("LEG FAIL", name, why); leg_failed.append(name); continue   # no glb: the gate fails the run at the end, the other scenes still go through
    legs[name] = json.loads(line[4:])
    vals[name] = manifest.validate(glb, max_warnings)   # a failing glb is reported and fails the run at the end, the other scenes still render
    v_ = vals[name].get("validator")
    print("VALIDATOR", "ok  " if vals[name]["validator_ok"] else "FAIL", name,
          (f"{v_['errors']}E {v_['warnings']}W {v_['infos']}I {v_['hints']}H {v_['triangles']} tris"
           + (f"  NOT VALIDATED: {','.join(v_['extensionsNotValidated'])}" if v_["extensionsNotValidated"] else "")
           + ("  EMPTY glb (no triangles)" if not v_["triangles"] else "")) if v_ else vals[name]["validator_error"])
    manifest.write_manifest(out, name, x3d, glb, vals[name], legs[name], src)
    txt = open(x3d, errors="ignore").read()
    m = re.search(r"<Background\b[^>]*skyColor=['\"]([^'\"]+)", txt)
    clear = [float(v) for v in m.group(1).replace(",", " ").split()[:3]] if m else [0, 0, 0]
    nav = re.search(r"<NavigationInfo\b[^>]*headlight=['\"](\w+)", txt)
    head_on = not (nav and nav.group(1).lower() == "false")
    model = legs[name].get("model")
    # X_ITE's headlight is a DirectionalLight of intensity 1: matched the way the add-on maps a DirectionalLight
    head = (sc.get("headlight_lux") or legs[name].get("headlight_lux") or 1.0) if head_on else None
    jobs.append(dict(name=name, x3d=os.path.abspath(x3d), glb=glb, clear=clear, headlight=head, outdir=out, wait=sc.get("wait", 1500),
                     view=first_viewpoint(x3d, src)))
jf = f"{RIG}/out/{label}/jobs.json"; json.dump(jobs, open(jf, "w"), indent=1)
for job in jobs:   # a render that fails must not leave an earlier run's image under this label
    for stale in ("xite.png", "babylon.png", "babylon_mask.png", "babylon_mask_green.png", "diff_x4.png"):
        if os.path.exists(f"{job['outdir']}/{stale}"):
            os.remove(f"{job['outdir']}/{stale}")
r = subprocess.run(["node", f"{RIG}/render.mjs", jf], capture_output=True, text=True, timeout=1800)
print(r.stdout[-6000:], r.stderr[-1500:])
if r.returncode != 0:
    validator_failures()
    sys.exit("render.mjs failed (exit %d)" % r.returncode)
rows = []
for job, sc in zip(jobs, [s for s in scenes if s["name"] in legs]):
    a = f"{job['outdir']}/xite.png"; b = f"{job['outdir']}/babylon.png"
    if not (os.path.exists(a) and os.path.exists(b)):
        rows.append(dict(scene=job["name"], error="missing render", **vals[job["name"]])); continue
    A = np.asarray(Image.open(a).convert("RGB"), dtype=np.float64); B = np.asarray(Image.open(b).convert("RGB"), dtype=np.float64)
    d = np.abs(A - B); Image.fromarray(np.clip(d * 4, 0, 255).astype(np.uint8)).save(f"{job['outdir']}/diff_x4.png")
    mask_path, green_path = f"{job['outdir']}/babylon_mask.png", f"{job['outdir']}/babylon_mask_green.png"
    geo = None
    if os.path.exists(mask_path) and os.path.exists(green_path):
        Mk = np.asarray(Image.open(mask_path).convert("RGB"), dtype=np.int32)
        Mg = np.asarray(Image.open(green_path).convert("RGB"), dtype=np.int32)
        clear = ((Mk[..., 0] == 255) & (Mk[..., 1] == 0) & (Mk[..., 2] == 255)) & \
            ((Mg[..., 0] == 0) & (Mg[..., 1] == 255) & (Mg[..., 2] == 0))
        geo = ~clear
    row = dict(scene=job["name"], mean_abs_delta=round(float(d.mean()), 2),
               geometry_delta=(round(float(d[geo].mean()), 2) if geo is not None and geo.any() else None),
               geometry_share=(round(float(geo.mean()), 3) if geo is not None else None), headlight=job["headlight"],
               lights=legs[job["name"]]["lights"], **vals[job["name"]])
    if "patches" in sc:
        row["patches"] = [dict(at=p, xite=int(A[p[1]-2:p[1]+3, p[0]-2:p[0]+3].mean()), babylon=int(B[p[1]-2:p[1]+3, p[0]-2:p[0]+3].mean()))
                          for p in sc["patches"]]
    rows.append(row)
rows += [dict(scene=n, error="leg failed: no glb", validator_ok=False) for n in leg_failed]   # no glb is not a pass
json.dump(rows, open(f"{RIG}/out/{label}/results.json", "w"), indent=1)
for row in rows:
    print(json.dumps({k: v for k, v in row.items() if k not in ("lights", "validator")}))
if validator_failures() or leg_failed:
    sys.exit("glTF validator gate failed (results.json is written)" + (f"; no glb for: {', '.join(leg_failed)}" if leg_failed else ""))
