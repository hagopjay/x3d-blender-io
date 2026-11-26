# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Play the X3D behaviour graph in Blender: the scene does in the viewport what the exported file will do in a browser.

``Player(scene)`` reads the scene's behaviour node tree, runs it with ``behaviour_sim.Simulation`` and writes every
value that reaches a target onto the Blender datablock it is bound to. ``stop()`` puts everything back.

    player = Player(scene)
    player.start(0.0)
    player.press(button_object, 1.0)      # the pointer goes down on an object a sensor senses
    player.release(1.1)
    player.step(2.5)                      # the door is now where the file's browser would have it at 2.5 s
    player.stop()                         # and back where it was

The operator ``x3d.behaviour_play`` is the same thing driven by the mouse and a timer; it needs a window.

Axes. The exporter writes a root object's Transform as ``global_matrix @ matrix_world`` and a child's as its matrix in
its parent's space. The player turns each object into that Transform once, changes the field an event set, and turns it
back, so a value means here what it means in the file.
"""

import json
import math
import time

import bpy
from bpy_extras.io_utils import axis_conversion
from mathutils import Matrix, Quaternion, Vector

from . import behaviour_graph as bg
from . import behaviour_nodes
from .behaviour_sim import POINTING, Simulation

EXPORT_AXES = axis_conversion(to_forward='-Z', to_up='Y').to_4x4()      # the export dialog's default: -Z forward, Y up


def _srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


GLOW_COLOUR = (0.95, 0.62, 0.15)   # a node that sends an event is tinted towards this
GLOW_FLASH = 0.85                  # how far, for an event that starts a run (1: all the way)
GLOW_BUSY = 0.35                   # how far, while a node keeps sending (a running timer): its text stays readable

# Keys: what a browser's key event would say for a Blender key event, as (key, which). The simulator's KeySensor and
# StringSensor read ``key`` (the character or the name) and ``which`` (the key code), as X_ITE's do.
KEY_SENSORS = ("KeySensor", "StringSensor")
_KEYS = {"LEFT_SHIFT": ("Shift", 16), "RIGHT_SHIFT": ("Shift", 16), "LEFT_CTRL": ("Control", 17),
         "RIGHT_CTRL": ("Control", 17), "LEFT_ALT": ("Alt", 18), "RIGHT_ALT": ("Alt", 18),
         "RET": ("Enter", 13), "NUMPAD_ENTER": ("Enter", 13), "BACK_SPACE": ("Backspace", 8), "DEL": ("Delete", 46),
         "TAB": ("Tab", 9), "SPACE": (" ", 32), "UP_ARROW": ("ArrowUp", 38), "DOWN_ARROW": ("ArrowDown", 40),
         "LEFT_ARROW": ("ArrowLeft", 37), "RIGHT_ARROW": ("ArrowRight", 39), "HOME": ("Home", 36),
         "END": ("End", 35), "PAGE_UP": ("PageUp", 33), "PAGE_DOWN": ("PageDown", 34),
         **{f"F{n}": (f"F{n}", 111 + n) for n in range(1, 13)}}
_DIGITS = ("ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE")


def x3d_key(event):
    """(key, which) of a Blender keyboard event as a browser would name it, or None for a key X3D has no name for
    (and for the mouse). A character comes from the event's own text when it has one (the keyboard layout and Shift
    are already in it), else from the key's name."""
    kind = event.type
    if kind in _KEYS:
        return _KEYS[kind]
    char = event.unicode if len(getattr(event, "unicode", "") or "") == 1 else ""
    if not char:
        if len(kind) == 1 and kind.isalpha():
            char = kind.upper() if event.shift else kind.lower()
        elif kind in _DIGITS:
            char = str(_DIGITS.index(kind))
    if not char:
        return None
    return char, ord(char.upper()) if char.isalnum() else ord(char)


def is_keyboard(event):
    """True for a Blender event that comes from a key (not the pointer, the timer or a 3D mouse)."""
    return event.value in ("PRESS", "RELEASE") and not event.type.endswith("MOUSE") \
        and not event.type.startswith(("NDOF", "TIMER", "WINDOW", "TRACKPAD", "MOUSE", "INBETWEEN"))


def _texture_matrix(values, center):
    """An X3D TextureTransform as a 3x3 on (s, t, 1): translation * center * rotation * scale * -center."""
    tx, ty = values["translation"]
    sx, sy = values["scale"]
    cx, cy = center
    c, d = math.cos(values["rotation"]), math.sin(values["rotation"])
    move = lambda x, y: Matrix(((1, 0, x), (0, 1, y), (0, 0, 1)))               # noqa: E731
    return move(tx, ty) @ move(cx, cy) @ Matrix(((c, -d, 0), (d, c, 0), (0, 0, 1))) @ \
        Matrix(((sx, 0, 0), (0, sy, 0), (0, 0, 1))) @ move(-cx, -cy)


