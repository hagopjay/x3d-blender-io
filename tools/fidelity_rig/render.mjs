// Render jobs: X_ITE on the X3D, Babylon.js on the glb, same 512x512 headless Chromium (SwiftShader).
// Usage: node render.mjs jobs.json   (jobs: [{name, x3d, glb, clear:[r,g,b], headlight: lux|null, outdir}])
import http from 'node:http'; import fs from 'node:fs'; import path from 'node:path'; import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url); const { chromium } = require('playwright');
const RIG = path.dirname(fileURLToPath(import.meta.url));   // a path with spaces, or on Windows, stays a path
const types = { '.js': 'text/javascript', '.mjs': 'text/javascript', '.x3d': 'model/x3d+xml', '.glb': 'model/gltf-binary',
  '.html': 'text/html', '.css': 'text/css', '.png': 'image/png', '.jpg': 'image/jpeg', '.wasm': 'application/wasm' };
const server = http.createServer((req, res) => {
  let p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  p = p.startsWith('/fs/') ? p.slice(3) : path.join(RIG, p);
  fs.readFile(p, (err, data) => { if (err) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { 'Content-Type': types[path.extname(p)] || 'application/octet-stream' }); res.end(data); });
}).listen(0);
const port = server.address().port; const base = `http://127.0.0.1:${port}`;
const jobs = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const browser = await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const ua = (await (await browser.newPage()).evaluate(() => navigator.userAgent)).match(/Chrome\/[\d.]+/)[0];
console.log('BROWSER', ua);
for (const job of jobs) {
  const out = job.outdir; fs.mkdirSync(out, { recursive: true });
  // X_ITE
  const a = await browser.newPage({ viewport: { width: 512, height: 512 } });
  a.on('pageerror', e => console.log('xite pageerror', job.name, String(e).slice(0, 200)));
  await a.goto(`${base}/xite.html`, { waitUntil: 'load' });
  try {
    await a.evaluate(async (url) => { const b = X3D.getBrowser('x3d-canvas');
      b.setBrowserOption('StraightenHorizon', false);   // X_ITE levels a rolled Viewpoint on bind by default; Babylon.js does not
      await b.loadURL(new X3D.MFString(url)); window.__ver = b.version; }, `${base}/fs${job.x3d}`);
    await a.waitForTimeout(job.wait ?? 1500);
    await a.locator('x3d-canvas').screenshot({ path: `${out}/xite.png` });
    if (job === jobs[0]) console.log('X_ITE', await a.evaluate(() => window.__ver));
  } catch (e) { console.log('xite fail', job.name, String(e).slice(0, 200)); }
  await a.close();
  // Babylon.js
  const b = await browser.newPage({ viewport: { width: 512, height: 512 } });
  b.on('pageerror', e => console.log('babylon pageerror', job.name, String(e).slice(0, 200)));
  await b.goto(`${base}/babylon.html`, { waitUntil: 'load' });
  try {
    const info = await b.evaluate(async (job) => {
      BABYLON.SceneLoader.ShowLoadingScreen = false; const engine = new BABYLON.Engine(document.getElementById('c'), false, { preserveDrawingBuffer: true, antialias: true });
      const scene = new BABYLON.Scene(engine); scene.useRightHandedSystem = true;
      scene.clearColor = new BABYLON.Color4(...job.clear, 1);
      await BABYLON.SceneLoader.AppendAsync('', job.glbUrl, scene);
      scene.animationGroups.forEach(g => { g.stop(); g.goToFrame(0); });
      const v = job.view || { position: [0, 0, 10], forward: [0, 0, -1], up: [0, 1, 0], fov: Math.PI / 4 };
      const cam = new BABYLON.FreeCamera('x3d-viewpoint', new BABYLON.Vector3(...v.position), scene);
      cam.upVector = new BABYLON.Vector3(...v.up);
      cam.setTarget(new BABYLON.Vector3(v.position[0] + v.forward[0], v.position[1] + v.forward[1], v.position[2] + v.forward[2]));
      cam.fov = v.fov; cam.maxZ = 10000;
      if (v.ortho) {   // OrthoViewpoint: fieldOfView is minX minY maxX maxY
        cam.mode = BABYLON.Camera.ORTHOGRAPHIC_CAMERA;
        [cam.orthoLeft, cam.orthoBottom, cam.orthoRight, cam.orthoTop] = v.ortho;
      }
      cam.minZ = 0.01; scene.activeCamera = cam;
      if (job.headlight) { const h = new BABYLON.DirectionalLight('headlight', new BABYLON.Vector3(0, 0, -1), scene);
        h.intensity = job.headlight; scene.registerBeforeRender(() => { h.direction = cam.getDirection(new BABYLON.Vector3(0, 0, -1)); }); }
      await Promise.race([scene.whenReadyAsync(), new Promise(r => setTimeout(r, 8000))]);
      for (let i = 0; i < 5; i++) scene.render();
      return { version: BABYLON.Engine.Version, lights: scene.lights.map(l => [l.name, l.getClassName(), +l.intensity.toFixed(4), l.range]) };
    }, { ...job, glbUrl: `${base}/fs${job.glb}` });
    await b.locator('#c').screenshot({ path: `${out}/babylon.png` });
    // geometry mask: two renders cleared to magenta and to green; a pixel is background only when it shows the clear
    // colour in both, so geometry that is itself magenta (or green) still counts
    await b.evaluate(() => { const sc = BABYLON.Engine.LastCreatedScene; sc.clearColor = new BABYLON.Color4(1, 0, 1, 1); sc.render(); });
    await b.locator('#c').screenshot({ path: `${out}/babylon_mask.png` });
    await b.evaluate(() => { const sc = BABYLON.Engine.LastCreatedScene; sc.clearColor = new BABYLON.Color4(0, 1, 0, 1); sc.render(); });
    await b.locator('#c').screenshot({ path: `${out}/babylon_mask_green.png` });
    console.log('BABYLON', job.name, JSON.stringify(info));
  } catch (e) { console.log('babylon fail', job.name, String(e).slice(0, 300)); }
  await b.close();
}
await browser.close(); server.close();
