# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The KHR_gaussian_splatting glb writer (no bpy)."""

import json
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "source"))

from ir import IRGaussianSplats  # noqa: E402
from splat_gltf import splat_glb_bytes  # noqa: E402


def _splats(count=4):
    splats = IRGaussianSplats(name="S")
    for i in range(count):
        splats.positions.append((i, -2 * i, 0.5))
        splats.scales.append((0.1, 0.2, 0.3))
        splats.orientations.append((0.0, 0.0, 0.0, 1.0))
        splats.opacities.append(0.25 * (i + 1))
        splats.sh.setdefault((0, 0), []).append((0.1 * i, 0.2, -0.3))
    return splats


def _parse(data):
    magic, version, length = struct.unpack_from("<4sII", data, 0)
    assert (magic, version, length) == (b"glTF", 2, len(data))
    json_len, json_tag = struct.unpack_from("<I4s", data, 12)
    assert json_tag == b"JSON"
    document = json.loads(data[20:20 + json_len])
    bin_len, bin_tag = struct.unpack_from("<I4s", data, 20 + json_len)
    assert bin_tag == b"BIN\0"
    return document, data[28 + json_len:28 + json_len + bin_len]


class SplatGlbTests(unittest.TestCase):
    def test_container_and_extension(self):
        document, blob = _parse(splat_glb_bytes(_splats()))
        self.assertEqual(document["extensionsUsed"], ["KHR_gaussian_splatting"])
        primitive = document["meshes"][0]["primitives"][0]
        self.assertEqual(primitive["mode"], 0)
        self.assertEqual(primitive["extensions"]["KHR_gaussian_splatting"],
                         {"kernel": "ellipse", "colorSpace": "srgb_rec709_display"})
        self.assertEqual(sorted(primitive["attributes"]), sorted([
            "POSITION", "KHR_gaussian_splatting:ROTATION", "KHR_gaussian_splatting:SCALE",
            "KHR_gaussian_splatting:OPACITY", "KHR_gaussian_splatting:SH_DEGREE_0_COEF_0"]))
        self.assertEqual(document["buffers"][0]["byteLength"], len(blob))
        self.assertEqual(len(blob) % 4, 0)

    def test_accessor_data_round_trips(self):
        document, blob = _parse(splat_glb_bytes(_splats()))
        primitive = document["meshes"][0]["primitives"][0]

        def read(name, width):
            accessor = document["accessors"][primitive["attributes"][name]]
            view = document["bufferViews"][accessor["bufferView"]]
            return struct.unpack_from(f"<{accessor['count'] * width}f", blob, view["byteOffset"]), accessor

        positions, accessor = read("POSITION", 3)
        self.assertEqual(positions[3:6], (1.0, -2.0, 0.5))
        self.assertEqual(accessor["min"], [0.0, -6.0, 0.5])
        self.assertEqual(accessor["max"], [3.0, 0.0, 0.5])
        self.assertEqual(read("KHR_gaussian_splatting:OPACITY", 1)[0], (0.25, 0.5, 0.75, 1.0))
        self.assertEqual(read("KHR_gaussian_splatting:ROTATION", 4)[0][:4], (0.0, 0.0, 0.0, 1.0))
        self.assertEqual(read("KHR_gaussian_splatting:SCALE", 3)[0][:3], (0.1, 0.2, 0.3) and struct.unpack("<3f", struct.pack("<3f", 0.1, 0.2, 0.3)))

    def test_needs_colour_and_splats(self):
        with self.assertRaises(ValueError):
            splat_glb_bytes(IRGaussianSplats(name="empty"))
        bare = _splats()
        bare.sh = {}
        with self.assertRaises(ValueError):
            splat_glb_bytes(bare)


if __name__ == "__main__":
    unittest.main()
