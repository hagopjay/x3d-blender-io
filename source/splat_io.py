# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Readers and writers for Gaussian-splat point files, free of ``bpy``.

Supported: the 3D Gaussian Splatting PLY layout (INRIA reference
implementation: x y z, f_dc_0..2, f_rest_0..44, opacity, scale_0..2,
rot_0..3) and the compact ``.splat`` layout (32 bytes per splat: position,
scale, RGBA bytes, quaternion bytes). Both decode into ``IRGaussianSplats``
with linear scales, 0..1 opacities and (x, y, z, w) unit quaternions, which
is also what the X3D 4.1 GaussianSplats node carries.
"""

from __future__ import annotations

import math
import os
import struct

try:
    from .ir import IRGaussianSplats
except ImportError:  # pragma: no cover - standalone test fallback
    from ir import IRGaussianSplats


SH_C0 = 0.28209479177387814

# (degree, coefficient) pairs in the order the PLY f_rest_* columns are laid
# out: all red coefficients, then green, then blue, for degrees 1..3.
SH_REST_SLOTS = [(degree, coef) for degree in (1, 2, 3) for coef in range(2 * degree + 1)]


def sh0_to_rgb(coefficient) -> tuple[float, float, float]:
    """Reconstructed base colour (0..1, display space) from the SH DC term."""
    return tuple(max(0.0, min(1.0, 0.5 + SH_C0 * float(channel))) for channel in coefficient[:3])


def rgb_to_sh0(rgb) -> tuple[float, float, float]:
    return tuple((float(channel) - 0.5) / SH_C0 for channel in rgb[:3])


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


def _logit(value: float) -> float:
    value = min(max(value, 1e-6), 1.0 - 1e-6)
    return math.log(value / (1.0 - value))


def _normalized(quaternion):
    length = math.sqrt(sum(component * component for component in quaternion))
    if length < 1e-12:
        return (0.0, 0.0, 0.0, 1.0)
    return tuple(component / length for component in quaternion)


def read_splats(filepath: str, *, name: str | None = None) -> IRGaussianSplats:
    """Read a .ply or .splat file into IRGaussianSplats."""
    lower = filepath.lower()
    name = name or os.path.splitext(os.path.basename(filepath))[0]
    if lower.endswith(".ply"):
        return read_ply(filepath, name=name)
    if lower.endswith(".splat"):
        return read_antimatter_splat(filepath, name=name)
    raise ValueError(f"Unsupported splat file type: {filepath}")


# -- PLY --------------------------------------------------------------------

_PLY_TYPES = {
    "char": "b", "int8": "b", "uchar": "B", "uint8": "B",
    "short": "h", "int16": "h", "ushort": "H", "uint16": "H",
    "int": "i", "int32": "i", "uint": "I", "uint32": "I",
    "float": "f", "float32": "f", "double": "d", "float64": "d",
}


def _parse_ply_header(handle):
    magic = handle.readline().strip()
    if magic != b"ply":
        raise ValueError("Not a PLY file")
    fmt = None
    elements = []  # (name, count, [(prop_name, struct_code)])
    while True:
        line = handle.readline()
        if not line:
            raise ValueError("Unterminated PLY header")
        parts = line.decode("ascii", "replace").split()
        if not parts:
            continue
        if parts[0] == "format":
            fmt = parts[1]
        elif parts[0] == "element":
            elements.append((parts[1], int(parts[2]), []))
        elif parts[0] == "property":
            if parts[1] == "list":
                raise ValueError("PLY list properties are not supported for splats")
            elements[-1][2].append((parts[2], _PLY_TYPES[parts[1]]))
        elif parts[0] == "end_header":
            break
    return fmt, elements


def read_ply(filepath: str, *, name: str | None = None) -> IRGaussianSplats:
    name = name or os.path.splitext(os.path.basename(filepath))[0]
    with open(filepath, "rb") as handle:
        fmt, elements = _parse_ply_header(handle)
        vertex = next((element for element in elements if element[0] == "vertex"), None)
        if vertex is None:
            raise ValueError("PLY file has no vertex element")
        _name, count, props = vertex
        names = [prop_name for prop_name, _code in props]
        if fmt == "ascii":
            rows = []
            for _ in range(count):
                values = handle.readline().split()
                rows.append([float(value) for value in values[:len(names)]])
        else:
            endian = "<" if fmt == "binary_little_endian" else ">"
            record = struct.Struct(endian + "".join(code for _prop_name, code in props))
            data = handle.read(record.size * count)
            rows = [list(values) for values in record.iter_unpack(data)]
    return _rows_to_splats(name, names, rows)


def _rows_to_splats(name, names, rows) -> IRGaussianSplats:
    column = {prop_name: index for index, prop_name in enumerate(names)}

    def get(row, key, default=None):
        index = column.get(key)
        return row[index] if index is not None else default

    splats = IRGaussianSplats(name=name)
    has_dc = "f_dc_0" in column
    has_rgb = "red" in column
    rest_count = sum(1 for prop_name in names if prop_name.startswith("f_rest_"))
    rest_per_channel = rest_count // 3
    sh_slots = SH_REST_SLOTS[:rest_per_channel]
    for row in rows:
        splats.positions.append((float(get(row, "x", 0.0)), float(get(row, "y", 0.0)), float(get(row, "z", 0.0))))
        if "scale_0" in column:
            splats.scales.append(tuple(math.exp(float(get(row, f"scale_{axis}", 0.0))) for axis in range(3)))
        else:
            splats.scales.append((0.01, 0.01, 0.01))
        if "rot_0" in column:
            w, x, y, z = (float(get(row, f"rot_{index}", 0.0)) for index in range(4))
            splats.orientations.append(_normalized((x, y, z, w)))
        else:
            splats.orientations.append((0.0, 0.0, 0.0, 1.0))
        if "opacity" in column:
            splats.opacities.append(_sigmoid(float(get(row, "opacity", 0.0))))
        elif "alpha" in column:
            splats.opacities.append(float(get(row, "alpha", 255.0)) / 255.0)
        else:
            splats.opacities.append(1.0)
        if has_dc:
            dc = tuple(float(get(row, f"f_dc_{channel}", 0.0)) for channel in range(3))
        elif has_rgb:
            dc = rgb_to_sh0(tuple(float(get(row, key, 0.0)) / 255.0 for key in ("red", "green", "blue")))
        else:
            dc = (0.0, 0.0, 0.0)
        splats.sh.setdefault((0, 0), []).append(dc)
        for slot_index, slot in enumerate(sh_slots):
            coefficient = tuple(
                float(get(row, f"f_rest_{channel * rest_per_channel + slot_index}", 0.0)) for channel in range(3)
            )
            splats.sh.setdefault(slot, []).append(coefficient)
    return splats


def write_ply(filepath: str, splats: IRGaussianSplats) -> None:
    """Write IRGaussianSplats in the reference 3DGS binary PLY layout."""
    degree = splats.sh_degree()
    slots = [slot for slot in SH_REST_SLOTS if slot[0] <= degree]
    rest_per_channel = len(slots)
    names = ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2"]
    names += [f"f_rest_{index}" for index in range(3 * rest_per_channel)]
    names += ["opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    header = ["ply", "format binary_little_endian 1.0", f"element vertex {len(splats)}"]
    header += [f"property float {prop_name}" for prop_name in names]
    header.append("end_header")
    record = struct.Struct("<" + "f" * len(names))
    dc = splats.sh.get((0, 0), [])
    with open(filepath, "wb") as handle:
        handle.write(("\n".join(header) + "\n").encode("ascii"))
        for index in range(len(splats)):
            x, y, z = splats.positions[index]
            sx, sy, sz = splats.scales[index] if index < len(splats.scales) else (0.01, 0.01, 0.01)
            qx, qy, qz, qw = splats.orientations[index] if index < len(splats.orientations) else (0.0, 0.0, 0.0, 1.0)
            opacity = splats.opacities[index] if index < len(splats.opacities) else 1.0
            values = [x, y, z, 0.0, 0.0, 0.0]
            values += list(dc[index]) if index < len(dc) else [0.0, 0.0, 0.0]
            for channel in range(3):
                for slot in slots:
                    coefficients = splats.sh.get(slot, [])
                    values.append(coefficients[index][channel] if index < len(coefficients) else 0.0)
            values += [_logit(opacity), math.log(max(sx, 1e-9)), math.log(max(sy, 1e-9)), math.log(max(sz, 1e-9))]
            values += [qw, qx, qy, qz]
            handle.write(record.pack(*values))


# -- .splat (antimatter15 layout) ------------------------------------------

_SPLAT_RECORD = struct.Struct("<3f3f4B4B")


def read_antimatter_splat(filepath: str, *, name: str | None = None) -> IRGaussianSplats:
    name = name or os.path.splitext(os.path.basename(filepath))[0]
    splats = IRGaussianSplats(name=name)
    with open(filepath, "rb") as handle:
        data = handle.read()
    for values in _SPLAT_RECORD.iter_unpack(data[: len(data) - len(data) % _SPLAT_RECORD.size]):
        x, y, z, sx, sy, sz, r, g, b, a, q0, q1, q2, q3 = values
        splats.positions.append((x, y, z))
        splats.scales.append((sx, sy, sz))
        # .splat stores (w, x, y, z) as bytes: q = (byte - 128) / 128
        w, qx, qy, qz = ((component - 128) / 128.0 for component in (q0, q1, q2, q3))
        splats.orientations.append(_normalized((qx, qy, qz, w)))
        splats.opacities.append(a / 255.0)
        splats.sh.setdefault((0, 0), []).append(rgb_to_sh0((r / 255.0, g / 255.0, b / 255.0)))
    return splats


def write_antimatter_splat(filepath: str, splats: IRGaussianSplats) -> None:
    dc = splats.sh.get((0, 0), [])

    def byte(value: float) -> int:
        return max(0, min(255, int(round(value))))

    with open(filepath, "wb") as handle:
        for index in range(len(splats)):
            r, g, b = sh0_to_rgb(dc[index]) if index < len(dc) else (0.5, 0.5, 0.5)
            qx, qy, qz, qw = splats.orientations[index] if index < len(splats.orientations) else (0.0, 0.0, 0.0, 1.0)
            opacity = splats.opacities[index] if index < len(splats.opacities) else 1.0
            handle.write(_SPLAT_RECORD.pack(
                *splats.positions[index],
                *(splats.scales[index] if index < len(splats.scales) else (0.01, 0.01, 0.01)),
                byte(r * 255), byte(g * 255), byte(b * 255), byte(opacity * 255),
                byte(qw * 128 + 128), byte(qx * 128 + 128), byte(qy * 128 + 128), byte(qz * 128 + 128),
            ))
