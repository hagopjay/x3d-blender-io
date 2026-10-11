# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Re-check every scene of the showcase page with the x3d_mcp validator fork.

Writes docs/showcase/scenes/verdicts.json, which the page reads to show a verdict
under each live demo (schema by declared version, semantic checks, X3DUOM profile).

    git clone -b integration/validator-fixes https://github.com/hagopjay/x3d_mcp
    X3D_MCP_SRC=x3d_mcp/src python3 tools/showcase_verdicts.py
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENES = os.path.join(HERE, "docs", "showcase", "scenes")


def main() -> int:
    src = os.environ.get("X3D_MCP_SRC")
    if not src:
        print("set X3D_MCP_SRC to the src/ folder of hagopjay/x3d_mcp (integration/validator-fixes)")
        return 2
    sys.path.insert(0, src)
    from lxml import etree
    from validation.profile import check_profile
    from validation.semantic import validate_semantic
    from validation.validate import validate_xml

    try:
        commit = subprocess.run(["git", "-C", src, "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"

    scenes = {}
    for path in sorted(glob.glob(os.path.join(SCENES, "*.x3d"))):
        raw = open(path, "rb").read()
        xml = raw.decode("utf-8")
        root = etree.fromstring(raw)
        schema = validate_xml(xml)
        semantic = validate_semantic(xml)
        counts = re.search(r"Found (\d+) error\(s\), (\d+) warning", semantic)
        errors, warnings = (int(counts.group(1)), int(counts.group(2))) if counts else (0, 0)
        profile = check_profile(root)
        name = os.path.basename(path)
        scenes[name] = {
            "version": root.get("version"),
            "profile": root.get("profile"),
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()[:16],
            "xsd": bool(schema.get("valid")),
            "xsd_errors": [str(e)[:220] for e in (schema.get("errors") or [])][:3],
            "semantic_errors": errors,
            "semantic_warnings": warnings,
            "profile_ok": profile.ok,
            "profile_missing": [m.get("node") for m in profile.missing][:5],
        }
        verdict = scenes[name]
        print(f"{name:34s} X3D {verdict['version']} schema={'ok' if verdict['xsd'] else 'FAIL'} "
              f"semantic={errors}e/{warnings}w profile={'ok' if profile.ok else 'FAIL'}")

    out = {
        "validator": f"hagopjay/x3d_mcp integration/validator-fixes @ {commit} "
                     "(XSD by declared version + semantic + X3DUOM profile check)",
        "scenes": scenes,
    }
    with open(os.path.join(SCENES, "verdicts.json"), "w", encoding="utf-8") as handle:
        json.dump(out, handle, indent=1)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
