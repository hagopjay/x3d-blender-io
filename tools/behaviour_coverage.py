# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""How far the behaviour graph covers the X3D event nodes, computed from the object model and the code.

The "57" are defined in docs/BEHAVIOUR_EVENT_NODES.md: a concrete X3D 4.0 node that inherits X3DSensorNode,
X3DInterpolatorNode, X3DFollowerNode, X3DSequencerNode, X3DTriggerNode, X3DScriptNode or X3DTimeDependentNode, or sits in
the EventUtilities component, plus EaseInEaseOut; minus the Sound component's Web Audio nodes (AudioClip stays) and the
DIS nodes. Each node stands on four rungs (wired, simulated, judged, played) and in one class (pure, or A to E: what it
needs beyond events and time). ::

    python tools/behaviour_coverage.py --markdown                       # the table
    python tools/behaviour_coverage.py --json                           # the same, as data
    python tools/behaviour_coverage.py --write docs/BEHAVIOUR_EVENT_NODES.md   # replace what is between the markers
    python tools/behaviour_coverage.py --check                          # exit 1 when docs/BEHAVIOUR_EVENT_NODES.md is stale
    python tools/behaviour_coverage.py --regenerate X3dUnifiedObjectModel-4.0.xml   # rewrite tools/behaviour_event_nodes.json

The 57 come from ``tools/behaviour_event_nodes.json`` (made from X3DUOM, with its sha256), so a checkout without the
object model can still run the tool and CI can pin the table. ``--regenerate`` recomputes the list from X3DUOM, and
fails loudly if the object model gives anything but 57 nodes in the component counts the document states.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source"))

import behaviour_catalogue as catalogue   # noqa: E402
import behaviour_graph as bg              # noqa: E402
import behaviour_sim as bs                # noqa: E402

NODES_JSON = ROOT / "tools" / "behaviour_event_nodes.json"
DOC = ROOT / "docs" / "BEHAVIOUR_EVENT_NODES.md"
TRACES = ROOT / "tests" / "behaviour" / "x_ite_traces"
WORLDS = ROOT / "tests" / "behaviour"
BEGIN, END = "<!-- coverage:begin", "<!-- coverage:end -->"

# What makes a node an event node (the document's definition).
INHERITS = ("X3DSensorNode", "X3DInterpolatorNode", "X3DFollowerNode", "X3DSequencerNode", "X3DTriggerNode",
            "X3DScriptNode", "X3DTimeDependentNode")
EXTRA_COMPONENT, EXTRA_NODE = "EventUtilities", "EaseInEaseOut"
OUT_OF_SCOPE = {"Sound": "AudioClip", "DIS": None}     # component -> the one node of it that stays (None: all out)

# The per-component counts of the document's table. The object model must give exactly these.
EXPECTED_COUNTS = {"Time": 1, "Interpolation": 13, "EventUtilities": 7, "Followers": 14, "PointingDeviceSensor": 4,
                   "KeyDeviceSensor": 2, "EnvironmentalSensor": 3, "Networking": 1, "Geospatial": 3, "Picking": 4,
                   "RigidBodyPhysics": 1, "Navigation": 1, "Scripting": 1, "Sound": 1, "Texturing": 1}
TOTAL = 57

# The class of a node: what it needs that events and time alone do not give (docs/BEHAVIOUR_EVENT_NODES.md). Every node
# not named here is "pure". A: lists of values. B: the world's shape. C: another coordinate system. D: outside resources
# and their clocks. E: code or an engine the graph cannot run.
CLASSES = {
    "CoordinateChaser": "A", "CoordinateDamper": "A", "TexCoordChaser2D": "A", "TexCoordDamper2D": "A",
    "TransformSensor": "B", "VisibilitySensor": "B", "Collision": "B",
    "GeoProximitySensor": "B+C", "GeoTouchSensor": "B+C",
    "LinePickSensor": "B", "PointPickSensor": "B", "PrimitivePickSensor": "B", "VolumePickSensor": "B",
    "GeoPositionInterpolator": "C",
    "LoadSensor": "D", "AudioClip": "D", "MovieTexture": "D",
    "Script": "E", "CollisionSensor": "E",
}

