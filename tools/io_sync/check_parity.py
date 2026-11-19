# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every element in real exports is declared in parity.json (plain Python).

    python3 tools/io_sync/check_parity.py FILE_OR_FOLDER [...]

Reads every .x3d under the arguments and exits 1, listing them, when an element name is missing from parity.json's
"nodes": the export wrote something nobody has said how the import reads back. The static half of this check (names
in the emitter's source) is tests/test_io_parity.py.
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


def main(argv):
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
