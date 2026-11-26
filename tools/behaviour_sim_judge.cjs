// SPDX-FileCopyrightText: 2026 HagopJay
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Records what X_ITE does with a behaviour graph, event by event, so tools/behaviour_sim_judge.py can ask the Python
// simulator (source/behaviour_sim.py) to do the same and compare.
//   NODE_PATH=$(npm root -g) node tools/behaviour_sim_judge.cjs <x_ite dist dir> <file.x3d> <sources.json> <clicks> <seconds> > trace.json
//   ... <seconds> --click-plan plan.json > trace.json   plan.json: ["SensorDEF", ...]: each named sensor is hunted (pointer sweep until its isOver) and clicked once, then 3.5 s for its flight (pass 0 clicks)
//   ... <seconds> [drags.json] > trace.json        with drags: real drags instead of clicks (pass 0 clicks)
// sources.json: [["DEF","field"], ...] every ROUTE source of the file (written by the .py with --sources).
// drags.json (tools/behaviour_probe.py writes one): {"drags": [{"sensor", "touch", "at": [x, y], "path": [[x, y], ...]}]}.
// Each drag presses at "at", moves through "path" one point every 80 ms, and releases. Every pointer event is logged
// with X_ITE's time ("pointer" in the trace) so the replay can rebuild the pointer's ray.
// A pointing sensor is found by moving the real pointer until one reports isOver; then <clicks> real clicks follow.
// Every event carries X_ITE's own time stamp (browser.currentTime). Software GL: values and order are claims.
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path');
const rawArgs = process.argv.slice(2);
// --click-plan FILE (a JSON list of pointing-sensor DEFs): hunt for each named sensor in turn, click it, wait for its flight
const planAt = rawArgs.indexOf('--click-plan');
const clickPlan = planAt >= 0 ? JSON.parse(fs.readFileSync(rawArgs.splice(planAt, 2)[1], 'utf8')) : null;
const [xiteDir, file, sourcesFile, clicksArg, secondsArg, dragsFile] = rawArgs;
const plan = dragsFile ? JSON.parse(fs.readFileSync(dragsFile, 'utf8')) : null;
const sources = JSON.parse(fs.readFileSync(sourcesFile, 'utf8'));
const types = { '.js': 'text/javascript', '.css': 'text/css', '.x3d': 'model/x3d+xml' };
const page = `<!doctype html><meta charset=utf-8><link rel=stylesheet href=/xite/x_ite.css><script src=/xite/x_ite.min.js></script>
<style>body{margin:0}x3d-canvas{width:960px;height:600px;display:block}</style>
<x3d-canvas id=c contextMenu=false notifications=false splashScreen=false timings=false></x3d-canvas>`;
const srv = http.createServer((q, r) => {
  const u = decodeURIComponent(q.url.split('?')[0]);
  if (u === '/') { r.writeHead(200, { 'content-type': 'text/html' }); return r.end(page); }
  const f = u === '/file' ? file : path.join(xiteDir, u.replace(/^\/xite\//, ''));
  fs.readFile(f, (e, d) => { if (e) { r.writeHead(404); return r.end(); } r.writeHead(200, { 'content-type': types[path.extname(f)] || 'application/octet-stream' }); r.end(d); });
}).listen(0);
const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const p = await b.newPage({ viewport: { width: 960, height: 600 } });
  const errors = []; p.on('pageerror', e => errors.push(String(e)));
  await p.goto(`http://localhost:${srv.address().port}/`);
  await p.evaluate(async () => { const B = X3D.getBrowser(document.getElementById('c')); await B.loadURL(new X3D.MFString('/file')); });
  await p.waitForFunction(s => { try { return !!X3D.getBrowser(document.getElementById('c')).currentScene.getNamedNode(s); } catch (e) { return false; } }, sources[0][0], { timeout: 90000 });
  await sleep(3000);   // let followers settle before recording
  const info = await p.evaluate(sources => {
    const B = X3D.getBrowser(document.getElementById('c')), s = B.currentScene;
    window.__events = []; window.__frames = []; window.__pointer = [];
    // capture: logged before X_ITE sees the event. The time is the wall clock X_ITE's own times are taken from, not
    // getCurrentTime(): that only moves when X_ITE draws a frame, and nothing is drawn while the pointer rests.
    for (const type of ['mousedown', 'mousemove', 'mouseup'])
      window.addEventListener(type, e => window.__pointer.push([(performance.timeOrigin + performance.now()) / 1000, type, e.pageX, e.pageY]), true);
    const text = v => (v !== null && typeof v === 'object') ? String(v) : v;
    const missing = [], sensors = [];
    sources.forEach(([d, f], i) => {
      try {
        const node = s.getNamedNode(d);
        node.getField(f).addFieldCallback('judge' + i, v => window.__events.push([B.getCurrentTime(), d, f, text(v)]));
        if (/Sensor$/.test(node.getNodeTypeName()) && node.getNodeTypeName() !== 'TimeSensor' && !sensors.includes(d)) sensors.push(d);
      } catch (e) { missing.push([d, f, String(e)]); }
    });
    // what every source held when recording began (an output that last changed before then is still in force)
    window.__initial = sources.map(([d, f]) => { try { return [d, f, text(s.getNamedNode(d).getField(f).getValue())]; } catch (e) { return null; } }).filter(Boolean);
    const tick = () => { window.__frames.push(B.getCurrentTime()); requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
    return { missing, sensors, began: B.getCurrentTime(), version: B.version, name: B.name };
  }, sources);
  let hit = null;
  if (info.sensors.length && Number(clicksArg) > 0) {
    scan: for (let y = 60; y < 600; y += 30) for (let x = 60; x < 960; x += 30) {
      await p.mouse.move(x - 3, y - 3); await p.mouse.move(x, y, { steps: 2 }); await sleep(120);
      if (await p.evaluate(ss => { const s = X3D.getBrowser(document.getElementById('c')).currentScene; return ss.some(d => s.getNamedNode(d).isOver); }, info.sensors)) { hit = { x, y }; break scan; }
    }
    for (let k = 0; hit && k < Number(clicksArg); k++) {
      await p.mouse.move(hit.x, hit.y); await p.mouse.down(); await sleep(140); await p.mouse.up(); await sleep(1100);
    }
  }
  const planned = [];
  for (const def of clickPlan || []) {     // each named sensor: sweep the pointer until that sensor reports isOver, then click it
    let at = null;
    for (let pass = 0; pass < 2 && !at; pass++) scan: for (let y = 30 + 15 * pass; y < 600; y += 30) for (let x = 30 + 15 * pass; x < 960; x += 30) {
      await p.mouse.move(x - 3, y - 3); await p.mouse.move(x, y, { steps: 2 }); await sleep(100);
      if (await p.evaluate(d => X3D.getBrowser(document.getElementById('c')).currentScene.getNamedNode(d).isOver, def)) { at = { x, y }; break scan; }
    }
    planned.push({ sensor: def, at });
    if (!at) continue;
    await p.mouse.down(); await sleep(140); await p.mouse.up(); await sleep(3500);
  }
  const drags = [];
  for (const drag of plan ? plan.drags : []) {
    const [x, y] = drag.at;
    await p.mouse.move(x - 4, y - 4); await p.mouse.move(x, y); await sleep(250);
    const down = await p.evaluate(() => X3D.getBrowser(document.getElementById('c')).getCurrentTime());
    await p.mouse.down(); await sleep(120);
    for (const [px, py] of drag.path) { await p.mouse.move(px, py); await sleep(80); }
    await p.mouse.up(); await sleep(500);
    drags.push({ sensor: drag.sensor, touch: drag.touch, at: drag.at, down });
  }
  await sleep(Number(secondsArg) * 1000);
  const out = await p.evaluate(() => ({ events: window.__events, frames: window.__frames, pointer: window.__pointer, initial: window.__initial }));
  await b.close(); srv.close();
  console.log(JSON.stringify({ file: path.basename(file), browser: `${info.name} ${info.version}`, began: info.began, sensorAt: hit, clickPlan: planned, clicks: Number(clicksArg), missing: info.missing, pageErrors: errors, frames: out.frames, events: out.events, initial: out.initial,
    ...(plan ? { view: plan.view, drags, pointer: out.pointer } : {}) }));
})();
