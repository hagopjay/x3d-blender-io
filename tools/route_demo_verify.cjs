// SPDX-FileCopyrightText: 2026 HagopJay
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Drives the exported route-demo.x3d in headless Chromium + X_ITE with real mouse events and records which timers and
// viewpoints the ROUTEs moved. Usage:
//   NODE_PATH=$(npm root -g) node tools/route_demo_verify.cjs <route-demo.x3d> <x_ite dist dir> <out dir>
// Writes receipt.json and the stills. Software GL (SwiftShader) draws ~0.6 s a frame: only the order of events and the
// timer states are claims, never a frame rate.
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path');

const [x3dPath, xiteDir, outDir] = process.argv.slice(2);
fs.mkdirSync(outDir, { recursive: true });
const page = `<!doctype html><meta charset=utf-8><link rel=stylesheet href=/xite/x_ite.css><script src=/xite/x_ite.min.js></script>
<style>body{margin:0}x3d-canvas{width:960px;height:600px;display:block}</style>
<x3d-canvas id=c src=/scene.x3d contextMenu=false notifications=false splashScreen=false timings=false></x3d-canvas>`;
const types = { '.js': 'text/javascript', '.css': 'text/css', '.x3d': 'model/x3d+xml', '.html': 'text/html' };
const srv = http.createServer((q, r) => {
  const u = decodeURIComponent(q.url.split('?')[0]);
  const f = u === '/' ? null : u === '/scene.x3d' ? x3dPath : path.join(xiteDir, u.replace(/^\/xite\//, ''));
  if (!f) { r.writeHead(200, { 'content-type': 'text/html' }); return r.end(page); }
  fs.readFile(f, (e, d) => { if (e) { r.writeHead(404); return r.end(); }
    r.writeHead(200, { 'content-type': types[path.extname(f)] || 'application/octet-stream' }); r.end(d); });
}).listen(0);

const TIMERS = ['SceneTimer', 'TT_Door', 'TT_Beacon', 'TourTimer', 'PS_Beacon'];
const state = p => p.evaluate(t => { const B = X3D.getBrowser(document.getElementById('c')), s = B.currentScene;
  return { viewpoint: B.activeViewpoint.description, active: t.filter(n => s.getNamedNode(n).isActive) }; }, TIMERS);
const move = async (p, x, y) => { await p.mouse.move(x - 6, y - 6); await p.waitForTimeout(250); await p.mouse.move(x, y, { steps: 4 });
  await p.waitForTimeout(400); };
const click = async (p, x, y) => { await move(p, x, y); await p.mouse.down(); await p.waitForTimeout(80); await p.mouse.up(); };
const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const p = await b.newPage({ viewport: { width: 960, height: 600 } });
  await p.goto(`http://localhost:${srv.address().port}/`);
  await p.waitForFunction(() => { try { return X3D.getBrowser(document.getElementById('c')).currentScene.getNamedNode('TS_DoorButton'); } catch (e) { return false; } }, null, { timeout: 90000 });
  await sleep(2500);
  const receipt = { xite: await p.evaluate(() => X3D.getBrowser().version), chromium: b.version(), steps: [] };
  const log = async (label, extra = {}) => { const s = await state(p); receipt.steps.push({ label, ...s, ...extra }); console.log(label, JSON.stringify(s)); };
  await log('loaded');
  await p.screenshot({ path: path.join(outDir, '01-start.png') });

  await click(p, 225, 420);                                    // green button: plays the Door's animation
  await sleep(500); await log('click DoorButton'); await p.screenshot({ path: path.join(outDir, '02-door-mid.png') });
  await sleep(2600); await log('door finished'); await p.screenshot({ path: path.join(outDir, '03-door-open.png') });

  await click(p, 735, 420);                                    // blue button: bind the Overview camera
  await sleep(1800); await log('click OverviewButton'); await p.screenshot({ path: path.join(outDir, '04-overview.png') });
  await p.evaluate(() => { const B = X3D.getBrowser(document.getElementById('c')); B.currentScene.getNamedNode('CA_Start').set_bind = true; });
  await sleep(1800); await log('back to Start by SAI (a test-rig step, not a ROUTE)');

  await click(p, 480, 505);                                    // orange button: start the tour
  const t0 = Date.now(); let shots = 0;
  while (Date.now() - t0 < 20000) {
    await sleep(900);
    const s = await state(p); const t = ((Date.now() - t0) / 1000).toFixed(1);
    receipt.steps.push({ label: `tour t=${t}s`, ...s }); console.log(`tour t=${t}s`, JSON.stringify(s));
    if (shots < 4 && s.active.includes('TourTimer') && Date.now() - t0 > 1500 + shots * 4500) {
      await p.screenshot({ path: path.join(outDir, `05-tour-${++shots}.png`) }); }
    if (!s.active.includes('TourTimer') && Date.now() - t0 > 3000) break;
  }
  await log('tour over');

  // Proximity: the tour passes the beacon, but X_ITE 16.7.1 did not fire PS_Beacon during it (Suspected: the sensor
  // is not re-evaluated while the viewpoint moves through an animated parent after a bind transition). Binding the
  // camera that sits inside the beacon's box does fire it, so the sensor -> timer ROUTE is proven that way.
  await p.evaluate(() => { const B = X3D.getBrowser(document.getElementById('c')); B.currentScene.getNamedNode('CA_Tour2_Beacon').set_bind = true; });
  await sleep(2300); await log('bind the camera inside the beacon box (SAI, a test-rig step)');
  await p.screenshot({ path: path.join(outDir, '06-beacon.png') });
  await sleep(2500); await log('beacon animation finished');
  fs.writeFileSync(path.join(outDir, 'receipt.json'), JSON.stringify(receipt, null, 1));
  await b.close(); srv.close();
})();
