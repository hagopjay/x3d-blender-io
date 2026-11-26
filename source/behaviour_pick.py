# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The four pick sensors (Picking component): LinePickSensor, PointPickSensor, PrimitivePickSensor, VolumePickSensor.

Pure data and geometry here, no Blender and no import of ``behaviour_sim``: ``machines(Machine, WorldSensor)`` makes the
four machines from the simulator's own base classes and ``behaviour_sim`` registers them at its end.

A ``PickScene`` is read from the X3D document once (``World.from_x3d`` calls ``build``): every Shape that can be a pick target
(its geometry, the frame it sits in, the chain of grouping nodes above it, the ``PickableGroup`` gates on the way), and every
pick sensor (its frame, its ``pickingGeometry``, the nodes its ``pickTarget`` names). A sensor asks the ``World`` for matrices
(the frames move when a ROUTE moves a Transform) and the scene for the shapes it may pick.

What X_ITE 16.8.1 does, from its source (PickingComponent.js, Shape and group traversal) and from recordings
(tests/behaviour/probe-pick.x3d; docs/BEHAVIOUR_EVENT_NODES.md, "P4 results"); the machines follow it:

* Every scene is under an implicit PickableGroup (the Layer's), so all shapes are pickable. A ``PickableGroup`` with
  ``pickable`` false, or an ``objectType`` holding NONE, hides everything below it; one that holds ALL leaves the filter as
  it was; any other lets through the sensors whose ``objectType`` meets its own, by ``matchCriterion`` (MATCH_EVERY needs the
  sensor's list to be a single type, because X_ITE counts at most one common type).
* A sensor is picked against the shapes that have one of the nodes its ``pickTarget`` names (a Shape, a grouping node) among
  the nodes above them or are one. Its own position (the matrix of the group it sits in) moves its ``pickingGeometry``.
* BOUNDS: the bounding box of the picking geometry, carried by the sensor's matrix, meets the bounding box of the target's
  geometry, carried by the shape's matrix (separating axis test of two parallelepipeds: touching counts). A geometry with no
  vertices has a box that is a point at its origin, not an empty one. ``isActive`` and ``pickedGeometry`` are sent when they
  change; BOUNDS sends none of the vector outputs.
* ``sortOrder``: CLOSEST and ANY report the one geometry (CLOSEST: the nearest by the distance between the centres of the
  two boxes, by X_ITE's own quicksort); ALL the geometries in scene order; ALL_SORTED the same sorted.
* A sensor that is the only child of its group is never picked by X_ITE 16.8.1 (its group is not rebuilt after the sensor
  goes live; a sibling Shape with a geometry, or a light, rebuilds it). Such a sensor sends nothing, and is named in
  ``noted["pick-lone-sensor"]``. A sensor whose group is hidden by a PickableGroup has nothing to pick with and is not active.
* A sensor with ``enabled`` false, or an ``objectType`` holding NONE, is out of X_ITE's set: it sends nothing (``isActive``
  stays as it was).
"""

from __future__ import annotations

import math
import struct

try:
    from . import behaviour_world as bw
except ImportError:  # imported as a plain module: tests, tools/
    import behaviour_world as bw

SENSORS = ("LinePickSensor", "PointPickSensor", "PrimitivePickSensor", "VolumePickSensor")
PICKING_GEOMETRY = {"LinePickSensor": ("IndexedLineSet", "LineSet"), "PointPickSensor": ("PointSet",),
                    "PrimitivePickSensor": ("Box", "Cone", "Cylinder", "Sphere"), "VolumePickSensor": None}   # None: any
_GROUPING = {"Group", "Transform", "Switch", "Anchor", "Billboard", "Collision", "LOD", "StaticGroup", "CADAssembly",
             "CADLayer", "CADPart", "CADFace", "PickableGroup", "HAnimHumanoid", "HAnimJoint", "HAnimSegment", "HAnimSite",
             "GeoLocation", "GeoTransform", "ViewpointGroup", "LayoutGroup", "ScreenGroup", "EspduTransform"}
_APPROXIMATED_GROUPING = {"LOD", "Billboard", "HAnimHumanoid", "HAnimJoint", "HAnimSegment", "HAnimSite", "GeoLocation",
                          "GeoTransform", "LayoutGroup", "ScreenGroup", "EspduTransform", "ViewpointGroup"}
_LIGHTS = {"PointLight", "DirectionalLight", "SpotLight"}
_PICK_SENSORS = set(SENSORS)
_FILLED = {"Box", "Sphere", "Cone", "Cylinder", "IndexedFaceSet", "TriangleSet", "PointSet", "IndexedLineSet", "LineSet"}
_GEOMETRY_TAGS = _FILLED | {"ElevationGrid", "Extrusion", "IndexedTriangleSet", "IndexedQuadSet", "QuadSet",
                            "TriangleFanSet", "TriangleStripSet", "IndexedTriangleFanSet", "IndexedTriangleStripSet",
                            "Text", "Arc2D", "ArcClose2D", "Circle2D", "Disk2D", "Polyline2D", "Polypoint2D", "Rectangle2D",
                            "TriangleSet2D", "NurbsCurve", "NurbsPatchSurface", "NurbsSweptSurface", "NurbsSwungSurface",
                            "NurbsTrimmedSurface", "GeoElevationGrid", "Contour2D", "FillProperties"}


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


# ---------------------------------------------------------------------------------------------------------------
# Boxes: what a bounding box is, and X_ITE's test of two of them (Box3.intersectsBox)
# ---------------------------------------------------------------------------------------------------------------

class Obb:
    """A parallelepiped: ``center`` and the three half axes (each a 3-vector, signed as X_ITE's matrix holds them), the box a
    geometry's bounding box becomes under a matrix. ``radius`` is the radius of a ball that holds it (the broad phase)."""
    __slots__ = ("center", "axes", "radius", "frame")

    def __init__(self, center, axes):
        self.center, self.axes = center, axes
        self.radius = sum(math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]) for a in axes)
        self.frame = None            # (unit axes, lengths) when the three axes are square to each other and none is flat; else False

    def unit(self):
        """The axes as unit vectors and lengths, or False for a box that is sheared, flat or not finite (the quick test of
        ``boxes_meet_quick`` is then not used)."""
        if self.frame is None:
            self.frame = False
            lengths = [math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]) for a in self.axes]
            if all(1e-9 < n < 1e12 for n in lengths):
                units = tuple((a[0] / n, a[1] / n, a[2] / n) for a, n in zip(self.axes, lengths))
                if all(abs(units[i][0] * units[j][0] + units[i][1] * units[j][1] + units[i][2] * units[j][2]) < 1e-9
                       for i, j in ((0, 1), (0, 2), (1, 2))):
                    self.frame = (units, tuple(lengths))
        return self.frame


