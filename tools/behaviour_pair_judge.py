# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Do two X3D files behave the same in X_ITE? A comparison that measures its own noise floor.

    python3 tools/behaviour_pair_judge.py a.x3d b.x3d [--stimulus s.json] [--repeats 3] [--x-ite DIST] [--out verdict.json]

    from behaviour_pair_judge import judge_pair
    verdict = judge_pair("a.x3d", "b.x3d", {"seconds": 4}, repeats=3, x_ite="/path/to/x_ite/dist")

Both files are replayed in X_ITE (headless Chromium, software GL, through tools/behaviour_sim_judge.cjs, the page code the
simulator judge records with), ``repeats`` times each, interleaved A B A B ..., under the same stimulus. The streams
watched are the fields that ROUTEs end at in the scene (a Transform's translation, a Coordinate's point, ...), matched
between the two files by DEF and field name; a stream only one file has is listed under "unmatched", not judged.

Each run is cut into samples every ``step`` seconds from its own time zero (the first start of a TimeSensor, which is where an animation a
click starts really begins; else the first press of a pointing sensor; else the first cycle start of a TimeSensor, which
lines up a looping timer whose phase depends on the wall clock; else the moment recording began), holding the last value. Two runs are compared sample by sample: a sample is "outside" when any
number differs by more than ``tolerance`` times that stream's span (largest minus smallest value seen in any run). Per
stream, from the same session:

    a_vs_b      the fraction of samples outside, and the largest absolute difference, for every A-run against every B-run
    floor       the same two numbers for A-run against A-run and B-run against B-run (what a file does against itself)
    verdict     "same"     the middle A-versus-B pairing is no worse than the worst repeat-against-repeat pairing
                "differs"  EVERY A-versus-B pairing is above the typical (median) repeat-against-repeat pairing by
                           ``margin`` times (default 3) and by at least ``min_abs`` (default 0.01) of the samples
                "unclear"  anything else (including a stream no run ever sent)
    overall     "differs" if any stream differs, else "unclear" if any is unclear, else "same"

The result also holds machine load (os.getloadavg before and after every run), X_ITE and browser versions, the
tolerances and every raw per-pairing number. CLI exit codes: 0 same, 1 differs, 2 unclear, 3 tool error (Node,
Playwright, Chromium, X_ITE or a file is missing, or a stimulus call cannot be replayed); the CLI prints the same dict as
JSON on stdout ({"verdict": "error", "error": ...} for a tool error). Importing this module starts nothing.

Stimulus (None, a dict, a path to a JSON file holding one, or a recorded list):
    None, {"seconds": 4}                load, run, sample (a timer-only world: no pointer at all)
    {"clicks": 2, "hold": [140, 4000], "gap": 1100, "seconds": 4}
                                        the pointer hunts for a pointing sensor and clicks it that many times (the judge's
                                        own click mode: --hold, --gap); "seconds" is the wait after the last click
    {"click_plan": ["Sensor1", ...], "seconds": 3}        each named sensor is found and clicked once (140 ms)
    {"drags": "drags.json" | {...}, "seconds": 2}         real drags (the file format of tools/behaviour_sim_judge.cjs)
    {"keys": "keys.json" | {...}, "seconds": 2}           real typing (same)
    [{"time": 1.0, "call": "click", "node": "Click", "args": []}, ...]   the recorded activity format. Replayable:
        "start" (loading is the start), "click", and "press" followed by "release" of the same sensor (a held click: the
        gap between them is the hold). Every other call (hover, drag, send, post, step, key, viewer, ...) cannot be made in
        X_ITE by this tool and is a tool error, never skipped. The clicks are made with the judge's click mode, which
        finds a sensor by moving the pointer, so a recorded list is accepted only when it names one sensor and the file
        has no other pointing sensor; the times set the holds and the gap between clicks, not absolute moments.
