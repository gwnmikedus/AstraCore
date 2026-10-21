// The home hero's live backdrop: a slow flight through fictional space past a planet whose colonies link up,
// drawn in code like the trailer (docs/demo/trailer/film/shared.js), so there is nothing to download.
// Every frame is a pure function of time and the loop is seamless. Reduced motion, a hidden tab or a hero
// scrolled out of view all stop the clock; the pause button's choice is remembered in this browser.
(function () {
  const canvas = document.querySelector('[data-hero-space]');
  if (!canvas || !canvas.getContext) return;
  const hero = canvas.closest('.platform-hero');
  const toggle = document.querySelector('[data-hero-space-toggle]');
  const ctx = canvas.getContext('2d');
  const W = 1920, H = 1080;          // the scene is drawn in this space and scaled to cover the hero
  const LOOP = 24;                   // seconds before the picture repeats
  const FPS = 30;
  const KEY = 'astracore.heroSpace';

  function rng(seed) {
    let s = seed >>> 0;
    return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
  }
  const r = rng(42);
  const D = 2400, F = 820;
  // Stars repeat every LOOP: they travel exactly one depth band D per loop.
  const SPEED = D / LOOP;
  const stars = Array.from({length: 520}, () => ({x: (r() - 0.5) * 5200, y: (r() - 0.5) * 3000, z: r() * D, b: 0.35 + r() * 0.65}));
  const neb = [[-0.9, -0.4, 900, '255,106,26', 0.10], [0.8, 0.5, 1100, '79,157,255', 0.08], [0.2, -0.9, 700, '255,138,71', 0.06],
               [-0.4, 0.9, 1000, '79,157,255', 0.05], [1.2, -0.6, 800, '255,106,26', 0.05]];
  const q = rng(5);
  const blobs = Array.from({length: 70}, () => ({lon: q() * 6.2832, lat: (q() - 0.5) * 2.6, s: 0.05 + q() * 0.16, a: 0.05 + q() * 0.12}));
  const nodes = [[-0.55, -0.25], [-0.2, -0.45], [0.15, -0.2], [-0.35, 0.15], [0.05, 0.3], [0.4, 0.1]];
  const links = [[0, 1], [1, 2], [0, 3], [3, 4], [2, 4], [4, 5], [2, 5]];
  const TAU = 6.2832;
  const seg = (t, a, b) => Math.min(1, Math.max(0, (t - a) / (b - a)));
  const eio = x => x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2;

  function space(T) {
    const z = SPEED * T, zp = SPEED * (T - 1 / FPS);
    const k = TAU / LOOP;                         // sway and drift repeat with the loop
    const sx = Math.sin(T * k) * 60, sy = Math.cos(T * k * 2) * 24;
    ctx.fillStyle = '#0b0c0d';
    ctx.fillRect(0, 0, W, H);
    for (const n of neb) {
      const px = 960 + n[0] * 900 - sx * 0.3, py = 540 + n[1] * 600 - sy * 0.3;
      const g = ctx.createRadialGradient(px, py, 0, px, py, n[2]);
      g.addColorStop(0, `rgba(${n[3]},${n[4]})`);
      g.addColorStop(1, `rgba(${n[3]},0)`);
      ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
    }
    ctx.lineCap = 'round';
    for (const s of stars) {
      const zz = ((s.z - z) % D + D) % D + 20, zo = ((s.z - zp) % D + D) % D + 20;
      const x = 960 + (s.x - sx) * F / zz, y = 540 + (s.y - sy) * F / zz;
      if (x < -50 || x > W + 50 || y < -50 || y > H + 50) continue;
      const near = 1 - zz / D;
      ctx.strokeStyle = `rgba(236,232,223,${(Math.min(1, near * 1.4) * s.b).toFixed(3)})`;
      ctx.lineWidth = 0.6 + near * near * 3.4;
      ctx.beginPath(); ctx.moveTo(x, y);
      if (zo > zz) ctx.lineTo(960 + (s.x - sx) * F / zo, 540 + (s.y - sy) * F / zo); else ctx.lineTo(x + 0.1, y);
      ctx.stroke();
    }
  }

  // Colonies link up one by one, hold, then dim again before the loop restarts.
  function planet(cx, cy, R, T) {
    const rot = T * TAU / LOOP;
    const on = i => eio(seg(T, 3 + i * 0.9, 4.2 + i * 0.9)) * (1 - eio(seg(T, LOOP - 3, LOOP - 0.5)));
    ctx.save();
    ctx.beginPath(); ctx.arc(cx, cy, R, 0, TAU); ctx.clip();
    const body = ctx.createRadialGradient(cx - R * 0.45, cy - R * 0.4, R * 0.1, cx, cy, R * 1.05);
    body.addColorStop(0, '#5a3a26'); body.addColorStop(0.45, '#2a1d16'); body.addColorStop(1, '#0d0b0a');
    ctx.fillStyle = body; ctx.fillRect(cx - R, cy - R, R * 2, R * 2);
    for (const b of blobs) {
      const lon = b.lon + rot; if (Math.cos(lon) < 0) continue;
      const px = cx + Math.sin(lon) * Math.cos(b.lat * 0.6) * R, py = cy + Math.sin(b.lat * 0.6) * R;
      ctx.fillStyle = `rgba(255,170,110,${(b.a * Math.cos(lon)).toFixed(3)})`;
      ctx.beginPath(); ctx.ellipse(px, py, b.s * R * Math.cos(lon), b.s * R * 0.45, 0, 0, TAU); ctx.fill();
    }
    const shade = ctx.createLinearGradient(cx - R, cy - R, cx + R, cy + R);
    shade.addColorStop(0.35, 'rgba(0,0,0,0)'); shade.addColorStop(0.95, 'rgba(0,0,0,.85)');
    ctx.fillStyle = shade; ctx.fillRect(cx - R, cy - R, R * 2, R * 2);
    const pts = nodes.map(n => [cx + (n[0] + Math.sin(rot) * 0.15) * R, cy + n[1] * R]);
    ctx.lineWidth = Math.max(2, R / 160); ctx.strokeStyle = '#ff6a1a'; ctx.shadowColor = '#ff6a1a'; ctx.shadowBlur = 14;
    links.forEach(([a, b], i) => {
      const p = on(i); if (p <= 0) return;
      ctx.beginPath(); ctx.moveTo(pts[a][0], pts[a][1]);
      ctx.lineTo(pts[a][0] + (pts[b][0] - pts[a][0]) * p, pts[a][1] + (pts[b][1] - pts[a][1]) * p); ctx.stroke();
    });
    pts.forEach(([x, y], i) => {
      const p = on(Math.max(0, i - 1)); if (p <= 0) return;
      const s = (8 + 6 * p + 2 * Math.sin(T * TAU / 3 + i)) * Math.max(1, R / 470);
      ctx.fillStyle = `rgba(255,106,26,${p.toFixed(3)})`; ctx.fillRect(x - s / 2, y - s / 2, s, s);
    });
    ctx.restore(); ctx.shadowBlur = 0;
    const rim = ctx.createRadialGradient(cx, cy, R * 0.94, cx, cy, R * 1.12);
    rim.addColorStop(0, 'rgba(79,157,255,0)'); rim.addColorStop(0.35, 'rgba(79,157,255,.45)'); rim.addColorStop(1, 'rgba(79,157,255,0)');
    ctx.fillStyle = rim; ctx.beginPath(); ctx.arc(cx, cy, R * 1.12, 0, TAU); ctx.fill();
  }

  // Cover the hero like object-fit: cover; the planet stays in the open area beside (or below) the copy.
  let view = {scale: 1, ox: 0, oy: 0, portrait: false};
  // Edge to edge: the hero's column isn't centred in the window, so measure instead of using 100vw.
  function bleed() {
    const page = document.documentElement.clientWidth;
    const margin = parseFloat(getComputedStyle(hero).marginLeft) || 0;
    const column = Math.round(hero.getBoundingClientRect().left - margin);   // where the hero would start
    hero.style.width = page + 'px';
    hero.style.marginLeft = -column + 'px';
    hero.style.setProperty('--column-left', column + 'px');   // the copy stays in the page column
  }
  function resize() {
    const box = canvas.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    canvas.width = Math.max(1, Math.round(box.width * dpr));
    canvas.height = Math.max(1, Math.round(box.height * dpr));
    const scale = Math.max(canvas.width / W, canvas.height / H);
    view = {scale, ox: (canvas.width - W * scale) / 2, oy: (canvas.height - H * scale) / 2, portrait: box.width < 760};
  }
  function frame(T) {
    ctx.setTransform(view.scale, 0, 0, view.scale, view.ox, view.oy);
    space(T);
    const visibleW = canvas.width / view.scale, visibleH = canvas.height / view.scale;
    const left = (W - visibleW) / 2, top = (H - visibleH) / 2;
    if (view.portrait) planet(left + visibleW * 0.98, top + visibleH * 0.6, visibleW * 0.36, T);   // peeks in at the right edge
    else planet(left + visibleW * 0.66, top + visibleH * 0.38, Math.min(visibleH * 0.28, visibleW * 0.16), T);   // clear of the trailer card
    ctx.setTransform(1, 0, 0, 1, 0, 0);
  }

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  let paused = false;
  try { paused = localStorage.getItem(KEY) === 'paused'; } catch (e) { /* storage blocked: play */ }
  let inView = true, raf = 0, last = 0, clock = 6;   // start a few seconds in, so the first frame isn't empty
  const running = () => !paused && !reduced.matches && inView && !document.hidden;
  function tick(now) {
    raf = 0;
    if (!running()) return;
    if (last) clock = (clock + Math.min(0.1, (now - last) / 1000)) % LOOP;
    if (!last || now - last >= 1000 / FPS - 1) { frame(clock); last = now; }
    raf = requestAnimationFrame(tick);
  }
  function update() {
    if (toggle) {
      toggle.setAttribute('aria-pressed', String(paused));
      toggle.querySelector('[data-hero-space-label]').textContent = paused ? 'Play background' : 'Pause background';
      toggle.hidden = reduced.matches;
    }
    hero.classList.toggle('is-live', true);
    if (running() && !raf) { last = 0; raf = requestAnimationFrame(tick); }
    if (!running()) frame(clock);          // a still frame, never an empty box
  }
  bleed();
  resize();
  frame(clock);
  new ResizeObserver(() => { resize(); frame(clock); }).observe(canvas);
  // Re-measure whenever the page column can move: after layout and fonts settle, and on every resize.
  new ResizeObserver(bleed).observe(hero.parentElement);
  window.addEventListener('resize', bleed);
  document.fonts?.ready.then(bleed);
  new IntersectionObserver(entries => { inView = entries[0].isIntersecting; update(); }).observe(hero);
  document.addEventListener('visibilitychange', update);
  reduced.addEventListener?.('change', update);
  toggle?.addEventListener('click', () => {
    paused = !paused;
    try { localStorage.setItem(KEY, paused ? 'paused' : 'playing'); } catch (e) { /* remembered for this visit only */ }
    update();
  });
  update();
  // Drawing any moment by hand (tests, screenshots); the loop keeps running on its own clock.
  window.AC = Object.assign(window.AC || {}, {heroSpace: {LOOP, frame}});
})();
