/* Star field: the real catalogue, drawn on a 2D canvas with a tiny perspective projection.
   Data: array of [x, y, z, r, g, b, s] (light-years from the Sun; linear-ish colour 0..1; s = relative size). */
(function () {
  'use strict';
  var canvas = document.getElementById('sky');
  if (!canvas) return;
  var ctx = canvas.getContext('2d');
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var stars = [], W = 0, H = 0, dpr = 1;
  var yaw = 0.6, pitch = -0.38, vyaw = reduce ? 0 : 0.045, dragging = false, lastX = 0, lastY = 0, idle = 0;
  var R = 50, visible = true;

  function resize() {
    var r = canvas.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = Math.max(1, Math.round(r.width)); H = Math.max(1, Math.round(r.height));
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (reduce || !running) draw(0);
  }

  function project(x, y, z, cy, sy, cp, sp, k, cx, cyy) {
    // rotate about the vertical (z, up) axis by yaw, then tilt by pitch; k = pixels per light-year at the Sun's depth
    var x1 = x * cy - y * sy, y1 = x * sy + y * cy, z1 = z;
    var y2 = y1 * cp - z1 * sp, z2 = y1 * sp + z1 * cp;
    var d = 150 / (150 + y2);                // the camera sits 150 ly out along +y after the tilt
    return [cx + x1 * k * d, cyy - z2 * k * d, d, y2];
  }

  function draw(dt) {
    ctx.clearRect(0, 0, W, H);
    var wide = W > 900, cx = wide ? W * 0.66 : W * 0.5, cyy = wide ? H * 0.5 : H * 0.8, f = wide ? Math.min(H * 0.98, W * 0.78) * 0.46 / 50 : W * 0.46 / 50;
    var cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
    // distance rings in the catalogue's equatorial plane
    ctx.lineWidth = 1;
    for (var ring = 10; ring <= 50; ring += 10) {
      ctx.beginPath();
      for (var a = 0; a <= 64; a++) {
        var t = a / 64 * Math.PI * 2, p = project(Math.cos(t) * ring, Math.sin(t) * ring, 0, cy, sy, cp, sp, f, cx, cyy);
        if (a === 0) ctx.moveTo(p[0], p[1]); else ctx.lineTo(p[0], p[1]);
      }
      ctx.strokeStyle = ring === 50 ? 'rgba(255,180,84,.30)' : 'rgba(150,170,220,.10)';
      ctx.stroke();
    }
    var proj = [];
    for (var i = 0; i < stars.length; i++) {
      var s = stars[i], p2 = project(s[0], s[1], s[2], cy, sy, cp, sp, f, cx, cyy);
      proj.push([p2[0], p2[1], p2[2], p2[3], s]);
    }
    proj.sort(function (a, b) { return b[3] - a[3]; });      // far to near
    ctx.globalCompositeOperation = 'lighter';
    for (var k = 0; k < proj.length; k++) {
      var q = proj[k], st = q[4], size = (0.45 + st[6] * 0.62) * q[2];
      var al = Math.min(1, 0.35 + q[2] * 0.55);
      var col = (st[3] * 255) | 0, g = (st[4] * 255) | 0, b = (st[5] * 255) | 0;
      if (size > 1.15) {
        var gr = ctx.createRadialGradient(q[0], q[1], 0, q[0], q[1], size * 3.4);
        gr.addColorStop(0, 'rgba(' + col + ',' + g + ',' + b + ',' + (al * 0.7) + ')');
        gr.addColorStop(1, 'rgba(' + col + ',' + g + ',' + b + ',0)');
        ctx.fillStyle = gr; ctx.beginPath(); ctx.arc(q[0], q[1], size * 3.4, 0, 6.2832); ctx.fill();
      }
      ctx.fillStyle = 'rgba(' + col + ',' + g + ',' + b + ',' + al + ')';
      ctx.beginPath(); ctx.arc(q[0], q[1], size, 0, 6.2832); ctx.fill();
    }
    ctx.globalCompositeOperation = 'source-over';
    // the Sun at the origin
    var sun = project(0, 0, 0, cy, sy, cp, sp, f, cx, cyy);
    ctx.fillStyle = '#ffd98a'; ctx.beginPath(); ctx.arc(sun[0], sun[1], 3.2, 0, 6.2832); ctx.fill();
    ctx.strokeStyle = 'rgba(255,217,138,.55)'; ctx.beginPath(); ctx.arc(sun[0], sun[1], 8, 0, 6.2832); ctx.stroke();
    var lab = project(50, 0, 0, cy, sy, cp, sp, f, cx, cyy);
    ctx.fillStyle = 'rgba(255,180,84,.8)'; ctx.font = '11px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';
    ctx.fillText('50 ly', lab[0] + 6, lab[1] - 4);
    ctx.fillStyle = 'rgba(255,217,138,.85)'; ctx.fillText('Sol', sun[0] + 12, sun[1] + 4);
  }

  var running = false, last = 0;
  function frame(ts) {
    if (!running) return;
    var dt = Math.min(0.05, (ts - last) / 1000 || 0.016); last = ts;
    if (!dragging) { idle += dt; if (idle > 0.6) yaw += vyaw * dt * 6; }
    draw(dt);
    requestAnimationFrame(frame);
  }
  function start() { if (running || reduce || !visible || document.hidden) return; running = true; last = performance.now(); requestAnimationFrame(frame); }
  function stop() { running = false; }

  canvas.addEventListener('pointerdown', function (e) { dragging = true; lastX = e.clientX; lastY = e.clientY; idle = 0; try { canvas.setPointerCapture(e.pointerId); } catch (_) {} });
  canvas.addEventListener('pointermove', function (e) {
    if (!dragging) return;
    yaw += (e.clientX - lastX) * 0.006; pitch = Math.max(-1.45, Math.min(1.45, pitch + (e.clientY - lastY) * 0.005));
    lastX = e.clientX; lastY = e.clientY; idle = 0; if (!running) draw(0);
  });
  function up() { dragging = false; idle = 0; }
  canvas.addEventListener('pointerup', up); canvas.addEventListener('pointercancel', up);
  canvas.addEventListener('keydown', function (e) {
    var k = e.key; if (k === 'ArrowLeft') yaw -= 0.12; else if (k === 'ArrowRight') yaw += 0.12; else if (k === 'ArrowUp') pitch = Math.min(1.45, pitch + 0.08); else if (k === 'ArrowDown') pitch = Math.max(-1.45, pitch - 0.08); else return;
    e.preventDefault(); if (!running) draw(0);
  });
  window.addEventListener('resize', resize);
  document.addEventListener('visibilitychange', function () { document.hidden ? stop() : start(); });
  if ('IntersectionObserver' in window) new IntersectionObserver(function (en) { visible = en[0].isIntersecting; visible ? start() : stop(); }).observe(canvas);

  window.__setStars = function (arr) { stars = arr; resize(); draw(0); start(); };
  window.__starsInfo = function () { return { n: stars.length, W: W, H: H }; };
})();
