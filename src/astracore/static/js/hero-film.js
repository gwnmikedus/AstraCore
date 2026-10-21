// The home hero plays the PI trailer live: its scenes (docs/demo/trailer/film) are drawn in code on a 1920x1080
// stage scaled to the hero, so there is no video to download. This is the small player they need; the scenes
// themselves are bundled into js/hero-film-scenes.js by scripts/trailer/build_hero_film.py.
// It plays once over the header and then dissolves into it; Play the film replays it. Only the scene on screen is in
// the page. Reduced motion, a phone-sized hero or a browser that has seen it start on the header; a hidden tab, a hero
// out of view or the pause button stop the clock.
(function () {
  const W = 1920, H = 1080, FPS = 30;
  const BAR = 120;                   // the film's letterbox bars: the hero shows the picture between them
  // Film seconds per real second, per scene: the busy ones (pilots, the wizard, the plan) play slower than the cut so
  // there's time to read them; the openers keep their pace. The groove scenes share one speed so the score holds tempo.
  const SPEED = {signal: 0.85, chaos: 0.85, promise: 0.8, meet: 0.8, pilots: 0.62, goal: 0.62, questions: 0.62,
                 area: 0.72, plan: 0.6, build: 0.6, planet: 0.78, screen: 0.66, title: 0.75};
  const SMALL = 760;                 // narrower heroes (phones) start on the header: the film plays on request
  const FADE = 0.5;                  // seconds of film for a cut: the old scene dips to dark, then the new one rises
  const KEY = 'astracore.heroFilm';   // 'seen' once the film has played or been skipped in this browser

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
  let scoreFn = null;   // js/hero-film-score.js, loaded with the sound
  const kit = {seg, lerp, eo, ei, eio, eob, rng, TextFx, h, stage: null, start: 0,
               scene(id, def) { defs[id] = def; }, score(fn) { scoreFn = fn; }};
  window.kit = kit;

  let order = [], total = 0;
  kit.boot = function (scenes) {
    const root = document.querySelector('[data-hero-film]');
    const hero = root && root.closest('.platform-hero');
    if (!root || !hero) return;
    let at = 0, real = 0;
    order = scenes.filter(s => defs[s.id]).map(s => {
      const speed = SPEED[s.id] || 1;
      const o = {...s, start: at, speed, realStart: real};
      at += s.dur; real += s.dur / speed;
      return o;
    });
    total = at;
    const realTotal = real;
    if (!order.length) return;
    const holder = root.querySelector('.hero-film-stage');
    const bar = hero.querySelector('[data-hero-film-bar]');
    const toggle = hero.querySelector('[data-hero-film-toggle]');
    const sound = hero.querySelector('[data-hero-film-sound]');
    const skip = hero.querySelector('[data-hero-film-skip]');
    const replay = hero.querySelector('[data-hero-film-replay]');
    const lives = new Map();   // scene index -> {scene, stage, canvases}: the one on screen, and one fading out
    const sceneAt = T => { const i = order.findIndex(s => T < s.start + s.dur); return i < 0 ? order.length - 1 : i; };
    // Real seconds from the start to film time T (the score is written in film time; this keeps it in step).
    const toReal = T => {
      const laps = Math.floor(T / total), f = T - laps * total, s = order[sceneAt(f)];
      return laps * realTotal + s.realStart + (f - s.start) / s.speed;
    };

    // Edge to edge: the hero's column isn't centred in the window, so measure rather than use 100vw. The copy
    // keeps to the page column through --column-left.
    function bleed() {
      const margin = parseFloat(getComputedStyle(hero).marginLeft) || 0;
      const column = Math.round(hero.getBoundingClientRect().left - margin);
      hero.style.width = document.documentElement.clientWidth + 'px';
      hero.style.marginLeft = -column + 'px';
      hero.style.setProperty('--column-left', column + 'px');
    }
    // The picture between the film's letterbox bars, as large as fits above the control bar; the starfield fills
    // the rest.
    function fit() {
      const box = root.getBoundingClientRect(), band = H - 2 * BAR;
      const over = !bar.hidden && getComputedStyle(bar).position === 'absolute';   // phones put it below the film
      const room = box.height - (over ? bar.offsetHeight + 8 : 0);
      const scale = Math.min(box.width / W, room / band);
      holder.style.transform = 'translate(' + (box.width - W * scale) / 2 + 'px,' + ((room - band * scale) / 2 - BAR * scale) + 'px) scale(' + scale + ')';
      // Canvases draw in 1920x1080 units but only need as many pixels as the hero shows.
      lives.forEach(l => l.canvases.forEach(sharpen));
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
      if (lives.has(index)) return lives.get(index);
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
      const live = {scene, stage, canvases};
      lives.set(index, live);
      return live;
    }
    function clear() { for (const l of lives.values()) l.stage.remove(); lives.clear(); }
    // The scene on screen. For FADE seconds after a cut the previous one plays on and dips to dark first, then the
    // new one rises: two scenes' words never share the screen. The opening rises from dark too.
    function frame(T) {
      T = Math.min(Math.max(T, 0), total - 1e-6);
      const i = sceneAt(T), into = T - order[i].start, half = FADE / 2;
      const keep = into < FADE && i > 0 ? [i, i - 1] : [i];
      for (const [k, l] of lives) if (!keep.includes(k)) { l.stage.remove(); lives.delete(k); }
      const cur = show(i);
      cur.stage.style.zIndex = 1;
      cur.stage.style.opacity = into < FADE ? eio(seg(into, i > 0 ? half : 0, FADE)) : 1;
      cur.scene.render(into);
      if (keep.length > 1) {
        const old = show(i - 1);
        old.stage.style.zIndex = 2;
        old.stage.style.opacity = 1 - eio(seg(into, 0, half));
        old.scene.render(order[i - 1].dur + into);
      }
    }

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    let seen = false;
    try { seen = localStorage.getItem(KEY) === 'seen'; } catch (e) { /* storage blocked: play it */ }
    let playing = false, paused = false, inView = true, raf = 0, last = 0, clock = 0;
    let audio = null, soundOn = false, loading = null, ending = false;
    const running = () => playing && !paused && inView && !document.hidden;
    function tick(now) {
      raf = 0;
      if (!running()) return;
      if (last) clock += Math.min(0.1, (now - last) / 1000) * order[sceneAt(clock)].speed;
      if (clock >= total) { finish(); return; }
      if (!last || now - last >= 1000 / FPS - 1) { frame(clock); last = now; }
      if (soundOn && audio) audio.sync(clock);
      raf = requestAnimationFrame(tick);
    }
    // Sound is off until the pilot turns it on; the synth and score load then, never before.
    function script(src) {
      return new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = src; s.onload = resolve; s.onerror = reject;
        document.head.append(s);
      });
    }
    async function enableSound() {
      loading = loading || (async () => {
        await script(root.dataset.audio);
        await script(root.dataset.score);
        const T = Object.fromEntries(order.map(s => [s.id, s.start]));
        audio = window.AC.heroFilmAudio.Player(scoreFn, T, total, toReal);
      })();
      await loading;
      await audio.resume();
    }
    function label(button, text, icon) {
      button.querySelector('[data-hero-film-label]').textContent = text;
      const slot = button.querySelector('[data-hero-film-icon]');
      if (slot && window.AC && AC.icon) slot.innerHTML = AC.icon(icon);
    }
    function update() {
      hero.classList.toggle('film-done', !playing);
      bar.hidden = !playing;
      replay.hidden = playing;
      toggle.setAttribute('aria-pressed', String(paused));
      label(toggle, paused ? 'Play film' : 'Pause film', paused ? 'play' : 'pause');
      sound.setAttribute('aria-pressed', String(soundOn));
      label(sound, soundOn ? 'Sound off' : 'Sound on', soundOn ? 'volume-2' : 'volume-x');
      sound.hidden = !(window.AudioContext || window.webkitAudioContext);
      if (audio && !(soundOn && running()) && !ending) audio.hush();
      if (running() && !raf) { last = 0; raf = requestAnimationFrame(tick); }
    }
    // The film ends (or is skipped): it dissolves into the header, which rises in; Play the film brings it back.
    function finish() {
      playing = false;
      ending = true;
      if (audio) audio.hush(1.6);   // the end card's hit rings out with the dissolve
      seen = true;
      try { localStorage.setItem(KEY, 'seen'); } catch (e) { /* plays again next visit */ }
      update();
      ending = false;
      setTimeout(() => { if (!playing) clear(); }, 1600);   // after the dissolve: nothing left running
    }
    function play() {
      playing = true; paused = false; clock = 0; last = 0;
      hero.classList.remove('film-done');
      bar.hidden = false;
      clear();
      fit();
      frame(0);
      update();
    }

    hero.classList.add('is-live');
    bleed();
    new ResizeObserver(bleed).observe(hero.parentElement);
    window.addEventListener('resize', bleed);
    document.fonts?.ready.then(bleed);
    new ResizeObserver(fit).observe(root);
    new IntersectionObserver(entries => { inView = entries[0].isIntersecting; update(); }).observe(hero);
    document.addEventListener('visibilitychange', update);
    toggle.addEventListener('click', () => { paused = !paused; update(); });
    skip.addEventListener('click', finish);
    replay.addEventListener('click', () => { play(); toggle.focus({preventScroll: true}); });
    // Sound isn't remembered: browsers only start audio after a click, so every visit begins quiet.
    sound.addEventListener('click', async () => {
      soundOn = !soundOn;
      if (soundOn) {
        sound.disabled = true;
        try { await enableSound(); paused = false; } catch (e) { soundOn = false; /* the synth didn't load: stay quiet */ }
        sound.disabled = false;
      }
      update();
    });
    if (seen || reduced.matches || hero.getBoundingClientRect().width < SMALL) { playing = false; update(); }
    else play();
    // Drawing any moment by hand (tests, screenshots) and the playback state.
    window.AC = Object.assign(window.AC || {}, {heroFilm: {total, realTotal, frame, play, finish, toReal,
      scenes: order.map(s => ({id: s.id, start: s.start, dur: s.dur, speed: s.speed})),
      get playing() { return playing; }, get audio() { return audio; }}});
  };
})();
