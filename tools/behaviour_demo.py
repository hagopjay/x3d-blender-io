# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One command per step for a behaviour demo in tests/behaviour/demos/NAME/ (see docs/BEHAVIOUR_DEMOS.md).

    python tools/behaviour_demo.py check  NAME     # the folder has what a demo needs; the world parses
    python tools/behaviour_demo.py record NAME     # X_ITE 16.7.1 in headless Chromium -> demos/NAME/x_ite.json
    python tools/behaviour_demo.py judge  NAME     # replay the trace through the simulator; exit 1 unless all agree
    python tools/behaviour_demo.py show   NAME [--out DIR] [--with door ...]   # a real Blender window plays it

record needs X_ITE_DIR (an X_ITE dist folder holding x_ite.min.js) and NODE_PATH (a node_modules with playwright).
show runs $BLENDER (default: the macOS app) with the eye test; the Host-eyes witness lands in DIR/host-eyes.json.

demo.json, the demo's contract with these tools:
    {"title": str, "streams": int,             # ROUTE sources the judge must compare (all must agree)
     "clicks": int, "seconds": number,         # what the recorder does: real clicks on the first pointing sensor ...
     "drags": "drags.json" | null,             # ... or real drags from this file (clicks must be 0)
     "keys": "keys.json" | null,               # ... or typed keys from this file (KeySensor / StringSensor demos)
     "click_plan": ["SensorDEF", ...],         # ... or one real click on each named pointing sensor, in this order (clicks 0)
     "judges": [node types this demo is the first to judge against X_ITE],
     "idle": ["Node.field", ...]}              # optional: ROUTE sources the recorded click cannot fire (see below)

idle: the recorder clicks one spot, so a world with several click chains fires only one of them. A source named here
must send nothing in X_ITE and nothing in the simulator (so the simulator cannot invent events); it still counts in
"streams", and the demo's act.py proves its chain in the live window. Every other source needs an X_ITE event.
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEMOS = ROOT / "tests" / "behaviour" / "demos"
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "source"))
import behaviour_graph as bg          # noqa: E402
import behaviour_sim_judge as judge   # noqa: E402

REQUIRED = ("title", "streams", "clicks", "seconds")


def folder(name):
    path = DEMOS / name
    if not (path / f"{name}.x3d").is_file():
        sys.exit(f"no demo world: {path / (name + '.x3d')}")
    return path


def contract(name):
    path = folder(name) / "demo.json"
    if not path.is_file():
        sys.exit(f"no {path}: write the demo's contract first (docs/BEHAVIOUR_DEMOS.md)")
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        sys.exit(f"{path}: missing {missing}")
    return data


def check(name):
    here, data = folder(name), contract(name)
    graph = bg.Behaviour.from_x3d((here / f"{name}.x3d").read_text(encoding="utf-8"))
    problems = []
    for key in ("drags", "keys"):
        if data.get(key) and not (here / data[key]).is_file():
            problems.append(f"{key} file {data[key]} is missing")
    if data.get("click_plan"):
        names = {n.id for n in graph.nodes.values() if n.node_type in ("TouchSensor", "PlaneSensor", "CylinderSensor", "SphereSensor")}
        problems += [f"click_plan names {d}, which is not a pointing sensor of the world" for d in data["click_plan"] if d not in names]
    if data.get("drags") and data["clicks"]:
        problems.append("drags and clicks together: the recorder does one or the other")
    if not (here / "act.py").is_file():
        problems.append("no act.py: the live window would only do the standard steps")
    if not (here / "README.md").is_file():
        problems.append("no README.md (what the demo shows, how to play it, what was checked)")
    sources = judge.sources_of(graph)
    known = {f"{node}.{field}" for node, field in sources}
    for idle in data.get("idle", []):
        if idle not in known:
            problems.append(f"idle source {idle} is not a ROUTE source of the world")
    print(f"{name}: {len(graph.nodes)} nodes, {len(graph.routes)} ROUTEs, {len(sources)} ROUTE sources; "
          f"contract expects {data['streams']} compared streams")
    for problem in problems:
        print("  problem:", problem)
    return 1 if problems else 0


