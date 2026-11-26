# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-14-slot-machine. The eye test's own click pulled the lever once just before the act; the act
watches that run, then pulls the lever itself with a real click and watches a second run. Times come from the simulator's
clock (`player.now`), not from counting yields. Checks per run: every reel shows exactly one symbol at all times, each reel
changes symbol many times with growing gaps (it decelerates), the reels stop one after another on the red 7 (symbol 0),
the lamps flash, the coins fly."""


def act(rig, ctx):
    scene, name, player = ctx["scene"], ctx["name"], ctx["player"]
    by_def = lambda d: [o for o in scene.objects if o.get("x3d_def") == d]
    shown = lambda o: not (o.hide_viewport or o.hide_get())
    sym = [[by_def(f"Sym{r}{s}")[0] for s in range(6)] for r in range(3)]
    coins = [by_def(f"Coin{c}")[0] for c in range(14)]
    lamps = [by_def(f"Lamp{i}")[0] for i in range(12)]
    lever = by_def("Lever")[0]

    def watch(seconds, shot_at=None, label=None):
        """Sample for `seconds` of simulator time; returns what happened."""
        start, ticks, last_now = player.now, [], player.now
        changes, last, never_blank, coin_max, lamp_max = [[], [], []], [None] * 3, True, 0, 0
        while player.now - start < seconds:
            yield 0.05
            if player.now != last_now:
                ticks.append(round(player.now - last_now, 3))     # how often the player's clock advances
                last_now = player.now
            t = player.now - start
            if shot_at is not None and t >= shot_at:
                rig.shot(f"{name}-act-{label}")
                shot_at = None
            for r in range(3):
                on = [s for s in range(6) if shown(sym[r][s])]
                if len(on) != 1:
                    never_blank = never_blank and (t < 0.05)
                    continue
                if on[0] != last[r]:
                    changes[r].append((round(t, 2), on[0]))
                    last[r] = on[0]
            coin_max = max(coin_max, sum(shown(c) for c in coins))
            lamp_max = max(lamp_max, sum(shown(l) for l in lamps))
        return changes, last, coin_max, lamp_max, sorted(ticks)[len(ticks) // 2] if ticks else None

    def summarise(res):
        changes, final, coins_seen, lamps_seen, tick = res
        gaps = [[round(b[0] - a[0], 2) for a, b in zip(c, c[1:])] for c in changes]
        mean = lambda xs: sum(xs) / len(xs)
        slows = all(len(g) >= 8 and max(g[-3:]) > max(g[:3]) for g in gaps)     # the longest late gap beats the longest early one (the player ticks in coarse steps, see median_player_tick_s)
        stop = [c[-1][0] if c else None for c in changes]
        return {"changes_per_reel": [len(c) for c in changes], "final_symbols": final, "last_change_s": stop, "slows_down": slows,
                "coins_in_flight_max": coins_seen, "lamps_lit_max": lamps_seen, "gaps_s": gaps, "median_player_tick_s": tick}

    yield 0.2
    run1 = yield from watch(9.0)
    rig.shot(f"{name}-act-1-after-first-pull")
    point = rig.screen_point(lever)
    if point is None:
        rig.note(name, "act_ok", False)
        return
    rig.mouse(*point)
    yield 0.2
    rig.mouse(*point, "LEFTMOUSE", "PRESS")
    yield 0.1
    rig.mouse(*point, "LEFTMOUSE", "RELEASE")
    run2 = yield from watch(7.0, shot_at=2.2, label="2-spinning")
    rig.shot(f"{name}-act-3-jackpot")
    s1, s2 = summarise(run1), summarise(run2)
    rig.note(name, "act_numbers", {"first_pull": s1, "second_pull_by_real_click": s2})
    stops_in_order = lambda s: all(a is not None for a in s["last_change_s"]) and s["last_change_s"][0] < s["last_change_s"][1] < s["last_change_s"][2]
    rig.note(name, "act_ok", s2["slows_down"] and s2["final_symbols"] == [0, 0, 0] and stops_in_order(s2) and s2["coins_in_flight_max"] >= 8 and s2["lamps_lit_max"] >= 8
             and s1["final_symbols"] == [0, 0, 0])
