# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The sound bridge in Blender: an X3D 4.0 audio graph the import carried becomes something you can hear, and the export
writes the graph back (docs/SOUND_BRIDGE.md, section 8).

* A **SpatialSound** graph becomes a Speaker object parented to its Transform's object (or at the top of the scene). The
  Speaker plays the graph rendered by ``sound_graph`` (a WAV packed into the .blend) and keeps the graph's XML, exactly as
  the file wrote it, in ``x3d_sound_graph``. The export writes that XML back inside the parent's Transform, with what was
  changed on the Speaker (volume, distances, cone, where it is and where it points) merged into those fields only; every
  other field and every node of the graph stays as written. Delete the Speaker and the graph goes with it.
* An **AudioDestination** or **StreamAudioDestination** graph stays carried as it is (no Blender property maps to it); a
  sound strip in the scene's sequencer plays its render, marked ``x3d_sound_cache``: a cache only, the export ignores it.

What is left carried, not bridged: a graph with a USE in it (fan-out rendering is untested), a graph a ROUTE touches (the
render would freeze the routed field), a graph with a node the model does not know (a MovieTexture source, a
ProtoInstance), a SpatialSound under a USE'd Transform (the copies would each need their own Speaker), and any graph whose
render fails. Those come back through carry, as before.
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import wave
import xml.etree.ElementTree as ET

try:
    from . import sound_graph as sg
except ImportError:  # pragma: no cover - standalone test fallback
    import sound_graph as sg

logger = logging.getLogger(__name__)

SOUND_GRAPH_PROPERTY = "x3d_sound_graph"     # on a Speaker object: the SpatialSound graph's XML, as the file wrote it
SOUND_CACHE_PROPERTY = "x3d_sound_cache"     # on a sequencer strip: the render of a carried destination graph
SOUND_APPLIED_PROPERTY = "x3d_sound_applied"  # on the Speaker: its properties as Blender kept them at import (clamped)
SPEAKER_ROOTS = ("SpatialSound",)
STRIP_ROOTS = ("AudioDestination", "StreamAudioDestination")
RATE = 48000
MAX_SECONDS = 60.0


# ----------------------------------------------------------------------------------------------- what is bridged
def bridgeable(xml: str, routed_defs) -> ET.Element | None:
    """The parsed root of a carried item when the bridge models every node of it, else None."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    if root.tag not in SPEAKER_ROOTS + STRIP_ROOTS:
        return None
    for element in root.iter():
        if element.tag not in sg.AUDIO_NODES and not element.tag.startswith("Metadata"):
            return None
        if element.get("USE") is not None or element.get("DEF") in routed_defs:
            return None
    return root


def render_seconds(scene) -> float:
    """How long a render is: the scene's frame range, at most a minute."""
    fps = scene.render.fps / (scene.render.fps_base or 1.0)
    return max(1.0, min(MAX_SECONDS, (scene.frame_end - scene.frame_start + 1) / fps))


def write_wav(samples, path: str, rate: int = RATE) -> None:
    """16-bit PCM through the stdlib (aud.Sound.write adds frames in Blender 5.3; see sound_bridge_demo.py)."""
    import numpy as np
    pcm = (np.clip(samples, -1.0, 32767 / 32768) * 32768).round().astype("<i2")
    with wave.open(path, "wb") as out:
        out.setnchannels(samples.shape[1])
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm.tobytes())


def render_to_sound(root: ET.Element, name: str, seconds: float, base_dir: str):
    """The graph rendered to a WAV and loaded as a packed bpy Sound."""
    import aud
    import bpy
    import numpy as np
    node = sg.parse_graph(root)
    renderer = sg.Renderer(aud, np, rate=RATE, duration=seconds, base_dir=base_dir)
    samples = renderer.array(renderer.render(node))
    folder = tempfile.mkdtemp(prefix="x3d_sound_")
    path = os.path.join(folder, f"{bpy.path.clean_name(name)}.wav")
    write_wav(samples, path)
    sound = bpy.data.sounds.load(path)
    sound.name = name
    sound.pack()
    return sound


# ----------------------------------------------------------------------------------------------- import
def _direction_matrix(location, direction):
    """X3D local frame -> the Speaker's: at ``location``, its -Z (where a Blender speaker points, OpenAL's convention)
    along ``direction``."""
    from mathutils import Matrix, Vector
    rotation = Matrix()
    d = Vector(direction)
    if d.length > 1e-12:
        rotation = Vector((0.0, 0.0, -1.0)).rotation_difference(d.normalized()).to_matrix().to_4x4()
    return Matrix.Translation(Vector(location)) @ rotation


