# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-19-step-sequencer. The eye test's own click has already toggled one pad (the first sensed
mesh), so the act reads the real state of all 32 pads, then:
1. watches the playhead for 5 s: every one of the 8 column glows must light, one at a time, and the flash plates of the
   column's 4 pads must light with it;
2. checks that every lit pad's voice moves and every unlit pad's voice stands still;
3. clicks three pads (two unlit, one lit): each must flip its cap, its voice's visibility and its clock (the voice moves
   if it is now lit, stops if not), and the 29 untouched pads must not change."""
ROWS, COLS = 4, 8


def act(rig, ctx):
    scene, name = ctx["scene"], ctx["name"]
    by_def = lambda d: [o for o in scene.objects if o.get("x3d_def") == d]
    shown = lambda o: not (o.hide_viewport or o.hide_get())
    ids = [f"{r}_{c}" for r in range(ROWS) for c in range(COLS)]
    caps = {p: by_def(f"Cap{p}") for p in ids}
    voices = {p: by_def(f"Voice{p}") for p in ids}
    flashes = {p: by_def(f"Flash{p}") for p in ids}
    glows = [by_def(f"Glow{c}") for c in range(COLS)]
    lit = lambda p: any(shown(o) for o in caps[p])
    voice_on = lambda p: any(shown(o) for o in voices[p])
    pose = lambda p: tuple(round(v, 3) for o in voices[p] for v in (*o.matrix_world.translation, *o.matrix_world.to_scale()))
    states = lambda: {p: (lit(p), voice_on(p)) for p in ids}

    def point(p):
        for o in by_def(f"Pad{p}"):
            pt = rig.screen_point(o)
            if pt:
                return pt
        return None

    def click(p):
        pt = point(p)
        if pt is None:
            return False
        rig.mouse(*pt)
        yield 0.2
        rig.mouse(*pt, "LEFTMOUSE", "PRESS")
        yield 0.1
        rig.mouse(*pt, "LEFTMOUSE", "RELEASE")
        return True

    def watch(seconds, tracked):
        """poses seen per tracked pad, plus the playhead: columns whose glow showed, worst glows at once, flash/glow mismatches"""
        poses = {p: set() for p in tracked}
        cols, most, mismatch = set(), 0, 0
        for _ in range(int(seconds * 5)):
            yield 0.2
            for p in tracked:
                poses[p].add(pose(p))
            on = [c for c in range(COLS) if any(shown(o) for o in glows[c])]
            cols.update(on)
            most = max(most, len(on))
            for c in on:
                mismatch += sum(not any(shown(o) for o in flashes[f"{r}_{c}"]) for r in range(ROWS))
        return poses, cols, most, mismatch

    yield 1.0
    s0 = states()
    consistent = all(a == b for a, b in s0.values())                      # cap and voice always agree
    lit0 = [p for p in ids if s0[p][0]]
    dark0 = [p for p in ids if not s0[p][0]]
    poses, cols, most, mismatch = yield from watch(5, ids)
    rig.shot(f"{name}-act-1-pattern")
    moving_lit = sum(len(poses[p]) > 3 for p in lit0)
    still_dark = sum(len(poses[p]) == 1 for p in dark0)

    flips, clicked = [], []
    for p in ("3_0", "3_3", "2_4"):
        before = states()
        ok = yield from click(p)
        yield 0.4
        after = states()
        changed = [q for q in ids if before[q] != after[q]]
        flips.append(ok and changed == [p] and after[p][0] != before[p][0] and after[p][0] == after[p][1])
        clicked.append((p, before[p][0], after[p][0]))
        rig.shot(f"{name}-act-2-click-{p}")
    # the pads just clicked: the lit ones must move, the darkened ones must stand still
    now = states()
    poses2, _, _, _ = yield from watch(3, [p for p, _, _ in clicked])
    new_moves = all((len(poses2[p]) > 2) == now[p][0] for p, _, _ in clicked)
    rig.shot(f"{name}-act-3-after")
    rig.note(name, "act_numbers", {"pads_lit_at_start": len(lit0), "cap_voice_disagree": [p for p in ids if s0[p][0] != s0[p][1]], "lit_pads_whose_voice_moved": moving_lit, "unlit_pads_voice_still": still_dark,
                                   "playhead_columns_seen": sorted(cols), "most_glows_at_once": most, "flash_missing_in_lit_column": mismatch,
                                   "clicks": clicked, "click_flips_ok": flips, "clicked_pads_move_iff_lit": new_moves})
    rig.note(name, "act_ok", consistent and len(lit0) > 0 and moving_lit == len(lit0) and still_dark == len(dark0) and len(cols) == COLS
             and most == 1 and mismatch == 0 and all(flips) and new_moves)