def obb_of(center, half, matrix):
    """The box of a bounding box (``center``, ``half`` sizes) in a frame, seen from the world through ``matrix``."""
    return Obb(bw.m_point(matrix, center),
               tuple(bw.m_dir(matrix, tuple(half[k] if j == k else 0.0 for k in range(3))) for j in range(3)))


def _corners(box):
    x, y, z = box.axes
    r1 = bw._add(y, z)
    r2 = bw._sub(z, y)
    first = [bw._add(bw._add(x, r1), box.center), bw._add(bw._sub(r1, x), box.center),
             bw._add(bw._sub(r2, x), box.center), bw._add(bw._add(x, r2), box.center)]
    return first + [(2 * box.center[0] - p[0], 2 * box.center[1] - p[1], 2 * box.center[2] - p[2])
                    for p in (first[2], first[3], first[0], first[1])]


def _apart(axes, points1, points2):
    """``behaviour_world._separated`` with the arithmetic written out (the same products, summed in the same order, so the
    same answers; it is the cost of the exact test): True when the corner sets do not overlap on some axis."""
    for ax, ay, az in axes:
        low1 = high1 = None
        for p in points1:
            d = p[0] * ax + p[1] * ay + p[2] * az
            if low1 is None:
                low1 = high1 = d
            elif d < low1:
                low1 = d
            elif d > high1:
                high1 = d
        low2 = high2 = None
        for p in points2:
            d = p[0] * ax + p[1] * ay + p[2] * az
            if low2 is None:
                low2 = high2 = d
            elif d < low2:
                low2 = d
            elif d > high2:
                high2 = d
        if not ((low1 <= low2 <= high1) or (low2 <= low1 <= high2)):
            return True
    return False


def boxes_meet_quick(a, b):
    """The same question for two boxes that are square (the usual case) by the radius form of the separating axis test: True
    or False when every axis is clear of touching by a margin far above rounding, else None (the caller runs the exact test,
    which also decides everything this does not: a sheared or flat box, touching, edges nearly parallel)."""
    fa, fb = a.unit(), b.unit()
    if not fa or not fb:
        return None
    (ua, ea), (ub, eb) = fa, fb
    t = (b.center[0] - a.center[0], b.center[1] - a.center[1], b.center[2] - a.center[2])
    tol = 1e-9 * (ea[0] + ea[1] + ea[2] + eb[0] + eb[1] + eb[2] + abs(t[0]) + abs(t[1]) + abs(t[2]) + 1e-300)
    ta = [t[0] * u[0] + t[1] * u[1] + t[2] * u[2] for u in ua]
    r = [[ua[i][0] * ub[j][0] + ua[i][1] * ub[j][1] + ua[i][2] * ub[j][2] for j in range(3)] for i in range(3)]
    ab = [[abs(v) for v in row] for row in r]
    clear = True
    for i in range(3):
        slack = abs(ta[i]) - (ea[i] + eb[0] * ab[i][0] + eb[1] * ab[i][1] + eb[2] * ab[i][2])
        if slack > tol:
            return False
        if slack > -tol:
            clear = False
    for j in range(3):
        tb = ta[0] * r[0][j] + ta[1] * r[1][j] + ta[2] * r[2][j]
        slack = abs(tb) - (ea[0] * ab[0][j] + ea[1] * ab[1][j] + ea[2] * ab[2][j] + eb[j])
        if slack > tol:
            return False
        if slack > -tol:
            clear = False
    for i in range(3):
        i1, i2 = (i + 1) % 3, (i + 2) % 3
        for j in range(3):
            j1, j2 = (j + 1) % 3, (j + 2) % 3
            sin2 = 1.0 - r[i][j] * r[i][j]
            if sin2 < 1e-6:
                if sin2 > 1e-24 or sin2 < -1e-6:
                    clear = False            # edges nearly parallel: X_ITE's own rounding decides
                continue                     # exactly parallel: its cross product is zero and separates nothing
            d = abs(ta[i2] * r[i1][j] - ta[i1] * r[i2][j])
            slack = d - (ea[i1] * ab[i2][j] + ea[i2] * ab[i1][j] + eb[j1] * ab[i][j2] + eb[j2] * ab[i][j1])
            if slack > tol * math.sqrt(sin2):
                return False
            if slack > -tol * math.sqrt(sin2):
                clear = False
    return True if clear else None


def boxes_meet(a, b):
    """X_ITE's ``Box3.intersectsBox`` for two boxes (boxes are never empty here): the three face normals of each, then the nine
    cross products of the axes; a gap on any of them separates. Touching boxes meet."""
    quick = boxes_meet_quick(a, b)
    if quick is not None:
        return quick
    points_a, points_b = _corners(a), _corners(b)
    if _apart(bw._box_normals(*a.axes), points_a, points_b):
        return False
    if _apart(bw._box_normals(*b.axes), points_a, points_b):
        return False
    crosses = [bw._cross(p, q) for p in a.axes for q in b.axes]
    return not _apart(crosses, points_a, points_b)


