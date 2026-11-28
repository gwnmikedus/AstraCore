// Guards the intentional easter eggs (docs/easter-eggs.md) so a cleanup can't remove them silently.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('src/astracore/static/js/easter-eggs.js', 'utf8');

function load() {
  const context = vm.createContext({window: {}});
  vm.runInContext(source, context);
  return context.window.AstraEggs;
}

function fakeDoc({tip = {textContent: 'Fly safe.'}, logo = null} = {}) {
  const listeners = {};
  const appended = [];
  const make = () => {
    const classes = new Set();
    const el = {attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, classList: {
      add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c)}};
    return el;
  };
  return {listeners, appended, tip, logo,
    querySelector: sel => sel === '[data-flight-tip]' ? tip : sel === '.site-footer .footmark' ? logo : null,
    addEventListener: (type, fn) => { listeners[type] = fn; },
    createElement: make,
    body: {appendChild: el => appended.push(el)}};
}

const at = iso => () => new Date(iso);

test('the theme switch warns about a flashbang before going light', () => {
  const nav = fs.readFileSync('src/astracore/templates/_navigation.html', 'utf8');
  const js = fs.readFileSync('src/astracore/static/js/astracore.js', 'utf8');
  assert.match(nav, /<strong>Flashbang warning<\/strong>/);
  assert.match(js, /dark: \['Flashbang warning', 'Light theme ahead\. Shield your eyes\.'\]/);
  assert.match(js, /light: \['Rest your eyes', /);
  assert.match(nav, /aria-label="Switch to light theme"/, 'the accessible name stays plain');
});

test('downtime and New Eden birthday lines show only at their time', () => {
  const eggs = load();
  assert.equal(eggs.footerLine(new Date('2026-11-28T11:05:00Z')), eggs.LINES.downtime);
  assert.equal(eggs.footerLine(new Date('2026-11-28T11:30:00Z')), null);
  assert.equal(eggs.footerLine(new Date('2026-11-28T10:59:00Z')), null);
  assert.equal(eggs.footerLine(new Date('2027-05-06T18:00:00Z')), eggs.LINES.birthday);
  assert.equal(eggs.footerLine(new Date('2027-05-07T18:00:00Z')), null);
  assert.equal(eggs.yc(new Date('2026-06-01T00:00:00Z')), 128);
});

test('the footer tip changes only during downtime and stays plain text', () => {
  const eggs = load();
  const quiet = fakeDoc();
  eggs.init(quiet, at('2026-11-28T15:00:00Z'), () => 0);
  assert.equal(quiet.tip.textContent, 'Fly safe.');
  const dt = fakeDoc();
  eggs.init(dt, at('2026-11-28T11:10:00Z'), () => 0);
  assert.equal(dt.tip.textContent, eggs.LINES.downtime);
  assert.doesNotThrow(() => eggs.init(fakeDoc({tip: null}), at('2026-11-28T11:10:00Z'), () => 0));
});

test('the Konami code shows one polite, click-through toast that hides itself', () => {
  const eggs = load();
  const doc = fakeDoc();
  const timers = [];
  eggs.init(doc, at('2026-11-28T15:00:00Z'), fn => timers.push(fn));
  for (const key of eggs.KONAMI.slice(0, -1)) doc.listeners.keydown({key, target: {tagName: 'BODY'}});
  assert.equal(doc.appended.length, 0);
  doc.listeners.keydown({key: 'A', target: {tagName: 'BODY'}});
  assert.equal(doc.appended.length, 1);
  const toast = doc.appended[0];
  assert.equal(toast.className, 'egg-toast');
  assert.equal(toast.attrs.role, 'status');
  assert.equal(toast.attrs['aria-live'], 'polite');
  assert.equal(toast.textContent, eggs.LINES.konami);
  assert.ok(toast.classList.contains('is-visible'));
  timers.at(-1)();
  assert.ok(!toast.classList.contains('is-visible'));
});

test('the Konami code is ignored while typing in a field and survives a stray key', () => {
  const eggs = load();
  const doc = fakeDoc();
  eggs.init(doc, at('2026-11-28T15:00:00Z'), () => 0);
  for (const key of eggs.KONAMI) doc.listeners.keydown({key, target: {tagName: 'INPUT'}});
  assert.equal(doc.appended.length, 0);
  const track = eggs.konamiTracker();
  ['ArrowUp', 'ArrowUp', 'ArrowUp'].forEach(k => track(k));
  assert.equal(eggs.KONAMI.slice(2).map(track).at(-1), true);
});

test('five quick clicks on the footer wordmark say o7', () => {
  const eggs = load();
  let click;
  const logo = {addEventListener: (type, fn) => { click = fn; }};
  const doc = fakeDoc({logo});
  let t = Date.parse('2026-11-28T15:00:00Z');
  eggs.init(doc, () => new Date(t), () => 0);
  for (let i = 0; i < eggs.LOGO_CLICKS - 1; i++) { click(); t += 200; }
  assert.equal(doc.appended.length, 0);
  click();
  assert.equal(doc.appended[0].textContent, eggs.LINES.logo);
  assert.match(eggs.LINES.logo, /^o7/);
});

test('easter eggs stay inside the CSP and the brand rules', () => {
  const base = fs.readFileSync('src/astracore/templates/base.html', 'utf8');
  assert.match(base, /<script src="\{\{ asset\('js\/easter-eggs\.js'\) \}\}" defer><\/script>/);
  assert.doesNotMatch(source, /innerHTML|\.style\.|https?:\/\//);
  for (const line of Object.values(load().LINES)) assert.doesNotMatch(line, /\p{Extended_Pictographic}/u);
  const css = fs.readFileSync('src/astracore/static/css/astracore.css', 'utf8');
  const rule = css.match(/\.egg-toast \{[^}]*\}/)[0];
  assert.match(rule, /position: fixed/);
  assert.match(rule, /pointer-events: none/);
  assert.ok(fs.readFileSync('docs/easter-eggs.md', 'utf8').includes('They are intentional'));
});
