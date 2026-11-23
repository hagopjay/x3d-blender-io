# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Texture coordinates the importer made up, and the export that leaves them out again.

An IndexedFaceSet without a TextureCoordinate has default texture coordinates (ISO/IEC 19775-1, 13.3.6: the bounding
box's longest side is S, the next is T). The importer writes them into a UV layer so a texture lands where a browser
draws it. Before 2.7.3 the export then wrote that layer back as a TextureCoordinate, so a file that had none gained
one after a round trip (20 of 276 scene-chaos cases drifted this way, chaos round 2.7.3).

The import marks the layer with a fingerprint of its values; the export leaves the layer out while the fingerprint
still matches, which is exactly what the file said (a browser makes the same default). A UV edit, a modifier that
changes the corners, or a joined mesh changes the fingerprint, and the layer is exported as before.
"""

from __future__ import annotations

import hashlib
from array import array

DEFAULT_UV_PROPERTY = "x3d_default_texcoord"


def fingerprint(layer) -> str:
    data = layer.data
    values = array("f", bytes(8 * len(data)))
    data.foreach_get("uv", values)
    return hashlib.sha1(values.tobytes()).hexdigest()[:20]


def mark(mesh, layer) -> None:
    """Record that ``layer`` holds the default texture coordinates the import computed."""
    if layer is not None:
        mesh[DEFAULT_UV_PROPERTY] = f"{layer.name}:{len(layer.data)}:{fingerprint(layer)}"


def is_unchanged_default(mesh, layer) -> bool:
    """True when ``layer`` is still the import's default texture coordinates, untouched."""
    get = getattr(mesh, "get", None)
    stored = get(DEFAULT_UV_PROPERTY) if get else None
    if layer is None or not isinstance(stored, str):
        return False
    try:
        return stored == f"{layer.name}:{len(layer.data)}:{fingerprint(layer)}"
    except (AttributeError, TypeError, ValueError):
        return False
