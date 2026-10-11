# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Convert between Blender's camera angle and X3D's Viewpoint.fieldOfView.

The two measure different things. X3D's fieldOfView is the angle across the
smaller side of the display (ISO/IEC 19775-1, 23.4.5 Viewpoint). Blender's
``Camera.angle`` is measured across the sensor's fitted side: with the default
AUTO fit that is the larger side of the render, so a 16:9 Blender camera
written unchanged opens about 1.8 times too wide in an X3D browser.

Pure Python so the emitters and the tests can use it without Blender.
"""

from __future__ import annotations

import math


def _fit(sensor_fit: str, width: float, height: float) -> str:
    if sensor_fit in {"HORIZONTAL", "VERTICAL"}:
        return sensor_fit
    return "HORIZONTAL" if width >= height else "VERTICAL"


def x3d_field_of_view(angle: float, sensor_fit: str, width: float, height: float) -> float:
    """Blender camera angle (across the fitted side) -> X3D fieldOfView (across the smaller side)."""
    if width <= 0 or height <= 0:
        return angle
    fit = _fit(sensor_fit, width, height)
    t = math.tan(angle / 2.0)
    tx, ty = (t, t * height / width) if fit == "HORIZONTAL" else (t * width / height, t)
    return 2.0 * math.atan(min(tx, ty))


def blender_camera_angle(field_of_view: float, sensor_fit: str, width: float, height: float) -> float:
    """X3D fieldOfView (across the smaller side) -> Blender camera angle (across the fitted side)."""
    if width <= 0 or height <= 0:
        return field_of_view
    fit = _fit(sensor_fit, width, height)
    t = math.tan(field_of_view / 2.0)
    tx, ty = (t * width / height, t) if width >= height else (t, t * height / width)
    return 2.0 * math.atan(tx if fit == "HORIZONTAL" else ty)


def render_size(scene) -> tuple[float, float]:
    """Display width and height of a Blender scene's render, pixel aspect included."""
    render = scene.render
    return (render.resolution_x * render.pixel_aspect_x, render.resolution_y * render.pixel_aspect_y)
