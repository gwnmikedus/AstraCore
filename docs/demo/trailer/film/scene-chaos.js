const { seg, eo, ei, eio, lerp, rng, TextFx } = kit;
const CH_Q = ['Barren or Lava?', 'Extractor heads?', 'CPU / powergrid', 'Customs office tax', 'Link length?', 'm³ to haul', 'Command Center Upgrades', 'Which template?', 'Which system?', 'Coolant or Enriched Uranium?', 'Storage full?', 'P1 → P2 → ?', 'Interplanetary Consolidation', 'Cycle time?'];
kit.scene('chaos', {
  init(kit) {
    const r = rng(9);
    const cell = () => '<td style="border:1px solid #2a2e33;padding:6px 14px;font-family:var(--mono, ui-monospace, monospace);font-size:20px;color:#a19d94">' + Math.floor(r() * 9000 + 100) + '</td>';
    const grid = () => '<table style="border-collapse:collapse;background:color-mix(in srgb, var(--ground) 90%, var(--second))">' + [0, 1, 2].map(() => '<tr>' + cell() + cell() + cell() + '</tr>').join('') + '</table>';
    let html = '';
    this.items = [];
    for (let i = 0; i < 22; i++) {
      const isQ = i < CH_Q.length;
      const inner = isQ ? '<span class="mono" style="display:block;padding:12px 20px;font-size:26px;text-transform:none;letter-spacing:.04em;border:2px solid color-mix(in srgb, var(--second) 30%, transparent);background:color-mix(in srgb, var(--ground) 85%, transparent);white-space:nowrap">' + CH_Q[i] + '</span>' : grid();
      html += '<div class="chaos-it" style="position:absolute;left:0;top:0;transform-origin:0 0">' + inner + '</div>';
      const ang = r() * 6.283, rad = 260 + r() * 900;
      this.items.push({ x: Math.cos(ang) * rad, y: Math.sin(ang) * rad * 0.6, z: 600 + i * 150 + r() * 120, rot: (r() - 0.5) * 14 });
    }
    kit.stage.append(kit.h('<div class="ground bars">' +
      '<canvas class="sky chaos-sky" width="1920" height="1080"></canvas>' +
      '<div class="layer chaos-field">' + html + '</div>' +
      '<div class="words chaos-words" style="left:0;right:0;top:470px;align-items:center;text-align:center"><h2 class="line" style="font-size:120px">Everybody hates setting up PI</h2></div>' +
      '<div class="chaos-seed" style="position:absolute;left:940px;top:520px;width:40px;height:40px;background:var(--main)"></div>' +
      '<div class="vignette"></div><div class="grain chaos-grain"></div></div>'));
    const q = (s) => kit.stage.querySelector(s);
    this.T0 = kit.start;
    this.ctx = q('.chaos-sky').getContext('2d');
    this.els = [...kit.stage.querySelectorAll('.chaos-it')].map((n) => n.style);
    this.line = q('.line');
    this.words = q('.chaos-words').style;
    this.seed = q('.chaos-seed').style;
    this.grain = q('.chaos-grain').style;
  },
  render(t) {
    window.SPACE.draw(this.ctx, this.T0 + t);
    const imp = ei(seg(t, 3.0, 3.75));
    this.items.forEach((it, i) => {
      const zz = it.z - 760 * t;
      const st = this.els[i];
      if (zz < 60) { st.opacity = 0; return; }
      const s = 700 / zz;
      const x = 960 + it.x * s * (1 - imp), y = 540 + it.y * s * (1 - imp);
      const fadeNear = Math.min(1, (zz - 60) / 220), fadeFar = Math.min(1, Math.max(0, (2600 - zz) / 900));
      st.opacity = (fadeNear * fadeFar * (1 - imp)).toFixed(3);
      st.transform = 'translate(' + x.toFixed(1) + 'px,' + y.toFixed(1) + 'px) scale(' + (s * lerp(1, 0.2, imp)).toFixed(3) + ') rotate(' + (it.rot + t * 4) + 'deg)';
    });
    TextFx.fadeFromRight(this.line, t, 1.1, { stagger: 0.1, dur: 0.5, dx: 30 });
    this.words.opacity = 1 - imp;
    this.words.transform = 'scale(' + lerp(1, 0.1, imp) + ')';
    const sp = eo(seg(t, 3.45, 3.8));
    this.seed.opacity = sp;
    this.seed.transform = 'scale(' + lerp(0.2, 1, sp) + ') rotate(' + lerp(45, 0, sp) + 'deg)';
    window.UI.grain(this.grain, t);
  },
});
