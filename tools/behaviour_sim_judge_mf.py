# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The simulator judge (tools/behaviour_sim_judge.py) for streams whose value is a list of vectors (MFVec3f, MFVec2f).

The judge reads a value as a flat list of numbers; X_ITE writes an MF value as text ("[\\n  0 0 0,\\n  1 0 0\\n]") and the
simulator sends a Python list of tuples, so neither reads. This wrapper hands the judge a reader that flattens both, runs
it, and puts the judge's own reader back. Nothing else about the judgement changes: same frames, same tolerances, the
same event-for-event comparison (a list of another length is a disagreement). Use it for any trace with MF streams:

    python tools/behaviour_sim_judge_mf.py file.x3d trace.json
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import behaviour_sim_judge as _judge          # noqa: E402


def _numbers(value):
    """Every number in ``value``, in order: X_ITE's text for an MF field, or nested lists and tuples."""
    if isinstance(value, str) and value.strip()[:1] == "[":
        value = value.replace("[", " ").replace("]", " ")
    if isinstance(value, (list, tuple)):
        found = []
        for item in value:
            found.extend(_numbers(item))
        return found
    return _plain(value)


_plain = _judge._numbers


def judge(x3d_path, trace, **options):
    """``behaviour_sim_judge.judge`` with MF values readable."""
    original = _judge._numbers
    _judge._numbers = _numbers
    try:
        return _judge.judge(x3d_path, trace, **options)
    finally:
        _judge._numbers = original


if __name__ == "__main__":
    result = judge(sys.argv[1], json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")))
    print(json.dumps(result, indent=1))
    sys.exit(0 if result.get("agree") else 1)
