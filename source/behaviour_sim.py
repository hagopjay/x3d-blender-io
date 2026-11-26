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
EaseInEaseOut, the Spline interpolators (scalar, position, 2D position), SquadOrientationInterpolator, PlaneSensor,
CylinderSensor and SphereSensor drags (from the pointer's ray and the viewer, X_ITE's rules), KeySensor and StringSensor from
raw keys (X_ITE's rules, one enabled at a time), the sequencers, the four event utilities and triggers, the dampers and the
chasers (the colour and orientation chasers buffer by buffer as X_ITE's do; the position 2D chaser likewise; the scalar and
position chasers sum eased jumps). Pointing sensors do not sense by
themselves here; the caller says what the pointer did (``hover``, ``press``, ``release``, ``drag``). Whatever is not run
is named in ``Simulation.not_simulated``, never silently skipped.

The rules follow ISO/IEC 19775-1:2023 clauses 8 (Time), 19 (Interpolation), 30 (Event utilities) and 39 (Followers), and
where the standard leaves room they follow X_ITE; ``tools/behaviour_sim_judge.cjs`` compares the two on real files.
"""

from __future__ import annotations

import bisect
import colorsys
import gc
import math
import xml.etree.ElementTree as ET
from collections import deque
from itertools import chain

try:
    from . import behaviour_graph as bg
    from .behaviour_resources import Resources
    from . import behaviour_world as bw
except ImportError:  # imported as a plain module: tests, tools/
    import behaviour_graph as bg
    from behaviour_resources import Resources
    import behaviour_world as bw

# ---------------------------------------------------------------------------------------------------------------
# X3D text <-> Python values
# ---------------------------------------------------------------------------------------------------------------

_SIZES = {"Vec2f": 2, "Vec2d": 2, "Vec3f": 3, "Vec3d": 3, "Vec4f": 4, "Vec4d": 4, "Color": 3, "ColorRGBA": 4,
          "Rotation": 4}


def parse_value(text, x3d_type, strict=False):
    """An X3D lexical value as Python: bool, int, float, str, a tuple (vectors, colours, rotations) or a list (MF).
    Text that is not a value of the type is, as empty text is, the type's zero (empty list for an MF type); with
    ``strict`` it raises ValueError instead (the simulator uses the field's default then)."""
    try:
        return _parse_value(text, x3d_type)
    except (ValueError, OverflowError):
        if strict:
            raise
        return _parse_value("", x3d_type)


def _parse_value(text, x3d_type):
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


def _finite(value):
    """False when a number anywhere in ``value`` is NaN or infinite."""
    kind = type(value)
    if kind is float:
        return value - value == 0.0              # NaN and the infinities are the only floats this is false for
    if kind is _Points:
        return True
    if kind is list and value and type(value[0]) is tuple:       # a list of vectors (a Coordinate's points): in C, not per number
        try:
            return all(map(math.isfinite, chain.from_iterable(value)))
        except (TypeError, OverflowError):                       # something that is not a vector of numbers: the slow way
            pass
    if kind is tuple or kind is list:
        for item in value:
            if type(item) is float:
                if item - item != 0.0:
                    return False
            elif not _finite(item):
                return False
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, (tuple, list)):
        return all(_finite(item) for item in value)
    return True


class _Points(list):
    """A list of vectors a list follower made from floats it knows are all finite: ``size`` numbers each. It is a plain list
    in every other way (equal, printed and sent as one); the two checks every event crosses (finite, fits a field of vectors)
    take its word instead of looking at every number again."""
    __slots__ = ("size",)


def _fits(value, x3d_type):
    """Is ``value`` shaped like an X3D field of ``x3d_type``? (a float is not a Vec3f; a Vec3f has three numbers)"""
    if x3d_type.startswith("MF"):
        if x3d_type == "MFNode":
            return isinstance(value, list)
        return isinstance(value, list) and all(_fits(item, "SF" + x3d_type[2:]) for item in value)
    base = x3d_type[2:]
    if base == "Bool":
        return isinstance(value, bool)
    if base == "String":
        return isinstance(value, str)
    if base == "Int32":
        return isinstance(value, int) and not isinstance(value, bool)
    if base in ("Float", "Double", "Time"):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if base in _SIZES:
        return isinstance(value, tuple) and len(value) == _SIZES[base] and \
            all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in value)
    return True


def _number(value):
    kind = type(value)
    return kind is float or kind is int or (isinstance(value, (int, float)) and not isinstance(value, bool))


_FITTERS = {}
_TUPLE, _FLOAT = frozenset((tuple,)), frozenset((float,))


def _fitter(x3d_type):
    """``_fits`` for one field type, worked out once: every event that crosses a ROUTE is checked with it."""
    found = _FITTERS.get(x3d_type)
    if found is None:
        base = x3d_type[2:]
        if x3d_type.startswith("SF") and base in ("Float", "Double", "Time"):
            found = _number
        elif x3d_type.startswith("SF") and base in _SIZES:
            size = _SIZES[base]

            def found(value, size=size):
                if type(value) is not tuple or len(value) != size:
                    return False
                for component in value:
                    kind = type(component)
                    if kind is not float and kind is not int and not _number(component):
                        return False
                return True
        elif x3d_type.startswith("MF") and base in _SIZES:
            size = _SIZES[base]       # a list of vectors (a Coordinate's points) is checked a point at a time, not a number at a time

            def found(value, size=size, x3d_type=x3d_type, sizes=frozenset((size,))):
                if type(value) is _Points:
                    return value.size == size
                if type(value) is list and set(map(type, value)) <= _TUPLE and set(map(len, value)) <= sizes \
                        and set(map(type, chain.from_iterable(value))) <= _FLOAT:
                    return True
                return _fits(value, x3d_type)           # not the plain case (an int, a subclass, a wrong size): the full test decides
        else:
            def found(value, x3d_type=x3d_type):
                return _fits(value, x3d_type)
        _FITTERS[x3d_type] = found
    return found


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
        if len(a) == 3 and len(b) == 3:         # the common case (positions, colours), without the generator
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)
        return tuple(x + (y - x) * t for x, y in zip(a, b))
    return a + (b - a) * t


def _distance(a, b):
    if isinstance(a, tuple):
        if len(a) == 3 and len(b) == 3:         # sum() of a tuple, not of a generator: the same additions, in order
            return math.sqrt(sum(((a[0] - b[0]) ** 2, (a[1] - b[1]) ** 2, (a[2] - b[2]) ** 2)))
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


def _hsv_of(rgb):
    """``colorsys.rgb_to_hsv``, but a colour whose largest part is 0 (and so with a negative part) is, as in X_ITE's
    Color3.getHSV, a grey of that value: colorsys divides by it."""
    try:
        return colorsys.rgb_to_hsv(*rgb)
    except ZeroDivisionError:
        return (0.0, 0.0, max(rgb))


def hsv_lerp(a, b, t):
    """Colour interpolation as X3D asks for it: through HSV, the short way round the hue circle."""
    ha, sa, va = _hsv_of(a)
    hb, sb, vb = _hsv_of(b)
    if abs(hb - ha) > 0.5:
        if hb > ha:
            ha += 1
        else:
            hb += 1
    try:
        return colorsys.hsv_to_rgb((ha + (hb - ha) * t) % 1.0, sa + (sb - sa) * t, va + (vb - va) * t)
    except (ValueError, OverflowError):      # a colour of 1e308 has no hue: not a number, which never leaves a node (dropped, counted)
        return (math.nan, math.nan, math.nan)


# ---------------------------------------------------------------------------------------------------------------
# One class per kind of node
# ---------------------------------------------------------------------------------------------------------------

class _Machine:
    """A behaviour node while it runs. ``receive`` takes an event at an input, ``tick`` is called once per step."""
    ticks = False
    records = False         # True for a scene node kept in place (AudioClip, ...): what reaches it is also reported as a change

    def __init__(self, sim, node):
        self.sim, self.id, self.node_type = sim, node.id, node.node_type
        self.f = {}
        for name, x3d_type, access, default in bg.field_rows(node.node_type):
            if access in ("inputOutput", "initializeOnly"):
                self.f[name] = self._read(node.fields.get(name, default), x3d_type, default)
        self.setup()

    def _read(self, text, x3d_type, default):
        """A field's value from its text. Text that is not a value of the type, or holds a NaN or an infinity, is
        counted in ``sim.dropped`` and the standard's default is used instead."""
        try:
            value = parse_value(text, x3d_type, strict=True)
            if _finite(value):
                return value
        except (ValueError, OverflowError):
            pass
        self.sim.dropped["bad-field"] = self.sim.dropped.get("bad-field", 0) + 1
        return parse_value(default, x3d_type)

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


