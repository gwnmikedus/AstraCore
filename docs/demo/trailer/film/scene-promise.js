const { seg, eo, ei, eio, lerp, TextFx } = kit;
kit.scene('promise', {
  init(kit) {
    kit.stage.append(kit.h('<div class="ground bars">' +
      '<canvas class="sky promise-sky" width="1920" height="1080"></canvas>' +
      '<div class="layer promise-cam" style="transform-origin:960px 500px">' +
      '<div class="words" style="left:0;right:0;top:400px;align-items:center;text-align:center"><h2 class="line" style="font-size:116px">What if setup was the fun part?</h2></div></div>' +
      '<div class="promise-bar" style="position:absolute;background:var(--main)"></div>' +
      '<div class="vignette"></div><div class="grain promise-grain"></div></div>'));
    const q = (s) => kit.stage.querySelector(s);
    this.T0 = kit.start;
    this.ctx = q('.promise-sky').getContext('2d');
    this.line = q('.line');
    this.cam = q('.promise-cam').style;
    this.bar = q('.promise-bar').style;
    this.grain = q('.promise-grain').style;
  },
  render(t) {
    window.SPACE.draw(this.ctx, this.T0 + t);
    const move = eio(seg(t, 0.1, 0.6));
    const grow = eio(seg(t, 0.5, 1.3));
    const back = ei(seg(t, 2.75, 3.3));
    const w = lerp(lerp(40, 14, move), 980, grow * (1 - back)) + lerp(0, 26, back);
    const h = lerp(40, 10, Math.max(move, 0)) + lerp(0, 30, back);
    const cy = lerp(lerp(540, 575, move), 540, back);
    this.bar.left = (960 - w / 2) + 'px';
    this.bar.top = (cy - h / 2) + 'px';
    this.bar.width = w + 'px';
    this.bar.height = h + 'px';
    if (t < 2.7) TextFx.fadeFromRight(this.line, t, 0.35, { stagger: 0.09, dur: 0.5, dx: 30 });
    else TextFx.fadeOutLeft(this.line, t, 2.7);
    this.cam.transform = 'translateY(' + lerp(0, -40, eo(seg(t, 0, 0.6))) + 'px) scale(' + (1 + 0.015 * t) + ')';
    window.UI.grain(this.grain, t);
  },
});
