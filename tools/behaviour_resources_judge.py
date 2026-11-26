# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Does the Python simulator do what X_ITE does with outside resources (LoadSensor, AudioClip, MovieTexture)?

    X_ITE_DIST=<x_ite dist> python tools/behaviour_resources_judge.py --record tests/behaviour/probe-audio.x3d --out trace.json
                                                  # needs node, playwright with Chromium, ffmpeg (for the WebM)
    python tools/behaviour_resources_judge.py tests/behaviour/probe-audio.x3d tests/behaviour/x_ite_traces/probe-audio.json

``--record`` makes tiny media files itself (a 1 s WAV with the wave module, a 2x2 PNG, a 1 s WebM with ffmpeg), serves them
from a local server after the delays the world's ``<name>.media.json`` names (or refuses them: a status), and has
tools/behaviour_resources_judge.cjs run the world in X_ITE from its first moment. Nothing is downloaded. The trace is X_ITE's
own account: every event at every ROUTE source, every change of a url object's load state, the frames, with X_ITE's time
stamp and the wall clock beside it.

The replay gives the simulator what X_ITE was given and nothing it produced. The world is started at the moment X_ITE
initialised its first node and stepped at every frame X_ITE drew. The resources are derived from the trace as a
stimulus: each url object's load took as long as X_ITE's load of it did, counted to the first frame after the load ended
(X_ITE tells a node's neighbours about a finished load at the next frame), and a medium lasts as long as X_ITE's
duration_changed said. Everything else (every start, stop, pause, the order of events inside a frame) is the simulator's.

Streams are compared source by source and event by event, in order: the same number of events, each at the same time
stamp (2 ms) with the same value. Two things X_ITE does cannot be an input, and the verdict says where they were allowed:

* A medium ends when X_ITE's audio or video clock reaches its duration; that clock is not the frame clock (it lags it by
  up to a frame, and an audio clock counts in blocks of 128 samples). The end of a clip that is not looping may fall on
  the frame the simulator chose or the next one: ``ends_within_a_frame``.
* X_ITE measures the time a node was paused on the wall clock, everything else on the frame clock: ``elapsedTime`` after a
  pause differs from the simulator's by that clock's difference (a millisecond or two).
* X_ITE runs a LoadSensor's ``timeOut`` on the wall clock and stamps what follows with the last frame's time: the replay
  tells the simulator on which step the timer fired (``timer_lags`` says how early that was, at most a frame).
"""

import json
import math
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
import xml.etree.ElementTree as ET
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source"))
import behaviour_graph as bg          # noqa: E402
import behaviour_sim as bs            # noqa: E402
from behaviour_resources import Resources   # noqa: E402

EXACT = 2e-3             # a time stamp, a number: the same to two milliseconds
PAUSE_CLOCKS = 0.01      # elapsedTime after a pause: wall clock against frame clock
IN_PROGRESS, COMPLETE, FAILED = 1007, 1008, 1009        # X_ITE's load states (X3DConstants)


# -- media a test makes itself -----------------------------------------------------------------------------------------

def make_media(folder, names):
    """A tiny file for each name: .wav (1 s, 440 Hz, 8 kHz mono), .png (2x2), .webm (1 s, 64x48, 10 fps; needs ffmpeg)."""
    folder = pathlib.Path(folder)
    for name in names:
        path = folder / name
        if path.suffix == ".wav":
            with wave.open(str(path), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(8000)
                out.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 8000))) for i in range(8000)))
        elif path.suffix == ".png":
            def chunk(kind, data):
                return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
            rows = b"".join(b"\x00" + bytes([255, 0, 0, 0, 255, 0]) for _ in range(2))
            path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
                             + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
        elif path.suffix == ".webm":
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x48:rate=10:duration=1",
                            "-c:v", "libvpx", "-b:v", "200k", str(path)], check=True)
        else:
            raise ValueError(f"no tiny {path.suffix} file to make for {name}")


def urls_of(x3d_text):
    """Every file name the world's url attributes name."""
    names = set()
    for element in ET.fromstring(x3d_text.encode("utf-8")).iter():
        names.update(bs._strings(element.get("url") or ""))
    return sorted(names)


