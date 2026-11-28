"""Show off the editor style: a busy behaviour world, the node editor beside the viewport, a preset on, playing.

    Blender --factory-startup --python tools/style_demo.py -- [--world gallery-02-disco-floor] [--preset PARTY]

No splash; the add-on is loaded from this checkout. With STYLE_DEMO_STATUS=path the window writes a line and a
screenshot there once it is up.
"""
import os
import sys
import tempfile
from pathlib import Path

import addon_utils
import bpy

bpy.context.preferences.view.show_splash = False
REPO = Path(__file__).resolve().parents[1]
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
WORLD = ARGS[ARGS.index("--world") + 1] if "--world" in ARGS else "gallery-02-disco-floor"
PRESET = ARGS[ARGS.index("--preset") + 1] if "--preset" in ARGS else "PARTY"

shelf = Path(tempfile.mkdtemp(prefix="x3d_style_pkg_"))
(shelf / "x3d_blender_io").symlink_to(REPO / "source", target_is_directory=True)
sys.path.insert(0, str(shelf))
addon_utils.enable("x3d_blender_io", default_set=True, handle_error=None)


def region(area, kind="WINDOW"):
    return next(r for r in area.regions if r.type == kind)


def go():
    from x3d_blender_io import behaviour_nodes
    win = bpy.context.window_manager.windows[0]
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    view = max((a for a in win.screen.areas if a.type == "VIEW_3D"), key=lambda a: a.width)
    with bpy.context.temp_override(window=win, area=view, region=region(view)):
        bpy.ops.screen.area_split(direction="VERTICAL", factor=0.55)
    views = sorted((a for a in win.screen.areas if a.type == "VIEW_3D"), key=lambda a: a.x)
    editor = views[-1]
    editor.type = "NODE_EDITOR"
    editor.spaces.active.tree_type = behaviour_nodes.TREE_IDNAME
    path = REPO / "tests" / "behaviour" / "demos" / WORLD / f"{WORLD}.x3d"
    with bpy.context.temp_override(window=win, area=views[0], region=region(views[0])):
        bpy.ops.import_scene.x3d(filepath=str(path), use_behaviour_graph=True)
    scene = bpy.context.scene
    tree = scene.x3d_behaviour_tree
    editor.spaces.active.node_tree = tree
    editor.spaces.active.show_region_ui = True
    camera = next((o for o in scene.objects if o.type == "CAMERA"), None)
    if camera is not None:
        scene.camera = camera
        views[0].spaces.active.region_3d.view_perspective = "CAMERA"
    views[0].spaces.active.shading.type = "MATERIAL"
    scene.x3d_activity_show = True
    with bpy.context.temp_override(window=win, area=editor, region=region(editor)):
        bpy.ops.x3d.style_preset(preset=PRESET)
        bpy.ops.node.view_all()
    for o in scene.objects:
        o.select_set(False)                         # the tiles, not orange selection outlines

    def close_up():
        """A big graph fits as a thin strip: after the editor's own frame-all, frame its top rows, close enough to
        read the colours."""
        nodes = sorted(tree.nodes, key=lambda n: (-n.location.y, n.location.x))[:16]
        for n in tree.nodes:
            n.select = n in nodes
        with bpy.context.temp_override(window=win, area=editor, region=region(editor)):
            bpy.ops.node.view_selected()
        for n in tree.nodes:
            n.select = False
        return None
    bpy.app.timers.register(close_up, first_interval=3.0)

    def play():
        with bpy.context.temp_override(window=win, area=editor, region=region(editor)):
            bpy.ops.x3d.behaviour_play("INVOKE_DEFAULT")
        try:
            region(editor, "UI").active_panel_category = "X3D"
        except Exception:       # noqa: BLE001
            pass
        note = os.environ.get("STYLE_DEMO_STATUS")
        if note:
            def snap():
                with bpy.context.temp_override(window=win):
                    bpy.ops.screen.screenshot(filepath=str(Path(note).with_suffix(".png")))
                Path(note).write_text(f"[style] {WORLD}: {len(tree.nodes)} nodes, theme {scene.x3d_style.theme}\n")
                return None
            bpy.app.timers.register(snap, first_interval=4.5)
        return None
    bpy.app.timers.register(play, first_interval=1.0)
    return None


bpy.app.timers.register(go, first_interval=1.0)
