# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Write tests/physics/receipts.json from X_ITE and Blender traces of the ladder (tools/physics_record.cjs and
tools/physics_blender_record.py): per fixture and engine, the engine and host, the step, the replay result, a sha256
of the per-step hashes, the ladder's metrics (tools/physics_judge.py) and each one's verdict against
tests/physics/limits.json, plus the drop's free-fall samples that tests/test_physics_rigid_bodies_bpy.py compares.

    python tools/physics_receipt.py TRACE_DIR [--commit SHA]     (TRACE_DIR holds xite-<fixture>.json and blender-<fixture>.json)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from physics_judge import SCENES, free_fall_error, judge  # noqa: E402


def verdict(value, limit):
    if value is None:
        return "fail"
    if "target" in limit:
        tol = limit.get("abs", abs(limit["target"]) * limit.get("rel", 0.0))
        ok = abs(value - limit["target"]) <= tol
    elif "absmax" in limit:
        ok = abs(value) <= limit["absmax"]
    else:
        ok = value <= limit["max"]
    return "pass" if ok else "fail"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("traces")
    ap.add_argument("--commit", default="")
    args = ap.parse_args(argv)
    limits_path = ROOT / "tests" / "physics" / "limits.json"
    limits = json.loads(limits_path.read_text())
    out = {"schema": "x3d-blender-io.physics-receipt/1", "limits": {"path": "tests/physics/limits.json",
           "sha256": hashlib.sha256(limits_path.read_bytes()).hexdigest()}, "code_commit": args.commit, "fixtures": {}}
    for fixture in SCENES:
        stem = fixture[:-4]
        entry = {}
        for engine, prefix in (("x_ite", "xite"), ("blender", "blender")):
            path = os.path.join(args.traces, f"{prefix}-{stem}.json")
            if not os.path.exists(path):
                entry[engine] = None
                continue
            tr = json.loads(Path(path).read_text())
            metrics = judge(tr)
            checks = {k: {"value": metrics.get(k), "verdict": verdict(metrics.get(k), lim), "expect": lim.get("expect", "pass")}
                      for k, lim in limits.get(fixture, {}).items()}
            entry[engine] = {"engine_version": tr.get("engine_version"), "host": tr.get("browser", "bpy"), "fps": tr["fps"],
                             "steps": tr["steps"], "replays": tr.get("replays"),
                             "trace_sha256": hashlib.sha256(",".join(str(h) for h in tr["hashes"]).encode()).hexdigest(),
                             "info": tr.get("info"), "renamed_friction": tr.get("renamed_friction"),
                             "metrics": metrics, "checks": checks}
            if fixture == "drop-bounce.x3d":
                y = [p[1] for p in tr["trajectories"]["S"]["p"]]
                entry[engine]["drop_y_first_55_frames"] = y[:55]
                entry[engine]["free_fall_vs_discrete_euler_m"] = free_fall_error(tr, "S", 5.0, 10)
        out["fixtures"][fixture] = entry
    sys.stdout.write(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    main()
