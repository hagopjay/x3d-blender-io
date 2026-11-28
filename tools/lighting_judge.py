# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Put each witness's pictures of the lighting probes next to the spec oracle's, and hold them to
tests/lighting/limits.json.

    python tools/lighting_judge.py RECORDING_DIR [RECORDING_DIR ...] > receipt.json

A recording dir holds <witness>/<scene>.png (64 x 64, 8-bit display values: tools/lighting_record.cjs for the browsers,
tools/lighting_blender_record.py for Blender). For every witness and scene the judge gives the mean and the 99th
percentile of |witness - oracle| in 8-bit levels, over the pixels away from a jump (see lighting_oracle.jump_mask),
for every reading and curve, and names the reading it lands closest to.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lighting_oracle as oracle  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def compare(picture, scene, reading, curve):
    expected, on = oracle.evaluate(scene, reading, curve)
    keep = ~oracle.jump_mask(on)
    error = np.abs(picture.astype(float) - expected * 255.0)[keep]
    return {"mean": round(float(error.mean()), 3), "p99": round(float(np.percentile(error, 99)), 3),
            "max": round(float(error.max()), 3)}


def judge(folders):
    witnesses = {}
    for folder in folders:
        for png in sorted(Path(folder).glob("*/*.png")):
            witness, scene = png.parent.name, png.stem
            if scene not in oracle.SCENES:
                continue
            picture = np.asarray(Image.open(png).convert("RGB"))
            rows = {}
            for reading in oracle.READINGS:
                for curve in ("srgb", "pow22"):
                    rows[f"{reading}/{curve}"] = compare(picture, scene, reading, curve)
            best = min(rows, key=lambda key: rows[key]["mean"])
            witnesses.setdefault(witness, {})[scene] = {"closest": best, **rows[best], "all": rows}
    return witnesses


READING_KEYS = {"linear": "linear", "display": "display", "linear-values": "linear-values"}


def gates(witnesses, limits):
    """Every gate of limits.json on the committed scenes: pass or fail, the worst scene, and whether that was expected."""
    scenes, verdicts = limits["scenes"], {}
    for name, gate in limits["gates"].items():
        names = gate["witness"] if isinstance(gate["witness"], list) else [gate["witness"]]
        for witness in names:
            rows = witnesses.get(witness)
            if rows is None:
                verdicts[f"{name}:{witness}"] = {"result": None, "why": "not recorded"}
                continue
            if gate["reading"].startswith("best"):
                measured = {scene: rows[scene] for scene in scenes}
            else:
                key = f"{gate['reading']}/{gate['curve']}"
                measured = {scene: rows[scene]["all"][key] for scene in gate.get("scenes", scenes)}
            if "mean_min" in gate:   # a wrong twin: must miss by at least this much everywhere it is held
                passed = all(row["mean"] >= gate["mean_min"] for row in measured.values())
                worst = min(measured, key=lambda scene: measured[scene]["mean"])
            else:
                passed = all(row["mean"] <= gate["mean_max"] and row["p99"] <= gate.get("p99_max", float("inf"))
                             for row in measured.values())
                worst = max(measured, key=lambda scene: measured[scene]["mean"])
            expected = gate.get("expected", "pass")
            verdicts[f"{name}:{witness}"] = {
                "result": "pass" if passed else "fail", "expected": expected,
                "as_expected": (passed and expected == "pass") or (not passed and expected == "fail"),
                "worst_scene": worst, "worst": measured[worst],
                "closest": sorted({row.get("closest") for row in (rows[s] for s in measured)} - {None})}
    return verdicts


if __name__ == "__main__":
    limits = json.loads((ROOT / "tests/lighting/limits.json").read_text())
    witnesses = judge(sys.argv[1:])
    versions = {}
    for folder in sys.argv[1:]:
        notes = Path(folder) / "versions.json"
        if notes.exists():
            versions[Path(folder).name] = json.loads(notes.read_text())
    json.dump({"oracle": "tools/lighting_oracle.py (X3D 4.0, ISO/IEC 19775-1:2023, 17.2.2.5)",
               "versions": versions, "gates": gates(witnesses, limits), "witnesses": witnesses}, sys.stdout, indent=1)
