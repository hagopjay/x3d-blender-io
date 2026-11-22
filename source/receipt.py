# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Loss receipt v1 (schema ``x3d-blender-io.loss-receipt/1``): what an X3D 4.0 export dropped, approximated or clamped.

The rules come from the Blender half of the mapping table (``mapping/blender_rna.json``): a row with a ``receipt``
rule adds an entry for every exported datablock the rule fires on. The receipt has two parts:

- one ``<meta name="x3d-blender-io.receipt">`` line in the file's head: a hash of the entries and three totals. It
  depends only on the scene's content (no time, no path, no host), so two exports of one scene write the same line and
  the import/export fixed point is not disturbed;
- the full receipt, a sidecar ``<file>.receipt.json`` beside the export when the operator's Receipt option is on (or
  ``BLENDER_X3D_RECEIPT=1``): every entry with its mapping row, locus and reason, the export's notes, the tools, and
  the hash of the receipt the imported file carried, if any (``prev``), so receipts chain across hops.

The core (``evaluate``, ``receipt_line``, ``build_receipt``) is plain Python; ``collect_owners`` reads Blender data.
tools/io_sync/perturb.py checks the receipt against the perturbation sweep.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

RECEIPT_SCHEMA = "x3d-blender-io.loss-receipt/1"
RECEIPT_META = "x3d-blender-io.receipt"
MAPPING_PATH = Path(__file__).resolve().parent / "mapping" / "blender_rna.json"
LOSS_KINDS = ("dropped", "approximated", "clamped")


@dataclass
class Owner:
    """One exported datablock seen by the rules: ``group`` is the mapping-row prefix (``light.spot``, ``principled``)."""

    group: str
    datablock: str
    get: Callable[[str], Any]
    custom: Callable[[str], Any] = lambda name: None
    node: str | None = None          # the X3D node the datablock became
    def_name: str | None = None      # the DEF it was written under, when known


@dataclass
class Entry:
    kind: str
    row: str
    datablock: str
    value: Any
    reason: str
    x3d: str | None = None
    node: str | None = None
    limit: Any = None

    def as_dict(self) -> dict:
        locus = {"datablock": self.datablock, "node": self.node, "field": self.x3d}
        out = {"kind": self.kind, "row": self.row, "locus": locus, "value": _plain(self.value), "reason": self.reason,
               "rule": f"source/mapping/blender_rna.json#{self.row}"}
        if self.limit is not None:
            out["limit"] = self.limit
        return out


def _plain(value):
    if isinstance(value, (bool, int, str)) or value is None:
        return value
    if isinstance(value, float):
        return round(value, 6)
    try:
        return [_plain(v) for v in value]
    except TypeError:
        return str(value)


_TABLE_CACHE: dict[str, dict] = {}


def load_table(path: str | os.PathLike | None = None) -> dict:
    path = str(path or MAPPING_PATH)
    if path not in _TABLE_CACHE:
        _TABLE_CACHE[path] = json.loads(Path(path).read_text(encoding="utf-8"))
    return _TABLE_CACHE[path]


def _version_tuple(text) -> tuple:
    import re

    return tuple(int(part) for part in re.findall(r"\d+", str(text))[:3])


def resolve_row(row: dict, blender_version: str | None) -> dict:
    """A row as it applies to this Blender version: ``before`` {"5.0": {...}} overrides its fields on older versions
    (the same reading as tools/io_sync/perturb.py)."""
    out = {k: v for k, v in row.items() if k != "before"}
    for limit, override in sorted((row.get("before") or {}).items(), key=lambda kv: _version_tuple(kv[0]), reverse=True):
        if blender_version and _version_tuple(blender_version) < _version_tuple(limit):
            out.update(override)
    return out


def _blender_version() -> str | None:
    try:
        import bpy

        return bpy.app.version_string
    except Exception:
        return None


