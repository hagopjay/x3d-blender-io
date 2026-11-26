# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The simulator judge (tools/behaviour_sim_judge.py) for the pick sensors, whose streams include node lists and lists of
vectors.

    NODE_PATH=$(npm root -g) node tools/behaviour_pick_record.cjs <x_ite dist> probe-pick.x3d sources.json 14 > trace.json
    python tools/behaviour_pick_judge.py probe-pick.x3d trace.json

``pickedGeometry`` is a list of nodes: the recorder writes the DEF names ("[B1,B2]") and the simulator sends the names of its
geometries, and the two lists are equal or they are not. The vector outputs (``pickedPoint``, ``pickedNormal``,
``pickedTextureCoordinate``) are read as lists of numbers, as in tools/behaviour_sim_judge_mf.py. Nothing else about the
judgement changes: the same frames, the same tolerances, event for event.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import behaviour_sim_judge as _judge          # noqa: E402
import behaviour_sim_judge_mf as _mf          # noqa: E402


def names(value):
    """A node list as a tuple of names: the recorder's "[a,b]" text, or the simulator's list of names."""
    if isinstance(value, str):
        value = value.strip()
        if value[:1] == "[":
            value = value[1:-1]
        return tuple(n.strip() for n in value.split(",") if n.strip())
    return tuple(str(n) for n in value)


def judge(x3d_path, trace, **options):
    """``behaviour_sim_judge.judge`` with node lists and vector lists readable."""
    original_numbers, original_gap = _judge._numbers, _judge._gap

    def gap(a, b, x3d_type):
        if x3d_type == "MFNode":
            return 0.0 if names(a) == names(b) else float("inf")
        return original_gap(a, b, x3d_type)

    _judge._numbers, _judge._gap = _mf._numbers, gap
    try:
        return _judge.judge(x3d_path, trace, **options)
    finally:
        _judge._numbers, _judge._gap = original_numbers, original_gap


if __name__ == "__main__":
    result = judge(sys.argv[1], json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")))
    print(json.dumps(result, indent=1))
    sys.exit(0 if result.get("agree") else 1)
