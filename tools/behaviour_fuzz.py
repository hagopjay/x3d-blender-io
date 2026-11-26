# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Throw random and hostile behaviour graphs at the graph, the simulator and the X3D round trip.

    python tools/behaviour_fuzz.py --count 2000 --seed 1                 # normal graphs: legal, finite, typed
    python tools/behaviour_fuzz.py --count 2000 --seed 1 --hostile       # wrong, empty, NaN, huge, mismatched, cyclic
    python tools/behaviour_fuzz.py --count 1 --seed 1 --only 17 --show   # one graph, with its schedule

Deterministic from ``--seed``: graph ``k`` of a run is built from ``random.Random(seed * 1000003 + k)`` and nothing else.
Every behaviour node type and every target type of ``behaviour_catalogue`` is used (graph ``k`` always contains node
type ``k mod len(NODES)`` and target type ``k mod len(TARGETS)``; a Script gets declared fields and random source, and the
nodes that hold content get a picking geometry, a reference by USE or, when hostile, markup that is not XML). Plain Python; no Blender, no network, no model.

Properties checked for every graph (``--properties`` names them in the receipt):

  a  nothing but a BehaviourError escapes ``Simulation`` (construction and every call); a node the simulator does not
     run is in ``not_simulated``. A BehaviourError is the documented answer to a call that names a node or field the
     simulation does not have, and is counted as ``rejected``.
  b  every call returns in under ``--call-seconds`` and a call delivers no more events to targets than the loop rule
     allows (one event per ROUTE per timestamp); a graph that runs over ``--graph-seconds`` is stopped by an alarm.
  c  normal: every value in ``sim.values`` (and every value a call returned) is finite and has the arity of its target
     field. Hostile rule: a non-finite number is never delivered to a target or a node; it is dropped and counted in
     ``sim.dropped``, so the same finiteness test holds, and a value whose shape does not fit the destination field
     (a float into a Vec3f, a Python tuple of the wrong length) is dropped and counted the same way.
     Normal graphs must also have no ``sim.faults`` (a node the simulator had to isolate after it raised).
  d  ``Behaviour.from_x3d(to_x3d(graph))`` has no ``difference`` from the graph (normal). Hostile: ``to_x3d`` either
     raises a BehaviourError (a ValueError) or its file parses and has no difference. A field whose text is empty is
     unset by design (``node_xml`` leaves it out), so it is compared as unset.
  e  the same seed gives the same log, values and counters on a second run.

A failing graph is minimised (routes, nodes and calls are dropped while the same kind of failure remains) and printed
as JSON with its schedule.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import platform
import random
import signal
import sys
import time
import warnings
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "source"))
import behaviour_catalogue as cat      # noqa: E402
import behaviour_graph as bg           # noqa: E402
import behaviour_sim as bs             # noqa: E402

NODE_TYPES = sorted(cat.NODES)
TARGET_TYPES = sorted(cat.TARGETS)
LIST_FOLLOWERS = ("CoordinateChaser", "CoordinateDamper", "TexCoordChaser2D", "TexCoordDamper2D")   # lists whose lengths need not agree
PROPERTIES = ("a-no-exception", "b-bounded", "c-values", "d-round-trip", "e-deterministic")
POINTER_OPS = ("press", "drag", "release", "hover", "click")

# ---------------------------------------------------------------------------------------------------------------
# field values (X3D text)
# ---------------------------------------------------------------------------------------------------------------

_SIZE = {"SFVec2f": 2, "SFVec3f": 3, "SFColor": 3, "SFRotation": 4, "SFColorRGBA": 4}
_WORDS = ["", "a", "Hello", "x y", 'quo"te', "back\\slash", "tab\there", "line\nbreak", "<&>", "\x01ctl", "é☃"]


def _f(x):
    return repr(round(x, 4))


def _vec(rng, kind, lo=-5.0, hi=5.0):
    size = _SIZE[kind]
    if kind == "SFColor":
        return " ".join(_f(rng.random()) for _ in range(3))
    if kind == "SFRotation":
        axis = [rng.uniform(-1, 1) for _ in range(3)]
        norm = math.sqrt(sum(c * c for c in axis)) or 1.0
        return " ".join(_f(c / norm) for c in axis) + " " + _f(rng.uniform(-7, 7))
    return " ".join(_f(rng.uniform(lo, hi)) for _ in range(size))


def valid_scalar(rng, name, kind):
    """One legal single value of an X3D field type, honouring what a few named fields mean."""
    if kind == "SFBool":
        return rng.choice(["true", "false"])
    if kind == "SFInt32":
        return str(rng.randint(0, 5) if name == "order" else rng.randint(-3, 6))
    if kind == "SFString":
        return rng.choice(["", "a", "Hello", "x y"])
    if kind in _SIZE:
        return _vec(rng, kind)
    if name == "cycleInterval":
        return _f(rng.uniform(0.2, 4))
    if name in ("duration", "tau"):
        return _f(rng.uniform(0.0, 2.0))
    if name == "tolerance":
        return rng.choice(["-1", "0.001", "0.01"])
    if name in ("startTime", "stopTime", "pauseTime", "resumeTime"):
        return _f(rng.uniform(0, 8))
    if name == "diskAngle":
        return _f(rng.uniform(0.1, 1.5))
    if name in ("minAngle", "maxAngle"):
        return _f(rng.uniform(-3, 3))
    return _f(rng.uniform(-5, 5))


def _unit(rng):
    v = [rng.gauss(0, 1) for _ in range(3)]
    length = math.sqrt(sum(c * c for c in v)) or 1.0
    return [c / length for c in v]


