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
EaseInEaseOut, the Spline interpolators (scalar, position, 2D position), SquadOrientationInterpolator, the sequencers, the four event utilities and triggers, the dampers and the chasers. Pointing sensors do not sense by
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
