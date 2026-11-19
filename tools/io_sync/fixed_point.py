# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Import/export fixed-point check over the export test suite's three files (plain Python driver; runs Blender).

    python3 tools/io_sync/fixed_point.py SUITE_OUT OUT_DIR [--blender PATH] [--profiles main,crease,x41]

SUITE_OUT is a folder written by tests/suite/x3d_test_suite.py --export (the three .x3d files and
x3d_suite_manifest.json). For each profile the export options come from the manifest, so E0 and its re-exports are
written the same way; an export written with color_space=AS_IS is imported with color_space=AS_IS.

For each file E0: fixed_point_leg.py imports it and re-exports E1, then imports E1 and re-exports E2. Reported:
  - E0 -> E1: what one Blender round trip changes in a file this add-on wrote (the import/export asymmetries);
  - E1 -> E2: must be empty up to number formatting, DEF spellings included; anything here is a round trip that does
    not converge (it changes the file again on every import/export).
Writes OUT_DIR/summary.json and OUT_DIR/summary.txt; exit 1 when E1 -> E2 has differences beyond --rel/--abs.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import x3d_diff  # noqa: E402

DEFAULT_BLENDER = os.environ.get("BLENDER", "/Applications/Blender.app/Contents/MacOS/Blender")
# head/meta that name the file or the tool run: they change on every export by design
IGNORE_META = True


def run(suite: Path, out: Path, blender: str, profiles, rel, abs_):
    manifest = json.loads((suite / "x3d_suite_manifest.json").read_text())
    out.mkdir(parents=True, exist_ok=True)
    rows = {key: {"error": "unknown profile"} for key in profiles if key not in manifest["profiles"]}
    for key, prof in manifest["profiles"].items():
        if profiles and key not in profiles:
            continue
        opts = dict(prof["export"])
        opts.pop("filepath", None)
        imp = {"color_space": "AS_IS"} if opts.get("color_space") == "AS_IS" else {}
        e0 = suite / prof["file"]
        od = out / key
        od.mkdir(parents=True, exist_ok=True)
        # Never accept evidence left by a previous invocation, including when Blender catches a Python failure and
        # exits zero. Preserve each run's logs while selecting only this invocation's exact expected directory.
        run_root = Path(tempfile.mkdtemp(prefix="run-", dir=od))
        leg = run_root / (e0.parent.name + "__" + e0.stem)
        cmd = [blender, "-b", "--factory-startup", "-noaudio", "--python-exit-code", "1", "--python", str(HERE / "fixed_point_leg.py"), "--",
               str(run_root), "--export", json.dumps(opts), "--import", json.dumps(imp), str(e0)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode or not all((leg / name).is_file() for name in ("e1.x3d", "e2.x3d", "s1.json", "s2.json")):
            rows[key] = {"error": (proc.stdout + proc.stderr)[-2000:] or "leg did not produce all expected outputs",
                         "artifacts": str(run_root)}
            continue
        r01 = x3d_diff.diff_files(str(e0), str(leg / "e1.x3d"), rel, abs_)
        r12 = x3d_diff.diff_files(str(leg / "e1.x3d"), str(leg / "e2.x3d"), rel, abs_, strict_defs=True)
        if IGNORE_META:
            r01 = [r for r in r01 if r["tag"] != "meta"]
            r12 = [r for r in r12 if r["tag"] != "meta"]
        rows[key] = {"artifacts": str(leg), "options": opts, "import": imp, "e0_e1": x3d_diff.summarise(r01), "e1_e2": x3d_diff.summarise(r12),
                     "e0_e1_count": len(r01), "e1_e2_count": len(r12)}
    (out / "summary.json").write_text(json.dumps(rows, indent=1))
    lines = [] if rows else ["No profiles selected; no round trips were checked."]
    for key, row in rows.items():
        if "error" in row:
            lines.append(f"{key}: LEG FAILED\n{row['error']}")
            continue
        lines.append(f"== {key}: E0->E1 {row['e0_e1_count']} differences, E1->E2 {row['e1_e2_count']}")
        for name in ("e0_e1", "e1_e2"):
            for g in row[name]:
                ex = g["example"]
                lines.append(f"  {name} {g['count']:5d} {g['kind']:12s} {g['tag']}.{g['attr'] or ''}  {ex['path']}  "
                             f"{str(ex['a'])[:60]!r} -> {str(ex['b'])[:60]!r}")
    (out / "summary.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 1 if not rows or any(row.get("e1_e2_count", 1) for row in rows.values()) else 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("suite", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--blender", default=DEFAULT_BLENDER)
    p.add_argument("--profiles", default="")
    p.add_argument("--rel", type=float, default=1e-4)
    p.add_argument("--abs", type=float, default=1e-4)
    o = p.parse_args()
    o.out.mkdir(parents=True, exist_ok=True)
    sys.exit(run(o.suite, o.out, o.blender, [x for x in o.profiles.split(",") if x], o.rel, o.abs))


if __name__ == "__main__":
    main()
