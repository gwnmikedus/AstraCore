// Guards the intentional easter eggs and the capsuleer's logbook (docs/easter-eggs.md) so a cleanup can't remove
// them silently.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('src/astracore/static/js/easter-eggs.js', 'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));

function load() {
  const context = vm.createContext({window: {}});
  vm.runInContext(source, context);
  return context.window.AstraEggs;
}

function element(extra = {}) {
  const classes = new Set();
  return {attrs: {}, children: [], dataset: {}, listeners: {},
    setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k] ?? null; },
    appendChild(child) { this.children.push(child); },
    addEventListener(type, fn) { this.listeners[type] = fn; },
    classList: {add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c)}, ...extra};
}

function fakeDoc({tip = {textContent: 'Fly safe.'}, logo = null, toggle = null, logbook = null, hovers = [], theme = 'dark'} = {}) {
  const listeners = {};
  const appended = [];
  return {listeners, appended, tip, logo, documentElement: {dataset: {theme}},
    querySelector: sel => ({'[data-flight-tip]': tip, '.site-footer .footmark': logo, '[data-logbook]': logbook})[sel] ?? null,
    querySelectorAll: sel => (sel === '[data-egg-hover]' ? hovers : []),
    addEventListener: (type, fn) => { listeners[type] = fn; },
    getElementById: id => (id === 'theme-toggle' ? toggle : null),
    createElement: tag => element({tagName: tag.toUpperCase()}),
    body: {appendChild: el => appended.push(el)}};
}

function memoryStorage(initial = null) {
  const data = {ac_logbook: initial};
  return {data, getItem: k => data[k] ?? null, setItem: (k, v) => { data[k] = v; }};
}

const at = iso => () => new Date(iso);
const quiet = () => 0;

