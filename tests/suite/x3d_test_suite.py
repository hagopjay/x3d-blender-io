#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
x3d_test_suite.py  -  X3D 4.0/4.1 exporter conformance scene for Blender 4.2 - 5.x
=====================================================================================

WHAT THIS DOES
    Builds ONE Blender scene ("X3D_TestSuite") that is a grid of small *zones*; every zone
    stress-tests one family of features of an X3D exporter (geometry, PBR materials, textures,
    hierarchy, instancing, lights, cameras, animation, HAnim, unsupported object types,
    Gaussian splats, GLSL-shader candidates ...).  While building, it records - as JSON, next to
    the scene - exactly what a correct X3D file must contain for every object ("the manifest").
    `validate_x3d_export.py` then compares the exported .x3d against that manifest.

HOW TO RUN
  A) Inside Blender (Scripting workspace -> Open -> Run Script).  Output goes to
        <folder of the .blend>/x3d_suite_out/     (or ~/x3d_suite_out if the file is unsaved)
     Then use  File > Export > X3D  with the options printed in the console (they are also in
     manifest["profiles"]), save as   x3d_suite_out/x3d_suite_main.x3d
  B) Headless, one command, exporter included (what this repo's CI-style run does):
        blender -b --python x3d_test_suite.py -- --out ./out --repo /path/to/x3d-blender-io --export
     (`--repo` registers <repo>/source as the add-on `io_scene_x3d`; without it the script uses
      whatever `export_scene.x3d` operator is already registered.)
  C) pip's `bpy` wheel:  python x3d_test_suite.py --out ./out --repo ... --export

OPTIONS (after the `--` Blender separator)
    --out DIR        output directory (default: see above)
    --zones a,b,c    build only these zones (ids or short names, e.g. Z04,anim)
    --export         after building, export every profile with the registered exporter
    --repo DIR       path of the x3d-blender-io checkout to register (headless convenience)
    --stress         also build the large-scene zone (2000 instances + 80k-face mesh)
    --no-labels      skip the floating text labels (they are themselves FONT -> mesh test cases)
    --list           print zone/case inventory and exit

DESIGN RULES (why this file looks the way it does)
  * Expectations are derived from Blender data at build time (world matrices, face counts,
    bounding boxes, the numbers typed into node sockets), never hard-coded guesses.
  * Every case carries a TIER:
        CORE      the exporter claims this; failing it is a bug / regression
        FIDELITY  a faithful exporter *should* do this; failing = known approximation (reported, not fatal)
        ROADMAP   feature not implemented yet (GLSL shaders, material extensions, fog ...);
                  MISSING is the expected state, and the case flips to NEW when someone implements it
  * No invented conventions: custom properties used (x3d_gaussian_splats, splat_*, x3d_inline_url)
    are exactly the ones the exporter's extract.py reads.
  * Nothing here touches your other scenes; re-running replaces only the X3D_TestSuite scene.

Blender 4.2 LTS .. 5.2 tested API surface:  slotted actions (no fcurve access), Principled v2
socket names, Material.use_nodes (deprecated in 5.x but still working), mesh.shade_smooth().
"""
from __future__ import annotations

import json
import math
import os
import struct
import sys
import time
import traceback
import zlib

import bpy  # noqa: E402  (must precede bmesh when running from the pip `bpy` wheel)
import bmesh
from mathutils import Euler, Matrix, Quaternion, Vector

SUITE_VERSION = "2.0.0"
SCENE_NAME = "X3D_TestSuite"

# --------------------------------------------------------------------------------------
# CLI / configuration
# --------------------------------------------------------------------------------------


def _parse_cli():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    cfg = {"out": None, "zones": None, "export": False, "repo": None, "stress": False,
           "labels": True, "list": False}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--out":
            cfg["out"] = argv[i + 1]; i += 1
        elif a == "--zones":
            cfg["zones"] = [z.strip().lower() for z in argv[i + 1].split(",") if z.strip()]; i += 1
        elif a == "--repo":
            cfg["repo"] = argv[i + 1]; i += 1
        elif a == "--export":
            cfg["export"] = True
        elif a == "--stress":
            cfg["stress"] = True
        elif a == "--no-labels":
            cfg["labels"] = False
        elif a == "--list":
            cfg["list"] = True
        i += 1
    return cfg


CFG = _parse_cli()


def out_dir() -> str:
    if CFG["out"]:
        path = os.path.abspath(CFG["out"])
    elif bpy.data.filepath:
        path = os.path.join(os.path.dirname(bpy.data.filepath), "x3d_suite_out")
    else:
        path = os.path.join(os.path.expanduser("~"), "x3d_suite_out")
    os.makedirs(path, exist_ok=True)
    return path


# --------------------------------------------------------------------------------------
# Constants shared with the validator (keep in sync - the manifest carries them too)
# --------------------------------------------------------------------------------------

FRAME_START, FRAME_END, FPS = 1, 49, 24           # 48 frames -> cycleInterval exactly 2.0 s
TOUR_ANGLE = math.radians(70)                      # horizontal lens angle of the per-zone tour cameras
ZONE_PITCH = 12.0                                  # metres between zone centres
ZONE_COLS = 6

# Blender (Z-up, -Y forward) -> X3D (Y-up, -Z forward): the exporter default axis_forward='-Z', axis_up='Y'
GLOBAL_MATRIX = Matrix.Rotation(-math.pi / 2.0, 4, "X")

# Export option sets ("profiles").  `main` is the primary run; the others exercise option-dependent code.
PROFILES = {
    "main": {
        "file": "x3d_suite_main.x3d",
        "title": "X3D 4.0, hierarchy, animation, normals, modifiers applied",
        "export": dict(x3d_version="X3D40", use_selection=False, use_hierarchy=True, use_animation=True,
                       animation_step=1, use_normals=True, use_mesh_modifiers=True, use_triangulate=False),
    },
    "crease": {
        "file": "x3d_suite_crease.x3d",
        "title": "X3D 4.0, no explicit normals (creaseAngle path), raw base meshes, triangulated, flat hierarchy",
        "export": dict(x3d_version="X3D40", use_selection=False, use_hierarchy=False, use_animation=False,
                       use_normals=False, use_mesh_modifiers=False, use_triangulate=True),
    },
    "x41": {
        "file": "x3d_suite_x41.x3d",
        "title": "X3D 4.1 draft (GaussianSplats node)",
        "export": dict(x3d_version="X3D41", use_selection=False, use_hierarchy=True, use_animation=False,
                       use_normals=False, use_mesh_modifiers=True),
    },
}

# --------------------------------------------------------------------------------------
# Case registry / manifest
# --------------------------------------------------------------------------------------

CASES: list[dict] = []
EXTRA_OBJECTS: dict[str, dict] = {}     # per-object facts that need build-time knowledge
ZONES: dict[str, dict] = {}             # zone id -> {id, name, title, center, builder}
_ZONE_FUNCS: list = []                  # (order, id, name, title, func)
_CUR = {"zone": None}
SKIPPED_ZONES: list[dict] = []
BUILD_LOG: list[str] = []


def log(msg: str) -> None:
    BUILD_LOG.append(msg)
    print("[x3d-suite]", msg)


def zone(zid: str, name: str, title: str):
    """Decorator registering a zone builder: func(ctx) creates objects and calls case(...)."""
    def deco(func):
        _ZONE_FUNCS.append((zid, name, title, func))
        return func
    return deco


def case(cid: str, tier: str, title: str, expect: str, *checks: dict, profile: str = "main",
         needs: str | None = None, known: str | None = None) -> None:
    """Register one test case.

    cid      short id, prefixed with the zone id automatically  (e.g. 'cube.faces' -> 'Z01.cube.faces')
    tier     'CORE' | 'FIDELITY' | 'ROADMAP'
    expect   plain-English description of what a correct export / browser view looks like
    checks   machine-checkable assertions (see validate_x3d_export.py for the vocabulary)
    profile  which export profile's file the checks run against
    needs    optional feature flag; the case is SKIPPED (not failed) when the flag is not available
    known    optional text: a defect in the exporter revision this suite was calibrated against (see SUITE_CALIBRATED_AGAINST);
             shown next to the verdict when the case fails, so a reviewer can tell "known bug" from "new regression"
    """
    assert tier in ("CORE", "FIDELITY", "ROADMAP"), tier
    zid = _CUR["zone"] or "Z??"
    CASES.append({"id": f"{zid}.{cid}", "zone": zid, "tier": tier, "title": title, "expect": expect,
                  "profile": profile, "needs": needs, "known": known, "checks": list(checks)})


def mat16(m: Matrix) -> list[float]:
    return [float(m[r][c]) for r in range(4) for c in range(4)]


def safe_name(name: str, fallback: str = "Node") -> str:
    """Mirror of the exporter's DEF sanitising rule (emit_x3d40._safe_name)."""
    out = []
    for i, ch in enumerate(name or fallback):
        out.append(ch if (ch.isalnum() or ch == "_") else "_")
        if i == 0 and out[-1].isdigit():
            out[-1] = "_"
    return "".join(out) or fallback


# --------------------------------------------------------------------------------------
# Scene helpers
# --------------------------------------------------------------------------------------


class Ctx:
    """Per-run build context handed to zone builders."""

    def __init__(self, scene):
        self.scene = scene
        self.root = scene.collection
        self.zone_id = None
        self.zone_center = Vector((0, 0, 0))
        self.collection = None
        self.images_dir = None
        self.out = None

    # -- placement ------------------------------------------------------------------
    def at(self, dx=0.0, dy=0.0, dz=0.0) -> Vector:
        """A point in the current zone, in zone-local metres (x right, y away from viewer, z up)."""
        return self.zone_center + Vector((dx, dy, dz))

    def link(self, obj, parent=None):
        self.collection.objects.link(obj)
        if parent is not None:
            obj.parent = parent
        return obj

    def new_obj(self, name, data=None, loc=None, rot=None, scale=None, parent=None):
        obj = bpy.data.objects.new(name, data)
        self.link(obj, parent)
        if loc is not None:
            obj.location = loc
        if rot is not None:
            obj.rotation_euler = rot
        if scale is not None:
            obj.scale = scale
        return obj


def update():
    bpy.context.view_layer.update()


def activate_scene(scene):
    for win in bpy.context.window_manager.windows:
        win.scene = scene
    update()


def iter_fcurves(action):
    """Every F-Curve of an Action, for both the legacy and the layered (Blender >= 4.4/5.x) action model."""
    if action is None:
        return
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:
        yield from legacy
    for layer in getattr(action, "layers", []):
        for strip in getattr(layer, "strips", []):
            for bag in getattr(strip, "channelbags", []):
                yield from bag.fcurves


def set_interpolation_linear():
    """Best effort only: ``keyframe_insert`` called from Python IGNORES this preference (verified on 5.2.2: new keys are
    BEZIER regardless).  Real enforcement is :func:`force_interpolation`, run after the scene is built."""
    try:
        bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"
    except Exception:
        pass


def set_interpolation_bezier():
    try:
        bpy.context.preferences.edit.keyframe_new_interpolation_type = "BEZIER"
    except Exception:
        pass


EASED_ACTIONS: set = set()      # names of Actions that must stay BEZIER (the deliberate ease-in/out case)


def force_interpolation():
    """Make every keyframe LINEAR except those in EASED_ACTIONS.  Must run BEFORE expectations are recorded."""
    keep = {bpy.data.actions[n] for n in EASED_ACTIONS if n in bpy.data.actions}
    n_lin = n_bez = 0
    for action in bpy.data.actions:
        mode = "BEZIER" if action in keep else "LINEAR"
        for fc in iter_fcurves(action):
            for kp in fc.keyframe_points:
                kp.interpolation = mode
                if mode == "BEZIER":
                    n_bez += 1
                else:
                    n_lin += 1
            fc.update()
    return n_lin, n_bez


# --------------------------------------------------------------------------------------
# Check vocabulary + mesh helpers
# --------------------------------------------------------------------------------------
def chk(kind: str, **kw) -> dict:
    """One machine-checkable assertion.  `kind` selects the function in validate_x3d_export.CHECKS."""
    return {"k": kind, **kw}


def mesh_from_bm(name: str, bm, smooth: bool = False):
    """bmesh -> new Mesh datablock (frees the bmesh).  `smooth` flags every face as smooth-shaded."""
    mesh = bpy.data.meshes.new(name)
    if smooth:
        for f in bm.faces:
            f.smooth = True
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def prim_mesh(kind: str, name: str, smooth: bool = False, size: float | None = None, radius: float | None = None,
              depth: float = 1.0, u: int = 16, v: int = 8, sub: int = 2, x: int = 1, y: int = 1):
    """Build a primitive mesh WITHOUT bpy.ops (no context needed).  All primitives carry UVs.

    cube       edge length `size` (1)                       uvsphere   radius (0.5), u x v segments
    icosphere  radius (0.5), `sub` subdivisions            cylinder   radius (0.5), depth, 24 segments
    cone       radius (0.5), depth, 24 segments            torus      major 0.5 / minor 0.18, 24 x 12 (UVs: u,v)
    monkey     Suzanne scaled to ~1 unit                   grid       x*y quads, bmesh `size` = HALF-extent (like the operator)
    """
    bm = bmesh.new()
    if kind != "torus":
        bm.loops.layers.uv.new("UVMap")          # calc_uvs=True fills a layer but does not create one
    r = 0.5 if radius is None else radius
    if kind == "cube":
        bmesh.ops.create_cube(bm, size=1.0 if size is None else size, calc_uvs=True)
    elif kind == "uvsphere":
        bmesh.ops.create_uvsphere(bm, u_segments=u, v_segments=v, radius=r, calc_uvs=True)
    elif kind == "icosphere":
        bmesh.ops.create_icosphere(bm, subdivisions=sub, radius=r, calc_uvs=True)
    elif kind == "cylinder":
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=24, radius1=r, radius2=r, depth=depth, calc_uvs=True)
    elif kind == "cone":
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=24, radius1=r, radius2=0.0, depth=depth, calc_uvs=True)
    elif kind == "torus":
        major, minor, nu, nv = 0.5, 0.18, 24, 12
        verts = [[bm.verts.new(((major + minor * math.cos(b)) * math.cos(a), (major + minor * math.cos(b)) * math.sin(a),
                                minor * math.sin(b)))
                  for b in (math.tau * j / nv for j in range(nv))] for a in (math.tau * i / nu for i in range(nu))]
        uv = bm.loops.layers.uv.new("UVMap")
        for i in range(nu):
            for j in range(nv):
                f = bm.faces.new((verts[i][j], verts[(i + 1) % nu][j], verts[(i + 1) % nu][(j + 1) % nv], verts[i][(j + 1) % nv]))
                for loop, (du, dv) in zip(f.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
                    loop[uv].uv = ((i + du) / nu, (j + dv) / nv)
    elif kind == "monkey":
        bmesh.ops.create_monkey(bm, calc_uvs=True)
        bmesh.ops.scale(bm, vec=(0.4, 0.4, 0.4), verts=bm.verts[:])
    elif kind == "grid":
        bmesh.ops.create_grid(bm, x_segments=x, y_segments=y, size=0.5 if size is None else size, calc_uvs=True)
    else:
        raise ValueError(f"unknown primitive {kind!r}")
    return mesh_from_bm(name, bm, smooth=smooth)


def poly_mesh(name: str, verts, faces, smooth: bool = False):
    """Mesh from explicit vertex tuples and index lists (loose vertices are kept; no UVs)."""
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(v) for v in verts], [], [list(f) for f in faces])
    mesh.update()
    if smooth:
        for p in mesh.polygons:
            p.use_smooth = True
    return mesh


def mesh_facts(obj, evaluated: bool = False, convex: bool = False) -> dict:
    """What a correct export of `obj` must contain, measured on Blender's data in object-local space.

    faces      polygon count                  tris       triangle count after triangulation (sum of n-2)
    positions  distinct vertex positions of vertices USED by a face (4 decimals; loose vertices are not exported)
    bbox       [lo, hi] of those vertices     area       total polygon area      has_uv / has_color  active layer present
    """
    eo = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()) if evaluated else None
    me = eo.to_mesh() if evaluated else obj.data
    try:
        used = sorted({i for p in me.polygons for i in p.vertices})
        pts = [tuple(me.vertices[i].co) for i in used]
        facts = {
            "obj": obj.name,
            "faces": len(me.polygons),
            "tris": sum(max(0, len(p.vertices) - 2) for p in me.polygons),
            "positions": len({tuple(round(c, 4) for c in p) for p in pts}),
            "bbox": ([min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]) if pts else None,
            "area": float(sum(p.area for p in me.polygons)),
            "has_uv": me.uv_layers.active is not None,
            "has_color": me.color_attributes.active_color is not None,
        }
        if facts["bbox"]:
            facts["bbox"] = [[float(c) for c in facts["bbox"][0]], [float(c) for c in facts["bbox"][1]]]
        if convex:
            facts["convex"] = True
        return facts
    finally:
        if eo is not None:
            eo.to_mesh_clear()


# --------------------------------------------------------------------------------------
# Texture synthesis (pure Python PNG/TGA writers + numpy patterns -> standard files on disk,
# so the exporter sees *real* image files exactly like a user's downloaded PBR set)
# --------------------------------------------------------------------------------------

try:
    import numpy as np
except Exception:  # Blender always bundles numpy; keep a readable failure otherwise
    np = None


def write_png(path: str, rgba_top_down: "np.ndarray") -> None:
    """Write an 8-bit RGBA PNG. `rgba_top_down` is HxWx4 uint8, first row = visual top."""
    h, w, _ = rgba_top_down.shape
    raw = b"".join(b"\x00" + rgba_top_down[y].tobytes() for y in range(h))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(png)


def write_tga(path: str, rgba_top_down: "np.ndarray") -> None:
    h, w, _ = rgba_top_down.shape
    header = struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, w, h, 32, 0x28)  # 0x20 = top-left origin
    bgra = rgba_top_down[:, :, [2, 1, 0, 3]]
    with open(path, "wb") as fh:
        fh.write(header + bgra.tobytes())


def _grid(n=128):
    ys, xs = np.mgrid[0:n, 0:n]
    u = (xs + 0.5) / n                 # 0 at left
    v = 1.0 - (ys + 0.5) / n           # 0 at the BOTTOM of the picture (Blender/X3D convention)
    return u, v


def pat_uvtest(n=128):
    """Quadrants: top-left RED, top-right GREEN, bottom-left BLUE, bottom-right YELLOW; white diagonal
    (bottom-left -> top-right) and a black dot in the top-left quadrant: orientation is unambiguous."""
    u, v = _grid(n)
    img = np.zeros((n, n, 4), np.float32)
    img[..., 3] = 1
    tl, tr, bl, br = (u < .5) & (v >= .5), (u >= .5) & (v >= .5), (u < .5) & (v < .5), (u >= .5) & (v < .5)
    img[tl, :3] = (0.9, 0.1, 0.1); img[tr, :3] = (0.1, 0.8, 0.2)
    img[bl, :3] = (0.1, 0.2, 0.9); img[br, :3] = (0.95, 0.85, 0.1)
    img[np.abs(u - v) < 0.02, :3] = 1.0
    img[((u - .25) ** 2 + (v - .75) ** 2) < 0.004, :3] = 0.0
    return (img * 255).astype(np.uint8)


def pat_normal(n=128):
    """Tangent-space normal map: a 4x4 grid of round bumps (OpenGL convention: +Y up, like Blender and glTF)."""
    u, v = _grid(n)
    cu, cv = (u * 4) % 1.0 - 0.5, (v * 4) % 1.0 - 0.5
    r2 = cu ** 2 + cv ** 2
    h = np.clip(0.2 - r2, 0, None)                      # paraboloid cap, radius ~0.45
    dx, dy = -2 * cu * (h > 0) * 2.5, -2 * cv * (h > 0) * 2.5
    nz = np.ones_like(dx)
    ln = np.sqrt(dx ** 2 + dy ** 2 + nz ** 2)
    img = np.stack([(dx / ln) * .5 + .5, (dy / ln) * .5 + .5, (nz / ln) * .5 + .5, np.ones_like(dx)], -1)
    return (img * 255).astype(np.uint8)


def pat_orm(n=128):
    """glTF-style packed map: R = ambient occlusion (vignette), G = roughness (left 0.2 -> right 1.0),
    B = metallic (bottom half 0, top half 1)."""
    u, v = _grid(n)
    r = 1.0 - 0.8 * np.clip(((u - .5) ** 2 + (v - .5) ** 2) * 3, 0, 1)
    g = 0.2 + 0.8 * u
    b = (v >= .5).astype(np.float32)
    img = np.stack([r, g, b, np.ones_like(u)], -1)
    return (img * 255).astype(np.uint8)


def pat_emissive(n=128):
    u, v = _grid(n)
    line = ((u * 8) % 1.0 < 0.08) | ((v * 8) % 1.0 < 0.08)
    img = np.zeros((n, n, 4), np.float32); img[..., 3] = 1
    img[line, :3] = (1.0, 0.45, 0.05)
    return (img * 255).astype(np.uint8)


def pat_alpha(n=128):
    u, v = _grid(n)
    inside = ((u - .5) ** 2 + (v - .5) ** 2) < 0.16
    img = np.zeros((n, n, 4), np.float32)
    img[..., :3] = (0.2, 0.7, 1.0)
    img[..., 3] = inside.astype(np.float32)
    return (img * 255).astype(np.uint8)


def pat_ao(n=128):
    u, v = _grid(n)
    a = 0.35 + 0.65 * (0.5 + 0.5 * np.sin(u * 18) * np.sin(v * 18))
    img = np.stack([a, a, a, np.ones_like(a)], -1)
    return (img * 255).astype(np.uint8)


def pat_checker(n=128, k=8):
    u, v = _grid(n)
    c = (((u * k).astype(int) + (v * k).astype(int)) % 2).astype(np.float32)
    img = np.stack([0.2 + 0.7 * c, 0.2 + 0.7 * c, 0.25 + 0.7 * c, np.ones_like(c)], -1)
    return (img * 255).astype(np.uint8)


def build_textures(directory: str) -> dict:
    """Create every source texture once; returns {key: absolute path}."""
    os.makedirs(directory, exist_ok=True)
    os.makedirs(os.path.join(directory, "kaolin_clay"), exist_ok=True)
    plan = {
        "base": ("T_base_uvtest.png", pat_uvtest, "png"),
        "normal": ("T_normal.png", pat_normal, "png"),
        "orm": ("T_orm.png", pat_orm, "png"),
        "emissive": ("T_emissive.png", pat_emissive, "png"),
        "alpha": ("T_alpha.png", pat_alpha, "png"),
        "occlusion": ("T_occlusion.png", pat_ao, "png"),
        "checker": ("T_checker.png", pat_checker, "png"),
        "decoy": (os.path.join("kaolin_clay", "T_decoy_albedo.png"), pat_checker, "png"),   # 'ao' hides in "kaolin"
        "legacy_tga": ("T_legacy.tga", pat_uvtest, "tga"),
    }
    paths = {}
    for key, (rel, fn, fmt) in plan.items():
        p = os.path.join(directory, rel)
        if np is None:
            raise RuntimeError("numpy is required to synthesise textures")
        data = fn()
        (write_png if fmt == "png" else write_tga)(p, data)
        paths[key] = p
    # JPEG goes through Blender's own encoder
    jpg = os.path.join(directory, "T_photo.jpg")
    tmp = bpy.data.images.new("T_tmp_jpg", 128, 128, alpha=False)
    rgba = pat_uvtest().astype(np.float32)[::-1] / 255.0          # image.pixels is bottom-up
    tmp.pixels.foreach_set(rgba.ravel())
    tmp.file_format = "JPEG"
    tmp.filepath_raw = jpg
    tmp.save()
    bpy.data.images.remove(tmp)
    paths["jpeg"] = jpg
    return paths