def _mapping_matrix(socket_values):
    """What a Mapping node (type Point) does to a texture coordinate, as a 3x3: Location + Rotation Z * Scale * v."""
    (lx, ly, _lz), (_rx, _ry, rz), (sx, sy, _sz) = (tuple(socket_values[n]) for n in ("Location", "Rotation", "Scale"))
    c, d = math.cos(rz), math.sin(rz)
    return Matrix(((c * sx, -d * sy, lx), (d * sx, c * sy, ly), (0, 0, 1)))


def _initial_texture_transform(material):
    """The authored TextureTransform recorded on the material at import (``x3d_texture_transform``, JSON), as numbers;
    the X3D defaults when there is none."""
    try:
        raw = json.loads(material.get("x3d_texture_transform") or "{}")
    except ValueError:
        raw = {}
    numbers = lambda key, default: tuple(float(v) for v in str(raw.get(key, default)).replace(",", " ").split())   # noqa: E731
    try:
        return {"translation": numbers("translation", "0 0")[:2], "rotation": numbers("rotation", "0")[0],
                "scale": numbers("scale", "1 1")[:2], "center": numbers("center", "0 0")[:2]}
    except (ValueError, IndexError):
        return {"translation": (0.0, 0.0), "rotation": 0.0, "scale": (1.0, 1.0), "center": (0.0, 0.0)}


class _TransformState:
    """One object as the X3D Transform the exporter writes for it."""

    def __init__(self, obj, global_matrix):
        self.obj, self.basis = obj, obj.matrix_basis.copy()
        if obj.parent is None:
            self.outer = global_matrix.inverted()                     # matrix_basis = outer @ X3D matrix
            local = global_matrix @ obj.matrix_basis
        else:
            self.outer = obj.matrix_parent_inverse.inverted()
            local = obj.matrix_parent_inverse @ obj.matrix_basis
        self.location, self.rotation, self.scale = local.decompose()

    def write(self):
        self.obj.matrix_basis = self.outer @ Matrix.LocRotScale(self.location, self.rotation, self.scale)

    def restore(self):
        self.obj.matrix_basis = self.basis


