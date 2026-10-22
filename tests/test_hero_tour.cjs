const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const source = readFileSync(path.join(__dirname, '../src/astracore/static/js/hero-tour.js'), 'utf8');

function deferred() {
  let resolve;
  const promise = new Promise(r => { resolve = r; });
  return {promise, resolve};
}

function element(extra = {}) {
  const attributes = new Map();
  const events = new Map();
  const classes = new Set();
  return {
    attributes, events, classes, dataset: {}, style: {setProperty() {}}, hidden: false,
    classList: {add: c => classes.add(c), remove: (...cs) => cs.forEach(c => classes.delete(c)), contains: c => classes.has(c)},
    setAttribute: (name, value) => attributes.set(name, value),
    hasAttribute: name => attributes.has(name),
    toggleAttribute(name, enabled) { if (enabled) attributes.set(name, ''); else attributes.delete(name); },
    addEventListener(name, listener) { events.set(name, listener); },
    querySelector: () => element(),
    querySelectorAll: () => [],
    contains: () => false,
    focus() {},
    getAnimations: () => [],
    ...extra,
  };
}

// A tour of four scenes; each node's own animations are whatever the test puts in `animations`.
function tour({reducedMotion = false} = {}) {
  const animations = new Map();
  const node = (key, index) => {
    const n = element({getAnimations: () => animations.get(n) || []});
    n.dataset[key] = String(index);
    n.hidden = index !== 0;
    return n;
  };
  const copies = [0, 1, 2, 3].map(i => node('heroCopy', i));
  const scenes = [0, 1, 2, 3].map(i => node('heroScene', i));
  const tabs = [0, 1, 2, 3].map(() => element());
  const root = element({
    querySelectorAll: selector => ({'[data-hero-copy]': copies, '[data-hero-scene]': scenes, '[data-hero-tab]': tabs})[selector] || [],
    querySelector: () => element(),
  });
  const timers = new Map();
  let timerId = 0;
  const document = element({querySelector: () => root, fonts: {ready: new Promise(() => {})}});
  const window = {matchMedia: () => ({matches: reducedMotion, addEventListener() {}})};
  const context = {
    document, window,
    IntersectionObserver: class { observe() {} },
    ResizeObserver: class { observe() {} },
    requestAnimationFrame: () => 1,
    setTimeout(callback, delay) { timers.set(++timerId, {callback, delay}); return timerId; },
    clearTimeout(id) { timers.delete(id); },
  };
  vm.runInNewContext(source, context);
  return {copies, scenes, tabs, timers, animations, show: i => tabs[i].events.get('click')()};
}

function animation() {
  const done = deferred();
  return {finish: done.resolve, finished: done.promise, effect: {getComputedTiming: () => ({iterations: 1})}};
}

const settled = () => new Promise(r => setImmediate(r));

test('the old scene leaves when its animations finish, not on a timer of the same length', async () => {
  const ui = tour();
  const leaving = animation(), entering = animation();
  const looping = {finished: new Promise(() => {}), effect: {getComputedTiming: () => ({iterations: Infinity})}};
  ui.animations.set(ui.scenes[0], [leaving, looping]);
  ui.animations.set(ui.scenes[1], [entering]);
  ui.show(1);
  assert.equal(ui.scenes[0].hidden, false, 'the old scene stays while it animates out');
  assert.ok(ui.scenes[0].classes.has('is-leaving'));
  assert.ok(ui.scenes[1].classes.has('is-entering'));
  assert.ok([...ui.timers.values()].every(timer => timer.delay > 550), 'any timer is only a fallback');
  leaving.finish();
  await settled();
  assert.equal(ui.scenes[0].hidden, false, 'waits for every finite animation');
  entering.finish();
  await settled();
  assert.equal(ui.scenes[0].hidden, true, 'an infinite animation is not waited for');
  assert.equal(ui.scenes[1].hidden, false);
  assert.equal(ui.scenes[1].classes.has('is-entering'), false);
  assert.equal(ui.timers.size, 0, 'the fallback is cleared');
});

test('the fallback settles the scenes when the animations never report their end', () => {
  const ui = tour();
  ui.animations.set(ui.scenes[0], [animation()]);
  ui.show(1);
  for (const [id, timer] of ui.timers) { ui.timers.delete(id); timer.callback(); }
  assert.equal(ui.scenes[0].hidden, true);
  assert.equal(ui.copies[0].hidden, true);
});

test('an older transition finishing cannot hide the scene showing now', async () => {
  const ui = tour();
  const first = animation();
  ui.animations.set(ui.scenes[1], [first]);
  ui.show(1);
  ui.animations.set(ui.scenes[1], []);
  const second = animation();
  ui.animations.set(ui.scenes[2], [second]);
  ui.show(2);
  first.finish();
  await settled();
  assert.equal(ui.scenes[1].hidden, false, 'scene 1 is still leaving');
  assert.equal(ui.scenes[2].hidden, false);
  second.finish();
  await settled();
  assert.equal(ui.scenes[1].hidden, true);
  assert.equal(ui.scenes[2].hidden, false);
});

test('reduced motion switches scenes at once without animating', () => {
  const ui = tour({reducedMotion: true});
  ui.show(1);
  assert.equal(ui.scenes[0].hidden, true);
  assert.equal(ui.scenes[1].hidden, false);
  assert.equal(ui.scenes[1].classes.has('is-entering'), false);
  assert.equal(ui.timers.size, 0);
});
