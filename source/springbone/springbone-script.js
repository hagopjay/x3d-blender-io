// springbone-script.js (built by tools/build.mjs; edit src/ instead). SpringBoneChain's Script, X3D ECMAScript.
// Own code (x3d.loom, MIT). springbone-core 0.1.0.
/*
 * springbone-core.js: a spring-bone solver for secondary motion (hair, tails, cloth strips, jiggle).
 *
 * Own code, written for x3d.loom (28 Nov 2026) from a written behaviour description (SPEC.md), not from any
 * vendor source. Its parameters are chosen so that a rig tuned in a popular Unity spring-bone asset carries
 * over by name (damping, elasticity, stiffness, inert, friction, radius, end length or offset, gravity, force,
 * per-depth curves, freeze axis, colliders); the arithmetic, the extra features and the tests are ours.
 *
 * No X3D, DOM or browser here: the same file runs in Node (tests), in an X3D Script node (X_ITE) and in a page.
 * Python mirror: x3d-blender-io source/springbone_core.py (same order of operations, same results to 1e-12).
 *
 * Conventions: vectors [x,y,z]; quaternions [x,y,z,w]; an affine is {L: 3x3 row-major Array(9), t: [x,y,z]}.
 * A joint's local frame follows the X3D Transform rule: T(translation) T(center) R SO S SO^-1 T(-center).
 * A joint's particle sits at its pivot: worldAffine(joint) applied to its center.
 */