def quicksort(items, less):
    """X_ITE's QuickSort (Hoare's scheme, ``compare(a, b)`` is "a before b"): not stable, so equal distances come out in the
    order it leaves them."""
    items = list(items)

    def sort(lo, hi):
        i, j = lo, hi
        pivot = items[(lo + hi) >> 1]
        while True:
            while less(items[i], pivot):
                i += 1
            while less(pivot, items[j]):
                j -= 1
            if i < j:
                items[i], items[j] = items[j], items[i]
                i += 1
                j -= 1
            else:
                if i == j:
                    i += 1
                    j -= 1
                break
        if lo < j:
            sort(lo, j)
        if i < hi:
            sort(i, hi)

    if len(items) > 1:
        sort(0, len(items) - 1)
    return items


# ---------------------------------------------------------------------------------------------------------------
# Geometry: the part of a geometry node a pick needs
# ---------------------------------------------------------------------------------------------------------------

class Geom:
    """A geometry node as the pick sensors see it: ``kind`` (the node's name), ``name`` (its DEF, or "Kind#n"), ``center`` and
    ``half`` of its bounding box in its own coordinates (X_ITE: ``getBBox``), and what the exact tests need: ``params``
    (a Box's size, a Sphere's radius ...), ``points`` (the coordinate points, in the order of the Coordinate) and ``segments``
    (index pairs of an IndexedLineSet or LineSet)."""
    __slots__ = ("kind", "name", "center", "half", "params", "points", "segments", "faces")

    def __init__(self, kind, name, center=(0.0, 0.0, 0.0), half=(0.0, 0.0, 0.0), params=(), points=(), segments=(),
                 faces=()):
        self.kind, self.name, self.center, self.half = kind, name, tuple(center), tuple(half)
        self.params, self.points, self.segments, self.faces = tuple(params), tuple(points), tuple(segments), tuple(faces)


def _floats(text, count=None, default=None):
    """The numbers of an attribute; ``default`` (and False for the caller) when it is not numbers, or not ``count`` of them."""
    try:
        values = tuple(float(v) for v in str(text).replace(",", " ").split())
    except ValueError:
        return default
    if not all(math.isfinite(v) for v in values) or (count is not None and len(values) != count):
        return default
    return values


def _float(text, default):
    try:
        value = float(text)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _bool(text, default):
    return default if text is None else str(text).strip().lower() != "false"


def _extent(points):
    """(center, half) of the box round ``points``; with none, a point at the origin (X_ITE: ``setExtents(0, 0)``)."""
    if not points:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    low = tuple(min(p[k] for p in points) for k in range(3))
    high = tuple(max(p[k] for p in points) for k in range(3))
    return tuple((low[k] + high[k]) / 2 for k in range(3)), tuple((high[k] - low[k]) / 2 for k in range(3))


def _coordinate(element, by_def):
    """The points of the Coordinate (or CoordinateDouble) child of a geometry element, or []."""
    for child in element:
        if _local(child.tag) in ("Coordinate", "CoordinateDouble"):
            child = _resolve(child, by_def)
            numbers = _floats(child.get("point", ""), None, ())
            return [tuple(numbers[i:i + 3]) for i in range(0, len(numbers) - 2, 3)]
    return []


def _resolve(element, by_def):
    use = element.get("USE")
    if use is not None:
        return by_def.get(use, element)
    return element


def _runs(indices):
    """The index lists between -1s."""
    run = []
    for index in indices:
        if index < 0:
            if run:
                yield run
            run = []
        else:
            run.append(index)
    if run:
        yield run


def parse_geometry(element, by_def, counter):
    """The ``Geom`` of a geometry element (a USE is followed), or None when it is a kind this module has no box for."""
    element = _resolve(element, by_def)
    kind = _local(element.tag)
    name = element.get("DEF") or f"{kind}#{next(counter)}"
    if kind == "Box":
        size = _floats(element.get("size"), 3, (2.0, 2.0, 2.0))
        half = tuple(abs(v) / 2 for v in size)
        return Geom(kind, name, (0.0, 0.0, 0.0), half, params=size)
    if kind == "Sphere":
        radius = abs(_float(element.get("radius"), 1.0))
        return Geom(kind, name, (0.0, 0.0, 0.0), (radius,) * 3, params=(radius,))
    if kind in ("Cone", "Cylinder"):
        radius = _float(element.get("bottomRadius" if kind == "Cone" else "radius"), 1.0)
        height = _float(element.get("height"), 2.0)
        side, bottom = _bool(element.get("side"), True), _bool(element.get("bottom"), True)
        top = _bool(element.get("top"), True) if kind == "Cylinder" else False
        y1 = height / 2
        y2 = -y1
        if kind == "Cone":
            low, high = ((0.0,) * 3, (0.0,) * 3) if not side and not bottom else \
                ((-radius, y2, -radius), (radius, y2, radius)) if not side else ((-radius, y2, -radius), (radius, y1, radius))
        elif not top and not side and not bottom:
            low = high = (0.0, 0.0, 0.0)
        elif not top and not side:
            low, high = (-radius, y2, -radius), (radius, y2, radius)
        elif not bottom and not side:
            low, high = (-radius, y1, -radius), (radius, y1, radius)
        else:
            low, high = (-radius, y2, -radius), (radius, y1, radius)
        return Geom(kind, name, tuple((low[k] + high[k]) / 2 for k in range(3)),
                    tuple((high[k] - low[k]) / 2 for k in range(3)), params=(radius, height))
    if kind == "PointSet":
        points = _coordinate(element, by_def)
        center, half = _extent(points)
        return Geom(kind, name, center, half, points=points)
    if kind == "IndexedLineSet":
        points = _coordinate(element, by_def)
        indices = _floats(element.get("coordIndex", ""), None, ())
        runs = [r for r in _runs(int(v) for v in indices) if all(i < len(points) for i in r)]
        used = [points[i] for r in runs if len(r) > 1 for i in r]
        segments = [(points[r[i]], points[r[i + 1]]) for r in runs for i in range(len(r) - 1)]
        center, half = _extent(used)
        return Geom(kind, name, center, half, points=points, segments=segments)
    if kind == "LineSet":
        points = _coordinate(element, by_def)
        counts = [int(v) for v in _floats(element.get("vertexCount", ""), None, ())]
        segments, used, at = [], [], 0
        for count in counts:
            if count < 2 or at + count > len(points):
                at += max(count, 0)
                continue
            run = points[at:at + count]
            used += run
            segments += [(run[i], run[i + 1]) for i in range(count - 1)]
            at += count
        center, half = _extent(used)
        return Geom(kind, name, center, half, points=points, segments=segments)
    if kind == "IndexedFaceSet":
        points = _coordinate(element, by_def)
        indices = [int(v) for v in _floats(element.get("coordIndex", ""), None, ())]
        faces = [r for r in _runs(indices) if len(r) >= 3 and all(i < len(points) for i in r)]
        used = [points[i] for r in faces for i in r]
        center, half = _extent(used)
        return Geom(kind, name, center, half, points=points, faces=faces)
    if kind == "TriangleSet":
        points = _coordinate(element, by_def)
        used = points[:len(points) - len(points) % 3]
        center, half = _extent(used)
        return Geom(kind, name, center, half, points=points)
    return None


