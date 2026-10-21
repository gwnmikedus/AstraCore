const { seg, eo, ei, eio, lerp, TextFx } = kit;
const QS = [
  ['Step 2 of 5', 'How often can you log in to restart extractors?', ['Every day', 'Every 2 days', 'Every 3 days', 'Once a week'], 2],
  ['Step 3 of 5', 'How far are you willing to fly?', ['One system', 'A few nearby systems', 'Wherever pays most'], 1],
  ['Step 4 of 5', 'How far should your planets process?', ['Only P1 (miners)', 'Up to P2', 'Up to P3', 'Up to P4'], 1],
  ['Step 5 of 5', 'How do you want to turn products into ISK?', ['Sell in Delve only', 'Also courier to Jita / Amarr', 'Haul to Jita / Amarr myself'], 1],
];
kit.scene('questions', {
  init(kit) {
    const blocks = QS.map((q) => '<div class="questions-q" style="position:absolute;left:60px;right:60px;top:150px">' +
      '<p class="mono hot" style="margin:46px 0 0;font-size:18px">' + q[0] + '</p>' +
      '<h3 style="margin:12px 0 0;font-family:var(--display, var(--sans, system-ui, sans-serif));font-weight:600;font-size:64px;line-height:1.05">' + q[1] + '</h3>' +
      '<div style="display:flex;flex-wrap:wrap;gap:20px;margin-top:56px">' + q[2].map((o) => '<span class="questions-opt" style="padding:24px 30px;font-size:28px;background:var(--ground);box-shadow:inset 0 0 0 1px #2a2e33">' + o + '</span>').join('') + '</div></div>').join('');
    kit.stage.append(kit.h('<div class="ground bars" style="perspective:1600px">' +
      '<canvas class="sky questions-sky" width="1920" height="1080"></canvas>' +
      '<div class="layer questions-cam" style="transform-origin:700px 420px">' +
      '<div class="panel questions-panel" style="left:210px;top:160px;width:1500px;height:760px;padding:46px 60px;box-sizing:border-box;transform-origin:50% 0">' +
      window.UI.stepper('questions') + blocks + '</div></div>' +
      '<div class="words" style="left:0;right:0;top:760px;align-items:center;text-align:center"><h2 class="line questions-line" style="font-size:104px">Five questions. No spreadsheet.</h2></div>' +
      '<div class="vignette"></div><div class="grain questions-grain"></div></div>'));
    const q = (s) => kit.stage.querySelector(s);
    this.kit = kit;
    this.T0 = kit.start;
    this.ctx = q('.questions-sky').getContext('2d');
    this.cam = q('.questions-cam').style;
    this.panel = q('.questions-panel').style;
    this.blocks = [...kit.stage.querySelectorAll('.questions-q')];
    this.line = q('.questions-line');
    this.grain = q('.questions-grain').style;
  },
  render(t) {
    window.SPACE.draw(this.ctx, this.T0 + t);
    const W = 1.15;
    this.blocks.forEach((b, i) => {
      const a = i * W - 0.15, e = (i + 1) * W - 0.15;
      // one question at a time: the next only comes in once this one has gone
      const pin = i === 0 ? 1 : eo(seg(t, a + 0.02, a + 0.36));
      const pout = i === 3 ? 0 : ei(seg(t, e - 0.3, e - 0.02));
      b.style.opacity = (pin * (1 - pout)).toFixed(3);
      b.style.transform = 'translateY(' + (lerp(40, 0, pin) - 40 * pout) + 'px)';
      const pick = t >= a + 0.65;
      [...b.querySelectorAll('.questions-opt')].forEach((o, j) => {
        const on = pick && j === QS[i][3];
        o.style.background = on ? 'color-mix(in srgb, var(--main) 22%, var(--ground))' : 'var(--ground)';
        o.style.boxShadow = 'inset 0 0 0 ' + (on ? 2 : 1) + 'px ' + (on ? 'var(--main)' : '#2a2e33');
        o.style.transform = on ? 'scale(' + lerp(0.96, 1, eo(seg(t, a + 0.65, a + 0.85))) + ')' : 'none';
      });
    });
    let k = 1;
    for (let i = 1; i < 4; i++) k += eio(seg(t, i * W - 0.25, i * W + 0.05));
    k += eio(seg(t, 4 * W - 0.25, 4 * W + 0.05));
    window.UI.setStep(this.kit, 'questions', k);
    const back = eio(seg(t, 4.75, 5.9));
    this.cam.transform = 'scale(' + (1.06 + 0.01 * t) + ')';
    this.panel.transform = 'translateY(' + lerp(0, -120, back) + 'px) rotateX(' + lerp(0, 58, back) + 'deg) scale(' + lerp(1, 0.55, back) + ')';
    this.panel.opacity = 1 - eo(seg(t, 5.5, 6.0));
    TextFx.fadeFromRight(this.line, t, 4.85, { stagger: 0.11, dur: 0.45, dx: 28 });
    window.UI.grain(this.grain, t);
  },
});