def _normal_slerp(a, b, t):
    """X_ITE's NormalInterpolator step: slerp along the great circle between two vectors, never the short way round and
    the vectors are not normalised first (so a vector that is not a unit vector stays as far from the sphere as the
    formula leaves it). Equal vectors stay as they are; a pair whose dot product is outside [-1, 1] gives NaN, which the
    simulation drops as it drops every non-finite value."""
    dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    if dot >= 1:
        return a
    if dot < -1:
        return (math.nan,) * 3
    omega = math.acos(dot)
    sinom = math.sin(omega)
    if sinom == 0:
        return (math.nan,) * 3
    scale0, scale1 = math.sin((1 - t) * omega) / sinom, math.sin(t * omega) / sinom
    return (a[0] * scale0 + b[0] * scale1, a[1] * scale0 + b[1] * scale1, a[2] * scale0 + b[2] * scale1)


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
            span = keys[upper] - keys[lower]                      # never 0 for sorted keys; unsorted ones can make it so
            weight = (value - keys[lower]) / span if span else 0.0
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


class _VectorListInterpolator(_Segmented):
    """CoordinateInterpolator, CoordinateInterpolator2D and NormalInterpolator (X3D 19.4.2, 19.4.3, 19.4.9): ``keyValue``
    holds ``len(key)`` lists of vectors, one list per key, and ``value_changed`` is the list between two keys. As X_ITE
    does it, the list length is ``len(keyValue) // len(key)``: a ``keyValue`` that is not a whole number of lists is read
    as that many whole lists (the rest is ignored), and one shorter than ``key`` gives empty lists. Either is counted in
    ``sim.noted["bad-count"]`` (not ``dropped``: the node still sends what X_ITE sends). No key: no event. A key list of one: that
    list. Past the ends: the first or the last list (``_Segmented``)."""

    def interpolate(self, lower, upper, weight):
        keys, values = self.f.get("key") or [], self.f.get("keyValue") or []
        if len(values) % len(keys):
            self.sim.noted["bad-count"] = self.sim.noted.get("bad-count", 0) + 1
        size = len(values) // len(keys)
        first = lower * size
        second = first + (size if len(keys) > 1 else 0)
        mix = _normal_slerp if self.node_type == "NormalInterpolator" else _lerp
        self.emit("value_changed", [mix(values[first + i], values[second + i], weight) for i in range(size)])


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
            minus, plus = [2 * (keys[1] - keys[0]) / d if d else 0.0], [2 * (keys[last] - keys[last - 1]) / d if d else 0.0]
        else:
            minus, plus = [1.0], [1.0]
        for i in range(1, last):
            d = keys[i + 1] - keys[i - 1]                         # 0 for three equal keys, which X3D allows
            minus.append(2 * (keys[i + 1] - keys[i]) / d if d else 0.0)
            plus.append(2 * (keys[i] - keys[i - 1]) / d if d else 0.0)
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
        self.buffer = [self.f["initialDestination"]] + [self.f["initialValue"]] * min(64, max(1, self.f["order"]))
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


def _rgb_to_hsv(rgb):
    """X_ITE's Color3.getHSV: hue in radians on [0, 2 pi), and a grey has no hue and no saturation."""
    r, g, b = rgb
    top, bottom = max(rgb), min(rgb)
    delta = top - bottom
    if top == 0 or delta == 0:
        return (0.0, 0.0, top)
    hue = (g - b) / delta if r == top else 2 + (b - r) / delta if g == top else 4 + (r - g) / delta
    hue *= math.pi / 3
    return (hue + 2 * math.pi if hue < 0 else hue, delta / top, top)


def _hsv_to_rgb(hsv):
    """X_ITE's Color3.setHSV."""
    h, s, v = hsv
    s, v = max(s, 0.0), max(v, 0.0)
    if s == 0:
        return (v, v, v)
    w = math.degrees(_interval(h, 0, 2 * math.pi)) / 60
    sector = math.floor(w)
    f = w - sector
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    return ((v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q))[int(sector) % 6]


def _hsv_lerp(a, b, t):
    """X_ITE's Color3.lerp on two HSV colours (hue in radians, the short way round the circle)."""
    (ha, sa, va), (hb, sb, vb) = a, b
    if sa == 0:
        ha = hb
    if sb == 0:
        hb = ha
    value, saturation = va + t * (vb - va), sa + t * (sb - sa)
    if abs(hb - ha) <= math.pi:
        return (ha + t * (hb - ha), saturation, value)
    step = (2 * math.pi - abs(hb - ha)) * t
    h = ha - step if ha < hb else ha + step
    h = h + 2 * math.pi if h < 0 else h - 2 * math.pi if h > 2 * math.pi else h
    return (h, saturation, value)


class _BufferChaser(_Machine):
    """X_ITE's chaser, buffer for buffer (X3DChaserNode.js; the scheme of the standard's Followers component). The destination is
    sampled into 60 slots, ``duration / 60`` apart; every frame the slots shift by the whole steps that have passed
    (the newest ones are blended from the destination back to the last sample, so a destination that moved between two
    frames is spread over the gap) and the output is the previous value plus every step between neighbouring slots,
    each answered with the eased ramp for its age. A kind of chaser says how its values blend and add up."""
    ticks = True
    SLOTS, TOLERANCE = 60, 1e-8

    def setup(self):
        self.destination = self.lift(self.f["initialDestination"])
        self.previous = self.lift(self.f["initialValue"])
        self.buffer = [self.destination] + [self.lift(self.f["initialValue"])] * (self.SLOTS - 1)
        self.step_time = self.f["duration"] / self.SLOTS
        self.buffer_end, self.active = 0.0, False

    def start(self, now):
        self.buffer_end = now
        if self.close(self.destination, self.previous):
            self.emit("value_changed", self.lower(self.destination))
        else:
            self._activate(True)

    def _activate(self, on):
        if on != self.active:
            self.active = on
            self.emit("isActive", on)

    def receive(self, name, value, now):
        if name == "set_destination":
            self.destination = self.lift(value)
        elif name == "set_value":
            if not self.active:
                self.buffer_end = now
            self.buffer = [self.lift(value)] * self.SLOTS
            self.previous = self.lift(value)
            self.emit("value_changed", value)
        else:
            return super().receive(name, value, now)
        if not self.active:
            self.buffer_end = now
        self._activate(True)

    def ramp(self, age):
        duration = self.f["duration"]
        return 0.0 if age <= 0 else 1.0 if age >= duration else 0.5 - 0.5 * math.cos(age / duration * math.pi)

    def _shift(self, now):
        """X_ITE's updateBuffer: the slots move on by the steps that have passed; what is left of a step is returned."""
        slots, fraction = self.SLOTS, (now - self.buffer_end) / self.step_time
        if fraction >= 1:
            steps = math.floor(fraction)
            fraction -= steps
            if steps < slots:
                self.previous = self.buffer[slots - steps]
                for i in range(slots - 1, steps - 1, -1):
                    self.buffer[i] = self.buffer[i - steps]
                for i in range(steps):
                    self.buffer[i] = self.blend(self.destination, self.buffer[steps], i / steps)
            else:
                self.previous = self.buffer[0] if steps == slots else self.destination
                self.buffer = [self.destination] * slots
            self.buffer_end += steps * self.step_time
        return fraction

    def tick(self, now, dt):
        if not self.active:
            return
        if not (self.f["duration"] > 0 and self.step_time > 0):    # no duration: the scalar chaser arrives at once (its steps are dropped), and so does this one
            self.buffer, self.previous = [self.destination] * self.SLOTS, self.destination
            self.emit("value_changed", self.lower(self.destination))
            self._activate(False)
            return
        if not (now - self.buffer_end) / self.step_time < 1e15:       # a clock that jumped, to infinity or NaN: as the list chasers do
            self.buffer, self.previous, self.buffer_end = [self.destination] * self.SLOTS, self.destination, now
        slots = self.SLOTS
        fraction = self._shift(now)
        output = self.blend(self.previous, self.buffer[slots - 1], self.ramp((slots - 1 + fraction) * self.step_time))
        for i in range(slots - 2, -1, -1):
            output = self.add(output, self.buffer[i], self.buffer[i + 1], self.ramp((i + fraction) * self.step_time))
        self.emit("value_changed", self.lower(output))
        if self.close(output, self.destination):
            self._activate(False)


class _ColorChaser(_BufferChaser):
    """A ColorChaser follows in HSV, hue in radians, as X_ITE does."""
    lift, lower, blend = staticmethod(_rgb_to_hsv), staticmethod(_hsv_to_rgb), staticmethod(_hsv_lerp)

    @staticmethod
    def add(output, value1, value2, t):
        return _hsv_lerp(output, tuple(o + a - b for o, a, b in zip(output, value1, value2)), t)

    @classmethod
    def close(cls, a, b):
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b))) < cls.TOLERANCE


