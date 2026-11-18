# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Object-properties panel that authors the ROUTE interaction custom properties (see interaction.py).

The panel only writes and clears custom properties; the exporter reads them. A scene authored by hand with the same
property names exports identically.
"""

import bpy

from .interaction import (ACTION_PROPERTY, RADIUS_PROPERTY, TARGET_PROPERTY, TOUR_AUTOSTART_PROPERTY,
                          TOUR_DWELL_PROPERTY, TOUR_LOOP_PROPERTY, TOUR_ORDER_PROPERTY, TOUR_TRAVEL_PROPERTY,
                          TRIGGER_PROPERTY)

_OBJECT_PROPS = (TRIGGER_PROPERTY, ACTION_PROPERTY, TARGET_PROPERTY, RADIUS_PROPERTY, TOUR_ORDER_PROPERTY,
                 TOUR_DWELL_PROPERTY)

_PRESETS = (
    ("CLICK_ANIMATE", "Click plays this animation", "A click on this object plays its own animation once"),
    ("PROXIMITY_ANIMATE", "Walk up plays this animation", "Coming within the radius plays this animation once"),
    ("CLICK_VIEWPOINT", "Click jumps to a camera", "A click binds the camera named in Target"),
    ("CLICK_TOUR", "Click starts the camera tour", "A click starts the tour through the cameras marked as stops"),
    ("TOUR_STOP", "This camera is a tour stop", "Adds the camera to the viewpoint tour"),
    ("CLEAR", "Clear all X3D interaction", "Remove every x3d_trigger / x3d_tour property from this object"),
)


class X3D_OT_interaction_preset(bpy.types.Operator):
    """Set the X3D interaction custom properties of the active object"""
    bl_idname = "object.x3d_interaction_preset"
    bl_label = "X3D Interaction Preset"
    bl_options = {"REGISTER", "UNDO"}

    preset: bpy.props.EnumProperty(name="Preset", items=_PRESETS)

    @classmethod
    def poll(cls, context):
        return context.object is not None

    def execute(self, context):
        obj = context.object
        for key in _OBJECT_PROPS:
            if key in obj:
                del obj[key]
        preset = self.preset
        if preset == "CLICK_ANIMATE":
            obj[TRIGGER_PROPERTY], obj[ACTION_PROPERTY] = "click", "animate"
        elif preset == "PROXIMITY_ANIMATE":
            obj[TRIGGER_PROPERTY], obj[ACTION_PROPERTY], obj[RADIUS_PROPERTY] = "proximity", "animate", 3.0
        elif preset == "CLICK_VIEWPOINT":
            obj[TRIGGER_PROPERTY], obj[ACTION_PROPERTY], obj[TARGET_PROPERTY] = "click", "viewpoint", ""
        elif preset == "CLICK_TOUR":
            obj[TRIGGER_PROPERTY], obj[ACTION_PROPERTY] = "click", "tour"
        elif preset == "TOUR_STOP":
            if obj.type != "CAMERA":
                self.report({"WARNING"}, "Tour stops are cameras")
                return {"CANCELLED"}
            obj[TOUR_ORDER_PROPERTY], obj[TOUR_DWELL_PROPERTY] = 1, 2.0
        return {"FINISHED"}


class X3D_PT_interaction(bpy.types.Panel):
    bl_label = "X3D Interaction"
    bl_idname = "OBJECT_PT_x3d_interaction"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context.object is not None

    def draw(self, context):
        layout, obj = self.layout, context.object
        for key in _OBJECT_PROPS:
            if key in obj:
                layout.prop(obj, f'["{key}"]', text=key[4:].replace("_", " ").capitalize())
        layout.label(text="Set up:")
        col = layout.column(align=True)
        for ident, label, _description in _PRESETS:
            col.operator(X3D_OT_interaction_preset.bl_idname, text=label).preset = ident
        if context.scene is not None:
            box = layout.box()
            box.label(text="Tour (scene)")
            for key in (TOUR_TRAVEL_PROPERTY, TOUR_LOOP_PROPERTY, TOUR_AUTOSTART_PROPERTY):
                if key in context.scene:
                    box.prop(context.scene, f'["{key}"]', text=key[4:].replace("_", " ").capitalize())
            if TOUR_TRAVEL_PROPERTY not in context.scene:
                box.operator("object.x3d_interaction_tour_defaults", text="Add tour settings")


class X3D_OT_interaction_tour_defaults(bpy.types.Operator):
    """Add the scene-level tour custom properties"""
    bl_idname = "object.x3d_interaction_tour_defaults"
    bl_label = "Add X3D Tour Settings"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        scene[TOUR_TRAVEL_PROPERTY] = 3.0
        scene[TOUR_LOOP_PROPERTY] = False
        scene[TOUR_AUTOSTART_PROPERTY] = False
        return {"FINISHED"}


classes = (X3D_OT_interaction_preset, X3D_OT_interaction_tour_defaults, X3D_PT_interaction)
