# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The validator every export passes through, pinned without Blender: field checks, messages and the x3d.py layer.

Mutation testing (mutmut 3.8.1) of source/validate.py against the Blender-free tests killed 107 of 408 mutants: the
x3d.py semantic layer (``validate_with_x3d_py``, ``validate_tree_with_x3d_py``, ``_coerce_field``; 211 mutants) was
reached only through Blender export tests, and the error messages, the "No Scene" warning and multi-field nodes were
not checked. These tests pin that behaviour. The x3d.py tests skip when the package is not installed (CI's unit job
installs x3d==4.0.65.8).

    cd tests && python -m unittest test_validate_semantic
"""

from __future__ import annotations

import gzip
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "source"))

import validate  # noqa: E402
from validate import (  # noqa: E402
    ValidationResult, _coerce_field, _field_kinds, field_value_errors, unknown_element_errors, validate_tree_with_x3d_py,
    validate_with_x3d_py, validate_xml_file, validate_xml_text, validate_xml_tree,
)

try:
    import x3d.x3d as X3D_MODULE
except Exception:  # pragma: no cover - the package is optional
    X3D_MODULE = None


def _doc(scene_body="", version="4.0", head=""):
    return f'<X3D version="{version}" profile="Immersive">{head}<Scene>{scene_body}</Scene></X3D>'


def _declaration(field_type_name):
    """A FIELD_DECLARATIONS entry whose type is a function named like x3d.py's (FieldType.SFVec3f, ...)."""
    def field_type():
        return None
    field_type.__name__ = field_type_name
    return ("name", None, field_type)


class StructureTests(unittest.TestCase):

    def test_root_must_be_x3d(self):
        result = validate_xml_text("<Scene/>")
        self.assertEqual(result, ValidationResult(valid=False, errors=["Unexpected root node: Scene"], warnings=[]))

    def test_accepted_and_refused_versions(self):
        for version in ("4.0", "4.1", "3.3", "3.0"):
            with self.subTest(version=version):
                self.assertTrue(validate_xml_text(_doc(version=version)).valid)
        for version in ("3.2", "4.2", "", "4"):
            with self.subTest(version=version):
                result = validate_xml_text(_doc(version=version))
                self.assertIs(result.valid, False)
                self.assertEqual(result.errors, [f"Unsupported X3D version: {version}"])
        result = validate_xml_text("<X3D><Scene/></X3D>")
        self.assertEqual(result.errors, ["Unsupported X3D version: None"])

    def test_missing_scene_is_a_warning_only(self):
        result = validate_xml_text('<X3D version="4.0"/>')
        self.assertEqual(result, ValidationResult(valid=True, errors=[], warnings=["No Scene element found."]))
        self.assertEqual(validate_xml_text(_doc()).warnings, [])

    def test_parse_errors_are_reported_not_raised(self):
        result = validate_xml_text("<X3D version='4.0'><Scene>")
        self.assertIs(result.valid, False)
        self.assertEqual(len(result.errors), 1)
        self.assertTrue(result.errors[0].startswith("XML parse error: "), result.errors)

    def test_files_plain_and_gzip_give_the_same_result(self):
        folder = tempfile.mkdtemp(prefix="x3d_validate_")
        text = _doc('<Shape><Box size="1 2 3"/></Shape><Banana/>')
        plain = os.path.join(folder, "a.x3d")
        packed = os.path.join(folder, "a.x3dz")
        with open(plain, "w", encoding="utf-8") as handle:
            handle.write(text)
        with gzip.open(packed, "wb") as handle:
            handle.write(text.encode("utf-8"))
        self.assertEqual(validate_xml_file(plain), validate_xml_file(packed))
        self.assertEqual(validate_xml_file(plain).errors, ["Unknown X3D element <Banana> (1x)"])
        broken = os.path.join(folder, "broken.x3d")
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write("<X3D")
        self.assertTrue(validate_xml_file(broken).errors[0].startswith("XML parse error: "))
        self.assertIs(validate_xml_file(broken).valid, False)

    def test_unknown_elements_counted_and_sorted(self):
        # comments kept as nodes (as a parser with insert_comments gives them): skipped, not an element, and the walk goes on
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
        root = ET.fromstring(_doc("<Zebra/><!-- note --><Apple/><Zebra/><Transform/>"), parser=parser)
        self.assertEqual(unknown_element_errors(root), ["Unknown X3D element <Apple> (1x)",
                                                        "Unknown X3D element <Zebra> (2x)"])


