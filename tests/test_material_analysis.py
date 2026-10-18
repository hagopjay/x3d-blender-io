# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


SOURCE_DIR = Path(__file__).resolve().parents[1] / "source"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from material import (
    OCCLUSION_IMAGE_KEYWORDS,
    ShaderNodeTypes,
    _find_image_node_from_socket,
    _find_labeled_image_node,
    _resolve_float_socket,
    _resolve_rgba_socket,
)


class FakeLink:
    def __init__(self, from_node):
        self.from_node = from_node


class FakeSocket:
    def __init__(self, name=None, default_value=None):
        self.name = name
        self.default_value = default_value
        self.links = []


class FakeSocketMap(list):
    def __init__(self, sockets=None):
        super().__init__(sockets or [])
        self._by_name = {socket.name: socket for socket in self if socket.name is not None}

    def add(self, socket):
        self.append(socket)
        if socket.name is not None:
            self._by_name[socket.name] = socket
        return socket

    def get(self, key, default=None):
        if isinstance(key, str):
            return self._by_name.get(key, default)
        try:
            return self[key]
        except IndexError:
            return default


class FakeNode:
    def __init__(self, bl_idname, *, inputs=None, outputs=None, operation=None, name=""):
        self.bl_idname = bl_idname
        self.inputs = FakeSocketMap(inputs)
        self.outputs = FakeSocketMap(outputs)
        self.operation = operation
        self.name = name or bl_idname
        self.label = self.name
        self.image = None


def _link(socket, from_node):
    socket.links.append(FakeLink(from_node))
    return socket


class MaterialAnalysisHelperTests(unittest.TestCase):
    def test_resolves_math_driven_float_chain(self):
        target = FakeSocket("Metallic", 0.0)

        value_a = FakeNode(ShaderNodeTypes.VALUE, outputs=[FakeSocket(default_value=0.75)])
        value_b = FakeNode(ShaderNodeTypes.VALUE, outputs=[FakeSocket(default_value=0.8)])
        multiply = FakeNode(
            ShaderNodeTypes.MATH,
            inputs=[FakeSocket(default_value=0.0), FakeSocket(default_value=0.0)],
            operation="MULTIPLY",
        )
        _link(multiply.inputs[0], value_a)
        _link(multiply.inputs[1], value_b)

        bias = FakeNode(ShaderNodeTypes.VALUE, outputs=[FakeSocket(default_value=0.1)])
        add = FakeNode(
            ShaderNodeTypes.MATH,
            inputs=[FakeSocket(default_value=0.0), FakeSocket(default_value=0.0)],
            operation="ADD",
        )
        _link(add.inputs[0], multiply)
        _link(add.inputs[1], bias)
        _link(target, add)

        self.assertAlmostEqual(_resolve_float_socket(target, 0.0), 0.7)

    def test_resolves_mixrgb_color_chain(self):
        target = FakeSocket("Base Color", (0.0, 0.0, 0.0, 1.0))

        fac_value = FakeNode(ShaderNodeTypes.VALUE, outputs=[FakeSocket(default_value=0.25)])
        color1 = FakeNode(ShaderNodeTypes.RGB, outputs=[FakeSocket(default_value=(0.8, 0.2, 0.1, 1.0))])
        color2 = FakeNode(ShaderNodeTypes.RGB, outputs=[FakeSocket(default_value=(0.2, 0.6, 0.9, 1.0))])
        mix = FakeNode(
            ShaderNodeTypes.MIX_RGB,
            inputs=[
                FakeSocket("Fac", 0.5),
                FakeSocket("Color1", (0.0, 0.0, 0.0, 1.0)),
                FakeSocket("Color2", (0.0, 0.0, 0.0, 1.0)),
            ],
        )
        _link(mix.inputs.get("Fac"), fac_value)
        _link(mix.inputs.get("Color1"), color1)
        _link(mix.inputs.get("Color2"), color2)
        _link(target, mix)

        resolved = _resolve_rgba_socket(target, (0.0, 0.0, 0.0, 1.0))
        expected = (0.65, 0.3, 0.3, 1.0)
        for actual_channel, expected_channel in zip(resolved, expected):
            self.assertAlmostEqual(actual_channel, expected_channel)

    def test_finds_image_texture_through_reroute(self):
        target = FakeSocket("Normal", None)
        reroute = FakeNode(ShaderNodeTypes.REROUTE, inputs=[FakeSocket(default_value=None)])
        image = FakeNode(ShaderNodeTypes.IMAGE_TEXTURE)
        image.image = object()
        _link(reroute.inputs[0], image)
        _link(target, reroute)

        self.assertIs(_find_image_node_from_socket(target, usage="normal"), image)

    def test_resolves_map_range_then_clamp_chain(self):
        target = FakeSocket("Roughness", 0.0)

        value = FakeNode(ShaderNodeTypes.VALUE, outputs=[FakeSocket(default_value=0.85)])
        map_range = FakeNode(
            ShaderNodeTypes.MAP_RANGE,
            inputs=[
                FakeSocket("Value", 0.0),
                FakeSocket("From Min", 0.0),
                FakeSocket("From Max", 1.0),
                FakeSocket("To Min", 0.1),
                FakeSocket("To Max", 0.9),
            ],
        )
        map_range.clamp = True
        _link(map_range.inputs.get("Value"), value)

        clamp = FakeNode(
            ShaderNodeTypes.CLAMP,
            inputs=[
                FakeSocket("Value", 0.0),
                FakeSocket("Min", 0.2),
                FakeSocket("Max", 0.75),
            ],
        )
        _link(clamp.inputs.get("Value"), map_range)
        _link(target, clamp)

        self.assertAlmostEqual(_resolve_float_socket(target, 0.0), 0.75)


