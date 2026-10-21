const { seg, eo, ei, eio, eob, lerp, TextFx } = kit;
kit.scene('meet', {
  init(kit) {
    kit.stage.append(kit.h('<div class="ground bars">' +
      '<canvas class="sky meet-sky" width="1920" height="1080"></canvas>' +
      '<div class="meet-flare" style="position:absolute;left:560px;top:180px;width:800px;height:600px;background:radial-gradient(closest-side, color-mix(in srgb, var(--main) 26%, transparent), transparent)"></div>' +
      '<div class="layer meet-cam" style="transform-origin:960px 470px">' +
      '<div class="meet-mark" style="position:absolute;left:870px;top:250px;width:180px;height:180px"><svg viewBox="0 0 64 64" style="width:100%;height:100%"><path d="M6 6H44L58 20V58H20L6 44Z" fill="none" stroke="#ece8df" stroke-width="5" stroke-linejoin="miter"/></svg></div>' +
      '<div class="meet-core" style="position:absolute;background:var(--main)"></div>' +
      '<div class="words" style="left:0;right:0;top:500px;align-items:center;text-align:center">' +
      '<h2 class="line meet-line" style="font-size:120px">Meet AstraCore PI</h2>' +
      '<p class="sub meet-sub" style="font-size:40px">Guided Planetary Industry setup for EVE pilots</p></div></div>' +
      '<div class="vignette"></div><div class="grain meet-grain"></div></div>'));
    const q = (s) => kit.stage.querySelector(s);
    this.T0 = kit.start;
    this.ctx = q('.meet-sky').getContext('2d');
    for (const k of ['flare', 'cam', 'mark', 'core', 'sub', 'grain']) this[k] = q('.meet-' + k).style;
    this.line = q('.meet-line');
  },
  render(t) {
    window.SPACE.draw(this.ctx, this.T0 + t);
    const rise = eio(seg(t, 0.05, 0.6));
    const cs = lerp(40, 45, rise), ccx = 960, ccy = lerp(540, 340, rise);
    this.core.left = (ccx - cs / 2) + 'px'; this.core.top = (ccy - cs / 2) + 'px'; this.core.width = cs + 'px'; this.core.height = cs + 'px';
    const m = seg(t, 0.4, 0.95);
    this.mark.transform = 'scale(' + (m <= 0 ? 0.2 : lerp(0.2, 1, eob(m, 1.7))) + ') rotate(' + lerp(-90, 0, eo(m)) + 'deg)';
    this.mark.opacity = eo(seg(t, 0.4, 0.6));
    this.flare.opacity = eo(seg(t, 0.5, 0.9)) * 0.9;
    TextFx.fadeFromRight(this.line, t, 0.8, { stagger: 0.12, dur: 0.5, dx: 28 });
    this.sub.opacity = eo(seg(t, 1.35, 1.8));
    const out = ei(seg(t, 2.45, 3.0));
    this.cam.transform = 'scale(' + ((1 + 0.02 * t) * lerp(1, 3.2, out)) + ')';
    this.cam.opacity = 1 - out;
    this.flare.opacity = (eo(seg(t, 0.5, 0.9)) * 0.9 * (1 - out)).toFixed(3);
    window.UI.grain(this.grain, t);
  },
});