# HAND-KEPT. What Blender's Player (source/behaviour_play.py, which imports bpy and so cannot be read from here) applies
# or feeds: every simulated node except those the Player gives no input to. The Player feeds the pointing sensors
# (POINTING), the KeySensor and StringSensor (KEY_SENSORS) and the ProximitySensor (the viewport camera); everything else
# simulated is driven by timers and ROUTEs, and what reaches a target is applied or listed as "Not shown". The test
# tests/test_behaviour_coverage.py fails when a simulated node is in neither table, and checks the three feeds against
# the Player's source text.
PLAYED = frozenset({
    "TimeSensor",
    "ScalarInterpolator", "PositionInterpolator", "PositionInterpolator2D", "ColorInterpolator",
    "OrientationInterpolator", "EaseInEaseOut", "SplinePositionInterpolator", "SplinePositionInterpolator2D",
    "SplineScalarInterpolator", "SquadOrientationInterpolator", "CoordinateInterpolator", "CoordinateInterpolator2D",
    "NormalInterpolator",
    "BooleanSequencer", "IntegerSequencer", "BooleanFilter", "BooleanToggle", "BooleanTrigger", "IntegerTrigger",
    "TimeTrigger",
    "ScalarDamper", "PositionDamper", "PositionDamper2D", "ColorDamper", "OrientationDamper",
    "ScalarChaser", "PositionChaser", "PositionChaser2D", "ColorChaser", "OrientationChaser",
    "TouchSensor", "PlaneSensor", "CylinderSensor", "SphereSensor", "ProximitySensor", "KeySensor", "StringSensor",
    "Script", "CollisionSensor",     # hosted: the Player runs a handler the person enabled, and reads the rigid body world
})
NOT_PLAYED = frozenset({"VisibilitySensor"})    # simulated, but the Player has no way to say what the viewer can see
PLAYER_FEEDS = {"POINTING": "from .behaviour_sim import POINTING", "KEY_SENSORS": 'KEY_SENSORS = ("KeySensor", "StringSensor")',
                "ProximitySensor": '"ProximitySensor"', "Script": "behaviour_hosted.build_handler",
                "CollisionSensor": "def _read_bodies"}      # strings that must stay in source/behaviour_play.py


# ---------------------------------------------------------------------------------------------------------------
# The 57
# ---------------------------------------------------------------------------------------------------------------

def _model(path):
    data = Path(path).read_bytes()
    root = ET.fromstring(data)
    info = {}
    for tag in ("ConcreteNode", "AbstractNodeType", "AbstractObjectType"):
        for node in root.iter(tag):
            definition = node.find("InterfaceDefinition")
            bases, component = [], None
            for child in definition if definition is not None else ():
                if child.tag in ("Inheritance", "AdditionalInheritance") and child.get("baseType"):
                    bases.append(child.get("baseType"))
                if child.tag == "componentInfo":
                    component = child.get("name")
            info[node.get("name")] = (tag, bases, component)
    return info, hashlib.sha256(data).hexdigest(), root.get("version")


def _ancestors(info, name, seen=None):
    seen = seen if seen is not None else set()
    for base in info.get(name, (None, [], None))[1]:
        if base not in seen:
            seen.add(base)
            _ancestors(info, base, seen)
    return seen


def event_nodes_from_x3duom(path):
    """{'x3duom_sha256', 'x3duom_version', 'nodes': [{name, component, inherits}], 'out_of_scope': {...}} from the
    object model. Raises ValueError when it does not give the 57 the document describes."""
    info, digest, version = _model(path)
    found, out = [], {}
    for name, (tag, _bases, component) in sorted(info.items()):
        if tag != "ConcreteNode":
            continue
        roots = sorted(_ancestors(info, name) & set(INHERITS))
        if not (roots or component == EXTRA_COMPONENT or name == EXTRA_NODE):
            continue
        if component in OUT_OF_SCOPE and name != OUT_OF_SCOPE[component]:
            out.setdefault(component, []).append(name)
            continue
        found.append({"name": name, "component": component, "inherits": roots})
    found.sort(key=lambda row: (row["component"], row["name"]))
    return _checked({"x3duom_sha256": digest, "x3duom_version": version, "nodes": found,
                     "out_of_scope": {key: sorted(value) for key, value in sorted(out.items())}})


