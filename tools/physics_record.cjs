// SPDX-FileCopyrightText: 2026 HagopJay
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Records what X_ITE's own physics (Ammo.js, a Bullet build) does with an X3D RigidBodyPhysics scene, step by step, so
// tools/physics_judge.py can put it next to Blender's rigid body world and the analytic answer.
//   NODE_PATH=$(npm root -g) node tools/physics_record.cjs <x_ite dist dir> <file.x3d> <seconds> [--fps=60] [--runs=2]
//                                                           [--rename-friction] > trace.json
//
// X_ITE steps Bullet once per drawn frame by 1 / max(10, frame rate), averaged over 15 frames from 0
// (RigidBodyCollection.getTimeStep), so what it computes depends on how fast the machine draws. Here every collection's
// getTimeStep returns exactly 1/fps and the page steps the collections itself, frame by frame, without drawing: the
// physics X_ITE runs, on a fixed clock. That is a change to X_ITE's timing and nothing else (its update(), its bodies,
// shapes, joints, friction and bounce are its own). The scene loads with X_ITE's own stepping off, so no step is taken
// before the clock is fixed; the first sample is the authored state.
//
// --rename-friction rewrites FRICTION_COEFFICIENT-2 (the X3D schema's spelling) as FRICTION_COEFFICIENT_2 (X_ITE's) in
// the copy given to X_ITE; without it X_ITE ignores the parameter, which is what a valid file gets in X_ITE.
// Each step's state (every body's float32 position, quaternion, linear and angular velocity) is hashed with FNV-1a, and
// --runs loads the scene again in a fresh page and compares the hashes (playbook pattern 3, one host).
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path');
const flags = Object.fromEntries(process.argv.slice(2).filter(a => a.startsWith('--')).map(a => { const [k, v] = a.slice(2).split('='); return [k, v ?? true]; }));
const [xiteDir, file, secondsArg] = process.argv.slice(2).filter(a => !a.startsWith('--'));
const fps = Number(flags.fps || 60), runs = Number(flags.runs || 2), seconds = Number(secondsArg || 3);
let xml = fs.readFileSync(file, 'utf8');
if (flags['rename-friction']) xml = xml.replace(/FRICTION_COEFFICIENT-2/g, 'FRICTION_COEFFICIENT_2');
const types = { '.js': 'text/javascript', '.css': 'text/css', '.wasm': 'application/wasm' };
const page = `<!doctype html><meta charset=utf-8><link rel=stylesheet href=/xite/x_ite.css><script src=/xite/x_ite.min.js></script>
<body style=margin:0><x3d-canvas id=c style="width:64px;height:64px;display:block" contextMenu=false notifications=false splashScreen=false></x3d-canvas>`;
const srv = http.createServer((q, r) => {
  const u = decodeURIComponent(q.url.split('?')[0]);
  if (u === '/') { r.writeHead(200, { 'content-type': 'text/html' }); return r.end(page); }
  const f = path.join(xiteDir, u.replace(/^\/xite\//, ''));
  fs.readFile(f, (e, d) => { if (e) { r.writeHead(404); return r.end(); } r.writeHead(200, { 'content-type': types[path.extname(f)] || 'application/octet-stream' }); r.end(d); });
}).listen(0);

async function record(browser) {
  const p = await browser.newPage();
  const errors = []; p.on('pageerror', e => errors.push(String(e).slice(0, 300)));
  await p.goto(`http://localhost:${srv.address().port}/`);
  await p.waitForFunction(() => window.X3D);
  const out = await p.evaluate(async ([xml, fps, steps]) => {
    const B = X3D.getBrowser(document.getElementById('c'));
    await B.loadComponents(B.getProfile('Full'), B.getComponent('RigidBodyPhysics'));
    const scene = await B.createX3DFromString(xml);
    // every RigidBodyCollection in the scene graph (SAI walk over SFNode / MFNode fields), before it goes live
    const seen = new Set(), cols = [];
    const walk = (sf) => {
      if (!sf) return; const n = sf.getValue ? sf.getValue() : sf; if (!n || seen.has(n)) return; seen.add(n);
      if (n.getTypeName && n.getTypeName() === 'RigidBodyCollection') cols.push(n);
      for (const f of n.getFields ? n.getFields() : []) {
        const t = f.getTypeName ? f.getTypeName() : '';
        if (t === 'SFNode') walk(f.getValue());
        else if (t === 'MFNode') for (const c of f) walk(c);
      }
    };
    for (const r of scene.rootNodes) walk(r);
    // X_ITE's own stepping off. sensorEvents().addInterest("update", c) keeps the function it found at that moment, so
    // take away a registration already made with the original, then leave a no-op for any later one to find.
    const originals = cols.map(c => c.update), registered = cols.map(c => c.getBrowser().sensorEvents().hasInterest('update', c));
    for (const c of cols) { c.getBrowser().sensorEvents().removeInterest('update', c); c.getTimeStep = () => 1 / fps; c.update = function () {}; }
    await B.replaceWorld(scene);
    await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));          // let the world initialise
    const bodies = [];
    cols.forEach((c, ci) => c.bodyNodes.forEach((b, bi) => bodies.push({ name: b.getName() || `c${ci}b${bi}`, node: b })));
    const tr = Object.fromEntries(bodies.map(b => [b.name, { p: [], q: [], v: [], w: [] }]));
    const hashes = [], f32 = new Float32Array(13 * bodies.length), u8 = new Uint8Array(f32.buffer);
    const sample = () => {
      let k = 0;
      for (const b of bodies) {
        const rb = b.node.getRigidBody(), t = rb.getWorldTransform(), o = t.getOrigin(), q = t.getRotation(), v = rb.getLinearVelocity(), w = rb.getAngularVelocity();
        const s = [o.x(), o.y(), o.z(), q.x(), q.y(), q.z(), q.w(), v.x(), v.y(), v.z(), w.x(), w.y(), w.z()];
        const T = tr[b.name]; T.p.push(s.slice(0, 3)); T.q.push(s.slice(3, 7)); T.v.push(s.slice(7, 10)); T.w.push(s.slice(10, 13));
        for (const x of s) f32[k++] = x;
      }
      let h = 0x811c9dc5; for (const x of u8) { h ^= x; h = Math.imul(h, 0x01000193) >>> 0; } hashes.push(h);
    };
    sample();
    for (let i = 0; i < steps; i++) { cols.forEach((c, ci) => originals[ci].call(c)); sample(); }
    return { version: B.version, registered_before_live: registered, steps, dt: 1 / fps, bodies: bodies.map(b => b.name), collections: cols.length, trajectories: tr, hashes };
  }, [xml, fps, Math.round(seconds * fps)]);
  await p.close();
  out.errors = errors;
  return out;
}

(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const all = [];
  for (let k = 0; k < runs; k++) all.push(await record(b));
  const first = all[0];
  const replays = all.slice(1).map(r => { const i = r.hashes.findIndex((h, j) => h !== first.hashes[j]); return { mismatches: r.hashes.filter((h, j) => h !== first.hashes[j]).length, first_mismatch: i < 0 ? null : i }; });
  const result = { schema: 'x3d-blender-io.physics-trace/1', engine: 'x_ite', engine_version: first.version, browser: b.version(), registered_before_live: first.registered_before_live,
    file: path.basename(file), fps, dt: first.dt, steps: first.steps, collections: first.collections, bodies: first.bodies,
    renamed_friction: !!flags['rename-friction'], errors: first.errors, replays, hashes: first.hashes, trajectories: first.trajectories };
  await b.close(); srv.close();
  process.stdout.write(JSON.stringify(result));
})().catch(e => { console.error(e); srv.close(); process.exit(3); });
