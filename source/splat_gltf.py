# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Write Gaussian splats as a glb with the ratified ``KHR_gaussian_splatting`` extension (no ``bpy``).

The extension (Khronos glTF registry, listed under Ratified; checked 18 Nov 2026): one POINTS primitive whose
``POSITION`` holds the centres and whose ``KHR_gaussian_splatting:ROTATION`` (unit quaternion x y z w), ``:SCALE`` (linear),
``:OPACITY`` (linear 0..1) and ``SH_DEGREE_0_COEF_0`` (the DC spherical-harmonic term) describe each splat. This writer
takes data already in glTF's Y-up frame (``extract.splats_to_gltf_frame``) and writes degree 0 only: higher degrees
depend on the view direction and would have to be rotated with the data.
"""

from __future__ import annotations

import json
import struct

COLOR_SPACES = {"SRGB_REC709_DISPLAY": "srgb_rec709_display", "LIN_REC709_DISPLAY": "lin_rec709_display"}


def splat_glb_bytes(splats) -> bytes:
    count = len(splats.positions)
    if count == 0:
        raise ValueError("no splats to write")
    dc = splats.sh.get((0, 0))
    if not dc or len(dc) != count:
        raise ValueError("splats have no degree-0 colour (sh[(0, 0)])")
    orientations = splats.orientations or [(0.0, 0.0, 0.0, 1.0)] * count
    scales = splats.scales or [(0.01, 0.01, 0.01)] * count
    opacities = splats.opacities or [1.0] * count
    columns = [
        ("POSITION", "VEC3", 3, [p[:3] for p in splats.positions]),
        ("KHR_gaussian_splatting:ROTATION", "VEC4", 4, [q[:4] for q in orientations]),
        ("KHR_gaussian_splatting:SCALE", "VEC3", 3, [s[:3] for s in scales]),
        ("KHR_gaussian_splatting:OPACITY", "SCALAR", 1, [(o,) for o in opacities]),
        ("SH_DEGREE_0_COEF_0", "VEC3", 3, [c[:3] for c in dc]),
    ]
    blob, views, accessors, attributes = bytearray(), [], [], {}
    for index, (name, kind, width, rows) in enumerate(columns):
        flat = [float(value) for row in rows for value in row]
        offset = len(blob)
        blob += struct.pack(f"<{len(flat)}f", *flat)
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(flat) * 4})
        accessor = {"bufferView": index, "componentType": 5126, "count": count, "type": kind}
        if name == "POSITION":
            accessor["min"] = [min(row[axis] for row in rows) for axis in range(3)]
            accessor["max"] = [max(row[axis] for row in rows) for axis in range(3)]
        accessors.append(accessor)
        attributes[name] = index
    document = {
        "asset": {"version": "2.0", "generator": "X3D Blender I/O"},
        "extensionsUsed": ["KHR_gaussian_splatting"],
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": splats.name}],
        "meshes": [{"name": splats.name, "primitives": [{
            "mode": 0, "attributes": attributes,
            "extensions": {"KHR_gaussian_splatting": {
                "kernel": "ellipse", "colorSpace": COLOR_SPACES.get(splats.color_space, "srgb_rec709_display")}}}]}],
        "buffers": [{"byteLength": len(blob)}], "bufferViews": views, "accessors": accessors,
    }
    text = json.dumps(document, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    blob += b"\0" * (-len(blob) % 4)
    document["buffers"][0]["byteLength"] = len(blob)
    text = json.dumps(document, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    total = 12 + 8 + len(text) + 8 + len(blob)
    return (struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(text), b"JSON") + text
            + struct.pack("<I4s", len(blob), b"BIN\0") + bytes(blob))


def write_splat_glb(path, splats) -> int:
    data = splat_glb_bytes(splats)
    with open(path, "wb") as handle:
        handle.write(data)
    return len(data)
