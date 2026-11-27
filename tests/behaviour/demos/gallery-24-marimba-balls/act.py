# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-24-marimba-balls. The eye test's own click has already struck the first bar. The act then
clicks the three song buttons in turn (2, 3, 1) with real clicks; after each click it watches one whole lap on the
simulator's clock (`player.now`) and reads, from Blender data, when each bar dips (its world height drops below rest).
Checks per song: at least 85 % of the designed landings show a dip of the right bar within 0.3 s before to 2.0 s after the designed time
(measured from the press), the order of landings that are 0.9 s or more apart is right, exactly one lamp is lit, and the
balls come back to the rail. Then: two songs give two different landing orders, and a click on a bar dips that bar."""
N = 10
RAIL = 6.24                                                    # a parked ball's height (Blender z), as in build.py
# (bar, landing seconds after the song starts), copied from build.py's tables
SONGS = {
    0: [(0, 0.6), (1, 1.05), (2, 1.5), (3, 1.95), (4, 2.4), (5, 2.85), (6, 3.3), (7, 3.75), (8, 4.2), (9, 4.65), (0, 6.5), (4, 6.5), (8, 6.5)],
    1: [(5, 0.6), (6, 0.95), (4, 1.55), (7, 1.9), (3, 2.5), (8, 2.85), (2, 3.45), (9, 3.8), (1, 4.4), (0, 4.75)],
    2: [(0, 0.6), (2, 1.5), (4, 2.3), (6, 3.0), (8, 3.6), (9, 4.1), (7, 4.55), (5, 4.95), (3, 5.35), (1, 5.75)],
}
LAP = {0: 8.5, 1: 6.75, 2: 7.75}


def act(rig, ctx):
    scene, name, player = ctx["scene"], ctx["name"], ctx["player"]
    by_def = lambda d: [o for o in scene.objects if o.get("x3d_def") == d]
    shown = lambda o: not (o.hide_viewport or o.hide_get())
    bars = [by_def(f"Bar{n}") for n in range(N)]
    balls = [by_def(f"Ball{n}") for n in range(N)]
    lamps = [by_def(f"Lamp{s}") for s in range(3)]
    height = lambda objs: sum(o.matrix_world.translation.z for o in objs)         # Blender z is X3D y; summed over the DEF's objects
    lamps_lit = lambda: [s for s in range(3) if any(shown(o) for o in lamps[s])]

    def point(objs):
        for o in objs:
            pt = rig.screen_point(o)
            if pt:
                return pt
        return None

    def click(objs):
        pt = point(objs)
        if pt is None:
            return False
        rig.mouse(*pt)
        yield 0.2
        rig.mouse(*pt, "LEFTMOUSE", "PRESS")
        yield 0.1
        rig.mouse(*pt, "LEFTMOUSE", "RELEASE")
        return True

    yield 1.5
    rest = [height(b) for b in bars]
    dipped = lambda n: rest[n] - height(bars[n]) > 0.08 * len(bars[n])

    def lap(song, label):
        """click the song's button, watch one lap; returns the observations"""
        pt = point(by_def(f"Btn{song}"))
        rig.mouse(*pt)
        yield 0.2
        t0 = player.now
        rig.mouse(*pt, "LEFTMOUSE", "PRESS")
        yield 0.1
        rig.mouse(*pt, "LEFTMOUSE", "RELEASE")
        ok = pt is not None
        last_now, step_max = player.now, 0.0
        was = [False] * N
        lifted = [False] * N
        events, low, lit_seen, shot = [], [10.0] * N, set(), False
        while player.now - t0 < LAP[song] + 1.0:
            yield 0.05
            t = player.now - t0
            step_max, last_now = max(step_max, player.now - last_now), player.now
            for n in range(N):
                d = dipped(n)
                if d and not was[n]:
                    events.append((round(t, 2), n))
                was[n] = d
                hb = height(balls[n])
                low[n] = min(low[n], hb)
                lifted[n] = lifted[n] or (low[n] < 1.5 and hb > RAIL - 0.3 and t > 0.5)
            lit_seen.add(tuple(lamps_lit()))
            if not shot and t >= 2.0:
                rig.shot(f"{name}-act-song{song + 1}")
                shot = True
        want = SONGS[song]
        # The player ticks every 0.3 to 0.7 s here, and a bar's dip shows one or two ticks after the ball's landing, so a
        # designed landing time t is matched by a dip of that bar between t - 0.3 and t + 2.0 s after the press. Dips of
        # the previous song's last balls (already falling at the click) match no designed note and are ignored.
        matched = []
        for b, tw in want:
            near = [te for te, n in events if n == b and tw - 0.3 <= te <= tw + 2.0]
            matched.append(min(near) if near else None)
        hits = sum(m is not None for m in matched)
        offsets = [m - tw for m, (b, tw) in zip(matched, want) if m is not None]
        pairs = [(i, j) for i, (_, ta) in enumerate(want) for j, (_, tb) in enumerate(want) if tb - ta >= 0.9 and matched[i] is not None and matched[j] is not None]
        inversions = sum(matched[i] > matched[j] for i, j in pairs)
        order = [want[i][0] for i in sorted((i for i in range(len(want)) if matched[i] is not None), key=lambda i: (matched[i], i))]
        back = sum(lifted)                                            # balls seen dropped and then lifted back to the rail
        return {"clicked": ok, "landings_designed": len(want), "landings_matched": hits, "median_lag_s": round(sorted(offsets)[len(offsets) // 2], 2) if offsets else None,
                "order_pairs_checked": len(pairs), "order_inversions": inversions, "lamps_seen": sorted(lit_seen), "balls_back_on_rail": back, "events": events, "max_player_step_s": round(step_max, 2), "dip_order": order,
                "balls_reached_bars": sum(low[n] < 1.5 for n in range(N))}

    results = {}
    for song in (1, 2, 0):
        results[song] = yield from lap(song, f"song{song + 1}")
    # a click on a bar dips that bar (a song is playing, so other bars may dip too; bar 9 is not due for several seconds)
    bar = 9                                                         # song 1 is playing: bar 9 lands at 4.65 s, not in the next 1.5 s
    yield 0.2
    ok = yield from click(bars[bar])
    seen = set()
    for _ in range(14):
        yield 0.1
        seen.update(n for n in range(N) if dipped(n))
    rig.shot(f"{name}-act-bar-click")
    clicked_dips = bar in seen
    rig.note(name, "act_numbers", {"songs": {str(s + 1): r for s, r in results.items()}, "bar_click_ok": ok, "bars_dipped_after_bar_click": sorted(seen)})
    good = lambda r: (r["clicked"] and r["landings_matched"] >= 0.85 * r["landings_designed"] and r["order_inversions"] == 0 and r["balls_back_on_rail"] >= 8
                      and r["balls_reached_bars"] >= 8)
    only_one_lamp = all(len(l) == 1 for r in results.values() for l in r["lamps_seen"])
    different = len({tuple(r["dip_order"]) for r in results.values()}) == 3
    rig.note(name, "act_ok", all(good(r) for r in results.values()) and only_one_lamp and different and ok and clicked_dips)
