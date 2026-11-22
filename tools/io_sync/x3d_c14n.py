# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""A canonical text form of an X3D XML file, for golden files and metamorphic relations (plain Python).

    python tools/io_sync/x3d_c14n.py FILE.x3d [--out FILE.c14n.x3d] [--rename-defs]

It follows the intent of the X3D Canonical Form (X3dC14n: one spelling per document, so two files that mean the same
are byte-equal), but it is this add-on's own v1 rule set, not a conforming X3dC14n implementation:

  1. no XML declaration, DOCTYPE, comments or processing instructions; one element per line, one space of indent per
     level; attributes in alphabetical order, single-quoted, with &, < and ' escaped;
  2. the head meta that describe the run, not the scene, are dropped: generator, filename, date, created, modified
     (A11 in tools/io_sync/parity.json); the loss receipt's line is kept (it depends on scene content only);
  3. every numeric token of an attribute that x3d.py types as a number (SF/MF Float, Double, Int32, Vec, Color,
     Rotation, Matrix, Time; read from mapping/x3d_fields.json) is rewritten as round(value, 5) with no trailing zeros
     and no negative zero, so 0.500000, 0.5 and 0.50000004 are one spelling;
  4. whitespace inside other attribute values is collapsed to single spaces;
  5. with --rename-defs, DEF names become D1, D2, ... in document order and every USE and ROUTE endpoint follows, so
     two files that differ only in names compare equal (metamorphic relation "rename an object").
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIELDS = REPO / "mapping" / "x3d_fields.json"
VOLATILE_META = {"generator", "filename", "date", "created", "modified", "translator"}
NUMERIC_TYPES = re.compile(r"^(SF|MF)(Float|Double|Int32|Vec[234][fd]|Color|ColorRGBA|Rotation|Matrix[34][fd]|Time)$")
NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
DIGITS = 5


@lru_cache(maxsize=1)
def numeric_fields() -> dict[str, set[str]]:
    table = json.loads(FIELDS.read_text(encoding="utf-8"))
    return {node: {name for name, f in row["fields"].items() if NUMERIC_TYPES.match(f["type"])}
            for node, row in table["nodes"].items()}


def _number(token: str) -> str:
    try:
        value = round(float(token), DIGITS)
    except ValueError:
        return token
    if value == 0:
        return "0"
    text = f"{value:.{DIGITS}f}".rstrip("0").rstrip(".")
    return text


def _value(tag: str, name: str, value: str) -> str:
    if name in numeric_fields().get(tag, ()):
        return NUMBER.sub(lambda m: _number(m.group(0)), " ".join(value.split()))
    return " ".join(value.split())


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace("'", "&apos;")


def canonical(data: bytes | str, rename_defs: bool = False) -> str:
    if isinstance(data, bytes):
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        data = data.decode("utf-8")
    data = re.sub(r"<!DOCTYPE[^>]*>", "", data, count=1)
    root = ET.fromstring(data)
    names = {}
    if rename_defs:
        for el in root.iter():
            if isinstance(el.tag, str) and el.get("DEF"):
                names.setdefault(el.get("DEF"), f"D{len(names) + 1}")
    lines = []

    def walk(el, depth):
        if not isinstance(el.tag, str):
            return
        tag = el.tag.split("}")[-1]
        if tag == "meta" and el.get("name") in VOLATILE_META:
            return
        attrs = {}
        for key, value in el.attrib.items():
            key = key.split("}")[-1]
            if key in ("noNamespaceSchemaLocation",):
                continue
            if rename_defs and (key in ("DEF", "USE") or (tag == "ROUTE" and key in ("fromNode", "toNode"))):
                value = names.get(value, value)
            attrs[key] = _value(tag, key, value)
        text = " ".join(f"{k}='{_escape(v)}'" for k, v in sorted(attrs.items()))
        children = [c for c in el if isinstance(c.tag, str)]
        body = (el.text or "").strip()
        pad = " " * depth
        if not children and not body:
            lines.append(f"{pad}<{tag}{' ' + text if text else ''}/>")
            return
        lines.append(f"{pad}<{tag}{' ' + text if text else ''}>")
        if body:
            lines.append(f"{pad} {_escape(' '.join(body.split()))}")
        for child in children:
            walk(child, depth + 1)
        lines.append(f"{pad}</{tag}>")

    walk(root, 0)
    return "\n".join(lines) + "\n"


def canonical_file(path: str | Path, rename_defs: bool = False) -> str:
    return canonical(Path(path).read_bytes(), rename_defs=rename_defs)


def main(argv):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("file")
    p.add_argument("--out")
    p.add_argument("--rename-defs", action="store_true")
    args = p.parse_args(argv)
    text = canonical_file(args.file, args.rename_defs)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
