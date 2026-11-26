# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Where things are: the World a simulation reads (class B of docs/BEHAVIOUR_EVENT_NODES.md). No Blender in here.

A ``World`` is plain data: the Transform hierarchy (``Frame``: translation, rotation, scale, centre, scale orientation,
and the world matrix they give), named volumes in a frame (``Volume``: a box, a sphere, points or segments), what each
environmental sensor sits in and aims at, the Collision groups and their shapes, and the viewer (``Viewer``: where it is,
which way it looks, its view frustum). ``Simulation`` asks it once per step; it never runs by itself.

    world = World.from_x3d(text)              # for the simulator and the judge
    world = World.from_blender(scene, graph)  # for the Player: behaviour_play.py (it needs bpy; this module does not)
    sim = Simulation(graph, world=world)

A ROUTE that moves a Transform the world knows reaches it through ``World.apply``; a frame's matrix is worked out when
asked for, and only for frames that moved (a moved frame marks its children).

What the queries are exact about, and what X_ITE 16.8.1 does that they follow (read from its source and recorded by
``tests/behaviour/probe-world.x3d``): see docs/BEHAVIOUR_EVENT_NODES.md. In short: ``box_contains`` is the box test a
ProximitySensor and a TransformSensor make; ``frustum_meets_box`` is X_ITE's separating-axis test of a box against the view
volume, including the edge axes it leaves out (its axis table is filled by ``i1 * 3 + i2``, so some cross products
overwrite others); ``collision_hits`` is the depth look X_ITE takes along the six axes of the viewpoint's frame, read at the
centres of the same 16 x 16 pixels.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET

IDENTITY = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)   # row-major, p' = M p
_NAVIGATION_DEFAULTS = {"avatarSize": (0.25, 1.6, 0.75), "visibilityLimit": 0.0}
# X_ITE: near = avatarSize[0] / 2 (0.125 when that is 0); far = visibilityLimit, or 1e5 when that is 0
_MAX_FAR = 1e5
_DEPTH_FAR = 2.0     # collision look reaches max(2 r, 2 avatarHeight)


# ---------------------------------------------------------------------------------------------------------------
# Small linear algebra (tuples, no numpy)
# ---------------------------------------------------------------------------------------------------------------

def _finite(value):
    if isinstance(value, (tuple, list)):
        return all(_finite(item) for item in value)
    if isinstance(value, bool):
        return True
    return isinstance(value, (int, float)) and math.isfinite(value)


def m_mul(a, b):
    # sixteen sums of four products, each added left to right as a loop over rows and columns would: the same bits, without the loop
    a0, a1, a2, a3, a4, a5, a6, a7, a8, a9, a10, a11, a12, a13, a14, a15 = a
    b0, b1, b2, b3, b4, b5, b6, b7, b8, b9, b10, b11, b12, b13, b14, b15 = b
    return (a0 * b0 + a1 * b4 + a2 * b8 + a3 * b12, a0 * b1 + a1 * b5 + a2 * b9 + a3 * b13,
            a0 * b2 + a1 * b6 + a2 * b10 + a3 * b14, a0 * b3 + a1 * b7 + a2 * b11 + a3 * b15,
            a4 * b0 + a5 * b4 + a6 * b8 + a7 * b12, a4 * b1 + a5 * b5 + a6 * b9 + a7 * b13,
            a4 * b2 + a5 * b6 + a6 * b10 + a7 * b14, a4 * b3 + a5 * b7 + a6 * b11 + a7 * b15,
            a8 * b0 + a9 * b4 + a10 * b8 + a11 * b12, a8 * b1 + a9 * b5 + a10 * b9 + a11 * b13,
            a8 * b2 + a9 * b6 + a10 * b10 + a11 * b14, a8 * b3 + a9 * b7 + a10 * b11 + a11 * b15,
            a12 * b0 + a13 * b4 + a14 * b8 + a15 * b12, a12 * b1 + a13 * b5 + a14 * b9 + a15 * b13,
            a12 * b2 + a13 * b6 + a14 * b10 + a15 * b14, a12 * b3 + a13 * b7 + a14 * b11 + a15 * b15)


def m_point(m, p):
    return (m[0] * p[0] + m[1] * p[1] + m[2] * p[2] + m[3], m[4] * p[0] + m[5] * p[1] + m[6] * p[2] + m[7],
            m[8] * p[0] + m[9] * p[1] + m[10] * p[2] + m[11])


def m_dir(m, d):
    return (m[0] * d[0] + m[1] * d[1] + m[2] * d[2], m[4] * d[0] + m[5] * d[1] + m[6] * d[2],
            m[8] * d[0] + m[9] * d[1] + m[10] * d[2])


def m_translate(t):
    return (1.0, 0.0, 0.0, t[0], 0.0, 1.0, 0.0, t[1], 0.0, 0.0, 1.0, t[2], 0.0, 0.0, 0.0, 1.0)


def m_scale(s):
    return (s[0], 0.0, 0.0, 0.0, 0.0, s[1], 0.0, 0.0, 0.0, 0.0, s[2], 0.0, 0.0, 0.0, 0.0, 1.0)


def m_rotate(rotation):
    """The matrix of an X3D axis-angle rotation (an axis of no length is no rotation)."""
    x, y, z, angle = rotation
    length = math.sqrt(x * x + y * y + z * z)
    if length == 0 or angle == 0:
        return IDENTITY
    x, y, z = x / length, y / length, z / length
    c, s = math.cos(angle), math.sin(angle)
    t = 1 - c
    return (t * x * x + c, t * x * y - s * z, t * x * z + s * y, 0.0,
            t * x * y + s * z, t * y * y + c, t * y * z - s * x, 0.0,
            t * x * z - s * y, t * y * z + s * x, t * z * z + c, 0.0,
            0.0, 0.0, 0.0, 1.0)


