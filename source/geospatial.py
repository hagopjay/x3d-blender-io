# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""X3D Geospatial component maths: the geoSystem field and its conversion to geocentric coordinates.

ISO/IEC 19775-1 (X3D 4.0), Geospatial component. A geoSystem is an MFString such as ``"GD" "WE"`` (geodetic, WGS 84:
latitude and longitude in degrees, height in metres), ``"GD" "WE" "longitude_first"``, ``"UTM" "Z31" "S"`` (zone 31,
southern hemisphere), ``"GC"`` (geocentric, metres) or ``"WM"`` (Web Mercator, metres; X_ITE 16.7.1 does not know it
and reads such a node as GD). The ellipsoid codes are the spec's reference ellipsoid table
(WE is WGS 84); the solar system bodies are the ones X_ITE 16.7.1 knows.

Geocentric coordinates are about 6.4e6 m for the Earth, so everything here runs in float64 (numpy) and only the
caller's last step, writing Blender's float32 vertices, rounds (the spacing of a float32 near 6.4e6 is 0.5 m).

Pure Python and numpy, so the tests can use it without Blender.
"""

from __future__ import annotations

import math
import re
from typing import NamedTuple

import numpy as np

# Reference ellipsoids: code -> (semi-major axis a in metres, inverse flattening 1/f), or for a body given by its two
# axes, (a, c). X3D 4.0's table of reference ellipsoids first, then X_ITE 16.7.1's solar system bodies.
_ELLIPSOIDS_BY_FLATTENING = {
    "AA": (6377563.396, 299.3249646),   # Airy 1830
    "AM": (6377340.189, 299.3249646),   # Modified Airy
    "AN": (6378160.0, 298.25),          # Australian National
    "BN": (6377483.865, 299.1528128),   # Bessel 1841 (Namibia)
    "BR": (6377397.155, 299.1528128),   # Bessel 1841 (Ethiopia, Indonesia, ...)
    "CC": (6378206.4, 294.9786982),     # Clarke 1866
    "CD": (6378249.145, 293.465),       # Clarke 1880
    "EA": (6377276.345, 300.8017),      # Everest (India 1830)
    "EB": (6377298.556, 300.8017),      # Everest (Sabah and Sarawak)
    "EC": (6377301.243, 300.8017),      # Everest (India 1956)
    "ED": (6377295.664, 300.8017),      # Everest (W. Malaysia 1969)
    "EE": (6377304.063, 300.8017),      # Everest (W. Malaysia and Singapore 1948)
    "EF": (6377309.613, 300.8017),      # Everest (Pakistan)
    "FA": (6378155.0, 298.3),           # Modified Fischer 1960
    "HE": (6378200.0, 298.3),           # Helmert 1906
    "HO": (6378270.0, 297.0),           # Hough 1960
    "ID": (6378160.0, 298.247),         # Indonesian 1974
    "IN": (6378388.0, 297.0),           # International 1924
    "KA": (6378245.0, 298.3),           # Krassovsky 1940
    "RF": (6378137.0, 298.257222101),   # GRS 80
    "SA": (6378160.0, 298.25),          # South American 1969
    "WD": (6378135.0, 298.26),          # WGS 72
    "WE": (6378137.0, 298.257223563),   # WGS 84
    "WGS84": (6378137.0, 298.257223563),
    "SUN": (696342000.0, 1.0 / 9e-6),
}
_ELLIPSOIDS_BY_AXES = {   # code -> (a, c)
    "MERCURY": (2439700.0, 2439700.0),
    "VENUS": (6051800.0, 6051800.0),
    "MOON": (1738140.0, 1735970.0),
    "MARS": (3395428.0, 3377678.0),
    "JUPITER": (71492000.0, 66854000.0),
    "SATURN": (60268000.0, 54364000.0),
    "URANUS": (25559000.0, 24973000.0),   # X_ITE 16.7.1 has 2555000 for a, a typo: that is smaller than c
    "NEPTUNE": (24764000.0, 24341000.0),
    "PLUTO": (1153000.0, 1153000.0),
}


def ellipsoid_axes(code: str):
    """(semi-major axis, semi-minor axis) in metres of an ellipsoid code, or None for an unknown code."""
    if code in _ELLIPSOIDS_BY_FLATTENING:
        a, f_1 = _ELLIPSOIDS_BY_FLATTENING[code]
        return a, a * (1.0 - 1.0 / f_1)
    return _ELLIPSOIDS_BY_AXES.get(code)


class GeoSystem(NamedTuple):
    kind: str             # "GD", "UTM", "GC" or "WM"
    a: float              # semi-major axis of the ellipsoid, metres
    c: float              # semi-minor axis
    standard_order: bool  # GD: latitude first (not "longitude_first"); UTM: northing first (not "easting_first")
    zone: int             # UTM zone, 1..60
    south: bool           # UTM southern hemisphere


_KINDS = {"GD": "GD", "GDC": "GD", "UTM": "UTM", "GC": "GC", "GCC": "GC", "WM": "WM"}
_ZONE = re.compile(r"^Z(\d+)$")


def parse_geo_system(tokens) -> GeoSystem:
    """A geoSystem MFString (a list of strings) as a GeoSystem. The coordinate system defaults to GD and the
    ellipsoid to WE, as in the spec; a token that is none of the spec's is ignored."""
    kind, ellipsoid, standard, zone, south = "GD", None, True, 1, False
    kind_seen = False
    for token in tokens:
        token = token.strip()
        if token in _KINDS and not kind_seen:
            kind, kind_seen = _KINDS[token], True
        elif token in ("longitude_first", "easting_first"):
            standard = False
        elif token == "S":
            south = True
        elif _ZONE.match(token):
            zone = int(_ZONE.match(token).group(1))
        elif ellipsoid is None and ellipsoid_axes(token) is not None:
            ellipsoid = ellipsoid_axes(token)
    a, c = ellipsoid or ellipsoid_axes("WE")
    if kind == "WM":   # Web Mercator is on WGS 84 and its coordinates are x (easting), y (northing), elevation
        (a, c), standard = ellipsoid_axes("WE"), False
    return GeoSystem(kind, a, c, standard, zone, south)


