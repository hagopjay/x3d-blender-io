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
EaseInEaseOut, the Spline interpolators (scalar, position, 2D position), SquadOrientationInterpolator, CylinderSensor and
SphereSensor drags (from the pointer's ray and the viewer, X_ITE's rules), KeySensor and StringSensor from raw keys (X_ITE's rules, one enabled at a time), the sequencers, the four event utilities and triggers, the dampers and the chasers. Pointing sensors do not sense by
themselves here; the caller says what the pointer did (``hover``, ``press``, ``release``, ``drag``). Whatever is not run
is named in ``Simulation.not_simulated``, never silently skipped.

The rules follow ISO/IEC 19775-1:2023 clauses 8 (Time), 19 (Interpolation), 30 (Event utilities) and 39 (Followers), and
where the standard leaves room they follow X_ITE; ``tools/behaviour_sim_judge.cjs`` compares the two on real files.
"""

from __future__ import annotations

import bisect
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
        self.finished_at = None        # when a non-looping cycle last ran out (see receive)

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
        if interval > 0 and self.f["startTime"] <= now:
            # cycles are counted from startTime (8.4.1), looping or not, so a sensor started with a startTime in the
            # past starts part way through a cycle (X_ITE's setRange: fraction = fract((now - startTime) / interval))
            # and a non-looping one ends when that cycle does; a loop's phase does not depend on when the world loaded
            offset = ((now - self.f["startTime"]) / interval) % 1.0
            self.cycle = now - offset * interval
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
        if name in ("startTime", "cycleInterval") and (self.active or self.finished_at == now):
            # 8.2.4.4: ignored while the sensor is active. X_ITE sends elapsedTime in its prepare phase and ends a
            # finished cycle later in the same frame, so a startTime that arrives in the frame the cycle ran out
            # still finds the sensor active; the next one (a frame later) starts it again
            return
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
                self.finished_at = now
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


# -- EaseInEaseOut, the Spline interpolators and Squad: X_ITE's algorithms, judged against it -----------------------

class _Segmented(_Machine):
    """X_ITE's X3DInterpolatorNode: which two keys a fraction falls between and how far along (0 to 1). Before the
    first key: (0, 1, 0); after the last: the last two keys at 1; one key: (0, 0, 0); no key: no event."""

    def setup(self):
        self.rebuild()

    def changed(self, name, now):
        self.rebuild()

    def rebuild(self):
        pass

    def receive(self, name, value, now):
        if name != "set_fraction":
            return super().receive(name, value, now)
        keys = self.f.get("key") or []
        count = len(keys)
        if count == 0:
            return None
        if count == 1:
            return self.interpolate(0, 0, 0.0)
        if value <= keys[0]:
            return self.interpolate(0, 1, 0.0)
        upper = bisect.bisect_right(keys, value)
        if upper != count:
            lower = upper - 1
            weight = (value - keys[lower]) / (keys[upper] - keys[lower])
            return self.interpolate(lower, upper, min(1.0, max(0.0, weight)))
        return self.interpolate(count - 2, count - 1, 1.0)

    def _padded(self, name, zero):
        """X_ITE pads a value list that is shorter than ``key`` with its last value (or the type's zero)."""
        values = list(self.f.get(name) or [])
        wanted = len(self.f.get("key") or [])
        if len(values) < wanted:
            values += [values[-1] if values else zero] * (wanted - len(values))
        return values


class _EaseInEaseOut(_Segmented):
    """Sends the eased weight within the segment, 0 to 1 (X_ITE), not a fraction mapped back onto the keys. A
    segment's ease out is its first key's y, its ease in the second key's x; together above 1, both are scaled down."""

    def interpolate(self, lower, upper, weight):
        pairs = self._padded("easeInEaseOut", (0.0, 0.0))
        ease_out, ease_in = pairs[lower][1], pairs[upper][0]
        total = ease_out + ease_in
        if total < 0:
            return self.emit("modifiedFraction_changed", weight)
        if total > 1:
            ease_in, ease_out = ease_in / total, ease_out / total
        t = 1 / (2 - ease_out - ease_in)
        if weight < ease_out:
            eased = (t / ease_out) * weight * weight
        elif weight <= 1 - ease_in:                    # X_ITE: <=, so an ease in of 0 never divides by it
            eased = t * (2 * weight - ease_out)
        else:
            eased = 1 - (t * (1 - weight) ** 2) / ease_in
        return self.emit("modifiedFraction_changed", eased)


def _scale(a, k):
    return tuple(x * k for x in a) if isinstance(a, tuple) else a * k


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b)) if isinstance(a, tuple) else a - b


def _magnitude(a):
    return math.sqrt(sum(x * x for x in a)) if isinstance(a, tuple) else abs(a)


