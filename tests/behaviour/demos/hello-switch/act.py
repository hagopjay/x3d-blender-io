# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for the hello-switch demo (run by tools/behaviour_eyetest.py after its standard steps).

`act(rig, ctx)` is a generator: yield seconds to wait, Blender keeps drawing between yields. `rig` is the eye-test
module (rig.mouse, rig.key, rig.shot, rig.screen_point, rig.note); ctx holds name, scene, player, editor, view.
Everything a demo checks goes through rig.note(ctx["name"], key, value) so it lands in eyetest.json and the
Host-eyes witness; every screenshot through rig.shot so it is hashed as evidence.
"""


def act(rig, ctx):
    scene, name = ctx["scene"], ctx["name"]
    named = lambda name: scene.objects.get(name) or next(o for o in scene.objects if o.name.startswith(name))
    button, bulb, halo = named("ButtonBase"), named("Bulb"), named("Halo")      # by DEF: the world has two lights
    states = []
    for press in range(3):
        point = rig.screen_point(button)
        rig.mouse(*point)
        yield 0.2
        rig.mouse(*point, "LEFTMOUSE", "PRESS")
        yield 0.15
        rig.mouse(*point, "LEFTMOUSE", "RELEASE")
        yield 0.5
        states.append((not bulb.hide_viewport, not (halo.hide_viewport or halo.hide_get())))   # `on`, `visible`
        rig.shot(f"{name}-act-press-{press + 1}")
    rig.note(name, "act_lamp_states", states)
    lamp = [on for on, _ in states]
    rig.note(name, "act_ok", all(on == seen for on, seen in states) and lamp in ([True, False, True], [False, True, False]))
