# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Editor style: make the X3D Behaviour node editor look the way you like.

An "Editor style" panel in the node editor's sidebar (X3D tab) with:

* a theme (Classic, Neon, Synthwave, Pastel, Candy, Mono) that colours the nodes by family (timers, sensors,
  interpolators, followers, logic, scripts, scene, looks, lights, cameras) and the events travelling along the links;
* packet size, glow strength and trail length for the live activity overlay (behaviour_activity);
* Rainbow (packets cycle through hues as they travel) and Sparkle (live links twinkle);
* presets: Party, Calm, Classic, and Surprise me.

Settings live on the scene (``scene.x3d_style``), so they are saved with the file. Classic changes nothing: the editor
looks as it did before this module. The theme only paints nodes while nothing is playing; the Play glow keeps each
node's colour and gives it back (behaviour_play).
"""
from __future__ import annotations

import colorsys
import math
import random

try:            # module level: Blender reads the property annotations below as strings, in this module's globals
    import bpy
except ImportError:         # plain Python (the colour and family helpers need no Blender)
    bpy = None

THEMES = (
    ("CLASSIC", "Classic", "The editor as it was: no node colours, events in their field type's colour", "NODETREE"),
    ("NEON", "Neon", "Saturated colours on dark nodes: events glow hot", "LIGHT_SUN"),
    ("SYNTHWAVE", "Synthwave", "Pink, violet and cyan, like an 80s horizon", "COLORSET_06_VEC"),
    ("PASTEL", "Pastel", "Soft colours, gentle glow", "COLORSET_14_VEC"),
    ("CANDY", "Candy", "Every family its own bright sweet", "COLORSET_03_VEC"),
    ("MONO", "Mono", "Grey nodes and one accent colour for every event", "IMAGE_ALPHA"),
)

ORIGINAL = "x3d_style_original"      # a node's own colour before a theme painted it: [custom?, r, g, b]
FAMILIES = ("timer", "sensor", "interpolator", "follower", "logic", "script", "scene", "look", "light", "camera", "other")

# Node colours per theme and family: dark enough that the node's text stays readable.
NODE_COLOURS = {
    "NEON": {"timer": (0.35, 0.25, 0.02), "sensor": (0.38, 0.05, 0.12), "interpolator": (0.05, 0.18, 0.38),
             "follower": (0.03, 0.30, 0.30), "logic": (0.10, 0.30, 0.05), "script": (0.30, 0.10, 0.35),
             "scene": (0.16, 0.16, 0.20), "look": (0.35, 0.18, 0.02), "light": (0.36, 0.33, 0.04),
             "camera": (0.08, 0.10, 0.32), "other": (0.18, 0.18, 0.18)},
    "SYNTHWAVE": {"timer": (0.34, 0.08, 0.28), "sensor": (0.38, 0.06, 0.20), "interpolator": (0.18, 0.08, 0.36),
                  "follower": (0.06, 0.24, 0.34), "logic": (0.24, 0.06, 0.34), "script": (0.30, 0.05, 0.30),
                  "scene": (0.12, 0.08, 0.22), "look": (0.32, 0.12, 0.30), "light": (0.36, 0.20, 0.10),
                  "camera": (0.05, 0.20, 0.30), "other": (0.14, 0.10, 0.20)},
    "PASTEL": {"timer": (0.42, 0.38, 0.26), "sensor": (0.42, 0.28, 0.30), "interpolator": (0.27, 0.33, 0.43),
               "follower": (0.26, 0.40, 0.38), "logic": (0.30, 0.40, 0.28), "script": (0.38, 0.30, 0.42),
               "scene": (0.32, 0.32, 0.34), "look": (0.43, 0.34, 0.27), "light": (0.43, 0.41, 0.28),
               "camera": (0.28, 0.30, 0.42), "other": (0.32, 0.32, 0.32)},
    "CANDY": {"timer": (0.45, 0.30, 0.00), "sensor": (0.48, 0.05, 0.18), "interpolator": (0.00, 0.25, 0.48),
              "follower": (0.00, 0.40, 0.33), "logic": (0.18, 0.42, 0.00), "script": (0.38, 0.00, 0.45),
              "scene": (0.25, 0.20, 0.30), "look": (0.48, 0.15, 0.00), "light": (0.45, 0.42, 0.00),
              "camera": (0.10, 0.12, 0.45), "other": (0.25, 0.25, 0.25)},
    "MONO": {family: (0.17, 0.17, 0.18) for family in FAMILIES},
}

PRESETS = {
    "PARTY": {"theme": "CANDY", "tint_nodes": True, "packet_size": 1.8, "glow": 2.2, "trail": 2.5, "rainbow": True,
              "sparkle": True},
    "CALM": {"theme": "PASTEL", "tint_nodes": True, "packet_size": 0.8, "glow": 0.6, "trail": 0.7, "rainbow": False,
             "sparkle": False},
    "CLASSIC": {"theme": "CLASSIC", "tint_nodes": True, "packet_size": 1.0, "glow": 1.0, "trail": 1.0, "rainbow": False,
                "sparkle": False},
}


def family(x3d_type: str) -> str:
    """Which family a node belongs to, from its X3D type."""
    t = x3d_type or ""
    if t == "TimeSensor":
        return "timer"
    if t.endswith("Sensor"):
        return "sensor"
    if "Interpolator" in t or t == "EaseInEaseOut":
        return "interpolator"
    if t.endswith(("Damper", "Chaser", "Damper2D", "Chaser2D")):
        return "follower"
    if t.startswith(("Boolean", "Integer")) or t == "TimeTrigger":
        return "logic"
    if t == "Script":
        return "script"
    if t in ("Transform", "Group", "Switch", "Billboard", "Collision", "LOD") or t.startswith("HAnim"):
        return "scene"
    if t.endswith(("Material", "Shader")) or t.startswith("Texture") or t in ("Appearance", "Text"):
        return "look"
    if t.endswith("Light"):
        return "light"
    if t.endswith("Viewpoint"):
        return "camera"
    return "other"


# -- colours for the activity overlay (behaviour_activity._colour asks here) ----------------------------------------

def _style(scene=None):
    try:
        import bpy
        scene = scene or bpy.context.scene
        return getattr(scene, "x3d_style", None)
    except Exception:       # noqa: BLE001 - no bpy (plain Python tests) or no scene
        return None


def field_colour(base, x3d_type, now, style=None):
    """An event's colour under the theme: ``base`` is the field type's own colour (behaviour_nodes._COLOURS)."""
    style = style or _style()
    if style is None:
        return tuple(base)
    r, g, b = base[:3]
    theme = style.theme
    if style.rainbow:
        hue = (now * 0.35 + (hash(x3d_type) % 97) / 97.0) % 1.0
        return colorsys.hsv_to_rgb(hue, 0.85, 1.0)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if theme == "NEON":
        return colorsys.hsv_to_rgb(h, min(1.0, s * 1.6 + 0.2), 1.0)
    if theme == "SYNTHWAVE":            # fold every hue into the pink-violet-cyan band
        return colorsys.hsv_to_rgb(0.5 + (h % 1.0) * 0.42, 0.8, 1.0)
    if theme == "PASTEL":
        return colorsys.hsv_to_rgb(h, s * 0.45, min(1.0, v * 0.6 + 0.4))
    if theme == "CANDY":
        return colorsys.hsv_to_rgb(h, 1.0, 1.0)
    if theme == "MONO":
        return (1.0, 0.55, 0.15)
    return (r, g, b)


def scales(style=None):
    """(packet size, glow, trail) multipliers for the overlay; 1, 1, 1 without a style."""
    style = style or _style()
    if style is None:
        return 1.0, 1.0, 1.0
    return style.packet_size, style.glow, style.trail


def sparkle_on(style=None):
    style = style or _style()
    return bool(style is not None and style.sparkle)


def sparkle_points(points, now, count=6, seed=0):
    """Twinkling spots along a link: positions and brightness (0-1) that change with time."""
    rng = random.Random(seed + int(now * 12))
    out = []
    for _ in range(count):
        i = rng.randrange(max(1, len(points) - 1))
        a, b = points[i], points[min(i + 1, len(points) - 1)]
        f = rng.random()
        out.append(((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f),
                    0.5 + 0.5 * math.sin(now * 9.0 + rng.random() * 6.28)))
    return out


# -- painting the nodes ---------------------------------------------------------------------------------------------

def _trees():
    import bpy
    from . import behaviour_nodes
    return [t for t in bpy.data.node_groups if getattr(t, "bl_idname", "") == behaviour_nodes.TREE_IDNAME]


def _playing():
    try:
        from . import behaviour_play
        return behaviour_play._running.get("player") is not None
    except Exception:       # noqa: BLE001
        return False


def paint(scene=None):
    """Colour every behaviour node by family under the scene's theme (Classic: take the colours off). Returns how many
    nodes changed; nothing while the graph plays (the Play glow owns the colours then)."""
    style = _style(scene)
    if style is None or _playing():
        return 0
    palette = NODE_COLOURS.get(style.theme) if style.tint_nodes else None
    changed = 0
    for tree in _trees():
        for node in tree.nodes:
            x3d_type = getattr(node, "x3d_type", None)
            if x3d_type is None:
                continue
            if palette is None:                     # Classic: each node's own colour back, exactly as it was
                saved = node.get(ORIGINAL)
                if saved is not None:
                    node.use_custom_color = bool(saved[0])
                    node.color = tuple(saved[1:4])
                    del node[ORIGINAL]
                    changed += 1
                continue
            if node.get(ORIGINAL) is None:          # remembered once, before the first theme paints it
                node[ORIGINAL] = [float(node.use_custom_color), *node.color]
            node.use_custom_color = True
            node.color = palette[family(x3d_type)]
            changed += 1
    _redraw()
    return changed


def _redraw():
    import bpy
    for window in getattr(bpy.context.window_manager, "windows", []):
        for area in window.screen.areas:
            if area.type == "NODE_EDITOR":
                area.tag_redraw()


def _changed(self, context):
    paint(context.scene)


# -- Blender classes ------------------------------------------------------------------------------------------------

_classes = []


def _build():
    import bpy

    class X3DEditorStyle(bpy.types.PropertyGroup):
        theme: bpy.props.EnumProperty(name="Theme", items=[(*item, number) for number, item in enumerate(THEMES)],
                                      default="CLASSIC", update=_changed)      # an item with an icon needs a number
        tint_nodes: bpy.props.BoolProperty(name="Colour nodes by family", default=True, update=_changed)
        packet_size: bpy.props.FloatProperty(name="Packet size", default=1.0, min=0.3, max=3.0, update=_changed)
        glow: bpy.props.FloatProperty(name="Glow", default=1.0, min=0.0, max=3.0, update=_changed)
        trail: bpy.props.FloatProperty(name="Trail", default=1.0, min=0.2, max=4.0, update=_changed)
        rainbow: bpy.props.BoolProperty(name="Rainbow", description="Events cycle through hues as they travel",
                                        default=False, update=_changed)
        sparkle: bpy.props.BoolProperty(name="Sparkle", description="Live links twinkle", default=False,
                                        update=_changed)

    class X3D_OT_style_preset(bpy.types.Operator):
        """Apply a look in one click"""
        bl_idname = "x3d.style_preset"
        bl_label = "Style preset"
        bl_options = {"REGISTER", "UNDO"}
        preset: bpy.props.EnumProperty(items=[(k, k.title(), "") for k in PRESETS] + [("SURPRISE", "Surprise me", "")])

        def execute(self, context):
            style = context.scene.x3d_style
            if self.preset == "SURPRISE":
                values = {"theme": random.choice([t[0] for t in THEMES[1:]]), "tint_nodes": True,
                          "packet_size": round(random.uniform(0.6, 2.6), 2), "glow": round(random.uniform(0.4, 2.8), 2),
                          "trail": round(random.uniform(0.4, 3.5), 2), "rainbow": random.random() < 0.4,
                          "sparkle": random.random() < 0.5}
            else:
                values = PRESETS[self.preset]
            for key, value in values.items():
                setattr(style, key, value)
            painted = paint(context.scene)
            self.report({"INFO"}, f"{self.preset.title()}: {style.theme.title()} theme, {painted} node(s) painted")
            return {"FINISHED"}

    class X3D_PT_editor_style(bpy.types.Panel):
        bl_label = "Editor style"
        bl_space_type = "NODE_EDITOR"
        bl_region_type = "UI"
        bl_category = "X3D"

        @classmethod
        def poll(cls, context):
            from . import behaviour_nodes
            space = context.space_data
            return getattr(space, "tree_type", "") == behaviour_nodes.TREE_IDNAME

        def draw(self, context):
            style = context.scene.x3d_style
            layout = self.layout
            row = layout.row(align=True)
            for key, icon in (("PARTY", "FUND"), ("CALM", "HEART"), ("CLASSIC", "LOOP_BACK")):
                row.operator("x3d.style_preset", text=key.title(), icon=icon).preset = key
            layout.operator("x3d.style_preset", text="Surprise me", icon="LIGHT").preset = "SURPRISE"
            layout.label(text="Theme")
            grid = layout.grid_flow(columns=3, align=True)
            grid.prop(style, "theme", expand=True)
            layout.prop(style, "tint_nodes")
            col = layout.column(align=True)
            col.label(text="Events while playing")
            col.prop(style, "packet_size", slider=True)
            col.prop(style, "glow", slider=True)
            col.prop(style, "trail", slider=True)
            row = layout.row(align=True)
            row.prop(style, "rainbow", toggle=True, icon="COLOR")
            row.prop(style, "sparkle", toggle=True, icon="SHADERFX")

    _classes[:] = [X3DEditorStyle, X3D_OT_style_preset, X3D_PT_editor_style]


def register():
    import bpy
    if not _classes:
        _build()
    for cls in _classes:
        if not getattr(cls, "is_registered", False):
            bpy.utils.register_class(cls)
    bpy.types.Scene.x3d_style = bpy.props.PointerProperty(type=_classes[0])


def unregister():
    import bpy
    if hasattr(bpy.types.Scene, "x3d_style"):
        del bpy.types.Scene.x3d_style
    for cls in reversed(_classes):
        if getattr(cls, "is_registered", False):
            bpy.utils.unregister_class(cls)