def load_image(path: str, name: str, colorspace: str = "sRGB"):
    img = bpy.data.images.load(path, check_existing=False)
    img.name = name
    try:
        img.colorspace_settings.name = colorspace
    except Exception:
        pass
    return img


# --------------------------------------------------------------------------------------
# Material helpers
# --------------------------------------------------------------------------------------


def _use_nodes(mat):
    try:
        if not mat.use_nodes:
            mat.use_nodes = True
    except Exception:
        pass


def socket(node, *names):
    """First existing input socket among `names` (Principled socket names moved between 3.x/4.x/5.x)."""
    for n in names:
        s = node.inputs.get(n)
        if s is not None:
            return s
    return None


def set_in(node, names, value) -> bool:
    s = socket(node, *((names,) if isinstance(names, str) else names))
    if s is None:
        return False
    s.default_value = value
    return True


def new_pbr(name, base=(0.8, 0.8, 0.8), metallic=0.0, roughness=0.5, alpha=1.0, emission=None,
            emission_strength=None, render_method=None, backface_culling=None, **extra):
    """Principled material with its node tree.  `extra` maps socket-name -> value (silently skipped if absent)."""
    mat = bpy.data.materials.new(name)
    _use_nodes(mat)
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    set_in(bsdf, "Base Color", (*base[:3], 1.0))
    set_in(bsdf, "Metallic", metallic)
    set_in(bsdf, "Roughness", roughness)
    set_in(bsdf, "Alpha", alpha)
    if emission is not None:
        set_in(bsdf, ("Emission Color", "Emission"), (*emission[:3], 1.0))
    if emission_strength is not None:
        set_in(bsdf, "Emission Strength", emission_strength)
    for sock, val in extra.items():
        set_in(bsdf, sock.replace("__", " "), val)
    if render_method is not None:
        try:
            mat.surface_render_method = render_method
        except Exception:
            pass
    if backface_culling is not None:
        mat.use_backface_culling = backface_culling
    return mat


def bsdf_of(mat):
    return mat.node_tree.nodes.get("Principled BSDF")


def add_node(mat, idname, x=-400, y=0, label=None, name=None):
    n = mat.node_tree.nodes.new(idname)
    n.location = (x, y)
    if label:
        n.label = label
    if name:
        n.name = name
    return n


def link(mat, out_sock, in_sock):
    mat.node_tree.links.new(out_sock, in_sock)


def add_image_node(mat, image, x=-500, y=0, label=None, extension=None, interpolation=None):
    n = add_node(mat, "ShaderNodeTexImage", x, y, label=label)
    n.image = image
    if extension:
        n.extension = extension
    if interpolation:
        n.interpolation = interpolation
    return n


def exp_color(c, tol=1e-4):
    return [float(c[0]), float(c[1]), float(c[2])]


def facing_camera_rot():
    """Rotation turning a +Z-normal plane to face -Y (towards the zone camera)."""
    return (math.pi / 2.0, 0.0, 0.0)


# ======================================================================================
# ZONES
# ======================================================================================

CLAY = None   # shared neutral material, created lazily


def clay():
    global CLAY
    if CLAY is None or CLAY.name not in bpy.data.materials:
        CLAY = new_pbr("T_clay", base=(0.72, 0.55, 0.42), metallic=0.0, roughness=0.6)
    return CLAY


def add_mesh_obj(ctx, name, mesh, loc=(0, 0, 0), rot=None, scale=None, material="clay", parent=None):
    obj = ctx.new_obj(name, mesh, loc=ctx.at(*loc) if parent is None else Vector(loc), rot=rot, scale=scale,
                      parent=parent)
    if material == "clay":
        mesh.materials.append(clay())
    elif material is not None:
        mesh.materials.append(material)
    return obj


def grid_slots(n, cols, spacing=2.6, z=1.1):
    rows = (n + cols - 1) // cols
    out = []
    for i in range(n):
        r, c = divmod(i, cols)
        out.append(((c - (cols - 1) / 2.0) * spacing, ((rows - 1) / 2.0 - r) * spacing, z))
    return out


# --------------------------------------------------------------------------------------
@zone("Z00", "doc", "Document, header, world and integrity")
def zone_doc(ctx):
    s = ctx.scene
    case("header", "CORE", "X3D 4.0 document header",
         "A well-formed XML file whose root is <X3D version='4.0' profile='Immersive'> with the X3D 4.0 DOCTYPE and "
         "a <head> that declares component Shape level 2 (PhysicalMaterial needs it) and a generator <meta>.",
         chk("doc", version="4.0", profile="Immersive", doctype="X3D 4.0"),
         chk("component", name="Shape", level=2),
         chk("meta", name="generator"))
    case("header41", "CORE", "X3D 4.1 draft document header",
         "Same file written with version 4.1: root version='4.1' and the 4.1 DOCTYPE.",
         chk("doc", version="4.1", profile="Immersive", doctype="X3D 4.1"), profile="x41")
    case("navinfo", "CORE", "NavigationInfo mirrors the scene lighting",
         "The scene contains Blender lights, so NavigationInfo must switch the headlight OFF "
         "(headlight='false') or the scene would be double-lit; navigation type lists EXAMINE.",
         chk("navinfo", headlight=False, type_has="EXAMINE"))
    case("background", "CORE", "World colour becomes Background skyColor",
         "The world's Background node colour x strength (0.10 0.20 0.40 x 0.5) appears as "
         "<Background skyColor='0.05 0.1 0.2'>.  A decoy 'viewport colour' is set on the world to a different value "
         "to prove the exporter reads the node tree.",
         chk("background", sky=[0.05, 0.10, 0.20], tol=1e-4))
    case("diag.reuse", "CORE", "Geometry reuse is reported in the head",
         "Because many objects share a mesh, a <meta name='info'> says 'Reused geometry (DEF/USE)'.",
         chk("diag", contains="Reused geometry (DEF/USE)"))
    for what, title, expect in [
        ("xml_wellformed", "File parses as XML", "No XML syntax errors, no duplicated attributes, UTF-8."),
        ("def_unique", "Every DEF is unique", "No two nodes share a DEF name (X3D requires scene-wide uniqueness)."),
        ("use_resolves", "Every USE resolves to an earlier DEF",
         "Each USE='x' names a DEF that appears EARLIER in document order (X3D forbids forward references)."),
        ("route_targets", "Every ROUTE endpoint exists",
         "Each ROUTE fromNode/toNode names a DEF'd node and the fields are valid for those node types "
         "(fraction_changed -> set_fraction, value_changed -> set_translation/set_rotation/set_scale)."),
        ("numbers_finite", "No NaN/Inf/overflow in any numeric attribute",
         "Every numeric attribute parses as a finite float."),
        ("coordindex_valid", "All IndexedFaceSet indices are in range",
         "Every coordIndex entry is -1 or a valid index into its Coordinate (or the shared skinCoord); every face has >= 3 vertices; "
         "TextureCoordinate / Normal / ColorRGBA arrays, when present, have exactly one entry per Coordinate."),
        ("interp_valid", "Interpolators are well-formed",
         "key is strictly increasing within [0,1] and len(keyValue) == len(key) x width."),
        ("sfcolor_range", "All SFColor values are within [0,1]",
         "baseColor / emissiveColor / light color etc. never exceed 1 (the X3D 4.0 XSD enforces this)."),
    ]:
        case("integrity." + what, "CORE", title, expect, chk("integrity", what=what))
    case("world.fog", "ROADMAP", "Mist / world fog -> Fog node",
         "Blender's Mist pass distance maps to an X3D <Fog visibilityRange=...>.  NOT implemented in the exporter at HEAD; "
         "expect MISSING until someone adds it.",
         chk("roadmap", feature="Fog from world mist", any_tags=["Fog", "LocalFog"]))
    case("world.hdri", "ROADMAP", "World environment -> EnvironmentLight / Background textures",
         "An HDRI-lit world should become an <EnvironmentLight> (needed for any PBR metal to look right in X_ITE).  "
         "Not implemented: only a flat skyColor is written.",
         chk("roadmap", feature="image-based lighting", any_tags=["EnvironmentLight"]))


# --------------------------------------------------------------------------------------
@zone("Z01", "prims", "Geometry: primitives, topology and robustness")
def zone_prims(ctx):
    specs = [
        ("cube", "cube", {}, False, True), ("uvsphere", "uvsphere", {}, True, True),
        ("icosphere", "icosphere", {"sub": 2}, True, True), ("cylinder", "cylinder", {}, False, True),
        ("cone", "cone", {}, False, True), ("torus", "torus", {}, True, False),
        ("monkey", "monkey", {}, True, False), ("grid", "grid", {"x": 5, "y": 5}, False, False),
    ]
    slots = grid_slots(len(specs) + 11, 6, 1.9)
    for (key, kind, kw, smooth, convex), pos in zip(specs, slots):
        name = f"Z01_{key}"
        mesh = prim_mesh(kind, name + "_mesh", smooth=smooth, **kw)
        obj = add_mesh_obj(ctx, name, mesh, loc=pos, rot=(math.pi / 2, 0, 0) if key == "grid" else None,
                           scale=(0.7, 0.7, 0.7))
        update()
        f = mesh_facts(obj, convex=convex)
        case(f"{key}.geometry", "CORE", f"{key}: faces, vertices, bounds and winding",
             f"One IndexedFaceSet with exactly {f['faces']} faces ({f['positions']} distinct vertex positions); local bounds "
             "match Blender's; for convex solids every face winds counter-clockwise seen from outside.  "
             "Browser: the solid looks correct and evenly lit, no inside-out shading.",
             chk("mesh", facts=f), chk("xf", obj=name))
    pos = slots[len(specs):]
    # 12-gon
    ng = [(math.cos(i * math.tau / 12), math.sin(i * math.tau / 12), 0) for i in range(12)]
    m = poly_mesh("Z01_ngon12_mesh", ng, [list(range(12))])
    o = add_mesh_obj(ctx, "Z01_ngon12", m, loc=pos[0], rot=(math.pi / 2, 0, 0), scale=(0.7,) * 3)
    update()
    case("ngon12.geometry", "CORE", "12-sided n-gon is written as ONE face",
         "A single 12-vertex face (X3D IndexedFaceSet supports n-gons natively), not a fan of triangles.",
         chk("mesh", facts=mesh_facts(o)), chk("xf", obj="Z01_ngon12"))
    case("ngon12.triangulated", "CORE", "12-gon with 'Triangulate' on becomes 10 triangles",
         "Export option Triangulate: the n-gon turns into 10 triangles.",
         chk("mesh", facts=mesh_facts(o), faces_eq="tris"), profile="crease")
    # concave L
    L = [(0, 0, 0), (2, 0, 0), (2, 1, 0), (1, 1, 0), (1, 2, 0), (0, 2, 0)]
    m = poly_mesh("Z01_concave_mesh", L, [list(range(6))])
    o = add_mesh_obj(ctx, "Z01_concave", m, loc=pos[1], rot=(math.pi / 2, 0, 0), scale=(0.5,) * 3)
    update()
    case("concave.geometry", "CORE", "Concave L-shaped polygon survives",
         "One 6-vertex concave face; X_ITE tessellates it, so the L renders as an L (not a filled convex hull).",
         chk("mesh", facts=mesh_facts(o)), chk("xf", obj="Z01_concave"))
    case("concave.triangulated", "CORE", "Concave polygon triangulated with Blender's tessellator",
         "With Triangulate on, 4 triangles cover the L exactly (area preserved).",
         chk("mesh", facts=mesh_facts(o), faces_eq="tris", area_preserved=True), profile="crease")
    # single triangle
    m = poly_mesh("Z01_tri_mesh", [(0, 0, 0), (1.6, 0, 0), (0.8, 1.4, 0)], [[0, 1, 2]])
    o = add_mesh_obj(ctx, "Z01_tri", m, loc=pos[2], rot=(math.pi / 2, 0, 0), scale=(0.6,) * 3)
    update()
    case("tri.geometry", "CORE", "A single triangle", "One 3-vertex face.",
         chk("mesh", facts=mesh_facts(o)), chk("xf", obj="Z01_tri"))
    # wire-only / empty / loose vertices
    m = bpy.data.meshes.new("Z01_wire_mesh")
    m.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [(0, 1), (1, 2), (2, 3), (3, 0)], [])
    m.update()
    o = add_mesh_obj(ctx, "Z01_wire", m, loc=pos[3], material=None, scale=(0.7,) * 3)
    case("wire.robust", "CORE", "Edge-only mesh is handled gracefully",
         "No crash.  The object keeps its Transform but has no Shape; a head <meta name='info'> explains "
         "\"Object 'Z01_wire' has no exportable faces.\"  Browser: nothing visible (X3D has no wireframe geometry without IndexedLineSet).",
         chk("shapes", obj="Z01_wire", n=0), chk("diag", contains="Z01_wire' has no exportable faces"),
         chk("xf", obj="Z01_wire"),
         known="extract.py logs 'has no exportable faces' but ir.IRInstance.iter_shapes() falls back to `object_type == \"MESH\"` and "
               "emit_x3d40._primitive_geometry_xml() writes a default grey <Sphere radius='0.75'> (scaled by the object's scale): "
               "a PHANTOM SPHERE appears where an edge-only / empty / un-realised-GN mesh sits.")
    case("wire.lines", "ROADMAP", "Edge-only mesh -> IndexedLineSet",
         "A faithful exporter would write loose edges as <IndexedLineSet> (useful for scientific wireframes, graphs, "
         "streamlines).  Not implemented.",
         chk("roadmap", feature="IndexedLineSet for edges", any_tags=["IndexedLineSet", "LineSet", "Polyline2D"]))
    m = bpy.data.meshes.new("Z01_empty_mesh")
    o = add_mesh_obj(ctx, "Z01_empty", m, loc=pos[4], material=None)
    case("empty.robust", "CORE", "Mesh with zero vertices", "No crash; Transform without Shape.",
         chk("shapes", obj="Z01_empty", n=0), chk("xf", obj="Z01_empty"),
         known="Same phantom <Sphere radius='0.75'> as Z01.wire.robust (iter_shapes() MESH fallback).")
    m = poly_mesh("Z01_loose_mesh", [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (3, 3, 3), (-4, -4, -4)], [[0, 1, 2, 3]])
    o = add_mesh_obj(ctx, "Z01_loose", m, loc=pos[5], rot=(math.pi / 2, 0, 0), scale=(0.7,) * 3)
    update()
    f = mesh_facts(o)
    case("loose.geometry", "CORE", "Loose vertices are ignored, the quad is kept",
         "Only the quad's 4 vertex positions appear; the two stray vertices at (3,3,3) and (-4,-4,-4) must NOT inflate the bounds.",
         chk("mesh", facts=f), chk("xf", obj="Z01_loose"))
    m = poly_mesh("Z01_degen_mesh", [(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0), (1, 1, 0), (1, 1, 0.0)],
                  [[0, 1, 2], [3, 4, 5]])
    o = add_mesh_obj(ctx, "Z01_degen", m, loc=pos[6], rot=(math.pi / 2, 0, 0), scale=(0.7,) * 3)
    update()
    case("degenerate.geometry", "CORE", "Zero-area faces do not break indexing",
         "Two degenerate triangles (collinear / coincident corners) are exported verbatim; indices stay valid.",
         chk("mesh", facts=mesh_facts(o)), chk("xf", obj="Z01_degen"))
    # Scale extremes (scientific visualisation: nm .. Mm)
    m = prim_mesh("cube", "Z01_micro_mesh", size=5e-7)
    o = add_mesh_obj(ctx, "Z01_micro", m, loc=pos[7])
    update()
    f = mesh_facts(o); f["rel"] = True
    case("micro.precision", "FIDELITY", "Sub-micron geometry keeps its size (nanoscale science)",
         "A 0.5 micrometre cube (half-extent 2.5e-7 m).  The exporter prints coordinates with 6 decimals, so vertices "
         "collapse to 0.000000 and the cube degenerates unless the artist rescales.  Expectation: bbox within 5% of the original.",
         chk("mesh", facts=f))
    m = prim_mesh("cube", "Z01_macro_mesh", size=5e6)
    o = add_mesh_obj(ctx, "Z01_macro", m, loc=pos[8], scale=(1, 1, 1))
    update()
    case("macro.range", "CORE", "Planet-scale geometry prints without exponents",
         "A 5000 km cube (half-extent 2.5e6 m): numbers are written as plain decimals (no '1e+06'), bounds preserved.",
         chk("mesh", facts=mesh_facts(o)))
    m = prim_mesh("cube", "Z01_flipped_mesh")
    bm = bmesh.new(); bm.from_mesh(m); bmesh.ops.reverse_faces(bm, faces=bm.faces[:]); bm.to_mesh(m); bm.free()
    m.update()
    o = add_mesh_obj(ctx, "Z01_flipped", m, loc=pos[9], scale=(0.7,) * 3)
    update()
    f = mesh_facts(o, convex=True); f["inward"] = True
    case("flipped.winding", "CORE", "Inside-out mesh keeps its (inverted) winding",
         "Faces wound clockwise-from-outside must be exported unchanged (no silent re-orientation); the validator sees every "
         "face normal pointing INTO the body.",
         chk("mesh", facts=f))
    # Backface culling / solid flag
    m = prim_mesh("cube", "Z01_solid_mesh")
    mat = new_pbr("T_culled", (0.3, 0.6, 0.9), 0.0, 0.5, backface_culling=True)
    o = add_mesh_obj(ctx, "Z01_solid", m, loc=pos[10], material=mat, scale=(0.7,) * 3)
    update()
    case("solid.culling", "CORE", "Backface culling -> solid",
         "Material with 'Backface Culling' ON gives an IndexedFaceSet without solid='false' (X3D default solid=true "
         "-> back faces culled); materials without it get solid='false' (two-sided).",
         chk("geo_attr", obj="Z01_solid", attr="solid", absent=True),
         chk("geo_attr", obj="Z01_cube", attr="solid", equals="false"))


# --------------------------------------------------------------------------------------
@zone("Z02", "shading", "Normals, smoothing and creaseAngle")
def zone_shading(ctx):
    slots = grid_slots(5, 5, 2.1)
    # flat cube
    m = prim_mesh("cube", "Z02_flat_mesh")
    o = add_mesh_obj(ctx, "Z02_flat", m, loc=slots[0], scale=(0.8,) * 3)
    # smooth sphere
    m2 = prim_mesh("uvsphere", "Z02_smooth_mesh", smooth=True)
    o2 = add_mesh_obj(ctx, "Z02_smooth", m2, loc=slots[1], scale=(0.8,) * 3)
    # mixed: sphere, only the northern hemisphere smooth
    m3 = prim_mesh("uvsphere", "Z02_mixed_mesh", smooth=False)
    for p in m3.polygons:
        if p.center.z > 0:
            p.use_smooth = True
    o3 = add_mesh_obj(ctx, "Z02_mixed", m3, loc=slots[2], scale=(0.8,) * 3)
    # custom split normals: every normal points +Z (a "flat lit" sphere that still has smooth topology)
    m4 = prim_mesh("uvsphere", "Z02_custom_mesh", smooth=True)
    custom_ok = False
    try:
        m4.normals_split_custom_set_from_vertices([(0.0, 0.0, 1.0)] * len(m4.vertices))
        custom_ok = True
    except Exception as exc:
        log(f"custom normals unavailable: {exc}")
    o4 = add_mesh_obj(ctx, "Z02_custom", m4, loc=slots[3], scale=(0.8,) * 3)
    # normals on a transformed (rotated, mirrored) object: local normals must stay local
    m5 = prim_mesh("cone", "Z02_xform_mesh", smooth=True)
    o5 = add_mesh_obj(ctx, "Z02_xform", m5, loc=slots[4], rot=(0.5, 0.7, 0.2), scale=(-0.7, 0.7, 0.7))
    update()
    case("flat.normals", "CORE", "Flat cube: one normal per corner, axis-aligned, unit length",
         "<Normal vector=...> present with one unit vector per Coordinate; each is +/-X, +/-Y or +/-Z; no creaseAngle.",
         chk("geo_node", obj="Z02_flat", node="Normal", present=True, count="coord"),
         chk("normals", obj="Z02_flat", unit=True, axis_aligned=True),
         chk("geo_attr", obj="Z02_flat", attr="creaseAngle", absent=True))
    case("smooth.normals", "CORE", "Smooth sphere: interpolated normals pointing away from the centre",
         "Normals are unit length and (for a sphere centred at the origin) parallel to their vertex positions; "
         "browser: smooth shading, no faceting.",
         chk("normals", obj="Z02_smooth", unit=True, radial=True))
    if custom_ok:
        case("custom.normals", "CORE", "Custom split normals are exported (Blender 4.1+)",
             "All normals equal (0,0,1) although the sphere is smooth: browser shows a sphere lit like a flat disc "
             "(top bright, uniformly shaded).",
             chk("normals", obj="Z02_custom", unit=True, all_equal=[0.0, 0.0, 1.0]))
    case("xform.normals", "CORE", "Normals stay in object space under rotation and negative scale",
         "Normals are written in local space; the Transform (rotation + mirrored X scale) carries the rest.  "
         "Radial test on the cone's rim: still consistent with positions in local space.",
         chk("normals", obj="Z02_xform", unit=True), chk("xf", obj="Z02_xform"))
    case("crease.flat", "CORE", "Without explicit normals a flat mesh has creaseAngle 0",
         "Export option 'Normals' OFF: smooth/flat intent is carried by creaseAngle.  Flat cube -> attribute absent (default 0).",
         chk("geo_attr", obj="Z02_flat", attr="creaseAngle", absent=True),
         chk("geo_node", obj="Z02_flat", node="Normal", present=False), profile="crease")
    case("crease.smooth", "CORE", "Without explicit normals a smooth mesh has creaseAngle pi",
         "Smooth sphere -> creaseAngle='3.141593' (full smoothing).  Browser computes the normals itself.",
         chk("geo_attr", obj="Z02_smooth", attr="creaseAngle", approx=math.pi, tol=1e-4), profile="crease")
    case("crease.mixed", "FIDELITY", "Mixed smooth/flat sphere keeps its hard edge",
         "A sphere whose northern half is smooth and southern half flat.  creaseAngle is per-geometry, so the exporter "
         "has to choose one value: it picks pi (smooth) as soon as ANY face is smooth, which silently smooths the flat half.  "
         "Faithful export = explicit normals (main profile does this correctly) or splitting by smoothing group.",
         chk("geo_attr", obj="Z02_mixed", attr="creaseAngle", absent=True), profile="crease")
    case("mixed.normals", "CORE", "With explicit normals the mixed sphere is exact",
         "Main profile: normals preserve the hard edge between the smooth upper and flat lower hemisphere "
         "(more distinct normals than a purely smooth sphere would give at the equator seam).",
         chk("normals", obj="Z02_mixed", unit=True, hard_edge=True))


