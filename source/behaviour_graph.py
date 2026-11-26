# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The X3D behaviour graph: sensors, timers, interpolators and the ROUTEs between them, as editable data.

X3D scenes are alive (a click starts a timer, the timer drives an interpolator, the interpolator moves a door) and that
life is a graph: nodes with typed fields, joined by ROUTEs. This module is the graph without Blender: read it out of an
X3D file, check it, change it, write it back. ``behaviour_nodes.py`` shows the same graph as a Blender node tree.

No ``bpy`` import (like ir.py, emit_x3d40.py and lineage.py), so everything here runs and is tested in plain Python.

Three kinds of node:

* ``behaviour``  a node of the catalogue (TimeSensor, PositionInterpolator, TouchSensor ...). The graph owns it: its
  fields are edited here and it is written from here.
* ``target``     scene content a ROUTE starts or ends at (a Transform, a Viewpoint, a material, a light). Blender owns it:
  the graph only holds a binding to the object and the exporter supplies the DEF.
* ``carried``    anything else a ROUTE touches (a Script, a ProtoInstance, a Transform Blender did not import). Kept as
  the XML it arrived as and written back unchanged; it can be wired but not edited.

The rule the module enforces is X3D's own: a ROUTE joins an output to an input of the same field type.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from xml.sax.saxutils import quoteattr

try:
    from .behaviour_catalogue import NODES, TARGETS
except ImportError:  # pragma: no cover - standalone test fallback
    from behaviour_catalogue import NODES, TARGETS

SCHEMA = "x3d-blender-io.behaviour-graph/v0"

BEHAVIOUR, TARGET, CARRIED = "behaviour", "target", "carried"
# How a target is bound to Blender data: the X3D node type decides which datablock carries it.
TRANSFORM_TYPES = {"Transform"}
VIEWPOINT_TYPES = {"Viewpoint", "OrthoViewpoint"}
LIGHT_TYPES = {"PointLight", "DirectionalLight", "SpotLight"}
MATERIAL_TYPES = {"PhysicalMaterial", "Material", "UnlitMaterial"}
BINDING_OF = {**{t: "transform" for t in TRANSFORM_TYPES}, **{t: "viewpoint" for t in VIEWPOINT_TYPES},
              **{t: "light" for t in LIGHT_TYPES}, **{t: "material" for t in MATERIAL_TYPES},
              **{"Text": "text"},
              }
BINDING_OF["TextureTransform"] = "texture"      # bound to the material of the Appearance it sits in
# Sensors that act on their siblings: where they sit in the scene graph is part of their meaning.
PLACED_TYPES = {"TouchSensor", "PlaneSensor", "CylinderSensor", "SphereSensor", "ProximitySensor", "VisibilitySensor",
                "TransformSensor"}
_STRUCTURAL = {"DEF", "USE", "containerField", "class", "id", "style"}
_OUT, _IN = "out", "in"
_XML_NAME = re.compile(r"^[A-Za-z_][\w.\-]*$")


