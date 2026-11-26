# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The X3D behaviour graph as a Blender node tree (proof of concept).

``behaviour_graph.py`` is the graph; this module shows it in Blender's node editor and keeps the two in step:

* ``apply(graph, scene)``   graph -> node tree, stored on ``scene.x3d_behaviour_tree``
* ``read(scene)``           node tree -> graph (what the exporter writes)
* ``target(graph, datablock)``  add a Blender object, camera, light or material to a graph as a ROUTE end

One node class per catalogue node, one socket class per X3D field type. A socket's colour is its field type, and a link
between two types is removed as it is made: the editor cannot hold a ROUTE X3D would reject.
"""

import json
import bpy
from bpy.props import (BoolProperty, CollectionProperty, FloatProperty, FloatVectorProperty, IntProperty,
                       PointerProperty, StringProperty)
from bpy.types import Node, NodeSocket, NodeTree, Operator, PropertyGroup

from . import behaviour_graph as bg
from .behaviour_catalogue import NODES, TARGETS
from .behaviour_sim import parse_value

TREE_IDNAME = "X3DBehaviourTree"
_BUILDING = set()         # names of the trees ``apply`` is filling: their update callback waits until it has finished
_SOCKETS_LATER = []       # while ``apply`` is filling a tree, a new node gets its sockets in a second pass (see _fill)
ANY = "X3DSocketAny"

# One colour per field type; families share a hue (time amber, booleans red, numbers grey, vectors blue ...).
_COLOURS = {
    "SFBool": (0.90, 0.30, 0.30, 1), "MFBool": (0.70, 0.25, 0.25, 1),
    "SFTime": (0.95, 0.70, 0.20, 1),
    "SFFloat": (0.63, 0.63, 0.63, 1), "MFFloat": (0.45, 0.45, 0.45, 1),
    "SFInt32": (0.35, 0.75, 0.45, 1), "MFInt32": (0.25, 0.55, 0.33, 1),
    "SFVec2f": (0.35, 0.70, 0.90, 1), "MFVec2f": (0.25, 0.52, 0.68, 1),
    "SFVec3f": (0.39, 0.39, 0.90, 1), "MFVec3f": (0.28, 0.28, 0.68, 1),
    "SFRotation": (0.75, 0.40, 0.90, 1), "MFRotation": (0.56, 0.30, 0.68, 1),
    "SFColor": (0.90, 0.85, 0.25, 1), "MFColor": (0.68, 0.64, 0.19, 1),
    "SFColorRGBA": (0.90, 0.60, 0.25, 1), "MFColorRGBA": (0.68, 0.45, 0.19, 1),
    "SFString": (0.30, 0.80, 0.80, 1), "MFString": (0.22, 0.60, 0.60, 1),
    "SFNode": (0.80, 0.80, 0.80, 1), "MFNode": (0.60, 0.60, 0.60, 1),
}


def socket_idname(x3d_type):
    return f"X3DSocket{x3d_type}" if x3d_type in _COLOURS else ANY


def _socket_class(x3d_type, colour):
    def draw(self, context, layout, node, text):
        layout.label(text=text)

    return type(socket_idname(x3d_type) if x3d_type else ANY, (NodeSocket,), {
        "bl_idname": socket_idname(x3d_type) if x3d_type else ANY,
        "bl_label": x3d_type or "Any X3D field",
        "x3d_type": x3d_type,
        "draw": draw,
        "draw_color_simple": classmethod(lambda cls: colour),
    })


# Every other field type a ROUTE may join gets a socket of its own too (a double, a matrix, an image), so that the editor
# refuses a ROUTE between two types as it does for the ones above: the colour is a shade of its family's, made from the type.
for _type in sorted(bg.FIELD_TYPES | bg.NODE_FIELD_TYPES):
    if _type not in _COLOURS:
        _near = _COLOURS.get(_type[:2] + {"Double": "Float", "Vec2d": "Vec2f", "Vec3d": "Vec3f", "Vec4d": "Vec3f",
                                          "Vec4f": "Vec3f"}.get(_type[2:], "Float"), (0.6, 0.6, 0.6, 1))
        _shade = 0.82 + 0.03 * (sum(map(ord, _type)) % 5)
        _COLOURS[_type] = (_near[0] * _shade, _near[1] * _shade, _near[2] * _shade, 1)

SOCKET_CLASSES = tuple(_socket_class(name, colour) for name, colour in _COLOURS.items()) + (
    _socket_class("", (0.2, 0.2, 0.2, 1)),)


# ---------------------------------------------------------------------------------------------------------------
# Field values. What is stored is always the X3D text of the file (``x3d_fields``); the typed widgets below read and
# write that text, so the file's numbers never pass through a second copy.
# ---------------------------------------------------------------------------------------------------------------

def _row_of(node, name):
    return next((row for row in NODES[node.x3d_type][1] if row[0] == name), None)


def field_text(node, name):
    """The X3D text of a field: what was set, else the standard's default, else ''."""
    item = node.x3d_fields.get(name)
    if item is not None and item.value != "":
        return item.value
    row = _row_of(node, name)
    return (row[3] if row is not None else None) or ""


def _store(node, name, value):
    """Set a field from a Python value. A value equal to the standard's default is not stored (not written)."""
    row = _row_of(node, name)
    text = bg.to_lexical(value, row[1], single=True)       # a value set from a widget is a 32-bit Blender float
    index = node.x3d_fields.find(name)
    if row[3] is not None and parse_value(text, row[1]) == parse_value(row[3], row[1]):
        if index >= 0:
            node.x3d_fields.remove(index)
        return
    item = node.x3d_fields[index] if index >= 0 else node.x3d_fields.add()
    item.name, item.value = name, text


# Which values are places and turns in the scene's axes: the key values of the interpolators that move things, and
# where a follower starts. Only these are shown turned when the tree's "Z up" switch is on.
_SPATIAL = {("PositionInterpolator", "keyValue"), ("OrientationInterpolator", "keyValue"),
            ("PositionDamper", "initialValue"), ("PositionDamper", "initialDestination"),
            ("PositionChaser", "initialValue"), ("PositionChaser", "initialDestination"),
            ("OrientationDamper", "initialValue"), ("OrientationDamper", "initialDestination"),
            ("OrientationChaser", "initialValue"), ("OrientationChaser", "initialDestination")}


