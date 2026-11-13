// Page behaviour for the x3d-blender-io brag page v2.
const XITE_URL = 'https://cdn.jsdelivr.net/npm/x_ite@16.7.1/dist/x_ite.min.js';
const BJS_URLS = ['https://cdn.jsdelivr.net/npm/babylonjs@9.32.0/babylon.js',
  'https://cdn.jsdelivr.net/npm/babylonjs-loaders@9.32.0/babylonjs.loaders.min.js'];
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
document.body.classList.remove('nojs');
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

// ---------------------------------------------------------------- showpieces (filled from brag/showpieces.json)
async function loadShowpieces() {
  const host = $('#shows');
  let list = [];
  try { list = await (await fetch('brag/showpieces.json')).json(); } catch (_) { return; }
  host.innerHTML = '';
  for (const s of list) {
    const el = document.createElement('article');
    el.className = 'show glass gborder rv' + (s.wide ? ' wide' : '');
    const ba = s.cycles
      ? `<div class="ba" data-ba><img src="${s.cycles}" alt="${s.title}: ${s.leftTag || 'Blender Cycles render'}" loading="lazy"><img class="after" src="${s.poster}" alt="${s.title}: X_ITE 16.7.1 drawing the X3D file live" loading="lazy"><input type="range" min="0" max="100" value="50" aria-label="Reveal: ${s.leftTag || 'Cycles render'} versus X_ITE"><div class="bar"></div><span class="tag l">${s.leftTag || 'Blender Cycles'}</span><span class="tag r">${s.rightTag || 'X3D in X_ITE'}</span></div>`
      : `<div class="ba"><img src="${s.poster}" alt="${s.title}: X_ITE 16.7.1 drawing the X3D file live" loading="lazy"><span class="tag r">${s.rightTag || 'X3D in X_ITE'}</span></div>`;
    el.innerHTML = `${ba}<div class="body"><h3><small>${s.kicker}</small>${s.title}</h3><p>${s.text}</p>
      <div class="facts">${(s.facts || []).map(f => `<span>${f}</span>`).join('')}</div>
      <div class="acts"><button class="btn primary" data-live="${s.id}" data-eng="xite">▶ Fly it live in X_ITE</button>${s.glb ? `<button class="btn" data-live="${s.id}" data-eng="bjs">glb in Babylon.js</button>` : ''}<a class="btn" href="${s.x3d}" download>.x3d ↓</a></div></div>`;
    host.appendChild(el);
  }
  SHOW = Object.fromEntries(list.map(s => [s.id, s]));
  wireSliders(host); reveal(host); tilt(host);
  $$('[data-live]', host).forEach(b => b.addEventListener('click', () => openTheatre(SHOW[b.dataset.live], b.dataset.eng)));
}
let SHOW = {};

// ---------------------------------------------------------------- reveal, counters, tiles, tilt, sliders
const io = 'IntersectionObserver' in window ? new IntersectionObserver(es => es.forEach(e => {
  if (!e.isIntersecting) return; e.target.classList.add('in'); io.unobserve(e.target);
  if (e.target.classList.contains('tile')) count(e.target);
}), { threshold: 0.12, rootMargin: '0px 0px -6% 0px' }) : null;
function reveal(root = document) { $$('.rv', root).forEach(el => io ? io.observe(el) : el.classList.add('in')); }
function count(tile) {
  const v = $('.v', tile); if (!v || tile.dataset.pair || reduced) return;
  const end = parseFloat(tile.dataset.count), dec = +(tile.dataset.dec || 0), t0 = performance.now(), dur = 1400;
  const fmt = x => x.toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });
  const step = now => { const k = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - k, 4); v.textContent = fmt(end * e); if (k < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}
