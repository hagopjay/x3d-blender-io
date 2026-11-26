# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""GeoPositionInterpolator, GeoProximitySensor and GeoTouchSensor: the machines (class B and C of
docs/BEHAVIOUR_EVENT_NODES.md). The arithmetic is ``behaviour_geo``; this module is the nodes.

Imported by ``behaviour_sim`` (at its end, which registers the machines); import ``behaviour_sim``, not this module.

What X_ITE 16.8.1 does, read from its source and recorded by ``tests/behaviour/probe-geo.x3d`` and
``tests/behaviour/probe-geo-touch.x3d`` (the simulator follows it; ``tools/behaviour_sim_judge.py`` compares the two):

* **GeoPositionInterpolator** takes the two keys' values to local coordinates (geocentric metres less the GeoOrigin, or in
  the GeoOrigin's Y-up frame with ``rotateYUp``), interpolates THERE with a slerp of the directions and a lerp of the lengths
  (not in geodetic coordinates, and not along a straight line), and sends the result as ``value_changed`` (an SFVec3f: X_ITE
  keeps it in single precision, as does this machine) and, converted back to the node's own ``geoSystem``, as
  ``geovalue_changed`` (an SFVec3d). Which keys, and the weight, are the plain interpolator's (``_Segmented``); a ``keyValue``
  shorter than ``key`` is padded with its last value, or with the zero coordinate when it is empty.
* **GeoProximitySensor** is a ProximitySensor in the coordinates of its parent, with one more output: ``geoCoord_changed``,
  the viewer's position as a coordinate in the node's ``geoSystem`` (sent whenever ``position_changed`` is). ``geoCenter`` is
  not read when the file is: X_ITE copies it to ``center`` only when it changes by an event, and copies it as it is (no
  conversion), so a ``geoCenter`` attribute does nothing and ``center`` is the box's centre.
* **GeoTouchSensor** is a TouchSensor with ``hitGeoCoord_changed``, the hit point as a coordinate in the node's
  ``geoSystem``, sent after every ``hitPoint_changed`` while the pointer is over the sensor.
* **GeoOrigin**, a deprecated node that files still carry: read from the node's content (``<GeoOrigin .../>`` inside it, or
  ``<GeoOrigin USE="..."/>`` named in the scene by DEF, which the ``World`` read from the file or another node's content).
  A USE that names no GeoOrigin in this simulation is refused by name: the node sends nothing that depends on the origin and
  ``Simulation.noted["geo-origin-unresolved"]`` counts it (through Blender's exporter a GeoOrigin DEF can be renamed away from
  the USE; the node then has no origin to find and works in geocentric metres, which cannot be told from a file that says so).
"""

from __future__ import annotations

import math
import struct
import xml.etree.ElementTree as ET

try:
    from . import behaviour_geo as geo
    from .behaviour_sim import _ProximitySensor, _Segmented, _Sensor
except ImportError:  # imported as plain modules: tests, tools/
    import behaviour_geo as geo
    from behaviour_sim import _ProximitySensor, _Segmented, _Sensor

_FLOAT32_MAX = 3.4028234663852886e38


def _note(sim, what):
    sim.noted[what] = sim.noted.get(what, 0) + 1


def float32(value):
    """``Math.fround`` of each component: X_ITE's SFVec3f is single precision."""
    out = []
    for v in value:
        if v != v or abs(v) == math.inf:
            out.append(v)
        elif abs(v) > _FLOAT32_MAX:
            out.append(math.copysign(math.inf, v))
        else:
            out.append(struct.unpack("f", struct.pack("f", v))[0])
    return tuple(out)


def known_origins(sim):
    """{DEF: GeoOrigin} every GeoOrigin the simulation can name: those of the World's scene (``World.geo_origins``) and those
    defined inside a node's content."""
    found = getattr(sim, "_geo_origins", None)
    if found is None:
        found = {}
        for node in sim.graph.nodes.values():
            if node.content and "GeoOrigin" in node.content:
                try:
                    found.update(geo.origins_in(ET.fromstring(f"<c>{node.content}</c>")))
                except ET.ParseError:
                    pass
        found.update(getattr(sim.world, "geo_origins", None) or {})
        sim._geo_origins = found
    return found


