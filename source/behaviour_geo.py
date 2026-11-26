# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Geospatial coordinates for the behaviour graph (class C of docs/BEHAVIOUR_EVENT_NODES.md): pure functions, no Blender,
no numpy, no other module of the add-on.

The Geo nodes in the behaviour graph (GeoPositionInterpolator, GeoProximitySensor, GeoTouchSensor) keep their numbers in a
``geoSystem`` and send them out in it, and in the scene's own metres. This module is the arithmetic between the two, as
X_ITE 16.8.1 does it (read from ``assets/components/GeospatialComponent.js``, and compared with X_ITE's own answers in
``tests/behaviour/geo_conversions.json``, recorded by ``tools/behaviour_geo_probe.py``). Where the standard's text and
X_ITE differ, X_ITE is followed and the difference is named here:

* ``geoSystem`` is read token by token, in any order: the first coordinate system among ``GD`` ``GDC`` ``UTM`` ``GC`` ``GCC``
  ``GS`` (none: ``GD``), the first reference ellipsoid code (none: ``WE``), ``longitude_first``, ``easting_first``, ``S``
  and ``Zn``. X_ITE knows no ``WM`` (Web Mercator): such a node reads as GD, and so does this module. A token that is none
  of these is ignored. The UTM zone is not checked (``Z0``, ``Z99`` work as they are given).
* Geocentric to geodetic is X_ITE's iteration (at most 30 steps, stopping when the height moves by less than 1 mm and the
  latitude by less than 1e-10 radians). A point on the polar axis comes back with latitude of pi radians (180 degrees
  in a GD system), not pi/2: X_ITE's pole case, followed as it is.
* UTM to geodetic is X_ITE's series, which uses ``tan(phi1) ** 8`` where Snyder has ``T ** 2`` squared (a term of the same
  order as the series' own error), and takes a negative northing as the other hemisphere.
* The local frame of a GeoOrigin with ``rotateYUp`` is ``x = (0, 0, 1) x up``, ``z = x x up`` (the pole: ``x = (1, 0, 0)``), so
  the local frame's Y is the ellipsoid's up at the origin: the same frame X_ITE builds, with the node's own ellipsoid.
* A geodetic coordinate of a node with no GeoOrigin is sent as it is: its local coordinates are geocentric metres.
* Every function returns ``(nan, nan, nan)`` where X_ITE's JavaScript would produce a NaN or an infinity (``math.sin(inf)``
  raises in Python and is NaN in JavaScript), so a hostile number is a number the simulator drops and counts, never a raise.
