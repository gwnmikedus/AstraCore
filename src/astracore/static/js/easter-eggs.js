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
    o7: 'o7 to you too, capsuleer.',
    themeFlip: 'Make up your mind, capsuleer. Your pupils have filed a complaint with CONCORD.',
    longSession: 'An hour of planning. Your extractors would like a word.',
    aprilFools: 'Today’s tips are 100% accurate. Check the date.',
    holidays: 'Happy holidays, capsuleer. The customs office never closes.',
    newYear: 'New year, new extractor cycle. Fly safe in YC {yc}.',
  };
  const LOGO_CLICKS = 5;
  const LOGO_WINDOW_MS = 2500;
  const TOAST_MS = 4500;
  const THEME_FLIPS = 6;
  const THEME_WINDOW_MS = 8000;
  const LONG_SESSION_MS = 60 * 60 * 1000;

  // Daily downtime starts at 11:00 UTC; the nod shows for its first half hour.
  const isDowntime = date => date.getUTCHours() === 11 && date.getUTCMinutes() < 30;
  // EVE Online launched on 6 May 2003.
  const isEveBirthday = date => date.getUTCMonth() === 4 && date.getUTCDate() === 6;
  // New Eden counts years from YC 0 = 1898.
  const yc = date => date.getUTCFullYear() - 1898;

  // Footer tip for a moment worth a nod (UTC), or null on an ordinary day.
  function footerLine(date) {
    const month = date.getUTCMonth() + 1;
    const day = date.getUTCDate();
    if (isDowntime(date)) return LINES.downtime;
    if (isEveBirthday(date)) return LINES.birthday;
    if (month === 4 && day === 1) return LINES.aprilFools;
    if (month === 12 && day >= 24 && day <= 26) return LINES.holidays;
    if (month === 1 && day === 1) return LINES.newYear.replace('{yc}', yc(date));
    return null;
  }

  // Feeds keys one at a time; true when the last two spell o7, the capsuleer salute.
  function o7Tracker() {
    let last = '';
    return key => {
      const k = key.length === 1 ? key.toLowerCase() : '';
      const hit = last === 'o' && k === '7';
      last = k;
      return hit;
    };
  }

  // Counts events in a sliding window; true once `count` land within `windowMs`, then starts over.
  function burst(count, windowMs) {
    let times = [];
    return t => {
      times = times.filter(x => t - x < windowMs).concat(t);
      if (times.length < count) return false;
      times = [];
      return true;
    };
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
    const o7 = o7Tracker();
    doc.addEventListener('keydown', event => {
      if (event.ctrlKey || event.metaKey || event.altKey || typing(event.target)) return;
      const key = event.key || '';
      if (konami(key)) say(LINES.konami);
      else if (o7(key)) say(LINES.o7);
    });

    const logo = doc.querySelector('.site-footer .footmark');
    if (logo) {
      const clicks = burst(LOGO_CLICKS, LOGO_WINDOW_MS);
      logo.addEventListener('click', () => { if (clicks(now().getTime())) say(LINES.logo); });
    }

    // Flipping the theme back and forth: astracore.js does the switch, this only notices.
    const toggle = doc.getElementById && doc.getElementById('theme-toggle');
    if (toggle && toggle.addEventListener) {
      const flips = burst(THEME_FLIPS, THEME_WINDOW_MS);
      toggle.addEventListener('click', () => { if (flips(now().getTime())) say(LINES.themeFlip); });
    }

    // Once per page, after an hour on it.
    schedule(() => say(LINES.longSession), LONG_SESSION_MS);
    return {say};
  }

  const api = {KONAMI, LINES, LOGO_CLICKS, THEME_FLIPS, LONG_SESSION_MS, isDowntime, isEveBirthday, yc, footerLine,
    konamiTracker, o7Tracker, burst, init};
  if (typeof window !== 'undefined') window.AstraEggs = api;
  if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('DOMContentLoaded', () => {
      init(document, () => new Date(), (fn, ms) => setTimeout(fn, ms));
      if (typeof console !== 'undefined' && console.info)
        console.info('o7, capsuleer. Reading the source? AstraCore is open: /project. Fly safe.');
    });
  }
})();