'use strict';
(function (G) {
  // ---------------------------------------------------------------------------------------------- vectors
  const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const mul = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const len = (a) => Math.sqrt(dot(a, a));
  const unit = (a) => { const l = len(a); return l > 1e-300 ? mul(a, 1 / l) : [0, 0, 0]; };
  const lerp = (a, b, t) => a + (b - a) * t;
  const clamp01 = (x) => (x < 0 ? 0 : x > 1 ? 1 : x);

  // ---------------------------------------------------------------------------------------------- quaternions
  const qmul = (a, b) => [
    a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1],
    a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
    a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3],
    a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2]];
  const qconj = (q) => [-q[0], -q[1], -q[2], q[3]];
  const qnorm = (q) => { const l = Math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]); return l > 0 ? [q[0] / l, q[1] / l, q[2] / l, q[3] / l] : [0, 0, 0, 1]; };
  function qFromAxisAngle(ax, angle) {
    const a = unit(ax);
    if (a[0] === 0 && a[1] === 0 && a[2] === 0) return [0, 0, 0, 1];
    const s = Math.sin(angle / 2);
    return [a[0] * s, a[1] * s, a[2] * s, Math.cos(angle / 2)];
  }
  function qToAxisAngle(q0) {
    let q = qnorm(q0);
    if (q[3] < 0) q = [-q[0], -q[1], -q[2], -q[3]];
    const s = Math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2]);
    if (s < 1e-15) return [0, 0, 1, 0];
    return [q[0] / s, q[1] / s, q[2] / s, 2 * Math.atan2(s, q[3])];
  }
  // shortest rotation taking direction u onto direction v
  function qFromTo(u0, v0) {
    const u = unit(u0), v = unit(v0);
    const d = dot(u, v);
    if (d >= 1 - 1e-15) return [0, 0, 0, 1];
    if (d <= -1 + 1e-15) {          // opposite: any axis perpendicular to u
      let ax = cross(u, [1, 0, 0]);
      if (len(ax) < 1e-6) ax = cross(u, [0, 1, 0]);
      ax = unit(ax);
      return [ax[0], ax[1], ax[2], 0];
    }
    const c = cross(u, v);
    return qnorm([c[0], c[1], c[2], 1 + d]);
  }
  function qSlerp(a, b0, t) {
    let b = b0, d = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3];
    if (d < 0) { b = [-b[0], -b[1], -b[2], -b[3]]; d = -d; }
    if (d > 1 - 1e-12) return qnorm([lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t), lerp(a[3], b[3], t)]);
    const th = Math.acos(d), s = Math.sin(th), wa = Math.sin((1 - t) * th) / s, wb = Math.sin(t * th) / s;
    return [a[0] * wa + b[0] * wb, a[1] * wa + b[1] * wb, a[2] * wa + b[2] * wb, a[3] * wa + b[3] * wb];
  }

  // ---------------------------------------------------------------------------------------------- 3x3 and affine
  function m3FromQuat(q0) {
    const q = qnorm(q0), x = q[0], y = q[1], z = q[2], w = q[3];
    return [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
            2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
            2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)];
  }
  function m3mul(A, B) {
    const C = new Array(9);
    for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) C[r * 3 + c] = A[r * 3] * B[c] + A[r * 3 + 1] * B[3 + c] + A[r * 3 + 2] * B[6 + c];
    return C;
  }
  const m3v = (A, v) => [A[0] * v[0] + A[1] * v[1] + A[2] * v[2], A[3] * v[0] + A[4] * v[1] + A[5] * v[2], A[6] * v[0] + A[7] * v[1] + A[8] * v[2]];
  const m3T = (A) => [A[0], A[3], A[6], A[1], A[4], A[7], A[2], A[5], A[8]];
  const m3col = (A, c) => [A[c], A[3 + c], A[6 + c]];
  function m3inv(A) {
    const a = A[0], b = A[1], c = A[2], d = A[3], e = A[4], f = A[5], g = A[6], h = A[7], i = A[8];
    const co0 = e * i - f * h, co1 = f * g - d * i, co2 = d * h - e * g, det = a * co0 + b * co1 + c * co2;
    const k = 1 / det;
    return [co0 * k, (c * h - b * i) * k, (b * f - c * e) * k, co1 * k, (a * i - c * g) * k, (c * d - a * f) * k, co2 * k, (b * g - a * h) * k, (a * e - b * d) * k];
  }
  // rotation part of a similarity (rotation x uniform positive scale); columns normalised, then Shepperd's method
  function quatOfLinear(A) {
    const c0 = unit(m3col(A, 0)), c1 = unit(m3col(A, 1)), c2 = unit(m3col(A, 2));
    const m00 = c0[0], m10 = c0[1], m20 = c0[2], m01 = c1[0], m11 = c1[1], m21 = c1[2], m02 = c2[0], m12 = c2[1], m22 = c2[2];
    const tr = m00 + m11 + m22;
    let q;
    if (tr > 0) { const s = Math.sqrt(tr + 1) * 2; q = [(m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s, 0.25 * s]; }
    else if (m00 > m11 && m00 > m22) { const s = Math.sqrt(1 + m00 - m11 - m22) * 2; q = [0.25 * s, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s]; }
    else if (m11 > m22) { const s = Math.sqrt(1 + m11 - m00 - m22) * 2; q = [(m01 + m10) / s, 0.25 * s, (m12 + m21) / s, (m02 - m20) / s]; }
    else { const s = Math.sqrt(1 + m22 - m00 - m11) * 2; q = [(m02 + m20) / s, (m12 + m21) / s, 0.25 * s, (m10 - m01) / s]; }
    return qnorm(q);
  }
  const IDENTITY = { L: [1, 0, 0, 0, 1, 0, 0, 0, 1], t: [0, 0, 0] };
  const compose = (A, B) => ({ L: m3mul(A.L, B.L), t: add(m3v(A.L, B.t), A.t) });
  const applyPoint = (A, p) => add(m3v(A.L, p), A.t);
  // X3D Transform / HAnimJoint fields -> affine
  function affineFromFields(f) {
    const R = m3FromQuat(f.rotation || [0, 0, 0, 1]);
    const s = f.scale || [1, 1, 1];
    let L = R;
    if (s[0] !== 1 || s[1] !== 1 || s[2] !== 1) {
      const SO = m3FromQuat(f.scaleOrientation || [0, 0, 0, 1]);
      L = m3mul(R, m3mul(SO, m3mul([s[0], 0, 0, 0, s[1], 0, 0, 0, s[2]], m3T(SO))));
    }
    const c = f.center || [0, 0, 0], tr = f.translation || [0, 0, 0];
    return { L, t: sub(add(tr, c), m3v(L, c)) };
  }

  // ---------------------------------------------------------------------------------------------- curves
  // A curve is a list of [t, value] keys (X3D MFVec2f), linear between keys, flat outside. Empty means 1.
  function evalCurve(keys, t) {
    if (!keys || keys.length === 0) return 1;
    if (t <= keys[0][0]) return keys[0][1];
    for (let i = 1; i < keys.length; i++) {
      if (t <= keys[i][0]) {
        const a = keys[i - 1], b = keys[i], w = b[0] - a[0];
        return w > 0 ? lerp(a[1], b[1], (t - a[0]) / w) : b[1];
      }
    }
    return keys[keys.length - 1][1];
  }

  // ---------------------------------------------------------------------------------------------- tuning
  // The per-step update of one particle with elasticity e and damping d, small motion, stiffness off, is the
  // linear recurrence y[n+1] = (1-e)((2-d) y[n] - (1-d) y[n-1]) (SPEC.md section 4). Its roots l1, l2 satisfy
  // l1 + l2 = (1-e)(2-d) = S and l1 l2 = (1-e)(1-d) = P, so S - P = 1 - e and 1 - d = P / (S - P).
  // A damped oscillator x'' + 2 zeta w x' + w^2 x = 0 sampled every h has roots exp(s h); choosing (d, e) from
  // those roots makes the solver's sampled response equal to the oscillator's, exactly.
  // Two spring models. POSITION (the default, and how the Unity asset behaves): after the Verlet move the particle
  // is pulled a share e of the way to its rest place, so y[n+1] = (1-e)((2-d) y[n] - (1-d) y[n-1]) and
  // S = (1-e)(2-d), P = (1-e)(1-d). Because the pull also scales the carried velocity, POSITION has a floor on
  // its damping ratio at any one frequency. FORCE (ours): the pull is a force on the old position,
  // y[n+1] = (2-d-e) y[n] - (1-d) y[n-1], so S = 2-d-e, P = 1-d, and any damping ratio from 0 up is reachable.
  function rootsSP(frequencyHz, zeta, rate) {
    const w = 2 * Math.PI * frequencyHz, h = 1 / rate;
    if (zeta < 1) {
      const wd = w * Math.sqrt(1 - zeta * zeta);
      return [2 * Math.exp(-zeta * w * h) * Math.cos(wd * h), Math.exp(-2 * zeta * w * h)];
    }
    const r = Math.sqrt(zeta * zeta - 1);
    return [Math.exp((-zeta + r) * w * h) + Math.exp((-zeta - r) * w * h), Math.exp(-2 * zeta * w * h)];
  }
  function tuningFromPhysical(frequencyHz, zeta, rate, model) {
    const [S, P] = rootsSP(frequencyHz, zeta, rate);
    let e, d;
    if (model === 'FORCE') { d = 1 - P; e = 1 + P - S; }
    else { e = 1 - (S - P); d = 1 - P / (S - P); }
    return { damping: d, elasticity: e, feasible: e >= 0 && e <= 1 && d >= 0 && d <= 1, model: model || 'POSITION' };
  }
  // the inverse: what oscillator a (damping, elasticity) pair at a rate behaves like (small motion)
  function physicalFromTuning(d, e, rate, model) {
    const h = 1 / rate;
    const S = model === 'FORCE' ? 2 - d - e : (1 - e) * (2 - d), P = model === 'FORCE' ? 1 - d : (1 - e) * (1 - d);
    const disc = S * S - 4 * P;
    if (P <= 0) return { frequency: Infinity, dampingRatio: Infinity, oscillates: false };
    if (disc < 0) {                       // complex pair r e^{+-i th}
      const r = Math.sqrt(P), th = Math.atan2(Math.sqrt(-disc), S);
      const sigma = Math.log(r) / h, wd = th / h, w = Math.sqrt(sigma * sigma + wd * wd);
      return { frequency: w / (2 * Math.PI), dampingRatio: -sigma / w, oscillates: true, periodSteps: 2 * Math.PI / th };
    }
    const l1 = (S + Math.sqrt(disc)) / 2, l2 = (S - Math.sqrt(disc)) / 2;
    if (l1 <= 0 || l2 <= 0) return { frequency: NaN, dampingRatio: NaN, oscillates: true, note: 'negative real root: alternating per step' };
    const s1 = Math.log(l1) / h, s2 = Math.log(l2) / h, w = Math.sqrt(s1 * s2);
    return { frequency: w / (2 * Math.PI), dampingRatio: -(s1 + s2) / (2 * w), oscillates: false };
  }

  // ---------------------------------------------------------------------------------------------- colliders
  // A collider is {shape: 'SPHERE'|'CAPSULE'|'PLANE', bound: 'OUTSIDE'|'INSIDE', center, radius, radius2, height,
  // direction: 'X'|'Y'|'Z', world: affine of the frame it is attached to}. prepareCollider turns it into world terms.
  const AXIS = { X: 0, Y: 1, Z: 2 };
  function prepareCollider(c) {
    const W = c.world || IDENTITY, sc = len(m3col(W.L, 0));
    const center = applyPoint(W, c.center || [0, 0, 0]);
    // `axis` (a vector in the frame) overrides `direction` (X, Y or Z of the frame) when it is not zero
    const axv = c.axis || [0, 0, 0];
    const dir = (axv[0] || axv[1] || axv[2]) ? unit(m3v(W.L, axv)) : unit(m3col(W.L, AXIS[c.direction || 'Y']));
    const r0 = (c.radius !== undefined ? c.radius : 0.5) * sc;
    const r1 = (c.radius2 !== undefined && c.radius2 > 0 ? c.radius2 : (c.radius !== undefined ? c.radius : 0.5)) * sc;
    const h = (c.height || 0) * sc;
    const out = { shape: c.shape || 'SPHERE', inside: (c.bound || 'OUTSIDE') === 'INSIDE', center, dir, r0, r1, prepared: true };
    if (out.shape === 'CAPSULE') {
      // `height` is the whole length, end caps included, centred on `center`: radius at the -axis end, radius2 at
      // the +axis end, so the sphere centres sit at -(height/2 - r0) and +(height/2 - r1)
      const segLen = Math.max(h - r0 - r1, 0);
      out.a = add(center, mul(dir, -(h / 2 - r0)));
      out.b = add(center, mul(dir, h / 2 - r1));
      out.segLen = segLen;
      if (segLen <= 0) { out.shape = 'SPHERE'; out.r0 = Math.max(r0, r1); }
    }
    return out;
  }
  // push p out of (or into) a sphere of centre q, radius R, for a particle of radius pr; returns [p, hit]
  function sphereBound(p, q, R, pr, inside) {
    const d = sub(p, q), l = len(d);
    if (!inside) {
      const m = R + pr;
      if (l < m) { const n = l > 1e-300 ? mul(d, 1 / l) : [0, 1, 0]; return [add(q, mul(n, m)), true]; }
      return [p, false];
    }
    const m = R - pr;
    if (l > m) { const n = l > 1e-300 ? mul(d, 1 / l) : [0, 1, 0]; return [add(q, mul(n, Math.max(m, 0))), true]; }
    return [p, false];
  }
  // round cone (sphere-swept segment with linearly varying radius): the exact nearest swept sphere
  function roundConeSphere(p, a, b, r0, r1) {
    const ab = sub(b, a), L = len(ab);
    if (L < 1e-300) return [a, Math.max(r0, r1)];
    const u = mul(ab, 1 / L), ap = sub(p, a), tp = dot(ap, u);
    const radial = sub(ap, mul(u, tp)), q = len(radial);
    const k = (r0 - r1) / L;                      // dr/dt is -k
    if (Math.abs(k) >= 1) return r0 >= r1 ? [a, r0] : [b, r1];   // one end sphere swallows the other
    let t = tp - k * q / Math.sqrt(1 - k * k);
    t = t < 0 ? 0 : t > L ? L : t;
    return [add(a, mul(u, t)), r0 - k * t];
  }
  function collide(c, p, pr) {
    if (c.shape === 'SPHERE') return sphereBound(p, c.center, c.r0, pr, c.inside);
    if (c.shape === 'CAPSULE') { const [q, R] = roundConeSphere(p, c.a, c.b, c.r0, c.r1); return sphereBound(p, q, R, pr, c.inside); }
    if (c.shape === 'PLANE') {
      const sd = dot(sub(p, c.center), c.dir);
      if (!c.inside) { if (sd < pr) return [add(p, mul(c.dir, pr - sd)), true]; }
      else if (sd > -pr) return [add(p, mul(c.dir, -pr - sd)), true];
      return [p, false];
    }
    return [p, false];
  }

  // ---------------------------------------------------------------------------------------------- wind
  // deterministic gusts: a sum of three incommensurate sines per particle, phase-shifted by depth and seed
  function gust(time, depth, seed) {
    const s = seed * 12.9898;
    return (Math.sin(time * 1.000 + depth * 2.1 + s) * 0.5 + Math.sin(time * 2.718 + depth * 1.3 + s * 1.7) * 0.3 +
            Math.sin(time * 5.393 + depth * 0.7 + s * 2.3) * 0.2);
  }

  // ---------------------------------------------------------------------------------------------- defaults
  const DEFAULTS = {
    enabled: true, updateRate: 60, timeMode: 'FIXED', maxSubsteps: 3, interpolate: false,
    springModel: 'POSITION', damping: 0.1, elasticity: 0.1, stiffness: 0.1, inert: 0, friction: 0, radius: 0, angleLimit: 0, stretch: 0,
    dampingCurve: [], elasticityCurve: [], stiffnessCurve: [], inertCurve: [], frictionCurve: [], radiusCurve: [], angleLimitCurve: [], stretchCurve: [],
    frequency: 0, dampingRatio: 0.2,
    endLength: 0, endOffset: [0, 0, 0],
    gravity: [0, 0, 0], force: [0, 0, 0], forceUnits: 'PER_STEP', gravityRestCompensation: true,
    wind: [0, 0, 0], windTurbulence: 0, windFrequency: 1, seed: 1,
    substepRoots: true, freezeAxis: 'NONE', branchMode: 'SKIP', weight: 1, resetDistance: 0,
    faults: null,     // tests only: {name: true} plants a known bug so a witness must fail
  };

  // ---------------------------------------------------------------------------------------------- the chain
  /**
   * new SpringChain(trees, params)
   *   trees: [{ joints: [{name, parent, center, endOffset?}], }]  one per root; parent is an index into the same
   *          list (-1 for the tree's root). Joints must be listed parents first (preorder is what X3D gives).
   *   params: see DEFAULTS.
   * chain.frame(input) -> output
   *   input: { dt, time, trees: [{ parentWorld: affine, pose: [{translation, center, rotation(q), scale, scaleOrientation}] }],
   *            reference: affine (the frame whose motion `inert` cancels; default trees[0].parentWorld),
   *            colliders: [collider in world terms or with .world] }
   *   output: { trees: [{ rotations: [q|null per joint], translations: [v|null], positions: [particle world positions] }],
   *             steps, droppedTime, collided, energy }
   */
  class SpringChain {
    constructor(trees, params) {
      this.p = Object.assign({}, DEFAULTS, params || {});
      this._tune();
      this.treesDesc = trees;
      this.ready = false;
      this.acc = 0; this.steps = 0; this.dropped = 0; this.time = 0;
    }
    fault(name) { return !!(this.p.faults && this.p.faults[name]); }

    // world pose of every joint from the input pose; particles' animated positions
    _animate(input) {
      const out = [];
      this.treesDesc.forEach((td, ti) => {
        const ti_in = input.trees[ti], W = [], piv = [];
        td.joints.forEach((j, k) => {
          const parentW = j.parent < 0 ? (ti_in.parentWorld || IDENTITY) : W[j.parent];
          const w = compose(parentW, affineFromFields(ti_in.pose[k]));
          W.push(w);
          piv.push(applyPoint(w, ti_in.pose[k].center || [0, 0, 0]));
        });
        out.push({ W, piv });
      });
      return out;
    }

    _setup(anim) {
      const P = this.p;
      this.trees = this.treesDesc.map((td, ti) => {
        const A = anim[ti], parts = [];
        const jointParticle = new Array(td.joints.length);
        const addParticle = (o) => { parts.push(o); return parts.length - 1; };
        td.joints.forEach((j, k) => {
          const parentPart = j.parent < 0 ? -1 : jointParticle[j.parent];
          jointParticle[k] = addParticle({ joint: k, parent: parentPart, children: 0 });
          if (parentPart >= 0) parts[parentPart].children++;
        });
        // end particles on leaves (or where a joint lists an explicit endOffset)
        const hasChild = td.joints.map(() => false);
        td.joints.forEach((j) => { if (j.parent >= 0) hasChild[j.parent] = true; });
        td.joints.forEach((j, k) => {
          if (hasChild[k] && !j.endOffset) return;
          let off = null;
          if (j.endOffset) off = j.endOffset;
          else if (P.endLength > 0) {
            if (j.parent >= 0) {
              // continue the last bone: the grandparent-to-parent vector, in the leaf's own frame, times endLength
              const v = sub(A.piv[k], A.piv[j.parent]);
              off = mul(m3v(m3inv(A.W[k].L), v), P.endLength);
            } else off = [P.endLength, 0, 0];
          } else if (P.endOffset[0] || P.endOffset[1] || P.endOffset[2]) off = P.endOffset.slice();
          if (!off) return;
          const pp = jointParticle[k];
          addParticle({ joint: -1, parent: pp, children: 0, endOffset: off });
          parts[pp].children++;
        });
        // depth along the tree for the curves (0 at the root, 1 at the farthest tip)
        const pos0 = parts.map((pt) => this._animPos(pt, parts, A));
        const depthLen = parts.map(() => 0);
        let total = 0;
        parts.forEach((pt, i) => {
          if (pt.parent >= 0) { depthLen[i] = depthLen[pt.parent] + len(sub(pos0[i], pos0[pt.parent])); total = Math.max(total, depthLen[i]); }
        });
        parts.forEach((pt, i) => {
          pt.depth = total > 0 ? depthLen[i] / total : 0;
          this._coefficients(pt);
          pt.pos = pos0[i].slice(); pt.prev = pos0[i].slice(); pt.last = pos0[i].slice(); pt.hit = false;
        });
        // gravity as seen by the tree's root at rest (used to remove the part of gravity the rest pose already holds)
        const qRoot = quatOfLinear(A.W[0].L);
        const g = P.gravity;
        const localGravity = m3v(m3T(m3FromQuat(qRoot)), g);
        return { parts, jointParticle, localGravity, depthTotal: total };
      });
      this.refAtStep = null;
      this.ready = true;
    }

    // per-particle values: the base value times its curve at the particle's depth
    _coefficients(pt) {
      const P = this.p, a = pt.depth;
      pt.damping = clamp01(P.damping * evalCurve(P.dampingCurve, a));
      pt.elasticity = clamp01(P.elasticity * evalCurve(P.elasticityCurve, a));
      pt.stiffness = clamp01(P.stiffness * evalCurve(P.stiffnessCurve, a));
      pt.inert = clamp01(P.inert * evalCurve(P.inertCurve, a));
      pt.friction = clamp01(P.friction * evalCurve(P.frictionCurve, a));
      pt.radius = Math.max(0, P.radius * evalCurve(P.radiusCurve, a));
      pt.angleLimit = Math.max(0, P.angleLimit * evalCurve(P.angleLimitCurve, a)) * Math.PI / 180;
      pt.stretch = clamp01(P.stretch * evalCurve(P.stretchCurve, a));
    }
    _tune() {
      this.tuning = null;
      if (this.p.frequency > 0) {
        const t = tuningFromPhysical(this.p.frequency, this.p.dampingRatio, this.p.updateRate, this.p.springModel);
        this.tuning = t;
        this.p.damping = clamp01(t.damping); this.p.elasticity = clamp01(t.elasticity);
      }
      this.equivalent = physicalFromTuning(this.p.damping, this.p.elasticity, this.p.updateRate, this.p.springModel);
    }
    // change parameters while running: the particles keep their state (end particles are fixed at build time)
    retune(params) {
      Object.assign(this.p, params || {});
      this._tune();
      if (this.trees) this.trees.forEach((T) => T.parts.forEach((pt) => this._coefficients(pt)));
    }

    _animPos(pt, parts, A) {
      if (pt.joint >= 0) return A.piv[pt.joint];
      const pj = parts[pt.parent].joint;
      return add(A.piv[pj], m3v(A.W[pj].L, pt.endOffset));
    }
    // the particle's offset from its parent's pivot, in the parent joint's local frame
    _localOffset(td, pt, parts, pose) {
      if (pt.joint < 0) return pt.endOffset;
      const pj = parts[pt.parent].joint;
      const cj = pose[pj].center || [0, 0, 0];
      const tk = pose[pt.joint].translation || [0, 0, 0], ck = pose[pt.joint].center || [0, 0, 0];
      return sub(add(tk, ck), cj);
    }

    reset(input) { this.ready = false; this.acc = 0; this.frame(Object.assign({}, input, { dt: 0 })); }

    frame(input) {
      const P = this.p;
      const anim = this._animate(input);
      if (!this.ready) this._setup(anim);
      const ref = input.reference || (input.trees[0].parentWorld || IDENTITY);
      const refOrigin = ref.t;
      const objectScale = len(m3col(ref.L, 0));
      // the reference's move since the last solver step (not since the last frame: a frame with no step
      // must not change the state, or the result would depend on the display rate)
      if (!this.refAtStep) this.refAtStep = refOrigin.slice();
      let objectMove = sub(refOrigin, this.refAtStep);
      const colliders = (input.colliders || []).map((c) => (c.prepared ? c : prepareCollider(c)));
      const dt = input.dt || 0;
      this.time = input.time !== undefined ? input.time : this.time + dt;

      // teleport: snap to the animated pose
      if (P.resetDistance > 0 && len(objectMove) > P.resetDistance) {
        this.trees.forEach((T, ti) => T.parts.forEach((pt) => { const a = this._animPos(pt, T.parts, anim[ti]); pt.pos = a.slice(); pt.prev = a.slice(); pt.last = a.slice(); }));
        objectMove = [0, 0, 0]; this.refAtStep = refOrigin.slice();
      }

      // how many solver steps this frame, and the time scale of each
      let loops = 1, timeVar = 1;
      if (!P.enabled || P.weight <= 0) loops = -1;
      else if (P.timeMode === 'VARIABLE') { timeVar = P.updateRate > 0 ? dt * P.updateRate : 1; if (dt <= 0) loops = 0; }
      else {
        const h = 1 / P.updateRate;
        this.acc += dt; loops = 0;
        while (this.acc >= h - 1e-12) {
          this.acc -= h;
          if (++loops >= P.maxSubsteps) { this.dropped += Math.max(this.acc, 0); this.acc = 0; break; }
        }
      }
      let collided = false;
      if (loops > 0) {
        for (let k = 0; k < loops; k++) {
          // wind clock: the step count in FIXED mode (display-rate free), the frame clock in VARIABLE mode
          const tStep = P.timeMode === 'FIXED' ? (this.steps + 1) / P.updateRate : this.time;
          this.trees.forEach((T) => { T.parts.forEach((pt) => { pt.last = pt.pos.slice(); }); });
          // with several steps in one frame the roots move in even shares between the last frame and this one
          const share = (k + 1) / loops;
          this.trees.forEach((T, ti) => { collided = this._step(T, this.treesDesc[ti], anim[ti], input.trees[ti].pose, timeVar, k === 0 ? objectMove : [0, 0, 0], objectScale, colliders, tStep, loops > 1 && P.substepRoots ? share : 1) || collided; });
          this.steps++;
        }
        this.refAtStep = refOrigin.slice();
      }
      // a frame without a step shows the last state carried along with the reference (display only)
      const carry = loops === 0 ? objectMove : [0, 0, 0];

      // display positions (optionally between the last two solver states)
      const alpha = (P.interpolate && P.timeMode === 'FIXED') ? clamp01(this.acc * P.updateRate) : 1;
      const out = { trees: [], steps: loops > 0 ? loops : 0, droppedTime: this.dropped, collided };
      this.trees.forEach((T, ti) => {
        const show = T.parts.map((pt, i) => {
          if (pt.parent < 0) return anim[ti].piv[pt.joint];
          const b = alpha < 1 ? [lerp(pt.last[0], pt.pos[0], alpha), lerp(pt.last[1], pt.pos[1], alpha), lerp(pt.last[2], pt.pos[2], alpha)] : pt.pos;
          return add(b, carry);
        });
        out.trees.push(loops < 0 ? this._passThrough(T, input.trees[ti]) : this._apply(T, this.treesDesc[ti], input.trees[ti], show));
      });
      out.energy = this.energy();
      return out;
    }

    _restLen(pt, T, A) {
      const pp = T.parts[pt.parent];
      if (pt.joint >= 0) return len(sub(A.piv[pp.joint], A.piv[pt.joint]));
      return len(m3v(A.W[pp.joint].L, pt.endOffset));
    }

    _step(T, td, A, pose, timeVar, objectMove, objectScale, colliders, time, share) {
      const P = this.p;
      // external force per step: gravity (less what the rest pose already holds) + force + wind
      const unitsScale = P.forceUnits === 'M_PER_S2' ? 1 / (P.updateRate * P.updateRate) : 1;
      let g = mul(P.gravity, unitsScale);
      if (P.gravityRestCompensation && !this.fault('noRestCompensation')) {
        const restG = mul(m3v(m3FromQuat(quatOfLinear(A.W[0].L)), T.localGravity), unitsScale);
        const fdir = unit(g);
        g = sub(g, mul(fdir, Math.max(dot(restG, fdir), 0)));
      }
      const base = add(g, mul(P.force, unitsScale));
      const windOn = P.wind[0] || P.wind[1] || P.wind[2];
      const tv = this.fault('gravityPerSecond') ? timeVar * P.updateRate : timeVar;
      let hit = false;
      // 1. integrate (Verlet with damping; inert carries a share of the reference's move)
      T.parts.forEach((pt, i) => {
        if (pt.parent < 0) {
          pt.prev = pt.pos;
          const target = A.piv[pt.joint];
          pt.pos = share < 1 && pt.framePiv ? add(pt.framePiv, mul(sub(target, pt.framePiv), share)) : target.slice();
          if (share >= 1) pt.framePiv = target.slice();
          return;
        }
        const v = sub(pt.pos, pt.prev);
        const rmove = mul(objectMove, pt.inert);
        pt.prev = add(pt.pos, rmove);
        let damping = pt.damping;
        if (pt.hit) { damping = Math.min(1, damping + pt.friction); pt.hit = false; }
        let f = base;
        if (windOn) f = add(f, mul(P.wind, unitsScale * (1 + P.windTurbulence * gust(time * P.windFrequency * 2 * Math.PI, pt.depth * 6, P.seed))));
        const keep = this.fault('dampingSquared') ? (1 - damping) * (1 - damping) : (1 - damping);
        pt.pos = add(add(pt.pos, mul(v, keep)), add(mul(f, objectScale * tv), rmove));
      });
      // 2. constraints, parents first
      for (let i = 1; i < T.parts.length; i++) {
        const pt = T.parts[i]; if (pt.parent < 0) continue;
        const p0 = T.parts[pt.parent];
        const restLen = this._restLen(pt, T, A);
        const stiff = lerp(1, pt.stiffness, P.weight);
        if (stiff > 0 || pt.elasticity > 0) {
          const o = this._localOffset(td, pt, T.parts, pose);
          const restPos = add(p0.pos, m3v(A.W[p0.joint].L, o));
          let d = sub(restPos, P.springModel === 'FORCE' ? pt.last : pt.pos);
          pt.pos = add(pt.pos, mul(d, pt.elasticity * timeVar));
          if (stiff > 0) {
            d = sub(restPos, pt.pos);
            const l = len(d), maxlen = restLen * (1 - stiff) * 2;
            if (l > maxlen) pt.pos = add(pt.pos, mul(d, (l - maxlen) / l));
          }
        }
        if (colliders.length) {
          const pr = pt.radius * objectScale;
          for (const c of colliders) { const r = collide(c, pt.pos, pr); pt.pos = r[0]; if (r[1]) { pt.hit = true; hit = true; } }
        }
        if (P.freezeAxis !== 'NONE') {
          const n = unit(m3col(A.W[p0.joint].L, AXIS[P.freezeAxis]));
          pt.pos = sub(pt.pos, mul(n, dot(sub(pt.pos, p0.pos), n)));
        }
        if (!this.fault('noKeepLength')) {
          const dd = sub(p0.pos, pt.pos), l = len(dd);
          if (l > 0) pt.pos = add(pt.pos, mul(dd, ((l - restLen) / l) * (1 - pt.stretch)));
        }
        if (pt.angleLimit > 0) {
          const o = this._localOffset(td, pt, T.parts, pose);
          const rd = unit(m3v(A.W[p0.joint].L, o)), sv = sub(pt.pos, p0.pos), sl = len(sv);
          if (sl > 0) {
            const sd = mul(sv, 1 / sl), c = Math.max(-1, Math.min(1, dot(rd, sd))), ang = Math.acos(c);
            if (ang > pt.angleLimit) {
              const q = qFromAxisAngle(len(cross(rd, sd)) > 1e-12 ? cross(rd, sd) : [1, 0, 0], pt.angleLimit);
              pt.pos = add(p0.pos, mul(m3v(m3FromQuat(q), rd), sl));
            }
          }
        }
      }
      return hit;
    }

    _passThrough(T, tin) {
      return { rotations: tin.pose.map(() => null), translations: tin.pose.map(() => null), positions: T.parts.map((p) => p.pos.slice()) };
    }

    // turn particle positions into joint rotations (and, for stretchy bones, translations), root to tip
    _apply(T, td, tin, show) {
      const P = this.p, pose = tin.pose, n = td.joints.length;
      const rotations = new Array(n).fill(null), translations = new Array(n).fill(null);
      const W = new Array(n), local = pose.map((f) => Object.assign({}, f));
      const kids = td.joints.map(() => []);
      T.parts.forEach((pt, i) => { if (pt.parent >= 0) kids[T.parts[pt.parent].joint].push(i); });
      for (let j = 0; j < n; j++) {
        const parentW = td.joints[j].parent < 0 ? (tin.parentWorld || IDENTITY) : W[td.joints[j].parent];
        let cur = compose(parentW, affineFromFields(local[j]));
        const ks = kids[j];
        if (ks.length === 1 || (ks.length > 1 && P.branchMode === 'MEAN')) {
          const pivot = applyPoint(cur, local[j].center || [0, 0, 0]);
          let v0 = [0, 0, 0], v1 = [0, 0, 0];
          ks.forEach((i) => {
            const o = this._localOffset(td, T.parts[i], T.parts, local);
            v0 = add(v0, m3v(cur.L, o)); v1 = add(v1, sub(show[i], pivot));
          });
          if (len(v0) > 1e-12 && len(v1) > 1e-12) {
            const Q = qFromTo(v0, v1);
            const qA = quatOfLinear(parentW.L);
            let r = qmul(qconj(qA), qmul(Q, qmul(qA, qnorm(local[j].rotation || [0, 0, 0, 1]))));
            if (P.weight < 1) r = qSlerp(qnorm(local[j].rotation || [0, 0, 0, 1]), r, clamp01(P.weight));
            local[j].rotation = r; rotations[j] = r;
            cur = compose(parentW, affineFromFields(local[j]));
          }
          // stretchy bones: move each child joint so its pivot lands on its particle
          ks.forEach((i) => {
            const pt = T.parts[i];
            if (pt.joint < 0 || pt.stretch <= 0) return;
            const pv = applyPoint(cur, local[j].center || [0, 0, 0]);
            const o2 = m3v(m3inv(cur.L), sub(show[i], pv));
            const tk = sub(add(o2, local[j].center || [0, 0, 0]), local[pt.joint].center || [0, 0, 0]);
            local[pt.joint].translation = tk; translations[pt.joint] = tk;
          });
        }
        W[j] = cur;
      }
      return { rotations, translations, positions: T.parts.map((p, i) => show[i].slice()) };
    }

    energy() {
      let e = 0;
      (this.trees || []).forEach((T) => T.parts.forEach((pt) => { if (pt.parent >= 0) { const v = sub(pt.pos, pt.prev); e += dot(v, v); } }));
      return 0.5 * e * this.p.updateRate * this.p.updateRate;
    }
    // FNV-1a over positions rounded to 1e-9 m: a replay witness, same in every engine that rounds the same
    stateHash() {
      let h = 0x811c9dc5;
      (this.trees || []).forEach((T) => T.parts.forEach((pt) => pt.pos.forEach((x) => {
        const s = Math.round(x * 1e9).toString();
        for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
      })));
      return ('00000000' + h.toString(16)).slice(-8);
    }
  }

  const api = {
    SpringChain, DEFAULTS, tuningFromPhysical, physicalFromTuning, evalCurve, prepareCollider, collide, roundConeSphere,
    affineFromFields, compose, applyPoint, quatOfLinear, qFromAxisAngle, qToAxisAngle, qFromTo, qmul, qnorm, m3FromQuat, m3v, IDENTITY,
    VERSION: '0.1.0',
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else G.SpringBone = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);

// x3d-script-glue.js: the X3D Script side of SpringBoneChain (appended to springbone-core.js by tools/build.mjs).
// Runs inside the PROTO's Script node (directOutput TRUE). It reads the bones and their ancestors as standard X3D
// fields, feeds springbone-core, and writes each bone's `rotation` (and `translation` for stretchy bones).
// Only standard X3D ECMAScript calls: SFNode field access, getNodeTypeName(), new SFRotation / SFVec3f.

var SB = (typeof globalThis !== 'undefined' ? globalThis : this).SpringBone;
var chain = null, trees = [], lastTime = -1, written = [], paramsKey = '', droppedReported = 0;

var PARAM_FIELDS = ['enabled', 'updateRate', 'timeMode', 'maxSubsteps', 'interpolate', 'springModel', 'damping', 'elasticity',
  'stiffness', 'inert', 'friction', 'radius', 'angleLimit', 'stretch', 'frequency', 'dampingRatio', 'endLength', 'endOffset',
  'gravity', 'force', 'forceUnits', 'gravityRestCompensation', 'wind', 'windTurbulence', 'windFrequency', 'seed',
  'freezeAxis', 'branchMode', 'weight', 'resetDistance', 'substepRoots',
  'dampingCurve', 'elasticityCurve', 'stiffnessCurve', 'inertCurve', 'frictionCurve', 'radiusCurve', 'angleLimitCurve', 'stretchCurve'];

function v3(f) { return [f.x, f.y, f.z]; }
function quat(r) { return SB.qFromAxisAngle([r.x, r.y, r.z], r.angle); }
function plain(value) {
  if (value === null || value === undefined) return value;
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return value;
  if (value.x !== undefined && value.z !== undefined && value.angle === undefined) return [value.x, value.y, value.z];
  if (value.length !== undefined) {           // MFVec2f -> [[t, v], ...]; MFString -> [..]
    var out = [];
    for (var i = 0; i < value.length; i++) { var e = value[i]; out.push(e && e.x !== undefined ? [e.x, e.y] : e); }
    return out;
  }
  return value;
}
// readParams() is generated by tools/build.mjs from PARAM_FIELDS (Script fields are reached by their names)

function hasTransformFields(n) {
  var t = n.getNodeTypeName();
  return t === 'Transform' || t === 'HAnimJoint' || t === 'HAnimHumanoid' || t === 'CADPart' || t === 'GeoTransform';
}
function fieldsOf(n) {
  if (!hasTransformFields(n)) return { translation: [0, 0, 0], center: [0, 0, 0], rotation: [0, 0, 0, 1], scale: [1, 1, 1], scaleOrientation: [0, 0, 0, 1] };
  return { translation: v3(n.translation), center: v3(n.center), rotation: quat(n.rotation), scale: v3(n.scale), scaleOrientation: quat(n.scaleOrientation) };
}
function isExcluded(n) {
  for (var i = 0; i < exclusions.length; i++) if (exclusions[i] && exclusions[i].getNodeName && exclusions[i] === n) return true;
  return false;
}
function isBone(n) {
  if (!n || !n.getNodeTypeName) return false;
  var t = n.getNodeTypeName();
  for (var i = 0; i < boneTypes.length; i++) if (boneTypes[i] === t) return true;
  return false;
}
function walk(root) {
  var nodes = [], joints = [];
  function visit(n, parent) {
    var k = nodes.length;
    nodes.push(n); joints.push({ name: n.getNodeName() || ('bone' + k), parent: parent });
    var kids = n.children;
    for (var i = 0; kids && i < kids.length; i++) if (isBone(kids[i]) && !isExcluded(kids[i])) visit(kids[i], k);
  }
  visit(root, -1);
  return { nodes: nodes, joints: joints };
}
function frameOf(list) {
  var W = SB.IDENTITY;
  for (var i = 0; list && i < list.length; i++) if (list[i]) W = SB.compose(W, SB.affineFromFields(fieldsOf(list[i])));
  return W;
}
function build() {
  trees = []; written = [];
  var descs = [];
  for (var r = 0; r < roots.length; r++) {
    if (!roots[r]) continue;
    var w = walk(roots[r]);
    trees.push(w); descs.push({ joints: w.joints });
    written.push(w.nodes.map(function () { return null; }));
  }
  var p = readParams();
  paramsKey = JSON.stringify(p);
  chain = new SB.SpringChain(descs, p);
  if (chain.equivalent) { equivalentFrequency = chain.equivalent.frequency || 0; equivalentDampingRatio = chain.equivalent.dampingRatio || 0; }
}
// the pose to simulate from: what the scene (or an interpolator) set, not what we wrote last frame
function poseOf(ti) {
  var nodes = trees[ti].nodes, pose = [];
  for (var j = 0; j < nodes.length; j++) {
    var f = fieldsOf(nodes[j]), wr = written[ti][j];
    if (wr) {
      var same = Math.abs(f.rotation[0] - wr.q[0]) + Math.abs(f.rotation[1] - wr.q[1]) + Math.abs(f.rotation[2] - wr.q[2]) + Math.abs(f.rotation[3] - wr.q[3]) < 1e-6 ||
                 Math.abs(f.rotation[0] + wr.q[0]) + Math.abs(f.rotation[1] + wr.q[1]) + Math.abs(f.rotation[2] + wr.q[2]) + Math.abs(f.rotation[3] + wr.q[3]) < 1e-6;
      if (same) f.rotation = wr.animRotation;
      if (wr.t) {
        var tsame = Math.abs(f.translation[0] - wr.t[0]) + Math.abs(f.translation[1] - wr.t[1]) + Math.abs(f.translation[2] - wr.t[2]) < 1e-9;
        if (tsame) f.translation = wr.animTranslation;
      }
    }
    pose.push(f);
  }
  return pose;
}
function colliderList() {
  var out = [];
  for (var i = 0; i < colliders.length; i++) {
    var c = colliders[i];
    if (!c || (c.enabled !== undefined && !c.enabled)) continue;
    var anc = c.ancestors, W = frameOf(anc);
    out.push({ shape: c.shape, bound: c.bound, center: v3(c.center), radius: c.radius, radius2: c.radius2, height: c.height, direction: c.direction, axis: v3(c.axis), world: W });
  }
  return out;
}

function initialize() { build(); }

function tick(t) { if (clock) advance(t); }
function set_time(t) { advance(t); }

function advance(t) {
  if (!chain) build();
  var key = JSON.stringify(readParams());
  if (key !== paramsKey) {
    paramsKey = key;
    chain.retune(JSON.parse(key));
    if (chain.equivalent) { equivalentFrequency = chain.equivalent.frequency || 0; equivalentDampingRatio = chain.equivalent.dampingRatio || 0; }
  }
  var dt = lastTime < 0 ? 0 : Math.max(0, Math.min(t - lastTime, 0.25));
  lastTime = t;
  var parentWorld = frameOf(ancestors);
  var inputs = [], poses = [];
  for (var ti = 0; ti < trees.length; ti++) { var pose = poseOf(ti); poses.push(pose); inputs.push({ parentWorld: parentWorld, pose: pose }); }
  var ref = reference && reference.length ? frameOf(reference) : parentWorld;
  var out = chain.frame({ dt: dt, time: t, trees: inputs, reference: ref, colliders: colliderList() });
  var tips = [];
  for (ti = 0; ti < trees.length; ti++) {
    var o = out.trees[ti], nodes = trees[ti].nodes;
    for (var j = 0; j < nodes.length; j++) {
      var q = o.rotations[j], tr = o.translations[j];
      if (q) {
        var aa = SB.qToAxisAngle(q);
        nodes[j].rotation = new SFRotation(aa[0], aa[1], aa[2], aa[3]);
        written[ti][j] = { q: SB.qFromAxisAngle([aa[0], aa[1], aa[2]], aa[3]), animRotation: poses[ti][j].rotation, t: null, animTranslation: null };
      }
      if (tr) {
        nodes[j].translation = new SFVec3f(tr[0], tr[1], tr[2]);
        written[ti][j] = written[ti][j] || { q: [9, 9, 9, 9], animRotation: poses[ti][j].rotation };
        written[ti][j].t = tr; written[ti][j].animTranslation = poses[ti][j].translation;
      }
    }
    var ps = o.positions;
    for (var k = 0; k < ps.length; k++) tips.push(new SFVec3f(ps[k][0], ps[k][1], ps[k][2]));
  }
  positions = new (Function.prototype.bind.apply(MFVec3f, [null].concat(tips)))();
  steps = chain.steps;
  if (out.droppedTime !== droppedReported) { droppedReported = out.droppedTime; droppedTime = out.droppedTime; }
  collided = out.collided;
  stateHash = chain.stateHash();
}

function set_reset(v) { if (v) { chain = null; lastTime = -1; build(); } }

function readParams() {
  var p = {};
  p.enabled = plain(enabled);
  p.updateRate = plain(updateRate);
  p.timeMode = plain(timeMode);
  p.maxSubsteps = plain(maxSubsteps);
  p.interpolate = plain(interpolate);
  p.springModel = plain(springModel);
  p.damping = plain(damping);
  p.elasticity = plain(elasticity);
  p.stiffness = plain(stiffness);
  p.inert = plain(inert);
  p.friction = plain(friction);
  p.radius = plain(radius);
  p.angleLimit = plain(angleLimit);
  p.stretch = plain(stretch);
  p.dampingCurve = plain(dampingCurve);
  p.elasticityCurve = plain(elasticityCurve);
  p.stiffnessCurve = plain(stiffnessCurve);
  p.inertCurve = plain(inertCurve);
  p.frictionCurve = plain(frictionCurve);
  p.radiusCurve = plain(radiusCurve);
  p.angleLimitCurve = plain(angleLimitCurve);
  p.stretchCurve = plain(stretchCurve);
  p.frequency = plain(frequency);
  p.dampingRatio = plain(dampingRatio);
  p.endLength = plain(endLength);
  p.endOffset = plain(endOffset);
  p.gravity = plain(gravity);
  p.force = plain(force);
  p.forceUnits = plain(forceUnits);
  p.gravityRestCompensation = plain(gravityRestCompensation);
  p.wind = plain(wind);
  p.windTurbulence = plain(windTurbulence);
  p.windFrequency = plain(windFrequency);
  p.seed = plain(seed);
  p.freezeAxis = plain(freezeAxis);
  p.branchMode = plain(branchMode);
  p.weight = plain(weight);
  p.resetDistance = plain(resetDistance);
  p.substepRoots = plain(substepRoots);
  return p;
}