def _checked(data):
    nodes = data["nodes"]
    counts = {}
    for row in nodes:
        counts[row["component"]] = counts.get(row["component"], 0) + 1
    if len(nodes) != TOTAL or counts != EXPECTED_COUNTS:
        raise ValueError(f"the event nodes are not the 57 of docs/BEHAVIOUR_EVENT_NODES.md: {len(nodes)} nodes; per "
                         f"component {dict(sorted(counts.items()))}, the document says {dict(sorted(EXPECTED_COUNTS.items()))}")
    if len({row["name"] for row in nodes}) != len(nodes):
        raise ValueError("a node is listed twice")
    return data


def load_event_nodes():
    data = json.loads(NODES_JSON.read_text(encoding="utf-8"))
    if data["x3duom_sha256"] != catalogue.X3DUOM_SHA256:
        raise ValueError("tools/behaviour_event_nodes.json was made from a different X3DUOM than source/behaviour_catalogue.py")
    return _checked(data)


# ---------------------------------------------------------------------------------------------------------------
# The rungs
# ---------------------------------------------------------------------------------------------------------------

def recorded_worlds():
    """[(label, Behaviour)] for every world under tests/behaviour that has a trace recorded on X_ITE: a file in
    tests/behaviour/x_ite_traces/ with a world of the same name beside it, and each demo folder that holds a
    ``demo.json`` and an ``x_ite.json``. The label is the file the probe is in."""
    worlds = []
    for trace in sorted(TRACES.glob("*.json")):
        world = WORLDS / f"{trace.stem}.x3d"
        if world.is_file():
            worlds.append((f"{trace.stem}.x3d", bg.Behaviour.from_x3d(world.read_text(encoding="utf-8"))))
    demos = WORLDS / "demos"
    for folder in sorted(demos.iterdir()) if demos.is_dir() else ():
        if (folder / "demo.json").is_file() and (folder / "x_ite.json").is_file():
            worlds.append((f"demos/{folder.name}", bg.Behaviour.from_x3d(
                (folder / f"{folder.name}.x3d").read_text(encoding="utf-8"))))
    return worlds


def judged_in(worlds):
    """{node type: [labels]}: where a node of this type sends on a ROUTE in a recorded world. A node that only receives
    is never compared, so it is not judged by it (the rule tests/test_behaviour_sim.py::test_the_probe_covers_what_the_
    simulator_runs states)."""
    found = {}
    for label, graph in worlds:
        for route in graph.routes:
            node = graph.nodes[route.from_id]
            if node.role == bg.BEHAVIOUR and node.node_type in bs.SIMULATED:
                found.setdefault(node.node_type, set()).add(label)
    return {name: sorted(labels) for name, labels in found.items()}


def wired(name):
    return name in catalogue.NODES or name in getattr(catalogue, "IN_PLACE", ())


def coverage():
    """The whole table as plain data."""
    data = load_event_nodes()
    judged = judged_in(recorded_worlds())
    rows = []
    for entry in data["nodes"]:
        name = entry["name"]
        rows.append({
            "node": name, "component": entry["component"], "class": CLASSES.get(name, "pure"),
            "wired": wired(name), "simulated": name in bs.SIMULATED,
            "judged": name in judged, "probes": judged.get(name, []),
            "played": name in PLAYED and name in bs.SIMULATED,
        })
    summary = {key: sum(1 for row in rows if row[key]) for key in ("wired", "simulated", "judged", "played")}
    summary["nodes"] = len(rows)
    by_component = {}
    for row in rows:
        item = by_component.setdefault(row["component"], {"nodes": 0, "wired": 0, "simulated": 0, "judged": 0, "played": 0})
        item["nodes"] += 1
        for key in ("wired", "simulated", "judged", "played"):
            item[key] += int(row[key])
    return {"x3duom_sha256": data["x3duom_sha256"], "x3duom_version": data["x3duom_version"], "summary": summary,
            "by_component": by_component, "rows": rows, "out_of_scope": data.get("out_of_scope", {})}


