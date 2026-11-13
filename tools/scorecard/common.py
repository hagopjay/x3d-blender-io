# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared helpers for the scorecard: paths, the fidelity rig bindings (imported, not copied), scene preparation, subprocess
running with logs, and the rig fingerprint. Needs no browser and no Blender; numpy is used only for viewpoint maths."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RIG = REPO / "tools" / "fidelity_rig"
ADDON_SRC = REPO / "source"

GEOMETRY_TAGS = {
    "Box", "Sphere", "Cone", "Cylinder", "ElevationGrid", "Extrusion", "IndexedFaceSet", "IndexedTriangleSet", "IndexedTriangleFanSet",
    "IndexedTriangleStripSet", "IndexedQuadSet", "TriangleSet", "TriangleFanSet", "TriangleStripSet", "QuadSet", "IndexedLineSet", "LineSet",
    "PointSet", "Text", "Arc2D", "ArcClose2D", "Circle2D", "Disk2D", "Polyline2D", "Polypoint2D", "Rectangle2D", "TriangleSet2D",
    "Inline", "ProtoInstance", "HAnimHumanoid", "HAnimSegment", "ParticleSystem"}


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


# --------------------------------------------------------------------------------------------------------- rig bindings
def load_rig_manifest():
    """tools/fidelity_rig/manifest.py (validate(), git_revision(), sha256_file()), loaded by path so the name `manifest` is not taken."""
    spec = importlib.util.spec_from_file_location("fidelity_rig_manifest", RIG / "manifest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_VIEWPOINT = None


def rig_viewpoint():
    """The rig's own first_viewpoint(path, src) from compare.py. compare.py is a script (it reads sys.argv and renders on import),
    so its viewpoint functions are taken from its source by name and executed in a private namespace: the rig stays the one
    implementation, nothing is copied here."""
    global _VIEWPOINT
    if _VIEWPOINT is None:
        src = (RIG / "compare.py").read_text()
        tree = ast.parse(src)
        wanted = {"_floats", "_rot", "geo_viewpoint", "first_viewpoint"}
        body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
        missing = wanted - {n.name for n in body}
        if missing:
            raise RuntimeError(f"tools/fidelity_rig/compare.py no longer defines {sorted(missing)}")
        import numpy as np
        ns = dict(np=np, re=re, ET=ET, sys=sys, os=os)
        exec(compile(ast.Module(body=body, type_ignores=[]), str(RIG / "compare.py"), "exec"), ns)
        _VIEWPOINT = ns["first_viewpoint"]
    return _VIEWPOINT


# --------------------------------------------------------------------------------------------------------- X3D facts
def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def x3d_wellformed(path) -> dict:
    """X3D well-formedness verdict: pass (parses as XML, root X3D with a Scene), fail (does not), not-checked (not an XML .x3d file)."""
    p = str(path)
    if not p.lower().endswith(".x3d"):
        return dict(verdict="not-checked", error="not an XML .x3d file (VRML, x3dv or compressed): well-formedness not examined")
    try:
        root = ET.parse(p).getroot()
    except (ET.ParseError, OSError) as e:
        return dict(verdict="fail", error=f"XML parse error: {e}"[:300])
    if _strip_ns(root.tag) != "X3D":
        return dict(verdict="fail", error=f"root element is {_strip_ns(root.tag)!r}, not X3D")
    if not any(_strip_ns(c.tag) == "Scene" for c in root):
        return dict(verdict="fail", error="no Scene element under X3D")
    return dict(verdict="pass", x3d_version=root.get("version"), profile=root.get("profile"))


def x3d_has_geometry(path) -> bool | None:
    """Whether the X3D file declares any geometry (heuristic over node names; an Inline or ProtoInstance counts as geometry).
    None for a file this cannot read as XML."""
    if not str(path).lower().endswith(".x3d"):
        return None
    try:
        root = ET.parse(str(path)).getroot()
    except (ET.ParseError, OSError):
        return None
    for e in root.iter():
        t = _strip_ns(e.tag)
        geo_node = t.startswith("Geo") and t not in ("GeoViewpoint", "GeoOrigin", "GeoMetadata", "GeoTransform", "GeoLocation", "GeoCoordinate")
        if t in GEOMETRY_TAGS or t.startswith("Nurbs") or geo_node or "Splat" in t:
            return True
    return False


def scene_facts(path: str) -> dict:
    """Clear colour (first Background skyColor, else black), headlight on/off (first NavigationInfo), as compare.py reads them."""
    with open(path, errors="ignore") as f:
        txt = f.read()
    m = re.search(r"<Background\b[^>]*skyColor=['\"]([^'\"]+)", txt)
    clear = [float(v) for v in m.group(1).replace(",", " ").split()[:3]] if m else [0.0, 0.0, 0.0]
    if len(clear) < 3:
        clear = [0.0, 0.0, 0.0]
    nav = re.search(r"<NavigationInfo\b[^>]*headlight=['\"](\w+)", txt)
    return dict(clear=clear, headlight_on=not (nav and nav.group(1).lower() == "false"))


class Scene:
    """One scene of a run: its name, file, view, clear colour and the folders its files go to."""

    def __init__(self, name, x3d_abs, rel, out, spec=None):
        self.name, self.x3d, self.rel, self.spec = name, str(x3d_abs), rel, spec or {}
        self.sha256 = sha256_file(x3d_abs)
        self.wellformed = x3d_wellformed(x3d_abs)
        self.has_geometry = x3d_has_geometry(x3d_abs)
        facts = scene_facts(x3d_abs)
        self.clear, self.headlight_on = facts["clear"], facts["headlight_on"]
        self.view = None
        self.view_error = None
        self.sdir = Path(out) / "scenes" / name      # results the report reads: PNGs, heat maps
        self.work = Path(out) / "work" / name        # intermediates: glb, validation json, render logs
        self.addon_leg = None                        # blender_leg.py's LEG record, once the add-on glb is made

    def compute_view(self, addon_src):
        try:
            self.view = rig_viewpoint()(self.x3d, str(addon_src)) if self.x3d.lower().endswith(".x3d") else None
        except Exception as e:  # noqa: BLE001 - recorded, the scene falls back to X3D's default view
            self.view, self.view_error = None, f"{type(e).__name__}: {e}"[:200]

    def headlight_lux(self, fallback=1.0):
        """The headlight the rig adds in Babylon.js: the scene's x3d_headlight_lux (from the add-on import) unless a NavigationInfo
        turns it off (None). Same rule as compare.py."""
        if not self.headlight_on:
            return None
        lux = (self.spec.get("headlight_lux") or (self.addon_leg or {}).get("headlight_lux") or fallback)
        return float(lux)

    def record_header(self, base):
        try:
            rel = os.path.relpath(self.x3d, base)
        except ValueError:
            rel = os.path.basename(self.x3d)
        path = self.rel if not os.path.isabs(self.rel) else (rel if not rel.startswith("..") else os.path.basename(self.x3d))
        return dict(name=self.name, x3d=dict(path=path, sha256=self.sha256, wellformed=self.wellformed, has_geometry=self.has_geometry),
                    view=self.view, view_error=self.view_error, clear=self.clear, headlight_on=self.headlight_on)


def load_scenes(scenes_json, base, out, addon_src=ADDON_SRC, only=None):
    """Scene objects from a scenes JSON (the rig's format: a list of {name, x3d, ...}, paths relative to `base`)."""
    with open(scenes_json) as f:
        spec = json.load(f)
    if isinstance(spec, dict):
        spec = spec.get("scenes", [])
    scenes, names = [], set()
    for s in spec:
        name = s["name"]
        if name in names:
            raise ValueError(f"duplicate scene name {name!r} in {scenes_json}")
        if only and name not in only:
            continue
        names.add(name)
        p = s["x3d"] if os.path.isabs(s["x3d"]) else os.path.join(base, s["x3d"])
        sc = Scene(name, os.path.abspath(p), s["x3d"], out, s)
        sc.compute_view(addon_src)
        scenes.append(sc)
    if only:
        missing = set(only) - names
        if missing:
            raise ValueError(f"--only names not in {scenes_json}: {sorted(missing)}")
    return scenes


# ---------------------------------------------------------------------------------------------------------- processes
def run_cmd(cmd, timeout, env=None, cwd=None, log_path=None):
    """Run a command; returns dict(rc, seconds, timeout, out). Output (stdout + stderr) goes to log_path when given."""
    t0 = time.time()
    e = dict(os.environ)
    e.update(env or {})
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=e, cwd=cwd, errors="replace")
        rc, out, to = r.returncode, (r.stdout or "") + (("\n--- stderr ---\n" + r.stderr) if r.stderr else ""), False
    except subprocess.TimeoutExpired as ex:
        def _t(v):
            return v.decode(errors="replace") if isinstance(v, bytes) else (v or "")
        rc, out, to = None, _t(ex.stdout) + "\n--- stderr ---\n" + _t(ex.stderr), True
    except OSError as ex:
        rc, out, to = None, f"could not start {cmd[0]}: {ex}", False
    sec = round(time.time() - t0, 2)
    if log_path:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w") as f:
            f.write("$ " + " ".join(map(str, cmd)) + "\n" + out + f"\n[exit {rc}{' TIMEOUT' if to else ''} after {sec} s]\n")
    return dict(rc=rc, seconds=sec, timeout=to, out=out)