"""

from __future__ import annotations

import math
import re
from typing import NamedTuple

NAN3 = (math.nan, math.nan, math.nan)

# -- reference ellipsoids: X_ITE's table, X3D 4.0's codes and then the bodies of the solar system --------------------------
_BY_FLATTENING = {       # code -> (semi-major axis a in metres, inverse flattening 1/f); c = a (1 - 1/f)
    "AA": (6377563.396, 299.3249646), "AM": (6377340.189, 299.3249646), "AN": (6378160.0, 298.25),
    "BN": (6377483.865, 299.1528128), "BR": (6377397.155, 299.1528128), "CC": (6378206.4, 294.9786982),
    "CD": (6378249.145, 293.465), "EA": (6377276.345, 300.8017), "EB": (6377298.556, 300.8017),
    "EC": (6377301.243, 300.8017), "ED": (6377295.664, 300.8017), "EE": (6377304.063, 300.8017),
    "EF": (6377309.613, 300.8017), "FA": (6378155.0, 298.3), "HE": (6378200.0, 298.3), "HO": (6378270.0, 297.0),
    "ID": (6378160.0, 298.247), "IN": (6378388.0, 297.0), "KA": (6378245.0, 298.3), "RF": (6378137.0, 298.257222101),
    "SA": (6378160.0, 298.25), "WD": (6378135.0, 298.26), "WE": (6378137.0, 298.257223563),
    "SUN": (696342000.0, 1 / 9e-6),
}
_BY_AXES = {             # code -> (a, c); URANUS: X_ITE 16.8.1 has 2555000 for a (a typo: smaller than c), followed
    "MERCURY": (2439700.0, 2439700.0), "VENUS": (6051800.0, 6051800.0), "MOON": (1738140.0, 1735970.0),
    "MARS": (3395428.0, 3377678.0), "JUPITER": (71492000.0, 66854000.0), "SATURN": (60268000.0, 54364000.0),
    "URANUS": (2555000.0, 24973000.0), "NEPTUNE": (24764000.0, 24341000.0), "PLUTO": (1153000.0, 1153000.0),
}
ELLIPSOIDS = {code: (a, a * (1 - 1 / f_1)) for code, (a, f_1) in _BY_FLATTENING.items()}
ELLIPSOIDS.update(_BY_AXES)

_SYSTEMS = {"GD": "GD", "GDC": "GD", "UTM": "UTM", "GC": "GC", "GCC": "GC", "GS": "GC"}
_ZONE = re.compile(r"^Z(\d+)$")          # X_ITE: the whole token must match
_N0, _E0, _K0 = 1.0e7, 5.0e5, 0.9996
_PI = math.pi


class GeoSystem(NamedTuple):
    kind: str            # "GD", "UTM" or "GC"
    a: float             # semi-major axis of the ellipsoid (also for GC: the elevation frame still uses it)
    c: float             # semi-minor axis
    standard: bool       # GD: latitude first; UTM: northing first; GC: always
    zone: int            # UTM zone (not checked)
    northern: bool       # UTM: northern hemisphere (no "S" token)


def strings(text):
    """An MFString attribute's text as a list of strings (``"GD" "WE"``). Text with no quote mark is one token per word,
    which X_ITE reads the same way (``geoSystem="GD WE"``)."""
    if text is None:
        return []
    if not isinstance(text, str):
        return [str(t) for t in text]
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
    if found or '"' in text:
        return found
    return text.replace(",", " ").split()


def parse_geo_system(tokens) -> GeoSystem:
    """A ``geoSystem`` (a list of strings, or the attribute's text) as a ``GeoSystem``, the way X_ITE reads it."""
    tokens = strings(tokens) if not isinstance(tokens, (list, tuple)) else [str(t) for t in tokens]
    kind = next((_SYSTEMS[t] for t in tokens if t in _SYSTEMS), "GD")
    a, c = next((ELLIPSOIDS[t] for t in tokens if t in ELLIPSOIDS), ELLIPSOIDS["WE"])
    latitude_first = "longitude_first" not in tokens
    northing_first = "easting_first" not in tokens
    zone = next((int(m.group(1)) for m in map(_ZONE.match, tokens) if m), 1)
    standard = {"GD": latitude_first, "UTM": northing_first, "GC": True}[kind]
    return GeoSystem(kind, a, c, standard, zone, "S" not in tokens)


# -- geodetic: latitude, longitude (degrees), elevation <-> geocentric x, y, z (metres) --------------------------------------

def _geodetic_radians_to_geocentric(gs, latitude, longitude, elevation):
    c2a2 = (gs.c / gs.a) ** 2
    ecc2 = 1 - c2a2
    slat, clat = math.sin(latitude), math.cos(latitude)
    n = gs.a / math.sqrt(1 - ecc2 * slat ** 2)
    nhl = (n + elevation) * clat
    return (nhl * math.cos(longitude), nhl * math.sin(longitude), (n * c2a2 + elevation) * slat)


def geocentric_to_geodetic_radians(gs, x, y, z):
    """(latitude, longitude, elevation), radians and metres, X_ITE's iteration (``Geodetic.applyRadians``)."""
    ecc2 = 1 - (gs.c / gs.a) ** 2
    p = math.sqrt(x * x + y * y)
    if p == 0:
        return (_PI, 0.0, z - gs.c)
    latitude, longitude, elevation = 0.0, math.atan2(y, x), 0.0
    a = n = gs.a
    for _ in range(30):
        h0, b0 = elevation, latitude
        latitude = math.atan(z / p / (1 - ecc2 * n / (n + elevation)))
        sin_p = math.sin(latitude)
        n = a / math.sqrt(1 - ecc2 * sin_p * sin_p)
        elevation = p / math.cos(latitude) - n
        if abs(elevation - h0) < 1e-3 and abs(latitude - b0) < 1e-10:
            break
    return (latitude, longitude, elevation)


# -- UTM ------------------------------------------------------------------------------------------------------------------

class _Utm:
    """X_ITE's UniversalTransverseMercator for one ellipsoid, zone, hemisphere and order."""

    def __init__(self, gs):
        a = gs.a
        ecc2 = 1 - (gs.c / a) ** 2
        ee = ecc2 / (1 - ecc2)
        e1 = (1 - math.sqrt(1 - ecc2)) / (1 + math.sqrt(1 - ecc2))
        self.gs, self.a, self.ecc2, self.ee, self.e1 = gs, a, ecc2, ee, e1
        self.e8, self.e9, self.e252 = 8 * ee, 9 * ee, 252 * ee
        self.A = _K0 * (a * (1 - ecc2 / 4 - 3 * ecc2 * ecc2 / 64 - 5 * ecc2 * ecc2 * ecc2 / 256))
        self.B = 3 * e1 / 2 - 7 * e1 * e1 * e1 / 32
        self.C = 21 * e1 * e1 / 16 - 55 * e1 * e1 * e1 * e1 / 32
        self.D = 151 * e1 * e1 * e1 / 96
        self.E = a * (1 - ecc2)
        self.W = 1 - ecc2 / 4 - 3 * ecc2 * ecc2 / 64 - 5 * ecc2 * ecc2 * ecc2 / 256
        self.X = 3 * ecc2 / 8 + 3 * ecc2 * ecc2 / 32 + 45 * ecc2 * ecc2 * ecc2 / 1024
        self.Y = 15 * ecc2 * ecc2 / 256 + 45 * ecc2 * ecc2 * ecc2 / 1024
        self.Z = 35 * ecc2 * ecc2 * ecc2 / 3072
        self.longitude0 = math.radians(gs.zone * 6 - 183) if abs(gs.zone) < 1e300 else math.inf

    def convert(self, utm):
        gs = self.gs
        northing, easting = (utm[0], utm[1]) if gs.standard else (utm[1], utm[0])   # X_ITE: eastingFirst = not northingFirst
        south = not gs.northern
        if northing < 0:
            south = not south
            northing = -northing
        if south:
            northing -= _N0
        easting -= _E0
        mu = northing / self.A
        phi1 = mu + self.B * math.sin(2 * mu) + self.C * math.sin(4 * mu) + self.D * math.sin(6 * mu)
        sinphi1 = math.sin(phi1) ** 2
        cosphi1 = math.cos(phi1)
        tanphi1 = math.tan(phi1)
        n1 = self.a / math.sqrt(1 - self.ecc2 * sinphi1)
        t2 = tanphi1 ** 2
        t8 = tanphi1 ** 8
        c1 = self.ee * t2
        c2 = c1 * c1
        r1 = self.E / (1 - self.ecc2 * sinphi1) ** 1.5
        i = easting / (n1 * _K0)
        j = (5 + 3 * t2 + 10 * c1 - 4 * c2 - self.e9) * i ** 4 / 24
        k = (61 + 90 * t2 + 298 * c1 + 45 * t8 - self.e252 - 3 * c2) * i ** 6 / 720
        l = (5 - 2 * c1 + 28 * t2 - 3 * c2 + self.e8 + 24 * t8) * i ** 5 / 120
        latitude = phi1 - (n1 * tanphi1 / r1) * (i * i / 2 - j + k)
        longitude = self.longitude0 + (i - (1 + 2 * t2 + c1) * i ** 3 / 6 + l) / cosphi1
        return _geodetic_radians_to_geocentric(gs, latitude, longitude, utm[2])

    def apply(self, point):
        gs = self.gs
        latitude, longitude, elevation = geocentric_to_geodetic_radians(gs, *point)
        tanlat, coslat = math.tan(latitude), math.cos(latitude)
        ee = self.ee
        n = self.a / math.sqrt(1 - self.ecc2 * math.sin(latitude) ** 2)
        t = tanlat * tanlat
        t6 = t * t * t
        c = ee * coslat * coslat
        a = coslat * (longitude - self.longitude0)
        m = self.a * (self.W * latitude - self.X * math.sin(2 * latitude) + self.Y * math.sin(4 * latitude)
                      - self.Z * math.sin(6 * latitude))
        easting = _K0 * n * (a + (1 - t + c) * a ** 3 / 6 + (5 - 18 * t6 + 72 * c - 58 * ee) * a ** 5 / 120) + _E0
        northing = _K0 * (m + n * tanlat * (a * a / 2 + (5 - t + 9 * c + 4 * c * c) * a ** 4 / 24
                                            + (61 - 58 * t6 + 600 * c - 330 * ee) * a ** 6 / 720))
        if latitude < 0:
            northing += _N0
            if gs.northern:
                northing = -northing
        elif not gs.northern:
            northing = -northing
        return (northing, easting, elevation) if gs.standard else (easting, northing, elevation)


# -- the two directions, for a GeoSystem -----------------------------------------------------------------------------------

_UTM_CACHE = {}


def _utm(gs):
    found = _UTM_CACHE.get(gs)
    if found is None:
        if len(_UTM_CACHE) > 64:
            _UTM_CACHE.clear()
        found = _UTM_CACHE[gs] = _Utm(gs)
    return found


def to_geocentric(gs, point):
    """A coordinate in ``gs`` (as the field holds it: GD latitude, longitude, elevation in degrees and metres, or longitude
    first; UTM northing, easting, elevation or easting first; GC x, y, z) as geocentric metres (``referenceFrame.convert``)."""
    try:
        if gs.kind == "GC":
            return (float(point[0]), float(point[1]), float(point[2]))
        if gs.kind == "UTM":
            return _utm(gs).convert(point)
        latitude, longitude = (point[0], point[1]) if gs.standard else (point[1], point[0])
        return _geodetic_radians_to_geocentric(gs, latitude * (_PI / 180), longitude * (_PI / 180), point[2])
    except (ValueError, OverflowError, ZeroDivisionError):
        return NAN3


def from_geocentric(gs, point):
    """Geocentric metres as a coordinate in ``gs`` (``referenceFrame.apply``)."""
    try:
        if gs.kind == "GC":
            return (float(point[0]), float(point[1]), float(point[2]))
        if gs.kind == "UTM":
            return _utm(gs).apply(point)
        latitude, longitude, elevation = geocentric_to_geodetic_radians(gs, *point)
        latitude *= 180 / _PI
        longitude *= 180 / _PI
        return (latitude, longitude, elevation) if gs.standard else (longitude, latitude, elevation)
    except (ValueError, OverflowError, ZeroDivisionError):
        return NAN3


def up_vector(gs, point):
    """The ellipsoid's up at a geocentric point (``elevationFrame.normal``): the node's own ellipsoid, latitude first, in
    radians. X_ITE's pole case gives latitude pi (see the module text)."""
    try:
        latitude, longitude, _ = geocentric_to_geodetic_radians(gs, *point)
        clat = math.cos(latitude)
        return (math.cos(longitude) * clat, math.sin(longitude) * clat, math.sin(latitude))
    except (ValueError, OverflowError, ZeroDivisionError):
        return NAN3


# -- a GeoOrigin, and the frame a Geo node works in ------------------------------------------------------------------------

class GeoOrigin(NamedTuple):
    """A GeoOrigin node: its own geoSystem (a list of tokens), its geoCoords and rotateYUp."""
    system: tuple = ("GD", "WE")
    coords: tuple = (0.0, 0.0, 0.0)
    rotate_y_up: bool = False


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(v):
    length = math.hypot(*v)
    return (v[0] / length, v[1] / length, v[2] / length) if length else v


def _inverse3(r0, r1, r2):
    """The inverse of the 3 x 3 matrix whose rows are r0, r1, r2 (rows, as the cofactors give it), or None."""
    a, b, c = r0
    d, e, f = r1
    g, h, i = r2
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if det == 0 or not math.isfinite(det):
        return None
    return (((e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det),
            ((f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det),
            ((d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det))


class GeoFrame:
    """What every Geo node does with its ``geoSystem`` and its ``geoOrigin``: ``local(geo)`` takes a coordinate in the node's
    geoSystem to the node's local coordinates (geocentric metres less the origin, or in the origin's Y-up frame when the
    GeoOrigin has ``rotateYUp``), and ``geo(point)`` takes local coordinates back. X3DGeospatialObject.js."""

    def __init__(self, system, origin=None):
        self.system = parse_geo_system(system)
        self.origin_node = origin
        self.origin = (0.0, 0.0, 0.0)
        self.rows = self.inverse = None            # the origin matrix's rows (x, y, z axes) and the inverse of that 3 x 3
        if origin is not None:
            self.origin = to_geocentric(parse_geo_system(origin.system), origin.coords)
            if origin.rotate_y_up:
                self._matrix()

    def _matrix(self):
        t = self.origin
        if not all(math.isfinite(v) for v in t):
            return
        y = up_vector(self.system, t)
        x = _cross((0.0, 0.0, 1.0), y)
        if x == (0.0, 0.0, 0.0):                   # the pole
            x = (1.0, 0.0, 0.0)
        z = _unit(_cross(x, y))
        x = _unit(x)
        self.rows = (x, y, z)
        self.inverse = _inverse3(x, y, z)          # of the matrix as X_ITE's Matrix4 has it (rows are the axes)

    @property
    def rotated(self):
        return self.rows is not None

    def local(self, geo):
        """Local coordinates of a coordinate in the node's geoSystem."""
        p = to_geocentric(self.system, geo)
        if self.origin_node is not None and self.origin_node.rotate_y_up:
            return self._from_origin_frame(p)
        return (p[0] - self.origin[0], p[1] - self.origin[1], p[2] - self.origin[2])

    def geo(self, point):
        """The node's geoSystem coordinate of a point in local coordinates."""
        if self.origin_node is not None and self.origin_node.rotate_y_up:
            return from_geocentric(self.system, self._to_origin_frame(point))
        o = self.origin
        return from_geocentric(self.system, (point[0] + o[0], point[1] + o[1], point[2] + o[2]))

    # X_ITE's Matrix4 is a row-vector matrix: v' = v.x * X + v.y * Y + v.z * Z + t, with rows X, Y, Z and translation t
    def _to_origin_frame(self, v):
        if self.rows is None:
            return NAN3
        (x, y, z), t = self.rows, self.origin
        return (v[0] * x[0] + v[1] * y[0] + v[2] * z[0] + t[0],
                v[0] * x[1] + v[1] * y[1] + v[2] * z[1] + t[1],
                v[0] * x[2] + v[1] * y[2] + v[2] * z[2] + t[2])

    def _from_origin_frame(self, p):
        """``invOriginMatrix.multVecMatrix(p)``: the inverse of the whole 4 x 4 (rotation, then the translation it implies)."""
        if self.inverse is None:
            return NAN3
        (r0, r1, r2), (x, y, z), t = self.inverse, self.rows, self.origin
        # inverse of [R 0; t 1] (row vectors) is [R^-1 0; -t R^-1 1]
        tx = -(t[0] * r0[0] + t[1] * r1[0] + t[2] * r2[0])
        ty = -(t[0] * r0[1] + t[1] * r1[1] + t[2] * r2[1])
        tz = -(t[0] * r0[2] + t[1] * r1[2] + t[2] * r2[2])
        return (p[0] * r0[0] + p[1] * r1[0] + p[2] * r2[0] + tx,
                p[0] * r0[1] + p[1] * r1[1] + p[2] * r2[1] + ty,
                p[0] * r0[2] + p[1] * r1[2] + p[2] * r2[2] + tz)


def slerp(a, b, t):
    """``Geocentric.slerp`` (GeoPositionInterpolator's mix): the two vectors' directions are slerped the long way round
    when they are more than a quarter turn apart (no shortest-path flip), and their lengths are lerped. Equal directions
    give the first direction. Two opposite vectors are a division by zero in the formula: huge but finite, as in X_ITE; a
    dot product a hair under -1 from rounding is ``acos`` of a number outside its domain, a NaN in X_ITE and here."""
    try:
        la, lb = math.hypot(*a), math.hypot(*b)
        ua, ub = _unit(a), _unit(b)
        cosom = ua[0] * ub[0] + ua[1] * ub[1] + ua[2] * ub[2]
        if cosom >= 1:
            direction = ua
        else:
            omega = math.acos(cosom)
            sinom = math.sin(omega)
            s0, s1 = math.sin((1 - t) * omega) / sinom, math.sin(t * omega) / sinom
            direction = (ua[0] * s0 + ub[0] * s1, ua[1] * s0 + ub[1] * s1, ua[2] * s0 + ub[2] * s1)
        length = la + t * (lb - la)
        return (direction[0] * length, direction[1] * length, direction[2] * length)
    except (ValueError, OverflowError, ZeroDivisionError):
        return NAN3


# -- reading a GeoOrigin from markup ----------------------------------------------------------------------------------------

def _numbers3(text, default):
    try:
        values = tuple(float(v) for v in str(text).replace(",", " ").split())
    except ValueError:
        return default
    return values if len(values) == 3 and all(math.isfinite(v) for v in values) else default


def origin_from_attributes(attributes):
    """A ``GeoOrigin`` from the attributes of a ``<GeoOrigin>`` element (a mapping: geoSystem, geoCoords, rotateYUp)."""
    system = tuple(strings(attributes.get("geoSystem", '"GD" "WE"')) or ("GD", "WE"))
    return GeoOrigin(system, _numbers3(attributes.get("geoCoords"), (0.0, 0.0, 0.0)),
                     str(attributes.get("rotateYUp", "false")).strip().lower() == "true")


def origins_in(root):
    """{DEF: GeoOrigin} for every ``<GeoOrigin DEF=...>`` under an ElementTree element."""
    found = {}
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == "GeoOrigin" and element.get("DEF") and element.get("USE") is None:
            found[element.get("DEF")] = origin_from_attributes(element.attrib)
    return found
