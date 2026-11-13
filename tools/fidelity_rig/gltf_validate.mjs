// Khronos glTF Validator over the glb files compare.py wrote: node gltf_validate.mjs out/LABEL
// Prints one line per scene (errors, warnings, infos, hints, extensions used, triangles, materials) and exits 1 on any error.
import fs from 'fs';
import path from 'path';
import validator from 'gltf-validator';
import pkg from './node_modules/gltf-validator/package.json' with { type: 'json' };

const dir = process.argv[2];
if (!dir) { console.error('usage: node gltf_validate.mjs out/LABEL'); process.exit(2); }
let failed = 0;
for (const scene of fs.readdirSync(dir).sort()) {
  const glb = path.join(dir, scene, 'scene.glb');
  if (!fs.existsSync(glb)) continue;
  const bytes = fs.readFileSync(glb);
  const r = await validator.validateBytes(new Uint8Array(bytes));
  const i = r.issues;
  const first = i.messages.filter((m) => m.severity < 2).slice(0, 3).map((m) => `${m.code} ${m.pointer}`);
  console.log(`${scene}: ${bytes.length} bytes, validator ${pkg.version}, errors ${i.numErrors}, warnings ${i.numWarnings}, infos ${i.numInfos}, hints ${i.numHints}, ` +
    `extensions ${JSON.stringify(r.info.extensionsUsed || [])}, triangles ${r.info.totalTriangleCount}, materials ${r.info.materialCount}` + (first.length ? `, first: ${first.join('; ')}` : ''));
  if (i.numErrors) failed = 1;
}
process.exit(failed);