def origin_of(sim, node):
    """(GeoOrigin or None, resolved): the node's ``geoOrigin``, or None when it has none. ``resolved`` is False when it
    names a GeoOrigin that cannot be found."""
    content = node.content
    if not content or "GeoOrigin" not in content and "geoOrigin" not in content:
        return None, True
    try:
        root = ET.fromstring(f"<c>{content}</c>")
    except ET.ParseError:
        return None, True
    for element in root:
        if element.tag.rsplit("}", 1)[-1] != "GeoOrigin" and element.get("containerField") != "geoOrigin":
            continue
        use = element.get("USE")
        if use is not None:
            found = known_origins(sim).get(use)
            return found, found is not None
        return geo.origin_from_attributes(element.attrib), True
    return None, True


class _GeoMixin:
    """The frame a Geo node works in, built once from its ``geoSystem`` and its ``geoOrigin``."""

    def geo_setup(self):
        node = self.sim.graph.nodes[self.id]
        origin, resolved = origin_of(self.sim, node)
        self.frame = geo.GeoFrame(self.f.get("geoSystem") or [], origin) if resolved else None
        if not resolved:
            _note(self.sim, "geo-origin-unresolved")


class _GeoPositionInterpolator(_GeoMixin, _Segmented):
    def setup(self):
        self.geo_setup()
        self._locals = {}
        super().setup()

    def rebuild(self):
        self._locals = {}

    def _local(self, values, index):
        found = self._locals.get(index)
        if found is None:
            found = self._locals[index] = self.frame.local(values[index])
        return found

    def interpolate(self, lower, upper, weight):
        if self.frame is None:
            return None
        values = self._padded("keyValue", (0.0, 0.0, 0.0))
        coord = geo.slerp(self._local(values, lower), self._local(values, upper), weight)
        self.emit("geovalue_changed", self.frame.geo(coord))
        self.emit("value_changed", float32(coord))


class _GeoProximitySensor(_GeoMixin, _ProximitySensor):
    def setup(self):
        self.geo_setup()
        self.pose = None             # the viewer as the last report gave it: what an ``enabled`` that arrives between reports uses
        super().setup()

    def sense(self, position, orientation, center_of_rotation, now, test_position=None):
        self.pose = (position, orientation, center_of_rotation, test_position)
        sent = super().sense(position, orientation, center_of_rotation, now, test_position)
        if self.frame is None:
            return sent
        out = []
        for name, value in sent:
            out.append((name, value))
            if name == "position_changed":
                out.append(("geoCoord_changed", self.frame.geo(value)))
        return out

    def changed(self, name, now):
        if name == "geoCenter":                  # X_ITE: geoCenter -> center, as it is
            self.f["center"] = self.f["geoCenter"]
            self.emit("center", self.f["center"])
        elif name == "enabled":
            # X_ITE does not wait for the next picture. Disabled, an active sensor leaves at once (isActive false and exitTime
            # at the time of the event; X_ITE sends that pair twice, once from the sensor and once from the ProximitySensor
            # inside it, and the simulator once: a ROUTE carries one event per time stamp). Enabled, the sensor is placed with the
            # viewer of this very frame, so it can enter at the time of the event.
            if not self.f["enabled"]:
                if self.active:
                    self.active = False
                    self.emit("isActive", False)
                    self.emit("exitTime", now)
            elif self.pose is not None:
                for field_name, value in self.sense(*self.pose[:3], now, self.pose[3]):
                    self.emit(field_name, value)


class _GeoTouchSensor(_GeoMixin, _Sensor):
    def setup(self):
        self.geo_setup()
        super().setup()

    def posted(self, field_name, value, now):
        """What follows an event the caller posted (``Simulation.post``): the hit point, while the pointer is over, is also
        sent as a coordinate in the node's geoSystem."""
        if field_name == "hitPoint_changed" and self.over and self.f.get("enabled", True):
            if self.frame is None or not geo.is_vec3(value):
                return []
            return [("hitGeoCoord_changed", self.frame.geo(value))]
        return []


MACHINES = {"GeoPositionInterpolator": _GeoPositionInterpolator, "GeoProximitySensor": _GeoProximitySensor,
            "GeoTouchSensor": _GeoTouchSensor}
PROXIMITY = ("ProximitySensor", "GeoProximitySensor")       # what ``Simulation.viewer`` and ``view`` feed
TOUCHING = ("GeoTouchSensor",)                              # pointing sensors beyond ``behaviour_sim.POINTING``