def rules_by_group(table: dict, blender_version: str | None = None) -> dict[str, list[dict]]:
    """{group: [row, ...]} of the rows that carry a receipt rule, as they apply to ``blender_version``."""
    groups: dict[str, list[dict]] = {}
    for row in (resolve_row(r, blender_version) for r in table.get("rows", [])):
        if row.get("receipt") and row.get("class") in LOSS_KINDS:
            group, _, _prop = row["id"].partition(":")
            groups.setdefault(group, []).append(row)
    return groups


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fires(rule: dict, value, owner: Owner) -> bool:
    if rule.get("unless_custom") and owner.custom(rule["unless_custom"]) is not None:
        return False
    when = rule.get("when")
    if when is not None and owner.get(when["prop"]) not in when.get("in", ()):
        return False
    kind = rule.get("kind", "neq")
    if kind == "always":
        return True
    if value is None:
        return False
    if value == "linked":
        return True   # a texture or node drives an input the export drops
    if kind == "gt":
        number = _num(value)
        return number is not None and number > float(rule["value"]) + 1e-9
    neutral = rule.get("neutral")
    if isinstance(value, (list, tuple)):
        if not isinstance(neutral, (list, tuple)):
            return True
        return any(abs(float(a) - float(b)) > 1e-6 for a, b in zip(value, neutral))
    if isinstance(value, float) or isinstance(neutral, float):
        a, b = _num(value), _num(neutral)
        return a is None or b is None or abs(a - b) > 1e-6
    return value != neutral


def evaluate(table: dict, owners: list[Owner], blender_version: str | None = None) -> list[Entry]:
    """Every receipt entry the rules give for these datablocks, sorted so the order does not depend on the scene's."""
    groups = rules_by_group(table, blender_version or _blender_version())
    entries = []
    for owner in owners:
        for row in groups.get(owner.group, ()):
            prop = row["id"].partition(":")[2]
            try:
                value = owner.get(prop)
            except Exception:  # a property this Blender version does not have
                continue
            rule = row["receipt"]
            if fires(rule, value, owner):
                entries.append(Entry(kind=row["class"], row=row["id"], datablock=owner.datablock, value=value,
                                     reason=row.get("reason", ""), x3d=row.get("x3d"), node=owner.node,
                                     limit=rule.get("value") if rule.get("kind") == "gt" else None))
    entries.sort(key=lambda e: (e.row, e.datablock))
    return entries


def totals(entries: list[Entry]) -> dict[str, int]:
    out = {kind: 0 for kind in LOSS_KINDS}
    for entry in entries:
        out[entry.kind] = out.get(entry.kind, 0) + 1
    return out


