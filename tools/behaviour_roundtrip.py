# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Import an X3D file with its behaviour as a node graph, optionally edit the graph, export it again.

    python tools/behaviour_roundtrip.py in.x3d out.x3d [--set NODE.field=value ...]

Prints the graph difference between the two files as JSON (behaviour_graph.difference). Needs ``bpy``."""
import importlib
import json
import sys
import tempfile
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "source"
tmp = tempfile.mkdtemp()
(Path(tmp) / "io_scene_x3d").symlink_to(SOURCE, target_is_directory=True)
sys.path.insert(0, tmp)
import bpy  # noqa: E402

addon = importlib.import_module("io_scene_x3d")
addon.register()
bpy.ops.wm.read_factory_settings(use_empty=True)
try:
    addon.register()
except ValueError:
    pass
bg = importlib.import_module("io_scene_x3d.behaviour_graph")

source, out = sys.argv[1:3]
bpy.ops.import_scene.x3d(filepath=source, use_behaviour_graph=True)
tree = bpy.context.scene.x3d_behaviour_tree
for edit in sys.argv[3:]:
    if edit == "--set":
        continue
    target, value = edit.split("=", 1)
    node, field_name = target.split(".", 1)
    tree.nodes[node].set_field(field_name, value)
bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40")
before = bg.Behaviour.from_x3d(Path(source).read_text(encoding="utf-8"))
after = bg.Behaviour.from_x3d(Path(out).read_text(encoding="utf-8"))
print("DIFFERENCE " + json.dumps(bg.difference(before, after)))
