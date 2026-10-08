# SPDX-License-Identifier: GPL-3.0-or-later
"""Smoke test: enable the installed extension by its manifest id and import it.

Run by CI after `blender --command extension install-file`:
    blender -b --python-exit-code 1 --python .github/scripts/check_extension_enabled.py
"""
from __future__ import annotations

import importlib
import sys
import tomllib
from pathlib import Path

import bpy

manifest = Path(__file__).resolve().parents[2] / "source" / "blender_manifest.toml"
ext_id = tomllib.loads(manifest.read_text(encoding="utf-8"))["id"]
module_name = f"bl_ext.user_default.{ext_id}"

bpy.ops.preferences.addon_enable(module=module_name)
module = importlib.import_module(module_name)
print(f"Enabled {module_name} from {module.__file__} in Blender {bpy.app.version_string}")

# Importers and exporters must be registered as operators.
missing = [op for op in ("import_scene.x3d", "export_scene.x3d") if op.split(".")[1] not in dir(getattr(bpy.ops, op.split(".")[0]))]
if missing:
    print(f"Missing operators: {missing}", file=sys.stderr)
    sys.exit(1)
