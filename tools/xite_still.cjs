// SPDX-FileCopyrightText: 2026 HagopJay
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Draw X3D files in headless Chromium + X_ITE and save 960x600 stills (software GL, 0.6 s a frame: pictures only).
//   NODE_PATH=$(npm root -g) node tools/xite_still.cjs <x_ite dist dir> <out dir> <a.x3d> [<b.x3d> ...]
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path');
const [xiteDir, outDir, ...files] = process.argv.slice(2);
fs.mkdirSync(outDir, { recursive: true });
let current = null;
const page = `<!doctype html><meta charset=utf-8><link rel=stylesheet href=/xite/x_ite.css><script src=/xite/x_ite.min.js></script>
<style>body{margin:0}x3d-canvas{width:960px;height:600px;display:block}</style>
<x3d-canvas id=c src=/scene.x3d contextMenu=false notifications=false splashScreen=false timings=false></x3d-canvas>`;
const srv = http.createServer((q, r) => {
  const u = decodeURIComponent(q.url.split('?')[0]);
  if (u === '/') { r.writeHead(200, { 'content-type': 'text/html' }); return r.end(page); }
  const f = u === '/scene.x3d' ? current : u.startsWith('/xite/') ? path.join(xiteDir, u.slice(6)) : path.join(path.dirname(current), u);   // Inline files sit beside the scene
  fs.readFile(f, (e, d) => { if (e) { r.writeHead(404); return r.end(); }
    const t = { '.js': 'text/javascript', '.css': 'text/css', '.x3d': 'model/x3d+xml', '.glb': 'model/gltf-binary' }[path.extname(f)] || 'application/octet-stream';
    r.writeHead(200, { 'content-type': t }); r.end(d); });
}).listen(0);
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  for (const f of files) {
    current = f;
    const p = await b.newPage({ viewport: { width: 960, height: 600 } });
    const t0 = Date.now();
    await p.goto(`http://localhost:${srv.address().port}/`);
    await p.waitForFunction(() => { try { return X3D.getBrowser(document.getElementById('c')).currentScene.rootNodes.length > 0; } catch (e) { return false; } }, null, { timeout: 120000 });
    const loadMs = Date.now() - t0;
    await p.waitForTimeout(4000);
    const out = path.join(outDir, path.basename(f).replace(/\.x3d$/, '.png'));
    await p.screenshot({ path: out });
    console.log(path.basename(f), 'scene ready after', loadMs, 'ms ->', out);
    await p.close();
  }
  await b.close(); srv.close();
})();