"""

import argparse
import bisect
import json
import math
import os
import pathlib
import statistics
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "source"))
import behaviour_graph as bg          # noqa: E402

JUDGE_CJS = HERE / "behaviour_sim_judge.cjs"
POINTING = ("TouchSensor", "PlaneSensor", "CylinderSensor", "SphereSensor")
EXIT = {"same": 0, "differs": 1, "unclear": 2, "error": 3}


class PairJudgeError(RuntimeError):
    """The tool could not run (CLI exit 3): Node, Playwright, Chromium, X_ITE or a file is missing, a stimulus call
    cannot be replayed, or a browser run failed."""


# -- pure parts: samples, pairings, verdicts ---------------------------------------------------------------------------

def flat(value):
    """A recorded value as a tuple of numbers (booleans are 0 and 1; X_ITE's text for vectors and MF lists is read as
    numbers in order), or ``("s", text)`` for text that is not numbers; ``None`` stays ``None``."""
    if value is None:
        return None
    if isinstance(value, bool):
        return (1.0 if value else 0.0,)
    if isinstance(value, (int, float)):
        return (float(value),)
    if isinstance(value, (list, tuple)):
        found = []
        for item in value:
            part = flat(item)
            if part is None or part[:1] == ("s",):
                return ("s", str(value))
            found.extend(part)
        return tuple(found)
    text = str(value)
    tokens = text.replace("[", " ").replace("]", " ").replace(",", " ").split()
    if len(tokens) == 1 and tokens[0] in ("true", "false", "TRUE", "FALSE"):
        return (1.0 if tokens[0].lower() == "true" else 0.0,)
    try:
        return tuple(float(token) for token in tokens)
    except ValueError:
        return ("s", text)


def sample(initial, events, grid):
    """The value of one stream at each time of ``grid`` (seconds from the run's time zero): the last event at or before
    it, else ``initial`` (what the field held when recording began; ``None`` if unknown). ``events`` is [(time, value)]."""
    ordered = sorted(events, key=lambda event: event[0])
    times = [t for t, _ in ordered]
    held = flat(initial)
    out = []
    for when in grid:
        i = bisect.bisect_right(times, when + 1e-9)
        out.append(flat(ordered[i - 1][1]) if i else held)
    return out


def span_of(runs):
    """The largest minus smallest number seen anywhere in the sampled ``runs`` of one stream (0 when none vary)."""
    low, high = math.inf, -math.inf
    for series in runs:
        for value in series:
            if value is not None and value[:1] != ("s",):
                for number in value:
                    low, high = min(low, number), max(high, number)
    return high - low if high >= low else 0.0


def compare(series_a, series_b, tolerance):
    """(fraction of samples outside ``tolerance``, largest absolute difference, samples with no number to compare).
    A sample where one run has a value and the other none, or the lists differ in length, or the text differs, is outside."""
    outside = worst = unmatched = 0
    for a, b in zip(series_a, series_b):
        if a is None and b is None:
            continue
        if a is None or b is None or len(a) != len(b) or a[:1] == ("s",) or b[:1] == ("s",):
            if a is not None and a == b:
                continue
            outside += 1
            unmatched += 1
            continue
        gap = max((abs(x - y) for x, y in zip(a, b)), default=0.0)
        worst = max(worst, gap)
        outside += gap > tolerance
    count = min(len(series_a), len(series_b))
    return (outside / count if count else 0.0), worst, unmatched


def verdict_of(ab_fractions, floor_fractions, margin=3.0, min_abs=0.01):
    """("same" | "differs" | "unclear", threshold) from the A-versus-B fractions of every pairing and the floor's
    (A against A, B against B pooled). "same" needs the middle A-versus-B pairing no worse than the worst floor pairing
    (so a noisy session cannot make two equal files differ); "differs" needs EVERY A-versus-B pairing above
    max(margin x typical floor, typical floor + min_abs), the typical floor being the median floor pairing, so that one bad
    repeat (which spoils some pairings of both kinds) neither hides a real difference nor invents one."""
    typical = statistics.median(floor_fractions) if floor_fractions else 0.0
    worst = max(floor_fractions, default=0.0)
    threshold = max(margin * typical, typical + min_abs)
    if not ab_fractions:
        return "unclear", threshold
    if all(f > threshold for f in ab_fractions):
        return "differs", threshold
    if statistics.median(ab_fractions) <= worst:
        return "same", threshold
    return "unclear", threshold


def judge_streams(runs_a, runs_b, tolerance=0.02, margin=3.0, min_abs=0.01):
    """One stream. ``runs_a`` and ``runs_b``: a sampled series (``sample``) per repeat. Returns the stream's numbers and
    verdict. ``tolerance`` is a fraction of the stream's span."""
    span = span_of(list(runs_a) + list(runs_b))
    tol = max(tolerance * span, 1e-6)
    pairs = lambda x, y: [compare(a, b, tol) for a in x for b in y]                    # noqa: E731
    within = lambda runs: [compare(runs[i], runs[j], tol) for i in range(len(runs)) for j in range(i + 1, len(runs))]  # noqa: E731
    ab, aa, bb = pairs(runs_a, runs_b), within(runs_a), within(runs_b)
    silent = span_of(list(runs_a) + list(runs_b)) == 0 and all(value is None for series in list(runs_a) + list(runs_b)
                                                               for value in series)
    verdict, threshold = ("unclear", None) if silent else verdict_of([r[0] for r in ab], [r[0] for r in aa + bb], margin, min_abs)
    numbers = lambda rows: {"fraction": [round(r[0], 6) for r in rows], "max_abs": [round(r[1], 6) for r in rows],  # noqa: E731
                            "unmatched": [r[2] for r in rows]}
    return {"verdict": verdict, "reason": "no run ever sent this stream" if silent else None, "span": span,
            "tolerance_abs": tol, "threshold": threshold, "a_vs_b": numbers(ab), "a_vs_a": numbers(aa), "b_vs_b": numbers(bb),
            "floor": max([r[0] for r in aa + bb], default=0.0),
            "floor_typical": statistics.median([r[0] for r in aa + bb]) if aa + bb else 0.0, "floor_max_abs": max([r[1] for r in aa + bb], default=0.0)}


def overall(verdicts):
    if "differs" in verdicts:
        return "differs"
    if "unclear" in verdicts or not verdicts:
        return "unclear"
    return "same"


# -- stimulus --------------------------------------------------------------------------------------------------------------

def normalise_stimulus(stimulus):
    """A dict of the judge's options from whatever the caller gave; raises PairJudgeError for what cannot be replayed."""
    if isinstance(stimulus, (str, os.PathLike)):
        try:
            stimulus = json.loads(pathlib.Path(stimulus).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise PairJudgeError(f"stimulus file {stimulus}: {error}") from error
    if stimulus is None:
        return {"seconds": 4.0}
    if isinstance(stimulus, dict):
        known = {"seconds", "clicks", "hold", "gap", "click_plan", "drags", "keys"}
        unknown = sorted(set(stimulus) - known)
        if unknown:
            raise PairJudgeError(f"stimulus keys not understood: {unknown}")
        out = dict(stimulus)
        out["seconds"] = float(out.get("seconds", 4.0))
        return out
    if isinstance(stimulus, list):
        return _from_recorded(stimulus)
    raise PairJudgeError(f"stimulus must be None, a dict, a path or a list, not {type(stimulus).__name__}")


def _from_recorded(steps):
    """The recorded activity format [{time, call, node, args}] as the judge's click mode: clicks and held presses."""
    clicks, nodes, down, last = [], set(), None, None
    for step in sorted(steps, key=lambda s: s.get("time", 0)):
        call, node, when = step.get("call"), step.get("node"), float(step.get("time", 0))
        if call == "start":
            continue
        if call == "click":
            clicks.append((when, 140.0)); nodes.add(node)
        elif call == "press":
            if down is not None:
                raise PairJudgeError(f"press of {node!r} at {when} while {down[1]!r} is still held")
            down = (when, node); nodes.add(node)
        elif call == "release":
            if down is None or down[1] != node:
                raise PairJudgeError(f"release of {node!r} at {when} without a press of it")
            clicks.append((down[0], max(1.0, (when - down[0]) * 1000.0))); down = None
        else:
            raise PairJudgeError(f"the recorded call {call!r} (node {node!r}, time {when}) cannot be replayed in X_ITE by "
                                 "this tool: only start, click, and press followed by release can")
        last = when
    if down is not None:
        raise PairJudgeError(f"press of {down[1]!r} at {down[0]} is never released")
    if len(nodes) > 1:
        raise PairJudgeError(f"the recorded stimulus names several sensors {sorted(map(str, nodes))}; the click mode finds one")
    if not clicks:
        return {"seconds": 4.0}
    gaps = [b[0] - a[0] - a[1] / 1000.0 for a, b in zip(clicks, clicks[1:])]
    out = {"clicks": len(clicks), "hold": [round(h) for _, h in clicks], "seconds": 3.0, "only_sensor": next(iter(nodes))}
    if gaps:
        out["gap"] = max(300, round(statistics.median(gaps) * 1000))
    return out


# -- recording --------------------------------------------------------------------------------------------------------------

def _graph(path):
    try:
        return bg.Behaviour.from_x3d(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, bg.BehaviourError) as error:
        raise PairJudgeError(f"{path}: {error}") from error


def watched(graph):
    """{(DEF, field): the field as X_ITE names it} for every ROUTE that ends at a scene node (a target, not a behaviour node)."""
    found = {}
    for route in graph.routes:
        node = graph.nodes.get(route.to_id)
        if node is None or node.role != bg.TARGET:
            continue
        try:
            field = bg.resolve_field(node.node_type, route.to_field, "in")[0]
        except bg.BehaviourError:
            field = route.to_field
        found[(route.to_id, field)] = field
    return found


def _extras(graph):
    """Fields recorded only to find time zero: a pointing sensor's isActive and a TimeSensor's cycleTime."""
    return [[n.id, "isActive"] for n in graph.nodes.values() if n.node_type in POINTING] + \
           [[n.id, "isActive"] for n in graph.nodes.values() if n.node_type == "TimeSensor"] + \
           [[n.id, "cycleTime"] for n in graph.nodes.values() if n.node_type == "TimeSensor"]


def _node_env():
    env = dict(os.environ)
    if "NODE_PATH" not in env:
        try:
            env["NODE_PATH"] = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, timeout=30).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return env


def browser_version():
    """Chromium's version as Playwright launches it (None if it cannot be launched)."""
    try:
        done = subprocess.run(["node", "-e", "const {chromium}=require('playwright');chromium.launch().then(async b=>{"
                              "console.log(b.version());await b.close()})"], capture_output=True, text=True, timeout=120,
                              env=_node_env())
        return done.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def record(file, sources, stimulus, x_ite, scratch, timeout=240):
    """One run of ``file`` in X_ITE: the judge's trace (events at ``sources``, with X_ITE's time stamps)."""
    scratch = pathlib.Path(scratch)
    sources_file = scratch / "sources.json"
    sources_file.write_text(json.dumps(sources), encoding="utf-8")
    command = ["node", str(JUDGE_CJS), str(x_ite), str(pathlib.Path(file).resolve()), str(sources_file)]
    seconds = str(stimulus["seconds"])
    flags = []
    if stimulus.get("click_plan"):
        plan = scratch / "plan.json"
        plan.write_text(json.dumps(stimulus["click_plan"]), encoding="utf-8")
        command += ["0", seconds, "--click-plan", str(plan)]
    elif stimulus.get("keys"):
        keys = _as_file(stimulus["keys"], scratch / "keys.json")
        command += ["0", seconds, "--keys", keys]
    elif stimulus.get("drags"):
        command += ["0", seconds, _as_file(stimulus["drags"], scratch / "drags.json")]
    else:
        command += [str(int(stimulus.get("clicks", 0))), seconds]
        if stimulus.get("clicks"):
            flags += ["--hold=" + ",".join(str(h) for h in stimulus.get("hold", [140]))]
            if stimulus.get("gap"):
                flags += [f"--gap={int(stimulus['gap'])}"]
    try:
        done = subprocess.run(command + flags, capture_output=True, text=True, timeout=timeout, env=_node_env())
    except FileNotFoundError as error:
        raise PairJudgeError("node is not installed") from error
    except subprocess.TimeoutExpired as error:
        raise PairJudgeError(f"X_ITE run of {file} took more than {timeout} s") from error
    if done.returncode != 0 or not done.stdout.strip():
        raise PairJudgeError(f"browser run of {file} failed: {(done.stderr or done.stdout).strip()[-600:]}")
    try:
        return json.loads(done.stdout)
    except ValueError as error:
        raise PairJudgeError(f"browser run of {file} printed no trace: {done.stdout[-300:]}") from error


def _as_file(value, target):
    if isinstance(value, (str, os.PathLike)):
        return str(value)
    target.write_text(json.dumps(value), encoding="utf-8")
    return str(target)


def _zero(trace, timers):
    """(time zero of a run, what it was taken from): the first start of a TimeSensor (``timers``: their DEFs) after
    recording began, which is where an animation a click starts really begins; else the first press of a pointing sensor;
    else the first cycle start of a TimeSensor (a looping timer's phase depends on the wall clock); else the moment
    recording began."""
    started = [e[0] for e in trace["events"] if e[1] in timers and e[2] == "isActive" and str(e[3]).lower() == "true"]
    if started:
        return min(started), "first timer start"
    pressed = [e[0] for e in trace["events"] if e[1] not in timers and e[2] == "isActive" and str(e[3]).lower() == "true"]
    if pressed:
        return min(pressed), "first press"
    cycles = [e[0] for e in trace["events"] if e[2] == "cycleTime"]
    if cycles:
        return min(cycles), "first cycle start"
    return trace["began"], "recording start"


def judge_pair(file_a, file_b, stimulus=None, repeats=3, x_ite=None, *, tolerance=0.02, margin=3.0, min_abs=0.01, step=0.05,
               timeout=240):
    """Replay ``file_a`` and ``file_b`` ``repeats`` times each in X_ITE, interleaved A B A B ..., and return the verdict
    dict described in the module text. Needs ``repeats`` >= 2 (the floor is measured from the repeats). Raises
    ``PairJudgeError`` when the tool cannot run."""
    if repeats < 2:
        raise PairJudgeError("repeats must be at least 2: the noise floor is measured from the repeats")
    x_ite = x_ite or os.environ.get("X_ITE_DIST")
    if not x_ite or not (pathlib.Path(x_ite) / "x_ite.min.js").is_file():
        raise PairJudgeError("X_ITE dist directory not found (pass x_ite=... or set X_ITE_DIST; it holds x_ite.min.js)")
    for path in (file_a, file_b):
        if not pathlib.Path(path).is_file():
            raise PairJudgeError(f"{path}: no such file")
    stim = normalise_stimulus(stimulus)
    graph_a, graph_b = _graph(file_a), _graph(file_b)
    wa, wb = watched(graph_a), watched(graph_b)
    common = sorted(set(wa) & set(wb))
    unmatched = {"only_in_a": [f"{d}.{f}" for d, f in sorted(set(wa) - set(wb))],
                 "only_in_b": [f"{d}.{f}" for d, f in sorted(set(wb) - set(wa))]}
    if stim.get("only_sensor"):
        for graph, name in ((graph_a, "a"), (graph_b, "b")):
            sensors = [n.id for n in graph.nodes.values() if n.node_type in POINTING]
            if sensors != [stim["only_sensor"]]:
                raise PairJudgeError(f"the recorded stimulus clicks {stim['only_sensor']!r} but file {name} has pointing "
                                     f"sensors {sensors}")
    if not common:
        raise PairJudgeError("the two files have no ROUTE target in common (same DEF and field): nothing to compare")
    load, traces = [], {"a": [], "b": []}
    with tempfile.TemporaryDirectory(prefix="pair-judge-") as scratch:
        for _ in range(repeats):
            for name, path, graph in (("a", file_a, graph_a), ("b", file_b, graph_b)):
                before = os.getloadavg()
                sources = [list(key) for key in common] + _extras(graph)
                trace = record(path, sources, stim, x_ite, scratch, timeout)
                load.append({"file": name, "before": before, "after": os.getloadavg()})
                traces[name].append(trace)
    # sample every run from its own time zero over the time every run covers
    timers = {n.id for graph in (graph_a, graph_b) for n in graph.nodes.values() if n.node_type == "TimeSensor"}
    zeros = {n: [_zero(t, timers) for t in traces[n]] for n in traces}
    ends = [max(t["frames"]) - z[0] for n in traces for t, z in zip(traces[n], zeros[n]) if t["frames"]]
    horizon = min(ends) if ends else 0.0
    grid = [i * step for i in range(int(horizon / step) + 1)]
    streams, unobservable = [], []
    for d, f in common:
        sampled = {}
        for n in traces:
            sampled[n] = []
            for trace, (zero, _) in zip(traces[n], zeros[n]):
                if any(m[0] == d and m[1] == f for m in trace.get("missing", [])):
                    unobservable.append(f"{d}.{f} ({n})")
                events = [(e[0] - zero, e[3]) for e in trace["events"] if e[1] == d and e[2] == f]
                initial = next((i[2] for i in trace.get("initial", []) if i[0] == d and i[1] == f), None)
                sampled[n].append(sample(initial, events, grid))
        result = judge_streams(sampled["a"], sampled["b"], tolerance, margin, min_abs)
        result["stream"] = f"{d}.{f}"
        result["events"] = {n: [sum(1 for e in t["events"] if e[1] == d and e[2] == f) for t in traces[n]] for n in traces}
        if not any(result["events"]["a"]) and not any(result["events"]["b"]):
            result["verdict"], result["reason"] = "unclear", "no run ever sent this stream"
        streams.append(result)
    unmatched["unobservable"] = sorted(set(unobservable))
    flat_load = [v for row in load for v in row["before"][:1] + row["after"][:1]]
    return {
        "verdict": overall([s["verdict"] for s in streams]),
        "files": {"a": str(file_a), "b": str(file_b)}, "stimulus": stim, "repeats": repeats,
        "x_ite": traces["a"][0]["browser"], "x_ite_dist": str(x_ite), "browser": browser_version(),
        "instrument": "tools/behaviour_pair_judge.py, headless Chromium with software GL",
        "tolerance": {"fraction_of_span": tolerance, "margin": margin, "min_abs": min_abs, "sample_step_s": step,
                      "samples": len(grid), "horizon_s": round(horizon, 3)},
        "load": {"max_1min": max(flat_load), "runs": load},
        "time_zero": {n: [{"time": round(z, 3), "from": how} for z, how in zeros[n]] for n in zeros},
        "page_errors": {n: [t.get("pageErrors", []) for t in traces[n]] for n in traces},
        "unmatched": unmatched, "streams": streams,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                     epilog="exit codes: 0 same, 1 differs, 2 unclear, 3 tool error")
    parser.add_argument("file_a")
    parser.add_argument("file_b")
    parser.add_argument("--stimulus", help="JSON file: a dict, or the recorded list (see the module text); default: run 4 s")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--x-ite", help="X_ITE dist directory (default: $X_ITE_DIST)")
    parser.add_argument("--out", help="also write the verdict JSON here")
    args = parser.parse_args(argv)
    try:
        result = judge_pair(args.file_a, args.file_b, args.stimulus, args.repeats, args.x_ite)
    except PairJudgeError as error:
        result = {"verdict": "error", "error": str(error)}
    text = json.dumps(result, indent=1)
    print(text)
    if args.out:
        pathlib.Path(args.out).write_text(text + "\n", encoding="utf-8")
    return EXIT[result["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
