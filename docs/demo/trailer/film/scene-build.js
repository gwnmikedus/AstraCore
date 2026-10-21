const { seg, eo, ei, eio, eob, lerp, TextFx } = kit;
const BD_T = [['Barren', 'P1 extraction'], ['Temperate', 'P2 factory'], ['Lava', 'P1 extraction'], ['Storm', 'P1 extraction']];
const BD_STEPS = ['Place the command center', 'Import the template', 'Start the extractors'];
kit.scene('build', {
  init(kit) {
    const pins = '<svg viewBox="0 0 300 120" style="width:100%;height:120px"><g stroke="#646a72" stroke-width="2"><line x1="150" y1="60" x2="60" y2="25"/><line x1="150" y1="60" x2="60" y2="95"/><line x1="150" y1="60" x2="240" y2="25"/><line x1="150" y1="60" x2="240" y2="95"/></g><rect x="138" y="48" width="24" height="24" fill="#ff6a1a"/><g fill="#ece8df"><rect x="52" y="17" width="16" height="16"/><rect x="52" y="87" width="16" height="16"/><rect x="232" y="17" width="16" height="16"/><rect x="232" y="87" width="16" height="16"/></g></svg>';
    const cards = BD_T.map((c) => '<div class="panel build-card" style="left:0;top:0;width:380px;height:290px;padding:26px 28px;box-sizing:border-box;transform-origin:50% 50%">' + pins +
      '<div style="margin-top:14px;font-family:var(--display, var(--sans, system-ui, sans-serif));font-weight:600;font-size:36px">' + c[0] + '</div>' +
      '<div style="font-size:22px;color:#a19d94">' + c[1] + '</div>' +
      '<div class="mono hot" style="margin-top:10px;font-size:15px">Template by DalShooth</div></div>').join('');
    const steps = BD_STEPS.map((s, i) => '<p class="build-step" style="margin:0;display:flex;align-items:center;gap:18px;font-size:28px"><span class="build-box" style="width:30px;height:30px;flex:none;display:grid;place-items:center;box-shadow:inset 0 0 0 2px #646a72;font-size:22px;color:#1a0a00"></span>' + (i + 1) + ' · ' + s + '</p>').join('');
    kit.stage.append(kit.h('<div class="ground bars">' +
      '<canvas class="sky build-sky" width="1920" height="1080"></canvas>' +
      '<div class="words" style="left:160px;top:150px;width:1600px"><h2 class="line build-line" style="font-size:84px">Matched templates. Then just build.</h2></div>' +
      '<div class="build-cards" style="position:absolute;inset:0">' + cards + '</div>' +
      '<div class="build-list" style="position:absolute;left:900px;top:700px;display:flex;flex-direction:column;gap:16px">' + steps + '</div>' +
      '<div class="build-btn" style="position:absolute;left:310px;top:765px;height:70px;padding:0 30px;display:flex;align-items:center;gap:14px;background:var(--main);color:#1a0a00;font-family:var(--display, var(--sans, system-ui, sans-serif));font-weight:600;font-size:28px;letter-spacing:.06em;text-transform:uppercase">↓ Templates for this plan (12)</div>' +
      '<div class="vignette"></div><div class="grain build-grain"></div></div>'));
    const q = (s) => kit.stage.querySelector(s);
    this.T0 = kit.start;
    this.ctx = q('.build-sky').getContext('2d');
    this.cards = [...kit.stage.querySelectorAll('.build-card')].map((n) => n.style);
    this.steps = [...kit.stage.querySelectorAll('.build-step')].map((n) => n.style);
    this.boxes = [...kit.stage.querySelectorAll('.build-box')];
    this.line = q('.build-line');
    this.btn = q('.build-btn').style;
    this.grain = q('.build-grain').style;
  },
  render(t) {
    window.SPACE.draw(this.ctx, this.T0 + t);
    const away = ei(seg(t, 4.15, 4.95));
    this.cards.forEach((st, i) => {
      const p = seg(t, 0.15 + i * 0.12, 0.85 + i * 0.12);
      const e = p <= 0 ? 0 : eob(p, 1.5);
      const x0 = 350, y0 = 655, x1 = 160 + i * 410, y1 = 330 + (i % 2) * 14;
      const x = lerp(lerp(x0, x1, e), 1080 - 190, away), y = lerp(lerp(y0, y1, e), 470 - 145, away);
      const s = lerp(0.15, 1, Math.min(1, e)) * lerp(1, 0.08, away);
      st.transform = 'translate(' + x + 'px,' + y + 'px) scale(' + s + ') rotate(' + lerp(-8 + i * 5, 0, Math.min(1, e)) + 'deg)';
      st.opacity = (eo(seg(t, 0.15 + i * 0.12, 0.35 + i * 0.12)) * (1 - eo(seg(t, 4.6, 4.95)))).toFixed(3);
    });
    this.btn.opacity = 1 - eo(seg(t, 1.2, 1.6));
    this.steps.forEach((st, i) => { const p = eo(seg(t, 1.5 + i * 0.2, 1.9 + i * 0.2)); st.opacity = p * (1 - eo(seg(t, 4.1, 4.4))); st.transform = 'translateX(' + lerp(24, 0, p) + 'px)'; });
    this.boxes.forEach((b, i) => { const on = t >= 2.4 + i * 0.45; b.style.background = on ? 'var(--main)' : 'transparent'; b.style.boxShadow = 'inset 0 0 0 2px ' + (on ? 'var(--main)' : '#646a72'); b.textContent = on ? '✓' : ''; });
    if (t < 4.0) TextFx.fadeFromRight(this.line, t, 0.35, { stagger: 0.1, dur: 0.5, dx: 28 });
    else TextFx.fadeOutLeft(this.line, t, 4.0);
    window.UI.grain(this.grain, t);
  },
});
