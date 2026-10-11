const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const source = readFileSync(path.join(__dirname, '../src/astracore/static/js/navigation.js'), 'utf8');

function element(parent = null) {
  const attributes = new Map();
  const events = new Map();
  return {
    parent, attributes, events,
    setAttribute: (name, value) => attributes.set(name, value),
    removeAttribute: name => attributes.delete(name),
    hasAttribute: name => attributes.has(name),
    toggleAttribute(name, enabled) { if (enabled) attributes.set(name, ''); else attributes.delete(name); },
    addEventListener(name, listener) { events.set(name, listener); },
    dispatch(name, event = {}) { return events.get(name)?.(event); },
    contains(target) { return target === this || Boolean(target?.parent && this.contains(target.parent)); },
    closest() { return null; },
  };
}

function navigation({reducedMotion = false, present = true} = {}) {
  const document = element();
  document.documentElement = element();
  const window = element();
  window.matchMedia = () => ({matches: reducedMotion});
  const menu = element();
  menu.open = false;
  const toggle = element(menu);
  let focused = null;
  toggle.focus = () => { focused = toggle; };
  const panel = element(menu);
  const label = element(menu);
  const backdrop = element(menu);
  const parts = {summary: toggle, '.menu-panel': panel, '[data-menu-label]': label, '[data-menu-backdrop]': backdrop};
  menu.querySelector = selector => parts[selector];
  document.querySelector = () => present ? menu : null;
  const timers = new Map();
  let timerId = 0;
  const context = {
    document, window,
    setTimeout(callback, delay) { timers.set(++timerId, {callback, delay}); return timerId; },
    clearTimeout(id) { timers.delete(id); },
  };
  vm.runInNewContext(source, context);
  return {
    document, window, menu, toggle, panel, label, backdrop, timers,
    get focused() { return focused; },
    clickToggle() {
      let prevented = false;
      toggle.dispatch('click', {preventDefault() { prevented = true; }});
      assert.equal(prevented, true);
    },
    finishClose() {
      for (const [id, timer] of timers) { timers.delete(id); timer.callback(); }
    },
  };
}

test('the disclosure opens from closed state and exposes its panel to the keyboard', () => {
  const ui = navigation();
  assert.equal(ui.panel.inert, true);
  assert.equal(ui.toggle.attributes.get('aria-expanded'), 'false');
  assert.equal(ui.document.documentElement.hasAttribute('data-menu-open'), false);
  ui.panel.scrollTop = 160;
  ui.clickToggle();
  assert.equal(ui.menu.open, true);
  assert.equal(ui.panel.inert, false);
  assert.equal(ui.panel.scrollTop, 0);
  assert.equal(ui.toggle.attributes.get('aria-expanded'), 'true');
  assert.equal(ui.toggle.attributes.get('aria-label'), 'Close AstraCore menu');
  assert.equal(ui.label.textContent, 'Close');
  assert.equal(ui.document.documentElement.hasAttribute('data-menu-open'), true);
});

test('Escape closes, restores disclosure focus, and keeps scroll locked through the exit', () => {
  const ui = navigation();
  ui.clickToggle();
  let prevented = false;
  ui.document.dispatch('keydown', {key: 'Escape', preventDefault() { prevented = true; }});
  assert.equal(prevented, true);
  assert.equal(ui.focused, ui.toggle);
  assert.equal(ui.panel.inert, true);
  assert.equal(ui.toggle.attributes.get('aria-expanded'), 'false');
  assert.equal(ui.menu.hasAttribute('data-closing'), true);
  assert.equal(ui.document.documentElement.hasAttribute('data-menu-open'), true);
  assert.equal([...ui.timers.values()][0].delay, 180);
  ui.finishClose();
  assert.equal(ui.menu.open, false);
  assert.equal(ui.document.documentElement.hasAttribute('data-menu-open'), false);
  assert.equal(ui.label.textContent, 'Menu');
});

test('outside clicks and keyboard focus leaving dismiss without stealing the new focus', () => {
  for (const event of ['click', 'focusin']) {
    const ui = navigation();
    ui.clickToggle();
    ui.document.dispatch(event, {target: element(ui.panel)});
    assert.equal(ui.menu.hasAttribute('data-closing'), false);
    ui.document.dispatch(event, {target: element()});
    assert.equal(ui.menu.hasAttribute('data-closing'), true);
    assert.equal(ui.focused, null);
    ui.finishClose();
    assert.equal(ui.menu.open, false);
  }
});

test('the backdrop restores focus and a selected destination dismisses without returning it', () => {
  const ui = navigation();
  ui.clickToggle();
  ui.backdrop.dispatch('click');
  assert.equal(ui.focused, ui.toggle);
  ui.finishClose();
  const destination = navigation();
  destination.clickToggle();
  destination.panel.dispatch('click', {target: {closest: () => element(destination.panel)}});
  assert.equal(destination.menu.hasAttribute('data-closing'), true);
  assert.equal(destination.focused, null);
});

test('rapid reopening cancels the pending close instead of hiding the reopened panel', () => {
  const ui = navigation();
  ui.clickToggle();
  ui.clickToggle();
  assert.equal(ui.timers.size, 1);
  ui.clickToggle();
  assert.equal(ui.timers.size, 0);
  ui.finishClose();
  assert.equal(ui.menu.open, true);
  assert.equal(ui.menu.hasAttribute('data-closing'), false);
  assert.equal(ui.panel.inert, false);
});

test('reduced motion closes immediately without a delayed invisible scroll lock', () => {
  const ui = navigation({reducedMotion: true});
  ui.clickToggle();
  ui.clickToggle();
  assert.equal(ui.menu.open, false);
  assert.equal(ui.menu.hasAttribute('data-closing'), false);
  assert.equal(ui.timers.size, 0);
  assert.equal(ui.document.documentElement.hasAttribute('data-menu-open'), false);
});

test('browser history restoration clears pending transitions and leaves navigation usable', () => {
  const ui = navigation();
  ui.clickToggle();
  ui.clickToggle();
  ui.window.dispatch('pageshow');
  assert.equal(ui.timers.size, 0);
  assert.equal(ui.menu.open, false);
  assert.equal(ui.panel.inert, true);
  assert.equal(ui.document.documentElement.hasAttribute('data-menu-open'), false);
  ui.clickToggle();
  assert.equal(ui.menu.open, true);
});

test('native toggle events synchronize the accessible disclosure state', () => {
  const ui = navigation();
  ui.menu.open = true;
  ui.menu.dispatch('toggle');
  assert.equal(ui.panel.inert, false);
  assert.equal(ui.toggle.attributes.get('aria-expanded'), 'true');
  ui.menu.open = false;
  ui.menu.dispatch('toggle');
  assert.equal(ui.panel.inert, true);
  assert.equal(ui.toggle.attributes.get('aria-expanded'), 'false');
});

test('pages without navigation initialize safely', () => {
  assert.doesNotThrow(() => navigation({present: false}));
});
