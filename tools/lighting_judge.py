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


if __name__ == "__main__":
    json.dump({"limits": json.loads((ROOT / "tests/lighting/limits.json").read_text()),
               "witnesses": judge(sys.argv[1:])}, sys.stdout, indent=1)
