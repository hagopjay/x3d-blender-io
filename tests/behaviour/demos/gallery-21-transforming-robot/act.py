# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-21-transforming-robot. The eye test's own click on the cube has already started the unfold
just before the act. The act watches the whole unfold (12.5 s of simulator time: legs and body rise, arms, head, eyes,
chest lamp, wave, dance), shoots at several moments, clicks the robot again, and watches it fold back. Times come from the
simulator clock (`player.now`); every number is read from Blender data (world positions of DEF'd Transforms, visibility)."""
import math


def act(rig, ctx):
    scene, name, player = ctx["scene"], ctx["name"], ctx["player"]
    by_def = lambda d: [o for o in scene.objects if o.get("x3d_def") == d]
    shown = lambda o: not (o.hide_viewport or o.hide_get())
    groups = {d: by_def(d) for d in ("Body", "HeadRise", "WristR", "Bounce")}                 # found once: scanning the scene on every sample is slow
    mean = lambda d, axis: sum(o.matrix_world.translation[axis] for o in groups[d]) / max(1, len(groups[d]))   # X3D y is Blender z
    body, head, wrist = "Body", "HeadRise", "WristR"
    eyes, lamp, bounce = by_def("Eyes"), by_def("ChestLamp"), by_def("Bounce")
    lamp_scales, bz_dance = set(), []
    z_body, z_head, z_hand, x_hand, eyes_on, lamp_on = [], [], [], [], [], []
    shots = [2.0, 4.0, 5.6, 7.0, 9.5, 11.5]
    t0 = player.now

    def sample():
        z_body.append(mean(body, 2)); z_head.append(mean(head, 2)); z_hand.append(mean(wrist, 2))
        x_hand.append(abs(mean(wrist, 0) - mean(body, 0)))
        eyes_on.append(any(shown(o) for o in eyes)); lamp_on.append(any(shown(o) for o in lamp))
        lamp_scales.update(round(o.matrix_world.to_scale()[0], 2) for o in lamp if shown(o))
        bz_dance.append(mean("Bounce", 2))

    quiet = 0
    while player.now - t0 < 12.6 or (quiet < 6 and player.now - t0 < 30.0):       # the whole unfold, then until the dance has stopped moving
        yield 0.1
        sample()
        quiet = quiet + 1 if len(x_hand) > 1 and abs(x_hand[-1] - x_hand[-2]) < 0.01 and abs(z_hand[-1] - z_hand[-2]) < 0.01 and abs(bz_dance[-1] - bz_dance[-2]) < 0.01 else 0
        if shots and player.now - t0 >= shots[0]:
            rig.shot(f"{name}-act-unfold-{int(shots.pop(0) * 10):03d}")
    unfolded = dict(body=z_body[-1], hand_x=x_hand[-1], eyes=eyes_on[-1], lamp=lamp_on[-1])
    n_unfold = len(z_body)
    rig.shot(f"{name}-act-unfolded")
    point = next((rig.screen_point(o) for o in by_def("Torso") if rig.screen_point(o)), None)
    if point:
        rig.mouse(*point)
        yield 0.2
        rig.mouse(*point, "LEFTMOUSE", "PRESS")
        yield 0.1
        rig.mouse(*point, "LEFTMOUSE", "RELEASE")
    t1 = player.now
    mid_shot = False
    while player.now - t1 < 4.6:
        yield 0.1
        sample()
        if not mid_shot and player.now - t1 >= 1.3:
            mid_shot = True
            rig.shot(f"{name}-act-folding")
    rig.shot(f"{name}-act-folded")
    folded = dict(body=z_body[-1], hand_x=x_hand[-1], eyes=eyes_on[-1], lamp=lamp_on[-1])
    low = min(z_body)
    rig.note(name, "act_numbers", {
        "clicked": point is not None, "body_z_low_high_m": [round(low, 2), round(max(z_body), 2)], "head_z_low_high_m": [round(min(z_head), 2), round(max(z_head), 2)],
        "wrist_max_reach_from_body_m": round(max(x_hand), 2), "wrist_max_height_m": round(max(z_hand), 2), "unfolded_end": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in unfolded.items()},
        "folded_end": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in folded.items()}, "chest_lamp_scales_seen": sorted(lamp_scales),
        "bounce_z_range_m": round(max(bz_dance) - min(bz_dance), 2), "samples_unfold": n_unfold})
    rose = max(z_body) - low > 1.3 and max(z_head) - min(z_head) > 1.3
    arms_out = max(x_hand) > 1.8 and max(z_hand) > 4.0                      # reached out sideways, and the right hand waved up above the head line
    lights = any(eyes_on) and any(lamp_on) and len(lamp_scales) >= 3
    danced = max(bz_dance) - min(bz_dance) > 0.15
    back = point is not None and abs(folded["body"] - low) < 0.15 and folded["hand_x"] < 1.2 and not folded["eyes"] and not folded["lamp"]
    rig.note(name, "act_ok", bool(rose and arms_out and lights and danced and back and unfolded["eyes"] and unfolded["hand_x"] > 1.8))