test('the theme switch warns about a flashbang before going light', () => {
  const nav = fs.readFileSync('src/astracore/templates/_navigation.html', 'utf8');
  const js = fs.readFileSync('src/astracore/static/js/astracore.js', 'utf8');
  assert.match(nav, /<strong>Flashbang warning<\/strong>/);
  assert.match(js, /dark: \['Flashbang warning', 'Light theme ahead\. Shield your eyes\.'\]/);
  assert.match(js, /light: \['Rest your eyes', /);
  assert.match(nav, /aria-label="Switch to light theme"/, 'the accessible name stays plain');
  assert.match(nav, /data-egg-hover="flashbang" data-egg-when="dark"/);
});

test('calendar lines show only at their time', () => {
  const eggs = load();
  assert.equal(eggs.footerLine(new Date('2026-11-28T11:05:00Z')), eggs.LINES.downtime);
  assert.equal(eggs.footerLine(new Date('2026-11-28T11:30:00Z')), null);
  assert.equal(eggs.footerLine(new Date('2026-11-28T10:59:00Z')), null);
  assert.equal(eggs.footerLine(new Date('2027-05-06T18:00:00Z')), eggs.LINES.birthday);
  assert.equal(eggs.footerLine(new Date('2027-05-07T18:00:00Z')), null);
  assert.equal(eggs.footerLine(new Date('2027-04-01T09:00:00Z')), eggs.LINES.aprilFools);
  assert.equal(eggs.footerLine(new Date('2026-12-25T09:00:00Z')), eggs.LINES.holidays);
  assert.equal(eggs.footerLine(new Date('2026-12-27T09:00:00Z')), null);
  assert.equal(eggs.footerLine(new Date('2027-01-01T09:00:00Z')), 'New year, new extractor cycle. Fly safe in YC 129.');
  assert.equal(eggs.yc(new Date('2026-06-01T00:00:00Z')), 128);
});

test('the footer tip changes during downtime and logs the find', async () => {
  const eggs = load();
  const calm = fakeDoc();
  eggs.init(calm, at('2026-11-28T15:00:00Z'), quiet);
  assert.equal(calm.tip.textContent, 'Fly safe.');
  const dt = fakeDoc();
  const storage = memoryStorage();
  eggs.init(dt, at('2026-11-28T11:10:00Z'), quiet, {storage});
  assert.equal(dt.tip.textContent, eggs.LINES.downtime);
  await settle();
  assert.deepEqual(JSON.parse(storage.data.ac_logbook), ['downtime']);
  assert.equal(dt.appended[0].textContent, 'Easter egg found: Downtime');
  assert.doesNotThrow(() => eggs.init(fakeDoc({tip: null}), at('2026-11-28T11:10:00Z'), quiet));
});

test('the Konami code shows one polite, click-through toast that hides itself', async () => {
  const eggs = load();
  const doc = fakeDoc();
  const timers = [];
  eggs.init(doc, at('2026-11-28T15:00:00Z'), fn => timers.push(fn));
  timers.length = 0;
  for (const key of eggs.KONAMI.slice(0, -1)) doc.listeners.keydown({key, target: {tagName: 'BODY'}});
  await settle();
  assert.equal(doc.appended.length, 0);
  doc.listeners.keydown({key: 'A', target: {tagName: 'BODY'}});
  await settle();
  assert.equal(doc.appended.length, 1);
  const toast = doc.appended[0];
  assert.equal(toast.className, 'egg-toast');
  assert.equal(toast.attrs.role, 'status');
  assert.equal(toast.attrs['aria-live'], 'polite');
  assert.equal(toast.textContent, eggs.LINES.konami);
  assert.match(toast.children[0].textContent, /^Easter egg found: Cheat code\. Logbook: 1 of 15\./);
  assert.ok(toast.classList.contains('is-visible'));
  timers.at(-1)();
  assert.ok(!toast.classList.contains('is-visible'));
});

test('the Konami code is ignored while typing in a field and survives a stray key', async () => {
  const eggs = load();
  const doc = fakeDoc();
  eggs.init(doc, at('2026-11-28T15:00:00Z'), quiet);
  for (const key of eggs.KONAMI) doc.listeners.keydown({key, target: {tagName: 'INPUT'}});
  await settle();
  assert.equal(doc.appended.length, 0);
  const track = eggs.konamiTracker();
  ['ArrowUp', 'ArrowUp', 'ArrowUp'].forEach(k => track(k));
  assert.equal(eggs.KONAMI.slice(2).map(track).at(-1), true);
});

test('five quick clicks on the footer wordmark say o7', async () => {
  const eggs = load();
  const logo = element();
  const doc = fakeDoc({logo});
  let t = Date.parse('2026-11-28T15:00:00Z');
  eggs.init(doc, () => new Date(t), quiet);
  for (let i = 0; i < eggs.LOGO_CLICKS - 1; i++) { logo.listeners.click(); t += 200; }
  await settle();
  assert.equal(doc.appended.length, 0);
  logo.listeners.click();
  await settle();
  assert.equal(doc.appended[0].textContent, eggs.LINES.logo);
  assert.match(eggs.LINES.logo, /^o7/);
});

test('typing o7 outside a field salutes back', async () => {
  const eggs = load();
  const doc = fakeDoc();
  eggs.init(doc, at('2026-11-28T15:00:00Z'), quiet);
  doc.listeners.keydown({key: 'o', target: {tagName: 'INPUT'}});
  doc.listeners.keydown({key: '7', target: {tagName: 'INPUT'}});
  await settle();
  assert.equal(doc.appended.length, 0);
  doc.listeners.keydown({key: 'O', target: {tagName: 'BODY'}});
  doc.listeners.keydown({key: '7', target: {tagName: 'BODY'}});
  await settle();
  assert.equal(doc.appended[0].textContent, eggs.LINES.o7);
});

test('flipping the theme back and forth draws a complaint, a normal switch does not', async () => {
  const eggs = load();
  const toggle = element();
  const doc = fakeDoc({toggle});
  let t = Date.parse('2026-11-28T15:00:00Z');
  eggs.init(doc, () => new Date(t), quiet);
  toggle.listeners.click(); t += 60000; toggle.listeners.click();
  await settle();
  assert.equal(doc.appended.length, 0);
  for (let i = 0; i < eggs.THEME_FLIPS - 1; i++) { toggle.listeners.click(); t += 500; }
  await settle();
  assert.equal(doc.appended[0].textContent, eggs.LINES.themeFlip);
});

test('an hour on one page gets one nudge', async () => {
  const eggs = load();
  const doc = fakeDoc();
  const timers = [];
  eggs.init(doc, at('2026-11-28T15:00:00Z'), (fn, ms) => timers.push({fn, ms}));
  timers.find(x => x.ms === eggs.LONG_SESSION_MS).fn();
  await settle();
  assert.equal(doc.appended[0].textContent, eggs.LINES.longSession);
});

test('tooltip eggs count after a pointer rests on them, and the flashbang only in the dark', async () => {
  const eggs = load();
  const year = element({attrs: {'data-egg-hover': 'yc_year'}});
  const flash = element({attrs: {'data-egg-hover': 'flashbang', 'data-egg-when': 'dark'}});
  const doc = fakeDoc({hovers: [year, flash], theme: 'light'});
  const timers = [];
  const storage = memoryStorage();
  eggs.init(doc, at('2026-11-28T15:00:00Z'), (fn, ms) => timers.push({fn, ms}), {storage});
  timers.length = 0;
  year.listeners.pointerenter();
  year.listeners.pointerleave();
  flash.listeners.pointerenter();
  assert.equal(timers.length, 1, 'no flashbang timer in the light theme');
  assert.equal(timers[0].ms, eggs.HOVER_MS);
  timers[0].fn();
  await settle();
  assert.deepEqual(JSON.parse(storage.data.ac_logbook), ['yc_year']);
});

test('signed out: finds stay in this browser, the footer line counts and the second find of one egg is quiet', async () => {
  const eggs = load();
  const logbook = element({dataset: {total: '15', unlock: '3', found: ''}});
  const doc = fakeDoc({logbook});
  const storage = memoryStorage(JSON.stringify(['o7', 'logo']));
  const api = eggs.init(doc, at('2026-11-28T15:00:00Z'), quiet, {storage});
  assert.equal(logbook.textContent, 'Capsuleer’s logbook: 2 of 15 found. Find 3 to open it.');
  await api.egg('konami');
  assert.equal(logbook.textContent, 'Capsuleer’s logbook: 3 of 15 found. Sign in to open it.');
  assert.match(doc.appended[0].children[0].textContent, /Sign in to open your logbook\./);
  doc.appended.length = 0;
  await api.egg('konami');
  assert.equal(doc.appended.length, 0);
  assert.equal(eggs.logbookLine(0, 15, 3, false).text, 'Rumour has it 15 things are hidden in AstraCore.');
});

test('signed in: finds go to the server, the logbook link appears once it opens, and old local finds sync', async () => {
  const eggs = load();
  const logbook = element({dataset: {total: '15', unlock: '3', found: 'o7,logo', signedIn: ''}});
  const doc = fakeDoc({logbook});
  const posts = [];
  const server = new Set(['o7', 'logo']);
  const post = async (url, body) => {
    posts.push([url, [...body.eggs]]);
    const fresh = body.eggs.filter(id => !server.has(id));
    const before = server.size;
    fresh.forEach(id => server.add(id));
    return {new: fresh, found: [...server], count: server.size, total: 15, open: server.size >= 3,
      opened: before < 3 && server.size >= 3};
  };
  const storage = memoryStorage(JSON.stringify(['yc_year']));
  const api = eggs.init(doc, at('2026-11-28T15:00:00Z'), quiet, {storage, post});
  await settle();
  assert.deepEqual(posts[0], ['/logbook/found', ['yc_year']], 'a signed-out find from this browser is synced');
  assert.equal(logbook.children[0].tagName, 'A');
  assert.equal(logbook.children[0].href, '/logbook');
  assert.equal(doc.appended.length, 0, 'syncing is quiet');
  await api.egg('o7');
  assert.equal(posts.length, 1, 'a known find is not posted again');
  await api.egg('konami');
  assert.deepEqual(posts[1], ['/logbook/found', ['konami']]);
  assert.match(doc.appended[0].children[0].textContent, /Logbook: 4 of 15\.$/);
});

test('the JS egg list matches the server catalog and the hint tip counts them right', () => {
  const eggs = load();
  const py = fs.readFileSync('src/astracore/core/logbook.py', 'utf8');
  const ids = [...py.matchAll(/\{"id": "([a-z0-9_]+)", "title": "([^"]+)"/g)].map(m => [m[1], m[2].replace("'", '’')]);
  assert.equal(ids.length, 15);
  assert.deepEqual(Object.entries(eggs.EGGS).sort(), ids.sort());
  const tips = fs.readFileSync('src/astracore/static/js/flight-tips.js', 'utf8');
  assert.match(tips, /Fifteen, rumour has it\./);
  assert.match(tips, /new CustomEvent\('astracore:egg', \{detail: 'rare_tip'\}\)/);
});

test('easter eggs stay inside the CSP and the brand rules', () => {
  const base = fs.readFileSync('src/astracore/templates/base.html', 'utf8');
  assert.match(base, /<script src="\{\{ asset\('js\/easter-eggs\.js'\) \}\}" defer><\/script>/);
  assert.match(base, /data-egg-hover="yc_year"/);
  assert.match(base, /data-logbook/);
  assert.doesNotMatch(source, /innerHTML|\.style\.|https?:\/\//);
  for (const line of Object.values(load().LINES)) assert.doesNotMatch(line, /\p{Extended_Pictographic}/u);
  const css = fs.readFileSync('src/astracore/static/css/astracore.css', 'utf8');
  const rule = css.match(/\.egg-toast \{[^}]*\}/)[0];
  assert.match(rule, /position: fixed/);
  assert.match(rule, /pointer-events: none/);
  assert.ok(fs.readFileSync('docs/easter-eggs.md', 'utf8').includes('They are intentional'));
});
