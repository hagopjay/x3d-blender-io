# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The allocation budget: a number the file states may not make the importer allocate without bound. No ``bpy``.

The 2.7.2 chaos round found one case (a coordIndex of 2147483647 padded the point list up to that index). The 2.7.3
audit looked for every other place where a count in the file, not the data in the file, sets a size:

* ElevationGrid and GeoElevationGrid ``xDimension`` x ``zDimension`` (the heights are padded up to it);
* the X3DOM ``subdivision`` of Sphere, Cylinder and Cone (rings x segments; 0 divided by zero);
* PixelTexture ``image`` width x height (an image of that size is allocated before a pixel is read);
* the number of Inline files one import loads (ten Inlines per level, five levels deep, is 100,000 loads);
* an animation's key count, on import and on export. The export samples every frame of the timeline, and the import
  makes the timeline as long as the file's cycleInterval: a 48-key, 47,000 s animation came back as 1,048,574 keys
  (48 MB) after one round trip, and the next import did not finish in three minutes.

Each is now checked here: over the budget, the node is skipped with a warning that names the number and the budget.
"""

from __future__ import annotations

import logging
import math
import os

logger = logging.getLogger("import_x3d")

ELEMENTS_ENV = "BLENDER_X3D_MAX_ELEMENTS"
MAX_ELEMENTS = 1 << 24          # 16,777,216 vertices, grid points or pixels from one node
MIN_DIVISIONS, MAX_DIVISIONS = 3, 1024   # a 1024 x 1024 Sphere is 1M vertices; 4096 x 4096 (16.7M) ran out of a 6 GB budget
MAX_IMPORT_KEYS = 1 << 16       # keyframes per animated object on import
MAX_EXPORT_SAMPLES_ENV = "BLENDER_X3D_MAX_ANIMATION_SAMPLES"
MAX_EXPORT_SAMPLES = 10000      # sampled frames per export
MAX_INLINES_ENV = "BLENDER_X3D_MAX_INLINES"
MAX_INLINES = 1000              # Inline file loads per import


def element_limit() -> int:
    """BLENDER_X3D_MAX_ELEMENTS when it is a positive integer, else 16,777,216."""
    try:
        value = int(os.environ.get(ELEMENTS_ENV, ""))
    except ValueError:
        return MAX_ELEMENTS
    return value if value > 0 else MAX_ELEMENTS


def count(value, what: str) -> int:
    """A count from the file as a non-negative int: NaN, INF, negatives and non-numbers become 0, with a warning."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        logger.warning("%s is %r, not a number; read as 0", what, value)
        return 0
    if not math.isfinite(number) or number < 0:
        logger.warning("%s is %r; read as 0", what, value)
        return 0
    return int(number)


def within(elements: int, what: str) -> bool:
    """True when ``elements`` fits the budget; False, with a warning, when the node must be skipped."""
    limit = element_limit()
    if elements <= limit:
        return True
    logger.warning("%s asks for %d elements, over the budget of %d; the node is skipped (set %s to raise it)",
                   what, elements, limit, ELEMENTS_ENV)
    return False


def divisions(value, default: int, what: str) -> int:
    """A ``subdivision`` count clamped to [3, 1024]: 0 divided by zero, 10^6 asked for 10^12 vertices."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float("nan")
    if not math.isfinite(number):
        logger.warning("%s subdivision %r is not a number; using %d", what, value, default)
        return default
    clamped = min(max(int(number), MIN_DIVISIONS), MAX_DIVISIONS)
    if clamped != int(number):
        logger.warning("%s subdivision %r is outside [%d, %d]; using %d", what, value, MIN_DIVISIONS, MAX_DIVISIONS,
                       clamped)
    return clamped


def export_sample_limit() -> int:
    try:
        value = int(os.environ.get(MAX_EXPORT_SAMPLES_ENV, ""))
    except ValueError:
        return MAX_EXPORT_SAMPLES
    return value if value > 0 else MAX_EXPORT_SAMPLES


def thin_keys(keys: list, limit: int, what: str) -> list:
    """At most ``limit`` keys, evenly spaced, the first and the last always kept; a warning when any are dropped."""
    if len(keys) <= limit or limit < 2:
        return keys
    step = (len(keys) - 1) / (limit - 1)
    kept = [keys[round(i * step)] for i in range(limit)]
    logger.warning("%s has %d keys, over the budget of %d; %d evenly spaced keys are kept", what, len(keys), limit,
                   len(kept))
    return kept


def inline_limit() -> int:
    """BLENDER_X3D_MAX_INLINES when it is a positive integer, else 1,000 Inline loads per import."""
    try:
        value = int(os.environ.get(MAX_INLINES_ENV, ""))
    except ValueError:
        return MAX_INLINES
    return value if value > 0 else MAX_INLINES
