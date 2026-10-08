# SPDX-FileCopyrightText: 2026 OpenAI
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class IRMetadata:
    creator: str | None = None
    title: str | None = None
    description: str | None = None
    keywords: str | None = None
    reference: str | None = None
    license: str | None = None


@dataclass(slots=True)
class IRTransform:
    translation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_axis_angle: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)


@dataclass(slots=True)
class IRTextureTransform:
    translation: tuple[float, float] = (0.0, 0.0)
    rotation: float = 0.0
    scale: tuple[float, float] = (1.0, 1.0)
    texcoord_set: int = 0


@dataclass(slots=True)
class IRTextureRef:
    image_name: str | None = None
    filepath: str | None = None
    source: str = "FILE"
    colorspace: str | None = None
    extension: str | None = None
    transform: IRTextureTransform | None = None
    usage: str | None = None


@dataclass(slots=True)
class IRMeshGeometry:
    name: str
    coord: list[tuple[float, float, float]] = field(default_factory=list)
    coord_index: list[int] = field(default_factory=list)
    solid: bool = True
    crease_angle: float | None = None


@dataclass(slots=True)
class IRPBRMaterial:
    name: str
    base_color: tuple[float, float, float, float] = (0.8, 0.8, 0.8, 1.0)
    emissive_color: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    metallic: float | None = None
    roughness: float | None = None
    normal_scale: float | None = None
    occlusion_strength: float | None = None
    alpha_mode: str = "OPAQUE"
    alpha_cutoff: float | None = None
    double_sided: bool | None = None
    unlit: bool = False
    base_color_texture: IRTextureRef | None = None
    metallic_roughness_texture: IRTextureRef | None = None
    normal_texture: IRTextureRef | None = None
    occlusion_texture: IRTextureRef | None = None
    emissive_texture: IRTextureRef | None = None


@dataclass(slots=True)
class IRInlineAsset:
    url: str
    asset_type: str = "x3d"
    transform: IRTransform = field(default_factory=IRTransform)
    import_policy: str = "native"


@dataclass(slots=True)
class IRViewpoint:
    description: str | None = None
    transform: IRTransform = field(default_factory=IRTransform)
    field_of_view: float | None = None


@dataclass(slots=True)
class IRInstance:
    source_key: str
    object_name: str
    object_type: str = "EMPTY"
    geometry_hint: str = "Sphere"
    geometry_name: str | None = None
    material_name: str | None = None
    transform: IRTransform = field(default_factory=IRTransform)


@dataclass(slots=True)
class IRScene:
    name: str
    source_version: str = "blender"
    source_path: str | None = None
    metadata: IRMetadata = field(default_factory=IRMetadata)
    object_names: list[str] = field(default_factory=list)
    geometries: list[IRMeshGeometry] = field(default_factory=list)
    materials: list[IRPBRMaterial] = field(default_factory=list)
    instances: list[IRInstance] = field(default_factory=list)
    inline_assets: list[IRInlineAsset] = field(default_factory=list)
    viewpoints: list[IRViewpoint] = field(default_factory=list)
    navigation_types: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