def entries_digest(entries: list[Entry]) -> str:
    """sha256 of the entries as canonical JSON: depends on the scene, not on the run."""
    payload = json.dumps([e.as_dict() for e in entries], sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def receipt_line(entries: list[Entry]) -> str:
    t = totals(entries)
    return (f"sha256={entries_digest(entries)[:32]} dropped={t['dropped']} approximated={t['approximated']} "
            f"clamped={t['clamped']} schema={RECEIPT_SCHEMA}")


def prev_from_meta(meta_entries) -> str | None:
    """The receipt line an imported file carried (its own head meta), so this receipt chains to it."""
    for name, content in meta_entries or ():
        if name == RECEIPT_META:
            return content
    return None


def build_receipt(entries: list[Entry], *, notes=(), subject: dict | None = None, tools: dict | None = None,
                  prev: str | None = None, table: dict | None = None) -> dict:
    table = table or load_table()
    mapping_bytes = json.dumps(table, sort_keys=True).encode("utf-8")
    return {
        "schema": RECEIPT_SCHEMA,
        "subject": subject or {},
        "line": receipt_line(entries),
        "totals": dict(totals(entries), notes=len(list(notes))),
        "entries": [e.as_dict() for e in entries],
        "notes": list(notes),
        "tools": dict(tools or {}, mapping=table.get("schema"),
                      mapping_sha256=hashlib.sha256(mapping_bytes).hexdigest()),
        "host": {"python": sys.version.split()[0], "platform": platform.platform(terse=True)},
        "prev": prev,
        "scope": ("v1 reports the rows of the mapping table that carry a receipt rule, for the exported objects, "
                  "materials, cameras, lights and world; a row without a rule is declared in the table and not "
                  "repeated per scene. Carried values (Metadata, Scripts) are not listed in v1."),
    }


def sidecar_requested(option: bool | None = None) -> bool:
    if os.environ.get("BLENDER_X3D_RECEIPT", "").strip() in ("1", "true", "on", "yes"):
        return True
    if os.environ.get("BLENDER_X3D_RECEIPT", "").strip() in ("0", "false", "off", "no"):
        return False
    return bool(option)


# ---------------------------------------------------------------- Blender side

def _rna_owner(group, datablock, node=None):
    def get(prop):
        return _plain(getattr(datablock, prop))

    def custom(name):
        try:
            return datablock.get(name)
        except Exception:
            return None
    return Owner(group=group, datablock=datablock.name, get=get, custom=custom, node=node)


def _socket_owner(group, datablock, tree_node, node=None):
    def get(name):
        sock = tree_node.inputs.get(name)
        if sock is None:
            raise KeyError(name)
        if sock.is_linked:
            return "linked"
        value = getattr(sock, "default_value", None)
        return _plain(value)
    return Owner(group=group, datablock=datablock.name, get=get, node=node)


LIGHT_NODES = {"POINT": "PointLight", "SPOT": "SpotLight", "SUN": "DirectionalLight", "AREA": "DirectionalLight"}


def collect_owners(ir_scene, scene) -> list[Owner]:
    """The datablocks an X3D 4.0 export of ``ir_scene`` wrote, as rule owners (needs bpy)."""
    import bpy

    owners: list[Owner] = []
    seen = set()

    def add(key, owner):
        if key not in seen:
            seen.add(key)
            owners.append(owner)

    for instance in ir_scene.iter_instances():
        obj = bpy.data.objects.get(instance.object_name)
        if obj is None:
            continue
        add(("object", obj.name), _rna_owner("object", obj, node="Transform"))
        data = getattr(obj, "data", None)
        if obj.type == "LIGHT" and data is not None:
            group = f"light.{data.type.lower()}"
            add((group, data.name), _rna_owner(group, data, node=LIGHT_NODES.get(data.type)))
        elif obj.type == "CAMERA" and data is not None:
            add(("camera", data.name), _rna_owner("camera", data, node="Viewpoint"))
    for material in ir_scene.materials:
        mat = bpy.data.materials.get(material.name)
        if mat is None:
            continue
        add(("material", mat.name), _rna_owner("material", mat, node="Appearance"))
        tree = getattr(mat, "node_tree", None)
        if tree is not None:
            bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if bsdf is not None:
                add(("principled", mat.name), _socket_owner("principled", mat, bsdf, node="PhysicalMaterial"))
    world = getattr(scene, "world", None)
    if world is not None:
        add(("world", world.name), _rna_owner("world", world, node="Background"))
        tree = getattr(world, "node_tree", None)
        background = next((n for n in tree.nodes if n.type == "BACKGROUND"), None) if tree is not None else None
        if background is not None:
            add(("world.background", world.name), _socket_owner("world.background", world, background, node="Background"))
    return owners


def for_export(ir_scene, scene, table: dict | None = None) -> list[Entry]:
    table = table or load_table()
    try:
        return evaluate(table, collect_owners(ir_scene, scene))
    except Exception as exc:  # a receipt must never break an export; say so in the notes instead
        ir_scene.diagnostics.append(f"Loss receipt could not be computed: {exc}")
        return []


def write_sidecar(path: str, receipt: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=1, sort_keys=False)
        handle.write("\n")


def subject_of(path: str) -> dict:
    data = Path(path).read_bytes()
    return {"file": os.path.basename(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


__all__ = ["RECEIPT_SCHEMA", "RECEIPT_META", "Owner", "Entry", "load_table", "evaluate", "receipt_line", "build_receipt",
           "collect_owners", "for_export", "write_sidecar", "subject_of", "sidecar_requested", "prev_from_meta", "fires"]

