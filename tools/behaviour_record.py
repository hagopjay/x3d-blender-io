# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Record everything a behaviour world does when it is given a script of pointer and key calls: pure Python, no Blender.

    python3 tools/behaviour_record.py door.x3d --script door.stimulus.json --seconds 4 --out door.activity.json

``--script`` is a JSON list of ``{"time": seconds, "call": "press", "node": "Click", "args": {...}}`` (calls: click,
press, drag, release, hover, key, viewer, post; arguments as ``Simulation`` takes them, tuples as lists). The tool starts
the simulation at 0, steps it every 1/``--fps`` s up to ``--seconds`` (a scripted call at a time happens before the
step at that time) and writes ``Activity.report()`` with the full trace and the complete stimulus (start and steps
included): ``trace`` is every delivery, in order, as ``[time, from, from_field, to, to_field, type, value]``. The file
replays: ``behaviour_activity.replay(Simulation(graph), report["stimulus"])`` sends the same events.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "source"))
import behaviour_activity as ba   # noqa: E402
import behaviour_graph as bg      # noqa: E402
import behaviour_sim as bs        # noqa: E402


def record(x3d_text, script, seconds=4.0, fps=60.0, world=None):
    """The Activity of ``x3d_text`` run for ``seconds`` with ``script`` (a list of call dicts)."""
    graph = bg.Behaviour.from_x3d(x3d_text)
    sim = bs.Simulation(graph, log_size=1_000_000)
    activity = ba.Activity.from_simulation(sim, record=True, world=world)
    calls = [(0.0, 0, {"time": 0.0, "call": "start", "node": None, "args": {}})]
    for index, call in enumerate(script):
        calls.append((float(call["time"]), 1 + index, call))
    for frame in range(1, int(round(seconds * fps)) + 1):
        calls.append((frame / fps, 10 ** 9 + frame, {"time": frame / fps, "call": "step", "node": None, "args": {}}))
    calls.sort(key=lambda item: (item[0], item[1]))           # a scripted call goes before the step at its time
    for _when, _order, call in calls:
        activity.drive(sim, call["call"], call.get("node"), float(call["time"]), **(call.get("args") or {}))
    return activity


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("world", help="an .x3d file with a behaviour graph")
    parser.add_argument("--script", help="JSON list of calls (default: none, the world runs by itself)")
    parser.add_argument("--seconds", type=float, default=4.0)
    parser.add_argument("--fps", type=float, default=60.0)
    parser.add_argument("--out", required=True, help="where to write the recording (JSON)")
    args = parser.parse_args(argv)
    script = json.loads(Path(args.script).read_text(encoding="utf-8")) if args.script else []
    activity = record(Path(args.world).read_text(encoding="utf-8"), script, args.seconds, args.fps,
                      world=Path(args.world).name)
    report = activity.report()
    Path(args.out).write_text(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{args.out}: {report['events']} events, {report['deliveries']} deliveries, "
          f"{len(report['stimulus'])} calls, {Path(args.out).stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
