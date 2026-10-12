const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('src/astracore/templates/base.html', 'utf8');
const js = fs.readFileSync('src/astracore/static/js/astracore.js', 'utf8');
const initial = html.match(/<script nonce="{{ nonce }}">(.*?)<\/script>/s)[1];
const controls = js.slice(js.indexOf("    const tt = document.getElementById('theme-toggle');"), js.indexOf("    document.addEventListener('click', async e"));

function page(saved, light = false) {
  const root = {dataset: {theme: 'dark'}, toggleAttribute() {}, removeAttribute() {}};
  const meta = {content: '#0b0c0d'};
  const toggle = {setAttribute(name, value) {this[name] = value;}, querySelector() {return null;},
    classList: {add() {}, remove() {}}, addEventListener() {}};
  const listeners = {};
  const system = {matches: light, addEventListener(name, fn) {listeners.system = fn;}};
  const storage = {getItem() {return saved;}, setItem(key, value) {saved = value;}};
  const document = {documentElement: root, getElementById() {return toggle;}, querySelector() {return meta;}};
  const context = vm.createContext({document, localStorage: storage, matchMedia: () => system,
    window: {matchMedia: query => query.includes('color-scheme') ? system : {matches: true},
      addEventListener(name, fn) {listeners[name] = fn;}},
    getComputedStyle: () => ({getPropertyValue: () => root.dataset.theme === 'light' ? '#e7e3da' : '#0b0c0d'}),
    setTimeout: () => 0, clearTimeout() {}});
  vm.runInContext(initial, context);
  vm.runInContext(`(() => {${controls}})()`, context);
  return {root, meta, toggle, system, listeners};
}

test('first paint follows system theme without a saved choice and updates browser chrome', () => {
  const p = page(null, true);
  assert.equal(p.root.dataset.theme, 'light');
  assert.equal(p.meta.content, '#e7e3da');
  assert.equal(p.toggle['aria-label'], 'Switch to dark theme');
});

test('saved theme wins over the system and remains stable when the system changes', () => {
  const p = page('dark', true);
  p.system.matches = false; p.listeners.system();
  assert.equal(p.root.dataset.theme, 'dark');
  assert.equal(p.meta.content, '#0b0c0d');
});

test('unsaved theme follows system changes but manual toggle takes precedence', () => {
  const p = page(null, false);
  p.system.matches = true; p.listeners.system();
  assert.equal(p.meta.content, '#e7e3da');
  p.toggle.onclick();
  assert.equal(p.meta.content, '#0b0c0d');
  p.listeners.system();
  assert.equal(p.root.dataset.theme, 'dark');
});

test('cross-tab saved theme removal returns to the system theme', () => {
  const p = page('dark', true);
  p.listeners.storage({key: 'ac_theme', newValue: null});
  assert.equal(p.root.dataset.theme, 'light');
  assert.equal(p.meta.content, '#e7e3da');
});
