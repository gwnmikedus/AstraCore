const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const vm = require('node:vm');
const guide = readFileSync('src/astracore/modules/pi/templates/pi/guide.html', 'utf8');
const code = guide.slice(guide.indexOf('function paint(step)'), guide.indexOf('// Products step:'));

function fixture() {
  const nodes = new Map();
  const $ = id => {
    if (!nodes.has(id)) nodes.set(id, {innerHTML: '', setAttribute() {}, addEventListener() {}});
    return nodes.get(id);
  };
  const details = {open: false, addEventListener(type, callback) { this[type] = callback; }};
  const summary = {focus(options) { this.focused = options.preventScroll; }};
  const bar = {style: {}};
  details.querySelector = () => summary;
  const res = {
    get innerHTML() { return this.html; },
    set innerHTML(value) {
      this.html = value;
      details.open = /class="answer-details" open/.test(value);
    },
  };
  const card = {dataset: {id: '1'}, classList: {toggle() {}, add() {}}, setAttribute() {},
    querySelector: selector => selector === '.res' ? res : selector === '.answer-details' ? details
      : selector === '.answer-details > summary' ? summary : selector === '.bar i' ? bar : {}};
  const result = {totals: {m3_per_week: 120, restarts_per_week: 3, systems: 2, factories: 1, transfers: 4},
    mix: 'Fictional production', holds: 2, channels: ['Example channel'], sell_net_per_cycle: 700};
  const option = {id: 1, label: 'Example answer', patch: {cycle_days: 7}};
  const context = {$, answerDetailsOpen: new Set(), results: {area: {1: result}, sell: {1: result}},
    complete: {area: true, sell: true}, picks: {area: 1, sell: 1}, saving: false, st: {selected_constellations: [1]},
    routineOnly: () => false, recommend: () => 1, needsOwnTrip: () => false,
    value: () => 100, optOf: () => option, minutesPerWeek: () => 10,
    isk: value => String(value), duration: value => String(value), count: value => String(value),
    m3: value => String(value), esc: String, HELP: {}, GLOSSARY: '/pi/glossary',
    AC: {icon: () => '', helpPartsFor: () => ({button: '', answer: ''})},
    advice: () => '', compareHTML: () => '', samePlanHTML: () => '',
    hourControl: {setValue() {}, setDisabled() {}}, iskPerHour: () => 0, HOUR_DEFAULT: {balanced: 0}, goalId: () => 'balanced',
    document: {querySelectorAll: () => [card]},
  };
  vm.createContext(context);
  vm.runInContext(code, context);
  return {context, details, res, summary, bar};
}

test('key figures stay visible while all remaining quantities and production remain in details', () => {
  const {context, details, res} = fixture();
  context.paint({id: 'area', options: [{id: 1}]});
  const [primary, secondary] = res.innerHTML.split('<details');
  assert.match(primary, /ISK\/day/);
  assert.match(primary, /Your time \/ week/);
  assert.match(primary, /Haul \/ week/);
  assert.doesNotMatch(primary, /Restarts|Factory planets|Transfers|Batches held/);
  for (const term of ['Restarts / week', 'Systems', 'Factory planets', 'Transfers', 'Batches held back', 'Fictional production'])
    assert.ok(secondary.includes(term), term);
  assert.equal(details.open, false);
  context.paint({id: 'sell', metric: 'sell', options: [{id: 1}]});
  assert.match(res.innerHTML.split('<details')[0], /Per batch/);
  assert.match(res.innerHTML.split('<details')[1], /Haul \/ week/);
});

test('stream repaint preserves expanded details separately for each question and answer', () => {
  const {context, details, res} = fixture();
  const step = {id: 'area', options: [{id: 1}]};
  context.paint(step);
  details.open = true;
  details.toggle();
  context.results.area[1].totals.systems = 5;
  context.paint(step);
  assert.equal(details.open, true);
  assert.match(res.innerHTML, /Systems<\/span><span>5/);
  context.paint({id: 'sell', options: [{id: 1}]});
  assert.equal(details.open, false);
  context.paint(step);
  assert.equal(details.open, true);
  details.open = false;
  details.toggle();
  context.paint(step);
  assert.equal(details.open, false);
});

test('stream repaint restores keyboard focus to a focused details summary without scrolling', () => {
  const {context, summary} = fixture();
  context.document.activeElement = summary;
  context.paint({id: 'area', options: [{id: 1}]});
  assert.equal(summary.focused, true);
});

test('comparison widths use trusted individual style properties without HTML style attributes', () => {
  const {context, res, bar} = fixture();
  const step = {id: 'area', options: [{id: 1}]};
  context.paint(step);
  assert.equal(bar.style.width, '100%');
  assert.doesNotMatch(res.innerHTML, /style=/);
  context.value = () => 0;
  context.paint(step);
  assert.equal(bar.style.width, '3%');
  context.value = () => NaN;
  context.paint(step);
  assert.equal(bar.style.width, '3%');
});
