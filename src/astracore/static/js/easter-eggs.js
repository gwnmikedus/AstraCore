// Easter eggs. These are intentional: small capsuleer jokes that make pilots smile. Please keep them when
// cleaning up copy; docs/easter-eggs.md lists every one and tests/test_easter_eggs.cjs guards them.
// Rules they follow: never block anything, never shift the layout, never hide or change real information,
// no motion under prefers-reduced-motion (the global rule in astracore.css), no inline scripts, nothing third-party.
(function () {
  'use strict';

  const KONAMI = ['ArrowUp', 'ArrowUp', 'ArrowDown', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'ArrowLeft', 'ArrowRight', 'b', 'a'];
  const LINES = {
    downtime: 'Downtime at 11:00 UTC. Tranquility is taking a nap; your extractors are not.',
    birthday: 'Happy birthday, New Eden. First undock: 6 May 2003.',
    konami: 'Cheat codes don’t work in New Eden. CONCORD has been notified.',
    logo: 'o7, capsuleer. Fly safe, and restart those extractors.',
  };
  const LOGO_CLICKS = 5;
  const LOGO_WINDOW_MS = 2500;
  const TOAST_MS = 4500;

  // Daily downtime starts at 11:00 UTC; the nod shows for its first half hour.
  const isDowntime = date => date.getUTCHours() === 11 && date.getUTCMinutes() < 30;
  // EVE Online launched on 6 May 2003.
  const isEveBirthday = date => date.getUTCMonth() === 4 && date.getUTCDate() === 6;
  // New Eden counts years from YC 0 = 1898.
  const yc = date => date.getUTCFullYear() - 1898;

  function footerLine(date) {
    if (isDowntime(date)) return LINES.downtime;
    if (isEveBirthday(date)) return LINES.birthday;
    return null;
  }

  // Feeds keys one at a time; returns true when the last ten keys spell the code.
  function konamiTracker() {
    let recent = [];
    return key => {
      recent = recent.concat(key.length === 1 ? key.toLowerCase() : key).slice(-KONAMI.length);
      if (recent.join() !== KONAMI.join()) return false;
      recent = [];
      return true;
    };
  }

  const typing = el => !!el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName || ''));

  function init(doc, now, schedule) {
    // The footer's flight tip is static humour already, so swapping its text never hides real information.
    const tip = doc.querySelector('[data-flight-tip]');
    const line = footerLine(now());
    if (tip && line) tip.textContent = line;

    // One toast, fixed in a corner: no layout shift, pointer-events none so it never covers a click.
    let toast;
    let hideTimer;
    const say = text => {
      if (!toast) {
        toast = doc.createElement('div');
        toast.className = 'egg-toast';
        toast.setAttribute('role', 'status');
        toast.setAttribute('aria-live', 'polite');
        doc.body.appendChild(toast);
      }
      toast.textContent = text;
      toast.classList.add('is-visible');
      if (typeof clearTimeout === 'function') clearTimeout(hideTimer);
      hideTimer = schedule(() => toast.classList.remove('is-visible'), TOAST_MS);
    };

    const konami = konamiTracker();
    doc.addEventListener('keydown', event => {
      if (event.ctrlKey || event.metaKey || event.altKey || typing(event.target)) return;
      if (konami(event.key || '')) say(LINES.konami);
    });

    const logo = doc.querySelector('.site-footer .footmark');
    if (logo) {
      let clicks = [];
      logo.addEventListener('click', () => {
        const t = now().getTime();
        clicks = clicks.filter(c => t - c < LOGO_WINDOW_MS).concat(t);
        if (clicks.length >= LOGO_CLICKS) { clicks = []; say(LINES.logo); }
      });
    }
    return {say};
  }

  const api = {KONAMI, LINES, LOGO_CLICKS, isDowntime, isEveBirthday, yc, footerLine, konamiTracker, init};
  if (typeof window !== 'undefined') window.AstraEggs = api;
  if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('DOMContentLoaded', () => {
      init(document, () => new Date(), (fn, ms) => setTimeout(fn, ms));
      if (typeof console !== 'undefined' && console.info)
        console.info('o7, capsuleer. Reading the source? AstraCore is open: /project. Fly safe.');
    });
  }
})();