def drives_root_objects(node):
    """True when every Transform this node's values reach (through any chain of nodes) belongs to an object with no
    parent. Those values are in the file's world axes (Y up); values for a child object are in its parent's axes, which
    are Blender's already."""
    seen, queue, found = {node.name}, [node], []
    while queue:
        current = queue.pop()
        for socket in current.outputs:
            for link in socket.links:
                other = link.to_node
                if other.name in seen:
                    continue
                seen.add(other.name)
                if getattr(other, "x3d_role", None) == bg.TARGET:
                    if other.x3d_type == "Transform" and other.x3d_object is not None:
                        found.append(other.x3d_object.parent is None)
                else:
                    queue.append(other)
    return bool(found) and all(found)


def shows_blender_axes(node, name):
    return bool(getattr(node.id_data, "x3d_blender_axes", False)) and (node.x3d_type, name) in _SPATIAL \
        and drives_root_objects(node)


def _to_blender(v):       # the export's default axes: X3D (x, y, z), Y up  ->  Blender (x, -z, y), Z up
    return (v[0], -v[2] or 0.0, v[1]) + tuple(v[3:])


def _to_x3d(v):
    return (v[0], v[2], -v[1] or 0.0) + tuple(v[3:])


def _accessors(name, x3d_type):
    """(get, set) for one field. Blender counts a callback's arguments, so each is made here with exactly its own."""
    def read(self):
        value = parse_value(field_text(self, name), x3d_type)
        if isinstance(value, tuple) and shows_blender_axes(self, name):
            value = _to_blender(value)
        return value

    def write(self, value):
        if not isinstance(value, (bool, int, float, str)):
            value = tuple(value)
            if shows_blender_axes(self, name):
                value = _to_x3d(value)
        _store(self, name, value)

    return read, write


def _rotation_accessors(read, write):
    def axis(self):
        return read(self)[:3]

    def set_axis(self, value):
        write(self, tuple(value) + (read(self)[3],))

    def angle(self):
        return read(self)[3]

    def set_angle(self, value):
        write(self, tuple(read(self)[:3]) + (value,))

    return axis, set_axis, angle, set_angle


def _typed_properties(x3d_type_name):
    """bpy properties for the single-value fields of one node type, each reading and writing the field's X3D text."""
    made = {}
    for name, x3d_type, access, _default in NODES[x3d_type_name][1]:
        if access not in ("inputOutput", "initializeOnly") or x3d_type.startswith("MF") or x3d_type == "SFNode":
            continue

        read, write = _accessors(name, x3d_type)
        hint = f"{x3d_type_name}.{name} ({x3d_type}, {access})"
        if x3d_type == "SFBool":
            made[f"f_{name}"] = BoolProperty(name=name, description=hint, get=read, set=write)
        elif x3d_type == "SFInt32":
            made[f"f_{name}"] = IntProperty(name=name, description=hint, get=read, set=write)
        elif x3d_type in ("SFFloat", "SFDouble"):
            made[f"f_{name}"] = FloatProperty(name=name, description=hint, get=read, set=write, precision=3)
        elif x3d_type == "SFTime":
            made[f"f_{name}"] = FloatProperty(name=name, description=hint + ", seconds", get=read, set=write,
                                              precision=3, unit="TIME_ABSOLUTE")
        elif x3d_type == "SFString":
            made[f"f_{name}"] = StringProperty(name=name, description=hint, get=read, set=write)
        elif x3d_type in ("SFColor", "SFColorRGBA"):
            made[f"f_{name}"] = FloatVectorProperty(name=name, description=hint, get=read, set=write, subtype="COLOR",
                                                    size=4 if x3d_type == "SFColorRGBA" else 3, min=0.0, max=1.0)
        elif x3d_type in ("SFVec2f", "SFVec3f", "SFVec2d", "SFVec3d"):
            made[f"f_{name}"] = FloatVectorProperty(name=name, description=hint, get=read, set=write, precision=3,
                                                    size=int(x3d_type[5]), subtype="XYZ" if x3d_type[5] == "3" else "NONE")
        elif x3d_type == "SFRotation":
            axis, set_axis, angle, set_angle = _rotation_accessors(read, write)
            made[f"f_{name}_axis"] = FloatVectorProperty(name=f"{name} axis", description=hint + ": the axis", size=3,
                                                         precision=3, get=axis, set=set_axis)
            made[f"f_{name}_angle"] = FloatProperty(name=f"{name} angle", description=hint + ": the angle",
                                                    subtype="ANGLE", precision=2, get=angle, set=set_angle)
    return made


# One row of an interpolator's or a sequencer's table: a key (when, 0 to 1) and the value there.
KEY_KINDS = {"ScalarInterpolator": "number", "PositionInterpolator": "vector", "PositionInterpolator2D": "vector2",
             "ColorInterpolator": "colour", "OrientationInterpolator": "rotation", "BooleanSequencer": "flag",
             "IntegerSequencer": "whole"}
_ROW_ZERO = {"number": 0.0, "vector": (0.0, 0.0, 0.0), "vector2": (0.0, 0.0), "colour": (0.0, 0.0, 0.0),
             "rotation": (0.0, 0.0, 1.0, 0.0), "flag": False, "whole": 0}


def _owner(item, collection="x3d_rows"):
    """(node, index) of a key row or a field value. A row remembers where it is; the memory is checked, and the tree is
    searched when it is stale (a node was renamed, a row was removed above this one)."""
    tree, pointer = item.id_data, item.as_pointer()
    node = tree.nodes.get(item.get("node", ""))
    index = item.get("index", -1)
    if node is not None and hasattr(node, collection):
        items = getattr(node, collection)
        if 0 <= index < len(items) and items[index].as_pointer() == pointer:
            return node, index
    for node in tree.nodes:
        for index, other in enumerate(getattr(node, collection, ())):
            if other.as_pointer() == pointer:
                return node, index
    return None, -1


def key_table(node):
    """(keys, values) of a node with a key table, padded so both have one entry per row."""
    kind = KEY_KINDS[node.x3d_type]
    keys = parse_value(field_text(node, "key"), "MFFloat")
    values = parse_value(field_text(node, "keyValue"), _row_of(node, "keyValue")[1])
    count = max(len(keys), len(values))
    keys += [keys[-1] if keys else 0.0] * (count - len(keys))
    values += [_ROW_ZERO[kind]] * (count - len(values))
    return keys, values


def store_key_table(node, keys, values):
    _store(node, "key", list(keys))
    _store(node, "keyValue", list(values))
    sync_rows(node)


