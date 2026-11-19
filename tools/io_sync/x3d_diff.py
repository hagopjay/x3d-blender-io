# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Structural diff of two X3D (XML) files, plain Python: what changed between an export and its re-export.

    python3 x3d_diff.py A.x3d B.x3d [--json OUT] [--rel 1e-5] [--abs 1e-6]

Both trees are walked in document order. Children are aligned per parent by (tag, DEF) when both sides carry the
DEF, then by a signature (the first DEF or description below the node, for the DEF-less Transform around a light or a
camera), the rest by tag and position among the remaining siblings of that tag, so one missing or renamed node does not
shift every node after it.
Numeric attributes (whitespace-separated lists of numbers) compare with |a-b| <= abs + rel*max(|a|,|b|); other
attributes compare as strings after whitespace normalisation. DEF and USE values are compared as references, not
spellings: a DEF renamed consistently (Cube -> Cube_001) is not a difference, a USE that points to a different node is.
With --strict-defs a DEF spelled differently is a difference too (the fixed-point gate uses it on E1 -> E2, where names
must not drift).

Exit 0 when the files are equivalent, 1 when they differ. Each difference is one record:
  {"kind": "missing"|"extra"|"attr_missing"|"attr_extra"|"value", "path": "...", "tag": ..., "attr": ..., "a": ..., "b": ...}
and the summary groups them by (kind, tag, attr) with counts, which is what a parity report needs.
"""
from __future__ import annotations

import gzip
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter

NUM = re.compile(r"^[\s,]*[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?([\s,]+[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?)*[\s,]*$")
# Attributes that name things rather than describe them: compared through the DEF map, or not at all.
REF_ATTRS = {"DEF", "USE"}
# Per-field absolute tolerance where Blender's storage is coarser than the file: custom normals are held as two 16-bit
# angles per corner fan, so a normal re-read from Blender moves by up to ~3e-4 (measured on the suite, Nov 2026).
FIELD_ABS = {("Normal", "vector"): 1e-3}
ROUTE_REF_ATTRS = {"fromNode", "toNode"}


def load(path: str) -> ET.Element:
    data = open(path, "rb").read()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return ET.fromstring(data)


def _numbers(text: str):
    return [float(t) for t in re.split(r"[\s,]+", text.strip()) if t]


def _close(a: float, b: float, rel: float, abs_: float) -> bool:
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    return abs(a - b) <= abs_ + rel * max(abs(a), abs(b))


def _signature(el: ET.Element) -> str | None:
    """The first DEF or description at or below el, ignoring the generated 'USE_' prefix and Blender's .001 suffixes."""
    for d in el.iter():
        name = d.get("DEF") or d.get("description")
        if name:
            return re.sub(r"(_\d{3})+$", "", name.replace("USE_", ""))
    return None


def _align(ca: list, cb: list):
    """Pair children of two parents: first by (tag, DEF) where both sides carry that DEF, then the rest by tag and
    position among the remaining siblings of that tag."""
    ca = [c for c in ca if isinstance(c.tag, str)]
    cb = [c for c in cb if isinstance(c.tag, str)]
    defs_b = {(c.tag, c.get("DEF")): c for c in cb if c.get("DEF")}
    pairs, used_b = [], set()
    rest_a = []
    for c in ca:
        k = (c.tag, c.get("DEF"))
        if c.get("DEF") and k in defs_b and id(defs_b[k]) not in used_b:
            pairs.append(((c.tag, "DEF=" + c.get("DEF")), c, defs_b[k]))
            used_b.add(id(defs_b[k]))
        else:
            rest_a.append(c)
    rest_b = [c for c in cb if id(c) not in used_b]

    # then by signature: a node without a DEF (the Transform around a light or a camera) is named by the first DEF or
    # description below it, so one flattened Transform does not shift every light and camera after it
    sig_b = {}
    for c in rest_b:
        sig_b.setdefault((c.tag, _signature(c)), []).append(c)
    still_a = []
    for c in rest_a:
        sig = _signature(c)
        bucket = sig_b.get((c.tag, sig)) if sig else None
        if bucket:
            match = bucket.pop(0)
            pairs.append(((c.tag, "~" + sig), c, match))
            used_b.add(id(match))
        else:
            still_a.append(c)
    rest_a = still_a
    rest_b = [c for c in rest_b if id(c) not in used_b]

    def keyed(children):
        seen = Counter()
        out = {}
        for c in children:
            out[(c.tag, seen[c.tag])] = c
            seen[c.tag] += 1
        return out
    ka, kb = keyed(rest_a), keyed(rest_b)
    pairs += [(k, ka.get(k), kb.get(k)) for k in list(ka) + [k for k in kb if k not in ka]]
    return pairs


