# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The analytic ladder for X3D RigidBodyPhysics: what each fixture of tests/physics/fixtures should do, measured on a
trace from tools/physics_record.cjs (X_ITE) or tools/physics_blender_record.py (Blender).

    python tools/physics_judge.py trace.json [trace.json ...]          # one metrics object per trace, as JSON lines

The seven scenes and their measurements are those of x3d.loom's rigid-engines comparison (x3d.physics/rigid-engines,
lib/scenes.js at fc30c89, the owner's own code), ported to Python unchanged in what they measure, so the numbers sit next
to the ones measured there for Rapier, cannon-es, the bridge's own engine and X_ITE 16.6.0. A trace is sampled at its own
``fps`` from the authored state (sample k is time k / fps).

Analytic answers (from the same source):
* drop-bounce: a 0.5 m sphere falls 4.5 m onto a fixed box, bounce 0.5: first contact at 0.958 s, rebound apex
  0.25 x 4.5 = 1.125 m above the contact centre, at rest on 0.5.
* stack3: three 1 m boxes at rest, heights 0.5, 1.5 and 2.5, no sideways drift.
* slope-mu0.2: a 1 m cube on a 30 degree slope, Coulomb friction 0.2: a = g (sin 30 - 0.2 cos 30) = 3.19 m/s^2.
* pendulum-ball: a 0.25 m ball 2 m from a BallJoint pivot, released at 10 degrees: physical-pendulum period 2.8429 s.
* hinge-limit: a door spun at 3 rad/s into a hinge stop at 1.0 rad.
* slider-limit: a box thrown at 2 m/s along a SliderJoint into a stop at separation 1.5 m.
* billiards-head-on: two equal spheres, bounce 1, no gravity: the moving one stops, the other leaves at 3 m/s.
"""

from __future__ import annotations

import json
import math
import sys

G = 9.8


def _times(trace, name):
    n = len(trace["trajectories"][name]["p"])
    return [k * trace["dt"] for k in range(n)]


def _crossings(t, y, level=0.0):
    out = []
    for i in range(1, len(y)):
        if (y[i - 1] - level) < 0 <= (y[i] - level):
            f = (level - y[i - 1]) / (y[i] - y[i - 1])
            out.append(t[i - 1] + f * (t[i] - t[i - 1]))
    return out


def drop_bounce(tr):
    p = tr["trajectories"]["S"]["p"]
    t = _times(tr, "S")
    y = [q[1] for q in p]
    t_impact = math.sqrt(2 * 4.5 / G)
    first = next((i for i, v in enumerate(y) if t[i] > t_impact - 0.2 and v <= 0.55), -1)
    hi = -1.0
    if first >= 0:
        for i in range(first, len(y)):
            hi = max(hi, y[i])
            if y[i] < hi - 0.02 and hi > 0.6:
                break
    return {"apex above contact (m), analytic 1.125": round(hi - 0.5, 3),
            "final centre height (m), analytic 0.5": round(y[-1], 3),
            "first contact (s), analytic 0.958": round(t[first], 3) if first >= 0 else None}


def stack3(tr):
    T = tr["trajectories"]
    last = lambda k: T[k]["p"][-1]
    return {"B1 height (m), ideal 0.5": round(last("B1")[1], 4), "B2 height (m), ideal 1.5": round(last("B2")[1], 4),
            "B3 height (m), ideal 2.5": round(last("B3")[1], 4),
            "sideways drift of top box (m)": round(math.hypot(last("B3")[0], last("B3")[2]), 5)}


def slope(tr):
    th = math.pi / 6
    p = tr["trajectories"]["C"]["p"]
    t = _times(tr, "C")
    along = lambda q: q[0] * -math.cos(th) + q[1] * -math.sin(th)

    def at(s):
        i = next(i for i, x in enumerate(t) if x >= s - 1e-9)
        return along(p[i])
    d = at(1.5) - at(0.5)
    v = (at(1.5) - at(1.0)) / 0.5 - (at(1.0) - at(0.5)) / 0.5
    return {"downhill distance, 0.5 s to 1.5 s (m)": round(d, 3), "acceleration (m/s2), analytic 3.19": round(v / 0.5, 2)}


L, R, ANG = 2.0, 0.25, 10 * math.pi / 180
T0 = 2 * math.pi * math.sqrt((L * L + 0.4 * R * R) / (G * L))


def pendulum(tr):
    p = tr["trajectories"]["Bob"]["p"]
    t = _times(tr, "Bob")
    x = [q[0] for q in p]
    up = _crossings(t, x, 0)
    down = _crossings(t, [-v for v in x], 0)
    allc = sorted(up + down)
    per = (allc[-1] - allc[0]) / (len(allc) - 1) * 2 if len(allc) > 2 else float("nan")
    length = [math.hypot(q[0], q[1] - 5, q[2]) for q in p]
    amp = max(abs(v) for v in x[-200:])
    return {f"period (s), analytic {T0:.4f}": round(per, 4), "period error (%)": round((per - T0) / T0 * 100, 2),
            "max drift of arm length (m), ideal 0": round(max(length) - min(length), 4),
            "amplitude in the last 3 s (m), start 0.347": round(amp, 3)}


def hinge(tr):
    p = tr["trajectories"]["Door"]["p"]
    th = [math.atan2(-q[2], q[0] - 0.1) for q in p]
    mx = max(abs(v) for v in th)
    drift = max(abs(math.hypot(q[0] - 0.1, q[2]) - 0.5) for q in p)
    return {"max angle (rad), limit 1.0": round(mx, 3), "angle at 3 s (rad)": round(abs(th[-1]), 3),
            "door centre off its 0.5 m circle (m), ideal 0": round(drift, 4)}


def slider(tr):
    p = tr["trajectories"]["Car"]["p"]
    xs, ys, zs = [q[0] for q in p], [q[1] for q in p], [q[2] for q in p]
    return {"max separation (m), limit 1.5": round(max(xs), 3), "x at 3 s (m)": round(xs[-1], 3),
            "sag (m), ideal 0": round(3 - min(ys), 4), "z drift (m)": round(max(abs(z) for z in zs), 4)}


def billiards(tr):
    T = tr["trajectories"]

    def v(k):
        p = T[k]["p"]
        n = len(p) - 1
        return (p[n][0] - p[n - 6][0]) / (6 * tr["dt"])
    va, vb = v("A"), v("B")
    return {"A speed after (m/s), analytic 0": round(va, 3), "B speed after (m/s), analytic 3": round(vb, 3),
            "momentum error (%)": round(abs(va + vb - 3) / 3 * 100, 2),
            "energy error (%)": round(abs(0.5 * (va * va + vb * vb) - 4.5) / 4.5 * 100, 2)}


SCENES = {"drop-bounce.x3d": (drop_bounce, 3), "stack3.x3d": (stack3, 6), "slope-mu0.2.x3d": (slope, 2),
          "pendulum-ball.x3d": (pendulum, 15), "hinge-limit.x3d": (hinge, 3), "slider-limit.x3d": (slider, 3),
          "billiards-head-on.x3d": (billiards, 2)}


def judge(trace):
    fn, _seconds = SCENES[trace["file"]]
    return fn(trace)


def free_fall_error(trace, body, y0, steps_per_frame):
    """Distance from the discrete semi-implicit Euler answer (playbook pattern 1) at each frame before contact:
    y_n = y0 - g h^2 n (n + 1) / 2 with h = dt / steps_per_frame and n = steps_per_frame x frame."""
    h = trace["dt"] / steps_per_frame
    worst = 0.0
    for k, q in enumerate(trace["trajectories"][body]["p"]):
        n = k * steps_per_frame
        exact = y0 - G * h * h * n * (n + 1) / 2
        if exact < 0.6:
            break
        worst = max(worst, abs(q[1] - exact))
    return worst


if __name__ == "__main__":
    for path in sys.argv[1:]:
        with open(path, encoding="utf-8") as f:
            tr = json.load(f)
        print(json.dumps({"trace": path, "engine": tr["engine"], "file": tr["file"], "metrics": judge(tr)}))