$$('.tile').forEach(t => t.addEventListener('click', () => t.setAttribute('aria-expanded', t.getAttribute('aria-expanded') === 'true' ? 'false' : 'true')));
function tilt(root = document) {
  if (reduced || matchMedia('(hover: none)').matches) return;
  $$('.show, .card', root).forEach(el => {
    el.addEventListener('pointermove', e => {
      const r = el.getBoundingClientRect(), x = (e.clientX - r.left) / r.width - 0.5, y = (e.clientY - r.top) / r.height - 0.5;
      el.style.transform = `perspective(1100px) rotateY(${x * 4}deg) rotateX(${-y * 4}deg) translateY(-2px)`;
    });
    el.addEventListener('pointerleave', () => { el.style.transform = ''; });
  });
}
function wireSliders(root = document) {
  $$('[data-ba]', root).forEach(ba => {
    const input = $('input', ba); if (!input || input.dataset.wired) return; input.dataset.wired = 1;
    const set = () => ba.style.setProperty('--p', input.value + '%'); input.addEventListener('input', set); set();
    // a one-time sweep when the slider first comes into view, to show it moves
    if (!reduced && io) {
      const o = new IntersectionObserver(es => { if (!es[0].isIntersecting) return; o.disconnect();
        const t0 = performance.now(); const f = now => { const k = Math.min(1, (now - t0) / 1600); input.value = 50 + 32 * Math.sin(k * Math.PI * 2) * (1 - k); set(); if (k < 1) requestAnimationFrame(f); }; requestAnimationFrame(f);
      }, { threshold: 0.6 }); o.observe(ba);
    }
  });
}
reveal(); wireSliders(); tilt();

// ---------------------------------------------------------------- hero (three.js)
async function startHero() {
  const stage = $('#heroStage'), canvas = $('#sky');
  let hero = null;
  try {
    const { initHero } = await import('./hero.mjs');
    hero = await initHero({ canvas, stage, dataUrl: 'brag/stars.json', namesUrl: 'brag/star-names.json', hud: $('#hud'), tip: $('#tip'), labelsLayer: $('#labels'),
      onReady: () => { $('#heroPoster').style.opacity = 0; } });
  } catch (e) { console.warn('hero: WebGL not available, poster stays', e); }
  if (!hero) { $('#fly').hidden = true; return; }
  $$('#fly [data-fly]').forEach(b => b.addEventListener('click', () => {
    $$('#fly .chip').forEach(c => c !== $('#arecibo') && c.classList.remove('on')); b.classList.add('on');
    hero.flyTo(b.dataset.fly, b.dataset.fly === 'sol' ? 9 : 6);
  }));
  // hide chips whose star the name fit did not find
  $$('#fly [data-fly]').forEach(b => { const n = b.dataset.fly; if (n !== 'sol' && n !== 'out' && !hero.names.some(s => s.name.toLowerCase().startsWith(n.toLowerCase()))) b.hidden = true; });
  const ar = $('#arecibo');
  ar.addEventListener('click', () => { const on = ar.getAttribute('aria-pressed') !== 'true'; ar.setAttribute('aria-pressed', on); ar.classList.toggle('on', on); hero.arecibo(on);
    const t = $('#tip'); if (on) { t.innerHTML = `<b>The Arecibo message</b><span>sent 16 Nov 1974 from Puerto Rico toward the M13 cluster</span><span class="d">${lyOut('1974-11-16').toFixed(2)} light-years out today, past the 49.9 ly edge of this map</span>`; t.hidden = false; t.style.transform = 'translate(24px, 110px)'; setTimeout(() => { t.hidden = true; }, 5200); } });
  startTicker();
  // scroll: dolly in, fade the copy, show the beat line
  const copy = $('#heroCopy'), beat = $('#beat1'), cue = $('#cue'), header = $('#top'), labels = $('#labels');
  const onScroll = () => {
    const r = header.getBoundingClientRect(), span = header.offsetHeight - innerHeight;
    const k = Math.max(0, Math.min(1, -r.top / Math.max(1, span)));
    hero.setScroll(k);
    copy.style.opacity = Math.max(0, 1 - k * 2.6);
    // phones: the star labels sit under the headline, so bring them in as the copy fades out
    labels.style.opacity = innerWidth < 900 ? Math.min(1, 0.12 + k * 2.6) : '';
    beat.style.opacity = Math.max(0, Math.min(1, (k - 0.42) * 4)) * Math.max(0, Math.min(1, (1 - k) * 6));
    cue.style.opacity = Math.max(0, 1 - k * 6);
  };
  addEventListener('scroll', onScroll, { passive: true }); onScroll();
}
startHero();

