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
import math
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
STRICT = "--strict" in ARGS                          # exit with a failure code when a check or the run failed (CI)
SLOW = float(_arg("--slow", 1.0))                    # multiply every wait: software GL is slow
ACTIVITY_DEBUG = "--activity-debug" in ARGS          # one extra shot per world with crosses at the estimated sockets
ACTIVITY = "--activity" in ARGS                      # also look at the Activity overlay (door, counter, snake)
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


_DIGITS = ("ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE")


def type_key(char):
    """One typed character through the event queue, with its text, as a keyboard would send it (letters, digits,
    space, return; anything else raises, so a demo never types what it did not mean)."""
    kind = (char.upper() if char.isascii() and char.isalpha() else _DIGITS[int(char)] if char.isdigit()
            else {" ": "SPACE", "\n": "RET"}[char])
    shift = char.isalpha() and char.isupper()
    window().event_simulate(type=kind, value="PRESS", unicode=char if char != "\n" else "", shift=shift)
    window().event_simulate(type=kind, value="RELEASE", shift=shift)


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


DEMOS = REPO / "tests" / "behaviour" / "demos"


def world_path(world):
    """A test world (tests/behaviour/NAME.x3d) or a demo (tests/behaviour/demos/NAME/NAME.x3d)."""
    demo = DEMOS / world / f"{world}.x3d"
    return demo if demo.is_file() else REPO / "tests" / "behaviour" / f"{world}.x3d"


def demo_act(world):
    """A demo's own live-window act (demos/NAME/act.py, a generator act(rig, ctx)), or None."""
    import importlib.util
    act_file = DEMOS / world / "act.py"
    if not act_file.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"behaviour_demo_act_{world.replace('-', '_')}", act_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.act


RIG = None                                        # what a demo act may call; filled in below the helpers it names


def act_module():
    import importlib
    return importlib.import_module("x3d_blender_io.behaviour_activity")


def activity_checks(name):
    return LOG["worlds"].setdefault(name, {}).setdefault("activity_checks", {})


def check(name, key, ok, detail=None):
    """A pass / fail the script decides itself (not by eye), kept in the JSON."""
    activity_checks(name)[key] = {"ok": bool(ok), "detail": detail}
    print(f"[eyetest] {name}: check {key} = {'ok' if ok else 'FAILED'} {detail if detail is not None else ''}")


def activity_shots(name, editor, win, player, targets):
    """Mid-play screenshots of the node editor with the Activity overlay, at two zoom levels (``--activity``). The
    pointer clicks what a sensor senses again so events are in flight when the shot is taken; the counts the overlay
    shows are the player's own Activity, written next to the shots so the picture can be checked against numbers."""
    act = player.activity
    check(name, "activity_attached", act is not None)
    if act is None:
        return
    region = region_of(editor)
    point = next((p for p in (screen_point(o) for o in targets) if p), None)
    for zoom in ("fit", "close"):
        with bpy.context.temp_override(window=win, area=editor, region=region):
            bpy.ops.node.view_all()
            if zoom == "close":
                for _ in range(3):
                    bpy.ops.view2d.zoom_in()
        yield 0.3
        if point is not None:                         # an event stream while the shot is taken
            mouse(*point)
            yield 0.1
            mouse(*point, "LEFTMOUSE", "PRESS")
            yield 0.05
            mouse(*point, "LEFTMOUSE", "RELEASE")
        for key in ("a", "d", "w"):
            if player.has_keys():
                type_key(key)
        yield 0.18
        note(name, f"activity_{zoom}", {"shot": shot(f"{name}-activity-{zoom}", editor), "events": act.events,
                                        "deliveries": act.deliveries, "packets": len(act.packets(player.sim.now)),
                                        "overlay": __import__("x3d_blender_io.behaviour_activity", fromlist=["x"]).handler_active()})
        yield 0.1
    if ACTIVITY_DEBUG:
        mod = act_module()
        with bpy.context.temp_override(window=win, area=editor, region=region):
            bpy.ops.node.view_all()
        mod.set_debug(True)
        yield 0.4
        note(name, "activity_debug", shot(f"{name}-activity-debug", editor))
        mod.set_debug(False)
        yield 0.2
    mod = act_module()
    check(name, "overlay_drew", mod.draw_count() > 0, {"draws": mod.draw_count()})
    check(name, "events_equal_sim_log", act.events == player.sim.log.appended,
          {"activity": act.events, "log": player.sim.log.appended})
    check(name, "has_events", act.events > 0, act.events)
    report = act.report()
    check(name, "route_totals_add_up", sum(r["events"] for r in report["routes"]) == act.deliveries)


