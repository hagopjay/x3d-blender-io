// Khronos glTF Validator gate: validates a .glb (or .gltf) and writes FILE.validation.json next to it.
// Usage: node validate_glb.mjs FILE.glb [--max-warnings N] [--out REPORT.json] [--quiet]
//        node validate_glb.mjs --version      (prints the validator version; exit 2 when it cannot be loaded)
// Exit code: 0 clean, 1 the file has validator errors (or more than N warnings, or the validator could not parse it),
// 2 usage error or the validator package is missing. The validator comes from node_modules next to this file
// (npm install in this folder) or, when GLTF_VALIDATOR_DIR is set, from that directory (CI installs it there).
import fs from 'node:fs'; import path from 'node:path'; import crypto from 'node:crypto'; import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const RIG = path.dirname(fileURLToPath(import.meta.url));
const SEVERITY = ['ERROR', 'WARNING', 'INFO', 'HINT'];   // gltf-validator's severity numbers 0..3
const die = (msg, code = 2) => { console.error('validate_glb: ' + msg); process.exit(code); };

let validator;
try {
  validator = createRequire(import.meta.url)(process.env.GLTF_VALIDATOR_DIR ? path.resolve(process.env.GLTF_VALIDATOR_DIR) : 'gltf-validator');   // resolve: a relative dir is a bare package name to require()
} catch (e) {
  die(`cannot load gltf-validator (${String(e.message).split('\n')[0]}); run npm install in ${RIG} or set GLTF_VALIDATOR_DIR`);
}

const args = process.argv.slice(2);
if (args.includes('--version')) { console.log(validator.version()); process.exit(0); }
let file = null, maxWarnings = null, outPath = null, quiet = false;
for (let i = 0; i < args.length; i++) {
  const a = args[i];
  if (a === '--max-warnings') { maxWarnings = Number(args[++i]); if (!Number.isInteger(maxWarnings) || maxWarnings < 0) die('--max-warnings needs an integer >= 0'); }
  else if (a === '--out') { outPath = args[++i]; if (!outPath) die('--out needs a path'); }
  else if (a === '--quiet') quiet = true;
  else if (a.startsWith('--')) die(`unknown option ${a}`);
  else if (file === null) file = a;
  else die('one input file only');
}
if (!file) die('usage: node validate_glb.mjs FILE.glb|FILE.gltf [--max-warnings N] [--out REPORT.json] [--quiet]');
if (!fs.existsSync(file)) die(`no such file: ${file}`);
if (!fs.statSync(file).isFile()) die(`not a file: ${file}`);

const bytes = fs.readFileSync(file);
const isGltf = path.extname(file).toLowerCase() === '.gltf';
const options = { uri: path.basename(file), maxIssues: 0 };   // maxIssues 0 = report every issue
if (isGltf) {   // a .gltf names its .bin and textures by relative URI; a .glb carries them, so no resource function there
  const dir = path.dirname(path.resolve(file));
  options.externalResourceFunction = async (uri) => {
    const p = path.resolve(dir, decodeURIComponent(uri));
    if (path.relative(dir, p).startsWith('..') || path.isAbsolute(path.relative(dir, p))) throw new Error('resource outside the asset folder: ' + uri);
    return new Uint8Array(fs.readFileSync(p));
  };
}

let report = null, exception = null;
try { report = await validator.validateBytes(new Uint8Array(bytes), options); }
catch (e) { exception = String(e && e.message || e); }   // e.g. "could not detect glTF format": the file is not a glTF

const issues = report ? report.issues : { numErrors: 1, numWarnings: 0, numInfos: 0, numHints: 0, messages: [] };
const info = (report && report.info) || {};   // a fatally broken file has issues but no info
const out = {
  schema: 'x3d-blender-io.glb-validation/v1',
  file: path.basename(file),
  bytes: bytes.length,
  sha256: crypto.createHash('sha256').update(bytes).digest('hex'),
  validator: 'gltf-validator',
  validatorVersion: report ? report.validatorVersion : validator.version(),
  numErrors: issues.numErrors, numWarnings: issues.numWarnings, numInfos: issues.numInfos, numHints: issues.numHints,
  truncated: !!issues.truncated,
  issues: report ? issues.messages.map(m => ({ code: m.code, severity: SEVERITY[m.severity] ?? String(m.severity), pointer: m.pointer ?? null, message: m.message }))
                 : [{ code: 'VALIDATOR_EXCEPTION', severity: 'ERROR', pointer: null, message: exception }],
  totalTriangleCount: info.totalTriangleCount ?? null, totalVertexCount: info.totalVertexCount ?? null,
  drawCallCount: info.drawCallCount ?? null, materialCount: info.materialCount ?? null,
  extensionsUsed: info.extensionsUsed ?? [], extensionsRequired: info.extensionsRequired ?? [],
  // extensions the file uses that this validator version does not know: it does not check their content (Khronos: "not validated")
  extensionsNotValidated: (info.extensionsUsed ?? []).filter(e => !validator.supportedExtensions().includes(e)),
  generator: info.generator ?? null, gltfVersion: info.version ?? null,
  maxWarnings,
};
out.ok = out.numErrors === 0 && (maxWarnings === null || out.numWarnings <= maxWarnings);
fs.writeFileSync(outPath || file + '.validation.json', JSON.stringify(out, null, 1) + '\n');

if (!quiet) {
  const tag = out.ok ? 'OK  ' : 'FAIL';
  console.log(`${tag} ${path.basename(file)}: ${out.numErrors} errors, ${out.numWarnings} warnings, ${out.numInfos} infos, ${out.numHints} hints; ` +
    `${out.totalTriangleCount} tris, ${out.drawCallCount} draw calls, ${out.materialCount} materials; ` +
    `extensions ${out.extensionsUsed.join(',') || 'none'} (gltf-validator ${out.validatorVersion})`);
  if (out.extensionsNotValidated.length)   // the validator reports these at INFO only; OK above does not cover their content
    console.log(`  NOT VALIDATED: ${out.extensionsNotValidated.join(',')} (unknown to this validator version; content unchecked` +
      `${out.extensionsNotValidated.some(e => out.extensionsRequired.includes(e)) ? '; REQUIRED by the file' : ''})`);
  for (const m of out.issues.filter(m => m.severity === 'ERROR' || m.severity === 'WARNING').slice(0, 20))
    console.log(`  ${m.severity} ${m.code} ${m.pointer ?? ''} ${m.message}`);
}
process.exit(out.ok ? 0 : 1);