class _OrientationChaser(_BufferChaser):
    """An OrientationChaser follows with quaternions: slerp for the blend, rotation steps composed as X_ITE does."""

    @staticmethod
    def lift(rotation):
        return _Rot.axis_angle(*rotation).q

    @staticmethod
    def lower(q):
        return _Rot(q).value()

    @staticmethod
    def blend(source, destination, t):
        return _q_slerp(source, destination, t)

    @staticmethod
    def add(output, value1, value2, t):
        conjugate = (-value2[0], -value2[1], -value2[2], value2[3])
        step = _q_normalize(_q_mul(_q_normalize(_q_mul(value1, conjugate)), output))     # multRight, then multLeft
        return _q_slerp(output, step, t)

    @classmethod
    def close(cls, a, b):
        x, y, z, w = _q_normalize(_q_mul(b, (-a[0], -a[1], -a[2], a[3])))
        return abs(2 * math.acos(max(-1.0, min(1.0, w)))) < cls.TOLERANCE


class _VectorChaser(_BufferChaser):
    """PositionChaser2D: X_ITE's buffer chaser on plain vectors, a straight blend, each step between slots added as X_ITE's
    vectors add."""
    lift = lower = staticmethod(tuple)

    @staticmethod
    def blend(a, b, t):
        return tuple(x + (y - x) * t for x, y in zip(a, b))

    @staticmethod
    def add(output, value1, value2, t):
        return tuple(o + (a - b) * t for o, a, b in zip(output, value1, value2))

    @classmethod
    def close(cls, a, b):
        return _distance(a, b) < cls.TOLERANCE

# -- followers of lists: CoordinateChaser, CoordinateDamper, TexCoordChaser2D, TexCoordDamper2D ---------------------
# X_ITE lifts its chaser and damper over a list of vectors (X3DArrayFollowerTemplate): the same machines, with the lists
# kept as long as the destination, a point that one list lacks taken as the zero vector, and "at rest" meaning the same
# length and every point within tolerance. Inside, a list of points is one flat list of floats (x0 y0 z0 x1 ...): the
# blends and sums are then one pass over numbers, not a tuple made per point. A list is never changed in place, so the
# slots of a chaser and the buffers of a damper share lists freely; the lists that leave a node are lists of tuples.

_MAX_POINTS = 10_000      # a list longer than this is cut to it (counted in ``sim.noted["capped"]``): memory is points x slots


def _blend(source, target, t):
    """X_ITE's array ``interpolate`` on flat lists: as long as ``source``; what ``target`` lacks is zero."""
    spare = len(source) - len(target)
    if spare > 0:
        target = target + [0.0] * spare
    return [x + (y - x) * t for x, y in zip(source, target)]


def _gap(a, b, size):
    """The largest distance between matching points, or infinity when the lists are not as long as each other."""
    if len(a) != len(b):
        return math.inf
    if not a:
        return 0.0
    squares = [(d := x - y) * d for x, y in zip(a, b)]
    return math.sqrt(max(map(sum, zip(*[squares[i::size] for i in range(size)]))))


class _ListMixin:
    """What both kinds of list follower share: the size of their vectors, how a list is kept inside, and the cap."""
    size = 3
    shown, whole = 0, False       # points in the last value_changed; True while a value is sent whole (start, set_value)

    def emit(self, name, value):
        # X_ITE 16.8.1: a list a follower works out is written into value_changed point by point, then cut to its length,
        # so an empty list after an empty list is no event at all; a list it is given (set_value, the initial value) is
        # assigned whole and is an event even when empty (tools/behaviour_sim_judge.cjs on a world of its own)
        if name == "value_changed":
            if not value and not self.shown and not self.whole:
                return
            self.shown = len(value)
        super().emit(name, value)

    def flat(self, points):
        """``points`` (a list of vectors) as a flat list of floats, cut to the cap."""
        if len(points) > _MAX_POINTS:
            self.sim.noted["capped"] = self.sim.noted.get("capped", 0) + 1
            points = points[:_MAX_POINTS]
        flat = list(chain.from_iterable(points))
        if len(flat) != self.size * len(points):
            raise ValueError("a list of vectors of another size")
        return flat

    def points(self, flat, floats=False):
        """A flat list as the list of tuples a node sends. ``floats``: the caller knows every number is a float (it came out
        of a blend); when they are also all finite (one sum says so: an infinity or a NaN makes it one, an overflow of
        finite numbers only makes it a slow check) the list is a ``_Points``."""
        size = self.size
        found = list(zip(flat[0::3], flat[1::3], flat[2::3])) if size == 3 else \
            list(zip(flat[0::2], flat[1::2])) if size == 2 else list(zip(*[flat[i::size] for i in range(size)]))
        if floats and math.isfinite(sum(flat)):
            found = _Points(found)
            found.size = size
        return found

    def fitted(self, flat, count):
        """``flat`` made ``count`` points long: cut, or padded with zero vectors (what X_ITE does to every buffer when a
        destination of another length arrives)."""
        length = count * self.size
        if len(flat) == length:
            return flat
        if len(flat) > length:
            return flat[:length]
        return flat + [0.0] * (length - len(flat))


class _ListChaser(_ListMixin, _BufferChaser):
    """CoordinateChaser and TexCoordChaser2D: X_ITE's buffer chaser on lists of vectors. A destination of another length
    first makes every one of the 60 slots that long (cut, or padded with zero vectors); the output is as long as the
    last value until the slots have shifted once, so a list of another length takes a frame or so to arrive."""

    def lift(self, value):
        return self.flat(value)

    def lower(self, flat):
        return self.points(flat)

    def blend(self, source, target, t):
        return _blend(source, target, t)

    def add(self, output, value1, value2, t):
        spare1, spare2 = len(output) - len(value1), len(output) - len(value2)
        if spare1 > 0:
            value1 = value1 + [0.0] * spare1
        if spare2 > 0:
            value2 = value2 + [0.0] * spare2
        return [o + (a - b) * t for o, a, b in zip(output, value1, value2)]

    def close(self, a, b):
        return _gap(a, b, self.size) < self.TOLERANCE

    def tick(self, now, dt):
        if self.f["duration"] > 0:
            if self.active and not (now - self.buffer_end) / self.step_time < 1e15:       # a clock that jumped, to infinity or NaN
                self.buffer, self.previous, self.buffer_end = [self.destination] * self.SLOTS, self.destination, now
            return super().tick(now, dt)
        if self.active:                    # no duration (X_ITE's step time is then 0 and its output NaN): the chaser jumps
            self.buffer, self.previous = [self.destination] * self.SLOTS, self.destination
            self.emit("value_changed", self.lower(self.destination))
            self._activate(False)

    def start(self, now):
        self.whole = True
        super().start(now)
        self.whole = False

    def receive(self, name, value, now):
        if name == "set_destination":
            count = min(len(value), _MAX_POINTS)
            fitted = {}
            for i, slot in enumerate(self.buffer):
                key = id(slot)
                if key not in fitted:
                    fitted[key] = self.fitted(slot, count)
                self.buffer[i] = fitted[key]
        elif name == "set_value":
            self.whole = True
        super().receive(name, value, now)
        self.whole = False


class _ListDamper(_ListMixin, _Machine):
    """CoordinateDamper and TexCoordDamper2D: X_ITE's damper on lists. Every ``set_destination`` or ``set_value`` wakes
    it (the lists need not differ); it is at rest when its last stage is as long as the destination and every point is
    within tolerance. Buffers are 1 + order (clamped to 0 .. 5) lists; the first holds the destination."""
    ticks = True

    def setup(self):
        order = min(5, max(0, self.f["order"]))
        self.buffer = [self.flat(self.f["initialDestination"])] + [self.flat(self.f["initialValue"])] * order
        self.active = False

    def tolerance(self):
        return self.f["tolerance"] if self.f["tolerance"] >= 0 else 1e-4

    def start(self, now):
        if _gap(self.flat(self.f["initialDestination"]), self.flat(self.f["initialValue"]), self.size) < self.tolerance():
            self.whole = True
            self.emit("value_changed", self.points(self.buffer[0]))
            self.whole = False
        else:
            self._wake()

    def _wake(self):
        if not self.active:
            self.active = True
            self.emit("isActive", True)

    def receive(self, name, value, now):
        if name == "set_destination":
            flat = self.flat(value)
            count, fitted = len(flat) // self.size, {}
            for i in range(1, len(self.buffer)):
                key = id(self.buffer[i])
                if key not in fitted:
                    fitted[key] = self.fitted(self.buffer[i], count)
                self.buffer[i] = fitted[key]
            self.buffer[0] = flat
            self._wake()
        elif name == "set_value":
            flat = self.flat(value)
            self.buffer[1:] = [flat] * (len(self.buffer) - 1)
            self.whole = True
            self.emit("value_changed", self.points(flat))
            self.whole = False
            self._wake()
        else:
            super().receive(name, value, now)

    def tick(self, now, dt):
        if not self.active:
            return
        buffer, tau = self.buffer, self.f["tau"]
        last = len(buffer) - 1
        if tau > 0:
            alpha = math.exp(-dt / tau)
            for i in range(last):
                buffer[i + 1] = _blend(buffer[i], buffer[i + 1], alpha)
            self.emit("value_changed", self.points(buffer[last], floats=True))
            if not _gap(buffer[last], buffer[0], self.size) < self.tolerance():
                return
        else:
            self.emit("value_changed", self.points(buffer[0]))
            last = 0
        buffer[1:] = [buffer[last]] * (len(buffer) - 1)
        self.active = False
        self.emit("isActive", False)


