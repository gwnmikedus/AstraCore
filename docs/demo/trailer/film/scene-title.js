const { seg, eo, eio, eob, lerp, TextFx } = kit;
const TTL_WORD = '<svg viewBox="0 0 184 24" style="width:100%;height:100%;overflow:visible"><g fill="none" stroke="#ece8df" stroke-width="4" stroke-linejoin="miter"><path d="M2 24V7L7 2H9L14 7V24M2 14H14"/><path transform="translate(21 0)" d="M16 2H6L2 6V9L5 12H11L14 15V18L10 22H0"/><path transform="translate(42 0)" d="M0 2H16M8 2V24"/><path transform="translate(63 0)" d="M2 24V2H10L14 6V9L11 12H2M11 12L14 15V24"/><path transform="translate(84 0)" d="M2 24V7L7 2H9L14 7V24M2 14H14"/><path transform="translate(105 0)" d="M16 2H6L2 6V18L6 22H16"/><path transform="translate(126 0)" d="M6 2H10L14 6V18L10 22H6L2 18V6Z"/><path transform="translate(147 0)" d="M2 24V2H10L14 6V9L11 12H2M11 12L14 15V24"/><path transform="translate(168 0)" d="M16 2H2V22H16M2 12H12"/></g><rect x="131.5" y="9.5" width="5" height="5" fill="#ff6a1a"/></svg>';
const TTL_MARK = '<svg viewBox="0 0 64 64" style="width:100%;height:100%"><path d="M6 6H44L58 20V58H20L6 44Z" fill="none" stroke="#ece8df" stroke-width="5" stroke-linejoin="miter"/><rect class="title-core" x="24" y="24" width="16" height="16" fill="#ff6a1a"/></svg>';
kit.scene('title', {
  init(kit) {
    kit.stage.append(kit.h('<div class="ground bars">' +
      '<canvas class="sky title-sky" width="1920" height="1080"></canvas>' +
      '<div class="title-beam" style="position:absolute;left:0;right:0;top:453px;height:4px;background:var(--main);transform-origin:575px 50%"></div>' +
      '<div class="title-seed" style="position:absolute;left:556px;top:436px;width:38px;height:38px;background:var(--main)"></div>' +
      '<div class="title-flare" style="position:absolute;left:460px;top:340px;width:1000px;height:400px;background:radial-gradient(closest-side, color-mix(in srgb, var(--main) 30%, transparent), transparent)"></div>' +
      '<div class="layer title-cam">' +
      '<div class="title-mark" style="position:absolute;left:500px;top:380px;width:150px;height:150px">' + TTL_MARK + '</div>' +
      '<div class="title-wordwrap" style="position:absolute;left:700px;top:412px;width:620px;height:81px;clip-path:inset(0 100% 0 0)">' + TTL_WORD + '</div>' +
      '<div class="title-code" style="position:absolute;left:1352px;top:410px;height:84px;padding:0 22px;display:flex;align-items:center;background:var(--main);color:var(--ground);font-family:var(--display, var(--sans, system-ui, sans-serif));font-weight:700;font-size:64px">PI</div>' +
      '<div class="words" style="left:500px;top:590px;width:960px"><p class="sub title-tag" style="font-size:44px;color:var(--second)">PI setup, without the spreadsheet.</p><p class="mono hot title-url" style="font-size:26px;text-transform:none;letter-spacing:.06em">astracore.hoppyhome.nl</p></div></div>' +
      '<p class="mono muted title-foot" style="position:absolute;left:0;right:0;bottom:150px;margin:0;text-align:center;font-size:16px">Independent fan-made tool · EVE Online belongs to CCP · Colony templates by DalShooth</p>' +
      '<div class="vignette"></div><div class="grain title-grain"></div></div>'));
    const q = (s) => kit.stage.querySelector(s);
    for (const k of ['beam', 'flare', 'cam', 'mark', 'wordwrap', 'code', 'foot', 'grain', 'seed']) this[k] = q('.title-' + k).style;
    this.tag = q('.title-tag');
    this.T0 = kit.start;
    this.ctx = q('.title-sky').getContext('2d');
  },
  render(t) {
    window.SPACE.draw(this.ctx, this.T0 + t, lerp(1, 0.6, eio(seg(t, 0, 1.2))));
    this.seed.opacity = 1 - eo(seg(t, 0.3, 0.55));
    const b = eo(seg(t, 0.05, 0.5));
    this.beam.transform = 'scaleX(' + b + ') scaleY(' + lerp(1, 0.25, eio(seg(t, 0.5, 1.1))) + ')';
    this.beam.opacity = 1 - eio(seg(t, 0.7, 1.2));
    this.flare.opacity = eo(seg(t, 0.2, 0.5)) * (1 - 0.6 * eio(seg(t, 0.6, 1.6)));
    const m = seg(t, 0.1, 0.6);
    this.mark.transform = 'scale(' + lerp(0.25, 1, m <= 0 ? 0 : eob(m, 1.6)) + ') rotate(' + lerp(-45, 0, eo(m)) + 'deg)';
    this.mark.opacity = eo(seg(t, 0.1, 0.3));
    this.wordwrap.clipPath = 'inset(0 ' + (100 - 100 * eio(seg(t, 0.55, 1.1))) + '% 0 0)';
    const c = seg(t, 1.0, 1.3);
    this.code.opacity = eo(c);
    this.code.transform = 'translateX(' + lerp(30, 0, eo(c)) + 'px)';
    TextFx.fadeFromRight(this.tag, t, 1.35, { stagger: 0.1, dur: 0.5, dx: 26 });
    const uq = this.url || (this.url = this.tag.parentNode.querySelector('.title-url').style);
    uq.opacity = eo(seg(t, 2.0, 2.4));
    uq.transform = 'translateX(' + lerp(24, 0, eo(seg(t, 2.0, 2.4))) + 'px)';
    this.foot.opacity = 0.9 * eo(seg(t, 2.5, 3.0));
    this.cam.transform = 'scale(' + (1 + 0.012 * t) + ')';
    this.grain.transform = 'translate(' + ((Math.floor(t * 24) * 37) % 60) + 'px,' + ((Math.floor(t * 24) * 53) % 60) + 'px)';
  },
});
