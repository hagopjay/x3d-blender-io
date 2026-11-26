// SPDX-FileCopyrightText: 2026 HagopJay
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Asks X_ITE what its Geospatial component computes, so source/behaviour_geo.py can be checked against it.
//   NODE_PATH=$(npm root -g) node tools/behaviour_geo_probe.cjs <x_ite dist dir> cases.json > answers.json
// cases.json: a list of {"op", ...}; the answer list has the same length, each [x, y, z] (or null when X_ITE threw):
//   {"op": "convert", "geoSystem": [...], "in": [a, b, c]}     referenceFrame.convert: a geoSystem coordinate -> geocentric
//   {"op": "apply",   "geoSystem": [...], "in": [x, y, z]}     referenceFrame.apply: geocentric -> a geoSystem coordinate
//   {"op": "local" | "geo", "geoSystem": [...], "origin": null | {"geoSystem": [...], "geoCoords": [..], "rotateYUp": bool}, "in": [...]}
//                                      a Geo node's getLocalCoord / getGeoCoord (a GeoPositionInterpolator made for the purpose)
//   {"op": "slerp", "a": [...], "b": [...], "t": t}            Geocentric.slerp (the interpolator's mix)
// X_ITE's own numbers, printed with all their digits (JSON of doubles).
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path');
const [xiteDir, casesFile] = process.argv.slice(2);
const cases = JSON.parse(fs.readFileSync(casesFile, 'utf8'));
const types = { '.js': 'text/javascript', '.css': 'text/css' };
const page = `<!doctype html><meta charset=utf-8><script src=/x_ite.min.js></script><x3d-canvas id=c></x3d-canvas>`;
const srv = http.createServer((q, r) => {
  const u = decodeURIComponent(q.url.split('?')[0]);
  if (u === '/') { r.writeHead(200, { 'content-type': 'text/html' }); return r.end(page); }
  fs.readFile(path.join(xiteDir, u), (e, d) => { if (e) { r.writeHead(404); return r.end(); } r.writeHead(200, { 'content-type': types[path.extname(u)] || 'application/octet-stream' }); r.end(d); });
}).listen(0);
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const p = await b.newPage();
  await p.goto(`http://localhost:${srv.address().port}/`);
  const answers = await p.evaluate(async cases => {
    const B = X3D.getBrowser(document.getElementById('c'));
    await B.loadComponents(B.getComponent('Geospatial'));
    const scene = B.currentScene, V = X3D.Vector3;
    const triple = v => [v.x, v.y, v.z];
    const node = (system, origin) => {
      const n = scene.createNode('GeoPositionInterpolator');
      n.geoSystem = new X3D.MFString(...system);
      if (origin) {
        const o = scene.createNode('GeoOrigin');
        o.geoSystem = new X3D.MFString(...origin.geoSystem);
        o.geoCoords = new X3D.SFVec3d(...origin.geoCoords);
        o.rotateYUp = origin.rotateYUp;
        n.geoOrigin = o;
      }
      // X_ITE works its field interests out at its next event pass; do it now, in the order it would (the origin first)
      const v = n.getValue();
      if (origin) n.geoOrigin.getValue().set_geoSystem__();
      v.set_geoSystem__();
      v.set_geoOrigin__();
      return v;
    };
    return cases.map(c => {
      try {
        if (c.op === 'convert' || c.op === 'apply') {
          const frame = X3D.GeospatialObject.getReferenceFrame(c.geoSystem, false);
          return triple(frame[c.op](new V(...c.in), new V()));
        }
        if (c.op === 'local') return triple(node(c.geoSystem, c.origin).getLocalCoord(new V(...c.in), new V()));
        if (c.op === 'geo') return triple(node(c.geoSystem, c.origin).getGeoCoord(new V(...c.in), new V()));
        if (c.op === 'slerp') return triple(new X3D.Geocentric().slerp(new V(...c.a), new V(...c.b), c.t));
      } catch (e) { return null; }
      return null;
    });
  }, cases);
  await b.close(); srv.close();
  console.log(JSON.stringify(answers));
})();
