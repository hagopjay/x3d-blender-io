# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-23-dance-floor. The eye test's own click has already pressed one button, so the act does not
assume which choreography runs: it clicks A (Mexican wave), B (disco point), C (twirl) and A again, and for each watches
10 s of Blender data: the raise of the left elbow of the first dancer in each of the 6 columns (world height), the
largest turn of the dancers' root (Spin), and the colour of the floor tiles. It checks that
  A: columns lag one another (neighbouring columns correlate, but not perfectly), no big turn, tiles cyan-ish
  B: neighbouring columns are in antiphase and the next-but-one in phase, tiles magenta-ish
  C: the dancers turn through more than 2.5 rad, tiles green-ish
and that every one of the three is distinct, which fails if two choreographies ran at once or a button did not switch."""
import math

COLS, ROWS = 6, 3


def pearson(a, b):
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den > 1e-9 else 0.0


def act(rig, ctx):
    scene, name = ctx["scene"], ctx["name"]
    by_def = lambda d: [o for o in scene.objects if o.get("x3d_def") == d]
    elbows = [by_def(f"ForeL{c}_0") for c in range(COLS)]
    roots = [o for c in range(COLS) for r in range(ROWS) for o in by_def(f"Root{c}_{r}")]
    height = lambda os: sum(o.matrix_world.translation.z for o in os) / len(os)

    def tile_material(c, r):
        for o in by_def(f"Tile{c}_{r}"):
            for cand in (o, *o.children):
                if getattr(cand, "active_material", None) is not None:
                    return cand.active_material
        return None
    tiles = [tile_material(c, r) for c in range(COLS) for r in range(ROWS)]
    points = {}
    for ch in "ABC":
        points[ch] = next((rig.screen_point(o) for o in by_def(f"Button{ch}") + [k for o in by_def(f"Button{ch}") for k in o.children] if rig.screen_point(o)), None)

    def click(ch):
        pt = points[ch]
        rig.mouse(*pt)
        yield 0.2
        rig.mouse(*pt, "LEFTMOUSE", "PRESS")
        yield 0.1
        rig.mouse(*pt, "LEFTMOUSE", "RELEASE")

    def watch(seconds):
        series, turn, bright_frame = [[] for _ in range(COLS)], 0.0, (0.0, (0, 0, 0))
        for _ in range(int(seconds * 5)):
            yield 0.2
            for c in range(COLS):
                series[c].append(height(elbows[c]))
            turn = max(turn, max((o.parent.matrix_world.to_quaternion().inverted() @ o.matrix_world.to_quaternion()).angle for o in roots))
            cols = [tuple(m.diffuse_color[:3]) for m in tiles if m is not None]
            if cols:
                best = max(cols, key=sum)
                if sum(best) > bright_frame[0]:
                    bright_frame = (sum(best), best)
        spread = [max(s) - min(s) for s in series]
        return {"corr01": pearson(series[0], series[1]), "corr02": pearson(series[0], series[2]), "min_swing": min(spread),
                "turn": turn, "tile": bright_frame[1], "samples": len(series[0])}

    def hue_ok(ch, rgb):
        r, g, b = rgb
        return {"A": b > r and b > 0.02, "B": r > g and b > g and r > 0.02, "C": g > r and g > b and g > 0.02}[ch]

    results = {}
    yield 1.0
    for step, ch in enumerate("ABCA"):
        yield from click(ch)
        yield 1.5
        results[f"{ch}{step}"] = yield from watch(10 if step < 3 else 5)
        rig.shot(f"{name}-act-{step + 1}-{ch}")
    A, B, C, A2 = results["A0"], results["B1"], results["C2"], results["A3"]
    wave = lambda m: 0.15 < m["corr01"] < 0.98 and m["turn"] < 0.8 and m["min_swing"] > 0.15
    ok = (wave(A) and wave(A2)
          and B["corr01"] < -0.7 and B["corr02"] > 0.7 and B["turn"] < 0.8 and B["min_swing"] > 0.15
          and C["turn"] > 2.5 and C["min_swing"] > 0.15
          and hue_ok("A", A["tile"]) and hue_ok("B", B["tile"]) and hue_ok("C", C["tile"]) and hue_ok("A", A2["tile"]))
    shape = lambda m: {k: (round(v, 3) if isinstance(v, float) else v) for k, v in m.items() if k != "tile"} | {"tile_rgb": [round(x, 2) for x in m["tile"]]}
    rig.note(name, "act_numbers", {k: shape(v) for k, v in results.items()})
    rig.note(name, "act_ok", bool(ok))
