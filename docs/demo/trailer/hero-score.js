// The home hero's score: a trailer cue in D minor, built for the film's scenes (times are film seconds; the hero plays
// some scenes slower and the player stretches the score with them). No voice-over: the music carries it.
// Cold open in the dark, pressure in the spreadsheet, hope at the promise, a hit on the name, a driving build under
// the guided setup and the plan, space to breathe at the planet, one last climb and the resolution on the end card.
kit.score(function (S, T) {
  S.tempo(132, { t0: T.pilots });
  S.program('str', 'strings', { rev: 0.55, gain: -2 });
  S.program('hi', 'strings', { rev: 0.85, gain: -6, pan: 0.15 });
  S.program('low', 'sub', { gain: -1 });
  S.program('ost', 'pluck', { rev: 0.25, gain: -2, pan: -0.1 });
  S.program('horn', 'brass', { rev: 0.5, gain: -4 });
  S.program('choir', 'choir', { rev: 0.9, gain: -5 });
  S.program('bell', 'vibes', { rev: 0.75, gain: -7, pan: 0.2 });
  const prog = [['D3', 'F3', 'A3'], ['Bb2', 'D3', 'F3'], ['F2', 'A2', 'C3'], ['C3', 'E3', 'G3']];
  const roots = ['D2', 'Bb1', 'F1', 'C2'];
  const fifths = ['A2', 'F2', 'C2', 'G2'];

  // cold open: a dark hall, a heartbeat, the typing
  S.note('low', 'D1', { t: 0, dur: 7.2, vel: 72 });
  S.chord('str', ['D2', 'A2'], { t: 0.1, dur: 7.0, vel: 48 });
  for (let i = 0; i < 10; i++) S.fx('tick', 0.02 + i * 0.045, { vel: 22 });
  S.fx('heartbeat', 0.7, { vel: 70 });
  S.fx('heartbeat', 2.0, { vel: 78 });
  S.fx('riser', T.chaos - 1.3, { dur: 1.3, vel: 62 });

  // the spreadsheet: pressure builds, then everything implodes into one point
  S.fx('impact', T.chaos, { vel: 92 });
  S.chord('str', ['D3', 'Eb3', 'A3'], { t: T.chaos + 0.4, dur: 2.7, vel: 64 });
  let k = 0;
  for (let t = T.chaos; t < T.chaos + 3.0; t += 0.25 - k * 0.0045) {
    S.note('ost', k % 4 === 3 ? 'Eb2' : 'D2', { t, dur: 0.12, vel: 50 + k * 1.4 });
    k++;
  }
  [0, 1, 1.75, 2.25, 2.6, 2.85].forEach((dt, i) => S.drum('taiko', { t: T.chaos + dt, vel: 80 + i * 8 }));
  S.fx('riser', T.chaos + 1.0, { dur: 2.05, vel: 84 });
  S.fx('braam', T.chaos + 3.05, { dur: 1.3, vel: 104 });

  // the promise: a breath of hope
  S.fx('shimmer', T.promise, { dur: 3.6, vel: 72 });
  S.chord('hi', ['F4', 'A4', 'C5'], { t: T.promise + 0.1, dur: 3.2, vel: 46 });
  S.chord('choir', ['F3', 'C4'], { t: T.promise + 0.2, dur: 3.2, vel: 46 });
  S.note('bell', 'A5', { t: T.promise + 0.35, dur: 1.4, vel: 42 });
  S.note('bell', 'C6', { t: T.promise + 1.2, dur: 1.6, vel: 36 });
  S.fx('riser', T.meet - 1.4, { dur: 1.8, vel: 88 });

  // meet AstraCore: the first big hit
  S.fx('impact', T.meet + 0.4, { vel: 118 });
  S.fx('braam', T.meet + 0.4, { dur: 2.2, vel: 96 });
  S.drum('crash', { t: T.meet + 0.4, vel: 92 });
  S.drum('taiko', { t: T.meet + 0.4, vel: 120 });
  S.chord('str', ['D2', 'A2', 'D3', 'F3', 'A3'], { t: T.meet + 0.4, dur: 2.6, vel: 80 });
  S.note('low', 'D1', { t: T.meet + 0.4, dur: 2.6, vel: 104 });
  S.chord('horn', ['D3', 'A3', 'D4'], { t: T.meet + 0.45, dur: 1.6, vel: 74 });

  // the guided setup: a driving build, a chord a bar, growing each bar
  const groove = (from, bars, base, drums) => {
    for (let b = 0; b < bars; b++) {
      const beat = from + b * 4, j = b % 4, up = b / Math.max(1, bars - 1);
      S.chord('str', prog[j], { beat, beats: 3.9, vel: base + 18 * up });
      S.note('low', roots[j], { beat, beats: 3.9, vel: 78 + 14 * up });
      S.pattern('ost', 'XxxXxxXx', { from: beat, repeat: 1, pitch: [roots[j].replace(/\d$/, d => +d + 1), fifths[j].replace(/\d$/, d => +d + 1)], vel: 44 + 20 * up });
      S.drums(drums(b, up), { from: beat, repeat: 1 });
    }
  };
  const barsA = Math.floor(S.toBeat(T.area - 0.6) / 4);
  groove(0, barsA, 44, (b) => b < 2 ? { taiko: 'x.......' } : b < 5 ? { taiko: 'x...x...' } : { taiko: 'x...x.x.', hat: '.x.x.x.x' });
  S.chord('horn', ['F3', 'A3', 'D4'], { t: T.goal, dur: 2.2, vel: 58 });
  S.fx('click', T.goal + 3.15, { vel: 60 });
  S.fx('pop', T.goal + 4.5, { vel: 40 });
  for (let i = 0; i < 4; i++) S.fx('pop', T.questions + i * 1.15 + 0.5, { vel: 44, pitch: i * 2 });
  S.fx('riser', T.questions + 3.3, { dur: 1.55, vel: 88 });
  S.fx('impact', T.questions + 4.85, { vel: 104 });
  S.drum('crash', { t: T.questions + 4.85, vel: 80 });
  S.chord('horn', ['D3', 'A3', 'D4', 'F4'], { t: T.questions + 4.85, dur: 1.2, vel: 76 });

  // your space: the world opens up
  S.fx('boom', T.area, { vel: 92 });
  S.chord('choir', ['D3', 'A3', 'E4'], { t: T.area, dur: 5, vel: 52 });
  S.chord('hi', ['A4', 'D5', 'E5'], { t: T.area + 0.3, dur: 4.6, vel: 40 });
  S.note('low', 'D1', { t: T.area, dur: 5, vel: 72 });
  S.fx('shimmer', T.area + 1.4, { dur: 3, vel: 60 });
  S.fx('ding', T.area + 1.5, { vel: 34 });
  S.fx('riser', T.plan - 1.6, { dur: 1.6, vel: 84 });

  // the plan and the build: the full theme, horns on top
  S.fx('impact', T.plan, { vel: 108 });
  S.drum('crash', { t: T.plan, vel: 84 });
  const b0 = Math.ceil(S.toBeat(T.plan));
  const barsB = Math.ceil((S.toBeat(T.planet - 0.3) - b0) / 4);   // run right up to the planet: no gap before it
  groove(b0, barsB, 58, (b) => ({ taiko: b % 2 ? 'x.x.x.xx' : 'x...x.x.', hat: 'xxxxxxxx' }));
  ['A3', 'F3', 'C4', 'G3', 'A3', 'Bb3', 'C4', 'E4'].slice(0, barsB).forEach((n, i) => S.note('horn', n, { beat: b0 + i * 4, beats: 3.6, vel: 60 + i * 3 }));
  S.fx('click', T.plan + 5.15, { vel: 58 });
  for (let i = 0; i < 4; i++) S.fx('pop', T.build + 0.3 + i * 0.12, { vel: 46, pitch: i * 3 });
  for (let i = 0; i < 3; i++) S.fx('tick', T.build + 2.4 + i * 0.45, { vel: 58 });
  S.fx('chime', T.build + 3.4, { vel: 44 });
  for (let i = 0; i < 8; i++) S.drum('tom', { t: T.planet - 0.6 + i * 0.07, vel: 50 + i * 9 });
  S.fx('riser', T.planet - 1.6, { dur: 1.6, vel: 80 });

  // it keeps watch: breathe, the colonies light up one by one
  S.fx('boom', T.planet, { vel: 96 });
  S.chord('str', ['Bb2', 'F3', 'D4'], { t: T.planet, dur: 4.2, vel: 56 });
  S.chord('choir', ['F3', 'D4'], { t: T.planet + 0.3, dur: 4, vel: 44 });
  S.note('low', 'Bb0', { t: T.planet, dur: 4.2, vel: 82 });
  [1.0, 2.2, 3.3].forEach((dt) => S.fx('heartbeat', T.planet + dt, { vel: 62 }));
  ['A4', 'D5', 'F5', 'A5', 'Bb5', 'D6'].forEach((n, i) => S.note('bell', n, { t: T.planet + 1.0 + i * 0.16, dur: 0.8, vel: 30 + i * 4 }));

  // next action: the last climb
  S.chord('str', ['A2', 'E3', 'A3', 'C#4'], { t: T.screen, dur: 4, vel: 60 });
  S.note('low', 'A1', { t: T.screen, dur: 4, vel: 86 });
  S.fx('click', T.screen + 0.95, { vel: 55 });
  k = 0;
  for (let t = T.screen + 0.4; t < T.title - 0.15; t += Math.max(0.14, 0.55 - k * 0.06)) { S.drum('taiko', { t, vel: 70 + k * 5 }); k++; }
  S.fx('riser', T.screen + 1.2, { dur: T.title - T.screen - 1.2, vel: 96 });

  // AstraCore PI: the resolution, in D major
  S.fx('impact', T.title, { vel: 127 });
  S.fx('braam', T.title, { dur: 3.4, vel: 108 });
  S.drum('crash', { t: T.title, vel: 100 });
  S.drum('taiko', { t: T.title, vel: 127 });
  S.chord('str', ['D2', 'A2', 'D3', 'F#3', 'A3', 'D4'], { t: T.title, dur: 5, vel: 86 });
  S.chord('horn', ['D3', 'F#3', 'A3', 'D4'], { t: T.title + 0.05, dur: 3.6, vel: 80 });
  S.chord('choir', ['A3', 'D4', 'F#4'], { t: T.title + 0.2, dur: 4.8, vel: 56 });
  S.note('low', 'D1', { t: T.title, dur: 5, vel: 112 });
  S.note('bell', 'A5', { t: T.title + 1.35, dur: 2, vel: 44 });
  S.note('bell', 'D6', { t: T.title + 2.0, dur: 2.4, vel: 38 });
  S.master({ gain: -3, fadeOut: 2.0 });
});
