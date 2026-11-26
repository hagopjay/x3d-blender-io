# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-02-disco-floor: let the ripple run, click the DJ deck (strobe), check tiles and camera moved."""


def act(rig, ctx):
    scene, name = ctx["scene"], ctx["name"]
    # the eye test imports a world more than once (names get .00N): the live copy has the highest suffix
    named = lambda n: max((o for o in scene.objects if o.name == n or o.name.startswith(n + ".")), key=lambda o: o.name)
    tiles = [named(f"Tile{x}_{y}") for x in range(8) for y in range(8)]
    emission = lambda o: tuple(round(v, 2) for v in next(n for n in o.active_material.node_tree.nodes if n.type == "BSDF_PRINCIPLED").inputs["Emission Color"].default_value[:3])
    heights = lambda: [round(o.matrix_basis.translation.z, 3) for o in tiles]
    cam = scene.camera
    cam0, h0, e0 = tuple(cam.matrix_world.translation), heights(), [emission(o) for o in tiles[:8]]
    yield 1.5
    rig.shot(f"{name}-act-ripple-1")
    yield 2.0
    rig.shot(f"{name}-act-ripple-2")
    h1, e1, cam1 = heights(), [emission(o) for o in tiles[:8]], tuple(cam.matrix_world.translation)
    deck = named("Deck")
    point = rig.screen_point(deck)
    for _ in range(60):                   # the camera orbits: wait until the deck is in view
        if point:
            break
        yield 0.5
        point = rig.screen_point(deck)
    rig.mouse(*point)
    yield 0.2
    rig.mouse(*point, "LEFTMOUSE", "PRESS")
    yield 0.1
    rig.mouse(*point, "LEFTMOUSE", "RELEASE")
    yield 0.4
    strobe = named("Strobe")
    on = not strobe.hide_viewport
    rig.shot(f"{name}-act-strobe")
    yield 2.5
    rig.shot(f"{name}-act-after")
    moved_cam = sum(abs(a - b) for a, b in zip(cam0, cam1))
    rig.note(name, "act_numbers", {"hop_changed": sum(a != b for a, b in zip(h0, h1)), "colour_changed": sum(a != b for a, b in zip(e0, e1)),
                                   "camera_moved": round(moved_cam, 2), "strobe_on": on})
    rig.note(name, "act_ok", sum(a != b for a, b in zip(e0, e1)) >= 4 and moved_cam > 0.5 and on)
