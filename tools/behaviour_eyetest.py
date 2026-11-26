# SPDX-License-Identifier: GPL-3.0-or-later
"""Look at the behaviour editor and the player on a real screen, with real (simulated) mouse events.

Opens a Blender window, loads the add-on from this checkout, and for each world in tests/behaviour imports it with
"Behaviour as node graph", screenshots the window and the node editor, then plays it: the pointer is moved onto
what a sensor senses and clicked through Blender's own event queue, so the Play operator's modal handler, the ray
cast, the glow and the restore on Esc all run as they do for a person. Screenshots and a log go to --out.

    blender --factory-startup --enable-event-simulate --window-geometry 0 0 1600 1000 \\
        --python tools/behaviour_eyetest.py -- --out /tmp/eyetest [--worlds door counter] [--source DIR] [--keep-open]

``--enable-event-simulate`` makes Blender ignore the real mouse and keyboard while it runs, so a person's hand
cannot disturb it. What it cannot judge is taste: the screenshots are for a person (or an agent) to look at.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

import bpy

REPO = Path(__file__).resolve().parents[1]
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _arg(name, default=None, many=False):
    if name not in ARGS:
        return default
    at = ARGS.index(name) + 1
    if not many:
        return ARGS[at]
    values = []
    while at < len(ARGS) and not ARGS[at].startswith("--"):
        values.append(ARGS[at])
        at += 1
    return values


OUT = Path(_arg("--out", tempfile.mkdtemp(prefix="x3d_eyetest_")))
WORLDS = _arg("--worlds", ["door", "counter", "snake", "probe", "route-demo"], many=True)
KEEP_OPEN = "--keep-open" in ARGS
SOURCE = Path(_arg("--source", REPO / "source"))      # another checkout's add-on, to compare before and after
OUT.mkdir(parents=True, exist_ok=True)
LOG = {"blender": bpy.app.version_string, "source": str(SOURCE), "worlds": {}, "errors": []}


def note(world, key, value):
    LOG["worlds"].setdefault(world, {})[key] = value
    print(f"[eyetest] {world}: {key} = {value}")


# -- the add-on, from this checkout ---------------------------------------------------------------------------------

def load_addon():
    import addon_utils
    shelf = Path(tempfile.mkdtemp(prefix="x3d_eyetest_pkg_"))
    (shelf / "x3d_blender_io").symlink_to(SOURCE, target_is_directory=True)
    sys.path.insert(0, str(shelf))
    module = addon_utils.enable("x3d_blender_io", default_set=True, handle_error=None)
    if module is None:
        raise RuntimeError("the add-on did not enable")
    return module


# -- window helpers ---------------------------------------------------------------------------------------------------

def window():
    return bpy.context.window_manager.windows[0]


def areas(kind):
    return [a for a in window().screen.areas if a.type == kind]


def region_of(area, kind="WINDOW"):
    return next(r for r in area.regions if r.type == kind)


def shot(name, area=None):
    path = OUT / f"{name}.png"
    win = window()
    with bpy.context.temp_override(window=win, area=area or win.screen.areas[0]):
        if area is None:
            bpy.ops.screen.screenshot(filepath=str(path))
        else:
            bpy.ops.screen.screenshot_area(filepath=str(path))
    return path.name


def mouse(x, y, kind="MOUSEMOVE", value="NOTHING"):
    window().event_simulate(type=kind, value=value, x=int(x), y=int(y))


def key(kind):
    window().event_simulate(type=kind, value="PRESS")
    window().event_simulate(type=kind, value="RELEASE")


def screen_point(obj):
    """Window coordinates of ``obj``'s middle in the 3D viewport, or None when it is off screen."""
    from bpy_extras import view3d_utils
    from mathutils import Vector
    view = areas("VIEW_3D")[0]
    region = region_of(view)
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    middle = sum(corners, Vector()) / 8
    where = view3d_utils.location_3d_to_region_2d(region, view.spaces.active.region_3d, middle)
    if where is None or not (0 <= where.x < region.width and 0 <= where.y < region.height):
        return None
    return region.x + where.x, region.y + where.y