def sync_rows(node):
    """Make the node's row list as long as its key list (rows hold no values, only their place in the table)."""
    if node.x3d_type not in KEY_KINDS:
        return
    wanted = len(key_table(node)[0])
    while len(node.x3d_rows) < wanted:
        node.x3d_rows.add()
    while len(node.x3d_rows) > wanted:
        node.x3d_rows.remove(len(node.x3d_rows) - 1)
    for index, row in enumerate(node.x3d_rows):
        if row.get("node") != node.name or row.get("index") != index:
            row["node"], row["index"] = node.name, index


def _row_value(row, part=None):
    node, index = _owner(row)
    if node is None:
        return 0.0
    keys, values = key_table(node)
    if not 0 <= index < len(keys):
        return 0.0 if part == "key" else _ROW_ZERO[KEY_KINDS[node.x3d_type]]
    if part == "key":
        return keys[index]
    value = values[index]
    if isinstance(value, tuple) and shows_blender_axes(node, "keyValue"):
        value = _to_blender(value)
    return value


def _set_row_value(row, new, part=None):
    node, index = _owner(row)
    if node is None:
        return
    keys, values = key_table(node)
    if not 0 <= index < len(keys):
        return
    if part == "key":
        keys[index] = new
    else:
        if not isinstance(new, (bool, int, float)):
            new = tuple(new)
            if shows_blender_axes(node, "keyValue"):
                new = _to_x3d(new)
        values[index] = new
    _store(node, "key", keys)
    _store(node, "keyValue", values)


def _row_key(row):
    return _row_value(row, "key")


def _set_row_key(row, value):
    _set_row_value(row, value, "key")


def _row_any(row):
    return _row_value(row)


def _set_row_any(row, value):
    _set_row_value(row, value)


def _row_axis(row):
    return _row_value(row)[:3]


def _set_row_axis(row, value):
    _set_row_value(row, tuple(value) + (_row_value(row)[3],))


def _row_angle(row):
    return _row_value(row)[3]


def _set_row_angle(row, value):
    _set_row_value(row, tuple(_row_value(row)[:3]) + (value,))


class X3DKeyRow(PropertyGroup):
    """One row of a key table. The numbers live in the node's key and keyValue text; a row is a window onto them."""
    key: FloatProperty(name="Key", description="When: 0 is the start of the cycle, 1 the end", precision=3,
                       get=_row_key, set=_set_row_key)
    number: FloatProperty(name="Value", precision=3, get=_row_any, set=_set_row_any)
    whole: IntProperty(name="Value", get=_row_any, set=_set_row_any)
    flag: BoolProperty(name="Value", get=_row_any, set=_set_row_any)
    vector: FloatVectorProperty(name="Place", size=3, precision=3, subtype="XYZ", get=_row_any, set=_set_row_any)
    vector2: FloatVectorProperty(name="Place", size=2, precision=3, get=_row_any, set=_set_row_any)
    colour: FloatVectorProperty(name="Colour", size=3, subtype="COLOR", min=0.0, max=1.0,
                                get=_row_any, set=_set_row_any)
    axis: FloatVectorProperty(name="Axis", size=3, precision=3, get=_row_axis, set=_set_row_axis)
    angle: FloatProperty(name="Angle", subtype="ANGLE", precision=2, get=_row_angle, set=_set_row_angle)


def _text_changed(item, context):
    if item.name not in ("key", "keyValue"):
        return
    node, _index = _owner(item, "x3d_fields")
    if item.name in ("key", "keyValue") and getattr(node, "x3d_type", None) in KEY_KINDS:
        sync_rows(node)


class X3DFieldValue(PropertyGroup):
    """One field that has a value: the X3D field name and its lexical text, exactly as it is written to the file."""
    value: StringProperty(name="Value", description="The field's value as X3D text, in the file's own axes (Y up)",
                          update=_text_changed)


class X3DBehaviourTree(NodeTree):
    """ROUTEs between X3D sensors, timers, interpolators and the scene"""
    bl_idname = TREE_IDNAME
    bl_label = "X3D Behaviour"
    bl_icon = "DRIVER"
    x3d_blender_axes: BoolProperty(
        name="Z up", default=False,
        description="Show the places and turns of nodes that move parentless objects in Blender's axes (Z up) instead "
                    "of the file's (Y up). Only the display changes; the stored X3D text does not")

    def update(self):
        # X3D: a ROUTE joins fields of one type. Remove a link that does not. (``apply`` makes every link itself and
        # checks them once at the end: this walk over all links would run once per link made.)
        if self.name in _BUILDING:
            return
        self.remove_mismatched_links()

    def remove_mismatched_links(self):
        bad = [link for link in self.links
               if (getattr(link.from_socket, "x3d_type", None) and getattr(link.to_socket, "x3d_type", None)
                   and link.from_socket.x3d_type != link.to_socket.x3d_type)]
        _BUILDING.add(self.name)          # removing a link calls update again: not for the links still on the list
        try:
            for link in bad:
                self.links.remove(link)
        finally:
            _BUILDING.discard(self.name)


class _X3DNodeBase:
    x3d_def: StringProperty(name="DEF", description="The node's name in the X3D file")
    x3d_content: StringProperty(name="Content", description="What is inside the node's element (a Script's fields and source, "
                                "a pick sensor's references), as X3D markup; written back unchanged")
    x3d_declared: StringProperty(name="Declared fields")   # a Script's <field>s, one "name type access" per line
    x3d_fields: CollectionProperty(type=X3DFieldValue)
    x3d_rows: CollectionProperty(type=X3DKeyRow)
    x3d_as_text: BoolProperty(name="As X3D text", default=False,
                              description="Show every value as the text that is written to the file")

    @classmethod
    def poll(cls, tree):
        return tree.bl_idname == TREE_IDNAME

    def _make_sockets(self, rows):
        for name, x3d_type, access, _default in rows:
            if access in ("inputOnly", "inputOutput"):
                self.inputs.new(socket_idname(x3d_type), name).link_limit = 4095   # X3D allows fan-in
            if access in ("outputOnly", "inputOutput"):
                self.outputs.new(socket_idname(x3d_type), name)

    def draw_label(self):
        return f"{self.x3d_type}  {self.x3d_def}" if self.x3d_def else self.x3d_type


