// Easter eggs. These are intentional: small capsuleer jokes that make pilots smile. Please keep them when
// cleaning up copy; docs/easter-eggs.md lists every one and tests/test_easter_eggs.cjs guards them.
// Each find goes into the capsuleer's logbook (core/logbook.py): on the server when signed in, in this browser
// otherwise. The first time an egg is found a short notice says so and counts; after that it stays quiet.
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
  // Mirrors core/logbook.py EGGS (a test keeps the two in step).
  const EGGS = {
    flashbang: 'Flashbang warning', yc_year: 'YC 128', logo: 'o7 from the logo', o7: 'o7',
    not_on_overview: 'Not on your overview', theme_flip: 'Make up your mind', konami: 'Cheat code',
    console: 'Console capsuleer', rare_tip: 'The rare tip', long_session: 'An hour of planning', downtime: 'Downtime',
    birthday: 'New Eden’s birthday', april_fools: 'Check the date', holidays: 'Customs never closes',
    new_year: 'New extractor cycle',
  };
  // Footer line key -> logbook egg.
  const LINE_EGG = {downtime: 'downtime', birthday: 'birthday', aprilFools: 'april_fools', holidays: 'holidays',
    newYear: 'new_year'};
  const STORE_KEY = 'ac_logbook';
  const HOVER_MS = 700;
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

  // Which footer line fits this moment (UTC), or null on an ordinary day.
  function footerKey(date) {
    const month = date.getUTCMonth() + 1;
    const day = date.getUTCDate();
    if (isDowntime(date)) return 'downtime';
    if (isEveBirthday(date)) return 'birthday';
    if (month === 4 && day === 1) return 'aprilFools';
    if (month === 12 && day >= 24 && day <= 26) return 'holidays';
    if (month === 1 && day === 1) return 'newYear';
    return null;
  }
  function footerLine(date) {
    const key = footerKey(date);
    return key ? LINES[key].replace('{yc}', yc(date)) : null;
  }

  // The footer's logbook line, as plain text plus whether it links to /logbook.
  function logbookLine(count, total, unlock, signedIn) {
    if (!count) return {text: `Rumour has it ${total} things are hidden in AstraCore.`, link: false};
    const base = `Capsuleer’s logbook: ${count} of ${total} found`;
    if (count < unlock) return {text: `${base}. Find ${unlock} to open it.`, link: false};
    return signedIn ? {text: base, link: true} : {text: `${base}. Sign in to open it.`, link: false};
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

  // Finds made before init (another script can report one early, e.g. the rare footer tip) wait here.
  const early = [];
  let report = id => { early.push(id); };
  if (typeof document !== 'undefined' && document.addEventListener)
    document.addEventListener('astracore:egg', event => report(event.detail));

  function readStore(storage) {
    try { return JSON.parse(storage.getItem(STORE_KEY) || '[]').filter(id => EGGS[id]); } catch (e) { return []; }
  }
  function writeStore(storage, ids) {
    try { storage.setItem(STORE_KEY, JSON.stringify(ids)); } catch (e) { /* private mode: the server copy still counts */ }
  }

  function init(doc, now, schedule, env = {}) {
    const storage = env.storage || {getItem: () => null, setItem() {}};
    const post = env.post || null;
    const line = doc.querySelector('[data-logbook]');
    const data = line && line.dataset ? line.dataset : {};
    const signedIn = !!post && data.signedIn !== undefined;
    const total = +data.total || Object.keys(EGGS).length;
    const unlock = +data.unlock || 3;
    const server = (data.found || '').split(',').filter(id => EGGS[id]);
    let found = new Set(signedIn ? server : readStore(storage));

    // One toast, fixed in a corner: no layout shift, pointer-events none so it never covers a click.
    let toast;
    let hideTimer;
    const say = (text, detail) => {
      if (!toast) {
        toast = doc.createElement('div');
        toast.className = 'egg-toast';
        toast.setAttribute('role', 'status');
        toast.setAttribute('aria-live', 'polite');
        doc.body.appendChild(toast);
      }
      toast.textContent = text;
      if (detail) {
        const small = doc.createElement('small');
        small.textContent = detail;
        toast.appendChild(small);
      }
      toast.classList.add('is-visible');
      if (typeof clearTimeout === 'function') clearTimeout(hideTimer);
      hideTimer = schedule(() => toast.classList.remove('is-visible'), TOAST_MS);
    };

    const showLine = () => {
      if (!line) return;
      const {text, link} = logbookLine(found.size, total, unlock, signedIn);
      line.textContent = '';
      if (link) {
        const a = doc.createElement('a');
        a.href = '/logbook';
        a.textContent = text;
        line.appendChild(a);
      } else {
        line.textContent = text;
      }
    };

    // Record a find. Resolves to the notice line when it's new for this pilot, or '' when it isn't.
    const record = async id => {
      if (!EGGS[id]) return '';
      let fresh = !found.has(id);
      let opened = false;
      if (signedIn) {
        if (!fresh) return '';
        const res = await post('/logbook/found', {eggs: [id]});
        if (!res || res.error || !res.found) return '';
        fresh = res.new.includes(id);
        opened = !!res.opened;
        found = new Set(res.found);
      } else if (fresh) {
        found.add(id);
      }
      writeStore(storage, [...found]);
      if (!fresh) return '';
      showLine();
      const count = `Logbook: ${found.size} of ${total}.`;
      if (opened) return `${count} Your logbook is open: it’s linked in the footer.`;
      if (!signedIn && found.size >= unlock) return `${count} Sign in to open your logbook.`;
      if (!signedIn) return `${count} Sign in to keep it.`;
      return count;
    };
    // An egg with its own line shows it, plus the logbook notice the first time; a quiet egg only shows the notice.
    const egg = async (id, text) => {
      const notice = await record(id);
      if (text) say(text, notice ? `Easter egg found: ${EGGS[id]}. ${notice}` : '');
      else if (notice) say(`Easter egg found: ${EGGS[id]}`, notice);
    };
    report = id => { egg(id); };

    // Signed in with finds from a signed-out visit in this browser: add them to the logbook, quietly.
    if (signedIn) {
      const local = readStore(storage).filter(id => !found.has(id));
      if (local.length) post('/logbook/found', {eggs: local}).then(res => {
        if (res && res.found) { found = new Set(res.found); writeStore(storage, [...found]); showLine(); }
      });
      else writeStore(storage, [...found]);
    }
    showLine();

    // The footer's flight tip is static humour already, so swapping its text never hides real information.
    const tip = doc.querySelector('[data-flight-tip]');
    const key = footerKey(now());
    if (tip && key) {
      tip.textContent = footerLine(now());
      egg(LINE_EGG[key]);
    }

    const konami = konamiTracker();
    const o7 = o7Tracker();
    doc.addEventListener('keydown', event => {
      if (event.ctrlKey || event.metaKey || event.altKey || typing(event.target)) return;
      const k = event.key || '';
      if (konami(k)) egg('konami', LINES.konami);
      else if (o7(k)) egg('o7', LINES.o7);
    });

    const logo = doc.querySelector('.site-footer .footmark');
    if (logo) {
      const clicks = burst(LOGO_CLICKS, LOGO_WINDOW_MS);
      logo.addEventListener('click', () => { if (clicks(now().getTime())) egg('logo', LINES.logo); });
    }

    // Flipping the theme back and forth: astracore.js does the switch, this only notices.
    const toggle = doc.getElementById && doc.getElementById('theme-toggle');
    if (toggle && toggle.addEventListener) {
      const flips = burst(THEME_FLIPS, THEME_WINDOW_MS);
      toggle.addEventListener('click', () => { if (flips(now().getTime())) egg('theme_flip', LINES.themeFlip); });
    }

    // Tooltips that are eggs themselves count once they've had time to show: a pointer resting on them, or focus.
    // data-egg-when="dark" limits one to the dark theme (the flashbang warning only shows there).
    const hovers = doc.querySelectorAll ? doc.querySelectorAll('[data-egg-hover]') : [];
    Array.prototype.forEach.call(hovers, el => {
      let timer = null;
      const id = el.getAttribute('data-egg-hover');
      const fits = () => el.getAttribute('data-egg-when') !== 'dark' || doc.documentElement.dataset.theme !== 'light';
      const start = () => { if (timer === null && fits()) timer = schedule(() => { timer = null; egg(id); }, HOVER_MS); };
      const stop = () => { if (timer !== null && typeof clearTimeout === 'function') clearTimeout(timer); timer = null; };
      el.addEventListener('pointerenter', start);
      el.addEventListener('pointerleave', stop);
      el.addEventListener('focus', () => { if (fits()) egg(id); });
    });

    // Once per page, after an hour on it.
    schedule(() => egg('long_session', LINES.longSession), LONG_SESSION_MS);

    early.splice(0).forEach(id => egg(id));
    return {say, egg, record, found: () => [...found]};
  }

  const api = {KONAMI, LINES, EGGS, LOGO_CLICKS, THEME_FLIPS, LONG_SESSION_MS, HOVER_MS, STORE_KEY, isDowntime,
    isEveBirthday, yc, footerKey, footerLine, logbookLine, konamiTracker, o7Tracker, burst, init};
  if (typeof window !== 'undefined') window.AstraEggs = api;
  if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('DOMContentLoaded', () => {
      let storage;
      try { storage = window.localStorage; } catch (e) { storage = null; }
      const token = document.querySelector('meta[name="csrf-token"]');
      const eggs = init(document, () => new Date(), (fn, ms) => setTimeout(fn, ms), {
        storage: storage || undefined,
        post: token && window.AC && window.AC.post ? (url, body) => window.AC.post(url, body) : null,
      });
      // For pilots who read the source: say it back in the console.
      window.o7 = () => { eggs.egg('console'); return 'o7. Logged.'; };
      if (typeof console !== 'undefined' && console.info)
        console.info('o7, capsuleer. Reading the source? AstraCore is open: /project. Type o7() to say it back.');
    });
  }
})();
