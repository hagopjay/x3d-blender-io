# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Blender bone names -> H-Anim 2.0 standard joint names (no ``bpy``).

An HAnimJoint whose ``name`` is a standard joint name tells every H-Anim player what the joint is (retargeting, motion
libraries, LOA conformance); a custom name only makes it a joint of an unrecognised skeleton. This maps the bone naming
of the three rigs people actually bring (Mixamo ``mixamorig:LeftArm``, Rigify ``upper_arm.L``, and plain
``LeftUpperArm`` / ``l_upper_arm`` style) onto the joints they unambiguously mean, and takes an explicit override from
the bone's ``x3d_hanim_joint`` custom property. Anything it is not sure of is left alone: spine bones and the neck have no
one-to-one standard joint in these rigs, so they keep their own names unless the property says otherwise.
"""

from __future__ import annotations

import re

HANIM_JOINT_PROPERTY = "x3d_hanim_joint"

_FINGERS = ("thumb", "index", "middle", "ring", "pinky")


def _standard_names() -> frozenset[str]:
    names = {"humanoid_root", "sacroiliac", "skullbase", "temporomandibular"}
    for side in ("l", "r"):
        names |= {f"{side}_{part}" for part in (
            "hip", "knee", "ankle", "subtalar", "midtarsal", "metatarsal", "sternoclavicular", "acromioclavicular",
            "shoulder", "elbow", "wrist", "eyeball_joint")}
        names |= {f"{side}_{finger}{index}" for finger in _FINGERS for index in (1, 2, 3)}
    names |= {f"vc{index}" for index in range(1, 8)} | {f"vt{index}" for index in range(1, 13)}
    names |= {f"vl{index}" for index in range(1, 6)}
    return frozenset(names)


STANDARD_JOINTS = _standard_names()

# normalised bone stem (side and prefix removed) -> joint stem
_LIMB = {
    "shoulder": "acromioclavicular", "clavicle": "acromioclavicular",
    "arm": "shoulder", "upperarm": "shoulder", "upper_arm": "shoulder",
    "forearm": "elbow", "lowerarm": "elbow", "lower_arm": "elbow",
    "hand": "wrist",
    "upleg": "hip", "upperleg": "hip", "upper_leg": "hip", "thigh": "hip",
    "leg": "knee", "lowerleg": "knee", "lower_leg": "knee", "shin": "knee", "calf": "knee",
    "foot": "ankle",
    "toebase": "metatarsal", "toe": "metatarsal", "toes": "metatarsal",
}
_CENTRE = {"hips": "humanoid_root", "pelvis": "humanoid_root", "head": "skullbase"}
_PREFIX = re.compile(r"^(mixamorig\d*[:_]|armature[:_]|def[-_])", re.IGNORECASE)
_SIDE = re.compile(r"^(left|right|l|r)[_.\-]?(?=[a-z])|[_.\-]?(left|right|l|r)$", re.IGNORECASE)


def _split_side(name: str):
    """(side 'l'/'r' or None, stem) for ``LeftArm``, ``Arm.L``, ``arm_l``, ``l_arm``."""
    match = _SIDE.search(name)
    if match is None:
        return None, name
    side = (match.group(1) or match.group(2)).lower()[0]
    return side, (name[:match.start()] + name[match.end():])


def standard_joint_name(bone_name: str, override=None):
    """The H-Anim joint name for a bone, or None. ``override`` is the bone's ``x3d_hanim_joint`` value."""
    if override:
        return str(override).strip() or None
    name = _PREFIX.sub("", bone_name.strip())
    side, stem = _split_side(name)
    stem = re.sub(r"[_.\-\s]+$", "", stem).lower()
    key = stem.replace(" ", "")
    if side is None:
        return _CENTRE.get(key)
    finger = re.fullmatch(r"(?:hand)?(thumb|index|middle|ring|pinky)([1-3])", key)
    if finger:
        return f"{side}_{finger.group(1)}{finger.group(2)}"
    joint = _LIMB.get(key)
    return f"{side}_{joint}" if joint else None


def map_bones(bones):
    """``bones``: iterable of (bone name, override or None). Returns ({bone: joint name}, [problems]).

    The first bone to claim a standard name keeps it; a later claimant keeps its own name and is reported.
    """
    mapping, taken, problems = {}, {}, []
    for bone_name, override in bones:
        joint = standard_joint_name(bone_name, override)
        if joint is None:
            continue
        if joint in taken:
            problems.append(f"bones {taken[joint]!r} and {bone_name!r} both map to H-Anim joint {joint!r}; "
                            f"{bone_name!r} keeps its own name")
            continue
        if override and joint not in STANDARD_JOINTS:
            problems.append(f"bone {bone_name!r}: x3d_hanim_joint {joint!r} is not an H-Anim 2.0 joint name this "
                            "exporter knows; written as given")
        taken[joint] = bone_name
        mapping[bone_name] = joint
    return mapping, problems
