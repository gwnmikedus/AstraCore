const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const vm = require('node:vm');
const path = require('node:path');
const guide = readFileSync(path.join(__dirname, '../src/astracore/modules/pi/templates/pi/guide.html'), 'utf8');
const code = guide.slice(guide.indexOf('function setHint('), guide.indexOf('async function load(step)'));

function fixture() {
  const nodes = new Map();
  const $ = id => {
    if (!nodes.has(id)) nodes.set(id, {innerHTML: '', textContent: '', dataset: {}});
    return nodes.get(id);
  };
  const options = [1, 2, 3].map(id => ({dataset: {id: JSON.stringify(id)}, tabIndex: -1,
    getAttribute() { return this.failed ? 'true' : 'false'; }, focus() { context.focused = id; }}));
  const chosen = [];
  const context = {$, cur: 1, QUESTIONS: 8, st: {}, saving: false, results: {}, picks: {},
    answered: new Set(), STEP_CONTEXT: {cycle: 'Pick a rhythm'}, esc: String,
    AC: {icon: () => ''}, hourPicker: () => '', blockedNote: () => '', wireHour() {}, navigate() {}, commit() {}, go() {},
    choose: (step, id) => chosen.push(id), paint() {}, load() {},
    document: {querySelectorAll: () => options}};
  vm.createContext(context);
  vm.runInContext(code, context);
  context.showQuestion({id: 'cycle', q: 'How often?', match: () => 1,
    options: options.map((o, i) => ({id: i + 1, label: 'Answer ' + (i + 1), blurb: 'Details'}))});
  return {context, $, options, chosen};
}

const key = value => ({key: value, preventDefault() {}});

test('answer names reference their labels, with blurb and results separate', () => {
  const {$} = fixture();
  const html = $('q').innerHTML;
  assert.match(html, /aria-labelledby="answer-name-0" aria-describedby="answer-blurb-0 answer-results-0"/);
  assert.match(html, /id="answer-name-0">Answer 1/);
  assert.match(html, /id="answer-results-0"/);
  assert.match(guide, /id="wizard-status"[^>]*role="status"[^>]*aria-live="polite"/);
});

test('loading announcements use one persistent region across question renders', () => {
  const {context, $} = fixture();
  const live = $('wizard-status');
  assert.equal(live.textContent, 'Comparing setups with your characters…');
  context.setHint('AstraCore is busy, your plan is queued…');
  assert.equal(live.textContent, $('navhint').textContent);
  context.showQuestion({id: 'cycle', q: 'Again?', match: () => 1, options: []});
  assert.equal($('wizard-status'), live);
  assert.equal(live.textContent, 'Comparing setups with your characters…');
});

test('arrows and Home/End move focus during loading without selecting an unavailable answer', () => {
  const {context, options, chosen} = fixture();
  options[0].onkeydown(key('ArrowRight'));
  assert.equal(context.focused, 2);
  assert.deepEqual(options.map(o => o.tabIndex), [-1, 0, -1]);
  options[1].onkeydown(key('End'));
  assert.equal(context.focused, 3);
  options[2].onkeydown(key('Home'));
  assert.equal(context.focused, 1);
  assert.deepEqual(chosen, []);
});

test('attempting to select a loading or failed answer explains why it is unavailable', () => {
  const {context, $, options, chosen} = fixture();
  options[0].onkeydown(key('Enter'));
  assert.match($('wizard-status').textContent, /Comparing setups/);
  context.results.cycle = {};
  options[0].failed = true;
  options[0].onclick();
  assert.match($('wizard-status').textContent, /unavailable/);
  context.saving = true;
  options[0].onclick();
  assert.match($('wizard-status').textContent, /Saving your answer/);
  assert.deepEqual(chosen, []);
});

test('ready answers retain arrow selection and saving prevents answer changes', () => {
  const {context, options, chosen} = fixture();
  context.results.cycle = {1: {}, 2: {}, 3: {}};
  options[0].onkeydown(key('ArrowRight'));
  assert.deepEqual(chosen, [2]);
  options[2].onclick();
  assert.deepEqual(chosen, [2, 3]);
  context.saving = true;
  options[2].onkeydown(key('Home'));
  options[0].onclick();
  assert.deepEqual(chosen, [2, 3]);
});
