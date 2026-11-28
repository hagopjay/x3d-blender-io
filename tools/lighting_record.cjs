// SPDX-FileCopyrightText: 2026 HagopJay
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Draws each lighting probe scene (tests/lighting/fixtures) in X_ITE and in X3DOM, in headless Chrome, on a 64 x 64
// canvas at device pixel ratio 1, and saves what each canvas shows as a PNG, for tools/lighting_judge.py.
//   NODE_PATH=$(npm root -g) node tools/lighting_record.cjs --xite=<x_ite dist dir> --x3dom=<x3dom dir> --out=<dir>
//                                                            [--configs=a,b] [fixtures...]
// Configurations (each one a witness):
//   x_ite              X_ITE as it ships: Shading GOURAUD, ColorSpace LINEAR_WHEN_PHYSICAL_MATERIAL
//   x_ite-phong        Shading PHONG (lighting per pixel, as X3D 4.0 17.2.2.5 describes), the default ColorSpace
//   x_ite-phong-linear Shading PHONG, ColorSpace LINEAR
//   x3dom              X3DOM as it ships (Environment gammaCorrectionDefault "linear")
//   x3dom-none         X3DOM with <Environment gammaCorrectionDefault='none'>
// out/versions.json names each library's version and the WebGL renderer that drew it.
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path');
const flags = Object.fromEntries(process.argv.slice(2).filter(a => a.startsWith('--')).map(a => { const [k, v] = a.slice(2).split('='); return [k, v ?? true]; }));
const root = path.resolve(__dirname, '..');
let files = process.argv.slice(2).filter(a => !a.startsWith('--'));
if (!files.length) files = fs.readdirSync(path.join(root, 'tests/lighting/fixtures')).filter(f => f.endsWith('.x3d')).map(f => path.join(root, 'tests/lighting/fixtures', f));
const configs = (flags.configs || 'x_ite,x_ite-phong,x_ite-phong-linear,x3dom,x3dom-none').split(',');
const out = path.resolve(flags.out || 'lighting-out'), SIZE = 64;
const types = { '.js': 'text/javascript', '.css': 'text/css', '.wasm': 'application/wasm', '.x3d': 'model/x3d+xml' };
let current = '';

function x3domMarkup(xml, gamma) {
  // the <Scene> children, inline in HTML: HTML has no self-closing elements, so <A .../> becomes <A ...></A>
  const body = xml.split(/<Scene>/)[1].split(/<\/Scene>/)[0].replace(/<([A-Za-z0-9]+)([^<>]*?)\/>/g, '<$1$2></$1>');
  const environment = gamma ? `<Environment gammaCorrectionDefault='${gamma}'></Environment>` : '';
  return `<x3d id=c width='${SIZE}px' height='${SIZE}px' showStat=false showLog=false style='border:0;display:block'><scene>${environment}${body}</scene></x3d>`;
}

function page(config) {
  if (config.startsWith('x_ite')) {
    const colorSpace = config.endsWith('-linear') ? 'LINEAR' : 'LINEAR_WHEN_PHYSICAL_MATERIAL';
    return `<!doctype html><meta charset=utf-8><link rel=stylesheet href=/xite/x_ite.css><script src=/xite/x_ite.min.js></script>
<body style=margin:0><x3d-canvas id=c style="width:${SIZE}px;height:${SIZE}px;display:block" colorSpace=${colorSpace} contextMenu=false notifications=false splashScreen=false timings=false></x3d-canvas>`;
  }
  return `<!doctype html><meta charset=utf-8><link rel=stylesheet href=/x3dom/x3dom.css><script src=/x3dom/x3dom.js></script>
<body style=margin:0>${x3domMarkup(current, config === 'x3dom-none' ? 'none' : '')}</body>`;
}

const srv = http.createServer((q, r) => {
  const u = decodeURIComponent(q.url.split('?')[0]);
  const [, lib, rest] = u.match(/^\/([^/]*)\/?(.*)$/) || [];
  if (lib && lib.startsWith('page-')) { r.writeHead(200, { 'content-type': 'text/html' }); return r.end(page(lib.slice(5))); }
  const dir = lib === 'xite' ? flags.xite : lib === 'x3dom' ? flags.x3dom : null;
  if (!dir) { r.writeHead(404); return r.end(); }
  const f = path.join(path.resolve(dir), rest);
  fs.readFile(f, (e, d) => { if (e) { r.writeHead(404); return r.end(); } r.writeHead(200, { 'content-type': types[path.extname(f)] || 'application/octet-stream' }); r.end(d); });
}).listen(0);

const frames = (p, n) => p.evaluate(n => new Promise(done => { const step = k => k ? requestAnimationFrame(() => step(k - 1)) : done(); step(n); }), n);

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: SIZE, height: SIZE }, deviceScaleFactor: 1 });
  const versions = { chromium: browser.version() };
  for (const config of configs) {
    fs.mkdirSync(path.join(out, config), { recursive: true });
    for (const file of files) {
      current = fs.readFileSync(file, 'utf8');
      const scene = path.basename(file, '.x3d');
      const p = await context.newPage();
      const errors = []; p.on('pageerror', e => errors.push(String(e).slice(0, 300)));
      await p.goto(`http://localhost:${srv.address().port}/page-${config}/`);
      if (config.startsWith('x_ite')) {
        await p.waitForFunction(() => window.X3D);
        versions[config] = await p.evaluate(async ([xml, phong]) => {
          const B = X3D.getBrowser(document.getElementById('c'));
          if (phong) B.setBrowserOption('Shading', 'PHONG');
          await B.replaceWorld(await B.createX3DFromString(xml));
          return { library: 'X_ITE ' + B.version, Shading: B.getBrowserOption('Shading'), ColorSpace: B.getBrowserOption('ColorSpace') };
        }, [current.replace(/<!DOCTYPE[^>]*>/, ''), config !== 'x_ite']);   // X_ITE 16.8.1's string parser rejects the DOCTYPE
      } else {
        await p.waitForFunction(() => window.x3dom && document.querySelector('canvas'));
        versions[config] = await p.evaluate(() => ({ library: 'X3DOM ' + x3dom.about.version + ' build ' + x3dom.about.build + ' (' + x3dom.about.revision.slice(0, 10) + ')' }));
      }
      await frames(p, 30);
      versions[config].webgl = await p.evaluate(() => {
        const c = document.querySelector('canvas');   // X_ITE's is in the x3d-canvas element's shadow root
        const g = window.X3D ? X3D.getBrowser(document.getElementById('c')).getContext() : (c.getContext('webgl2') || c.getContext('webgl'));
        const e = g && g.getExtension('WEBGL_debug_renderer_info');
        return g ? (e ? g.getParameter(e.UNMASKED_RENDERER_WEBGL) : g.getParameter(g.RENDERER)) : null;
      });
      await p.locator(config.startsWith('x_ite') ? '#c' : 'canvas').first().screenshot({ path: path.join(out, config, scene + '.png') });
      if (errors.length) versions[config + ':' + scene + ':errors'] = errors;
      console.error(config, scene, errors.length ? errors[0] : 'ok');
      await p.close();
    }
  }
  fs.writeFileSync(path.join(out, 'versions.json'), JSON.stringify(versions, null, 1));
  await browser.close(); srv.close();
})();