class FieldValueTests(unittest.TestCase):

    def setUp(self):
        validate._KIND_CACHE.clear()   # each test parses the declarations itself

    def _errors(self, body):
        return field_value_errors(ET.fromstring(_doc(body)))

    def test_messages_name_the_node_field_and_type(self):
        self.assertEqual(self._errors('<IndexedFaceSet solid="yes"/>'),
                         ["Invalid value 'yes' in <IndexedFaceSet solid> (expected boolean)"])
        self.assertEqual(self._errors('<IndexedFaceSet coordIndex="0 1 2.5 -1"/>'),
                         ["Invalid value '2.5' in <IndexedFaceSet coordIndex> (expected integer)"])
        self.assertEqual(self._errors('<Material transparency="half"/>'),
                         ["Invalid value 'half' in <Material transparency> (expected finite real)"])

    def test_non_finite_label_for_nan_and_infinities_only(self):
        for token in ("nan", "NaN", "inf", "-inf", "+Infinity", "INF"):
            with self.subTest(token=token):
                self.assertEqual(self._errors(f'<Material transparency="{token}"/>'),
                                 [f"Non-finite number '{token}' in <Material transparency> (expected finite real)"])
        self.assertEqual(self._errors('<Material transparency="1e999"/>'),
                         ["Invalid value '1e999' in <Material transparency> (expected finite real)"])
        # "nan" in an integer or boolean field is just an invalid value
        self.assertEqual(self._errors('<IndexedFaceSet coordIndex="nan"/>'),
                         ["Invalid value 'nan' in <IndexedFaceSet coordIndex> (expected integer)"])

    def test_every_declared_field_of_a_node_is_checked(self):
        """Multi-field nodes: the declaration list is split on commas into name:kind pairs."""
        errors = self._errors('<PointLight global="maybe" intensity="x" on="TRUE" radius="5" location="1,2,3"/>')
        self.assertEqual(errors, ["Invalid value 'maybe' in <PointLight global> (expected boolean)",
                                  "Invalid value 'x' in <PointLight intensity> (expected finite real)"])
        self.assertEqual(_field_kinds("PointLight")["shadows"], "b")
        self.assertEqual(_field_kinds("PointLight")["attenuation"], "f")

    def test_accepted_forms(self):
        self.assertEqual(self._errors('<IndexedFaceSet coordIndex="0,1,-2 0x1F +3" solid="FALSE" ccw="true"/>'), [])
        self.assertEqual(self._errors('<Material transparency="-.5e-3" shininess="1." diffuseColor="1,0 .25"/>'), [])

    def test_skipped_elements_and_attributes_do_not_stop_the_walk(self):
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
        root = ET.fromstring(_doc('<!-- c --><IndexedFaceSet USE="x" solid="yes"/>'
                                  '<IndexedFaceSet undeclared="1" solid="maybe"/>'), parser=parser)
        self.assertEqual(field_value_errors(root), ["Invalid value 'maybe' in <IndexedFaceSet solid> (expected boolean)"])

    def test_first_bad_token_once_per_field_and_use_skipped(self):
        self.assertEqual(self._errors('<IndexedFaceSet coordIndex="0 a b 2"/>'),
                         ["Invalid value 'a' in <IndexedFaceSet coordIndex> (expected integer)"])
        self.assertEqual(self._errors('<IndexedFaceSet USE="x" solid="yes"/>'), [])
        self.assertEqual(self._errors('<IndexedFaceSet undeclared="yes"/>'), [])

    def test_field_kinds_are_parsed_and_cached(self):
        kinds = _field_kinds("IndexedFaceSet")
        self.assertEqual(kinds, {"ccw": "b", "colorIndex": "i", "colorPerVertex": "b", "convex": "b", "coordIndex": "i",
                                 "creaseAngle": "f", "normalIndex": "i", "normalPerVertex": "b", "solid": "b",
                                 "texCoordIndex": "i"})
        self.assertIs(_field_kinds("IndexedFaceSet"), kinds)
        self.assertIs(validate._KIND_CACHE["IndexedFaceSet"], kinds)
        self.assertEqual(_field_kinds("NoSuchNode"), {})

    def test_tree_reports_field_errors_and_unknown_elements_together(self):
        result = validate_xml_text(_doc('<Banana/><Material transparency="nan"/>'))
        self.assertFalse(result.valid)
        self.assertEqual(result.errors, ["Unknown X3D element <Banana> (1x)",
                                         "Non-finite number 'nan' in <Material transparency> (expected finite real)"])