def tail(text, n=300):
    return (text or "").strip()[-n:]


def tool_version(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return ((r.stdout or r.stderr).strip().splitlines() or [None])[0]
    except (OSError, subprocess.SubprocessError):
        return None


def pkg_version(name):
    from importlib import metadata
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def node_pkg_version(name):
    p = RIG / "node_modules" / name / "package.json"
    try:
        with open(p) as f:
            return json.load(f).get("version")
    except (OSError, ValueError):
        return None


class Ctx:
    """Everything a leg needs: folders, settings, the rig bindings and the fingerprint dict it adds versions to."""

    def __init__(self, out, base=None, addon=None, spp=256, seeds=(0, 1), size=512, threads=2, timeouts=None, env=None, verbose=True):
        self.out = Path(out).resolve()
        self.base = Path(base).resolve() if base else RIG
        self.addon = Path(addon).resolve() if addon else ADDON_SRC
        self.rig = RIG
        self.spp, self.seeds, self.size, self.threads = int(spp), tuple(int(s) for s in seeds), int(size), int(threads)
        self.timeouts = dict(per_scene_web=150, per_scene_cycles=900, per_scene_eevee=300, eevee_startup=300, convert=120, castle=180, glb=600)
        self.timeouts.update(timeouts or {})
        self.env = os.environ if env is None else env
        self.py = self.env.get("BPY_PYTHON") or sys.executable
        self.node = shutil.which("node") or "node"
        self.verbose = verbose
        self.manifest = load_rig_manifest()
        self.tools: dict = {}       # versions the legs learn while running (browser, x_ite, babylon, castle, ...)
        self._bpy_ok = None
        (self.out / "logs").mkdir(parents=True, exist_ok=True)

    # -- environment switches for the optional legs
    @property
    def castle_convert(self):
        v = self.env.get("CASTLE_CONVERT")
        return v or None

    @property
    def castle_render(self):
        v = self.env.get("CASTLE_RENDER")
        return v or None

    def log(self, msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        if self.verbose:
            print(line, flush=True)
        with open(self.out / "logs" / "run.log", "a") as f:
            f.write(line + "\n")

    def run(self, cmd, timeout, tag=None, **kw):
        log_path = str(self.out / "logs" / f"{tag}.log") if tag else None
        self.log("run: " + " ".join(str(c) for c in cmd)[:240])
        r = run_cmd(cmd, timeout, log_path=log_path, **kw)
        self.log(f"  -> exit {r['rc']}{' TIMEOUT' if r['timeout'] else ''} in {r['seconds']} s" + (f", log logs/{tag}.log" if tag else ""))
        return r

    def bpy_available(self):
        """(ok, reason): whether BPY_PYTHON (or this Python) can `import bpy`."""
        if self._bpy_ok is None:
            r = run_cmd([self.py, "-c", "import bpy; print(bpy.app.version_string)"], 120)
            self._bpy_ok = (True, r["out"].strip().splitlines()[0]) if r["rc"] == 0 else (False, f"`{self.py} -c 'import bpy'` failed: {tail(r['out'], 200)}")
        return self._bpy_ok

    def node_ok(self):
        if not shutil.which(self.node) and not os.path.exists(self.node):
            return False, "node is not installed"
        if not (RIG / "node_modules" / "playwright").exists():
            return False, "tools/fidelity_rig/node_modules is missing (npm install in tools/fidelity_rig)"
        return True, "ok"

    def rel(self, path):
        """A path under the results folder as a posix path relative to it (what results.json stores)."""
        return Path(os.path.relpath(path, self.out)).as_posix()


def collect_fingerprint(ctx: Ctx) -> dict:
    """The rig fingerprint: host, browser launch flags, GL stack, tool versions, git revisions of the inputs. Browser and
    engine versions that only a run reveals are filled in later through ctx.tools."""
    cpu_model = None
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.lower().startswith("model name"):
                    cpu_model = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    try:
        affinity = len(os.sched_getaffinity(0))
    except AttributeError:
        affinity = None
    mem_gb = None
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    mem_gb = round(int(line.split()[1]) / 1048576, 1)
                    break
    except OSError:
        pass
    render_src = (RIG / "render.mjs").read_text()
    m = re.search(r"chromium\.launch\(\{ args: \[([^\]]*)\]", render_src)
    flags = [s.strip().strip("'\"") for s in m.group(1).split(",")] if m else None
    mesa = tool_version(["dpkg-query", "-W", "-f=${Package} ${Version}", "libgl1-mesa-dri"])
    xvfb = shutil.which("xvfb-run")
    commit, dirty = ctx.manifest.git_revision(str(ctx.addon))
    repo_rev, repo_dirty = ctx.manifest.git_revision(str(REPO))
    castle = {}
    for env_name in ("CASTLE_CONVERT", "CASTLE_RENDER"):
        p = ctx.env.get(env_name)
        if not p:
            castle[env_name.lower()] = None
            continue
        entry = dict(sha256=sha256_file(p) if os.path.isfile(p) else None, exists=os.path.isfile(p))
        d = os.path.dirname(os.path.abspath(p))
        while d != os.path.dirname(d) and not os.path.exists(os.path.join(d, ".git")):
            d = os.path.dirname(d)
        if os.path.exists(os.path.join(d, ".git")):
            entry["git_revision"], entry["git_dirty"] = ctx.manifest.git_revision(d)
        castle[env_name.lower()] = entry
    return dict(
        host=dict(vcpu_count=os.cpu_count(), vcpu_usable=affinity, cpu_model=cpu_model, memory_gb=mem_gb, gpu="none (software GL)",
                  os=platform.platform()),
        browser=dict(name="Chromium (Playwright)", version=None, launch_flags=flags,
                     gl="ANGLE SwiftShader" if flags and any("swiftshader" in f for f in flags) else None),
        blender_gl=dict(engine_leg="BLENDER_EEVEE under xvfb-run on Mesa llvmpipe", xvfb_run=bool(xvfb), mesa_dri_package=mesa),
        tools=dict(python=platform.python_version(), numpy=pkg_version("numpy"), pillow=pkg_version("Pillow"),
                   flip_evaluator=pkg_version("flip-evaluator"), bpy=pkg_version("bpy"), node=tool_version([ctx.node, "--version"]),
                   x_ite=node_pkg_version("x_ite"), babylonjs=node_pkg_version("babylonjs"), playwright=node_pkg_version("playwright"),
                   gltf_validator=node_pkg_version("gltf-validator")),
        git=dict(addon=dict(revision=commit, dirty=dirty), scorecard_repo=dict(revision=repo_rev, dirty=repo_dirty), castle=castle))
