# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""HAnim completion (node board batch 11): what HAnimSegment, HAnimSite, HAnimMotion and HAnimDisplacer become in
Blender, and the helpers the import and the export share.

* HAnimSegment: its Shapes are mesh objects bone-parented to the joint's bone; the segment's name, DEF and description
  are a JSON prop on the bone (SEGMENT_PROPERTY), its mass, centerOfMass and momentsOfInertia plain number props
  (x3d_hanim_segment_mass, ...).
* HAnimSite: an Empty bone-parented to its segment's bone; name (and description) in SITE_PROPERTY on the Empty.
* HAnimMotion: a Blender Action on the armature, one key per frame on each named joint's pose bone; the node's fields
  as written in MOTION_PROPERTY on the action. Rotation channels are read as radians (X3D's angle unit; neither the
  X3D 4.0 XSD nor X3DUOM 4.0 names a unit for them), applied in the order the channels list them (R = R1 R2 R3, as
  BVH does), position channels as the joint's translation.
* HAnimDisplacer of a joint: a shape key on each skin mesh (key co = basis + displacement, value = weight); its joint in
  DISPLACERS_PROPERTY on the mesh object. A displacer with no skin to key, or one of a segment, is kept as written on
  the bone (RAW_DISPLACERS_PROPERTY).

The props are JSON strings, so they survive any Blender version's ID-property rules.
"""

from __future__ import annotations

import json

SEGMENT_PROPERTY = "x3d_hanim_segment"
SITE_PROPERTY = "x3d_hanim_site"
MOTION_PROPERTY = "x3d_hanim_motion"
DISPLACERS_PROPERTY = "x3d_hanim_displacers"
RAW_DISPLACERS_PROPERTY = "x3d_hanim_raw_displacers"

SEGMENT_FIELDS = ("description",)
# the segment's numbers, each a plain prop on the bone (so the N panel's Custom Properties edits them):
# "x3d_hanim_segment_mass" and so on
SEGMENT_NUMBERS = {"mass": 1, "centerOfMass": 3, "momentsOfInertia": 9}
SEGMENT_NUMBER_PREFIX = "x3d_hanim_segment_"
SITE_FIELDS = ("description",)
DISPLACER_FIELDS = ("description",)
# HAnimMotion fields kept as written (values is kept apart: it is what the action holds)
MOTION_FIELDS = ("description", "channels", "channelsEnabled", "enabled", "endFrame", "frameDuration",
                 "frameIncrement", "frameIndex", "joints", "loa", "loop", "startFrame")

POSITION_CHANNELS = {"Xposition": 0, "Yposition": 1, "Zposition": 2}
ROTATION_CHANNELS = {"Xrotation": "X", "Yrotation": "Y", "Zrotation": "Z"}


def load(value, default=None):
    """A JSON prop as Python data (``default`` when absent or unreadable)."""
    if value is None:
        return default
    try:
        return json.loads(str(value))
    except ValueError:
        return default


def dump(value) -> str:
    return json.dumps(value, sort_keys=True)


def parse_channels(channels: str, joints: str):
    """[(joint name, [channel names])] from HAnimMotion ``channels`` ("6 Xposition ... 3 Xrotation ...") and ``joints``
    (joint names, one per channel group). A group without a joint name gets None."""
    tokens = (channels or "").split()
    names = (joints or "").split()
    groups = []
    index = 0
    while index < len(tokens):
        try:
            count = int(tokens[index])
        except ValueError:
            break
        group = tokens[index + 1:index + 1 + count]
        index += 1 + count
        groups.append((names[len(groups)] if len(groups) < len(names) else None, group))
    return groups


def euler_order(rotation_names):
    """The mathutils Euler order for rotation channels listed as ``rotation_names`` (R = R1 R2 R3 is the order
    R3, R2, R1 applied first to last, which mathutils names in that application order), or None when the channels
    are not three distinct axes."""
    axes = [ROTATION_CHANNELS[name] for name in rotation_names if name in ROTATION_CHANNELS]
    if len(axes) != 3 or len(set(axes)) != 3:
        return None
    return "".join(reversed(axes))


def floats(text):
    out = []
    for token in (text or "").replace(",", " ").split():
        try:
            out.append(float(token))
        except ValueError:
            pass
    return out
