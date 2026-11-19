# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline regression controls for XML and remote import resource boundaries."""

import io
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import patch
import xml.dom.minidom
from xml.sax import SAXException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))
from import_resources import ResourceLimitError, _HTTPRedirectsOnly, convert_gif, download_resource, make_x3d_sax_parser


class _Response(io.BytesIO):
    def __init__(self, data, **headers):
        super().__init__(data)
        self.headers = headers


class _Opener:
    def __init__(self, data=b"image", **headers):
        self.response = _Response(data, **headers)
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request.full_url, timeout))
        return self.response


class ImportResourceTests(unittest.TestCase):
    def test_gif_conversion_treats_shell_characters_as_a_literal_path(self):
        path = '/tmp/image$(touch SHOULD_NOT_EXIST);".gif'
        with patch("import_resources.subprocess.run") as run:
            converted = convert_gif(path)
        try:
            args, kwargs = run.call_args
            self.assertEqual(args[0], ["convert", path, converted])
            self.assertNotIn("shell", kwargs)
            self.assertEqual(kwargs["timeout"], 30)
            self.assertTrue(kwargs["check"])
            self.assertTrue(Path(converted).is_file())
        finally:
            Path(converted).unlink()

    def test_failed_gif_conversion_removes_its_private_output(self):
        for error in (FileNotFoundError("convert unavailable"), subprocess.TimeoutExpired("convert", 30)):
            with self.subTest(error=error), patch("import_resources.subprocess.run", side_effect=error) as run:
                with self.assertRaises(type(error)):
                    convert_gif("image.gif")
                self.assertFalse(Path(run.call_args.args[0][2]).exists())

    def test_same_basename_cannot_overwrite_other_asset_or_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory, "albedo.png")
            existing.write_bytes(b"local image")
            paths = []
            for host, data in (("one", b"one"), ("two", b"two")):
                opener = _Opener(data, **{"Content-Type": "image/png"})
                path = download_resource(f"https://{host}.example/albedo.png", directory=directory, opener=opener)
                paths.append(path)
                self.assertEqual(Path(path).read_bytes(), data)
                self.assertEqual(opener.calls[0][1], 10)
                self.assertTrue(opener.response.closed)
            self.assertNotEqual(paths[0], paths[1])
            self.assertEqual(existing.read_bytes(), b"local image")

    def test_repeated_url_uses_exclusive_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [download_resource("https://example.org/asset", directory=directory, opener=_Opener())
                     for _ in range(2)]
            self.assertNotEqual(*paths)

    def test_declared_oversize_rejected_before_file_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            opener = _Opener(**{"Content-Length": "100"})
            with self.assertRaises(ResourceLimitError):
                download_resource("https://example.org/a", directory=directory, opener=opener, max_bytes=4)
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.assertTrue(opener.response.closed)

    def test_streamed_oversize_rejected_and_partial_removed(self):
        for headers in ({}, {"Content-Length": "1"}, {"Content-Length": "invalid"}):
            with self.subTest(headers=headers), tempfile.TemporaryDirectory() as directory:
                opener = _Opener(b"12345", **headers)
                with self.assertRaises(ResourceLimitError):
                    download_resource("https://example.org/a", directory=directory, opener=opener, max_bytes=4)
                self.assertEqual(list(Path(directory).iterdir()), [])
                self.assertTrue(opener.response.closed)

    def test_deadline_rejected_and_partial_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("import_resources.time.monotonic", side_effect=[0, 31]):
                with self.assertRaises(ResourceLimitError):
                    download_resource("https://example.org/a", directory=directory, opener=_Opener())
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_deadline_is_checked_after_final_read(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("import_resources.time.monotonic", side_effect=[0, 0, 31]):
                with self.assertRaises(ResourceLimitError):
                    download_resource("https://example.org/a", directory=directory, opener=_Opener(b""))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_read_failure_removes_partial_and_closes_response(self):
        with tempfile.TemporaryDirectory() as directory:
            opener = _Opener()
            with patch.object(opener.response, "read", side_effect=TimeoutError("timed out")):
                with self.assertRaises(TimeoutError):
                    download_resource("https://example.org/a", directory=directory, opener=opener)
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.assertTrue(opener.response.closed)

    def test_non_http_scheme_rejected_before_io(self):
        opener = _Opener()
        for url in ("file:///etc/passwd", "ftp://example.org/a", "www.example.org/a"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                download_resource(url, opener=opener)
        self.assertEqual(opener.calls, [])

    def test_redirect_to_non_http_scheme_rejected(self):
        with self.assertRaises(ValueError):
            _HTTPRedirectsOnly().redirect_request(None, None, 302, "Found", {}, "ftp://example.org/a")

    def test_missing_content_type_preserves_safe_url_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            path = download_resource("https://example.org/sound.mp3?token=x", directory=directory, opener=_Opener())
            self.assertEqual(Path(path).suffix, ".mp3")


class XMLResourceTests(unittest.TestCase):
    def parse(self, data):
        if isinstance(data, bytes):
            return xml.dom.minidom.parse(io.BytesIO(data), make_x3d_sax_parser())
        return xml.dom.minidom.parseString(data, make_x3d_sax_parser())

    def test_standard_external_x3d_doctype_and_predefined_entities_remain_legal(self):
        doc = self.parse('''<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN"
          "https://invalid.example/x3d.dtd"><X3D><Scene><WorldInfo title="A &amp; B"/></Scene></X3D>''')
        self.assertEqual(doc.getElementsByTagName("WorldInfo")[0].getAttribute("title"), "A & B")

    def test_internal_entity_rejected_at_declaration(self):
        with self.assertRaisesRegex(SAXException, "entity declarations"):
            self.parse('''<!DOCTYPE X3D [<!ENTITY e "expanded">]>
                <X3D><Scene><WorldInfo title="&e;"/></Scene></X3D>''')

    def test_external_entity_and_parameter_entity_rejected(self):
        for declaration in ('<!ENTITY e SYSTEM "file:///etc/passwd">',
                            '<!ENTITY % e SYSTEM "https://invalid.example/entity">'):
            with self.subTest(declaration=declaration), self.assertRaisesRegex(SAXException, "entity declarations"):
                self.parse(f'<!DOCTYPE X3D [{declaration}]><X3D><Scene/></X3D>')

    def test_entity_rejection_honours_xml_encoding(self):
        text = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE X3D [<!ENTITY e "expanded">]><X3D/>'
        with self.assertRaisesRegex(SAXException, "entity declarations"):
            self.parse(text.encode("utf-16"))

    def test_entity_text_in_comments_remains_legal(self):
        self.parse('<X3D><!-- <!ENTITY e "comment"> --><Scene/></X3D>')

    def test_large_attribute_is_not_lost(self):
        points = "0 0 0 " * 100000
        doc = self.parse(f'<X3D><Scene><Shape><PointSet><Coordinate point="{points}"/></PointSet></Shape></Scene></X3D>')
        self.assertEqual(doc.getElementsByTagName("Coordinate")[0].getAttribute("point"), points)


if __name__ == "__main__":
    unittest.main()
