# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-face colours and indexed texture coordinates import without false "indexed up to" warnings.

Found by the Demo 65 round trip (x3d.demo blender-giza-numbers/v3): a correct 1,600-face terrain with 1,600 per-face
colours (colorPerVertex false, no colorIndex) warned "Color has 1600 values but is indexed up to 1680; padding",
and a face set whose texCoordIndex never passed 2 warned "TextureCoordinate has 3 values but is indexed up to 4".
The importer took the maximum over coordIndex as well, which the X3D rules use only when the values are per
vertex and their own index is empty. Short fields must still be padded.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_import_attribute_padding_bpy
"""

from __future__ import annotations

import logging
import os
import tempfile
import unittest

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension

SCENE = """<?xml version="1.0" encoding="UTF-8"?>
<X3D profile="Interchange" version="4.0"><Scene>
<Shape><Appearance><Material/></Appearance>
<IndexedFaceSet coordIndex="0 1 4 -1 1 2 4 -1 2 3 4 -1 3 0 4 -1" colorPerVertex="false" {extra}>
<Coordinate point="0 0 0 1 0 0 1 0 1 0 0 1 0.5 1 0.5"/>
<Color color="{colors}"/>{tex}</IndexedFaceSet></Shape>
</Scene></X3D>"""


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@unittest.skipUnless(HAVE_BPY, "needs bpy")
class AttributePaddingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _register_extension(self.tmp)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.capture = _Capture()
        logging.getLogger().addHandler(self.capture)
        logging.getLogger("io_scene_x3d").addHandler(self.capture)

    def tearDown(self):
        logging.getLogger().removeHandler(self.capture)
        logging.getLogger("io_scene_x3d").removeHandler(self.capture)

    def _import(self, colors, tex="", extra=""):
        path = os.path.join(self.tmp, "pad.x3d")
        with open(path, "w", encoding="utf-8") as f:
            f.write(SCENE.format(colors=colors, tex=tex, extra=extra))
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
        return [m for m in self.capture.messages if "indexed up to" in m]

    def test_per_face_colours_one_per_face_do_not_warn(self):
        warnings = self._import("1 0 0 0 1 0 0 0 1 1 1 0")
        self.assertEqual(warnings, [])

    def test_indexed_texture_coordinates_do_not_warn(self):
        warnings = self._import("1 0 0 0 1 0 0 0 1 1 1 0", tex='<TextureCoordinate point="0 0 1 0 .5 1"/>',
                                extra='texCoordIndex="0 2 1 -1 0 2 1 -1 0 2 1 -1 0 2 1 -1"')
        self.assertEqual(warnings, [])

    def test_too_few_per_face_colours_still_pad(self):
        warnings = self._import("1 0 0 0 1 0")
        self.assertEqual(len(warnings), 1)
        self.assertIn("Color has 2 values", warnings[0])


if __name__ == "__main__":
    unittest.main()