# ---------------------------------------------------------------------------------------------------------------
# GEOMETRY: the shapes whose contact is worked out exactly (Box and Sphere; points; the segments of a line set)
# ---------------------------------------------------------------------------------------------------------------

_BOX_CORNERS = ((1, 1, 1), (-1, 1, 1), (-1, -1, 1), (1, -1, 1), (1, 1, -1), (-1, 1, -1), (-1, -1, -1), (1, -1, -1))
_BOX_QUADS = ((0, 1, 2, 3), (5, 4, 7, 6), (1, 5, 6, 2), (4, 0, 3, 7), (4, 5, 1, 0), (3, 2, 6, 7))
_QUAD_TEX = ((1.0, 1.0), (0.0, 1.0), (0.0, 0.0), (1.0, 0.0))
# X_ITE's Box is an IndexedFaceSet of six quads, each cut into the triangles (0 1 2) and (0 2 3): 12 triangles of
# (corner indices, normal, texture coordinates), in the order its intersectsLine walks them (checked against the arrays
# X_ITE 16.8.1 holds: ``B.getBoxOptions().getGeometry()``).
_BOX_TRIANGLES = tuple(
    (tuple(_BOX_CORNERS[q[i]] for i in tri),
     tuple(bw._unit(bw._cross(bw._sub(_BOX_CORNERS[q[tri[1]]], _BOX_CORNERS[q[tri[0]]]),
                              bw._sub(_BOX_CORNERS[q[tri[2]]], _BOX_CORNERS[q[tri[0]]])))),
     tuple(_QUAD_TEX[i] for i in tri))
    for q in _BOX_QUADS for tri in ((0, 1, 2), (0, 2, 3)))


def rigid(matrix):
    """(axes, scales) of a matrix when it is a turn and a scale along the turned axes (no shear, no mirror, no flattening):
    what X_ITE's Ammo path reads out of a matrix (``getTransform``) and uses as it is. None otherwise."""
    axes = [(matrix[0], matrix[4], matrix[8]), (matrix[1], matrix[5], matrix[9]), (matrix[2], matrix[6], matrix[10])]
    scales = [math.sqrt(bw._dot(a, a)) for a in axes]
    if not all(math.isfinite(k) and k > 1e-12 for k in scales):
        return None
    top = max(scales)
    for i in range(3):
        j = (i + 1) % 3
        if abs(bw._dot(axes[i], axes[j])) > 1e-9 * scales[i] * scales[j]:
            return None
    if bw._dot(bw._cross(axes[0], axes[1]), axes[2]) <= 0 or min(scales) < 1e-9 * top:
        return None
    return axes, scales


MARGIN = 0.015          # fitted, not read from Ammo: pg.json agrees stream for stream for any value in 0.01 to 0.0225 (a box is its core grown by this much)


def margin_of(half):
    """The margin of a btBoxShape of these (unscaled) half sizes: 0.04, or a tenth of the least half size when that is less."""
    return min(MARGIN, 0.1 * min(half))


def core_of(box, margin):
    """The core of a rounded box: the same box with each half axis shorter by ``margin`` (not below nothing)."""
    axes = []
    for axis in box.axes:
        length = math.sqrt(bw._dot(axis, axis))
        keep = max(length - margin, 0.0) / length if length > 0 else 0.0
        axes.append(tuple(c * keep for c in axis))
    return Obb(box.center, tuple(axes))


def distance_point_box(point, box):
    """How far ``point`` is from the box (zero inside)."""
    offset = bw._sub(point, box.center)
    total = 0.0
    for axis in box.axes:
        length = math.sqrt(bw._dot(axis, axis))
        if length == 0.0:
            continue
        outside = abs(bw._dot(offset, axis)) / length - length
        if outside > 0:
            total += outside * outside
    # the part of the offset not along any axis (a box of no thickness): its own distance
    along = [bw._dot(offset, ax) / bw._dot(ax, ax) if bw._dot(ax, ax) > 0 else 0.0 for ax in box.axes]
    rest = offset
    for ax, k in zip(box.axes, along):
        rest = bw._sub(rest, tuple(c * k for c in ax))
    return math.sqrt(total + bw._dot(rest, rest)) if any(bw._dot(ax, ax) == 0.0 for ax in box.axes) else math.sqrt(total)


