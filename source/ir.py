# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Intermediate representation (IR) shared by the X3D 4.0 export and import paths.

This module must stay free of ``bpy`` imports so that it can be unit-tested
outside Blender. Extractors turn Blender data into these dataclasses, emitters
turn them into X3D, parsers turn X3D into them, and populators turn them back
into Blender data.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class IRMetadata:
    creator: str | None = None
    title: str | None = None
    description: str | None = None
    keywords: str | None = None
    reference: str | None = None
    license: str | None = None
    filename: str | None = None


@dataclass
class IRTransform:
    translation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_axis_angle: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)


@dataclass
class IRTextureTransform:
    translation: tuple[float, float] = (0.0, 0.0)
    rotation: float = 0.0
    scale: tuple[float, float] = (1.0, 1.0)
    texcoord_set: int = 0


@dataclass
class IRTextureRef:
    image_name: str | None = None
    filepath: str | None = None
    source: str = "FILE"
    colorspace: str | None = None
    extension: str | None = None
    transform: IRTextureTransform | None = None
    usage: str | None = None
    # Final URL written into the X3D file. Filled in by the export pipeline
    # after path-mode resolution (COPY / RELATIVE / STRIP); when None the
    # emitter falls back to ``filepath``.
    url: str | None = None


@dataclass
class IRMeshGeometry:
    """One IndexedFaceSet worth of mesh data.

    Vertices are already split so that ``coord``, ``normal``, ``tex_coord``
    and ``color`` are parallel arrays indexed by ``coord_index`` (X3D
    ``normalPerVertex`` / ``colorPerVertex`` true with shared indices).
    A Blender mesh with several material slots becomes several geometries,
    one per slot, with ``material_slot`` recording which.
    """

    name: str
    coord: list[tuple[float, float, float]] = field(default_factory=list)
    coord_index: list[int] = field(default_factory=list)
    solid: bool = True
    crease_angle: float | None = None
    normal: list[tuple[float, float, float]] = field(default_factory=list)
    tex_coord: list[tuple[float, float]] = field(default_factory=list)
    color: list[tuple[float, float, float, float]] = field(default_factory=list)
    material_slot: int = 0
    source_mesh: str | None = None
    # Original Blender vertex index for every split vertex (skinning needs it).
    orig_vertex_index: list[int] = field(default_factory=list)
    # When set, ``coord`` is empty and ``coord_index`` points into the named
    # humanoid's shared skinCoord Coordinate node.
    skin_coord_def: str | None = None


@dataclass
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

    def texture_refs(self):
        """Yield (containerField, IRTextureRef) pairs for every assigned texture."""
        for container_field, texture_ref in (
            ("baseTexture", self.base_color_texture),
            ("metallicRoughnessTexture", self.metallic_roughness_texture),
            ("normalTexture", self.normal_texture),
            ("emissiveTexture", self.emissive_texture),
            ("occlusionTexture", self.occlusion_texture),
        ):
            if texture_ref is not None:
                yield container_field, texture_ref


@dataclass
class IRInlineAsset:
    url: str
    asset_type: str = "x3d"
    transform: IRTransform = field(default_factory=IRTransform)
    import_policy: str = "native"


@dataclass
class IRGaussianSplats:
    """One X3D 4.1 GaussianSplats node worth of data (or a PointSet fallback in 4.0).

    ``orientations`` are unit quaternions as (x, y, z, w). ``scales`` are
    linear (not log) per-axis extents, ``opacities`` are 0..1 (not logits).
    ``sh`` maps (degree, coefficient) to a per-splat list of RGB coefficients;
    (0, 0) is the DC term the reconstructed colour comes from.
    """

    name: str
    positions: list[tuple[float, float, float]] = field(default_factory=list)
    scales: list[tuple[float, float, float]] = field(default_factory=list)
    orientations: list[tuple[float, float, float, float]] = field(default_factory=list)
    opacities: list[float] = field(default_factory=list)
    sh: dict[tuple[int, int], list[tuple[float, float, float]]] = field(default_factory=dict)
    color_space: str = "SRGB_REC709_DISPLAY"

    def sh_degree(self) -> int:
        return max((degree for degree, _coef in self.sh), default=-1)

    def __len__(self) -> int:
        return len(self.positions)


@dataclass
class IRViewpoint:
    description: str | None = None
    transform: IRTransform = field(default_factory=IRTransform)
    field_of_view: float | None = None
    name: str | None = None