def valid_field(rng, node_type, name, kind, n):
    """Text of a legal value; ``n`` is the node's key count, which key and keyValue must agree on."""
    if kind.startswith("SF"):
        if node_type == "ProximitySensor" and name == "size":
            return rng.choice(["-1 -1 -1", "2 2 2", "0 1 1", "10 10 10"])
        if node_type == "PlaneSensor" and name in ("minPosition", "maxPosition"):
            return rng.choice(["0 0", "-1 -1", "2 2", "1 1"])
        return valid_scalar(rng, name, kind)
    base = kind[2:]
    if name == "key":
        marks = sorted(rng.sample(range(0, 101), n))
        return " ".join(_f(m / 100) for m in marks)
    if name == "easeInEaseOut":
        return " ".join(f"{_f(rng.random())} {_f(rng.random())}" for _ in range(n))
    if base == "Bool":
        return " ".join(rng.choice(["true", "false"]) for _ in range(n))
    if base == "Int32":
        return " ".join(str(rng.randint(-3, 6)) for _ in range(n))
    if base == "String":
        return " ".join('"' + rng.choice(["a", "b c", "d"]) + '"' for _ in range(rng.randint(0, 3)))
    if base == "Float":
        return " ".join(_f(rng.uniform(-5, 5)) for _ in range(n))
    if node_type in LIST_FOLLOWERS and name in ("initialValue", "initialDestination"):
        n = rng.randint(0, 5)                    # the two lists need not be as long as each other (nor as long as key)
    if "Vec2f" == base:
        return " ".join(_vec(rng, "SFVec2f") for _ in range(n))
    if "Vec3f" == base and node_type == "NormalInterpolator":      # unit vectors: a slerp of others can be NaN (as in X_ITE)
        return " ".join(_f(c) for _ in range(n) for c in _unit(rng))
    if "Vec3f" == base:
        return " ".join(_vec(rng, "SFVec3f") for _ in range(n))
    if base == "Color":
        return " ".join(_vec(rng, "SFColor") for _ in range(n))
    if base == "Rotation":
        return " ".join(_vec(rng, "SFRotation") for _ in range(n))
    return ""


_HOSTILE_NUMBERS = ["nan", "NaN", "inf", "-inf", "Infinity", "1e308", "-1e308", "1e38", "3.5e38", "1e-320", "0", "-0",
                    "-1", "1e300", "99999999999999999999", "0.0000001", "abc", "", "1,2", "0x10", "1e", "--1"]


def hostile_field(rng, node_type, name, kind, n):
    """Text that is wrong in one of the ways a user, a bad file or a search program can get it wrong."""
    roll = rng.random()
    if roll < 0.30:
        return valid_field(rng, node_type, name, kind, n)
    if kind in ("SFNode", "MFNode"):
        return rng.choice(["NULL", "", "junk"])
    base = kind[2:]
    size = _SIZE.get(kind, 1)
    if kind.startswith("MF"):
        size = {"Vec2f": 2, "Vec3f": 3, "Color": 3, "Rotation": 4, "ColorRGBA": 4}.get(base, 1)
    if name == "key" or kind.startswith("MF"):
        count = rng.choice([0, 0, 1, 2, 3, 5, n + 1, max(0, n - 1)])
        if name == "key":
            pool = ["0", "0", "0.5", "1", "1", "-1", "2", "0.25", "nan", "inf", "1e308", "-1e308"]
            return " ".join(rng.choice(pool) for _ in range(count))
        if base in ("String",):
            return " ".join('"' + rng.choice(_WORDS) + '"' for _ in range(count))
        items = []
        for _ in range(count * size + rng.choice([0, 0, 0, 1, -1])):
            items.append(rng.choice(_HOSTILE_NUMBERS) if rng.random() < 0.35 else _f(rng.uniform(-5, 5)))
        return " ".join(items)
    if kind == "SFString":
        return rng.choice(_WORDS)
    if kind == "SFBool":
        return rng.choice(["true", "false", "TRUE", "yes", "1", "", "nan", "True"])
    parts = size + rng.choice([0, 0, 0, 1, -1, -size])
    parts = max(0, parts)
    items = [rng.choice(_HOSTILE_NUMBERS) if rng.random() < 0.5 else _f(rng.uniform(-5, 5)) for _ in range(parts)]
    if kind == "SFRotation" and rng.random() < 0.3:
        items = ["0", "0", "0", rng.choice(["1", "0", "nan", "1e308"])]       # a zero-length axis
    return " ".join(items)


# ---------------------------------------------------------------------------------------------------------------
# graphs
# ---------------------------------------------------------------------------------------------------------------

def _settable(rows):
    """The rows a value may be given: not events, and not node-valued fields (those are content, never an attribute)."""
    return [row for row in rows if row[2] in ("inputOutput", "initializeOnly") and row[1] not in bg.NODE_FIELD_TYPES]


def _content(rng, node, index, hostile):
    """What a node that holds content holds: a Script's source (text with the characters markup is made of), a pick
    sensor's geometry or references, a bit of nothing. Hostile adds a reference to nothing and markup that is not XML."""
    if node.node_type == "Script":
        text = "".join(rng.choice(["a", " ", "<", "&", "]]>", "\n", "x=1;", "é", '"', "'"]) for _ in range(rng.randint(0, 12)))
        return bg._markup_text(text) if text.strip() else ""
    parts = []
    if node.node_type.endswith("PickSensor") and rng.random() < 0.7:
        parts.append(f'<Box DEF="Pick{index}" containerField="pickingGeometry"/>')
    if hostile and rng.random() < 0.3:
        parts.append(rng.choice(['<Group USE="Missing" containerField="pickTarget"/>', "<unclosed", "&bad;", "</x>"]))
    return "".join(parts)


def _ends(rows, outgoing):
    keep = ("outputOnly", "inputOutput") if outgoing else ("inputOnly", "inputOutput")
    return [row for row in rows if row[2] in keep]


def _spelling(rng, row, outgoing):
    """A field's name as a ROUTE may spell it: x, set_x or x_changed."""
    name, access = row[0], row[2]
    if access == "inputOutput" and rng.random() < 0.3:
        return f"{name}_changed" if outgoing else f"set_{name}"
    return name


