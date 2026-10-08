# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class X3DFieldSpec:
    name: str
    field_type: str
    default: object = None


@dataclass(frozen=True, slots=True)
class X3DNodeSpec:
    name: str
    version: str
    fields: tuple[X3DFieldSpec, ...]
    import_supported: bool = True
    export_supported: bool = True


REGISTRY: dict[str, X3DNodeSpec] = {
    "X3D": X3DNodeSpec(
        name="X3D",
        version="4.0",
        fields=(
            X3DFieldSpec("version", "SFString", "4.0"),
            X3DFieldSpec("profile", "SFString", "Immersive"),
        ),
    ),
    "Appearance": X3DNodeSpec(
        name="Appearance",
        version="4.0",
        fields=(
            X3DFieldSpec("alphaMode", "SFString", "OPAQUE"),
            X3DFieldSpec("material", "SFNode", None),
        ),
    ),
    "PhysicalMaterial": X3DNodeSpec(
        name="PhysicalMaterial",
        version="4.0",
        fields=(
            X3DFieldSpec("baseColor", "SFColor", (0.8, 0.8, 0.8)),
            X3DFieldSpec("metallic", "SFFloat", 0.0),
            X3DFieldSpec("roughness", "SFFloat", 0.5),
            X3DFieldSpec("emissiveColor", "SFColor", (0.0, 0.0, 0.0)),
            X3DFieldSpec("transparency", "SFFloat", 0.0),
            X3DFieldSpec("baseTexture", "SFNode", None),
            X3DFieldSpec("metallicRoughnessTexture", "SFNode", None),
            X3DFieldSpec("normalTexture", "SFNode", None),
            X3DFieldSpec("occlusionTexture", "SFNode", None),
            X3DFieldSpec("emissiveTexture", "SFNode", None),
        ),
    ),
    "UnlitMaterial": X3DNodeSpec(
        name="UnlitMaterial",
        version="4.0",
        fields=(
            X3DFieldSpec("emissiveColor", "SFColor", (1.0, 1.0, 1.0)),
            X3DFieldSpec("emissiveTexture", "SFNode", None),
            X3DFieldSpec("transparency", "SFFloat", 0.0),
        ),
    ),
    "TextureTransform": X3DNodeSpec(
        name="TextureTransform",
        version="3.0",
        fields=(
            X3DFieldSpec("translation", "SFVec2f", (0.0, 0.0)),
            X3DFieldSpec("rotation", "SFFloat", 0.0),
            X3DFieldSpec("scale", "SFVec2f", (1.0, 1.0)),
        ),
    ),
    "TextureTransformMatrix3D": X3DNodeSpec(
        name="TextureTransformMatrix3D",
        version="4.0",
        fields=(
            X3DFieldSpec("matrix", "SFMatrix4f", None),
            X3DFieldSpec("mapping", "SFString", ""),
        ),
    ),
    "Inline": X3DNodeSpec(
        name="Inline",
        version="3.0",
        fields=(
            X3DFieldSpec("url", "MFString", ()),
        ),
    ),
    "HAnimHumanoid": X3DNodeSpec(
        name="HAnimHumanoid",
        version="4.0",
        fields=(
            X3DFieldSpec("name", "SFString", ""),
            X3DFieldSpec("joints", "MFNode", ()),
            X3DFieldSpec("segments", "MFNode", ()),
            X3DFieldSpec("sites", "MFNode", ()),
        ),
    ),
}


def get_node_spec(name: str) -> X3DNodeSpec | None:
    return REGISTRY.get(name)

