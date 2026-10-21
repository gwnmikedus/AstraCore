// The hero film's soundtrack, synthesised in the browser (Web Audio): loaded only when the pilot turns sound on.
// The score itself (docs/demo/trailer/film/score.js, bundled as js/hero-film-score.js) writes notes, drums and
// effects against the film's scene times; this compiles it once into events and plays them in step with the
// film's clock, a fraction of a second ahead. Notes already sounding when sound starts, the film resumes or the
// loop comes round start softly, so nothing clicks in or cuts off.
(function () {
  const AudioCtx = window.AudioContext || window.webkitAudioContext;
  if (!AudioCtx) return;
  const LOOKAHEAD = 0.35;                       // seconds of film scheduled ahead
  const VOLUME = 0.55;                          // a background score: well under the page's other sounds
  const NOTE = {C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11};
  const midi = n => { const m = /^([A-G])(#|b)?(-?\d)$/.exec(n); return 12 * (+m[3] + 1) + NOTE[m[1]] + (m[2] === '#' ? 1 : m[2] === 'b' ? -1 : 0); };
  const hz = m => 440 * Math.pow(2, (m - 69) / 12);
  const db = g => Math.pow(10, (g || 0) / 20);
  const masterGain = g => db(g) * VOLUME;
  const level = v => Math.pow(Math.max(0, Math.min(127, v == null ? 80 : v)) / 127, 1.6);

  // ---- the score, compiled into a flat list of events --------------------------------------------------------
  function compile(score, T) {
    const events = [], programs = {};
    let bpm = 120, t0 = 0, master = {gain: 0, fadeOut: 0};
    const beatTime = b => t0 + b * 60 / bpm;
    const when = o => o.t != null ? o.t : beatTime(o.beat || 0);
    const length = (o, d) => o.dur != null ? o.dur : o.beats != null ? o.beats * 60 / bpm : d;
    const S = {
      tempo(b, o = {}) { bpm = b; t0 = o.t0 || 0; },
      toBeat: t => (t - t0) * bpm / 60,
      program(name, inst, o = {}) { programs[name] = {inst, rev: o.rev || 0, gain: o.gain || 0, pan: o.pan || 0}; },
      note(p, n, o = {}) { events.push({kind: 'note', p, m: midi(n), t: when(o), d: length(o, 0.5), v: o.vel}); },
      chord(p, ns, o = {}) { ns.forEach(n => S.note(p, n, o)); },
      run(p, ns, o = {}) { ns.forEach((n, i) => S.note(p, n, {t: o.t + i * o.step, dur: o.step * 3, vel: (o.vel || 60) + i * (o.cresc || 0)})); },
      drum(name, o = {}) { events.push({kind: 'drum', name, t: when(o), v: o.vel}); },
      fx(name, t, o = {}) { events.push({kind: 'fx', name, t, d: o.dur || 0.3, v: o.vel == null ? 70 : o.vel, pitch: o.pitch || 0}); },
      // 8 steps a bar (half beats): x = hit, X = accent, o = soft or open, . = rest
      pattern(p, str, o = {}) {
        let k = 0;
        for (let r = 0; r < (o.repeat || 1); r++) [...str].forEach((c, i) => {
          if (c === '.') return;
          const pitches = [].concat(o.pitch || 'C4');
          S.note(p, pitches[k++ % pitches.length], {beat: (o.from || 0) + r * 4 + i / 2, beats: 0.45, vel: (o.vel || 60) * (c === 'X' ? 1.25 : c === 'o' ? 0.7 : 1)});
        });
      },
      drums(lines, o = {}) {
        for (const [name, str] of Object.entries(lines))
          for (let r = 0; r < (o.repeat || 1); r++) [...str].forEach((c, i) => {
            if (c === '.') return;
            events.push({kind: 'drum', name: name === 'hat' && c === 'o' ? 'openhat' : name, t: beatTime((o.from || 0) + r * 4 + i / 2), v: c === 'X' ? 110 : c === 'o' ? 52 : 72});
          });
      },
      master(o = {}) { master = {gain: o.gain || 0, fadeOut: o.fadeOut || 0}; },
    };
    score(S, T);
    for (const e of events) if (e.kind !== 'note') e.d = e.d || {kick: 0.4, crash: 1.6, tom: 0.3, openhat: 0.3}[e.name] || 0.12;
    events.sort((a, b) => a.t - b.t);
    return {events, programs, master};
  }

  // ---- instruments ------------------------------------------------------------------------------------------
  function noiseBuffer(ctx) {
    const b = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate), d = b.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    return b;
  }
  function reverb(ctx) {
    const len = ctx.sampleRate * 2.4, ir = ctx.createBuffer(2, len, ctx.sampleRate);
    for (let c = 0; c < 2; c++) { const d = ir.getChannelData(c); for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 3); }
    const conv = ctx.createConvolver(); conv.buffer = ir;
    return conv;
  }

  function Player(score, T, total) {
    const ctx = new AudioCtx();
    const {events, programs, master} = compile(score, T);
    const noise = noiseBuffer(ctx);
    const out = ctx.createGain(); out.gain.value = 0;
    const comp = ctx.createDynamicsCompressor();
    const room = reverb(ctx), roomIn = ctx.createGain(); roomIn.gain.value = 0.5;
    roomIn.connect(room).connect(out);
    const meter = ctx.createAnalyser(); meter.fftSize = 2048;
    out.connect(comp).connect(ctx.destination);
    comp.connect(meter);
    let scheduled = 0;
    const live = new Set();
    // Film time keeps counting across loops here (laps), so scheduling never has to think about the wrap.
    let rate = 1, from = null, prev = null, laps = 0;

    function bus(p) {
      const pr = programs[p] || {}, g = ctx.createGain(); g.gain.value = db(pr.gain);
      let node = g;
      if (pr.pan && ctx.createStereoPanner) { const s = ctx.createStereoPanner(); s.pan.value = pr.pan; g.connect(s); node = s; }
      node.connect(out);
      if (pr.rev) { const r = ctx.createGain(); r.gain.value = pr.rev; g.connect(r).connect(roomIn); }
      return g;
    }
    function env(g, at, peak, attack, hold, release) {
      g.gain.setValueAtTime(0.0001, at);
      g.gain.linearRampToValueAtTime(peak, at + attack);
      g.gain.setValueAtTime(peak, at + attack + Math.max(0, hold));
      g.gain.exponentialRampToValueAtTime(0.0001, at + attack + Math.max(0, hold) + release);
      return at + attack + Math.max(0, hold) + release;
    }
    function osc(type, f, at, end, dest, detune = 0) {
      const o = ctx.createOscillator(); o.type = type; o.frequency.setValueAtTime(f, at); o.detune.value = detune;
      o.connect(dest); o.start(at); o.stop(end + 0.05); track(o, end); return o;
    }
    function noiseSrc(at, end, dest) {
      const s = ctx.createBufferSource(); s.buffer = noise; s.loop = true;
      s.connect(dest); s.start(at, Math.random()); s.stop(end + 0.05); track(s, end); return s;
    }
    function track(node, end) { live.add(node); node.onended = () => live.delete(node); node._end = end; }
    function filter(type, f, q = 0.7) { const b = ctx.createBiquadFilter(); b.type = type; b.frequency.value = f; b.Q.value = q; return b; }

    // late = how far into the note we already are (sound turned on mid-note): start softly where it would be.
    function note(e, at, late, dur) {
      const pr = programs[e.p] || {inst: 'ep'}, f = hz(e.m), v = level(e.v) * 0.5, dest = bus(e.p), g = ctx.createGain();
      g.connect(dest);
      const soft = late > 0 ? 0.4 : 0;
      let end;
      switch (pr.inst) {
        case 'pad': {
          const lp = filter('lowpass', 900); lp.connect(g);
          end = env(g, at, v * 0.55, Math.max(soft, Math.min(0.8, dur * 0.3)), dur - 0.6, 1.4);
          osc('sawtooth', f, at, end, lp, -7); osc('sawtooth', f, at, end, lp, 7);
          break;
        }
        case 'bass': {
          const lp = filter('lowpass', 380); lp.connect(g);
          end = env(g, at, v * 0.9, Math.max(soft, 0.01), dur * 0.6, Math.max(0.2, dur * 0.5));
          osc('triangle', f, at, end, lp); osc('sine', f, at, end, lp);
          break;
        }
        case 'vibes':
          end = env(g, at, v * 0.5, Math.max(soft, 0.005), 0, 1.6);
          osc('sine', f, at, end, g); osc('sine', f * 4, at, at + 0.4, g);
          break;
        case 'marimba':
          end = env(g, at, v * 0.6, Math.max(soft, 0.003), 0, 0.35);
          osc('sine', f, at, end, g); osc('sine', f * 3.9, at, at + 0.12, g);
          break;
        default:   // 'ep': soft electric piano
          end = env(g, at, v * 0.4, Math.max(soft, 0.01), Math.min(dur, 1) * 0.3, Math.max(0.6, dur * 0.6));
          osc('sine', f, at, end, g); osc('triangle', f * 2, at, end, g, 3);
      }
    }
    function drum(e, at) {
      const v = level(e.v), g = ctx.createGain(); g.connect(out);
      const sweep = (f0, f1, len, amp, type = 'sine') => {
        const o = osc(type, f0, at, env(g, at, amp, 0.002, 0, len), g);
        o.frequency.exponentialRampToValueAtTime(f1, at + len);
      };
      switch (e.name) {
        case 'kick': sweep(130, 42, 0.38, v * 0.95); break;
        case 'tom': sweep(210, 95, 0.28, v * 0.55); break;
        case 'hat': case 'openhat': {
          const hp = filter('highpass', 7500); hp.connect(g);
          noiseSrc(at, env(g, at, v * 0.18, 0.001, 0, e.name === 'hat' ? 0.05 : 0.28), hp); break;
        }
        case 'sidestick': {
          const bp = filter('bandpass', 1900, 3); bp.connect(g);
          noiseSrc(at, env(g, at, v * 0.4, 0.001, 0, 0.06), bp); break;
        }
        case 'crash': {
          const hp = filter('highpass', 4200); hp.connect(g);
          noiseSrc(at, env(g, at, v * 0.25, 0.002, 0, 1.6), hp); break;
        }
      }
    }
    function fx(e, at) {
      const v = level(e.v), g = ctx.createGain(); g.connect(out);
      const tone = (f, len, amp, type = 'sine') => osc(type, f, at, env(g, at, amp, 0.002, 0, len), g);
      switch (e.name) {
        case 'tick': tone(2400, 0.03, v * 0.12, 'square'); break;
        case 'click': tone(1300, 0.05, v * 0.25, 'triangle'); break;
        case 'pop': { const o = tone(620 * Math.pow(2, e.pitch / 12), 0.12, v * 0.35); o.frequency.exponentialRampToValueAtTime(380 * Math.pow(2, e.pitch / 12), at + 0.1); break; }
        case 'ding': tone(1760, 1.1, v * 0.25); break;
        case 'chime': tone(1318.5, 1.5, v * 0.2); tone(1975.5, 1.2, v * 0.14); break;
        case 'thud': { const o = tone(70, 0.6, v * 0.8); o.frequency.exponentialRampToValueAtTime(38, at + 0.5); break; }
        case 'whoosh': case 'revswell': case 'roll': {
          const bp = filter(e.name === 'revswell' ? 'lowpass' : 'bandpass', 400, e.name === 'whoosh' ? 1.4 : 0.8); bp.connect(g);
          const len = e.d;
          g.gain.setValueAtTime(0.0001, at);
          g.gain.linearRampToValueAtTime(v * (e.name === 'roll' ? 0.18 : 0.3), at + len * (e.name === 'whoosh' ? 0.6 : 0.95));
          g.gain.exponentialRampToValueAtTime(0.0001, at + len + 0.15);
          bp.frequency.exponentialRampToValueAtTime(e.name === 'revswell' ? 5000 : 2600, at + len);
          noiseSrc(at, at + len + 0.15, bp);
          break;
        }
      }
    }

    function schedule(e, filmNow, nowCtx) {
      const late = Math.max(0, filmNow - e.t);
      const at = nowCtx + Math.max(0, e.t - filmNow) / rate;
      const dur = Math.max(0.05, (e.d - late) / rate);
      scheduled++;
      if (e.kind === 'note') note(e, at, late, dur);
      else if (late > 0.05) return;               // a hit that already happened stays in the past
      else if (e.kind === 'drum') drum(e, at);
      else fx(e, at);
    }
    // Everything sounding at film time f (sound turned on, film resumed or jumped): long notes join softly.
    function catchUp(f, nowCtx) {
      for (const e of events) if (e.kind === 'note' && e.t < f && e.t + e.d > f + 0.3) schedule(e, f, nowCtx);
    }

    return {
      // Called from the film's clock: f = film seconds, r = playback rate.
      sync(f, r) {
        rate = r;
        const now = ctx.currentTime;
        if (prev != null && f < prev - total / 2) laps++;
        prev = f;
        const F = f + laps * total;
        if (from == null) { catchUp(f, now); from = F; this.level(1); }
        const to = F + LOOKAHEAD * rate;
        for (let k = Math.floor(from / total); k <= Math.floor(to / total); k++)   // this pass, and the next one's opening
          for (const e of events) {
            const abs = e.t + k * total;
            if (abs >= from && abs < to) schedule({...e, t: abs}, F, now);
          }
        from = to;
        // fade at the loop seam, so the end card's hit decays into the cold open instead of cutting
        const left = total - f;
        out.gain.setTargetAtTime(left < master.fadeOut ? masterGain(master.gain) * Math.max(0.15, left / master.fadeOut) : masterGain(master.gain), now, 0.3);
      },
      level(on) { out.gain.cancelScheduledValues(ctx.currentTime); out.gain.setTargetAtTime(on ? masterGain(master.gain) : 0.0001, ctx.currentTime, on ? 0.25 : 0.08); },
      // Film paused or hidden: fade out and drop what's scheduled; the next sync picks up where the film is.
      hush() {
        this.level(0);
        const at = ctx.currentTime + 0.4;
        for (const n of live) { try { n.stop(at); } catch (e) { /* already stopped */ } }
        live.clear();
        from = null;
      },
      resume() { return ctx.state === 'suspended' ? ctx.resume() : Promise.resolve(); },
      close() { this.hush(); setTimeout(() => ctx.close(), 600); },
      // For checks: how many events were played, the context's state and the output level right now (RMS).
      stats() {
        const d = new Float32Array(meter.fftSize); meter.getFloatTimeDomainData(d);
        return {scheduled, state: ctx.state, rms: Math.sqrt(d.reduce((s, x) => s + x * x, 0) / d.length)};
      },
    };
  }

  window.AC = Object.assign(window.AC || {}, {heroFilmAudio: {Player, compile}});
})();
