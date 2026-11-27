# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-25-weather-machine. The eye test's own click has already pressed one button, so the act
first reads which weather is on, then presses SNOW, RAIN, STORM, SUN, RAIN in turn and, after each, watches the player
clock for several seconds and checks that exactly that weather is alive: drops, flakes, splashes, flash plates and bolts,
the lighthouse beam, the rainbow arcs, the birds (visible and really moving), plus the ground colour and cloud size."""
import math


def act(rig, ctx):
    scene, name, player = ctx["scene"], ctx["name"], ctx["player"]
    by_def = lambda d: [o for o in scene.objects if o.get("x3d_def") == d]
    one = lambda d: by_def(d)[0]

    def shown(o):                                           # hidden itself or under a hidden parent
        while o is not None:
            if o.hide_viewport or o.hide_get():
                return False
            o = o.parent
        return True

    groups = {"rain": [one(f"Drop{i}") for i in range(60)], "snow": [one(f"Flake{i}") for i in range(36)], "splash": [one(f"Splash{i}") for i in range(18)],
              "bird": [one(f"Bird{i}") for i in range(4)]}
    arcs = [one(f"Arc{i}") for i in range(7)]
    flashes = [one("FlashBack"), one("FlashFront")] + [one(f"Bolt{t}") for t in "ABC"]
    beam = by_def("BeamArm")
    clouds = [one(f"Cloud{i}") for i in range(5)]
    ground = next(c for o in [one("Ground")] for c in [o, *o.children_recursive] if c.type == "MESH")
    roof = next(c for o in [one("RoofL")] for c in [o, *o.children_recursive] if c.type == "MESH")

    def base_colour(o):
        node = next(n for n in o.active_material.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        return tuple(node.inputs["Base Color"].default_value)[:3]

    pos = lambda o: tuple(o.matrix_world.translation) + tuple(o.matrix_world.to_scale())    # translation and scale (the splashes only grow)
    pilots = {w: one("Pilot" + w) for w in ("Rain", "Snow", "Storm", "Sun")}
    points = {}
    for w in pilots:
        b = one("Btn" + w)
        meshes = [c for c in [b, *b.children_recursive] if c.type == "MESH"]
        points[w] = next((p for p in (rig.screen_point(m) for m in meshes) if p), None)

    def click(w):
        rig.mouse(*points[w])
        yield 0.2
        rig.mouse(*points[w], "LEFTMOUSE", "PRESS")
        yield 0.1
        rig.mouse(*points[w], "LEFTMOUSE", "RELEASE")

    def until(t):
        while player.now < t:
            yield 0.1

    def moved(objs, before):
        return sum(1 for o, p in zip(objs, before) if math.dist(pos(o), p) > 0.02)

    def survey(seconds):
        """Watch `seconds` of player time; counts at the end of the window plus what was seen during it."""
        t0 = player.now
        start = {k: [pos(o) for o in v] for k, v in groups.items()}
        beam0 = [tuple(round(x, 3) for x in o.matrix_basis.to_quaternion()) for o in beam]
        flash_seen, beam_poses = 0, set()
        yield 0.9
        mid = {k: [pos(o) for o in v] for k, v in groups.items()}
        while player.now < t0 + seconds:
            yield 0.1
            flash_seen = max(flash_seen, sum(shown(o) for o in flashes))
            beam_poses.add(tuple(tuple(round(x, 2) for x in o.matrix_basis.to_quaternion()) for o in beam))
        out = {k: (sum(shown(o) for o in v), moved(v, mid[k])) for k, v in groups.items()}
        out["arcs"] = sum(shown(o) for o in arcs)
        out["flash_seen"] = flash_seen
        out["beam_poses"] = len(beam_poses) if any(shown(o) for o in beam) else 0
        out["pilots"] = [w for w, o in pilots.items() if shown(o)]
        out["ground"] = tuple(round(c, 2) for c in base_colour(ground))
        out["roof"] = tuple(round(c, 2) for c in base_colour(roof))
        out["cloud_scale"] = round(clouds[0].matrix_world.to_scale().x, 2)
        return out

    expect = {                                              # (drops visible, flakes, splashes, birds, arcs, flashes, beam, ground, roof, cloud)
        "Rain": lambda r: r["rain"][0] == 60 and r["rain"][1] >= 55 and r["splash"][0] == 18 and r["splash"][1] >= 3,
        "Snow": lambda r: r["snow"][0] == 36 and r["snow"][1] >= 30 and min(r["ground"]) > 0.8 and min(r["roof"]) > 0.8,
        "Storm": lambda r: r["flash_seen"] >= 2 and r["beam_poses"] >= 3 and r["cloud_scale"] > 1.5 and max(r["ground"]) < 0.4,
        "Sun": lambda r: r["arcs"] == 7 and r["bird"][0] == 4 and r["bird"][1] >= 3 and r["ground"][1] > r["ground"][0] + 0.2 and r["cloud_scale"] < 0.8,
    }
    quiet = {                                               # what must be absent when this weather is NOT on
        "Rain": lambda r: r["rain"] == (0, 0) and r["splash"] == (0, 0),
        "Snow": lambda r: r["snow"] == (0, 0),
        "Storm": lambda r: r["flash_seen"] == 0 and r["beam_poses"] == 0,
        "Sun": lambda r: r["arcs"] == 0 and r["bird"] == (0, 0),
    }
    results, ok = {}, True
    yield 1.0
    first = yield from survey(2)
    rig.shot(f"{name}-act-0-start")
    results["start"] = {"pilots": first["pilots"], "rain": first["rain"], "snow": first["snow"], "arcs": first["arcs"]}
    for step, w in enumerate(["Snow", "Rain", "Storm", "Sun", "Rain"], 1):
        yield from click(w)
        yield from until(player.now + 3.2)
        r = yield from survey(9.0 if w == "Storm" else 5.0)
        rig.shot(f"{name}-act-{step}-{w.lower()}")
        good = expect[w](r) and r["pilots"] == [w] and all(quiet[o](r) for o in quiet if o != w)
        results[f"{step}-{w}"] = {"ok": good, "pilots": r["pilots"], "drops": r["rain"], "flakes": r["snow"], "splashes": r["splash"], "birds": r["bird"], "arcs": r["arcs"],
                                  "flash_plates_max": r["flash_seen"], "beam_poses": r["beam_poses"], "ground": r["ground"], "roof": r["roof"], "cloud_scale": r["cloud_scale"]}
        ok = ok and good
    rig.note(name, "act_numbers", results)
    rig.note(name, "act_ok", ok)
