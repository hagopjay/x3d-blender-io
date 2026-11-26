# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hosted nodes in Blender (class E of docs/BEHAVIOUR_EVENT_NODES.md): what may run a Script, and what a CollisionSensor
may read. No bpy here; ``behaviour_play`` supplies the datablocks.

A Script's JavaScript is never run: nothing in this add-on evaluates the text of a file it imported. A Script can still be
given a Python handler (``behaviour_sim.Simulation.host``), and this module is the only place where the add-on runs code
at all. The code is the text of a Python text datablock that the person chose for one Script and enabled, and it is run
only while three things hold:

1. the enablement is in ``REGISTRY``, which lives in this process's memory and nowhere else. Nothing a file can carry
   (an X3D document, a .blend, a linked library, a scene or node property, a text datablock's name) says "on": the registry
   starts empty with every Blender session and is emptied again whenever another file is loaded;
2. the enablement was made for this text's exact content: it keeps the SHA-256 of the source, so a text edited, replaced or
   swapped for a same-named one after the person enabled it is no longer enabled;
3. the text is the person's own, not a library's: ``behaviour_play`` refuses a text linked from another .blend.

The threat considered is a file that executes code on a person who only opened or imported it (a hostile .x3d, a .blend or
a linked library with a text datablock and properties pre-set to "enabled" and a name that matches a Script's DEF). The
defence is that "enabled" is an act of this session, stored where no file can write, bound to the content that was shown.
What it does not defend against: a person who enables text they did not read (a Python handler has all the rights of
Blender: Python cannot be sandboxed), and Python already running in the session (it could call ``REGISTRY.enable`` too; it
could also just run the code).
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET

HANDLER_FUNCTION = "handle"          # the function a handler text defines: handle(field, value, time, state) -> [(field, value)]


class HostedRefused(Exception):
    """A handler was asked for and may not run (not enabled, changed since, or not a handler). The message says why."""


def digest(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8", "surrogatepass")).hexdigest()


class Registry:
    """What the person has enabled in this session: (scope, Script DEF) -> (text name, digest of its source at that time)."""

    def __init__(self):
        self._enabled = {}

    def enable(self, scope, script_id, text_name, source):
        """Enable the text ``text_name`` with this ``source`` for the Script ``script_id`` of ``scope`` (a scene's name). One
        text per Script; enabling another replaces it."""
        self._enabled[(scope, script_id)] = (text_name, digest(source))

    def disable(self, scope, script_id):
        self._enabled.pop((scope, script_id), None)

    def clear(self):
        self._enabled.clear()

    def binding(self, scope, script_id):
        """(text name, digest) enabled for the Script, or None."""
        return self._enabled.get((scope, script_id))

    def is_enabled(self, scope, script_id, text_name, source):
        found = self._enabled.get((scope, script_id))
        return found is not None and found == (text_name, digest(source))

    def __len__(self):
        return len(self._enabled)


REGISTRY = Registry()


def build_handler(scope, script_id, text_name, source, registry=None):
    """The ``handle`` function of the text ``source``, for the Script ``script_id``: only when the registry says the person
    enabled exactly this text for it. Raises ``HostedRefused`` otherwise, and when the text does not run or does not define
    ``handle``. The text runs once here, to define its function; errors it raises are the person's own text's errors."""
    registry = REGISTRY if registry is None else registry
    if not registry.is_enabled(scope, script_id, text_name, source):
        found = registry.binding(scope, script_id)
        raise HostedRefused(f"Script {script_id}: " + ("the handler text was never enabled in this session" if found is None
                            else "the text changed since it was enabled" if found[0] == text_name
                            else f"another text ({found[0]!r}) is the one enabled"))
    namespace = {"__name__": f"x3d_handler_{script_id}"}
    try:
        exec(compile(source, f"<x3d handler {text_name}>", "exec"), namespace)      # the add-on's one exec: see the module text
    except Exception as error:                  # noqa: BLE001 - the person's text failed to define itself
        raise HostedRefused(f"Script {script_id}: {text_name} did not run: {type(error).__name__}: {error}") from error
    handler = namespace.get(HANDLER_FUNCTION)
    if not callable(handler):
        raise HostedRefused(f"Script {script_id}: {text_name} defines no function {HANDLER_FUNCTION}(field, value, time, state)")
    return handler


# ---------------------------------------------------------------------------------------------------------------
# CollisionSensor: what can be read from a rigid body world
# ---------------------------------------------------------------------------------------------------------------

COLLIDABLE_TYPES = ("CollidableShape", "CollidableOffset", "RigidBody")


def collidable_names(content):
    """The DEF and USE names of the collidables and bodies a CollisionSensor's content names, in order, once each. A
    sensor that refers to its CollisionCollection with ``USE`` names none (the collection is not in the sensor)."""
    names = []
    if content:
        try:
            root = ET.fromstring(f"<c>{content}</c>")
        except ET.ParseError:
            return names
        for element in root.iter():
            if element.tag.rpartition("}")[2] in COLLIDABLE_TYPES:
                for attribute in ("DEF", "USE"):
                    name = element.get(attribute)
                    if name and name not in names:
                        names.append(name)
    return names


def touching(boxes, watched=None):
    """Which of the bodies in ``boxes`` touch. ``boxes`` is {name: (low, high, margin)}: the body's axis-aligned box in world
    space (two (x, y, z) corners) and its collision margin. Two bodies touch when their boxes, each grown by its margin,
    overlap or meet on all three axes. Like X_ITE's CollisionSensor, a pair counts when either body is one of ``watched``
    (None: every body). Returns (contacts, intersections): the pairs as "A|B" names, and the watched bodies in them."""
    names = sorted(boxes)
    contacts, involved = [], set()
    for i, a in enumerate(names):
        low_a, high_a, margin_a = boxes[a]
        for b in names[i + 1:]:
            if watched is not None and a not in watched and b not in watched:
                continue
            low_b, high_b, margin_b = boxes[b]
            grow = margin_a + margin_b
            if all(low_a[k] - grow <= high_b[k] and low_b[k] - grow <= high_a[k] for k in range(3)):
                contacts.append(f"{a}|{b}")
                involved.update(n for n in (a, b) if watched is None or n in watched)
    return contacts, sorted(involved)
