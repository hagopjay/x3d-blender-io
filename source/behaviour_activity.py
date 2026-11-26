# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Live X3D event activity while the behaviour graph plays: what crossed which ROUTE, how often, and how it looks.

Two halves, kept apart.

Half 1 is plain Python (this file imports no ``bpy`` at its top, so tests run anywhere). ``Activity`` counts what the
simulation really delivered: it reads the simulation's own log (every event a node sent) and, for each event, the
ROUTEs the simulation then carried it over. It never runs, changes or reorders the simulation. No event, no packet,
no count. ``report()`` and ``to_json()`` give the numbers as plain data, so they can leave Blender.

    activity = Activity.from_simulation(sim)         # or Player(scene, activity=True).activity
    activity.feed_log(sim.log, sim.now)               # once after each simulation call
    activity.report()                                 # {"events": ..., "routes": [...], "ring": [...], ...}

What the words mean
  event       one entry of ``Simulation.log``: a node sent a value from an output field (a ROUTE-less output counts).
  delivery    one event carried over one ROUTE, as the simulation delivered it (a ROUTE carries one event per call of
              the simulation and only a value that fits the destination field). ROUTE totals count deliveries.
  cascade     the events sharing one timestamp.

Half 2 (further down) draws it over Blender's node editor and needs a window. Its geometry (the link curve, mapping to
the screen, packet positions, panel rectangles) is in plain functions that take numbers.
"""

import json
import math
from collections import deque
from itertools import islice

SCHEMA = "x3d.activity/1"
TRAVEL = 0.6             # seconds a packet takes along a link
WINDOW = 1.0             # seconds in "per second"
COALESCE = 0.25          # a stream: the same ROUTE within this many seconds updates one stream line
RING = 200               # event lines kept
PER_ROUTE = 3            # packets drawn at most per ROUTE
MAX_PACKETS = 400        # and in all
TRACE_CAP = 200_000      # recorded deliveries and calls kept at most (then ``trace_truncated``)
RECENT = 4096            # times kept per ROUTE (exact "per second" up to this many a second)


class CountingLog(deque):
    """The simulation's log with a count of everything ever appended, so what is new since the last look is known even
    when the log (bounded) has dropped old lines. Same order, same lines."""

    def __init__(self, iterable=(), maxlen=None):
        super().__init__(iterable, maxlen)
        self.appended = len(self)

    def append(self, item):
        self.appended += 1
        deque.append(self, item)


def value_text(value, limit=32):
    """A value as short text for a stream line: 0.5, TRUE, (1, 0, 0), "abc"."""
    def one(item, depth=0):
        if isinstance(item, bool):
            return "TRUE" if item else "FALSE"
        if isinstance(item, float):
            return f"{item:.4g}"
        if isinstance(item, (tuple, list)):
            if depth > 1:
                return "(...)"
            shown = ", ".join(one(i, depth + 1) for i in item[:6])
            return f"({shown}{', ...' if len(item) > 6 else ''})"
        if isinstance(item, str):
            return '"' + item + '"'
        return str(item)
    text = one(value)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def plain(value):
    """``value`` as plain JSON data: numbers, strings, booleans, None and lists (tuples become lists)."""
    if isinstance(value, (bool, int, str)) or value is None:
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    return str(value)


def _tuples(value):
    """The inverse of ``plain`` for a recorded argument: lists become tuples (what the simulation is given)."""
    if isinstance(value, list):
        return tuple(_tuples(v) for v in value)
    if isinstance(value, dict):
        return {k: _tuples(v) for k, v in value.items()}
    return value


POINTER_CALLS = ("click", "press", "drag", "release", "hover")      # calls a person makes on an object
NOTE_NO_OBJECT = "the sensor sits at the scene root or in an unnamed group: it has no object name"


def sensors_on(graph, object_name, parent_of=None):
    """The pointing sensors that sense the scene object ``object_name``, as ``Player.sensors_for`` finds them: those of
    the nearest object above it (``parent_of(name)`` gives an object's parent, None at the top) that has any, else the
    sensors at the scene root. Without ``parent_of`` only the object itself and the root are looked at."""
    pointing = [n for n in graph.nodes.values() if n.role == "behaviour" and n.node_type in POINTING_TYPES]
    name = object_name
    while name is not None:
        found = [n.id for n in pointing if n.parent == name]
        if found:
            return found
        name = parent_of(name) if parent_of is not None else None
    return [n.id for n in pointing if n.parent is None]


POINTING_TYPES = ("TouchSensor", "PlaneSensor", "CylinderSensor", "SphereSensor")


def perform(sim, entry, parent_of=None):
    """Do one recorded call (``{"time", "call", "node", "args"}``) on a Simulation; returns its changes. The calls are
    the Simulation's own: start, step, click, press, drag, release, hover, key, viewer, post. A pointer call that names
    only an ``"object"`` (no ``"node"``) is done on every sensor of that object (``sensors_on``)."""
    if entry.get("node") is None and entry.get("object") is not None and entry["call"] in POINTER_CALLS:
        changes = []
        for node in sensors_on(sim.graph, entry["object"], parent_of):
            changes += perform(sim, {**entry, "node": node}, parent_of)
        return changes
    call, node, now = entry["call"], entry.get("node"), entry["time"]
    args = _tuples(entry.get("args") or {})
    if call == "start":
        return sim.start(now)
    if call == "step":
        return sim.step(now)
    if call == "click":
        return sim.click(node, now, held=args.get("held", 0.0))
    if call == "press":
        return sim.press(node, now, point=args.get("point", (0.0, 0.0, 0.0)), ray=args.get("ray"), eye=args.get("eye"),
                         follow=args.get("follow", True), screen=args.get("screen"))
    if call == "drag":
        return sim.drag(node, args.get("point"), now, ray=args.get("ray"))
    if call == "release":
        return sim.release(node, now)
    if call == "hover":
        return sim.hover(node, args["over"], now)
    if call == "key":
        return sim.key(args["kind"], args["event"], now)
    if call == "viewer":
        return sim.viewer(node, args["position"], args["orientation"], now,
                          center_of_rotation=args.get("center_of_rotation", (0.0, 0.0, 0.0)),
                          test_position=args.get("test_position"))
    if call == "post":
        return sim.post(node, args["field"], args["value"], now)
    raise ValueError(f"unknown call {call!r}")


def replay(sim, stimulus, activity=None, parent_of=None):
    """Run a recorded stimulus on a (fresh) Simulation, feeding ``activity`` after every call when given. The same
    graph and the same stimulus give the same events: that is how a recording is checked."""
    for entry in stimulus:
        perform(sim, entry, parent_of)
        if activity is not None:
            activity.feed_log(sim.log, sim.now)


class _Route:
    __slots__ = ("key", "type", "total", "recent", "last_time", "last_value", "live")

    def __init__(self, key, x3d_type):
        self.key, self.type, self.total = key, x3d_type, 0
        self.recent = deque(maxlen=RECENT)
        self.last_time, self.last_value, self.live = None, None, None


class _Entry:
    """One line of the event stream: a ROUTE's event, or a run of them (a stream) with how many and how fast."""
    __slots__ = ("first", "time", "key", "type", "value", "count")

    def __init__(self, when, key, x3d_type, value):
        self.first = self.time = when
        self.key, self.type, self.value, self.count = key, x3d_type, value, 1

    @property
    def rate(self):
        return (self.count - 1) / (self.time - self.first) if self.count > 1 and self.time > self.first else 0.0

    def as_tuple(self):
        """(time, from_node, from_field, to_node, to_field, type, value_text)"""
        return (self.time, *self.key, self.type, value_text(self.value))


class Activity:
    """What a running simulation delivered. Memory is bounded: one record per ROUTE and node, the last second of times
    per ROUTE, 200 stream lines."""

    def __init__(self, routes=None, types=None, *, travel=TRAVEL, record=False, world=None):
        """``routes``: {(from node, from field): [(to node, to field, fits)]}; ``fits`` is None or a function of the
        value that says whether the ROUTE carries it. ``types``: {(from, field, to, field): X3D type name}."""
        self.travel = travel
        self.record, self.world = bool(record), world
        self.graph = None                    # set by from_simulation: lets a pointer call name its object
        self._out = {}
        self._routes = {}
        types = types or {}
        for source, targets in (routes or {}).items():
            for to_id, to_field, fits in targets:
                key = (*source, to_id, to_field)
                self._out.setdefault(source, []).append((to_id, to_field, fits, key))
                self._routes[key] = _Route(key, types.get(key, ""))
        self.reset()

    @classmethod
    def from_simulation(cls, sim, **options):
        """For a Simulation: its ROUTE table (read only) and the type of each destination field. The simulation's log
        is replaced by a CountingLog with the same lines; nothing else of it is touched."""
        routes, types = {}, {}
        for source, targets in sim._routes.items():
            for to_id, to_field, fits, key in targets:
                routes.setdefault(source, []).append((to_id, to_field, fits))
                try:
                    types[key] = sim._field_type(to_id, to_field) or ""
                except Exception:       # noqa: BLE001 - a type that cannot be told is drawn plain
                    types[key] = ""
        activity = cls(routes, types, **options)
        if not isinstance(sim.log, CountingLog):
            sim.log = CountingLog(sim.log, maxlen=sim.log.maxlen)
        activity.graph = sim.graph
        activity._seen = sim.log.appended
        # The simulation lets each ROUTE carry one event per ``post`` (it forgets which ROUTEs fired at the start of every
        # post, and a press or a drag makes several). So what a post delivered is fed as its own batch: the batches are
        # the simulation's own moments, and a delivery here is a delivery there.
        original = sim.post

        def post(*args, **kwargs):
            activity.feed_log(sim.log, sim.now)
            try:
                return original(*args, **kwargs)
            finally:
                activity.feed_log(sim.log, sim.now)
        sim.post = post
        return activity

    def reset(self):
        self.events = self.deliveries = self.unseen = 0
        self.now = 0.0
        self.widest = 0
        self.nodes = {}                      # node id -> [events in, events out, last output field]
        self.ring = deque(maxlen=RING)
        for route in self._routes.values():
            route.total, route.last_time, route.last_value, route.live = 0, None, None, None
            route.recent.clear()
        self._window, self._window_sum = deque(), 0
        self._cascade_time, self._cascade = None, 0
        self._hot = {}                       # ROUTEs that carried something within the last second, oldest first
        self._seen = 0
        # the full recording (opt in): every delivery in order and every call the world received, as plain data
        self.trace = [] if self.record else None
        self.stimulus = [] if self.record else None
        self.trace_truncated = False

    # -- feeding ----------------------------------------------------------------------------------------------

    def feed_log(self, log, now=None):
        """Take what is new in a CountingLog since the last call. Returns how many events that was."""
        new = log.appended - self._seen
        if new <= 0:
            return 0
        self._seen = log.appended
        lost = 0
        if new > len(log):                   # the log dropped some before they were read: counted, not attributed
            lost, new = new - len(log), len(log)
            self.unseen += lost
            self.events += lost
            self._add_window(now if now is not None else self.now, lost)
        fresh = list(islice(reversed(log), new))
        fresh.reverse()
        self.feed(fresh, now)
        return new + lost

    def feed(self, events, now=None):
        """``events``: [(time, node, field, value)] the simulation sent in one call, in order."""
        fired = set()                        # a ROUTE carries one event per call (X3D 4.4.8.3), as the simulation does
        out, routes, nodes, ring = self._out, self._routes, self.nodes, self.ring
        last = self.now
        for when, node_id, field_name, value in events:
            last = when
            self.events += 1
            record = nodes.get(node_id)
            if record is None:
                record = nodes[node_id] = [0, 0, None]
            record[1] += 1
            record[2] = field_name
            self._add_window(when, 1)
            if when == self._cascade_time:
                self._cascade += 1
            else:
                self._cascade_time, self._cascade = when, 1
            if self._cascade > self.widest:
                self.widest = self._cascade
            for to_id, to_field, fits, key in out.get((node_id, field_name), ()):
                if key in fired:
                    continue
                if fits is not None and not fits(value):
                    continue
                fired.add(key)
                self.deliveries += 1
                if self.trace is not None:
                    if len(self.trace) < TRACE_CAP:
                        self.trace.append([when, *key, self._routes[key].type, plain(value)])
                    else:
                        self.trace_truncated = True
                route = routes[key]
                route.total += 1
                route.recent.append(when)
                route.last_time, route.last_value = when, value
                if key in self._hot:
                    del self._hot[key]
                self._hot[key] = None
                target = nodes.get(to_id)
                if target is None:
                    target = nodes[to_id] = [0, 0, None]
                target[0] += 1
                entry = route.live
                if entry is not None and 0 <= when - entry.time <= COALESCE:
                    entry.time, entry.value = when, value
                    entry.count += 1
                else:
                    entry = route.live = _Entry(when, key, route.type, value)
                    ring.append(entry)
        self.now = max(self.now, last if now is None else now)

    def note_call(self, call, node, now, **args):
        """Record a call the world received (start, step, click, press, drag, release, hover, key, viewer, post) so
        the recording can be replayed. Does nothing unless ``record`` is on. ``args`` are the call's own arguments."""
        if self.stimulus is None:
            return
        if len(self.stimulus) < TRACE_CAP:
            entry = {"time": now, "call": call, "node": node, "args": plain(args)}
            if call in POINTER_CALLS and node is not None and self.graph is not None and node in self.graph.nodes:
                entry["object"] = self.graph.nodes[node].parent        # what a person pointed at; None: no object name
                if entry["object"] is None:
                    entry["note"] = NOTE_NO_OBJECT
            self.stimulus.append(entry)
        else:
            self.trace_truncated = True

    def drive(self, sim, call, node, now, **args):
        """For pure Python: note the call, do it on ``sim`` and take what it delivered. Returns the sim's changes."""
        entry = {"time": now, "call": call, "node": node, "args": plain(args)}
        self.note_call(call, node, now, **args)
        changes = perform(sim, entry)
        self.feed_log(sim.log, sim.now)
        return changes

    def _add_window(self, when, count):
        window = self._window
        if window and window[-1][0] == when:
            window[-1][1] += count
        else:
            window.append([when, count])
        self._window_sum += count

    def _trim(self, now):
        window, cutoff = self._window, now - WINDOW
        while window and window[0][0] <= cutoff:
            self._window_sum -= window.popleft()[1]

    # -- numbers ----------------------------------------------------------------------------------------------

    def events_per_second(self, now=None):
        """Events sent in the last second of simulation time."""
        now = self.now if now is None else now
        self._trim(now)
        return self._window_sum / WINDOW

    def _active(self, now):
        """The ROUTE records that carried an event within the last second, oldest first."""
        cutoff = now - WINDOW
        for key in [k for k in self._hot if self._routes[k].last_time <= cutoff]:
            del self._hot[key]
        return [self._routes[key] for key in self._hot]

    def routes_active(self, now=None):
        return len(self._active(self.now if now is None else now))

    def route_count(self):
        return len(self._routes)

    def route_rate(self, key, now=None):
        """Events this ROUTE carried in the last second."""
        now = self.now if now is None else now
        recent, cutoff = self._routes[key].recent, now - WINDOW
        while recent and recent[0] <= cutoff:
            recent.popleft()
        return len(recent) / WINDOW

    def route_total(self, key):
        return self._routes[key].total

    def route_keys(self):
        return list(self._routes)

    def route_type(self, key):
        return self._routes[key].type

    def glow(self, key, now=None):
        """0..1, how recently the ROUTE carried an event: 1 at the event, 0 after a second (squared, so it fades fast
        and lingers a little)."""
        route = self._routes[key]
        now = self.now if now is None else now
        if route.last_time is None:
            return 0.0
        return max(0.0, 1.0 - max(0.0, now - route.last_time) / WINDOW) ** 2

    def active_keys(self, now=None):
        return [route.key for route in self._active(self.now if now is None else now)]

    def packets(self, now=None):
        """[(route key, age 0..1, count)] for events younger than the travel time: age 0 is the output socket, 1 the
        input socket. At most PER_ROUTE per ROUTE (events of one ROUTE are grouped by age into that many bins, the
        count says how many each stands for: a 60 per second stream is a steady flow) and MAX_PACKETS in all (the
        youngest kept). Nothing without a delivered event."""
        now = self.now if now is None else now
        travel, found = self.travel, []
        width = travel / PER_ROUTE
        for key in self._hot:
            route = self._routes[key]
            if now - route.last_time > travel:
                continue
            bins = {}
            for when in reversed(route.recent):
                age = max(0.0, now - when)
                if age > travel:
                    break
                index = min(int(age / width), PER_ROUTE - 1)
                if index in bins:
                    bins[index][1] += 1
                else:
                    bins[index] = [age / travel, 1]
            for index in sorted(bins):
                found.append((key, bins[index][0], bins[index][1]))
        found.sort(key=lambda packet: packet[1])
        return found[:MAX_PACKETS]

    def busiest(self, count=10, now=None):
        """[(key, total, per second)] of the ROUTEs that carried most."""
        now = self.now if now is None else now
        top = sorted((r for r in self._routes.values() if r.total), key=lambda r: (-r.total, r.key))[:count]
        return [(r.key, r.total, self.route_rate(r.key, now)) for r in top]

    # -- leaving Blender ----------------------------------------------------------------------------------------

    def report(self, now=None):
        """Everything as plain data (numbers, text, lists, dicts): totals, per-ROUTE counts and rates, per-node
        counts, and the event stream (newest last)."""
        now = self.now if now is None else now
        routes = []
        for route in sorted(self._routes.values(), key=lambda r: (-r.total, r.key)):
            routes.append({"from": route.key[0], "from_field": route.key[1], "to": route.key[2],
                           "to_field": route.key[3], "type": route.type, "events": route.total,
                           "per_second": self.route_rate(route.key, now), "last_time": route.last_time,
                           "last_value": None if route.last_time is None else value_text(route.last_value)})
        return {
            "schema": SCHEMA, "time": now, "events": self.events, "deliveries": self.deliveries,
            "unattributed": self.unseen, "events_per_second": self.events_per_second(now),
            "routes_total": len(self._routes), "routes_active": self.routes_active(now),
            "widest_cascade": self.widest, "world": self.world, "routes": routes,
            "nodes": [{"node": name, "in": record[0], "out": record[1], "last_output": record[2]}
                      for name, record in sorted(self.nodes.items())],
            "ring": [{"time": e.time, "from": e.key[0], "from_field": e.key[1], "to": e.key[2], "to_field": e.key[3],
                      "type": e.type, "value": value_text(e.value), "count": e.count, "per_second": e.rate}
                     for e in self.ring],
            "trace": self.trace, "trace_truncated": self.trace_truncated, "stimulus": self.stimulus,
        }

    def to_json(self, now=None, indent=None):
        return json.dumps(self.report(now), sort_keys=True, indent=indent)


def report_text(report):
    """A report (``Activity.report()``) as a plain-text table, for the clipboard."""
    lines = [f"X3D activity  t={report['time']:.3f}s", "",
             f"events {report['events']}   deliveries {report['deliveries']}   "
             f"{report['events_per_second']:.0f}/s   ROUTEs active {report['routes_active']}/{report['routes_total']}   "
             f"widest cascade {report['widest_cascade']}", ""]
    rows = [r for r in report["routes"] if r["events"]]
    names = [f"{r['from']}.{r['from_field']} -> {r['to']}.{r['to_field']}" for r in rows]
    width = max([len("ROUTE"), *map(len, names)])
    lines.append(f"{'ROUTE':<{width}}  {'events':>8}  {'per s':>7}  last value")
    for name, row in zip(names, rows):
        lines.append(f"{name:<{width}}  {row['events']:>8}  {row['per_second']:>7.0f}  {row['last_value']}")
    if not rows:
        lines.append("(no ROUTE carried an event)")
    silent = len(report["routes"]) - len(rows)
    if silent:
        lines.append(f"{silent} ROUTE(s) carried nothing")
    lines += ["", f"{'node':<{max([4, *(len(n['node']) for n in report['nodes'])])}}  {'in':>8}  {'out':>8}"]
    for node in report["nodes"]:
        lines.append(f"{node['node']:<{max([4, *(len(n['node']) for n in report['nodes'])])}}  "
                     f"{node['in']:>8}  {node['out']:>8}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------------------------------------
# Geometry in plain numbers (no Blender): the link curve, the view, packets, panels
# ---------------------------------------------------------------------------------------------------------------

def bezier(p0, p1, p2, p3, t):
    u = 1.0 - t
    a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return (a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1])


def link_curve(start, end, curving=5.0, segments=24):
    """The points of a node link as Blender's editor draws it: a cubic from the output socket to the input socket with
    horizontal handles of ``curving * 0.1 * |dx|`` (the theme's Noodle Curving, 5 by default). The first point is
    ``start`` and the last ``end`` exactly."""
    reach = curving * 0.10 * abs(start[0] - end[0])
    p1, p2 = (start[0] + reach, start[1]), (end[0] - reach, end[1])
    points = [start] + [bezier(start, p1, p2, end, i / segments) for i in range(1, segments)] + [end]
    return points


def arc_lengths(points):
    total, out = 0.0, [0.0]
    for a, b in zip(points, points[1:]):
        total += math.hypot(b[0] - a[0], b[1] - a[1])
        out.append(total)
    return out


def point_along(points, lengths, fraction):
    """The point ``fraction`` (0..1) of the way along the polyline by distance, so a packet moves at a steady speed."""
    fraction = min(1.0, max(0.0, fraction))
    target = lengths[-1] * fraction
    low, high = 0, len(points) - 1
    while high - low > 1:
        middle = (low + high) // 2
        if lengths[middle] <= target:
            low = middle
        else:
            high = middle
    span = lengths[high] - lengths[low]
    t = 0.0 if span <= 0 else (target - lengths[low]) / span
    a, b = points[low], points[high]
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


class LinearView:
    """A stand-in for a region's View2D: ``view_to_region`` is scale and offset. Tests use it; Blender's is the real one."""

    def __init__(self, scale=1.0, offset=(0.0, 0.0)):
        self.scale, self.offset = scale, offset

    def view_to_region(self, x, y, clip=False):
        return (x * self.scale + self.offset[0], y * self.scale + self.offset[1])


def to_region(view2d, points):
    """View-space points to region pixels with a View2D-like object."""
    return [tuple(view2d.view_to_region(x, y, clip=False)) for x, y in points]


# The layout of a node in the editor, measured on a screenshot of Blender 5.2.2 (a TimeSensor node: 14 outputs, 8 inputs):
# the header is 23.3 view units, every socket row 21.6 (a row of 20 and 1.6 between), outputs hang from the header, the
# node's own properties block comes next (its height is whatever ``draw_buttons`` drew, so it is never computed here),
# and the inputs sit at the foot, the last one a row above a 2.9 margin. So outputs are measured from the top and inputs
# from the bottom, and the properties block does not matter: only the node's own height does (``node.dimensions``).
NODE_HEADER = 23.3
NODE_ROW = 21.6
NODE_FOOT = 2.9


def socket_position(left, top, width, height, index, count, is_output, unit=1.0, collapsed=False):
    """Where a node's socket centre is, in view space. ``left``, ``top``, ``width``, ``height``: the node's box (``top``
    is its upper edge, y up). ``index`` counts only the sockets that are drawn (not hidden, not unavailable) of that
    side, ``count`` is how many there are. ``unit`` is the UI scale the layout constants are multiplied by. A collapsed
    node draws every socket on its header's middle."""
    x = left + width if is_output else left
    if collapsed:
        return (x, top - NODE_HEADER * unit / 2)
    if is_output:
        return (x, top - (NODE_HEADER + NODE_ROW * (index + 0.5)) * unit)
    return (x, top - height + (NODE_FOOT + NODE_ROW * (count - index - 0.5)) * unit)


def visible_rect(region_width, region_height, left=0.0, right=0.0, top=0.0, bottom=0.0):
    """(x, y, w, h) of what of a region is not under its own sidebar, tool shelf, header or footer (sizes in pixels,
    y up from the region's bottom)."""
    return (left, bottom, max(0.0, region_width - left - right), max(0.0, region_height - top - bottom))


def hud_rect(visible, width, height, margin=12.0, max_fraction=0.6):
    """(x, y, w, h) of the activity block in the bottom-left of ``visible`` (see ``visible_rect``), inset by ``margin``,
    at most ``max_fraction`` of its width and kept inside it."""
    x, y, vw, vh = visible
    w = min(width, vw * max_fraction, max(0.0, vw - 2 * margin))
    h = min(height, max(0.0, vh - 2 * margin))
    return (x + margin, y + margin, w, h)


def rects_overlap(a, b, gap=0.0):
    return a[0] < b[0] + b[2] + gap and b[0] < a[0] + a[2] + gap and a[1] < b[1] + b[3] + gap and b[1] < a[1] + a[3] + gap


def counter_labels(nodes, text_width, text_height, gap=3.0):
    """Which per-node labels to draw. ``nodes``: [(key, (x, y, w, h) of the node in pixels, text)]. Each label sits above
    its node's own top-right corner, right-aligned to the node; one that would touch another node or an already placed
    label is left out. Returns [(text, (x, y, w, h))] with the label's rectangle."""
    placed, out = [], []
    for key, box, text in nodes:
        width = text_width(text)
        label = (box[0] + box[2] - width, box[1] + box[3] + gap, width, text_height)
        if any(rects_overlap(label, other[1]) for other in nodes if other[0] != key) or \
                any(rects_overlap(label, r) for r in placed):
            continue
        placed.append(label)
        out.append((text, label))
    return out


def badge_spot(points, lengths, width, height, blockers, fractions=(0.5, 0.42, 0.58, 0.34, 0.66, 0.26, 0.74)):
    """Where along a link (polyline in pixels) a badge of ``width`` x ``height`` goes: the first of ``fractions`` whose
    rectangle touches none of ``blockers`` (node rectangles); the middle when none is free (None: every spot is blocked)."""
    for fraction in fractions:
        x, y = point_along(points, lengths, fraction)
        rect = (x - width / 2, y - height / 2, width, height)
        if not any(rects_overlap(rect, blocker) for blocker in blockers):
            return (x, y)
    return None


def badge_rect(cx, cy, text_width, text_height, pad=4.0):
    """(x, y, w, h) of a badge centred on (cx, cy)."""
    w, h = text_width + 2 * pad, text_height + 2 * pad
    return (cx - w / 2, cy - h / 2, w, h)


def trim_text(measure, text, limit):
    """``text`` cut with an ellipsis so ``measure(text)`` is at most ``limit``."""
    if measure(text) <= limit:
        return text
    while text and measure(text + "…") > limit:
        text = text[:-1]
    return text + "…" if text else ""


def rounded_rect(x, y, w, h, radius, segments=6):
    """The outline of a rounded rectangle, counter-clockwise from the lower-left corner's arc."""
    radius = max(0.0, min(radius, w / 2, h / 2))
    corners = ((x + w - radius, y + radius, -90), (x + w - radius, y + h - radius, 0),
               (x + radius, y + h - radius, 90), (x + radius, y + radius, 180))
    points = []
    for cx, cy, start in corners:
        for i in range(segments + 1):
            angle = math.radians(start + 90 * i / segments)
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return points


def packet_trail(points, lengths, age, tail=0.12, samples=8):
    """[(point, strength)] for one packet at ``age`` (0..1 along the link): the head (strength 1) and a tail of ``tail``
    (a fraction of the link) behind it that fades."""
    out = []
    for i in range(samples + 1):
        behind = age - tail * i / samples
        if behind < 0:
            break
        out.append((point_along(points, lengths, behind), (1.0 - i / (samples + 1)) ** 1.5))
    return out


# ---------------------------------------------------------------------------------------------------------------
# Half 2: drawing in the node editor (bpy, gpu, blf; needs a window)
#
# Two handlers. The first draws in the editor's own view space (POST_VIEW: the very matrices the nodes and links are
# drawn with, so a link's glow and a packet cannot drift from the link whatever the zoom, and the region's scroll
# margins and overlaps do not matter). It also works out where, in pixels, the text goes. The second (POST_PIXEL)
# draws that text, the badges and the HUD.
# ---------------------------------------------------------------------------------------------------------------

_state = {"handles": [], "player": None, "failed": None, "gpu": None, "index": None, "font": None,
          "last": None, "classes": None, "draws": 0, "debug": False, "frame": None, "diag": {}}


def last_activity():
    """The Activity of the most recent Play (kept after Stop, so the report can still be copied)."""
    return _state["last"]


def handler_active():
    return bool(_state["handles"])


def draw_count():
    """How many times the overlay really drew (all checks passed, something was put on the screen). For tests that
    have a window: a handler that is registered but never draws is not working."""
    return _state["draws"]


def failure():
    """Why the overlay disabled itself or could not start, else None."""
    return _state["failed"]


def diagnostics():
    """What the last frame measured (viewport, scale, a node's box), for a person reading a log from a machine with a
    window and no one to look at it."""
    return dict(_state["diag"])


def set_debug(on):
    """Draw each node's box and a cross at every socket position the overlay computes, to check them against the editor's
    own drawing."""
    _state["debug"] = bool(on)
    _redraw()


def start_overlay(player):
    """Draw ``player``'s Activity over the X3D behaviour node editor until ``stop_overlay``. False when the player has
    none or the API is missing (nothing is added then)."""
    stop_overlay()
    activity = getattr(player, "activity", None)
    if activity is None:
        return False
    _state["last"] = activity
    import bpy
    handles = []
    try:
        add = bpy.types.SpaceNodeEditor.draw_handler_add
        handles.append(add(_draw_view, (), "WINDOW", "POST_VIEW"))
        handles.append(add(_draw_pixel, (), "WINDOW", "POST_PIXEL"))
    except Exception as error:      # noqa: BLE001 - an API that differs: no overlay, Play still works
        _state["failed"] = f"{type(error).__name__}: {error}"
        _state["handles"] = handles
        stop_overlay()
        return False
    _state["handles"], _state["player"], _state["failed"], _state["index"] = handles, player, None, None
    _state["frame"] = None
    _redraw()
    return True


def stop_overlay():
    handles, _state["handles"], _state["player"], _state["frame"] = _state["handles"], [], None, None
    if not handles:
        return
    try:
        import bpy
        for handle in handles:
            try:
                bpy.types.SpaceNodeEditor.draw_handler_remove(handle, "WINDOW")
            except Exception:       # noqa: BLE001 - already gone (file load, unregister)
                pass
    except Exception:       # noqa: BLE001
        pass
    _redraw()


def _redraw():
    try:
        import bpy
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "NODE_EDITOR":
                    area.tag_redraw()
    except Exception:       # noqa: BLE001 - no window (background)
        pass


def _fail(error):
    """The handler never raises: say why once, remove itself."""
    import traceback
    _state["failed"] = f"{type(error).__name__}: {error}"
    print("[x3d activity] overlay disabled:", traceback.format_exc())
    stop_overlay()


def _shaders():
    if _state["gpu"] is None:
        import gpu
        _state["gpu"] = {
            "line": gpu.shader.from_builtin("POLYLINE_SMOOTH_COLOR"),
            "point": gpu.shader.from_builtin("POINT_FLAT_COLOR"),
            "flat": gpu.shader.from_builtin("FLAT_COLOR"),
        }
    return _state["gpu"]


def _link_index(tree):
    """(from def, from socket, to def, to socket) -> the tree's link: the key of a ROUTE in the simulation. Cached
    until the link count changes."""
    cached = _state["index"]
    if cached is not None and cached[0] is tree and cached[1] == len(tree.links):
        return cached[2]
    index = {}
    for link in tree.links:
        a, b = link.from_node, link.to_node
        index[((a.x3d_def or a.name), link.from_socket.name, (b.x3d_def or b.name), link.to_socket.name)] = link
    _state["index"] = (tree, len(tree.links), index)
    return index


def _colour(x3d_type):
    from . import behaviour_nodes
    return behaviour_nodes._COLOURS.get(x3d_type, (0.62, 0.62, 0.62, 1.0))[:3]


def _bright(colour, amount=0.4):
    return tuple(c + (1.0 - c) * amount for c in colour)


def _font():
    """A monospaced font id (digits that line up), else the default."""
    if _state["font"] is None:
        import blf
        import bpy
        found = 0
        try:
            from pathlib import Path
            path = Path(bpy.utils.system_resource("DATAFILES")) / "fonts" / "DejaVuSansMono.woff2"
            if path.is_file():
                loaded = blf.load(str(path))
                found = loaded if loaded >= 0 else 0
        except Exception:       # noqa: BLE001
            found = 0
        _state["font"] = found
    return _state["font"]


def _text_size(fid, px):
    import blf
    try:
        blf.size(fid, px)
    except TypeError:       # Blender before 4.0 takes (font, size, dpi)
        blf.size(fid, px, 72)


def _editor(player):
    """(space, region, tree, scene) when this is the X3D behaviour editor of the playing scene and the overlay is on."""
    import bpy
    from . import behaviour_nodes, behaviour_play
    if player is None or behaviour_play._running["player"] is not player:
        return None
    context = bpy.context
    space, region = context.space_data, context.region
    if space is None or getattr(space, "tree_type", "") != behaviour_nodes.TREE_IDNAME or region is None:
        return None
    scene = player.scene
    tree = scene.x3d_behaviour_tree
    if tree is None or space.edit_tree != tree or not getattr(scene, "x3d_activity_show", True):
        return None
    return space, region, tree, scene


def _sides(sockets):
    """The sockets a node draws (not hidden, not unavailable), in order."""
    return [s for s in sockets if getattr(s, "enabled", True) and not s.hide and not getattr(s, "is_unavailable", False)]


class _Layout:
    """Where nodes and sockets are, in view space, for one frame."""

    def __init__(self, tree, unit):
        self.unit, self.nodes = unit, {}
        for node in tree.nodes:
            left, top = node.location.x * unit, node.location.y * unit
            self.nodes[node.name] = (node, left, top, node.dimensions.x, node.dimensions.y,
                                     _sides(node.outputs), _sides(node.inputs))

    def box(self, node):
        _n, left, top, width, height, _o, _i = self.nodes[node.name]
        return left, top, width, height

    def socket(self, node, socket):
        """(x, y) of ``socket`` of ``node`` in view space, or None when it is not drawn."""
        _n, left, top, width, height, outs, ins = self.nodes[node.name]
        sockets = outs if socket.is_output else ins
        if socket not in sockets:
            return None
        return socket_position(left, top, width, height, sockets.index(socket), len(sockets), socket.is_output,
                               self.unit, bool(node.hide))


def _link_points(layout, link, curving):
    start, end = layout.socket(link.from_node, link.from_socket), layout.socket(link.to_node, link.to_socket)
    if start is None or end is None:
        return None
    return link_curve(start, end, curving)


def _draw_view(*_args):
    try:
        _draw_in_view()
    except Exception as error:      # noqa: BLE001
        _fail(error)


def _draw_in_view():
    import bpy
    import gpu
    from gpu_extras.batch import batch_for_shader
    from mathutils import Vector
    player = _state["player"]
    found = _editor(player)
    if found is None:
        return
    space, region, tree, scene = found
    context = bpy.context
    activity = player.activity
    now = player.sim.now if player.sim.now is not None else activity.now
    unit = context.preferences.system.ui_scale or 1.0
    try:
        curving = context.preferences.themes[0].node_editor.noodle_curving
    except Exception:       # noqa: BLE001
        curving = 5.0
    matrix = gpu.matrix.get_projection_matrix() @ gpu.matrix.get_model_view_matrix()
    _vx, _vy, vw, vh = gpu.state.viewport_get()

    def pixels(x, y):
        v = matrix @ Vector((x, y, 0.0, 1.0))
        return ((v.x / v.w * 0.5 + 0.5) * vw, (v.y / v.w * 0.5 + 0.5) * vh)

    origin = pixels(0.0, 0.0)
    per_unit = abs(pixels(1.0, 0.0)[0] - origin[0]) or 1.0          # pixels in one view unit
    shaders, index = _shaders(), _link_index(tree)
    layout = _Layout(tree, unit)
    _state["draws"] += 1
    size = (vw, vh)
    node_rects = {}
    for name, (node, left, top, width, height, _o, _i) in layout.nodes.items():
        x0, y0 = pixels(left, top - height)
        x1, y1 = pixels(left + width, top)
        node_rects[name] = (min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
    first = next(iter(layout.nodes.values()), None)
    _state["diag"] = {"viewport": [vw, vh], "region": [region.width, region.height], "px_per_unit": per_unit, "ui": unit,
                      "origin_px": list(origin), "curving": curving, "nodes": len(layout.nodes),
                      "first_node": None if first is None else {"name": first[0].name, "left": first[1], "top": first[2],
                                                                "width": first[3], "height": first[4],
                                                                "px_rect": list(node_rects[first[0].name])}}

    gpu.state.blend_set("ADDITIVE")
    halo_pos, halo_col, core_pos, core_col, paths = [], [], [], [], {}
    for key in activity.active_keys(now):
        link = index.get(key)
        if link is None:
            continue
        points = _link_points(layout, link, curving)
        if points is None:
            continue
        lengths = arc_lengths(points)
        paths[key] = (points, lengths)
        colour, strength = _colour(activity.route_type(key)), activity.glow(key, now)
        for a, b in zip(points, points[1:]):
            halo_pos += [(a[0], a[1], 0.0), (b[0], b[1], 0.0)]
            halo_col += [(*colour, 0.20 * strength)] * 2
            core_pos += [(a[0], a[1], 0.0), (b[0], b[1], 0.0)]
            core_col += [(*_bright(colour, 0.5), 0.95 * strength)] * 2
    line = shaders["line"]
    line.uniform_float("viewportSize", size)
    for pos, col, width in ((halo_pos, halo_col, 9.0 * unit), (core_pos, core_col, 2.0 * unit)):
        if pos:
            line.uniform_float("lineWidth", width)
            batch_for_shader(line, "LINES", {"pos": pos, "color": col}).draw(line)

    layers = {"halo": ([], []), "tail": ([], []), "head": ([], []), "core": ([], [])}
    for key, age, count in activity.packets(now):
        found_path = paths.get(key)
        if found_path is None:
            continue
        points, lengths = found_path
        if lengths[-1] <= 0:
            continue
        colour = _colour(activity.route_type(key))
        tail = min(0.5, 40.0 * unit / (per_unit * lengths[-1]))             # about 40 pixels
        for number, (position, strength) in enumerate(packet_trail(points, lengths, age, tail)):
            spot = (position[0], position[1], 0.0)
            if number == 0:
                layers["halo"][0].append(spot)
                layers["halo"][1].append((*colour, 0.35))
                layers["head"][0].append(spot)
                layers["head"][1].append((*_bright(colour, 0.55), 1.0))
                layers["core"][0].append(spot)
                layers["core"][1].append((1.0, 1.0, 1.0, 1.0))
            else:
                layers["tail"][0].append(spot)
                layers["tail"][1].append((*_bright(colour, 0.3), 0.8 * strength))
    point = shaders["point"]
    for name, px in (("halo", 20.0), ("tail", 4.0), ("head", 8.0), ("core", 4.0)):
        pos, col = layers[name]
        if pos:
            point.uniform_float("size", px * unit)
            batch_for_shader(point, "POINTS", {"pos": pos, "color": col}).draw(point)
    gpu.state.blend_set("ALPHA")
    if _state["debug"]:
        _draw_debug(layout, node_rects, per_unit, unit, size, batch_for_shader, shaders)

    # where the text goes, in pixels, for the second handler
    badges, spots = [], []
    if getattr(scene, "x3d_activity_badges", True):
        for key in activity.route_keys():
            total = activity.route_total(key)
            link = index.get(key)
            if not total or link is None or len(badges) >= 250:
                continue
            points = _link_points(layout, link, curving)
            if points is None:
                continue
            on_screen = [pixels(x, y) for x, y in points]
            lengths = arc_lengths(on_screen)
            spots.append((key, total, on_screen, lengths))
        badges = spots
    counters = []
    if len(layout.nodes) <= 600:
        for name, (node, _l, _t, _w, _h, _o, _i) in layout.nodes.items():
            record = activity.nodes.get(getattr(node, "x3d_def", "") or node.name)
            if record is not None:
                counters.append((name, node_rects[name], f"in {record[0]}  out {record[1]}"))
    _state["frame"] = {"size": size, "badges": badges, "counters": counters, "rects": list(node_rects.values()),
                       "colours": {key: _colour(activity.route_type(key)) for key, *_rest in badges}}
    gpu.state.blend_set("NONE")


def _draw_debug(layout, node_rects, per_unit, unit, size, batch_for_shader, shaders):
    """The box of every node (green) and a cross at every socket position (magenta: outputs, cyan: inputs)."""
    pos, col = [], []
    arm = 6.0 * unit / per_unit
    for node, left, top, width, height, outs, ins in layout.nodes.values():
        corners = [(left, top), (left + width, top), (left + width, top - height), (left, top - height)]
        for a, b in zip(corners, corners[1:] + corners[:1]):
            pos += [(a[0], a[1], 0.0), (b[0], b[1], 0.0)]
            col += [(0.2, 1.0, 0.3, 1.0)] * 2
        for sockets, colour in ((outs, (1.0, 0.0, 1.0, 1.0)), (ins, (0.0, 1.0, 1.0, 1.0))):
            for socket in sockets:
                x, y = layout.socket(node, socket)
                for dx, dy in ((-arm, 0), (arm, 0), (0, -arm), (0, arm)):
                    pos.append((x + dx, y + dy, 0.0))
                    col.append(colour)
    if pos:
        shader = shaders["line"]
        shader.uniform_float("viewportSize", size)
        shader.uniform_float("lineWidth", 1.5)
        batch_for_shader(shader, "LINES", {"pos": pos, "color": col}).draw(shader)


def _draw_pixel(*_args):
    try:
        _draw_in_pixels()
    except Exception as error:      # noqa: BLE001
        _fail(error)


def _insets(area):
    """Pixels of the editor's main region covered by its own sidebar, tool shelf, header and footer."""
    left = right = top = bottom = 0.0
    for region in area.regions:
        if region.type == "WINDOW" or region.width <= 1 or region.height <= 1:
            continue
        side = region.alignment
        if side == "RIGHT":
            right = max(right, region.width)
        elif side == "LEFT":
            left = max(left, region.width)
        elif side == "TOP":
            top += region.height
        elif side == "BOTTOM":
            bottom += region.height
    return left, right, top, bottom


def _panel(shaders, batch_for_shader, rect, radius, fill, border, size):
    import gpu
    x, y, w, h = rect
    outline = rounded_rect(x, y, w, h, radius)
    fan = [(x + w / 2, y + h / 2, 0.0)] + [(px, py, 0.0) for px, py in outline] + [(*outline[0], 0.0)]
    flat = shaders["flat"]
    batch_for_shader(flat, "TRI_FAN", {"pos": fan, "color": [fill] * len(fan)}).draw(flat)
    line = shaders["line"]
    ring = [(px, py, 0.0) for px, py in outline + [outline[0]]]
    pairs = [p for a, b in zip(ring, ring[1:]) for p in (a, b)]
    line.uniform_float("viewportSize", size)
    line.uniform_float("lineWidth", 1.2)
    batch_for_shader(line, "LINES", {"pos": pairs, "color": [border] * len(pairs)}).draw(line)
    gpu.state.blend_set("ALPHA")


def _draw_in_pixels():
    import blf
    import bpy
    import gpu
    from gpu_extras.batch import batch_for_shader
    player = _state["player"]
    frame = _state["frame"]
    found = _editor(player)
    if found is None or frame is None:
        return
    space, region, tree, scene = found
    context = bpy.context
    activity = player.activity
    now = player.sim.now if player.sim.now is not None else activity.now
    unit = context.preferences.system.ui_scale or 1.0
    shaders, fid = _shaders(), _font()
    size = (region.width, region.height)
    gpu.state.blend_set("ALPHA")

    # count badges on the links, where they touch no node
    if frame["badges"]:
        _text_size(fid, 11.0 * unit)
        for key, total, points, lengths in frame["badges"]:
            text = str(total)
            width, height = blf.dimensions(fid, text)
            w, h = width + 6.0 * unit, height + 6.0 * unit
            spot = badge_spot(points, lengths, w, h, frame["rects"])
            if spot is None or not (-20 < spot[0] < size[0] + 20 and -20 < spot[1] < size[1] + 20):
                continue
            x, y, w, h = badge_rect(spot[0], spot[1], width, height, 3.0 * unit)
            _panel(shaders, batch_for_shader, (x, y, w, h), h / 2, (0.05, 0.06, 0.08, 0.78),
                   (*frame["colours"][key], 0.95), size)
            blf.color(fid, 0.95, 0.97, 1.0, 1.0)
            blf.position(fid, x + 3.0 * unit, y + 3.0 * unit + 1.0, 0)
            blf.draw(fid, text)

    # in / out above each node's own top-right corner, small, only where it touches nothing
    if frame["counters"]:
        _text_size(fid, 9.0 * unit)
        height = blf.dimensions(fid, "0")[1]
        for text, (x, y, w, h) in counter_labels(frame["counters"], lambda t: blf.dimensions(fid, t)[0], height):
            if x < -50 or y < -20 or x > size[0] or y > size[1]:
                continue
            blf.color(fid, 0.98, 0.78, 0.35, 0.95)
            blf.position(fid, x, y, 0)
            blf.draw(fid, text)

    # the HUD: bottom-left of what the sidebar and header leave, see-through
    left, right, top, bottom = _insets(context.area)
    visible = visible_rect(region.width, region.height, left, right, top, bottom)
    head_px, line_px = 13.0 * unit, 11.0 * unit
    pad, line_h = 10.0 * unit, 16.0 * unit
    stats = [f"ACTIVITY   t {now:8.2f}s",
             f"events {activity.events:>8}   {activity.events_per_second(now):>6.0f}/s",
             f"ROUTEs {activity.routes_active(now)}/{activity.route_count()} active   cascade {activity.widest}"]
    lines = list(activity.ring)[-10:] if getattr(scene, "x3d_activity_stream", True) else []
    room = int((visible[3] - 24.0 * unit - 2 * pad) / line_h) - len(stats) - 1
    lines = lines[-max(0, min(len(lines), room)):] if lines and room > 0 else []
    height = 2 * pad + line_h * (len(stats) + (len(lines) + 0.5 if lines else 0))
    rect = hud_rect(visible, 400.0 * unit, height, 12.0 * unit, 0.6)
    _panel(shaders, batch_for_shader, rect, 8.0 * unit, (0.04, 0.05, 0.07, 0.8), (0.35, 0.8, 1.0, 0.9), size)
    x, ytop = rect[0] + pad, rect[1] + rect[3] - pad
    inner = rect[2] - 2 * pad
    measure = lambda t: blf.dimensions(fid, t)[0]                   # noqa: E731
    for row, text in enumerate(stats):
        _text_size(fid, head_px if row == 0 else line_px)
        blf.color(fid, 0.55, 0.9, 1.0, 1.0) if row == 0 else blf.color(fid, 0.95, 0.97, 1.0, 1.0)
        blf.position(fid, x, ytop - line_h * (row + 0.8), 0)
        blf.draw(fid, trim_text(measure, text, inner))
    _text_size(fid, line_px)
    chips_pos, chips_col = [], []
    base = ytop - line_h * (len(stats) + 0.5)
    for row, entry in enumerate(reversed(lines)):
        yy = base - line_h * (row + 0.8)
        colour = _colour(entry.type)
        s = 7.0 * unit
        chips_pos += [(x, yy, 0), (x + s, yy, 0), (x + s, yy + s, 0), (x, yy, 0), (x + s, yy + s, 0), (x, yy + s, 0)]
        chips_col += [(*colour, 1.0)] * 6
        key = entry.key
        text = f"{entry.time:7.2f} {key[0]}.{key[1]} > {key[2]}.{key[3]}  {value_text(entry.value, 18)}"
        if entry.count > 1:
            text += f"  x{entry.count} {entry.rate:.0f}/s"
        blf.color(fid, 0.82, 0.88, 0.95, 0.95 - 0.05 * row)
        blf.position(fid, x + 12.0 * unit, yy, 0)
        blf.draw(fid, trim_text(measure, text, inner - 12.0 * unit))
    if chips_pos:
        flat = shaders["flat"]
        batch_for_shader(flat, "TRIS", {"pos": chips_pos, "color": chips_col}).draw(flat)
    _state["diag"]["hud"] = {"rect": list(rect), "visible": list(visible), "insets": [left, right, top, bottom]}
    gpu.state.blend_set("NONE")


# ---------------------------------------------------------------------------------------------------------------
# Scene properties, the copy button, registration
# ---------------------------------------------------------------------------------------------------------------

PROPERTIES = (("x3d_activity_show", "Show activity", "Draw events travelling along the links while playing", True),
              ("x3d_activity_stream", "Event stream", "List the latest events in the activity panel", True),
              ("x3d_activity_badges", "Count badges", "Show how many events each link carried", True),
              ("x3d_activity_record", "Record full trace",
               "Keep every delivered event and every call the world received (up to 200,000), for Copy activity report "
               "and the saved JSON", False))


def ensure_properties():
    """Define the three Scene properties when missing (a factory reset with another copy of the add-on drops them)."""
    import bpy
    for name, label, text, default in PROPERTIES:
        if not hasattr(bpy.types.Scene, name):
            setattr(bpy.types.Scene, name, bpy.props.BoolProperty(name=label, description=text, default=default))


def draw_options(layout, context):
    """The Activity checkboxes and the copy button, for the Play panel."""
    ensure_properties()
    box = layout.column(align=True)
    box.label(text="Activity")
    for name, _label, _text, _default in PROPERTIES:
        box.prop(context.scene, name)
    row = box.row()
    row.enabled = last_activity() is not None
    if _state["classes"]:
        row.operator("x3d.behaviour_activity_copy", icon="COPYDOWN")


def copy_text():
    """The last Play's report as plain text, or None when nothing was played with Activity on."""
    activity = last_activity()
    return None if activity is None else report_text(activity.report())


def _classes():
    import bpy
    if _state["classes"] is None:
        class X3D_OT_behaviour_activity_copy(bpy.types.Operator):
            """Put the activity report (events and per-ROUTE totals) on the clipboard as text"""
            bl_idname = "x3d.behaviour_activity_copy"
            bl_label = "Copy activity report"

            @classmethod
            def poll(cls, context):
                return last_activity() is not None

            def execute(self, context):
                text = copy_text()
                if text is None:
                    self.report({"WARNING"}, "Nothing to copy: play the graph first")
                    return {"CANCELLED"}
                context.window_manager.clipboard = text
                self.report({"INFO"}, "Activity report copied")
                return {"FINISHED"}

        _state["classes"] = (X3D_OT_behaviour_activity_copy,)
    return _state["classes"]


def _on_load(*_args):
    stop_overlay()
    _state["last"] = None


def register():
    import bpy
    ensure_properties()
    bpy.app.handlers.persistent(_on_load)         # kept across a file load, where it stops the overlay
    for cls in _classes():
        if not getattr(cls, "is_registered", False):
            bpy.utils.register_class(cls)
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister():
    import bpy
    stop_overlay()
    _state["last"] = None
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    for name, _label, _text, _default in PROPERTIES:
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
    for cls in reversed(_state["classes"] or ()):
        if getattr(cls, "is_registered", False):
            bpy.utils.unregister_class(cls)
