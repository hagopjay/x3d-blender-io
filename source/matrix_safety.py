# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Matrices with extreme scales, kept usable by Blender's float32 maths.

X3D allows any scale: stars-view.x3d Inlines a file in metres under ``scale='1.057e-16'`` so one unit is one
light-year. Blender stores and inverts object matrices in float32. The determinant of a uniform 1e-16 scale
(1e-48) underflows to 0, and ``Matrix.inverted_safe()`` then nudges the diagonal by about 1e-8 and returns a
scale near 1e8 instead of 1e16. Blender's glTF exporter writes every child node as
``parent.matrix_world.inverted_safe() @ child.matrix_world``, so the stars-view glb came out about 1e8 times too
small. The same happens for scales beyond about 1e12, where the determinant overflows.

``push_scale_to_children`` rebuilds such a parent: an Empty with children whose world axes are scaled outside
``[1 / EXTREME_SCALE, EXTREME_SCALE]`` gets world axes of length 1, and its children's parent inverse absorbs the
scale, so no world matrix in the scene changes and every parent matrix inverts cleanly in float32. The scale it
moved is kept on the Empty as ``x3d_scale_to_children`` (X, Y, Z in the Empty's local axes), which the X3D exporter
multiplies back in for an Inline placeholder, whose children it does not write.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("import_x3d")

# A parent whose world axes are scaled by less than 1e-6 or more than 1e6 has its scale moved to its children.
# Blender's float32 Matrix.inverted_safe() is still exact to 1e-7 at 1e-12 and 1e12 and breaks at 1e-14 and 1e13;
# 1e6 leaves that margin and does not touch everyday unit changes (mm, cm, km, inches).
EXTREME_SCALE = 1e6
SCALE_TO_CHILDREN_PROPERTY = "x3d_scale_to_children"


def inverted64(matrix, what="matrix"):
    """The inverse of a 4x4 transform, computed in float64 (see import_x3d._inverted, which this mirrors).

    A singular matrix gives its pseudo-inverse and a warning; an inverse beyond float32 range gives the identity
    and a warning."""
    import numpy as np
    from mathutils import Matrix

    values = np.array(matrix, dtype=np.float64)
    try:
        inverse = np.linalg.inv(values)
    except np.linalg.LinAlgError:
        logger.warning("%s is singular (a scale of 0?); using its pseudo-inverse", what)
        inverse = np.linalg.pinv(values)
    if not np.abs(inverse).max() <= np.finfo(np.float32).max:
        logger.warning("%s has no inverse in float32 range; using the identity", what)
        return Matrix()
    return Matrix(inverse.tolist())


def axis_scales(matrix):
    """Lengths of the matrix's three linear columns, in float64: the world size of the object's unit axes."""
    import numpy as np

    linear = np.array(matrix, dtype=np.float64)[:3, :3]
    return [float(v) for v in np.linalg.norm(linear, axis=0)]


def is_extreme(scales, limit=EXTREME_SCALE):
    """True when any axis scale is outside [1 / limit, limit] (0 counts: it is handled, and refused, by the caller)."""
    return any(not (1.0 / limit <= s <= limit) for s in scales)


def _is_animated(obj):
    animation = getattr(obj, "animation_data", None)
    return animation is not None and (animation.action is not None or len(animation.drivers) > 0)


def _depth(obj):
    depth = 0
    while obj.parent is not None:
        obj, depth = obj.parent, depth + 1
    return depth


def push_scale_to_children(objects, limit=EXTREME_SCALE):
    """Move an extreme world scale off every Empty parent in ``objects`` and onto its children (see module doc).

    Parents are visited from the root down, so a chain of extreme Inlines ends with every parent well scaled. An
    Empty is skipped, with a warning, when an axis scale is 0 (nothing to divide by), when it is animated (its
    keys would put the scale back) or when the change would move a child by more than 1e-4 of its matrix (it is
    then undone). Returns the Empties it changed."""
    import bpy
    from mathutils import Matrix

    changed = []
    candidates = [ob for ob in objects if ob.type == 'EMPTY' and ob.children]
    candidates.sort(key=_depth)
    for ob in candidates:
        bpy.context.view_layer.update()
        world = ob.matrix_world.copy()
        scales = axis_scales(world)
        if not is_extreme(scales, limit):
            continue
        if min(scales) <= 0.0:
            logger.warning("%r has a world scale of 0 on an axis; its matrix stays singular", ob.name)
            continue
        if _is_animated(ob):
            logger.warning("%r is animated with an extreme world scale %s; glTF export may misplace its children",
                           ob.name, ["%.3g" % s for s in scales])
            continue
        down = Matrix.Diagonal((*scales, 1.0))
        up = Matrix.Diagonal((1.0 / scales[0], 1.0 / scales[1], 1.0 / scales[2], 1.0))
        # The basis is loc/rot/scale, and a diagonal on its right keeps it so: only the Empty's scale changes.
        old_basis = ob.matrix_basis.copy()
        old_inverses = {child: child.matrix_parent_inverse.copy() for child in ob.children}
        before = {child: child.matrix_world.copy() for child in ob.children}
        ob.matrix_basis = _product64(old_basis, up)
        for child in ob.children:
            child.matrix_parent_inverse = _product64(down, old_inverses[child])
        bpy.context.view_layer.update()
        drift = max((_relative_drift(matrix, child.matrix_world) for child, matrix in before.items()), default=0.0)
        if drift > 1e-4:
            ob.matrix_basis = old_basis
            for child, inverse in old_inverses.items():
                child.matrix_parent_inverse = inverse
            bpy.context.view_layer.update()
            logger.warning("%r: moving its world scale %s to its children would move them (%.2g); left as it was",
                           ob.name, ["%.3g" % s for s in scales], drift)
            continue
        previous = ob.get(SCALE_TO_CHILDREN_PROPERTY)
        if previous is not None and len(previous) == 3:
            scales = [s * float(p) for s, p in zip(scales, previous)]
        ob[SCALE_TO_CHILDREN_PROPERTY] = [float(s) for s in scales]
        logger.info("%r: world scale %s moved to its %d children", ob.name, ["%.4g" % s for s in scales],
                    len(before))
        changed.append(ob)
    return changed


def scale_to_children_matrix(obj):
    """The diagonal matrix of the scale ``push_scale_to_children`` moved off ``obj`` (the identity if none)."""
    from mathutils import Matrix

    scales = obj.get(SCALE_TO_CHILDREN_PROPERTY)
    if scales is None or len(scales) != 3:
        return Matrix.Identity(4)
    return Matrix.Diagonal((float(scales[0]), float(scales[1]), float(scales[2]), 1.0))


def _product64(a, b):
    import numpy as np
    from mathutils import Matrix

    return Matrix((np.array(a, dtype=np.float64) @ np.array(b, dtype=np.float64)).tolist())


def _relative_drift(a, b):
    import numpy as np

    a = np.array(a, dtype=np.float64)
    b = np.array(b, dtype=np.float64)
    size = max(np.abs(a).max(), 1e-300)
    return float(np.abs(a - b).max() / size)