def _geodetic_to_geocentric(gs: GeoSystem, lat, lon, height):
    """Radians and metres to geocentric metres, on gs's ellipsoid. Works on numpy arrays or scalars."""
    c2a2 = (gs.c / gs.a) ** 2
    ecc2 = 1.0 - c2a2
    slat, clat = np.sin(lat), np.cos(lat)
    n = gs.a / np.sqrt(1.0 - ecc2 * slat * slat)
    r = (n + height) * clat
    return r * np.cos(lon), r * np.sin(lon), (n * c2a2 + height) * slat


_N0, _E0, _K0 = 1.0e7, 5.0e5, 0.9996   # UTM false northing (southern hemisphere), false easting, scale on the meridian


def _utm_to_geodetic(gs: GeoSystem, northing, easting):
    """UTM zone gs.zone to latitude and longitude in radians (Snyder, Map Projections, the inverse series)."""
    a, c = gs.a, gs.c
    ecc2 = 1.0 - (c / a) ** 2
    ee = ecc2 / (1.0 - ecc2)
    e1 = (1.0 - math.sqrt(1.0 - ecc2)) / (1.0 + math.sqrt(1.0 - ecc2))
    if gs.south:
        northing = northing - _N0
    easting = easting - _E0
    mu = northing / (_K0 * a * (1.0 - ecc2 / 4.0 - 3.0 * ecc2 ** 2 / 64.0 - 5.0 * ecc2 ** 3 / 256.0))
    phi1 = (mu + (3.0 * e1 / 2.0 - 27.0 * e1 ** 3 / 32.0) * np.sin(2.0 * mu)
            + (21.0 * e1 ** 2 / 16.0 - 55.0 * e1 ** 4 / 32.0) * np.sin(4.0 * mu)
            + (151.0 * e1 ** 3 / 96.0) * np.sin(6.0 * mu))
    s2, cos1, tan1 = np.sin(phi1) ** 2, np.cos(phi1), np.tan(phi1)
    n1 = a / np.sqrt(1.0 - ecc2 * s2)
    t1 = tan1 ** 2
    c1 = ee * cos1 ** 2
    r1 = a * (1.0 - ecc2) / (1.0 - ecc2 * s2) ** 1.5
    d = easting / (n1 * _K0)
    lat = phi1 - (n1 * tan1 / r1) * (
        d ** 2 / 2.0
        - (5.0 + 3.0 * t1 + 10.0 * c1 - 4.0 * c1 ** 2 - 9.0 * ee) * d ** 4 / 24.0
        + (61.0 + 90.0 * t1 + 298.0 * c1 + 45.0 * t1 ** 2 - 252.0 * ee - 3.0 * c1 ** 2) * d ** 6 / 720.0)
    lon = math.radians(gs.zone * 6 - 183) + (
        d - (1.0 + 2.0 * t1 + c1) * d ** 3 / 6.0
        + (5.0 - 2.0 * c1 + 28.0 * t1 - 3.0 * c1 ** 2 + 8.0 * ee + 24.0 * t1 ** 2) * d ** 5 / 120.0) / cos1
    return lat, lon