# --------------------------------------------------------------------------------------
@zone("Z03", "uv_color", "UV sets, seams and vertex colours")
def zone_uv_color(ctx):
    # (a) UV seams split vertices
    m = prim_mesh("cube", "Z03_seams_mesh")
    o = add_mesh_obj(ctx, "Z03_seams", m, loc=(-3.6, 0, 1.1), scale=(0.8,) * 3)
    update()
    case("seams", "CORE", "UV seams split vertices, arrays stay parallel",
         "The cube's cross-shaped UV unwrap needs more than 8 Coordinates (vertices are duplicated along seams); "
         "TextureCoordinate has exactly as many entries as Coordinate; coordIndex indexes all of them.",
         chk("mesh", facts=mesh_facts(o)),
         chk("geo_node", obj="Z03_seams", node="TextureCoordinate", present=True, count="coord"),
         chk("geo_more_coords", obj="Z03_seams", than_positions=True))
    # (b) no UVs at all
    m = poly_mesh("Z03_nouv_mesh", [(0, 0, 0), (1.6, 0, 0), (1.6, 1.6, 0), (0, 1.6, 0)], [[0, 1, 2, 3]])
    o = add_mesh_obj(ctx, "Z03_nouv", m, loc=(-1.2, 0, 1.1), rot=(math.pi / 2, 0, 0), scale=(0.8,) * 3)
    case("nouv", "CORE", "Mesh without UVs: no TextureCoordinate node",
         "No TextureCoordinate element is written (an empty or fabricated one would break X_ITE texturing).",
         chk("geo_node", obj="Z03_nouv", node="TextureCoordinate", present=False))
    # (c) two UV layers, the SECOND one active
    m = poly_mesh("Z03_twouv_mesh", [(0, 0, 0), (1.6, 0, 0), (1.6, 1.6, 0), (0, 1.6, 0)], [[0, 1, 2, 3]])
    m.uv_layers.new(name="UVMap")
    m.uv_layers.new(name="Second")
    for i, (u, v) in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)]):
        m.uv_layers["UVMap"].data[i].uv = (u, v)
    second = [(0.125, 0.875), (0.5, 0.875), (0.5, 0.5), (0.125, 0.5)]
    for i, uv in enumerate(second):
        m.uv_layers["Second"].data[i].uv = uv
    m.uv_layers.active = m.uv_layers["Second"]
    try:
        m.uv_layers["Second"].active_render = True
    except Exception:
        pass
    o = add_mesh_obj(ctx, "Z03_twouv", m, loc=(1.2, 0, 1.1), rot=(math.pi / 2, 0, 0), scale=(0.8,) * 3)
    case("twouv", "CORE", "Only the ACTIVE UV map is exported",
         "TextureCoordinate holds the values of the layer named 'Second' (e.g. 0.125 0.875), not the default 'UVMap'.",
         chk("value_set", obj="Z03_twouv", node="TextureCoordinate", field="point", width=2,
             contains=[list(p) for p in second], excludes=[[0.0, 0.0], [1.0, 1.0]]))
    case("twouv.extra", "ROADMAP", "Second UV set -> multi-texturing / TextureCoordinate for lightmaps",
         "X3D 4 supports per-texture texCoord mapping ('TEXCOORD1' etc.); glTF-style TEXCOORD_1 is dropped today.",
         chk("roadmap", feature="UV set selection per texture", any_attrs=["baseTextureMapping", "occlusionTextureMapping"]))
    # (d) vertex colours: POINT domain float colour + alpha
    m = prim_mesh("grid", "Z03_vcol_mesh", x=3, y=3, size=1.0)
    attr = m.color_attributes.new("Z03_pt", "FLOAT_COLOR", "POINT")
    cols = []
    for v in m.vertices:
        cols.append((max(0.0, min(1.0, 0.5 + 0.5 * v.co.x)), max(0.0, min(1.0, 0.5 + 0.5 * v.co.y)), 0.25, 0.75))
    for v, c in zip(m.vertices, cols):
        attr.data[v.index].color = c
    m.color_attributes.active_color = attr
    o = add_mesh_obj(ctx, "Z03_vcol", m, loc=(3.6, 0, 1.1), rot=(math.pi / 2, 0, 0), scale=(0.8,) * 3)
    update()
    case("vcol.point", "CORE", "Per-vertex float colours with alpha -> ColorRGBA",
         "<ColorRGBA color=...> with one RGBA entry per Coordinate; alpha 0.75 everywhere; values are Blender's linear floats verbatim.  "
         "Browser: a red/green gradient plate (the colours multiply the base colour in X_ITE).",
         chk("geo_node", obj="Z03_vcol", node="ColorRGBA", present=True, count="coord"),
         chk("value_set", obj="Z03_vcol", node="ColorRGBA", field="color", width=4,
             contains=[list(cols[0]), list(cols[-1])], tol=1e-5))
    # (e) corner-domain byte colours: each face a flat colour, forcing vertex splitting
    m = prim_mesh("cube", "Z03_corner_mesh")
    attr = m.color_attributes.new("Z03_corner", "BYTE_COLOR", "CORNER")
    palette = [(1, 0, 0, 1), (0, 1, 0, 1), (0, 0, 1, 1), (1, 1, 0, 1), (1, 0, 1, 1), (0, 1, 1, 1)]
    for poly in m.polygons:
        for li in poly.loop_indices:
            attr.data[li].color = palette[poly.index % 6]
    m.color_attributes.active_color = attr
    o = add_mesh_obj(ctx, "Z03_corner", m, loc=(0, 3.4, 1.1), scale=(0.8,) * 3)
    update()
    f = mesh_facts(o)
    case("vcol.corner", "CORE", "Per-face (corner) colours split vertices",
         "Each cube face has its own flat colour, so the 8 positions become >= 24 Coordinate entries with 24 matching colours; "
         "browser: a six-coloured cube.",
         chk("mesh", facts=f), chk("geo_node", obj="Z03_corner", node="ColorRGBA", present=True, count="coord"),
         chk("geo_more_coords", obj="Z03_corner", than_positions=True, min_coords=24))


# --------------------------------------------------------------------------------------
def _sphere(ctx, name, mat, pos, r=0.38, smooth=True, u=20, v=10):
    m = prim_mesh("uvsphere", name + "_mesh", smooth=smooth, radius=1.0, u=u, v=v)
    return add_mesh_obj(ctx, name, m, loc=pos, scale=(r, r, r), material=mat)


def _fmt_attrs(**kw):
    return kw


@zone("Z04", "mat_pbr", "PBR scalar materials: metallic x roughness grid, colour, emission")
def zone_mat_pbr(ctx):
    metallics = [0.0, 0.25, 0.5, 0.75, 1.0]
    roughs = [0.0, 0.25, 0.5, 0.75, 1.0]
    base = (0.90, 0.55, 0.20)
    for mi, met in enumerate(metallics):
        checks = []
        for ri, rough in enumerate(roughs):
            name = f"Z04_m{mi}_r{ri}"
            mat = new_pbr(f"T_pbr_m{mi}_r{ri}", base, met, rough)
            _sphere(ctx, name, mat, ((ri - 2) * 1.25, (2 - mi) * 1.25 - 0.4, 0.5))
            checks.append(chk("mat", obj=name, tag="PhysicalMaterial",
                              attrs={"baseColor": list(base), "metallic": met, "roughness": rough},
                              absent=["emissiveColor", "transparency", "occlusionStrength", "normalScale"]))
        case(f"grid.metal{mi}", "CORE", f"Metallic {met} row: five roughness steps",
             f"Five spheres with metallic={met} and roughness 0, .25, .5, .75, 1 written verbatim as "
             "<PhysicalMaterial baseColor='0.9 0.55 0.2' metallic roughness>; no stray emissive/transparency attributes.  "
             "Browser: roughness blurs highlights left->right; metals need an environment to look right (see ROADMAP/EnvironmentLight).",
             *checks)
    # base colour edge cases
    edge = [
        ("black", (0.0, 0.0, 0.0), [0, 0, 0]), ("white", (1.0, 1.0, 1.0), [1, 1, 1]),
        ("saturated", (1.0, 0.0, 0.0), [1, 0, 0]),
        ("hdr", (2.0, 0.5, 0.1), [1.0, 0.25, 0.05]),      # >1: exporter keeps hue, scales peak to 1
    ]
    checks = []
    for i, (key, col, exp) in enumerate(edge):
        mat = new_pbr(f"T_col_{key}", col, 0.0, 0.5)
        _sphere(ctx, f"Z04_col_{key}", mat, (-3.0 + i * 1.0, -3.9, 0.5), r=0.4)
        checks.append(chk("mat", obj=f"Z04_col_{key}", attrs={"baseColor": exp}))
    case("basecolor.edges", "CORE", "Base colour extremes incl. HDR (>1) values",
         "Black/white/pure red verbatim.  A base colour with a channel above 1.0 (2.0 0.5 0.1) is scaled so the peak is 1.0 "
         "(hue kept) because SFColor is limited to [0,1] -> '1 0.25 0.05'.", *checks)
    # emission
    em_specs = [
        ("e1", (1.0, 0.5, 0.1), 1.0, [1.0, 0.5, 0.1]),
        ("e025", (1.0, 0.5, 0.1), 0.25, [0.25, 0.125, 0.025]),
        ("e4", (1.0, 0.5, 0.1), 4.0, [1.0, 0.5, 0.1]),          # peak scaled back to 1 -> strength is LOST
    ]
    checks = []
    for i, (key, col, strength, exp) in enumerate(em_specs):
        mat = new_pbr(f"T_emit_{key}", (0.02, 0.02, 0.02), 0.0, 0.8, emission=col, emission_strength=strength)
        _sphere(ctx, f"Z04_emit_{key}", mat, (1.3 + i * 1.0, -3.9, 0.5), r=0.4)
        checks.append(chk("mat", obj=f"Z04_emit_{key}", attrs={"emissiveColor": exp}, tol=1e-4))
    case("emission.scaling", "CORE", "Emission colour x strength -> emissiveColor (clamped into [0,1])",
         "strength 1 -> '1 0.5 0.1'; strength 0.25 -> '0.25 0.125 0.025'; strength 4 -> channels above 1 are rescaled by the peak "
         "so it lands on the same '1 0.5 0.1' (hue kept).  Browser: orange glow, first and third sphere look identical.", *checks)
    case("emission.strength", "ROADMAP", "Emission strength above 1 -> EmissiveStrengthMaterialExtension",
         "The strength-4 sphere should keep its 4x via <EmissiveStrengthMaterialExtension emissiveStrength='4'> (X_ITE implements it, "
         "glTF KHR_materials_emissive_strength has the same meaning).  Exporter currently normalises it away.",
         chk("roadmap", feature="emissive strength", any_tags=["EmissiveStrengthMaterialExtension"]))
    # default principled -> no emissive attribute
    mat = new_pbr("T_emit_none", (0.5, 0.5, 0.5), 0.0, 0.5)
    _sphere(ctx, "Z04_emit_none", mat, (4.6, -3.9, 0.5), r=0.4)
    case("emission.default", "CORE", "A default Principled BSDF emits nothing",
         "Blender >= 4.0 defaults Emission Strength to 0, so no emissiveColor attribute is written.",
         chk("mat", obj="Z04_emit_none", attrs={}, absent=["emissiveColor"]))
    # Emission shader only -> UnlitMaterial
    m = bpy.data.materials.new("T_unlit")
    _use_nodes(m)
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (0.2, 0.9, 0.4, 1.0)
    em.inputs["Strength"].default_value = 0.5
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    _sphere(ctx, "Z04_unlit", m, (-4.6, -3.9, 0.5), r=0.4)
    case("unlit", "CORE", "Pure Emission shader -> UnlitMaterial",
         "An Emission-only material becomes <UnlitMaterial emissiveColor='0.1 0.45 0.2'> (colour x 0.5): shape glows flat, "
         "independent of lights (X3D 4.0 UnlitMaterial).",
         chk("mat", obj="Z04_unlit", tag="UnlitMaterial", attrs={"emissiveColor": [0.1, 0.45, 0.2]}, tol=1e-4))


# --------------------------------------------------------------------------------------
@zone("Z05", "mat_alpha", "Transparency, blend modes and culling")
def zone_mat_alpha(ctx):
    back = prim_mesh("grid", "Z05_backdrop_mesh", x=1, y=1, size=4.5)
    bd = add_mesh_obj(ctx, "Z05_backdrop", back, loc=(0, 1.2, 2.2), rot=facing_camera_rot(), material=None)
    bmat = new_pbr("T_backdrop", (1, 1, 1), 0.0, 0.9)
    bd.data.materials.append(bmat)
    img = load_image(ctx.textures["checker"], "T_checker")
    n = add_image_node(bmat, img, label="checker")
    link(bmat, n.outputs["Color"], bsdf_of(bmat).inputs["Base Color"])
    specs = [
        ("blend50", dict(base=(0.9, 0.2, 0.2), alpha=0.5, render_method="BLENDED"), "BLEND", 0.5),
        ("dither50", dict(base=(0.9, 0.2, 0.2), alpha=0.5, render_method="DITHERED"), None, 0.5),
        ("blend100", dict(base=(0.2, 0.6, 0.9), alpha=1.0, render_method="BLENDED"), "BLEND", 0.0),
        ("blend25", dict(base=(0.2, 0.9, 0.5), alpha=0.25, render_method="BLENDED"), "BLEND", 0.75),
    ]
    for i, (key, kw, mode, transp) in enumerate(specs):
        name = f"Z05_{key}"
        mat = new_pbr(f"T_alpha_{key}", metallic=0.0, roughness=0.5, **kw)
        m = prim_mesh("grid", name + "_mesh", x=1, y=1, size=0.8)
        add_mesh_obj(ctx, name, m, loc=(-3.0 + i * 2.0, -0.2, 2.2), rot=facing_camera_rot(), material=mat)
        attrs = {"transparency": transp} if transp > 0 else {}
        absent = [] if transp > 0 else ["transparency"]
        case(f"{key}", "CORE", f"alpha {kw['alpha']} with {kw['render_method']} render method",
             f"Appearance alphaMode={'BLEND' if mode else 'absent (AUTO)'}; PhysicalMaterial transparency = 1 - alpha = {transp}"
             f"{' (attribute omitted when 0)' if transp == 0 else ''}.  Browser: the plate "
             f"{'is see-through' if transp > 0 else 'is opaque'}; the checker backdrop shows through proportionally.",
             chk("app", obj=name, alphaMode=mode),
             chk("mat", obj=name, attrs=attrs, absent=absent, tol=1e-4))
    # textured alpha (RGBA PNG with a round hole)
    mat = new_pbr("T_alpha_tex", (1, 1, 1), 0.0, 0.5, render_method="BLENDED")
    t = load_image(ctx.textures["alpha"], "T_alpha_cutout")
    n = add_image_node(mat, t, label="cutout")
    link(mat, n.outputs["Color"], bsdf_of(mat).inputs["Base Color"])
    link(mat, n.outputs["Alpha"], bsdf_of(mat).inputs["Alpha"])
    m = prim_mesh("grid", "Z05_texalpha_mesh", x=1, y=1, size=0.8)
    add_mesh_obj(ctx, "Z05_texalpha", m, loc=(5.0 - 1.0, -0.2, 2.2), rot=facing_camera_rot(), material=mat)
    case("texalpha", "CORE", "RGBA texture drives alpha",
         "baseTexture points at T_alpha_cutout.png (copied next to the .x3d); alphaMode BLEND.  Browser: a blue disc, "
         "the corners fully transparent (texture alpha channel).",
         chk("app", obj="Z05_texalpha", alphaMode="BLEND"),
         chk("tex", obj="Z05_texalpha", field="baseTexture", ext=".png", exists=True))
    case("clip", "ROADMAP", "Alpha cutout -> alphaMode='MASK' with alphaCutoff",
         "Blender 4.2+ removed the 'Alpha Clip' blend mode and Material.blend_method can no longer be set to CLIP "
         "(it silently becomes HASHED), so the exporter's MASK branch is unreachable on current Blender.  A convention "
         "(custom property or a Math>Greater Than node feeding Alpha) is needed.  Expect MISSING.",
         chk("roadmap", feature="alphaMode MASK reachable", any_attrs=["alphaCutoff"], any_values={"alphaMode": "MASK"}))


# --------------------------------------------------------------------------------------
def _plane(ctx, name, mat, pos, size=0.8, uv_scale=1.0, rot=None, scale=None):
    m = prim_mesh("grid", name + "_mesh", x=1, y=1, size=size)
    if uv_scale != 1.0:
        layer = m.uv_layers.active
        for d in layer.data:
            d.uv = (d.uv[0] * uv_scale, d.uv[1] * uv_scale)
    return add_mesh_obj(ctx, name, m, loc=pos, rot=rot or facing_camera_rot(), scale=scale, material=mat)


def _principled_with(mat_name, base=(1, 1, 1), **kw):
    mat = new_pbr(mat_name, base, 0.0, 0.5, **kw)
    return mat, bsdf_of(mat)