def generate(rng, index, hostile):
    """A Behaviour and its schedule, from the generator state alone."""
    graph = bg.Behaviour()
    types = [NODE_TYPES[index % len(NODE_TYPES)]]
    types += [rng.choice(NODE_TYPES) for _ in range(rng.randint(1, 6))]
    target_types = [TARGET_TYPES[index % len(TARGET_TYPES)], "Transform"]
    target_types += [rng.choice(TARGET_TYPES) for _ in range(rng.randint(0, 2))]
    rng.shuffle(target_types)
    for i, target_type in enumerate(target_types):
        graph.target(target_type, f"T{i}")
    for node in graph.nodes.values():             # a ComposedShader declares some fields of its own, of random types and access
        if node.node_type in bg.DECLARING_TYPES:
            names = rng.sample(["uTime", "uTint", "uSteps", "uFlag", "uOffset", "uAxis", "uMatrix", "uName", "uTimes", "uPoints"],
                               rng.randint(1, 5))
            kinds = rng.sample(sorted(bg.FIELD_TYPES), len(names))
            node.declared = tuple((n, k, rng.choice(["inputOutput", "inputOutput", "inputOnly", "outputOnly", "initializeOnly"]))
                                  for n, k in zip(names, kinds))
    transforms = [n.id for n in graph.nodes.values() if n.node_type == "Transform"]
    for i, node_type in enumerate(types):
        name = f"N{i}" if not hostile or rng.random() < 0.8 else rng.choice(["a-b.c", "_x", "N.1", "Z" * 40, "é", "x y", "x\n", "1x", "a\"b"]) + (str(i) if rng.random() < 0.8 else "")
        parent = rng.choice(transforms) if node_type in bg.PLACED_TYPES and transforms and rng.random() < 0.5 else None
        try:
            node = graph.add(node_type, name, parent=parent).node
        except bg.BehaviourError:                         # a name X3D does not allow is refused, with a clear error
            node = graph.add(node_type, f"N{i}", parent=parent).node
        rows = cat.NODES[node_type][1]
        if node_type in bg.DECLARING_TYPES:                # a Script declares fields of its own, node types included
            names = rng.sample(["go", "inA", "outB", "state", "pts", "things", "thing", "when"], rng.randint(0, 5))
            kinds = rng.sample(sorted(bg.FIELD_TYPES | bg.NODE_FIELD_TYPES), len(names))
            node.declared = tuple((n, k, rng.choice(["inputOutput", "inputOnly", "outputOnly", "initializeOnly"]))
                                  for n, k in zip(names, kinds))
        if node_type in bg.CONTENT_TYPES:
            node.content = _content(rng, node, i, hostile)
            node.inner = tuple(sorted(bg._use_names(node.content)[1]))
        count = rng.randint(1, 5) if not hostile else rng.choice([1, 2, 3, 4, 5, 8])
        for row in _settable(rows):
            if rng.random() < (0.55 if not hostile else 0.65):
                make = hostile_field if hostile else valid_field
                node.fields[row[0]] = make(rng, node_type, row[0], row[1], count)
    for node in graph.nodes.values():
        if node.node_type == "TimeSensor" and rng.random() < 0.6 and not hostile:
            node.fields["loop"] = rng.choice(["true", "false"])
            node.fields["startTime"] = _f(rng.uniform(0, 3))
            node.fields["stopTime"] = "0"
    # ROUTEs: legal ones by type; hostile adds wrong ones
    sources, sinks = [], []
    for node in graph.nodes.values():
        rows = bg.node_rows(node)
        sources += [(node, row) for row in _ends(rows, True)]
        sinks += [(node, row) for row in _ends(rows, False)]
    routes = rng.randint(2, 14)
    reused = []
    for _ in range(routes):
        node, row = rng.choice(sources)
        if reused and rng.random() < 0.35:
            node, row = rng.choice([(n, r) for n, r in sources if n.id in reused] or sources)
        same = [(n, r) for n, r in sinks if r[1] == row[1]]
        if reused and rng.random() < 0.3:
            same = [(n, r) for n, r in same if n.id in reused] or same
        if rng.random() < 0.15:
            same = [(n, r) for n, r in same if n is node] or same           # a self-loop where the node has one
        if not same:
            continue
        other, other_row = rng.choice(same)
        graph.route(node.id, _spelling(rng, row, True), other.id, _spelling(rng, other_row, False), check=False)
        reused += [node.id, other.id]
    # a few ROUTEs that end at a scene node, so what the simulator sends reaches a target
    machines = [(n, r) for n, r in sources if n.role == bg.BEHAVIOUR]
    scene = [(n, r) for n, r in sinks if n.role == bg.TARGET]
    for _ in range(rng.randint(1, 4) if machines else 0):
        node, row = rng.choice(machines)
        same = [(n, r) for n, r in scene if r[1] == row[1]]
        if same:
            other, other_row = rng.choice(same)
            graph.route(node.id, _spelling(rng, row, True), other.id, _spelling(rng, other_row, False), check=False)
    if hostile:
        ids = list(graph.nodes)
        for _ in range(rng.randint(1, 6)):
            node, row = rng.choice(sources)
            other, other_row = rng.choice(sinks)
            roll = rng.random()
            if roll < 0.10:
                graph.route(node.id, row[0], "Nowhere", other_row[0], check=False)
            elif roll < 0.18:
                graph.route(node.id, "nothing", other.id, other_row[0], check=False)
            elif roll < 0.25:
                graph.route(rng.choice(ids), row[0], rng.choice(ids), "set_" + other_row[0], check=False)
            else:
                graph.route(node.id, row[0], other.id, other_row[0], check=False)
    return graph, schedule(rng, graph, hostile)


# ---------------------------------------------------------------------------------------------------------------
# schedules
# ---------------------------------------------------------------------------------------------------------------

def _vector(rng, hostile, size=3):
    if hostile and rng.random() < 0.3:
        return tuple(rng.choice([0.0, 1e308, -1e308, math.nan, math.inf, 1e-300]) for _ in range(size))
    return tuple(rng.uniform(-3, 3) for _ in range(size))