def activity_after_stop(name, editor, win, tree):
    """After the Esc the run ends with: no handler. Then the copy button, the panel checkboxes, a second Play ended by
    the Stop operator."""
    from x3d_blender_io import behaviour_play
    mod = act_module()
    check(name, "no_handler_after_esc", not mod.handler_active() and behaviour_play._running["player"] is None)
    scene = bpy.context.scene
    check(name, "properties_exist", all(hasattr(scene, p) for p in ("x3d_activity_show", "x3d_activity_stream",
                                                                    "x3d_activity_badges")))
    check(name, "panel_registered", hasattr(bpy.types, "X3D_PT_behaviour_play"))
    bpy.context.window_manager.clipboard = ""
    with bpy.context.temp_override(window=win, area=editor, region=region_of(editor)):
        result = bpy.ops.x3d.behaviour_activity_copy()
    clip = bpy.context.window_manager.clipboard
    check(name, "copy_fills_clipboard", "FINISHED" in result and "ROUTE" in clip and len(clip) > 40,
          {"result": sorted(result), "chars": len(clip)})
    view = areas("VIEW_3D")[0]
    view.spaces.active.show_region_ui = True
    try:
        region_of(view, "UI").active_panel_category = "X3D"
    except (AttributeError, TypeError):
        pass
    yield 0.5
    note(name, "shot_play_panel", shot(f"{name}-activity-panel", view))
    with bpy.context.temp_override(window=win, area=editor, region=region_of(editor)):
        bpy.ops.x3d.behaviour_play("INVOKE_DEFAULT")
    yield 0.6
    check(name, "second_play_has_handler", mod.handler_active() and behaviour_play._running["player"] is not None)
    with bpy.context.temp_override(window=win, area=editor, region=region_of(editor)):
        bpy.ops.x3d.behaviour_stop()
    mouse(300, 300)                                   # the modal operator sees the stop on its next event
    yield 0.8
    check(name, "no_handler_after_stop", not mod.handler_active() and behaviour_play._running["player"] is None)


