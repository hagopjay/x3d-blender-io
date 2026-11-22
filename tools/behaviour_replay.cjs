// SPDX-FileCopyrightText: 2026 HagopJay
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Behaviour replay: plays the same real mouse clicks on two X3D files in headless Chromium + X_ITE and compares what
// the scene did. Used to check that a file still behaves the same after a trip through Blender.
//   NODE_PATH=$(npm root -g) node tools/behaviour_replay.cjs <x_ite dist dir> <sensor DEF> <watch DEF.field,...> <clicks> <a.x3d> <b.x3d>
// The sensor is found by moving the real pointer until the sensor reports isOver. After each click the watched fields
// are sampled at fixed delays. Software GL: values and order are claims, frame rate is not.
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path');
const [xiteDir, sensor, watchArg, clicksArg, ...files] = process.argv.slice(2);
const watch = watchArg.split(',').map(w => w.split('.'));
const types = { '.js': 'text/javascript', '.css': 'text/css', '.x3d': 'model/x3d+xml' };
const page = `<!doctype html><meta charset=utf-8><link rel=stylesheet href=/xite/x_ite.css><script src=/xite/x_ite.min.js></script>
<style>body{margin:0}x3d-canvas{width:960px;height:600px;display:block}</style>
<x3d-canvas id=c contextMenu=false notifications=false splashScreen=false timings=false></x3d-canvas>`;
const srv = http.createServer((q, r) => {
  const u = decodeURIComponent(q.url.split('?')[0]);
  if (u === '/') { r.writeHead(200, { 'content-type': 'text/html' }); return r.end(page); }
  const f = u.startsWith('/file/') ? files[Number(u.slice(6))] : path.join(xiteDir, u.replace(/^\/xite\//, ''));
  fs.readFile(f, (e, d) => { if (e) { r.writeHead(404); return r.end(); } r.writeHead(200, { 'content-type': types[path.extname(f)] || 'application/octet-stream' }); r.end(d); });
}).listen(0);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const round = v => String(v).split(' ').map(x => Number.isNaN(Number(x)) ? x : +Number(x).toFixed(2)).join(' ');

(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const runs = [];
  for (let i = 0; i < files.length; i++) {
    const p = await b.newPage({ viewport: { width: 960, height: 600 } });
    await p.goto(`http://localhost:${srv.address().port}/`);
    await p.evaluate(async u => { const B = X3D.getBrowser(document.getElementById('c')); await B.loadURL(new X3D.MFString(u)); }, `/file/${i}`);
    await p.waitForFunction(s => { try { return !!X3D.getBrowser(document.getElementById('c')).currentScene.getNamedNode(s); } catch (e) { return false; } }, sensor, { timeout: 90000 });
    await sleep(2500);
    const read = () => p.evaluate(w => { const s = X3D.getBrowser(document.getElementById('c')).currentScene; return w.map(([d, f]) => { const v = s.getNamedNode(d)[f]; return typeof v === 'object' ? String(v) : v; }); }, watch);
    let hit = null;
    scan: for (let y = 60; y < 600; y += 30) for (let x = 60; x < 960; x += 30) {
      await p.mouse.move(x - 3, y - 3); await p.mouse.move(x, y, { steps: 2 }); await sleep(120);
      if (await p.evaluate(s => X3D.getBrowser(document.getElementById('c')).currentScene.getNamedNode(s).isOver, sensor)) { hit = { x, y }; break scan; }
    }
    const samples = [(await read()).map(round)];
    for (let k = 0; hit && k < Number(clicksArg); k++) {
      await p.mouse.move(hit.x, hit.y); await p.mouse.down(); await sleep(90); await p.mouse.up();
      await sleep(900); samples.push((await read()).map(round));
    }
    await sleep(4000); samples.push((await read()).map(round));
    runs.push({ file: path.basename(files[i]), sensorAt: hit, samples });
    await p.close();
  }
  await b.close(); srv.close();
  const same = runs.length === 2 && JSON.stringify(runs[0].samples) === JSON.stringify(runs[1].samples) && JSON.stringify(runs[0].sensorAt) === JSON.stringify(runs[1].sensorAt);
  console.log(JSON.stringify({ sensor, watch: watchArg, clicks: Number(clicksArg), runs, same }, null, 1));
  process.exit(same || runs.length !== 2 ? 0 : 1);
})();
