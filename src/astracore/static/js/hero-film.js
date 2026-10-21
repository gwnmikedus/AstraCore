// The home hero plays the PI trailer live: its scenes (docs/demo/trailer/film) are drawn in code on a 1920x1080
// stage scaled to the hero, so there is no video to download. This is the small player they need; the scenes
// themselves are bundled into js/hero-film-scenes.js by scripts/trailer/build_hero_film.py.
// Only the scene on screen is in the page. Reduced motion shows the end card; a hidden tab, a hero out of view
// or the pause button stop the clock (the pause choice is remembered in this browser).
(function () {
  const W = 1920, H = 1080, FPS = 30;
  const KEY = 'astracore.heroFilm';
  const STILL = ['title', 4];        // what reduced motion shows: the end card, settled

  // ---- timing helpers the scenes use --------------------------------------------------------------------
  const clamp = x => Math.min(1, Math.max(0, x));
  const seg = (t, a, b) => clamp((t - a) / (b - a));
  const lerp = (a, b, p) => a + (b - a) * p;
  const eo = p => 1 - Math.pow(1 - p, 3);
  const ei = p => p * p * p;
  const eio = p => p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
  const eob = (p, s = 1.7) => 1 + (s + 1) * Math.pow(p - 1, 3) + s * Math.pow(p - 1, 2);
  function rng(seed) {
    let s = seed >>> 0;
    return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
  }

  // Declarations from the bundle's data-css (the film's inline styles) through CSSOM: the page's content
  // security policy forbids style attributes, not styles set by a trusted script.
  function declarations(css) {
    const out = [];
    let depth = 0, quote = '', start = 0;
    for (let i = 0; i <= css.length; i++) {
      const ch = css[i];
      if (quote) { if (ch === quote) quote = ''; continue; }
      if (ch === '"' || ch === "'") quote = ch;
      else if (ch === '(') depth++;
      else if (ch === ')') depth--;
      else if ((ch === ';' || i === css.length) && depth === 0) {
        const part = css.slice(start, i), colon = part.indexOf(':');
        if (colon > 0) out.push([part.slice(0, colon).trim(), part.slice(colon + 1).trim()]);
        start = i + 1;
      }
    }
    return out;
  }
  function h(html) {
    const tpl = document.createElement('template');
    tpl.innerHTML = html.trim();
    for (const el of tpl.content.querySelectorAll('[data-css]')) {
      for (const [prop, value] of declarations(el.getAttribute('data-css'))) {
        const important = /!important$/.test(value);
        el.style.setProperty(prop, important ? value.replace(/\s*!important$/, '') : value, important ? 'important' : '');
      }
      el.removeAttribute('data-css');
    }
    return tpl.content.firstElementChild;
  }

  // Words slide in from the right, one after another, and out to the left.
  function words(el) {
    if (!el._words) {
      const parts = el.textContent.split(/(\s+)/);
      el.textContent = '';
      el._words = [];
      for (const p of parts) {
        if (/^\s+$/.test(p) || !p) { el.append(p); continue; }
        const w = document.createElement('span');
        w.textContent = p;
        w.style.display = 'inline-block';
        el.append(w);
        el._words.push(w.style);
      }
    }
    return el._words;
  }
  const TextFx = {
    fadeFromRight(el, t, start, {stagger = 0.1, dur = 0.5, dx = 28} = {}) {
      words(el).forEach((st, i) => {
        const p = eo(seg(t, start + i * stagger, start + i * stagger + dur));
        st.opacity = p;
        st.transform = 'translateX(' + lerp(dx, 0, p) + 'px)';
      });
    },
    fadeOutLeft(el, t, start, {stagger = 0.04, dur = 0.35, dx = 24} = {}) {
      words(el).forEach((st, i) => {
        const p = ei(seg(t, start + i * stagger, start + i * stagger + dur));
        st.opacity = 1 - p;
        st.transform = 'translateX(' + lerp(0, -dx, p) + 'px)';
      });
    },
  };

  // A typed line: at(t) is the text shown at local time t.
  function typist(text, start, perSecond) {
    return {at: t => text.slice(0, Math.max(0, Math.min(text.length, Math.floor((t - start) * perSecond))))};
  }

  // The demo pointer: glides between key positions (optionally on a curve), with a click pulse.
  function cursor(stage) {
    const el = h('<div class="film-cursor"><svg viewBox="0 0 24 24" width="44" height="44"><path d="M3 2L3 19L8 14.5L11.5 22L14.5 20.7L11 13.4L17.5 13.4Z" fill="#ece8df" stroke="#0b0c0d" stroke-width="1.5" stroke-linejoin="round"/></svg><span class="film-click"></span></div>');
    stage.append(el);
    const ring = el.querySelector('.film-click').style;
    const c = {keys: [], clicks: [], visible: () => 1};
    c.render = t => {
      const k = c.keys;
      if (!k.length) return;
      let x = k[0].at[0], y = k[0].at[1];
      for (let i = 1; i < k.length; i++) {
        if (t < k[i - 1].t) break;
        const p = eio(seg(t, k[i - 1].t, k[i].t));
        const [ax, ay] = k[i - 1].at, [bx, by] = k[i].at;
        const bow = (k[i].bow || 0) * Math.sin(Math.PI * p) * Math.hypot(bx - ax, by - ay);
        x = lerp(ax, bx, p) - bow * (by - ay) / (Math.hypot(bx - ax, by - ay) || 1);
        y = lerp(ay, by, p) + bow * (bx - ax) / (Math.hypot(bx - ax, by - ay) || 1);
      }
      const press = Math.max(0, ...c.clicks.map(at => 1 - seg(t, at, at + 0.45)).map((v, i) => t >= c.clicks[i] ? v : 0));
      el.style.opacity = clamp(c.visible(t));
      el.style.transform = 'translate(' + x + 'px,' + y + 'px) scale(' + (1 - 0.12 * Math.sin(Math.PI * Math.min(1, press * 2))) + ')';
      ring.opacity = press;
      ring.transform = 'translate(-50%, -50%) scale(' + lerp(1.6, 0.4, press) + ')';
    };
    return c;
  }

  // ---- the player ----------------------------------------------------------------------------------------
  const defs = {};
  const kit = {seg, lerp, eo, ei, eio, eob, rng, TextFx, h, stage: null, start: 0,
               scene(id, def) { defs[id] = def; }, score() { /* the hero plays without sound */ }};
  window.kit = kit;

  let order = [], total = 0;
  kit.boot = function (scenes) {
    const root = document.querySelector('[data-hero-film]');
    const hero = root && root.closest('.platform-hero');
    if (!root) return;
    let at = 0;
    order = scenes.filter(s => defs[s.id]).map(s => { const o = {...s, start: at}; at += s.dur; return o; });
    total = at;
    if (!order.length) return;
    const holder = root.querySelector('.hero-film-stage');
    const toggle = document.querySelector('[data-hero-film-toggle]');
    let live = null;      // {index, scene, stage, canvases}

    // Edge to edge: the hero's column isn't centred in the window, so measure rather than use 100vw. The copy
    // below the film keeps to the page column through --column-left.
    function bleed() {
      if (!hero) return;
      const margin = parseFloat(getComputedStyle(hero).marginLeft) || 0;
      const column = Math.round(hero.getBoundingClientRect().left - margin);
      hero.style.width = document.documentElement.clientWidth + 'px';
      hero.style.marginLeft = -column + 'px';
      hero.style.setProperty('--column-left', column + 'px');
    }
    function fit() {
      const box = root.getBoundingClientRect();
      const scale = Math.max(box.width / W, box.height / H);   // cover; the stage is 16:9, like the hero
      holder.style.transform = 'translate(' + (box.width - W * scale) / 2 + 'px,' + (box.height - H * scale) / 2 + 'px) scale(' + scale + ')';
      // Canvases draw in 1920x1080 units but only need as many pixels as the hero shows.
      live && live.canvases.forEach(sharpen);
    }
    function quality() {
      const box = root.getBoundingClientRect();
      return Math.min(1, Math.max(0.35, box.width * Math.min(window.devicePixelRatio || 1, 1.5) / W));
    }
    function sharpen(c) {
      const q = quality();
      if (c._q === q) return;
      c._q = q;
      c.width = Math.round(W * q); c.height = Math.round(H * q);
      c.getContext('2d').setTransform(q, 0, 0, q, 0, 0);
    }
    function show(index) {
      if (live && live.index === index) return live;
      if (live) live.stage.remove();
      const s = order[index];
      const stage = document.createElement('div');
      stage.className = 'film-scene';
      holder.append(stage);
      const scene = Object.create(defs[s.id]);   // a fresh instance each time a scene comes round
      const ctx = Object.assign(Object.create(kit), {stage, start: s.start});
      ctx.cursor = () => cursor(stage);
      ctx.typist = typist;
      kit.stage = stage; kit.start = s.start;
      scene.init(ctx);
      const canvases = [...stage.querySelectorAll('canvas')];
      canvases.forEach(sharpen);
      live = {index, scene, stage, canvases};
      return live;
    }
    function frame(T) {
      T = ((T % total) + total) % total;
      let i = order.findIndex(s => T < s.start + s.dur);
      if (i < 0) i = order.length - 1;
      show(i).scene.render(T - order[i].start);
    }

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    let paused = false;
    try { paused = localStorage.getItem(KEY) === 'paused'; } catch (e) { /* storage blocked: play */ }
    let inView = true, raf = 0, last = 0, clock = 0;
    const running = () => !paused && !reduced.matches && inView && !document.hidden;
    function tick(now) {
      raf = 0;
      if (!running()) return;
      if (last) clock = (clock + Math.min(0.1, (now - last) / 1000)) % total;
      if (!last || now - last >= 1000 / FPS - 1) { frame(clock); last = now; }
      raf = requestAnimationFrame(tick);
    }
    function still() {
      const s = order.find(o => o.id === STILL[0]);
      return s ? s.start + STILL[1] : clock;
    }
    function update() {
      if (toggle) {
        toggle.setAttribute('aria-pressed', String(paused));
        toggle.querySelector('[data-hero-film-label]').textContent = paused ? 'Play film' : 'Pause film';
        toggle.hidden = reduced.matches;
      }
      if (running() && !raf) { last = 0; raf = requestAnimationFrame(tick); }
      if (!running()) frame(reduced.matches ? still() : clock);   // a still frame, never an empty box
    }
    hero && hero.classList.add('is-live');
    bleed();
    fit();
    hero && new ResizeObserver(bleed).observe(hero.parentElement);
    window.addEventListener('resize', bleed);
    document.fonts?.ready.then(bleed);
    frame(clock);
    new ResizeObserver(fit).observe(root);
    new IntersectionObserver(entries => { inView = entries[0].isIntersecting; update(); }).observe(root);
    document.addEventListener('visibilitychange', update);
    reduced.addEventListener?.('change', update);
    toggle?.addEventListener('click', () => {
      paused = !paused;
      try { localStorage.setItem(KEY, paused ? 'paused' : 'playing'); } catch (e) { /* remembered for this visit only */ }
      update();
    });
    update();
    // Drawing any moment by hand (tests, screenshots); playback keeps its own clock.
    window.AC = Object.assign(window.AC || {}, {heroFilm: {total, frame, scenes: order.map(s => ({id: s.id, start: s.start, dur: s.dur}))}});
  };
})();
