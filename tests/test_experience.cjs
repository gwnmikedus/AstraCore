const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const source = readFileSync(path.join(__dirname, '../src/astracore/static/js/experience.js'), 'utf8');

function experience({reducedMotion = false, supported = true, guided = false, marketing = false, parallax = false, width = 1366} = {}) {
  const animations = [];
  const observers = [];
  const mutations = [];
  const sections = [{}, {}];
  const question = guided ? {getBoundingClientRect: () => ({top: 120, bottom: 620})} : null;
  if (question) sections.push(question);
  for (const section of sections) {
    section.contains = () => false;
    section.animate = (frames, options) => {
      const animation = {element: section, frames, options, cancelled: false,
        cancel() { this.cancelled = true; this.oncancel?.(); }};
      animations.push(animation);
      return animation;
    };
  }
  const scenes = parallax ? ['hero', 'section'].map(kind => {
    const values = new Map();
    const bounds = {top: 100, height: 660};
    return {dataset: {parallax: kind}, bounds,
      style: {setProperty: (name, value) => values.set(name, value), removeProperty: name => values.delete(name)},
      values, getBoundingClientRect: () => bounds, parentElement: {getBoundingClientRect: () => bounds}};
  }) : [];
  const frames = new Map();
  let frameId = 0;
  function events() {
    const listeners = new Map();
    return {addEventListener: (event, listener) => listeners.set(event, listener),
      removeEventListener: event => listeners.delete(event), dispatch: event => listeners.get(event)?.()};
  }
  let preferenceListener;
  const preference = {matches: reducedMotion, addEventListener: (event, listener) => preferenceListener = listener};
  class IntersectionObserver {
    constructor(callback, options) { this.callback = callback; this.options = options; this.observed = new Set(); observers.push(this); }
    observe(element) { this.observed.add(element); }
    unobserve(element) { this.observed.delete(element); }
    disconnect() { this.observed.clear(); this.disconnected = true; }
    intersect(target, isIntersecting = true) { this.callback([{target, isIntersecting}]); }
  }
  class MutationObserver {
    constructor(callback) { this.callback = callback; mutations.push(this); }
    observe(target, options) { this.target = target; this.options = options; }
    disconnect() { this.disconnected = true; }
  }
  const main = {animate() {}, querySelectorAll: selector => selector === '[data-parallax]' ? scenes : sections,
    querySelector: () => question};
  const window = {...events(), IntersectionObserver: supported ? IntersectionObserver : null, MutationObserver,
    innerHeight: 800, innerWidth: width, matchMedia: () => preference,
    requestAnimationFrame: callback => {frames.set(++frameId, callback); return frameId;},
    cancelAnimationFrame: id => frames.delete(id)};
  const document = {...events(), getElementById: () => main, hidden: false,
    body: {classList: {contains: () => marketing}}};
  vm.runInNewContext(source, {window, IntersectionObserver, MutationObserver, document});
  return {animations, observers, mutations, sections, question, scenes, frames, window, document,
    flushFrame() { for (const [id, callback] of [...frames]) {frames.delete(id); callback();} },
    changeMotion(matches) { preference.matches = matches; preferenceListener?.(); }};
}

test('sections animate once when entering view, without altering unseen content', () => {
  const ui = experience();
  const observer = ui.observers[0];
  assert.equal(observer.observed.size, 2);
  assert.equal(ui.animations.length, 0);
  observer.intersect(ui.sections[0], false);
  assert.equal(ui.animations.length, 0);
  observer.intersect(ui.sections[0]);
  assert.equal(ui.animations.length, 1);
  assert.equal(observer.observed.has(ui.sections[0]), false);
  observer.intersect(ui.sections[0]);
  assert.equal(ui.animations.length, 1);
  assert.equal(ui.animations[0].options.duration, 300);
  assert.equal(ui.animations[0].options.fill, undefined);
  assert.ok(ui.animations[0].frames[0].opacity > 0);
});

test('reduced motion starts without observers and enabling motion watches unseen sections', () => {
  const ui = experience({reducedMotion: true, guided: true});
  assert.equal(ui.observers.length, 0);
  assert.equal(ui.mutations.length, 0);
  assert.equal(ui.animations.length, 0);
  ui.changeMotion(false);
  assert.equal(ui.observers.length, 1);
  assert.equal(ui.mutations.length, 1);
  assert.equal(ui.observers[0].observed.size, 3);
});

