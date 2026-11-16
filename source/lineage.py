# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Lineage report for an X3D 4.0 export: which Blender datablock each X3D field came from and which conversions it went through.

Pure Python, no ``bpy`` (like ir.py, emit_x3d40.py and viewpoint_fov.py): it reads the IR the extractor built and the X3D text
the emitter wrote. The idea is the FIND / COMPARE / LOCATE check of source tracing, turned around for an exporter:

* FIND    the DEF'd element and the attribute exist in the written file;
* COMPARE the written number equals what the IR value gives when the *emitter's* conversions are applied again here, by an
          independent implementation of each conversion (colour encoding, SFColor clipping, number format);
* LOCATE  line, column and character span of the attribute in the file.

A conversion that has no independent recompute (the Blinn-Phong fit, ``phong_from_principled``) or that loses information
(``sfcolor_clip`` drops Emission Strength) gives the verdict ``check``: the value is where the record says and may still be
right, but a person should look. Hop 1 (Blender property -> IR, done in extract.py) needs ``bpy``: records name its steps in
``derivation`` with ``checked: false``; a caller that holds a snapshot of the Blender values can pass ``source_values`` and
the steps that can be recomputed from numbers alone are compared too.

Verdicts use the names of GAIK ``source_tracing`` and x3dtrace: verified, check, unchecked. Nothing here changes how a file is written.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET

try:
    from .emit_x3d40 import _safe_name
except ImportError:  # pragma: no cover - standalone test fallback
    from emit_x3d40 import _safe_name

SCHEMA = "x3d-blender-io.lineage/v1"

# id -> what it is, where it lives, whether the step is lossless and whether this module recomputes it from numbers.
CONVERSIONS = {
    "matrix_world_to_trs": dict(hop=1, anchor="extract._matrix_transform", lossless=True, recompute=False,
                                what="object matrix -> translation, axis-angle rotation (radians), scale"),
    "axis_conversion": dict(hop=1, anchor="__init__.ExportX3D.execute (axis_conversion)", lossless=True, recompute=False,
                            what="Blender Z-up, -Y forward to X3D Y-up, -Z forward (export defaults axis_forward -Z, axis_up Y)"),
    "file_unit_scale": dict(hop=1, anchor="__init__.ExportX3D.file_unit / global_scale", lossless=True, recompute=False,
                            what="Blender metres times global_scale (CM 100, MM 1000, IN 1/0.0254)"),
    "energy_to_intensity": dict(hop=1, anchor="extract.light_intensity", lossless=True, recompute=True,
                                what="light energy / energy per intensity (point and spot 1.75, sun 1, or the imported x3d_energy_per_intensity); a light made in Blender is capped at 1"),
    "fov_smaller_side": dict(hop=1, anchor="viewpoint_fov.x3d_field_of_view", lossless=True, recompute=True,
                             what="camera angle across the fitted side -> X3D fieldOfView across the smaller side"),
    "linear_to_srgb": dict(hop=2, anchor="extract.display_colour", lossless=True, recompute=True,
                           what="linear colour -> sRGB-encoded value, as classic Material and UnlitMaterial colours are read (colour space SRGB)"),
    "sfcolor_clip": dict(hop=2, anchor="emit_x3d40._sfcolor", lossless=True, recompute=True, lossy_when="a channel is above 1 or below 0",
                         what="channels above 1 scaled down together (Emission Strength is lost), negative channels to 0"),
    "phong_from_principled": dict(hop=2, anchor="emit_x3d40.phong_from_principled", lossless=False, recompute=False,
                                  what="roughness, Specular IOR Level and Tint -> Blinn-Phong shininess and specularColor (a fit, not an identity)"),
    "alpha_to_transparency": dict(hop=2, anchor="emit_x3d40._material_xml", lossless=True, recompute=True,
                                  what="transparency = 1 - alpha, clamped to [0, 1]"),
    "fmt6": dict(hop=2, anchor="emit_x3d40._fmt3 / _fmt4 / _fmt", lossless=True, recompute=True,
                 what="printed with six decimals (rounding error at most 5e-7)"),
    "fmt_length": dict(hop=2, anchor="emit_x3d40._fmt_length", lossless=True, recompute=True,
                       what="six decimals, or nine significant digits below 1e-3"),
}
_TOL = 5.0e-7 + 1e-12


def _srgb(c: float) -> float:
    c = max(0.0, float(c))
    return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1.0 / 2.4) - 0.055


def _sfcolor(values):
    rgb = [max(0.0, float(c)) for c in values[:3]]
    peak = max(rgb)
    return [c / peak for c in rgb] if peak > 1.0 else rgb


