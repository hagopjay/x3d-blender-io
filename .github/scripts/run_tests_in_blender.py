# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the repository's unit tests, inside Blender's Python or plain Python.

CI invokes it three ways:
    python .github/scripts/run_tests_in_blender.py                      # no bpy: skips *_bpy* modules
    python .github/scripts/run_tests_in_blender.py                      # with the bpy wheel installed: runs everything
    blender -b --python-exit-code 1 --python .github/scripts/run_tests_in_blender.py -- [args]

Tests live in tests/ as test_*.py and put ../source on sys.path themselves, so discovery
from the tests directory is enough. Modules whose name contains "_bpy" need Blender's
Python and are skipped when ``import bpy`` fails. Exit code is non-zero on any failure,
which ``--python-exit-code 1`` propagates to the Blender process.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "tests"

# Arguments after "--" belong to us, not to Blender (currently: optional test module names).
argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
pattern = os.environ.get("TEST_PATTERN", "test_*.py")

try:
    import bpy  # noqa: F401

    have_bpy = True
    print(f"[run_tests] Blender {bpy.app.version_string}, Python {sys.version.split()[0]}")
except ImportError:
    have_bpy = False
    print(f"[run_tests] bpy not importable; Python {sys.version.split()[0]}, skipping *_bpy* modules")

sys.path.insert(0, str(TESTS_DIR))
loader = unittest.defaultTestLoader
if argv:
    suite = loader.loadTestsFromNames(argv)
else:
    suite = unittest.TestSuite()
    for path in sorted(TESTS_DIR.glob(pattern)):
        if not have_bpy and "_bpy" in path.stem:
            print(f"[run_tests] skipping {path.name} (needs bpy)")
            continue
        suite.addTests(loader.loadTestsFromName(path.stem))

result = unittest.TextTestRunner(verbosity=2).run(suite)
if result.testsRun == 0:
    print("[run_tests] no tests ran", file=sys.stderr)
    sys.exit(1)
sys.exit(0 if result.wasSuccessful() else 1)
