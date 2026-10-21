const { seg, eo, ei, eio, lerp } = kit;
const SCR_ROWS = [
  ['#ff4d6d', 'Restart extractors · Demo Harbour III', 'Now'],
  ['#f2c230', 'Pick up 4,200 m³ · Demo Harbour V', 'in 3h'],
  ['#a19d94', 'Restock factory · Demo Pilot Aurora', 'tomorrow'],
];
kit.scene('screen', {
  init(kit) {
    const rows = SCR_ROWS.map((r, i) => '<li class="screen-row" style="display:flex;align-items:center;gap:22px;padding:22px 0;border-top:' + (i ? '1px solid #2a2e33' : '0') + '">' +
      '<span style="width:16px;height:16px;flex:none;background:' + r[0] + '"></span>' +
      '<span style="flex:1;font-size:30px;color:#ece8df">' + r[1] + '</span>' +
      '<span style="font-family:var(--mono, ui-monospace, monospace);font-size:24px;color:' + r[0] + '">' + r[2] + '</span></li>').join('');
    kit.stage.append(kit.h('<div class="ground bars" style="perspective:1600px">' +
      '<canvas class="sky screen-sky" width="1920" height="1080"></canvas>' +
      '<div class="screen-rig" style="position:absolute;left:390px;top:290px;width:1140px;height:500px;transform-origin:570px 250px">' +
      '<div class="panel screen-panel" style="inset:0;padding:44px 56px">' +
      '<div style="display:flex;justify-content:space-between;align-items:baseline">' +
      '<h3 style="margin:0;font-family:var(--display, var(--sans, system-ui, sans-serif));font-weight:600;font-size:44px">Next up</h3>' +
      '<span class="mono muted" style="font-size:18px">Example data</span></div>' +
      '<ul style="list-style:none;margin:22px 0 0;padding:0">' + rows + '</ul></div>' +
      '<div class="screen-mark" style="position:absolute;left:30px;top:108px;width:1080px;height:84px;border:3px solid var(--main)"></div>' +
      '<p class="mono hot screen-tag" style="position:absolute;right:30px;top:-46px;margin:0;font-size:20px">▸ Next action</p></div>' +
      '<div class="screen-frame" style="position:absolute;border:3px solid var(--main);box-sizing:border-box"></div>' +
      '<div class="screen-seed" style="position:absolute;background:var(--main)"></div>' +
      '<div class="vignette"></div><div class="grain screen-grain"></div></div>'));
    const q = (s) => kit.stage.querySelector(s);
    this.T0 = kit.start;
    this.ctx = q('.screen-sky').getContext('2d');
    for (const k of ['rig', 'panel', 'mark', 'tag', 'frame', 'seed', 'grain']) this[k] = q('.screen-' + k).style;
    this.rows = [...kit.stage.querySelectorAll('.screen-row')].map((n) => n.style);
  },
  box(st, cx, cy, w, h) { st.left = (cx - w / 2) + 'px'; st.top = (cy - h / 2) + 'px'; st.width = w + 'px'; st.height = h + 'px'; },
  render(T) {
    const t = T <= 1.4 ? T : T <= 3.5 ? 1.4 + (T - 1.4) * 0.1 / 2.1 : 1.5 + (T - 3.5);
    const c = this.ctx;
    window.SPACE.draw(c, this.T0 + T);
    const back = eio(seg(t, -0.05, 1.4));
    const R = lerp(3300, 1150, back);
    const u = window.SPACE.nodeAt(2, 0.3 + t * 0.12);
    const ncx = lerp(960, 240, back), ncy = lerp(540, 1380, back);
    window.SPACE.planet(c, ncx - u[0] * R, ncy - u[1] * R, R, 0.3 + t * 0.12, () => 1, () => 1, t);
    c.fillStyle = 'rgba(11,12,13,' + (0.55 * back).toFixed(3) + ')';
    c.fillRect(0, 0, 1920, 1080);
    const g = eio(seg(t, 0, 0.5));
    this.box(this.frame, 960, 540, lerp(110, 1140, g), lerp(110, 500, g));
    this.frame.opacity = 1 - eo(seg(t, 0.55, 0.85));
    const seedIn = 1 - eo(seg(t, 0, 0.25));
    const exit = ei(seg(t, 1.5, 2.0));
    const ss = seedIn > 0 ? lerp(40, 110, seedIn) : 38;
    this.box(this.seed, lerp(960, 575, exit > 0 ? 1 : 0), lerp(540, 455, exit > 0 ? 1 : 0), ss, ss);
    this.seed.opacity = Math.max(seedIn, eo(seg(t, 1.8, 2.0)));
    const sway = Math.sin(T * 1.1) * 3 - 0.6 * T;
    this.rig.transform = 'translate(' + lerp(0, -385, exit) + 'px,' + lerp(0, -85, exit) + 'px) rotateY(' + (sway - 4 * (1 - g)) + 'deg) rotateX(' + lerp(6, 2, g) + 'deg) scale(' + (lerp(1, 1.04, eo(seg(t, 0.4, 1.5))) * lerp(1, 0.04, exit)) + ')';
    this.rig.opacity = eo(seg(t, 0.25, 0.6)) * (1 - eo(seg(t, 1.75, 1.95)));
    this.rows.forEach((st, i) => { const p = eo(seg(t, 0.45 + i * 0.12, 0.8 + i * 0.12)); st.opacity = p; st.transform = 'translateY(' + lerp(14, 0, p) + 'px)'; });
    const m = eo(seg(t, 0.95, 1.25));
    this.mark.opacity = m;
    this.mark.transform = 'scale(' + lerp(1.06, 1, m) + ')';
    this.tag.opacity = eo(seg(t, 1.05, 1.35));
    window.UI.grain(this.grain, T);
  },
});