class OcclusionImageLookupTests(unittest.TestCase):
    """The exporter writes an image as occlusionTexture when its name mentions occlusion or AO."""

    @staticmethod
    def _is_occlusion(filepath, image_name=None, label=""):
        node = FakeNode(ShaderNodeTypes.IMAGE_TEXTURE, name="Image Texture")
        node.label = label
        file_name = filepath.replace("\\", "/").rsplit("/", 1)[-1]
        node.image = SimpleNamespace(name=image_name or file_name, filepath=filepath)
        material = SimpleNamespace(node_tree=SimpleNamespace(nodes=[node]))
        return _find_labeled_image_node(material, OCCLUSION_IMAGE_KEYWORDS) is node

    def test_folder_names_are_not_searched(self):
        # The swatch-book checker once became an occlusion map too, because its random temp folder
        # (/tmp/x3d_roundtrip_ plus 8 characters) happened to contain "ao".
        self.assertFalse(self._is_occlusion("/tmp/x3d_roundtrip_k2aoq1zz/swatch_checker.png", "swatch_checker"))
        self.assertFalse(self._is_occlusion("C:\\Users\\Joao\\textures\\brick.png"))
        self.assertFalse(self._is_occlusion("//ao/brick.png"))

    def test_ao_must_be_a_whole_word(self):
        for name in ("chaos.png", "cacao_bean.png", "Macao.jpg"):
            self.assertFalse(self._is_occlusion("//textures/" + name), name)
        for name in ("rock_AO.png", "RockAO.png", "AOMap.png", "ao.png", "brick-ao-2k.jpg"):
            self.assertTrue(self._is_occlusion("//textures/" + name), name)

    def test_occlusion_anywhere_in_a_name(self):
        self.assertTrue(self._is_occlusion("//textures/brickAmbientOcclusion.png"))
        self.assertTrue(self._is_occlusion("", image_name="T_Brick_occlusionmap"))
        # The importer labels the image node of an occlusionTexture "Occlusion".
        self.assertTrue(self._is_occlusion("//textures/brick_2.png", label="Occlusion"))


class OcclusionMapDetectionTests(unittest.TestCase):
    """_find_labeled_image_node must recognise real occlusion maps and ignore look-alike words and folder names."""

    KEYWORDS = ("occlusion", "ambient_occlusion", "ao")

    @staticmethod
    def _material(node_name="Image Texture", label="", image_name="", filepath=""):
        class Image:
            pass

        class Node:
            bl_idname = ShaderNodeTypes.IMAGE_TEXTURE

        class Tree:
            pass

        image = Image()
        image.name, image.filepath = image_name, filepath
        node = Node()
        node.name, node.label, node.image = node_name, label, image
        tree = Tree()
        tree.nodes = [node]
        material = Tree()
        material.node_tree = tree
        return material, node

    def _found(self, **kwargs):
        material, node = self._material(**kwargs)
        return _find_labeled_image_node(material, self.KEYWORDS) is node

    def test_kaolin_texture_in_kaolin_folder_is_not_an_occlusion_map(self):
        self.assertFalse(self._found(image_name="T_decoy_albedo.png",
                                     filepath="/home/Naomi/kaolin/T_decoy_albedo.png"))

    def test_look_alike_words_do_not_match_short_keyword(self):
        for name in ("kaolin.png", "Naomi_diffuse.png", "cacao.jpg", "Paolo.png", "gao_color.png", "Image Texture.001"):
            with self.subTest(name=name):
                self.assertFalse(self._found(image_name=name))

    def test_filepath_is_never_searched(self):
        self.assertFalse(self._found(image_name="wall.png", filepath="/textures/ao/wall.png"))
        self.assertFalse(self._found(image_name="wall.png", filepath="/textures/occlusion/wall.png"))

    def test_real_occlusion_maps_are_found(self):
        cases = [
            dict(image_name="wall_AO.png"), dict(image_name="AO.001"), dict(image_name="T_occlusion.png"),
            dict(image_name="wall-ao-2k.jpg"), dict(image_name="WallAO.png"), dict(image_name="AOMap.png"),
            dict(image_name="rock_AmbientOcclusion.png"), dict(image_name="x.png", label="Ambient Occlusion"),
            dict(image_name="x.png", node_name="occlusion map"), dict(image_name="metal_OcclusionRoughness.png"),
        ]
        for kwargs in cases:
            with self.subTest(**kwargs):
                self.assertTrue(self._found(**kwargs))


if __name__ == "__main__":
    unittest.main()