def to_geocentric(gs: GeoSystem, c0, c1, c2):
    """Geospatial coordinates as the field holds them (GD: latitude, longitude in degrees, height in metres, or with
    longitude_first; UTM: northing, easting, height, or easting first; WM: x, y, height; GC: x, y, z) to geocentric
    metres, as the tuple (x, y, z) of float64 values or arrays."""
    c0, c1, c2 = (np.asarray(v, dtype=np.float64) for v in (c0, c1, c2))
    if gs.kind == "GC":
        return c0, c1, c2
    if gs.kind == "WM":   # EPSG:3857: longitude is x / a, latitude the inverse Gudermannian of y / a
        return _geodetic_to_geocentric(gs, 2.0 * np.arctan(np.exp(c1 / gs.a)) - math.pi / 2.0, c0 / gs.a, c2)
    if gs.kind == "GD":
        lat, lon = (c0, c1) if gs.standard_order else (c1, c0)
        return _geodetic_to_geocentric(gs, np.radians(lat), np.radians(lon), c2)
    northing, easting = (c0, c1) if gs.standard_order else (c1, c0)
    lat, lon = _utm_to_geodetic(gs, northing, easting)
    return _geodetic_to_geocentric(gs, lat, lon, c2)


def geocentric_to_geodetic(gs: GeoSystem, x, y, z):
    """Geocentric metres to (latitude, longitude, height) in radians and metres, on gs's ellipsoid (the iteration
    X_ITE uses; a point on the polar axis comes back with longitude 0)."""
    a = gs.a
    ecc2 = 1.0 - (gs.c / a) ** 2
    p = math.hypot(x, y)
    if p == 0.0:
        return math.copysign(math.pi / 2.0, z), 0.0, abs(z) - gs.c
    lon = math.atan2(y, x)
    lat, height, n = 0.0, 0.0, a
    for _ in range(30):
        h0, b0 = height, lat
        lat = math.atan(z / p / (1.0 - ecc2 * n / (n + height)))
        n = a / math.sqrt(1.0 - ecc2 * math.sin(lat) ** 2)
        height = p / math.cos(lat) - n
        if abs(height - h0) < 1e-3 and abs(lat - b0) < 1e-10:
            break
    return lat, lon, height


def local_frame(gs: GeoSystem, point):
    """The 3 x 3 rotation whose columns are the local east, up and south directions at a geocentric point (up is the
    ellipsoid normal): X3D's local Y-up frame, the one a GeoViewpoint's orientation is relative to and the one a
    GeoOrigin with rotateYUp aligns the scene with."""
    lat, lon, _ = geocentric_to_geodetic(gs, *point)
    up = np.array([math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)])
    east = np.cross([0.0, 0.0, 1.0], up)
    if not east.any():   # on the polar axis
        east = np.array([1.0, 0.0, 0.0])
    south = np.cross(east, up)
    return np.column_stack((east / np.linalg.norm(east), up, south / np.linalg.norm(south)))


def grid_points(gs: GeoSystem, origin, x_dim: int, z_dim: int, x_spacing: float, z_spacing: float, heights):
    """The geocentric points of a GeoElevationGrid, an (x_dim * z_dim, 3) float64 array in X3D's order (point
    z * x_dim + x). X is the longitude (easting) direction and Z the latitude (northing) one: the grid starts at
    ``origin`` (geoGridOrigin, in the field's order) and steps x_spacing and z_spacing (degrees for GD, metres for
    UTM). `heights` (already times yScale) are added to the elevation. As X_ITE 16.7.1 builds it, a GC grid steps
    z_spacing along the first geocentric axis and x_spacing along the second."""
    zz, xx = np.divmod(np.arange(x_dim * z_dim), x_dim)
    first, second = (z_spacing * zz, x_spacing * xx) if gs.standard_order else (x_spacing * xx, z_spacing * zz)
    h = np.zeros(x_dim * z_dim)
    h[:min(len(heights), h.size)] = np.asarray(heights, dtype=np.float64)[:h.size]
    x, y, z = to_geocentric(gs, origin[0] + first, origin[1] + second, origin[2] + h)
    return np.column_stack((x, y, z))
