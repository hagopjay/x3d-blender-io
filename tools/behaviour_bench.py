# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""How the behaviour simulator and the Blender player scale: synthetic graphs, timed.

Four shapes, each at N = 10, 100, 1000, 5000 units (``--sizes`` changes them):

  fan     one looping TimeSensor drives N PositionInterpolators, each into its own Transform
  chains  N independent chains: TimeSensor (loop) -> PositionInterpolator -> PositionDamper -> Transform
  mixed   N copies of the door world's graph (TouchSensor -> TimeSensor -> PositionInterpolator -> Transform), and
          one click per 10 copies spread over the run
  hosted  N Scripts with Python handlers fed by one looping TimeSensor, each into its own Transform, and a
          CollisionSensor for every fifth one, told every step whether it touches (class E)

For each case the benchmark times ``Simulation(graph)``, ``start()`` and 300 steps of 1/60 s, and reports the median
and 95th percentile of a step, the events sent per step, and the peak memory (tracemalloc). With ``--bpy`` (needs the
bpy module) it also builds the scene (one empty per target, the node tree) and times ``Player.step`` over the same
300 frames. Nothing is random: the same command gives the same graphs and the same events. ::

    python tools/behaviour_bench.py --out receipt.json
    python tools/behaviour_bench.py --bpy --sizes 10 100 1000 --out receipt.json
    python tools/behaviour_bench.py --tree --shapes fan --sizes 100 300     # apply, read, second apply (bpy)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
import time
import tracemalloc
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source"))

import behaviour_graph as bg      # noqa: E402
import behaviour_sim as bs        # noqa: E402

SHAPES = ("fan", "chains", "mixed", "hosted")
SIZES = (10, 100, 1000, 5000)
STEPS = 300
DT = 1 / 60


def _lift(b, name):
    return b.target("Transform", name)


def build(shape: str, n: int) -> bg.Behaviour:
    """The synthetic graph of ``shape`` with ``n`` units. Deterministic."""
    b = bg.Behaviour()
    if shape == "fan":
        clock = b.add("TimeSensor", "Clock", cycleInterval=4, loop=True)
        for i in range(n):
            move = b.add("PositionInterpolator", f"Move{i}", key=[0, 0.5, 1],
                         keyValue=[(i, 0, 0), (i, 1 + i % 3, 0), (i, 0, 0)])
            clock.fraction_changed >> move.set_fraction
            move.value_changed >> _lift(b, f"Thing{i}").translation
    elif shape == "chains":
        for i in range(n):
            clock = b.add("TimeSensor", f"Clock{i}", cycleInterval=2 + i % 5, loop=True)
            move = b.add("PositionInterpolator", f"Move{i}", key=[0, 1], keyValue=[(0, 0, 0), (i, 2, 0)])
            follow = b.add("PositionDamper", f"Follow{i}", tau=0.3)
            clock.fraction_changed >> move.set_fraction
            move.value_changed >> follow.set_destination
            follow.value_changed >> _lift(b, f"Thing{i}").translation
    elif shape == "mixed":
        for i in range(n):
            click = b.add("TouchSensor", f"Click{i}", parent=f"Button{i}")
            timer = b.add("TimeSensor", f"Timer{i}", cycleInterval=3)
            slide = b.add("PositionInterpolator", f"Slide{i}", key=[0, 0.4, 0.6, 1],
                          keyValue=[(0, 1.2, 0), (0, 3.7, 0), (0, 3.7, 0), (0, 1.2, 0)])
            click.touchTime >> timer.startTime
            timer.fraction_changed >> slide.set_fraction
            slide.value_changed >> _lift(b, f"Door{i}").translation
    elif shape == "hosted":
        # class E: n Scripts, each with a Python handler, fed by one looping clock; every fifth unit also has a CollisionSensor
        # that is told every step whether it touches (alternating each frame)
        clock = b.add("TimeSensor", "Clock", cycleInterval=4, loop=True)
        for i in range(n):
            script = b.add("Script", f"Script{i}", declared=[("level", "SFFloat", "inputOnly"), ("place", "SFVec3f", "outputOnly")])
            clock.fraction_changed >> script.level
            script.place >> _lift(b, f"Thing{i}").translation
            if i % 5 == 0:
                b.add("CollisionSensor", f"Hit{i}")
    else:
        raise ValueError(f"unknown shape {shape!r}")
    return b


def _place(field, value, time, state):
    return [("place", (value, value * 0.5, 0.0))] if field == "level" else []