def _segment_distance2(p1, q1, p2, q2):
    """The least squared distance between segments p1 q1 and p2 q2 (Ericson, Real-Time Collision Detection)."""
    d1, d2, r = bw._sub(q1, p1), bw._sub(q2, p2), bw._sub(p1, p2)
    a, e, f = bw._dot(d1, d1), bw._dot(d2, d2), bw._dot(d2, r)
    if a <= 1e-30 and e <= 1e-30:
        s = t = 0.0
    elif a <= 1e-30:
        s, t = 0.0, min(max(f / e, 0.0), 1.0)
    else:
        c = bw._dot(d1, r)
        if e <= 1e-30:
            t, s = 0.0, min(max(-c / a, 0.0), 1.0)
        else:
            b = bw._dot(d1, d2)
            denom = a * e - b * b
            s = min(max((b * f - c * e) / denom, 0.0), 1.0) if denom > 1e-30 else 0.0
            t = (b * s + f) / e
            if t < 0.0:
                t, s = 0.0, min(max(-c / a, 0.0), 1.0)
            elif t > 1.0:
                t, s = 1.0, min(max((b - c) / a, 0.0), 1.0)
    c1 = tuple(p1[k] + d1[k] * s for k in range(3))
    c2 = tuple(p2[k] + d2[k] * t for k in range(3))
    d = bw._sub(c1, c2)
    return bw._dot(d, d)


_EDGES = tuple((i, j) for i in range(8) for j in range(i + 1, 8) if bin(i ^ j).count("1") == 1)


def _vertices(box):
    x, y, z = box.axes
    return [tuple(box.center[k] + sx * x[k] + sy * y[k] + sz * z[k] for k in range(3))
            for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]


def distance_box_box(a, b):
    """The least distance between two boxes (zero when they overlap or touch): separating axes say whether they overlap; if
    not, the nearest pair of features is a vertex and a box, or an edge and an edge."""
    points_a, points_b = _corners(a), _corners(b)
    axes = list(a.axes) + list(b.axes) + [bw._cross(p, q) for p in a.axes for q in b.axes]
    gap = 0.0
    for axis in axes:
        norm = math.sqrt(bw._dot(axis, axis))
        if norm == 0.0:
            continue
        pa = [bw._dot(p, axis) / norm for p in points_a]
        pb = [bw._dot(p, axis) / norm for p in points_b]
        gap = max(gap, min(pb) - max(pa), min(pa) - max(pb))
    if gap <= 0.0:
        return 0.0
    va, vb = _vertices(a), _vertices(b)
    best = min(min(distance_point_box(p, b) for p in va), min(distance_point_box(p, a) for p in vb))
    best *= best
    for i, j in _EDGES:
        for k, m in _EDGES:
            best = min(best, _segment_distance2(va[i], va[j], vb[k], vb[m]))
    return math.sqrt(best)


def line_meets_box_bounds(p1, direction, low, high):
    """X_ITE's ``intersectsBBox`` for the line through ``p1``: it looks at five faces of the box (not the left one)."""
    for axis, plane, others in ((2, high[2], (0, 1)), (2, low[2], (0, 1)), (1, high[1], (0, 2)), (1, low[1], (0, 2)),
                                (0, high[0], (1, 2))):
        if direction[axis] == 0.0:
            continue
        t = (plane - p1[axis]) / direction[axis]
        hit = tuple(p1[k] + direction[k] * t for k in range(3))
        if all(low[k] <= hit[k] <= high[k] for k in others):
            return True
    return False


def segment_hits_box(p1, p2, half):
    """[(point, normal, texture coordinate)] where the segment p1 p2 (in the box's own coordinates) meets the surface of X_ITE's
    Box of half sizes ``half`` (its triangles, front and back faces, a line through an edge meeting two of them), the way
    ``X3DGeometryNode.intersectsLine`` finds them: the infinite line through the points against each triangle, then the hits
    that are within the segment."""
    length = math.dist(p1, p2)
    if not math.isfinite(length) or length == 0.0:
        return []
    direction = tuple((p2[k] - p1[k]) / length for k in range(3))
    low, high = tuple(-h for h in half), tuple(half)
    if not line_meets_box_bounds(p1, direction, low, high):
        return []
    found = []
    for corners, normal, texture in _BOX_TRIANGLES:
        a, b, c = (tuple(corner[k] * half[k] for k in range(3)) for corner in corners)
        edge1, edge2 = bw._sub(b, a), bw._sub(c, a)
        pvec = bw._cross(direction, edge2)
        det = bw._dot(edge1, pvec)
        if det == 0.0:
            continue
        inverse = 1 / det
        tvec = bw._sub(p1, a)
        u = bw._dot(tvec, pvec) * inverse
        if u < 0 or u > 1:
            continue
        qvec = bw._cross(tvec, edge1)
        v = bw._dot(direction, qvec) * inverse
        if v < 0 or u + v > 1:
            continue
        weights = (1 - u - v, u, v)
        point = tuple(weights[0] * a[k] + weights[1] * b[k] + weights[2] * c[k] for k in range(3))
        mid = bw._add(bw._sub(point, p1), bw._sub(point, p2))
        if math.sqrt(bw._dot(mid, mid)) <= length:
            norm = tuple(sum(w * normal[k] for w in weights) for k in range(3))
            total = sum(weights)
            tex = tuple(sum(w * t[k] for w, t in zip(weights, texture)) / total for k in range(2)) + (0.0,)
            found.append((point, norm, tex))
    return found


# ---------------------------------------------------------------------------------------------------------------
# The scene
# ---------------------------------------------------------------------------------------------------------------

class Gate:
    """A PickableGroup on the way to a shape (or to a sensor): ``pickable`` and ``objectType`` change by ROUTE."""
    __slots__ = ("name", "pickable", "object_type")

    def __init__(self, name, pickable, object_type):
        self.name, self.pickable, self.object_type = name, pickable, tuple(object_type)


class PickShape:
    """A Shape that can be picked, where it is (``frame``: a key of ``World.frames`` or None for the scene root)."""
    __slots__ = ("geom", "frame", "chain", "gates", "index", "matrix", "box")

    def __init__(self, geom, frame, chain, gates, index):
        self.geom, self.frame, self.chain, self.gates, self.index = geom, frame, chain, gates, index
        self.matrix = self.box = None


