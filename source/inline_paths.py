# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Where an exported Inline points: its url as seen from the folder the X3D file is written to.

Pure Python, no ``bpy``. An imported Inline keeps the url its file gave it, which is relative to the folder that file
lived in; written verbatim into a file in another folder it points at nothing (X_ITE then draws nothing for it: the
Showcase's stilllife-stage re-exported next to nothing it inlines came back empty). The export finds the target and
writes the path from its own folder. Nothing is copied.
"""

from __future__ import annotations

import os
import re

_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def is_remote(url: str) -> bool:
    """A url with a scheme (http, https, data, file, ...). A one-letter scheme is a Windows drive."""
    match = _SCHEME.match(url)
    return bool(match) and len(match.group(0)) > 2


def _split_fragment(url: str):
    base, hash_, fragment = url.partition("#")
    return base, hash_ + fragment


def rebase_inline_url(url: str, export_dir: str, *, source_path: str | None = None, blend_dir: str | None = None,
                      path_mode: str = "COPY"):
    """``(url to write, warning or None)`` for an Inline.

    The target is looked for at ``source_path`` (where the import found it), at the url taken relative to the .blend
    file's folder, and at the url taken relative to ``export_dir`` (the file is written beside what it inlines). The url
    written is the target's path from ``export_dir`` with forward slashes (``path_mode`` ABSOLUTE writes the absolute
    path, STRIP the file name). A url with a scheme is left alone, and so is one whose target is nowhere to be found,
    with a warning that says so. Nothing is copied: the export writes a reference.
    """
    if not url or is_remote(url):
        return url, None
    path, fragment = _split_fragment(url)
    candidates = []
    if source_path:
        candidates.append(source_path)
    if os.path.isabs(path):
        candidates.append(path)
    else:
        if blend_dir:
            candidates.append(os.path.join(blend_dir, path))
        candidates.append(os.path.join(export_dir, path))
    target = next((os.path.abspath(c) for c in candidates if c and os.path.isfile(c)), None)
    if target is None:
        return url, (f"Inline target {url!r} was not found (looked beside the exported file, next to the .blend file and "
                     "where the import found it); the url is written as it was, so the Inline may point at nothing.")
    mode = (path_mode or "COPY").upper()
    if mode == "STRIP":
        written = os.path.basename(target)
    elif mode == "ABSOLUTE":
        written = target
    else:
        try:
            written = os.path.relpath(target, export_dir)
        except ValueError:  # another drive on Windows: no relative path exists
            written = target
    return written.replace("\\", "/") + fragment, None
