"""Run X3D scenes through the add-on to a glb, render X_ITE on the X3D and Babylon.js on the glb from the X3D's first
Viewpoint, and report the mean |delta| per pixel (0-255) over the frame and over the glb's geometry only, plus the
5x5 patches a scene lists. Writes out/LABEL/<scene>/{xite,babylon,babylon_mask,diff_x4}.png and results.json.

Usage (from this folder, after `npm install`):
    BPY_PYTHON=/path/to/python-with-bpy python3 compare.py LABEL ../../source probes.json
The environment reaches the Blender leg (BLENDER_X3D_COLOR_SPACE, BLENDER_X3D_LIGHT_UNITS, BLENDER_X3D_CIRCLE_DIV).
Measured with X_ITE 16.7.1, Babylon.js 9.32.0, Blender 5.3 (bpy), Playwright's Chromium 153 with SwiftShader."""
import json, os, re, subprocess, sys, xml.etree.ElementTree as ET
import numpy as np


def _floats(text, n):
    v = [float(x) for x in (text or "").replace(",", " ").split()]
    return v[:n] if len(v) >= n else None


def _rot(axis_angle):
    x, y, z, a = axis_angle
    n = np.linalg.norm([x, y, z]) or 1.0
    x, y, z = x / n, y / n, z / n
    c, s_, C = np.cos(a), np.sin(a), 1 - np.cos(a)
    return np.array([[c + x*x*C, x*y*C - z*s_, x*z*C + y*s_], [y*x*C + z*s_, c + y*y*C, y*z*C - x*s_],
                     [z*x*C - y*s_, z*y*C + x*s_, c + z*z*C]])


def first_viewpoint(path):
    """World position, rotation matrix and fieldOfView of the first Viewpoint in document order (what X_ITE binds)."""
    root = ET.parse(path).getroot()
    parents = {child: parent for parent in root.iter() for child in parent}
    vp = next((e for e in root.iter() if e.tag in ("Viewpoint", "OrthoViewpoint")), None)
    if vp is None:
        return None
    M = np.eye(4)
    node = parents.get(vp)
    chain = []
    while node is not None:
        if node.tag == "Transform":
            chain.append(node)
        node = parents.get(node)
    for t in reversed(chain):
        T = np.eye(4); T[:3, 3] = _floats(t.get("translation"), 3) or [0, 0, 0]
        R = np.eye(4); R[:3, :3] = _rot(_floats(t.get("rotation"), 4) or [0, 0, 1, 0])
        S = np.diag((_floats(t.get("scale"), 3) or [1, 1, 1]) + [1])
        C = np.eye(4); C[:3, 3] = _floats(t.get("center"), 3) or [0, 0, 0]
        SR = np.eye(4); SR[:3, :3] = _rot(_floats(t.get("scaleOrientation"), 4) or [0, 0, 1, 0])
        M = M @ T @ C @ R @ SR @ S @ np.linalg.inv(SR) @ np.linalg.inv(C)
    pos = np.array((_floats(vp.get("position"), 3) or [0, 0, 10]) + [1.0])
    rot = _rot(_floats(vp.get("orientation"), 4) or [0, 0, 1, 0])
    world_pos = (M @ pos)[:3]
    world_rot = M[:3, :3] @ rot
    world_rot = world_rot / np.linalg.norm(world_rot, axis=0)
    view = dict(position=[float(v) for v in world_pos], forward=[float(v) for v in -world_rot[:, 2]],
                up=[float(v) for v in world_rot[:, 1]], fov=0.785398)
    if vp.tag == "OrthoViewpoint":   # fieldOfView is the four extents minX minY maxX maxY
        view["ortho"] = _floats(vp.get("fieldOfView"), 4) or [-1.0, -1.0, 1.0, 1.0]
    else:
        view["fov"] = float((_floats(vp.get("fieldOfView"), 1) or [0.785398])[0])
    return view
from PIL import Image
RIG = os.path.dirname(os.path.abspath(__file__))
label, src, scenes_file = sys.argv[1:4]
scenes = json.load(open(scenes_file))
PY = os.environ.get("BPY_PYTHON", sys.executable)  # a Python with bpy installed
def lin(c): return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
jobs, legs = [], {}
for sc in scenes:
    name, x3d = sc["name"], sc["x3d"]
    out = f"{RIG}/out/{label}/{name}"; os.makedirs(out, exist_ok=True)
    glb = os.path.abspath(f"{out}/scene.glb")
    r = subprocess.run([PY, f"{RIG}/blender_leg.py", src, x3d, glb], capture_output=True, text=True, timeout=900)
    line = next((l for l in r.stdout.splitlines() if l.startswith("LEG ")), None)
    if not line:
        print("LEG FAIL", name, r.stderr[-800:]); continue
    legs[name] = json.loads(line[4:])
    txt = open(x3d, errors="ignore").read()
    m = re.search(r"<Background\b[^>]*skyColor=['\"]([^'\"]+)", txt)
    clear = [float(v) for v in m.group(1).replace(",", " ").split()[:3]] if m else [0, 0, 0]
    nav = re.search(r"<NavigationInfo\b[^>]*headlight=['\"](\w+)", txt)
    head_on = not (nav and nav.group(1).lower() == "false")
    model = legs[name].get("model")
    # X_ITE's headlight is a DirectionalLight of intensity 1: matched the way the add-on maps a DirectionalLight
    head = (sc.get("headlight_lux") or legs[name].get("headlight_lux") or 1.0) if head_on else None
    jobs.append(dict(name=name, x3d=os.path.abspath(x3d), glb=glb, clear=clear, headlight=head, outdir=out, wait=sc.get("wait", 1500),
                     view=first_viewpoint(x3d)))
jf = f"{RIG}/out/{label}/jobs.json"; json.dump(jobs, open(jf, "w"), indent=1)
for job in jobs:   # a render that fails must not leave an earlier run's image under this label
    for stale in ("xite.png", "babylon.png", "babylon_mask.png", "babylon_mask_green.png", "diff_x4.png"):
        if os.path.exists(f"{job['outdir']}/{stale}"):
            os.remove(f"{job['outdir']}/{stale}")
r = subprocess.run(["node", f"{RIG}/render.mjs", jf], capture_output=True, text=True, timeout=1800)
print(r.stdout[-6000:], r.stderr[-1500:])
if r.returncode != 0:
    sys.exit("render.mjs failed (exit %d)" % r.returncode)
rows = []
for job, sc in zip(jobs, [s for s in scenes if s["name"] in legs]):
    a = f"{job['outdir']}/xite.png"; b = f"{job['outdir']}/babylon.png"
    if not (os.path.exists(a) and os.path.exists(b)):
        rows.append(dict(scene=job["name"], error="missing render")); continue
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
               lights=legs[job["name"]]["lights"])
    if "patches" in sc:
        row["patches"] = [dict(at=p, xite=int(A[p[1]-2:p[1]+3, p[0]-2:p[0]+3].mean()), babylon=int(B[p[1]-2:p[1]+3, p[0]-2:p[0]+3].mean()))
                          for p in sc["patches"]]
    rows.append(row)
json.dump(rows, open(f"{RIG}/out/{label}/results.json", "w"), indent=1)
for row in rows:
    print(json.dumps({k: v for k, v in row.items() if k != "lights"}))
