# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Do two X3D files behave the same in X_ITE? A comparison that measures its own noise floor.

    python3 tools/behaviour_pair_judge.py a.x3d b.x3d [--stimulus s.json] [--repeats 3] [--mode auto|simultaneous|sequential] [--x-ite DIST] [--out verdict.json]

    from behaviour_pair_judge import judge_pair
    verdict = judge_pair("a.x3d", "b.x3d", {"seconds": 4}, repeats=3, x_ite="/path/to/x_ite/dist")

Both files are replayed in X_ITE (headless Chromium, software GL, through tools/behaviour_sim_judge.cjs, the page code the
simulator judge records with), ``repeats`` times each, under the same stimulus. The streams watched are the fields that
ROUTEs end at in the scene (a Transform's translation, a Coordinate's point, ...), matched between the two files by DEF and
field name; a stream only one file has is listed under "unmatched", not judged. A stream whose values are nodes (SFNode,
MFNode: a rigid body's set_contacts, ...) has no numbers to compare and is listed under "skipped", with the reason.

Two ways to line the runs up in time (``mode``):

    "simultaneous"  (the default for a world nobody touches: no clicks, plan, drags or keys) every pairing is run at the same
                    moment, in two browsers started together, and compared at the same X_ITE time stamps (X_ITE's own clock
                    is the wall clock, shared by both browsers). Why: in X_ITE a looping TimeSensor with startTime 0 takes
                    its phase from the wall clock (a cycle starts at every whole multiple of cycleInterval since 1970), so two
                    runs a few seconds apart are at different points of the loop, and a world with several loops (3, 5, 7 s)
                    has no one moment to line everything up on. Run together, equal loops are in equal phase by themselves.
                    Per repeat three pairs run: A with B (the A-versus-B pairing), A with A and B with B (the floor).
                    Pointer stimuli cannot be made at the same moment in two browsers: asking for them is a tool error.
    "sequential"    (the default when the stimulus has a pointer, key or drag) runs A and B alternately, A B A B ..., and cuts
                    each run into samples from its own time zero (see below). It is the mode for a world that starts on
                    a click, where "time zero" is the click; it cannot tell a free-running loop apart from noise unless a
                    cycle start falls in the watch.

Sequential runs are cut into samples every ``step`` seconds from the run's own time zero (the first start of a TimeSensor, which is where an animation a
click starts really begins; else the first press of a pointing sensor; else the first cycle start of a TimeSensor, which
lines up a looping timer whose phase depends on the wall clock; else the moment recording began), holding the last value;
simultaneous runs from the later of the two recording starts. Two runs are compared sample by sample: a sample is "outside" when any
number differs by more than ``tolerance`` times that stream's span (largest minus smallest value seen in any run). A
rotation stream (SFRotation, MFRotation) is not compared number by number (0 1 0 6.17 and 0 -1 0 0.11 are 0.003 rad
apart as rotations) but by the angle between the two rotations, in radians; its span is the widest angle any run sweeps from
its first value, and ``tolerance_abs`` is then in radians (the result says so in ``tolerance_unit``). Per
stream, from the same session:

    a_vs_b      the fraction of samples outside, and the largest absolute difference, for every A-run against every B-run
    floor       the same two numbers for A-run against A-run and B-run against B-run (what a file does against itself)
    verdict     "same"     the middle A-versus-B pairing is no worse than the worst repeat-against-repeat pairing
                "differs"  EVERY A-versus-B pairing is above the typical (median) repeat-against-repeat pairing by
                           ``margin`` times (default 3) and by at least ``min_abs`` (default 0.01) of the samples
                "unclear"  anything else (including a stream no run ever sent), and always when the judge is BLIND:
                           the median floor pairing has ``blind`` (default 0.5) or more of its samples outside, so a file
                           disagrees with itself on half the samples or more and nothing can be told from the comparison.
                           Then the stream's ``reason`` is "blind" (``detail`` has the numbers); "same" is impossible
    overall     "differs" if any stream differs, else "unclear" if any is unclear, else "same"; ``reason`` is "blind"
                when the overall verdict is unclear and any stream is blind