def _event_value(rng, kind, hostile):
    """A Python value for an X3D field type; hostile adds the wrong ones."""
    if hostile and rng.random() < 0.2:
        return rng.choice([None, "text", [], (), (1.0,), (1.0, 2.0, 3.0, 4.0, 5.0), True, -1, 1e308, math.nan, math.inf,
                           {"a": 1}, [(1, 2, 3)], b"x"])
    if kind == "SFBool":
        return rng.random() < 0.5
    if kind == "SFInt32":
        return rng.randint(-5, 9)
    if kind in _SIZE:
        size = _SIZE[kind]
        return _vector(rng, hostile, size)
    if kind.startswith("MF"):
        return [_event_value(rng, "SF" + kind[2:], False) for _ in range(rng.randint(0, 3))]
    if kind == "SFString":
        return rng.choice(_WORDS)
    if hostile and rng.random() < 0.25:
        return rng.choice([math.nan, math.inf, -math.inf, 1e308, -1e308, 0.0, -0.0, 1e-320])
    return rng.uniform(-3, 6)


def schedule(rng, graph, hostile):
    """A list of calls: [name, args...], plain data so a failure can be written out and replayed."""
    calls, clock = [], 0.0
    ids = list(graph.nodes)
    pointing = [n.id for n in graph.nodes.values() if n.node_type in bs.POINTING]
    proximity = [n.id for n in graph.nodes.values() if n.node_type == "ProximitySensor"]
    colliders = [n.id for n in graph.nodes.values() if n.node_type == "CollisionSensor"]
    behaviours = [n for n in graph.nodes.values() if n.role == bg.BEHAVIOUR]
    if not hostile:
        behaviours = [n for n in behaviours if n.node_type in bs.SIMULATED] or behaviours
    if rng.random() < (0.9 if not hostile else 0.75):
        calls.append(["start", 0.0 if not hostile or rng.random() < 0.8 else rng.choice([-5.0, 3.0, 1e9])])

    def tick():
        nonlocal clock
        if not hostile:
            clock += rng.choice([0.0, 0.016, 0.05, 0.3, 1.0, 2.5, 20.0])
            return clock
        roll = rng.random()
        if roll < 0.35:
            clock += rng.choice([0.016, 0.5, 2.0])
        elif roll < 0.55:
            pass                                               # the same time again
        elif roll < 0.75:
            clock -= rng.choice([0.5, 3.0])                    # time going backwards
        elif roll < 0.85:
            clock += rng.choice([1e6, 1e12, 1e300])
        elif roll < 0.92:
            return rng.choice([math.nan, math.inf, -math.inf, -1e300])
        else:
            clock = 0.0
        return clock

    def target_of(want_pointing=False):
        if want_pointing and pointing and (not hostile or rng.random() < 0.85):
            return rng.choice(pointing)
        return rng.choice(ids)

    for _ in range(rng.randint(8, 40) if not hostile else rng.randint(8, 50)):
        op = rng.choice(["step", "step", "step", "click", "press", "drag", "release", "hover", "send", "send", "post",
                         "viewer", "contact"])
        if not hostile and ((op in POINTER_OPS and not pointing) or (op == "viewer" and not proximity)
                            or (op == "contact" and not colliders)):
            op = "step"                                         # a normal schedule only asks a node for what it can do
        now = tick()
        if op == "step":
            calls.append(["step", now])
        elif op in POINTER_OPS:
            node = target_of(True)
            ray = [list(_vector(rng, hostile)), list(_vector(rng, hostile))]
            eye = [list(_vector(rng, hostile)), list(_vector(rng, hostile))]
            point = list(_vector(rng, hostile))
            if op == "click":
                calls.append(["click", node, now, rng.choice([0.0, 0.1, 2.0])])
            elif op == "press":
                calls.append(["press", node, now, point, ray if rng.random() < 0.7 else None, eye, rng.random() < 0.8])
            elif op == "drag":
                calls.append(["drag", node, point, now, ray if rng.random() < 0.8 else None])
            elif op == "release":
                calls.append(["release", node, now])
            else:
                calls.append(["hover", node, rng.random() < 0.5, now])
        elif op == "contact":             # what a physics engine says: touching or not, and which nodes
            node = rng.choice(colliders) if colliders and (not hostile or rng.random() < 0.85) else rng.choice(ids)
            names = [rng.choice(_WORDS) for _ in range(rng.randint(0, 3))]
            if hostile and rng.random() < 0.2:
                names = rng.choice([None, "AB", [1, 2], [None], names + [math.nan]])
            calls.append(["contact", node, rng.random() < 0.5 if not hostile or rng.random() < 0.8 else rng.choice([1, None, "yes"]),
                          names, names if rng.random() < 0.7 else [], now])
        elif op == "viewer":
            node = rng.choice(proximity) if proximity and rng.random() < 0.9 else rng.choice(ids)
            calls.append(["viewer", node, list(_vector(rng, hostile)), list(_vector(rng, hostile, 4)), now,
                          list(_vector(rng, hostile)), None if rng.random() < 0.7 else list(_vector(rng, hostile))])
        else:
            node = rng.choice(behaviours) if behaviours and (not hostile or rng.random() < 0.85) else None
            if node is None:
                calls.append([op, rng.choice(ids + ["Nowhere"]), "x", 1.0, now])
                continue
            rows = bg.node_rows(node)
            if op == "send":
                pool = _ends(rows, False) or rows
            else:
                pool = _ends(rows, True) or rows
            row = rng.choice(pool)
            calls.append([op, node.id, row[0], _event_value(rng, row[1], hostile), now])
    return calls


# ---------------------------------------------------------------------------------------------------------------
# running a case and checking it
# ---------------------------------------------------------------------------------------------------------------

class Hang(BaseException):      # not an Exception: the simulator must not be able to swallow the alarm
    pass


def _alarm(_signal, _frame):
    raise Hang("graph ran over its time limit")


def fits(value, x3d_type):
    """Is ``value`` a legal Python value of an X3D field type (the tool's own test, independent of the simulator's)?"""
    if x3d_type == "SFBool":
        return isinstance(value, bool)
    if x3d_type == "SFString":
        return isinstance(value, str)
    if x3d_type in ("SFNode", "MFNode"):
        return True
    if x3d_type.startswith("MF"):
        return isinstance(value, list) and all(fits(item, "SF" + x3d_type[2:]) for item in value)
    if x3d_type in ("SFFloat", "SFTime", "SFDouble", "SFInt32"):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and \
            (x3d_type != "SFInt32" or isinstance(value, int))
    size = _SIZE.get(x3d_type)
    if size is None:
        return True
    return isinstance(value, tuple) and len(value) == size and all(
        isinstance(c, (int, float)) and not isinstance(c, bool) for c in value)