class _CoordinateChaser(_ListChaser):
    size = 3


class _TexCoordChaser2D(_ListChaser):
    size = 2


class _CoordinateDamper(_ListDamper):
    size = 3


class _TexCoordDamper2D(_ListDamper):
    size = 2


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
    try:
        if value >= high:
            return math.fmod(value - low, high - low) + low
        if value < low:
            return math.fmod(value - high, high - low) + high
    except ValueError:                 # fmod of an infinity: JavaScript's answer is NaN
        return math.nan
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
        gap = self.sx_plane.distance(z_point)
        distance = gap / self.radius if self.radius else math.nan if not gap or gap != gap else math.copysign(math.inf, gap)   # JavaScript's division
        half = (distance + 1) / 2
        section = math.floor(half) if math.isfinite(half) else math.nan     # JavaScript's Math.floor: a hit on the axis (radius 0) is NaN
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
        return bw.box_contains(self.f["center"], self.f["size"], position)

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

class _WorldSensor(_Machine):
    """An environmental sensor that reads the ``World`` once per step, after the step's events have settled. Its inputs
    are the world and its own fields; with no ``World`` (or no frame for it) it sends nothing and says so in
    ``Simulation.noted``."""
    senses = True

    def setup(self):
        self.active = False
        self._warned = False

    def enter(self, now):
        self.active = True
        self.emit("isActive", True)
        self.emit("enterTime", now)

    def leave(self, now):
        self.active = False
        self.emit("isActive", False)
        self.emit("exitTime", now)

    def blind(self, why):
        """Nothing to sense with: leave an active sensor, count the reason once."""
        if not self._warned:
            self._warned = True
            self.sim.noted[why] = self.sim.noted.get(why, 0) + 1

    def update(self, now):
        pass

    def traverse(self):
        pass


class _TransformSensor(_WorldSensor):
    """X_ITE's TransformSensor (Components/EnvironmentalSensor/TransformSensor.js). Once per frame, after the events,
    it takes the target's world matrix relative to the sensor's own coordinates: the target is in when that matrix's
    origin (the Transform's own position, centre and turn included) is in the box (size -1 -1 -1: always; a size of 0
    in all three: the sensor is off; no target: off). Entering sends isActive, enterTime, position_changed and
    orientation_changed; while inside, position_changed and orientation_changed each time they differ (exactly);
    leaving sends isActive false and exitTime. The orientation is the rotation of the matrix with scale and shear taken
    out. A disabled sensor is outside."""

    def update(self, now):
        world = self.sim.world
        if world is None:
            return self.blind("no-world")
        target = world.sensor_target.get(self.id)
        wanted = self.f.get("enabled", True) and tuple(self.f["size"]) != (0.0, 0.0, 0.0)
        relative = origin = None
        if wanted and target is not None and self.id in world.sensors:
            target_matrix = world.target_matrix(target)
            inverse = world.sensor_inverse(self.id) if target_matrix is not None else None
            if inverse is not None:
                # the target's origin in the sensor's coordinates; the whole matrix is only needed to say how it is turned
                origin = bw.m_point(inverse, (target_matrix[3], target_matrix[7], target_matrix[11]))
                relative = (inverse, target_matrix)
            else:
                self.blind("singular-frame")
        elif wanted:
            self.blind("no-target" if self.id in world.sensors else "no-frame")
        if relative is not None and bw.box_contains(self.f["center"], self.f["size"], origin):
            position, orientation = origin, bw.rotation_of(bw.m_mul(*relative))
            if self.active:
                for name, value in (("position_changed", position), ("orientation_changed", orientation)):
                    if self.f.get(name) != value:
                        self.f[name] = value
                        self.emit(name, value)
            else:
                self.enter(now)
                self.f["position_changed"], self.f["orientation_changed"] = position, orientation
                self.emit("position_changed", position)
                self.emit("orientation_changed", orientation)
        elif self.active:
            self.leave(now)


class _VisibilitySensor(_WorldSensor):
    """X_ITE's VisibilitySensor (Components/EnvironmentalSensor/VisibilitySensor.js). A frame draws the scene and notes
    whether the box meets the view volume (``traverse``); the next frame's sensor events send it (``update``), so the
    sensor lags the picture by one frame and reports the next frame's time. The box test is X_ITE's separating-axis test
    against the view frustum, not a visibility test: a box behind another shape, or fully behind the sensor's own parent
    when that is hidden, is "visible" if the frustum meets it. Size -1 -1 -1 is always visible; a size of 0 0 0 is a point,
    and X_ITE reports it visible too when the frustum contains it. A disabled sensor is outside, and is not drawn: what
    the last drawing found stays, so enabling a sensor sends isActive true at once if it was visible when it was
    switched off, whether or not it is now."""

    def setup(self):
        super().setup()
        self.visible = False

    def update(self, now):
        if not self.f.get("enabled", True):
            if self.active:
                self.leave(now)
            return                       # ``visible`` stays as the last drawing left it: X_ITE enters on it at once
        if self.visible:
            if not self.active:
                self.enter(now)
            self.visible = False
        elif self.active:
            self.leave(now)

    def traverse(self):
        world = self.sim.world
        if world is None:
            return self.blind("no-world")
        if not self.f.get("enabled", True):
            return
        if self.id not in world.sensors:
            return self.blind("no-frame")
        self.visible = bool(world.sees_box(self.id, self.f["center"], self.f["size"]))


class _CollisionGroup:
    """A Collision node of the scene (a TARGET in the graph: the node stays where the scene has it). It is active
    while the viewer is touching one of its shapes (see ``World.collision_hits``); going active sends isActive and
    collideTime. Its ``enabled`` comes through ``World.apply``."""
    senses = True

    def __init__(self, sim, node_id):
        self.sim, self.id, self.active = sim, node_id, False

    def update(self, now, hits):
        touching = self.id in hits
        if touching != self.active:
            self.active = touching
            self.sim._emit(self.id, "isActive", touching)
            if touching:
                self.sim._emit(self.id, "collideTime", now)


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