def host(sim, shape):
    """Give every Script of the "hosted" shape its handler (the other shapes have none)."""
    if shape == "hosted":
        for node in sim.graph.nodes.values():
            if node.node_type == "Script":
                sim.host(node.id, _place)


def touch(sim, shape, n, k, now):
    """The "hosted" shape's contact stimulus for step ``k``: each CollisionSensor touches on odd frames."""
    if shape == "hosted":
        for i in range(0, n, 5):
            sim.contact(f"Hit{i}", bool(k % 2), ["A|B"] if k % 2 else (), ["A"] if k % 2 else (), now)


def clicks(shape: str, n: int, steps: int = STEPS) -> dict[int, list[int]]:
    """step number (1-based) -> the copies clicked at that step; only "mixed" has any: one per 10 copies."""
    if shape != "mixed":
        return {}
    wanted = max(1, n // 10)
    when: dict[int, list[int]] = {}
    for j in range(wanted):
        when.setdefault(2 + (j * (steps - 4)) // wanted, []).append(10 * j if n >= 10 else 0)
    return when


def run_sim(sim: bs.Simulation, shape: str, n: int, steps: int = STEPS, times: list | None = None) -> list:
    """Start ``sim`` and step it; returns every step's changes. ``times`` collects each step's seconds."""
    when = clicks(shape, n, steps)
    host(sim, shape)
    out = list(sim.start(0.0))
    for k in range(1, steps + 1):
        now = k * DT
        began = time.perf_counter()
        for i in when.get(k, ()):
            out.extend(sim.click(f"Click{i}", now))
        touch(sim, shape, n, k, now)
        out.extend(sim.step(now))
        if times is not None:
            times.append(time.perf_counter() - began)
    return out


def _rounded(value, places):
    if isinstance(value, float):
        return round(value, places) + 0.0
    if isinstance(value, (tuple, list)):
        return type(value)(_rounded(v, places) for v in value)
    return value


def digest(shape: str, n: int, steps: int, places: int | None = None) -> str:
    """SHA-256 of everything the simulation sent (its whole log, then every change handed back), as exact text, or
    with floats rounded to ``places`` decimals (for graphs that call exp(): the C library's last bit differs)."""
    sim = bs.Simulation(build(shape, n), log_size=10_000_000)
    changes = run_sim(sim, shape, n, steps)
    h = hashlib.sha256()
    for line in sim.log:
        h.update(repr(line if places is None else _rounded(line, places)).encode())
    h.update(b"|")
    for line in changes:
        h.update(repr(line if places is None else _rounded(line, places)).encode())
    return h.hexdigest()


def p95(values):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]


def measure_sim(shape: str, n: int, budget: float) -> dict:
    graph = build(shape, n)
    began = time.perf_counter()
    sim = bs.Simulation(graph)
    construct = time.perf_counter() - began
    host(sim, shape)
    began = time.perf_counter()
    sim.start(0.0)
    start = time.perf_counter() - began
    steps: list[float] = []
    when = clicks(shape, n)
    finished = True
    total = time.perf_counter()
    for k in range(1, STEPS + 1):
        now = k * DT
        began = time.perf_counter()
        for i in when.get(k, ()):
            sim.click(f"Click{i}", now)
        touch(sim, shape, n, k, now)
        sim.step(now)
        steps.append(time.perf_counter() - began)
        if time.perf_counter() - total > budget:
            finished = False
            break
    row = {"shape": shape, "n": n, "nodes": len(graph.nodes), "routes": len(graph.routes),
           "construct_ms": construct * 1e3, "start_ms": start * 1e3, "steps_done": len(steps),
           "finished": finished,
           "step_median_ms": statistics.median(steps) * 1e3, "step_p95_ms": p95(steps) * 1e3}
    # events and memory in a second pass (tracemalloc slows everything, so it never shares a pass with the clock)
    tracemalloc.start()
    sim = bs.Simulation(build(shape, n))
    counted = [0]

    class CountingLog(deque):          # every event sent is one entry in the log
        def append(self, item):
            counted[0] += 1
            super().append(item)
    sim.log = CountingLog(sim.log, maxlen=sim.log.maxlen)
    run_sim(sim, shape, n, len(steps))
    row["peak_memory_mb"] = tracemalloc.get_traced_memory()[1] / 2**20
    tracemalloc.stop()
    row["events_per_step"] = counted[0] / max(1, len(steps))
    return row


def measure_player(shape: str, n: int, budget: float, tree_limit: int = 1000) -> dict:
    """Build the scene (one empty per target, one per sensor parent) and time Player.step. The node tree (what the
    player tints) is built with behaviour_nodes.apply for graphs of up to ``tree_limit`` nodes: apply is slow on big
    graphs (it is not what is measured), and without a tree the player has no node to tint."""
    import importlib
    import tempfile
    sys.path.insert(0, str(ROOT / "tests"))
    import bpy
    from test_roundtrip_bpy import _register_extension
    _register_extension(tempfile.mkdtemp(prefix="x3d_bench_"))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bn = importlib.import_module("io_scene_x3d.behaviour_nodes")
    bp = importlib.import_module("io_scene_x3d.behaviour_play")
    bn.ensure_registered()
    bp.ensure_axes_properties()
    scene = bpy.context.scene
    graph = build(shape, n)
    for node in list(graph.nodes.values()):
        if node.role == bg.TARGET:
            obj = bpy.data.objects.new(node.id, None)
            scene.collection.objects.link(obj)
            node.binding = ("transform", obj.name)
        elif node.parent:
            if node.parent not in bpy.data.objects:
                scene.collection.objects.link(bpy.data.objects.new(node.parent, None))
    began = time.perf_counter()
    with_tree = len(graph.nodes) <= tree_limit
    if with_tree:
        bn.apply(graph, scene)
    build_ms = (time.perf_counter() - began) * 1e3
    player = bp.Player(scene) if with_tree else bp.Player(scene, graph)
    player.start(0.0)
    when = clicks(shape, n)
    steps: list[float] = []
    total = time.perf_counter()
    finished = True
    for k in range(1, STEPS + 1):
        now = k * DT
        began = time.perf_counter()
        for i in when.get(k, ()):
            player.click(bpy.data.objects[f"Button{i}"], now, held=0.0)
        player.step(now)
        steps.append(time.perf_counter() - began)
        if time.perf_counter() - total > budget:
            finished = False
            break
    player.stop()
    return {"shape": shape, "n": n, "scene_build_ms": build_ms, "glow": with_tree, "steps_done": len(steps), "finished": finished,
            "step_median_ms": statistics.median(steps) * 1e3, "step_p95_ms": p95(steps) * 1e3}


TREE_SIZES = (10, 30, 100, 300, 1000)


def _tree_env():
    import importlib
    import tempfile
    sys.path.insert(0, str(ROOT / "tests"))
    import bpy
    from test_roundtrip_bpy import _register_extension
    _register_extension(tempfile.mkdtemp(prefix="x3d_bench_"))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bn = importlib.import_module("io_scene_x3d.behaviour_nodes")
    bn.ensure_registered()
    return bpy, bn


def bind_targets(bpy, scene, graph):
    """One empty per target and per sensor parent, as measure_player does."""
    for node in list(graph.nodes.values()):
        if node.role == bg.TARGET:
            obj = bpy.data.objects.new(node.id, None)
            scene.collection.objects.link(obj)
            node.binding = ("transform", obj.name)
        elif node.parent and node.parent not in bpy.data.objects:
            scene.collection.objects.link(bpy.data.objects.new(node.parent, None))


def measure_tree(shape: str, n: int, budget: float) -> dict:
    """Seconds for apply (fresh scene), read, and a second apply onto the tree that exists. A call that takes longer
    than ``budget`` seconds is not interrupted (it cannot be), so run big sizes one at a time and give up by hand."""
    bpy, bn = _tree_env()
    scene = bpy.context.scene
    graph = build(shape, n)
    bind_targets(bpy, scene, graph)
    row = {"shape": shape, "n": n, "nodes": len(graph.nodes), "routes": len(graph.routes)}
    began = time.perf_counter()
    bn.apply(graph, scene)
    row["apply_s"] = time.perf_counter() - began
    began = time.perf_counter()
    back = bn.read(scene)
    row["read_s"] = time.perf_counter() - began
    row["read_differences"] = sum(len(v) for v in bg.difference(graph, back).values())
    began = time.perf_counter()
    bn.apply(graph, scene)
    row["apply_again_s"] = time.perf_counter() - began
    for key in ("apply", "read", "apply_again"):
        row[f"{key}_ms_per_node"] = row[f"{key}_s"] / row["nodes"] * 1e3
    row["over_budget"] = max(row["apply_s"], row["read_s"], row["apply_again_s"]) > budget
    return row


def measure_tree_all(shapes, sizes, budget):
    rows = []
    for shape in shapes:
        for n in sizes:
            rows.append(measure_tree(shape, n, budget))
            r = rows[-1]
            print(f"tree {shape} {n}: apply {r['apply_s']:.3f}s read {r['read_s']:.3f}s again {r['apply_again_s']:.3f}s",
                  file=sys.stderr)
    return rows


def tree_table(rows):
    out = ["### Node tree (seconds; ms per node in brackets)", "",
           "| shape | N | nodes | apply | read | apply again |", "|---|---:|---:|---:|---:|---:|"]
    for r in rows:
        cells = [f"{r[k + '_s']:.3f} ({r[k + '_ms_per_node']:.2f})" for k in ("apply", "read", "apply_again")]
        out.append(f"| {r['shape']} | {r['n']} | {r['nodes']} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def machine() -> dict:
    cpu = "unknown"
    try:
        cpu = next(line.split(":", 1)[1].strip() for line in open("/proc/cpuinfo") if line.startswith("model name"))
    except Exception:
        pass
    info = {"cpu": cpu, "python": platform.python_version()}
    try:
        import bpy
        info["bpy"] = bpy.app.version_string
    except Exception:
        pass
    return info


def table(rows: list[dict], title: str, columns: list[tuple[str, str]]) -> str:
    out = [f"### {title}", "", "| shape | N | " + " | ".join(c[0] for c in columns) + " |",
           "|---|---:|" + "---:|" * len(columns)]
    for r in rows:
        cells = []
        for _, key in columns:
            value = r.get(key)
            cells.append("-" if value is None else f"{value:.2f}" if isinstance(value, float) else str(value))
        note = "" if r["finished"] else f" (did not finish: {r['steps_done']}/{STEPS} steps in the budget)"
        out.append(f"| {r['shape']} | {r['n']}{note} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sizes", type=int, nargs="+", default=list(SIZES))
    ap.add_argument("--shapes", nargs="+", default=list(SHAPES), choices=SHAPES)
    ap.add_argument("--bpy", action="store_true", help="also time Player.step in Blender (needs the bpy module)")
    ap.add_argument("--budget", type=float, default=120.0, help="seconds of stepping allowed per case")
    ap.add_argument("--tree-limit", type=int, default=1000, help="--bpy: build the node tree (glow on) up to this many nodes")
    ap.add_argument("--tree", action="store_true", help="time behaviour_nodes.apply, read and a second apply (needs bpy); "
                    "uses --sizes (default here: 10 30 100 300 1000) and --shapes; --budget is the seconds one call may take")
    ap.add_argument("--out", help="write the JSON receipt here")
    args = ap.parse_args(argv)
    if args.tree:
        sizes = args.sizes if args.sizes != list(SIZES) else list(TREE_SIZES)
        rows = measure_tree_all(args.shapes, sizes, args.budget)
        if args.out:
            Path(args.out).write_text(json.dumps({"machine": machine(), "tree": rows}, indent=1), encoding="utf-8")
        print(f"Machine: {machine()}\n")
        print(tree_table(rows))
        return
    receipt = {"machine": machine(), "steps": STEPS, "dt": DT, "simulation": [], "player": []}
    for shape in args.shapes:
        for n in args.sizes:
            receipt["simulation"].append(measure_sim(shape, n, args.budget))
            print(f"sim {shape} {n}: {receipt['simulation'][-1]['step_median_ms']:.3f} ms/step", file=sys.stderr)
    if args.bpy:
        for shape in args.shapes:
            for n in args.sizes:
                receipt["player"].append(measure_player(shape, n, args.budget, args.tree_limit))
                print(f"player {shape} {n}: {receipt['player'][-1]['step_median_ms']:.3f} ms/step", file=sys.stderr)
    if args.out:
        Path(args.out).write_text(json.dumps(receipt, indent=1), encoding="utf-8")
    print(f"Machine: {receipt['machine']}\n")
    print(table(receipt["simulation"], "Simulation (300 steps of 1/60 s)",
                [("nodes", "nodes"), ("construct ms", "construct_ms"), ("start ms", "start_ms"),
                 ("median ms/step", "step_median_ms"), ("p95 ms/step", "step_p95_ms"),
                 ("events/step", "events_per_step"), ("peak MB", "peak_memory_mb")]))
    if receipt["player"]:
        print()
        print(table(receipt["player"], "Player.step in Blender (same 300 frames; glow only where the node tree was built)",
                    [("node tree built (glow)", "glow"), ("tree build ms", "scene_build_ms"), ("median ms/step", "step_median_ms"),
                     ("p95 ms/step", "step_p95_ms")]))


if __name__ == "__main__":
    main()