The result also holds machine load (os.getloadavg before and after every run), X_ITE and browser versions, the
tolerances and every raw per-pairing number. CLI exit codes: 0 same, 1 differs, 2 unclear (blind included), 3 tool error (Node,
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
import re
import statistics
import subprocess
import sys
import tempfile
import concurrent.futures

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


def rotation_distance(a, b):
    """The angle in radians between two axis-angle rotations (x, y, z, angle): the same maths as
    behaviour_sim._rotation_distance, so q and -q, and an axis flipped with a negated angle, are the same rotation
    (0 1 0 6.17 and 0 -1 0 0.11 are 0.003 rad apart). A zero axis is no turn."""
    def quaternion(rotation):
        x, y, z, angle = rotation
        length = math.sqrt(x * x + y * y + z * z)
        if length == 0:
            return (0.0, 0.0, 0.0, 1.0)
        s = math.sin(angle / 2) / length
        return (x * s, y * s, z * s, math.cos(angle / 2))
    qa, qb = quaternion(a), quaternion(b)
    return 2 * math.acos(min(1.0, abs(sum(x * y for x, y in zip(qa, qb)))))


def _gap(a, b, rotation):
    """The distance between two numeric samples of equal length: the largest absolute difference, or for a rotation stream
    the largest angle between corresponding rotations (4 numbers each), in radians."""
    if rotation and len(a) % 4 == 0:
        return max((rotation_distance(a[i:i + 4], b[i:i + 4]) for i in range(0, len(a), 4)), default=0.0)
    return max((abs(x - y) for x, y in zip(a, b)), default=0.0)


def span_of(runs, rotation=False):
    """The largest minus smallest number seen anywhere in the sampled ``runs`` of one stream (0 when none vary). For a
    ``rotation`` stream: the widest angle in radians any sample is from the first value seen."""
    if rotation:
        first = next((v for series in runs for v in series if v is not None and v[:1] != ("s",) and len(v) % 4 == 0), None)
        if first is None:
            return 0.0
        return max((_gap(v, first, True) for series in runs for v in series
                    if v is not None and v[:1] != ("s",) and len(v) == len(first)), default=0.0)
    low, high = math.inf, -math.inf
    for series in runs:
        for value in series:
            if value is not None and value[:1] != ("s",):
                for number in value:
                    low, high = min(low, number), max(high, number)
    return high - low if high >= low else 0.0


def compare(series_a, series_b, tolerance, rotation=False):
    """(fraction of samples outside ``tolerance``, largest difference, samples with no number to compare).
    A sample where one run has a value and the other none, or the lists differ in length, or the text differs, is outside.
    ``rotation``: differences are angles between rotations, in radians, ``tolerance`` too."""
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
        gap = _gap(a, b, rotation)
        worst = max(worst, gap)
        outside += gap > tolerance
    count = min(len(series_a), len(series_b))
    return (outside / count if count else 0.0), worst, unmatched


def verdict_of(ab_fractions, floor_fractions, margin=3.0, min_abs=0.01):
    """("same" | "differs" | "unclear", threshold) from the A-versus-B fractions of every pairing and the floor's
    (A against A, B against B pooled). "same" needs the middle A-versus-B pairing no worse than the worst floor pairing
    (so a noisy session cannot make two equal files differ); "differs" needs EVERY A-versus-B pairing above
    max(margin x typical floor, typical floor + min_abs), the typical floor being the median floor pairing, so that one bad
    repeat (which spoils some pairings of both kinds) neither hides a real difference nor invents one. A blind floor is
    judged by ``judge_pairings``, not here."""
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


BLIND = 0.5


def judge_pairings(ab_pairs, aa_pairs, bb_pairs, tolerance=0.02, margin=3.0, min_abs=0.01, blind=BLIND, rotation=False):
    """One stream, from pairings that were measured together: ``ab_pairs``, ``aa_pairs``, ``bb_pairs`` are lists of
    (series, series), each series sampled on one grid (``sample``). Returns the stream's numbers and verdict.
    ``tolerance`` is a fraction of the stream's span (of the widest angle swept, for a ``rotation`` stream, then in
    radians). Blind: when the median floor pairing has ``blind`` or more of its samples outside, the verdict is
    "unclear" with reason "blind", whatever the A-versus-B numbers say."""
    every = [s for pair in list(ab_pairs) + list(aa_pairs) + list(bb_pairs) for s in pair]
    span = span_of(every, rotation)
    tol = max(tolerance * span, 1e-6)
    ab = [compare(x, y, tol, rotation) for x, y in ab_pairs]
    aa = [compare(x, y, tol, rotation) for x, y in aa_pairs]
    bb = [compare(x, y, tol, rotation) for x, y in bb_pairs]
    floor = [r[0] for r in aa + bb]
    typical = statistics.median(floor) if floor else 0.0
    silent = span == 0 and all(value is None for series in every for value in series)
    verdict, threshold = ("unclear", None) if silent else verdict_of([r[0] for r in ab], floor, margin, min_abs)
    reason, detail = ("no run ever sent this stream" if silent else None), None
    if not silent and floor and typical >= blind:
        verdict, reason = "unclear", "blind"
        detail = (f"the median file-against-itself pairing has {typical:.3f} of its samples outside tolerance, at or above the "
                  f"blind limit {blind}: the runs were not lined up, or the stream is too noisy, to tell anything")
    numbers = lambda rows: {"fraction": [round(r[0], 6) for r in rows], "max_abs": [round(r[1], 6) for r in rows],  # noqa: E731
                            "unmatched": [r[2] for r in rows]}
    return {"verdict": verdict, "reason": reason, "detail": detail, "span": span, "tolerance_abs": tol,
            "tolerance_unit": "rad" if rotation else "value", "threshold": threshold,
            "a_vs_b": numbers(ab), "a_vs_a": numbers(aa), "b_vs_b": numbers(bb),
            "floor": max(floor, default=0.0), "floor_typical": typical, "floor_max_abs": max([r[1] for r in aa + bb], default=0.0),
            "blind_limit": blind}


def judge_streams(runs_a, runs_b, tolerance=0.02, margin=3.0, min_abs=0.01, blind=BLIND, rotation=False):
    """One stream from repeats (the sequential layout). ``runs_a`` and ``runs_b``: a sampled series (``sample``) per repeat;
    every A against every B, and every repeat against every other of the same file, are the pairings."""
    within = lambda runs: [(runs[i], runs[j]) for i in range(len(runs)) for j in range(i + 1, len(runs))]  # noqa: E731
    return judge_pairings([(a, b) for a in runs_a for b in runs_b], within(runs_a), within(runs_b), tolerance, margin, min_abs,
                          blind, rotation)


def overall(verdicts):
    if "differs" in verdicts:
        return "differs"
    if "unclear" in verdicts or not verdicts:
        return "unclear"
    return "same"


def overall_reason(streams):
    """Why the overall verdict is unclear: "blind" when any stream is blind, else the first stream reason, else None."""
    if overall([s["verdict"] for s in streams]) != "unclear":
        return None
    if any(s.get("reason") == "blind" for s in streams):
        return "blind"
    return next((s["reason"] for s in streams if s.get("reason")), "no comparable stream" if not streams else None)


NODE_TYPES = ("SFNode", "MFNode")
_NODE_TEXT = re.compile(r"^\s*(NULL|\[?\s*[A-Z][A-Za-z0-9_]*\s*\{)")


def looks_like_node(text):
    """Whether X_ITE's text for a value is a node ("Shape { }", "[ Box { } ]", "NULL")."""
    return bool(_NODE_TEXT.match(str(text)))


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


def field_types(graph):
    """{(DEF, field): the X3D field type} of the same fields ``watched`` lists, "?" where the node type is not in the
    catalogue (then the type is not known and the values are looked at instead)."""
    found = {}
    for route in graph.routes:
        node = graph.nodes.get(route.to_id)
        if node is None or node.role != bg.TARGET:
            continue
        try:
            field, kind = bg.resolve_field(node.node_type, route.to_field, "in")
        except bg.BehaviourError:
            field, kind = route.to_field, "?"
        found[(route.to_id, field)] = kind
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


def _pointer(stim):
    return bool(stim.get("clicks") or stim.get("click_plan") or stim.get("drags") or stim.get("keys"))


def record_together(files, sources, stimulus, x_ite, scratch, timeout=240):
    """The runs of ``files`` (a list) at the same moment, one browser each, started together: the list of traces."""
    scratch = pathlib.Path(scratch)
    folders = []
    for i in range(len(files)):
        folder = scratch / f"together-{i}"
        folder.mkdir(exist_ok=True)
        folders.append(folder)
    with concurrent.futures.ThreadPoolExecutor(len(files)) as pool:
        futures = [pool.submit(record, f, src, stimulus, x_ite, folder, timeout) for f, src, folder in zip(files, sources, folders)]
        return [f.result() for f in futures]


SLACK = 2.0


def judge_pair(file_a, file_b, stimulus=None, repeats=3, x_ite=None, *, tolerance=0.02, margin=3.0, min_abs=0.01, step=0.05,
               timeout=240, mode="auto", blind=BLIND):
    """Replay ``file_a`` and ``file_b`` ``repeats`` times each in X_ITE and return the verdict dict described in the module
    text. ``mode``: "simultaneous" (A with B, A with A and B with B run at the same moment, every repeat), "sequential"
    (A B A B ... one at a time, each run from its own time zero), or "auto" (simultaneous unless the stimulus has a pointer,
    keys or drags). Needs ``repeats`` >= 2 (the floor is measured from the repeats). Raises ``PairJudgeError`` when the tool
    cannot run."""
    if repeats < 2:
        raise PairJudgeError("repeats must be at least 2: the noise floor is measured from the repeats")
    if mode not in ("auto", "simultaneous", "sequential"):
        raise PairJudgeError(f"mode must be auto, simultaneous or sequential, not {mode!r}")
    x_ite = x_ite or os.environ.get("X_ITE_DIST")
    if not x_ite or not (pathlib.Path(x_ite) / "x_ite.min.js").is_file():
        raise PairJudgeError("X_ITE dist directory not found (pass x_ite=... or set X_ITE_DIST; it holds x_ite.min.js)")
    for path in (file_a, file_b):
        if not pathlib.Path(path).is_file():
            raise PairJudgeError(f"{path}: no such file")
    stim = normalise_stimulus(stimulus)
    if mode == "auto":
        mode = "sequential" if _pointer(stim) else "simultaneous"
    elif mode == "simultaneous" and _pointer(stim):
        raise PairJudgeError("a pointer, key or drag stimulus cannot be made at the same moment in two browsers: use "
                             "mode='sequential' (or 'auto') for it")
    graph_a, graph_b = _graph(file_a), _graph(file_b)
    wa, wb = watched(graph_a), watched(graph_b)
    ta_, tb_ = field_types(graph_a), field_types(graph_b)
    common = sorted(set(wa) & set(wb))
    unmatched = {"only_in_a": [f"{d}.{f}" for d, f in sorted(set(wa) - set(wb))],
                 "only_in_b": [f"{d}.{f}" for d, f in sorted(set(wb) - set(wa))]}
    skipped = [{"stream": f"{d}.{f}", "why": f"its values are nodes ({ta_[(d, f)] if ta_[(d, f)] in NODE_TYPES else tb_[(d, f)]})"}
               for d, f in common if ta_[(d, f)] in NODE_TYPES or tb_[(d, f)] in NODE_TYPES]
    common = [key for key in common if f"{key[0]}.{key[1]}" not in {row["stream"] for row in skipped}]
    if stim.get("only_sensor"):
        for graph, name in ((graph_a, "a"), (graph_b, "b")):
            sensors = [n.id for n in graph.nodes.values() if n.node_type in POINTING]
            if sensors != [stim["only_sensor"]]:
                raise PairJudgeError(f"the recorded stimulus clicks {stim['only_sensor']!r} but file {name} has pointing "
                                     f"sensors {sensors}")
    if not common and not skipped:
        raise PairJudgeError("the two files have no ROUTE target in common (same DEF and field): nothing to compare")
    sources = {"a": [list(key) for key in common] + _extras(graph_a), "b": [list(key) for key in common] + _extras(graph_b)}
    paths = {"a": file_a, "b": file_b}
    load, traces = [], {"a": [], "b": []}
    plan = {"ab": [], "aa": [], "bb": []}          # [(trace, trace)] of every pairing, in the order it was measured
    seen = lambda: os.getloadavg()                 # noqa: E731
    with tempfile.TemporaryDirectory(prefix="pair-judge-") as scratch:
        if mode == "simultaneous":
            run_stim = dict(stim, seconds=stim["seconds"] + SLACK)
            for _ in range(repeats):
                for kind, (n1, n2) in (("ab", "ab"), ("aa", "aa"), ("bb", "bb")):
                    before = seen()
                    t1, t2 = record_together([paths[n1], paths[n2]], [sources[n1], sources[n2]], run_stim, x_ite, scratch, timeout)
                    load.append({"pair": kind, "before": before, "after": seen()})
                    plan[kind].append((t1, t2))
                    traces[n1].append(t1)
                    traces[n2].append(t2)
        else:
            for _ in range(repeats):
                for name in ("a", "b"):
                    before = seen()
                    trace = record(paths[name], sources[name], stim, x_ite, scratch, timeout)
                    load.append({"file": name, "before": before, "after": seen()})
                    traces[name].append(trace)
    timers = {n.id for graph in (graph_a, graph_b) for n in graph.nodes.values() if n.node_type == "TimeSensor"}
    # lay out every pairing: (trace, zero, trace, zero, grid), the zero being a run's time zero, grids in seconds from it
    if mode == "simultaneous":
        layout, zeros = {}, {"a": [], "b": []}
        for kind in plan:
            layout[kind] = []
            for t1, t2 in plan[kind]:
                zero = max(t1["began"], t2["began"])
                end = min(max(t1["frames"], default=0.0), max(t2["frames"], default=0.0))
                span = min(end - zero, stim["seconds"])
                if span < 1.0:
                    raise PairJudgeError(f"the two simultaneous runs overlapped for {max(span, 0):.2f} s: too little to compare "
                                         "(was the machine busy? raise 'seconds')")
                layout[kind].append((t1, zero, t2, zero, [i * step for i in range(int(span / step) + 1)]))
        zeros = {"a": [(row[1], "shared clock") for row in layout["ab"]], "b": [(row[3], "shared clock") for row in layout["ab"]]}
    else:
        zeros = {n: [_zero(t, timers) for t in traces[n]] for n in traces}
        ends = [max(t["frames"]) - z[0] for n in traces for t, z in zip(traces[n], zeros[n]) if t["frames"]]
        grid = [i * step for i in range(int((min(ends) if ends else 0.0) / step) + 1)]
        zero_of = {id(t): z[0] for n in traces for t, z in zip(traces[n], zeros[n])}
        within = lambda ts: [(ts[i], ts[j]) for i in range(len(ts)) for j in range(i + 1, len(ts))]  # noqa: E731
        pairs = {"ab": [(a, b) for a in traces["a"] for b in traces["b"]], "aa": within(traces["a"]), "bb": within(traces["b"])}
        layout = {k: [(x, zero_of[id(x)], y, zero_of[id(y)], grid) for x, y in v] for k, v in pairs.items()}
    horizon = min(len(row[4]) for rows in layout.values() for row in rows) - 1
    horizon = max(horizon, 0) * step
    streams, unobservable = [], []
    for d, f in common:
        kind = ta_[(d, f)] if ta_[(d, f)] != "?" else tb_[(d, f)]
        rotation = kind in ("SFRotation", "MFRotation")

        def series(trace, zero, grid):
            if any(m[0] == d and m[1] == f for m in trace.get("missing", [])):
                unobservable.append(f"{d}.{f}")
            events = [(e[0] - zero, e[3]) for e in trace["events"] if e[1] == d and e[2] == f]
            initial = next((i[2] for i in trace.get("initial", []) if i[0] == d and i[1] == f), None)
            return sample(initial, events, grid)

        texts = [e[3] for n in traces for t in traces[n] for e in t["events"] if e[1] == d and e[2] == f]
        if kind == "?" and texts and all(looks_like_node(x) for x in texts):
            skipped.append({"stream": f"{d}.{f}", "why": "its values are nodes (read from the values: the node type is not in the catalogue)"})
            continue
        built = {k: [(series(t1, z1, g), series(t2, z2, g)) for t1, z1, t2, z2, g in rows] for k, rows in layout.items()}
        result = judge_pairings(built["ab"], built["aa"], built["bb"], tolerance, margin, min_abs, blind, rotation)
        result["stream"] = f"{d}.{f}"
        result["type"] = kind
        result["events"] = {n: [sum(1 for e in t["events"] if e[1] == d and e[2] == f) for t in traces[n]] for n in traces}
        if not any(result["events"]["a"]) and not any(result["events"]["b"]):
            result["verdict"], result["reason"] = "unclear", "no run ever sent this stream"
        streams.append(result)
    unmatched["unobservable"] = sorted(set(unobservable))
    flat_load = [v for row in load for v in row["before"][:1] + row["after"][:1]]
    return {
        "verdict": overall([s["verdict"] for s in streams]), "reason": overall_reason(streams), "mode": mode,
        "files": {"a": str(file_a), "b": str(file_b)}, "stimulus": stim, "repeats": repeats,
        "x_ite": traces["a"][0]["browser"], "x_ite_dist": str(x_ite), "browser": browser_version(),
        "instrument": "tools/behaviour_pair_judge.py, headless Chromium with software GL",
        "tolerance": {"fraction_of_span": tolerance, "margin": margin, "min_abs": min_abs, "sample_step_s": step,
                      "samples": int(round(horizon / step)) + 1, "horizon_s": round(horizon, 3), "blind_floor": blind,
                      "rotation": "the angle between the two rotations, in radians"},
        "load": {"max_1min": max(flat_load), "runs": load},
        "time_zero": {n: [{"time": round(z, 3), "from": how} for z, how in zeros[n]] for n in zeros},
        "page_errors": {n: [t.get("pageErrors", []) for t in traces[n]] for n in traces},
        "unmatched": unmatched, "skipped": skipped, "streams": streams,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                     epilog="exit codes: 0 same, 1 differs, 2 unclear, 3 tool error")
    parser.add_argument("file_a")
    parser.add_argument("file_b")
    parser.add_argument("--stimulus", help="JSON file: a dict, or the recorded list (see the module text); default: run 4 s")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--mode", choices=["auto", "simultaneous", "sequential"], default="auto",
                        help="simultaneous: A and B run at the same moment (a world nobody touches); sequential: one at a time")
    parser.add_argument("--x-ite", help="X_ITE dist directory (default: $X_ITE_DIST)")
    parser.add_argument("--out", help="also write the verdict JSON here")
    args = parser.parse_args(argv)
    try:
        result = judge_pair(args.file_a, args.file_b, args.stimulus, args.repeats, args.x_ite, mode=args.mode)
    except PairJudgeError as error:
        result = {"verdict": "error", "error": str(error)}
    text = json.dumps(result, indent=1)
    print(text)
    if args.out:
        pathlib.Path(args.out).write_text(text + "\n", encoding="utf-8")
    return EXIT[result["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