class _PlaneSensor(_Sensor):
    """A PlaneSensor, from the pointer's ray (X_ITE's rules, PlaneSensor.js). With both limits free on one axis
    (``minPosition.x == maxPosition.x`` or the same for y) X_ITE does not use a plane: it slides along that axis as a
    line, and the point on the line is the one whose picture on the screen is nearest the pointer. That needs the
    camera: ``screen`` is (right, up), the camera's own x and y axes in the sensor's coordinates (the Transforms above
    the sensor may move and turn it but not scale it), and the ray's origin is the eye. The pixel size cancels out. With
    both axes limited, or none, the pointer's ray meets the plane through the press point, square to the sensor's z."""

    def setup(self):
        super().setup()
        self.last = None
        self.start_point = None            # where the press began: None until a press whose ray met the plane or the line
        self.sent = {"trackPoint_changed": (0.0, 0.0, 0.0), "translation_changed": (0.0, 0.0, 0.0)}

    def _line_point(self, ray, screen, point, direction):
        """The point of the line (``point``, unit ``direction``) nearest the pointer's picture of it, or None when the
        ray and the line are parallel: X_ITE's getLineTrackPoint."""
        origin, ray_direction = ray
        if screen is None:                     # no camera: the point of the line nearest the ray itself
            t = _v_dot(direction, ray_direction)
            if abs(t) >= 1:
                return None
            u = _v_sub(origin, point)
            t = (_v_dot(u, direction) - t * _v_dot(u, ray_direction)) / (1 - t * t)
            return _v_add(_v_scale(direction, t), point)
        right, up = screen
        back = _v_cross(right, up)

        def picture(p):                                    # where the camera sees it, in units of the pixel size
            v = _v_sub(p, origin)
            depth = -_v_dot(v, back)
            return (_v_dot(v, right) / depth, _v_dot(v, up) / depth)

        pointer = picture(_v_add(origin, ray_direction))
        near, far = picture(point), picture(_v_add(_v_scale(direction, 1e9), point))
        way = (far[0] - near[0], far[1] - near[1])
        length = math.hypot(*way)
        way = (way[0] / length, way[1] / length)
        along = (pointer[0] - near[0]) * way[0] + (pointer[1] - near[1]) * way[1]
        foot = (near[0] + way[0] * along, near[1] + way[1] * along)
        through = _v_unit(_v_sub(_v_add(_v_scale(right, foot[0]), _v_scale(up, foot[1])), back))
        t = _v_dot(direction, through)
        if abs(t) >= 1:
            return None
        u = _v_sub(origin, point)
        t = (_v_dot(u, direction) - t * _v_dot(u, through)) / (1 - t * t)
        return _v_add(_v_scale(direction, t), point)

    def _line_direction(self):
        low, high = self.f["minPosition"], self.f["maxPosition"]
        if low[0] == high[0]:
            along = (0.0, abs(high[1] - low[1]), 0.0)
        elif low[1] == high[1]:
            along = (abs(high[0] - low[0]), 0.0, 0.0)
        else:
            return None
        return _v_unit(_Rot.axis_angle(*self.f["axisRotation"]).rotate(along))

    def _send(self, name, value, always=False):
        if always or value != self.sent[name]:
            self.sent[name] = value
            return [(name, value)]
        return []

    def plane_press(self, ray, hit, screen):
        origin, direction = ray
        self.start_point = None
        self.hit, self.line = tuple(hit), self._line_direction()
        self.screen = screen
        if self.line is None:
            self.plane = _Plane(hit, _Rot.axis_angle(*self.f["axisRotation"]).rotate((0.0, 0.0, 1.0)))
            start = self.plane.meet(origin, direction)
            track = start
        else:
            start = self._line_point(ray, screen, hit, self.line)
            track = self._line_point(ray, screen, self.line, self.line) if start is not None else None
            track = start if track is None else track
        if start is None:
            return []
        self.start_point, self.start_offset = start, self.f["offset"]
        self.last = self.f["offset"]
        return self._send("trackPoint_changed", track, True) + self._send("translation_changed", self.f["offset"], True)

    def plane_drag(self, ray, always=False):
        if self.start_point is None:       # the press never met the plane (its ray ran along it): nothing to drag from
            return []
        origin, direction = ray
        if self.line is None:
            end = track = self.plane.meet(origin, direction)
        else:
            end = self._line_point(ray, self.screen, self.hit, self.line)
            track = self._line_point(ray, self.screen, (0.0, 0.0, 0.0), self.line) if end is not None else None
            track = end if track is None else track
        if end is None:
            return self._send("trackPoint_changed", self.sent["trackPoint_changed"], True) + \
                self._send("translation_changed", self.sent["translation_changed"], True)
        moved = _Rot.axis_angle(*self.f["axisRotation"]).inverse().rotate(
            _v_sub(_v_add(end, self.start_offset), self.start_point))
        low, high = self.f["minPosition"], self.f["maxPosition"]
        moved = tuple(min(max(moved[i], low[i]), high[i]) if i < 2 and not low[i] > high[i] else moved[i]
                      for i in range(3))
        self.last = moved
        # X_ITE works the translation out as (end + offset) - start. On the motion that follows a press, end and start are
        # the same point, so the result is the offset up to the rounding of that sum: X_ITE's exact-equality guard lets
        # it through whenever the offset is not zero (and the track point, found a different way, always differs in the
        # last bits). Both are sent on that first motion; later motions send only what changed.
        return self._send("trackPoint_changed", track, always) + \
            self._send("translation_changed", moved, always and any(self.start_offset))


# ---------------------------------------------------------------------------------------------------------------
# Hosted nodes (class E): code and engines the graph cannot run. Their ports are typed from the node's own declarations;
# what they send comes from a Python handler registered by name, or from the caller's stimulus.
# ---------------------------------------------------------------------------------------------------------------

CALLED_AT = "@called-at"        # a handler's way to ask for a later call (see _Script), and the field that call is made with
INITIALIZE = "initialize"       # the field of the one call a handler gets when the simulation starts (a Script's initialize())


def _declared_values(node):
    """{field name: value} of the <field value="..."> a Script's content gives its declared fields (a field with no value
    is the zero of its type). The source text is never looked at except as markup, and never run."""
    given = {}
    if node.content and "<field" in node.content:
        try:
            root = ET.fromstring(f"<c>{node.content}</c>")
        except ET.ParseError:
            root = None
        for element in root if root is not None else ():
            if element.tag.rpartition("}")[2] == "field" and element.get("value") is not None:
                given[element.get("name")] = element.get("value")
    values = {}
    for name, kind, access in node.declared:
        if kind in bg.NODE_FIELD_TYPES or access == "inputOnly":
            continue
        try:
            value = parse_value(given.get(name), kind, strict=True)
        except (ValueError, OverflowError):
            value = parse_value("", kind)
        values[name] = value if _finite(value) else parse_value("", kind)
    return values


def _as_field_value(value, kind):
    """What a handler returned as a value of field type ``kind``, or None when it is not one. Follows X_ITE (16.8.1): an
    integer field takes a number's whole part (7.9 is 7); a vector may be a list."""
    if kind == "SFInt32" and isinstance(value, float) and math.isfinite(value) and abs(value) < 2 ** 31:
        return int(value)
    if isinstance(value, list) and not kind.startswith("MF") and kind[2:] in _SIZES:
        value = tuple(value)
    return value if _fits(value, kind) else None


class _Script(_Machine):
    """A Script. Its ``<field>`` declarations are its ports, typed. ``Simulation.host(def_name, handler)`` gives it a Python
    handler, ``handler(field, value, time, state) -> [(field, value), ...]``: it is called for every event that reaches an
    inputOnly or inputOutput port (``field`` is the port's name, as a Script's function of that name is) and sends the
    returned values from its outputOnly or inputOutput ports in the same cascade. ``state`` is a dict that lives as long as
    the Script and starts with the value of every declared field that holds one (what the script's variables would be).
    The handler is also called once as ``handler("initialize", None, time, state)`` when the simulation starts (a Script's
    initialize()). It may ask to be called again at a later time by returning ``(CALLED_AT, time)``: at the first step at
    or after that time it is called as ``handler(CALLED_AT, time, now, state)`` (a Script's timer). Like X_ITE's, a
    call sends one event per field however often it assigned it (the last value, in the order the fields were first
    assigned). Events into a Script that has no handler are counted in ``Simulation.noted["hosted-not-run"]`` and
    kept in ``received``. The Script's own text (JavaScript) is never run."""
    ticks = True

    def setup(self):
        node = self.sim.graph.nodes[self.id]
        self.ports = {name: (kind, access) for name, kind, access in node.declared}
        self.state = _declared_values(node)
        self.handler, self.wake = None, None
        self.received = deque(maxlen=200)

    def host(self, handler):
        self.handler, self.wake = handler, None

    def start(self, now):
        if self.handler is not None:
            self._call(INITIALIZE, None, now)

    def receive(self, name, value, now):
        port = self.ports.get(name)
        if port is None:
            return super().receive(name, value, now)
        kind, access = port
        if access == "inputOutput":
            self.state[name] = value
            self.emit(name, value)
        if self.handler is None:
            self.sim.noted["hosted-not-run"] = self.sim.noted.get("hosted-not-run", 0) + 1
            self.received.append((now, name, value))
        else:
            self._call(name, value, now)

    def tick(self, now, dt):
        if self.wake is not None and now >= self.wake and self.handler is not None:
            asked, self.wake = self.wake, None
            self._call(CALLED_AT, asked, now)

    def _call(self, field, value, now):
        sent = self.handler(field, value, now, self.state)
        sim, collected = self.sim, {}
        try:
            items = list(sent or ())
        except TypeError:                          # a handler that answers with something that is not a list of pairs
            sim.dropped["mismatch"] = sim.dropped.get("mismatch", 0) + 1
            items = ()
        for item in items:
            try:
                name, out = item
            except (TypeError, ValueError):
                sim.dropped["mismatch"] = sim.dropped.get("mismatch", 0) + 1
                continue
            if name == CALLED_AT:
                if isinstance(out, (int, float)) and not isinstance(out, bool) and math.isfinite(out):
                    self.wake = out
                continue
            port = self.ports.get(name)
            if port is None or port[1] not in ("outputOnly", "inputOutput"):
                sim.dropped["mismatch"] = sim.dropped.get("mismatch", 0) + 1       # not an output the Script declares
                continue
            fitted = _as_field_value(out, port[0])
            if fitted is None:
                sim.dropped["mismatch"] = sim.dropped.get("mismatch", 0) + 1
            else:
                collected[name] = fitted           # a field assigned twice is sent once, in the place of its first assignment
        for name, out in collected.items():
            if _finite(out):
                self.state[name] = out
                sim.hosted_outputs.append((now, self.id, name, out))
            self.emit(name, out)