def world_steps(world, tag=""):
    from x3d_blender_io import behaviour_nodes, behaviour_play
    path = world_path(world)
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
    # drag sensors: grab each object one senses and sweep the pointer through an arc, through the event queue
    draggers = {"PlaneSensor", "CylinderSensor", "SphereSensor"}
    if any(player.graph.nodes[s].node_type in draggers for sensors in player._sensors.values() for s in sensors):
        dragged = []
        for index, obj in enumerate(o for o in targets if any(player.graph.nodes[s].node_type in draggers
                                                               for s in player.sensors_for(o))):
            start = screen_point(obj)
            if start is None:
                continue
            before_turn = tuple(round(v, 4) for v in obj.matrix_world.to_euler())
            mouse(*start)
            yield 0.1
            mouse(*start, "LEFTMOUSE", "PRESS")
            yield 0.05
            radius = 90
            for step in range(1, 25):
                a = step / 24 * math.pi * 1.2
                mouse(start[0] + radius * math.sin(a), start[1] + radius * (1 - math.cos(a)) * 0.6)
                yield 0.04
                if step == 12:
                    shot(f"{name}-drag-{index}-{obj.name}")
            mouse(start[0] + radius * math.sin(math.pi * 1.2), start[1] + radius * (1 - math.cos(math.pi * 1.2)) * 0.6,
                  "LEFTMOUSE", "RELEASE")
            yield 0.1
            turned = {o.name for o in scene.objects
                      if tuple(round(v, 4) for v in o.matrix_basis.to_euler()) != before_full.get(o.name, (None, None))[1]}
            dragged.append({"grabbed": obj.name, "sensors": player.sensors_for(obj), "turned": sorted(turned)})
        note(name, "drags", dragged)
    # proximity sensors: let the camera fly (a scripted Viewpoint, or the viewport) and watch what lights
    if player.proximity_sensors():
        shown = lambda o: not (o.hide_viewport or o.hide_get())
        seen = {}
        for tick in range(90):                       # 9 seconds: one 8 s flight and a little more
            yield 0.1
            for o in scene.objects:
                seen.setdefault(o.name, set()).add(shown(o))
            if tick % 15 == 14:
                shot(f"{name}-fly-{tick // 15}")
        note(name, "proximity_toggled", sorted(n for n, states in seen.items() if len(states) == 2))
        camera_now = scene.camera.matrix_world.translation if scene.camera else None
        note(name, "camera_moved", camera_now is not None and
             tuple(round(v, 3) for v in camera_now) != before_full.get(scene.camera.name, ((None,),))[0])
    act = demo_act(world)
    if act is not None:                           # the demo's own act: its interactions, screenshots and checks
        try:
            yield from act(RIG, {"name": name, "scene": scene, "player": player, "editor": editor, "view": view,
                                 "window": win})
        except Exception:
            LOG["errors"].append(f"{name} act: {traceback.format_exc()}")
            note(name, "act_ok", False)
    if ACTIVITY and world in ("door", "counter", "snake") and not tag:
        try:
            yield from activity_shots(name, editor, win, player, targets)
        except Exception:
            LOG["errors"].append(f"{name} activity: {traceback.format_exc()}")
            note(name, "activity_ok", False)
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
    if ACTIVITY and world in ("door", "counter", "snake") and not tag:
        try:
            yield from activity_after_stop(name, editor, win, tree)
        except Exception:
            LOG["errors"].append(f"{name} activity after stop: {traceback.format_exc()}")
            note(name, "activity_after_stop_ok", False)


RIG = __import__("types").SimpleNamespace(mouse=mouse, key=key, type_key=type_key, shot=shot, note=note, screen_point=screen_point,
                                         areas=areas, region_of=region_of, window=window)


