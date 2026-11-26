// SPDX-FileCopyrightText: 2026 HagopJay
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Records what X_ITE does with the pick sensors of a world, event by event, in the format of tools/behaviour_sim_judge.cjs
// (so tools/behaviour_pick_judge.py can judge it), with one difference: a node list (MFNode: a pick sensor's
// pickedGeometry) is written as the DEF names of its nodes, "[B1,B2]", because the other recorder writes a node as "Box { }".
//   NODE_PATH=$(npm root -g) node tools/behaviour_pick_record.cjs <x_ite dist dir> <file.x3d> <sources.json> <seconds> [--settle=3000] > trace.json
// sources.json: [["DEF","field"], ...] (tools/behaviour_sim_judge.py --sources writes one). The first source must be a
// node that exists once the world has loaded; its DEF is waited for. Software GL: values and order are claims.
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path');
const flags = Object.fromEntries(process.argv.slice(2).filter(a => /^--[a-z]+=/.test(a)).map(a => a.slice(2).split(/=(.*)/s).slice(0, 2)));
const [xiteDir, file, sourcesFile, secondsArg] = process.argv.slice(2).filter(a => !/^--[a-z]+=/.test(a));
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
  await sleep(Number(flags.settle || 3000));
  const info = await p.evaluate(sources => {
    const B = X3D.getBrowser(document.getElementById('c')), s = B.currentScene;
    window.__events = []; window.__frames = [];
    // a node list is its DEF names (a node without one: its type), anything else as the other recorder writes it
    const text = v => v instanceof X3D.MFNode ? '[' + Array.from(v).map(n => n.getNodeName() || n.getNodeTypeName()).join(',') + ']'
      : (v !== null && typeof v === 'object') ? String(v) : v;
    const missing = [];
    sources.forEach(([d, f], i) => {
      try { s.getNamedNode(d).getField(f).addFieldCallback('judge' + i, v => window.__events.push([B.getCurrentTime(), d, f, text(v)])); }
      catch (e) { missing.push([d, f, String(e)]); }
    });
    window.__initial = sources.map(([d, f]) => { try { return [d, f, text(s.getNamedNode(d).getField(f).getValue())]; } catch (e) { return null; } }).filter(Boolean);
    const tick = () => { window.__frames.push(B.getCurrentTime()); requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
    return { missing, began: B.getCurrentTime(), version: B.version, name: B.name };
  }, sources);
  await sleep(Number(secondsArg) * 1000);
  const out = await p.evaluate(() => ({ events: window.__events, frames: window.__frames, initial: window.__initial }));
  await b.close(); srv.close();
  console.log(JSON.stringify({ file: path.basename(file), browser: `${info.name} ${info.version}`, began: info.began, sensorAt: null, clickPlan: [], clicks: 0, holds: [],
    missing: info.missing, pageErrors: errors, frames: out.frames, events: out.events, initial: out.initial }));
})();
