# SPDX-License-Identifier: GPL-3.0-or-later
"""Resource boundaries shared by the X3D importer, without a Blender dependency."""

from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.sax import SAXException, expatreader, handler


DOWNLOAD_TIMEOUT_SECONDS = 10
DOWNLOAD_DEADLINE_SECONDS = 30
DOWNLOAD_MAX_BYTES = 64 * 1024 * 1024


class ResourceLimitError(ValueError):
    """The resource exceeds an importer's explicit resource budget."""


SOURCE_MAX_BYTES_ENV = "BLENDER_X3D_MAX_SOURCE_BYTES"
SOURCE_MAX_BYTES = 1024 ** 3   # 1 GiB of X3D / VRML text, after decompression


def source_byte_limit():
    """The decompressed source budget: BLENDER_X3D_MAX_SOURCE_BYTES when it is a positive integer, else 1 GiB."""
    try:
        value = int(os.environ.get(SOURCE_MAX_BYTES_ENV, ""))
    except ValueError:
        return SOURCE_MAX_BYTES
    return value if value > 0 else SOURCE_MAX_BYTES


def read_source_bytes(path, limit=None):
    """The bytes of an X3D / VRML file, gunzipped when they are gzip (by content, so .x3dz, .wrz and a gzipped .x3dv
    all load), never more than ``limit`` after decompression: a few kilobytes of gzip can expand to gigabytes."""
    import gzip
    limit = source_byte_limit() if limit is None else limit
    with open(path, "rb") as raw:
        gzipped = raw.read(2) == b"\x1f\x8b"
    opener = gzip.open if gzipped else open
    with opener(path, "rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ResourceLimitError(f"{os.path.basename(path)} is larger than {limit} bytes"
                                 f"{' when decompressed' if gzipped else ''} (set {SOURCE_MAX_BYTES_ENV} to raise it)")
    return data


class _HTTPRedirectsOnly(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme.lower() not in {"http", "https"}:
            raise ValueError("Remote resources must redirect to HTTP(S)")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def convert_gif(path, *, timeout=30):
    """Run the legacy optional GIF converter without interpreting shell syntax.

    The output is an exclusive temporary file rather than a sibling PNG which
    could overwrite a scene asset. The caller handles an unavailable converter.
    """
    fd, converted = tempfile.mkstemp(prefix="x3d-converted-", suffix=".png")
    os.close(fd)
    try:
        subprocess.run(["convert", os.path.abspath(path), converted], check=True, timeout=timeout,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return converted
    except BaseException:
        os.unlink(converted)
        raise


def download_resource(url, *, directory=None, default_extension=".bin", name="x3d-resource",
                      timeout=DOWNLOAD_TIMEOUT_SECONDS, deadline=DOWNLOAD_DEADLINE_SECONDS,
                      max_bytes=DOWNLOAD_MAX_BYTES, opener=None):
    """Fetch HTTP(S) bytes to a unique private file; remove partial files on failure.

    ``timeout`` bounds each blocking socket operation; ``deadline`` additionally
    stops a streaming peer on the next read boundary. No URL basename is ever
    used as a writable destination, so assets and existing scene files cannot
    overwrite one another. The caller owns successful files and caches only
    successful results. ``opener`` permits deterministic, offline verification.
    """
    if urlsplit(url).scheme.lower() not in {"http", "https"}:
        raise ValueError("Remote resources require an HTTP(S) URL")
    if timeout <= 0 or deadline <= 0 or max_bytes < 0:
        raise ValueError("Download budgets must be positive (max_bytes may be zero)")
    if directory is not None and not os.path.isdir(directory):
        raise ValueError("Provided output_path must be a directory.")

    opener = opener or build_opener(_HTTPRedirectsOnly())
    started = time.monotonic()
    path = None
    try:
        request = Request(url, headers={"User-Agent": "Blender-X3D-importer"})
        with opener.open(request, timeout=min(timeout, deadline)) as response:
            length = response.headers.get("Content-Length")
            if length is not None:
                try:
                    declared_size = int(length)
                except ValueError:
                    declared_size = None
                if declared_size is not None and declared_size > max_bytes:
                    raise ResourceLimitError("Remote resource exceeds byte limit")

            content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
            extension = (mimetypes.guess_extension(content_type)
                         or os.path.splitext(urlsplit(url).path)[1] or default_extension)
            if not re.fullmatch(r"\.[A-Za-z0-9]{1,16}", extension):
                extension = ".bin"
            safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", name)[:40] or "x3d-resource"
            digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
            fd, path = tempfile.mkstemp(prefix=f"{safe_name}-{digest}-", suffix=extension, dir=directory)
            with os.fdopen(fd, "wb") as output:
                size = 0
                while True:
                    if time.monotonic() - started >= deadline:
                        raise ResourceLimitError("Remote resource exceeds time limit")
                    chunk = response.read(min(64 * 1024, max_bytes - size + 1))
                    if time.monotonic() - started >= deadline:
                        raise ResourceLimitError("Remote resource exceeds time limit")
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise ResourceLimitError("Remote resource exceeds byte limit")
                    output.write(chunk)
        return path
    except BaseException:
        if path is not None:
            os.unlink(path)
        raise


def make_x3d_sax_parser():
    """Parse large X3D attributes without permitting declared XML entities.

    Ordinary external X3D DOCTYPE declarations remain legal and are not fetched.
    Internal entities are unnecessary for X3D and rejected at declaration time,
    before expansion, independently of the bundled Expat amplification limit.
    """
    class _X3DExpatParser(expatreader.ExpatParser):
        def reset(self):
            super().reset()
            self._parser.EntityDeclHandler = self._reject_entity
            # pulldom otherwise loses very large start tags deferred until close.
            if hasattr(self._parser, "SetReparseDeferralEnabled"):
                self._parser.SetReparseDeferralEnabled(False)

        @staticmethod
        def _reject_entity(*_args):
            raise SAXException("XML entity declarations are not allowed in X3D imports")

    parser = _X3DExpatParser()
    parser.setFeature(handler.feature_external_ges, False)
    parser.setFeature(handler.feature_external_pes, False)
    return parser