class _BehaviourNode(_X3DNodeBase):
    x3d_role = bg.BEHAVIOUR
    x3d_parent: PointerProperty(type=bpy.types.Object, name="Sits in",
                                description="The object this sensor sits in: it senses that object's shapes")

    def init(self, context):
        if not _SOCKETS_LATER:
            self._make_sockets(NODES[self.x3d_type][1])
        self.width = 240

    def _draw_content(self, layout):
        if self.x3d_content:
            layout.label(text=f"{len(self.x3d_content)} characters inside, written back unchanged", icon="LOCKED")

    def draw_buttons(self, context, layout):
        layout.prop(self, "x3d_def")
        if self.x3d_type in bg.PLACED_TYPES:
            layout.prop(self, "x3d_parent")
        self._draw_content(layout)
        if self.x3d_as_text:
            for item in self.x3d_fields:
                layout.prop(item, "value", text=item.name)
            return
        shown = [name for name in MAIN_FIELDS.get(self.x3d_type, ())]
        shown += [item.name for item in self.x3d_fields if item.name not in shown]
        table = self.x3d_type in KEY_KINDS
        for name in shown:
            if not (table and name in ("key", "keyValue")):
                self._draw_field(layout, name)
        if table:
            self._draw_table(layout, NODE_TABLE_ROWS)

    def draw_buttons_ext(self, context, layout):
        """The sidebar: every field that can hold a value, not only the ones the node shows."""
        layout.prop(self, "x3d_def")
        if self.x3d_type in bg.PLACED_TYPES:
            layout.prop(self, "x3d_parent")
        layout.prop(self, "x3d_as_text")
        self._draw_content(layout)
        table = self.x3d_type in KEY_KINDS
        for name, _type, access, _default in NODES[self.x3d_type][1]:
            if access in ("inputOutput", "initializeOnly") and not (table and name in ("key", "keyValue")) \
                    and _type not in bg.NODE_FIELD_TYPES:           # a node-valued field is content, not a value
                self._draw_field(layout, name)
        if table:
            self._draw_table(layout)

    def _draw_field(self, layout, name):
        row = _row_of(self, name)
        if row is None:
            return
        if hasattr(self, f"f_{name}"):
            if row[1] in ("SFVec2f", "SFVec3f", "SFVec2d", "SFVec3d"):
                column = layout.column(align=True)
                column.label(text=name + ("  (Z up)" if shows_blender_axes(self, name) else ""))
                column.row(align=True).prop(self, f"f_{name}", text="")
            elif row[1] == "SFTime" and abs(getattr(self, f"f_{name}")) >= NEVER_SECONDS \
                    and self.x3d_fields.get(name) is not None:
                # 1e+30 is how a file says "not until an event says so"; as seconds it is thirty digits, cut off
                layout.prop(self.x3d_fields.get(name), "value", text=f"{name} (never)")
            else:
                layout.prop(self, f"f_{name}", text=name)
        elif hasattr(self, f"f_{name}_axis"):
            column = layout.column(align=True)
            column.label(text=name + ("  (Z up)" if shows_blender_axes(self, name) else ""))
            line = column.row(align=True)
            line.prop(self, f"f_{name}_axis", text="")
            line.prop(self, f"f_{name}_angle", text="")
        else:                                  # a list (MF) field without a table: its X3D text
            item = self.x3d_fields.get(name)
            if item is not None:
                layout.prop(item, "value", text=name)
            else:
                layout.label(text=f"{name}: not set")

    def _draw_table(self, layout, limit=None):
        """The key table; ``limit`` rows at most (the node body), every row when None (the sidebar)."""
        kind = KEY_KINDS[self.x3d_type]
        box = layout.column(align=True)
        box.label(text="key  /  value" + ("  (Z up)" if shows_blender_axes(self, "keyValue") else ""))
        shown = rows_on_node(len(self.x3d_rows), limit)
        for index, row in enumerate(self.x3d_rows):
            if index not in shown:
                if index == shown[-2] + 1:                       # one line where the hidden rows are
                    box.label(text=f"… {len(self.x3d_rows) - len(shown)} more keys: sidebar (N)")
                continue
            line = box.row(align=True)
            split = line.split(factor=0.22, align=True)
            split.prop(row, "key", text="")
            cell = split.row(align=True)
            if kind == "rotation":
                cell.prop(row, "axis", text="")
                cell.prop(row, "angle", text="")
            else:
                cell.prop(row, kind, text="")
            remove = line.operator(X3D_OT_behaviour_key_remove.bl_idname, text="", icon="REMOVE")
            remove.node, remove.index = self.name, index
        add = box.operator(X3D_OT_behaviour_key_add.bl_idname, text="Add a key", icon="ADD")
        add.node = self.name

    def set_field(self, name, value):
        item = self.x3d_fields.get(name) or self.x3d_fields.add()
        item.name, item.value = name, value
        if name in ("key", "keyValue"):
            sync_rows(self)


NEVER_SECONDS = 1e20      # an SFTime this far off is "never" (files write 1e+30), shown as text, not as seconds
NODE_TABLE_ROWS = 6       # key rows drawn on a node's body; the sidebar draws them all


def rows_on_node(count, limit):
    """Which of ``count`` key rows a node's body shows, at most ``limit`` (None: all). The first rows and the last
    one: where the animation starts, how it goes on, and where it ends (the last key is usually 1)."""
    if limit is None or count <= limit:
        return list(range(count))
    return list(range(limit - 1)) + [count - 1]


MATERIAL_KINDS = ("material", "texture")      # bindings that name a Blender material rather than an object
NAMED_KINDS = ("joint", "site", "switch", "shader", "scene")     # bindings that are a name the Player looks for (a bone, a site's object, a Switch's DEF) or only names (a shader; a scene node kept in place: Collision, AudioClip, MovieTexture)


class _TargetNode(_X3DNodeBase):
    x3d_role = bg.TARGET
    x3d_object: PointerProperty(type=bpy.types.Object, name="Object")
    x3d_material: PointerProperty(type=bpy.types.Material, name="Material")
    x3d_bone: StringProperty(name="Name")      # an HAnimJoint's bone, an HAnimSite's object: found by name when Play runs

    def init(self, context):
        if not _SOCKETS_LATER:
            self._make_sockets(TARGETS[self.x3d_type] + _declared_rows(self))
        self.width = 220
        self.use_custom_color, self.color = True, (0.16, 0.24, 0.30)

    def draw_buttons(self, context, layout):
        kind = bg.BINDING_OF.get(self.x3d_type)
        layout.prop(self, "x3d_bone" if kind in NAMED_KINDS else "x3d_material" if kind in MATERIAL_KINDS else "x3d_object",
                    text="")

    def draw_label(self):
        kind = bg.BINDING_OF.get(self.x3d_type)
        if kind in NAMED_KINDS:
            return f"{self.x3d_type}  {self.x3d_bone}" if self.x3d_bone else f"{self.x3d_type}  (unbound)"
        data = self.x3d_material if kind in MATERIAL_KINDS else self.x3d_object
        return f"{self.x3d_type}  {data.name}" if data else f"{self.x3d_type}  (unbound)"