@zone("Z06", "mat_tex", "Textures: the glTF-style PBR set, mapping, wrapping, formats")
def zone_mat_tex(ctx):
    T = ctx.textures
    imgs = {
        "base": load_image(T["base"], "T_base_uvtest", "sRGB"),
        "normal": load_image(T["normal"], "T_normal", "Non-Color"),
        "orm": load_image(T["orm"], "T_orm", "Non-Color"),
        "emissive": load_image(T["emissive"], "T_emissive", "sRGB"),
        "occlusion": load_image(T["occlusion"], "T_occlusion", "Non-Color"),
        "checker": load_image(T["checker"], "T_checker_tex", "sRGB"),
        "decoy": load_image(T["decoy"], "T_decoy_kaolin", "sRGB"),
        "tga": load_image(T["legacy_tga"], "T_legacy_tga", "sRGB"),
        "jpeg": load_image(T["jpeg"], "T_photo_jpg", "sRGB"),
    }
    sl = [(x, 0.0, 2.7) for x in (-4.5, -3.0, -1.5, 0.0, 1.5, 3.0, 4.5)]
    sl2 = [(x, 0.0, 1.1) for x in (-4.5, -3.0, -1.5, 0.0, 1.5, 3.0, 4.5)]
    sl3 = [(x, 0.0, -0.5) for x in (-4.5, -3.0, -1.5, 0.0, 1.5, 3.0, 4.5)]

    # 1. base colour texture
    mat, b = _principled_with("T_tex_base")
    n = add_image_node(mat, imgs["base"], label="base")
    link(mat, n.outputs["Color"], b.inputs["Base Color"])
    _plane(ctx, "Z06_base", mat, sl[0])
    case("base", "CORE", "Base colour texture -> baseTexture",
         "PhysicalMaterial has baseColor='1 1 1' and a child <ImageTexture containerField='baseTexture' url='\"T_base_uvtest.png\"'>; "
         "the PNG is copied next to the .x3d.  Browser orientation test: RED top-left, GREEN top-right, BLUE bottom-left, "
         "YELLOW bottom-right, white diagonal rising to the right, black dot in the red quadrant.  If red is bottom-left the V axis is flipped.",
         chk("mat", obj="Z06_base", attrs={"baseColor": [1, 1, 1]}),
         chk("tex", obj="Z06_base", field="baseTexture", name_has="T_base_uvtest", ext=".png", exists=True),
         chk("geo_node", obj="Z06_base", node="TextureCoordinate", present=True, count="coord"))
    # 2. normal map
    mat, b = _principled_with("T_tex_normal", base=(0.8, 0.8, 0.8))
    nm = add_node(mat, "ShaderNodeNormalMap", -300, -200)
    nm.inputs["Strength"].default_value = 0.7
    n = add_image_node(mat, imgs["normal"], x=-600, y=-200, label="normal")
    link(mat, n.outputs["Color"], nm.inputs["Color"])
    link(mat, nm.outputs["Normal"], b.inputs["Normal"])
    _plane(ctx, "Z06_normal", mat, sl[1])
    case("normal", "CORE", "Normal map + strength -> normalTexture + normalScale",
         "normalScale='0.7' and <ImageTexture containerField='normalTexture'> referencing T_normal.png.  Browser (with light): a 4x4 grid of bumps.",
         chk("mat", obj="Z06_normal", attrs={"normalScale": 0.7}),
         chk("tex", obj="Z06_normal", field="normalTexture", name_has="T_normal", exists=True))
    # 3. packed ORM
    mat, b = _principled_with("T_tex_orm")
    sep = add_node(mat, "ShaderNodeSeparateColor", -300, -100)
    n = add_image_node(mat, imgs["orm"], x=-600, y=-100, label="orm")
    link(mat, n.outputs["Color"], sep.inputs["Color"])
    link(mat, sep.outputs["Green"], b.inputs["Roughness"])
    link(mat, sep.outputs["Blue"], b.inputs["Metallic"])
    _plane(ctx, "Z06_orm", mat, sl[2])
    case("orm", "CORE", "Packed metallic/roughness image -> metallicRoughnessTexture",
         "The Separate Color node feeding Roughness(G) and Metallic(B) is followed back to its image: "
         "<ImageTexture containerField='metallicRoughnessTexture'> with T_orm.png.",
         chk("tex", obj="Z06_orm", field="metallicRoughnessTexture", name_has="T_orm", exists=True))
    # 3b. same, with Blender's DEFAULT socket values left behind (0.0 / 0.5 / 0.8 grey)
    mat = new_pbr("T_tex_orm_defaults", (0.8, 0.8, 0.8), 0.0, 0.5)
    b = bsdf_of(mat)
    sep = add_node(mat, "ShaderNodeSeparateColor", -300, -100)
    n = add_image_node(mat, imgs["orm"], x=-600, y=-100, label="orm")
    n2 = add_image_node(mat, imgs["base"], x=-600, y=100, label="base")
    link(mat, n.outputs["Color"], sep.inputs["Color"])
    link(mat, sep.outputs["Green"], b.inputs["Roughness"])
    link(mat, sep.outputs["Blue"], b.inputs["Metallic"])
    link(mat, n2.outputs["Color"], b.inputs["Base Color"])
    _plane(ctx, "Z06_orm_defaults", mat, sl[3])
    case("factors", "FIDELITY", "Linked sockets must not leak their default values into the glTF-style factors",
         "In X3D/glTF the factor MULTIPLIES the texture.  Blender's unlinked default values (Base Color 0.8, Metallic 0.0, Roughness 0.5) "
         "are irrelevant once a texture is linked, so a faithful export writes factors 1/1/1.  Writing metallic='0' silently "
         "kills the metalness map (0 x texture = 0); baseColor 0.8 darkens the texture by 20%.",
         chk("mat", obj="Z06_orm_defaults", attrs={"baseColor": [1, 1, 1], "metallic": 1.0, "roughness": 1.0}, tol=1e-3))
    # 4. emissive texture
    mat, b = _principled_with("T_tex_emissive", base=(0.02, 0.02, 0.02), emission=(1, 1, 1), emission_strength=1.0)
    n = add_image_node(mat, imgs["emissive"], label="emissive")
    link(mat, n.outputs["Color"], socket(b, "Emission Color", "Emission"))
    _plane(ctx, "Z06_emissive", mat, sl[4])
    case("emissive", "CORE", "Emission image -> emissiveTexture",
         "emissiveColor='1 1 1' (factor) plus <ImageTexture containerField='emissiveTexture'> with T_emissive.png.  Browser: orange grid lines "
         "glowing on black.",
         chk("mat", obj="Z06_emissive", attrs={"emissiveColor": [1, 1, 1]}),
         chk("tex", obj="Z06_emissive", field="emissiveTexture", name_has="T_emissive", exists=True))
    # 5. occlusion via labelled node (+ strength Value node)
    mat, b = _principled_with("T_tex_ao")
    n = add_image_node(mat, imgs["occlusion"], x=-600, y=-300, label="occlusion")
    val = add_node(mat, "ShaderNodeValue", -300, -400, label="occlusion_strength", name="occlusion_strength")
    val.outputs[0].default_value = 0.6
    _plane(ctx, "Z06_ao", mat, sl[5])
    case("occlusion", "CORE", "Occlusion texture (labelled node) + strength",
         "Blender's Principled BSDF has no AO input, so the exporter recognises an image node whose name/label contains "
         "'occlusion' and a Value node named 'occlusion_strength': occlusionStrength='0.6' + <ImageTexture containerField='occlusionTexture'>.",
         chk("mat", obj="Z06_ao", attrs={"occlusionStrength": 0.6}),
         chk("tex", obj="Z06_ao", field="occlusionTexture", name_has="T_occlusion", exists=True))
    # 6. everything at once
    mat, b = _principled_with("T_tex_all", emission=(1, 1, 1), emission_strength=1.0)
    n = add_image_node(mat, imgs["base"], x=-900, y=300, label="base"); link(mat, n.outputs["Color"], b.inputs["Base Color"])
    nm = add_node(mat, "ShaderNodeNormalMap", -500, 0); nm.inputs["Strength"].default_value = 1.0
    n = add_image_node(mat, imgs["normal"], x=-900, y=0, label="normal"); link(mat, n.outputs["Color"], nm.inputs["Color"])
    link(mat, nm.outputs["Normal"], b.inputs["Normal"])
    sep = add_node(mat, "ShaderNodeSeparateColor", -500, -200)
    n = add_image_node(mat, imgs["orm"], x=-900, y=-200, label="orm"); link(mat, n.outputs["Color"], sep.inputs["Color"])
    link(mat, sep.outputs["Green"], b.inputs["Roughness"]); link(mat, sep.outputs["Blue"], b.inputs["Metallic"])
    n = add_image_node(mat, imgs["emissive"], x=-900, y=-500, label="emissive")
    link(mat, n.outputs["Color"], socket(b, "Emission Color", "Emission"))
    n = add_image_node(mat, imgs["occlusion"], x=-900, y=-800, label="occlusion")
    _plane(ctx, "Z06_all", mat, sl[6])
    case("all", "CORE", "Complete five-texture PBR set on one material",
         "One <PhysicalMaterial> carries baseTexture, normalTexture, metallicRoughnessTexture, emissiveTexture and occlusionTexture, "
         "each pointing at its own file; the Appearance is DEF'd once.",
         *[chk("tex", obj="Z06_all", field=f, exists=True) for f in
           ("baseTexture", "normalTexture", "metallicRoughnessTexture", "emissiveTexture", "occlusionTexture")])
    # row 2: wrapping / mapping / decoy / formats
    mat, b = _principled_with("T_tex_repeat")
    n = add_image_node(mat, imgs["base"], label="base", extension="REPEAT"); link(mat, n.outputs["Color"], b.inputs["Base Color"])
    _plane(ctx, "Z06_repeat", mat, sl2[0], uv_scale=2.0)
    mat, b = _principled_with("T_tex_clip")
    n = add_image_node(mat, imgs["base"], label="base", extension="CLIP"); link(mat, n.outputs["Color"], b.inputs["Base Color"])
    _plane(ctx, "Z06_clip", mat, sl2[1], uv_scale=2.0)
    case("wrap", "CORE", "Texture extension: REPEAT vs CLIP -> repeatS/repeatT",
         "UVs run 0..2 on both planes.  REPEAT: no repeat attributes (X3D default TRUE): the image tiles 2x2.  CLIP: "
         "repeatS='false' repeatT='false': a single image, edge texels stretched (X3D has no transparent border).",
         chk("tex", obj="Z06_repeat", field="baseTexture", repeat=True),
         chk("tex", obj="Z06_clip", field="baseTexture", repeat=False))
    case("wrap.mirror", "ROADMAP", "MIRROR / EXTEND extension modes",
         "Only CLIP is mapped.  X3D 4.0 has mirrored repeat via TextureProperties (boundaryModeS='MIRRORED_REPEAT'); Blender's MIRROR extension is exported as plain repeat.",
         chk("roadmap", feature="TextureProperties boundary modes", any_tags=["TextureProperties"]))
    mat, b = _principled_with("T_tex_mapping")
    tc = add_node(mat, "ShaderNodeTexCoord", -1000, 0)
    mp = add_node(mat, "ShaderNodeMapping", -750, 0)
    mp.inputs["Location"].default_value = (0.25, 0.1, 0.0)
    mp.inputs["Rotation"].default_value = (0.0, 0.0, 0.5)
    mp.inputs["Scale"].default_value = (2.0, 3.0, 1.0)
    n = add_image_node(mat, imgs["base"], x=-500, y=0, label="base")
    link(mat, tc.outputs["UV"], mp.inputs["Vector"]); link(mat, mp.outputs["Vector"], n.inputs["Vector"])
    link(mat, n.outputs["Color"], b.inputs["Base Color"])
    _plane(ctx, "Z06_mapping", mat, sl2[2])
    case("mapping", "CORE", "Mapping node -> TextureTransform",
         "<TextureTransform translation='0.25 0.1' rotation='0.5' scale='2 3'> inside the Appearance.  Browser: texture tiled 2x3, rotated ~29 deg.",
         chk("ttf", obj="Z06_mapping", translation=[0.25, 0.1], rotation=0.5, scale=[2.0, 3.0]))
    # decoy 'ao' false positive
    mat, b = _principled_with("T_tex_decoy")
    n = add_image_node(mat, imgs["decoy"], label="albedo"); link(mat, n.outputs["Color"], b.inputs["Base Color"])
    _plane(ctx, "Z06_decoy", mat, sl2[3])
    case("decoy.ao", "CORE", "A texture called 'kaolin' is NOT an occlusion map",
         "Detection of occlusion maps by keyword must not fire on the substring 'ao' inside unrelated words/folders such as "
         "'kaolin' or '/home/Naomi/'.  Expected: baseTexture only, NO occlusionTexture.  (Bug hunt: the exporter matches bare "
         "substrings against name, label, image name AND the full file path.)",
         chk("tex", obj="Z06_decoy", field="baseTexture", exists=True),
         chk("tex", obj="Z06_decoy", field="occlusionTexture", absent=True),
         known="material.py:_find_labeled_image_node() tests `keyword in lowercased(node.name + label + image.name + image.filepath)`; "
               "the keyword 'ao' therefore matches 'kaolin', 'Naomi', 'Paolo', 'cacao', 'gaol' ... and ANY folder name containing 'ao'.")
    # formats
    mat, b = _principled_with("T_tex_jpeg")
    n = add_image_node(mat, imgs["jpeg"], label="photo"); link(mat, n.outputs["Color"], b.inputs["Base Color"])
    _plane(ctx, "Z06_jpeg", mat, sl2[4])
    case("jpeg", "CORE", "JPEG texture keeps its format",
         "url ends in .jpg and the file exists next to the .x3d (browsers decode it natively).",
         chk("tex", obj="Z06_jpeg", field="baseTexture", ext=".jpg", exists=True))
    mat, b = _principled_with("T_tex_tga")
    n = add_image_node(mat, imgs["tga"], label="legacy"); link(mat, n.outputs["Color"], b.inputs["Base Color"])
    _plane(ctx, "Z06_tga", mat, sl2[5])
    case("webformat", "FIDELITY", "Browser-decodable texture formats only",
         "WebGL/X_ITE cannot decode TGA/TIFF/BMP/EXR.  A web-ready export converts such images to PNG/JPEG (or KTX2) while copying; "
         "today the file is copied verbatim and the browser shows a missing texture.",
         chk("tex", obj="Z06_tga", field="baseTexture", ext_in=[".png", ".jpg", ".jpeg", ".webp", ".ktx2"], exists=True))
    # packed / generated image (no file on disk)
    gen = bpy.data.images.new("T_generated_packed", 64, 64, alpha=False)
    px = np.zeros((64, 64, 4), np.float32); px[..., 3] = 1.0
    px[:32, :32, :3] = (1, 0.2, 0.2); px[32:, 32:, :3] = (0.2, 0.4, 1.0); px[:32, 32:, :3] = 0.8; px[32:, :32, :3] = 0.2
    gen.pixels.foreach_set(px.ravel())
    gen.pack()
    mat, b = _principled_with("T_tex_packed")
    n = add_image_node(mat, gen, label="generated"); link(mat, n.outputs["Color"], b.inputs["Base Color"])
    _plane(ctx, "Z06_packed", mat, sl2[6])
    case("packed", "CORE", "Packed / generated image has no file: exporter writes one",
         "The image only lives inside the .blend; the exporter must write it (as PNG) next to the .x3d and reference it; "
         "the URL is never an empty string and never a Blender-internal path.",
         chk("tex", obj="Z06_packed", field="baseTexture", ext=".png", exists=True))


# --------------------------------------------------------------------------------------
def _shader_only_material(name, builder):
    """Material whose surface is NOT a Principled BSDF.  builder(nodes, links) -> shader output socket."""
    m = bpy.data.materials.new(name)
    _use_nodes(m)
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    shader_out = builder(nt.nodes, nt.links)
    nt.links.new(shader_out, out.inputs["Surface"])
    return m


@zone("Z07", "mat_adv", "Beyond scalar PBR: Principled extras and non-Principled shaders")
def zone_mat_adv(ctx):
    ext = [
        ("clearcoat", "Coat Weight", 1.0, "ClearcoatMaterialExtension", {"Coat Roughness": 0.05}),
        ("transmission", "Transmission Weight", 1.0, "TransmissionMaterialExtension", {"Roughness": 0.0, "IOR": 1.45}),
        ("sheen", "Sheen Weight", 1.0, "SheenMaterialExtension", {"Sheen Roughness": 0.4}),
        ("ior", "IOR", 1.8, "IORMaterialExtension", {}),
        ("specular", "Specular IOR Level", 0.2, "SpecularMaterialExtension", {}),
        ("aniso", "Anisotropic", 0.8, "AnisotropyMaterialExtension", {"Roughness": 0.3, "Metallic": 1.0}),
        ("thinfilm", "Thin Film Thickness", 400.0, "IridescenceMaterialExtension", {"Thin Film IOR": 1.4}),
    ]
    for i, (key, sock, val, node, more) in enumerate(ext):
        mat = new_pbr(f"T_adv_{key}", (0.8, 0.85, 0.95), 0.0, 0.2)
        b = bsdf_of(mat)
        if not set_in(b, sock, val):
            log(f"Principled socket '{sock}' unavailable; Z07.{key} skipped")
            continue
        for s, v in more.items():
            set_in(b, s, v)
        _sphere(ctx, f"Z07_{key}", mat, (-4.2 + i * 1.4, -2.2, 0.5), r=0.55)
        case(f"ext.{key}", "ROADMAP", f"Principled '{sock}' -> <{node}>",
             f"X_ITE 16 implements <{node}> inside PhysicalMaterial.extensions (verified in its X3DUOM).  The exporter writes only "
             "the five core PBR fields, so this extra surface response is dropped -> MISSING until implemented.",
             chk("roadmap", feature=sock, any_tags=[node]))
    # Non-Principled shaders
    def diffuse_red(nodes, links):
        d = nodes.new("ShaderNodeBsdfDiffuse"); d.inputs["Color"].default_value = (0.9, 0.1, 0.1, 1); return d.outputs[0]

    def glossy_blue(nodes, links):
        d = nodes.new("ShaderNodeBsdfGlossy"); d.inputs["Color"].default_value = (0.1, 0.2, 0.9, 1)
        d.inputs["Roughness"].default_value = 0.2; return d.outputs[0]

    def glass(nodes, links):
        d = nodes.new("ShaderNodeBsdfGlass"); d.inputs["Color"].default_value = (1, 1, 1, 1)
        d.inputs["IOR"].default_value = 1.45; d.inputs["Roughness"].default_value = 0.0; return d.outputs[0]

    def mix_red_green(nodes, links):
        a = nodes.new("ShaderNodeBsdfDiffuse"); a.inputs["Color"].default_value = (0.9, 0.0, 0.0, 1)
        b = nodes.new("ShaderNodeBsdfDiffuse"); b.inputs["Color"].default_value = (0.0, 0.9, 0.0, 1)
        m = nodes.new("ShaderNodeMixShader"); m.inputs["Fac"].default_value = 0.5
        links.new(a.outputs[0], m.inputs[1]); links.new(b.outputs[0], m.inputs[2]); return m.outputs[0]

    items = [
        ("diffuse", diffuse_red, {"baseColor": [0.9, 0.1, 0.1]}),
        ("glossy", glossy_blue, {"baseColor": [0.1, 0.2, 0.9], "metallic": 1.0, "roughness": 0.2}),
        ("glass", glass, {"baseColor": [1, 1, 1], "roughness": 0.0}),
        ("mix", mix_red_green, {"baseColor": [0.45, 0.45, 0.0]}),
    ]
    for i, (key, fn, attrs) in enumerate(items):
        mat = _shader_only_material(f"T_shader_{key}", fn)
        _sphere(ctx, f"Z07_{key}", mat, (-2.1 + i * 1.4, -4.0, 0.5), r=0.55)
        case(f"shader.{key}", "FIDELITY", f"Non-Principled surface: {key}",
             "Only Principled BSDF and Emission are understood; every other shader falls back to a neutral grey 0.8 and, worse, leaves "
             "metallic/roughness UNWRITTEN, which X3D 4.0 reads as metallic=1, roughness=1 (a dark mirror).  "
             "A faithful export maps Diffuse/Glossy/Glass/Mix to the nearest PBR values.",
             chk("mat", obj=f"Z07_{key}", attrs=attrs, tol=0.05, present=["metallic", "roughness"]))
    case("implicit.metal", "FIDELITY", "Unwritten metallic/roughness default to 1.0 in X3D",
         "Whenever the exporter cannot find a Principled node it omits metallic/roughness; PhysicalMaterial's defaults are "
         "metallic=1, roughness=1.  Writing explicit values (0 and 0.5, as the no-material path does) avoids a black chrome look.",
         chk("mat", obj="Z07_diffuse", present=["metallic", "roughness"]))


# --------------------------------------------------------------------------------------
@zone("Z08", "hier", "Transforms, hierarchy and parenting")
def zone_hier(ctx):
    base_mesh = prim_mesh("cube", "Z08_cube_mesh", size=0.5)
    base_mesh.materials.append(clay())

    def cube(name, loc=(0, 0, 0), rot=None, scale=None, parent=None, space="zone"):
        o = ctx.new_obj(name, base_mesh, loc=(ctx.at(*loc) if parent is None else Vector(loc)), rot=rot, scale=scale,
                        parent=parent)
        return o

    # chain of 5, each local offset + rotation + UNIFORM scale (non-uniform scale under rotation = shear, tested separately below)
    prev = None
    names = []
    for i in range(5):
        n = f"Z08_chain{i}"
        if prev is None:
            o = cube(n, (-4.5, -3.2, 0.6), rot=(0, 0, math.radians(15)))
        else:
            o = cube(n, (0.9, 0.0, 0.25), rot=(math.radians(10), 0, math.radians(18)), scale=(0.92, 0.92, 0.92), parent=prev)
        prev = o
        names.append(n)
    update()
    case("chain.xf", "CORE", "Five-deep parent chain keeps world transforms",
         "Each Transform is nested in its parent's Transform (hierarchy mode) and the composition of translation/rotation/scale up "
         "the chain equals Blender's matrix_world after the Y-up conversion.  Browser: a gently rising spiral of five cubes.",
         *[chk("xf", obj=n) for n in names])
    case("chain.nesting", "CORE", "Hierarchy export nests Transforms; flat export does not",
         "Main profile: chain1 is a direct child of chain0, etc.  'crease' profile (Hierarchy OFF): every Transform is top-level "
         "(world matrices) yet world poses are still right.",
         *[chk("parent", obj=names[i], parent=names[i - 1]) for i in range(1, 5)])
    case("chain.flat", "CORE", "Flat (non-hierarchical) export keeps world transforms",
         "Hierarchy OFF: all five cubes are top-level Transforms with baked world matrices.",
         *[chk("parent", obj=n, parent=None) for n in names], *[chk("xf", obj=n) for n in names], profile="crease")
    # shear: rotated child under non-uniformly scaled parent
    par = ctx.new_obj("Z08_shear_parent", None, loc=ctx.at(-1.8, -3.2, 0.7), scale=(2.0, 1.0, 1.0))
    par.empty_display_type = "ARROWS"
    ch = cube("Z08_shear_child", (0, 0, 0.3), rot=(0, 0, math.radians(45)), parent=par)
    update()
    case("shear.hier", "CORE", "Skew from non-uniform parent scale survives in hierarchy mode",
         "Parent scale (2,1,1) with a child rotated 45 deg produces a sheared world matrix.  Nested TRS Transforms reproduce it exactly.",
         chk("xf", obj="Z08_shear_child"), chk("xf", obj="Z08_shear_parent"))
    case("shear.flat", "FIDELITY", "Skew is lost when the hierarchy is flattened",
         "With Hierarchy OFF the sheared world matrix must be decomposed into translation/rotation/scale, which cannot hold shear: "
         "the child lands deformed.  A faithful flat export would bake the skew into the vertices or force hierarchy.",
         chk("xf", obj="Z08_shear_child"), profile="crease")
    # rotation modes
    modes = [
        ("xyz", "XYZ", dict(rotation_euler=(0.4, 0.7, 1.1))),
        ("zyx", "ZYX", dict(rotation_euler=(0.4, 0.7, 1.1))),
        ("quat", "QUATERNION", dict(rotation_quaternion=Quaternion((0.8, 0.3, -0.4, 0.2)).normalized())),
        ("axis", "AXIS_ANGLE", dict(rotation_axis_angle=(0.9, 0.3, 0.5, -0.2))),
        ("gimbal", "XYZ", dict(rotation_euler=(0.3, math.pi / 2, 0.5))),
    ]
    cs = []
    for i, (key, mode, kw) in enumerate(modes):
        o = cube(f"Z08_rot_{key}", (0.0 + i * 1.1, -3.2, 0.6))
        o.rotation_mode = mode
        for k, v in kw.items():
            setattr(o, k, v)
        cs.append(chk("xf", obj=o.name))
    case("rotation.modes", "CORE", "All rotation modes (Euler orders, quaternion, axis-angle, gimbal pole)",
         "Whatever the rotation mode, the Transform rotation equals the object's actual orientation (axis-angle in X3D space).  "
         "Includes a 90 deg gimbal-lock pitch.", *cs)
    o = cube("Z08_negscale", (5.0, -3.2, 0.6), rot=(0.3, 0.2, 0.1), scale=(-1.0, 1.0, 1.0))
    o2 = cube("Z08_negscale2", (5.0, -2.0, 0.6), rot=(0.0, 0.0, 0.6), scale=(-1.0, -1.0, -1.0))
    case("negative.scale", "CORE", "Mirrored (negative) scale",
         "Negative scales are written as such (X3D allows them); the composed matrix equals Blender's, including a full inversion (-1,-1,-1).",
         chk("xf", obj="Z08_negscale"), chk("xf", obj="Z08_negscale2"))
    # delta transforms + parent inverse
    o = cube("Z08_delta", (-4.5, -0.8, 0.6))
    o.delta_location = (0.0, 0.4, 0.2); o.delta_rotation_euler = (0.0, 0.0, 0.5); o.delta_scale = (1.2, 1.0, 0.8)
    par = ctx.new_obj("Z08_pinv_parent", None, loc=ctx.at(-2.2, -0.8, 0.3), rot=(0, 0, 0.8))
    chd = cube("Z08_pinv_child", (-2.0, 0.0, 0.6))
    update()
    chd.parent = par
    chd.matrix_parent_inverse = par.matrix_world.inverted()
    update()
    case("delta.pinv", "CORE", "Delta transforms and a non-identity parent-inverse matrix",
         "Both are baked into matrix_world by Blender and therefore into the exported Transforms.",
         chk("xf", obj="Z08_delta"), chk("xf", obj="Z08_pinv_child"), chk("xf", obj="Z08_pinv_parent"))
    # vertex parent + constraint
    host = prim_mesh("uvsphere", "Z08_host_mesh", smooth=True, radius=0.5)
    ho = add_mesh_obj(ctx, "Z08_vhost", host, loc=(0.2, -0.8, 0.8), rot=(0.3, 0.2, 0.9))
    vc = ctx.new_obj("Z08_vchild", base_mesh, loc=(0, 0, 0))
    vc.parent = ho
    vc.parent_type = "VERTEX"
    vc.parent_vertices = (5, 5, 5)
    target = ctx.new_obj("Z08_target", None, loc=ctx.at(4.0, 0.5, 1.8))
    tracker = cube("Z08_tracker", (2.5, -0.8, 0.6))
    con = tracker.constraints.new("TRACK_TO")
    con.target = target
    con.track_axis = "TRACK_NEGATIVE_Z"
    con.up_axis = "UP_Y"
    update()
    case("parent.vertex.constraint", "CORE", "Vertex parenting and Track-To constraint resolve to world matrices",
         "matrix_world already contains the constraint / vertex-parent result, so both objects land exactly where Blender shows them.",
         chk("xf", obj="Z08_vchild"), chk("xf", obj="Z08_tracker"), chk("xf", obj="Z08_target"))
    # hidden object
    hid = cube("Z08_hidden", (4.5, -0.8, 0.6))
    hid.hide_viewport = True
    update()
    case("hidden.object", "CORE", "Viewport-disabled objects are exported unless 'Visible only' is chosen",
         "Default export options include hidden objects (use_visible=False): the Transform and its Shape are present.",
         chk("xf", obj="Z08_hidden"), chk("shapes", obj="Z08_hidden", n=1))
    # empties
    for i, disp in enumerate(("PLAIN_AXES", "ARROWS", "SINGLE_ARROW", "CIRCLE", "CUBE", "SPHERE", "CONE")):
        e = ctx.new_obj(f"Z08_empty_{disp.lower()}", None, loc=ctx.at(-4.5 + i * 1.5, 3.2, 0.5), rot=(0, 0, i * 0.3))
        e.empty_display_type = disp
    case("empties", "CORE", "Empties become bare Transforms",
         "Each empty is a <Transform> without children; X3D has no 'display type'.  Browser: nothing drawn.",
         *[chk("xf", obj=f"Z08_empty_{d.lower()}") for d in ("PLAIN_AXES", "ARROWS", "SINGLE_ARROW", "CIRCLE", "CUBE", "SPHERE", "CONE")],
         chk("shapes", obj="Z08_empty_arrows", n=0))


