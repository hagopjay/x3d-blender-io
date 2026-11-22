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

import bpy
from bpy.props import CollectionProperty, PointerProperty, StringProperty
from bpy.types import Node, NodeSocket, NodeTree, PropertyGroup

from . import behaviour_graph as bg
from .behaviour_catalogue import NODES, TARGETS

TREE_IDNAME = "X3DBehaviourTree"
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


SOCKET_CLASSES = tuple(_socket_class(name, colour) for name, colour in _COLOURS.items()) + (
    _socket_class("", (0.2, 0.2, 0.2, 1)),)


class X3DFieldValue(PropertyGroup):
    """One field that has a value: the X3D field name and its lexical text, exactly as it is written to the file."""
    value: StringProperty(name="Value", description="The field's value as X3D text, in the file's own axes (Y up)")


class X3DBehaviourTree(NodeTree):
    """ROUTEs between X3D sensors, timers, interpolators and the scene"""
    bl_idname = TREE_IDNAME
    bl_label = "X3D Behaviour"
    bl_icon = "DRIVER"

    def update(self):
        # X3D: a ROUTE joins fields of one type. Remove a link that does not.
        for link in list(self.links):
            a = getattr(link.from_socket, "x3d_type", None)
            b = getattr(link.to_socket, "x3d_type", None)
            if a and b and a != b:
                self.links.remove(link)


class _X3DNodeBase:
    x3d_def: StringProperty(name="DEF", description="The node's name in the X3D file")
    x3d_fields: CollectionProperty(type=X3DFieldValue)

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
        self._make_sockets(NODES[self.x3d_type][1])
        self.width = 240

    def draw_buttons(self, context, layout):
        layout.prop(self, "x3d_def")
        if self.x3d_type in bg.PLACED_TYPES:
            layout.prop(self, "x3d_parent")
        for item in self.x3d_fields:
            layout.prop(item, "value", text=item.name)

    def set_field(self, name, value):
        item = self.x3d_fields.get(name) or self.x3d_fields.add()
        item.name, item.value = name, value


class _TargetNode(_X3DNodeBase):
    x3d_role = bg.TARGET
    x3d_object: PointerProperty(type=bpy.types.Object, name="Object")
    x3d_material: PointerProperty(type=bpy.types.Material, name="Material")

    def init(self, context):
        self._make_sockets(TARGETS[self.x3d_type])
        self.width = 220
        self.use_custom_color, self.color = True, (0.16, 0.24, 0.30)

    def draw_buttons(self, context, layout):
        layout.prop(self, "x3d_material" if bg.BINDING_OF.get(self.x3d_type) == "material" else "x3d_object", text="")

    def draw_label(self):
        data = self.x3d_material if bg.BINDING_OF.get(self.x3d_type) == "material" else self.x3d_object
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
        "__annotations__": dict(getattr(base, "__annotations__", {}), **_X3DNodeBase.__annotations__),
    })


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

def _datablock_of(binding):
    kind, name = binding
    if kind == "material":
        return None, bpy.data.materials.get(name)
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
    tree = scene.x3d_behaviour_tree or bpy.data.node_groups.new(name, TREE_IDNAME)
    tree.nodes.clear()
    positions = bg.layout(graph)
    made = {}
    for node in graph.nodes.values():
        if node.role == bg.BEHAVIOUR:
            item = tree.nodes.new(BEHAVIOUR_CLASSES[node.node_type].bl_idname)
            for field_name, value in node.fields.items():
                item.set_field(field_name, value)
            if node.parent:
                item.x3d_parent = bpy.data.objects.get(node.parent)
        elif node.role == bg.TARGET:
            if node.node_type not in TARGET_CLASSES or node.binding is None:
                continue
            item = tree.nodes.new(TARGET_CLASSES[node.node_type].bl_idname)
            item.x3d_object, item.x3d_material = _datablock_of(node.binding)
        else:
            item = tree.nodes.new(X3DBehaviourCarried.bl_idname)
            item.x3d_type, item.x3d_xml, item.x3d_inner = node.node_type, node.xml or "", " ".join(node.inner)
        item.x3d_def = node.id
        item.name = node.id
        item.label = item.draw_label()
        item.location = node.position or positions.get(node.id, (0, 0))
        made[node.id] = item
    for route in graph.routes:
        a, b = made.get(route.from_id), made.get(route.to_id)
        if a is None or b is None:
            continue
        out_socket = _socket(a, graph.nodes[route.from_id], route.from_field, "out")
        in_socket = _socket(b, graph.nodes[route.to_id], route.to_field, "in")
        if out_socket is not None and in_socket is not None:
            tree.links.new(out_socket, in_socket)
    scene.x3d_behaviour_tree = tree
    return tree


