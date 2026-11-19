# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Malformed X3D and VRML never crash the importer with an internal error.

A broken file either imports what it can (with warnings) or fails with a parse error the caller can catch as such:
``ValueError`` (the VRML reader's existing signal), ``xml.sax.SAXException`` or ``UnicodeError``. Before this, a
mutation fuzz of two small seed scenes hit NameError, KeyError, TypeError, IndexError and AttributeError deep in the
reader and the mesh builder (14 of 400 cases); the cases below are its minimised reproducers.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_import_malformed_bpy
"""

from __future__ import annotations

import importlib
import os
import random
import re
import sys
import tempfile
import unittest
import xml.sax

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension, SOURCE_DIR

TYPED = (ValueError, xml.sax.SAXException, UnicodeError)

DOOR_WRL = ('#VRML V2.0 utf8\nDEF Door Transform { translation 1 2 3 children [ Shape { appearance Appearance { '
            'material Material { diffuseColor 1 0 0 } } geometry IndexedFaceSet { coord Coordinate { point [ 0 0 0, '
            '1 0 0, 1 1 0 ] } coordIndex [ 0 1 2 -1 ] } } ] }\nDEF TT TimeSensor { cycleInterval 2 }\n'
            'DEF P PositionInterpolator { key [0 1] keyValue [0 0 0, 1 1 1] }\n')

DOOR_X3D = ('<?xml version="1.0" encoding="UTF-8"?><X3D version="4.0" profile="Immersive"><Scene>'
            '<Transform DEF="Door" translation="1 2 3" rotation="0 1 0 0.5"><Shape><Appearance>'
            '<Material diffuseColor="1 0 0" transparency="0.5"/></Appearance>'
            '<IndexedFaceSet coordIndex="0 1 2 -1 0 2 3 -1" texCoordIndex="0 1 2 -1 0 2 3 -1" colorPerVertex="true">'
            '<Coordinate point="0 0 0 1 0 0 1 1 0 0 1 0"/><TextureCoordinate point="0 0 1 0 1 1 0 1"/>'
            '<Color color="1 0 0 0 1 0 0 0 1 1 1 1"/></IndexedFaceSet></Shape></Transform>'
            '<Transform DEF="Handle"><TouchSensor DEF="Touch"/><Shape><Sphere radius="0.5"/></Shape></Transform>'
            '<TimeSensor DEF="TT" cycleInterval="2" loop="false"/>'
            '<PositionInterpolator DEF="Slide" key="0 1" keyValue="0 0 0 2 0 0"/>'
            '<ROUTE fromNode="Touch" fromField="touchTime" toNode="TT" toField="set_startTime"/>'
            '<ROUTE fromNode="TT" fromField="fraction_changed" toNode="Slide" toField="set_fraction"/>'
            '<ROUTE fromNode="Slide" fromField="value_changed" toNode="Door" toField="set_translation"/>'
            '<Transform USE="Door"/></Scene></X3D>')


def _ifs(coord_index, extra_fields="", children=""):
    return ('<X3D version="4.0"><Scene><Shape><IndexedFaceSet coordIndex="%s"%s>'
            '<Coordinate point="0 0 0 1 0 0 1 1 0"/>%s</IndexedFaceSet></Shape></Scene></X3D>'
            % (coord_index, extra_fields, children))


# name -> (file extension, text); each raised an untyped error before the fix
REPRODUCERS = {
    "vrml_numline_warning_name_error": (".wrl", "#VRML V2.0 utf8\nShape { geometry IndexedFaceSet { coord Coordinate "
                                                "{ point [ 0 0 0, 1 0 0,\n 1 1e 0 ] } coordIndex [ 0 1 2 -1 ] } }\n"),
    "vrml_use_of_undefined_def": (".wrl", "#VRML V2.0 utf8\nTransform { children [ USE Nope ] }\n"),
    "vrml_unterminated_string_at_eof": (".wrl", DOOR_WRL + 'RO-1UTE TT.fraction_changed TO P.set_fraction\n'
                                                           'ROUTE P.valu"e_changed TO Door.set_translation\nUSE Door\n'),
    "vrml_node_in_a_number_field": (".wrl", DOOR_WRL + "ROUTE TT.fraction_changed TO P.set_fraction\nROUTE "
                                    "P.value_changed sform { translation 1 2 3 children [ Shape { appearance Appearance "
                                    "{ material Material { diffuseColor 1 0 0 } } geometry IndexedFaceSet { coord "
                                    "Coordinate { point [ 0 0 0, 1 0 0, 1 1 0 ] } coordIndex TO Door.set_translation\n"
                                    "USE Door\n"),
    "tex_coord_index_past_the_end": (".x3d", _ifs("0 1 2 -1", ' texCoordIndex="0 1 7 -1"',
                                                  '<TextureCoordinate point="0 0 1 0 1 1"/>')),
    "non_integer_coord_index": (".x3d", _ifs("0 1 2.5 -1")),
    "negative_coord_index": (".x3d", _ifs("0 1 -7 -1")),
    "empty_x3d_file": (".x3d", ""),
    "rotation_with_three_numbers": (".x3d", '<X3D version="4.0"><Scene><Transform rotation="0 1 0"><Shape><Box/></Shape>'
                                            '</Transform></Scene></X3D>'),
    "tex_coord_index_shorter_than_coord_index": (".x3d", '<X3D version="4.0"><Scene><Shape><IndexedFaceSet coordIndex="0 1 2'
                                                         ' -1 0 2 3 -1" texCoordIndex="0 1 2 -1 0 1"><Coordinate point="0 0 0'
                                                         ' 1 0 0 1 1 0 0 1 0"/><TextureCoordinate point="0 0 1 0 1 1 0 1"/>'
                                                         '</IndexedFaceSet></Shape></Scene></X3D>'),
    "vrml_use_without_a_name": (".wrl", "#VRML V2.0 utf8\nTransform { children [ Shape { geometry Box { } } ] }\nUSE"),
    # an infinite keyValue moves lit geometry to infinity: the light-unit fit saw only NaN errors (StopIteration)
    "infinite_animation_under_a_light": (".x3d", '<?xml version="1.0" encoding="UTF-8"?><X3D version="4.0" profile="Immersive"><Scene><Transform DEF="Door" translation="1 2 3" rotation="0 1 0 0.5" scale="1 2 1"><Shape><Appearance><Material diffuseColor="1 0 0" transpnanarency="0.5"/><ImageTexture url=\'"t.png"\'/></Appearance><IndexedFaceSet coordIndex="0 1 2 -1 0 2 3 -1" texCoordIndex="0 1 2 -1 0 2 3 -1" colorPerVertex="true"><Coordinate point="0 0 0 1 0 0 1 1 0 0 1 0"/><TextureCoordinate point="0 0 1 0 1 1 0 1"/><Color color="1 0 0 0 1 0 0 0 1 1 1 1"/></IndexedFaceSet></Shape></Transform><Transform DEF="Handle"><TouchSensor DEF="Touch"/><Shape><Sphere radius="0.5"/></Shape><Shape><Box size="1 2 3"/></Shape><Shape><Cylinder/></Shape></Transform><TimeSensor DEF="TT" cycleInterval="2" loop="false"/><PositionInterpolator DEF="Slide" key="0 1" keyValue="0 0 1e309 2 0 0"/><ROUTE fromNode="Touch" fromField="touTT" toField="set_startTime"/><ROUTE fromNode="TT" fromField="fraction_changed" toNode="Slide" toField="set_fraction"/><ROUTE fromNode="Slide" fromField="value_changed" toNode="Door" toField="set_translation"/><Viewpoint position="0 0 10"/><PointLight location="0 5 0"/><Transform USE="Door"/></Scene></X3D>'),
}

_TOKENS = ["-1", "0", "1e309", "nan", "-inf", "999999999", "", "\"", "<", ">", "&", "]", "[", "{", "}",
           'USE="Nope"', 'DEF="Door"', "<Transform>", "</Shape>", "<Shape/>", '<IndexedFaceSet coordIndex="5 6 7"/>',
           "ROUTE", "é", "true", "TRUE", "0x1F", ",", "1 2"]


def _mutate(rng, text):
    for _ in range(rng.randint(1, 4)):
        op, i = rng.random(), rng.randrange(len(text) + 1)
        if op < 0.25:
            text = text[:i] + text[i + rng.randint(1, 20):]
        elif op < 0.5:
            text = text[:i] + rng.choice(_TOKENS) + text[i:]
        elif op < 0.7:
            numbers = list(re.finditer(r"-?\d+(\.\d+)?", text))
            if numbers:
                m = rng.choice(numbers)
                text = text[:m.start()] + rng.choice(["-1", "1e309", "nan", "-99999", "0", "1e-320", "3.5"]) + text[m.end():]
        elif op < 0.85:
            j = rng.randrange(len(text) + 1)
            a, b = sorted((i, j))
            text = text[:b] + text[a:b][:200] + text[b:]
        else:
            text = text[:i]
    return text


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ImportMalformedTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_malformed_")
        _register_extension(cls.tmpdir)
        sys.path.insert(0, str(SOURCE_DIR))
        cls.importer = importlib.import_module("io_scene_x3d.import_x3d")

    def _load(self, name, extension, text):
        path = os.path.join(self.tmpdir, name + extension)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmpdir)
        try:
            self.importer.load(bpy.context, path)
        except TYPED:
            pass  # a parse error the caller can handle

    def test_reproducers_import_or_fail_with_a_parse_error(self):
        for name, (extension, text) in REPRODUCERS.items():
            with self.subTest(case=name):
                self._load(name, extension, text)

    def test_valid_neighbours_still_import_their_geometry(self):
        """The guards only touch malformed indices: a valid face next to a bad one is kept."""
        self._load("one_bad_face", ".x3d", _ifs("0 1 2 -1 0 2 -9 -1"))
        meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
        self.assertEqual(len(meshes), 1)
        self.assertGreaterEqual(len(meshes[0].data.polygons), 1)

    def test_seeded_mutation_fuzz(self):
        rng = random.Random(20261118)
        for k in range(150):
            extension, seed = (".wrl", DOOR_WRL + "USE Door\n") if k % 3 == 0 else (".x3d", DOOR_X3D)
            text = _mutate(rng, seed)
            with self.subTest(case=k, text=text[:200]):
                self._load(f"fuzz{k}", extension, text)


if __name__ == "__main__":
    unittest.main()