# --------------------------------------------------------------------------------------
@zone("Z09", "instances", "Instancing, DEF/USE, naming and collection instances")
def zone_instances(ctx):
    shared = prim_mesh("icosphere", "Z09_shared_mesh", sub=1, radius=0.35, smooth=True)
    mat_a = new_pbr("T_inst_a", (0.2, 0.7, 0.9), 0.0, 0.4)
    mat_b = new_pbr("T_inst_b", (0.9, 0.3, 0.3), 0.0, 0.4)
    shared.materials.append(mat_a)
    names = []
    for i in range(12):
        o = ctx.new_obj(f"Z09_inst_{i:02d}", shared, loc=ctx.at(-4.2 + (i % 6) * 1.5, -3.5 + (i // 6) * 1.2, 0.6),
                        rot=(0, 0, i * 0.2))
        names.append(o.name)
    o = ctx.new_obj("Z09_inst_override", shared, loc=ctx.at(-4.2, -1.1, 0.6))
    o.material_slots[0].link = "OBJECT"
    o.material_slots[0].material = mat_b
    update()
    case("defuse.geometry", "CORE", "13 objects sharing one mesh -> 1 IndexedFaceSet + 12 USE",
         "Exactly one <IndexedFaceSet DEF='ME_Z09_shared_mesh'> and twelve <IndexedFaceSet USE='ME_Z09_shared_mesh'>; the file stays small. "
         "Browser: identical spheres, no extra memory.",
         chk("xpath", path=".//IndexedFaceSet[@DEF='ME_Z09_shared_mesh']", n={"eq": 1}),
         chk("xpath", path=".//IndexedFaceSet[@USE='ME_Z09_shared_mesh']", n={"eq": 12}),
         *[chk("xf", obj=n) for n in names])
    case("defuse.appearance", "CORE", "Shared material -> 1 Appearance + USE; per-object override gets its own",
         "Twelve instance objects plus slot 0 of the two-material cube share <Appearance DEF='APP_T_inst_a'>: 1 DEF + 12 USE "
         "(11 from the instances, 1 from Z09_multi); the object-linked override carries APP_T_inst_b while still re-using the geometry.",
         chk("xpath", path=".//Appearance[@DEF='APP_T_inst_a']", n={"eq": 1}),
         chk("xpath", path=".//Appearance[@USE='APP_T_inst_a']", n={"eq": 12}),
         chk("xpath", path=".//Appearance[@DEF='APP_T_inst_b']", n={"eq": 1}),
         chk("xpath", path=".//Transform[@DEF='OB_Z09_inst_override']//IndexedFaceSet[@USE='ME_Z09_shared_mesh']", n={"eq": 1}))
    # multi-material mesh -> several Shapes
    mm = prim_mesh("cube", "Z09_multi_mesh", size=1.0)
    mm.materials.append(mat_a); mm.materials.append(mat_b)
    for p in mm.polygons:
        p.material_index = p.index % 2
    mo = ctx.new_obj("Z09_multi", mm, loc=ctx.at(2.5, -3.2, 0.6))
    update()
    case("multislot", "CORE", "Two material slots -> two Shapes, geometry split per slot",
         "Z09_multi has 6 faces on 2 slots: two <Shape> children, geometries DEF'd ME_Z09_multi_mesh_m0 / _m1 with 3 faces each.",
         chk("shapes", obj="Z09_multi", n=2),
         chk("xpath", path=".//Transform[@DEF='OB_Z09_multi']/Shape", n={"eq": 2}),
         chk("xpath", path=".//IndexedFaceSet[@DEF='ME_Z09_multi_mesh_m0']", n={"eq": 1}),
         chk("xpath", path=".//IndexedFaceSet[@DEF='ME_Z09_multi_mesh_m1']", n={"eq": 1}))
    # naming collisions and unusual names
    m1 = prim_mesh("cube", "Dup.001", size=0.5); m2 = prim_mesh("cube", "Dup_001", size=0.5)
    ctx.new_obj("Z09_dupA", m1, loc=ctx.at(-4.2, 1.0, 0.5)); ctx.new_obj("Z09_dupB", m2, loc=ctx.at(-3.2, 1.0, 0.5))
    weird = ctx.new_obj("Z09 weird name é.001", prim_mesh("cube", "9starts_with_digit", size=0.5), loc=ctx.at(-2.2, 1.0, 0.5))
    num = ctx.new_obj("9lives", prim_mesh("cube", "Mesh With Spaces", size=0.5), loc=ctx.at(-1.2, 1.0, 0.5))
    update()
    case("names.collision", "CORE", "Names that sanitise to the same DEF stay unique",
         "'Dup.001' and 'Dup_001' both sanitise to Dup_001; the exporter must add a suffix (ME_Dup_001, ME_Dup_001_2) so DEFs never collide.",
         chk("xpath", path=".//IndexedFaceSet[@DEF]", n={"min": 2}),
         chk("integrity", what="def_unique"),
         chk("xf", obj="Z09_dupA"), chk("xf", obj="Z09_dupB"))
    case("names.unusual", "CORE", "Spaces, dots, accents and leading digits become valid X3D names",
         "'Z09 weird name é.001' -> OB_Z09_weird_name_é_001; '9lives' -> OB__lives; mesh 'Mesh With Spaces' -> ME_Mesh_With_Spaces. "
         "All DEFs must stay valid XML names without spaces or dots.",
         chk("xf", obj="Z09 weird name é.001"), chk("xf", obj="9lives"),
         chk("def_names_valid"))
    # collection instance
    src = bpy.data.collections.new("Z09_src_coll")
    sm = prim_mesh("cone", "Z09_collsrc_mesh", radius=0.4, depth=0.8)
    sm.materials.append(mat_b)
    so = bpy.data.objects.new("Z09_collsrc_obj", sm)
    src.objects.link(so)
    ci = ctx.new_obj("Z09_collinst", None, loc=ctx.at(0.8, 1.0, 0.6))
    ci.instance_type = "COLLECTION"
    ci.instance_collection = src
    ci2 = ctx.new_obj("Z09_collinst2", None, loc=ctx.at(2.2, 1.0, 0.6), rot=(0, 0, 1.0))
    ci2.instance_type = "COLLECTION"
    ci2.instance_collection = src
    update()
    case("collection.instance", "FIDELITY", "Collection instances carry their geometry",
         "Two empties instancing a cone collection are the standard way scripts (and AI-generated bpy code) repeat objects.  "
         "The instance Transforms should contain the instanced Shapes (ideally as DEF/USE of one geometry).  Today an instancing empty is "
         "exported as a bare Transform, so the cones vanish.",
         chk("xpath", path=".//Transform[@DEF='OB_Z09_collinst']//Shape", n={"min": 1}),
         chk("xpath", path=".//Transform[@DEF='OB_Z09_collinst2']//Shape", n={"min": 1}))
    # geometry-nodes realised vs not realised
    _gn_instances(ctx)


def _gn_instances(ctx):
    try:
        ng = bpy.data.node_groups.new("Z09_GN_scatter", "GeometryNodeTree")
        ng.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        ng.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
        gi = ng.nodes.new("NodeGroupInput"); go = ng.nodes.new("NodeGroupOutput")
        cube = ng.nodes.new("GeometryNodeMeshCube"); cube.inputs["Size"].default_value = (0.25, 0.25, 0.25)
        iop = ng.nodes.new("GeometryNodeInstanceOnPoints")
        real = ng.nodes.new("GeometryNodeRealizeInstances")
        ng.links.new(gi.outputs[0], iop.inputs["Points"]); ng.links.new(cube.outputs["Mesh"], iop.inputs["Instance"])
        ng.links.new(iop.outputs["Instances"], real.inputs["Geometry"]); ng.links.new(real.outputs["Geometry"], go.inputs[0])
        ng2 = ng.copy(); ng2.name = "Z09_GN_scatter_unrealised"
        # un-realised variant: bypass the Realize node
        for l in list(ng2.links):
            if l.from_node.bl_idname == "GeometryNodeInstanceOnPoints" or l.to_node.bl_idname == "NodeGroupOutput":
                ng2.links.remove(l)
        iop2 = next(n for n in ng2.nodes if n.bl_idname == "GeometryNodeInstanceOnPoints")
        go2 = next(n for n in ng2.nodes if n.bl_idname == "NodeGroupOutput")
        ng2.links.new(iop2.outputs["Instances"], go2.inputs[0])
        for key, group, x in (("realised", ng, 3.4), ("instances", ng2, 4.4)):
            base = prim_mesh("grid", f"Z09_gn_{key}_mesh", x=3, y=3, size=0.5)
            o = ctx.new_obj(f"Z09_gn_{key}", base, loc=ctx.at(x - 3.0, 3.4, 0.6), rot=(math.pi / 2, 0, 0))
            o.data.materials.append(clay())
            md = o.modifiers.new("scatter", "NODES"); md.node_group = group
        update()
        o = bpy.data.objects["Z09_gn_realised"]
        f = mesh_facts(o, evaluated=True)
        case("gn.realised", "CORE", "Geometry Nodes output (realised) is exported as a mesh",
             f"Main profile applies modifiers: the 16 scattered cubes ({f['faces']} faces) appear as ONE IndexedFaceSet - the usual route "
             "for procedurally generated scientific geometry.",
             chk("mesh", facts={"obj": f["obj"], "faces": f["faces"], "positions": f["positions"], "bbox": f["bbox"]}))
        case("gn.nophantom", "CORE", "A mesh object whose evaluated geometry has no faces writes no placeholder shape",
             "Z09_gn_instances evaluates to instances only (no mesh faces).  Expected: the Transform is written without a Shape.  "
             "Browser: nothing at that spot - NOT a grey sphere.",
             chk("shapes", obj="Z09_gn_instances", n=0),
             known="Same phantom <Sphere radius='0.75'> as Z01.wire.robust; the sphere is the only thing a viewer sees for 16 instanced cubes.")
        case("gn.instances", "FIDELITY", "Un-realised Geometry Nodes instances are exported",
             "'Instance on Points' without 'Realize Instances' shows 16 cubes in Blender, but the evaluated mesh contains no instances, "
             "so nothing is written.  Expected: 96 faces (16 cubes x 6) or 16 USE references.",
             chk("mesh", facts={"obj": "Z09_gn_instances", "faces": 96}))
    except Exception as exc:  # API differences between Blender versions
        log(f"Geometry-nodes cases skipped: {exc!r}")


# --------------------------------------------------------------------------------------
@zone("Z10", "modifiers", "Modifier stack: evaluated vs. base meshes")
def zone_modifiers(ctx):
    specs = []
    def add(key, kind, kw, mods, loc, scale=0.8, extra=None):
        mesh = prim_mesh(kind, f"Z10_{key}_mesh", **kw)
        o = add_mesh_obj(ctx, f"Z10_{key}", mesh, loc=loc, scale=(scale,) * 3)
        for mt, props in mods:
            md = o.modifiers.new(mt.lower(), mt)
            for k, v in props.items():
                setattr(md, k, v)
        specs.append((key, o))
        return o
    add("subsurf", "cube", {}, [("SUBSURF", {"levels": 2, "render_levels": 2})], (-4.0, -3.0, 1.0))
    add("array", "cube", {"size": 0.6}, [("ARRAY", {"count": 3, "relative_offset_displace": (1.4, 0, 0)})], (-1.2, -3.0, 0.5), 0.8)
    add("mirror", "cone", {"radius": 0.5, "depth": 1.0}, [("MIRROR", {"use_axis": (False, False, True)})], (1.4, -3.0, 1.0))
    add("solidify", "grid", {"x": 2, "y": 2, "size": 0.7}, [("SOLIDIFY", {"thickness": 0.3})], (3.8, -3.0, 1.0))
    add("bevel", "cube", {}, [("BEVEL", {"width": 0.15, "segments": 2})], (-4.0, -0.3, 1.0))
    add("triangulate", "cube", {}, [("TRIANGULATE", {})], (-1.2, -0.3, 1.0))
    off = add("disabled", "cube", {}, [("SUBSURF", {"levels": 2, "render_levels": 2})], (1.4, -0.3, 1.0))
    off.modifiers[0].show_viewport = False
    cutter = prim_mesh("uvsphere", "Z10_cutter_mesh", radius=0.7, u=16, v=8)
    co = add_mesh_obj(ctx, "Z10_cutter", cutter, loc=(3.0, 0.5, 1.4), scale=(0.8,) * 3)
    co.display_type = "WIRE"
    bo = add("boolean", "cube", {}, [("BOOLEAN", {"operation": "DIFFERENCE", "object": co, "solver": "EXACT"})], (3.8, -0.3, 1.0))
    update()
    for key, o in specs:
        fe = mesh_facts(o, evaluated=True)
        fb = mesh_facts(o, evaluated=False)
        case(f"{key}.applied", "CORE", f"{key}: modifier result exported (Apply Modifiers ON)",
             f"With 'Apply Modifiers' the evaluated mesh ({fe['faces']} faces) is written - what the viewport shows, not the {fb['faces']}-face base."
             + (" The disabled-in-viewport modifier is NOT applied." if key == "disabled" else ""),
             chk("mesh", facts=fe), chk("xf", obj=o.name))
        case(f"{key}.base", "CORE", f"{key}: base mesh exported (Apply Modifiers OFF)",
             f"With the option off the {fb['faces']}-face base mesh is written.",
             chk("mesh", facts=fb), profile="crease")
    case("boolean.cutter", "CORE", "The boolean cutter is itself exported as a solid",
         "Helper objects displayed as wire/bounds are still ordinary meshes to the exporter; hide them (or use 'Visible Only') if unwanted.",
         chk("shapes", obj="Z10_cutter", n=1))


# --------------------------------------------------------------------------------------
def _track_rot(src: Vector, dst: Vector):
    q = (dst - src).to_track_quat("-Z", "Y")
    return q.to_euler()


def x3d_fov_expected(angle, sensor_fit, W, H):
    """Independent re-implementation of Blender camera angle -> X3D fieldOfView (smaller display side)."""
    fit = sensor_fit if sensor_fit in ("HORIZONTAL", "VERTICAL") else ("HORIZONTAL" if W >= H else "VERTICAL")
    t = math.tan(angle / 2.0)
    tx, ty = (t, t * H / W) if fit == "HORIZONTAL" else (t * W / H, t)
    return 2.0 * math.atan(min(tx, ty))


@zone("Z11", "lights", "Lights: type mapping, intensity, spot cone, direction")
def zone_lights(ctx):
    # matte target spheres so the effect is visible in the browser
    for i in range(5):
        _sphere(ctx, f"Z11_target{i}", new_pbr(f"T_white_{i}", (0.85, 0.85, 0.85), 0.0, 0.8),
                (-4.0 + i * 2.0, 1.5, 0.6), r=0.6)

    def light(name, ltype, loc, rot=(0, 0, 0), **props):
        data = bpy.data.lights.new(name, ltype)
        for k, v in props.items():
            setattr(data, k, v)
        o = ctx.new_obj(name, data, loc=ctx.at(*loc), rot=rot)
        return o

    p = light("Z11_point", "POINT", (-4.0, -1.5, 2.0), energy=1.0, color=(1.0, 0.8, 0.6),
              use_custom_distance=True, cutoff_distance=8.0)
    p0 = light("Z11_point_default", "POINT", (-2.0, -1.5, 2.0), energy=1000.0, color=(0.6, 0.8, 1.0))
    p10 = light("Z11_p10", "POINT", (0.0, -1.5, 2.0), energy=10.0, use_custom_distance=True, cutoff_distance=6.0)
    p100 = light("Z11_p100", "POINT", (1.0, -1.5, 2.0), energy=100.0, use_custom_distance=True, cutoff_distance=6.0)
    spot_size = math.radians(60.0)
    sp = light("Z11_spot", "SPOT", (2.5, -1.5, 3.0), rot=(math.radians(20), 0, 0), energy=0.875, spot_size=spot_size,
               spot_blend=0.5, use_custom_distance=True, cutoff_distance=10.0, color=(1.0, 0.4, 0.4))
    sb0 = light("Z11_spot_b0", "SPOT", (3.6, -1.5, 3.0), rot=(math.radians(20), 0, 0), energy=0.5, spot_size=math.radians(50),
                spot_blend=0.0, use_custom_distance=True, cutoff_distance=10.0)
    sb1 = light("Z11_spot_b1", "SPOT", (4.5, -1.5, 3.0), rot=(math.radians(20), 0, 0), energy=0.5, spot_size=math.radians(50),
                spot_blend=1.0, use_custom_distance=True, cutoff_distance=10.0)
    sun = light("Z11_sun", "SUN", (-4.5, 3.5, 4.0), rot=(math.radians(40), math.radians(20), math.radians(10)), energy=0.6,
                color=(1.0, 0.95, 0.9))
    sunh = light("Z11_sun_hi", "SUN", (-3.0, 3.5, 4.0), rot=(math.radians(120), 0, 0), energy=3.0)
    ar = light("Z11_area", "AREA", (0.0, 3.5, 4.0), rot=(math.radians(180), 0, 0), energy=100.0, size=2.0)
    update()

    def wdir(o):
        return list((GLOBAL_MATRIX.to_3x3() @ o.matrix_world.to_3x3() @ Vector((0, 0, -1))).normalized())

    case("point", "CORE", "Point light: colour, intensity mapping, custom range",
         "<PointLight color='1 0.8 0.6' intensity='0.571429' radius='8' global='true'> inside the object's Transform; location 0 0 0 "
         "(the Transform places it).  intensity = min(energy_watts / 1.75, 1).",
         chk("light", obj="Z11_point", tag="PointLight",
             attrs={"color": [1.0, 0.8, 0.6], "intensity": 1.0 / 1.75, "radius": 8.0, "global": "true", "location": [0, 0, 0]}, tol=1e-4),
         chk("xf", obj="Z11_point"))
    case("point.saturation", "CORE", "Very bright point light clamps to intensity 1",
         "1000 W -> intensity 1.0 (SFFloat intensity is limited to [0,1]).",
         chk("light", obj="Z11_point_default", tag="PointLight", attrs={"intensity": 1.0, "color": [0.6, 0.8, 1.0]}, tol=1e-4))
    case("point.range", "FIDELITY", "Light radius follows the 'Custom Distance' switch",
         "When Custom Distance is OFF the light is unbounded in Blender; the exporter's documented fallback is radius 100.  "
         "It reads Blender's stored cutoff_distance (40 by default) even when the switch is off.",
         chk("light", obj="Z11_point_default", tag="PointLight", attrs={"radius": 100.0}, tol=1e-3))
    case("point.dynamic_range", "FIDELITY", "10 W and 100 W lights stay distinguishable",
         "Both clamp to intensity 1.0, so a 10x brightness difference vanishes.  A tone-mapped or log mapping (or rescaling the "
         "whole scene's lights by the maximum) would keep the ratio.",
         chk("light_differs", a={"obj": "Z11_p10", "attr": "intensity"}, b={"obj": "Z11_p100", "attr": "intensity"}))
    beam = float(spot_size) * 0.37
    cut = min(beam * 1.3, math.pi / 2)
    case("spot", "CORE", "Spot light: cone angles and range",
         f"<SpotLight beamWidth='{beam:.6f}' cutOffAngle='{cut:.6f}' direction='0 0 -1' radius='{10 * math.cos(beam):.4f}'> "
         "(legacy-exporter formulae: beamWidth = size x 0.37, cutOffAngle = 1.3 x beamWidth).  intensity 0.875/1.75 = 0.5.",
         chk("light", obj="Z11_spot", tag="SpotLight",
             attrs={"beamWidth": beam, "cutOffAngle": cut, "direction": [0, 0, -1], "intensity": 0.5, "radius": 10 * math.cos(beam),
                    "color": [1.0, 0.4, 0.4]}, tol=1e-4),
         chk("xf", obj="Z11_spot"))
    case("spot.cone", "FIDELITY", "cutOffAngle is the cone's half angle",
         "A 60 deg Blender spot has a 30 deg (0.5236 rad) half angle.  The legacy empirical formula gives 0.5037 (-3.8%).  "
         "Tolerance 1%.",
         chk("light", obj="Z11_spot", tag="SpotLight", attrs={"cutOffAngle": spot_size / 2.0}, tol=0.01 * spot_size / 2.0))
    case("spot.blend", "FIDELITY", "Spot blend influences beamWidth",
         "Blender's Blend value (0 hard edge .. 1 fully soft) has no counterpart in the formula, so two spots that differ only in blend export "
         "identical beamWidth.  Expected: beamWidth(blend 1.0) < beamWidth(blend 0.0).",
         chk("light_differs", a={"obj": "Z11_spot_b0", "attr": "beamWidth"}, b={"obj": "Z11_spot_b1", "attr": "beamWidth"}))
    case("sun", "CORE", "Sun -> DirectionalLight with world direction",
         "<DirectionalLight direction='0 0 -1' intensity='0.6' global='true'> in a Transform that rotates it; the WORLD direction "
         "(Transform rotation applied to the local -Z) equals Blender's light direction after the Y-up conversion.",
         chk("light", obj="Z11_sun", tag="DirectionalLight", attrs={"intensity": 0.6, "color": [1.0, 0.95, 0.9], "direction": [0, 0, -1]},
             tol=1e-4, world_dir=wdir(sun)),
         chk("xf", obj="Z11_sun"))
    case("sun.saturation", "CORE", "Sun strength above 1 clamps", "strength 3 -> intensity 1.",
         chk("light", obj="Z11_sun_hi", tag="DirectionalLight", attrs={"intensity": 1.0}, tol=1e-4, world_dir=wdir(sunh)))
    case("area", "CORE", "Area light -> DirectionalLight (documented approximation)",
         "X3D has no area light; the exporter maps it to a DirectionalLight along the lamp's -Z.  Expect a DirectionalLight with the right "
         "world direction (no crash, no PointLight).",
         chk("light", obj="Z11_area", tag="DirectionalLight", attrs={"intensity": 1.0}, tol=1e-4, world_dir=wdir(ar)))
    case("global", "CORE", "Every light is global",
         "global='true' on all lights: lights inside a Transform would otherwise only light their siblings (nothing).",
         chk("xpath", path=".//*[@global='false']", n={"eq": 0}),
         chk("xpath", path=".//PointLight[@global='true']", n={"min": 4}))
    case("shadow", "ROADMAP", "Shadows / soft size / specular factor",
         "Blender's shadow flags, light radius (soft shadows) and specular multiplier have no X3D equivalent in the exported subset; "
         "X_ITE supports shadows via the 'shadows' field of lights (X3D 4.0 'shadowIntensity').  Expect MISSING.",
         chk("roadmap", feature="light shadows", any_attrs=["shadowIntensity", "shadows"]))


# --------------------------------------------------------------------------------------
@zone("Z12", "cameras", "Cameras -> Viewpoints")
def zone_cameras(ctx):
    W, H = ctx.scene.render.resolution_x, ctx.scene.render.resolution_y

    def cam(name, loc, target, **props):
        data = bpy.data.cameras.new(name)
        for k, v in props.items():
            setattr(data, k, v)
        o = ctx.new_obj(name, data, loc=ctx.at(*loc))
        o.rotation_euler = _track_rot(Vector(ctx.at(*loc)), Vector(ctx.at(*target)))
        return o

    specs = [
        ("Z12_persp50", dict(angle=math.radians(50)), (-3.5, -4.0, 2.0)),
        ("Z12_vfit40", dict(sensor_fit="VERTICAL", angle=math.radians(40)), (-1.0, -4.0, 2.0)),
        ("Z12_hfit90", dict(sensor_fit="HORIZONTAL", angle=math.radians(90)), (1.5, -4.0, 2.0)),
        ("Z12_tele85", dict(lens=85.0, sensor_width=36.0), (4.0, -4.0, 2.0)),
    ]
    cams = []
    for name, props, loc in specs:
        c = cam(name, loc, (0, 2, 1), **props)
        cams.append(c)
    update()
    for c in cams:
        d = c.data
        exp = x3d_fov_expected(d.angle, d.sensor_fit, W, H)
        case(c.name.split("_", 1)[1], "CORE", f"{c.name}: FOV conversion ({d.sensor_fit}, {math.degrees(d.angle):.1f} deg in Blender)",
             f"<Viewpoint DEF='CA_{c.name}' fieldOfView='{exp:.6f}' position='0 0 0' orientation='0 0 1 0'> - X3D measures the FOV across the "
             f"SMALLER display side, Blender across the fitted side ({W}x{H} render).  The camera pose lives in the parent Transform.  "
             "Browser: select this viewpoint from the viewpoint list; framing matches Blender's camera view.",
             chk("view", obj=c.name, attrs={"fieldOfView": exp, "position": [0, 0, 0], "orientation": [0, 0, 1, 0]}, tol=1e-4,
                 description=c.name),
             chk("xf", obj=c.name))
    oc = cam("Z12_ortho", (-3.5, -4.0, 4.0), (0, 2, 1), type="ORTHO", ortho_scale=6.0)
    case("ortho", "CORE", "Orthographic camera does not crash",
         "Exported as a Viewpoint (no fieldOfView).  Browser: shows with the default perspective FOV.",
         chk("view", obj="Z12_ortho", attrs={"position": [0, 0, 0]}, tol=1e-4), chk("xf", obj="Z12_ortho"))
    case("ortho.viewpoint", "ROADMAP", "Orthographic camera -> OrthoViewpoint",
         "X3D 4.0 has OrthoViewpoint (fieldOfView = left/bottom/right/top box derived from ortho_scale).  Not mapped yet.",
         chk("roadmap", feature="OrthoViewpoint", any_tags=["OrthoViewpoint"]))
    ctx.scene.camera = cams[0]
    case("initial.view", "FIDELITY", "The scene's active camera is the initial Viewpoint",
         "X3D binds the FIRST Viewpoint in the file on load.  Blender's active camera (here Z12_persp50) should therefore come first "
         "(or be bound explicitly) so the file opens exactly like the Blender camera view.",
         chk("first_viewpoint", obj="Z12_persp50"))
    case("pan", "ROADMAP", "Lens shift and clipping planes",
         "shift_x/shift_y and clip_start/clip_end have no Viewpoint fields; X3D carries clipping in NavigationInfo.visibilityLimit/avatarSize. "
         "Not exported (acceptable for most scenes).",
         chk("roadmap", feature="NavigationInfo.visibilityLimit from clip_end", any_attrs=["visibilityLimit"]))


# --------------------------------------------------------------------------------------
SAMPLE_FRAMES = [1, 7, 13, 19, 25, 31, 37, 43, 49]
HALF_FRAMES = [1.5, 12.5, 24.5, 36.5, 48.5]


def _goto(frame):
    sc = bpy.context.scene
    fi = int(math.floor(frame))
    sc.frame_set(fi, subframe=frame - fi)
    update()


def record_world(obj_name, frames):
    """[(frame, world matrix in X3D space)] by really evaluating Blender at those frames."""
    out = []
    obj = bpy.data.objects[obj_name]
    for f in frames:
        _goto(f)
        out.append({"frame": f, "m": mat16(GLOBAL_MATRIX @ obj.matrix_world)})
    _goto(FRAME_START)
    return out


def _key(obj, path, frame, index=-1, data=None):
    (data or obj).keyframe_insert(data_path=path, frame=frame, index=index)


@zone("Z13", "anim", "Animation: sampled transforms, hierarchy, constraints, drivers, physics")
def zone_anim(ctx):
    sc = ctx.scene
    base = prim_mesh("cube", "Z13_cube_mesh", size=0.5)
    base.materials.append(clay())

    def cube(name, loc, **kw):
        return ctx.new_obj(name, base, loc=ctx.at(*loc), **kw)

    set_interpolation_linear()
    # 1 translation with a mid key
    o = cube("Z13_move", (-4.0, -4.0, 0.5))
    for f, p in ((1, (-4.0, -4.0, 0.5)), (25, (0.0, -4.0, 2.0)), (49, (4.0, -4.0, 0.5))):
        o.location = ctx.at(*p); _key(o, "location", f)
    # 2 one full turn about Z
    o = cube("Z13_spin", (-4.0, -2.4, 0.5))
    for f, a in ((1, 0.0), (49, math.tau)):
        o.rotation_euler = (0, 0, a); _key(o, "rotation_euler", f)
    # 3 scale pulse
    o = cube("Z13_scale", (-2.0, -2.4, 0.5))
    for f, s in ((1, 1.0), (25, 2.0), (49, 1.0)):
        o.scale = (s, s, s); _key(o, "scale", f)
    # 5 parent orbit + child bob
    par = ctx.new_obj("Z13_orbit_parent", None, loc=ctx.at(2.0, -2.4, 0.5))
    for f, a in ((1, 0.0), (49, math.tau)):
        par.rotation_euler = (0, 0, a); _key(par, "rotation_euler", f)
    ch = ctx.new_obj("Z13_orbit_child", base, loc=(1.4, 0.0, 0.0), parent=par)
    for f, z in ((1, 0.0), (25, 0.8), (49, 0.0)):
        ch.location = (1.4, 0.0, z); _key(ch, "location", f)
    # 6 constraint follower (no keys of its own)
    fol = cube("Z13_follow", (0, 0, 0))
    fol.location = (0.0, 1.4, 0.4)
    cc = fol.constraints.new("COPY_LOCATION"); cc.target = bpy.data.objects["Z13_move"]; cc.use_offset = True
    # 7 driver
    dr = cube("Z13_driver", (-4.0, 0.0, 0.5))
    fc = dr.driver_add("rotation_euler", 2)
    fc.driver.type = "SCRIPTED"; fc.driver.expression = "frame * 0.1309"
    # 8 keyed but constant -> must produce no interpolators
    st = cube("Z13_still", (-2.0, 0.0, 0.5))
    for f in (1, 49):
        st.location = ctx.at(-2.0, 0.0, 0.5); _key(st, "location", f)
    # 9 camera flight with Track-To
    tgt = ctx.new_obj("Z13_cam_target", None, loc=ctx.at(0.0, 2.2, 0.8))
    cdata = bpy.data.cameras.new("Z13_cam")
    cam = ctx.new_obj("Z13_cam", cdata, loc=ctx.at(-3.0, 0.5, 2.0))
    tc = cam.constraints.new("TRACK_TO"); tc.target = tgt; tc.track_axis = "TRACK_NEGATIVE_Z"; tc.up_axis = "UP_Y"
    for f, p in ((1, (-3.0, 0.5, 2.0)), (25, (0.0, -1.5, 3.0)), (49, (3.0, 0.5, 2.0))):
        cam.location = ctx.at(*p); _key(cam, "location", f)
    # 10 fast spin: 24.3 turns -> >180 deg per sampled frame (aliasing)
    fs = cube("Z13_fastspin", (2.0, 0.0, 0.5))
    for f, a in ((1, 0.0), (49, 24.3 * math.tau)):
        fs.rotation_euler = (0, 0, a); _key(fs, "rotation_euler", f)
    # 4 bezier ease (must come after linear ones so interpolation preference is right)
    set_interpolation_bezier()
    be = cube("Z13_ease", (-4.0, 2.4, 0.5))
    for f, x in ((1, -4.0), (49, 4.0)):
        be.location = ctx.at(x, 2.4, 0.5); _key(be, "location", f)
    EASED_ACTIONS.add(be.animation_data.action.name)
    set_interpolation_linear()
    # 11 light animation
    ld = bpy.data.lights.new("Z13_lamp", "POINT"); ld.energy = 0.3
    lo = ctx.new_obj("Z13_lamp", ld, loc=ctx.at(2.5, 2.4, 2.0))
    ld.use_custom_distance = True; ld.cutoff_distance = 6.0
    for f, e, c in ((1, 0.3, (1, 0, 0)), (49, 1.5, (0, 0, 1))):
        ld.energy = e; ld.color = c
        ld.keyframe_insert("energy", frame=f); ld.keyframe_insert("color", frame=f)
    # 12 material colour animation
    am = new_pbr("T_anim_color", (1.0, 0.1, 0.1), 0.0, 0.4)
    sp = _sphere(ctx, "Z13_matanim", am, (4.0, 0.0, 0.5), r=0.4)
    try:
        sock = bsdf_of(am).inputs["Base Color"]
        for f, c in ((1, (1.0, 0.1, 0.1, 1)), (49, (0.1, 0.1, 1.0, 1))):
            sock.default_value = c
            sock.keyframe_insert("default_value", frame=f)
        mat_anim_ok = True
    except Exception as exc:
        log(f"material animation not keyable: {exc!r}"); mat_anim_ok = False
    # 13 shape key
    sk_mesh = prim_mesh("uvsphere", "Z13_morph_mesh", smooth=True, radius=0.5, u=16, v=8)
    sk = add_mesh_obj(ctx, "Z13_morph", sk_mesh, loc=(4.0, 2.4, 0.6))
    sk.shape_key_add(name="Basis")
    k1 = sk.shape_key_add(name="Stretch")
    for v in k1.data:
        v.co.z *= 2.0
    for f, val in ((1, 0.0), (49, 1.0)):
        k1.value = val; k1.keyframe_insert("value", frame=f)
    # keyframe_insert() ignores the interpolation preference when called from Python -> enforce explicitly,
    # BEFORE any expectation is recorded from the evaluated scene.
    force_interpolation()
    # 14 rigid body ball
    phys_ok = False
    try:
        ground = ctx.new_obj("Z13_ground", prim_mesh("cube", "Z13_ground_mesh", size=1.0), loc=ctx.at(0, -0.8, -0.2), scale=(9.0, 3.0, 0.2))
        ball = _sphere(ctx, "Z13_ball", new_pbr("T_ball", (0.9, 0.9, 0.2), 0.0, 0.3), (0.0, -0.8, 5.0), r=0.4)
        view_layer = sc.view_layers[0]
        with bpy.context.temp_override(scene=sc, view_layer=view_layer):
            if sc.rigidbody_world is None:
                bpy.ops.rigidbody.world_add()
            for ob, typ in ((ground, "PASSIVE"), (ball, "ACTIVE")):
                view_layer.objects.active = ob
                for other in sc.objects:
                    other.select_set(other is ob)
                with bpy.context.temp_override(scene=sc, view_layer=view_layer, active_object=ob, object=ob, selected_objects=[ob]):
                    bpy.ops.rigidbody.object_add(type=typ)
            ball.rigid_body.restitution = 0.7
            ball.rigid_body.collision_shape = "SPHERE"
            ground.rigid_body.collision_shape = "BOX"
            sc.rigidbody_world.point_cache.frame_start = FRAME_START
            sc.rigidbody_world.point_cache.frame_end = FRAME_END
        phys_ok = True
    except Exception as exc:
        log(f"rigid body setup failed: {exc!r}")
    update()
    if phys_ok:
        # A rigid-body world only advances when frames are visited IN ORDER; jumping straight to frame 25 would record a
        # different state than the exporter's sequential 1..49 pass.  Visit every frame once so the point cache is filled.
        for f in range(FRAME_START, FRAME_END + 1):
            sc.frame_set(f)
    _goto(FRAME_START)

    # ---------------- cases ----------------
    case("timer", "CORE", "One TimeSensor drives everything",
         f"<TimeSensor DEF='SceneTimer' cycleInterval='{(FRAME_END - FRAME_START) / FPS:.6f}' loop='true'>: frames {FRAME_START}..{FRAME_END} at {FPS} fps = "
         f"{(FRAME_END - FRAME_START) / FPS:.1f} s.  Browser: animation starts by itself and loops seamlessly.",
         chk("timer", cycle=(FRAME_END - FRAME_START) / FPS, loop=True))
    case("move", "CORE", "Keyframed translation (linear, 3 keys)",
         "A PositionInterpolator with one key per frame (49 keys, 0..1) routed TimeSensor.fraction_changed -> set_fraction and "
         "value_changed -> Transform.set_translation.  Browser: the cube glides left->right rising to the middle and sinking again.",
         chk("anim_nodes", obj="Z13_move", kinds=["position"], keys=FRAME_END - FRAME_START + 1),
         chk("anim_world", obj="Z13_move", samples=record_world("Z13_move", SAMPLE_FRAMES), tol=2e-4))
    case("spin", "CORE", "One full revolution (OrientationInterpolator)",
         "49 orientation keys; angular velocity constant, so even mid-frame playback positions match Blender.  First and last orientation are "
         "identical (seamless loop).",
         chk("anim_nodes", obj="Z13_spin", kinds=["orientation"], keys=FRAME_END - FRAME_START + 1),
         chk("anim_world", obj="Z13_spin", samples=record_world("Z13_spin", SAMPLE_FRAMES + HALF_FRAMES), tol=2e-3))
    case("scale", "CORE", "Scale pulse", "A scale interpolator (PositionInterpolator DEF SI_*) routed to set_scale.",
         chk("anim_nodes", obj="Z13_scale", kinds=["scale"], keys=FRAME_END - FRAME_START + 1),
         chk("anim_world", obj="Z13_scale", samples=record_world("Z13_scale", SAMPLE_FRAMES), tol=2e-4))
    case("ease", "CORE", "Bezier-eased motion is sampled, not approximated by two keys",
         "Because every frame is sampled, the ease-in/ease-out curve survives: mid-timeline positions match Blender (not a straight line).",
         chk("anim_world", obj="Z13_ease", samples=record_world("Z13_ease", SAMPLE_FRAMES + HALF_FRAMES), tol=2e-3))
    case("hierarchy", "CORE", "Animated parent with animated child (orbit + bob)",
         "Parent rotates (orientation interpolator), child bobs (position interpolator) in parent space; composed world position equals "
         "Blender's at every sample frame.  Browser: a cube circling its pivot while bobbing.",
         chk("anim_world", obj="Z13_orbit_parent", samples=record_world("Z13_orbit_parent", SAMPLE_FRAMES), tol=2e-4),
         chk("anim_world", obj="Z13_orbit_child", samples=record_world("Z13_orbit_child", SAMPLE_FRAMES + HALF_FRAMES), tol=2e-3))
    case("constraint", "CORE", "Constraint-driven object animates without own keyframes",
         "Z13_follow has no keys, but follows Z13_move through a Copy Location constraint: the exporter samples matrix_world, so it still "
         "receives an interpolator.",
         chk("anim_nodes", obj="Z13_follow", kinds=["position"]),
         chk("anim_world", obj="Z13_follow", samples=record_world("Z13_follow", SAMPLE_FRAMES), tol=2e-4))
    case("driver", "CORE", "Driver-based animation (rotation = frame x 7.5 deg)",
         "Drivers are evaluated by Blender before sampling, so Z13_driver turns 360 deg over the cycle.",
         chk("anim_world", obj="Z13_driver", samples=record_world("Z13_driver", SAMPLE_FRAMES), tol=2e-3))
    case("still", "CORE", "Keyed but unchanging objects get no interpolators",
         "Z13_still has keyframes with identical values -> no PositionInterpolator, no ROUTE.",
         chk("anim_absent", obj="Z13_still"))
    case("camera", "CORE", "Animated camera (Track-To) -> animated Viewpoint Transform",
         "The camera's Transform is animated with the constraint solved at every frame, so the Viewpoint swings along the path while "
         "always looking at the target.",
         chk("anim_world", obj="Z13_cam", samples=record_world("Z13_cam", SAMPLE_FRAMES), tol=2e-3))
    case("fastspin", "FIDELITY", "Spins faster than half a turn per frame are not aliased",
         "24.3 turns in 48 frames = 182 deg per frame.  Interpolators take the SHORTEST rotation between consecutive keys, so the "
         "playback shows the cube creeping slowly BACKWARDS.  Faithful export subdivides keys (or uses more keys per frame).  Checked at mid-frame points.",
         chk("anim_world", obj="Z13_fastspin", samples=record_world("Z13_fastspin", HALF_FRAMES), tol=2e-2))
    case("light", "ROADMAP", "Animated light colour / energy",
         "Animation sampling covers object transforms only.  Light energy/colour keyframes would need a ScalarInterpolator/ColorInterpolator "
         "routed to the light's intensity/color.  Expect MISSING.",
         chk("roadmap", feature="light property animation", route_into=["LA_Z13_lamp"]))
    if mat_anim_ok:
        case("material", "ROADMAP", "Animated material colour",
             "Keyframed Base Color -> ColorInterpolator routed to the PhysicalMaterial.baseColor.  Not implemented.",
             chk("roadmap", feature="material animation", route_into=["MA_T_anim_color", "APP_T_anim_color"]))
    case("shapekey", "ROADMAP", "Shape keys (morph targets)",
         "Keyed shape-key value -> CoordinateInterpolator animating the Coordinate points (or morph weights).  Today the basis mesh is "
         "exported and the morph is lost.",
         chk("roadmap", feature="vertex animation", any_tags=["CoordinateInterpolator", "CoordinateInterpolator2D"]))
    if phys_ok:
        # Record the simulation the way the exporter will see it (sequential frame stepping from the start)
        samples = record_world("Z13_ball", SAMPLE_FRAMES)
        case("physics", "FIDELITY", "Baked rigid-body simulation becomes keyframe-like interpolators",
             "A ball dropped from 5 m bounces on a box (restitution 0.7).  The exporter steps the frame range sequentially, sampling "
             "matrix_world, so the dynamics become a PositionInterpolator.  This is the bridge from Blender simulations to X3D.  "
             "Marked FIDELITY because it relies on the rigid-body cache being deterministic across two sequential passes.",
             chk("anim_nodes", obj="Z13_ball", kinds=["position"], keys=FRAME_END - FRAME_START + 1),
             chk("anim_world", obj="Z13_ball", samples=samples, tol=5e-3))
    case("meshdeform", "ROADMAP", "Per-frame mesh deformation (cloth, soft body, simulation output)",
         "Scientific/engineering simulations usually deform geometry over time.  X3D handles this with CoordinateInterpolator; the exporter "
         "samples transforms only.", chk("roadmap", feature="CoordinateInterpolator export", any_tags=["CoordinateInterpolator"]))
    set_interpolation_bezier()
    _goto(FRAME_START)


# --------------------------------------------------------------------------------------
def _tube(bm, p0, p1, radius, rings=8, segs=10):
    p0, p1 = Vector(p0), Vector(p1)
    axis = (p1 - p0)
    length = axis.length
    rot = axis.to_track_quat("Z", "Y").to_matrix()
    ring_verts = []
    for r in range(rings + 1):
        t = r / rings
        row = []
        for s in range(segs):
            a = s * math.tau / segs
            local = Vector((radius * math.cos(a), radius * math.sin(a), t * length))
            row.append(bm.verts.new(p0 + rot @ local))
        ring_verts.append(row)
    for r in range(rings):
        for s in range(segs):
            bm.faces.new((ring_verts[r][s], ring_verts[r][(s + 1) % segs], ring_verts[r + 1][(s + 1) % segs], ring_verts[r + 1][s]))


@zone("Z14", "hanim", "Armature -> HAnim humanoid with skinning and pose animation")
def zone_hanim(ctx):
    sc = ctx.scene
    origin = ctx.at(0, 0, 0.0)
    bones = [  # name, head, tail, parent
        ("hips", (0, 0, 0.0), (0, 0, 0.6), None),
        ("spine", (0, 0, 0.6), (0, 0, 1.2), "hips"),
        ("head", (0, 0, 1.2), (0, 0, 1.7), "spine"),
        ("arm_L", (0, 0, 1.1), (0.7, 0, 1.1), "spine"),
        ("forearm_L", (0.7, 0, 1.1), (1.4, 0, 1.1), "arm_L"),
        ("arm_R", (0, 0, 1.1), (-0.7, 0, 1.1), "spine"),
    ]
    adata = bpy.data.armatures.new("Z14_rig_data")
    arm = ctx.new_obj("Z14_rig", adata, loc=origin)
    vl = sc.view_layers[0]
    vl.objects.active = arm
    for o in sc.objects:
        o.select_set(o is arm)
    with bpy.context.temp_override(scene=sc, view_layer=vl, active_object=arm, object=arm):
        bpy.ops.object.mode_set(mode="EDIT")
        eb = adata.edit_bones
        for name, head, tail, parent in bones:
            b = eb.new(name)
            b.head, b.tail = head, tail
            if parent:
                b.parent = eb[parent]
        bpy.ops.object.mode_set(mode="OBJECT")
    # skin mesh: torso tube, head tube, two arm tubes
    bm = bmesh.new()
    _tube(bm, (0, 0, 0.0), (0, 0, 1.2), 0.25, rings=12)
    _tube(bm, (0, 0, 1.2), (0, 0, 1.7), 0.17, rings=4)
    _tube(bm, (0, 0, 1.1), (1.4, 0, 1.1), 0.1, rings=12)
    _tube(bm, (0, 0, 1.1), (-0.7, 0, 1.1), 0.1, rings=6)
    mesh = mesh_from_bm("Z14_skin_mesh", bm, smooth=True)
    skin = ctx.new_obj("Z14_skin", mesh, loc=origin)
    mesh.materials.append(new_pbr("T_skin", (0.85, 0.6, 0.5), 0.0, 0.6))
    # weights: smooth falloff by distance to each bone segment, keep the 2 strongest, normalise
    def seg_dist(p, a, b):
        a, b = Vector(a), Vector(b)
        ab = b - a
        t = max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
        return (p - (a + ab * t)).length
    groups = {n: skin.vertex_groups.new(name=n) for n, *_ in bones}
    for v in mesh.vertices:
        d = {n: seg_dist(v.co, h, t) for n, h, t, _ in bones}
        near = sorted(d, key=d.get)[:2]
        ws = {n: math.exp(-(d[n] / 0.35) ** 2) for n in near}
        tot = sum(ws.values())
        for n, w in ws.items():
            groups[n].add([v.index], w / tot, "REPLACE")
    md = skin.modifiers.new("Armature", "ARMATURE")
    md.object = arm
    skin.parent = arm
    skin.location = (0.0, 0.0, 0.0)      # parented with identity parent-inverse: the skin sits AT the armature origin
    # pose animation
    set_interpolation_linear()
    for pb_name, axis, keys in (
        ("spine", 0, ((1, 0.0), (25, math.radians(25)), (49, 0.0))),
        ("arm_L", 1, ((1, 0.0), (25, math.radians(-70)), (49, 0.0))),
        ("forearm_L", 1, ((1, 0.0), (25, math.radians(-60)), (49, 0.0))),
        ("head", 2, ((1, 0.0), (25, math.radians(40)), (49, 0.0))),
    ):
        pb = arm.pose.bones[pb_name]
        pb.rotation_mode = "XYZ"
        for f, a in keys:
            e = [0.0, 0.0, 0.0]; e[axis] = a
            pb.rotation_euler = e
            pb.keyframe_insert("rotation_euler", frame=f)
    force_interpolation()
    set_interpolation_bezier()
    _goto(FRAME_START)
    # second, skin-less armature
    a2 = bpy.data.armatures.new("Z14_rig2_data")
    arm2 = ctx.new_obj("Z14_rig2", a2, loc=ctx.at(3.5, 0, 0))
    vl.objects.active = arm2
    for o in sc.objects:
        o.select_set(o is arm2)
    with bpy.context.temp_override(scene=sc, view_layer=vl, active_object=arm2, object=arm2):
        bpy.ops.object.mode_set(mode="EDIT")
        b1 = a2.edit_bones.new("base"); b1.head, b1.tail = (0, 0, 0), (0, 0, 1)
        b2 = a2.edit_bones.new("tip"); b2.head, b2.tail = (0, 0, 1), (0, 0, 2); b2.parent = b1; b2.use_connect = True
        bpy.ops.object.mode_set(mode="OBJECT")
    update()
    # ----- facts for the validator
    binfo = []
    for b in arm.data.bones:
        binfo.append({"name": b.name, "parent": b.parent.name if b.parent else None, "head": [float(c) for c in b.head_local]})
    # skin probes: rest position (armature space) + expected posed world position (X3D space) per frame
    # Only vertices whose rest position is UNIQUE can be probed: the arm tubes share a start ring, and two vertices at one rest
    # position (with different weights) cannot be told apart when matching file points to Blender vertices by position.
    inv = arm.matrix_world.inverted()
    rest = {i: [float(c) for c in (inv @ skin.matrix_world @ v.co)] for i, v in enumerate(mesh.vertices)}
    from collections import Counter
    cnt = Counter(tuple(round(c, 3) for c in p) for p in rest.values())
    uniq = [i for i in rest if cnt[tuple(round(c, 3) for c in rest[i])] == 1]
    probe_ids = uniq[::max(1, len(uniq) // 24)]
    probes = []
    for f in [1, 13, 25, 37, 49]:
        _goto(f)
        dg = bpy.context.evaluated_depsgraph_get()
        ev = skin.evaluated_get(dg)
        tmp = ev.to_mesh()
        for i in probe_ids:
            pw = GLOBAL_MATRIX @ (skin.matrix_world @ tmp.vertices[i].co)
            probes.append({"frame": f, "rest": rest[i], "world": [float(c) for c in pw]})
        ev.to_mesh_clear()
    _goto(FRAME_START)
    case("structure", "CORE", "Armature -> HAnimHumanoid with a joint tree",
         "One <HAnimHumanoid name='Z14_rig' version='2.0'> whose <HAnimJoint> tree mirrors the bone hierarchy (6 joints, names = bone names, "
         "'center' = bone head in armature space), each joint also listed once in 'joints' via USE.  Component HAnim level 1 is declared.",
         chk("component", name="HAnim", level=1),
         chk("hanim", armature="Z14_rig", bones=binfo, skin_vertices=len({tuple(round(c, 4) for c in v.co) for v in mesh.vertices})),
         chk("xf", obj="Z14_rig"))
    case("weights", "CORE", "Skin weights are complete and normalised",
         "Every skin vertex is attached to joints through skinCoordIndex/skinCoordWeight; the weights for each skinCoord point sum to 1.",
         chk("hanim_weights", armature="Z14_rig"))
    case("pose", "CORE", "Linear-blend skinning reproduces Blender's deformation",
         "Emulating HAnim's skinning (sum over joints of weight x joint matrix about 'center') with the exported joint interpolators "
         "reproduces the vertex positions Blender's Armature modifier produces at frames 1, 13, 25, 37, 49.  Browser: arm raises, torso bends, head turns.",
         chk("hanim_pose", armature="Z14_rig", probes=probes, tol=2e-3))
    case("skinless", "CORE", "Armature without skin still exports a humanoid",
         "Z14_rig2 has two bones and no mesh: HAnimHumanoid with joints base and tip, no skinCoord, no crash.",
         chk("hanim", armature="Z14_rig2", bones=[{"name": b.name, "parent": b.parent.name if b.parent else None,
                                                    "head": [float(c) for c in b.head_local]} for b in arm2.data.bones],
             skin_vertices=0))
    case("hanim.names", "ROADMAP", "Standard HAnim joint names / LOA",
         "The exporter writes Blender bone names and skeletalConfiguration='BLENDER'.  Standards-conformant avatars need the HAnim joint "
         "names (l_shoulder, vl5 ...) and a level of articulation; a mapping table would make Blender rigs interchangeable with other HAnim tools.",
         chk("roadmap", feature="standard HAnim names", any_values={"name": "humanoid_root"}))


# --------------------------------------------------------------------------------------
def _try_new(label, fn):
    try:
        return fn()
    except Exception as exc:
        log(f"{label}: could not create ({exc!r})")
        return None


@zone("Z15", "types", "Object types: text, curves, surfaces and everything the exporter must skip gracefully")
def zone_types(ctx):
    # --- convertible types ---------------------------------------------------------
    cu = bpy.data.curves.new("Z15_text_data", "FONT")
    cu.body = "X3D"; cu.extrude = 0.06; cu.size = 0.9; cu.align_x = "CENTER"
    t = ctx.new_obj("Z15_text", cu, loc=ctx.at(-4.0, -3.0, 0.1), rot=(math.pi / 2, 0, 0))
    t.data.materials.append(clay())
    cv = bpy.data.curves.new("Z15_bevel_data", "CURVE")
    cv.dimensions = "3D"; cv.bevel_depth = 0.08; cv.resolution_u = 8
    sp = cv.splines.new("POLY"); sp.points.add(5)
    for i, p in enumerate([(0, 0, 0), (0.8, 0, 0.6), (1.6, 0, 0), (2.4, 0, 0.6), (3.2, 0, 0), (4.0, 0, 0.6)]):
        sp.points[i].co = (*p, 1.0)
    c1 = ctx.new_obj("Z15_curve_bevel", cv, loc=ctx.at(-1.0, -3.0, 0.5)); c1.data.materials.append(clay())
    cw = bpy.data.curves.new("Z15_wire_data", "CURVE")
    cw.dimensions = "3D"
    sp = cw.splines.new("BEZIER"); sp.bezier_points.add(2)
    for i, (p, l, r) in enumerate([((0, 0, 0), (-0.3, 0, 0), (0.3, 0, 0)), ((1, 0, 1), (0.7, 0, 1), (1.3, 0, 1)), ((2, 0, 0), (1.7, 0, 0), (2.3, 0, 0))]):
        sp.bezier_points[i].co = p; sp.bezier_points[i].handle_left = l; sp.bezier_points[i].handle_right = r
    cw_o = ctx.new_obj("Z15_curve_wire", cw, loc=ctx.at(3.2, -3.0, 0.5))
    update()
    case("text", "CORE", "Text object is converted to a mesh",
         "A FONT object ('X3D', extruded) becomes an IndexedFaceSet of the glyph outlines (evaluated mesh).  Browser: extruded letters X 3 D.",
         chk("mesh", facts={"obj": "Z15_text", "faces_min": 20}), chk("xf", obj="Z15_text"))
    case("curve.bevel", "CORE", "Beveled curve is converted to a tube mesh",
         "A poly curve with bevel depth becomes a mesh tube (faces > 0).", chk("mesh", facts={"obj": "Z15_curve_bevel", "faces_min": 20}),
         chk("xf", obj="Z15_curve_bevel"))
    case("curve.wire", "CORE", "Un-beveled curve has no faces: handled gracefully",
         "A curve without thickness exports no Shape; the diagnostics say \"Object 'Z15_curve_wire' has no exportable faces.\"",
         chk("shapes", obj="Z15_curve_wire", n=0), chk("diag", contains="Z15_curve_wire' has no exportable faces"))
    case("curve.lines", "ROADMAP", "Curves -> IndexedLineSet / Polyline2D / NurbsCurve",
         "Scientific content (streamlines, trajectories, graphs) is naturally curves.  X3D has NurbsCurve and IndexedLineSet; neither is written.",
         chk("roadmap", feature="curve export", any_tags=["IndexedLineSet", "NurbsCurve", "LineSet"]))
    # NURBS surface through the data API
    def make_surface():
        sc_, vl_ = ctx.scene, ctx.scene.view_layers[0]
        with bpy.context.temp_override(scene=sc_, view_layer=vl_):
            before = set(sc_.objects)
            bpy.ops.surface.primitive_nurbs_surface_surface_add(radius=1.0, location=tuple(ctx.at(-4.0, 0.0, 0.6)))
            created = [o for o in sc_.objects if o not in before]
        o = created[0]
        o.name = "Z15_surface"
        o.data.name = "Z15_surf_data"
        for c in list(o.users_collection):
            c.objects.unlink(o)
        ctx.collection.objects.link(o)
        o.data.materials.append(clay())
        return o
    so = _try_new("NURBS surface", make_surface)
    update()
    if so is not None:
        case("surface", "CORE", "NURBS surface is tessellated to a mesh",
             "A SURFACE object is evaluated to a mesh (resolution 8x8) and exported as an IndexedFaceSet.",
             chk("mesh", facts={"obj": "Z15_surface", "faces_min": 4}))
    # --- skipped types -------------------------------------------------------------
    def meta():
        mb = bpy.data.metaballs.new("Z15_meta_data")
        e = mb.elements.new(); e.radius = 0.6
        e2 = mb.elements.new(); e2.co = (0.5, 0, 0); e2.radius = 0.5
        return ctx.new_obj("Z15_meta", mb, loc=ctx.at(-1.0, 0.0, 0.8))
    def volume():
        return ctx.new_obj("Z15_volume", bpy.data.volumes.new("Z15_volume_data"), loc=ctx.at(0.5, 0.0, 0.8))
    def lattice():
        return ctx.new_obj("Z15_lattice", bpy.data.lattices.new("Z15_lattice_data"), loc=ctx.at(2.0, 0.0, 0.8))
    def speaker():
        return ctx.new_obj("Z15_speaker", bpy.data.speakers.new("Z15_speaker_data"), loc=ctx.at(3.5, 0.0, 0.8))
    def probe():
        return ctx.new_obj("Z15_probe", bpy.data.lightprobes.new("Z15_probe_data", "SPHERE"), loc=ctx.at(-4.0, 3.0, 0.8))
    def gpencil():
        coll = getattr(bpy.data, "grease_pencils_v3", None) or bpy.data.grease_pencils
        return ctx.new_obj("Z15_gpencil", coll.new("Z15_gp_data"), loc=ctx.at(-2.5, 3.0, 0.8))
    def hair():
        return ctx.new_obj("Z15_hair", bpy.data.hair_curves.new("Z15_hair_data"), loc=ctx.at(-1.0, 3.0, 0.8))
    def pcloud():
        return ctx.new_obj("Z15_points", bpy.data.pointclouds.new("Z15_points_data"), loc=ctx.at(0.5, 3.0, 0.8))
    made = []
    for label, fn in (("meta", meta), ("volume", volume), ("lattice", lattice), ("speaker", speaker), ("probe", probe),
                      ("gpencil", gpencil), ("hair", hair), ("points", pcloud)):
        o = _try_new(label, fn)
        if o is not None:
            made.append((label, o))
    update()
    for label, o in made:
        case(f"skip.{label}", "CORE", f"{o.type} object is skipped with a diagnostic, not a crash",
             f"The exporter writes <meta name='info' content='Skipped 1 {o.type} object(s): not yet supported by the X3D 4.0 path.'>; "
             "the export still completes and the file validates.  (In hierarchy mode the object keeps an empty Transform.)",
             chk("diag", contains=f"Skipped 1 {o.type} object"))
    if any(l == "meta" for l, _ in made):
        case("meta.geometry", "FIDELITY", "Metaballs are exported as meshes",
             "Metaballs are common for blobs/molecular surfaces.  They evaluate to meshes, so an exporter could tessellate them like curves and text; "
             "today they are skipped.",
             chk("xpath", path=".//Transform[@DEF='OB_Z15_meta']//Shape", n={"min": 1}))
    if any(l == "gpencil" for l, _ in made):
        case("gpencil.geometry", "ROADMAP", "Grease Pencil strokes", "Strokes could become IndexedLineSet.  Skipped today.",
             chk("xpath", path=".//Transform[@DEF='OB_Z15_gpencil']//Shape", n={"min": 1}))


# --------------------------------------------------------------------------------------
SH_C0 = 0.28209479177387814


@zone("Z16", "splats", "Gaussian splats (X3D 4.1) and Inline references")
def zone_splats(ctx):
    n = 48
    mesh = bpy.data.meshes.new("Z16_helix_splats")
    pts, scales, quats, ops, cols = [], [], [], [], []
    for i in range(n):
        t = i / (n - 1)
        a = t * 4 * math.pi
        pts.append((math.cos(a), math.sin(a), 2 * t - 1))
        scales.append((0.05 + 0.05 * t, 0.02, 0.08))
        quats.append((math.cos(a / 2), 0.0, 0.0, math.sin(a / 2)))       # Blender order (w, x, y, z)
        ops.append(0.25 + 0.75 * t)
        cols.append((t, 1.0 - t, 0.5))
    mesh.from_pydata(pts, [], []); mesh.update()
    mesh["x3d_gaussian_splats"] = True
    mesh["x3d_splat_color_space"] = "SRGB_REC709_DISPLAY"
    a = mesh.attributes.new("splat_scale", "FLOAT_VECTOR", "POINT"); a.data.foreach_set("vector", [c for s in scales for c in s])
    a = mesh.attributes.new("splat_rotation", "QUATERNION", "POINT"); a.data.foreach_set("value", [c for q in quats for c in q])
    a = mesh.attributes.new("splat_opacity", "FLOAT", "POINT"); a.data.foreach_set("value", ops)
    a = mesh.attributes.new("splat_sh0_0", "FLOAT_VECTOR", "POINT")
    a.data.foreach_set("vector", [c for rgb in cols for c in ((rgb[0] - 0.5) / SH_C0, (rgb[1] - 0.5) / SH_C0, (rgb[2] - 0.5) / SH_C0)])
    o = ctx.new_obj("Z16_splats", mesh, loc=ctx.at(-2.5, 0.0, 1.4), rot=(0.0, 0.0, math.radians(30)), scale=(1.2, 1.2, 1.2))
    update()
    case("pointset", "CORE", "4.0 export degrades splats to a coloured PointSet",
         "X3D 4.0 has no splat node: the splat centres are written as <PointSet> with one ColorRGBA per point (48 points) and a head note "
         "'Gaussian splat object(s) written as PointSet; choose X3D 4.1'.  Browser: a coloured helix of dots.",
         chk("xpath", path=".//Transform[@DEF='OB_Z16_splats']//PointSet", n={"eq": 1}),
         chk("xpath", path=".//Transform[@DEF='OB_Z16_splats']//PointSet/Coordinate", n={"eq": 1}),
         chk("count_floats", path=".//Transform[@DEF='OB_Z16_splats']//PointSet/Coordinate", attr="point", count=n * 3),
         chk("count_floats", path=".//Transform[@DEF='OB_Z16_splats']//PointSet/ColorRGBA", attr="color", count=n * 4),
         chk("diag", contains="written as PointSet"), chk("xf", obj="Z16_splats"))
    case("gaussiansplats", "CORE", "4.1 export writes the GaussianSplats node",
         "<GaussianSplats positions scales orientations opacities sphericalHarmonicsDegree0Coef0 ...> with 48 splats (positions 144 floats, "
         "scales 144, orientations 192 (x,y,z,w), opacities 48, SH0 144) and component GaussianSplats level 1.  Browser support depends on "
         "the X_ITE version.",
         chk("component", name="GaussianSplats", level=1),
         chk("xpath", path=".//GaussianSplats", n={"eq": 1}),
         chk("count_floats", path=".//GaussianSplats", attr="positions", count=n * 3),
         chk("count_floats", path=".//GaussianSplats", attr="scales", count=n * 3),
         chk("count_floats", path=".//GaussianSplats", attr="orientations", count=n * 4),
         chk("count_floats", path=".//GaussianSplats", attr="opacities", count=n),
         chk("count_floats", path=".//GaussianSplats", attr="sphericalHarmonicsDegree0Coef0", count=n * 3),
         chk("xf", obj="Z16_splats"), profile="x41")
    case("splat.quaternion", "CORE", "Splat orientation order is (x, y, z, w)",
         "Blender stores (w,x,y,z); X3D carries (x,y,z,w).  Splat 1 (angle 4pi/47) must therefore read '0 0 sin(a/2) cos(a/2)' with the sine in the THIRD slot.",
         chk("splat_orientation", index=1, expected=[0.0, 0.0, math.sin((1 / (n - 1)) * 4 * math.pi / 2), math.cos((1 / (n - 1)) * 4 * math.pi / 2)],
             tol=1e-5), profile="x41")
    # Inline
    ie = ctx.new_obj("Z16_inline", None, loc=ctx.at(2.5, 0.0, 1.0), rot=(0.0, 0.0, math.radians(45)))
    ie["x3d_inline_url"] = "reference/inline_target.x3d"
    update()
    EXTRA_OBJECTS["Z16_inline"] = {"world": mat16(GLOBAL_MATRIX @ ie.matrix_world @ GLOBAL_MATRIX.inverted())}
    case("inline", "CORE", "Empty with x3d_inline_url -> Inline node",
         "<Inline DEF='IN_Z16_inline' url='\"reference/inline_target.x3d\"'> inside a Transform whose matrix is G x M x G^-1 (the extra "
         "rotation keeps a Y-up asset upright).  Browser (served over http): a small magenta box with a white stripe appears.",
         chk("xpath", path=".//Transform[@DEF='OB_Z16_inline']/Inline", n={"eq": 1}),
         chk("attr", path=".//Inline", attr="url", contains="reference/inline_target.x3d"),
         chk("xf", obj="Z16_inline"))


# --------------------------------------------------------------------------------------
def _ramp(nt, stops):
    r = nt.nodes.new("ShaderNodeValToRGB")
    cr = r.color_ramp
    while len(cr.elements) > 1:
        cr.elements.remove(cr.elements[-1])
    cr.elements[0].position, cr.elements[0].color = stops[0]
    for pos, col in stops[1:]:
        e = cr.elements.new(pos); e.color = col
    return r


@zone("Z17", "shader_lab", "Procedural / scalar-field materials: the GLSL ComposedShader roadmap")
def zone_shader_lab(ctx):
    viridis = [(0.0, (0.267, 0.005, 0.329, 1)), (0.25, (0.231, 0.322, 0.546, 1)), (0.5, (0.128, 0.567, 0.551, 1)),
               (0.75, (0.369, 0.789, 0.383, 1)), (1.0, (0.993, 0.906, 0.144, 1))]

    def mk(name, build):
        m = new_pbr(name, (0.8, 0.8, 0.8), 0.0, 0.5)
        nt = m.node_tree
        b = bsdf_of(m)
        build(nt, b)
        return m

    def b_noise(nt, b):
        n = nt.nodes.new("ShaderNodeTexNoise"); n.inputs["Scale"].default_value = 6.0
        r = _ramp(nt, viridis)
        nt.links.new(n.outputs["Fac"], r.inputs["Fac"]); nt.links.new(r.outputs["Color"], b.inputs["Base Color"])

    def b_wave(nt, b):
        w = nt.nodes.new("ShaderNodeTexWave"); w.inputs["Scale"].default_value = 5.0
        r = _ramp(nt, [(0.0, (0.05, 0.05, 0.4, 1)), (1.0, (1.0, 0.9, 0.3, 1))])
        nt.links.new(w.outputs["Fac"], r.inputs["Fac"]); nt.links.new(r.outputs["Color"], b.inputs["Base Color"])

    def b_checker(nt, b):
        c = nt.nodes.new("ShaderNodeTexChecker"); c.inputs["Scale"].default_value = 6.0
        c.inputs["Color1"].default_value = (0.9, 0.9, 0.9, 1); c.inputs["Color2"].default_value = (0.1, 0.1, 0.3, 1)
        nt.links.new(c.outputs["Color"], b.inputs["Base Color"])

    def b_voronoi(nt, b):
        v = nt.nodes.new("ShaderNodeTexVoronoi"); v.inputs["Scale"].default_value = 4.0
        nt.links.new(v.outputs["Color"], b.inputs["Base Color"])

    def b_scalar_height(nt, b):      # temperature-like field: colour = colormap(z)
        tc = nt.nodes.new("ShaderNodeTexCoord"); sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        mr = nt.nodes.new("ShaderNodeMapRange"); mr.inputs["From Min"].default_value = -1.0; mr.inputs["From Max"].default_value = 1.0
        r = _ramp(nt, viridis)
        nt.links.new(tc.outputs["Object"], sep.inputs["Vector"]); nt.links.new(sep.outputs["Z"], mr.inputs["Value"])
        nt.links.new(mr.outputs["Result"], r.inputs["Fac"]); nt.links.new(r.outputs["Color"], b.inputs["Base Color"])

    def b_fresnel(nt, b):
        lw = nt.nodes.new("ShaderNodeLayerWeight"); lw.inputs["Blend"].default_value = 0.4
        r = _ramp(nt, [(0.0, (0.1, 0.1, 0.1, 1)), (1.0, (0.2, 0.8, 1.0, 1))])
        nt.links.new(lw.outputs["Fresnel"], r.inputs["Fac"]); nt.links.new(r.outputs["Color"], b.inputs["Base Color"])

    specs = [("noise_viridis", b_noise), ("wave_stripes", b_wave), ("checker3d", b_checker), ("voronoi", b_voronoi),
             ("scalar_height", b_scalar_height), ("fresnel_rim", b_fresnel)]
    checks_shader, checks_fallback = [], []
    for i, (key, fn) in enumerate(specs):
        m = mk(f"T_proc_{key}", fn)
        _sphere(ctx, f"Z17_{key}", m, (-3.75 + i * 1.5, -1.5, 0.7), r=0.6, u=32, v=16)
        checks_shader.append(chk("xpath", path=f".//Transform[@DEF='OB_Z17_{key}']//ComposedShader", n={"min": 1}))
        checks_fallback.append(chk("mat", obj=f"Z17_{key}", attrs={}, absent=["emissiveColor"], present=["baseColor", "metallic", "roughness"]))
    case("glsl.composedshader", "ROADMAP", "Procedural materials -> <ComposedShader> (GLSL)",
         "Noise/Wave/Checker/Voronoi/ColorRamp/Map Range node networks have no PBR-parameter equivalent.  The planned shader subsystem "
         "(docs/SHADER_NL_IMPLEMENTATION_SPEC.md in the exporter repo) is meant to emit ComposedShader + ShaderPart (GLSL ES 3.00 for X_ITE).  "
         "At repository HEAD only the legacy X3D 3.3/H3D writer emits shaders, so the 4.0 path gives MISSING.  This case flips to NEW when it lands.  "
         "Target output: reference/glsl_golden.x3d (hand-written, compiles in X_ITE 16.5.1 with no console messages; check it with "
         "x3d_browser_check.py --file reference/glsl_golden.x3d --zones Z17): a <ComposedShader language='GLSL'> with a VERTEX and a FRAGMENT <ShaderPart> "
         "(GLSL ES 3.00, data: URI), user parameters as <field>s, and a ROUTE-driven uniform.  Browser: viridis-banded sphere, cyan rim-lit sphere, 3D checker sphere.",
         *checks_shader)
    case("proc.fallback", "FIDELITY", "Procedural material at least exports a complete PBR fallback",
         "When shaders are not generated the PhysicalMaterial should still be a sensible, fully specified fallback "
         "(baseColor, metallic, roughness all written).  Only baseColor is guaranteed here; the validator also reports what colour was chosen.",
         *checks_fallback)
    case("glsl.bake", "ROADMAP", "Baked-texture fallback for procedural materials",
         "Alternative to GLSL: bake the node network to a PNG (Cycles bake) and reference it as baseTexture, so every X3D browser shows the pattern.",
         chk("tex", obj="Z17_noise_viridis", field="baseTexture", exists=True))


# --------------------------------------------------------------------------------------
@zone("Z18", "stress", "Scale: thousands of instances and an 80k-face mesh (only with --stress)")
def zone_stress(ctx):
    if not CFG["stress"]:
        raise _SkipZone("pass --stress to build this zone")
    m = prim_mesh("cube", "Z18_cube_mesh", size=0.2); m.materials.append(clay())
    n = 0
    for ix in range(20):
        for iy in range(20):
            for iz in range(5):
                o = ctx.new_obj(f"Z18_i{ix:02d}_{iy:02d}_{iz}", m, loc=ctx.at(-5 + ix * 0.5, -5 + iy * 0.5, 0.2 + iz * 0.4))
                n += 1
    big = prim_mesh("icosphere", "Z18_big_mesh", sub=6, radius=1.0, smooth=True)
    bo = add_mesh_obj(ctx, "Z18_big", big, loc=(0, 0, 3.0))
    update()
    case("instances", "CORE", f"{n} instances of one mesh stay compact",
         f"One IndexedFaceSet DEF and {n - 1} USE references; export time stays reasonable.",
         chk("xpath", path=".//IndexedFaceSet[@DEF='ME_Z18_cube_mesh']", n={"eq": 1}),
         chk("xpath", path=".//IndexedFaceSet[@USE='ME_Z18_cube_mesh']", n={"eq": n - 1}))
    f = mesh_facts(bo)
    case("bigmesh", "CORE", f"{f['faces']}-face mesh",
         "A single large IndexedFaceSet exports with all faces.", chk("mesh", facts={"obj": "Z18_big", "faces": f["faces"], "positions": f["positions"]}))


class _SkipZone(Exception):
    pass


# --------------------------------------------------------------------------------------
# Golden reference: what a GLSL-capable X3D 4.0 export of the Z17 materials should look like in X_ITE.
# Hand-written (NOT produced by the exporter, which has no 4.0 shader path at the calibrated revision) and
# verified to compile and animate in X_ITE 16.5.1 by x3d_browser_check.py:
#     python3 x3d_browser_check.py out --file reference/glsl_golden.x3d --zones Z17
# It fixes the contract the roadmap cases check for: <ComposedShader language="GLSL"> + two <ShaderPart>s, GLSL ES 3.00,
# X_ITE's built-in x3d_* attributes/uniforms, user parameters as <field>s that can be ROUTEd to (here: an animated phase).
# --------------------------------------------------------------------------------------
GLSL_VERTEX = """#version 300 es
precision highp float;
uniform mat4 x3d_ProjectionMatrix;
uniform mat4 x3d_ModelViewMatrix;
uniform mat3 x3d_NormalMatrix;
in vec4 x3d_Vertex;
in vec3 x3d_Normal;
out vec3 vObj;     // object-space position: the 'Object' output of Blender's Texture Coordinate node
out vec3 vN;
out vec3 vView;
void main() {
  vObj = x3d_Vertex.xyz;
  vN = normalize(x3d_NormalMatrix * x3d_Normal);
  vec4 p = x3d_ModelViewMatrix * x3d_Vertex;
  vView = -p.xyz;
  gl_Position = x3d_ProjectionMatrix * p;
}"""

GLSL_COMMON = """#version 300 es
precision highp float;
uniform float phase;
uniform float vmin;
uniform float vmax;
in vec3 vObj;
in vec3 vN;
in vec3 vView;
out vec4 fragColor;
// Blender ColorRamp (5 stops, linear) -> piecewise mix(); the stops are exactly the ones typed into the Z17 ramp.
vec3 viridis(float t) {
  t = clamp(t, 0.0, 1.0);
  const vec3 c0 = vec3(0.267, 0.005, 0.329), c1 = vec3(0.231, 0.322, 0.546), c2 = vec3(0.128, 0.567, 0.551),
             c3 = vec3(0.369, 0.789, 0.383), c4 = vec3(0.993, 0.906, 0.144);
  if (t < 0.25) return mix(c0, c1, t / 0.25);
  if (t < 0.50) return mix(c1, c2, (t - 0.25) / 0.25);
  if (t < 0.75) return mix(c2, c3, (t - 0.50) / 0.25);
  return mix(c3, c4, (t - 0.75) / 0.25);
}
float lambert(vec3 n) { return 0.35 + 0.65 * max(dot(normalize(n), normalize(vec3(0.4, 0.6, 0.7))), 0.0); }
"""

GLSL_FRAG_SCALAR = GLSL_COMMON + """void main() {
  // scalar field = height (Map Range From Min/Max -> 0..1) + a travelling wave whose phase is driven by a ROUTE
  float s = (vObj.z - vmin) / (vmax - vmin) + 0.12 * sin(9.0 * vObj.x + phase);
  fragColor = vec4(viridis(s) * lambert(vN), 1.0);
}"""

GLSL_FRAG_FRESNEL = GLSL_COMMON + """uniform float blend;      // Layer Weight 'Blend': 0 = thin grazing rim, towards 1 = wide rim
uniform vec3 baseColor;
uniform vec3 rimColor;
// Exact unpolarised dielectric Fresnel - the formula behind Blender's Fresnel and Layer Weight nodes (fresnel_dielectric_cos).
float fresnelDielectric(float cosi, float eta) {
  float c = abs(cosi);
  float g = eta * eta - 1.0 + c * c;
  if (g <= 0.0) return 1.0;                 // total internal reflection
  g = sqrt(g);
  float A = (g - c) / (g + c);
  float B = (c * (g + c) - 1.0) / (c * (g - c) + 1.0);
  return 0.5 * A * A * (1.0 + B * B);
}
void main() {
  vec3 N = normalize(vN), V = normalize(vView);
  // 1st enhancement: Layer Weight semantics - eta = max(1 - blend, 1e-5), front faces use 1/eta
  float F = fresnelDielectric(dot(N, V), 1.0 / max(1.0 - blend, 1e-5));
  // 2nd enhancement: the same F weights a studio-gradient reflection and a Blinn-Phong highlight,
  // so the ball reads as glossy and grazing angles brighten like a real dielectric (view-space up = +y).
  vec3 R = reflect(-V, N);
  vec3 env = mix(vec3(0.05, 0.06, 0.08), vec3(0.55, 0.75, 0.95), smoothstep(-0.3, 0.8, R.y));
  float spec = pow(max(dot(N, normalize(normalize(vec3(0.4, 0.6, 0.7)) + V)), 0.0), 96.0);
  vec3 col = mix(baseColor * lambert(N), rimColor, F) + 0.6 * F * env + spec * (0.25 + 0.75 * F);
  fragColor = vec4(col, 1.0);
}"""

GLSL_FRAG_CHECKER = GLSL_COMMON + """void main() {
  // Checker Texture 3D, scale 6 on object coordinates
  vec3 q = floor(vObj * 6.0 + 1000.0);
  float c = mod(q.x + q.y + q.z, 2.0);
  fragColor = vec4(mix(vec3(0.9), vec3(0.1, 0.1, 0.3), c) * lambert(vN), 1.0);
}"""


FIELDS_BASIC = '''            <field name="phase" type="SFFloat" accessType="inputOutput" value="0" />
            <field name="vmin" type="SFFloat" accessType="inputOutput" value="-0.6" />
            <field name="vmax" type="SFFloat" accessType="inputOutput" value="0.6" />
'''
FIELDS_FRESNEL = '''            <field name="blend" type="SFFloat" accessType="inputOutput" value="0.4" />
            <field name="baseColor" type="SFColor" accessType="inputOutput" value="0.1 0.1 0.1" />
            <field name="rimColor" type="SFColor" accessType="inputOutput" value="0.2 0.8 1" />
'''


def _golden_shader(name, frag, x, fields=FIELDS_BASIC):
    return f"""    <Transform DEF="OB_Z17_{name}" translation="{x} 0.7 0">
      <Shape>
        <Appearance>
          <ComposedShader DEF="SH_{name}" language="GLSL">
{fields}            <ShaderPart type="VERTEX"><![CDATA[data:x-shader/x-vertex,{GLSL_VERTEX}]]></ShaderPart>
            <ShaderPart type="FRAGMENT"><![CDATA[data:x-shader/x-fragment,{frag}]]></ShaderPart>
          </ComposedShader>
        </Appearance>
        <Sphere radius="0.6" />
      </Shape>
    </Transform>
"""


def glsl_golden_x3d() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D version="4.0" profile="Immersive" xmlns:xsd="http://www.w3.org/2001/XMLSchema-instance" xsd:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="Shaders" level="1" />
    <meta name="title" content="GLSL golden reference for the Z17 shader_lab zone" />
    <meta name="description" content="Hand-written target output: three Blender procedural materials as ComposedShader (GLSL ES 3.00)." />
  </head>
  <Scene>
    <NavigationInfo type='"EXAMINE" "ANY"' headlight="false" />
    <Background skyColor="0.05 0.1 0.2" />
    <Viewpoint DEF="CA_CAM_Z17" description="CAM_Z17" position="0 1.2 5.2" orientation="1 0 0 -0.12" fieldOfView="0.75" />
    <TimeSensor DEF="Clock" cycleInterval="4" loop="true" />
    <ScalarInterpolator DEF="PhaseRamp" key="0 1" keyValue="0 6.2831853" />
    <ScalarInterpolator DEF="BlendBreath" key="0 0.5 1" keyValue="0.1 0.7 0.1" />
{_golden_shader("scalar_height", GLSL_FRAG_SCALAR, "-1.6")}{_golden_shader("fresnel_rim", GLSL_FRAG_FRESNEL, "0", FIELDS_FRESNEL)}{_golden_shader("checker3d", GLSL_FRAG_CHECKER, "1.6")}    <!-- ROUTEs come AFTER the nodes they name (X3D XML parsers resolve DEF names in document order) -->
    <ROUTE fromNode="Clock" fromField="fraction_changed" toNode="PhaseRamp" toField="set_fraction" />
    <ROUTE fromNode="PhaseRamp" fromField="value_changed" toNode="SH_scalar_height" toField="phase" />
    <ROUTE fromNode="Clock" fromField="fraction_changed" toNode="BlendBreath" toField="set_fraction" />
    <ROUTE fromNode="BlendBreath" fromField="value_changed" toNode="SH_fresnel_rim" toField="blend" />
  </Scene>
</X3D>
"""


# ======================================================================================
# DRIVER
# ======================================================================================

INLINE_TARGET = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D version="4.0" profile="Immersive">
  <head><meta name="title" content="Inline target for the X3D exporter test suite" /></head>
  <Scene>
    <Shape>
      <Appearance><PhysicalMaterial baseColor="0.9 0.1 0.8" metallic="0" roughness="0.5" /></Appearance>
      <Box size="1 1 1" />
    </Shape>
    <Transform translation="0 0.52 0">
      <Shape>
        <Appearance><PhysicalMaterial baseColor="1 1 1" metallic="0" roughness="0.5" /></Appearance>
        <Box size="1 0.04 0.2" />
      </Shape>
    </Transform>
  </Scene>
</X3D>
"""


def purge_previous():
    old = bpy.data.scenes.get(SCENE_NAME)
    if old is not None:
        for o in list(old.objects):
            bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.scenes.remove(old)
    for col in list(bpy.data.collections):
        if col.name.startswith("Z") and col.name[1:3].isdigit():
            bpy.data.collections.remove(col)
    try:
        bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    except Exception:
        pass


def exporter_available() -> bool:
    return hasattr(bpy.types, "EXPORT_SCENE_OT_x3d")


def register_repo(repo: str):
    """Register <repo>/source as the add-on package `io_scene_x3d` (the way the repo's own tests do)."""
    import importlib
    import tempfile
    src = os.path.join(os.path.abspath(repo), "source")
    if not os.path.isdir(src):
        raise SystemExit(f"--repo: {src} not found")
    tmp = tempfile.mkdtemp(prefix="x3d_repo_")
    link = os.path.join(tmp, "io_scene_x3d")
    try:
        os.symlink(src, link, target_is_directory=True)
    except OSError:
        import shutil
        shutil.copytree(src, link)
    sys.path.insert(0, tmp)
    mod = importlib.import_module("io_scene_x3d")
    try:
        mod.register()
    except Exception as exc:
        log(f"register(): {exc!r} (already registered?)")
    return mod


def make_floor(ctx, zid):
    m = prim_mesh("grid", f"{zid}_floor_mesh", x=1, y=1, size=5.0)
    mat = bpy.data.materials.get("T_floor") or new_pbr("T_floor", (0.10, 0.11, 0.13), 0.0, 0.95)
    m.materials.append(mat)
    ctx.new_obj(f"{zid}_floor", m, loc=ctx.at(0, 0, -0.05))


def make_label(ctx, zid, name):
    cu = bpy.data.curves.new(f"{zid}_label_data", "FONT")
    cu.body = f"{zid}  {name}"
    cu.size = 0.55
    cu.extrude = 0.01
    o = ctx.new_obj(f"{zid}_label", cu, loc=ctx.at(-4.8, -4.7, 0.0))
    o.data.materials.append(bpy.data.materials.get("T_label") or new_pbr("T_label", (0.9, 0.9, 0.95), 0.0, 0.5))


def make_tour_camera(ctx, zid):
    data = bpy.data.cameras.new(f"CAM_{zid}_data")
    data.angle = TOUR_ANGLE
    loc = ctx.at(0.0, -11.0, 10.0)          # high and far enough that the whole 10 x 10 m zone floor is inside a 16:9 frame
    o = ctx.new_obj(f"CAM_{zid}", data, loc=loc)
    o.rotation_euler = _track_rot(Vector(loc), Vector(ctx.at(0, 0.6, 0.4)))
    return o


def run_exports(out: str, only=None) -> dict:
    results = {}
    if not exporter_available():
        log("No export_scene.x3d operator registered: skipping --export")
        return results
    for key, prof in PROFILES.items():
        if only and key not in only:
            continue
        path = os.path.join(out, prof["file"])
        t0 = time.time()
        try:
            res = bpy.ops.export_scene.x3d(filepath=path, **prof["export"])
            results[key] = {"result": sorted(res), "seconds": round(time.time() - t0, 2), "bytes": os.path.getsize(path)}
        except Exception as exc:
            results[key] = {"result": "EXCEPTION", "error": repr(exc)}
            log(f"export {key} failed: {exc!r}")
            traceback.print_exc()
    return results


def build_all():
    out = out_dir()
    if CFG["repo"]:
        register_repo(CFG["repo"])
    purge_previous()
    scene = bpy.data.scenes.new(SCENE_NAME)
    scene.frame_start, scene.frame_end, scene.frame_current = FRAME_START, FRAME_END, FRAME_START
    scene.render.fps, scene.render.fps_base = FPS, 1.0
    scene.render.resolution_x, scene.render.resolution_y, scene.render.pixel_aspect_x = 1280, 720, 1.0
    scene.render.pixel_aspect_y = 1.0
    world = bpy.data.worlds.new("T_world")
    _use_nodes_world(world)
    scene.world = world
    activate_scene(scene)

    ctx = Ctx(scene)
    ctx.out = out
    ctx.textures = build_textures(os.path.join(out, "textures_src"))

    for lamp, loc, rot, energy in (("T_key_sun", (6, -8, 10), (math.radians(50), 0, math.radians(25)), 0.9),
                                   ("T_fill_sun", (-6, 8, 10), (math.radians(60), 0, math.radians(200)), 0.35)):
        d = bpy.data.lights.new(lamp, "SUN"); d.energy = energy
        o = bpy.data.objects.new(lamp, d); scene.collection.objects.link(o); o.location = loc; o.rotation_euler = rot
    selected = CFG["zones"]
    for zid, name, title, func in sorted(_ZONE_FUNCS, key=lambda z: z[0]):
        if selected and not (zid.lower() in selected or name.lower() in selected):
            continue
        idx = int(zid[1:])
        coll = bpy.data.collections.new(f"{zid}_{name}")
        scene.collection.children.link(coll)
        ctx.collection, ctx.zone_id = coll, zid
        ctx.zone_center = Vector(((idx % ZONE_COLS) * ZONE_PITCH, -(idx // ZONE_COLS) * ZONE_PITCH, 0.0))
        _CUR["zone"] = zid
        make_floor(ctx, zid)
        if CFG["labels"]:
            make_label(ctx, zid, name)
        make_tour_camera(ctx, zid)
        before = len(CASES)
        status = "ok"
        try:
            func(ctx)
        except _SkipZone as exc:
            status = f"skipped: {exc}"
            SKIPPED_ZONES.append({"zone": zid, "reason": str(exc)})
        except Exception as exc:
            status = f"ERROR: {exc!r}"
            SKIPPED_ZONES.append({"zone": zid, "reason": repr(exc)})
            traceback.print_exc()
        ZONES[zid] = {"id": zid, "name": name, "title": title, "center": list(ctx.zone_center), "status": status,
                      "cases": len(CASES) - before}
        log(f"{zid} {name:<11} {status:<9} cases={len(CASES) - before}")
        # keep the evaluated state stable between zones
        scene.frame_set(FRAME_START)
    scene.frame_set(FRAME_START)
    update()

    # tour viewpoints: one per zone camera
    _CUR["zone"] = "Z12"
    tour = [chk("view", obj=f"CAM_{zid}", attrs={"fieldOfView": x3d_fov_expected(TOUR_ANGLE, "AUTO", 1280, 720)}, tol=1e-4,
                description=f"CAM_{zid}") for zid in ZONES]
    if tour:
        case("tour", "CORE", "One tour Viewpoint per zone",
             "Every zone has a camera 'CAM_Zxx' that frames it from the front and above; each becomes a <Viewpoint> with description = camera name and "
             f"fieldOfView {x3d_fov_expected(TOUR_ANGLE, 'AUTO', 1280, 720):.3f} (X3D measures the SMALLER display side: a {math.degrees(TOUR_ANGLE):.0f} deg horizontal lens on a 16:9 render).  In X_ITE use the viewpoint menu (or the browser_check script) to hop "
             "from zone to zone.", *tour)

    objects = {}
    for o in scene.objects:
        objects[o.name] = {"type": o.type, "parent": o.parent.name if o.parent else None, "data": o.data.name if o.data else None,
                           "world": mat16(GLOBAL_MATRIX @ o.matrix_world)}
        objects[o.name].update(EXTRA_OBJECTS.get(o.name, {}))

    manifest = {
        "schema": 1, "suite_version": SUITE_VERSION, "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "blender": bpy.app.version_string,
        "frame": {"start": FRAME_START, "end": FRAME_END, "fps": FPS, "current": scene.frame_current},
        "global_matrix": mat16(GLOBAL_MATRIX),
        "profiles": PROFILES, "zones": list(ZONES.values()), "skipped_zones": SKIPPED_ZONES,
        "objects": objects, "cases": CASES, "build_log": BUILD_LOG,
        "exporter_available": exporter_available(),
    }
    with open(os.path.join(out, "x3d_suite_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1, default=str)
    os.makedirs(os.path.join(out, "reference"), exist_ok=True)
    with open(os.path.join(out, "reference", "inline_target.x3d"), "w", encoding="utf-8") as fh:
        fh.write(INLINE_TARGET)
    with open(os.path.join(out, "reference", "glsl_golden.x3d"), "w", encoding="utf-8") as fh:
        fh.write(glsl_golden_x3d())
    n_core = sum(1 for c in CASES if c["tier"] == "CORE")
    log(f"{len(CASES)} cases ({n_core} CORE, {sum(1 for c in CASES if c['tier'] == 'FIDELITY')} FIDELITY, "
        f"{sum(1 for c in CASES if c['tier'] == 'ROADMAP')} ROADMAP) in {len(ZONES)} zones -> {out}")
    if CFG["export"]:
        manifest["export_results"] = run_exports(out)
        with open(os.path.join(out, "x3d_suite_manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=1, default=str)
        log("exports: " + json.dumps(manifest["export_results"]))
    print_instructions(out)
    return manifest


def _use_nodes_world(world):
    try:
        world.use_nodes = True
    except Exception:
        pass
    bg = world.node_tree.nodes.get("Background") if world.node_tree else None
    if bg is not None:
        bg.inputs["Color"].default_value = (0.10, 0.20, 0.40, 1.0)
        bg.inputs["Strength"].default_value = 0.5
    world.color = (0.9, 0.1, 0.1)         # decoy: the exporter should prefer the node tree


def print_instructions(out):
    print("\n" + "=" * 78)
    print("X3D TEST SUITE READY")
    print(f"  scene     : {SCENE_NAME}  ({len(ZONES)} zones, {len(CASES)} cases)")
    print(f"  output dir: {out}")
    print("  Export with File > Export > X3D (Selection Only OFF!) using, for the primary run:")
    for k, v in PROFILES["main"]["export"].items():
        print(f"      {k} = {v}")
    print(f"  save as   : {os.path.join(out, PROFILES['main']['file'])}")
    print("  then run  : python validate_x3d_export.py " + out)
    print("=" * 78 + "\n")


if __name__ == "__main__":
    if CFG["list"]:
        for zid, name, title, _ in sorted(_ZONE_FUNCS, key=lambda z: z[0]):
            print(f"{zid}  {name:<11} {title}")
    else:
        build_all()
