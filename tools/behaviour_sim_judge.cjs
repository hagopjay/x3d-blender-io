// SPDX-FileCopyrightText: 2026 HagopJay
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Records what X_ITE does with a behaviour graph, event by event, so tools/behaviour_sim_judge.py can ask the Python
// simulator (source/behaviour_sim.py) to do the same and compare.
//   NODE_PATH=$(npm root -g) node tools/behaviour_sim_judge.cjs <x_ite dist dir> <file.x3d> <sources.json> <clicks> <seconds> > trace.json
//   ... <seconds> [drags.json] > trace.json        with drags: real drags instead of clicks (pass 0 clicks)
//   ... <seconds> --keys keys.json > trace.json    with keys: real typing instead of clicks (pass 0 clicks); after the positionals
// sources.json: [["DEF","field"], ...] every ROUTE source of the file (written by the .py with --sources).
// drags.json (tools/behaviour_probe.py writes one): {"drags": [{"sensor", "touch", "at": [x, y], "path": [[x, y], ...]}]}.
// Each drag presses at "at", moves through "path" one point every 80 ms, and releases. Every pointer event is logged
// with X_ITE's time ("pointer" in the trace) so the replay can rebuild the pointer's ray.
// keys.json (the demo's own): {"keys": [{"type": "Hello"}, {"press": "Shift+A"}, {"press": "ArrowUp"}, ...], "gap_ms": 150}.
// The canvas is focused and Playwright types each step: "type" is one key per character (a letter that needs Shift is
// sent with it), "press" is one chord ("Shift+A", "F1", "Enter"). Every keydown and keyup X_ITE saw is logged ("keys" in
// the trace) with X_ITE's own time stamp (browser.currentTime, taken after X_ITE's handler has advanced it) and the
// fields its KeySensor and StringSensor read: key, which, charCode, keyCode.
// A step {"down": "Shift"} / {"up": "Shift"} holds a key and lets it go (to click or type with a modifier held).
// A step {"click": "DEF"} presses the pointing sensor DEF with the real mouse (found by moving the pointer until it reports
// isOver, or at "at": [x, y] when the step says where), holds it 140 ms and lets go: a click in the middle of the typing.
// A pointing sensor is found by moving the real pointer until one reports isOver; then <clicks> real clicks follow.
// Every event carries X_ITE's own time stamp (browser.currentTime). Software GL: values and order are claims.
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path');
const argv = process.argv.slice(2), keysAt = argv.indexOf('--keys');
const keysFile = keysAt >= 0 ? argv[keysAt + 1] : null;
if (keysAt >= 0) argv.splice(keysAt, 2);
const [xiteDir, file, sourcesFile, clicksArg, secondsArg, dragsFile] = argv;
const plan = dragsFile ? JSON.parse(fs.readFileSync(dragsFile, 'utf8')) : null;
const keyPlan = keysFile ? JSON.parse(fs.readFileSync(keysFile, 'utf8')) : null;
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
    window.__events = []; window.__frames = []; window.__pointer = []; window.__keys = [];
    // bubbling, so X_ITE's own handler on the canvas has already advanced its clock: its time stamp for this key
    for (const type of ['keydown', 'keyup'])
      window.addEventListener(type, e => window.__keys.push([B.getCurrentTime(), type, e.key, e.which, e.charCode, e.keyCode]), false);
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
  const spots = {};
  if (keyPlan) {
    await p.focus('x3d-canvas');
    const gap = keyPlan.gap_ms || 150;
    const isOver = def => p.evaluate(d => X3D.getBrowser(document.getElementById('c')).currentScene.getNamedNode(d).isOver, def);
    const spotOf = async (def, at) => {
      if (spots[def]) return spots[def];
      if (at) {
        await p.mouse.move(at[0] - 3, at[1] - 3); await p.mouse.move(at[0], at[1], { steps: 2 }); await sleep(250);
        if (await isOver(def)) return (spots[def] = { x: at[0], y: at[1] });
      }
      const tries = [];
      for (let y = 60; y < 600; y += 30) for (let x = 60; x < 960; x += 30) tries.push([x, y]);
      for (const [x, y] of tries) {
        await p.mouse.move(x - 3, y - 3); await p.mouse.move(x, y, { steps: 2 }); await sleep(120);
        if (await isOver(def)) return (spots[def] = { x, y });
      }
      throw new Error('no point over ' + def);
    };
    for (const step of keyPlan.keys) {
      if (step.click) {
        const { x, y } = await spotOf(step.click, step.at);
        await p.mouse.move(x, y); await sleep(200); await p.mouse.down(); await sleep(140); await p.mouse.up(); await sleep(gap);
        await p.focus('x3d-canvas');
      }
      else if (step.down) { await p.keyboard.down(step.down); await sleep(gap); }
      else if (step.up) { await p.keyboard.up(step.up); await sleep(gap); }
      else if (step.type !== undefined) for (const ch of step.type) { await p.keyboard.press(ch === ' ' ? 'Space' : /[A-Z]/.test(ch) ? `Shift+${ch}` : ch); await sleep(gap); }
      else { await p.keyboard.press(step.press); await sleep(gap); }
      if (step.wait_ms) await sleep(step.wait_ms);
    }
  }
  await sleep(Number(secondsArg) * 1000);
  const out = await p.evaluate(() => ({ events: window.__events, frames: window.__frames, pointer: window.__pointer, keys: window.__keys, initial: window.__initial }));
  await b.close(); srv.close();
  console.log(JSON.stringify({ file: path.basename(file), browser: `${info.name} ${info.version}`, began: info.began, sensorAt: hit, clicks: Number(clicksArg), missing: info.missing, pageErrors: errors, frames: out.frames, events: out.events, initial: out.initial,
    ...(plan ? { view: plan.view, drags, pointer: out.pointer } : {}), ...(keyPlan ? { keyPlan, keys: out.keys, spots } : {}) }));
})();