# ---------------------------------------------------------------------------------------------------------------
# The text
# ---------------------------------------------------------------------------------------------------------------

def _mark(flag):
    return "yes" if flag else "-"


def _probes(labels):
    if not labels:
        return "-"
    shown = ", ".join(f"`{label}`" for label in labels[:2])
    return shown + (f" and {len(labels) - 2} more" if len(labels) > 2 else "")


def markdown(data=None):
    data = data or coverage()
    total = data["summary"]
    lines = [
        f"{total['nodes']} event nodes: **{total['wired']} wired, {total['simulated']} simulated, {total['judged']} judged, "
        f"{total['played']} played**. Instrument: `tools/behaviour_coverage.py` over `tools/behaviour_event_nodes.json` "
        f"(X3DUOM {data['x3duom_version']}, sha256 `{data['x3duom_sha256'][:12]}`), `source/behaviour_catalogue.py`, "
        "`source/behaviour_sim.py` (`SIMULATED`) and the traces in `tests/behaviour/x_ite_traces/` and "
        "`tests/behaviour/demos/*/x_ite.json`. Judged means the node sends on a ROUTE in a world recorded on X_ITE and "
        "the simulator agrees stream for stream; the probes column names where (first two). Played is hand-kept in the "
        "tool (see its comment); the test pins it.",
        "",
        "| component | nodes | wired | simulated | judged | played |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for component, item in data["by_component"].items():
        lines.append(f"| {component} | {item['nodes']} | {item['wired']} | {item['simulated']} | {item['judged']} | "
                     f"{item['played']} |")
    lines += ["", "| node | component | class | wired | simulated | judged | played | probes |",
              "|---|---|---|:-:|:-:|:-:|:-:|---|"]
    for row in data["rows"]:
        lines.append(f"| {row['node']} | {row['component']} | {row['class']} | {_mark(row['wired'])} | "
                     f"{_mark(row['simulated'])} | {_mark(row['judged'])} | {_mark(row['played'])} | "
                     f"{_probes(row['probes'])} |")
    return "\n".join(lines) + "\n"


def written(doc_text, table):
    """``doc_text`` with what lies between the coverage markers replaced by ``table``."""
    start = doc_text.index(BEGIN)
    start = doc_text.index("\n", start) + 1
    end = doc_text.index(END)
    return doc_text[:start] + table + doc_text[end:]


def is_stale(doc=DOC):
    text = Path(doc).read_text(encoding="utf-8")
    return written(text, markdown()) != text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--markdown", action="store_true", help="print the table")
    parser.add_argument("--json", action="store_true", help="print the table as data")
    parser.add_argument("--write", metavar="DOC", help="replace the text between the coverage markers in DOC")
    parser.add_argument("--check", action="store_true", help="exit 1 when docs/BEHAVIOUR_EVENT_NODES.md is stale")
    parser.add_argument("--regenerate", metavar="X3DUOM", help="rewrite tools/behaviour_event_nodes.json from the object model")
    args = parser.parse_args(argv)
    if args.regenerate:
        data = event_nodes_from_x3duom(args.regenerate)
        if data["x3duom_sha256"] != catalogue.X3DUOM_SHA256:
            sys.exit("that X3DUOM is not the one source/behaviour_catalogue.py was made from (sha256 differs)")
        NODES_JSON.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {NODES_JSON} ({len(data['nodes'])} nodes)")
        return 0
    if args.write:
        path = Path(args.write)
        path.write_text(written(path.read_text(encoding="utf-8"), markdown()), encoding="utf-8")
        print(f"wrote the coverage table into {path}")
        return 0
    if args.check:
        stale = is_stale()
        print("docs/BEHAVIOUR_EVENT_NODES.md is stale: run tools/behaviour_coverage.py --write docs/BEHAVIOUR_EVENT_NODES.md"
              if stale else "docs/BEHAVIOUR_EVENT_NODES.md is current")
        return 1 if stale else 0
    if args.json:
        print(json.dumps(coverage(), indent=1))
        return 0
    print(markdown(), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
