// POC #1 hero: the 978 real stars within 50 light-years (HYG v4.1), the same data as
// showcase/scenes/stars-splats.x3d, drawn with three.js. Every point is a catalogue star; nothing decorative is
// added to the star field. Frame: x east, y north, z up, Sun at the origin, one unit one light-year.
import * as THREE from 'three';

const TAU = Math.PI * 2;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DAY = 864e5, LY_DAYS = 365.25;
// when the light arriving now left a star d light-years away (computed for the viewer's date, not baked in)
const lightLeft = d => { const t = new Date(Date.now() - d * LY_DAYS * DAY); return d < 3000 ? `in ${MONTHS[t.getUTCMonth()]} ${t.getUTCFullYear()}` : 'long ago'; };
export const lyOutSince = iso => (Date.now() - Date.parse(iso)) / DAY / LY_DAYS;

const STAR_VS = /* glsl */`
  attribute vec3 color;
  attribute float lum;
  attribute float seed;
  attribute float named;
  uniform float uTime, uPx, uFocus, uTwinkle, uHover;
  varying vec3 vColor; varying float vGlow; varying float vSpike;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    float d = max(-mv.z, 0.5);
    // apparent size: a floor so faint red dwarfs stay visible, plus intrinsic brightness, softened with distance
    float s = (7.0 + 38.0 * lum) * uPx * clamp(pow(uFocus / d, 0.6), 0.5, 3.0);
    float tw = 1.0 + uTwinkle * 0.16 * sin(uTime * (1.3 + seed * 2.7) + seed * 40.0);
    s *= tw;
    s += named * uHover * 6.0 * uPx;
    gl_PointSize = s;
    gl_Position = projectionMatrix * mv;
    vColor = color; vGlow = clamp(0.62 + 0.8 * lum, 0.0, 1.5) * tw; vSpike = smoothstep(0.62, 0.95, lum);
  }`;
const STAR_FS = /* glsl */`
  varying vec3 vColor; varying float vGlow; varying float vSpike;
  void main() {
    vec2 p = gl_PointCoord * 2.0 - 1.0;
    float r2 = dot(p, p);
    if (r2 > 1.0) discard;
    float core = exp(-r2 * 18.0);
    float halo = exp(-sqrt(r2) * 4.2) * 0.5;
    float spike = vSpike * (exp(-abs(p.x) * 40.0) + exp(-abs(p.y) * 40.0)) * (1.0 - sqrt(r2)) * 0.55;
    float a = (core + halo + spike) * vGlow;
    vec3 c = mix(vColor, vec3(1.0), core * 0.65);
    gl_FragColor = vec4(c * a, a);
  }`;

const SHELL_VS = /* glsl */`
  varying vec3 vN; varying vec3 vV;
  void main() { vec4 mv = modelViewMatrix * vec4(position, 1.0); vN = normalize(normalMatrix * normal); vV = normalize(-mv.xyz);
    gl_Position = projectionMatrix * mv; }`;
const SHELL_FS = /* glsl */`
  uniform vec3 uColor; uniform float uAlpha; varying vec3 vN; varying vec3 vV;
  void main() { float f = pow(1.0 - abs(dot(vN, vV)), 3.0); gl_FragColor = vec4(uColor * f * uAlpha, f * uAlpha); }`;

const SKY_VS = /* glsl */`varying vec3 vDir; void main(){ vDir = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`;
// A soft band along the galactic plane (direction from the fitted frame) so the bubble sits in the Milky Way.
const SKY_FS = /* glsl */`
  uniform vec3 uGal; uniform float uAlpha; varying vec3 vDir;
  float h(vec3 p){ return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453); }
  float n3(vec3 p){ vec3 i=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);
    return mix(mix(mix(h(i),h(i+vec3(1,0,0)),f.x),mix(h(i+vec3(0,1,0)),h(i+vec3(1,1,0)),f.x),f.y),
               mix(mix(h(i+vec3(0,0,1)),h(i+vec3(1,0,1)),f.x),mix(h(i+vec3(0,1,1)),h(i+vec3(1,1,1)),f.x),f.y),f.z); }
  float fbm(vec3 p){ float a=0.5, s=0.0; for(int i=0;i<5;i++){ s+=a*n3(p); p*=2.03; a*=0.5; } return s; }
  void main(){
    float b = dot(normalize(vDir), uGal);
    float band = exp(-b*b*18.0);
    float dust = fbm(vDir*6.0);
    float lanes = smoothstep(0.35, 0.75, fbm(vDir*11.0 + 3.0));
    float glow = band * (0.55 + 0.6*dust) * (1.0 - 0.55*lanes*exp(-b*b*60.0));
    vec3 col = mix(vec3(0.20,0.24,0.42), vec3(0.95,0.78,0.55), smoothstep(0.4,0.9,dust)) * glow;
    gl_FragColor = vec4(col * uAlpha, 1.0);
  }`;

