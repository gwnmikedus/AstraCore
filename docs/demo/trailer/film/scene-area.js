const { seg, eo, ei, eio, lerp, rng, TextFx } = kit;
const AR_H = [1100, 560];
kit.scene('area', {
  init(kit) {
    const r = rng(23);
    const sys = [AR_H];
    while (sys.length < 30) { const p = [300 + r() * 1500, 220 + r() * 680]; if (sys.every((s) => Math.hypot(s[0] - p[0], s[1] - p[1]) > 120)) sys.push(p); }
    const near = sys.map((s, i) => i).sort((a, b) => Math.hypot(sys[a][0] - AR_H[0], sys[a][1] - AR_H[1]) - Math.hypot(sys[b][0] - AR_H[0], sys[b][1] - AR_H[1]));
    this.pick = near.slice(1, 3);
    const edges = [];
    sys.forEach((s, i) => { const o = sys.map((u, j) => [j, Math.hypot(u[0] - s[0], u[1] - s[1])]).filter((x) => x[0] !== i).sort((a, b) => a[1] - b[1]); o.slice(0, 2).forEach(([j]) => { if (i < j) edges.push([i, j]); }); });
    let svg = '<svg viewBox="0 0 1920 1080" style="position:absolute;inset:0;width:100%;height:100%;overflow:visible">';
    svg += '<circle class="area-ring" cx="' + AR_H[0] + '" cy="' + AR_H[1] + '" r="260" fill="rgba(255,106,26,0.07)" stroke="#ff6a1a" stroke-width="2" stroke-dasharray="10 10"/>';
    edges.forEach(([a, b]) => { svg += '<line class="area-edge" x1="' + sys[a][0] + '" y1="' + sys[a][1] + '" x2="' + sys[b][0] + '" y2="' + sys[b][1] + '" stroke="#646a72" stroke-width="2"/>'; });
    sys.forEach((s, i) => { const hot = i === 0 || this.pick.includes(i); svg += '<rect class="area-sys" data-hot="' + (hot ? 1 : 0) + '" x="' + (s[0] - 7) + '" y="' + (s[1] - 7) + '" width="14" height="14" fill="#a19d94"/>'; });
    svg += '</svg>';
    const lab = (x, y, txt, cls) => '<p class="mono ' + cls + '" style="position:absolute;left:' + x + 'px;top:' + y + 'px;margin:0;font-size:20px;white-space:nowrap">' + txt + '</p>';
    kit.stage.append(kit.h('<div class="ground bars" style="perspective:1400px">' +
      '<canvas class="sky area-sky" width="1920" height="1080"></canvas>' +
      '<div class="layer area-map" style="transform-origin:' + AR_H[0] + 'px ' + AR_H[1] + 'px">' + svg +
      lab(AR_H[0] + 24, AR_H[1] - 40, 'Demo Harbour · drop-off', 'hot area-lab') +
      lab(AR_H[0] - 250, AR_H[1] + 280, 'Demo Coast · ≤ 3 jumps', 'muted area-lab') + '</div>' +
      '<div class="words area-words" style="left:210px;top:160px;width:900px;gap:16px"><h2 class="line area-line" style="font-size:88px">Planned around where you fly</h2>' +
      '<p class="sub area-sub">Systems, planets and drop-off, found from your characters</p></div>' +
      '<div class="area-seed" style="position:absolute;left:940px;top:520px;width:40px;height:40px;background:var(--main)"></div>' +
      '<div class="vignette"></div><div class="grain area-grain"></div></div>'));
    const q = (s) => kit.stage.querySelector(s);
    this.T0 = kit.start;
    this.ctx = q('.area-sky').getContext('2d');
    this.map = q('.area-map').style;
    this.ring = q('.area-ring');
    this.edges = [...kit.stage.querySelectorAll('.area-edge')];
    this.sys = [...kit.stage.querySelectorAll('.area-sys')];
    this.labs = [...kit.stage.querySelectorAll('.area-lab')].map((n) => n.style);
    this.line = q('.area-line');
    this.words = q('.area-words').style;
    this.sub = q('.area-sub').style;
    this.seed = q('.area-seed').style;
    this.grain = q('.area-grain').style;
  },
  render(t) {
    window.SPACE.draw(this.ctx, this.T0 + t);
    const arrive = eo(seg(t, -0.1, 1.2));
    const dive = ei(seg(t, 4.1, 5.0));
    const tilt = lerp(lerp(62, 48, arrive), 0, dive);
    const s = lerp(0.7, 1.0, arrive) * (1 + 0.02 * t) * lerp(1, 9, dive);
    const dx = lerp(-200 + 30 * t, 960 - AR_H[0], dive), dy = lerp(-40, 540 - AR_H[1], dive);
    this.map.transform = 'translate(' + dx + 'px,' + dy + 'px) rotateX(' + tilt + 'deg) scale(' + s + ')';
    this.map.opacity = eo(seg(t, -0.1, 0.5)) * (1 - eo(seg(t, 4.6, 4.95)));
    this.edges.forEach((e, i) => { e.style.opacity = (0.6 * eo(seg(t, 0.1 + (i % 12) * 0.05, 0.6 + (i % 12) * 0.05))).toFixed(3); });
    const lit = eo(seg(t, 1.5, 2.1));
    this.sys.forEach((n, i) => { const hot = n.getAttribute('data-hot') === '1'; const on = hot && t >= 1.5 + (i === 0 ? 0 : 0.25 * this.pick.indexOf(i) + 0.25); n.setAttribute('fill', on ? '#ff6a1a' : '#a19d94'); });
    this.ring.style.opacity = lit.toFixed(3);
    this.ring.style.transform = 'scale(' + lerp(0.6, 1, lit) + ')';
    this.ring.style.transformOrigin = AR_H[0] + 'px ' + AR_H[1] + 'px';
    this.labs.forEach((st, i) => { st.opacity = eo(seg(t, 1.7 + i * 0.3, 2.1 + i * 0.3)); });
    if (t < 3.9) TextFx.fadeFromRight(this.line, t, 0.3, { stagger: 0.1, dur: 0.5, dx: 28 });
    else TextFx.fadeOutLeft(this.line, t, 3.9);
    this.sub.opacity = eo(seg(t, 1.0, 1.5)) * (1 - eo(seg(t, 3.9, 4.2)));
    this.seed.opacity = eo(seg(t, 4.55, 4.85));
    window.UI.grain(this.grain, t);
  },
});