def finite(value):
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, (tuple, list)):
        return all(finite(item) for item in value)
    return True


def field_type(graph, node_id, field_name):
    node = graph.nodes.get(node_id)
    if node is None or node.role == bg.CARRIED:
        return None
    try:
        return bg.resolve_field(node.node_type, field_name, "in", node.declared)[1]
    except bg.BehaviourError:
        try:
            return bg.resolve_field(node.node_type, field_name, "out", node.declared)[1]
        except bg.BehaviourError:
            return None


def _apply_call(sim, call):
    name, args = call[0], call[1:]
    if name == "start":
        return sim.start(args[0])
    if name == "step":
        return sim.step(args[0])
    if name == "click":
        return sim.click(args[0], args[1], args[2])
    if name == "press":
        node, now, point, ray, eye, follow = args
        return sim.press(node, now, tuple(point), None if ray is None else (tuple(ray[0]), tuple(ray[1])),
                         (tuple(eye[0]), tuple(eye[1])), follow)
    if name == "drag":
        node, point, now, ray = args
        return sim.drag(node, tuple(point), now, None if ray is None else (tuple(ray[0]), tuple(ray[1])))
    if name == "release":
        return sim.release(args[0], args[1])
    if name == "hover":
        return sim.hover(args[0], args[1], args[2])
    if name == "viewer":
        node, position, orientation, now, centre, test = args
        return sim.viewer(node, tuple(position), tuple(orientation), now, tuple(centre), None if test is None else tuple(test))
    if name in ("send", "post"):
        node, field_name, value, now = args
        return getattr(sim, name)(node, field_name, value, now)
    if name == "contact":
        return sim.contact(*args[:3], args[3], args[4])
    raise ValueError(name)


def _chaos_handler(node, hostile):
    """A Python handler for a Script that sends random values from its declared outputs (typed: any, when hostile, also
    wrong ones, undeclared names, NaN, a request for a later call, and now and then an exception). Deterministic: what it
    does for the n-th call is a function of the node, the field and n."""
    outputs = [row for row in node.declared if row[2] in ("outputOnly", "inputOutput") and row[1] not in bg.NODE_FIELD_TYPES]
    count = [0]

    def handler(field, value, time, state):
        count[0] += 1
        rng = random.Random(f"{node.id}:{field}:{count[0]}")
        sent = []
        for _ in range(rng.randint(0, 3)):
            if outputs and (not hostile or rng.random() < 0.7):
                name, kind, _access = rng.choice(outputs)
                sent.append((name, _event_value(rng, kind, hostile)))
            elif hostile:
                sent.append(rng.choice([("nothing", 1), (None, None), "x", (bs.CALLED_AT, rng.uniform(-1, 30)), (bs.CALLED_AT, math.nan),
                                        ("url", ["a"]), (1, 2, 3)]))
        if hostile and rng.random() < 0.04:
            raise RuntimeError("a handler failed")
        if hostile and rng.random() < 0.03:
            return 5                                                  # not a list at all
        return sent
    return handler


def run_case(graph, calls, hostile, *, call_seconds=2.0, graph_seconds=20):
    """Run one graph through its schedule. Returns (findings, digest, stats); findings are (property, detail)."""
    findings, stats = [], {"calls": 0, "rejected": 0, "targets_hit": 0, "dropped": {}, "faults": 0, "slowest": 0.0}
    digest = []
    armed = hasattr(signal, "SIGALRM")
    if armed:
        try:
            signal.signal(signal.SIGALRM, _alarm)
            signal.alarm(graph_seconds)
        except ValueError:                       # not the main thread
            armed = False
    try:
        try:
            sim = bs.Simulation(graph)
        except Hang as error:
            return [("b-bounded", f"construction: {error}")], digest, stats
        except bg.BehaviourError as error:
            return [("a-no-exception", f"construction: BehaviourError {error}")], digest, stats
        except Exception as error:                                      # noqa: BLE001 - this is what we look for
            return [("a-no-exception", f"construction: {type(error).__name__}: {error}")], digest, stats
        for node in graph.nodes.values():          # half of the Scripts get a handler that sends whatever it is told to
            if node.node_type == "Script" and node.id in sim.machines and zlib.crc32(f"{node.id}{len(graph.routes)}".encode()) % 2 == 0:
                sim.host(node.id, _chaos_handler(node, hostile))
        simulated = {n.id for n in graph.nodes.values() if n.role == bg.BEHAVIOUR and n.node_type in bs.SIMULATED}
        listed = {entry.split(" ", 1)[1] for entry in sim.not_simulated}
        for node in graph.nodes.values():
            if node.role == bg.BEHAVIOUR and node.node_type not in bs.SIMULATED and node.id not in listed:
                findings.append(("a-no-exception", f"{node.node_type} {node.id} is neither simulated nor in not_simulated"))
        for call in calls:
            stats["calls"] += 1
            began = time.perf_counter()
            try:
                changes = _apply_call(sim, call)
            except bg.BehaviourError:
                stats["rejected"] += 1
                changes = []
            except Hang as error:
                findings.append(("b-bounded", f"{call[0]}: {error}"))
                break
            except Exception as error:                                  # noqa: BLE001
                findings.append(("a-no-exception", f"{call[0]}: {type(error).__name__}: {error}"))
                break
            took = time.perf_counter() - began
            stats["slowest"] = max(stats["slowest"], took)
            if took > call_seconds:
                findings.append(("b-bounded", f"{call[0]} took {took:.2f} s"))
            allowed = 16 * (len(graph.routes) + 1)
            if len(changes) > allowed:
                findings.append(("b-bounded", f"{call[0]} delivered {len(changes)} events to targets, over {allowed}"))
            stats["targets_hit"] += len(changes)
            for target_id, field_name, value in changes:
                _check_value(findings, graph, hostile, target_id, field_name, value)
            digest.append((call[0], repr(changes)))
        for (target_id, field_name), value in sim.values.items():
            _check_value(findings, graph, hostile, target_id, field_name, value)
        if not hostile:
            for (node_id, field_name), value in sim.outputs.items():
                if not finite(value):
                    findings.append(("c-values", f"{node_id}.{field_name} sent a non-finite value {value!r}"))
        dropped = dict(getattr(sim, "dropped", {}))
        stats["dropped"] = dropped
        stats["faults"] = dropped.get("fault", 0)
        stats["fault_samples"] = list(getattr(sim, "faults", ()))
        if not hostile and stats["faults"]:
            findings.append(("c-values", f"a node was isolated after raising: {list(sim.faults)[:3]}"))
        digest.append(("end", repr(sorted(sim.values.items(), key=repr)), repr(list(sim.log)), repr(sorted(dropped.items()))))
        del simulated
    finally:
        if armed:
            signal.alarm(0)
    return findings, digest, stats


