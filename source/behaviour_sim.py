# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Run an X3D behaviour graph: the event model in plain Python, with no Blender and no browser.

``Simulation(graph)`` takes a ``behaviour_graph.Graph`` and plays it. Time is whatever number you hand ``step``; events
you post at sensors travel along the ROUTEs in the same step, and every value that reaches a target (a Transform's
translation, a material's colour) is reported back.

    sim = Simulation(graph)
    sim.start(0.0)
    sim.click("Click", 1.0)           # a TouchSensor press and release
    for change in sim.step(2.5):      # [(target id, field, value), ...]
        ...

What it runs: TimeSensor, the linear interpolators (scalar, position, 2D position, colour in HSV, orientation by slerp),
the sequencers, the four event utilities and triggers, the dampers and the chasers. Pointing sensors do not sense by
themselves here; the caller says what the pointer did (``hover``, ``press``, ``release``, ``drag``). Whatever is not run
is named in ``Simulation.not_simulated``, never silently skipped.

The rules follow ISO/IEC 19775-1:2023 clauses 8 (Time), 19 (Interpolation), 30 (Event utilities) and 39 (Followers), and
where the standard leaves room they follow X_ITE; ``tools/behaviour_sim_judge.cjs`` compares the two on real files.
"""

from __future__ import annotations

import colorsys
import math
from collections import deque

try:
    from . import behaviour_graph as bg
except ImportError:  # imported as a plain module: tests, tools/
    import behaviour_graph as bg

# ---------------------------------------------------------------------------------------------------------------
# X3D text <-> Python values
# ---------------------------------------------------------------------------------------------------------------

_SIZES = {"Vec2f": 2, "Vec2d": 2, "Vec3f": 3, "Vec3d": 3, "Vec4f": 4, "Vec4d": 4, "Color": 3, "ColorRGBA": 4,
          "Rotation": 4}


def parse_value(text, x3d_type):
    """An X3D lexical value as Python: bool, int, float, str, a tuple (vectors, colours, rotations) or a list (MF)."""
    multiple, base = x3d_type.startswith("MF"), x3d_type[2:]
    if base == "String":
        if not multiple:
            return "" if text is None else str(text)
        return _strings(text or "")
    tokens = (text or "").replace(",", " ").split()
    if base == "Bool":
        values = [token.lower() == "true" for token in tokens]
    elif base == "Int32":
        values = [int(float(token)) for token in tokens]
    elif base in ("Float", "Double", "Time"):
        values = [float(token) for token in tokens]
    elif base in _SIZES:
        size = _SIZES[base]
        numbers = [float(token) for token in tokens]
        values = [tuple(numbers[i:i + size]) for i in range(0, len(numbers) - size + 1, size)]
    else:
        return text
    if multiple:
        return values
    if values:
        return values[0]
    return {"Bool": False, "Int32": 0}.get(base, (0.0,) * _SIZES[base] if base in _SIZES else 0.0)


def _strings(text):
    found, current, inside, escaped = [], [], False, False
    for ch in text:
        if escaped:
            current.append(ch)
            escaped = False
        elif ch == "\\" and inside:
            escaped = True
        elif ch == '"':
            if inside:
                found.append("".join(current))
                current = []
            inside = not inside
        elif inside:
            current.append(ch)
    return found


def _lerp(a, b, t):
    if isinstance(a, tuple):
        return tuple(x + (y - x) * t for x, y in zip(a, b))
    return a + (b - a) * t


def _distance(a, b):
    if isinstance(a, tuple):
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))
    return abs(a - b)


def _add(a, b, scale=1.0):
    if isinstance(a, tuple):
        return tuple(x + y * scale for x, y in zip(a, b))
    return a + b * scale


def quaternion(rotation):
    """(x, y, z, w) of an X3D axis-angle rotation."""
    x, y, z, angle = rotation
    length = math.sqrt(x * x + y * y + z * z)
    if length == 0:
        return (0.0, 0.0, 0.0, 1.0)
    s = math.sin(angle / 2) / length
    return (x * s, y * s, z * s, math.cos(angle / 2))


def axis_angle(q):
    """The X3D axis-angle rotation of a quaternion (x, y, z, w)."""
    x, y, z, w = q
    length = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / length, y / length, z / length, max(-1.0, min(1.0, w / length))
    s = math.sqrt(max(0.0, 1 - w * w))
    if s < 1e-9:
        return (0.0, 0.0, 1.0, 0.0)
    return (x / s, y / s, z / s, 2 * math.acos(w))


def slerp(a, b, t):
    """Shortest-path spherical interpolation between two axis-angle rotations."""
    qa, qb = quaternion(a), quaternion(b)
    dot = sum(x * y for x, y in zip(qa, qb))
    if dot < 0:
        qb, dot = tuple(-x for x in qb), -dot
    if dot > 0.9999995:
        return axis_angle(tuple(x + (y - x) * t for x, y in zip(qa, qb)))
    theta = math.acos(dot)
    wa, wb = math.sin((1 - t) * theta) / math.sin(theta), math.sin(t * theta) / math.sin(theta)
    return axis_angle(tuple(x * wa + y * wb for x, y in zip(qa, qb)))


def _rotation_distance(a, b):
    qa, qb = quaternion(a), quaternion(b)
    return 2 * math.acos(min(1.0, abs(sum(x * y for x, y in zip(qa, qb)))))


def hsv_lerp(a, b, t):
    """Colour interpolation as X3D asks for it: through HSV, the short way round the hue circle."""
    ha, sa, va = colorsys.rgb_to_hsv(*a)
    hb, sb, vb = colorsys.rgb_to_hsv(*b)
    if abs(hb - ha) > 0.5:
        if hb > ha:
            ha += 1
        else:
            hb += 1
    return colorsys.hsv_to_rgb((ha + (hb - ha) * t) % 1.0, sa + (sb - sa) * t, va + (vb - va) * t)


# ---------------------------------------------------------------------------------------------------------------
# One class per kind of node
# ---------------------------------------------------------------------------------------------------------------

class _Machine:
    """A behaviour node while it runs. ``receive`` takes an event at an input, ``tick`` is called once per step."""
    ticks = False

    def __init__(self, sim, node):
        self.sim, self.id, self.node_type = sim, node.id, node.node_type
        self.f = {}
        for name, x3d_type, access, default in bg.field_rows(node.node_type):
            if access in ("inputOutput", "initializeOnly"):
                self.f[name] = parse_value(node.fields.get(name, default), x3d_type)
        self.setup()

    def setup(self):
        pass

    def start(self, now):
        pass

    def receive(self, name, value, now):
        if name in self.f:
            self.f[name] = value
            self.changed(name, now)
            self.emit(name, value)

    def changed(self, name, now):
        pass

    def tick(self, now, dt):
        pass

    def emit(self, name, value):
        self.sim._emit(self.id, name, value)


class _TimeSensor(_Machine):
    ticks = True

    def setup(self):
        self.active, self.cycle, self.begun, self.pending = False, 0.0, 0.0, None

    def start(self, now):
        if self.f["loop"] and self.f["enabled"] and self.f["stopTime"] <= self.f["startTime"]:
            self._begin(now)
        elif self.f["startTime"] > now:
            self.pending = self.f["startTime"]

    def _begin(self, now):
        if self.active or not self.f["enabled"]:
            return
        self.active, self.cycle, self.begun, self.pending = True, now, now, None
        interval = self.f["cycleInterval"]
        if self.f["loop"] and interval > 0 and self.f["startTime"] <= now:
            # a looping sensor's cycles are counted from startTime (8.4.1), so its phase does not depend on when
            # the world was loaded
            self.cycle = self.f["startTime"] + interval * math.floor((now - self.f["startTime"]) / interval)
        self.emit("isActive", True)
        self.emit("cycleTime", now)
        self._fraction(now)

    def _end(self, now):
        if self.active:
            self.active = False
            self.emit("isActive", False)

    def _fraction(self, now):
        interval = self.f["cycleInterval"]
        fraction = ((now - self.cycle) / interval) % 1.0 if interval > 0 else 0.0
        self.emit("fraction_changed", fraction)
        self.emit("elapsedTime", now - self.begun)
        self.emit("time", now)

    def receive(self, name, value, now):
        if self.active and name in ("startTime", "cycleInterval"):
            return                                     # 8.2.4.4: ignored while the sensor is active
        super().receive(name, value, now)

    def changed(self, name, now):
        if name == "startTime":
            if self.f["startTime"] <= now:
                self._begin(now)
            else:
                self.pending = self.f["startTime"]
        elif name == "stopTime":
            if self.f["startTime"] < self.f["stopTime"] <= now:
                self._end(now)
        elif name == "enabled":
            if not self.f["enabled"]:
                self._end(now)
            elif self.f["loop"] and self.f["stopTime"] <= self.f["startTime"]:
                self._begin(now)
        elif name == "loop" and self.f["loop"] and self.f["stopTime"] <= self.f["startTime"]:
            self._begin(now)

    def tick(self, now, dt):
        if not self.active:
            if self.pending is not None and now >= self.pending:
                self._begin(now)
            return
        if self.f["startTime"] < self.f["stopTime"] <= now:
            self._end(now)
            return
        interval = self.f["cycleInterval"]
        if interval > 0 and now - self.cycle >= interval:
            if self.f["loop"]:
                self.cycle += interval * math.floor((now - self.cycle) / interval)
                self.emit("cycleTime", now)
                self._fraction(now)                    # X_ITE: the new cycle's fraction is what a ROUTE delivers
            else:
                self.emit("fraction_changed", 1.0)
                self.emit("elapsedTime", now - self.begun)
                self.emit("time", now)
                self._end(now)
        else:
            self._fraction(now)


class _Interpolator(_Machine):
    mix = staticmethod(_lerp)

    def receive(self, name, value, now):
        if name != "set_fraction":
            return super().receive(name, value, now)
        keys, values = self.f.get("key") or [], self.f.get("keyValue") or []
        count = min(len(keys), len(values))
        if count == 0:
            return
        if value <= keys[0] or count == 1:
            return self.emit("value_changed", values[0])
        if value >= keys[count - 1]:
            return self.emit("value_changed", values[count - 1])
        for i in range(1, count):
            if value < keys[i]:
                span = keys[i] - keys[i - 1]
                t = (value - keys[i - 1]) / span if span > 0 else 0.0
                return self.emit("value_changed", self.mix(values[i - 1], values[i], t))


class _ColorInterpolator(_Interpolator):
    mix = staticmethod(hsv_lerp)


class _OrientationInterpolator(_Interpolator):
    mix = staticmethod(slerp)


class _Sequencer(_Machine):
    def setup(self):
        self.index = -1

    def _send(self, index):
        values = self.f.get("keyValue") or []
        if values:
            self.index = index % len(values)
            self.emit("value_changed", values[self.index])

    def receive(self, name, value, now):
        if name == "set_fraction":
            keys, values = self.f.get("key") or [], self.f.get("keyValue") or []
            count = min(len(keys), len(values))
            if count == 0:
                return
            index = 0
            for i in range(count):
                if value >= keys[i]:
                    index = i
            if index != self.index:
                self._send(index)
        elif name == "next" and value:
            self._send(self.index + 1)
        elif name == "previous" and value:
            self._send(self.index - 1)
        else:
            super().receive(name, value, now)


class _BooleanFilter(_Machine):
    def receive(self, name, value, now):
        if name != "set_boolean":
            return super().receive(name, value, now)
        self.emit("inputTrue" if value else "inputFalse", bool(value))
        self.emit("inputNegate", not value)


class _BooleanToggle(_Machine):
    def receive(self, name, value, now):
        if name == "set_boolean":
            if value:
                self.f["toggle"] = not self.f["toggle"]
                self.emit("toggle", self.f["toggle"])
        else:
            super().receive(name, value, now)


class _BooleanTrigger(_Machine):
    def receive(self, name, value, now):
        if name == "set_triggerTime":
            self.emit("triggerTrue", True)


class _IntegerTrigger(_Machine):
    def receive(self, name, value, now):
        if name == "set_boolean":
            if value:                                  # X_ITE 16.7.1 answers true only (measured: the judge's probe)
                self.emit("triggerValue", self.f["integerKey"])
        else:
            super().receive(name, value, now)


class _TimeTrigger(_Machine):
    def receive(self, name, value, now):
        if name == "set_boolean" and value:           # true only, as X_ITE 16.7.1 does
            self.emit("triggerTime", now)


class _Damper(_Machine):
    ticks = True
    mix, gap = staticmethod(_lerp), staticmethod(_distance)

    def setup(self):
        self.buffer = [self.f["initialDestination"]] + [self.f["initialValue"]] * max(1, self.f["order"])
        self.active = False

    def start(self, now):
        if self.gap(self.buffer[0], self.buffer[-1]) > self._tolerance():
            self._wake()

    def _tolerance(self):
        return self.f["tolerance"] if self.f["tolerance"] >= 0 else 1e-4

    def _wake(self):
        if not self.active:
            self.active = True
            self.emit("isActive", True)

    def receive(self, name, value, now):
        if name == "set_destination":
            self.buffer[0] = value
            if self.gap(self.buffer[0], self.buffer[-1]) > self._tolerance():
                self._wake()
        elif name == "set_value":
            self.buffer[1:] = [value] * (len(self.buffer) - 1)
            self.emit("value_changed", value)
            if self.gap(self.buffer[0], value) > self._tolerance():
                self._wake()
        else:
            super().receive(name, value, now)

    def tick(self, now, dt):
        if not self.active:
            return
        tau = self.f["tau"]
        if tau > 0:
            alpha = math.exp(-dt / tau)
            for i in range(len(self.buffer) - 1):
                self.buffer[i + 1] = self.mix(self.buffer[i], self.buffer[i + 1], alpha)
            self.emit("value_changed", self.buffer[-1])
            if self.gap(self.buffer[-1], self.buffer[0]) >= self._tolerance():
                return
        else:
            self.emit("value_changed", self.buffer[0])
        self.buffer[1:] = [self.buffer[0]] * (len(self.buffer) - 1)
        self.active = False
        self.emit("isActive", False)


class _ColorDamper(_Damper):
    mix = staticmethod(hsv_lerp)


class _OrientationDamper(_Damper):
    mix, gap = staticmethod(slerp), staticmethod(_rotation_distance)


def _ease(t):
    """A chaser's answer to a jump, 0 to 1 over its duration: slow, fast, slow (half a cosine, as X_ITE draws it)."""
    return 0.0 if t <= 0 else 1.0 if t >= 1 else 0.5 - 0.5 * math.cos(math.pi * t)


class _Chaser(_Machine):
    """A chaser answers a jump of its destination with an eased ramp that takes ``duration`` seconds. Jumps add up."""
    ticks = True

    def setup(self):
        self.destination, self.value = self.f["initialDestination"], self.f["initialValue"]
        self.steps, self.active = [], False            # (time of the jump, how far it jumped)

    def start(self, now):
        if _distance(self.destination, self.value) > 0:
            self.steps.append((now, _add(self.destination, self.value, -1.0)))
            self.active = True
            self.emit("isActive", True)

    def receive(self, name, value, now):
        if name == "set_destination":
            if _distance(value, self.destination) == 0:
                return
            self.steps.append((now, _add(value, self.destination, -1.0)))
            self.destination = value
            if not self.active:
                self.active = True
                self.emit("isActive", True)
        elif name == "set_value":
            self.steps, self.value = [(now, _add(self.destination, value, -1.0))], value
            self.emit("value_changed", value)
            if not self.active:
                self.active = True
                self.emit("isActive", True)
        else:
            super().receive(name, value, now)

    def tick(self, now, dt):
        if not self.active:
            return
        duration, value = self.f["duration"], self.destination
        self.steps = [step for step in self.steps if duration > 0 and now - step[0] < duration]
        for began, jump in self.steps:
            value = _add(value, jump, -(1 - _ease((now - began) / duration)))
        self.value = value
        self.emit("value_changed", value)
        if not self.steps:
            self.active = False
            self.emit("isActive", False)


class _OrientationChaser(_Machine):
    """One ramp at a time: slerp from where it was when the destination last changed."""
    ticks = True

    def setup(self):
        self.destination = self.origin = self.value = None
        self.destination, self.value = self.f["initialDestination"], self.f["initialValue"]
        self.origin, self.began, self.active = self.value, 0.0, False

    def start(self, now):
        if _rotation_distance(self.destination, self.value) > 1e-6:
            self.began, self.active = now, True
            self.emit("isActive", True)

    def receive(self, name, value, now):
        if name in ("set_destination", "set_value"):
            if name == "set_value":
                self.value = value
                self.emit("value_changed", value)
            elif _rotation_distance(value, self.destination) < 1e-9:
                return
            else:
                self.destination = value
            self.origin, self.began = self.value, now
            if not self.active:
                self.active = True
                self.emit("isActive", True)
        else:
            super().receive(name, value, now)

    def tick(self, now, dt):
        if not self.active:
            return
        duration = self.f["duration"]
        t = min(1.0, (now - self.began) / duration) if duration > 0 else 1.0
        self.value = slerp(self.origin, self.destination, _ease(t))
        self.emit("value_changed", self.value)
        if t >= 1.0:
            self.active = False
            self.emit("isActive", False)


class _Sensor(_Machine):
    """A sensor the caller drives: its outputs are posted from outside (``Simulation.post``, ``press``, ``drag``)."""

    def setup(self):
        self.over = self.pressed = False
        self.origin = None


_MACHINES = {
    "TimeSensor": _TimeSensor,
    "ScalarInterpolator": _Interpolator, "PositionInterpolator": _Interpolator, "PositionInterpolator2D": _Interpolator,
    "ColorInterpolator": _ColorInterpolator, "OrientationInterpolator": _OrientationInterpolator,
    "BooleanSequencer": _Sequencer, "IntegerSequencer": _Sequencer,
    "BooleanFilter": _BooleanFilter, "BooleanToggle": _BooleanToggle, "BooleanTrigger": _BooleanTrigger,
    "IntegerTrigger": _IntegerTrigger, "TimeTrigger": _TimeTrigger,
    "ScalarDamper": _Damper, "PositionDamper": _Damper, "PositionDamper2D": _Damper, "ColorDamper": _ColorDamper,
    "OrientationDamper": _OrientationDamper,
    "ScalarChaser": _Chaser, "PositionChaser": _Chaser, "PositionChaser2D": _Chaser, "ColorChaser": _Chaser,
    "OrientationChaser": _OrientationChaser,
    "TouchSensor": _Sensor, "PlaneSensor": _Sensor, "CylinderSensor": _Sensor, "SphereSensor": _Sensor,
    "ProximitySensor": _Sensor, "VisibilitySensor": _Sensor, "KeySensor": _Sensor, "StringSensor": _Sensor,
}

# sensors the caller can drive with press / release / drag; the others only through post()
POINTING = ("TouchSensor", "PlaneSensor", "CylinderSensor", "SphereSensor")
SIMULATED = tuple(sorted(_MACHINES))


class Simulation:
    """A behaviour graph, running. See the module text for the short tour."""

    def __init__(self, graph, *, log_size=400):
        self.graph = graph
        self.machines, self.not_simulated = {}, []
        for node in graph.nodes.values():
            if node.role == bg.BEHAVIOUR and node.node_type in _MACHINES:
                self.machines[node.id] = _MACHINES[node.node_type](self, node)
            elif node.role != bg.TARGET:
                self.not_simulated.append(f"{node.node_type} {node.id}")
        self._routes = {}
        for route in graph.routes:
            source = self._canonical(route.from_id, route.from_field, "out")
            destination = self._canonical(route.to_id, route.to_field, "in")
            if source and destination:
                self._routes.setdefault(source, []).append(destination)
        self.values = {}                 # (target id, field) -> the last value that reached it
        self.outputs = {}                # (node id, field) -> the last value any node sent
        self.log = deque(maxlen=log_size)   # (time, node id, field, value) of every event sent
        self.now = None
        self._queue, self._changes, self._fired = deque(), [], set()

    def _canonical(self, node_id, field_name, direction):
        node = self.graph.nodes.get(node_id)
        if node is None:
            return None
        if node.role == bg.CARRIED:
            return (node_id, field_name)
        try:
            return (node_id, bg.resolve_field(node.node_type, field_name, direction)[0])
        except bg.BehaviourError:
            return None

    # -- the cascade ------------------------------------------------------------------------------------------

    def _emit(self, node_id, field_name, value):
        self._queue.append((node_id, field_name, value))

    def _drain(self):
        now = self.now
        while self._queue:
            node_id, field_name, value = self._queue.popleft()
            self.outputs[(node_id, field_name)] = value
            self.log.append((now, node_id, field_name, value))
            for to_id, to_field in self._routes.get((node_id, field_name), ()):
                key = (node_id, field_name, to_id, to_field)
                if key in self._fired:               # 4.4.8.3: a ROUTE carries one event per timestamp, which
                    continue                         # is also what stops a loop of ROUTEs
                self._fired.add(key)
                machine = self.machines.get(to_id)
                if machine is not None:
                    machine.receive(to_field, value, now)
                elif self.graph.nodes[to_id].role == bg.TARGET:
                    self.values[(to_id, to_field)] = value
                    self._changes.append((to_id, to_field, value))
                    self._emit(to_id, to_field, value)      # an inputOutput field sends what it was given

    def _collect(self):
        changes, self._changes = self._changes, []
        return changes

    # -- what the caller does -----------------------------------------------------------------------------------

    def start(self, now=0.0):
        """Begin at time ``now``: looping timers start, followers that are not at rest wake up."""
        self.now, self._fired = now, set()
        for machine in self.machines.values():
            machine.start(now)
        self._drain()
        return self._collect()

    def step(self, now):
        """Advance to time ``now``; returns [(target id, field, value)] in the order the values arrived."""
        if self.now is None:
            return self.start(now)
        dt, self.now, self._fired = max(0.0, now - self.now), now, set()
        # every time-driven node first works out what it sends, from what it knew before this step; then the events
        # travel. So a follower chases where its destination was one step ago, as it does in X_ITE.
        for machine in list(self.machines.values()):
            if machine.ticks:
                machine.tick(now, dt)
        self._drain()
        return self._collect()

    def post(self, node_id, field_name, value, now=None):
        """Send ``value`` out of an output field, as the node itself would (a sensor that sensed something)."""
        if now is not None:
            self.now = now
        self._fired = set()              # something outside the graph happened: that is a new moment
        self._emit(node_id, field_name, value)
        self._drain()
        return self._collect()

    def send(self, node_id, field_name, value, now=None):
        """Deliver ``value`` to an input field, as a ROUTE would."""
        if now is not None:
            self.now = now
        machine = self.machines.get(node_id)
        if machine is None:
            raise bg.BehaviourError("unknown-def", f"{node_id!r} is not a node this simulation runs")
        name = bg.resolve_field(machine.node_type, field_name, "in")[0]
        self._fired = set()
        machine.receive(name, value, self.now)
        self._drain()
        return self._collect()

    # pointing sensors: the caller is the pointer

    def _sensor(self, node_id):
        machine = self.machines.get(node_id)
        if machine is None or machine.node_type not in POINTING:
            raise bg.BehaviourError("unknown-def", f"{node_id!r} is not a pointing sensor in this graph")
        return machine

    def hover(self, node_id, over, now):
        sensor = self._sensor(node_id)
        if not sensor.f.get("enabled", True) or sensor.over == bool(over):
            return []
        sensor.over = bool(over)
        return self.post(node_id, "isOver", sensor.over, now)

    def press(self, node_id, now, point=(0.0, 0.0, 0.0)):
        """The pointer button goes down on the sensor's shapes. ``point`` is where, in the sensor's own coordinates."""
        sensor = self._sensor(node_id)
        if not sensor.f.get("enabled", True) or sensor.pressed:
            return []
        changes = self.hover(node_id, True, now)
        sensor.pressed, sensor.origin = True, tuple(point)
        return changes + self.post(node_id, "isActive", True, now)

    def drag(self, node_id, point, now):
        """The pointer moves with the button down. A PlaneSensor sends where its plane was hit, less where it began."""
        sensor = self._sensor(node_id)
        if not sensor.pressed:
            return []
        changes = []
        if sensor.node_type == "PlaneSensor":
            changes += self.post(node_id, "trackPoint_changed", tuple(point), now)
            moved = _add(_add(tuple(point), sensor.origin, -1.0), sensor.f["offset"])
            low, high = sensor.f["minPosition"], sensor.f["maxPosition"]
            moved = tuple(min(max(moved[i], low[i]), high[i]) if i < 2 and high[i] >= low[i] else moved[i]
                          for i in range(3))
            moved = (moved[0], moved[1], sensor.f["offset"][2])
            sensor.last = moved
            changes += self.post(node_id, "translation_changed", moved, now)
        return changes

    def release(self, node_id, now):
        sensor = self._sensor(node_id)
        if not sensor.pressed:
            return []
        sensor.pressed = False
        changes = self.post(node_id, "isActive", False, now)
        if sensor.node_type == "TouchSensor" and sensor.over:
            changes += self.post(node_id, "touchTime", now, now)
        if sensor.node_type == "PlaneSensor" and sensor.f["autoOffset"] and getattr(sensor, "last", None):
            sensor.f["offset"] = sensor.last
            changes += self.post(node_id, "offset", sensor.last, now)
        return changes

    def click(self, node_id, now, held=0.0):
        """Press and release. ``held`` seconds later for the release."""
        return self.press(node_id, now) + self.release(node_id, now + held)