def record(world, out, seconds=8, xite=None):
    """Run ``world`` in X_ITE (the dist directory ``xite``, else $X_ITE_DIST) for ``seconds`` and write the trace to ``out``."""
    world = pathlib.Path(world)
    text = world.read_text(encoding="utf-8")
    rules = json.loads(world.with_suffix(".media.json").read_text(encoding="utf-8")) if world.with_suffix(".media.json").is_file() else {}
    xite = xite or os.environ.get("X_ITE_DIST")
    if not xite:
        raise SystemExit("X_ITE dist directory not found: pass --xite or set X_ITE_DIST (it holds x_ite.min.js)")
    with tempfile.TemporaryDirectory() as work:
        work = pathlib.Path(work)
        (work / "media").mkdir()
        make_media(work / "media", [name for name in urls_of(text) if not (rules.get(name) or {}).get("status")])
        graph = bg.Behaviour.from_x3d(text)
        (work / "sources.json").write_text(json.dumps(sources_of(graph)), encoding="utf-8")
        (work / "media.json").write_text(json.dumps(rules), encoding="utf-8")
        done = subprocess.run(["node", str(ROOT / "tools" / "behaviour_resources_judge.cjs"), str(xite), str(world), str(work / "sources.json"),
                               str(seconds), str(work / "media"), str(work / "media.json")], capture_output=True, text=True, check=True)
    pathlib.Path(out).write_text(done.stdout, encoding="utf-8")


def sources_of(graph):
    seen = []
    for route in graph.routes:
        pair = [route.from_id, route.from_field]
        if pair not in seen:
            seen.append(pair)
    return seen


# -- the stimulus, from the trace -----------------------------------------------------------------------------------

def _first_frame_after(trace, wall):
    """X_ITE's stamp of the first frame that sent an event at or after the wall-clock moment ``wall``: a load finishes
    between frames, and what it causes is delivered, stamped, at the next frame that has something to send. (The page's
    own animation-frame stamps are not used: they can be a frame behind X_ITE's.)"""
    later = [event for event in trace["events"] if event[1] >= wall and event[3] not in ("loadState", "live")]
    return min(later, key=lambda event: event[1])[0] if later else trace["events"][-1][0]


def start_of(trace):
    """When the replay starts, on X_ITE's clock. Nothing time-dependent runs before the world goes live: a node started while
    the world loads (a TimeSensor that loops, an AudioClip) is held, and its clock starts at that moment; events sent before
    it carry the time of the loading, and are compared without their time stamps. A world with no clock in it (only
    LoadSensors and what they watch) has nothing held: it starts with the first event it sent, and every stamp counts."""
    if not trace.get("clocks", True):
        return min((event[0] for event in trace["events"] if event[3] not in ("loadState", "live")), default=trace["starts"][0][0])
    live = [event[0] for event in trace["events"] if event[2] == "(world)" and event[4] is True]
    return live[0] if live else min((event[0] for event in trace["events"] if event[3] != "loadState"), default=trace["starts"][0][0])


def derive(x3d_text, trace):
    """(Resources, notes): what each url object's load was, from X_ITE's own load states in the trace."""
    root = ET.fromstring(x3d_text.encode("utf-8"))
    urls = {element.get("DEF"): bs._strings(element.get("url") or "") for element in root.iter() if element.get("DEF") and element.get("url")}
    asked = {}
    for request in trace.get("requests", []):
        asked.setdefault(request["file"], []).append(request)
    table, notes = {}, []
    by_def = {}
    for stamp, wall, name, field_name, value in trace["events"]:
        if field_name == "loadState":
            by_def.setdefault(name, []).append((stamp, wall, int(value)))
    durations = {}
    for _stamp, _wall, name, field_name, value in trace["events"]:
        if field_name == "duration_changed" and float(value) >= 0:
            durations.setdefault(name, float(value))
    for name, states in by_def.items():
        begun = next((entry for entry in states if entry[2] == IN_PROGRESS), None)
        ended = next((entry for entry in states if entry[2] in (COMPLETE, FAILED)), None)
        if begun is None or ended is None or name not in urls:
            notes.append(f"{name}: no complete load in the trace")
            continue
        total = max(_first_frame_after(trace, ended[1]) - max(begun[0], start_of(trace)), 0.0)
        spent = 0.0
        for url in urls[name]:
            ours = next(iter(asked.get(url, [])), None)
            took = (ours["answered"] - ours["asked"]) if ours else 0.0
            failed = ours is not None and ours["status"] != 200
            last = url == urls[name][-1]
            if failed and not last:
                table[url] = {"fails": round(took, 3)}
                spent += round(took, 3)
            else:
                entry = {"loads": max(total - spent, 0.0)}
                if name in durations:
                    entry["duration"] = durations[name]
                if ended[2] == FAILED:
                    entry = {"fails": entry["loads"]}
                table[url] = entry
                break
    return Resources(table), notes


