// SPDX-FileCopyrightText: 2026 HagopJay
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Records what X_ITE does with the world's outside resources and their clocks (LoadSensor, AudioClip, MovieTexture), from
// the first moment of the scene, so tools/behaviour_resources_judge.py can hand the Python simulator the same resources
// and compare. Nothing is downloaded: the files are served from a folder the caller made (a WAV, a PNG, a WebM written by
// the test itself), each after the delay media.json names, or refused.
//   NODE_PATH=$(npm root -g) node tools/behaviour_resources_judge.cjs <x_ite dist dir> <file.x3d> <sources.json> <seconds> <media dir> <media.json> > trace.json
// sources.json: [["DEF","field"], ...] every ROUTE source of the file (tools/behaviour_sim_judge.py --sources writes it).
// media.json:   {"tone.wav": {"delay": 400}, "gone.wav": {"status": 404}}  by the file's name; a file it does not name is
//               served at once. Every request is logged with the wall-clock time it came in and the time it was answered.
// A hook on the classes of the file's named nodes watches each node before X_ITE initialises it, so nothing the scene does
// at its first moment is missed. The trace holds, with X_ITE's own time stamp (browser.getCurrentTime) and the
// wall clock beside it: every event at every source, every change of a url object's load state ("loadState": X_ITE's
// constants 1006 not started, 1007 in progress, 1008 complete, 1009 failed), when the world went live ("(world)" "live"),
// and what every source held at the start.
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path');
const [xiteDir, file, sourcesFile, secondsArg, mediaDir, mediaFile] = process.argv.slice(2);
const sources = JSON.parse(fs.readFileSync(sourcesFile, 'utf8'));
const media = mediaFile ? JSON.parse(fs.readFileSync(mediaFile, 'utf8')) : {};
const types = { '.js': 'text/javascript', '.css': 'text/css', '.x3d': 'model/x3d+xml', '.wav': 'audio/wav', '.png': 'image/png',
                '.webm': 'video/webm', '.mp4': 'video/mp4', '.x3dv': 'model/x3d+vrml' };
const page = `<!doctype html><meta charset=utf-8><link rel=stylesheet href=/xite/x_ite.css><script src=/xite/x_ite.min.js></script>
<style>body{margin:0}x3d-canvas{width:480px;height:300px;display:block}</style>
<x3d-canvas id=c contextMenu=false notifications=false splashScreen=false timings=false></x3d-canvas>`;
const requests = [];
const sleep = ms => new Promise(r => setTimeout(r, ms));
const srv = http.createServer(async (q, r) => {
  const u = decodeURIComponent(q.url.split('?')[0]);
  if (u === '/') { r.writeHead(200, { 'content-type': 'text/html' }); return r.end(page); }
  if (u === '/file') return fs.readFile(file, (e, d) => { r.writeHead(e ? 404 : 200, { 'content-type': 'model/x3d+xml' }); r.end(d); });
  if (u.startsWith('/xite/')) return fs.readFile(path.join(xiteDir, u.slice(6)), (e, d) => { r.writeHead(e ? 404 : 200, { 'content-type': types[path.extname(u)] || 'application/octet-stream' }); r.end(d); });
  const name = path.basename(u), rule = media[name] || {}, asked = Date.now() / 1000;
  if (rule.delay) await sleep(rule.delay);
  const target = path.join(mediaDir, name);
  const exists = !rule.status && fs.existsSync(target);
  requests.push({ file: name, asked, answered: Date.now() / 1000, status: exists ? 200 : (rule.status || 404) });
  if (!exists) { r.writeHead(rule.status || 404); return r.end(); }
  const data = fs.readFileSync(target), range = q.headers.range;
  if (range) {            // a video element asks for ranges
    const m = /bytes=(\d+)-(\d*)/.exec(range), from = Number(m[1]), to = m[2] ? Number(m[2]) : data.length - 1;
    r.writeHead(206, { 'content-type': types[path.extname(name)] || 'application/octet-stream', 'content-range': `bytes ${from}-${to}/${data.length}`, 'accept-ranges': 'bytes', 'content-length': to - from + 1 });
    return r.end(data.subarray(from, to + 1));
  }
  r.writeHead(200, { 'content-type': types[path.extname(name)] || 'application/octet-stream', 'accept-ranges': 'bytes', 'content-length': data.length });
  r.end(data);
}).listen(0);