@dataclass
class IRLight:
    """A light written inside its owning Transform (location 0, direction -Z)."""

    name: str
    light_type: str = "POINT"  # POINT, SPOT, DIRECTIONAL
    color: tuple[float, float, float] = (1.0, 1.0, 1.0)
    intensity: float = 1.0
    ambient_intensity: float = 0.0
    radius: float | None = None
    beam_width: float | None = None
    cut_off_angle: float | None = None
    location: tuple[float, float, float] = (0.0, 0.0, 0.0)
    direction: tuple[float, float, float] = (0.0, 0.0, -1.0)


@dataclass
class IRAnimation:
    """Sampled transform animation for one instance.

    ``keys`` are fractions of the cycle in [0, 1]; the value lists are
    parallel to ``keys``. Empty value lists mean that channel is static.
    """

    target: str
    target_kind: str = "transform"  # "transform" (OB_ DEF) or "joint" (HAnimJoint DEF)
    keys: list[float] = field(default_factory=list)
    translations: list[tuple[float, float, float]] = field(default_factory=list)
    rotations: list[tuple[float, float, float, float]] = field(default_factory=list)
    scales: list[tuple[float, float, float]] = field(default_factory=list)


@dataclass
class IRShape:
    """One Shape inside an instance: a geometry paired with a material."""

    geometry_name: str | None = None
    material_name: str | None = None
    geometry_hint: str = "Sphere"


@dataclass
class IRInstance:
    source_key: str
    object_name: str
    object_type: str = "EMPTY"
    geometry_hint: str = "Sphere"
    geometry_name: str | None = None
    material_name: str | None = None
    transform: IRTransform = field(default_factory=IRTransform)
    shapes: list[IRShape] = field(default_factory=list)
    children: list["IRInstance"] = field(default_factory=list)
    light: IRLight | None = None
    viewpoint: IRViewpoint | None = None
    humanoid_name: str | None = None
    # Set when the instance stands for an external asset referenced by Inline.
    inline: IRInlineAsset | None = None
    # Name of an IRGaussianSplats in IRScene.splats carried by this instance.
    splats_name: str | None = None

    def iter_shapes(self):
        """Yield the shapes of this instance.

        Instances built before multi-material support carry a single
        ``geometry_name`` / ``material_name`` pair; those are still honoured.
        """
        if self.shapes:
            yield from self.shapes
        elif self.inline is not None or self.splats_name:
            return
        elif self.geometry_name or self.material_name or self.object_type == "MESH":
            yield IRShape(
                geometry_name=self.geometry_name,
                material_name=self.material_name,
                geometry_hint=self.geometry_hint,
            )


@dataclass
class IRJoint:
    """One HAnimJoint: a Blender bone. ``center`` is the bone head in humanoid space."""

    name: str
    center: tuple[float, float, float] = (0.0, 0.0, 0.0)
    children: list["IRJoint"] = field(default_factory=list)
    skin_coord_index: list[int] = field(default_factory=list)
    skin_coord_weight: list[float] = field(default_factory=list)

    def iter_joints(self):
        yield self
        for child in self.children:
            yield from child.iter_joints()


@dataclass
class IRHumanoid:
    """An HAnimHumanoid built from one armature and the meshes it deforms."""

    name: str
    transform: IRTransform = field(default_factory=IRTransform)
    root_joints: list[IRJoint] = field(default_factory=list)
    skin_coord: list[tuple[float, float, float]] = field(default_factory=list)
    skin_shapes: list[IRShape] = field(default_factory=list)

    def iter_joints(self):
        for root in self.root_joints:
            yield from root.iter_joints()


@dataclass
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
    animations: list[IRAnimation] = field(default_factory=list)
    humanoids: list[IRHumanoid] = field(default_factory=list)
    splats: list[IRGaussianSplats] = field(default_factory=list)
    cycle_interval: float | None = None
    background_color: tuple[float, float, float] | None = None

    def iter_instances(self):
        """Depth-first walk over every instance, nested children included."""
        stack = list(reversed(self.instances))
        while stack:
            instance = stack.pop()
            yield instance
            stack.extend(reversed(instance.children))

    def splats_by_name(self) -> dict[str, IRGaussianSplats]:
        return {splats.name: splats for splats in self.splats}

    def has_lights(self) -> bool:
        return any(instance.light is not None for instance in self.iter_instances())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def geometry_by_name(self) -> dict[str, IRMeshGeometry]:
        return {geometry.name: geometry for geometry in self.geometries}

    def material_by_name(self) -> dict[str, IRPBRMaterial]:
        return {material.name: material for material in self.materials}

    def iter_texture_refs(self):
        for material in self.materials:
            for _container_field, texture_ref in material.texture_refs():
                yield texture_ref
