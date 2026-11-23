# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reading and copying the files a scene names, within limits. Pure Python, no ``bpy``.

The chaos round of 2.7.3 (tools/chaos/hostile.py) found that an ImageTexture url of ``/dev/zero`` imported, and the
default re-export (path mode COPY) then copied it with ``bpy_extras.io_utils.path_reference_copy``, which calls
``shutil.copy``: a device that never ends was copied until the disk was full (Confirmed: about 50 GB in 62 seconds on
the test machine). A FIFO would hang the export the same way. A texture, an Inline or a sound is a regular file, so
anything else is skipped with a warning, and a copy stops at a byte budget.
"""

from __future__ import annotations

import os
import stat

COPY_MAX_BYTES_ENV = "BLENDER_X3D_MAX_COPY_BYTES"
COPY_MAX_BYTES = 4 * 1024 ** 3          # 4 GiB for any one copied resource
_CHUNK = 1 << 20


def copy_byte_limit() -> int:
    """The per-file copy budget: BLENDER_X3D_MAX_COPY_BYTES when it is a positive integer, else 4 GiB."""
    try:
        value = int(os.environ.get(COPY_MAX_BYTES_ENV, ""))
    except ValueError:
        return COPY_MAX_BYTES
    return value if value > 0 else COPY_MAX_BYTES


def is_regular_file(path: str) -> bool:
    """True for a regular file (following links); False for a device, FIFO, socket, directory or a missing path."""
    try:
        return stat.S_ISREG(os.stat(path).st_mode)
    except (OSError, ValueError):
        return False


def special_file_reason(path: str) -> str | None:
    """Why ``path`` must not be read as a resource, or None when it is a regular file or does not exist."""
    try:
        mode = os.stat(path).st_mode
    except (OSError, ValueError):
        return None
    if stat.S_ISREG(mode):
        return None
    if stat.S_ISDIR(mode):
        return "it is a folder"
    if stat.S_ISCHR(mode) or stat.S_ISBLK(mode):
        return "it is a device, which can be endless"
    if stat.S_ISFIFO(mode):
        return "it is a pipe, which can block forever"
    if stat.S_ISSOCK(mode):
        return "it is a socket"
    return "it is not a regular file"


def bounded_copy(src: str, dst: str, limit: int | None = None) -> None:
    """Copy a regular file in chunks, raising OSError past ``limit`` bytes (a file that grows while it is read)."""
    limit = copy_byte_limit() if limit is None else limit
    reason = special_file_reason(src)
    if reason:
        raise OSError(f"not copying {src!r}: {reason}")
    size = os.path.getsize(src)
    if size > limit:
        raise OSError(f"not copying {src!r}: {size} bytes is over the {limit}-byte budget (set {COPY_MAX_BYTES_ENV})")
    written = 0
    try:
        with open(src, "rb") as fin, open(dst, "wb") as fout:
            while True:
                chunk = fin.read(_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit:
                    raise OSError(f"not copying {src!r}: it grew past the {limit}-byte budget while being read")
                fout.write(chunk)
    except OSError:
        if written > limit:
            try:
                os.unlink(dst)
            except OSError:
                pass
        raise
    try:
        import shutil
        shutil.copymode(src, dst)
    except OSError:
        pass


def path_reference_copy(copy_set, report=print, limit: int | None = None) -> int:
    """``bpy_extras.io_utils.path_reference_copy`` with the two guards above: only regular files, within the budget.

    Returns the number of files copied. Every skipped file is reported with its reason.
    """
    copied = 0
    for file_src, file_dst in copy_set:
        if not os.path.exists(file_src):
            report(f"missing {file_src!r}, not copying")
            continue
        reason = special_file_reason(file_src)
        if reason:
            report(f"not copying {file_src!r}: {reason}")
            continue
        try:
            if os.path.exists(file_dst) and os.path.samefile(file_src, file_dst):
                continue
        except OSError:
            pass
        try:
            os.makedirs(os.path.dirname(file_dst) or ".", exist_ok=True)
            bounded_copy(file_src, file_dst, limit)
            copied += 1
        except OSError as exc:
            report(str(exc))
    return copied