class _CollisionSensor(_Machine):
    """A CollisionSensor. There is no physics engine here: ``Simulation.contact(node_id, active, contacts, intersections)``
    says what the engine (X_ITE's, Blender's, or a recording) found. ``isActive`` follows ``active``; ``contacts`` and
    ``intersections`` (names of the nodes involved) are sent while it is active. A disabled sensor sends nothing."""

    def setup(self):
        self.active, self.fed = False, False

    def contact(self, active, contacts, intersections, now):
        self.fed = True
        if not self.f.get("enabled", True):
            return
        if active and contacts:
            self.emit("contacts", list(contacts))
        if active and intersections:
            self.emit("intersections", list(intersections))
        if active != self.active:
            self.active = active
            self.emit("isActive", active)

    def changed(self, name, now):
        if name == "enabled" and not self.f["enabled"] and self.active:
            self.active = False                  # a sensor that is switched off while touching ends its contact
            self.emit("isActive", False)


_MACHINES = {
    "TimeSensor": _TimeSensor,
    "ScalarInterpolator": _Interpolator, "PositionInterpolator": _Interpolator, "PositionInterpolator2D": _Interpolator,
    "ColorInterpolator": _ColorInterpolator, "OrientationInterpolator": _OrientationInterpolator,
    "EaseInEaseOut": _EaseInEaseOut, "SplinePositionInterpolator": _SplineInterpolator,
    "SplinePositionInterpolator2D": _SplineInterpolator, "SplineScalarInterpolator": _SplineInterpolator,
    "SquadOrientationInterpolator": _SquadOrientationInterpolator,
    "CoordinateInterpolator": _VectorListInterpolator, "CoordinateInterpolator2D": _VectorListInterpolator,
    "NormalInterpolator": _VectorListInterpolator,
    "BooleanSequencer": _Sequencer, "IntegerSequencer": _Sequencer,
    "BooleanFilter": _BooleanFilter, "BooleanToggle": _BooleanToggle, "BooleanTrigger": _BooleanTrigger,
    "IntegerTrigger": _IntegerTrigger, "TimeTrigger": _TimeTrigger,
    "ScalarDamper": _Damper, "PositionDamper": _Damper, "PositionDamper2D": _Damper, "ColorDamper": _ColorDamper,
    "OrientationDamper": _OrientationDamper,
    "ScalarChaser": _Chaser, "PositionChaser": _Chaser, "PositionChaser2D": _VectorChaser, "ColorChaser": _ColorChaser,
    "OrientationChaser": _OrientationChaser,
    "CoordinateChaser": _CoordinateChaser, "CoordinateDamper": _CoordinateDamper,
    "TexCoordChaser2D": _TexCoordChaser2D, "TexCoordDamper2D": _TexCoordDamper2D,
    "TouchSensor": _Sensor, "PlaneSensor": _PlaneSensor, "CylinderSensor": _DragSensor, "SphereSensor": _DragSensor,
    "ProximitySensor": _ProximitySensor, "VisibilitySensor": _VisibilitySensor,
    "TransformSensor": _TransformSensor, "KeySensor": _KeySensor, "StringSensor": _StringSensor,
    "Script": _Script, "CollisionSensor": _CollisionSensor,
}

# sensors the caller can drive with press / release / drag; the others only through post()
POINTING = ("TouchSensor", "PlaneSensor", "CylinderSensor", "SphereSensor")
DRAGGED = POINTING[1:]            # the ones a drag moves

# Class D (what waits on the outside: LoadSensor, AudioClip, MovieTexture) lives in behaviour_media, which needs _Machine
# from here; it registers its machines now that everything above exists. AudioClip and MovieTexture are scene nodes kept in
# place (targets in the graph), so they run as ``_SCENE_MACHINES``; ImageTexture and Inline run too, as plain load states
# a LoadSensor can watch, and are not event nodes.
try:
    from . import behaviour_media as _media
except ImportError:  # imported as a plain module: tests, tools/
    import behaviour_media as _media
_MACHINES.update(_media.MACHINES)
try:
    from . import behaviour_pick as _pick
except ImportError:  # imported as a plain module: tests, tools/
    import behaviour_pick as _pick
_MACHINES.update(_pick.machines(_Machine, _WorldSensor))
_SCENE_MACHINES = _media.SCENE_MACHINES
# Class C (another coordinate system: GeoPositionInterpolator, GeoProximitySensor, GeoTouchSensor) lives in behaviour_geo_machines
try:
    from . import behaviour_geo_machines as _geo
except ImportError:  # imported as a plain module: tests, tools/
    import behaviour_geo_machines as _geo
_MACHINES.update(_geo.MACHINES)
PROXIMITY = _geo.PROXIMITY           # the sensors Simulation.viewer and Simulation.view feed
GEO_POINTING = _geo.TOUCHING         # pointing sensors that are not in POINTING (the Player and the fuzzer feed POINTING only)
SIMULATED = tuple(sorted({*_MACHINES, "AudioClip", "MovieTexture"}))
# Event nodes that are scene content (catalogue IN_PLACE: the graph names them, the scene keeps them) and that the
# simulation runs anyway, from the World. They are not machines and not in SIMULATED.
SIMULATED_IN_PLACE = ("Collision",)