def overlaps(tree):
    """Pairs of nodes whose boxes overlap in the editor (should be none)."""
    scale = bpy.context.preferences.system.ui_scale or 1.0
    boxes = [(n.name, n.location.x, n.location.y, n.dimensions.x / scale, n.dimensions.y / scale) for n in tree.nodes]
    found = []
    for i, (a, ax, ay, aw, ah) in enumerate(boxes):
        for b, bx, by, bw, bh in boxes[i + 1:]:
            if ax < bx + bw and bx < ax + aw and ay - ah < by and by - bh < ay:
                found.append((a, b))
    return found


# -- one world --------------------------------------------------------------------------------------------------------

def fresh_scene(name):
    old = bpy.context.window.scene if bpy.context.window else None
    scene = bpy.data.scenes.new(name)
    window().scene = scene
    if old is not None and old.name != name:
        bpy.data.batch_remove(list(old.objects))     # or the next import's names get ".001"
        bpy.data.scenes.remove(old)
        bpy.data.orphans_purge(do_recursive=True)
    return scene


def node_editor_beside_viewport():
    """Split the 3D viewport and make the right half a (shader) node editor, as a person might have open."""
    view = areas("VIEW_3D")[0]
    with bpy.context.temp_override(window=window(), area=view, region=region_of(view)):
        bpy.ops.screen.area_split(direction="VERTICAL", factor=0.5)
    editor = max((a for a in window().screen.areas if a.type == "VIEW_3D"), key=lambda a: a.x)
    editor.type = "NODE_EDITOR"
    editor.ui_type = "ShaderNodeTree"
    return editor