class X3DBehaviourCarried(_X3DNodeBase, Node):
    """A node the graph keeps exactly as the file had it (a Script, a ProtoInstance, a rig Blender did not import)"""
    bl_idname = "X3DBehaviourCarried"
    bl_label = "Carried X3D"
    x3d_role = bg.CARRIED
    x3d_type: StringProperty()
    x3d_xml: StringProperty(name="XML")
    x3d_inner: StringProperty()

    def init(self, context):
        self.width = 240
        self.use_custom_color, self.color = True, (0.30, 0.22, 0.14)

    def draw_buttons(self, context, layout):
        layout.label(text=f"{len(self.x3d_xml)} characters of X3D, written back unchanged", icon="LOCKED")


def _node_class(x3d_type, base):
    prefix = "X3DBehaviour" if base is _BehaviourNode else "X3DTarget"
    return type(f"{prefix}{x3d_type}", (base, Node), {
        "bl_idname": f"{prefix}{x3d_type}", "bl_label": x3d_type, "x3d_type": x3d_type,
        "__doc__": f"X3D {x3d_type}" + (f" ({NODES[x3d_type][0]})" if base is _BehaviourNode else " (scene)"),
        "__annotations__": dict(getattr(base, "__annotations__", {}), **_X3DNodeBase.__annotations__,
                                **(_typed_properties(x3d_type) if base is _BehaviourNode else {})),
    })


# The fields a node shows on its face even before they are given a value (the rest are in the sidebar).
MAIN_FIELDS = {
    "TimeSensor": ("cycleInterval", "loop"), "IntegerTrigger": ("integerKey",),
    "PlaneSensor": ("autoOffset",), "ProximitySensor": ("size",),
    **{name: ("tau", "order") for name in NODES if name.endswith(("Damper", "Damper2D"))},
    **{name: ("duration",) for name in NODES if name.endswith(("Chaser", "Chaser2D"))},
}


def _tree_of(context):
    space = context.space_data
    tree = getattr(space, "edit_tree", None) if space is not None else None
    if tree is None or tree.bl_idname != TREE_IDNAME:
        tree = getattr(context.scene, "x3d_behaviour_tree", None)
    return tree


class X3D_OT_behaviour_key_add(Operator):
    """Add a key after the last one (or halfway to the next, when one is named), with the value found there"""
    bl_idname = "x3d.behaviour_key_add"
    bl_label = "Add a key"
    bl_options = {"REGISTER", "UNDO"}
    node: StringProperty()
    index: IntProperty(default=-1)

    def execute(self, context):
        tree = _tree_of(context)
        node = tree.nodes.get(self.node) if tree is not None else None
        if node is None or node.x3d_type not in KEY_KINDS:
            return {"CANCELLED"}
        add_key(node, self.index)
        return {"FINISHED"}


class X3D_OT_behaviour_key_remove(Operator):
    """Remove this key and its value"""
    bl_idname = "x3d.behaviour_key_remove"
    bl_label = "Remove key"
    bl_options = {"REGISTER", "UNDO"}
    node: StringProperty()
    index: IntProperty()

    def execute(self, context):
        tree = _tree_of(context)
        node = tree.nodes.get(self.node) if tree is not None else None
        if node is None or node.x3d_type not in KEY_KINDS:
            return {"CANCELLED"}
        remove_key(node, self.index)
        return {"FINISHED"}


def add_key(node, after=-1):
    """Add a row to a key table: after row ``after`` (halfway to the next key), or at the end."""
    keys, values = key_table(node)
    zero = _ROW_ZERO[KEY_KINDS[node.x3d_type]]
    if not keys:
        keys, values = [0.0], [zero]
    elif 0 <= after < len(keys) - 1:
        keys.insert(after + 1, (keys[after] + keys[after + 1]) / 2)
        values.insert(after + 1, values[after])
    else:
        keys.append(min(1.0, keys[-1] + 0.25) if keys[-1] < 1.0 else keys[-1])
        values.append(values[-1])
    store_key_table(node, keys, values)


def remove_key(node, index):
    keys, values = key_table(node)
    if 0 <= index < len(keys):
        del keys[index], values[index]
        store_key_table(node, keys, values)


BEHAVIOUR_CLASSES = {name: _node_class(name, _BehaviourNode) for name in NODES}
TARGET_CLASSES = {name: _node_class(name, _TargetNode) for name in TARGETS if name in bg.BINDING_OF}


class X3D_MT_behaviour_add(bpy.types.Menu):
    bl_idname = "X3D_MT_behaviour_add"
    bl_label = "X3D"

    def draw(self, context):
        layout = self.layout
        groups = {}
        for name, (group, _rows) in NODES.items():
            groups.setdefault(group, []).append(name)
        for group, names in groups.items():
            layout.label(text=group)
            for name in names:
                layout.operator("node.add_node", text=name).type = BEHAVIOUR_CLASSES[name].bl_idname
            layout.separator()
        layout.label(text="Scene")
        for name, cls in TARGET_CLASSES.items():
            layout.operator("node.add_node", text=name).type = cls.bl_idname


def _add_menu(self, context):
    if context.space_data and getattr(context.space_data, "tree_type", "") == TREE_IDNAME:
        self.layout.menu(X3D_MT_behaviour_add.bl_idname)


# ---------------------------------------------------------------------------------------------------------------
# graph <-> tree
# ---------------------------------------------------------------------------------------------------------------

def _declared_rows(item):
    """A target node's declared fields as catalogue rows: (name, type, access, None)."""
    return tuple((*line.split(), None) for line in item.x3d_declared.splitlines() if len(line.split()) == 3)


def _datablock_of(binding):
    kind, name = binding
    if kind in MATERIAL_KINDS:
        return None, bpy.data.materials.get(name)
    if kind in NAMED_KINDS:
        return None, None            # held as text (``x3d_bone``): a bone is no object, and a site's object may not exist
    return bpy.data.objects.get(name), None


