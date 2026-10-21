const { seg, eo, ei, eio, lerp, TextFx } = kit;
const PL_TILES = [['ISK / week', 8.4, (v) => v.toFixed(1) + 'M'], ['Your time / week', 105, (v) => Math.floor(v / 60) + 'h ' + String(Math.round(v % 60)).padStart(2, '0') + 'm'], ['To haul / week', 7000, (v) => Math.round(v).toLocaleString('en-US') + ' m³'], ['Colonies', 12, (v) => String(Math.round(v))]];
window.PLAN_BTN = '<div class="planbtn" style="position:absolute;left:310px;top:780px;height:70px;padding:0 30px;display:flex;align-items:center;gap:14px;background:var(--main);color:#1a0a00;font-family:var(--display, var(--sans, system-ui, sans-serif));font-weight:600;font-size:28px;letter-spacing:.06em;text-transform:uppercase">↓ Templates for this plan (12)</div>';
kit.scene('plan', {
  init(kit) {
    const tiles = PL_TILES.map((x) => '<div style="flex:1;min-width:0;padding:26px 28px;background:var(--ground);box-shadow:inset 0 0 0 1px #2a2e33">' +
      '<div class="mono muted" style="font-size:17px">' + x[0] + '</div>' +
      '<div class="plan-num" style="margin-top:14px;font-family:var(--mono, ui-monospace, monospace);font-size:48px;white-space:nowrap;font-variant-numeric:tabular-nums"></div></div>').join('');
    kit.stage.append(kit.h('<div class="ground bars">' +
      '<canvas class="sky plan-sky" width="1920" height="1080"></canvas>' +
      '<div class="words plan-words" style="left:260px;top:150px;width:1400px"><h2 class="line plan-line" style="font-size:84px">A plan sized to your time</h2></div>' +
      '<div class="plan-rig" style="position:absolute;inset:0;transform-origin:960px 600px">' +
      '<div class="panel plan-panel" style="left:260px;top:300px;width:1400px;height:600px;padding:44px 50px;box-sizing:border-box">' +
      '<div style="display:flex;justify-content:space-between;align-items:baseline"><h3 style="margin:0;font-family:var(--display, var(--sans, system-ui, sans-serif));font-weight:600;font-size:48px">Your plan</h3>' +
      '<span class="mono muted" style="font-size:18px">Example figures</span></div>' +
      '<div class="plan-warn" style="margin-top:24px;padding:18px 24px;box-shadow:inset 0 0 0 1px #f2c230;font-size:24px;color:var(--second)"><b style="color:#f2c230">▲ Yield is an estimate</b> until your extractors run. Prices and demand change.</div>' +
      '<div style="display:flex;gap:20px;margin-top:28px">' + tiles + '</div></div>' +
      '<div class="plan-chk" style="position:absolute;left:820px;top:780px;height:70px;padding:0 30px;display:flex;align-items:center;font-family:var(--display, var(--sans, system-ui, sans-serif));font-weight:600;font-size:28px;letter-spacing:.06em;text-transform:uppercase;box-shadow:inset 0 0 0 2px #646a72">Print build checklist</div></div>' +
      window.PLAN_BTN +
      '<div class="plan-frame" style="position:absolute;border:3px solid var(--main);box-sizing:border-box"></div>' +
      '<div class="plan-seed" style="position:absolute;background:var(--main)"></div>' +
      '<div class="vignette"></div><div class="grain plan-grain"></div></div>'));
    const q = (s) => kit.stage.querySelector(s);
    this.T0 = kit.start;
    this.ctx = q('.plan-sky').getContext('2d');
    for (const k of ['rig', 'frame', 'seed', 'warn', 'grain', 'words']) this[k] = q('.plan-' + k).style;
    this.btn = q('.planbtn').style;
    this.line = q('.plan-line');
    this.nums = [...kit.stage.querySelectorAll('.plan-num')];
    this.cur = kit.cursor();
    this.cur.keys = [{ t: 4.2, at: [1250, 980] }, { t: 4.9, at: [560, 818], bow: 0.12 }, { t: 6.5, at: [560, 818] }];
    this.cur.clicks = [5.15];
    this.cur.visible = (t) => eo(seg(t, 4.1, 4.4));
  },
  box(st, x, y, w, h) { st.left = x + 'px'; st.top = y + 'px'; st.width = w + 'px'; st.height = h + 'px'; },
  render(t) {
    window.SPACE.draw(this.ctx, this.T0 + t);
    const g = eio(seg(t, 0.05, 0.6));
    const fw = lerp(40, 1400, g), fh = lerp(40, 600, g);
    this.box(this.frame, lerp(940, 260, g), lerp(520, 300, g), fw, fh);
    this.frame.opacity = 1 - eo(seg(t, 0.7, 1.0));
    const ss = lerp(40, 0, eo(seg(t, 0, 0.3)));
    this.box(this.seed, 960 - ss / 2, 540 - ss / 2, ss, ss);
    const fadeAll = eo(seg(t, 5.35, 5.9));
    this.rig.opacity = eo(seg(t, 0.4, 0.75)) * (1 - fadeAll);
    this.rig.transform = 'translateY(' + (-3 * t) + 'px)';
    this.words.transform = 'translateX(' + (-6 * t) + 'px)';
    this.btn.opacity = eo(seg(t, 1.6, 1.9));
    this.btn.transform = 'translateY(' + (-3 * Math.min(t, 5.0)) + 'px) scale(' + (t > 5.15 && t < 5.3 ? 0.97 : 1) + ')';
    this.warn.opacity = eo(seg(t, 0.8, 1.1));
    PL_TILES.forEach((x, i) => { const p = eo(seg(t, 0.9 + i * 0.15, 2.2 + i * 0.15)); this.nums[i].textContent = x[2](x[1] * lerp(0.5, 1, p)); this.nums[i].style.opacity = eo(seg(t, 0.9 + i * 0.15, 1.2 + i * 0.15)); });
    if (t < 5.3) TextFx.fadeFromRight(this.line, t, 0.6, { stagger: 0.1, dur: 0.5, dx: 28 });
    else TextFx.fadeOutLeft(this.line, t, 5.3);
    this.cur.render(t);
    window.UI.grain(this.grain, t);
  },
});
