const { seg, eo, ei, eio, lerp, TextFx } = kit;
const PIL = [['Demo Pilot Aurora', '6', 'V', 'IV'], ['Demo Pilot Beacon', '5', 'IV', 'IV'], ['Demo Pilot Corvid', '6', 'V', 'V']];
kit.scene('pilots', {
  init(kit) {
    const kv = (k, v) => '<div style="display:flex;justify-content:space-between;padding:12px 0;border-top:1px solid #2a2e33"><span style="font-size:22px;color:#a19d94">' + k + '</span><b style="font-family:var(--mono, ui-monospace, monospace);font-weight:500;font-size:22px">' + v + '</b></div>';
    const card = (p, i) => '<div class="panel pilots-card" style="left:' + (210 + i * 520) + 'px;top:420px;width:460px;height:380px;padding:32px 34px;box-sizing:border-box">' +
      '<div style="display:flex;align-items:center;gap:20px;margin-bottom:24px">' +
      '<div style="width:64px;height:64px;flex:none;display:grid;place-items:center;box-shadow:inset 0 0 0 2px #646a72"><span class="sq" style="width:20px;height:20px"></span></div>' +
      '<div style="flex:1;min-width:0"><div style="font-family:var(--display, var(--sans, system-ui, sans-serif));font-weight:600;font-size:32px">' + p[0] + '</div>' +
      '<div style="font-size:18px;color:#a19d94">Last ESI refresh just now</div></div>' +
      '<span class="mono pilots-ok" style="font-size:16px;padding:6px 10px;box-shadow:inset 0 0 0 1px #5aa9ff;color:#5aa9ff">■ OK</span></div>' +
      kv('Colony slots', p[1]) + kv('Command Center Upgrades', p[2]) + kv('Interplanetary Consolidation', p[3]) + '</div>';
    kit.stage.append(kit.h('<div class="ground bars" style="perspective:1800px">' +
      '<canvas class="sky pilots-sky" width="1920" height="1080"></canvas>' +
      '<div class="layer pilots-cam" style="perspective:1800px">' +
      '<div class="words" style="left:210px;top:160px;width:1500px;gap:16px"><h2 class="line pilots-line">Start with your pilots</h2>' +
      '<p class="sub pilots-sub">Skills and colony slots, read from EVE for you</p></div>' +
      PIL.map(card).join('') + '</div>' +
      '<div class="vignette"></div><div class="grain pilots-grain"></div></div>'));
    const q = (s) => kit.stage.querySelector(s);
    this.T0 = kit.start;
    this.ctx = q('.pilots-sky').getContext('2d');
    this.cards = [...kit.stage.querySelectorAll('.pilots-card')].map((n) => n.style);
    this.oks = [...kit.stage.querySelectorAll('.pilots-ok')].map((n) => n.style);
    this.line = q('.pilots-line');
    this.sub = q('.pilots-sub').style;
    this.cam = q('.pilots-cam').style;
    this.grain = q('.pilots-grain').style;
  },
  render(t) {
    window.SPACE.draw(this.ctx, this.T0 + t);
    this.cards.forEach((st, i) => {
      const p = eo(seg(t, 0.35 + i * 0.3, 1.25 + i * 0.3));
      st.opacity = eo(seg(t, 0.35 + i * 0.3, 0.7 + i * 0.3));
      st.transform = 'translateZ(' + lerp(-2400, 0, p) + 'px) translateY(' + lerp(-120, 0, p) + 'px) rotateY(' + lerp(-18, 0, p) + 'deg)';
    });
    this.oks.forEach((st, i) => { const p = eo(seg(t, 1.6 + i * 0.25, 1.9 + i * 0.25)); st.opacity = p; st.transform = 'scale(' + lerp(1.4, 1, p) + ')'; });
    if (t < 4.2) TextFx.fadeFromRight(this.line, t, 0.1, { stagger: 0.11, dur: 0.5, dx: 28 });
    else TextFx.fadeOutLeft(this.line, t, 4.2);
    this.sub.opacity = eo(seg(t, 0.8, 1.3)) * (1 - eo(seg(t, 4.2, 4.5)));
    const out = eio(seg(t, 4.25, 5.0));
    this.cam.transform = 'translateX(' + lerp(0, -900, out) + 'px) scale(' + (1.0 + 0.012 * t) + ')';
    this.cam.opacity = 1 - ei(seg(t, 4.4, 5.0));
    window.UI.grain(this.grain, t);
  },
});
