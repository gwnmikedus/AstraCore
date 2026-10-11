const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const source = readFileSync(path.join(__dirname, '../src/astracore/static/js/experience.js'), 'utf8');

function experience({reducedMotion = false, supported = true, guided = false} = {}) {
  const animations = [];
  const observers = [];
  const mutations = [];
  const sections = [{}, {}];
  const question = guided ? {getBoundingClientRect: () => ({top: 120, bottom: 620})} : null;
  if (question) sections.push(question);
  for (const section of sections) {
    section.animate = (frames, options) => {
      const animation = {element: section, frames, options, cancelled: false,
        cancel() { this.cancelled = true; this.oncancel?.(); }};
      animations.push(animation);
      return animation;
    };
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
  const main = {animate() {}, querySelectorAll: () => sections, querySelector: () => question};
  const window = {IntersectionObserver: supported ? IntersectionObserver : null, MutationObserver, innerHeight: 800,
    matchMedia: () => preference};
  vm.runInNewContext(source, {window, IntersectionObserver, MutationObserver, document: {getElementById: () => main}});
  return {animations, observers, mutations, sections, question,
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
  assert.equal(ui.animations[0].options.duration, 200);
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
