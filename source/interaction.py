# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""ROUTE interaction scaffolding authored from Blender custom properties.

A Blender scene cannot say "click this and it plays". X3D can, in pure X3D, with no Script: a sensor inside the
object's Transform, a TimeSensor and the ROUTEs between them. This module reads the custom properties that author
that and writes the nodes.

Object custom properties (string values, or ints / floats where noted)::

    x3d_trigger   "click" | "proximity"           which sensor goes inside the object's Transform
    x3d_action    "animate" | "viewpoint" | "tour"  what the sensor fires
    x3d_target    object name                     animate: the object whose animation plays (default: this object);
                                                  viewpoint: the camera to bind
    x3d_radius    float, metres                   proximity only: the sensor box is 2 x radius on each side (default 3)

Camera custom properties (the viewpoint tour)::

    x3d_tour_order  int > 0     the camera is a tour stop; stops are visited in this order
    x3d_tour_dwell  float, s    how long the tour rests there (default 2)

Scene custom properties::

    x3d_tour_travel     float, s  flight time between stops (default 3)
    x3d_tour_loop       bool      the tour repeats
    x3d_tour_autostart  bool      the tour starts when the file loads (and repeats: a TimeSensor that starts at load
                                  with no startTime has no way to stop after one cycle)

The animation an ``animate`` action plays is the object's sampled transform animation, so Export > Animation must be
on. An object that some trigger targets stops being driven by the always-looping scene timer and gets a timer of its
own (loop false, started by the trigger).

No ``bpy`` import: ``read_interaction`` and ``read_tour`` take anything with ``.get``.
"""

from __future__ import annotations

try:
    from .ir import IRInteraction, IRTour, IRTourStop
except ImportError:  # pragma: no cover - standalone test fallback
    from ir import IRInteraction, IRTour, IRTourStop

TRIGGER_PROPERTY = "x3d_trigger"
ACTION_PROPERTY = "x3d_action"
TARGET_PROPERTY = "x3d_target"
RADIUS_PROPERTY = "x3d_radius"
TOUR_ORDER_PROPERTY = "x3d_tour_order"
TOUR_DWELL_PROPERTY = "x3d_tour_dwell"
TOUR_TRAVEL_PROPERTY = "x3d_tour_travel"
TOUR_LOOP_PROPERTY = "x3d_tour_loop"
TOUR_AUTOSTART_PROPERTY = "x3d_tour_autostart"

TRIGGERS = ("click", "proximity")
ACTIONS = ("animate", "viewpoint", "tour")
DEFAULT_RADIUS = 3.0
DEFAULT_DWELL = 2.0
DEFAULT_TRAVEL = 3.0


def _number(value, default, *, minimum=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number >= minimum and number == number else default


def read_interaction(obj, diagnostics=None):
    """The IRInteraction an object's custom properties author, or None. Unknown values are reported, not guessed."""
    trigger = obj.get(TRIGGER_PROPERTY)
    if not trigger:
        return None
    note = diagnostics.append if diagnostics is not None else (lambda _message: None)
    trigger = str(trigger).strip().lower()
    action = str(obj.get(ACTION_PROPERTY) or "animate").strip().lower()
    if trigger not in TRIGGERS:
        note(f"Object {obj.name!r}: x3d_trigger {trigger!r} is not one of {', '.join(TRIGGERS)}; no sensor written.")
        return None
    if action not in ACTIONS:
        note(f"Object {obj.name!r}: x3d_action {action!r} is not one of {', '.join(ACTIONS)}; no sensor written.")
        return None
    target = str(obj.get(TARGET_PROPERTY) or "").strip()
    if action == "animate" and not target:
        target = obj.name
    if action == "viewpoint" and not target:
        note(f"Object {obj.name!r}: x3d_action 'viewpoint' needs x3d_target (the camera to bind); no sensor written.")
        return None
    radius = _number(obj.get(RADIUS_PROPERTY), DEFAULT_RADIUS, minimum=1e-6) if trigger == "proximity" else DEFAULT_RADIUS
    return IRInteraction(source=obj.name, trigger=trigger, action=action, target=target, radius=radius)


def read_tour(cameras, scene, transform_of):
    """An IRTour from the cameras that carry x3d_tour_order, or None.

    ``transform_of(camera)`` returns the camera's IRTransform in the exported frame (scale dropped by the caller's
    choice: a Viewpoint has none).
    """
    stops = []
    for camera in cameras:
        order = camera.get(TOUR_ORDER_PROPERTY)
        if order is None:
            continue
        order = _number(order, 0.0, minimum=1e-9)
        if order <= 0:
            continue
        stops.append((order, camera.name, camera))
    if not stops:
        return None
    stops.sort(key=lambda item: (item[0], item[1]))
    tour = IRTour(
        travel=_number(scene.get(TOUR_TRAVEL_PROPERTY), DEFAULT_TRAVEL),
        loop=bool(scene.get(TOUR_LOOP_PROPERTY)),
        autostart=bool(scene.get(TOUR_AUTOSTART_PROPERTY)),
    )
    for _order, name, camera in stops:
        tour.stops.append(IRTourStop(
            name=name,
            transform=transform_of(camera),
            dwell=_number(camera.get(TOUR_DWELL_PROPERTY), DEFAULT_DWELL),
            field_of_view=None,
        ))
    return tour


def tour_timeline(tour):
    """(keys, total_seconds): interpolator keys (fractions) for two entries per stop, arrive then leave."""
    times = []
    clock = 0.0
    for index, stop in enumerate(tour.stops):
        times.append(clock)
        clock += stop.dwell
        times.append(clock)
        if index < len(tour.stops) - 1:
            clock += tour.travel
    total = clock
    if total <= 0:
        return [0.0 for _ in times], 0.0
    return [time / total for time in times], total


def check_interactions(ir_scene, diagnostics):
    """Report interactions whose target cannot be reached; returns the instances whose sensor is kept."""
    by_object = {instance.object_name: instance for instance in ir_scene.iter_instances()}
    animated = {animation.target for animation in ir_scene.animations if animation.target_kind == "transform"}
    has_tour = ir_scene.tour is not None and bool(ir_scene.tour.stops)
    for instance in ir_scene.iter_instances():
        interaction = instance.interaction
        if interaction is None:
            continue
        reason = None
        if interaction.action == "animate":
            if interaction.target not in by_object:
                reason = f"target {interaction.target!r} is not an exported object"
            elif interaction.target not in animated:
                reason = (f"{interaction.target!r} has no animation to play (turn Animation on in the export dialog "
                          "and keyframe or drive its transform)")
        elif interaction.action == "viewpoint":
            target = by_object.get(interaction.target)
            if target is None or target.viewpoint is None:
                reason = f"{interaction.target!r} is not an exported camera"
        elif interaction.action == "tour" and not has_tour:
            reason = "no camera carries x3d_tour_order"
        if reason:
            diagnostics.append(f"Interaction on {instance.object_name!r} ({interaction.trigger} -> {interaction.action}) "
                               f"dropped: {reason}.")
            instance.interaction = None