def _target_id(graph, blender_name, kind):
    """A legal, unused node id for a datablock: its name, with the kind added for anything but a Transform."""
    base = "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in blender_name) or "Node"
    if not (base[0].isalpha() or base[0] == "_"):
        base = "_" + base
    if kind != "transform":
        base = f"{base}.{kind}"
    for node in graph.nodes.values():
        if node.role == bg.TARGET and node.binding == (kind, blender_name):
            return node.id
    name, index = base, 1
    while name in graph.nodes:
        index += 1
        name = f"{base}_{index}"
    return name


def target(graph, datablock, name=None):
    """Add a Blender object, camera, light or material to ``graph`` as a ROUTE end; returns its handle.
    The X3D node is chosen from the datablock: a mesh or empty is a Transform, a camera a Viewpoint, a lamp its light."""
    if isinstance(datablock, bpy.types.Material):
        x3d_type, kind = "PhysicalMaterial", "material"
    elif datablock.type == "CAMERA":
        x3d_type, kind = ("OrthoViewpoint" if datablock.data.type == "ORTHO" else "Viewpoint"), "viewpoint"
    elif datablock.type == "LIGHT":
        x3d_type = {"SUN": "DirectionalLight", "SPOT": "SpotLight"}.get(datablock.data.type, "PointLight")
        kind = "light"
    else:
        x3d_type, kind = "Transform", "transform"
    return graph.target(x3d_type, name or _target_id(graph, datablock.name, kind), binding=(kind, datablock.name))


def transform_of(graph, obj, name=None):
    """The Transform of any object (a camera or a lamp also has one): ``transform_of(g, camera).translation``."""
    return graph.target("Transform", name or _target_id(graph, obj.name, "transform"), binding=("transform", obj.name))


def apply(graph, scene, name="X3D Behaviour"):
    """Show ``graph`` as the scene's behaviour node tree (replacing the nodes of the tree the scene already has)."""
    _ensure_scene_property()
    tree = scene.x3d_behaviour_tree or bpy.data.node_groups.new(name, TREE_IDNAME)
    _BUILDING.add(tree.name)
    try:
        _fill(graph, scene, tree)
    finally:
        _BUILDING.discard(tree.name)
        del _SOCKETS_LATER[:]
    tree.remove_mismatched_links()
    scene.x3d_behaviour_tree = tree
    return tree


def _fill(graph, scene, tree):
    """Build the nodes, then their sockets, then the links. Blender re-checks the whole tree after every change, so a
    call costs in proportion to the sockets the tree holds at that moment (measured: see docs/BEHAVIOUR_GRAPH.md): the
    node, its name and its place are set while the tree has none, and only the sockets and links are made after."""
    tree.nodes.clear()
    _SOCKETS_LATER.append(True)
    positions = bg.layout(graph)
    made = {}
    for node in graph.nodes.values():
        if node.role == bg.BEHAVIOUR:
            item = tree.nodes.new(BEHAVIOUR_CLASSES[node.node_type].bl_idname)
            for field_name, value in node.fields.items():
                item.set_field(field_name, value)
            if node.parent:
                item.x3d_parent = bpy.data.objects.get(node.parent)
            item.x3d_content = node.content
            item.x3d_declared = "\n".join(" ".join(row) for row in node.declared)
        elif node.role == bg.TARGET:
            if node.node_type not in TARGET_CLASSES or node.binding is None:
                continue
            item = tree.nodes.new(TARGET_CLASSES[node.node_type].bl_idname)
            item.x3d_object, item.x3d_material = _datablock_of(node.binding)
            if node.binding[0] in NAMED_KINDS:
                item.x3d_bone = node.binding[1]
            item.x3d_declared = "\n".join(" ".join(row) for row in node.declared)
        else:
            item = tree.nodes.new(X3DBehaviourCarried.bl_idname)
            item.x3d_type, item.x3d_xml, item.x3d_inner = node.node_type, node.xml or "", " ".join(node.inner)
        item.x3d_def = node.id
        item.name = node.id
        item.label = item.draw_label()
        item.location = node.position or positions.get(node.id, (0, 0))
        made[node.id] = item
    del _SOCKETS_LATER[:]
    for node_id, item in made.items():
        if item.x3d_role == bg.BEHAVIOUR:
            item._make_sockets(NODES[item.x3d_type][1] + _declared_rows(item))
        elif item.x3d_role == bg.TARGET:
            item._make_sockets(TARGETS[item.x3d_type] + _declared_rows(item))
    for route in graph.routes:
        a, b = made.get(route.from_id), made.get(route.to_id)
        if a is None or b is None:
            continue
        out_socket = _socket(a, graph.nodes[route.from_id], route.from_field, "out")
        in_socket = _socket(b, graph.nodes[route.to_id], route.to_field, "in")
        if out_socket is not None and in_socket is not None:
            tree.links.new(out_socket, in_socket)


def _socket(item, node, field_name, direction):
    sockets = item.outputs if direction == "out" else item.inputs
    if node.role == bg.CARRIED:
        found = sockets.get(field_name)
        if found is None:
            found = sockets.new(ANY, field_name)
            found.link_limit = 4095
        return found
    try:
        canonical = bg.resolve_field(node.node_type, field_name, direction, node.declared)[0]
    except bg.BehaviourError:
        return None
    return sockets.get(canonical)