def _check_value(findings, graph, hostile, target_id, field_name, value):
    if not finite(value):
        findings.append(("c-values", f"{target_id}.{field_name} was given a non-finite value {value!r}"))
        return
    kind = field_type(graph, target_id, field_name)
    if kind is not None and not fits(value, kind):
        findings.append(("c-values", f"{target_id}.{field_name} ({kind}) was given {value!r}"))


# -- the round trip --------------------------------------------------------------------------------------------

def to_x3d(graph):
    """A small X3D document holding the graph: every target as an element of its type, then ``weave``."""
    def element(node):
        if not node.declared:
            return f'  <{node.node_type} DEF="{node.id}"/>\n'
        fields = "".join(f'<field name="{n}" type="{k}" accessType="{a}"/>' for n, k, a in node.declared)
        return f'  <{node.node_type} DEF="{node.id}">{fields}</{node.node_type}>\n'

    scene = "".join(element(node) for node in graph.nodes.values() if node.role == bg.TARGET)
    document = f'<?xml version="1.0" encoding="UTF-8"?>\n<X3D profile="Interchange" version="4.0"><Scene>\n{scene}</Scene></X3D>\n'
    return bg.weave(document, graph)


def _blank_is_unset(graph):
    clean = copy.deepcopy(graph)
    for node in clean.nodes.values():
        node.fields = {k: v for k, v in node.fields.items() if v != ""}
    return clean


def check_round_trip(graph, hostile):
    try:
        text = to_x3d(graph)
    except bg.BehaviourError:
        return [] if hostile else [("d-round-trip", "to_x3d refused a normal graph")]
    except Exception as error:                                          # noqa: BLE001
        return [("d-round-trip", f"to_x3d raised {type(error).__name__}: {error}")]
    try:
        back = bg.Behaviour.from_x3d(text)
    except Exception as error:                                          # noqa: BLE001
        return [("d-round-trip", f"from_x3d could not read to_x3d's file: {type(error).__name__}: {error}")]
    difference = bg.difference(_blank_is_unset(graph), back)
    if any(difference.values()):
        return [("d-round-trip", "difference " + json.dumps({k: v for k, v in difference.items() if v}, default=str)[:300])]
    return []


# -- one graph, all properties -------------------------------------------------------------------------------------

def case(seed, index, hostile):
    rng = random.Random(seed * 1000003 + index + (500009 if hostile else 0))
    return generate(rng, index, hostile)


def check(graph, calls, hostile):
    """All five properties. Returns (findings, stats)."""
    findings, digest, stats = run_case(graph, calls, hostile)
    findings += check_round_trip(graph, hostile)
    again, digest_again, _ = run_case(graph, calls, hostile)
    if not [f for f in findings if f[0] in ("a-no-exception", "b-bounded")] and digest != digest_again:
        findings.append(("e-deterministic", "a second run of the same graph and calls gave a different log"))
    return findings, stats


def snapshot(graph, calls):
    return {"graph": bg.to_json(graph), "calls": calls}


def minimise(graph, calls, hostile, wanted):
    """Drop calls, routes and nodes while a failure of the property ``wanted`` remains."""
    def fails(g, c):
        try:
            return any(f[0] == wanted for f in check(g, c, hostile)[0])
        except Exception:                                               # noqa: BLE001
            return False
    graph, calls = copy.deepcopy(graph), list(calls)
    changed = True
    while changed:
        changed = False
        for i in range(len(calls) - 1, -1, -1):
            trial = calls[:i] + calls[i + 1:]
            if fails(graph, trial):
                calls, changed = trial, True
        for route in list(graph.routes):
            trial = copy.deepcopy(graph)
            trial.routes = [r for r in trial.routes if r.key() != route.key()]
            if fails(trial, calls):
                graph, changed = trial, True
        for name in list(graph.nodes):
            trial = copy.deepcopy(graph)
            trial.nodes.pop(name)
            trial.routes = [r for r in trial.routes if name not in (r.from_id, r.to_id)]
            if fails(trial, calls):
                graph, changed = trial, True
    return graph, calls