class CoerceFieldTests(unittest.TestCase):

    def test_booleans(self):
        for text, want in (("true", True), ("TRUE", True), (" true ", True), ("false", False), ("yes", False)):
            with self.subTest(text=text):
                self.assertIs(_coerce_field(text, _declaration("SFBool")), want)

    def test_strings(self):
        self.assertEqual(_coerce_field("  keep spaces ", _declaration("SFString")), "  keep spaces ")
        self.assertEqual(_coerce_field('"a" "b c" ""', _declaration("MFString")), ["a", "b c", ""])
        self.assertEqual(_coerce_field(r'"say \"hi\"" "back\\slash"', _declaration("MFString")),
                         ['say "hi"', "back\\slash"])
        self.assertEqual(_coerce_field("", _declaration("MFString")), [])

    def test_scalars(self):
        self.assertEqual(_coerce_field("2.5", _declaration("SFFloat")), 2.5)
        self.assertEqual(_coerce_field("1e3", _declaration("SFTime")), 1000.0)
        self.assertEqual(_coerce_field("7", _declaration("SFDouble")), 7.0)
        value = _coerce_field("4", _declaration("SFInt32"))
        self.assertEqual((value, type(value)), (4, int))
        self.assertEqual(_coerce_field("", _declaration("SFFloat")), 0)

    def test_single_vectors_are_tuples(self):
        self.assertEqual(_coerce_field("1 2 3", _declaration("SFVec3f")), (1.0, 2.0, 3.0))
        self.assertEqual(_coerce_field("0,1,0, 1.5", _declaration("SFRotation")), (0.0, 1.0, 0.0, 1.5))

    def test_multiple_values_are_grouped_by_width(self):
        cases = {"MFVec3f": ("1 2 3 4 5 6", [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)]),
                 "MFVec2f": ("1 2 3 4", [(1.0, 2.0), (3.0, 4.0)]),
                 "MFVec4f": ("1 2 3 4 5 6 7 8", [(1.0, 2.0, 3.0, 4.0), (5.0, 6.0, 7.0, 8.0)]),
                 "MFColor": ("1 0 0 0 1 0", [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]),
                 "MFColorRGBA": ("1 0 0 1 0 1 0 0.5", [(1.0, 0.0, 0.0, 1.0), (0.0, 1.0, 0.0, 0.5)]),
                 "MFRotation": ("0 1 0 1 1 0 0 2", [(0.0, 1.0, 0.0, 1.0), (1.0, 0.0, 0.0, 2.0)]),
                 "MFQuaternion": ("0 0 0 1 1 0 0 0", [(0.0, 0.0, 0.0, 1.0), (1.0, 0.0, 0.0, 0.0)])}
        for field_type, (text, want) in cases.items():
            with self.subTest(field_type=field_type):
                self.assertEqual(_coerce_field(text, _declaration(field_type)), want)

    def test_flat_lists(self):
        self.assertEqual(_coerce_field("1 2 3", _declaration("MFFloat")), [1.0, 2.0, 3.0])
        ints = _coerce_field("0 1 -1", _declaration("MFInt32"))
        self.assertEqual((ints, [type(v) for v in ints]), ([0, 1, -1], [int, int, int]))
        self.assertEqual(_coerce_field("1 0 0 1", _declaration("SFMatrix3f")), (1.0, 0.0, 0.0, 1.0))
        self.assertEqual(_coerce_field("1 2 3 4", _declaration("MFMatrix4f")), [1.0, 2.0, 3.0, 4.0])

    def test_type_as_a_plain_string_and_missing(self):
        self.assertEqual(_coerce_field("1 2", ("name", None, "SFVec2f")), (1.0, 2.0))
        self.assertEqual(_coerce_field("1 2", ("name", None)), [1.0, 2.0])