def read(scene):
    """The scene's behaviour node tree as a graph, or None when the scene has none."""
    tree = getattr(scene, "x3d_behaviour_tree", None)
    if tree is None:
        return None
    graph = bg.Behaviour()
    ids = {}
    for item in tree.nodes:
        role = getattr(item, "x3d_role", None)
        if role is None:
            continue
        name = item.x3d_def or item.name
        if not bg._XML_NAME.match(name) or name in graph.nodes:
            base, index = "".join(ch if (ch.isalnum() or ch in "_-.") else "_" for ch in name) or "Node", 1
            if not base[0].isalpha() and base[0] != "_":
                base = "_" + base
            name = base
            while name in graph.nodes:
                index += 1
                name = f"{base}_{index}"
        ids[item.name] = name
        position = (item.location.x, item.location.y)
        if role == bg.BEHAVIOUR:
            graph.nodes[name] = bg.Node(id=name, node_type=item.x3d_type, role=role, position=position,
                                        fields={f.name: f.value for f in item.x3d_fields if f.value != ""},
                                        parent=item.x3d_parent.name if item.x3d_parent else None,
                                        content=item.x3d_content,
                                        declared=tuple(tuple(line.split()) for line in item.x3d_declared.splitlines()
                                                       if len(line.split()) == 3))
            if item.x3d_parent:
                # a parent with shapes records its DEF path; an empty parent (a Transform holding only other
                # Transforms) records only its DEF
                recorded = str(item.x3d_parent.get("x3d_def_path") or "").split("/")[-1] or \
                    str(item.x3d_parent.get("x3d_def") or "")
                if recorded:
                    graph.def_hints[item.x3d_parent.name] = recorded
        elif role == bg.TARGET:
            kind = bg.BINDING_OF[item.x3d_type]
            data = item.x3d_material if kind in MATERIAL_KINDS else item.x3d_object
            if kind in NAMED_KINDS:
                binding = (kind, item.x3d_bone) if item.x3d_bone else None
            else:
                binding = (kind, data.name) if data else None
            graph.nodes[name] = bg.Node(id=name, node_type=item.x3d_type, role=role, position=position, binding=binding,
                                        declared=tuple(tuple(line.split()) for line in item.x3d_declared.splitlines()
                                                       if len(line.split()) == 3))
        else:
            graph.nodes[name] = bg.Node(id=name, node_type=item.x3d_type, role=role, position=position,
                                        xml=item.x3d_xml, inner=tuple(item.x3d_inner.split()))
    seen = set()        # what graph.route(check=False) does, without it building the set of all routes for every link
    for link in tree.links:
        a, b = ids.get(link.from_node.name), ids.get(link.to_node.name)
        if a and b:
            route = bg.Route(a, link.from_socket.name, b, link.to_socket.name)
            if route.key() not in seen:
                seen.add(route.key())
                graph.routes.append(route)
    return graph


_PRESET_PROPERTIES = ("x3d_trigger", "x3d_action", "x3d_target", "x3d_radius", "x3d_tour_order", "x3d_tour_dwell")
_SCENE_PRESET_PROPERTIES = ("x3d_tour_travel", "x3d_tour_autostart", "x3d_tour_loop")


def import_graph(scene, filepath, new_actions=None):
    """Build the scene's behaviour node tree from the X3D file just imported; returns the diagnostics.

    Every ROUTE end is looked up among the imported objects by the DEF the importer recorded on them (``x3d_def``,
    ``x3d_def_path``). A top-level node Blender did not import (a tour rig, a Script) is carried as its XML. The click and
    tour presets the importer wrote as custom properties are removed, because the graph now holds the same ROUTEs and
    the exporter would otherwise write them twice."""
    if not str(filepath).lower().endswith(".x3d"):
        return [f"Behaviour graph: {filepath} is not XML-encoded X3D; no graph was built."]
    with open(filepath, "rb") as handle:
        parsed = bg.parse_x3d(handle.read())

    def resolver(def_name, node_type):
        kind = bg.BINDING_OF.get(node_type)
        if kind == "switch":
            # only where the importer tagged objects with this Switch's DEF: else the Switch stays what it was (carried
            # whole, listed as not simulated), since Play would have nothing to show or hide
            tagged = any(def_name == entry.rsplit(":", 2)[0] for obj in scene.objects
                         for entry in str(obj.get("x3d_switch") or "").split())
            return (kind, def_name) if tagged else None
        if kind in NAMED_KINDS:
            # kept whether or not Blender has it: Play finds the bone or object by this name, and says "not shown" when
            # it does not. A joint is the bone the importer named after the joint's ``name`` (else its DEF).
            wanted = (parsed._candidates.get(def_name) or {}).get("hanim_name") if kind == "joint" else None
            return kind, wanted or def_name
        if kind in MATERIAL_KINDS:          # a texture target is found through the material it belongs to
            for material in bpy.data.materials:
                if material.get("x3d_def") == def_name:
                    return kind, material.name
            return None
        if kind == "text":
            # the importer names a Text's FONT object by its Shape's or Transform's DEF and the curve by the Text's DEF
            found = [obj for obj in scene.objects if obj.type == "FONT" and getattr(obj.data, "name", None) == def_name]
            outer = [obj for obj in found if obj.parent is None or obj.parent not in found]
            return (kind, (outer or found)[0].name) if found else None
        wanted = {"transform": None, "viewpoint": "CAMERA", "light": "LIGHT"}.get(kind, "?")
        if wanted == "?":
            return None
        if wanted is None:
            # The importer gives a DEF'd Transform's unnamed child Transforms its DEF too (and often its name, the
            # Transform itself becoming "Name.001"): the Transform is the outermost object that carries the DEF.
            found = [obj for obj in scene.objects if obj.type not in {"CAMERA", "LIGHT"} and (
                str(obj.get("x3d_def_path") or "").split("/")[-1] == def_name or obj.get("x3d_def") == def_name)]
            outer = [obj for obj in found if obj.parent is None or obj.parent not in found]
            return (kind, (outer or found)[0].name) if found else None
        for obj in scene.objects:
            if obj.type == wanted and obj.get("x3d_def") == def_name:
                return kind, obj.name
        return None

    bg.bind(parsed, resolver)
    for node in parsed.nodes.values():           # the transform the importer baked into the UVs: Play shows only the change from it
        if node.role == bg.TARGET and node.node_type == "TextureTransform" and node.binding:
            material = bpy.data.materials.get(node.binding[1])
            authored = (parsed._candidates.get(node.id) or {}).get("texture_transform")
            if material is not None and authored is not None:
                material["x3d_texture_transform"] = json.dumps(authored)
    graph = bg.Behaviour(nodes=parsed.nodes, routes=parsed.routes, diagnostics=parsed.diagnostics)
    for node in graph.nodes.values():            # a placed sensor's parent is a DEF in the file: make it the object's name
        if node.role == bg.BEHAVIOUR and node.parent:
            found = resolver(node.parent, "Transform")
            if found is None:
                graph.diagnostics.append(f"{node.node_type} {node.id!r} sat in {node.parent!r}, which was not imported as "
                                         "an object; it will be written at the scene root.")
            node.parent = found[1] if found else None
    for obj in scene.objects:
        for key in _PRESET_PROPERTIES:
            if key in obj:
                del obj[key]
    for key in _SCENE_PRESET_PROPERTIES:
        if key in scene:
            del scene[key]
    graph.diagnostics.extend(_drop_baked_actions(graph, new_actions))
    tree = apply(graph, scene)
    tree["x3d_diagnostics"] = "\n".join(graph.diagnostics)
    kept = sum(1 for node in graph.nodes.values() if node.role == bg.BEHAVIOUR)
    return [f"Behaviour graph: {kept} nodes and {len(graph.routes)} ROUTEs in node tree {tree.name!r}."] + \
        [f"Behaviour graph: {message}" for message in graph.diagnostics]