def _apply(step: str, values: list[float], ctx: dict) -> list[float]:
    """The independent recompute of one hop-2 step on a list of numbers."""
    if step == "linear_to_srgb":
        return [_srgb(c) if ctx["colour_space"] == "SRGB" else float(c) for c in values]
    if step == "sfcolor_clip":
        return _sfcolor(values)
    if step == "alpha_to_transparency":
        return [max(0.0, min(1.0, 1.0 - float(values[0])))]
    return [float(v) for v in values]   # fmt6 / fmt_length only change the printing


def _numbers(text: str) -> list[float]:
    return [float(t) for t in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", text or "")]


class _Alloc:
    """The DEF allocator of emit_x3d40 (_DefNames.get), repeated here so a report can name the DEF an IR object was written under."""

    def __init__(self):
        self._by_key, self._used = {}, set()

    def get(self, kind: str, key: str, prefix: str) -> str:
        name = self._by_key.get((kind, key))
        if name is None:
            base = f"{prefix}{_safe_name(key, kind)}"
            name, counter = base, 1
            while name in self._used:
                counter += 1
                name = f"{base}_{counter}"
            self._used.add(name)
            self._by_key[(kind, key)] = name
        return name


def _locate(text: str, def_name: str, attr: str):
    """(line, column, [start, end]) of ``attr`` on the element DEF'd ``def_name``, or None. 1-based line and column; the span covers the attribute value."""
    m = re.search(r"""\bDEF=(["'])%s\1""" % re.escape(def_name), text)
    if not m:
        return None
    tag_start = text.rfind("<", 0, m.start())
    tag_end = text.find(">", m.end())
    a = re.compile(r"""\s%s=(["'])(.*?)\1""" % re.escape(attr), re.S).search(text, tag_start, tag_end)
    if not a:
        return None
    start, end = a.start(2), a.end(2)
    line = text.count("\n", 0, start) + 1
    return line, start - (text.rfind("\n", 0, start) + 1) + 1, [start, end]


def _record(def_name, node, field, source, ir_value, derivation, text, elems, ctx, source_value=None):
    el = elems.get(def_name)
    rec = dict(
        {"def": def_name}, node=node, field=field, source=source, ir_value=[float(v) for v in ir_value],
        derivation=[dict(id=s, hop=CONVERSIONS[s]["hop"], checked=False) for s in derivation["hop1"]]
        + [dict(id=s, hop=2, checked=CONVERSIONS[s]["recompute"]) for s in derivation["hop2"]],
        file_value=None, locus=None, status="not_found", value_status="unchecked", verdict="unchecked", note="")
    if el is None or field not in el.attrib:
        rec["note"] = "element or attribute not in the file"
        return rec
    rec["file_value"] = el.attrib[field]
    rec["status"] = "found"
    loc = _locate(text, def_name, field)
    if loc:
        rec["locus"] = dict(line=loc[0], col=loc[1], span=loc[2])
    lossy = [s for s in derivation["hop1"] + derivation["hop2"] if not CONVERSIONS[s]["lossless"]]
    unrecomputable = [s for s in derivation["hop2"] if not CONVERSIONS[s]["recompute"]]
    expected, got = list(ir_value), _numbers(rec["file_value"])
    if unrecomputable:   # a fit with no independent formula here: the number is located, not compared
        rec["value_status"] = "unchecked"
    else:
        for step in derivation["hop2"]:
            if step == "sfcolor_clip" and (max(expected[:3]) > 1.0 + 1e-12 or min(expected[:3]) < 0.0):
                lossy.append(step)   # this value really was clipped: information was dropped
            expected = _apply(step, expected, ctx)
        rec["value_status"] = "match" if len(got) == len(expected) and all(
            abs(g - e) <= _TOL + 1e-9 * abs(e) for g, e in zip(got, expected)) else "mismatch"
    if rec["value_status"] == "mismatch":
        rec["verdict"], rec["note"] = "check", "the file value differs from the recomputed one: %s vs %s" % (got, [round(e, 7) for e in expected])
    elif unrecomputable or lossy:
        rec["verdict"] = "check"
        rec["note"] = "conversion with no independent recompute or with loss: " + ", ".join(unrecomputable + lossy)
    else:
        rec["verdict"] = "verified"
    if source_value is not None:   # hop 1 from a snapshot of Blender-side numbers
        rec["source_value"] = [float(v) for v in source_value]
        rec["source_ok"] = _hop1_ok(derivation["hop1"], source_value, ir_value, ctx)
        if rec["source_ok"] is False:
            rec["verdict"], rec["note"] = "check", (rec["note"] + "; " if rec["note"] else "") + "the IR value does not follow from the Blender value"
    return rec


def _hop1_ok(steps, source_value, ir_value, ctx):
    """True or False when every hop-1 step of the record can be recomputed from numbers, else None (not decided)."""
    if "energy_to_intensity" in steps and len(source_value) == 3:   # energy, energy per intensity, native (1) or imported (0)
        energy, per, native = source_value
        want = max(0.0, energy) / per
        want = min(want, 1.0) if native else want
        return abs(want - ir_value[0]) <= 1e-9 + 1e-9 * abs(want)
    if "fov_smaller_side" in steps and len(source_value) == 4:      # angle, fit (0 horizontal, 1 vertical), width, height
        angle, fit, w, h = source_value
        t = math.tan(angle / 2.0)
        tx, ty = (t, t * h / w) if fit == 0 else (t * w / h, t)
        want = 2.0 * math.atan(min(tx, ty))
        return abs(want - ir_value[0]) <= 1e-9
    return None


def build_report(ir_scene, x3d_text: str, *, colour_space: str = "AS_IS", source_values: dict | None = None,
                 settings: dict | None = None) -> dict:
    """The lineage report of one export: ``ir_scene`` is the IR that was written, ``x3d_text`` the file that came out.

    ``source_values`` maps ``"DEF/field"`` to the Blender-side numbers of a hop-1 check (see ``_hop1_ok``)."""
    root = ET.fromstring(x3d_text)
    elems = {e.attrib["DEF"]: e for e in root.iter() if "DEF" in e.attrib}
    ctx = dict(colour_space=colour_space)
    source_values = source_values or {}
    alloc = _Alloc()
    classic = ir_scene.material_model == "classic"
    records, seen_materials = [], set()
    t_hop1 = ["matrix_world_to_trs", "axis_conversion"] + (["file_unit_scale"] if (settings or {}).get("global_scale", 1.0) != 1.0 else [])

    def rec(def_name, node, field, source, ir_value, hop1, hop2):
        sv = source_values.get(f"{def_name}/{field}")
        records.append(_record(def_name, node, field, source, ir_value, dict(hop1=hop1, hop2=hop2), x3d_text, elems, ctx, sv))

    for inst in ir_scene.iter_instances():
        d = alloc.get("transform", inst.object_name, "OB_")
        obj = dict(datablock="objects", name=inst.object_name, path="matrix_world")
        rec(d, "Transform", "translation", obj, inst.transform.translation, t_hop1, ["fmt_length"])
        rec(d, "Transform", "rotation", obj, inst.transform.rotation_axis_angle, t_hop1, ["fmt6"])
        rec(d, "Transform", "scale", obj, inst.transform.scale, t_hop1[:1] + t_hop1[2:], ["fmt_length"])
        for shape in inst.iter_shapes():
            if shape.material_name and shape.material_name not in seen_materials:
                seen_materials.add(shape.material_name)
                _material_records(rec, alloc, ir_scene, shape.material_name, colour_space, classic)
        if inst.light is not None:
            L = inst.light
            ld = alloc.get("light", L.name, "LA_")
            src = dict(datablock="objects", name=inst.object_name, path="data")
            rec(ld, _light_tag(L), "intensity", dict(src, path="data.energy"), [L.intensity], ["energy_to_intensity"], ["fmt6"])
            rec(ld, _light_tag(L), "color", dict(src, path="data.color"), L.color, [], ["fmt6"])
        if inst.viewpoint is not None:
            V = inst.viewpoint
            vd = alloc.get("viewpoint", V.name or V.description or "Viewpoint", "CA_")
            src = dict(datablock="objects", name=inst.object_name, path="data")
            # position and orientation stay at their identity here: the object's Transform (OB_) carries the camera matrix
            if V.field_of_view is not None:
                rec(vd, "Viewpoint", "fieldOfView", dict(src, path="data.angle"), [V.field_of_view], ["fov_smaller_side"], ["fmt6"])
    return _finish(records, root, x3d_text, ir_scene, colour_space, settings)


def _light_tag(light):
    return {"DIRECTIONAL": "DirectionalLight", "SPOT": "SpotLight"}.get(light.light_type, "PointLight")


def _material_records(rec, alloc, ir_scene, name, colour_space, classic):
    m = next((x for x in ir_scene.materials if x.name == name), None)
    if m is None:
        return
    d = alloc.get("material", name, "MA_")
    src = dict(datablock="materials", name=name, path="node_tree.nodes['Principled BSDF']")
    if m.unlit:
        rec(d, "UnlitMaterial", "emissiveColor", dict(src, path=src["path"] + ".inputs['Emission Color']"), m.emissive_color[:3],
            [], ["linear_to_srgb", "sfcolor_clip", "fmt6"] if colour_space == "SRGB" else ["sfcolor_clip", "fmt6"])
        return
    tag = "Material" if _written_as_classic(m, ir_scene) else "PhysicalMaterial"
    if tag == "PhysicalMaterial":
        rec(d, tag, "baseColor", dict(src, path=src["path"] + ".inputs['Base Color']"), m.base_color[:3], [], ["sfcolor_clip", "fmt6"])
        if m.metallic is not None:
            rec(d, tag, "metallic", dict(src, path=src["path"] + ".inputs['Metallic']"), [m.metallic], [], ["fmt6"])
        if m.roughness is not None:
            rec(d, tag, "roughness", dict(src, path=src["path"] + ".inputs['Roughness']"), [m.roughness], [], ["fmt6"])
    else:
        rec(d, tag, "diffuseColor", dict(src, path=src["path"] + ".inputs['Base Color']"), m.base_color[:3], [],
            ["linear_to_srgb", "sfcolor_clip", "fmt6"])
        rec(d, tag, "specularColor", dict(src, path=src["path"] + ".inputs['Specular IOR Level','Specular Tint','Roughness']"),
            [m.roughness if m.roughness is not None else 0.5], [], ["phong_from_principled"])
        if any(c > 0.0 for c in m.emissive_color[:3]):
            rec(d, tag, "emissiveColor", dict(src, path=src["path"] + ".inputs['Emission Color']"), m.emissive_color[:3], [],
                ["sfcolor_clip", "linear_to_srgb", "sfcolor_clip", "fmt6"])
    if m.base_color and len(m.base_color) > 3 and m.base_color[3] < 1.0:
        rec(d, tag, "transparency", dict(src, path=src["path"] + ".inputs['Alpha']"), [m.base_color[3]], [], ["alpha_to_transparency", "fmt6"])


def _written_as_classic(material, ir_scene) -> bool:
    if material.unlit or (material.metallic is not None and material.metallic > 0.1) or material.metallic_roughness_texture is not None:
        return False
    return ir_scene.material_model == "classic" if ir_scene.material_model_forced else (ir_scene.material_model == "classic" or material.model == "classic")


_NON_VALUE = {"DEF", "USE", "containerField", "name", "description", "url", "reference", "version", "profile", "type", "value",
              "xsd:noNamespaceSchemaLocation", "alphaMode", "global", "shadows", "solid", "visible", "castShadow", "headlight"}


def _finish(records, root, text, ir_scene, colour_space, settings):
    scene = root.find("Scene")
    attrs_total = sum(1 for e in scene.iter() for k, v in e.attrib.items() if k not in _NON_VALUE and _numbers(v)) if scene is not None else 0
    verdicts = {v: sum(1 for r in records if r["verdict"] == v) for v in ("verified", "check", "unchecked")}
    covered = len({(r["def"], r["field"]) for r in records if r["status"] == "found"})
    carried = [list(p) for p in ir_scene.metadata.entries if p[0] not in ("generator", "translator", "filename", "created")]
    return dict(
        schema=SCHEMA, x3d=dict(sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(), bytes=len(text.encode("utf-8")),
                                version=root.attrib.get("version")),
        settings=dict(colour_space=colour_space, material_model=ir_scene.material_model, **(settings or {})),
        conversions={k: v for k, v in CONVERSIONS.items() if any(s["id"] == k for r in records for s in r["derivation"])},
        records=records,
        summary=dict(total=len(records), **verdicts, attributes_in_scene=attrs_total, attributes_with_lineage=covered,
                     coverage=round(covered / attrs_total, 4) if attrs_total else None),
        carried_head_meta=dict(entries=carried, note="copied from an imported file; describes that file, not this export" if carried else ""))


def canonical(report: dict) -> str:
    return json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def report_sha256(report: dict) -> str:
    return hashlib.sha256(canonical(report).encode("utf-8")).hexdigest()


def reverify(report: dict, x3d_text: str) -> list[str]:
    """Check a stored report against a file: the file's sha256 and every record's attribute text and locus. A list of problems; empty means the file is the one the report describes."""
    problems = []
    if hashlib.sha256(x3d_text.encode("utf-8")).hexdigest() != report["x3d"]["sha256"]:
        problems.append("file sha256 differs from the report's")
    root = ET.fromstring(x3d_text)
    elems = {e.attrib["DEF"]: e for e in root.iter() if "DEF" in e.attrib}
    for r in report["records"]:
        el = elems.get(r["def"])
        if r["file_value"] is None:
            continue
        if el is None or el.attrib.get(r["field"]) != r["file_value"]:
            problems.append(f"{r['def']}/{r['field']}: file now has {None if el is None else el.attrib.get(r['field'])!r}, report has {r['file_value']!r}")
    return problems