class _SplineInterpolator(_Segmented):
    """X_ITE's CatmullRomSplineInterpolator (X3D 19.4.5 to 19.4.7) as written there: an open curve's end tangents are
    zero; a closed one's first tangent wraps and its last copies the first; velocities shorter than ``key`` are padded
    with zeros; ``normalizeVelocity`` scales every velocity but the last to the path length; tangents are weighted by
    the key spacing on each side, then a cubic Hermite runs on each segment."""

    def rebuild(self):
        keys = self.f.get("key") or []
        zero = (0.0,) * len(self.f["keyValue"][0]) if self.f.get("keyValue") and \
            isinstance(self.f["keyValue"][0], tuple) else 0.0
        if self.node_type == "SplinePositionInterpolator2D":
            zero = (0.0, 0.0)
        elif self.node_type == "SplinePositionInterpolator":
            zero = (0.0, 0.0, 0.0)
        values = self.values = self._padded("keyValue", zero)
        velocities = list(self.f.get("keyVelocity") or [])
        if velocities and len(velocities) < len(keys):
            velocities += [zero] * (len(keys) - len(velocities))
        self.T0, self.T1 = [zero], [zero]
        if len(keys) <= 1:
            return
        if not velocities:
            first = _scale(_sub(values[1], values[-2]), 0.5) if self.f.get("closed") else zero
            tangents = [first] + [_scale(_sub(values[i + 1], values[i - 1]), 0.5) for i in range(1, len(values) - 1)]
            tangents.append(tangents[0])
        else:
            tangents = list(velocities)
            if self.f.get("normalizeVelocity"):
                path = sum(_magnitude(_sub(values[i + 1], values[i])) for i in range(len(values) - 1))
                for i in range(len(tangents) - 1):            # X_ITE leaves the last velocity as it is
                    size = _magnitude(tangents[i])
                    if size:
                        tangents[i] = _scale(tangents[i], path / size)
        last = len(keys) - 1
        if self.f.get("closed"):
            d = keys[1] - keys[0] + keys[last] - keys[last - 1]
            minus, plus = [2 * (keys[1] - keys[0]) / d], [2 * (keys[last] - keys[last - 1]) / d]
        else:
            minus, plus = [1.0], [1.0]
        for i in range(1, last):
            d = keys[i + 1] - keys[i - 1]
            minus.append(2 * (keys[i + 1] - keys[i]) / d)
            plus.append(2 * (keys[i] - keys[i - 1]) / d)
        minus.append(minus[0])
        plus.append(plus[0])
        count = min(len(tangents), len(plus))
        self.T0 = [_scale(tangents[i], plus[i]) for i in range(count)]
        self.T1 = [_scale(tangents[i], minus[i]) for i in range(count)]

    def interpolate(self, lower, upper, weight):
        w2, w3 = weight * weight, weight * weight * weight
        h = (2 * w3 - 3 * w2 + 1, -2 * w3 + 3 * w2, w3 - 2 * w2 + weight, w3 - w2)
        parts = (self.values[lower], self.values[upper], self.T0[lower], self.T1[upper])
        if isinstance(parts[0], tuple):
            value = tuple(sum(k * part[i] for k, part in zip(h, parts)) for i in range(len(parts[0])))
        else:
            value = sum(k * part for k, part in zip(h, parts))
        return self.emit("value_changed", value)


# quaternions as (x, y, z, w), with X_ITE's conventions: q.multRight(r) is r * q; slerp goes the short way and returns
# the source unchanged when the two are equal

def _q_mul(p, q):
    px, py, pz, pw = p
    qx, qy, qz, qw = q
    return (pw * qx + px * qw + py * qz - pz * qy, pw * qy + py * qw + pz * qx - px * qz,
            pw * qz + pz * qw + px * qy - py * qx, pw * qw - px * qx - py * qy - pz * qz)


def _q_inverse(q):
    x, y, z, w = -q[0], -q[1], -q[2], q[3]
    norm = x * x + y * y + z * z + w * w
    return (x / norm, y / norm, z / norm, w / norm) if norm else (x, y, z, w)


def _q_log(q):
    x, y, z, w = q
    r = math.sqrt(x * x + y * y + z * z)
    t = math.atan2(r, w) / r if r > 0 else 0.0
    return (x * t, y * t, z * t, 0.5 * math.log(x * x + y * y + z * z + w * w))


def _q_exp(q):
    x, y, z, w = q
    r = math.sqrt(x * x + y * y + z * z)
    et = math.exp(w)
    s = et * math.sin(r) / r if r > 0 else 0.0
    return (x * s, y * s, z * s, et * math.cos(r))


