# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Spring bones (hair, tails, cloth strips, jiggle): the Python twin of x3d.loom ``x3d.springbone/src/springbone-core.js``.

Own code, written from the behaviour description in x3d.loom ``x3d.springbone/SPEC.md``; no vendor source. The order of
operations follows the JavaScript file line for line, so the two agree to rounding (tests/springbone: the JavaScript
golden trace is matched to 1e-12 m, and the replay hash is equal). No bpy here; ``springbone_blender`` drives it from
an armature.

Conventions: vectors are 3-tuples or lists; quaternions [x, y, z, w]; an affine is (L, t) with L a row-major 9-list.
A joint's local frame follows the X3D Transform rule T(translation) T(center) R SO S SO^-1 T(-center); a joint's
particle sits at its pivot (the joint's world matrix applied to its center).
"""

from __future__ import annotations

import math

VERSION = "0.1.0"

# --- vectors --------------------------------------------------------------------------------------------------------


def add(a, b):
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]


def sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def mul(a, s):
    return [a[0] * s, a[1] * s, a[2] * s]


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def length(a):
    return math.sqrt(dot(a, a))


def unit(a):
    n = length(a)
    return mul(a, 1 / n) if n > 1e-300 else [0.0, 0.0, 0.0]


def lerp(a, b, t):
    return a + (b - a) * t


def clamp01(x):
    return 0.0 if x < 0 else 1.0 if x > 1 else x


# --- quaternions ----------------------------------------------------------------------------------------------------


def qmul(a, b):
    return [a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1],
            a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
            a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3],
            a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2]]


def qconj(q):
    return [-q[0], -q[1], -q[2], q[3]]


def qnorm(q):
    n = math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3])
    return [q[0] / n, q[1] / n, q[2] / n, q[3] / n] if n > 0 else [0.0, 0.0, 0.0, 1.0]


def q_from_axis_angle(axis, angle):
    a = unit(axis)
    if a[0] == 0 and a[1] == 0 and a[2] == 0:
        return [0.0, 0.0, 0.0, 1.0]
    s = math.sin(angle / 2)
    return [a[0] * s, a[1] * s, a[2] * s, math.cos(angle / 2)]


def q_to_axis_angle(q0):
    q = qnorm(q0)
    if q[3] < 0:
        q = [-q[0], -q[1], -q[2], -q[3]]
    s = math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2])
    if s < 1e-15:
        return [0.0, 0.0, 1.0, 0.0]
    return [q[0] / s, q[1] / s, q[2] / s, 2 * math.atan2(s, q[3])]


def q_from_to(u0, v0):
    u, v = unit(u0), unit(v0)
    d = dot(u, v)
    if d >= 1 - 1e-15:
        return [0.0, 0.0, 0.0, 1.0]
    if d <= -1 + 1e-15:
        ax = cross(u, [1, 0, 0])
        if length(ax) < 1e-6:
            ax = cross(u, [0, 1, 0])
        ax = unit(ax)
        return [ax[0], ax[1], ax[2], 0.0]
    c = cross(u, v)
    return qnorm([c[0], c[1], c[2], 1 + d])


def q_slerp(a, b0, t):
    b = b0
    d = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]
    if d < 0:
        b = [-b[0], -b[1], -b[2], -b[3]]
        d = -d
    if d > 1 - 1e-12:
        return qnorm([lerp(a[i], b[i], t) for i in range(4)])
    th = math.acos(d)
    s = math.sin(th)
    wa, wb = math.sin((1 - t) * th) / s, math.sin(t * th) / s
    return [a[i] * wa + b[i] * wb for i in range(4)]


# --- 3x3 and affine -------------------------------------------------------------------------------------------------


def m3_from_quat(q0):
    x, y, z, w = qnorm(q0)
    return [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
            2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
            2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]


def m3mul(A, B):
    return [A[r * 3] * B[c] + A[r * 3 + 1] * B[3 + c] + A[r * 3 + 2] * B[6 + c] for r in range(3) for c in range(3)]


def m3v(A, v):
    return [A[0] * v[0] + A[1] * v[1] + A[2] * v[2], A[3] * v[0] + A[4] * v[1] + A[5] * v[2],
            A[6] * v[0] + A[7] * v[1] + A[8] * v[2]]


def m3T(A):
    return [A[0], A[3], A[6], A[1], A[4], A[7], A[2], A[5], A[8]]


def m3col(A, c):
    return [A[c], A[3 + c], A[6 + c]]


def m3inv(A):
    a, b, c, d, e, f, g, h, i = A
    co0, co1, co2 = e * i - f * h, f * g - d * i, d * h - e * g
    det = a * co0 + b * co1 + c * co2
    k = 1 / det
    return [co0 * k, (c * h - b * i) * k, (b * f - c * e) * k, co1 * k, (a * i - c * g) * k, (c * d - a * f) * k,
            co2 * k, (b * g - a * h) * k, (a * e - b * d) * k]


def quat_of_linear(A):
    c0, c1, c2 = unit(m3col(A, 0)), unit(m3col(A, 1)), unit(m3col(A, 2))
    m00, m10, m20 = c0
    m01, m11, m21 = c1
    m02, m12, m22 = c2
    tr = m00 + m11 + m22
    if tr > 0:
        s = math.sqrt(tr + 1) * 2
        q = [(m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s, 0.25 * s]
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1 + m00 - m11 - m22) * 2
        q = [0.25 * s, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s]
    elif m11 > m22:
        s = math.sqrt(1 + m11 - m00 - m22) * 2
        q = [(m01 + m10) / s, 0.25 * s, (m12 + m21) / s, (m02 - m20) / s]
    else:
        s = math.sqrt(1 + m22 - m00 - m11) * 2
        q = [(m02 + m20) / s, (m12 + m21) / s, 0.25 * s, (m10 - m01) / s]
    return qnorm(q)


IDENTITY = ([1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0], [0.0, 0.0, 0.0])


def compose(A, B):
    return (m3mul(A[0], B[0]), add(m3v(A[0], B[1]), A[1]))


def apply_point(A, p):
    return add(m3v(A[0], p), A[1])


def affine_from_fields(f):
    R = m3_from_quat(f.get("rotation") or [0, 0, 0, 1])
    s = f.get("scale") or [1, 1, 1]
    L = R
    if s[0] != 1 or s[1] != 1 or s[2] != 1:
        SO = m3_from_quat(f.get("scaleOrientation") or [0, 0, 0, 1])
        L = m3mul(R, m3mul(SO, m3mul([s[0], 0, 0, 0, s[1], 0, 0, 0, s[2]], m3T(SO))))
    c = f.get("center") or [0, 0, 0]
    tr = f.get("translation") or [0, 0, 0]
    return (L, sub(add(tr, c), m3v(L, c)))


# --- curves and tuning ----------------------------------------------------------------------------------------------


def eval_curve(keys, t):
    if not keys:
        return 1
    if t <= keys[0][0]:
        return keys[0][1]
    for i in range(1, len(keys)):
        if t <= keys[i][0]:
            a, b = keys[i - 1], keys[i]
            w = b[0] - a[0]
            return lerp(a[1], b[1], (t - a[0]) / w) if w > 0 else b[1]
    return keys[-1][1]


def _roots_sp(frequency_hz, zeta, rate):
    w, h = 2 * math.pi * frequency_hz, 1 / rate
    if zeta < 1:
        wd = w * math.sqrt(1 - zeta * zeta)
        return 2 * math.exp(-zeta * w * h) * math.cos(wd * h), math.exp(-2 * zeta * w * h)
    r = math.sqrt(zeta * zeta - 1)
    return math.exp((-zeta + r) * w * h) + math.exp((-zeta - r) * w * h), math.exp(-2 * zeta * w * h)


def tuning_from_physical(frequency_hz, zeta, rate, model="POSITION"):
    """(frequency, damping ratio) at ``rate`` steps per second -> the damping and elasticity that sample it exactly."""
    S, P = _roots_sp(frequency_hz, zeta, rate)
    if model == "FORCE":
        d, e = 1 - P, 1 + P - S
    else:
        e = 1 - (S - P)
        d = 1 - P / (S - P)
    return {"damping": d, "elasticity": e, "feasible": 0 <= e <= 1 and 0 <= d <= 1, "model": model}


def physical_from_tuning(d, e, rate, model="POSITION"):
    """What oscillator (damping, elasticity) at ``rate`` behaves like for small motion."""
    h = 1 / rate
    S = 2 - d - e if model == "FORCE" else (1 - e) * (2 - d)
    P = 1 - d if model == "FORCE" else (1 - e) * (1 - d)
    disc = S * S - 4 * P
    if P <= 0:
        return {"frequency": math.inf, "dampingRatio": math.inf, "oscillates": False}
    if disc < 0:
        r, th = math.sqrt(P), math.atan2(math.sqrt(-disc), S)
        sigma, wd = math.log(r) / h, th / h
        w = math.sqrt(sigma * sigma + wd * wd)
        return {"frequency": w / (2 * math.pi), "dampingRatio": -sigma / w, "oscillates": True, "periodSteps": 2 * math.pi / th}
    l1, l2 = (S + math.sqrt(disc)) / 2, (S - math.sqrt(disc)) / 2
    if l1 <= 0 or l2 <= 0:
        return {"frequency": math.nan, "dampingRatio": math.nan, "oscillates": True}
    s1, s2 = math.log(l1) / h, math.log(l2) / h
    w = math.sqrt(s1 * s2)
    return {"frequency": w / (2 * math.pi), "dampingRatio": -(s1 + s2) / (2 * w), "oscillates": False}


# --- colliders ------------------------------------------------------------------------------------------------------

AXIS = {"X": 0, "Y": 1, "Z": 2}


def prepare_collider(c):
    W = c.get("world") or IDENTITY
    sc = length(m3col(W[0], 0))
    center = apply_point(W, c.get("center") or [0, 0, 0])
    axis = c.get("axis") or [0, 0, 0]
    if axis[0] or axis[1] or axis[2]:
        direction = unit(m3v(W[0], axis))
    else:
        direction = unit(m3col(W[0], AXIS[c.get("direction") or "Y"]))
    radius = c.get("radius", 0.5)
    r0 = radius * sc
    r1 = (c["radius2"] if c.get("radius2", 0) > 0 else radius) * sc
    h = (c.get("height") or 0) * sc
    out = {"shape": c.get("shape") or "SPHERE", "inside": (c.get("bound") or "OUTSIDE") == "INSIDE", "center": center,
           "dir": direction, "r0": r0, "r1": r1, "prepared": True}
    if out["shape"] == "CAPSULE":
        seg = max(h - r0 - r1, 0)
        out["a"] = add(center, mul(direction, -(h / 2 - r0)))      # caps inside height, centred: r0 at -axis, r1 at +axis
        out["b"] = add(center, mul(direction, h / 2 - r1))
        out["segLen"] = seg
        if seg <= 0:
            out["shape"] = "SPHERE"
            out["r0"] = max(r0, r1)
    return out


def _sphere_bound(p, q, R, pr, inside):
    d = sub(p, q)
    n = length(d)
    if not inside:
        m = R + pr
        if n < m:
            nn = mul(d, 1 / n) if n > 1e-300 else [0, 1, 0]
            return add(q, mul(nn, m)), True
        return p, False
    m = R - pr
    if n > m:
        nn = mul(d, 1 / n) if n > 1e-300 else [0, 1, 0]
        return add(q, mul(nn, max(m, 0))), True
    return p, False


def round_cone_sphere(p, a, b, r0, r1):
    ab = sub(b, a)
    L = length(ab)
    if L < 1e-300:
        return a, max(r0, r1)
    u = mul(ab, 1 / L)
    ap = sub(p, a)
    tp = dot(ap, u)
    q = length(sub(ap, mul(u, tp)))
    k = (r0 - r1) / L
    if abs(k) >= 1:
        return (a, r0) if r0 >= r1 else (b, r1)
    t = tp - k * q / math.sqrt(1 - k * k)
    t = 0 if t < 0 else L if t > L else t
    return add(a, mul(u, t)), r0 - k * t


def collide(c, p, pr):
    if c["shape"] == "SPHERE":
        return _sphere_bound(p, c["center"], c["r0"], pr, c["inside"])
    if c["shape"] == "CAPSULE":
        q, R = round_cone_sphere(p, c["a"], c["b"], c["r0"], c["r1"])
        return _sphere_bound(p, q, R, pr, c["inside"])
    if c["shape"] == "PLANE":
        sd = dot(sub(p, c["center"]), c["dir"])
        if not c["inside"]:
            if sd < pr:
                return add(p, mul(c["dir"], pr - sd)), True
        elif sd > -pr:
            return add(p, mul(c["dir"], -pr - sd)), True
        return p, False
    return p, False


def gust(time, depth, seed):
    s = seed * 12.9898
    return (math.sin(time * 1.000 + depth * 2.1 + s) * 0.5 + math.sin(time * 2.718 + depth * 1.3 + s * 1.7) * 0.3 +
            math.sin(time * 5.393 + depth * 0.7 + s * 2.3) * 0.2)


DEFAULTS = {
    "enabled": True, "updateRate": 60.0, "timeMode": "FIXED", "maxSubsteps": 3, "interpolate": False,
    "springModel": "POSITION", "damping": 0.1, "elasticity": 0.1, "stiffness": 0.1, "inert": 0.0, "friction": 0.0,
    "radius": 0.0, "angleLimit": 0.0, "stretch": 0.0,
    "dampingCurve": [], "elasticityCurve": [], "stiffnessCurve": [], "inertCurve": [], "frictionCurve": [],
    "radiusCurve": [], "angleLimitCurve": [], "stretchCurve": [],
    "frequency": 0.0, "dampingRatio": 0.2, "endLength": 0.0, "endOffset": [0.0, 0.0, 0.0],
    "gravity": [0.0, 0.0, 0.0], "force": [0.0, 0.0, 0.0], "forceUnits": "PER_STEP", "gravityRestCompensation": True,
    "wind": [0.0, 0.0, 0.0], "windTurbulence": 0.0, "windFrequency": 1.0, "seed": 1,
    "substepRoots": True, "freezeAxis": "NONE", "branchMode": "SKIP", "weight": 1.0, "resetDistance": 0.0,
}


class _Particle:
    __slots__ = ("joint", "parent", "children", "endOffset", "depth", "damping", "elasticity", "stiffness", "inert",
                 "friction", "radius", "angleLimit", "stretch", "pos", "prev", "last", "hit", "framePiv")

    def __init__(self, joint, parent, end_offset=None):
        self.joint, self.parent, self.children, self.endOffset = joint, parent, 0, end_offset
        self.hit, self.framePiv = False, None


class SpringChain:
    """See springbone-core.js: same constructor, frame(), retune(), state_hash()."""

    def __init__(self, trees, params=None):
        self.p = dict(DEFAULTS)
        self.p.update(params or {})
        self.trees_desc = trees
        self.ready = False
        self.acc = 0.0
        self.steps = 0
        self.dropped = 0.0
        self.time = 0.0
        self.ref_at_step = None
        self.trees = None
        self._tune()

    def _tune(self):
        self.tuning = None
        if self.p["frequency"] > 0:
            t = tuning_from_physical(self.p["frequency"], self.p["dampingRatio"], self.p["updateRate"], self.p["springModel"])
            self.tuning = t
            self.p["damping"], self.p["elasticity"] = clamp01(t["damping"]), clamp01(t["elasticity"])
        self.equivalent = physical_from_tuning(self.p["damping"], self.p["elasticity"], self.p["updateRate"], self.p["springModel"])

    def retune(self, params):
        self.p.update(params or {})
        self._tune()
        for T in self.trees or []:
            for pt in T["parts"]:
                self._coefficients(pt)

    def _coefficients(self, pt):
        P, a = self.p, pt.depth
        pt.damping = clamp01(P["damping"] * eval_curve(P["dampingCurve"], a))
        pt.elasticity = clamp01(P["elasticity"] * eval_curve(P["elasticityCurve"], a))
        pt.stiffness = clamp01(P["stiffness"] * eval_curve(P["stiffnessCurve"], a))
        pt.inert = clamp01(P["inert"] * eval_curve(P["inertCurve"], a))
        pt.friction = clamp01(P["friction"] * eval_curve(P["frictionCurve"], a))
        pt.radius = max(0, P["radius"] * eval_curve(P["radiusCurve"], a))
        pt.angleLimit = max(0, P["angleLimit"] * eval_curve(P["angleLimitCurve"], a)) * math.pi / 180
        pt.stretch = clamp01(P["stretch"] * eval_curve(P["stretchCurve"], a))

    def _animate(self, inp):
        out = []
        for ti, td in enumerate(self.trees_desc):
            tin = inp["trees"][ti]
            W, piv = [], []
            for k, j in enumerate(td["joints"]):
                parent_w = (tin.get("parentWorld") or IDENTITY) if j["parent"] < 0 else W[j["parent"]]
                w = compose(parent_w, affine_from_fields(tin["pose"][k]))
                W.append(w)
                piv.append(apply_point(w, tin["pose"][k].get("center") or [0, 0, 0]))
            out.append({"W": W, "piv": piv})
        return out

    def _anim_pos(self, pt, parts, A):
        if pt.joint >= 0:
            return A["piv"][pt.joint]
        pj = parts[pt.parent].joint
        return add(A["piv"][pj], m3v(A["W"][pj][0], pt.endOffset))

    def _local_offset(self, pt, parts, pose):
        if pt.joint < 0:
            return pt.endOffset
        pj = parts[pt.parent].joint
        cj = pose[pj].get("center") or [0, 0, 0]
        tk = pose[pt.joint].get("translation") or [0, 0, 0]
        ck = pose[pt.joint].get("center") or [0, 0, 0]
        return sub(add(tk, ck), cj)

    def _setup(self, anim):
        P = self.p
        self.trees = []
        for ti, td in enumerate(self.trees_desc):
            A, parts = anim[ti], []
            joint_particle = [None] * len(td["joints"])
            for k, j in enumerate(td["joints"]):
                parent_part = -1 if j["parent"] < 0 else joint_particle[j["parent"]]
                parts.append(_Particle(k, parent_part))
                joint_particle[k] = len(parts) - 1
                if parent_part >= 0:
                    parts[parent_part].children += 1
            has_child = [False] * len(td["joints"])
            for j in td["joints"]:
                if j["parent"] >= 0:
                    has_child[j["parent"]] = True
            for k, j in enumerate(td["joints"]):
                if has_child[k] and not j.get("endOffset"):
                    continue
                off = None
                if j.get("endOffset"):
                    off = list(j["endOffset"])
                elif P["endLength"] > 0:
                    if j["parent"] >= 0:
                        v = sub(A["piv"][k], A["piv"][j["parent"]])
                        off = mul(m3v(m3inv(A["W"][k][0]), v), P["endLength"])
                    else:
                        off = [P["endLength"], 0, 0]
                elif P["endOffset"][0] or P["endOffset"][1] or P["endOffset"][2]:
                    off = list(P["endOffset"])
                if not off:
                    continue
                pp = joint_particle[k]
                parts.append(_Particle(-1, pp, off))
                parts[pp].children += 1
            pos0 = [self._anim_pos(pt, parts, A) for pt in parts]
            depth_len = [0.0] * len(parts)
            total = 0.0
            for i, pt in enumerate(parts):
                if pt.parent >= 0:
                    depth_len[i] = depth_len[pt.parent] + length(sub(pos0[i], pos0[pt.parent]))
                    total = max(total, depth_len[i])
            for i, pt in enumerate(parts):
                pt.depth = depth_len[i] / total if total > 0 else 0
                self._coefficients(pt)
                pt.pos, pt.prev, pt.last = list(pos0[i]), list(pos0[i]), list(pos0[i])
                pt.hit = False
            q_root = quat_of_linear(A["W"][0][0])
            local_gravity = m3v(m3T(m3_from_quat(q_root)), P["gravity"])
            self.trees.append({"parts": parts, "jointParticle": joint_particle, "localGravity": local_gravity, "depthTotal": total})
        self.ref_at_step = None
        self.ready = True

    def frame(self, inp):
        P = self.p
        anim = self._animate(inp)
        if not self.ready:
            self._setup(anim)
        ref = inp.get("reference") or (inp["trees"][0].get("parentWorld") or IDENTITY)
        ref_origin = ref[1]
        object_scale = length(m3col(ref[0], 0))
        if self.ref_at_step is None:
            self.ref_at_step = list(ref_origin)
        object_move = sub(ref_origin, self.ref_at_step)
        colliders = [c if c.get("prepared") else prepare_collider(c) for c in inp.get("colliders") or []]
        dt = inp.get("dt") or 0
        self.time = inp["time"] if inp.get("time") is not None else self.time + dt

        if P["resetDistance"] > 0 and length(object_move) > P["resetDistance"]:
            for ti, T in enumerate(self.trees):
                for pt in T["parts"]:
                    a = self._anim_pos(pt, T["parts"], anim[ti])
                    pt.pos, pt.prev, pt.last = list(a), list(a), list(a)
            object_move = [0.0, 0.0, 0.0]
            self.ref_at_step = list(ref_origin)

        loops, time_var = 1, 1
        if not P["enabled"] or P["weight"] <= 0:
            loops = -1
        elif P["timeMode"] == "VARIABLE":
            time_var = dt * P["updateRate"] if P["updateRate"] > 0 else 1
            if dt <= 0:
                loops = 0
        else:
            h = 1 / P["updateRate"]
            self.acc += dt
            loops = 0
            while self.acc >= h - 1e-12:
                self.acc -= h
                loops += 1
                if loops >= P["maxSubsteps"]:
                    self.dropped += max(self.acc, 0)
                    self.acc = 0
                    break
        collided = False
        if loops > 0:
            for k in range(loops):
                t_step = (self.steps + 1) / P["updateRate"] if P["timeMode"] == "FIXED" else self.time
                for T in self.trees:
                    for pt in T["parts"]:
                        pt.last = list(pt.pos)
                share = (k + 1) / loops
                for ti, T in enumerate(self.trees):
                    hit = self._step(T, self.trees_desc[ti], anim[ti], inp["trees"][ti]["pose"], time_var,
                                     object_move if k == 0 else [0.0, 0.0, 0.0], object_scale, colliders, t_step,
                                     share if loops > 1 and P["substepRoots"] else 1)
                    collided = hit or collided
                self.steps += 1
            self.ref_at_step = list(ref_origin)
        carry = object_move if loops == 0 else [0.0, 0.0, 0.0]
        alpha = clamp01(self.acc * P["updateRate"]) if (P["interpolate"] and P["timeMode"] == "FIXED") else 1
        out = {"trees": [], "steps": loops if loops > 0 else 0, "droppedTime": self.dropped, "collided": collided}
        for ti, T in enumerate(self.trees):
            show = []
            for pt in T["parts"]:
                if pt.parent < 0:
                    show.append(anim[ti]["piv"][pt.joint])
                    continue
                b = [lerp(pt.last[i], pt.pos[i], alpha) for i in range(3)] if alpha < 1 else pt.pos
                show.append(add(b, carry))
            out["trees"].append(self._pass_through(T, inp["trees"][ti]) if loops < 0 else
                                self._apply(T, self.trees_desc[ti], inp["trees"][ti], show))
        out["energy"] = self.energy()
        return out

    def _rest_len(self, pt, T, A):
        pp = T["parts"][pt.parent]
        if pt.joint >= 0:
            return length(sub(A["piv"][pp.joint], A["piv"][pt.joint]))
        return length(m3v(A["W"][pp.joint][0], pt.endOffset))

    def _step(self, T, td, A, pose, time_var, object_move, object_scale, colliders, time, share):
        P = self.p
        units = 1 / (P["updateRate"] * P["updateRate"]) if P["forceUnits"] == "M_PER_S2" else 1
        g = mul(P["gravity"], units)
        if P["gravityRestCompensation"]:
            rest_g = mul(m3v(m3_from_quat(quat_of_linear(A["W"][0][0])), T["localGravity"]), units)
            fdir = unit(g)
            g = sub(g, mul(fdir, max(dot(rest_g, fdir), 0)))
        base = add(g, mul(P["force"], units))
        wind_on = P["wind"][0] or P["wind"][1] or P["wind"][2]
        tv = time_var
        hit = False
        parts = T["parts"]
        for pt in parts:
            if pt.parent < 0:
                pt.prev = pt.pos
                target = A["piv"][pt.joint]
                pt.pos = add(pt.framePiv, mul(sub(target, pt.framePiv), share)) if share < 1 and pt.framePiv else list(target)
                if share >= 1:
                    pt.framePiv = list(target)
                continue
            v = sub(pt.pos, pt.prev)
            rmove = mul(object_move, pt.inert)
            pt.prev = add(pt.pos, rmove)
            damping = pt.damping
            if pt.hit:
                damping = min(1, damping + pt.friction)
                pt.hit = False
            f = base
            if wind_on:
                f = add(f, mul(P["wind"], units * (1 + P["windTurbulence"] * gust(time * P["windFrequency"] * 2 * math.pi, pt.depth * 6, P["seed"]))))
            keep = 1 - damping
            pt.pos = add(add(pt.pos, mul(v, keep)), add(mul(f, object_scale * tv), rmove))
        for i in range(1, len(parts)):
            pt = parts[i]
            if pt.parent < 0:
                continue
            p0 = parts[pt.parent]
            rest_len = self._rest_len(pt, T, A)
            stiff = lerp(1, pt.stiffness, P["weight"])
            if stiff > 0 or pt.elasticity > 0:
                o = self._local_offset(pt, parts, pose)
                rest_pos = add(p0.pos, m3v(A["W"][p0.joint][0], o))
                d = sub(rest_pos, pt.last if P["springModel"] == "FORCE" else pt.pos)
                pt.pos = add(pt.pos, mul(d, pt.elasticity * time_var))
                if stiff > 0:
                    d = sub(rest_pos, pt.pos)
                    n = length(d)
                    maxlen = rest_len * (1 - stiff) * 2
                    if n > maxlen:
                        pt.pos = add(pt.pos, mul(d, (n - maxlen) / n))
            if colliders:
                pr = pt.radius * object_scale
                for c in colliders:
                    pt.pos, touched = collide(c, pt.pos, pr)
                    if touched:
                        pt.hit = True
                        hit = True
            if P["freezeAxis"] != "NONE":
                nrm = unit(m3col(A["W"][p0.joint][0], AXIS[P["freezeAxis"]]))
                pt.pos = sub(pt.pos, mul(nrm, dot(sub(pt.pos, p0.pos), nrm)))
            dd = sub(p0.pos, pt.pos)
            n = length(dd)
            if n > 0:
                pt.pos = add(pt.pos, mul(dd, ((n - rest_len) / n) * (1 - pt.stretch)))
            if pt.angleLimit > 0:
                o = self._local_offset(pt, parts, pose)
                rd = unit(m3v(A["W"][p0.joint][0], o))
                sv = sub(pt.pos, p0.pos)
                sl = length(sv)
                if sl > 0:
                    sd = mul(sv, 1 / sl)
                    c = max(-1, min(1, dot(rd, sd)))
                    ang = math.acos(c)
                    if ang > pt.angleLimit:
                        ax = cross(rd, sd) if length(cross(rd, sd)) > 1e-12 else [1, 0, 0]
                        q = q_from_axis_angle(ax, pt.angleLimit)
                        pt.pos = add(p0.pos, mul(m3v(m3_from_quat(q), rd), sl))
        return hit

    def _pass_through(self, T, tin):
        n = len(tin["pose"])
        return {"rotations": [None] * n, "translations": [None] * n, "positions": [list(p.pos) for p in T["parts"]]}

    def _apply(self, T, td, tin, show):
        P = self.p
        pose = tin["pose"]
        n = len(td["joints"])
        rotations, translations = [None] * n, [None] * n
        W = [None] * n
        local = [dict(f) for f in pose]
        kids = [[] for _ in range(n)]
        for i, pt in enumerate(T["parts"]):
            if pt.parent >= 0:
                kids[T["parts"][pt.parent].joint].append(i)
        for j in range(n):
            parent_w = (tin.get("parentWorld") or IDENTITY) if td["joints"][j]["parent"] < 0 else W[td["joints"][j]["parent"]]
            cur = compose(parent_w, affine_from_fields(local[j]))
            ks = kids[j]
            if len(ks) == 1 or (len(ks) > 1 and P["branchMode"] == "MEAN"):
                pivot = apply_point(cur, local[j].get("center") or [0, 0, 0])
                v0, v1 = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
                for i in ks:
                    o = self._local_offset(T["parts"][i], T["parts"], local)
                    v0 = add(v0, m3v(cur[0], o))
                    v1 = add(v1, sub(show[i], pivot))
                if length(v0) > 1e-12 and length(v1) > 1e-12:
                    Q = q_from_to(v0, v1)
                    qA = quat_of_linear(parent_w[0])
                    r_anim = qnorm(local[j].get("rotation") or [0, 0, 0, 1])
                    r = qmul(qconj(qA), qmul(Q, qmul(qA, r_anim)))
                    if P["weight"] < 1:
                        r = q_slerp(r_anim, r, clamp01(P["weight"]))
                    local[j]["rotation"] = r
                    rotations[j] = r
                    cur = compose(parent_w, affine_from_fields(local[j]))
                for i in ks:
                    pt = T["parts"][i]
                    if pt.joint < 0 or pt.stretch <= 0:
                        continue
                    pv = apply_point(cur, local[j].get("center") or [0, 0, 0])
                    o2 = m3v(m3inv(cur[0]), sub(show[i], pv))
                    tk = sub(add(o2, local[j].get("center") or [0, 0, 0]), local[pt.joint].get("center") or [0, 0, 0])
                    local[pt.joint]["translation"] = tk
                    translations[pt.joint] = tk
            W[j] = cur
        return {"rotations": rotations, "translations": translations, "positions": [list(s) for s in show]}

    def energy(self):
        e = 0.0
        for T in self.trees or []:
            for pt in T["parts"]:
                if pt.parent >= 0:
                    v = sub(pt.pos, pt.prev)
                    e += dot(v, v)
        return 0.5 * e * self.p["updateRate"] * self.p["updateRate"]

    def state_hash(self):
        """FNV-1a over positions rounded to 1 nm, rounding as JavaScript's Math.round does (half up)."""
        h = 0x811c9dc5
        for T in self.trees or []:
            for pt in T["parts"]:
                for x in pt.pos:
                    s = str(int(math.floor(x * 1e9 + 0.5)))
                    for ch in s:
                        h ^= ord(ch)
                        h = (h * 0x01000193) & 0xFFFFFFFF
        return f"{h:08x}"
