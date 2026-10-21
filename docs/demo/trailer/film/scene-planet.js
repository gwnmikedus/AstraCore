const { seg, eo, ei, eio, lerp, TextFx } = kit;
kit.scene('planet', {
  init(kit) {
    kit.stage.append(kit.h('<div class="ground bars">' +
      '<canvas class="sky planet-sky" width="1920" height="1080"></canvas>' +
      '<div class="words planet-words" style="left:210px;top:420px;width:820px">' +
      '<h2 class="line" style="font-size:110px">Then it keeps watch</h2>' +
      '<p class="mono muted planet-sub" style="font-size:22px">Restarts · pickups · sales, in order</p></div>' +
      '<div class="vignette"></div><div class="grain planet-grain"></div></div>'));
    const q = (s) => kit.stage.querySelector(s);
    this.T0 = kit.start;
    this.line = q('.line');
    this.words = q('.planet-words').style;
    this.sub = q('.planet-sub').style;
    this.grain = q('.planet-grain').style;
    this.ctx = q('.planet-sky').getContext('2d');
  },
  render(t) {
    const c = this.ctx;
    window.SPACE.draw(c, this.T0 + t);
    const rot = t * 0.1 - 0.1;
    const a = eo(seg(t, -0.1, 1.8));
    const R0 = lerp(60, 470, a) * (1 + 0.015 * t);
    const cx0 = lerp(1080, 1360, a), cy0 = lerp(470, 580, a);
    const p = ei(seg(t, 3.25, 4.0));
    const R = R0 * lerp(1, 7, p);
    const u = window.SPACE.nodeAt(2, rot);
    const cx = lerp(cx0, 960 - u[0] * R, p), cy = lerp(cy0, 540 - u[1] * R, p);
    window.SPACE.planet(c, cx, cy, R, rot,
      (i) => eio(seg(t, 1.0 + i * 0.16, 1.5 + i * 0.16)),
      (i) => eo(seg(t, 0.8 + i * 0.14, 1.1 + i * 0.14)), t);
    if (t < 3.1) TextFx.fadeFromRight(this.line, t, 0.5, { stagger: 0.12, dur: 0.55, dx: 30 });
    else TextFx.fadeOutLeft(this.line, t, 3.1);
    this.sub.opacity = eo(seg(t, 1.4, 1.8)) * (1 - eo(seg(t, 3.1, 3.4)));
    this.words.transform = 'translateX(' + (-12 * t) + 'px)';
    window.UI.grain(this.grain, t);
  },
});
