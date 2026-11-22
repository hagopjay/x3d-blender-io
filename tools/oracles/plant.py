# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Planted faults: a judge is trusted only once it has failed a fault of the kind it claims to catch (Loom laws 19, 44).

    python tools/oracles/plant.py list
    python tools/oracles/plant.py make NAME OUT_DIR          # a copy of source/ with one planted edit (code plants)
    python tools/oracles/plant.py expect-fail NAME -- CMD...  # run CMD; exit 0 only if CMD fails and says the plant's words

tools/oracles/plants.json lists every plant: the judge it is for, the one edit (code plants: file, find, replace) or the
fixture (file plants: a wrong X3D file under tests/plants/), and the words the judge's output must contain when it fails.
CI runs every plant (job "contract" and "oracles"); a plant that a judge lets through turns the build red.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PLANTS = json.loads((Path(__file__).resolve().parent / "plants.json").read_text())


def make(name, out):
    plant = PLANTS["plants"][name]
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(REPO / "source", out / "source", ignore=shutil.ignore_patterns("__pycache__"))
    target = out / plant["file"]
    text = target.read_text(encoding="utf-8")
    if text.count(plant["find"]) != 1:
        raise SystemExit(f"plant {name}: the text to replace occurs {text.count(plant['find'])} times in {plant['file']}, "
                         "not once; update tools/oracles/plants.json with the code")
    target.write_text(text.replace(plant["find"], plant["replace"]), encoding="utf-8")
    print(f"[plant] {name}: {plant['what']} -> {out / 'source'}")
    return 0


def expect_fail(name, cmd):
    plant = PLANTS["plants"][name]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    output = proc.stdout + proc.stderr
    said = [w for w in plant["must_say"] if w in output]
    caught = proc.returncode != 0 and len(said) == len(plant["must_say"])
    tail = "\n".join(output.strip().splitlines()[-12:])
    print(f"[plant] {name} ({plant['judge']}): exit {proc.returncode}; must say {plant['must_say']}, said {said}")
    print(tail)
    if caught:
        print(f"[plant] CAUGHT: the {plant['judge']} judge failed the planted fault, as it must")
        return 0
    print(f"[plant] MISSED: the {plant['judge']} judge let '{name}' through; it cannot be trusted until it catches it")
    return 1


def main(argv):
    if not argv or argv[0] == "list":
        for name, plant in PLANTS["plants"].items():
            print(f"{name:28} {plant['judge']:12} {plant['what']}")
        return 0
    if argv[0] == "make":
        return make(argv[1], argv[2])
    if argv[0] == "expect-fail":
        name = argv[1]
        cmd = argv[argv.index("--") + 1:]
        return expect_fail(name, cmd)
    raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
