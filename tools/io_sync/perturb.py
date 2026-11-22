# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Perturbation sweep: which Blender properties change the X3D 4.0 export when they change? (runs in Blender's Python)

    python tools/io_sync/perturb.py --out OUT.json [--source DIR] [--check] [--mapping FILE] [--states a,b]
    blender -b --factory-startup --python tools/io_sync/perturb.py -- --out OUT.json --check

A silent loss is a property the exporter never reads, so a scan of what the code reads cannot find it. This sweep
changes one property at a time on a probe scene, exports X3D 4.0 and compares the file with the unchanged export
(every <meta> removed, so the receipt line and the run's date do not count). A property whose change leaves the file
byte-identical is *inert* in that starting state; one that changes it is *carried*. The probe is rebuilt from factory
settings for each starting state (``STATES``), because one state hides properties masked by another setting
(Emission Color does nothing while Emission Strength is 0; light energy does nothing above the 1.75 W cap).

With ``--check`` the result is judged against the Blender half of the mapping table (source/mapping/blender_rna.json,
schema x3d-blender-io.mapping-blender/1). The run exits 1 when:

  - a property has no row (exact or pattern): an undeclared property is a loss nobody has looked at;
  - a row says carried, approximated or clamped but the property was inert in every state: the exporter stopped
    reading it (this is the silent-loss oracle; tests/test_perturb_gate.py plants such a fault);
  - a row says dropped or editor_only but the property changed the file: the row is stale;
  - the loss receipt of a perturbed export disagrees with the row: a dropped or clamped value the sweep set is not
    in the receipt, or the receipt names a row the sweep saw carried (the receipt is checked against the sweep);
  - an export failed.

``--skeleton FILE`` writes a row for every undeclared property with a suggested class, for review.
Baseline (x3d.loom runs/blender-io-perturb-20261122, main 47ed742, bpy 5.3.0): 363 properties, 39 carried, 324 inert,
one starting state, nothing declared. With three states and the table (22 Nov 2026): bpy 5.3.0 379 properties, 54
carried; Blender 5.2.2 LTS 377 / 54; 5.1.2 374 / 54; 4.5.14 LTS 371 / 56; PASS on all four, 0 receipt disagreements.
"""
from __future__ import annotations

import argparse
import fnmatch
import importlib
import json
import os
import re
import sys
import tempfile
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)

REPO = Path(__file__).resolve().parents[2]
DEFAULT_MAPPING = REPO / "source" / "mapping" / "blender_rna.json"
SCHEMA = "x3d-blender-io.perturb/1"
LOST_CLASSES = {"dropped", "editor_only"}
KEPT_CLASSES = {"carried", "approximated", "clamped"}
ALL_CLASSES = LOST_CLASSES | KEPT_CLASSES
META = re.compile(r"<meta [^>]*/>\s*")


def parse_args(argv):
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    elif any(a.endswith(".py") for a in argv[:1]):
        argv = argv[1:]
    if "--python" in argv:   # blender -b --python golden.py with no "--": no arguments of ours
        argv = []
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out", required=True)
    p.add_argument("--source", default=str(REPO / "source"), help="add-on source folder to register as io_scene_x3d")
    p.add_argument("--mapping", default=str(DEFAULT_MAPPING))
    p.add_argument("--check", action="store_true", help="judge the sweep against the mapping table; exit 1 on a failure")
    p.add_argument("--states", default="", help="comma-separated subset of the starting states")
    p.add_argument("--skeleton", default="", help="write rows for undeclared properties here")
    p.add_argument("--no-receipt", action="store_true", help="do not ask for the receipt sidecar")
    return p.parse_args(argv)


def register_addon(source):
    tmp = tempfile.mkdtemp(prefix="perturb_addon_")
    (Path(tmp) / "io_scene_x3d").symlink_to(Path(source).resolve(), target_is_directory=True)
    sys.path.insert(0, tmp)
    import bpy  # noqa: F401

    addon = importlib.import_module("io_scene_x3d")
    try:
        addon.register()
    except ValueError:
        pass
    return addon


# ---------------------------------------------------------------- probe scene and starting states

def build(state):
    """The probe scene in one starting state: a cube with a Principled material, four lights, a camera, a world.

    Built with from_pydata, not the primitive operators, so two processes give the same mesh (R8 of the v3 plan)."""
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    verts = [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (0, 2)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    mesh = bpy.data.meshes.new("ProbeMesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    cube = bpy.data.objects.new("Probe", mesh)
    scene.collection.objects.link(cube)
    mat = bpy.data.materials.new("ProbeMat")
    mat.use_nodes = True
    mesh.materials.append(mat)
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    lights = {}
    for i, kind in enumerate(("POINT", "SUN", "SPOT", "AREA")):
        data = bpy.data.lights.new(kind.title(), kind)
        obj = bpy.data.objects.new(kind.title(), data)
        obj.location = (3 + i, -3, 4)
        scene.collection.objects.link(obj)
        lights[kind] = data
    cam_d = bpy.data.cameras.new("Cam")
    cam = bpy.data.objects.new("Cam", cam_d)
    cam.location = (6, -6, 4)
    scene.collection.objects.link(cam)
    scene.camera = cam
    world = bpy.data.worlds.new("World")
    scene.world = world
    if hasattr(world, "use_nodes"):
        try:
            world.use_nodes = True
        except Exception:
            pass
    background = None
    if world.node_tree is not None:
        background = next((n for n in world.node_tree.nodes if n.type == "BACKGROUND"), None)

    if state == "dim":
        # everything below its cap, emission on, quaternion rotation, orthographic camera
        for kind, energy in (("POINT", 1.0), ("SPOT", 1.0), ("SUN", 0.5), ("AREA", 1.0)):
            lights[kind].energy = energy
        lights["SPOT"].spot_blend = 0.5
        bsdf.inputs["Emission Strength"].default_value = 1.0
        bsdf.inputs["Emission Color"].default_value = (0.2, 0.3, 0.4, 1.0)
        bsdf.inputs["Coat Weight"].default_value = 0.5
        bsdf.inputs["Transmission Weight"].default_value = 0.3
        cube.rotation_mode = "QUATERNION"
        cam_d.type = "ORTHO"
        if background is not None:
            background.inputs["Strength"].default_value = 0.5
    elif state == "pano":
        # panoramic camera, axis-angle rotation, colour temperature on, a hidden object, no world nodes
        for kind in lights:
            lights[kind].energy = 0.8
            if hasattr(lights[kind], "use_temperature"):
                lights[kind].use_temperature = True
        cam_d.type = "PANO"
        cube.rotation_mode = "AXIS_ANGLE"
        cube.hide_render = True
        bsdf.inputs["Specular IOR Level"].default_value = 0.8
        bsdf.inputs["Base Color"].default_value = (0.9, 0.2, 0.1, 1.0)
        mat.diffuse_color = (0.3, 0.6, 0.2, 1.0)
        if hasattr(world, "use_nodes"):
            try:
                world.use_nodes = False
            except Exception:
                pass
        background = None
        world.color = (0.2, 0.25, 0.3)
    owners = [("object", cube), ("mesh", mesh), ("material", mat), ("camera", cam_d), ("world", world),
              ("light.point", lights["POINT"]), ("light.sun", lights["SUN"]), ("light.spot", lights["SPOT"]),
              ("light.area", lights["AREA"])]
    return dict(cube=cube, mesh=mesh, mat=mat, bsdf=bsdf, background=background, owners=owners)


STATES = {
    "factory": "Blender's defaults: 10 W point, spot and area lights, 1 W sun, Emission Strength 0, perspective camera",
    "dim": "lights below the intensity cap, emission on, coat and transmission on, quaternion rotation, "
           "orthographic camera, world Background strength 0.5",
    "pano": "panoramic camera, axis-angle rotation, colour temperature on, object hidden in renders, world nodes off",
}


# ---------------------------------------------------------------- perturbations

def perturb_value(v, prop=None):
    if isinstance(v, bool):
        return not v
    if isinstance(v, int):
        hi = getattr(prop, "hard_max", None)
        return v + 1 if hi is None or v + 1 <= hi else v - 1
    if isinstance(v, float):
        lo, hi = (prop.hard_min, prop.hard_max) if prop is not None and hasattr(prop, "hard_min") else (-1e30, 1e30)
        cand = v * 0.5 + 0.37
        if abs(cand - v) < 1e-6:
            cand = v + 0.21
        cand = max(lo, min(hi, cand))
        if abs(cand - v) < 1e-9:
            cand = max(lo, min(hi, v - 0.21))
        return cand
    return None


def rna_targets(owner):
    for prop in owner.bl_rna.properties:
        pid = prop.identifier
        if pid in ("rna_type", "name") or prop.is_readonly:
            continue
        if prop.type not in ("BOOLEAN", "INT", "FLOAT", "ENUM"):
            continue
        yield pid, prop


def try_rna(owner, pid, prop):
    """Set one RNA property to a different value; return (undo, new value) or None when it has no scalar change."""
    old = getattr(owner, pid)
    if prop.type == "ENUM":
        if prop.is_enum_flag:
            return None
        ids = [e.identifier for e in prop.enum_items]
        if len(ids) < 2 or old not in ids:
            return None
        new = ids[(ids.index(old) + 1) % len(ids)]
        setattr(owner, pid, new)
        return (lambda: setattr(owner, pid, old)), new
    if getattr(prop, "is_array", False) or getattr(prop, "array_length", 0):
        if hasattr(old[0], "__len__"):
            return None
        vals = list(old)
        new = list(vals)
        # a quaternion (w, x, y, z) with only w changed is the same rotation once normalised: change x instead
        index = 1 if "quaternion" in pid and len(vals) == 4 else 0
        new[index] = perturb_value(vals[index], prop)
        if new[index] is None:
            return None
        setattr(owner, pid, new)
        return (lambda: setattr(owner, pid, vals)), new
    new = perturb_value(old, prop)
    if new is None:
        return None
    setattr(owner, pid, new)
    return (lambda: setattr(owner, pid, old)), new


def rna_default(owner, pid, prop):
    if prop.type == "ENUM":
        return prop.default if not prop.is_enum_flag else None
    if getattr(prop, "is_array", False) or getattr(prop, "array_length", 0):
        try:
            return [float(v) if prop.type == "FLOAT" else v for v in prop.default_array]
        except Exception:
            return None
    return prop.default


def socket_value(sock):
    v = sock.default_value
    return v if isinstance(v, (bool, int, float)) else [float(x) for x in v]


SOCKET_OPEN_RANGE = {"IOR", "Emission Strength", "Thin Film Thickness", "Thin Film IOR", "Coat IOR", "Subsurface Scale",
                     "Strength"}


def try_socket(sock):
    old = sock.default_value
    if isinstance(old, (bool, int, float)):
        new = perturb_value(old)
        if isinstance(old, float):
            new = min(1.0, max(0.0, new)) if sock.name not in SOCKET_OPEN_RANGE else old + 0.6
            if abs(new - old) < 1e-9:
                new = 0.5 if old != 0.5 else 0.25
        sock.default_value = new
        return (lambda: setattr(sock, "default_value", old)), new
    vals = list(old)
    new = list(vals)
    new[0] = 0.5 if abs(vals[0] - 0.5) > 1e-6 else 0.25
    sock.default_value = new
    return (lambda: setattr(sock, "default_value", vals)), new


def extra_targets(probe):
    """Changes that are not one RNA scalar but that an artist makes all the time."""
    import bpy

    mesh = probe["mesh"]

    def smooth():
        mesh.shade_smooth()
        return (lambda: mesh.shade_flat()), True

    def uv_layer():
        layer = mesh.uv_layers.new(name="ProbeUV")
        for i, loop in enumerate(layer.data):
            loop.uv = ((i % 4) / 3.0, (i // 4) / 6.0)
        return (lambda: mesh.uv_layers.remove(mesh.uv_layers["ProbeUV"])), True

    def colour_attribute():
        attr = mesh.color_attributes.new("ProbeCol", "FLOAT_COLOR", "POINT")
        for i, item in enumerate(attr.data):
            item.color = (i / 8.0, 0.5, 1.0 - i / 8.0, 1.0)
        return (lambda: mesh.color_attributes.remove(mesh.color_attributes["ProbeCol"])), True

    def move_vertex():
        old = tuple(mesh.vertices[0].co)
        mesh.vertices[0].co = (old[0] - 0.25, old[1], old[2])
        mesh.update()

        def undo():
            mesh.vertices[0].co = old
            mesh.update()
        return undo, True

    def custom_property():
        probe["cube"]["probe_note"] = "kept?"
        return (lambda: probe["cube"].pop("probe_note")), "kept?"

    def second_material():
        extra = bpy.data.materials.new("ProbeMat2")
        mesh.materials.append(extra)
        mesh.polygons[0].material_index = 1

        def undo():
            mesh.polygons[0].material_index = 0
            mesh.materials.pop()
            bpy.data.materials.remove(extra)
        return undo, True

    return [("mesh.data", "shade_smooth", smooth), ("mesh.data", "uv_layer", uv_layer),
            ("mesh.data", "colour_attribute", colour_attribute), ("mesh.data", "vertex_position", move_vertex),
            ("mesh.data", "material_slot_2", second_material), ("object", "custom_property", custom_property)]


# ---------------------------------------------------------------- mapping rows

def version_tuple(text):
    return tuple(int(part) for part in re.findall(r"\d+", str(text))[:3])


def resolve_row(row, blender_version):
    """A row as it applies to this Blender version: ``before`` {"5.0": {...}} overrides fields on older versions."""
    out = {k: v for k, v in row.items() if k != "before"}
    for limit, override in sorted((row.get("before") or {}).items(), key=lambda kv: version_tuple(kv[0]), reverse=True):
        if blender_version and version_tuple(blender_version) < version_tuple(limit):
            out.update(override)
    return out


class Mapping:
    def __init__(self, path, blender_version=None):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {"rows": [], "patterns": []}
        self.rows = {row["id"]: resolve_row(row, blender_version) for row in self.data.get("rows", [])}
        self.patterns = list(self.data.get("patterns", []))

    def row(self, key):
        if key in self.rows:
            return self.rows[key]
        for pattern in self.patterns:
            if any(fnmatch.fnmatchcase(key, m) for m in pattern["match"]):
                return dict(pattern, id=key, via=pattern["match"])
        return None


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def rule_fires(rule, value, owner):
    """The sweep's own reading of a receipt rule (kept apart from source/receipt.py on purpose, so the two can disagree)."""
    if not rule:
        return False
    if rule.get("unless_custom") and owner is not None and owner.get(rule["unless_custom"]) is not None:
        return False
    when = rule.get("when")
    if when and owner is not None:
        current = getattr(owner, when["prop"], None)
        if "in" in when and current not in when["in"]:
            return False
    kind = rule.get("kind", "neq")
    if kind == "always":
        return True
    if kind == "gt":
        v = _num(value[0] if isinstance(value, (list, tuple)) else value)
        return v is not None and v > rule["value"] + 1e-9
    neutral = rule.get("neutral")
    if isinstance(value, (list, tuple)):
        if not isinstance(neutral, (list, tuple)):
            return True
        return any(abs(float(a) - float(b)) > 1e-6 for a, b in zip(value, neutral))
    if isinstance(value, float) or isinstance(neutral, float):
        a, b = _num(value), _num(neutral)
        return a is None or b is None or abs(a - b) > 1e-6
    return value != neutral


# ---------------------------------------------------------------- the sweep

def main(argv):
    args = parse_args(argv)
    t0 = time.time()
    register_addon(args.source)
    import bpy

    mapping = Mapping(args.mapping, bpy.app.version_string)
    states = [s for s in (args.states.split(",") if args.states else STATES) if s]
    work = tempfile.mkdtemp(prefix="perturb_out_")
    if not args.no_receipt:
        os.environ["BLENDER_X3D_RECEIPT"] = "1"
    exports = 0

    def export(name):
        nonlocal exports
        path = os.path.join(work, name)
        result = bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False)
        assert result == {"FINISHED"}, result
        exports += 1
        receipt = None
        sidecar = Path(path + ".receipt.json")
        if sidecar.exists():
            receipt = json.loads(sidecar.read_text())
            sidecar.unlink()
        return META.sub("", Path(path).read_text()), receipt

    rows = []
    for state in states:
        probe = build(state)
        base, _ = export("base.x3d")
        again, _ = export("base2.x3d")
        holder = {"base": base}

        def run(group, name, apply, owner=None, default=None):
            key = f"{group}:{name}"
            row = dict(state=state, group=group, prop=name, id=key)
            try:
                applied = apply()
            except Exception as exc:  # the property refuses the write in this state
                rows.append(dict(row, result="unsettable", why=str(exc)[:100]))
                return
            if applied is None:
                rows.append(dict(row, result="skipped"))
                return
            undo, new = applied
            if default is not None:
                row["default"] = default
            declared = mapping.row(key)
            if declared and declared.get("receipt") and declared["class"] in ("dropped", "clamped", "approximated"):
                # what the receipt must say, judged by the sweep while the value is set (owner state included)
                row["expect_entry"] = rule_fires(declared["receipt"], new, owner)
            try:
                text, receipt = export("p.x3d")
                row["result"] = "carried" if text != holder["base"] else "inert"
                row["value"] = new if isinstance(new, (bool, int, float, str)) else list(new)
                if receipt is not None:
                    row["receipt_rows"] = sorted({e["row"] for e in receipt.get("entries", [])
                                                  if owner is None or e.get("locus", {}).get("datablock") in (None, owner.name)})
                    row["receipt_owner"] = owner.name if owner is not None else None
                rows.append(row)
            except Exception as exc:
                rows.append(dict(row, result="export_error", why=str(exc)[:160]))
            finally:
                try:
                    undo()
                except Exception:
                    pass
                after, _ = export("u.x3d")
                if after != holder["base"]:
                    rows[-1]["undo_drift"] = True
                    holder["base"] = after

        for sock in probe["bsdf"].inputs:
            if not hasattr(sock, "default_value"):
                continue
            run("principled", sock.name, lambda sock=sock: try_socket(sock), owner=probe["mat"],
                default=socket_value(sock) if state == "factory" else None)
        if probe["background"] is not None:
            for sock in probe["background"].inputs:
                if hasattr(sock, "default_value"):
                    run("world.background", sock.name, lambda sock=sock: try_socket(sock), owner=None)
        for label, owner in probe["owners"]:
            for pid, prop in rna_targets(owner):
                run(label, pid, lambda owner=owner, pid=pid, prop=prop: try_rna(owner, pid, prop), owner=owner,
                    default=rna_default(owner, pid, prop))
        for group, name, apply in extra_targets(probe):
            run(group, name, apply, owner=None)
        rows.append(dict(state=state, group="_baseline", prop="deterministic", id="_baseline:deterministic",
                         result="ok" if base == again else "nondeterministic", bytes=len(base)))

    verdict = judge(rows, mapping, states) if args.check or args.skeleton else None
    summary = {}
    for r in rows:
        if r["group"].startswith("_"):
            continue
        summary.setdefault(r["group"], {}).setdefault(r["state"], {}).setdefault(r["result"], 0)
        summary[r["group"]][r["state"]][r["result"]] += 1
    props = aggregate(rows)
    totals = {"properties": len(props),
              "carried_in_any_state": sum(1 for p in props.values() if "carried" in p["results"].values()),
              "inert_in_every_state": sum(1 for p in props.values()
                                          if p["results"] and set(p["results"].values()) == {"inert"})}
    import io_scene_x3d

    out = dict(schema=SCHEMA, instruments=dict(blender=bpy.app.version_string, python=sys.version.split()[0],
                                               addon=".".join(map(str, io_scene_x3d.bl_info.get("version", ()))),
                                               mapping=str(Path(args.mapping).name),
                                               mapping_sha256=_sha(Path(args.mapping))),
               states={s: STATES[s] for s in states}, exports=exports, seconds=round(time.time() - t0, 1),
               totals=totals, summary=summary, verdict=verdict, properties=props, rows=rows)
    Path(args.out).write_text(json.dumps(out, indent=1, sort_keys=False, default=str))
    print(f"[perturb] Blender {bpy.app.version_string}: {totals['properties']} properties over {len(states)} state(s), "
          f"{totals['carried_in_any_state']} carried in at least one, {totals['inert_in_every_state']} inert in all; "
          f"{exports} exports in {out['seconds']} s")
    if args.skeleton and verdict is not None:
        Path(args.skeleton).write_text(json.dumps(verdict["skeleton"], indent=1))
        print(f"[perturb] {len(verdict['skeleton'])} skeleton row(s) written to {args.skeleton}")
    if verdict is not None:
        for kind in ("undeclared", "silent_loss", "stale_row", "receipt_disagrees", "export_error", "nondeterministic"):
            items = verdict[kind]
            print(f"[perturb] {kind}: {len(items)}")
            for item in items[:40]:
                print(f"    {item}")
        if args.check and verdict["failures"]:
            print(f"[perturb] FAIL: {verdict['failures']} failure(s)")
            return 1
        if args.check:
            print("[perturb] PASS: every property is declared and behaves as its row says")
    return 0


