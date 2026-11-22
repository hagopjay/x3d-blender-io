# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Golden-file judge: each frozen scene's X3D 4.0 export, in canonical form, equals its committed golden file.

    python tools/io_sync/golden.py [--write] [--source DIR] [--scenes a,b]       # bpy wheel
    blender -b --factory-startup --python tools/io_sync/golden.py -- [--write]

Scenes: tests/frozen_scenes.py (built from data, so every process and Blender version builds the same scene).
Canonical form: tools/io_sync/x3d_c14n.py (run-describing head meta dropped, numbers rounded to 5 decimals).
Golden files: tests/golden/<scene>.c14n.x3d. A change that alters an export regenerates them with --write in the same
pull request, so the diff shows exactly what every frozen scene's file gained or lost. Exit 1 on any difference.
"""
from __future__ import annotations

import argparse
import difflib
import importlib
import os
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)
REPO = Path(__file__).resolve().parents[2]
GOLDEN = REPO / "tests" / "golden"
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def register(source):
    tmp = tempfile.mkdtemp(prefix="golden_addon_")
    (Path(tmp) / "io_scene_x3d").symlink_to(Path(source).resolve(), target_is_directory=True)
    sys.path.insert(0, tmp)
    addon = importlib.import_module("io_scene_x3d")
    try:
        addon.register()
    except ValueError:
        pass


def export_scene(name, folder):
    import bpy
    import frozen_scenes

    frozen_scenes.build(name)
    path = os.path.join(folder, f"{name}.x3d")
    result = bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False)
    assert result == {"FINISHED"}, result
    return path


def main(argv):
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    elif any(a.endswith(".py") for a in argv[:1]):
        argv = argv[1:]
    if "--python" in argv:   # blender -b --python golden.py with no "--": no arguments of ours
        argv = []
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--write", action="store_true")
    p.add_argument("--source", default=str(REPO / "source"))
    p.add_argument("--scenes", default="")
    p.add_argument("--golden", default=str(GOLDEN))
    args = p.parse_args(argv)
    register(args.source)
    import bpy
    import frozen_scenes
    import x3d_c14n

    golden = Path(args.golden)
    golden.mkdir(parents=True, exist_ok=True)
    names = [n for n in (args.scenes.split(",") if args.scenes else frozen_scenes.SCENES) if n]
    folder = tempfile.mkdtemp(prefix="golden_out_")
    differ = []
    for name in names:
        text = x3d_c14n.canonical_file(export_scene(name, folder))
        target = golden / f"{name}.c14n.x3d"
        if args.write:
            target.write_text(text, encoding="utf-8")
            print(f"[golden] wrote {target.relative_to(REPO)} ({len(text.splitlines())} lines)")
            continue
        old = target.read_text(encoding="utf-8") if target.exists() else ""
        if old == text:
            print(f"[golden] {name}: same as {target.name} ({len(text.splitlines())} lines)")
            continue
        differ.append(name)
        diff = list(difflib.unified_diff(old.splitlines(), text.splitlines(), f"golden/{target.name}", "export", n=1,
                                         lineterm=""))
        print(f"[golden] {name}: DIFFERS from {target.name} ({len(diff)} diff lines)")
        for line in diff[:30]:
            print("    " + line[:220])
    print(f"[golden] Blender {bpy.app.version_string}: {len(names) - len(differ)} of {len(names)} scenes match"
          + ("" if not differ else f"; differ: {', '.join(differ)} (regenerate with tools/io_sync/golden.py --write "
                                  "if the change is intended)"))
    return 1 if differ and not args.write else 0


if __name__ == "__main__":
    code = main(sys.argv)
    sys.stdout.flush()
    os._exit(code)