(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--autoplay-policy=no-user-gesture-required'] });
  const p = await b.newPage({ viewport: { width: 480, height: 300 } });
  const errors = [], consoleLines = []; p.on('pageerror', e => errors.push(String(e))); p.on('console', m => { if (['warning', 'error'].includes(m.type())) consoleLines.push(m.text()); });
  await p.goto(`http://localhost:${srv.address().port}/`);
  // node type of every named node of the file: those prototypes get a hook that watches the node before it is initialised
  const named = [...fs.readFileSync(file, 'utf8').matchAll(/<(\w+)\s[^>]*?\bDEF="([^"]+)"/g)].map(m => [m[1], m[2]]);
  const info = await p.evaluate(async ([sources, named, MEDIA]) => {
    const B = X3D.getBrowser(document.getElementById('c'));
    window.__events = []; window.__frames = []; window.__starts = [];
    const text = v => (v !== null && typeof v === 'object') ? String(v) : v;
    const stamp = () => [B.getCurrentTime(), Date.now() / 1000];
    const missing = [];
    await B.loadComponents(B.getProfile('Full'));      // the classes below exist once their components are loaded
    const urlObjectTypes = new Set(['ImageTexture', 'AudioClip', 'MovieTexture', 'Inline', 'Script', 'ShaderPart']);
    for (const type of new Set(named.map(n => n[0]))) {
      const Class = X3D.require(type);
      if (!Class) { missing.push([type, '(no such class)']); continue; }
      const prototype = Class.prototype, initialize = prototype.initialize, setLoadState = prototype.setLoadState;
      prototype.initialize = function (...args) {
        const name = this.getName();
        window.__starts.push([...stamp(), name, type, 'initialize']);
        if (!window.__watchingLive) {       // when the world goes live: nothing time-dependent runs before that
          window.__watchingLive = true;
          this.getLive().addFieldCallback('judgeLive', v => window.__events.push([...stamp(), '(world)', 'live', Boolean(v.valueOf ? v.valueOf() : v)]));
        }
        sources.forEach(([d, f], i) => {
          if (d !== name) return;
          try { this['_' + f].addFieldCallback('judge' + i, v => window.__events.push([...stamp(), d, f, text(v)])); }
          catch (e) { missing.push([d, f, String(e)]); }
        });
        return initialize.apply(this, args);
      };
      if (setLoadState && urlObjectTypes.has(type))
        prototype.setLoadState = function (value, ...rest) {
          if (this.getName()) window.__events.push([...stamp(), this.getName(), 'loadState', Number(value)]);
          return setLoadState.call(this, value, ...rest);
        };
    }
    const tick = () => { window.__frames.push(stamp()); requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
    const before = stamp();
    await B.loadURL(new X3D.MFString('/file'));
    const scene = B.currentScene;
    const initial = sources.map(([d, f]) => { try { return [d, f, text(scene.getNamedNode(d)['_' + f].getValue())]; } catch (e) { return null; } }).filter(Boolean);
    return { missing, initial, before, began: stamp(), version: B.version, name: B.name };
  }, [sources, named, null]);
  await sleep(Number(secondsArg) * 1000);
  const out = await p.evaluate(() => ({ events: window.__events, frames: window.__frames, starts: window.__starts }));
  process.stdout.write(JSON.stringify({ file: path.basename(file), browser: `${info.name} ${info.version}`, began: info.began[0], wallBegan: info.began[1],
    before: info.before, missing: info.missing, initial: info.initial, starts: out.starts.slice(0, 3), pageErrors: errors.length, console: consoleLines.filter(l => !/GL Driver/.test(l)).slice(0, 10).map(l => l.split('\n')[0]),
    requests, frameCount: out.frames.length, frames: out.frames.slice(0, 3).map(f => f[0]), events: out.events }) + '\n');
  await b.close(); srv.close();
})().catch(e => { console.error(e); process.exit(1); });