def make_speaker(root: ET.Element, xml: str, owner, bpyscene, global_matrix, base_dir: str, collection):
    """A Speaker for a SpatialSound graph, under ``owner`` (an object, or the scene for the top level)."""
    import bpy
    node = sg.parse_graph(root)
    name = root.get("DEF") or root.tag
    sound = render_to_sound(root, name, render_seconds(bpyscene), base_dir)
    speaker = bpy.data.speakers.new(name)
    speaker.sound = sound
    applied = {}
    for key, value in sg.speaker_settings(node).items():
        if not key.startswith("_") and hasattr(speaker, key):
            setattr(speaker, key, value)
            applied[key] = float(getattr(speaker, key))     # read back: Blender clamps (volume to 0..1)
    ob = bpy.data.objects.new(name, speaker)
    collection.objects.link(ob)
    local = _direction_matrix(node.floats("location") or (0, 0, 0), node.floats("direction") or (0, 0, 1))
    if isinstance(owner, bpy.types.Object):
        ob.parent = owner
        ob.matrix_world = owner.matrix_world @ local
    else:
        ob.matrix_world = global_matrix @ local
    ob[SOUND_GRAPH_PROPERTY] = xml
    ob[SOUND_APPLIED_PROPERTY] = json.dumps(applied)
    return ob


def make_strip(root: ET.Element, bpyscene, base_dir: str):
    """A sequencer sound strip playing a destination graph's render (a cache: the graph stays carried)."""
    name = root.get("DEF") or root.tag
    sound = render_to_sound(root, name, render_seconds(bpyscene), base_dir)
    editor = bpyscene.sequence_editor or bpyscene.sequence_editor_create()
    strips = (editor.strips if hasattr(editor, "strips") else editor.sequences)       # 'strips' from Blender 4.4/5.0
    channel = 1 + max((s.channel for s in strips), default=0)
    strip = strips.new_sound(name, sound.filepath, channel, bpyscene.frame_start)
    if strip.sound is not sound:                      # new_sound loads the file again: use the packed one
        old, strip.sound = strip.sound, sound
        if old is not None and old.users == 0:
            import bpy
            bpy.data.sounds.remove(old)
    strip[SOUND_CACHE_PROPERTY] = True
    return strip


# ----------------------------------------------------------------------------------------------- export
# Speaker property -> SpatialSound field, and how a field value becomes the property's (speaker_settings) and back
_FIELDS = (
    ("distance_reference", "referenceDistance", float, float),
    ("distance_max", "maxDistance", float, float),
    ("attenuation", "rolloffFactor", float, float),
    ("cone_angle_inner", "coneInnerAngle", math.degrees, math.radians),
    ("cone_angle_outer", "coneOuterAngle", math.degrees, math.radians),
    ("cone_volume_outer", "coneOuterGain", float, float),
)


def _num(value: float) -> str:
    text = f"{value:.6g}"
    return "0" if text == "-0" else text


def _differs(a: float, b: float) -> bool:
    return abs(a - b) > 1e-5 * max(1.0, abs(a), abs(b))      # Blender keeps these as float32


def speaker_graph_xml(obj, local_matrix, diagnostics=None) -> str | None:
    """The SpatialSound XML for a bridged Speaker, its edits merged in; the stored text unchanged when there are none.
    ``local_matrix``: the Speaker in its X3D parent's frame (or the scene's)."""
    text = obj.get(SOUND_GRAPH_PROPERTY)
    if not isinstance(text, str):
        return None
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        if diagnostics is not None:
            diagnostics.append(f"Speaker {obj.name!r}: its stored sound graph is not well-formed XML; not written.")
        return None
    node = sg.parse_graph(root)
    want = sg.speaker_settings(node)
    try:      # compare with what Blender kept at import, not the file's value: a clamped volume is not an edit
        want.update(json.loads(obj.get(SOUND_APPLIED_PROPERTY) or "{}"))
    except (TypeError, ValueError):
        pass
    speaker = obj.data
    edits = {}
    for prop, field_name, _to_prop, to_field in _FIELDS:
        have = float(getattr(speaker, prop))
        if _differs(have, want[prop]):
            edits[field_name] = _num(to_field(have))
    if _differs(float(speaker.volume), want["volume"]):
        gain = node.num("gain")
        edits["intensity"] = _num(speaker.volume / gain) if gain else node.raw("intensity")
    from mathutils import Vector
    location = local_matrix.to_translation()
    pointing = (local_matrix.to_3x3() @ Vector((0.0, 0.0, -1.0)))
    stored_location = Vector(node.floats("location") or (0.0, 0.0, 0.0))
    stored_direction = Vector(node.floats("direction") or (0.0, 0.0, 1.0))
    if (location - stored_location).length > 1e-5 * max(1.0, location.length):
        edits["location"] = " ".join(_num(v) for v in location)
    if pointing.length > 1e-12 and stored_direction.length > 1e-12 and \
            (pointing.normalized() - stored_direction.normalized()).length > 1e-5:
        # the length of direction is not used by SpatialSound; keep the file's
        edits["direction"] = " ".join(_num(v) for v in pointing.normalized() * stored_direction.length)
    if not edits:
        return text
    for name, value in edits.items():
        root.set(name, value)
    return ET.tostring(root, encoding="unicode")
