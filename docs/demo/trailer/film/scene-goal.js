const { seg, eo, ei, eio, lerp } = kit;
const GOAL_OPTS = [['Set and forget', 'Simple colonies, longer programs, and fewer pickup stops. Keep maintenance predictable.'], ['Balanced', 'Extra work only where it clearly pays off.'], ['Maximum ISK', 'Every million counts. You don’t mind hauling and flying to more systems.']];
kit.scene('goal', {
  init(kit) {
    const cards = GOAL_OPTS.map((o, i) => '<div class="goal-card" style="flex:1;min-width:0;padding:34px 32px;box-sizing:border-box;height:250px;background:var(--ground);box-shadow:inset 0 0 0 1px #2a2e33;clip-path:polygon(0 0, calc(100% - 16px) 0, 100% 16px, 100% 100%, 0 100%)">' +
      '<div style="font-family:var(--display, var(--sans, system-ui, sans-serif));font-weight:600;font-size:40px;margin-bottom:16px">' + o[0] + '</div>' +
      '<div style="font-size:22px;line-height:1.45;color:#a19d94">' + o[1] + '</div></div>').join('');
    kit.stage.append(kit.h('<div class="ground bars">' +
      '<canvas class="sky goal-sky" width="1920" height="1080"></canvas>' +
      '<div class="layer goal-cam">' +
      '<div class="panel goal-panel" style="left:210px;top:160px;width:1500px;height:760px;padding:46px 60px;box-sizing:border-box">' +
      window.UI.stepper('goal') +
      '<p class="mono hot" style="margin:46px 0 0;font-size:18px">Step 1 of 6</p>' +
      '<h3 style="margin:12px 0 0;font-family:var(--display, var(--sans, system-ui, sans-serif));font-weight:600;font-size:72px">What do you want from PI?</h3>' +
      '<p style="margin:14px 0 0;font-size:26px;color:#a19d94">Choose the balance between income and upkeep. You can change this later.</p>' +
      '<div style="display:flex;gap:30px;margin-top:40px">' + cards + '</div></div></div>' +
      '<div class="vignette"></div><div class="grain goal-grain"></div></div>'));
    const q = (s) => kit.stage.querySelector(s);
    this.kit = kit;
    this.T0 = kit.start;
    this.ctx = q('.goal-sky').getContext('2d');
    this.cam = q('.goal-cam').style;
    this.panel = q('.goal-panel').style;
    this.cards = [...kit.stage.querySelectorAll('.goal-card')].map((n) => n.style);
    this.grain = q('.goal-grain').style;
    this.cur = kit.cursor();
    this.cur.keys = [{ t: 2.2, at: [1500, 980] }, { t: 2.95, at: [930, 700], bow: 0.15 }, { t: 4.6, at: [930, 700] }, { t: 5.3, at: [1300, 880] }];
    this.cur.clicks = [3.15];
    this.cur.visible = (t) => eo(seg(t, 2.1, 2.4)) * (1 - eo(seg(t, 5.0, 5.4)));
  },
  render(t) {
    window.SPACE.draw(this.ctx, this.T0 + t);
    const inn = eio(seg(t, -0.15, 0.85));
    const zin = eio(seg(t, 0.9, 1.6)), zout = eio(seg(t, 1.9, 2.5));
    const z = 1 + 0.32 * zin * (1 - zout) + 0.01 * t;
    this.cam.transformOrigin = '700px 420px';
    this.cam.transform = 'translateX(' + lerp(900, 0, inn) + 'px) scale(' + z + ')';
    this.cam.opacity = eo(seg(t, -0.1, 0.4));
    const sel = t >= 3.15;
    this.cards.forEach((st, i) => {
      const on = i === 1 && sel;
      const hover = i === 1 && t > 2.9;
      st.background = on ? 'color-mix(in srgb, var(--main) 22%, var(--ground))' : (hover ? 'color-mix(in srgb, var(--second) 6%, var(--ground))' : 'var(--ground)');
      st.boxShadow = 'inset 0 0 0 ' + (on ? 2 : 1) + 'px ' + (on ? 'var(--main)' : '#2a2e33');
      const p = eo(seg(t, 0.5 + i * 0.12, 0.9 + i * 0.12));
      st.opacity = p;
      st.transform = 'translateY(' + lerp(18, 0, p) + 'px)';
    });
    const k = lerp(0, 1, eio(seg(t, 3.8, 4.5)));
    window.UI.setStep(this.kit, 'goal', k);
    this.cur.render(t);
    window.UI.grain(this.grain, t);
  },
});