def _sha256(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_candidate():
    """The add-on source as a Loom candidate digest, byte for byte as loomkit's candidate() makes it: sha256 of every
    file keyed by POSIX relative path, written as sorted compact JSON, then hashed. Caches and archives are skipped
    the same way, so `loom accept` over the source folder finds this record current."""
    import hashlib
    skip_dirs = {"evidence", ".git", "node_modules", ".venv", "__pycache__", "receipts", "runs-local", ".work"}
    files = {}
    for path in sorted(SOURCE.rglob("*")):
        rel = path.relative_to(SOURCE)
        if (not path.is_file() or any(part in skip_dirs for part in rel.parts[:-1])
                or path.name in {"SHA256SUMS.txt", ".build-in-progress", ".DS_Store"} or path.suffix in {".pyc", ".zip"}):
            continue
        files[rel.as_posix()] = _sha256(path)
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def source_uncommitted():
    """True when the source folder differs from its git commit (or git cannot say): a development run, which
    `loom accept` refuses."""
    import subprocess
    try:
        r = subprocess.run(["git", "-C", str(SOURCE), "status", "--porcelain", "--", "."],
                           capture_output=True, text=True, timeout=10)
        return r.returncode != 0 or bool(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return True


def witness_record(subject_at_start):
    """The run as a Loom witness record (loom.witness/1, the fields loomkit's write_witness writes): the Host-eyes
    witness. Pass when nothing errored, every world imported with a node editor open was shown in it with no
    overlapping nodes, and every world that played was put back as it was. Error, not pass or fail, when the source
    changed while the run watched it."""
    import datetime
    import platform
    subject = source_candidate()
    worlds = {name: v for name, v in LOG["worlds"].items() if not name.endswith("-no-editor")}
    checks = {name: {"shown": v.get("shown_in_editor") is True, "overlaps": len(v.get("overlaps") or []),
                     "played": v.get("playing") is True, "restored": v.get("restored"),
                     "not_simulated": v.get("not_simulated"), "drags": len(v.get("drags") or []),
                     "proximity_toggled": v.get("proximity_toggled"), "act_ok": v.get("act_ok")}
              for name, v in worlds.items()}
    failed = [name for name, c in checks.items()
              if not c["shown"] or c["overlaps"] or (c["played"] and c["restored"] is not True) or c["act_ok"] is False]
    played = [name for name, c in checks.items() if c["played"]]
    if subject != subject_at_start:
        status, reason = "error", "the add-on source changed while the run watched it"
    else:
        status = "pass" if not failed and not LOG["errors"] else "fail"
        reason = (f"{len(worlds) - len(failed)} of {len(worlds)} worlds shown, laid out, played and restored"
                  + (f"; failed: {', '.join(failed)}" if failed else "")
                  + (f"; {len(LOG['errors'])} error(s)" if LOG["errors"] else ""))
    evidence = [{"path": p.name, "sha256": _sha256(p)} for p in sorted(OUT.glob("*.png"))]
    evidence.append({"path": "eyetest.json", "sha256": _sha256(OUT / "eyetest.json")})
    return {
        "schema": "loom.witness/1", "witness": "host-eyes", "status": status, "grade": "C", "origin": "executed",
        "subject_sha256": subject_at_start,
        "instrument": {"tool": "tools/behaviour_eyetest.py", "blender": bpy.app.version_string,
                       "flags": ["--factory-startup", "--enable-event-simulate"],
                       "window": [window().width, window().height], "os": f"{platform.system()} {platform.release()}",
                       "machine": platform.machine()},
        "measurements": checks,
        "coverage": {"worlds": len(worlds), "shown": sum(c["shown"] for c in checks.values()),
                     "played": len(played), "restored": sum(checks[n]["restored"] is True for n in played),
                     "names": sorted(worlds)},
        "limitations": ["taste is not judged: the screenshots are for a person", "one window size and UI scale",
                        "events come from Blender's queue, not the operating system's",
                        "Blender versions other than the one named were not run"],
        "evidence": evidence,
        "development": source_uncommitted(),
        "reason": reason,
        "finished_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
        "environment": {"python": sys.version.split()[0], "optimized": bool(sys.flags.optimize)},
    }


def failures():
    """What failed: every error, every activity check that is not ok, and a world that was played but not restored."""
    found = [f"error: {e.splitlines()[0][:120]}" for e in LOG["errors"]]
    for world, values in LOG["worlds"].items():
        found += [f"{world}: {key}" for key, c in values.get("activity_checks", {}).items() if not c["ok"]]
        found += [f"{world}: {key} is False" for key in ("act_ok", "activity_ok", "activity_after_stop_ok")
                  if values.get(key) is False]
        if values.get("playing") and values.get("restored") is not True:
            found.append(f"{world}: not restored")
    return found


def run():
    global SUBJECT_AT_START
    SUBJECT_AT_START = source_candidate()       # taken before the add-on loads; checked again at the end
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
    (OUT / "host-eyes.json").write_text(json.dumps(witness_record(SUBJECT_AT_START), sort_keys=True, indent=2) + "\n")
    print(f"[eyetest] done: {OUT}")
    failed = failures()
    (OUT / "eyetest-result.json").write_text(json.dumps({"failed": failed, "errors": len(LOG["errors"]),
                                                         "blender": bpy.app.version_string}, indent=1))
    if STRICT and failed:
        print("[eyetest] FAILED:", failed)
        sys.stdout.flush()
        os._exit(1)
    if not KEEP_OPEN:
        bpy.ops.wm.quit_blender()


_steps = run()


def _tick():
    try:
        return next(_steps) * SLOW
    except StopIteration:
        return None
    except Exception:
        LOG["errors"].append(traceback.format_exc())
        (OUT / "eyetest.json").write_text(json.dumps(LOG, indent=1))
        print(traceback.format_exc())
        if STRICT:
            sys.stdout.flush()
            os._exit(1)
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(_tick, first_interval=1.0, persistent=True)