class PickSensor:
    """A pick sensor of the scene: where it sits, what it picks with and what its ``pickTarget`` names."""
    __slots__ = ("name", "kind", "frame", "geom", "targets", "gates", "alive", "bad_geometry")

    def __init__(self, name, kind, frame, geom, targets, gates, alive, bad_geometry):
        self.name, self.kind, self.frame, self.geom, self.targets = name, kind, frame, geom, targets
        self.gates, self.alive, self.bad_geometry = gates, alive, bad_geometry


class PickScene:
    def __init__(self):
        self.shapes = []             # PickShape in scene order (X_ITE collects targets in traversal order)
        self.sensors = {}            # DEF -> PickSensor
        self.gates = {}              # DEF of a PickableGroup -> Gate
        self.version = 0             # counts changes of a gate
        self.noted = {}

    def note(self, what):
        self.noted[what] = self.noted.get(what, 0) + 1

    def watches(self, name):
        return name in self.gates

    def apply(self, name, field_name, value):
        """A ROUTE delivered ``value`` to ``field_name`` of the PickableGroup ``name``; True when it was a field that matters."""
        gate = self.gates.get(name)
        if gate is None:
            return False
        if field_name == "pickable" and isinstance(value, bool):
            gate.pickable = value
        elif field_name == "objectType" and isinstance(value, list) and all(isinstance(v, str) for v in value):
            gate.object_type = tuple(value)
        else:
            return False
        self.version += 1
        return True


def _passes(gate, sensor_types, criterion):
    """May a sensor with these ``objectType`` values and ``matchCriterion`` see through ``gate``? (PickableGroup.traverse)"""
    if not gate.pickable or "NONE" in gate.object_type:
        return False
    if "ALL" in gate.object_type or "ALL" in sensor_types:
        return True
    shared = 1 if any(t in sensor_types for t in gate.object_type) else 0       # X_ITE counts at most one
    if criterion == "MATCH_EVERY":
        return shared == len(set(sensor_types))
    if criterion == "MATCH_ONLY_ONE":
        return shared == 1
    return shared != 0


def _reaches(gates):
    """Is a node under these gates traversed at all (a hidden PickableGroup stops X_ITE's picking traversal)?"""
    return all(g.pickable and "NONE" not in g.object_type for g in gates)


def eligible(scene, sensor, object_type, criterion):
    """The shapes ``sensor`` collects as targets, in scene order, for the sensor's current ``objectType`` list and
    ``matchCriterion`` (X_ITE: ``collect`` is only called for sensors in the stack of the PickableGroups above the shape)."""
    found = []
    for shape in scene.shapes:
        if not (shape.chain & sensor.targets):
            continue
        if all(_passes(g, object_type, criterion) for g in shape.gates):
            found.append(shape)
    return found


class _Builder:
    """Reads the document in X_ITE's order: groups, Shapes and pick sensors, with the frame of each Transform from the World."""

    def __init__(self, by_def, frames):
        self.by_def, self.frames, self.scene = by_def, frames, PickScene()
        self.counter = _Counter()
        self.sensor_elements = []

    def walk(self, children, frame, chain, gates, root=False):
        for child in children:
            tag = _local(child.tag)
            if child.get("containerField", "children") != "children":
                continue
            if tag in _PICK_SENSORS:
                if child.get("USE") is None and child.get("DEF"):
                    self.sensor_elements.append((child, frame, gates, root, children))
                continue
            node = _resolve(child, self.by_def)
            tag = _local(node.tag)
            if tag == "Shape":
                geometry = next((c for c in node if c.get("containerField", "geometry") == "geometry"
                                 and _local(_resolve(c, self.by_def).tag) in _GEOMETRY_TAGS), None)
                if geometry is None or not _bool(node.get("visible"), True):
                    continue
                geom = parse_geometry(geometry, self.by_def, self.counter)
                if geom is None:
                    self.scene.note("pick-no-volume")
                    continue
                self.scene.shapes.append(PickShape(geom, frame, frozenset(chain | {id(node)}), gates, len(self.scene.shapes)))
            elif tag in _GROUPING:
                if child.get("USE") is not None:
                    self.scene.note("use-instance")
                    continue
                if not _bool(child.get("visible"), True):
                    continue
                if tag in _APPROXIMATED_GROUPING:
                    self.scene.note("pick-approximated-group")
                inner_frame = self.frames.get(id(child), frame) if tag == "Transform" else frame
                inner_gates = gates
                if tag == "PickableGroup":
                    gate = Gate(child.get("DEF"), _bool(child.get("pickable"), True),
                                tuple(_strings(child.get("objectType"))) if child.get("objectType") is not None else ("ALL",))
                    if gate.name:
                        self.scene.gates[gate.name] = gate
                    inner_gates = gates + (gate,)
                self.walk(children_of(child, tag), inner_frame, chain | {id(child)}, inner_gates)


def children_of(element, tag):
    """The children X_ITE traverses for picking: all of them, but a Switch's chosen one (``whichChoice`` as the file has it)."""
    kids = [c for c in element if c.get("containerField", "children") == "children"]
    if tag == "Switch":
        choice = int(_float(element.get("whichChoice"), -1.0))
        return [kids[choice]] if 0 <= choice < len(kids) else []
    return kids


class _Counter:
    def __init__(self):
        self.n = 0

    def __iter__(self):
        return self

    def __next__(self):
        self.n += 1
        return self.n


def _strings(text):
    found, current, inside, escaped = [], [], False, False
    for ch in text or "":
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


def _has_picture(element, by_def, depth=0):
    """Does the subtree hold a Shape with a geometry or a light? (what makes X_ITE 16.8.1 rebuild the group a sensor sits in)"""
    element = _resolve(element, by_def)
    tag = _local(element.tag)
    if tag in _LIGHTS:
        return True
    if tag == "Shape":
        return any(c.get("containerField", "geometry") == "geometry" and _local(_resolve(c, by_def).tag) in _GEOMETRY_TAGS
                   for c in element)
    if depth > 200:
        return False
    return any(_has_picture(c, by_def, depth + 1) for c in element if c.get("containerField", "children") == "children")