class Player:
    """A scene's behaviour graph, running on the scene's own objects."""

    def __init__(self, scene, graph=None, *, global_matrix=None, flash=True):
        self.scene = scene
        self.graph = graph if graph is not None else behaviour_nodes.read(scene)
        if self.graph is None:
            raise bg.BehaviourError("no-graph", "this scene has no X3D Behaviour node tree to play")
        self.sim = Simulation(self.graph)
        self.global_matrix = global_matrix if global_matrix is not None else EXPORT_AXES
        self.not_applied = []          # "Type.field" an event reached but the player does not show
        self.now = 0.0
        self._transforms, self._hidden, self._materials, self._lights, self._camera = {}, {}, {}, {}, scene.camera
        self._over, self._held, self._plane = [], [], {}
        self._sensors = {}             # Blender object name (None: the scene root) -> [sensor id, ...]
        for node in self.graph.nodes.values():
            if node.role == bg.BEHAVIOUR and node.node_type in POINTING:
                self._sensors.setdefault(node.parent, []).append(node.id)
        self._keys = [node_id for node_id, node in self.graph.nodes.items()
                      if node.role == bg.BEHAVIOUR and node.node_type in KEY_SENSORS]
        self._down = {}                # Blender key -> (key, which) it went down as, so it comes up as the same key
        self._flash = self._tree_nodes() if flash else {}
        self._colours = {}
        self._maps = {}              # material name -> the Mapping nodes Play drives for a TextureTransform, and how to undo them
        self._burst = {}             # node id -> when its current run of events began (for the glow)

    # -- what can be clicked ------------------------------------------------------------------------------------

    def sensors_for(self, obj):
        """The pointing sensors that sense ``obj``: those of the nearest object above it that has any (X3D: the
        sensors lowest in the hierarchy win), else the ones at the scene root."""
        while obj is not None:
            found = self._sensors.get(obj.name)
            if found:
                return list(found)
            obj = obj.parent
        return list(self._sensors.get(None, ()))

    def sensed_objects(self):
        """Every object some pointing sensor senses (the things worth clicking)."""
        return [obj for obj in self.scene.objects if self.sensors_for(obj)]

    def _frame(self, sensor_id):
        """Sensor coordinates -> Blender world. A sensor shares its parent Transform's coordinates."""
        parent = self.graph.nodes[sensor_id].parent
        obj = bpy.data.objects.get(parent) if parent else None
        return obj.matrix_world.copy() if obj is not None else self.global_matrix.inverted()

    # -- time and the pointer -----------------------------------------------------------------------------------

    def start(self, now=0.0):
        self.now = now
        self._apply(self.sim.start(now))

    def step(self, now):
        self.now = now
        self._apply(self.sim.step(now))
        self._flash_nodes()

    # -- the keyboard ---------------------------------------------------------------------------------------------

    def has_keys(self):
        """True when the graph has a KeySensor or a StringSensor (then the keyboard belongs to the player)."""
        return bool(self._keys)

    def key(self, kind, key, which, now):
        """A key goes down (``kind`` "keydown") or up ("keyup"), named as a browser names it. The simulator hands it to
        the one KeySensor or StringSensor that is enabled."""
        self.now = now
        event = {"key": key, "which": which, "charCode": 0, "keyCode": which}
        self._apply(self.sim.key(kind, event, now))

    def key_event(self, event, now):
        """Forward a Blender keyboard event. True when it was sent on (a key X3D has a name for); a release comes
        up as the key that went down, whatever the modifiers say by then."""
        if event.value == "PRESS":
            named = x3d_key(event)
            if named is None:
                return False
            self._down[event.type] = named
            self.key("keydown", *named, now)
            return True
        named = self._down.pop(event.type, None)
        if named is None:
            return False
        self.key("keyup", *named, now)
        return True

    def typed_lines(self):
        """The lines for the status bar and the viewport: one per StringSensor that has something."""
        return [f"{node_id}: {fields.get('enteredText', '')}" + (f"   (entered: {fields['finalText']})"
                if "finalText" in fields else "") for node_id, fields in self.typed().items() if fields]

    def typed(self):
        """What the StringSensors have in hand, for a place the scene has no object for (the status bar): a Text node
        cannot be reached by a ROUTE from a StringSensor (SFString into MFString) without a Script, which is not run."""
        shown = {}
        for node_id in self._keys:
            if self.graph.nodes[node_id].node_type == "StringSensor":
                shown[node_id] = {field: self.sim.outputs[(node_id, field)] for field in ("enteredText", "finalText")
                                  if (node_id, field) in self.sim.outputs}
        return shown

    def proximity_sensors(self):
        return [node_id for node_id, node in self.graph.nodes.items() if node.node_type == "ProximitySensor"]

    def view(self, eye, pivot, now):
        """The viewer for every ProximitySensor: ``eye`` is the camera's matrix in Blender world (looking down its -Z,
        as an X3D viewer does), ``pivot`` the point the view turns about (Blender's orbit centre)."""
        for sensor in self.proximity_sensors():
            local = self._frame(sensor).inverted() @ eye
            position, turn, _scale = local.decompose()
            axis, angle = turn.to_axis_angle()
            center = self._frame(sensor).inverted() @ Vector(pivot)
            self._apply(self.sim.viewer(sensor, tuple(position), (*axis, angle), now, center_of_rotation=tuple(center)))

    def hover(self, obj, now):
        """The pointer is over ``obj`` (None: over nothing a sensor senses)."""
        wanted = self.sensors_for(obj) if obj is not None else []
        for sensor in [s for s in self._over if s not in wanted]:
            self._apply(self.sim.hover(sensor, False, now))
        for sensor in [s for s in wanted if s not in self._over]:
            self._apply(self.sim.hover(sensor, True, now))
        self._over = wanted
        return bool(wanted)

    def _local_ray(self, sensor, origin, direction):
        inverse = self._frame(sensor).inverted()
        return tuple(inverse @ Vector(origin)), tuple((inverse.to_3x3() @ Vector(direction)).normalized())

    def press(self, obj, now, location=None, ray=None, eye=None):
        """The button goes down on ``obj`` at ``location`` (Blender world). True when a sensor took it. A
        CylinderSensor or SphereSensor also needs the pointer's ``ray`` (origin, direction) and the viewer's ``eye``
        (where it is, which way is back), in Blender world; the player turns them into the sensor's coordinates."""
        self.hover(obj, now)
        self._held = list(self._over)
        for sensor in self._held:
            point = self._frame(sensor).inverted() @ Vector(location) if location is not None else Vector((0, 0, 0))
            self._plane[sensor] = point.z
            extra = {}
            if ray is not None and eye is not None and \
                    self.graph.nodes[sensor].node_type in ("CylinderSensor", "SphereSensor"):
                inverse = self._frame(sensor).inverted()
                extra = {"ray": self._local_ray(sensor, *ray),
                         "eye": (tuple(inverse @ Vector(eye[0])),
                                 tuple((inverse.to_3x3() @ Vector(eye[1])).normalized()))}
            self._apply(self.sim.press(sensor, now, tuple(point), **extra))
        return bool(self._held)

    def drag(self, origin, direction, now):
        """The pointer moved with the button down; ``origin`` and ``direction`` are its ray in Blender world. A
        PlaneSensor follows the ray on the plane (its own XY, through the point it was pressed at); a CylinderSensor
        or SphereSensor turns by the ray (X_ITE's rules, judged against X_ITE)."""
        for sensor in self._held:
            kind = self.graph.nodes[sensor].node_type
            if kind in ("CylinderSensor", "SphereSensor"):
                self._apply(self.sim.drag(sensor, None, now, ray=self._local_ray(sensor, origin, direction)))
                continue
            if kind != "PlaneSensor":
                continue
            inverse = self._frame(sensor).inverted()
            start, way = inverse @ Vector(origin), inverse.to_3x3() @ Vector(direction)
            if abs(way.z) < 1e-9:
                continue
            point = start + way * ((self._plane[sensor] - start.z) / way.z)
            self._apply(self.sim.drag(sensor, tuple(point), now))

    def release(self, now):
        for sensor in self._held:
            self._apply(self.sim.release(sensor, now))
        self._held = []

    def click(self, obj, now, held=0.1):
        taken = self.press(obj, now)
        self.release(now + held)
        return taken

    # -- events onto datablocks -----------------------------------------------------------------------------------

    def _apply(self, changes):
        touched = {}
        for node_id, field_name, value in changes:
            node = self.graph.nodes[node_id]
            kind, name = node.binding or (None, None)
            if kind == "transform" or (kind in ("viewpoint", "light") and field_name == "visible"):
                obj = bpy.data.objects.get(name)
                if obj is None:
                    continue
                if field_name == "visible":
                    self._show(obj, bool(value))
                    continue
                state = self._transforms.get(name)
                if state is None:
                    state = self._transforms[name] = _TransformState(obj, self.global_matrix)
                if field_name == "translation":
                    state.location = Vector(value)
                elif field_name == "rotation":
                    axis = Vector(value[:3])
                    state.rotation = Quaternion(axis.normalized(), value[3]) if axis.length > 0 else Quaternion()
                elif field_name == "scale":
                    state.scale = Vector(value)
                else:
                    self._skip(node, field_name)
                    continue
                touched[name] = state
            elif kind == "material":
                self._paint(node, bpy.data.materials.get(name), field_name, value)
            elif kind == "light":
                self._light(node, bpy.data.objects.get(name), field_name, value)
            elif kind == "texture":
                self._texture(node, bpy.data.materials.get(name), field_name, value)
            elif kind == "viewpoint":
                obj = bpy.data.objects.get(name)
                if field_name == "set_bind" and value and obj is not None:
                    self.scene.camera = obj
                elif field_name in ("position", "orientation") and obj is not None:
                    # an imported camera's transform in the file's axes is the Viewpoint's position and orientation
                    state = self._transforms.get(name)
                    if state is None:
                        state = self._transforms[name] = _TransformState(obj, self.global_matrix)
                    if field_name == "position":
                        state.location = Vector(value)
                    else:
                        axis = Vector(value[:3])
                        state.rotation = Quaternion(axis.normalized(), value[3]) if axis.length > 0 else Quaternion()
                    touched[name] = state
                else:
                    self._skip(node, field_name)
            else:
                self._skip(node, field_name)
        for state in touched.values():
            state.write()

    def _skip(self, node, field_name):
        label = f"{node.node_type}.{field_name}"
        if label not in self.not_applied:
            self.not_applied.append(label)

    def _show(self, obj, visible):
        for item in [obj, *obj.children_recursive]:          # visible="false" hides everything under the Transform
            if item.name not in self._hidden:
                self._hidden[item.name] = (item.hide_viewport, item.hide_render, self._eye(item))
            item.hide_viewport = item.hide_render = not visible
            if visible:
                self._set_eye(item, False)

    @staticmethod
    def _eye(obj):
        try:
            return obj.hide_get()
        except RuntimeError:
            return None

    @staticmethod
    def _set_eye(obj, hidden):
        try:
            obj.hide_set(hidden)
        except RuntimeError:       # not in the view layer
            pass

    def _paint(self, node, material, field_name, value):
        if material is None:
            return
        shader = None
        if material.use_nodes and material.node_tree is not None:
            shader = next((n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if material.name not in self._materials:
            saved = {"diffuse_color": tuple(material.diffuse_color)}
            if shader is not None:
                for socket in ("Base Color", "Emission Color", "Alpha", "Roughness", "Metallic", "Emission Strength"):
                    if socket in shader.inputs:
                        entry = shader.inputs[socket].default_value
                        saved[socket] = tuple(entry) if hasattr(entry, "__len__") else entry
            self._materials[material.name] = saved
        display = node.node_type == "Material"               # Material colours are display colours, the others linear
        colour = lambda: tuple(_srgb_to_linear(c) if display else c for c in value[:3]) + (1.0,)   # noqa: E731
        socket, new = None, None
        if field_name in ("diffuseColor", "baseColor"):
            socket, new = "Base Color", colour()
            material.diffuse_color = new[:3] + (material.diffuse_color[3],)
        elif field_name == "emissiveColor":
            socket, new = "Emission Color", colour()
            if shader is not None and "Emission Strength" in shader.inputs and \
                    shader.inputs["Emission Strength"].default_value == 0 and any(value[:3]):
                shader.inputs["Emission Strength"].default_value = 1.0
        elif field_name == "transparency":
            socket, new = "Alpha", 1.0 - float(value)
            material.diffuse_color = tuple(material.diffuse_color[:3]) + (new,)
        elif field_name in ("roughness", "metallic"):
            socket, new = field_name.capitalize(), float(value)
        else:
            return self._skip(node, field_name)
        if shader is not None and socket in shader.inputs:
            shader.inputs[socket].default_value = new

    def _texture(self, node, material, field_name, value):
        """TextureTransform ``translation``, ``rotation`` and ``scale`` onto the Mapping node in front of the material's
        Image Texture nodes. The importer bakes the authored TextureTransform into the UVs and makes no Mapping node, so
        the first event makes one (Texture Coordinate UV -> Mapping -> each Image Texture's Vector) and ``stop`` takes it
        away again. The Mapping node holds only the change from the authored transform (new composed with the inverse
        of the initial one, recorded on the material at import), so a value equal to the authored one changes nothing."""
        if material is None or not material.use_nodes or material.node_tree is None:
            return
        if field_name not in ("translation", "rotation", "scale"):
            return self._skip(node, field_name)
        state = self._maps.get(material.name)
        if state is None:
            state = self._maps[material.name] = self._mapping_for(material)
        if state is None:
            return self._skip(node, field_name)
        state["now"][field_name] = float(value) if field_name == "rotation" else tuple(float(v) for v in value[:2])
        change = state["base"] @ _texture_matrix(state["now"], state["center"]) @ _texture_matrix(
            state["initial"], state["center"]).inverted()
        sx_axis, sy_axis = Vector((change[0][0], change[1][0])), Vector((change[0][1], change[1][1]))
        scale_x = sx_axis.length
        if scale_x < 1e-9 or abs(sx_axis.dot(sy_axis)) > 1e-4 * scale_x * max(sy_axis.length, 1e-9):
            return self._skip(node, f"{field_name} (the composed transform has shear or no size: a Mapping node cannot show it)")
        entries = {"Location": (change[0][2], change[1][2], 0.0),
                   "Rotation": (0.0, 0.0, math.atan2(sx_axis.y, sx_axis.x)),
                   "Scale": (scale_x, (sx_axis.x * sy_axis.y - sx_axis.y * sy_axis.x) / scale_x, 1.0)}
        for mapping in state["mappings"]:
            for socket, entry in entries.items():
                mapping.inputs[socket].default_value = entry

    @staticmethod
    def _mapping_for(material):
        """Mapping nodes in front of ``material``'s Image Textures (found, or made), and what ``stop`` must undo; None
        when the material has no Image Texture."""
        tree = material.node_tree
        images = [n for n in tree.nodes if n.type == "TEX_IMAGE"]
        if not images:
            return None
        initial = _initial_texture_transform(material)
        state = {"mappings": [], "made": [], "relink": [], "saved": [], "base": Matrix.Identity(3),
                 "initial": dict(initial), "now": dict(initial), "center": initial["center"]}
        coords = fresh = None
        for image in images:
            vector = image.inputs["Vector"]
            upstream = vector.links[0].from_node if vector.links else None
            if upstream is not None and upstream.type == "MAPPING":
                mapping = upstream
                if mapping not in state["mappings"]:
                    saved = {name: tuple(mapping.inputs[name].default_value) for name in ("Location", "Rotation", "Scale")}
                    state["saved"].append((mapping, saved))
                    state["mappings"].append(mapping)
                    state["base"] = _mapping_matrix(saved)                  # what the Mapping node already did stays
                continue
            origin = had = vector.links[0].from_socket if vector.links else None
            if origin is None and fresh is not None:          # unlinked images share the one Mapping node made for them
                tree.links.new(fresh.outputs["Vector"], vector)
                state["relink"].append((vector, None))
                continue
            if origin is None:
                if coords is None:
                    coords = tree.nodes.new("ShaderNodeTexCoord")
                    coords.location = (image.location.x - 560, image.location.y)
                    state["made"].append(coords)
                origin = coords.outputs["UV"]
            mapping = tree.nodes.new("ShaderNodeMapping")
            mapping.vector_type = "POINT"
            mapping.location = (image.location.x - 280, image.location.y)
            state["made"].append(mapping)
            state["mappings"].append(mapping)
            tree.links.new(origin, mapping.inputs["Vector"])
            tree.links.new(mapping.outputs["Vector"], vector)
            state["relink"].append((vector, had))
            if had is None:
                fresh = mapping
        return state

    def _undo_textures(self):
        for name, state in self._maps.items():
            material = bpy.data.materials.get(name)
            if material is None or state is None or material.node_tree is None:
                continue
            tree = material.node_tree
            for mapping, saved in state["saved"]:
                for socket, entry in saved.items():
                    mapping.inputs[socket].default_value = entry
            for vector, origin in state["relink"]:
                if origin is not None:
                    tree.links.new(origin, vector)
            for made in state["made"]:
                if tree.nodes.get(made.name) is not None:
                    tree.nodes.remove(made)

    def _light(self, node, obj, field_name, value):
        if obj is None or obj.type != "LIGHT":
            return
        if obj.name not in self._lights:
            self._lights[obj.name] = (tuple(obj.data.color), obj.hide_viewport, obj.hide_render)
        if field_name == "color":
            obj.data.color = tuple(value[:3])
        elif field_name == "on":
            obj.hide_viewport = obj.hide_render = not value
        else:
            self._skip(node, field_name)

    # -- the node editor lights up --------------------------------------------------------------------------------

    def _tree_nodes(self):
        tree = getattr(self.scene, "x3d_behaviour_tree", None)
        return {} if tree is None else {(item.x3d_def or item.name): item for item in tree.nodes
                                        if getattr(item, "x3d_role", None) is not None}

    def _flash_nodes(self, glow=0.35):
        """Tint the nodes that just sent events. A single event flashes (FLASH) and fades over ``glow`` seconds; a
        node that keeps sending, like a running timer, settles at BUSY after ``glow`` so its fields stay readable."""
        if not self._flash:
            return
        recent = {}
        for when, node_id, _field, _value in reversed(self.sim.log):
            if self.now - when > glow:
                break
            recent.setdefault(node_id, when)
        for node_id, item in self._flash.items():
            if node_id not in recent and node_id not in self._colours:
                continue
            if node_id not in self._colours:
                self._colours[node_id] = (item.use_custom_color, tuple(item.color))
            base = self._colours[node_id][1] if self._colours[node_id][0] else (0.19, 0.19, 0.19)
            if node_id in recent:
                began = self._burst.setdefault(node_id, recent[node_id])
                peak = GLOW_FLASH if self.now - began <= glow else GLOW_BUSY
                heat = peak * max(0.0, 1 - (self.now - recent[node_id]) / glow)
            else:
                heat = 0.0
            item.use_custom_color = True
            item.color = tuple(b + (h - b) * heat for b, h in zip(base, GLOW_COLOUR))
            if heat == 0.0:
                self._burst.pop(node_id, None)
                item.use_custom_color, item.color = self._colours.pop(node_id)

    # -- the end --------------------------------------------------------------------------------------------------

    def stop(self):
        """Put every object, material, light and node colour back as it was before ``start``."""
        for state in self._transforms.values():
            state.restore()
        for name, (viewport, render, eye) in self._hidden.items():
            obj = bpy.data.objects.get(name)
            if obj is not None:
                obj.hide_viewport, obj.hide_render = viewport, render
                if eye is not None:
                    self._set_eye(obj, eye)
        for name, saved in self._materials.items():
            material = bpy.data.materials.get(name)
            if material is None:
                continue
            material.diffuse_color = saved["diffuse_color"]
            shader = next((n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) \
                if material.use_nodes and material.node_tree else None
            for socket, entry in saved.items():
                if shader is not None and socket in shader.inputs:
                    shader.inputs[socket].default_value = entry
        for name, (colour, viewport, render) in self._lights.items():
            obj = bpy.data.objects.get(name)
            if obj is not None:
                obj.data.color, obj.hide_viewport, obj.hide_render = colour, viewport, render
        self._undo_textures()
        for node_id, (custom, colour) in self._colours.items():
            item = self._flash.get(node_id)
            if item is not None:
                item.use_custom_color, item.color = custom, colour
        self.scene.camera = self._camera
        self._transforms, self._hidden, self._materials, self._lights, self._colours = {}, {}, {}, {}, {}
        self._maps = {}
        self._burst, self._down = {}, {}


# ---------------------------------------------------------------------------------------------------------------
# The operator: a timer and the mouse
# ---------------------------------------------------------------------------------------------------------------

_running = {"player": None}


def is_playing():
    return _running["player"] is not None


def _viewer(context):
    """(camera matrix, orbit centre) in Blender world for the first 3D viewport: the scene camera when the view looks
    through it (so a Viewpoint that a ROUTE flies carries the viewer with it), else the viewport's own eye."""
    area = next((a for a in context.window.screen.areas if a.type == "VIEW_3D"), None)
    if area is None:
        return None
    region_3d = area.spaces.active.region_3d
    camera = context.scene.camera
    if region_3d.view_perspective == "CAMERA" and camera is not None:
        eye = camera.matrix_world.copy()
    else:
        eye = region_3d.view_matrix.inverted()
    return eye, tuple(region_3d.view_location)


def _eye(context, event):
    """Where the viewer is and which way is back (Blender world) for the 3D viewport under the pointer."""
    found = _view_under(context, event)
    if found is None:
        return None
    view = found[1].view_matrix.inverted()
    return tuple(view.translation), tuple((view.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized())


def _view_under(context, event):
    """(region, region_3d, (x, y) in the region) of the 3D viewport the pointer is over, or None."""
    for area in context.window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        for region in area.regions:
            if region.type == "WINDOW" and region.x <= event.mouse_x < region.x + region.width \
                    and region.y <= event.mouse_y < region.y + region.height:
                return region, area.spaces.active.region_3d, (event.mouse_x - region.x, event.mouse_y - region.y)
    return None


def _draw_typed(player):
    """Over the 3D viewport: what the StringSensors hold. A Text node cannot be fed by a StringSensor without a Script
    (SFString into MFString) and Scripts are not run, so the player shows the line here instead of on the Text object."""
    import blf
    lines = player.typed_lines()
    if not lines:
        return
    blf.size(0, 20.0)
    blf.color(0, 1.0, 0.85, 0.4, 1.0)
    for row, line in enumerate(reversed(lines)):
        blf.position(0, 24.0, 40.0 + 28.0 * row, 0)
        blf.draw(0, line)


class X3D_OT_behaviour_play(bpy.types.Operator):
    """Run the X3D Behaviour graph in the viewport: click what a sensor senses and watch the events travel. Esc stops and puts the scene back"""
    bl_idname = "x3d.behaviour_play"
    bl_label = "Play X3D Behaviour"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return not is_playing() and getattr(context.scene, "x3d_behaviour_tree", None) is not None

    def invoke(self, context, event):
        try:
            self.player = Player(context.scene)
        except bg.BehaviourError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.began, self.dragging = time.perf_counter(), False
        self.player.start(0.0)
        _running["player"] = self.player
        self.overlay = bpy.types.SpaceView3D.draw_handler_add(_draw_typed, (self.player,), "WINDOW", "POST_PIXEL") \
            if self.player.has_keys() else None
        self.timer = context.window_manager.event_timer_add(1 / 60, window=context.window)
        context.window_manager.modal_handler_add(self)
        sensed = len(self.player.sensed_objects())
        context.workspace.status_text_set(
            f"X3D Behaviour is playing: {sensed} object(s) answer the pointer. Click or drag them. Esc stops.")
        for label in self.player.sim.not_simulated:
            self.report({"WARNING"}, f"Not played: {label}")
        return {"RUNNING_MODAL"}

    def _ray(self, context, event):
        from bpy_extras import view3d_utils
        found = _view_under(context, event)
        if found is None:
            return None
        region, region_3d, where = found
        origin = view3d_utils.region_2d_to_origin_3d(region, region_3d, where)
        direction = view3d_utils.region_2d_to_vector_3d(region, region_3d, where)
        hit, location, _normal, _index, obj, _matrix = context.scene.ray_cast(
            context.evaluated_depsgraph_get(), origin, direction)
        return origin, direction, (obj.original if hit and obj is not None else None), (location if hit else None)

    def modal(self, context, event):
        now = time.perf_counter() - self.began
        if event.type == "ESC" or _running["player"] is not self.player:
            return self._finish(context)
        if self.player.has_keys() and is_keyboard(event):
            self.player.key_event(event, now)          # the keyboard is the world's while it plays (Esc stops, above)
            self._show_typed(context)
            return {"RUNNING_MODAL"}
        if event.type == "TIMER":
            if self.player.proximity_sensors():
                viewer = _viewer(context)
                if viewer is not None:
                    self.player.view(*viewer, now)
            self.player.step(now)
            for area in context.window.screen.areas:
                if area.type in ("VIEW_3D", "NODE_EDITOR"):
                    area.tag_redraw()
            return {"PASS_THROUGH"}
        if event.type in ("MOUSEMOVE", "LEFTMOUSE"):
            ray = self._ray(context, event)
            if ray is None:
                if self.dragging and event.type == "LEFTMOUSE" and event.value == "RELEASE":
                    self.player.release(now)
                    self.dragging = False
                return {"PASS_THROUGH"}
            origin, direction, obj, location = ray
            if event.type == "MOUSEMOVE":
                if self.dragging:
                    self.player.drag(origin, direction, now)
                    return {"RUNNING_MODAL"}
                over = self.player.hover(obj, now)
                context.window.cursor_set("HAND" if over else "DEFAULT")
            elif event.value == "PRESS":
                if obj is not None and self.player.press(obj, now, location, ray=(origin, direction),
                                                          eye=_eye(context, event)):
                    self.dragging = True
                    return {"RUNNING_MODAL"}           # the click was for a sensor, not for selecting
            elif event.value == "RELEASE" and self.dragging:
                self.player.release(now)
                self.dragging = False
                return {"RUNNING_MODAL"}
        return {"PASS_THROUGH"}

    def _show_typed(self, context):
        """The line a StringSensor holds goes on the status bar (and over the viewport, see ``_draw_typed``)."""
        lines = self.player.typed_lines()
        if lines:
            context.workspace.status_text_set("X3D Behaviour is playing. Typing: " + "; ".join(lines) + ". Esc stops.")

    def _finish(self, context):
        if getattr(self, "overlay", None) is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self.overlay, "WINDOW")
            self.overlay = None
        context.window_manager.event_timer_remove(self.timer)
        self.player.stop()
        if _running["player"] is self.player:
            _running["player"] = None
        context.workspace.status_text_set(None)
        context.window.cursor_set("DEFAULT")
        for area in context.window.screen.areas:
            area.tag_redraw()
        return {"FINISHED"}


class X3D_OT_behaviour_stop(bpy.types.Operator):
    """Stop playing and put the scene back as it was"""
    bl_idname = "x3d.behaviour_stop"
    bl_label = "Stop"

    @classmethod
    def poll(cls, context):
        return is_playing()

    def execute(self, context):
        _running["player"] = None          # the running operator sees this on its next event and restores the scene
        return {"FINISHED"}


def _draw_buttons(layout, context):
    if is_playing():
        layout.operator(X3D_OT_behaviour_stop.bl_idname, icon="PAUSE")
    else:
        layout.operator(X3D_OT_behaviour_play.bl_idname, text="Play", icon="PLAY")


def _node_header(self, context):
    if getattr(context.space_data, "tree_type", "") == behaviour_nodes.TREE_IDNAME:
        _draw_buttons(self.layout, context)
        tree = getattr(context.space_data, "edit_tree", None)
        if tree is not None and hasattr(tree, "x3d_blender_axes"):
            self.layout.prop(tree, "x3d_blender_axes", toggle=True)


class X3D_PT_behaviour_play(bpy.types.Panel):
    bl_label = "X3D Behaviour"
    bl_idname = "X3D_PT_behaviour_play"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "X3D"

    def draw(self, context):
        layout = self.layout
        tree = getattr(context.scene, "x3d_behaviour_tree", None)
        if tree is None:
            layout.label(text="This scene has no behaviour graph yet.")
            return
        layout.prop(context.scene, "x3d_behaviour_tree", text="")
        _draw_buttons(layout, context)
        player = _running["player"]
        if player is not None:
            layout.label(text=f"{len(player.sensed_objects())} object(s) answer the pointer")
            for label in player.sim.not_simulated:
                layout.label(text=f"Not played: {label}", icon="ERROR")
            for label in player.not_applied:
                layout.label(text=f"Not shown: {label}", icon="INFO")
        else:
            layout.label(text="Click what a sensor senses. Esc stops.")


classes = (X3D_OT_behaviour_play, X3D_OT_behaviour_stop, X3D_PT_behaviour_play)


def register():
    for cls in classes:
        if not getattr(cls, "is_registered", False):
            bpy.utils.register_class(cls)
    bpy.types.NODE_HT_header.append(_node_header)


def unregister():
    if _running["player"] is not None:
        _running["player"].stop()
        _running["player"] = None
    bpy.types.NODE_HT_header.remove(_node_header)
    for cls in reversed(classes):
        if getattr(cls, "is_registered", False):
            bpy.utils.unregister_class(cls)