// ---------------------------------------------------------------- "tonight in the bubble": facts computed for the viewer's date
const DAY = 864e5, lyOut = iso => (Date.now() - Date.parse(iso + 'T00:00:00Z')) / DAY / 365.25;
const MON = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const ago = ly => { const t = new Date(Date.now() - ly * 365.25 * DAY); return `${MON[t.getUTCMonth()]} ${t.getUTCFullYear()}`; };
function facts() {
  const v1 = Date.parse('2026-11-19T02:00:00Z') > Date.now();
  const mfe = lyOut('2008-10-09'), toGo = 20.27 - mfe;
  return [
    `<b>Sirius</b> The light you see from it tonight left in ${ago(8.60)}.`,
    `<b>Arcturus</b> Its light switched on the 1933 Chicago World's Fair. That light had left the star in 1896.`,
    `<b>Radio Earth</b> Every radio and TV signal sent since about ${ago(49.9)} is still inside this bubble.`,
    toGo > 0 ? `<b>A Message From Earth</b> Sent in 2008 toward Gliese 581, it is ${Math.round(100 * mfe / 20.27)}% of the way there.` : `<b>A Message From Earth</b> Sent in 2008, it has reached Gliese 581, 20.3 ly out.`,
    `<b>Arecibo, 1974</b> ${lyOut('1974-11-16').toFixed(2)} light-years out today, on its way to M13. Press ◎ to see it.`,
    `<b>Voyager 1</b> ${v1 ? 'Reaches' : 'Reached'} one light-day from Earth on 19 November 2026 (JPL Horizons). On this map that is inside the Sun's dot.`,
  ];
}
function startTicker() {
  const el = $('#ticker'); if (!el) return;
  const list = facts(); let i = 0;
  const show = () => { el.classList.remove('on'); setTimeout(() => { el.innerHTML = list[i % list.length]; el.classList.add('on'); i++; }, reduced ? 0 : 420); };
  show(); if (!reduced) setInterval(() => { if (!document.hidden) show(); }, 6500);
  el.addEventListener('click', show);
}

// ---------------------------------------------------------------- loaders
const once = new Map();
function script(src) {
  if (!once.has(src)) once.set(src, new Promise((res, rej) => { const s = document.createElement('script'); s.src = src; s.async = true; s.onload = res; s.onerror = () => { once.delete(src); s.remove(); rej(new Error('could not load ' + src)); }; document.head.appendChild(s); }));
  return once.get(src);
}
const loadXite = () => script(XITE_URL).then(() => window.X3D);
const loadBjs = async () => { await script(BJS_URLS[0]); await script(BJS_URLS[1]); return window.BABYLON; };

async function mountXite(host, url, { onStatus, viewpoint } = {}) {
  const X3D = await loadXite();
  const canvas = X3D.createBrowser();
  canvas.setAttribute('splashScreen', 'false');
  canvas.setAttribute('contextMenu', 'false');
  canvas.setAttribute('notifications', 'false');
  canvas.setAttribute('update', 'auto'); // X_ITE stops drawing while off-screen or in a hidden tab
  canvas.style.width = '100%'; canvas.style.height = '100%';
  host.appendChild(canvas);
  const browser = canvas.browser || X3D.getBrowser(canvas);
  const t0 = performance.now();
  await browser.loadURL(new X3D.MFString(new URL(url, location.href).href));
  if (viewpoint) { try { browser.currentScene.getNamedNode(viewpoint).set_bind = true; } catch (_) {} }
  onStatus && onStatus(`X_ITE ${browser.version || '16.7.1'} · loaded in ${((performance.now() - t0) / 1000).toFixed(1)} s · drag to orbit, wheel to zoom`);
  // dispose() frees the WebGL context; without it about 16 opens make Chrome drop the oldest one, the hero's
  return () => { try { browser.replaceWorld(null); } catch (_) {} try { browser.dispose(); } catch (_) {} canvas.remove(); };
}

