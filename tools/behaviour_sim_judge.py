# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Does the Python simulator do what X_ITE does?

    python tools/behaviour_sim_judge.py --sources file.x3d > sources.json     # every ROUTE source of the file
    node   tools/behaviour_sim_judge.cjs <x_ite dir> file.x3d sources.json <clicks> <seconds> > trace.json
    python tools/behaviour_sim_judge.py file.x3d trace.json                    # replay and compare

The trace is X_ITE's own account: every event at every ROUTE source, with X_ITE's time stamp. The replay gives the
simulator the same pointer events (whatever the pointing sensors sent) at the same times, steps it at X_ITE's own frame
times, and compares every other event stream, source by source. Followers use the frame time, so they are compared with
a looser tolerance than everything else (X_ITE takes its step from the frame rate, the simulator from the clock).
"""

import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "source"))
import behaviour_graph as bg          # noqa: E402
import behaviour_sim as bs            # noqa: E402

EXACT, FOLLOWER = 2e-3, 8e-2
PIXEL_CENTRE = 0.0       # drag rays: X_ITE uses the pointer as given (getPointerFromEvent); the press point comes from its pick


# -- drag sensors: the pointer's ray, rebuilt from the recorded pointer and the viewpoint ------------------------------

def _transform_chain(x3d_text, def_name):
    """The Transforms from the scene root down to the one called ``def_name``, as (translation, rotation, scale,
    center, scaleOrientation) each."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(x3d_text.encode("utf-8"))
    parents = {child: parent for parent in root.iter() for child in parent}
    node = next((e for e in root.iter("Transform") if e.get("DEF") == def_name), None)
    chain = []
    while node is not None:
        if node.tag == "Transform":
            numbers = lambda name, default: tuple(float(v) for v in (node.get(name) or default).split())
            chain.append((numbers("translation", "0 0 0"), numbers("rotation", "0 0 1 0"), numbers("scale", "1 1 1"),
                          numbers("center", "0 0 0"), numbers("scaleOrientation", "0 0 1 0")))
        node = parents.get(node)
    return list(reversed(chain))


def _to_local(chain, point, direction=False):
    """A world point (or direction) in the coordinates of the innermost Transform of ``chain``."""
    for translation, rotation, scale, center, scale_orientation in chain:
        if not direction:
            point = bs._v_sub(bs._v_sub(point, translation), center)
        point = bs._Rot.axis_angle(*rotation).inverse().rotate(point)
        so = bs._Rot.axis_angle(*scale_orientation)
        point = so.inverse().rotate(point)
        point = tuple(c / k for c, k in zip(point, scale))
        point = so.rotate(point)
        if not direction:
            point = bs._v_add(point, center)
    return point


def _pointer_ray(view, page_x, page_y, centre=PIXEL_CENTRE):
    x = page_x + centre
    y = view["height"] - page_y + centre
    tf = math.tan(view["fieldOfView"] / 2)
    aspect = view["width"] / view["height"]
    direction = ((2 * x / view["width"] - 1) * tf * aspect, (2 * y / view["height"] - 1) * tf, -1.0)
    return tuple(view["position"]), bs._v_unit(direction)


def _drag_actions(graph, x3d_text, trace, centre=PIXEL_CENTRE):
    """(time, sensor, action, args) for each recorded drag of a CylinderSensor or SphereSensor: press with the
    TouchSensor's hit point and the ray, drag with the ray, release."""
    view, actions, queue = trace["view"], [], list(trace.get("drags", []))
    current = None
    for when, kind, page_x, page_y in trace["pointer"]:
        if kind == "mousedown":
            current = queue.pop(0) if queue else None
            if current is not None and graph.nodes[current["sensor"]].node_type not in ("CylinderSensor", "SphereSensor"):
                current = None
            if current is None:
                continue
            chain = _transform_chain(x3d_text, graph.nodes[current["sensor"]].parent)
            current["chain"] = chain
            hits = [e for e in trace["events"] if e[1] == current["touch"] and e[2] == "hitPoint_changed"]
            before = [e for e in hits if e[0] <= when + 1e-6]
            hit = (before[-1] if before else hits[0])[3]
            point = tuple(float(c) for c in str(hit).split())
            eye = (_to_local(chain, tuple(view["position"])), _to_local(chain, (0.0, 0.0, 1.0), direction=True))
            origin, direction = _pointer_ray(view, page_x, page_y, centre)
            ray = (_to_local(chain, origin), _to_local(chain, direction, direction=True))
            actions.append((when, current["sensor"], "press", (point, ray, eye)))
        elif current is not None and kind == "mousemove":
            origin, direction = _pointer_ray(view, page_x, page_y, centre)
            ray = (_to_local(current["chain"], origin), _to_local(current["chain"], direction, direction=True))
            actions.append((when, current["sensor"], "drag", (ray,)))
        elif current is not None and kind == "mouseup":
            actions.append((when, current["sensor"], "release", ()))
            current = None
    return actions


