# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for the piano demo (run by tools/behaviour_eyetest.py after its standard steps).

Types through Blender's event queue and checks what a person would see: the hammer dips and the lamp flashes on a key,
the three pedals light while Shift, Ctrl and Alt are held, an arrow and an F key go down the Integer chain, a click on
the sheet hands the keyboard to the StringSensor, the typed line reads what was typed (Backspace edits it), Enter stamps
it and hands the keyboard back. Objects are found by DEF (the importer's `x3d_def`), never by type.

The typed line itself is a Text node fed through a Script in the file; Play does not run Scripts, so the line is read
from the StringSensor's own outputs (what the status bar shows), not from a Blender text object.
"""


def act(rig, ctx):
    scene, name, player = ctx["scene"], ctx["name"], ctx["player"]
    sim = player.sim

    def by_def(def_name):
        found = [o for o in scene.objects if o.get("x3d_def") == def_name or
                 str(o.get("x3d_def_path") or "").split("/")[-1] == def_name]
        found = [o for o in found if o.parent is None or o.parent not in found]
        return (found or [scene.objects[def_name]])[0]

    shown = lambda obj: not (obj.hide_viewport or obj.hide_get())              # noqa: E731
    hammer, lamp_paint = by_def("Hammer"), None
    from bpy import data
    lamp_paint = next(m for m in data.materials if m.get("x3d_def") == "GlowPaint")
    alpha = lambda: lamp_paint.node_tree.nodes["Principled BSDF"].inputs["Alpha"].default_value    # noqa: E731
    glows = {"Shift": by_def("SoftGlow"), "Alt": by_def("SostGlow"), "Control": by_def("SustainGlow")}
    holds = {"Shift": "LEFT_SHIFT", "Control": "LEFT_CTRL", "Alt": "LEFT_ALT"}
    keys_light, type_light, sheet, lever = by_def("KeysLight"), by_def("TypeLight"), by_def("Sheet"), by_def("Lever")
    for obj in scene.objects:                                    # the import leaves everything selected: clear the outlines
        obj.select_set(False)
    out = {}
    typing = lambda: sim.machines["Typed"].listening                            # noqa: E731
    entered = lambda: sim.outputs.get(("Typed", "enteredText"), "")             # noqa: E731

    def click(obj):
        point = rig.screen_point(obj)
        rig.mouse(*point)
        yield 0.2
        rig.mouse(*point, "LEFTMOUSE", "PRESS")
        yield 0.15
        rig.mouse(*point, "LEFTMOUSE", "RELEASE")
        yield 0.3

    def type_line(text):
        for char in text:
            rig.type_key(char)
            yield 0.07

    # what the standard steps left: their click may have been on the sheet or the lever
    if typing():
        yield from type_line("x")
        rig.type_key("\n")
        yield 0.3
    if not sim.machines["Typed"].f["deletionAllowed"]:
        yield from click(lever)
    out["start_keyboard_mode"] = sim.machines["Keys"].listening and not typing()

    # 1. any key: the hammer strikes and the lamp flashes
    rest, rest_alpha, dip, flash = hammer.matrix_basis.translation.copy(), alpha(), 0.0, alpha()
    rig.type_key("a")
    for _ in range(14):
        yield 0.04
        dip = max(dip, (hammer.matrix_basis.translation - rest).length)
        flash = max(flash, alpha())
        if _ == 3:
            rig.shot(f"{name}-act-1-strike")
    yield 0.2
    out["act_hammer_dip"], out["act_lamp_alpha_peak"] = round(dip, 4), round(flash, 3)
    out["act_hammer_back"] = (hammer.matrix_basis.translation - rest).length < 1e-4

    # 2. the pedals: one at a time, then all three, lit while the modifier is held
    lit, dark = {}, {}
    window = rig.window()
    for modifier, held in holds.items():
        window.event_simulate(type=held, value="PRESS")
        yield 0.15
        lit[modifier] = [shown(glows[m]) for m in holds]
        window.event_simulate(type=held, value="RELEASE")
        yield 0.15
        dark[modifier] = [shown(glows[m]) for m in holds]
    for held in holds.values():
        window.event_simulate(type=held, value="PRESS")
    yield 0.2
    all_lit = [shown(glows[m]) for m in holds]
    rig.shot(f"{name}-act-2-pedals")
    for held in holds.values():
        window.event_simulate(type=held, value="RELEASE")
    yield 0.2
    out["act_pedals_lit"], out["act_pedals_dark"] = lit, dark
    out["act_all_pedals"] = all_lit
    pedals_ok = all(lit[m] == [m == other for other in holds] for m in holds) and all(not any(v) for v in dark.values()) \
        and all(all_lit) and not any(shown(glows[m]) for m in holds)

    # 3. arrow and F keys: the action key code goes down the Integer chain (ActionCode, then LastAction)
    codes = []
    for key in ("UP_ARROW", "F2", "LEFT_ARROW"):
        rig.key(key)
        yield 0.15
        codes.append(sim.outputs.get(("ActionCode", "triggerValue")))
    out["act_action_codes"] = codes

    # 4. click the sheet: the StringSensor has the keyboard (the lights say so), then type, delete, finish
    yield from click(sheet)
    out["act_typing_after_click"] = typing()
    out["act_lights_typing"] = [shown(keys_light), shown(type_light)]
    yield from type_line("Hi Pianos")
    out["act_typed"] = entered()
    rig.shot(f"{name}-act-3-typing")
    rig.key("BACK_SPACE")
    yield 0.15
    out["act_after_backspace"] = entered()
    yield from type_line(" 88")
    rig.type_key("\n")
    yield 0.4
    out["act_final"] = sim.outputs.get(("Typed", "finalText"))
    out["act_back_to_keys"] = not typing() and sim.machines["Keys"].listening
    out["act_lights_keys"] = [shown(keys_light), shown(type_light)]
    rig.shot(f"{name}-act-4-stamped")

    # 5. the keyboard works again
    dip_again = 0.0
    rig.type_key("z")
    for _ in range(10):
        yield 0.04
        dip_again = max(dip_again, (hammer.matrix_basis.translation - rest).length)
    out["act_hammer_dip_again"] = round(dip_again, 4)
    yield 0.4
    for key, value in out.items():
        rig.note(name, key, value)
    rig.note(name, "act_ok", bool(
        out["start_keyboard_mode"] and dip > 0.03 and flash > rest_alpha + 0.5 and out["act_hammer_back"] and pedals_ok
        and codes == [17, 2, 19] and out["act_typing_after_click"] and out["act_lights_typing"] == [False, True]
        and out["act_typed"] == "Hi Pianos" and out["act_after_backspace"] == "Hi Piano"
        and out["act_final"] == "Hi Piano 88" and out["act_back_to_keys"] and out["act_lights_keys"] == [True, False]
        and dip_again > 0.03))