def _socket(item, node, field_name, direction):
    sockets = item.outputs if direction == "out" else item.inputs
    if node.role == bg.CARRIED:
        found = sockets.get(field_name)
        if found is None:
            found = sockets.new(ANY, field_name)
            found.link_limit = 4095
        return found
    try:
        canonical = bg.resolve_field(node.node_type, field_name, direction)[0]
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
                                        parent=item.x3d_parent.name if item.x3d_parent else None)
            if item.x3d_parent:
                recorded = str(item.x3d_parent.get("x3d_def_path") or "").split("/")[-1]
                if recorded:
                    graph.def_hints[item.x3d_parent.name] = recorded
        elif role == bg.TARGET:
            kind = bg.BINDING_OF[item.x3d_type]
            data = item.x3d_material if kind == "material" else item.x3d_object
            graph.nodes[name] = bg.Node(id=name, node_type=item.x3d_type, role=role, position=position,
                                        binding=(kind, data.name) if data else None)
        else:
            graph.nodes[name] = bg.Node(id=name, node_type=item.x3d_type, role=role, position=position,
                                        xml=item.x3d_xml, inner=tuple(item.x3d_inner.split()))
    for link in tree.links:
        a, b = ids.get(link.from_node.name), ids.get(link.to_node.name)
        if a and b:
            graph.route(a, link.from_socket.name, b, link.to_socket.name, check=False)
    return graph


_PRESET_PROPERTIES = ("x3d_trigger", "x3d_action", "x3d_target", "x3d_radius", "x3d_tour_order", "x3d_tour_dwell")
_SCENE_PRESET_PROPERTIES = ("x3d_tour_travel", "x3d_tour_autostart", "x3d_tour_loop")


def import_graph(scene, filepath):
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
        if kind == "material":
            for material in bpy.data.materials:
                if material.get("x3d_def") == def_name:
                    return kind, material.name
            return None
        wanted = {"transform": None, "viewpoint": "CAMERA", "light": "LIGHT"}.get(kind, "?")
        if wanted == "?":
            return None
        for obj in scene.objects:
            if wanted is None:
                path = str(obj.get("x3d_def_path") or "")
                if path.split("/")[-1] == def_name or (obj.get("x3d_def") == def_name and obj.type not in {"CAMERA", "LIGHT"}):
                    return kind, obj.name
            elif obj.type == wanted and obj.get("x3d_def") == def_name:
                return kind, obj.name
        return None

    bg.bind(parsed, resolver)
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
    tree = apply(graph, scene)
    tree["x3d_diagnostics"] = "\n".join(graph.diagnostics)
    kept = sum(1 for node in graph.nodes.values() if node.role == bg.BEHAVIOUR)
    return [f"Behaviour graph: {kept} nodes and {len(graph.routes)} ROUTEs in node tree {tree.name!r}."] + \
        [f"Behaviour graph: {message}" for message in graph.diagnostics]


classes = (X3DFieldValue, *SOCKET_CLASSES, X3DBehaviourTree, *BEHAVIOUR_CLASSES.values(), *TARGET_CLASSES.values(),
           X3DBehaviourCarried, X3D_MT_behaviour_add)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.x3d_behaviour_tree = PointerProperty(
        type=bpy.types.NodeTree, name="X3D Behaviour",
        description="The node tree whose sensors, timers, interpolators and ROUTEs are exported with this scene",
        poll=lambda self, tree: tree.bl_idname == TREE_IDNAME)
    bpy.types.NODE_MT_add.append(_add_menu)


def unregister():
    bpy.types.NODE_MT_add.remove(_add_menu)
    del bpy.types.Scene.x3d_behaviour_tree
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