test('changing to reduced motion disconnects observation and cancels active arrivals', () => {
  const ui = experience({guided: true});
  ui.observers[0].intersect(ui.sections[0]);
  ui.changeMotion(true);
  assert.equal(ui.observers[0].disconnected, true);
  assert.equal(ui.mutations[0].disconnected, true);
  assert.equal(ui.animations[0].cancelled, true);
  ui.observers[0].intersect(ui.sections[1]);
  ui.mutations[0].callback();
  assert.equal(ui.animations.length, 1);
  ui.changeMotion(false);
  assert.equal(ui.observers[1].observed.has(ui.sections[0]), false);
  assert.equal(ui.observers[1].observed.has(ui.sections[1]), true);
});

test('replaced guided questions arrive when visible but do not animate offscreen updates', () => {
  const ui = experience({guided: true});
  const mutation = ui.mutations[0];
  assert.equal(mutation.target, ui.question);
  assert.equal(mutation.options.childList, true);
  assert.equal(mutation.options.subtree, undefined);
  mutation.callback();
  assert.equal(ui.animations.length, 1);
  ui.observers[0].intersect(ui.question);
  assert.equal(ui.animations.length, 1);
  mutation.callback();
  assert.equal(ui.animations.length, 2);
  ui.question.getBoundingClientRect = () => ({top: 900, bottom: 1400});
  mutation.callback();
  assert.equal(ui.animations.length, 2);
});

test('unsupported arrival APIs leave the page untouched', () => {
  const ui = experience({supported: false});
  assert.equal(ui.observers.length, 0);
  assert.equal(ui.animations.length, 0);
});

test('marketing reveals stay visible longer while focused controls remain stationary', () => {
  const marketing = experience({marketing: true});
  const operational = experience();
  marketing.observers[0].intersect(marketing.sections[0]);
  operational.observers[0].intersect(operational.sections[0]);
  assert.ok(marketing.animations[0].options.duration > operational.animations[0].options.duration);
  marketing.sections[1].contains = () => true;
  marketing.observers[0].intersect(marketing.sections[1]);
  assert.equal(marketing.animations.length, 1);
});

test('parallax batches scroll frames, clamps travel and stops updating offscreen scenes', () => {
  const ui = experience({parallax: true});
  assert.equal(ui.frames.size, 0);
  const observer = ui.observers[1];
  observer.intersect(ui.scenes[0]);
  ui.window.dispatch('scroll');
  ui.window.dispatch('scroll');
  assert.equal(ui.frames.size, 1);
  ui.flushFrame();
  const before = Number.parseFloat(ui.scenes[0].values.get('--art-offset'));
  ui.scenes[0].bounds.top = -2000;
  ui.window.dispatch('scroll');
  ui.flushFrame();
  const after = Number.parseFloat(ui.scenes[0].values.get('--art-offset'));
  assert.ok(after > before);
  assert.ok(after < 50);
  observer.intersect(ui.scenes[0], false);
  ui.window.dispatch('scroll');
  assert.equal(ui.frames.size, 0);
  assert.equal(ui.scenes[1].values.size, 0);
});

test('reduced motion cancels pending scenery and resets artwork, then restores visible observation', () => {
  const ui = experience({parallax: true});
  ui.observers[1].intersect(ui.scenes[0]);
  ui.flushFrame();
  assert.equal(ui.scenes[0].values.size, 1);
  ui.window.dispatch('scroll');
  assert.equal(ui.frames.size, 1);
  ui.changeMotion(true);
  assert.equal(ui.frames.size, 0);
  assert.equal(ui.scenes[0].values.size, 0);
  ui.window.dispatch('scroll');
  assert.equal(ui.frames.size, 0);
  ui.changeMotion(false);
  assert.equal(ui.observers[3].observed.size, 2);
});

test('hidden pages pause scenery and mobile artwork has a smaller travel limit', () => {
  const ui = experience({parallax: true, width: 390});
  ui.scenes[0].bounds.top = -2000;
  ui.observers[1].intersect(ui.scenes[0]);
  ui.document.hidden = true;
  ui.document.dispatch('visibilitychange');
  assert.equal(ui.frames.size, 0);
  ui.window.dispatch('scroll');
  assert.equal(ui.frames.size, 0);
  ui.document.hidden = false;
  ui.document.dispatch('visibilitychange');
  ui.flushFrame();
  assert.ok(Number.parseFloat(ui.scenes[0].values.get('--art-offset')) <= 12);
});