def sources_of(graph):
    seen = []
    for route in graph.routes:
        pair = [route.from_id, route.from_field]
        if pair not in seen:
            seen.append(pair)
    return seen


def _numbers(value):
    if isinstance(value, bool):
        return [1.0 if value else 0.0]
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, str):
        if value in ("true", "false"):
            return [1.0 if value == "true" else 0.0]
        return [float(token) for token in value.replace(",", " ").split()]
    return [float(x) for x in value]


def _gap(a, b, x3d_type):
    a, b = _numbers(a), _numbers(b)
    if x3d_type == "SFRotation" and len(a) == 4 and len(b) == 4:
        return bs._rotation_distance(tuple(a), tuple(b))
    if len(a) != len(b):
        return float("inf")
    return max((abs(x - y) for x, y in zip(a, b)), default=0.0)


def judge(x3d_path, trace, centre=PIXEL_CENTRE):
    x3d_text = pathlib.Path(x3d_path).read_text(encoding="utf-8")
    graph = bg.Behaviour.from_x3d(x3d_text)
    sim = bs.Simulation(graph, log_size=10 ** 7)
    pointing = {node.id for node in graph.nodes.values() if node.node_type in bs.POINTING}
    # drag sensors with a recorded pointer are run by the simulator from the pointer's ray and judged, not replayed
    actions = _drag_actions(graph, x3d_text, trace, centre) if trace.get("pointer") else []
    driven = {sensor for _when, sensor, _action, _args in actions}
    by_action = {}
    for action in actions:
        by_action.setdefault(action[0], []).append(action)
    events = sorted(trace["events"], key=lambda e: e[0])
    times = sorted(set(trace["frames"]) | {e[0] for e in events} | set(by_action))
    if not times:
        return {"file": trace["file"], "verdict": "no events recorded", "streams": []}
    # X_ITE had been running for a few seconds before recording began; the simulator is started earlier still, so
    # followers have settled into the same motion by the first recorded event.
    t = min(trace["began"], times[0]) - 12.0
    sim.start(t)
    aligned = set()
    for when, node_id, field_name, value in events:      # X_ITE's cycle start is a frame or so off the exact multiple
        node = graph.nodes.get(node_id)
        if node is not None and node.node_type == "TimeSensor" and field_name == "fraction_changed" \
                and node_id not in aligned and sim.machines[node_id].f["loop"] and 0 < float(value) < 1:
            aligned.add(node_id)
            interval = sim.machines[node_id].f["cycleInterval"]
            start = when - float(value) * interval
            sim.machines[node_id].cycle = start - interval * (1 + int((start - t) / interval))
    while t + 1 / 60 < times[0]:
        t += 1 / 60
        sim.step(t)
    sim.log.clear()
    by_time = {}
    for event in events:
        by_time.setdefault(event[0], []).append(event)
    for when in times:
        for _when, sensor, action, args in by_action.get(when, ()):
            sim.now = when
            if action == "press":
                point, ray, eye = args
                sim.press(sensor, when, point, ray=ray, eye=eye)
            elif action == "drag":
                sim.drag(sensor, None, when, ray=args[0])
            else:
                sim.release(sensor, when)
        for _when, node_id, field_name, value in by_time.get(when, ()):
            if node_id in pointing and node_id not in driven:
                x3d_type = bg.resolve_field(graph.nodes[node_id].node_type, field_name, "out")[1]
                sim.now = when
                machine = sim.machines[node_id]
                if field_name == "isOver":
                    machine.over = str(value) == "true" or value is True
                sim.post(node_id, field_name, bs.parse_value(str(value).lower() if isinstance(value, bool) else str(value),
                                                             x3d_type), when)
        sim.step(when)
    theirs, ours = {}, {}
    for when, node_id, field_name, value in events:
        if node_id not in pointing or node_id in driven:
            theirs.setdefault((node_id, field_name), []).append((when, value))
    for when, node_id, field_name, value in sim.log:
        ours.setdefault((node_id, field_name), []).append((when, value))
    streams, agree = [], True
    for node_id, field_name in [tuple(pair) for pair in sources_of(graph) if pair[0] not in pointing or pair[0] in driven]:
        node = graph.nodes[node_id]
        canonical, x3d_type = bg.resolve_field(node.node_type, field_name, "out")
        a, b = theirs.get((node_id, field_name), []), ours.get((node_id, canonical), [])
        follower = node.node_type.endswith(("Damper", "Chaser", "Damper2D", "Chaser2D")) or _fed_by_follower(graph, node_id)
        time_like = x3d_type == "SFTime"
        tolerance = FOLLOWER if follower else EXACT
        if node_id in driven:
            # a sensor the simulator ran from the recorded pointer: X_ITE stamps a press with a fresh clock and a
            # motion with its last frame's, so the two are matched event for event, in order, not by time
            pairs = list(zip(sorted(a, key=lambda e: e[0]), b))
            worst = max((_gap(theirs_value, mine_value, x3d_type) for (_t, theirs_value), (_m, mine_value) in pairs),
                        default=0.0)
            ok = len(a) == len(b) and len(a) > 0 and worst <= EXACT
            agree = agree and ok
            streams.append({"source": f"{node_id}.{field_name}", "node": node.node_type, "type": x3d_type,
                            "x_ite_events": len(a), "simulator_events": len(b), "compared": len(pairs),
                            "x_ite_only": max(0, len(a) - len(b)), "simulator_only": max(0, len(b) - len(a)),
                            "worst_gap": round(worst, 6), "tolerance": EXACT, "agree": ok, "matched": "in order"})
            continue
        index, worst, compared, unmatched = {round(when, 6): value for when, value in b}, 0.0, 0, 0
        a = list({round(when, 6): (when, value) for when, value in a}.values())   # two events in one frame: the last stands
        discrete = x3d_type in ("SFBool", "SFInt32", "SFTime") or \
            node.node_type.endswith(("Sequencer", "Trigger", "Toggle", "Filter"))
        held = None
        ordered = sorted(index)
        cursor = 0
        for when, value in sorted(a):
            key = round(when, 6)
            while cursor < len(ordered) and ordered[cursor] <= key:
                held = index[ordered[cursor]]
                cursor += 1
            mine = index.get(key)
            if mine is None and not discrete:
                mine = held                # a continuous value that was not sent again still stands
                if mine is None:
                    continue               # nothing sent yet: X_ITE repeats a value at rest, the simulator stays quiet
            if mine is None:
                unmatched += 1
                continue
            compared += 1
            gap = 0.0 if time_like and abs(float(value) - float(mine)) < 0.05 else _gap(value, mine, x3d_type)
            worst = max(worst, gap)
        extra = len({round(when, 6) for when, _ in b} - {round(when, 6) for when, _ in a})
        ok = compared > 0 and worst <= tolerance and unmatched == 0 if a else not b
        if discrete and node.node_type != "TimeSensor":
            ok = ok and extra == 0            # discrete streams must have the same events, not only the same values
        agree = agree and ok
        streams.append({"source": f"{node_id}.{field_name}", "node": node.node_type, "type": x3d_type,
                        "x_ite_events": len(a), "simulator_events": len(b), "compared": compared,
                        "x_ite_only": unmatched, "simulator_only": extra, "worst_gap": round(worst, 6),
                        "tolerance": tolerance, "agree": ok})
    return {"file": trace["file"], "browser": trace["browser"], "clicks": trace["clicks"],
            "frames": len(trace["frames"]), "not_simulated": sim.not_simulated,
            "streams": streams, "agree": agree}


def _fed_by_follower(graph, node_id, seen=None):
    seen = seen or set()
    for route in graph.routes:
        if route.to_id == node_id and route.from_id not in seen:
            seen.add(route.from_id)
            source = graph.nodes[route.from_id]
            if source.node_type.endswith(("Damper", "Chaser", "Damper2D", "Chaser2D")) or \
                    _fed_by_follower(graph, route.from_id, seen):
                return True
    return False


if __name__ == "__main__":
    if sys.argv[1] == "--sources":
        graph = bg.Behaviour.from_x3d(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
        print(json.dumps(sources_of(graph)))
    else:
        result = judge(sys.argv[1], json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")))
        print(json.dumps(result, indent=1))
        sys.exit(0 if result.get("agree") else 1)