def build(scene_element, by_def, frames):
    """The ``PickScene`` of a document: ``scene_element`` is its Scene, ``frames`` maps ``id(Transform element)`` to the
    key of its frame in the ``World``."""
    builder = _Builder(by_def, frames)
    builder.walk(list(scene_element), None, frozenset(), (), root=True)
    scene = builder.scene
    for element, frame, gates, root, siblings in builder.sensor_elements:
        kind = _local(element.tag)
        geom, bad, targets = None, False, set()
        for child in element:
            field = child.get("containerField")
            if field == "pickingGeometry":
                resolved = _resolve(child, by_def)
                wanted = PICKING_GEOMETRY[kind]
                geom = None
                if _local(resolved.tag) in _GEOMETRY_TAGS and (wanted is None or _local(resolved.tag) in wanted):
                    geom = parse_geometry(child, by_def, builder.counter)
                bad = geom is None
            elif field == "pickTarget":
                resolved = _resolve(child, by_def)
                if _local(resolved.tag) == "Shape" or _local(resolved.tag) in _GROUPING or _local(resolved.tag) == "Inline":
                    targets.add(id(resolved))
        alive = root or any(_has_picture(s, by_def) for s in siblings if _local(s.tag) not in _PICK_SENSORS)
        scene.sensors[element.get("DEF")] = PickSensor(element.get("DEF"), kind, frame, geom, frozenset(targets), gates,
                                                       alive, bad)
    return scene


# ---------------------------------------------------------------------------------------------------------------
# The machines
# ---------------------------------------------------------------------------------------------------------------

def _round32(value):
    """``value`` (a list of 3-tuples) as X_ITE holds it, in single precision: what its ``equals`` compares."""
    return tuple(tuple(struct.unpack("f", struct.pack("f", c))[0] if abs(c) < 3.4e38 else c for c in v) for v in value)