def record(name):
    here, data = folder(name), contract(name)
    xite = os.environ.get("X_ITE_DIR")
    if not xite or not (pathlib.Path(xite) / "x_ite.min.js").is_file():
        sys.exit("set X_ITE_DIR to an X_ITE 16.7.1 dist folder (the one holding x_ite.min.js)")
    if not os.environ.get("NODE_PATH"):
        sys.exit("set NODE_PATH to a node_modules folder with playwright installed")
    graph = bg.Behaviour.from_x3d((here / f"{name}.x3d").read_text(encoding="utf-8"))
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as sources:
        json.dump(judge.sources_of(graph), sources)
    args = ["node", str(ROOT / "tools" / "behaviour_sim_judge.cjs"), xite, str(here / f"{name}.x3d"), sources.name,
            str(data["clicks"]), str(data["seconds"])]
    if data.get("drags"):
        args.append(str(here / data["drags"]))
    if data.get("keys"):
        args += ["--keys", str(here / data["keys"])]
    plan = None
    if data.get("click_plan"):
        plan = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(data["click_plan"], plan)
        plan.close()
        args += ["--click-plan", plan.name]
    out = subprocess.run(args, capture_output=True, text=True)
    pathlib.Path(sources.name).unlink()
    if plan is not None:
        pathlib.Path(plan.name).unlink()
    if out.returncode != 0:
        sys.exit(f"recorder failed ({out.returncode}):\n{out.stderr[-2000:]}")
    trace = json.loads(out.stdout)
    (here / "x_ite.json").write_text(json.dumps(trace, indent=1) + "\n", encoding="utf-8")
    print(f"recorded {name}: {len(trace.get('events', []))} events, page errors {trace.get('pageErrors')}")
    return 0 if not trace.get("pageErrors") else 1


def run_judge(name):
    here, data = folder(name), contract(name)
    trace_path = here / "x_ite.json"
    if not trace_path.is_file():
        sys.exit(f"no trace: run `python tools/behaviour_demo.py record {name}` first")
    result = judge.judge(here / f"{name}.x3d", json.loads(trace_path.read_text(encoding="utf-8")))
    streams = result["streams"]
    for s in streams:
        print(f"  {'ok ' if s['agree'] else 'BAD'}{'~' if s['source'] in set(data.get('idle', [])) else ' '}{s['source']:40} x_ite {s['x_ite_events']:4}  "
              f"simulator {s['simulator_events']:4}  worst gap {s['worst_gap']:.6f} (tolerance {s['tolerance']})")
    idle = set(data.get("idle", []))
    live = [s for s in streams if s["source"] not in idle]
    quiet = [s for s in streams if s["source"] in idle]
    ok = bool(result.get("agree")) and len(streams) == data["streams"] and all(s["x_ite_events"] > 0 for s in live) \
        and len(quiet) == len(idle) and all(s["x_ite_events"] == 0 and s["simulator_events"] == 0 for s in quiet)
    print(f"{name}: {sum(s['agree'] for s in streams)} of {len(streams)} streams agree "
          f"(contract: {data['streams']}; {len(quiet)} idle, silent in both); {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def show(name, argv):
    folder(name)
    out = pathlib.Path(argv[argv.index("--out") + 1]) if "--out" in argv else pathlib.Path(tempfile.mkdtemp(prefix=f"demo-{name}-"))
    extra = argv[argv.index("--with") + 1:] if "--with" in argv else []
    blender = os.environ.get("BLENDER", "/Applications/Blender.app/Contents/MacOS/Blender")
    args = [blender, "--factory-startup", "--enable-event-simulate", "--window-geometry", "0", "0", "1600", "1000",
            "--python", str(ROOT / "tools" / "behaviour_eyetest.py"), "--", "--out", str(out), "--worlds", name, *extra]
    code = subprocess.run(args).returncode
    witness = out / "host-eyes.json"
    if witness.is_file():
        record = json.loads(witness.read_text())
        print(f"host-eyes: {record['status']} ({record['reason']}); evidence in {out}")
        return 0 if record["status"] == "pass" and code == 0 else 1
    print(f"no witness written (Blender exit {code}); see {out}")
    return 1


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("check", "record", "judge", "show"):
        sys.exit(__doc__)
    command, demo = sys.argv[1], sys.argv[2]
    sys.exit({"check": lambda: check(demo), "record": lambda: record(demo), "judge": lambda: run_judge(demo),
              "show": lambda: show(demo, sys.argv[3:])}[command]())