def _q_normalize(q):
    n = math.sqrt(sum(c * c for c in q))
    return tuple(c / n for c in q) if n else q


def _q_slerp(a, b, t):
    cosom = sum(x * y for x, y in zip(a, b))
    if cosom < 0:
        cosom, b = -cosom, tuple(-c for c in b)
    if cosom >= 1:
        return a
    omega = math.acos(cosom)
    sinom = math.sin(omega)
    k0, k1 = math.sin((1 - t) * omega) / sinom, math.sin(t * omega) / sinom
    return tuple(x * k0 + y * k1 for x, y in zip(a, b))


def _q_spline(q0, q1, q2):
    """Shoemake's inner control point at q1 (X_ITE's Quaternion.spline)."""
    if sum(x * y for x, y in zip(q0, q1)) < 0:
        q0 = tuple(-c for c in q0)
    if sum(x * y for x, y in zip(q2, q1)) < 0:
        q2 = tuple(-c for c in q2)
    inverse = _q_inverse(q1)
    a, b = _q_log(_q_mul(q0, inverse)), _q_log(_q_mul(q2, inverse))
    middle = _q_exp(tuple((x + y) / -4 for x, y in zip(a, b)))
    return _q_normalize(_q_mul(middle, q1))


class _SquadOrientationInterpolator(_Segmented):
    """X_ITE's SquadInterpolator: Shoemake's squad through inner points made by ``_q_spline``; an open path's ends use
    the key itself as their inner point. X_ITE does not use ``normalizeVelocity`` here."""

    def rebuild(self):
        keys = self.f.get("key") or []
        rotations = self._padded("keyValue", (0.0, 0.0, 1.0, 0.0))
        self.q = [quaternion(r) for r in rotations]
        q, n = self.q, len(keys)
        if n > 1:
            closed = bool(self.f.get("closed"))
            self.inner = [_q_spline(q[n - 2], q[0], q[1]) if closed else q[0]]
            self.inner += [_q_spline(q[i - 1], q[i], q[i + 1]) for i in range(1, n - 1)]
            self.inner.append(_q_spline(q[n - 2], q[n - 1], q[1]) if closed else q[n - 1])
        else:
            self.inner = q[:1]

    def interpolate(self, lower, upper, weight):
        q, inner = self.q, self.inner
        outer = _q_slerp(q[lower], q[upper], weight)
        between = _q_slerp(inner[lower], inner[upper], weight)
        return self.emit("value_changed", axis_angle(_q_slerp(outer, between, 2 * weight * (1 - weight))))


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


# -- drag sensors: X_ITE's CylinderSensor and SphereSensor --------------------------------------------------------
# Vectors are 3-tuples in the sensor's own coordinates. A rotation is kept as X_ITE keeps it (Rotation4): a quaternion
# built from axis and angle with the half angle wrapped into [0, pi), compared exactly, read back by acos.

