# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""The scorecard's results schema: leg registry, record constructors, validator verdicts and marks, and `check_results`.

results.json (schema id SCHEMA) is one document per run:

    {schema, created, params, rig, legs: {leg_id: {label, engine, role, input_kind, optional, ...}},
     scenes: [{name, x3d: {path, sha256, wellformed}, view, clear, headlight, legs: {leg_id: LEG_RECORD}}]}

LEG_RECORD (every scene carries one for every leg in the registry, so nothing is silently omitted):

    leg, engine, engine_version, status (ok | failed | not-applicable | not-run), reason (always set unless ok),
    input: {kind: "x3d" | "glb", path, sha256, producer},
    validator: {kind: "gltf-validator" | "x3d-wellformed", verdict, ...} or null,
    image: path of the 512 x 512 render relative to the results folder, or null,
    seconds: {render, ...}, config: the settings of the render, config_key + scene_sha256: what --resume compares,
    metrics_sig: hash of the images the metrics were computed from,
    metrics: {flip_vs_reference, flip_vs_xite, mean_abs_vs_xite, noise_floor (reference leg only)}, notes: [..], tool: str

No timestamps inside records (only `created` at the top), so the same inputs give comparable files."""
from __future__ import annotations

SCHEMA = "x3d-blender-io.scorecard/v1"

OK, FAILED, NOT_APPLICABLE, NOT_RUN = "ok", "failed", "not-applicable", "not-run"
STATUSES = (OK, FAILED, NOT_APPLICABLE, NOT_RUN)

REFERENCE_LEG = "blender_cycles"
XITE_LEG = "xite"

# id -> spec. Order is the display order of columns; the reference is listed last in tables (it is the yardstick).
LEGS = {
    "xite": dict(
        label="X_ITE", engine="X_ITE", role="engine", input_kind="x3d", optional=False, env=None,
        what="X_ITE on the X3D file (headless Chromium, SwiftShader)",
        independent="reads the X3D itself"),
    "babylon_addon_glb": dict(
        label="Babylon (add-on glb)", engine="Babylon.js", role="engine", input_kind="glb", optional=False, env=None,
        what="Babylon.js on the glb the x3d-blender-io add-on writes",
        independent="shares the add-on's reading of the file with the Cycles reference: NOT independent of it"),
    "babylon_castle_glb": dict(
        label="Babylon (Castle glb)", engine="Babylon.js", role="engine", input_kind="glb", optional=True, env="CASTLE_CONVERT",
        what="Babylon.js on the glb the Castle exporter writes (x3d-castle-convert)",
        independent="an independent reading of the file (Castle exporter)"),
    "castle_native": dict(
        label="Castle native", engine="Castle Game Engine", role="engine", input_kind="x3d", optional=True, env="CASTLE_RENDER",
        what="castle-render: the X3D loaded and drawn by Castle itself",
        independent="reads the X3D itself"),
    "blender_eevee": dict(
        label="Blender EEVEE", engine="Blender EEVEE (BLENDER_EEVEE)", role="engine", input_kind="x3d", optional=False, env=None,
        what="Blender EEVEE on the add-on's import of the X3D (xvfb + Mesa llvmpipe); a rasteriser scored against Cycles",
        independent="shares the add-on's reading of the file with the Cycles reference: NOT independent of it"),
    "blender_cycles": dict(
        label="Blender Cycles (reference)", engine="Blender Cycles (CPU)", role="reference", input_kind="x3d", optional=False, env=None,
        what="Cycles path tracer on the add-on's import of the X3D: the reference image, and its own seed-to-seed noise floor",
        independent="the reference itself"),
}
LEG_IDS = tuple(LEGS)
ENGINE_LEGS = tuple(k for k, v in LEGS.items() if v["role"] == "engine")


def new_leg_record(leg: str, status: str = NOT_RUN, reason: str | None = None, **kw) -> dict:
    """A complete leg record with every field present (None / empty when unknown)."""
    spec = LEGS[leg]
    rec = dict(
        leg=leg, label=spec["label"], engine=spec["engine"], engine_version=None, status=status, reason=reason,
        input=None, validator=None, image=None, extra_images={}, seconds={}, config={}, config_key={}, scene_sha256=None, metrics={},
        metrics_sig=None, notes=[], tool=None)
    rec.update(kw)
    return rec


def gltf_verdict(summary: dict | None, error: str | None = None, x3d_has_geometry: bool | None = True) -> dict:
    """Validator record for a glb leg from manifest.validate()'s summary (or its error text).

    verdict: "pass" (0 errors), "fail" (errors), "empty" (a structurally valid glb with 0 triangles while the X3D has geometry:
    the Khronos validator proves structure only), "error" (the validator did not run: never a pass)."""
    if not summary:
        return dict(kind="gltf-validator", verdict="error", error=error or "validator did not run", errors=None, warnings=None,
                    triangles=None, empty=None)
    errors, warnings, tris = summary["errors"], summary["warnings"], summary["triangles"]
    zero = (tris == 0)
    empty = bool(zero and x3d_has_geometry is not False)
    verdict = "fail" if errors else ("empty" if empty else "pass")
    return dict(kind="gltf-validator", verdict=verdict, version=summary.get("version"), errors=errors, warnings=warnings,
                infos=summary.get("infos"), hints=summary.get("hints"), triangles=tris, empty=empty,
                zero_triangles=zero, x3d_has_geometry=x3d_has_geometry, draw_calls=summary.get("drawCalls"),
                materials=summary.get("materials"), extensions_used=summary.get("extensionsUsed"),
                extensions_not_validated=summary.get("extensionsNotValidated"), glb_bytes=summary.get("bytes"),
                glb_sha256=summary.get("sha256"), issues=[dict(code=i["code"], severity=i["severity"], pointer=i.get("pointer"),
                                                              message=i["message"][:200]) for i in (summary.get("issues") or [])[:8]])


def x3d_verdict(wellformed: dict | None) -> dict:
    """Validator record for an X3D-input leg from common.x3d_wellformed(): verdict pass / fail / not-checked."""
    if not wellformed:
        return dict(kind="x3d-wellformed", verdict="not-checked", error="not examined")
    return dict(kind="x3d-wellformed", **wellformed)


def mark(validator: dict | None) -> str:
    """The short table mark for a validator record.

    glb: "✓" 0 errors and 0 warnings, "✓w" 0 errors with warnings, "✗" errors, "∅" EMPTY (valid but 0 triangles with geometry in the X3D),
    "?" the validator did not run. X3D: "x✓" well-formed, "x✗" not well-formed, "x?" not an XML X3D file (not examined)."""
    if not validator:
        return ""
    v, kind = validator.get("verdict"), validator.get("kind")
    if kind == "x3d-wellformed":
        return {"pass": "x✓", "fail": "x✗"}.get(v, "x?")
    if v == "empty":
        return "∅"
    if v == "fail":
        return "✗"
    if v == "pass":
        return "✓w" if (validator.get("warnings") or 0) > 0 else "✓"
    return "?"


def mark_title(validator: dict | None) -> str:
    """Plain-text explanation of the mark (tooltip / legend)."""
    if not validator:
        return ""
    if validator.get("kind") == "x3d-wellformed":
        return f"X3D well-formedness: {validator.get('verdict')}" + (f" ({validator['error']})" if validator.get("error") else "")
    v = validator.get("verdict")
    if v == "error":
        return "glTF validator did not run: " + str(validator.get("error"))
    return (f"gltf-validator {validator.get('version')}: {validator.get('errors')} errors, {validator.get('warnings')} warnings, "
            f"{validator.get('triangles')} triangles" + (", EMPTY (no triangles while the X3D has geometry)" if validator.get("empty") else ""))


def check_results(doc: dict) -> list[str]:
    """Structural problems of a results document (an empty list means it conforms). Never raises on malformed input."""
    p: list[str] = []
    if not isinstance(doc, dict):
        return ["document is not an object"]
    if doc.get("schema") != SCHEMA:
        p.append(f"schema is {doc.get('schema')!r}, expected {SCHEMA!r}")
    for key in ("params", "rig", "legs", "scenes"):
        if key not in doc:
            p.append(f"missing top-level key {key!r}")
    scenes = doc.get("scenes")
    if not isinstance(scenes, list):
        return p + ["scenes is not a list"]
    seen = set()
    for i, sc in enumerate(scenes):
        where = f"scenes[{i}]"
        if not isinstance(sc, dict):
            p.append(f"{where} is not an object")
            continue
        name = sc.get("name")
        where = f"scene {name!r}" if name else where
        if not name:
            p.append(f"{where}: no name")
        elif name in seen:
            p.append(f"{where}: duplicate scene name")
        seen.add(name)
        if not isinstance(sc.get("x3d"), dict) or not sc["x3d"].get("sha256"):
            p.append(f"{where}: x3d needs path and sha256")
        legs = sc.get("legs")
        if not isinstance(legs, dict):
            p.append(f"{where}: legs is not an object")
            continue
        for leg in LEG_IDS:
            if leg not in legs:
                p.append(f"{where}: leg {leg!r} is missing (a leg that did not run is recorded as {NOT_RUN!r}, never omitted)")
        for leg, rec in legs.items():
            w = f"{where} leg {leg}"
            if leg not in LEGS:
                p.append(f"{w}: unknown leg id")
                continue
            if not isinstance(rec, dict):
                p.append(f"{w}: not an object")
                continue
            st = rec.get("status")
            if st not in STATUSES:
                p.append(f"{w}: status {st!r} is not one of {STATUSES}")
            if st != OK and not rec.get("reason"):
                p.append(f"{w}: status {st} needs a reason")
            if st == OK:
                if not rec.get("image"):
                    p.append(f"{w}: ok without an image")
                if not rec.get("engine_version"):
                    p.append(f"{w}: ok without engine_version")
                inp = rec.get("input")
                if not isinstance(inp, dict) or inp.get("kind") not in ("x3d", "glb") or not inp.get("path"):
                    p.append(f"{w}: ok without input kind and path")
                elif inp["kind"] != LEGS[leg]["input_kind"]:
                    p.append(f"{w}: input kind {inp['kind']} but the leg reads {LEGS[leg]['input_kind']}")
                v = rec.get("validator")
                if not isinstance(v, dict) or v.get("kind") not in ("gltf-validator", "x3d-wellformed"):
                    p.append(f"{w}: ok without a validator verdict")
                elif (v["kind"] == "gltf-validator") != (LEGS[leg]["input_kind"] == "glb"):
                    p.append(f"{w}: validator kind {v['kind']} does not match input kind {LEGS[leg]['input_kind']}")
            for k in ("seconds", "metrics", "config"):
                if not isinstance(rec.get(k), dict):
                    p.append(f"{w}: {k} is not an object")
    return p
