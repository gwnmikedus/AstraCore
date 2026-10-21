const { seg, eo, ei, eio, lerp } = kit;
const SIG_LINE = 'Opening pi_setup_v7_FINAL.xlsx';
kit.scene('signal', {
  init(kit) {
    kit.stage.append(kit.h('<div class="ground bars">' +
      '<canvas class="sky signal-sky" width="1920" height="1080"></canvas>' +
      '<div class="layer signal-cam">' +
      '<div class="words" style="left:220px;top:360px;width:1500px;gap:26px">' +
      '<p class="mono muted signal-eyebrow" style="font-size:22px"><span class="sq" style="margin-right:16px"></span>Planetary Industry · setup</p>' +
      '<p class="mono hot signal-typed" style="font-size:46px;letter-spacing:.08em;text-transform:none"></p>' +
      '<div style="display:flex;flex-direction:column;gap:12px;margin-top:22px">' +
      '<p class="mono muted signal-r" style="font-size:22px;margin:0">Tab 3 · which planets?</p>' +
      '<p class="mono muted signal-r" style="font-size:22px;margin:0">Tab 7 · P2 or P3?</p>' +
      '<p class="mono muted signal-r" style="font-size:22px;margin:0">Tab 12 · where was that template?</p>' +
      '<p class="mono signal-r" style="font-size:22px;margin:0;color:#ff4d6d">Tab 14 · #REF!</p></div></div></div>' +
      '<div class="vignette"></div><div class="grain signal-grain"></div></div>'));
    const q = (s) => kit.stage.querySelector(s);
    this.T0 = kit.start;
    this.cam = q('.signal-cam').style;
    this.cam.transformOrigin = '700px 520px';
    this.typedEl = q('.signal-typed');
    this.eyebrow = q('.signal-eyebrow').style;
    this.rows = [...kit.stage.querySelectorAll('.signal-r')].map((n) => n.style);
    this.grain = q('.signal-grain').style;
    this.typed = kit.typist(SIG_LINE, -0.9, 22);
    this.ctx = q('.signal-sky').getContext('2d');
  },
  render(t) {
    window.SPACE.draw(this.ctx, this.T0 + t);
    const out = ei(seg(t, 2.85, 3.5));
    this.cam.transform = 'scale(' + (lerp(1, 1.05, eio(seg(t, -0.5, 2.9))) * lerp(1, 2.4, out)) + ')';
    this.cam.opacity = 1 - out;
    this.eyebrow.opacity = 0.55 + 0.45 * eo(seg(t, -0.6, 0.2));
    const shown = this.typed.at(t);
    this.typedEl.textContent = shown + (Math.floor(t / 0.4) % 2 === 0 ? '█' : ' ');
    this.rows.forEach((st, i) => {
      const p = eo(seg(t, 0.75 + i * 0.4, 1.15 + i * 0.4));
      st.opacity = p;
      st.transform = 'translateX(' + lerp(26, 0, p) + 'px)';
    });
    window.UI.grain(this.grain, t);
  },
});