class BehaviourError(ValueError):
    """A graph operation X3D does not allow; ``code`` is stable for tests and receipts."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Node:
    id: str                                  # the DEF in the file it came from (or the one it will get)
    node_type: str                           # X3D node name
    role: str = BEHAVIOUR
    fields: dict[str, str] = field(default_factory=dict)   # X3D lexical values of the fields that are set
    parent: str | None = None                # behaviour: DEF of the Transform it sits in (None: the scene root)
    binding: tuple[str, str] | None = None   # target: (kind, Blender name), set by bind()
    xml: str | None = None                   # carried: the element as text
    inner: tuple[str, ...] = ()              # carried: DEFs inside it that ROUTEs may name
    position: tuple[float, float] | None = None


@dataclass(frozen=True)
class Route:
    from_id: str
    from_field: str
    to_id: str
    to_field: str

    def key(self):
        return (self.from_id, self.from_field, self.to_id, self.to_field)


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    routes: list[Route] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    # Blender object name -> the DEF its Transform had in the imported file (set by behaviour_nodes.read): the exporter
    # gives a placed sensor's parent that DEF back, so a file's names survive the trip.
    def_hints: dict[str, str] = field(default_factory=dict, repr=False)
    # parse_x3d only: what bind() needs to carry a node Blender could not take.
    _candidates: dict[str, dict] = field(default_factory=dict, repr=False)

    def add(self, node: Node) -> Node:
        if node.id in self.nodes:
            raise BehaviourError("duplicate-def", f"DEF {node.id!r} is already in the graph")
        if not _XML_NAME.match(node.id):
            raise BehaviourError("bad-def", f"{node.id!r} is not a legal DEF name")
        if node.role == BEHAVIOUR and node.node_type not in NODES:
            raise BehaviourError("unknown-node", f"{node.node_type!r} is not a behaviour node of the catalogue")
        self.nodes[node.id] = node
        return node

    def route(self, from_id, from_field, to_id, to_field, *, check=True) -> Route:
        route = Route(from_id, from_field, to_id, to_field)
        if check:
            problem = route_problem(self, route)
            if problem is not None:
                raise BehaviourError(problem[0], problem[1])
        if route.key() not in {r.key() for r in self.routes}:
            self.routes.append(route)
        return route

    def route_keys(self) -> set[tuple[str, str, str, str]]:
        return {route.key() for route in self.routes}


# ---------------------------------------------------------------------------------------------------------------
# The catalogue: which fields a node has, and which way events may flow through them
# ---------------------------------------------------------------------------------------------------------------

def field_rows(node_type: str):
    """((name, type, access, default), ...) of a catalogue node or target type, or None when the type is not known."""
    if node_type in NODES:
        return NODES[node_type][1]
    return TARGETS.get(node_type)


def resolve_field(node_type: str, name: str, direction: str):
    """(canonical field name, X3D field type) of ``name`` used as a ROUTE source ('out') or destination ('in').

    X3D lets an inputOutput field ``x`` be named ``x``, ``set_x`` (as a destination) or ``x_changed`` (as a source).
    Raises BehaviourError('unknown-field' | 'wrong-direction')."""
    rows = field_rows(node_type)
    if rows is None:
        raise BehaviourError("unknown-node", f"{node_type!r} is not in the catalogue")
    table = {row[0]: row for row in rows}
    candidates = [name]
    if direction == _IN and name.startswith("set_"):
        candidates.append(name[4:])
    if direction == _OUT and name.endswith("_changed"):
        candidates.append(name[:-8])
    for candidate in candidates:
        row = table.get(candidate)
        if row is None:
            continue
        access = row[2]
        if candidate != name and access != "inputOutput":
            continue
        allowed = ("outputOnly", "inputOutput") if direction == _OUT else ("inputOnly", "inputOutput")
        if access not in allowed:
            way = "a ROUTE source" if direction == _OUT else "a ROUTE destination"
            raise BehaviourError("wrong-direction", f"{node_type}.{name} is {access}: it cannot be {way}")
        return candidate, row[1]
    raise BehaviourError("unknown-field", f"{node_type} has no field {name!r}")


def _endpoint_type(graph: Graph, node_id: str, field_name: str, direction: str):
    """The field type at one end of a ROUTE, or None when it cannot be known (a carried node)."""
    node = graph.nodes.get(node_id)
    if node is None:
        raise BehaviourError("unknown-def", f"no node with DEF {node_id!r} in the graph")
    if node.role == CARRIED:
        return None
    return resolve_field(node.node_type, field_name, direction)[1]


def route_problem(graph: Graph, route: Route):
    """None when the ROUTE is legal X3D, else (code, message)."""
    try:
        source = _endpoint_type(graph, route.from_id, route.from_field, _OUT)
        destination = _endpoint_type(graph, route.to_id, route.to_field, _IN)
    except BehaviourError as error:
        return error.code, str(error)
    if source is not None and destination is not None and source != destination:
        return ("type-mismatch", f"{route.from_id}.{route.from_field} is {source} but {route.to_id}.{route.to_field} is "
                                 f"{destination}: a ROUTE joins fields of one type")
    return None


def validate(graph: Graph) -> list[dict]:
    """Every problem in the graph: [{code, message, where}], empty when it is legal X3D."""
    problems = []
    seen = set()
    for route in graph.routes:
        where = f"ROUTE {route.from_id}.{route.from_field} -> {route.to_id}.{route.to_field}"
        if route.key() in seen:
            problems.append({"code": "duplicate-route", "message": "the same ROUTE is listed twice", "where": where})
        seen.add(route.key())
        problem = route_problem(graph, route)
        if problem is not None:
            problems.append({"code": problem[0], "message": problem[1], "where": where})
    for node in graph.nodes.values():
        if node.role == BEHAVIOUR:
            table = {row[0]: row for row in field_rows(node.node_type) or ()}
            for name in node.fields:
                row = table.get(name)
                if row is None:
                    problems.append({"code": "unknown-field", "message": f"{node.node_type} has no field {name!r}",
                                     "where": node.id})
                elif row[2] in ("inputOnly", "outputOnly"):
                    problems.append({"code": "event-has-no-value", "where": node.id,
                                     "message": f"{node.node_type}.{name} is {row[2]}: an event cannot hold a value"})
        if node.role == TARGET and node.binding is None:
            problems.append({"code": "unbound-target", "where": node.id,
                             "message": f"target {node.id!r} ({node.node_type}) is not bound to a Blender datablock"})
    return problems


# ---------------------------------------------------------------------------------------------------------------
# Python values -> X3D lexical values (what the scripting API accepts)
# ---------------------------------------------------------------------------------------------------------------

def _number(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text if text not in ("-0", "") else "0"


def to_lexical(value, x3d_type: str = "") -> str:
    """A Python value as X3D field text: True -> 'true', (0, 1, 0) -> '0 1 0', [(0,0,0), (0,2,0)] -> '0 0 0 0 2 0'.
    A str is taken as already lexical, except for MFString where a list of str is quoted item by item."""
    if isinstance(value, str):
        return value
    if isinstance(value, (bool, int, float)):
        return _number(value)
    if x3d_type == "MFString":
        return " ".join('"' + str(item).replace("\\", "\\\\").replace('"', '\\"') + '"' for item in value)
    parts = []
    for item in value:
        if isinstance(item, (list, tuple)) or (hasattr(item, "__iter__") and not isinstance(item, str)):
            parts.extend(_number(component) for component in item)
        else:
            parts.append(_number(item))
    return " ".join(parts)


# ---------------------------------------------------------------------------------------------------------------
# X3D file -> graph
# ---------------------------------------------------------------------------------------------------------------

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_x3d(source) -> Graph:
    """The behaviour graph of an X3D document (XML text, bytes, an ElementTree or its root element).

    Every DEF'd catalogue node becomes a behaviour node and every ROUTE a route. A ROUTE end that is not a catalogue
    node becomes an unbound target (``bind`` decides what it is in Blender). Nothing is guessed: a ROUTE whose DEF does
    not exist is reported in ``diagnostics`` and left out."""
    if isinstance(source, (str, bytes)):
        root = ET.fromstring(source)
    elif hasattr(source, "getroot"):
        root = source.getroot()
    else:
        root = source
    scene = next((element for element in root.iter() if _local(element.tag) == "Scene"), root)
    graph = Graph()
    by_def: dict[str, ET.Element] = {}
    parent_of: dict[ET.Element, ET.Element] = {}
    nameless = 0
    for parent in scene.iter():
        for child in parent:
            parent_of[child] = parent
    for element in scene.iter():
        name = element.get("DEF")
        tag = _local(element.tag)
        if name and name not in by_def:
            by_def[name] = element
        elif not name and tag in NODES and element.get("USE") is None:
            nameless += 1
    if nameless:
        graph.diagnostics.append(f"{nameless} behaviour node(s) without a DEF cannot be routed and were left out of the graph.")

    def enclosing_transform(element):
        walker = parent_of.get(element)
        while walker is not None and walker is not scene:
            if _local(walker.tag) in TRANSFORM_TYPES and walker.get("DEF"):
                return walker.get("DEF")
            walker = parent_of.get(walker)
        return None

    def root_ancestor(element):
        walker = element
        while parent_of.get(walker) is not None and parent_of[walker] is not scene:
            walker = parent_of[walker]
        return walker if parent_of.get(walker) is scene else None

    for name, element in by_def.items():
        tag = _local(element.tag)
        if tag not in NODES:
            continue
        fields = {key: value for key, value in element.attrib.items() if key not in _STRUCTURAL}
        if len(element):
            graph.diagnostics.append(f"{tag} {name!r} has child nodes ({', '.join(sorted({_local(c.tag) for c in element}))}); "
                                     "they are not held by the graph.")
        graph.nodes[name] = Node(id=name, node_type=tag, role=BEHAVIOUR, fields=fields,
                                 parent=enclosing_transform(element) if tag in PLACED_TYPES else None)

    for element in scene.iter():
        if _local(element.tag) != "ROUTE":
            continue
        ends = [element.get(key) for key in ("fromNode", "fromField", "toNode", "toField")]
        if not all(ends):
            graph.diagnostics.append(f"A ROUTE with a missing attribute was left out: {ET.tostring(element, encoding='unicode').strip()}")
            continue
        missing = [name for name in (ends[0], ends[2]) if name not in by_def]
        if missing:
            graph.diagnostics.append(f"ROUTE {ends[0]}.{ends[1]} -> {ends[2]}.{ends[3]} names DEF {missing[0]!r}, which is not "
                                     "in the file; left out.")
            continue
        for name in (ends[0], ends[2]):
            if name in graph.nodes:
                continue
            target = by_def[name]
            top = root_ancestor(target)
            graph.nodes[name] = Node(id=name, node_type=_local(target.tag), role=TARGET)
            graph._candidates[name] = {
                "top_def": top.get("DEF") if top is not None else None,
                "top_xml": _element_text(top) if top is not None else None,
                "top_inner": tuple(sorted(e.get("DEF") for e in top.iter() if e.get("DEF"))) if top is not None else (),
                "top_type": _local(top.tag) if top is not None else None,
                "appearance_material": _appearance_material_def(target, parent_of),
                "texture_transform": {k: v for k, v in target.attrib.items() if k in ("center", "rotation", "scale", "translation")}
                if _local(target.tag) == "TextureTransform" else None,
            }
        graph.routes.append(Route(*ends))
    # routes are a set in X3D; keep first occurrences in file order
    unique, seen = [], set()
    for route in graph.routes:
        if route.key() not in seen:
            seen.add(route.key())
            unique.append(route)
    graph.routes = unique
    return graph


def _appearance_material_def(element, parent_of):
    """The DEF of the material in the Appearance an element sits in (a TextureTransform's), or None."""
    appearance = parent_of.get(element)
    for sibling in appearance if appearance is not None else ():
        if _local(sibling.tag) in MATERIAL_TYPES and sibling.get("DEF"):
            return sibling.get("DEF")
    return None


def _element_text(element: ET.Element) -> str:
    copy = ET.fromstring(ET.tostring(element))
    copy.tail = None
    return ET.tostring(copy, encoding="unicode")


def bind(graph: Graph, resolver) -> Graph:
    """Decide what every target is in Blender. ``resolver(def_name, node_type)`` returns (kind, blender_name) or None.

    A target the resolver does not know is carried when its top-level element can be kept whole (a Script, a
    ProtoInstance, a Transform Blender did not import): ROUTEs into it are rewritten to name the carried node and the
    inner DEF. A target that can be neither bound nor carried loses its ROUTEs, and the diagnostics say which."""
    renamed: dict[str, tuple[str, str | None]] = {}
    for name in list(graph.nodes):
        node = graph.nodes[name]
        if node.role != TARGET or node.binding is not None:
            continue
        # a TextureTransform is not a DEF the importer keeps: it is found through the material of its Appearance
        lookup = (graph._candidates.get(name) or {}).get("appearance_material") if node.node_type == "TextureTransform" else name
        binding = resolver(lookup, node.node_type) if lookup else None
        if node.node_type == "TextureTransform" and not lookup:
            graph.diagnostics.append(f"TextureTransform {name!r} sits in an Appearance whose material has no DEF, so it cannot "
                                     "be tied to a Blender material (not guessed); its ROUTEs were left out.")
        if binding is not None:
            node.binding = tuple(binding)
            continue
        candidate = graph._candidates.get(name) or {}
        top_def = candidate.get("top_def")
        if top_def and candidate.get("top_xml") and resolver(top_def, candidate.get("top_type") or "") is None:
            carried_id = top_def
            if carried_id not in graph.nodes or graph.nodes[carried_id].role != CARRIED:
                existing = graph.nodes.get(carried_id)
                if existing is not None and existing.role == BEHAVIOUR:
                    carried_id = None
                else:
                    graph.nodes[carried_id] = Node(id=carried_id, node_type=candidate["top_type"], role=CARRIED,
                                                   xml=candidate["top_xml"], inner=candidate["top_inner"])
            if carried_id is not None:
                if name != carried_id:
                    del graph.nodes[name]
                    renamed[name] = (carried_id, name)
                continue
        del graph.nodes[name]
        renamed[name] = ("", None)
        graph.diagnostics.append(f"{node.node_type} {name!r} is the end of a ROUTE but is neither a Blender object nor a "
                                 "top-level node that can be carried; its ROUTEs were left out.")
    kept = []
    for route in graph.routes:
        from_id, from_field, to_id, to_field = route.key()
        if from_id in renamed:
            carrier, inner = renamed[from_id]
            if not carrier:
                continue
            from_id, from_field = carrier, f"{inner}.{from_field}"
        if to_id in renamed:
            carrier, inner = renamed[to_id]
            if not carrier:
                continue
            to_id, to_field = carrier, f"{inner}.{to_field}"
        kept.append(Route(from_id, from_field, to_id, to_field))
    graph.routes = kept
    return graph


# ---------------------------------------------------------------------------------------------------------------
# graph -> X3D text
# ---------------------------------------------------------------------------------------------------------------

@dataclass
class Emission:
    root: list[str] = field(default_factory=list)                 # nodes written at the scene root
    children: dict[str, list[str]] = field(default_factory=dict)  # Blender object name -> nodes inside its Transform
    routes: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    driven: set[tuple[str, str]] = field(default_factory=set)     # (object name, field) a ROUTE writes into
    written_routes: int = 0
    dropped_routes: int = 0


def node_xml(node: Node, def_name: str | None = None) -> str:
    """A behaviour node as one self-closing element, fields in catalogue order."""
    rows = field_rows(node.node_type) or ()
    order = [row[0] for row in rows]
    names = [name for name in order if name in node.fields] + sorted(name for name in node.fields if name not in order)
    attributes = "".join(f" {name}={quoteattr(node.fields[name])}" for name in names if node.fields[name] != "")
    return f"<{node.node_type} DEF={quoteattr(def_name or node.id)}{attributes} />"


def emit(graph: Graph, *, def_of_node=None, def_of_target=None, object_of_parent=None, indent="    ") -> Emission:
    """The graph as X3D text.

    ``def_of_node(id)`` returns the DEF a behaviour or carried node gets in this file (default: its id).
    ``def_of_target(node)`` returns the DEF of the scene node a target is bound to, or None when it is not in the file.
    ``object_of_parent(parent)`` returns the exported object a placed sensor sits in, or None (then it goes to the root)."""
    def_of_node = def_of_node or (lambda node_id: node_id)
    def_of_target = def_of_target or (lambda node: node.id)
    object_of_parent = object_of_parent or (lambda parent: None)
    out = Emission()
    names: dict[str, str | None] = {}
    for node in graph.nodes.values():
        if node.role == BEHAVIOUR:
            names[node.id] = def_of_node(node.id)
            text = node_xml(node, names[node.id])
            owner = object_of_parent(node.parent) if node.parent else None
            if node.parent and owner is None:
                out.diagnostics.append(f"{node.node_type} {node.id!r} sat inside {node.parent!r}, which is not exported; "
                                       "written at the scene root, where it senses the whole scene.")
            if owner is not None:
                out.children.setdefault(owner, []).append(text)
            else:
                out.root.append(f"{indent}{text}\n")
        elif node.role == CARRIED:
            names[node.id] = node.id      # the XML is written as it came, DEFs included
            out.root.append(f"{indent}{node.xml}\n")
            out.diagnostics.append(f"{node.node_type} {node.id!r} is carried unchanged from the imported file.")
        else:
            names[node.id] = def_of_target(node) if node.binding is not None else None
            if names[node.id] is None:
                out.diagnostics.append(f"Target {node.id!r} ({node.node_type}) is not in the exported file; "
                                       "its ROUTEs were left out.")
    for route in graph.routes:
        ends = []
        for node_id, field_name in ((route.from_id, route.from_field), (route.to_id, route.to_field)):
            node = graph.nodes.get(node_id)
            name = names.get(node_id)
            if node is not None and node.role == CARRIED and "." in field_name:
                name, field_name = field_name.split(".", 1)
            ends.append((name, field_name))
        if ends[0][0] is None or ends[1][0] is None:
            out.dropped_routes += 1
            continue
        out.routes.append(f'{indent}<ROUTE fromNode="{ends[0][0]}" fromField="{ends[0][1]}" '
                          f'toNode="{ends[1][0]}" toField="{ends[1][1]}" />\n')
        out.written_routes += 1
        destination = graph.nodes.get(route.to_id)
        if destination is not None and destination.role == TARGET and destination.binding is not None:
            try:
                canonical = resolve_field(destination.node_type, route.to_field, _IN)[0]
            except BehaviourError:
                canonical = route.to_field
            out.driven.add((destination.binding[1], canonical))
    return out


# ---------------------------------------------------------------------------------------------------------------
# Comparing and laying out
# ---------------------------------------------------------------------------------------------------------------

def signature(graph: Graph) -> dict:
    """What must survive a round trip: every behaviour node with its set fields, and every ROUTE."""
    return {
        "nodes": {node.id: {"type": node.node_type, "fields": dict(sorted(node.fields.items())), "parent": node.parent}
                  for node in graph.nodes.values() if node.role == BEHAVIOUR},
        "carried": sorted(node.id for node in graph.nodes.values() if node.role == CARRIED),
        "routes": sorted(_canonical_route(graph, route) for route in graph.routes),
    }


def _canonical_route(graph: Graph, route: Route):
    """A ROUTE with X3D's spelling variants folded (set_translation and translation are one field)."""
    names = []
    for node_id, field_name, direction in ((route.from_id, route.from_field, _OUT), (route.to_id, route.to_field, _IN)):
        node = graph.nodes.get(node_id)
        if node is not None and node.role != CARRIED:
            try:
                field_name = resolve_field(node.node_type, field_name, direction)[0]
            except BehaviourError:
                pass
        names.append(field_name)
    return (route.from_id, names[0], route.to_id, names[1])


def difference(before: Graph, after: Graph) -> dict:
    """{'nodes_lost', 'nodes_added', 'fields_changed', 'routes_lost', 'routes_added'}; all empty when nothing changed."""
    a, b = signature(before), signature(after)
    changed = {}
    for name in sorted(set(a["nodes"]) & set(b["nodes"])):
        if a["nodes"][name] != b["nodes"][name]:
            fields_a, fields_b = a["nodes"][name]["fields"], b["nodes"][name]["fields"]
            changed[name] = {key: (fields_a.get(key), fields_b.get(key)) for key in sorted(set(fields_a) | set(fields_b))
                             if fields_a.get(key) != fields_b.get(key)}
            if a["nodes"][name]["parent"] != b["nodes"][name]["parent"]:
                changed[name]["(parent)"] = (a["nodes"][name]["parent"], b["nodes"][name]["parent"])
    return {
        "nodes_lost": sorted(set(a["nodes"]) - set(b["nodes"])),
        "nodes_added": sorted(set(b["nodes"]) - set(a["nodes"])),
        "fields_changed": changed,
        "routes_lost": sorted(set(map(tuple, a["routes"])) - set(map(tuple, b["routes"]))),
        "routes_added": sorted(set(map(tuple, b["routes"])) - set(map(tuple, a["routes"]))),
    }


def unstack_columns(boxes, *, gap=40.0):
    """New y for boxes that overlap the one above them in their column; ``boxes`` is ``(key, x, y, height)`` with y up
    (the top edge) and nodes in one column sharing x. Returns only the keys that move. ``layout`` spaces rows evenly;
    a node is as tall as the fields it shows, which only the editor knows after drawing it."""
    columns: dict[int, list] = {}
    for box in boxes:
        columns.setdefault(round(box[1]), []).append(box)
    moved = {}
    for column in columns.values():
        floor = None
        for key, _x, y, height in sorted(column, key=lambda box: -box[2]):
            if floor is not None and y > floor:
                y = moved[key] = floor
            floor = y - height - gap
    return moved


def layout(graph: Graph, *, column=320.0, row=200.0) -> dict[str, tuple[float, float]]:
    """A left-to-right position for every node: events flow from the sensors on the left to the scene on the right.
    Columns are the longest path from a source; a cycle is cut where it is first met."""
    outgoing: dict[str, list[str]] = {name: [] for name in graph.nodes}
    incoming: dict[str, int] = {name: 0 for name in graph.nodes}
    for route in graph.routes:
        if route.from_id in outgoing and route.to_id in outgoing and route.to_id not in outgoing[route.from_id] \
                and route.from_id != route.to_id:
            outgoing[route.from_id].append(route.to_id)
            incoming[route.to_id] += 1
    depth = {name: 0 for name in graph.nodes}
    state: dict[str, int] = {}

    def visit(name, level):
        if state.get(name) == 1:
            return
        if level > depth[name] or name not in state:
            depth[name] = max(depth[name], level)
        else:
            return
        state[name] = 1
        for following in outgoing[name]:
            visit(following, depth[name] + 1)
        state[name] = 2

    for name in graph.nodes:
        if incoming[name] == 0:
            visit(name, 0)
    for name in graph.nodes:
        if name not in state:
            visit(name, 0)
    # scene targets read best in the last column
    last = max(depth.values(), default=0)
    for name, node in graph.nodes.items():
        if node.role != BEHAVIOUR and not outgoing[name]:
            depth[name] = max(depth[name], last)
    columns: dict[int, list[str]] = {}
    for name in graph.nodes:
        columns.setdefault(depth[name], []).append(name)
    positions = {}
    for level, names in columns.items():
        for index, name in enumerate(names):
            positions[name] = (level * column, -index * row)
    return positions


# ---------------------------------------------------------------------------------------------------------------
# The scripting methods: build a graph in a few readable lines
# ---------------------------------------------------------------------------------------------------------------

class Port:
    """One field of one node, as a ROUTE end. ``a.touchTime >> b.startTime`` draws the ROUTE (one per line) and
    returns ``b``."""

    def __init__(self, handle: "Handle", name: str):
        self.handle, self.name = handle, name

    def __rshift__(self, other: "Port") -> "Handle":
        if not isinstance(other, Port):
            raise BehaviourError("not-a-port", "the right side of >> must be a field, such as timer.startTime")
        self.handle.graph.route(self.handle.id, self.name, other.handle.id, other.name)
        return other.handle

    def __repr__(self):
        return f"{self.handle.id}.{self.name}"


class Handle:
    """What ``Behaviour.add`` and ``Behaviour.target`` return: the node, with every field reachable as an attribute."""

    def __init__(self, graph: Graph, node: Node):
        object.__setattr__(self, "graph", graph)
        object.__setattr__(self, "node", node)
        object.__setattr__(self, "id", node.id)

    def __getattr__(self, name: str) -> Port:
        if name.startswith("__"):
            raise AttributeError(name)
        node = self.node
        if node.role != CARRIED:
            rows = {row[0] for row in field_rows(node.node_type) or ()}
            bare = name[4:] if name.startswith("set_") else name[:-8] if name.endswith("_changed") else name
            if name not in rows and bare not in rows:
                raise BehaviourError("unknown-field", f"{node.node_type} has no field {name!r}; it has: "
                                                      f"{', '.join(sorted(rows))}")
        return Port(self, name)

    def __setattr__(self, name: str, value):
        self.set(**{name: value})

    def set(self, **fields) -> "Handle":
        """Give fields a value: ``timer.set(cycleInterval=4, loop=True)``."""
        node = self.node
        if node.role != BEHAVIOUR:
            raise BehaviourError("not-editable", f"{node.id!r} is {node.role}: its fields are not edited in the graph")
        table = {row[0]: row for row in field_rows(node.node_type)}
        for name, value in fields.items():
            row = table.get(name)
            if row is None:
                raise BehaviourError("unknown-field", f"{node.node_type} has no field {name!r}; it has: "
                                                      f"{', '.join(sorted(table))}")
            if row[2] in ("inputOnly", "outputOnly"):
                raise BehaviourError("event-has-no-value", f"{node.node_type}.{name} is {row[2]}: an event carries values "
                                                           "while the scene runs, it cannot be given one beforehand")
            node.fields[name] = to_lexical(value, row[1])
        return self

    def __repr__(self):
        return f"<{self.node.node_type} {self.id}>"


class Behaviour(Graph):
    """A graph you build by script.

        b = Behaviour()
        click = b.add("TouchSensor", "Click", parent="Door")
        timer = b.add("TimeSensor", "Timer", cycleInterval=2)
        slide = b.add("PositionInterpolator", "Slide", key=[0, 1], keyValue=[(0, 0, 0), (0, 2, 0)])
        door = b.target("Transform", "Door")
        click.touchTime >> timer.startTime
        timer.fraction_changed >> slide.set_fraction
        slide.value_changed >> door.translation
    """

    def add(self, node_type: str, name: str | None = None, parent: str | None = None, **fields) -> Handle:
        """A new behaviour node. ``name`` becomes its DEF (made up when left out). ``parent`` is the DEF of the Transform a
        sensor sits in: a TouchSensor senses clicks on its parent's shapes."""
        if node_type not in NODES:
            import difflib
            near = difflib.get_close_matches(node_type, list(NODES), n=2, cutoff=0.8)
            hint = f"; did you mean {', '.join(near)}?" if near else ""
            raise BehaviourError("unknown-node", f"{node_type!r} is not a behaviour node{hint}")
        if name is None:
            index = 1
            while f"{node_type}{index}" in self.nodes:
                index += 1
            name = f"{node_type}{index}"
        node = Graph.add(self, Node(id=name, node_type=node_type, role=BEHAVIOUR, parent=parent))
        return Handle(self, node).set(**fields)

    def target(self, node_type: str, name: str, binding: tuple[str, str] | None = None) -> Handle:
        """A piece of the scene a ROUTE may start or end at, named by the DEF it has (or will have) in the file."""
        if node_type not in TARGETS and node_type not in NODES:
            raise BehaviourError("unknown-node", f"{node_type!r} is not a target type of the catalogue")
        if name in self.nodes:
            return Handle(self, self.nodes[name])
        node = Graph.add(self, Node(id=name, node_type=node_type, role=TARGET,
                                    binding=binding or (BINDING_OF.get(node_type, "def"), name)))
        return Handle(self, node)

    def get(self, name: str) -> Handle:
        if name not in self.nodes:
            raise BehaviourError("unknown-def", f"no node named {name!r}; the graph has: {', '.join(sorted(self.nodes))}")
        return Handle(self, self.nodes[name])

    def connect(self, source: Port, destination: Port) -> Route:
        """The same as ``source >> destination``."""
        return self.route(source.handle.id, source.name, destination.handle.id, destination.name)

    def disconnect(self, source: Port, destination: Port) -> bool:
        key = (source.handle.id, source.name, destination.handle.id, destination.name)
        before = len(self.routes)
        self.routes = [route for route in self.routes if route.key() != key]
        return len(self.routes) != before

    def remove(self, name: str) -> None:
        """Take a node out, with every ROUTE that touches it."""
        self.nodes.pop(name, None)
        self.routes = [route for route in self.routes if name not in (route.from_id, route.to_id)]

    def check(self) -> list[dict]:
        return validate(self)

    def explain(self) -> str:
        """The graph as sentences, one per ROUTE: for reading aloud, for a diff, for an AI to check its own work."""
        lines = []
        for route in self.routes:
            a, b = self.nodes[route.from_id], self.nodes[route.to_id]
            try:
                kind = _endpoint_type(self, route.from_id, route.from_field, _OUT) or "?"
            except BehaviourError:
                kind = "?"
            lines.append(f"{a.node_type} {a.id}.{route.from_field} --{kind}--> {b.node_type} {b.id}.{route.to_field}")
        return "\n".join(lines)

    @classmethod
    def from_x3d(cls, source) -> "Behaviour":
        """The graph already in an X3D file, ready to be changed. Scene nodes keep their DEF as their binding."""
        parsed = parse_x3d(source)
        graph = cls(nodes=parsed.nodes, routes=parsed.routes, diagnostics=parsed.diagnostics)
        for node in graph.nodes.values():
            if node.role == TARGET and node.binding is None:
                node.binding = (BINDING_OF.get(node.node_type, "def"), node.id)
        return graph

    def weave(self, x3d_text: str) -> str:
        """This graph written into an X3D document: see ``weave``."""
        return weave(x3d_text, self)


def strip(x3d_text: str) -> str:
    """An X3D document with its behaviour taken out: every DEF'd catalogue node and every ROUTE removed.
    ``weave(strip(doc), Behaviour.from_x3d(doc))`` gives back a document with the same graph."""
    root = ET.fromstring(x3d_text)
    for parent in list(root.iter()):
        for child in list(parent):
            tag = _local(child.tag)
            if tag == "ROUTE" or (tag in NODES and child.get("DEF")):
                parent.remove(child)
    return _document_text(x3d_text, root)


def weave(x3d_text: str, graph: Graph) -> str:
    """Write the graph into an X3D document that already holds the scene.

    Placed sensors go inside the Transform their ``parent`` names; every other node, then every ROUTE, goes at the end of
    the Scene. A target must already be in the document under its DEF. Raises BehaviourError when the graph is not legal
    X3D or names a DEF the document lacks: a file is never written from a broken graph."""
    problems = [p for p in validate(graph) if p["code"] != "unbound-target"]
    if problems:
        raise BehaviourError(problems[0]["code"], "; ".join(f"{p['where']}: {p['message']}" for p in problems))
    root = ET.fromstring(x3d_text)
    scene = next((element for element in root.iter() if _local(element.tag) == "Scene"), None)
    if scene is None:
        raise BehaviourError("no-scene", "the document has no Scene element")
    by_def = {element.get("DEF"): element for element in root.iter() if element.get("DEF")}
    for node in graph.nodes.values():
        if node.role == TARGET and node.id not in by_def:
            raise BehaviourError("unknown-def", f"target {node.id!r} is not in the document")
        if node.role != TARGET and node.id in by_def:
            raise BehaviourError("duplicate-def", f"the document already has a node with DEF {node.id!r}")
        if node.role == BEHAVIOUR and node.parent and node.parent not in by_def:
            raise BehaviourError("unknown-def", f"{node.id!r} names parent {node.parent!r}, which is not in the document")
    emission = emit(graph, object_of_parent=lambda parent: parent, indent="")
    for parent, texts in emission.children.items():
        for text in texts:
            by_def[parent].append(ET.fromstring(text))
    for text in emission.root + emission.routes:
        scene.append(ET.fromstring(text))
    return _document_text(x3d_text, root)


def _document_text(original: str, root: ET.Element) -> str:
    ET.indent(root, space="  ")
    head = original[:original.find("<X3D")] if "<X3D" in original else '<?xml version="1.0" encoding="UTF-8"?>\n'
    return head + ET.tostring(root, encoding="unicode") + "\n"


def to_json(graph: Graph) -> dict:
    """The graph as plain data (schema ``x3d-blender-io.behaviour-graph/v0``): what an AI agent reads and writes."""
    return {
        "schema": SCHEMA,
        "nodes": [{"id": n.id, "type": n.node_type, "role": n.role, **({"fields": dict(n.fields)} if n.fields else {}),
                   **({"parent": n.parent} if n.parent else {}), **({"binding": list(n.binding)} if n.binding else {}),
                   **({"xml": n.xml, "inner": list(n.inner)} if n.role == CARRIED else {}),
                   **({"position": list(n.position)} if n.position else {})} for n in graph.nodes.values()],
        "routes": [list(route.key()) for route in graph.routes],
    }


def from_json(data: dict) -> Behaviour:
    if data.get("schema") != SCHEMA:
        raise BehaviourError("bad-schema", f"expected schema {SCHEMA!r}, got {data.get('schema')!r}")
    graph = Behaviour()
    for item in data.get("nodes", ()):
        Graph.add(graph, Node(id=item["id"], node_type=item["type"], role=item.get("role", BEHAVIOUR),
                              fields=dict(item.get("fields", {})), parent=item.get("parent"),
                              binding=tuple(item["binding"]) if item.get("binding") else None,
                              xml=item.get("xml"), inner=tuple(item.get("inner", ())),
                              position=tuple(item["position"]) if item.get("position") else None))
    for ends in data.get("routes", ()):
        graph.route(*ends, check=False)
    return graph


def route_verdict(from_type: str, from_field: str, to_type: str, to_field: str) -> str:
    """'ok' when X3D allows a ROUTE from ``from_type.from_field`` to ``to_type.to_field``, else the error code.
    The browser Wire Lab has the same function; tests/behaviour/route-cases.json holds the cases both must agree on."""
    try:
        source = resolve_field(from_type, from_field, _OUT)[1]
        destination = resolve_field(to_type, to_field, _IN)[1]
    except BehaviourError as error:
        return error.code
    return "ok" if source == destination else "type-mismatch"
