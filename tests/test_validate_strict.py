# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The structural validator refuses invented elements and reads compressed files."""

import gzip
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "source"))

from validate import validate_xml_file, validate_xml_text  # noqa: E402

GOOD = '<X3D version="4.0"><Scene><Shape><Box/></Shape><ROUTE fromNode="a" fromField="b" toNode="c" toField="d"/></Scene></X3D>'
BAD = '<X3D version="4.0"><Scene><Banana size="1"/><Banana/><Shape><Box/></Shape></Scene></X3D>'


class StrictValidatorTests(unittest.TestCase):
    def test_known_document_passes(self):
        self.assertEqual(validate_xml_text(GOOD).errors, [])

    def test_invented_element_is_an_error_with_its_count(self):
        result = validate_xml_text(BAD)
        self.assertFalse(result.valid)
        self.assertEqual(result.errors, ["Unknown X3D element <Banana> (2x)"])

    def test_misspelled_real_node_is_caught(self):
        self.assertFalse(validate_xml_text(GOOD.replace("Shape", "Shapes")).valid)

    def test_comments_and_text_are_ignored(self):
        self.assertTrue(validate_xml_text(GOOD.replace("<Scene>", "<Scene><!-- note -->")).valid)

    def test_compressed_file_is_validated_not_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            for name, text, expected in (("good.x3dz", GOOD, True), ("bad.x3dz", BAD, False)):
                path = os.path.join(folder, name)
                with gzip.open(path, "wb") as handle:
                    handle.write(text.encode())
                self.assertEqual(validate_xml_file(path).valid, expected, name)

    def test_truncated_gzip_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "cut.x3dz")
            data = gzip.compress(GOOD.encode())
            with open(path, "wb") as handle:
                handle.write(data[:len(data) // 2])
            self.assertFalse(validate_xml_file(path).valid)

    def test_missing_file_fails_closed(self):
        self.assertFalse(validate_xml_file("/nonexistent/none.x3d").valid)


if __name__ == "__main__":
    unittest.main()
