#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""EEVEE leg of the scorecard: the same scene set-up as cycles_ref.py, rendered with engine BLENDER_EEVEE in ONE process.

    xvfb-run -a python eevee_ref.py --jobs JOBS.json --addon ADDON_SOURCE_DIR [--size 512] [--result FILE]

EEVEE needs an OpenGL context: headless this works only under Xvfb with Mesa llvmpipe, and the first render of the process pays
about 66 s of shader compile (Blender 5.3.0, 4 shared vCPUs), so every scene goes through this one process. Writes OUTDIR/eevee.png
per job and the same BLENDER_LEG records as cycles_ref.py."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cycles_ref  # noqa: E402

if __name__ == "__main__":
    code = cycles_ref.main(engine_default="eevee")
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