function ease(t) { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }

export async function initHero(opts) {
  const { canvas, stage, dataUrl, namesUrl, hud, tip, labelsLayer, onReady } = opts;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, powerPreference: 'high-performance' });
  } catch (e) { return null; }
  const [data, names] = await Promise.all([
    fetch(dataUrl).then(r => r.json()),
    namesUrl ? fetch(namesUrl).then(r => r.ok ? r.json() : null).catch(() => null) : null,
  ]);
  const stars = data.stars;
  const N = stars.length;
  renderer.setClearColor(0x03050b, 1);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(48, 1, 0.05, 5000);
  camera.up.set(0, 0, 1);

  // ---- stars
  const pos = new Float32Array(N * 3), col = new Float32Array(N * 3), lum = new Float32Array(N), seed = new Float32Array(N), named = new Float32Array(N);
  let maxSize = 0; for (const s of stars) maxSize = Math.max(maxSize, s[6]);
  const dist = new Float32Array(N);
  stars.forEach((s, i) => {
    pos.set([s[0], s[1], s[2]], i * 3);
    // the catalogue colours are near-white; lift saturation so B-V reads at a glance
    const c = new THREE.Color(s[3] / 255, s[4] / 255, s[5] / 255);
    const hsl = {}; c.getHSL(hsl); c.setHSL(hsl.h, Math.min(1, hsl.s * 2.4 + 0.12), Math.min(0.78, hsl.l * 0.86));
    col.set([c.r, c.g, c.b], i * 3);
    lum[i] = Math.pow(s[6] / maxSize, 2.6);
    seed[i] = ((i * 2654435761) % 1000) / 1000;
    dist[i] = Math.hypot(s[0], s[1], s[2]);
  });
  const nameList = (names && names.stars) || [];
  const byIndex = new Map(nameList.map(n => [n.index, n]));
  for (const n of nameList) if (n.index >= 0 && n.index < N) named[n.index] = 1;
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('color', new THREE.BufferAttribute(col, 3));
  g.setAttribute('lum', new THREE.BufferAttribute(lum, 1));
  g.setAttribute('seed', new THREE.BufferAttribute(seed, 1));
  g.setAttribute('named', new THREE.BufferAttribute(named, 1));
  const starMat = new THREE.ShaderMaterial({
    vertexShader: STAR_VS, fragmentShader: STAR_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uTime: { value: 0 }, uPx: { value: 1 }, uFocus: { value: 128 }, uTwinkle: { value: reduced ? 0 : 1 }, uHover: { value: 0 } },
  });
  scene.add(new THREE.Points(g, starMat));

  // ---- the Sun
  const solGeo = new THREE.BufferGeometry();
  solGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array([0, 0, 0]), 3));
  solGeo.setAttribute('color', new THREE.BufferAttribute(new Float32Array([1, 0.86, 0.55]), 3));
  solGeo.setAttribute('lum', new THREE.BufferAttribute(new Float32Array([0.55]), 1));
  solGeo.setAttribute('seed', new THREE.BufferAttribute(new Float32Array([0.3]), 1));
  solGeo.setAttribute('named', new THREE.BufferAttribute(new Float32Array([0]), 1));
  scene.add(new THREE.Points(solGeo, starMat));

  // ---- instrument: rings in the horizon plane, spokes, drop lines for named stars
  const amber = new THREE.Color(0xffb35c), cyan = new THREE.Color(0x6fd3ff);
  const ringGroup = new THREE.Group(); scene.add(ringGroup);
  for (let r = 10; r <= 50; r += 10) {
    const pts = []; for (let k = 0; k <= 256; k++) { const a = k / 256 * TAU; pts.push(new THREE.Vector3(Math.cos(a) * r, Math.sin(a) * r, 0)); }
    const m = new THREE.LineBasicMaterial({ color: r === 50 ? amber : 0x3a4a6e, transparent: true, opacity: r === 50 ? 0.55 : 0.28, depthWrite: false });
    ringGroup.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), m));
  }
  {
    const pts = [];
    for (let k = 0; k < 12; k++) { const a = k / 12 * TAU; pts.push(new THREE.Vector3(Math.cos(a) * 10, Math.sin(a) * 10, 0), new THREE.Vector3(Math.cos(a) * 50, Math.sin(a) * 50, 0)); }
    ringGroup.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts),
      new THREE.LineBasicMaterial({ color: 0x2a3858, transparent: true, opacity: 0.22, depthWrite: false })));
  }
  {
    const pts = [];
    const brightest = [...Array(N).keys()].sort((a, b) => lum[b] - lum[a]).slice(0, 40);
    const set = new Set([...brightest, ...nameList.map(n => n.index)]);
    for (const i of set) { if (i < 0 || i >= N) continue; const x = pos[i * 3], y = pos[i * 3 + 1], z = pos[i * 3 + 2]; pts.push(new THREE.Vector3(x, y, z), new THREE.Vector3(x, y, 0)); }
    const drop = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts),
      new THREE.LineBasicMaterial({ color: 0x5b7bb5, transparent: true, opacity: 0.09, depthWrite: false }));
    ringGroup.add(drop);
  }
  // the 50 ly bubble, a rim-lit shell
  const shell = new THREE.Mesh(new THREE.SphereGeometry(50, 96, 64), new THREE.ShaderMaterial({
    vertexShader: SHELL_VS, fragmentShader: SHELL_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.FrontSide,
    uniforms: { uColor: { value: new THREE.Color(0x4f7dff) }, uAlpha: { value: 0.32 } },
  }));
  scene.add(shell);
  // Arecibo message: sent 16 Nov 1974, about 52 light-years out by Nov 2026 (just beyond this map)
  const arecibo = new THREE.Mesh(new THREE.SphereGeometry(1, 64, 48), new THREE.ShaderMaterial({
    vertexShader: SHELL_VS, fragmentShader: SHELL_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uColor: { value: new THREE.Color(0xffb35c) }, uAlpha: { value: 0 } },
  }));
  scene.add(arecibo);
  // its beam toward M13 (direction from the star-name fit), drawn out to the 52 ly front
  const arDir = names && Array.isArray(names.arecibo_direction) ? new THREE.Vector3(...names.arecibo_direction).normalize() : null;
  let beam = null;
  if (arDir) {
    const n = 64, bp = new Float32Array(n * 3), bc = new Float32Array(n * 3);
    for (let k = 0; k < n; k++) { const r = 52 * k / (n - 1); bp.set([arDir.x * r, arDir.y * r, arDir.z * r], k * 3); const f = 0.25 + 0.75 * k / (n - 1); bc.set([1 * f, 0.7 * f, 0.36 * f], k * 3); }
    const bg = new THREE.BufferGeometry(); bg.setAttribute('position', new THREE.BufferAttribute(bp, 3)); bg.setAttribute('color', new THREE.BufferAttribute(bc, 3));
    beam = new THREE.Line(bg, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false }));
    scene.add(beam);
  }

  // the Milky Way band, only when the star-name fit recovered the galactic pole in this frame
  const gal = names && Array.isArray(names.galactic_north) ? new THREE.Vector3(...names.galactic_north).normalize() : null;
  let skyMat = null;
  if (gal) {
    skyMat = new THREE.ShaderMaterial({ vertexShader: SKY_VS, fragmentShader: SKY_FS, side: THREE.BackSide, depthWrite: false,
      uniforms: { uGal: { value: gal }, uAlpha: { value: 0.22 } } });
    scene.add(new THREE.Mesh(new THREE.SphereGeometry(1500, 64, 32), skyMat));
  }

  // ---- camera rig: spherical orbit with damping, scroll dolly, fly-to
  const rig = { target: new THREE.Vector3(), theta: -0.9, phi: 1.12, radius: 104, vt: 0, vp: 0 };
  const goal = { target: new THREE.Vector3(), radius: 128 };
  let flight = null;
  let focusName = '';
  let auto = !reduced;
  let scrollK = 0;
  function place() {
    const r = rig.radius;
    camera.position.set(rig.target.x + r * Math.sin(rig.phi) * Math.cos(rig.theta), rig.target.y + r * Math.sin(rig.phi) * Math.sin(rig.theta), rig.target.z + r * Math.cos(rig.phi));
    camera.lookAt(rig.target);
  }
  function flyTo(index, radius) {
    focusName = index == null ? '' : ((byIndex.get(index) || {}).name || 'HYG star #' + (index + 1));
    const to = index == null ? new THREE.Vector3() : new THREE.Vector3(pos[index * 3], pos[index * 3 + 1], pos[index * 3 + 2]);
    flight = { t: 0, from: rig.target.clone(), to, r0: rig.radius, r1: radius, dur: 2.6 };
    auto = false;
  }

  // ---- pointer: drag to orbit, hover to read a star
  let drag = null;
  canvas.addEventListener('pointerdown', e => { drag = { x: e.clientX, y: e.clientY, auto }; canvas.setPointerCapture(e.pointerId); auto = false; });
  canvas.addEventListener('pointerup', e => { drag = null; try { canvas.releasePointerCapture(e.pointerId); } catch (_) {} });
  // a touch that became a page scroll ends in pointercancel: it was not an orbit, so undo it and keep the slow turn
  canvas.addEventListener('pointercancel', () => { if (drag) auto = drag.auto; drag = null; rig.vt = rig.vp = 0; });
  const mouse = { x: -1e4, y: -1e4 };
  canvas.addEventListener('pointermove', e => {
    const r = canvas.getBoundingClientRect(); mouse.x = e.clientX - r.left; mouse.y = e.clientY - r.top;
    if (drag) { rig.vt -= (e.clientX - drag.x) * 0.0042; rig.vp -= (e.clientY - drag.y) * 0.0032; drag.x = e.clientX; drag.y = e.clientY; }
  });
  canvas.addEventListener('pointerleave', () => { mouse.x = mouse.y = -1e4; if (tip) tip.hidden = true; });
  canvas.addEventListener('dblclick', () => { if (hover >= 0) flyTo(hover, 7); });
  canvas.tabIndex = 0;
  canvas.addEventListener('keydown', e => {
    const k = { ArrowLeft: [0.06, 0], ArrowRight: [-0.06, 0], ArrowUp: [0, -0.05], ArrowDown: [0, 0.05] }[e.key];
    if (k) { rig.vt += k[0]; rig.vp += k[1]; auto = false; e.preventDefault(); }
  });

  // ---- labels
  const labelEls = [];
  if (labelsLayer) {
    const sol = document.createElement('div'); sol.className = 'lbl sol'; sol.innerHTML = '<b>Sol</b><span>you are here</span>';
    labelsLayer.appendChild(sol); labelEls.push({ el: sol, i: -1, v: new THREE.Vector3() });
    for (const n of nameList) {
      if (n.index < 0 || n.index >= N) continue;
      const el = document.createElement('div'); el.className = 'lbl';
      el.innerHTML = `<b>${n.name}</b><span>${(+n.distance_ly).toFixed(1)} ly</span>`;
      labelsLayer.appendChild(el);
      labelEls.push({ el, i: n.index, v: new THREE.Vector3(pos[n.index * 3], pos[n.index * 3 + 1], pos[n.index * 3 + 2]) });
    }
    if (names && Array.isArray(names.galactic_center)) {
      const el = document.createElement('div'); el.className = 'lbl far'; el.innerHTML = '<b>→ Galactic centre</b><span>about 26,000 ly that way</span>';
      labelsLayer.appendChild(el); labelEls.push({ el, i: -3, v: new THREE.Vector3(...names.galactic_center).normalize().multiplyScalar(60) });
    }
    if (arDir) {
      const el = document.createElement('div'); el.className = 'lbl far beam'; el.innerHTML = `<b>Arecibo message → M13</b><span>sent 16 Nov 1974 · ${lyOutSince('1974-11-16T00:00:00Z').toFixed(2)} ly out today</span>`;
      labelsLayer.appendChild(el); labelEls.push({ el, i: -4, v: arDir.clone().multiplyScalar(54) });
    }
    for (let r = 10; r <= 50; r += 10) {
      const el = document.createElement('div'); el.className = 'lbl ring'; el.textContent = r + ' ly';
      labelsLayer.appendChild(el); labelEls.push({ el, i: -2, v: new THREE.Vector3(r * Math.cos(-0.5), r * Math.sin(-0.5), 0) });
    }
  }

  // Sol and the beam first, then named stars from brightest, then the far markers and ring distances
  const rank = L => L.i === -1 ? -1e3 : L.i === -4 ? -999 : L.i === -2 ? 1e3 : L.i === -3 ? 900 : -lum[L.i];
  const labelsByPriority = [...labelEls].sort((a, b) => rank(a) - rank(b));
  const placed = [];

  // ---- size and loop
  let W = 1, H = 1, px = 1;
  function resize() {
    const r = stage.getBoundingClientRect(); W = Math.max(1, r.width); H = Math.max(1, r.height);
    px = Math.min(window.devicePixelRatio || 1, W < 700 ? 1.5 : 1.75);
    renderer.setPixelRatio(px); renderer.setSize(W, H, false);
    camera.aspect = W / H; camera.fov = W / H < 0.8 ? 64 : 48;
    // on wide screens put the Sun right of centre, clear of the headline
    if (W > 900) camera.setViewOffset(W, H, -W * 0.16, 0, W, H); else camera.clearViewOffset();
    camera.updateProjectionMatrix();
    starMat.uniforms.uPx.value = px * Math.max(0.75, Math.min(1.25, H / 900));
  }
  new ResizeObserver(resize).observe(stage); resize();
  let visible = true;
  new IntersectionObserver(es => { visible = es[0].isIntersecting; if (visible) loop(); }, { threshold: 0 }).observe(stage);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) loop(); });

  let hover = -1, running = false, last = performance.now(), t0 = last, frames = 0, aRecibo = 0, showArecibo = false;
  const v = new THREE.Vector3();
  function pick() {
    let best = -1, bd = 15 * 15;
    for (let i = 0; i < N; i++) {
      v.set(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]).project(camera);
      if (v.z > 1) continue;
      const sx = (v.x * 0.5 + 0.5) * W, sy = (-v.y * 0.5 + 0.5) * H;
      const d = (sx - mouse.x) ** 2 + (sy - mouse.y) ** 2;
      if (d < bd) { bd = d; best = i; }
    }
    return best;
  }
  function describe(i) {
    const n = byIndex.get(i), d = dist[i];
    const left = lightLeft(n ? +n.distance_ly : d);
    const t = n ? `<b>${n.name}</b>` : `<b>HYG star #${i + 1}</b>`;
    const spec = n && n.spectral ? ` · ${n.spectral}` : '';
    const note = n && n.note ? `<span class="n">${n.note.split(/(?<=\.)\s/)[0]}</span>` : '';
    return `${t}<span>${(n ? +n.distance_ly : d).toFixed(2)} ly${spec}</span>${note}<span class="d">the light you see tonight left it ${left}</span>`;
  }
  function frame(now) {
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    const t = (now - t0) / 1000;
    starMat.uniforms.uTime.value = t;
    if (flight) {
      flight.t = Math.min(1, flight.t + dt / flight.dur); const k = ease(flight.t);
      rig.target.lerpVectors(flight.from, flight.to, k); rig.radius = flight.r0 + (flight.r1 - flight.r0) * k;
      if (flight.t >= 1) flight = null;
    } else {
      const want = 104 - 44 * scrollK;
      if (rig.target.lengthSq() < 1e-6) rig.radius += (want - rig.radius) * Math.min(1, dt * 3);
    }
    if (auto) rig.theta += dt * 0.035;
    rig.theta += rig.vt; rig.phi = Math.min(2.9, Math.max(0.12, rig.phi + rig.vp));
    rig.vt *= 0.9; rig.vp *= 0.9;
    place();
    // Arecibo shell breathes out to 52 ly when shown
    aRecibo += ((showArecibo ? 1 : 0) - aRecibo) * Math.min(1, dt * 2.5);
    const pulse = (t * 0.16) % 1;
    arecibo.scale.setScalar(showArecibo ? 52 * (0.12 + 0.88 * ease(pulse)) : 52);
    arecibo.material.uniforms.uAlpha.value = aRecibo * (showArecibo ? (1 - pulse) * 0.9 : 0);
    if (beam) beam.material.opacity = aRecibo * (0.55 + 0.35 * Math.sin(t * 3.1));
    starMat.uniforms.uHover.value += ((hover >= 0 && named[hover] ? 1 : 0) - starMat.uniforms.uHover.value) * 0.2;
    renderer.render(scene, camera);
    // labels: project, fade with distance, and declutter (higher priority wins a crowded spot)
    placed.length = 0;
    for (const L of labelsByPriority) {
      const p = L.i === -1 ? v.set(0, 0, 0) : v.copy(L.v);
      const cd = camera.position.distanceTo(p);
      p.project(camera);
      const on = p.z < 1 && Math.abs(p.x) < 1.05 && Math.abs(p.y) < 1.05;
      if (!on) { L.el.style.opacity = 0; continue; }
      const x = (p.x * 0.5 + 0.5) * W, y = (-p.y * 0.5 + 0.5) * H;
      if (!L.w) L.w = L.el.offsetWidth || 90;
      const clash = placed.some(q => x < q.x + q.w + 6 && q.x < x + L.w + 6 && Math.abs(q.y - y) < 15);
      const want = L.i === -2 ? 0.75 : L.i === -1 ? 0.95 : L.i === -3 ? 0.55 : L.i === -4 ? aRecibo : Math.max(0.3, Math.min(1, 1.3 - cd / 160));
      const op = clash ? 0 : want;
      if (!clash && want > 0.05) placed.push({ x, y, w: L.w });
      L.el.style.opacity = op;
      L.el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;
    }
    if (frames++ % 3 === 0 && mouse.x > -1e3) {
      hover = pick();
      if (tip) {
        if (hover >= 0) {
          tip.innerHTML = describe(hover); tip.hidden = false;
          tip.style.transform = `translate(${Math.min(W - 230, mouse.x + 16)}px, ${mouse.y + 16}px)`;
          canvas.style.cursor = 'pointer';
        } else { tip.hidden = true; canvas.style.cursor = drag ? 'grabbing' : 'grab'; }
      }
    }
    if (hud && frames % 10 === 0) hud.textContent = `camera ${rig.radius.toFixed(0)} ly from ${rig.target.lengthSq() < 0.01 ? 'Sol' : (focusName || 'the star')} · drag to orbit · double-click a star to fly`;
  }
  function loop() {
    if (running) return; running = true;
    const step = now => {
      if (!visible || document.hidden) { running = false; return; }
      frame(now);
      if (reduced && !flight && !drag && Math.abs(rig.vt) + Math.abs(rig.vp) < 1e-5 && frames > 2 && !showArecibo) { running = false; return; }
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  const wake = () => loop();
  canvas.addEventListener('pointermove', wake); canvas.addEventListener('pointerdown', wake); canvas.addEventListener('keydown', wake);
  place(); loop();
  onReady && onReady();
  const api = {
    flyTo(nameOrIndex, radius = 7) {
      if (nameOrIndex === 'sol') { flight = { t: 0, from: rig.target.clone(), to: new THREE.Vector3(), r0: rig.radius, r1: radius, dur: 2.6 }; auto = false; loop(); return; }
      if (nameOrIndex === 'out') { flight = { t: 0, from: rig.target.clone(), to: new THREE.Vector3(), r0: rig.radius, r1: 104, dur: 2.6 }; auto = !reduced; loop(); return; }
      const n = typeof nameOrIndex === 'number' ? nameOrIndex : (nameList.find(s => s.name.toLowerCase().startsWith(String(nameOrIndex).toLowerCase())) || {}).index;
      if (n != null) { flyTo(n, radius); loop(); }
    },
    setScroll(k) { scrollK = Math.max(0, Math.min(1, k)); loop(); },
    arecibo(on) { showArecibo = on; loop(); },
    names: nameList,
    galaxy: !!gal,
  };
  return api;
}