def _sha(path):
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def aggregate(rows):
    props = {}
    for r in rows:
        if r["group"].startswith("_"):
            continue
        p = props.setdefault(r["id"], {"group": r["group"], "prop": r["prop"], "results": {}})
        p["results"][r["state"]] = r["result"]
    return props


def judge(rows, mapping, states):
    verdict = {k: [] for k in ("undeclared", "silent_loss", "stale_row", "receipt_disagrees", "export_error",
                               "nondeterministic")}
    skeleton = []
    props = aggregate(rows)
    for key, p in sorted(props.items()):
        results = set(p["results"].values())
        if results <= {"skipped", "unsettable"}:
            continue
        row = mapping.row(key)
        carried = "carried" in results
        if row is None:
            verdict["undeclared"].append(f"{key}: {dict(p['results'])}")
            skeleton.append(dict(id=key, cls="carried" if carried else "?", observed=p["results"]))
            continue
        cls = row["class"]
        if cls not in ALL_CLASSES:
            verdict["undeclared"].append(f"{key}: class {cls!r} is not one of {sorted(ALL_CLASSES)}")
            continue
        if cls in KEPT_CLASSES and not carried and "inert" in results:
            verdict["silent_loss"].append(f"{key}: row says {cls} but inert in every state {dict(p['results'])}")
        if cls in LOST_CLASSES and carried:
            verdict["stale_row"].append(f"{key}: row says {cls} but it changed the file {dict(p['results'])}")
    for r in rows:
        if r.get("result") == "export_error":
            verdict["export_error"].append(f"{r['state']} {r['id']}: {r.get('why')}")
        if r.get("result") == "nondeterministic":
            verdict["nondeterministic"].append(f"{r['state']}: two exports of the unchanged probe differ")
        if "receipt_rows" not in r or r.get("result") not in ("carried", "inert"):
            continue
        row = mapping.row(r["id"])
        if row is None:
            continue
        named = r["id"] in r["receipt_rows"]
        if "expect_entry" in r:
            expected = r["expect_entry"]
            if expected != named:
                verdict["receipt_disagrees"].append(
                    f"{r['state']} {r['id']}={r.get('value')!r}: sweep expects {'an entry' if expected else 'no entry'}, "
                    f"receipt {'has one' if named else 'has none'}")
        if named and r["result"] == "carried" and row["class"] == "dropped":
            verdict["receipt_disagrees"].append(f"{r['state']} {r['id']}: receipt says dropped but the value changed the file")
    verdict["failures"] = sum(len(v) for v in verdict.values())
    verdict["skeleton"] = skeleton
    return verdict


if __name__ == "__main__":
    code = main(sys.argv)
    sys.stdout.flush()
    # bpy's atexit can hang on a wheel; leave now
    os._exit(code)