def _v_add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _v_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _v_scale(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def _v_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _v_cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _v_norm(a):
    return math.sqrt(_v_dot(a, a))


def _v_unit(a):
    n = _v_norm(a)
    return _v_scale(a, 1 / n) if n else a


def _interval(value, low, high):
    """X_ITE's Algorithm.interval: wrap ``value`` into [low, high) (JavaScript's %, which keeps the dividend's sign)."""
    if value >= high:
        return math.fmod(value - low, high - low) + low
    if value < low:
        return math.fmod(value - high, high - low) + high
    return value


class _Rot:
    def __init__(self, q=(0.0, 0.0, 0.0, 1.0), raw=None):
        self.q = tuple(q)
        self.raw = raw          # the axis and angle it was made from; X_ITE reads those back until it is multiplied

    @classmethod
    def axis_angle(cls, x, y, z, angle):
        raw = (x, y, z, angle)
        scale = math.hypot(x, y, z)
        if scale == 0:
            return cls(raw=raw)
        half = _interval(angle / 2, 0, math.pi)
        k = math.sin(half) / scale
        return cls((x * k, y * k, z * k, math.cos(half)), raw=raw)

    @classmethod
    def from_vectors(cls, a, b):
        a, b = _v_unit(a), _v_unit(b)
        cos_angle = max(-1.0, min(1.0, _v_dot(a, b)))
        cross = _v_unit(_v_cross(a, b))
        if _v_norm(cross) == 0:
            if cos_angle > 0:
                return cls()
            t = _v_cross(a, (1.0, 0.0, 0.0))
            if _v_dot(t, t) == 0:
                t = _v_cross(a, (0.0, 1.0, 0.0))
            t = _v_unit(t)
            return cls((t[0], t[1], t[2], 0.0))
        k = math.sqrt(abs(1 - cos_angle) / 2)
        return cls((cross[0] * k, cross[1] * k, cross[2] * k, math.sqrt(abs(1 + cos_angle) / 2)))

    def value(self):
        """What X_ITE reads back: the axis and angle it was made from, or (after a product) Rotation4.get."""
        if self.raw is not None:
            return self.raw
        x, y, z, w = self.q
        if abs(w) >= 1:
            return (0.0, 0.0, 1.0, 0.0)
        angle = math.acos(w) * 2
        scale = math.sin(angle / 2)
        if scale == 0:
            return (0.0, 0.0, 1.0, 0.0)
        return (x / scale, y / scale, z / scale, angle)

    def then(self, other):                      # X_ITE multRight: this, then other (other * this), normalised
        return _Rot(_q_normalize(_q_mul(other.q, self.q)))

    def after(self, other):                     # X_ITE multLeft: other, then this (this * other), normalised
        return _Rot(_q_normalize(_q_mul(self.q, other.q)))

    def inverse(self):
        x, y, z, w = self.q
        return _Rot((-x, -y, -z, w))

    def rotate(self, v):
        qx, qy, qz, qw = self.q
        t = _v_scale(_v_cross((qx, qy, qz), v), 2)
        return _v_add(_v_add(v, _v_scale(t, qw)), _v_cross((qx, qy, qz), t))


def _perpendicular(line_point, line_direction, point):
    """X_ITE's Line3.getPerpendicularVectorToPoint: from ``point`` to the line, square to it."""
    r = _v_sub(line_point, point)
    return _v_sub(r, _v_scale(line_direction, _v_dot(r, line_direction)))


class _Plane:
    def __init__(self, point, normal):
        self.normal, self.d = tuple(normal), _v_dot(normal, point)

    def distance(self, point):
        return _v_dot(point, self.normal) - self.d

    def meet(self, origin, direction):
        theta = _v_dot(direction, self.normal)
        if theta == 0:
            return None
        return _v_add(_v_scale(direction, (self.d - _v_dot(self.normal, origin)) / theta), origin)


def _ray(ray):
    origin, direction = ray
    return tuple(origin), _v_unit(tuple(direction))


class _DragSensor(_Machine):
    """A CylinderSensor or SphereSensor. ``press`` and ``drag`` take the pointer's ray and, on press, the hit point
    and the viewer (where it is and which way is back), all in the sensor's own coordinates."""

    def setup(self):
        self.over = self.pressed = False
        self.origin = None

    # CylinderSensor ------------------------------------------------------------------------------------------------

    def _cylinder_behind(self, origin, direction, hit):
        """Inventor's SbCylinder: which crossing is 'enter' depends on the sign of b, not on the order along the ray."""
        p, d = origin, direction
        y = self.y_axis
        p_perp, d_perp = _v_sub(p, _v_scale(y, _v_dot(p, y))), _v_sub(d, _v_scale(y, _v_dot(d, y)))
        a, b, c = _v_dot(d_perp, d_perp), 2 * _v_dot(p_perp, d_perp), _v_dot(p_perp, p_perp) - self.radius ** 2
        disc = b * b - 4 * a * c
        if disc < 0 or a == 0:
            enter = exit_ = (0.0, 0.0, 0.0)            # X_ITE leaves both at zero: never behind
        else:
            plus, minus = (-b + math.sqrt(disc)) / (2 * a), (-b - math.sqrt(disc)) / (2 * a)
            t_enter, t_exit = (plus, minus) if b > 0 else (minus, plus)
            enter, exit_ = _v_add(p, _v_scale(d, t_enter)), _v_add(p, _v_scale(d, t_exit))
        return _v_norm(_v_sub(hit, enter)) > _v_norm(_v_sub(hit, exit_))

    def _cylinder_track(self, origin, direction):
        z_point = self.z_plane.meet(origin, direction) or (0.0, 0.0, 0.0)
        axis_point = _v_add(z_point, _perpendicular((0.0, 0.0, 0.0), self.y_axis, z_point))
        distance = self.sx_plane.distance(z_point) / self.radius
        section = math.floor((distance + 1) / 2)
        sinp = _interval(distance, -1, 1)
        phi = math.asin(sinp) if section == 0 else sinp * math.pi / 2
        turn = _Rot.axis_angle(*self.y_axis, phi + section * math.pi)
        return _v_add(turn.rotate(_v_scale(self.sz_normal, self.radius)), axis_point)

    def _cylinder_point(self, origin, direction):
        if self.disk:
            return self.y_plane.meet(origin, direction) or (0.0, 0.0, 0.0)
        return self._cylinder_track(origin, direction)

    def cylinder_press(self, ray, hit, eye):
        origin, direction = ray
        eye_origin, eye_back = eye
        axis_rotation = _Rot.axis_angle(*self.f["axisRotation"])
        self.axis_rotation = axis_rotation
        self.y_axis = axis_rotation.rotate((0.0, 1.0, 0.0))
        back = _v_unit(eye_back)
        self.eye_origin, self.eye_back = tuple(eye_origin), back
        self.radius = _v_norm(_perpendicular((0.0, 0.0, 0.0), self.y_axis, hit))
        self.disk = abs(_v_dot(back, self.y_axis)) > math.cos(self.f["diskAngle"])
        self.behind = self._cylinder_behind(origin, direction, hit)
        self.y_plane, self.z_plane = _Plane(hit, self.y_axis), _Plane(hit, back)
        sx_normal = _v_unit(_v_cross(self.y_axis, self.eye_origin))
        self.sx_plane = _Plane((0.0, 0.0, 0.0), sx_normal)
        self.sz_normal = _v_unit(_v_cross(sx_normal, self.y_axis))
        track = self._cylinder_point(origin, direction)
        self.from_vector = _v_scale(_perpendicular((0.0, 0.0, 0.0), self.y_axis, track), -1)
        self.start_offset = _Rot.axis_angle(*self.y_axis, self.f["offset"])
        self.rotation = self.start_offset
        self.angle = self.f["offset"]
        self.start_vector = self.rotation.rotate(axis_rotation.rotate((0.0, 0.0, 1.0)))
        return [("trackPoint_changed", track), ("rotation_changed", self.rotation.value())]

    def cylinder_drag(self, ray):
        origin, direction = ray
        track = self._cylinder_point(origin, direction)
        sent = [("trackPoint_changed", track)]
        to_vector = _v_scale(_perpendicular((0.0, 0.0, 0.0), self.y_axis, track), -1)
        rotation = _Rot.from_vectors(self.from_vector, to_vector)
        if self.disk:
            if _v_dot(_v_sub(track, self.eye_origin), self.eye_back) > 0:   # behind the viewer
                rotation = rotation.then(_Rot.axis_angle(*self.y_plane.normal, math.pi))
        elif self.behind:
            rotation = rotation.inverse()
        rotation = rotation.after(self.start_offset)
        low, high = self.f["minAngle"], self.f["maxAngle"]
        if low > high:
            self.rotation = rotation
            return sent + [("rotation_changed", rotation.value())]
        end_vector = rotation.rotate(self.axis_rotation.rotate((0.0, 0.0, 1.0)))
        delta = _Rot.from_vectors(self.start_vector, end_vector)
        axis = self.axis_rotation.rotate((0.0, 1.0, 0.0))
        sign = 1 if _v_dot(axis, delta.value()[:3]) > 0 else -1
        self.angle += sign * delta.value()[3]
        self.start_vector = end_vector
        rotation = _Rot.axis_angle(*self.y_axis, min(max(self.angle, low), high))
        if rotation.q != self.rotation.q:
            self.rotation = rotation
            sent.append(("rotation_changed", rotation.value()))
        return sent

    def cylinder_release(self):
        x, y, z, angle = self.rotation.value()
        offset = angle if _v_dot((x, y, z), self.y_axis) > 0 else -angle
        return [("offset", offset)] if self.f["autoOffset"] else []

    # SphereSensor --------------------------------------------------------------------------------------------------

    def _sphere_meet(self, origin, direction):
        """X_ITE's Sphere3.intersectsLine: (nearer, farther) along the ray, or None."""
        b = 2 * _v_dot(origin, direction)
        c = _v_dot(origin, origin) - self.radius ** 2
        core = b * b - 4 * c
        if core < 0:
            return None
        t1, t2 = sorted(((-b + math.sqrt(core)) / 2, (-b - math.sqrt(core)) / 2))
        return _v_add(_v_scale(direction, t1), origin), _v_add(_v_scale(direction, t2), origin)

    def _sphere_track(self, origin, direction, behind):
        met = self._sphere_meet(origin, direction)
        if met is None:
            return None
        enter, exit_ = met
        # X_ITE: (exit nearer than enter) - behind, a number used as a truth value: true when the two differ
        if (_v_norm(_v_sub(origin, exit_)) < _v_norm(_v_sub(origin, enter))) != bool(behind):
            return exit_
        return enter

    def sphere_press(self, ray, hit, eye):
        self.eye_back = _v_unit(eye[1])
        self.z_plane = _Plane((0.0, 0.0, 0.0), self.eye_back)
        self.radius = _v_norm(hit)
        self.behind = self.z_plane.distance(hit) < 0
        self.from_vector = self.start_point = tuple(hit)
        self.start_offset = _Rot.axis_angle(*self.f["offset"])
        self.rotation = self.start_offset
        return [("trackPoint_changed", tuple(hit)), ("rotation_changed", tuple(self.f["offset"]))]

    def sphere_drag(self, ray):
        origin, direction = ray
        track = self._sphere_track(origin, direction, self.behind)
        if track is not None:
            self.z_plane = _Plane(track, self.eye_back)
        else:                                           # off the sphere: X_ITE folds the ray back onto it
            tangent = self.z_plane.meet(origin, direction) or (0.0, 0.0, 0.0)
            track = self._sphere_track(tangent, _v_unit(_v_scale(tangent, -1)), False) or (0.0, 0.0, 0.0)
            a, b, c = (0.0, 0.0, 0.0), track, self.start_point
            tri = _v_unit(_v_cross(_v_sub(c, b), _v_sub(a, b)))
            normal = _v_unit(_v_cross(tri, _v_unit(track)))
            point1 = _v_sub(track, _v_scale(normal, _v_norm(_v_sub(tangent, track))))
            track = self._sphere_track(point1, _v_unit(_v_scale(point1, -1)), False) or track
        rotation = _Rot.from_vectors(self.from_vector, track)
        if self.behind:
            rotation = rotation.inverse()
        self.rotation = self.start_offset.then(rotation)
        return [("trackPoint_changed", track), ("rotation_changed", self.rotation.value())]

    def sphere_release(self):
        return [("offset", self.rotation.value())] if self.f["autoOffset"] else []


class _ProximitySensor(_Machine):
    """X_ITE's ProximitySensor. ``Simulation.viewer`` hands it the viewer's position, orientation and centre of
    rotation in the sensor's own coordinates, once per frame; it is active while the position is inside its box
    (size -1 -1 -1: everywhere; a size of 0 in any axis: a box of no width). Entering sends isActive, enterTime and all
    three; inside, only what changed; leaving sends isActive false and exitTime. A disabled sensor is outside."""

    def setup(self):
        self.active = False
        self.last = {}

    def inside(self, position):
        size, center = self.f["size"], self.f["center"]
        if tuple(size) == (-1.0, -1.0, -1.0):
            return True
        return all(center[i] - size[i] / 2 <= position[i] <= center[i] + size[i] / 2 for i in range(3))

    def sense(self, position, orientation, center_of_rotation, now, test_position=None):
        if self.f.get("enabled", True) and self.inside(position if test_position is None else test_position):
            values = {"position_changed": tuple(position), "orientation_changed": tuple(orientation),
                      "centerOfRotation_changed": tuple(center_of_rotation)}
            if not self.active:
                self.active = True
                sent = [("isActive", True), ("enterTime", now)] + list(values.items())
            else:
                sent = [(name, value) for name, value in values.items() if self.last.get(name) != value]
            self.last.update(values)
            return sent
        if self.active:
            self.active = False
            return [("isActive", False), ("exitTime", now)]
        return []

# KeySensor and StringSensor, from raw keys. X_ITE (Components/KeyDeviceSensor/KeySensor.js, StringSensor.js) reads a
# browser key event's ``which`` (the key code), ``key`` (the character or name), ``charCode`` and ``keyCode``.
_ACTION_KEYS = {**{112 + i: 1 + i for i in range(12)},                  # F1 .. F12 -> 1 .. 12
                36: 13, 35: 14, 33: 15, 34: 16,                          # Home End PageUp PageDown
                38: 17, 40: 18, 37: 19, 39: 20}                          # Up Down Left Right
_MODIFIER_KEYS = {16: "shiftKey", 17: "controlKey", 18: "altKey"}
_NAMED_KEYS = {"Backspace": chr(8), "Delete": chr(127), "Enter": "\n", "Escape": chr(27), "Tab": "\t"}
_QUIET_KEYS = ("AltGraph", "CapsLock", "Insert")


class _KeyDevice(_Machine):
    """What KeySensor and StringSensor share. X_ITE lets one key device sensor be enabled at a time: enabling one
    (at load, or by a ROUTE into ``enabled``) sets every other enabled one to ``enabled`` false, which releases it.
    Fields are set, not sent: a field set twice by one key event sends its last value once."""

    def setup(self):
        self.pending = {}
        self.state = {}
        self.listening = False        # in the browser's set of key device sensors (enabled, and the world has loaded)

    def start(self, now):
        if self.f["enabled"]:
            self._enable()

    def changed(self, name, now):
        if name == "enabled":
            if self.f["enabled"]:
                self._enable()
            else:
                self.listening = False
                self.release()

    def _enable(self):
        self.listening = True
        for other in self.sim.machines.values():
            if other is not self and isinstance(other, _KeyDevice) and other.listening and other.f["enabled"]:
                other.f["enabled"], other.listening = False, False
                other.emit("enabled", False)
                other.release()

    def put(self, name, value):
        """Set an output field (the last value set during one key event is the one sent)."""
        self.state[name] = value
        self.pending.pop(name, None)
        self.pending[name] = value

    def flush(self):
        pending, self.pending = self.pending, {}
        for name, value in pending.items():
            self.emit(name, value)

    def release(self):
        pass

    def key(self, kind, event):
        pass


class _KeySensor(_KeyDevice):
    def setup(self):
        super().setup()
        self.state = {"isActive": False, "shiftKey": False, "controlKey": False, "altKey": False}

    def release(self):
        for name in ("shiftKey", "controlKey", "altKey", "isActive"):
            if self.state[name]:
                self.put(name, False)
        self.flush()

    @staticmethod
    def _named(event):
        """The string X_ITE gives keyPress / keyRelease for a key that is not a modifier or an action key."""
        if not (event.get("charCode") or event.get("keyCode")):
            return None
        key = event.get("key", "")
        if key in _QUIET_KEYS:
            return None
        if key in _NAMED_KEYS:
            return _NAMED_KEYS[key]
        return key if len(key) == 1 else None

    def key(self, kind, event):
        which = event.get("which", 0)
        if kind == "keydown":
            if not self.state["isActive"]:
                self.put("isActive", True)
            if which in _MODIFIER_KEYS:
                self.put(_MODIFIER_KEYS[which], True)
            elif which in _ACTION_KEYS:
                self.put("actionKeyPress", _ACTION_KEYS[which])
            else:
                named = self._named(event)
                if named is not None:
                    self.put("keyPress", named)
        else:
            if which in _MODIFIER_KEYS:
                self.put(_MODIFIER_KEYS[which], False)
            elif which in _ACTION_KEYS:
                self.put("actionKeyRelease", _ACTION_KEYS[which])
            else:
                named = self._named(event)
                if named is not None:
                    self.put("keyRelease", named)
            if self.state["isActive"]:
                self.put("isActive", False)
        self.flush()


class _StringSensor(_KeyDevice):
    def setup(self):
        super().setup()
        self.state = {"isActive": False, "enteredText": ""}

    def key(self, kind, event):
        if kind != "keydown":
            return
        key = event.get("key", "")
        text = self.state["enteredText"]
        if key == "Backspace":
            if self.state["isActive"] and self.f["deletionAllowed"] and text:
                self.put("enteredText", text[:-1])
        elif key == "Enter":
            self.put("finalText", text)
            self.state["enteredText"] = ""            # X_ITE clears the field without sending it
            if self.state["isActive"]:
                self.put("isActive", False)
        elif key == "Escape":
            self.state["enteredText"] = ""
            if self.state["isActive"]:
                self.put("isActive", False)
        elif key == "Tab":
            pass
        elif (event.get("charCode") or event.get("keyCode")) and len(key) == 1:
            if not self.state["isActive"]:
                self.put("isActive", True)
                self.put("enteredText", "")
            self.put("enteredText", self.state["enteredText"] + key)
        self.flush()


class _Sensor(_Machine):
    """A sensor the caller drives: its outputs are posted from outside (``Simulation.post``, ``press``, ``drag``)."""

    def setup(self):
        self.over = self.pressed = False
        self.origin = None


_MACHINES = {
    "TimeSensor": _TimeSensor,
    "ScalarInterpolator": _Interpolator, "PositionInterpolator": _Interpolator, "PositionInterpolator2D": _Interpolator,
    "ColorInterpolator": _ColorInterpolator, "OrientationInterpolator": _OrientationInterpolator,
    "EaseInEaseOut": _EaseInEaseOut, "SplinePositionInterpolator": _SplineInterpolator,
    "SplinePositionInterpolator2D": _SplineInterpolator, "SplineScalarInterpolator": _SplineInterpolator,
    "SquadOrientationInterpolator": _SquadOrientationInterpolator,
    "BooleanSequencer": _Sequencer, "IntegerSequencer": _Sequencer,
    "BooleanFilter": _BooleanFilter, "BooleanToggle": _BooleanToggle, "BooleanTrigger": _BooleanTrigger,
    "IntegerTrigger": _IntegerTrigger, "TimeTrigger": _TimeTrigger,
    "ScalarDamper": _Damper, "PositionDamper": _Damper, "PositionDamper2D": _Damper, "ColorDamper": _ColorDamper,
    "OrientationDamper": _OrientationDamper,
    "ScalarChaser": _Chaser, "PositionChaser": _Chaser, "PositionChaser2D": _Chaser, "ColorChaser": _Chaser,
    "OrientationChaser": _OrientationChaser,
    "TouchSensor": _Sensor, "PlaneSensor": _Sensor, "CylinderSensor": _DragSensor, "SphereSensor": _DragSensor,
    "ProximitySensor": _ProximitySensor, "VisibilitySensor": _Sensor, "KeySensor": _KeySensor, "StringSensor": _StringSensor,
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

    def viewer(self, node_id, position, orientation, now, center_of_rotation=(0.0, 0.0, 0.0), test_position=None):
        """Where the viewer is, for one ProximitySensor, in that sensor's own coordinates: position, orientation
        (axis and angle) and the bound viewpoint's centre of rotation. Call it once per frame for each sensor.
        ``test_position``, when given, is the position the box test uses (X_ITE tests the camera as it was drawn, one
        frame behind a viewpoint that a ROUTE moves, and reports where it is now)."""
        machine = self.machines.get(node_id)
        if machine is None or machine.node_type != "ProximitySensor":
            raise bg.BehaviourError("unknown-def", f"{node_id!r} is not a ProximitySensor in this graph")
        changes = []
        for field_name, value in machine.sense(position, orientation, center_of_rotation, now, test_position):
            changes += self.post(node_id, field_name, value, now)
        return changes

    def key(self, kind, event, now):
        """A key goes down (``kind`` "keydown") or up ("keyup"): ``event`` holds what a browser's key event does,
        ``key``, ``which``, ``charCode`` and ``keyCode``. The one enabled KeySensor or StringSensor takes it (X_ITE: only
        one key device sensor is enabled at a time)."""
        self.now, self._fired = now, set()
        for machine in list(self.machines.values()):
            if isinstance(machine, _KeyDevice) and machine.listening:
                machine.key(kind, event)
        self._drain()
        return self._collect()

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

    def press(self, node_id, now, point=(0.0, 0.0, 0.0), ray=None, eye=None, follow=True):
        """The pointer button goes down on the sensor's shapes. ``point`` is where, in the sensor's own coordinates.
        A CylinderSensor or SphereSensor also needs the pointer's ``ray`` (origin, direction) and the viewer's ``eye``
        (where it is, which way is back), in the same coordinates; without them it sends only isActive."""
        sensor = self._sensor(node_id)
        if not sensor.f.get("enabled", True) or sensor.pressed:
            return []
        changes = self.hover(node_id, True, now)
        sensor.pressed, sensor.origin = True, tuple(point)
        changes += self.post(node_id, "isActive", True, now)
        sensor.geometry = ray is not None and eye is not None
        if sensor.node_type in ("CylinderSensor", "SphereSensor") and sensor.geometry:
            start = sensor.cylinder_press if sensor.node_type == "CylinderSensor" else sensor.sphere_press
            for field_name, value in start(_ray(ray), tuple(point), eye):
                changes += self.post(node_id, field_name, value, now)
            # X_ITE follows the press with one motion along the same ray (recorded: at its next frame, before any move),
            # so a SphereSensor's track point leaves the picked point for the ray's own crossing of the sphere.
            # ``follow=False`` leaves that motion to the caller (the judge sends it at X_ITE's next frame time).
            if follow:
                changes += self.drag(node_id, None, now, ray=ray)
        return changes

    def drag(self, node_id, point, now, ray=None):
        """The pointer moves with the button down. A PlaneSensor sends where its plane was hit, less where it began;
        a CylinderSensor or SphereSensor turns by the pointer's ``ray``, in the sensor's own coordinates."""
        sensor = self._sensor(node_id)
        if not sensor.pressed:
            return []
        changes = []
        if sensor.node_type in ("CylinderSensor", "SphereSensor"):
            if ray is None or not getattr(sensor, "geometry", False):
                return []
            move = sensor.cylinder_drag if sensor.node_type == "CylinderSensor" else sensor.sphere_drag
            for field_name, value in move(_ray(ray)):
                changes += self.post(node_id, field_name, value, now)
            return changes
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
        if sensor.node_type in ("CylinderSensor", "SphereSensor") and getattr(sensor, "geometry", False):
            finish = sensor.cylinder_release if sensor.node_type == "CylinderSensor" else sensor.sphere_release
            for field_name, value in finish():
                sensor.f[field_name] = value
                changes += self.post(node_id, field_name, value, now)
        if sensor.node_type == "PlaneSensor" and sensor.f["autoOffset"] and getattr(sensor, "last", None):
            sensor.f["offset"] = sensor.last
            changes += self.post(node_id, "offset", sensor.last, now)
        return changes

    def click(self, node_id, now, held=0.0):
        """Press and release. ``held`` seconds later for the release."""
        return self.press(node_id, now) + self.release(node_id, now + held)
