# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Presets to graph: the click / proximity presets authored as custom properties (source/interaction.py), turned into
nodes of the scene's X3D Behaviour tree, so there is one way to carry behaviour and the person can see and rewire it.

``presets_to_graph(scene)`` adds to the scene's tree the nodes and ROUTEs the exporter writes today for a preset
(a TouchSensor or ProximitySensor inside the object, the target's own TimeSensor and the interpolators of its sampled
animation, or a BooleanFilter and the Viewpoint bind), bound to the same Blender objects, and then removes the
preset's properties so the exporter does not write the behaviour twice. The numbers (keys, key values, cycle) come from
the exporter's own extraction (``extract_scene`` with the export dialog's defaults: Animation on, every frame, -Z forward
and Y up) and are written with the exporter's own number formatting, so an export before and after the conversion holds
the same behaviour. The tour (``x3d_action`` "tour", ``x3d_tour_*``) has no nodes in the catalogue that stand for it
(the exporter writes a rig of its own), so it is left untouched and named in the notes.
"""

from __future__ import annotations

import bpy
from bpy.types import Operator
from bpy_extras.io_utils import axis_conversion

from . import behaviour_graph as bg
from . import behaviour_nodes as bn
from .emit_x3d40 import _NEVER_STARTED, _fmt, _fmt3_length, _fmt4, _fmt_short
from .extract import extract_scene
from .interaction import (ACTION_PROPERTY, RADIUS_PROPERTY, TARGET_PROPERTY, TOUR_AUTOSTART_PROPERTY,
                          TOUR_LOOP_PROPERTY, TOUR_ORDER_PROPERTY, TOUR_TRAVEL_PROPERTY, TRIGGER_PROPERTY, TRIGGERS,
                          read_interaction)

# What a converted object loses. The tour properties stay: nothing here stands in for them.
CONVERTED_PROPERTIES = (TRIGGER_PROPERTY, ACTION_PROPERTY, TARGET_PROPERTY, RADIUS_PROPERTY)
CONVERTIBLE_ACTIONS = ("animate", "viewpoint")


def _text(value):
    return str(value or "").strip().lower()


def is_convertible(obj):
    """True when the object's properties ask for a click or proximity preset with an action the graph can carry.
    Properties only: whether the target animates or exists is judged when the conversion runs."""
    trigger = obj.get(TRIGGER_PROPERTY)
    if not trigger or _text(trigger) not in TRIGGERS:
        return False
    return (_text(obj.get(ACTION_PROPERTY)) or "animate") in CONVERTIBLE_ACTIONS


def has_convertible_presets(scene):
    return any(is_convertible(obj) for obj in scene.objects)


def _safe(name):
    text = "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in name) or "Node"
    return text if (text[0].isalpha() or text[0] == "_") else "_" + text


def _free_id(graph, base):
    name, index = base, 1
    while name in graph.nodes:
        index += 1
        name = f"{base}_{index}"
    return name


def _ir_of(scene):
    """The exporter's own view of the scene with the export dialog's defaults, and the frame put back."""
    context = bpy.context
    if context.scene is scene:
        view_layer, depsgraph = context.view_layer, context.evaluated_depsgraph_get()
    else:
        view_layer = scene.view_layers[0]
        depsgraph = view_layer.depsgraph
    frame = scene.frame_current
    try:
        return extract_scene(scene, view_layer=view_layer, depsgraph=depsgraph,
                             global_matrix=axis_conversion(to_forward='-Z', to_up='Y').to_4x4(),
                             use_selection=False, use_animation=True, animation_step=1)
    finally:
        if scene.frame_current != frame:
            scene.frame_set(frame)


def _why_dropped(ir_scene, obj):
    """The exporter's own reason an object's interaction was dropped, else the usual one."""
    for line in ir_scene.diagnostics:
        if line.startswith(f"Interaction on {obj.name!r}") or line.startswith(f"Object {obj.name!r}:"):
            return line
    return "the object is not part of what the exporter writes"


def _drives_transform(graph, obj_name):
    """True when a ROUTE already writes into the Transform of this object."""
    bound = {node.id for node in graph.nodes.values()
             if node.role == bg.TARGET and node.binding == ("transform", obj_name)}
    return any(route.to_id in bound for route in graph.routes)


def _leave_notes(scene, tour_scene_props=True):
    """Notes for what is deliberately not converted: tours, and presets whose values the exporter does not understand."""
    notes = []
    for obj in sorted(scene.objects, key=lambda item: item.name):
        trigger = obj.get(TRIGGER_PROPERTY)
        if trigger and _text(trigger) in TRIGGERS and _text(obj.get(ACTION_PROPERTY) or "animate") == "tour":
            notes.append(f"Object {obj.name!r}: left alone: x3d_action 'tour' starts the camera tour, and the tour has no "
                         "nodes in the catalogue (the exporter writes its rig and timer).")
        elif trigger and not is_convertible(obj):
            diagnostics = []
            read_interaction(obj, diagnostics)
            notes.append(f"Object {obj.name!r}: left alone: " + (diagnostics[0] if diagnostics else
                         "its x3d_trigger or x3d_action is not one the exporter understands."))
        if obj.get(TOUR_ORDER_PROPERTY) is not None:
            notes.append(f"Object {obj.name!r}: left alone: x3d_tour_order makes it a stop of the camera tour, which is "
                         "not converted.")
    if tour_scene_props and any(key in scene for key in (TOUR_TRAVEL_PROPERTY, TOUR_LOOP_PROPERTY, TOUR_AUTOSTART_PROPERTY)):
        notes.append(f"Scene {scene.name!r}: left alone: the x3d_tour_* properties belong to the camera tour, which is "
                     "not converted.")
    return notes


def presets_to_graph(scene):
    """Convert the scene's click and proximity presets (``animate`` and ``viewpoint``) into nodes of its behaviour tree.

    Returns ``(converted, notes)``: how many presets became nodes, and one line for everything left alone (tour presets,
    presets the exporter would drop, a target the graph already drives) and for each thing worth knowing about what was
    done. The tree is created when the scene has none, and is not touched when nothing converts. The keyframes of an
    animated target are kept (they are the person's); the exporter ignores them for a target the graph drives."""
    notes = _leave_notes(scene)
    candidates = sorted((obj for obj in scene.objects if is_convertible(obj)), key=lambda item: item.name)
    if not candidates:
        return 0, notes

    ir_scene = _ir_of(scene)
    instances = {instance.object_name: instance for instance in ir_scene.iter_instances()}
    cycle = ir_scene.cycle_interval or 1.0
    graph = bn.read(scene) or bg.Behaviour()
    before = set(graph.nodes)
    timers = {}               # target name -> the TimeSensor this run made for it (several triggers may share it)
    converted = 0

    for obj in candidates:
        instance = instances.get(obj.name)
        interaction = instance.interaction if instance is not None else None
        if interaction is None:
            notes.append(f"Object {obj.name!r}: left alone: {_why_dropped(ir_scene, obj)}")
            continue
        made, new_timer = [], None
        try:
            target_obj = bpy.data.objects.get(interaction.target)
            click = interaction.trigger == "click"
            if interaction.action == "animate":
                timer = timers.get(interaction.target)
                if timer is None:
                    if _drives_transform(graph, interaction.target):
                        notes.append(f"Object {obj.name!r}: left alone: the graph already drives "
                                     f"{interaction.target!r}; a second timer would fight the first.")
                        continue
                    timer_id = _free_id(graph, "TT_" + _safe(interaction.target))
                    made.append(timer_id)
                    timer = new_timer = graph.add("TimeSensor", timer_id, cycleInterval=_fmt(cycle), loop="false",
                                                  startTime=_NEVER_STARTED)
                    destination = bn.transform_of(graph, target_obj)
                    safe_target = _safe(interaction.target)
                    for animation in ir_scene.animations:
                        if animation.target != interaction.target or animation.target_kind != "transform":
                            continue
                        keys = " ".join(_fmt(key) for key in animation.keys)
                        for prefix, values, text, field_name in (
                                ("PI_", animation.translations, _fmt3_length, "translation"),
                                ("OI_", animation.rotations, _fmt4, "rotation"),
                                ("SI_", animation.scales, _fmt3_length, "scale")):
                            if not values:
                                continue
                            kind = "OrientationInterpolator" if prefix == "OI_" else "PositionInterpolator"
                            node_id = _free_id(graph, prefix + safe_target)
                            made.append(node_id)
                            node = graph.add(kind, node_id, key=keys, keyValue=" ".join(text(value) for value in values))
                            timer.fraction_changed >> node.set_fraction
                            node.value_changed >> getattr(destination, field_name)
            elif interaction.action == "viewpoint":
                destination = bn.target(graph, target_obj)
            sensor_type = "TouchSensor" if click else "ProximitySensor"
            sensor_id = _free_id(graph, ("TS_" if click else "PS_") + _safe(obj.name))
            made.append(sensor_id)
            description = f"{interaction.action} {interaction.target}".strip()
            if click:
                sensor = graph.add(sensor_type, sensor_id, parent=obj.name, description=description)
            else:
                size = " ".join(_fmt_short(2.0 * interaction.radius / max(abs(axis), 1e-6))
                                for axis in instance.transform.scale)
                sensor = graph.add(sensor_type, sensor_id, parent=obj.name, description=description, center="0 0 0",
                                   size=size)
            if interaction.action == "animate":
                (sensor.touchTime if click else sensor.enterTime) >> timer.startTime
            elif click:
                # a press binds the camera; the release must not unbind it, so only the true edge goes on
                filter_id = _free_id(graph, "BF_" + _safe(obj.name))
                made.append(filter_id)
                boolean_filter = graph.add("BooleanFilter", filter_id)
                sensor.isActive >> boolean_filter.set_boolean
                boolean_filter.inputTrue >> destination.set_bind
            else:
                sensor.isActive >> destination.set_bind
        except bg.BehaviourError as error:
            for node_id in made:                 # nothing of a preset that could not be finished stays in the graph
                graph.remove(node_id)
            notes.append(f"Object {obj.name!r}: left alone: the graph cannot say it ({error}).")
            continue
        if new_timer is not None:
            timers[interaction.target] = new_timer
        for key in CONVERTED_PROPERTIES:
            if key in obj:
                del obj[key]
        converted += 1

    if converted:
        _place(graph, before)
        bn.apply(graph, scene)
        notes.append(f"{converted} preset(s) now are nodes in {scene.x3d_behaviour_tree.name!r}; their x3d_trigger, "
                     "x3d_action, x3d_target and x3d_radius properties were removed.")
        if timers:
            notes.append("The keyframes of " + ", ".join(sorted(timers)) + " were kept: the exporter ignores them for an "
                         "object the graph drives, and the timeline still plays them.")
    return converted, notes


def _place(graph, before):
    """Give the new nodes a place of their own below the nodes already in the tree."""
    new = {name for name in graph.nodes if name not in before}
    scratch = bg.Behaviour(nodes={name: graph.nodes[name] for name in new},
                           routes=[route for route in graph.routes if route.from_id in new and route.to_id in new])
    laid = bg.layout(scratch)
    floor = min((node.position[1] for name, node in graph.nodes.items() if name in before and node.position), default=None)
    drop = 0.0 if floor is None else floor - 400.0
    for name in new:
        x, y = laid.get(name, (0.0, 0.0))
        graph.nodes[name].position = (x, y + drop)


class X3D_OT_behaviour_from_presets(Operator):
    """Turn the click and proximity presets (x3d_trigger and friends) into nodes of the X3D Behaviour tree, so they can be seen and rewired there. The camera tour is left as it is"""
    bl_idname = "x3d.behaviour_from_presets"
    bl_label = "Presets to graph"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.scene is not None and has_convertible_presets(context.scene)

    def execute(self, context):
        converted, notes = presets_to_graph(context.scene)
        for note in notes:
            self.report({"WARNING"} if "left alone" in note else {"INFO"}, note)
        tree = getattr(context.scene, "x3d_behaviour_tree", None)
        if converted and tree is not None:
            bn.show_tree(context, tree)
        if not converted:
            self.report({"WARNING"}, "Presets to graph: nothing was converted.")
            return {"CANCELLED"}
        return {"FINISHED"}


def draw_button(layout, context):
    if context.scene is not None and has_convertible_presets(context.scene):
        layout.operator(X3D_OT_behaviour_from_presets.bl_idname, icon="NODETREE")


def _node_header(self, context):
    if getattr(context.space_data, "tree_type", "") == bn.TREE_IDNAME:
        draw_button(self.layout, context)


classes = (X3D_OT_behaviour_from_presets,)


def register():
    for cls in classes:
        if not getattr(cls, "is_registered", False):
            bpy.utils.register_class(cls)
    bpy.types.NODE_HT_header.append(_node_header)


def unregister():
    bpy.types.NODE_HT_header.remove(_node_header)
    for cls in reversed(classes):
        if getattr(cls, "is_registered", False):
            bpy.utils.unregister_class(cls)
