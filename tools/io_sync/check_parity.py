# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every element in real exports is declared in parity.json (plain Python).

    python3 tools/io_sync/check_parity.py FILE_OR_FOLDER [...]
    python3 tools/io_sync/check_parity.py --fields mapping/x3d_fields.json FILE_OR_FOLDER [...]

Reads every .x3d under the arguments and exits 1, listing them, when an element name is missing from parity.json's
"nodes": the export wrote something nobody has said how the import reads back. The static half of this check (names
in the emitter's source) is tests/test_io_parity.py.

With ``--fields`` the check is per field (v3 plan, Gate 1): every attribute a file writes must have a row in the X3D half
of the mapping table (mapping/x3d_fields.json, tools/mapping/build_mapping.py) whose export is "written"; DEF, USE and
containerField are structural. An attribute the table lists as default_only or not_written is a field the export now
writes without a row saying how it round-trips.
"""
from __future__ import annotations

import gzip
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

MANIFEST = Path(__file__).resolve().parent / "parity.json"


def element_names(path: Path) -> set[str]:
    data = path.read_bytes()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return {el.tag for el in ET.fromstring(data).iter() if isinstance(el.tag, str)}


STRUCTURAL = {"DEF", "USE", "containerField", "class", "id", "style"}


def attributes(path: Path) -> set[tuple[str, str]]:
    data = path.read_bytes()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return {(el.tag, a.split("}")[-1]) for el in ET.fromstring(data).iter() if isinstance(el.tag, str) for a in el.attrib}


def check_fields(table_path: str, files: list[Path]) -> int:
    table = json.loads(Path(table_path).read_text())
    nodes, statements = table["nodes"], table["statements"]
    missing = {}
    for f in files:
        for tag, attr in attributes(f):
            if attr in STRUCTURAL or tag in ("X3D", "head", "meta", "component", "Scene", "ROUTE", "unit"):
                continue
            if tag in statements:
                ok = attr in statements[tag]["attributes_written"]
            else:
                ok = nodes.get(tag, {}).get("fields", {}).get(attr, {}).get("export") == "written"
            if not ok:
                missing.setdefault(f"{tag}@{attr}", f)
    for name, where in sorted(missing.items()):
        print(f"{name}: written in {where}, no 'written' row in {Path(table_path).name}")
    print(f"{len(files)} file(s), {len(missing)} attribute(s) without a mapping row")
    return 1 if missing or not files else 0


def main(argv):
    argv = list(argv)
    if argv[:1] == ["--fields"]:
        table, rest = argv[1], argv[2:]
        files = []
        for arg in rest:
            p = Path(arg)
            files += sorted(p.rglob("*.x3d")) if p.is_dir() else [p]
        return check_fields(table, files)
    declared = set(json.loads(MANIFEST.read_text())["nodes"])
    missing = {}
    files = []
    for arg in argv:
        p = Path(arg)
        files += sorted(p.rglob("*.x3d")) if p.is_dir() else [p]
    for f in files:
        for name in element_names(f) - declared:
            missing.setdefault(name, f)
    for name, where in sorted(missing.items()):
        print(f"{name}: written in {where}, not declared in {MANIFEST.name}")
    print(f"{len(files)} file(s), {len(missing)} undeclared element(s)")
    return 1 if missing or not files else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