def fuzz(count, seed, hostile, *, only=None, minimise_failures=True, limit=12):
    indexes = [only] if only is not None else range(count)
    receipt = {"mode": "hostile" if hostile else "normal", "seed": seed, "graphs": 0,
               "properties": {p: {"checked": 0, "failed": 0} for p in PROPERTIES},
               "calls": 0, "rejected_calls": 0, "target_events": 0, "dropped": {}, "faults": 0,
               "fault_signatures": {}, "node_types_used": set(), "target_types_used": set(), "slowest_call_seconds": 0.0, "failures": []}
    for index in indexes:
        graph, calls = case(seed, index, hostile)
        receipt["graphs"] += 1
        receipt["node_types_used"] |= {n.node_type for n in graph.nodes.values() if n.role == bg.BEHAVIOUR}
        receipt["target_types_used"] |= {n.node_type for n in graph.nodes.values() if n.role == bg.TARGET}
        findings, stats = check(graph, calls, hostile)
        receipt["calls"] += stats["calls"]
        receipt["rejected_calls"] += stats["rejected"]
        receipt["target_events"] += stats["targets_hit"]
        receipt["faults"] += stats["faults"]
        for sample in stats.get("fault_samples", ()):
            node_id, _, rest = sample.partition(".")
            key = rest.split(":")[0] + ": " + rest.split(":")[1].strip() + " [" + graph.nodes[node_id].node_type + "]" \
                if node_id in graph.nodes and rest.count(":") >= 1 else sample
            receipt["fault_signatures"].setdefault(key, {"count": 0, "first_index": index})["count"] += 1
        receipt["slowest_call_seconds"] = max(receipt["slowest_call_seconds"], round(stats["slowest"], 4))
        for key, number in stats["dropped"].items():
            receipt["dropped"][key] = receipt["dropped"].get(key, 0) + number
        failed = {f[0] for f in findings}
        for name in PROPERTIES:
            receipt["properties"][name]["checked"] += 1
            receipt["properties"][name]["failed"] += name in failed
        if findings and len(receipt["failures"]) < limit:
            entry = {"seed": seed, "index": index, "hostile": hostile, "findings": [list(f) for f in findings[:4]]}
            if minimise_failures:
                kind = findings[0][0]
                small_graph, small_calls = minimise(graph, calls, hostile, kind)
                entry["minimised"] = snapshot(small_graph, small_calls)
            receipt["failures"].append(entry)
    receipt["node_types_used"] = sorted(receipt["node_types_used"])
    receipt["target_types_used"] = sorted(receipt["target_types_used"])
    receipt["all_node_types_covered"] = receipt["node_types_used"] == NODE_TYPES if only is None and count >= len(NODE_TYPES) else None
    receipt["all_target_types_covered"] = receipt["target_types_used"] == TARGET_TYPES if only is None and count >= len(TARGET_TYPES) else None
    receipt["failed_graphs"] = len(receipt["failures"])
    return receipt


# ---------------------------------------------------------------------------------------------------------------
# Blender pass: the node tree and the Player
# ---------------------------------------------------------------------------------------------------------------

def _blender_scene(graph, rng):
    """Objects, cameras, lights and materials for every target of ``graph`` that Blender can bind, with random
    transforms; the targets Blender cannot bind (Group, Switch, ...) are taken out of the graph."""
    import bpy
    for node in list(graph.nodes.values()):
        if node.role == bg.TARGET and node.node_type not in bg.BINDING_OF:
            graph.remove(node.id)
    for node in graph.nodes.values():
        if node.role == bg.BEHAVIOUR and node.parent is not None and node.parent not in graph.nodes:
            node.parent = None
    scene = bpy.context.scene
    for node in graph.nodes.values():
        if node.role != bg.TARGET:
            continue
        kind = bg.BINDING_OF[node.node_type]
        node.binding = (kind, node.id)
        if kind == "material":
            with warnings.catch_warnings():                       # use_nodes is deprecated in Blender 6; the Player reads nodes
                warnings.simplefilter("ignore")
                bpy.data.materials.new(node.id).use_nodes = True
            continue
        if kind == "viewpoint":
            data = bpy.data.cameras.new(node.id)
        elif kind == "light":
            data = bpy.data.lights.new(node.id, {"DirectionalLight": "SUN", "SpotLight": "SPOT"}.get(node.node_type, "POINT"))
        else:
            data = None
        obj = bpy.data.objects.new(node.id, data)
        scene.collection.objects.link(obj)
        obj.location = [rng.uniform(-3, 3) for _ in range(3)]
        obj.rotation_euler = [rng.uniform(-3, 3) for _ in range(3)]
        obj.scale = [rng.uniform(0.3, 2) for _ in range(3)]
    # what the Player shows on Blender data, so that the run changes the scene and the restore has something to undo
    shown = {"Transform": ("translation", "rotation", "scale", "visible"), "PointLight": ("color", "on"),
             "DirectionalLight": ("color", "on"), "SpotLight": ("color", "on"),
             "PhysicalMaterial": ("baseColor", "emissiveColor", "transparency", "roughness", "metallic"),
             "Material": ("diffuseColor", "emissiveColor", "transparency"), "UnlitMaterial": ("emissiveColor", "transparency"),
             "Viewpoint": ("position", "orientation", "set_bind"), "OrthoViewpoint": ("position", "orientation", "set_bind")}
    ends = [(n, f) for n in graph.nodes.values() if n.role == bg.TARGET for f in shown.get(n.node_type, ())]
    for _ in range(rng.randint(2, 6)):
        machines = [(n, row) for n in graph.nodes.values() if n.role == bg.BEHAVIOUR and n.node_type in bs.SIMULATED
                    for row in _ends(cat.NODES[n.node_type][1], True)]
        if not machines or not ends:
            break
        node, row = rng.choice(machines)
        fits_ = [(t, f) for t, f in ends if cat.TARGETS[t.node_type] and
                 next(r for r in cat.TARGETS[t.node_type] if r[0] == f)[1] == row[1]]
        if fits_:
            other, other_field = rng.choice(fits_)
            graph.route(node.id, row[0], other.id, other_field, check=False)
    return scene


def _scene_state(scene):
    import bpy
    state = {}
    for obj in bpy.data.objects:
        state[obj.name] = (tuple(tuple(row) for row in obj.matrix_world), tuple(obj.location), tuple(obj.rotation_euler),
                           tuple(obj.rotation_quaternion), tuple(obj.scale), obj.hide_viewport, obj.hide_render,
                           tuple(obj.data.color) if obj.type == "LIGHT" else None)
    for material in bpy.data.materials:
        state["material:" + material.name] = tuple(material.diffuse_color)
    state["camera"] = scene.camera.name if scene.camera else None
    return state