class Simulation:
    """A behaviour graph, running. See the module text for the short tour."""

    def __init__(self, graph, *, log_size=400, resources=None, world=None):
        self.graph = graph
        self.world = world               # behaviour_world.World, or None: the sensors that need one then send nothing
        # What hostile input cost: ``dropped`` counts values that were never delivered ("non-finite": a NaN or an
        # infinity; "mismatch": a value whose shape does not fit the field it was routed to; "bad-field": field text
        # that is not a value, replaced by the default; "bad-time": a time that is not a number, ignored) and
        # ``faults`` names each node that raised and was left out of that event (none, for a legal graph).
        self.dropped, self.faults = {}, []
        self.noted = {}                  # oddities that lose nothing: "bad-count" (a keyValue that is not a whole number of lists)
        self.hosted_outputs = deque(maxlen=log_size)    # (time, Script id, field, value) of what Python handlers sent
        self.machines, self.not_simulated = {}, []
        # what the outside world does when something asks to load (see behaviour_resources): a table, or plain data for one
        self.resources = resources if isinstance(resources, Resources) else Resources(resources)
        if self.resources.rejected:
            self.dropped["bad-resource"] = len(self.resources.rejected)
        for node in graph.nodes.values():
            if (node.role == bg.BEHAVIOUR and node.node_type in _MACHINES) or \
                    (node.role == bg.TARGET and node.node_type in _SCENE_MACHINES):
                try:
                    self.machines[node.id] = (_MACHINES if node.role == bg.BEHAVIOUR else _SCENE_MACHINES)[node.node_type](self, node)
                except Exception as error:      # a node that cannot be built is reported, not run
                    self._fault(node.id, "setup", error)
                    self.not_simulated.append(f"{node.node_type} {node.id}")
            elif node.role != bg.TARGET:
                self.not_simulated.append(f"{node.node_type} {node.id}")
        self._ticking = [machine for machine in self.machines.values() if machine.ticks]    # fixed once built
        self._sensing = [machine for machine in self.machines.values() if getattr(machine, "senses", False)]
        self._collisions = [_CollisionGroup(self, node.id) for node in graph.nodes.values()
                            if node.role == bg.TARGET and node.node_type == "Collision"
                            and world is not None and node.id in world.collisions]
        self._seeing = [machine for machine in self._sensing if isinstance(machine, _VisibilitySensor)]
        self._routes = {}
        for route in graph.routes:
            source = self._canonical(route.from_id, route.from_field, "out")
            destination = self._canonical(route.to_id, route.to_field, "in")
            if source and destination:
                # the ROUTE's identity is built once here, not for every event that crosses it
                self._routes.setdefault(source, []).append(
                    (*destination, self._fitter_of(*destination), (*source, *destination)))
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
            return (node_id, bg.resolve_field(node.node_type, field_name, direction, node.declared)[0])
        except bg.BehaviourError:
            return None

    def _fitter_of(self, node_id, field_name):
        x3d_type = self._field_type(node_id, field_name)
        return _fitter(x3d_type) if x3d_type is not None else None

    def _field_type(self, node_id, field_name):
        node = self.graph.nodes[node_id]
        if node.role == bg.CARRIED:
            return None
        return bg.resolve_field(node.node_type, field_name, "in", node.declared)[1]

    def _fault(self, node_id, where, error):
        self.faults.append(f"{node_id}.{where}: {type(error).__name__}: {error}")
        del self.faults[:-20]
        self.dropped["fault"] = self.dropped.get("fault", 0) + 1

    def _time(self, now):
        """``now`` when it is a number the clock can use; else the time the simulation was already at."""
        if isinstance(now, (int, float)) and not isinstance(now, bool) and math.isfinite(now):
            return now
        self.dropped["bad-time"] = self.dropped.get("bad-time", 0) + 1
        return self.now if self.now is not None else 0.0

    def _try(self, node_id, where, function, *args):
        """``function(*args)``, or ``[]`` after counting the fault when it raises (a sensor fed nonsense)."""
        try:
            return function(*args)
        except Exception as error:               # noqa: BLE001 - one bad node must not end the run
            self._fault(node_id, where, error)
            return []

    # -- the cascade ------------------------------------------------------------------------------------------

    def _emit(self, node_id, field_name, value):
        self._queue.append((node_id, field_name, value))

    def _drain(self):
        now = self.now if self.now is not None else 0.0
        queue, outputs, log, routes, fired, machines, dropped, world = \
            self._queue, self.outputs, self.log, self._routes, self._fired, self.machines, self.dropped, self.world
        while queue:
            node_id, field_name, value = queue.popleft()
            if not _finite(value):               # a NaN or an infinity never leaves a node
                dropped["non-finite"] = dropped.get("non-finite", 0) + 1
                continue
            outputs[(node_id, field_name)] = value
            log.append((now, node_id, field_name, value))
            verdicts = None
            for to_id, to_field, fits, key in routes.get((node_id, field_name), ()):
                if key in fired:                     # 4.4.8.3: a ROUTE carries one event per timestamp, which
                    continue                         # is also what stops a loop of ROUTEs
                if fits is not None:
                    # one event, one value: asked once per kind of field (a list of points sent to 1000 followers)
                    ok = verdicts.get(fits) if verdicts is not None else None
                    if ok is None:
                        ok = fits(value)
                        if verdicts is None:
                            verdicts = {}
                        verdicts[fits] = ok
                    if not ok:
                        dropped["mismatch"] = dropped.get("mismatch", 0) + 1
                        continue
                fired.add(key)
                machine = machines.get(to_id)
                if machine is not None:
                    try:
                        machine.receive(to_field, value, now)
                    except Exception as error:       # noqa: BLE001 - one bad node must not end the run
                        self._fault(to_id, "receive", error)
                    if machine.records:              # a scene node that runs (AudioClip, ...): the change is also reported
                        self.values[(to_id, to_field)] = value
                        self._changes.append((to_id, to_field, value))
                elif self.graph.nodes[to_id].role == bg.TARGET:
                    if world is not None and world.watches(to_id):
                        world.apply(to_id, to_field, value)
                    self.values[(to_id, to_field)] = value
                    self._changes.append((to_id, to_field, value))
                    queue.append((to_id, to_field, value))      # an inputOutput field sends what it was given

    def _collect(self):
        changes, self._changes = self._changes, []
        return changes

    def _sense(self, now):
        """The world is asked once, after a step's events have settled (X_ITE: its sensor events, then the drawing):
        Collision and the sensors that read the World send, their events travel, then a VisibilitySensor notes what the
        picture just drawn shows, for the next step to send."""
        if not (self._sensing or self._collisions):
            return
        if self._collisions:
            hits = self.world.collision_hits()
            for group in self._collisions:
                group.update(now, hits)
        for machine in self._sensing:
            self._try(machine.id, "sense", machine.update, now)
        self._drain()
        for machine in self._seeing:
            self._try(machine.id, "sense", machine.traverse)

    # -- what the caller does -----------------------------------------------------------------------------------

    def start(self, now=0.0):
        """Begin at time ``now``: looping timers start, followers that are not at rest wake up."""
        now = self._time(now)
        self.now, self._fired = now, set()
        for machine in self.machines.values():
            self._try(machine.id, "start", machine.start, now)
        self._drain()
        self._sense(now)
        return self._collect()

    def step(self, now):
        """Advance to time ``now``; returns [(target id, field, value)] in the order the values arrived."""
        # A step allocates tens of thousands of short-lived values (a list follower makes a tuple per point); the collector
        # scanning them again and again took a fifth of the time of the ``lists`` shape (tools/behaviour_bench.py). The
        # values have no cycles, so reference counting frees them: the collector is off for the step and back as it was.
        enabled = gc.isenabled()
        if enabled:
            gc.disable()
        try:
            return self._advance(now)
        finally:
            if enabled:
                gc.enable()

    def _advance(self, now):
        if self.now is None:
            return self.start(now)
        now = self._time(now)
        dt, self.now, self._fired = max(0.0, now - self.now), now, set()
        # every time-driven node first works out what it sends, from what it knew before this step; then the events
        # travel. So a follower chases where its destination was one step ago, as it does in X_ITE.
        for machine in self._ticking:
            try:
                machine.tick(now, dt)
            except Exception as error:               # noqa: BLE001 - one bad node must not end the run
                self._fault(machine.id, "tick", error)
        self._drain()
        self._sense(now)
        return self._collect()

    def post(self, node_id, field_name, value, now=None):
        """Send ``value`` out of an output field, as the node itself would (a sensor that sensed something)."""
        if now is not None:
            self.now = self._time(now)
        self._fired = set()              # something outside the graph happened: that is a new moment
        self._emit(node_id, field_name, value)
        posted = getattr(self.machines.get(node_id), "posted", None)      # a node that sends more because of this (GeoTouchSensor)
        if posted is not None:
            for more_field, more_value in self._try(node_id, "post", posted, field_name, value, self.now):
                self._emit(node_id, more_field, more_value)
        self._drain()
        return self._collect()

    def send(self, node_id, field_name, value, now=None):
        """Deliver ``value`` to an input field, as a ROUTE would."""
        if now is not None:
            self.now = self._time(now)
        machine = self.machines.get(node_id)
        if machine is None:
            raise bg.BehaviourError("unknown-def", f"{node_id!r} is not a node this simulation runs")
        name, kind = bg.resolve_field(machine.node_type, field_name, "in", self.graph.nodes[node_id].declared)
        if not _fits(value, kind) or not _finite(value):
            raise bg.BehaviourError("bad-value", f"{value!r} is not a value of {machine.node_type}.{name} ({kind})")
        self._fired = set()
        self._try(node_id, "receive", machine.receive, name, value, self.now if self.now is not None else 0.0)
        self._drain()
        return self._collect()

    # hosted nodes: a Script's handler, a CollisionSensor's contacts

    def host(self, def_name, handler):
        """Give the Script ``def_name`` a Python handler (see ``_Script``); ``None`` takes it away. Call it before ``start``
        for the handler to get its initialize call."""
        machine = self.machines.get(def_name)
        if not isinstance(machine, _Script):
            raise bg.BehaviourError("unknown-def", f"{def_name!r} is not a Script this simulation runs")
        if handler is not None and not callable(handler):
            raise bg.BehaviourError("bad-handler", "a handler is a function (field, value, time, state) -> [(field, value)]")
        machine.host(handler)

    def contact(self, node_id, active, contacts=(), intersections=(), now=None):
        """What a physics engine found for the CollisionSensor ``node_id``: it touches something (``active``), the names of
        the contacts and of the intersecting collidables. The stimulus ``{"call": "contact", "node": DEF, "active": bool,
        "contacts": [...]}`` makes this call."""
        machine = self.machines.get(node_id)
        if not isinstance(machine, _CollisionSensor):
            raise bg.BehaviourError("unknown-def", f"{node_id!r} is not a CollisionSensor this simulation runs")
        names = (list(contacts), list(intersections)) if isinstance(contacts, (list, tuple)) and isinstance(intersections, (list, tuple)) else None
        if not isinstance(active, bool) or names is None or not all(isinstance(n, str) for n in names[0] + names[1]):
            raise bg.BehaviourError("bad-value", "contact takes a bool and lists of names")
        if now is not None:
            self.now = self._time(now)
        self._fired = set()
        self._try(node_id, "contact", machine.contact, active, names[0], names[1], self.now if self.now is not None else 0.0)
        self._drain()
        return self._collect()

    def hosted_not_run(self):
        """The hosted nodes that have nothing to run them: a Script with no handler, a CollisionSensor no contact has been
        told to ("Script Brain", "CollisionSensor Hit"). The Player lists them; they are wired and say so."""
        return [f"{m.node_type} {m.id}" for m in self.machines.values()
                if (isinstance(m, _Script) and m.handler is None) or (isinstance(m, _CollisionSensor) and not m.fed)]

    # pointing sensors: the caller is the pointer

    def viewer(self, node_id, position, orientation, now, center_of_rotation=(0.0, 0.0, 0.0), test_position=None):
        """Where the viewer is, for one ProximitySensor, in that sensor's own coordinates: position, orientation
        (axis and angle) and the bound viewpoint's centre of rotation. Call it once per frame for each sensor.
        ``test_position``, when given, is the position the box test uses (X_ITE tests the camera as it was drawn, one
        frame behind a viewpoint that a ROUTE moves, and reports where it is now)."""
        machine = self.machines.get(node_id)
        if machine is None or machine.node_type not in PROXIMITY:
            raise bg.BehaviourError("unknown-def", f"{node_id!r} is not a ProximitySensor in this graph")
        return self._proximity(machine, position, orientation, center_of_rotation, now, test_position)

    def _proximity(self, machine, position, orientation, center_of_rotation, now, test_position):
        node_id = machine.id
        if not _finite((position, orientation, center_of_rotation, test_position)):
            self.dropped["non-finite"] = self.dropped.get("non-finite", 0) + 1
            return []
        changes = []
        for field_name, value in self._try(node_id, "sense", machine.sense, position, orientation, center_of_rotation,
                                           now, test_position):
            changes += self.post(node_id, field_name, value, now)
        return changes

    def view(self, position, orientation, now, center_of_rotation=(0.0, 0.0, 0.0), test_position=None, **frustum):
        """Where the viewer is in WORLD coordinates (position, orientation as axis and angle, the centre of rotation),
        for every ProximitySensor at once: the World gives each sensor's own coordinates (``World.viewer_in``) and the
        sensor then does what ``viewer`` makes it do. The viewer is also the World's viewer for the sensors that look
        through it (``frustum``: field_of_view, aspect, near, far). ``test_position`` is the world position the box test
        uses (the camera as it was drawn). A sensor the World has no frame for is named in ``noted["no-frame"]``."""
        if self.world is None:
            self.noted["no-world"] = self.noted.get("no-world", 0) + 1
            return []
        if not _finite((position, orientation, center_of_rotation, test_position, tuple(frustum.values()))):
            self.dropped["non-finite"] = self.dropped.get("non-finite", 0) + 1
            return []
        self.world.set_viewer(position, orientation, center_of_rotation, **frustum)
        changes = []
        for machine in self.machines.values():
            if machine.node_type not in PROXIMITY:
                continue
            if machine.id not in self.world.sensors:
                self.noted["no-frame"] = self.noted.get("no-frame", 0) + 1
                continue
            local = self.world.viewer_in(machine.id)
            drawn = None if test_position is None else self.world.to_local(machine.id, test_position)
            if local is not None and (test_position is None or drawn is not None):
                changes += self._proximity(machine, *local, now, drawn)
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
        if machine is None or (machine.node_type not in POINTING and machine.node_type not in GEO_POINTING):
            raise bg.BehaviourError("unknown-def", f"{node_id!r} is not a pointing sensor in this graph")
        return machine

    def hover(self, node_id, over, now):
        sensor = self._sensor(node_id)
        if not sensor.f.get("enabled", True) or sensor.over == bool(over):
            return []
        sensor.over = bool(over)
        return self.post(node_id, "isOver", sensor.over, now)

    def hit(self, node_id, point, now):
        """Where on the sensor's shapes the pointer is, in the sensor's own coordinates: the sensor sends ``hitPoint_changed``
        (and a GeoTouchSensor its ``hitGeoCoord_changed`` after it), while the pointer is over it (``hover``) and the sensor is
        enabled. Other sensors' hit points are not simulated: this is how a caller gives one."""
        sensor = self._sensor(node_id)
        if not sensor.f.get("enabled", True) or not sensor.over:
            return []
        point = tuple(point) if isinstance(point, (tuple, list)) else point
        if not _fits(point, "SFVec3f") or not _finite(point):
            self.dropped["non-finite" if _fits(point, "SFVec3f") else "mismatch"] = \
                self.dropped.get("non-finite" if _fits(point, "SFVec3f") else "mismatch", 0) + 1
            return []
        return self.post(node_id, "hitPoint_changed", point, now)

    def press(self, node_id, now, point=(0.0, 0.0, 0.0), ray=None, eye=None, follow=True, screen=None):
        """The pointer button goes down on the sensor's shapes. ``point`` is where, in the sensor's own coordinates.
        A CylinderSensor or SphereSensor also needs the pointer's ``ray`` (origin, direction) and the viewer's ``eye``
        (where it is, which way is back), in the same coordinates; without them it sends only isActive. A PlaneSensor
        given a ``ray`` runs from it (X_ITE's way: see ``_PlaneSensor``; ``screen`` is the camera, needed when it slides
        along a line); without one the caller drags it with points on its plane."""
        sensor = self._sensor(node_id)
        if not sensor.f.get("enabled", True) or sensor.pressed:
            return []
        if not _finite((point, ray, eye)):
            self.dropped["non-finite"] = self.dropped.get("non-finite", 0) + 1
            return []
        changes = self.hover(node_id, True, now)
        sensor.pressed, sensor.origin = True, tuple(point)
        changes += self.post(node_id, "isActive", True, now)
        sensor.geometry = ray is not None and eye is not None
        if sensor.node_type in ("CylinderSensor", "SphereSensor") and sensor.geometry:
            start = sensor.cylinder_press if sensor.node_type == "CylinderSensor" else sensor.sphere_press
            started = self._try(node_id, "press", lambda: start(_ray(ray), tuple(point), eye))
            sensor.geometry = bool(started)             # a press that failed leaves nothing to drag or release
            for field_name, value in started:
                changes += self.post(node_id, field_name, value, now)
            # X_ITE follows the press with one motion along the same ray (recorded: at its next frame, before any move),
            # so a SphereSensor's track point leaves the picked point for the ray's own crossing of the sphere.
            # ``follow=False`` leaves that motion to the caller (the judge sends it at X_ITE's next frame time).
            if follow:
                changes += self.drag(node_id, None, now, ray=ray)
        sensor.rayed = sensor.node_type == "PlaneSensor" and ray is not None
        if sensor.rayed:
            for field_name, value in sensor.plane_press(_ray(ray), tuple(point), screen):
                changes += self.post(node_id, field_name, value, now)
            if follow:     # the motion X_ITE makes along the press's own ray: its track point is worked out afresh
                changes += self.drag(node_id, None, now, ray=ray, fresh=True)
        return changes

    def drag(self, node_id, point, now, ray=None, fresh=False):
        """The pointer moves with the button down. A PlaneSensor sends where its plane was hit, less where it began;
        a CylinderSensor or SphereSensor turns by the pointer's ``ray``, in the sensor's own coordinates."""
        sensor = self._sensor(node_id)
        if not sensor.pressed:
            return []
        if not _finite((point, ray)):
            self.dropped["non-finite"] = self.dropped.get("non-finite", 0) + 1
            return []
        changes = []
        if sensor.node_type in ("CylinderSensor", "SphereSensor"):
            if ray is None or not getattr(sensor, "geometry", False):
                return []
            move = sensor.cylinder_drag if sensor.node_type == "CylinderSensor" else sensor.sphere_drag
            for field_name, value in self._try(node_id, "drag", lambda: move(_ray(ray))):
                changes += self.post(node_id, field_name, value, now)
            return changes
        if sensor.node_type == "PlaneSensor" and getattr(sensor, "rayed", False):
            if ray is not None:
                for field_name, value in sensor.plane_drag(_ray(ray), always=fresh):
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
        if sensor.node_type in ("TouchSensor", "GeoTouchSensor") and sensor.over:
            changes += self.post(node_id, "touchTime", now, now)
        if sensor.node_type in ("CylinderSensor", "SphereSensor") and getattr(sensor, "geometry", False):
            finish = sensor.cylinder_release if sensor.node_type == "CylinderSensor" else sensor.sphere_release
            for field_name, value in self._try(node_id, "release", finish):
                sensor.f[field_name] = value
                changes += self.post(node_id, field_name, value, now)
        if sensor.node_type == "PlaneSensor" and sensor.f["autoOffset"] and getattr(sensor, "last", None):
            sensor.f["offset"] = sensor.last
            changes += self.post(node_id, "offset", sensor.last, now)
        return changes

    def click(self, node_id, now, held=0.0):
        """Press and release. ``held`` seconds later for the release."""
        return self.press(node_id, now) + self.release(node_id, now + held)