# -- replay and comparison -----------------------------------------------------------------------------------------

def _plain(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    return value


def _gap(a, b):
    if isinstance(a, bool) or isinstance(b, bool) or isinstance(a, str) or isinstance(b, str):
        return 0.0 if a == b else float("inf")
    return abs(float(a) - float(b))


CLOCKS = ("AudioClip", "MovieTexture")
FRAME = 0.04             # the longest frame X_ITE drew while a trace was recorded counts as this; one frame of slack at the end of a clip


def tolerance_for(node, field_name):
    """How close two values at one stamp must be: elapsedTime after a pause carries the wall clock's difference."""
    return PAUSE_CLOCKS if node.node_type in CLOCKS and field_name == "elapsedTime" else EXACT


def _within_a_frame(a, b, ends, field_name):
    """A clip's end, as X_ITE's audio or video clock decides it, falls on the frame the simulator chose or the next (see the
    module text). Returns (a, b, how many ends differed, whether every end was within FRAME) with the events of those last
    frames taken out of both lists so the rest is compared exactly. ``isActive`` False events are kept (compared with the
    stamp slack the caller allows); for ``elapsedTime`` a run's events after the earlier of the two ends are dropped."""
    their_ends, our_ends = ends
    if len(their_ends) != len(our_ends):
        return a, b, 0, False
    differed, within = 0, True
    cuts = []
    for end_x, end_s in zip(their_ends, our_ends):
        gap = abs(end_x - end_s)
        if gap > EXACT:
            differed += 1
            within = within and gap <= FRAME
            cuts.append((min(end_x, end_s), max(end_x, end_s)))
    if field_name == "isActive":
        # the end is the event that moved: move it onto the other's stamp, so everything else is compared exactly
        moved = []
        for stamp, value in a:
            for low, high in cuts:
                if value is False and stamp in (low, high):
                    stamp = low
            moved.append((stamp, value))
        shifted = []
        for stamp, value in b:
            for low, high in cuts:
                if value is False and stamp in (low, high):
                    stamp = low
            shifted.append((stamp, value))
        return moved, shifted, differed, within
    def trimmed(events):
        return [event for event in events if not any(low < event[0] <= high for low, high in cuts)]
    return trimmed(a), trimmed(b), differed, within


def has_clocks(x3d_text):
    """Does the world start a clock by itself: a TimeSensor that is not switched off, or a medium that loops?"""
    for element in ET.fromstring(x3d_text.encode("utf-8")).iter():
        if element.tag == "TimeSensor" and element.get("enabled") != "false":
            return True
        if element.tag in ("AudioClip", "MovieTexture") and element.get("loop") == "true":
            return True
    return False


def run(x3d_text, trace):
    """The simulator's log for the trace's stimulus: (graph, simulation, resources, notes)."""
    trace = dict(trace, clocks=has_clocks(x3d_text))
    graph = bg.Behaviour.from_x3d(x3d_text)
    resources, notes = derive(x3d_text, trace)
    sim = bs.Simulation(graph, log_size=10 ** 7, resources=resources)
    t_init = start_of(trace)
    sim.start(t_init)
    stamps = sorted({event[0] for event in trace["events"] if event[0] > t_init and event[3] not in ("loadState", "live")})
    # X_ITE runs a LoadSensor's timeOut on the wall clock and stamps what it does with the last frame's time, so the abort
    # can carry a stamp up to a frame before the frame-clock moment the timeOut names. The replay tells the simulator when
    # the timer fired (the stamp of the sensor's isActive going false while it waits) and judges what it does then.
    waiting = {}
    for stamp, _wall, name, field_name, value in trace["events"]:
        if field_name == "isActive" and value is False and name in sim.machines and sim.machines[name].node_type == "LoadSensor":
            waiting.setdefault(stamp, []).append(name)
    timer_lags = {}
    for stamp in stamps:
        for name in waiting.get(stamp, ()):
            machine = sim.machines[name]
            if machine.deadline is not None and stamp < machine.deadline <= stamp + FRAME:
                timer_lags[name] = machine.deadline - stamp
                machine.deadline = stamp
        sim.step(stamp)
    sim.timer_lags = timer_lags
    return graph, sim, resources, notes


def judge(x3d_path, trace):
    x3d_text = pathlib.Path(x3d_path).read_text(encoding="utf-8")
    trace = dict(trace, clocks=has_clocks(x3d_text))
    graph, sim, resources, notes = run(x3d_text, trace)
    theirs, ours = {}, {}
    for stamp, _wall, name, field_name, value in trace["events"]:
        if field_name not in ("loadState", "live"):
            theirs.setdefault((name, field_name), []).append((stamp, _plain(value)))
    for when, node_id, field_name, value in sim.log:
        ours.setdefault((node_id, field_name), []).append((when, _plain(value)))
    streams, agree = [], True
    live = start_of(trace)
    clock_ends = {}
    for node_id, node in graph.nodes.items():
        if node.node_type in CLOCKS:
            clock_ends[node_id] = (sorted(t for t, v in theirs.get((node_id, "isActive"), []) if v is False),
                                   sorted(t for t, v in ours.get((node_id, "isActive"), []) if v is False))
    for node_id, field_name in sources_of(graph):
        node = graph.nodes[node_id]
        canonical, x3d_type = bg.resolve_field(node.node_type, field_name, "out", node.declared)
        a, b = theirs.get((node_id, field_name), []), ours.get((node_id, canonical), [])
        flexible = 0
        if node_id in clock_ends and field_name in ("isActive", "elapsedTime"):
            a, b, flexible, ends_ok = _within_a_frame(a, b, clock_ends[node_id], field_name)
        else:
            ends_ok = True
        pairs = list(zip(a, b))
        # before the world is live X_ITE's stamps (and the times it puts in values) are the loading's: only order and the rest count
        time_gap = max((abs(x[0] - y[0]) for x, y in pairs if x[0] >= live), default=0.0)
        value_gap = max((_gap(x[1], y[1]) for x, y in pairs if x[0] >= live or x3d_type != "SFTime"), default=0.0)
        ok = len(a) == len(b) and time_gap <= EXACT and value_gap <= tolerance_for(node, field_name) and ends_ok
        agree = agree and ok
        streams.append({"source": f"{node_id}.{field_name}", "node": node.node_type, "type": x3d_type, "x_ite_events": len(a),
                        "simulator_events": len(b), "compared": len(pairs), "worst_time_gap": round(time_gap, 6),
                        "worst_value_gap": round(value_gap, 6), "ends_within_a_frame": flexible, "agree": ok})
    return {"file": trace["file"], "browser": trace["browser"], "frames": trace.get("frameCount"), "resources": resources.to_dict(),
            "resource_notes": notes, "timer_lags": {name: round(lag, 4) for name, lag in sim.timer_lags.items()}, "noted": dict(sim.noted), "dropped": dict(sim.dropped), "faults": list(sim.faults),
            "streams": streams, "agree": agree}


def main(argv):
    if argv and argv[0] == "--record":
        out = argv[argv.index("--out") + 1]
        record(argv[1], out, seconds=float(argv[argv.index("--seconds") + 1]) if "--seconds" in argv else 8,
               xite=argv[argv.index("--xite") + 1] if "--xite" in argv else None)
        return 0
    result = judge(argv[0], json.loads(pathlib.Path(argv[1]).read_text(encoding="utf-8")))
    print(json.dumps(result, indent=1))
    return 0 if result["agree"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