// A studio environment for the glb's PBR metals, computed on the page (no download, no extra render pass):
// a dark gradient room with a warm key softbox and a cool rim, as a small cube map with mipmaps.
function studio(B, scene) {
  const N = 64, warmDir = new B.Vector3(0.6, 0.55, -0.58).normalize(), coolDir = new B.Vector3(-0.7, 0.4, 0.6).normalize();
  const faceDir = [(u, v) => [1, -v, -u], (u, v) => [-1, -v, u], (u, v) => [u, 1, v], (u, v) => [u, -1, -v], (u, v) => [u, -v, 1], (u, v) => [-u, -v, -1]];
  const bytes = [], floats = [];
  for (const fd of faceDir) {
    const b8 = new Uint8Array(N * N * 4), f32 = new Float32Array(N * N * 4);
    for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
      const [dx, dy, dz] = fd(2 * (x + 0.5) / N - 1, 2 * (y + 0.5) / N - 1), l = Math.hypot(dx, dy, dz), X = dx / l, Y = dy / l, Z = dz / l;
      const sky = Math.max(0, Y), floor = Math.max(0, -Y);
      const warm = Math.pow(Math.max(0, X * warmDir.x + Y * warmDir.y + Z * warmDir.z), 24), cool = Math.pow(Math.max(0, X * coolDir.x + Y * coolDir.y + Z * coolDir.z), 16);
      const c = [0.035 + 0.16 * sky - 0.02 * floor + 1.0 * warm + 0.12 * cool, 0.04 + 0.18 * sky - 0.02 * floor + 0.82 * warm + 0.45 * cool, 0.055 + 0.24 * sky - 0.02 * floor + 0.6 * warm + 0.95 * cool];
      const k = (y * N + x) * 4;
      for (let j = 0; j < 3; j++) { f32[k + j] = c[j]; b8[k + j] = Math.max(0, Math.min(255, Math.round(255 * c[j]))); }
      f32[k + 3] = 1; b8[k + 3] = 255;
    }
    bytes.push(b8); floats.push(f32);
  }
  const tex = new B.RawCubeTexture(scene, bytes, N, B.Constants.TEXTUREFORMAT_RGBA, B.Constants.TEXTURETYPE_UNSIGNED_BYTE, true);
  tex.gammaSpace = false;
  tex.sphericalPolynomial = B.CubeMapToSphericalPolynomialTools.ConvertCubeMapToSphericalPolynomial({ size: N, right: floats[0], left: floats[1], up: floats[2], down: floats[3], front: floats[4], back: floats[5], format: B.Constants.TEXTUREFORMAT_RGBA, type: B.Constants.TEXTURETYPE_FLOAT, gammaSpace: false });
  scene.environmentTexture = tex;
  scene.environmentIntensity = 1.6;
}

async function mountBabylon(host, url, { onStatus, glow = true, pointSize = 0, env = true } = {}) {
  const B = await loadBjs();
  const canvas = document.createElement('canvas'); canvas.style.width = '100%'; canvas.style.height = '100%'; canvas.style.display = 'block'; canvas.style.touchAction = 'none';
  host.appendChild(canvas);
  const engine = new B.Engine(canvas, true, { preserveDrawingBuffer: false, stencil: true, antialias: true, loseContextOnDispose: true }, true);
  const scene = new B.Scene(engine);
  scene.clearColor = new B.Color4(0.012, 0.016, 0.03, 1);
  const t0 = performance.now();
  await B.SceneLoader.AppendAsync('', new URL(url, location.href).href, scene);
  scene.createDefaultCameraOrLight(true, true, true);
  // glTF point primitives (splats exported as points): draw them unlit at a visible size, in their COLOR_0
  if (pointSize) for (const m of scene.materials) if (m.fillMode === B.Material.PointFillMode || m.pointsCloud) { m.pointSize = pointSize * (devicePixelRatio || 1); if ('unlit' in m) m.unlit = true; }
  const cam = scene.activeCamera;
  const gltfCam = scene.cameras.find(c => c !== cam && c.name !== 'default camera');
  // open on the authored camera: same eye, aimed where it looked, orbiting the point nearest the scene centre on that line
  if (gltfCam && cam && cam.setPosition) {
    gltfCam.computeWorldMatrix(true);
    const eye = gltfCam.globalPosition.clone(), dir = gltfCam.getForwardRay(1).direction.normalize();
    const ext = scene.getWorldExtends(m => m.isVisible && m.isEnabled() && m.getTotalVertices() > 0);
    const centre = ext.min.add(ext.max).scale(0.5);
    const along = Math.max(0.1, B.Vector3.Dot(centre.subtract(eye), dir));
    cam.setTarget(eye.add(dir.scale(along))); cam.setPosition(eye);
    if (gltfCam.fov) cam.fov = gltfCam.fov;
  }
  if (env) { try { studio(B, scene); } catch (e) { console.warn('studio environment skipped', e); } }
  if (cam) { cam.wheelPrecision = Math.max(cam.wheelPrecision || 3, 3); cam.minZ = Math.max(0.01, (cam.radius || 10) / 2000); cam.attachControl(canvas, true); if (!reduced) { cam.useAutoRotationBehavior = true; cam.autoRotationBehavior.idleRotationSpeed = 0.12; } }
  scene.imageProcessingConfiguration.toneMappingEnabled = true;
  scene.imageProcessingConfiguration.toneMappingType = B.ImageProcessingConfiguration.TONEMAPPING_ACES;
  if (glow) { const gl = new B.GlowLayer('glow', scene, { blurKernelSize: 48 }); gl.intensity = 0.7; }
  engine.runRenderLoop(() => scene.render());
  const ro = new ResizeObserver(() => engine.resize()); ro.observe(host);
  onStatus && onStatus(`Babylon.js ${B.Engine.Version} · glb loaded in ${((performance.now() - t0) / 1000).toFixed(1)} s · drag to orbit`);
  return () => { ro.disconnect(); engine.stopRenderLoop(); scene.dispose(); engine.dispose(); canvas.remove(); };
}