def blender_modules():
    """The add-on's behaviour modules as the package ``io_scene_x3d`` (source/ linked into a temporary folder)."""
    import importlib
    import tempfile
    if "io_scene_x3d.behaviour_nodes" not in sys.modules:
        folder = tempfile.mkdtemp(prefix="x3d_fuzz_")
        (Path(folder) / "io_scene_x3d").symlink_to(Path(__file__).resolve().parent.parent / "source", target_is_directory=True)
        sys.path.insert(0, folder)
        package = importlib.import_module("io_scene_x3d")
        try:
            package.register()
        except Exception:                                               # noqa: BLE001 - already registered
            pass
    return (importlib.import_module("io_scene_x3d.behaviour_nodes"), importlib.import_module("io_scene_x3d.behaviour_play"),
            importlib.import_module("io_scene_x3d.behaviour_graph"))


def bpy_pass(count, seed, *, steps=30, limit=12, hostile=False):
    """``count`` normal graphs through the Blender node tree (apply, read: no difference) and the Player (start, step
    ``steps`` times with clicks and drags, stop: nothing raised, every transform, light and material back exactly).
    ``hostile``: the hostile graphs play directly (``Player(scene, graph)``); the tree comparison is skipped, because
    Blender removes a link between two field types as it is made."""
    import bpy  # noqa: F401 - first: it makes mathutils importable
    import mathutils
    bn, bp, pbg = blender_modules()
    result = {"mode": "blender-hostile" if hostile else "blender", "seed": seed, "graphs": 0, "calls": 0,
              "graphs_that_changed_the_scene_while_playing": 0,
              "properties": {"apply-read-no-difference": {"checked": 0, "failed": 0},
                             "player-no-exception": {"checked": 0, "failed": 0},
                             "player-restores-scene": {"checked": 0, "failed": 0}}, "failures": []}
    for index in range(count):
        graph, _calls = case(seed, index, hostile)
        rng = random.Random(seed * 7919 + index)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bn.ensure_registered()
        bp.ensure_axes_properties()
        scene = _blender_scene(graph, rng)
        result["graphs"] += 1
        found = []
        before_tree = None
        try:
            bn.apply(graph, scene)
            back = bn.read(scene)
            difference = pbg.difference(_blank_is_unset(graph), back)
            if not hostile and any(difference.values()):
                found.append(("apply-read-no-difference", json.dumps({k: v for k, v in difference.items() if v}, default=str)[:400]))
        except Exception as error:                                      # noqa: BLE001
            found.append(("apply-read-no-difference", f"{type(error).__name__}: {error}"))
        result["properties"]["apply-read-no-difference"]["checked"] += 1
        if getattr(scene, "x3d_behaviour_tree", None) is not None:
            before = _scene_state(scene)
            try:
                player = bp.Player(scene, graph if hostile else None)
                player.start(0.0)
                objects = [o for o in bpy.data.objects]
                for k in range(1, steps + 1):
                    now = k * 0.1
                    player.step(now)
                    result["calls"] += 1
                    if objects and k % 4 == 0:
                        obj = rng.choice(objects)
                        if k % 8 == 0:
                            origin = mathutils.Vector([rng.uniform(-3, 3) for _ in range(3)])
                            direction = mathutils.Vector([rng.uniform(-1, 1) for _ in range(3)])
                            player.press(obj, now, tuple(origin), (tuple(origin), tuple(direction)),
                                         (tuple(origin), tuple(-direction)))
                            player.drag(tuple(origin + direction), tuple(direction), now + 0.01)
                            player.release(now + 0.02)
                        else:
                            player.click(obj, now)
                    if k % 5 == 0:
                        player.view(mathutils.Matrix.Translation((k, 0, 1)), (0, 0, 0), now)
                result["graphs_that_changed_the_scene_while_playing"] += _scene_state(scene) != before
                player.stop()
            except Exception as error:                                  # noqa: BLE001
                found.append(("player-no-exception", f"{type(error).__name__}: {error}"))
                try:
                    player.stop()
                except Exception:                                       # noqa: BLE001
                    pass
            result["properties"]["player-no-exception"]["checked"] += 1
            after = _scene_state(scene)
            result["properties"]["player-restores-scene"]["checked"] += 1
            if after != before:
                changed = sorted(k for k in before if before[k] != after.get(k))
                detail = [(k, [(i, a, b) for i, (a, b) in enumerate(zip(before[k], after[k])) if a != b])
                          for k in changed[:2] if isinstance(before[k], tuple)]
                found.append(("player-restores-scene", f"changed after stop: {changed[:4]} {detail}"[:600]))
        for name, _detail in {(f[0], f[1]) for f in found}:
            result["properties"][name]["failed"] += 1
        if found and len(result["failures"]) < limit:
            result["failures"].append({"seed": seed, "index": index, "findings": [list(f) for f in found[:3]],
                                       "graph": bg.to_json(graph)})
    result["failed_graphs"] = len(result["failures"])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--count", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--hostile", action="store_true")
    parser.add_argument("--blender", action="store_true", help="the Blender pass (needs bpy): node tree and Player")
    parser.add_argument("--only", type=int, help="run graph number N of the seed only")
    parser.add_argument("--show", action="store_true", help="with --only: print the graph and its schedule")
    parser.add_argument("--no-minimise", action="store_true")
    parser.add_argument("--out", help="write the JSON receipt here as well")
    args = parser.parse_args(argv)
    if args.show and args.only is not None:
        graph, calls = case(args.seed, args.only, args.hostile)
        print(json.dumps(snapshot(graph, calls), indent=1))
    began = time.perf_counter()
    if args.blender:
        receipt = bpy_pass(args.count, args.seed, hostile=args.hostile)
        receipt["instrument"] = f"tools/behaviour_fuzz.py --blender, Python {platform.python_version()}, bpy"
        receipt["seconds"] = round(time.perf_counter() - began, 1)
        print(json.dumps(receipt, indent=1, default=str))
        return 1 if receipt["failures"] else 0
    receipt = fuzz(args.count, args.seed, args.hostile, only=args.only, minimise_failures=not args.no_minimise)
    receipt["instrument"] = f"tools/behaviour_fuzz.py, Python {platform.python_version()}"
    receipt["seconds"] = round(time.perf_counter() - began, 1)
    text = json.dumps(receipt, indent=1, default=str)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 1 if receipt["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