def m_transform(translation=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 1.0, 0.0), scale=(1.0, 1.0, 1.0),
                center=(0.0, 0.0, 0.0), scale_orientation=(0.0, 0.0, 1.0, 0.0)):
    """P' = T * C * R * SR * S * -SR * -C * P (X3D 4.0, Transform)."""
    m = m_mul(m_translate(translation), m_translate(center))
    m = m_mul(m, m_rotate(rotation))
    if tuple(scale) != (1.0, 1.0, 1.0):
        so = m_rotate(scale_orientation)
        m = m_mul(m_mul(m_mul(m, so), m_scale(scale)), m_rotate((*scale_orientation[:3], -scale_orientation[3])))
    return m_mul(m, m_translate((-center[0], -center[1], -center[2])))


def m_inverse(m):
    """The inverse of an affine matrix, or None when its 3 x 3 part has no inverse."""
    a, b, c, d, e, f, g, h, i = m[0], m[1], m[2], m[4], m[5], m[6], m[8], m[9], m[10]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if not math.isfinite(det) or abs(det) < 1e-300:
        return None
    r = ((e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det,
         (f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det,
         (d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det)
    tx, ty, tz = m[3], m[7], m[11]
    return (r[0], r[1], r[2], -(r[0] * tx + r[1] * ty + r[2] * tz),
            r[3], r[4], r[5], -(r[3] * tx + r[4] * ty + r[5] * tz),
            r[6], r[7], r[8], -(r[6] * tx + r[7] * ty + r[8] * tz),
            0.0, 0.0, 0.0, 1.0)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _unit(a):
    n = math.sqrt(_dot(a, a))
    return (a[0] / n, a[1] / n, a[2] / n) if n else a


def rotation_of(m):
    """The rotation of a matrix as an X3D axis-angle, scale and shear removed by polar decomposition (what X_ITE's
    ``Matrix4.getTransform`` reports as the orientation)."""
    r = [[m[0], m[1], m[2]], [m[4], m[5], m[6]], [m[8], m[9], m[10]]]
    for _ in range(40):                      # R <- (R + R^-T) / 2 converges to the rotation of a matrix with det > 0
        a, b, c, d, e, f, g, h, i = (r[0][0], r[0][1], r[0][2], r[1][0], r[1][1], r[1][2], r[2][0], r[2][1], r[2][2])
        det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
        if not math.isfinite(det) or abs(det) < 1e-300:
            break
        inv_t = [[(e * i - f * h) / det, (f * g - d * i) / det, (d * h - e * g) / det],
                 [(c * h - b * i) / det, (a * i - c * g) / det, (b * g - a * h) / det],
                 [(b * f - c * e) / det, (c * d - a * f) / det, (a * e - b * d) / det]]
        nxt = [[(r[x][y] + inv_t[x][y]) / 2 for y in range(3)] for x in range(3)]
        done = max(abs(nxt[x][y] - r[x][y]) for x in range(3) for y in range(3)) < 1e-14
        r = nxt
        if done:
            break
    trace = r[0][0] + r[1][1] + r[2][2]
    angle = math.acos(max(-1.0, min(1.0, (trace - 1) / 2)))
    if angle < 1e-12:
        return (0.0, 0.0, 1.0, 0.0)
    if math.pi - angle < 1e-6:               # half a turn: the axis is the column of R + I with the most in it
        sym = [[(r[x][y] + (1.0 if x == y else 0.0)) / 2 for y in range(3)] for x in range(3)]
        k = max(range(3), key=lambda j: sym[j][j])
        axis = _unit((sym[0][k], sym[1][k], sym[2][k]))
        return (*axis, angle)
    axis = _unit((r[2][1] - r[1][2], r[0][2] - r[2][0], r[1][0] - r[0][1]))
    return (*axis, angle)


def box_contains(center, size, point):
    """A point in a box (edges count in), as a ProximitySensor and a TransformSensor test it. A size of -1 -1 -1 is
    everywhere."""
    if size[0] == -1.0 and size[1] == -1.0 and size[2] == -1.0:
        return True
    return all(center[i] - size[i] / 2 <= point[i] <= center[i] + size[i] / 2 for i in range(3))


# ---------------------------------------------------------------------------------------------------------------
# The view volume against a box (X_ITE: ViewVolume.intersectsBox, Box3, SAT)
# ---------------------------------------------------------------------------------------------------------------

def view_volume(fov, aspect, near, far):
    """The eight corners of the view frustum in camera space, in X_ITE's order (near: lower left, lower right, upper
    right, upper left; then the far plane the same way). X3D's field of view is the smaller angle of the window."""
    ratio = math.tan(fov / 2) * near
    half_x, half_y = (aspect * ratio, ratio) if aspect > 1 else (ratio, ratio / aspect)
    k = far / near
    return ((-half_x, -half_y, -near), (half_x, -half_y, -near), (half_x, half_y, -near), (-half_x, half_y, -near),
            (-half_x * k, -half_y * k, -far), (half_x * k, -half_y * k, -far), (half_x * k, half_y * k, -far),
            (-half_x * k, half_y * k, -far))


def _separated(axes, points1, points2):
    for axis in axes:
        a0, a1, a2 = axis                  # the same products and sums as ``_dot``, each point projected once
        projected1 = [p[0] * a0 + p[1] * a1 + p[2] * a2 for p in points1]
        projected2 = [p[0] * a0 + p[1] * a1 + p[2] * a2 for p in points2]
        low1, high1, low2, high2 = min(projected1), max(projected1), min(projected2), max(projected2)
        if not ((low1 <= low2 <= high1) or (low2 <= low1 <= high2)):
            return True
    return False


def _box_normals(x, y, z):
    """Box3.getNormals: the three face normals, with its fallbacks for a box of no width."""
    axes = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    zero = (0.0, 0.0, 0.0)

    def first(others, against):
        for axis in others:
            v = _cross(axis, against)
            if _dot(v, v) != 0:
                return v
        return zero

    if _dot(x, x) == 0:
        x = _cross(y, z)
        if _dot(x, x) == 0:
            x = first(axes, y)
            if _dot(x, x) == 0:
                x = first(axes, z)
                if _dot(x, x) == 0:
                    x = axes[0]
    if _dot(y, y) == 0:
        y = _cross(z, x)
        if _dot(y, y) == 0:
            y = first(axes, z)
            if _dot(y, y) == 0:
                y = first(axes, x)
                if _dot(y, y) == 0:
                    y = axes[1]
    if _dot(z, z) == 0:
        z = _cross(x, y)
        if _dot(z, z) == 0:
            z = first(axes, x)
            if _dot(z, z) == 0:
                z = first(axes, y)
                if _dot(z, z) == 0:
                    z = axes[2]
    return tuple(_unit(_cross(*pair)) for pair in ((y, z), (z, x), (x, y)))


def frustum_meets_box(volume, center, half_axes):
    """Does the view volume (``view_volume``, camera space) meet the box with this centre and these three half axes
    (camera space)? X_ITE's test, line for line: the box's three normals, the frustum's six, then cross products of the
    box axes with the frustum's eight edge directions, kept in a table of 24 filled at ``i1 * 3 + i2`` (so only 14
    distinct slots survive and later products overwrite earlier ones; the rest stay zero and separate nothing)."""
    x, y, z = half_axes
    r1, r2 = _add(y, z), _sub(z, y)
    points = [_add(p, center) for p in (_add(x, r1), _sub(r1, x), _sub(r2, x), _add(x, r2))]
    points += [(-points[i][0] + 2 * center[0], -points[i][1] + 2 * center[1], -points[i][2] + 2 * center[2])
               for i in (2, 3, 0, 1)]
    if _separated(_box_normals(x, y, z), points, volume):
        return False
    p = volume
    normals = [_cross(_sub(b, a), _sub(c, a)) for a, b, c in
               ((p[0], p[1], p[2]), (p[7], p[4], p[0]), (p[6], p[2], p[1]), (p[2], p[6], p[7]), (p[1], p[0], p[4]),
                (p[4], p[7], p[6]))]
    if _separated([_unit(n) for n in normals], points, volume):
        return False
    edges = [_sub(p[0], p[1]), _sub(p[1], p[2]), _sub(p[2], p[3]), _sub(p[3], p[0]), _sub(p[0], p[4]), _sub(p[1], p[5]),
             _sub(p[2], p[6]), _sub(p[3], p[7])]
    table = [(0.0, 0.0, 0.0)] * 24
    for i1, axis in enumerate((x, y, z)):
        for i2 in range(8):
            table[i1 * 3 + i2] = _cross(axis, edges[i2])
    return not _separated(table, points, volume)


# ---------------------------------------------------------------------------------------------------------------
# What is near the viewer (X_ITE: X3DRenderObject.collide, getClosestObject)
# ---------------------------------------------------------------------------------------------------------------

def _clip(polygon, axis, offset, keep_above):
    """The part of a convex polygon (list of 3-vectors) with ``polygon . axis >= offset`` (or ``<=``)."""
    out = []
    for index, current in enumerate(polygon):
        previous = polygon[index - 1]
        dc, dp = _dot(current, axis) - offset, _dot(previous, axis) - offset
        if not keep_above:
            dc, dp = -dc, -dp
        if dc >= 0:
            if dp < 0:
                t = dp / (dp - dc)
                out.append(tuple(previous[k] + (current[k] - previous[k]) * t for k in range(3)))
            out.append(current)
        elif dp >= 0:
            t = dp / (dp - dc)
            out.append(tuple(previous[k] + (current[k] - previous[k]) * t for k in range(3)))
    return out


_FACES = ((0, 1, 3, 2), (4, 5, 7, 6), (0, 1, 5, 4), (2, 3, 7, 6), (0, 2, 6, 4), (1, 3, 7, 5))


def _box_corners(center, half_axes):
    x, y, z = half_axes
    return [(center[0] + sx * x[0] + sy * y[0] + sz * z[0], center[1] + sx * x[1] + sy * y[1] + sz * z[1],
             center[2] + sx * x[2] + sy * y[2] + sz * z[2]) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]


def closest_depth(corners, origin, right, up, forward, radius, down, ceiling, near, far):
    """The least distance along ``forward`` from ``origin`` to a box (its eight ``corners``) inside the slab X_ITE looks
    through: ``radius`` either side of ``forward`` across, ``down`` below and ``ceiling`` above ``up``, between ``near`` and
    ``far``, as the depth raster sees it: faces seen edge on are not drawn, and the viewer inside a box sees its far faces
    (X_ITE draws with face culling off). None when no face is in the slab."""
    local = [(_dot(_sub(c, origin), right), _dot(_sub(c, origin), up), _dot(_sub(c, origin), forward)) for c in corners]
    best = None
    for face in _FACES:
        polygon = [local[i] for i in face]
        normal = _cross(_sub(polygon[1], polygon[0]), _sub(polygon[3], polygon[0]))
        if abs(normal[2]) <= 1e-9 * math.sqrt(_dot(normal, normal)):
            continue                         # a face seen edge on has no area on the depth raster: nothing to see
        for axis, offset, above in (((1.0, 0.0, 0.0), -radius, True), ((1.0, 0.0, 0.0), radius, False),
                                    ((0.0, 1.0, 0.0), down, True), ((0.0, 1.0, 0.0), ceiling, False),
                                    ((0.0, 0.0, 1.0), near, True), ((0.0, 0.0, 1.0), far, False)):
            polygon = _clip(polygon, axis, offset, above)
            if not polygon:
                break
        for _u, _v, w in polygon:
            if best is None or w < best:
                best = w
    return best


_RASTER = 16        # X_ITE's collision look is a depth image of 16 x 16 pixels (DEPTH_BUFFER_SIZE)


def _inverse3(a0, a1, a2):
    """The inverse of the matrix whose columns are a0, a1, a2 (rows of the result), or None when it has none."""
    c0, c1, c2 = _cross(a1, a2), _cross(a2, a0), _cross(a0, a1)
    det = _dot(a0, c0)
    if not math.isfinite(det) or abs(det) < 1e-300:
        return None
    return (tuple(v / det for v in c0), tuple(v / det for v in c1), tuple(v / det for v in c2))


def sampled_depth(box, origin, right, up, forward, radius, down, ceiling, near, far):
    """The depth image X_ITE reads, for one box: the nearest first hit at the centres of 16 x 16 pixels spread over the
    slab (``closest_depth`` is its exact limit). ``box`` is (centre, rows of the inverse of its half axes)."""
    center, inverse = box
    rel = _sub(origin, center)
    s_forward = _dot_rows(inverse, forward)
    s_right, s_up, s_origin = _dot_rows(inverse, right), _dot_rows(inverse, up), _dot_rows(inverse, rel)
    best = None
    for j in range(_RASTER):
        v = down + (j + 0.5) / _RASTER * (ceiling - down)
        for i in range(_RASTER):
            u = -radius + (i + 0.5) / _RASTER * 2 * radius
            low, high = -math.inf, math.inf
            for k in range(3):
                start = s_origin[k] + u * s_right[k] + v * s_up[k]
                rate = s_forward[k]
                if rate == 0:
                    if not -1.0 <= start <= 1.0:
                        low, high = 1.0, 0.0
                        break
                    continue
                t1, t2 = (-1.0 - start) / rate, (1.0 - start) / rate
                if t1 > t2:
                    t1, t2 = t2, t1
                low, high = max(low, t1), min(high, t2)
                if low > high:
                    break
            if low > high:
                continue
            depth = low if low >= near else (high if high >= near else None)
            if depth is not None and depth <= far and (best is None or depth < best):
                best = depth
    return best


def _dot_rows(rows, v):
    return (_dot(rows[0], v), _dot(rows[1], v), _dot(rows[2], v))


# ---------------------------------------------------------------------------------------------------------------
# The data
# ---------------------------------------------------------------------------------------------------------------

class Frame:
    """A Transform (or the scene root's child group): its fields, its parent and its world matrix."""
    __slots__ = ("name", "parent", "children", "translation", "rotation", "scale", "center", "scale_orientation",
                 "local", "world", "dirty", "fixed")

    def __init__(self, name, parent=None, translation=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 1.0, 0.0),
                 scale=(1.0, 1.0, 1.0), center=(0.0, 0.0, 0.0), scale_orientation=(0.0, 0.0, 1.0, 0.0)):
        self.name, self.parent, self.children = name, parent, []
        self.translation, self.rotation, self.scale = tuple(translation), tuple(rotation), tuple(scale)
        self.center, self.scale_orientation = tuple(center), tuple(scale_orientation)
        self.local = self.world = None
        self.dirty = True
        self.fixed = None          # a world matrix handed in (from Blender): the hierarchy is not used for this frame


class Volume:
    """A shape of the world in a frame: kind "box" (``center``, ``size``), "sphere" (``center``, ``radius``), "points" or
    "segments" (``points``: tuples; ``segments``: index pairs)."""
    __slots__ = ("name", "kind", "frame", "center", "size", "radius", "points", "segments")

    def __init__(self, name, kind, frame, center=(0.0, 0.0, 0.0), size=(0.0, 0.0, 0.0), radius=0.0, points=(), segments=()):
        self.name, self.kind, self.frame = name, kind, frame
        self.center, self.size, self.radius = tuple(center), tuple(size), radius
        self.points, self.segments = tuple(points), tuple(segments)


class Viewer:
    """The viewer: where it is in its frame (the Viewpoint's parent), which way it looks, and its frustum. ``near`` and
    ``far`` are None until given: X_ITE then takes the near plane from the avatar's size and the far plane from the
    navigation info's visibilityLimit (or 1e5)."""
    __slots__ = ("frame", "position", "orientation", "center_of_rotation", "field_of_view", "aspect", "near", "far")

    def __init__(self, frame=None, position=(0.0, 0.0, 10.0), orientation=(0.0, 0.0, 1.0, 0.0),
                 center_of_rotation=(0.0, 0.0, 0.0), field_of_view=math.pi / 4, aspect=1.6, near=None, far=None):
        self.frame, self.position, self.orientation = frame, tuple(position), tuple(orientation)
        self.center_of_rotation, self.field_of_view = tuple(center_of_rotation), field_of_view
        self.aspect, self.near, self.far = aspect, near, far


class World:
    """See the module text. ``noted`` counts what was left out and why (never silently): "singular-frame" (a Transform
    with a zero scale was asked for its inverse), "use-instance" (a USE of a grouping node: one instance only),
    "bounds-for-geometry" (a Collision child that is not a box is taken as its bounding box)."""

    def __init__(self, aspect=1.6):
        self.frames = {}                 # name -> Frame; "#1", "#2" ... for Transforms without a DEF
        self.volumes = {}                # name -> Volume (a DEF'd shape or group: its bounding box)
        self.sensors = {}                # DEF of a sensor -> the frame it sits in (None: the scene root)
        self.targets = {}                # DEF of a node -> the frame its matrix is (a Transform: its own)
        self.sensor_target = {}          # DEF of a TransformSensor -> DEF of its targetObject
        self.geo_origins = {}            # DEF of a GeoOrigin -> behaviour_geo.GeoOrigin (a Geo node's ``USE`` of it names one)
        self.collisions = {}             # DEF of a Collision -> {"enabled": bool, "shapes": [Volume]}
        self.viewpoint = None            # DEF of the bound Viewpoint (its fields change through ``apply``)
        self.viewer = Viewer(aspect=aspect)
        self.avatar_size = _NAVIGATION_DEFAULTS["avatarSize"]
        self.visibility_limit = _NAVIGATION_DEFAULTS["visibilityLimit"]
        self.noted = {}
        self.pick = None                 # behaviour_pick.PickScene: what the pick sensors pick, read from the document
        self._anonymous = 0
        self.version = 0                 # counts changes of any frame or of the viewer
        self.frames_version = 0          # ... of a frame (or of a Collision's shapes) alone
        self.viewer_version = 0          # ... of the viewer alone
        self._memo = {}                  # what was worked out for one state of the frames or the viewer (see ``_cached``)

    # -- building ---------------------------------------------------------------------------------------------

    def note(self, what):
        self.noted[what] = self.noted.get(what, 0) + 1

    def add_frame(self, name, parent=None, **fields):
        frame = Frame(name, parent, **fields)
        self.frames[name] = frame
        if parent is not None:
            self.frames[parent].children.append(name)
        return frame

    def set_frame_matrix(self, name, matrix):
        """Give a frame a world matrix from outside (Blender's own): the frame stops following its Transform fields."""
        frame = self.frames.get(name)
        if frame is None:
            frame = self.add_frame(name)
        matrix = tuple(float(v) for v in matrix)
        if len(matrix) != 16 or not _finite(matrix):
            raise ValueError("a world matrix is sixteen finite numbers")
        frame.fixed = matrix
        self._dirty(frame)

    @classmethod
    def from_x3d(cls, document, aspect=1.6):
        """The world of an X3D document (XML text, bytes or an ElementTree element). ``aspect`` is the canvas width over
        height the view frustum is made for (``tools/behaviour_sim_judge.cjs`` records on 960 x 600)."""
        root = ET.fromstring(document) if isinstance(document, (str, bytes)) else \
            (document.getroot() if hasattr(document, "getroot") else document)
        scene = next((e for e in root.iter() if _local(e.tag) == "Scene"), root)
        world = cls(aspect)
        by_def = {e.get("DEF"): e for e in scene.iter() if e.get("DEF")}
        walker = _Walker(world, by_def)
        walker.walk(scene, None)
        walker.finish()
        try:
            from . import behaviour_pick
        except ImportError:  # imported as a plain module: tests, tools/
            import behaviour_pick
        try:
            world.pick = behaviour_pick.build(scene, by_def, walker.frame_of)
        except Exception:                # noqa: BLE001 - a document the pick reader cannot follow still gives a World
            world.note("pick-scene-failed")
        world.geo_origins = _geo_origins(scene)
        return world

    # -- the Transform hierarchy --------------------------------------------------------------------------------

    def _dirty(self, frame):
        """Mark a frame and what hangs below it as needing its matrix again (a dirty frame has only dirty children)."""
        self.version += 1
        self.frames_version += 1
        stack = [frame]
        while stack:
            current = stack.pop()
            current.dirty = True
            for child in current.children:
                if not self.frames[child].dirty:
                    stack.append(self.frames[child])

    def _cached(self, key, state, make):
        """``make()``, remembered while ``state`` (a version) stays what it was."""
        held = self._memo.get(key)
        if held is not None and held[0] == state:
            return held[1]
        value = make()
        self._memo[key] = (state, value)
        return value

    def matrix(self, name):
        """The world matrix of a frame (None: the scene root, the identity). Worked out only when a frame moved."""
        if name is None:
            return IDENTITY
        frame = self.frames[name]
        if not frame.dirty and frame.world is not None:
            return frame.world
        if frame.fixed is not None:
            frame.world = frame.fixed
        else:
            frame.local = m_transform(frame.translation, frame.rotation, frame.scale, frame.center,
                                      frame.scale_orientation)
            frame.world = m_mul(self.matrix(frame.parent), frame.local) if frame.parent is not None else frame.local
        frame.dirty = False
        return frame.world

    def apply(self, name, field_name, value):
        """A ROUTE delivered ``value`` to ``field_name`` of the node DEF ``name``. True when the world took it."""
        frame = self.frames.get(name)
        if frame is not None and field_name in ("translation", "rotation", "scale", "center", "scaleOrientation"):
            if not _finite(value) or len(value) != (4 if field_name in ("rotation", "scaleOrientation") else 3):
                return False
            attribute = {"scaleOrientation": "scale_orientation"}.get(field_name, field_name)
            setattr(frame, attribute, tuple(float(v) for v in value))
            self._dirty(frame)
            return True
        if name == self.viewpoint and field_name in ("position", "orientation", "centerOfRotation", "fieldOfView"):
            if not _finite(value):
                return False
            viewer = self.viewer
            if field_name == "fieldOfView":
                viewer.field_of_view = float(value) if 0 < value < math.pi else math.pi / 4
            else:
                setattr(viewer, {"centerOfRotation": "center_of_rotation"}.get(field_name, field_name),
                        tuple(float(v) for v in value))
            self.version += 1
            self.viewer_version += 1
            return True
        collision = self.collisions.get(name)
        if collision is not None and field_name == "enabled":
            collision["enabled"] = bool(value)
            self.frames_version += 1
            return True
        if self.pick is not None and self.pick.watches(name):
            return self.pick.apply(name, field_name, value)
        return False

    def watches(self, name):
        """True when a ROUTE into ``name`` matters to the world."""
        return name in self.frames or name == self.viewpoint or name in self.collisions or \
            (self.pick is not None and self.pick.watches(name))

    # -- asking -------------------------------------------------------------------------------------------------

    def sensor_matrix(self, name):
        """The world matrix of the coordinates a sensor's ``center`` and ``size`` are in."""
        return self.matrix(self.sensors.get(name))

    def sensor_inverse(self, name):
        """The inverse of ``sensor_matrix`` (None when it has none), kept while that matrix stays what it is."""
        matrix = self.sensor_matrix(name)
        return self._cached(("inverse", name), matrix, lambda: m_inverse(matrix))

    def camera(self):
        """(camera to world, world to camera or None), kept while the viewer and its frame stay where they are."""
        def make():
            matrix = self.viewer_matrix()
            return matrix, m_inverse(matrix)
        return self._cached("camera", (self.viewer_version, self.matrix(self.viewer.frame)), make)

    def target_matrix(self, name):
        """The world matrix of a node a TransformSensor aims at (a Transform: its own), or None when unknown."""
        if name not in self.targets:
            return None
        return self.matrix(self.targets[name])

    def viewer_matrix(self):
        """Camera to world: the viewpoint's frame, then its position, then its orientation."""
        viewer = self.viewer
        return m_mul(m_mul(self.matrix(viewer.frame), m_translate(viewer.position)), m_rotate(viewer.orientation))

    def set_viewer(self, position, orientation, center_of_rotation=None, field_of_view=None, aspect=None, near=None,
                   far=None):
        """The caller says where the viewer is in world coordinates (the Viewpoint's frame becomes the root)."""
        viewer = self.viewer
        viewer.frame = None
        viewer.position, viewer.orientation = tuple(position), tuple(orientation)
        if center_of_rotation is not None:
            viewer.center_of_rotation = tuple(center_of_rotation)
        for name, value in (("field_of_view", field_of_view), ("aspect", aspect), ("near", near), ("far", far)):
            if value is not None and _finite(value) and value > 0:
                setattr(viewer, name, float(value))
        self.version += 1
        self.viewer_version += 1

    def to_local(self, name, point):
        """A world point in the coordinates of a sensor's frame, or None when the frame has no inverse."""
        inverse = self.sensor_inverse(name)
        if inverse is None:
            self.note("singular-frame")
            return None
        return m_point(inverse, point)

    def viewer_in(self, name):
        """The viewer as a ProximitySensor wants it: (position, orientation, centre of rotation) in the coordinates of the
        sensor's frame, or None when the frame has no inverse."""
        inverse = self.sensor_inverse(name)
        if inverse is None:
            self.note("singular-frame")
            return None
        camera = self.camera()[0]
        viewer = self.viewer
        pivot = m_point(self.matrix(viewer.frame), viewer.center_of_rotation)
        return (m_point(inverse, m_point(camera, (0.0, 0.0, 0.0))), rotation_of(m_mul(inverse, camera)),
                m_point(inverse, pivot))

    def near_far(self):
        """The near and far planes of the view: the viewpoint's own, else X_ITE's (avatarSize[0] / 2, or 0.125 for an avatar
        of no width; visibilityLimit, or 1e5 when it is 0)."""
        viewer = self.viewer
        near = viewer.near if viewer.near else (self.avatar_size[0] / 2 or 0.125)
        far = viewer.far if viewer.far else (self.visibility_limit or _MAX_FAR)
        return near, far

    def frustum(self):
        """(corners, planes) of the view volume in camera space for the viewer's frustum, kept while it stays the same. A
        plane is (normal, offset) with the inside where ``normal . p >= offset``."""
        viewer = self.viewer
        near, far = self.near_far()
        key = (viewer.field_of_view, viewer.aspect, near, far)

        def make():
            corners = view_volume(*key[:2], near, far)
            inside = (0.0, 0.0, -(near + far) / 2)
            planes = []
            for a, b, c in ((0, 1, 2), (7, 4, 0), (6, 2, 1), (2, 6, 7), (1, 0, 4), (4, 7, 6)):
                normal = _unit(_cross(_sub(corners[b], corners[a]), _sub(corners[c], corners[a])))
                offset = _dot(normal, corners[a])
                if _dot(normal, inside) < offset:
                    normal, offset = (-normal[0], -normal[1], -normal[2]), -offset
                planes.append((normal, offset))
            return corners, planes
        return self._cached(("frustum", key), 0, make)

    def sees_box(self, name, center, size):
        """Is any of the box (``center``, ``size`` in the coordinates of sensor ``name``'s frame) in the view volume? A
        size of -1 -1 -1 is always in. None when the frame or the camera has no inverse. A ball round the box that is
        wholly outside one face of the view volume (or wholly inside all six) settles it at once; only a box near the
        edge of the view is tested axis by axis (``frustum_meets_box``), which is what X_ITE does for every box."""
        if size[0] == -1.0 and size[1] == -1.0 and size[2] == -1.0:
            return True
        camera_inverse = self.camera()[1]
        if camera_inverse is None:
            self.note("singular-frame")
            return None
        m = m_mul(camera_inverse, self.sensor_matrix(name))
        half_axes = tuple(m_dir(m, tuple(size[k] / 2 if j == k else 0.0 for k in range(3))) for j in range(3))
        corners, planes = self.frustum()
        middle = m_point(m, center)
        reach = sum(math.sqrt(_dot(axis, axis)) for axis in half_axes)
        straddling = []
        for normal, offset in planes:
            distance = _dot(normal, middle) - offset
            if distance < -reach:
                return False
            if distance < reach:
                straddling.append((normal, distance))
        # The ball is a loose bound. Along a plane's own normal the box reaches exactly the sum of its half axes' parts on it,
        # so a box wholly outside that plane is separated on one of the six frustum normals the full test tries (and one
        # wholly inside every plane is not separated on any): the answer is the full test's, found without it.
        for normal, distance in straddling[:]:
            extent = abs(_dot(normal, half_axes[0])) + abs(_dot(normal, half_axes[1])) + abs(_dot(normal, half_axes[2]))
            if distance < -extent:
                return False
            if distance >= extent:
                straddling.remove((normal, distance))
        return True if not straddling else frustum_meets_box(corners, middle, half_axes)

    def collision_hits(self):
        """The Collision groups the viewer is touching. X_ITE looks along the six axes of the viewpoint's frame through a slab
        as wide as the avatar (``avatarSize[0]`` either side, from below by ``min(stepHeight - avatarHeight, -radius)`` to
        ``radius`` above, between the near plane and twice the avatar's height) at the shapes of every enabled Collision;
        the closest shape along an axis that is within ``radius`` times the square root of two sets every Collision it is
        in active. A polytope clip (``closest_depth``) says cheaply which boxes are near enough to matter; the depth is then
        read at the centres of 16 x 16 pixels as X_ITE does (``sampled_depth``), so a shape that overlaps the slab by less
        than half a pixel is not seen."""
        viewer = self.viewer
        radius, height, step = self.avatar_size
        reach = radius * math.sqrt(2)
        bottom = min(step - height, -radius)
        near = self.near_far()[0]
        far = max(radius * 2, height * 2)
        boxes = self._collision_boxes()
        if not boxes:
            return set()
        inverse = None
        if viewer.frame is not None:
            inverse = m_inverse(self.matrix(viewer.frame))
            if inverse is None:
                self.note("singular-frame")
                return set()
        origin = viewer.position
        look_at = []
        for name, corners, center, rows, bound in boxes:
            if inverse is not None:               # the viewer's own frame is not the world: bring the box into it
                corners = [m_point(inverse, c) for c in corners]
                center = m_point(inverse, center)
                half = [tuple(v / 2 for v in _sub(corners[k], corners[0])) for k in (4, 2, 1)]
                rows = _inverse3(*half)
                if rows is None:
                    continue
                bound = sum(math.sqrt(_dot(axis, axis)) for axis in half)
            offset = _sub(center, origin)
            if math.sqrt(_dot(offset, offset)) - bound > far:       # too far to be seen by any of the six looks
                continue
            look_at.append((name, corners, (center, rows)))
        active = set()
        for direction, right, up in _LOOKS:
            near_ones = [(name, box) for name, corners, box in look_at
                         if (closest_depth(corners, origin, right, up, direction, radius, bottom, radius, near, far) or
                             math.inf) <= reach]
            best, owner = None, None
            for name, box in near_ones:
                depth = sampled_depth(box, origin, right, up, direction, radius, bottom, radius, near, far)
                if depth is not None and (best is None or depth < best):
                    best, owner = depth, name
            if best is not None and best <= reach:
                active.add(owner)
        for name in list(active):
            while self.collisions[name].get("parent") is not None:       # every Collision the shape is inside
                name = self.collisions[name]["parent"]
                active.add(name)
        return active

    def _collision_boxes(self):
        """[(collision, corners, centre, rows of the inverse of the half axes, bound)] of every shape of every enabled
        Collision, in world coordinates; kept while the frames of those shapes stay where they are."""
        def make():
            boxes = []
            for name, group in self.collisions.items():
                if not group["enabled"]:
                    continue
                for shape in group["shapes"]:
                    m = self.matrix(shape.frame)
                    half = tuple(m_dir(m, tuple(shape.size[k] / 2 if j == k else 0.0 for k in range(3)))
                                 for j in range(3))
                    center = m_point(m, shape.center)
                    rows = _inverse3(*half)
                    if rows is not None and _finite(center) and _finite(half):      # a box of no volume draws nothing
                        boxes.append((name, _box_corners(center, half), center, rows,
                                      sum(math.sqrt(_dot(axis, axis)) for axis in half)))
            return boxes
        state = tuple((name, shape.center, shape.size, self.matrix(shape.frame)) for name, group in self.collisions.items()
                      if group["enabled"] for shape in group["shapes"])
        return self._cached("collision-boxes", state, make)


# (direction, camera right, camera up): X_ITE turns -z onto the direction, then straightens the horizon
_LOOKS = (((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)), ((-1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
          ((0.0, 0.0, -1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), ((0.0, 0.0, 1.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
          ((0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)), ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, -1.0)))


def _geo_origins(scene):
    try:
        import behaviour_geo
    except ImportError:      # imported inside the add-on package
        from . import behaviour_geo
    return behaviour_geo.origins_in(scene)


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _numbers(text, count, default):
    try:
        values = tuple(float(v) for v in str(text).replace(",", " ").split())
    except ValueError:
        return default
    return values if len(values) == count and _finite(values) else default


_GROUPING = {"Group", "Transform", "Switch", "Anchor", "Billboard", "Collision", "LOD", "StaticGroup", "CADAssembly",
             "CADLayer", "CADPart", "CADFace", "ViewpointGroup"}
_SENSORS = {"ProximitySensor", "VisibilitySensor", "TransformSensor", "GeoProximitySensor"}


class _Walker:
    """Reads the scene once: frames, sensors, targets, collisions, the viewpoint and the navigation info."""

    def __init__(self, world, by_def):
        self.world, self.by_def, self.pending_targets = world, by_def, []
        self.seen_viewpoint = self.seen_navigation = False
        self.frame_of = {}         # id(Transform element) -> the key of its frame (the pick sensors read the document again)

    def walk(self, element, frame, collision=None):
        world = self.world
        for child in element:
            tag = _local(child.tag)
            name = child.get("DEF")
            if child.get("USE") is not None:
                if tag in _GROUPING and child.get("containerField") != "targetObject":
                    world.note("use-instance")
                continue
            if tag == "Transform":
                world._anonymous += 0 if name else 1
                key = name or f"#{world._anonymous}"
                if key in world.frames:
                    key = f"{key}#{len(world.frames)}"
                world.add_frame(key, frame,
                                translation=_numbers(child.get("translation"), 3, (0.0, 0.0, 0.0)),
                                rotation=_numbers(child.get("rotation"), 4, (0.0, 0.0, 1.0, 0.0)),
                                scale=_numbers(child.get("scale"), 3, (1.0, 1.0, 1.0)),
                                center=_numbers(child.get("center"), 3, (0.0, 0.0, 0.0)),
                                scale_orientation=_numbers(child.get("scaleOrientation"), 4, (0.0, 0.0, 1.0, 0.0)))
                self.frame_of[id(child)] = key
                if name:
                    world.targets[name] = key
                self.walk(child, key, collision)
            elif tag in _GROUPING:
                if name:
                    world.targets[name] = frame
                inner = collision
                if tag == "Collision":
                    inner = name or f"collision#{len(world.collisions)}"
                    world.collisions[inner] = {"enabled": child.get("enabled", "true").lower() != "false", "shapes": [],
                                               "parent": collision}
                self.walk(child, frame, inner)
            elif tag in _SENSORS and name:
                world.sensors[name] = frame
                if tag == "TransformSensor":
                    target = next((c.get("USE") for c in child if c.get("USE") and c.get("containerField") == "targetObject"),
                                  None)
                    if target:
                        world.sensor_target[name] = target
            elif tag == "Shape":
                if name:
                    world.targets[name] = frame
                volume = self.shape_volume(child, frame, name)
                if volume is not None and collision is not None:
                    world.collisions[collision]["shapes"].append(volume)
            elif tag == "Viewpoint" and not self.seen_viewpoint and child.get("bind") != "false":
                self.seen_viewpoint = True
                world.viewpoint = name
                world.viewer = Viewer(frame, _numbers(child.get("position"), 3, (0.0, 0.0, 10.0)),
                                      _numbers(child.get("orientation"), 4, (0.0, 0.0, 1.0, 0.0)),
                                      _numbers(child.get("centerOfRotation"), 3, (0.0, 0.0, 0.0)),
                                      self.fov(child.get("fieldOfView")), world.viewer.aspect)
            elif tag == "NavigationInfo" and not self.seen_navigation:
                self.seen_navigation = True
                try:
                    listed = [float(v) for v in (child.get("avatarSize") or "").replace(",", " ").split()]
                except ValueError:
                    listed = []
                defaults = _NAVIGATION_DEFAULTS["avatarSize"]
                world.avatar_size = tuple(max(0.0, listed[i]) if i < len(listed) and math.isfinite(listed[i]) else defaults[i]
                                          for i in range(3))
                try:
                    limit = float(child.get("visibilityLimit", "0"))
                except ValueError:
                    limit = 0.0
                world.visibility_limit = max(0.0, limit) if math.isfinite(limit) else 0.0
            else:
                self.walk(child, frame, collision)

    @staticmethod
    def fov(text):
        try:
            value = float(text) if text is not None else math.pi / 4
        except ValueError:
            return math.pi / 4
        return value if 0 < value < math.pi else math.pi / 4

    def shape_volume(self, shape, frame, name):
        """The bounding box of a Shape's geometry, as a Volume in ``frame``."""
        geometry = next((c for c in shape if _local(c.tag) in _GEOMETRY), None)
        if geometry is None:
            return None
        tag = _local(geometry.tag)
        center, size = _GEOMETRY[tag](geometry)
        if tag not in ("Box",):
            self.world.note("bounds-for-geometry")
        volume = Volume(name or f"shape#{len(self.world.volumes)}", "box", frame, center, size)
        if name:
            self.world.volumes[name] = volume
        return volume

    def finish(self):
        world = self.world
        for name, target in list(world.sensor_target.items()):
            if target not in world.targets:
                world.note("no-target")
                del world.sensor_target[name]
        # a Transform DEF's own frame is what its sensors see as the target; groups and shapes have their enclosing one


def _box(geometry):
    return (0.0, 0.0, 0.0), _numbers(geometry.get("size"), 3, (2.0, 2.0, 2.0))


def _sphere(geometry):
    try:
        radius = float(geometry.get("radius", "1"))
    except ValueError:
        radius = 1.0
    return (0.0, 0.0, 0.0), (2 * radius,) * 3


def _cone(geometry):
    try:
        radius, height = float(geometry.get("bottomRadius", "1")), float(geometry.get("height", "2"))
    except ValueError:
        radius, height = 1.0, 2.0
    return (0.0, 0.0, 0.0), (2 * radius, height, 2 * radius)


def _cylinder(geometry):
    try:
        radius, height = float(geometry.get("radius", "1")), float(geometry.get("height", "2"))
    except ValueError:
        radius, height = 1.0, 2.0
    return (0.0, 0.0, 0.0), (2 * radius, height, 2 * radius)


def _points(geometry):
    coordinate = next((c for c in geometry.iter() if _local(c.tag) in ("Coordinate", "CoordinateDouble")), None)
    try:
        numbers = [float(v) for v in (coordinate.get("point", "") if coordinate is not None else "").replace(",", " ").split()]
    except ValueError:
        numbers = []
    triples = [numbers[i:i + 3] for i in range(0, len(numbers) - 2, 3) if all(math.isfinite(v) for v in numbers[i:i + 3])]
    if not triples:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    low = [min(p[k] for p in triples) for k in range(3)]
    high = [max(p[k] for p in triples) for k in range(3)]
    return tuple((low[k] + high[k]) / 2 for k in range(3)), tuple(high[k] - low[k] for k in range(3))


_GEOMETRY = {"Box": _box, "Sphere": _sphere, "Cone": _cone, "Cylinder": _cylinder, "IndexedFaceSet": _points,
             "IndexedLineSet": _points, "PointSet": _points, "IndexedTriangleSet": _points, "TriangleSet": _points}