// ---------------------------------------------------------------- POC #1 live panels
const POC = { xite: 'brag/poc1/stars-view.x3d', bjs: 'brag/poc1/stars-view.glb' };
$$('#poc1 [data-run]').forEach(btn => btn.addEventListener('click', async () => {
  const view = btn.closest('.view'), status = $('.status', view), which = btn.dataset.run;
  btn.disabled = true; btn.textContent = 'Loading…'; status.hidden = false; status.textContent = which === 'xite' ? 'loading X_ITE 16.7.1 from jsDelivr…' : 'loading Babylon.js 9.32.0 from jsDelivr…';
  const holder = document.createElement('div'); holder.style.cssText = 'position:absolute;inset:0'; view.appendChild(holder);
  try {
    if (which === 'xite') await mountXite(holder, POC.xite, { onStatus: s => status.textContent = s });
    else await mountBabylon(holder, POC.bjs, { onStatus: s => status.textContent = s, glow: false, pointSize: 2.5, env: false });
    $('img', view).remove(); btn.parentElement.remove();
  } catch (e) { status.textContent = 'could not load: ' + (e.message || e); btn.disabled = false; btn.textContent = '▶ Retry'; holder.remove(); }
}));

// ---------------------------------------------------------------- theatre
const th = $('#theatre'), tStage = $('#tStage'), tNote = $('#tNote');
let current = null, unmount = null, lastFocus = null, gen = 0;
async function show(eng) {
  // each call owns a generation: a mount that finishes after a newer show() or after close is torn down at once
  const my = ++gen, live = () => my === gen && th.classList.contains('open');
  if (unmount) { try { unmount(); } catch (_) {} unmount = null; }
  tStage.innerHTML = '<div class="loader"><div>loading ' + (eng === 'xite' ? 'X_ITE' : 'Babylon.js') + '</div></div>';
  tNote.textContent = '';
  $$('.seg button', th).forEach(b => b.setAttribute('aria-pressed', b.dataset.eng === eng));
  $('.seg button[data-eng=bjs]', th).hidden = !current.glb;
  const host = document.createElement('div'); tStage.appendChild(host);
  const note = s => { if (live()) tNote.textContent = s + (current.note && eng === 'xite' ? ' · ' + current.note : ''); };
  try {
    const u = eng === 'xite' ? await mountXite(host, current.x3d, { onStatus: note, viewpoint: current.viewpoint }) : await mountBabylon(host, current.glb, { onStatus: note, env: current.studio !== false });
    if (!live()) { try { u(); } catch (_) {} return; }
    unmount = u;
    $('.loader', tStage) && $('.loader', tStage).remove();
  } catch (e) { if (live()) tStage.innerHTML = `<div class="loader"><div>could not load: ${String(e.message || e).slice(0, 120)}</div></div>`; }
}
// while the dialog is open the page behind it is inert: Tab stays in the dialog, screen readers see only the dialog
const behind = () => [$('.nav'), $('#top'), $('#main'), $('footer')].filter(Boolean);
function openTheatre(s, eng = 'xite') {
  current = s; lastFocus = document.activeElement;
  $('#tTitle').textContent = s.title; th.classList.add('open'); document.body.style.overflow = 'hidden';
  behind().forEach(el => { el.inert = true; });
  $('#tClose').focus(); show(eng);
}
function closeTheatre() {
  if (unmount) { try { unmount(); } catch (_) {} unmount = null; }
  behind().forEach(el => { el.inert = false; });
  th.classList.remove('open'); document.body.style.overflow = ''; tStage.innerHTML = ''; tNote.textContent = ''; lastFocus && lastFocus.focus();
}
$('#tClose').addEventListener('click', closeTheatre);
addEventListener('keydown', e => { if (e.key === 'Escape' && th.classList.contains('open')) closeTheatre(); });
$$('.seg button', th).forEach(b => b.addEventListener('click', () => show(b.dataset.eng)));

loadShowpieces();