def world_steps(world, tag=""):
    from x3d_blender_io import behaviour_nodes, behaviour_play
    path = REPO / "tests" / "behaviour" / f"{world}.x3d"
    scene = fresh_scene(f"eyetest_{world}{tag}")
    name = f"{world}{tag}"
    win = window()
    with bpy.context.temp_override(window=win, area=areas("VIEW_3D")[0], scene=scene):
        result = bpy.ops.import_scene.x3d(filepath=str(path), use_behaviour_graph=True)
    tree = scene.x3d_behaviour_tree
    note(name, "import", sorted(result))
    note(name, "tree", None if tree is None else {"nodes": len(tree.nodes), "links": len(tree.links)})
    shown = [a for a in win.screen.areas if a.type == "NODE_EDITOR" and a.spaces.active.node_tree == tree]
    note(name, "shown_in_editor", bool(shown))
    if hasattr(behaviour_nodes, "import_summary"):
        note(name, "summary", behaviour_nodes.import_summary(tree, shown[0] if shown else None) if tree else None)
    camera = scene.camera or next((o for o in scene.objects if o.type == "CAMERA"), None)
    view = areas("VIEW_3D")[0]
    if camera is not None:
        scene.camera = camera
        view.spaces.active.region_3d.view_perspective = "CAMERA"
        with bpy.context.temp_override(window=win, area=view, region=region_of(view)):
            bpy.ops.view3d.view_center_camera()
    yield 1.2                                     # let the editor draw, unstack and frame itself (view_all animates)
    note(name, "shot_import", shot(f"{name}-1-import"))
    if not shown:
        editors = [a for a in win.screen.areas if a.type == "NODE_EDITOR"]
        if not editors or tree is None:
            return
        editors[0].spaces.active.tree_type = behaviour_nodes.TREE_IDNAME      # an add-on that does not show it
        editors[0].spaces.active.node_tree = tree                              # (main before 2.7.5): the rig does
        note(name, "shown_by_rig", True)
        yield 0.5
        with bpy.context.temp_override(window=win, area=editors[0], region=region_of(editors[0])):
            bpy.ops.node.view_all()
        yield 0.6
        shown = editors
    editor = shown[0]
    editor.spaces.active.show_region_ui = True    # the sidebar: every field, the key table
    try:
        region_of(editor, "UI").active_panel_category = "Node"
    except (AttributeError, TypeError) as error:          # read-only in some versions: click the tab instead
        note(name, "sidebar_tab", f"{type(error).__name__}: {error}")
        ui = region_of(editor, "UI")
        tab = (ui.x + ui.width - 8, ui.y + ui.height - 75)
        mouse(*tab)
        mouse(*tab, "LEFTMOUSE", "PRESS")
        mouse(*tab, "LEFTMOUSE", "RELEASE")
    interp = next((n for n in tree.nodes if "Interpolator" in n.bl_idname or "Sequencer" in n.bl_idname), None)
    for n in tree.nodes:
        n.select = n is interp
    if interp is not None:
        tree.nodes.active = interp
    yield 0.4
    note(name, "shot_editor", shot(f"{name}-2-editor", editor))
    tree.x3d_blender_axes = True
    yield 0.3
    note(name, "shot_zup", shot(f"{name}-3-editor-zup", editor))
    tree.x3d_blender_axes = False

    note(name, "overlaps", overlaps(tree))
    note(name, "custom_colour_before_play", [n.name for n in tree.nodes if n.use_custom_color])
    # matrix_basis, not matrix_world: the world matrix is only brought up to date at the next redraw
    state = lambda o: (tuple(round(v, 4) for v in o.matrix_basis.translation),
                       tuple(round(v, 4) for v in o.matrix_basis.to_euler()), o.hide_viewport, o.hide_get())
    before_full = {o.name: state(o) for o in scene.objects}
    # Play, then click what a sensor senses, through the event queue
    with bpy.context.temp_override(window=win, area=editor, region=region_of(editor)):
        bpy.ops.x3d.behaviour_play("INVOKE_DEFAULT")
    player = behaviour_play._running["player"]
    note(name, "playing", player is not None)
    if player is None:
        return
    note(name, "not_simulated", list(player.sim.not_simulated))
    note(name, "not_applied", list(player.not_applied))
    targets = [o for o in scene.objects if o.type == "MESH" and player.sensors_for(o)]
    point = next((p for p in (screen_point(o) for o in targets) if p), None)
    note(name, "click_target", [o.name for o in targets][:4])
    before = {o.name: tuple(round(v, 4) for v in o.matrix_basis.translation) for o in scene.objects}
    if point is not None:
        mouse(*point)
        yield 0.2
        mouse(*point, "LEFTMOUSE", "PRESS")
        yield 0.1
        mouse(*point, "LEFTMOUSE", "RELEASE")
    yield 0.15
    glowing = [n.name for n in tree.nodes if n.use_custom_color]
    note(name, "glowing_after_click", glowing)
    note(name, "shot_glow", shot(f"{name}-4-play-glow"))
    yield 1.6
    moved = [o.name for o in scene.objects
             if tuple(round(v, 4) for v in o.matrix_basis.translation) != before.get(o.name)]
    note(name, "moved_while_playing", moved)
    note(name, "shot_later", shot(f"{name}-5-play-later"))
    mouse(*(point or (200, 200)))
    key("ESC")
    yield 0.4
    note(name, "stopped", behaviour_play._running["player"] is None)
    after = {o.name: tuple(round(v, 4) for v in o.matrix_basis.translation) for o in scene.objects}
    note(name, "restored", after == before)
    after_full = {o.name: state(o) for o in scene.objects}
    note(name, "not_restored", {k: [before_full.get(k), v] for k, v in after_full.items() if before_full.get(k) != v})
    note(name, "custom_colour_left", [n.name for n in tree.nodes if n.use_custom_color])
    note(name, "shot_restored", shot(f"{name}-6-restored"))


def run():
    load_addon()
    yield 0.5
    key("ESC")                                   # the splash screen
    yield 0.3
    plan = [(WORLDS[0], "-no-editor")] + [(world, "") for world in WORLDS]
    for index, (world, tag) in enumerate(plan):
        if index == 1:
            node_editor_beside_viewport()      # the first import runs with no node editor open, as after a restart
            yield 0.3
        try:
            yield from world_steps(world, tag)
        except Exception:
            LOG["errors"].append(f"{world}: {traceback.format_exc()}")
            print(traceback.format_exc())
    (OUT / "eyetest.json").write_text(json.dumps(LOG, indent=1))
    print(f"[eyetest] done: {OUT}")
    if not KEEP_OPEN:
        bpy.ops.wm.quit_blender()


_steps = run()


def _tick():
    try:
        return next(_steps)
    except StopIteration:
        return None
    except Exception:
        LOG["errors"].append(traceback.format_exc())
        (OUT / "eyetest.json").write_text(json.dumps(LOG, indent=1))
        print(traceback.format_exc())
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(_tick, first_interval=1.0, persistent=True)
