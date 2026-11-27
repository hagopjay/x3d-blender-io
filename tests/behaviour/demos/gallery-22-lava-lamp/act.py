# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-22-lava-lamp. Clicks COOL (the eye test's own click may have pressed any button), measures
how fast the seven blobs rise and sink (summed height change per second, from world positions), clicks HEAT and
measures again, clicks COOL and measures again; then presses COLOUR three times and records the lamp light's colour
after each fade. act_ok: HEAT is clearly faster than COOL, COOL after HEAT is slow again, and the lamp colour moved."""


def act(rig, ctx):
    scene, name, player = ctx["scene"], ctx["name"], ctx["player"]
    by_def = lambda d: [o for o in scene.objects if o.get("x3d_def") == d]
    blobs = [by_def(f"Blob{b}")[0] for b in range(7)]
    lamp = next((o for o in by_def("Lamp") if o.type == "LIGHT"), None) or next((o for o in scene.objects if o.type == "LIGHT"), None)
    height = lambda o: o.matrix_world.translation.z                     # X3D y is Blender z
    point = {k: next((rig.screen_point(o) for o in by_def(f"{k}Btn") if rig.screen_point(o)), None) for k in ("Heat", "Cool", "Colour")}

    def click(kind):
        p = point[kind]
        rig.mouse(*p)
        yield 0.2
        rig.mouse(*p, "LEFTMOUSE", "PRESS")
        yield 0.1
        rig.mouse(*p, "LEFTMOUSE", "RELEASE")

    def speed(seconds):
        """Summed |change of height| of the seven blobs per second of the player's clock."""
        start, last, total = player.now, [height(o) for o in blobs], 0.0
        while player.now - start < seconds:
            yield 0.2
            now = [height(o) for o in blobs]
            total += sum(abs(a - b) for a, b in zip(now, last))
            last = now
        return total / max(player.now - start, 1e-6)

    def tone():
        return tuple(round(c, 2) for c in lamp.data.color) if lamp else None

    yield 1.0
    yield from click("Cool")
    yield 3.0                                           # let the chasers settle
    slow = yield from speed(8)
    rig.shot(f"{name}-act-1-cool")
    yield from click("Heat")
    yield 3.0
    fast = yield from speed(8)
    rig.shot(f"{name}-act-2-heat")
    yield from click("Cool")
    yield 3.0
    slow_again = yield from speed(8)
    tones = [tone()]
    for k in range(3):
        yield from click("Colour")
        yield 4.0                                       # the chasers fade over 2.2 s
        tones.append(tone())
        rig.shot(f"{name}-act-{3 + k}-colour")
    moved = max(max(abs(a - b) for a, b in zip(t, tones[0])) for t in tones[1:]) if lamp else 0.0
    rig.note(name, "act_numbers", {"cool_m_per_s": round(slow, 2), "heat_m_per_s": round(fast, 2), "cool_again_m_per_s": round(slow_again, 2),
                                   "lamp_colour_after_each_colour_press": tones, "largest_lamp_channel_change": round(moved, 2)})
    rig.note(name, "act_ok", fast > 1.8 * slow and slow_again < 0.7 * fast and moved > 0.2)