def _drop_baked_actions(graph, new_actions):
    """Remove the keyframes this import baked for an object the graph drives, and say so.

    The importer bakes interpolators into an action (``<object>_x3d``); the graph now holds the same behaviour, the
    exporter already ignores keyframes of a driven object (rule 5), and the timeline would otherwise play a second copy.
    Only an action in ``new_actions`` (made by this import; None: none are touched), on an object a ROUTE reaches, and
    used by nothing else, is removed: keyframes the person made are never touched."""
    if not new_actions:
        return []
    driven = {node.binding[1] for node in graph.nodes.values()
              if node.role == bg.TARGET and node.binding and node.binding[0] not in MATERIAL_KINDS
              and any(route.to_id == node.id for route in graph.routes)}
    messages = []
    for name in sorted(driven):
        obj = bpy.data.objects.get(name)
        data = getattr(obj, "animation_data", None)
        action = getattr(data, "action", None)
        if action is None or action not in new_actions or action.users > 1:
            continue
        baked = action.name                       # read before the action is gone
        data.action = None
        bpy.data.actions.remove(action)
        messages.append(f"removed the keyframes the importer baked for {name!r} (action {baked!r}): the graph drives "
                        "it, so the timeline no longer plays a second copy.")
    return messages


def _editor_area_for(screen):
    """The node editor an imported graph is shown in: one already showing an X3D Behaviour tree, else the largest open
    node editor. None when the screen has no node editor: the layout is the person's, so no other editor is turned
    into one."""
    editors = [area for area in screen.areas if area.type == "NODE_EDITOR"]
    for area in editors:
        if area.spaces.active.tree_type == TREE_IDNAME:
            return area
    return max(editors, key=lambda area: area.width * area.height, default=None)


def unstack(tree, gap=40.0):
    """Push apart nodes that overlap in a column (see ``bg.unstack_columns``); only meaningful after the editor has
    drawn the tree, since a node has no size before. Returns how many nodes moved."""
    scale = bpy.context.preferences.system.ui_scale or 1.0       # dimensions are in pixels, locations are not
    moved = bg.unstack_columns([(node.name, node.location.x, node.location.y, node.dimensions.y / scale)
                                for node in tree.nodes], gap=gap)
    for name, y in moved.items():
        tree.nodes[name].location.y = y
    return len(moved)


def show_tree(context, tree):
    """Put ``tree`` in front of the person after an import; returns the area it is shown in, or None (no window, as in
    a script or ``blender -b``, or no node editor open)."""
    window = getattr(context, "window", None)
    screen = getattr(window, "screen", None)
    if screen is None or tree is None:
        return None
    area = _editor_area_for(screen)
    if area is None:
        return None
    space = area.spaces.active
    space.tree_type = TREE_IDNAME
    space.node_tree = tree

    wait = {"tries": 40, "unstacked": False}

    def frame_all():
        # A node has no size until the editor has drawn it once; unstack and view_all both need sizes. So: wait for
        # the first draw, unstack, wait for the draw with the new places, frame. Gives up waiting after two seconds.
        try:
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            drawn = region is not None and region.width > 1 and all(node.dimensions.x > 0 for node in tree.nodes)
            wait["tries"] -= 1
            if not drawn and wait["tries"] > 0:
                area.tag_redraw()
                return 0.05
            if drawn and not wait["unstacked"]:
                wait["unstacked"] = True
                if unstack(tree):
                    area.tag_redraw()
                    return 0.25                  # view_all frames the places of the last draw: let one happen
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.node.view_all()
        except (RuntimeError, ReferenceError):   # the area or window was closed in between
            pass
        return None

    bpy.app.timers.register(frame_all, first_interval=0.05)
    area.tag_redraw()
    return area


def import_summary(tree, area):
    """The line the import reports last (the one the status bar keeps), so the person knows where the graph went."""
    kinds = {cls.bl_idname for cls in BEHAVIOUR_CLASSES.values()}
    count = sum(1 for node in tree.nodes if node.bl_idname in kinds)
    head = f"X3D Behaviour: {count} nodes, {len(tree.links)} ROUTEs in node tree {tree.name!r}"
    if area is not None:
        return head + ", shown in the node editor."
    return head + ". To see them, switch any editor's type to X3D Behaviour."


classes = (X3DKeyRow, X3DFieldValue, X3D_OT_behaviour_key_add, X3D_OT_behaviour_key_remove, *SOCKET_CLASSES,
           X3DBehaviourTree, *BEHAVIOUR_CLASSES.values(), *TARGET_CLASSES.values(),
           X3DBehaviourCarried, X3D_MT_behaviour_add)


def _ensure_scene_property():
    """Define ``Scene.x3d_behaviour_tree`` when it is missing. Another copy of the add-on being disabled (a factory
    reset with the extension installed, while a development copy is also loaded) deletes the property; the node classes
    stay, so ``apply`` and ``import_graph`` put it back."""
    if not hasattr(bpy.types.Scene, "x3d_behaviour_tree"):
        bpy.types.Scene.x3d_behaviour_tree = PointerProperty(
            type=bpy.types.NodeTree, name="X3D Behaviour",
            description="The node tree whose sensors, timers, interpolators and ROUTEs are exported with this scene",
            poll=lambda self, tree: tree.bl_idname == TREE_IDNAME)


def ensure_registered():
    """Register whatever of this module is not registered now (classes and the scene property); safe to call again."""
    for cls in classes:
        if not getattr(cls, "is_registered", False):
            bpy.utils.register_class(cls)
    _ensure_scene_property()


def register():
    ensure_registered()
    bpy.types.NODE_MT_add.append(_add_menu)


def unregister():
    bpy.types.NODE_MT_add.remove(_add_menu)
    if hasattr(bpy.types.Scene, "x3d_behaviour_tree"):
        del bpy.types.Scene.x3d_behaviour_tree
    for cls in reversed(classes):
        if getattr(cls, "is_registered", False):
            bpy.utils.unregister_class(cls)