def machines(Machine, WorldSensor):
    """The four pick sensor machines, built on the simulator's own base classes."""

    class _PickSensor(WorldSensor):
        """The common part: once per step, after the events have settled, the targets the sensor may see are tested against its
        picking geometry; ``isActive`` and ``pickedGeometry`` are sent when they change (and the vector outputs of a
        sensor that finds points)."""
        vector_outputs = ()               # (field, index into a hit's payload) of what GEOMETRY adds

        def setup(self):
            super().setup()
            self.names = ()               # pickedGeometry as last sent
            self.sent = {}                # the vector outputs as last sent (single precision)
            self.cache = None
            self.memo = None
            self.said = set()

        def registered(self):
            """X_ITE: in the browser's set of pick sensors only while enabled and with no NONE in its ``objectType``."""
            return bool(self.f.get("enabled", True)) and "NONE" not in self.f.get("objectType", ["ALL"])

        def say(self, why):
            """Count an approximation once for this sensor (``Simulation.noted``)."""
            if why not in self.said:
                self.said.add(why)
                self.sim.noted[why] = self.sim.noted.get(why, 0) + 1

        def update(self, now):
            world = self.sim.world
            if world is None:
                return self.blind("no-world")
            scene = getattr(world, "pick", None)
            info = scene.sensors.get(self.id) if scene is not None else None
            if info is None:
                return self.blind("no-frame" if scene is not None else "no-pick-scene")
            if not self.registered():
                return
            if not info.alive:
                return self.blind("pick-lone-sensor")
            if info.geom is None:
                if info.bad_geometry:
                    self.blind("no-volume")
                return
            if self.settled(world, scene, info):
                return                    # nothing the answer depends on has changed since the last step
            hits = self.hits(world, scene, info)
            names = tuple(h[0].geom.name for h in hits)
            active = bool(names)
            if active != self.active:
                self.active = active
                self.emit("isActive", active)
            if names != self.names:
                self.names = names
                self.emit("pickedGeometry", list(names))
            if self.vector_outputs:
                self.vectors(hits)

        def settled(self, world, scene, info):
            """True when this step's inputs are the last step's: no frame the answer reads has moved (a frame that moved, or one
            below it, is marked dirty, and gets a new matrix object when asked), the gates are as they were, and so are the
            fields that decide. Remembers what it saw for the next step."""
            f = self.f
            fields = (scene.version, f.get("intersectionType"), f.get("sortOrder"), f.get("matchCriterion"), f.get("objectType"))
            last = self.memo
            if last is not None and last[0] == fields:
                for frame, matrix in last[1]:
                    if frame.dirty or frame.world is not matrix:
                        break
                else:
                    return True
            frames = world.frames
            names = {info.frame}
            names.update(shape.frame for shape in self.shapes_of(scene, info))
            seen = []
            for name in names:
                if name is not None:
                    matrix = world.matrix(name)
                    seen.append((frames[name], matrix))
            self.memo = (fields, seen)
            return False

        def shapes_of(self, scene, info):
            key = (scene.version, tuple(self.f.get("objectType", ["ALL"])), str(self.f.get("matchCriterion", "MATCH_ANY")))
            if self.cache is None or self.cache[0] != key:
                self.cache = (key, eligible(scene, info, key[1], key[2]))
            return self.cache[1]

        def vectors(self, hits):
            """GEOMETRY: the points (and normals, texture coordinates) of every target that was hit, in the order of ``hits``
            (X_ITE reports the same for every ``sortOrder``: all the picked targets, sorted or not by the order)."""
            if str(self.f.get("intersectionType", "BOUNDS")) != "GEOMETRY":
                return
            picked = self.all_hits
            for field_name, index in self.vector_outputs:
                value = [item[index] if index is not None else item for h in picked for item in h[2]]
                key = _round32(value)
                if self.sent.get(field_name, ()) != key:
                    self.sent[field_name] = key
                    self.emit(field_name, value)

        def hits(self, world, scene, info):
            """[(shape, distance, payload)] the sensor picked this step, in the order its ``sortOrder`` reports them."""
            self.all_hits = []
            if not _reaches(info.gates):
                return []                 # the sensor's own group is hidden: nothing carries the picking geometry
            order = str(self.f.get("sortOrder", "CLOSEST"))
            if order not in ("ANY", "CLOSEST", "ALL", "ALL_SORTED"):
                order = "CLOSEST"
            criterion = str(self.f.get("matchCriterion", "MATCH_ANY"))
            matrix = world.matrix(info.frame)
            picker = obb_of(info.geom.center, info.geom.half, matrix)
            geometry = str(self.f.get("intersectionType", "BOUNDS")) == "GEOMETRY"
            found = []
            for shape in self.shapes_of(scene, info):
                box = self.box_of(world, shape)
                reach = picker.radius + box.radius
                d = (picker.center[0] - box.center[0], picker.center[1] - box.center[1], picker.center[2] - box.center[2])
                if d[0] * d[0] + d[1] * d[1] + d[2] * d[2] > reach * reach * (1 + 1e-9) + 1e-12:
                    continue
                payload = self.touch(picker, box, shape, info, matrix, world) if geometry else ()
                if payload is None or (not geometry and not boxes_meet(picker, box)):
                    continue
                found.append((shape, math.dist(picker.center, box.center), payload))
            return self.sorted_hits(found, order)

        def box_of(self, world, shape):
            matrix = world.matrix(shape.frame)
            if shape.matrix is not matrix:
                shape.matrix, shape.box = matrix, obb_of(shape.geom.center, shape.geom.half, matrix)
            return shape.box

        def touch(self, picker, box, shape, info, matrix, world):
            """GEOMETRY: None when the picking geometry and the target's do not touch, else the payload (a list of what the
            vector outputs carry). What this module has no exact test for is BOUNDS, counted in
            ``noted["bounds-for-geometry"]``."""
            if not boxes_meet(picker, box):
                return None
            self.say("bounds-for-geometry")
            return []

        def sorted_hits(self, found, order):
            if order in ("CLOSEST", "ALL_SORTED"):
                found = quicksort(found, lambda a, b: a[1] < b[1])
            self.all_hits = found                      # X_ITE collects the vectors of every picked target
            return found[:1] if order in ("CLOSEST", "ANY") else found

    def _both(info, shape, world, matrix):
        """(sensor frame, target frame) as rigid matrices, or None (and the reason) when one is sheared or flat."""
        ours, theirs = rigid(matrix), rigid(world.matrix(shape.frame))
        return (ours, theirs) if ours is not None and theirs is not None else None

    def _solid(geom, matrix, rigid_parts):
        """(\"box\", Obb) or (\"ball\", centre, radius) for a Box or Sphere of ``geom`` under ``matrix``, else None."""
        axes, scales = rigid_parts
        if geom.kind == "Box":
            margin = margin_of(geom.half)
            return "box", core_of(obb_of(geom.center, geom.half, matrix), margin), margin
        if geom.kind == "Sphere":
            if max(scales) - min(scales) > 1e-9 * max(scales):
                return None                 # X_ITE's ball takes the x scale; an ellipsoid is not simulated
            return "ball", bw.m_point(matrix, geom.center), geom.params[0] * scales[0]
        return None

    def _contact(a, b):
        """Ammo's contact: the distance between the two cores is within the sum of the margins (a ball's core is its centre
        and its margin its radius; a box's core is shorter by its margin all round)."""
        if a[0] == "box" and b[0] == "box":
            return distance_box_box(a[1], b[1]) < a[2] + b[2]
        if a[0] == "ball" and b[0] == "ball":
            return math.dist(a[1], b[1]) <= a[2] + b[2]
        ball, box = (a, b) if a[0] == "ball" else (b, a)
        return distance_point_box(ball[1], box[1]) <= ball[2] + box[2]

    class _ShapePick(_PickSensor):
        """Primitive and Volume: the picking geometry and the target are both a Box or a Sphere, and touch."""

        def touch(self, picker, box, shape, info, matrix, world):
            parts = _both(info, shape, world, matrix)
            first = second = None
            if parts is not None:
                first = _solid(info.geom, matrix, parts[0])
                second = _solid(shape.geom, world.matrix(shape.frame), parts[1])
            if first is None or second is None:
                return _PickSensor.touch(self, picker, box, shape, info, matrix, world)
            return [] if _contact(first, second) else None

    class LinePickSensor(_PickSensor):
        vector_outputs = (("pickedTextureCoordinate", 2), ("pickedNormal", 1), ("pickedPoint", 0))

        def touch(self, picker, box, shape, info, matrix, world):
            if shape.geom.kind != "Box":
                return _PickSensor.touch(self, picker, box, shape, info, matrix, world)
            inverse = bw.m_inverse(world.matrix(shape.frame))
            if inverse is None:
                self.say("singular-frame")
                return None
            carry = bw.m_mul(inverse, matrix)
            half = shape.geom.half
            found = []
            for a, b in info.geom.segments:
                found += segment_hits_box(bw.m_point(carry, a), bw.m_point(carry, b), half)
            return found or None

    class PointPickSensor(_PickSensor):
        vector_outputs = (("pickedPoint", None),)

        def touch(self, picker, box, shape, info, matrix, world):
            parts = _both(info, shape, world, matrix)
            target = _solid(shape.geom, world.matrix(shape.frame), parts[1]) if parts is not None else None
            if target is None:
                return _PickSensor.touch(self, picker, box, shape, info, matrix, world)
            found = []
            for point in info.geom.points:
                at = bw.m_point(matrix, point)
                if (target[0] == "box" and distance_point_box(at, core_of(target[1], -target[2])) <= 0.0) or \
                        (target[0] == "ball" and math.dist(at, target[1]) <= target[2]):
                    found.append(point)
            return found or None

    class PrimitivePickSensor(_ShapePick):
        pass

    class VolumePickSensor(_ShapePick):
        pass

    return {"LinePickSensor": LinePickSensor, "PointPickSensor": PointPickSensor,
            "PrimitivePickSensor": PrimitivePickSensor, "VolumePickSensor": VolumePickSensor}