class Differ:
    def __init__(self, rel=1e-5, abs_=1e-6, ignore_attrs=(), strict_defs=False):
        self.rel, self.abs = rel, abs_
        self.strict_defs = strict_defs
        self.ignore = set(ignore_attrs)
        self.records = []
        self.def_a, self.def_b = {}, {}
        self.pending_refs = []

    def _rec(self, kind, path, tag, attr=None, a=None, b=None):
        self.records.append({"kind": kind, "path": path, "tag": tag, "attr": attr, "a": a, "b": b})

    def compare(self, a: ET.Element, b: ET.Element):
        self._walk(a, b, a.tag)
        # references: a USE / ROUTE end is the same when it names the DEF found at the same aligned path
        for name, va, vb, path, tag in self.pending_refs:
            if self.def_a.get(va) != self.def_b.get(vb) or self.def_a.get(va) is None:
                if va != vb or va not in self.def_a:
                    self._rec("value", path, tag, name, va, vb)
        return self.records

    def _walk(self, a, b, path):
        tag = a.tag
        if a.get("DEF"):
            self.def_a[a.get("DEF")] = path
        if b.get("DEF"):
            self.def_b[b.get("DEF")] = path
        attrs = set(a.attrib) | set(b.attrib)
        for name in sorted(attrs - self.ignore):
            va, vb = a.get(name), b.get(name)
            if va is None:
                self._rec("attr_extra", path, tag, name, None, vb)
                continue
            if vb is None:
                self._rec("attr_missing", path, tag, name, va, None)
                continue
            if name == "DEF":
                if self.strict_defs and va != vb:
                    self._rec("value", path, tag, name, va, vb)
                continue  # otherwise positions are compared by alignment; spelling may change on re-import
            if name in ("USE",) or (tag == "ROUTE" and name in ROUTE_REF_ATTRS):
                self.pending_refs.append((name, va, vb, path, tag))
                continue
            if va == vb:
                continue
            if NUM.match(va) and NUM.match(vb):
                na, nb = _numbers(va), _numbers(vb)
                if len(na) != len(nb):
                    self._rec("value", path, tag, name, f"{len(na)} numbers", f"{len(nb)} numbers")
                elif not all(_close(x, y, self.rel, max(self.abs, FIELD_ABS.get((tag, name), 0.0))) for x, y in zip(na, nb)):
                    worst = max(abs(x - y) for x, y in zip(na, nb))
                    self._rec("value", path, tag, name, va[:80], vb[:80] + f"  (max |d| {worst:.3g})")
                continue
            if " ".join(va.split()) != " ".join(vb.split()):
                self._rec("value", path, tag, name, va[:80], vb[:80])
        for k, ca, cb in _align(list(a), list(b)):
            sub = f"{path}/{k[0]}[{k[1]}]"
            lone = ca if cb is None else cb if ca is None else None
            if lone is not None and lone.get("DEF"):
                sub = f"{path}/{k[0]}[DEF={lone.get('DEF')}]"
            elif lone is not None and _signature(lone):
                sub = f"{path}/{k[0]}[~{_signature(lone)}]"
            if cb is None:
                self._rec("missing", sub, k[0])
            elif ca is None:
                self._rec("extra", sub, k[0])
            else:
                self._walk(ca, cb, sub)


def summarise(records):
    groups = Counter((r["kind"], r["tag"], r["attr"]) for r in records)
    return [{"kind": k, "tag": t, "attr": a, "count": n, "example": next(
        r for r in records if (r["kind"], r["tag"], r["attr"]) == (k, t, a))} for (k, t, a), n in groups.most_common()]


def diff_files(pa, pb, rel=1e-5, abs_=1e-6, ignore_attrs=(), strict_defs=False):
    d = Differ(rel, abs_, ignore_attrs, strict_defs)
    return d.compare(load(pa), load(pb))


def main(argv):
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("a"); p.add_argument("b")
    p.add_argument("--json"); p.add_argument("--rel", type=float, default=1e-5); p.add_argument("--abs", type=float, default=1e-6)
    p.add_argument("--ignore", action="append", default=[])
    p.add_argument("--strict-defs", action="store_true", help="a DEF spelled differently is a difference")
    o = p.parse_args(argv)
    rec = diff_files(o.a, o.b, o.rel, o.abs, o.ignore, o.strict_defs)
    summ = summarise(rec)
    for g in summ:
        print(f"{g['count']:6d}  {g['kind']:12s} {g['tag']}.{g['attr'] or ''}   e.g. {g['example']['path']}  {g['example']['a']!r} -> {g['example']['b']!r}")
    if o.json:
        json.dump({"records": rec, "summary": summ}, open(o.json, "w"), indent=1)
    return 1 if rec else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
