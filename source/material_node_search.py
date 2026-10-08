# SPDX-FileCopyrightText: 2024 Vincent Marchetti, Bujus_Krachus
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Compatibility wrappers for material analysis helpers.

The legacy exporter still imports these symbols from `material_node_search`.
Modern implementations should live in `material.py`.
"""

from .material import (
    analyze_material,
    get_diffuse_color,
    get_emissive_color,
    get_movie_texture_properties,
    get_vector_mapping_properties,
    image_texture_in_material,
)

imageTexture_in_material = image_texture_in_material

__all__ = [
    "analyze_material",
    "get_diffuse_color",
    "get_emissive_color",
    "get_movie_texture_properties",
    "get_vector_mapping_properties",
    "imageTexture_in_material",
    "image_texture_in_material",
]