@unittest.skipUnless(X3D_MODULE is not None, "the x3d package is not installed")
class X3dPyLayerTests(unittest.TestCase):

    def _check(self, body, head=""):
        return validate_tree_with_x3d_py(ET.fromstring(_doc(body, head=head)), X3D_MODULE)

    def test_clean_scene(self):
        result = self._check('<Transform translation="1 2 3"><Shape><Appearance><Material transparency="0.5"/>'
                             '</Appearance><Box size="1 2 3"/></Shape></Transform>',
                             head='<head><meta name="title" content="t"/><component name="HAnim" level="1"/></head>')
        self.assertEqual(result, ValidationResult(valid=True, errors=[], warnings=[]))

    def test_out_of_range_value_is_an_error_in_a_nested_child(self):
        result = self._check('<Transform><Transform><Shape><Appearance><Material transparency="2"/></Appearance>'
                             '</Shape></Transform></Transform>')
        self.assertFalse(result.valid)
        self.assertEqual(len(result.errors), 1)
        self.assertTrue(result.errors[0].startswith("<Material transparency=...>: "), result.errors)

    def test_unknown_nodes_and_fields_are_warnings(self):
        result = self._check('<Banana/><Transform wobble="1"/>')
        self.assertTrue(result.valid)
        self.assertEqual(result.warnings, ["<Banana>: unknown X3D node", "<Transform>: unknown field 'wobble'"])

    def test_keyword_named_field_and_skipped_attributes(self):
        result = self._check('<PointLight DEF="L" global="true" containerField="children" class="c" id="i" style="s"/>')
        self.assertEqual(result, ValidationResult(valid=True, errors=[], warnings=[]))

    def test_attributes_after_skipped_or_unknown_ones_are_checked(self):
        result = self._check('<Material DEF="M" wobble="1" transparency="2"/>')
        self.assertEqual(result.warnings, ["<Material>: unknown field 'wobble'"])
        self.assertEqual(len(result.errors), 1)
        self.assertTrue(result.errors[0].startswith("<Material transparency=...>: "), result.errors)

    def test_use_is_not_field_checked(self):
        result = self._check('<Material DEF="M" transparency="0.5"/><Material USE="M" transparency="2"/>')
        self.assertEqual(result.errors, [])

    def test_system_exit_from_x3d_py_is_an_error(self):
        class Halting:
            @staticmethod
            def FIELD_DECLARATIONS():
                return [("size", None, "SFFloat")]

            def __init__(self, **_kwargs):
                raise SystemExit("stop")
        module = mock.Mock(spec=[])
        module.Halting = Halting
        result = validate_tree_with_x3d_py(ET.fromstring(_doc('<Halting size="1"/>')), module)
        self.assertEqual(result.errors, ["<Halting size=...>: x3d.py halted (stop)"])

    def test_broken_declarations_mean_every_field_is_unknown(self):
        class Broken:
            @staticmethod
            def FIELD_DECLARATIONS():
                raise RuntimeError("no declarations")
        module = mock.Mock(spec=[])
        module.Broken = Broken
        result = validate_tree_with_x3d_py(ET.fromstring(_doc('<Broken size="1"/>')), module)
        self.assertEqual((result.errors, result.warnings), ([], ["<Broken>: unknown field 'size'"]))

    def test_file_entry_point(self):
        folder = tempfile.mkdtemp(prefix="x3d_semantic_")
        good = os.path.join(folder, "good.x3dz")
        with gzip.open(good, "wb") as handle:
            handle.write(_doc('<Material transparency="2"/>').encode("utf-8"))
        result = validate_with_x3d_py(good)
        self.assertFalse(result.valid)
        self.assertTrue(result.errors[0].startswith("<Material transparency=...>: "))
        broken = os.path.join(folder, "broken.x3d")
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write("<X3D")
        result = validate_with_x3d_py(broken)
        self.assertEqual((result.valid, len(result.errors)), (False, 1))
        self.assertTrue(result.errors[0].startswith("XML parse error: "))
        self.assertFalse(validate_with_x3d_py(os.path.join(folder, "missing.x3d")).valid)


class OptionalPackageTests(unittest.TestCase):

    def test_none_when_x3d_is_not_importable(self):
        with mock.patch.dict(sys.modules, {"x3d": None, "x3d.x3d": None}):
            self.assertIsNone(validate.validate_with_x3d_py("does-not-matter.x3d"))


if __name__ == "__main__":
    unittest.main()
