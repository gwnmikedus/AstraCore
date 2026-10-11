const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const path = require('node:path');
const vm = require('node:vm');

function load() {
  const context = {Intl};
  context.window = context;
  for (const file of ['fmt.js', 'plan-compare.js'])
    vm.runInNewContext(readFileSync(path.join(__dirname, '../src/astracore/static/js', file), 'utf8'), context);
  return context.AC;
}

// Fake plans: three pilots over five systems, and a single-pilot plan in one system.
const WIDE = {
  label: 'Wide <script>', note: 'Your pick', current: true,
  totals: {isk_per_day: 46.2e6, colonies: 6, slots_total: 8, factories: 1, systems: 5, restarts_per_week: 11.7,
           m3_per_week: 120000, transfers: 2},
  facts: {minutes_per_week: 119.6, characters_used: 3, characters_total: 4, dropoff: 'HUB',
          system_names: ['EDGE', 'FAR', 'HUB', 'NEXT', 'RIM'],
          uncertainty: {level: 'higher', label: 'Higher', reasons: ['Yield is an estimate until your extractors have run', 'Sell orders: price and time to sell can change']}},
};
const COMPACT = {
  label: 'One system', income: 30e6, incomeUnit: 'ISK/day paid out',
  totals: {isk_per_day: 31e6, colonies: 2, slots_total: 8, factories: 0, systems: 1, restarts_per_week: 4.7, m3_per_week: 9.4, transfers: 0},
  facts: {minutes_per_week: 45, characters_used: 1, characters_total: 4, system_names: ['HUB'],
          uncertainty: {level: 'lower', label: 'Lower', reasons: ['Measured yield and instant sales']}},
};

test('durations read as minutes and hours without a 60-minute remainder', () => {
  const AC = load();
  assert.equal(AC.duration(45), '45 min');
  assert.equal(AC.duration(119.6), '2 h 00 min');
  assert.equal(AC.duration(65), '1 h 05 min');
  assert.equal(AC.duration(Infinity), '–');
  assert.equal(AC.duration(null), '–');
});

test('a comparison table shows income, effort and uncertainty with units for multi-character, multi-system plans', () => {
  const AC = load();
  const html = AC.compareTableHTML({caption: 'Area: what each answer means', rows: [WIDE, COMPACT], first: 'Answer'});
  for (const text of ['46.2M ISK/day', '323.4M ISK/week', '≈ 2 h 00 min / week', '6 of 8 slots', '1 factory planet',
                      '3 of 4', '12 / week', '120,000 m³ / week', '2 transfers between characters',
                      'EDGE, FAR, HUB, NEXT +1 more', 'drop-off HUB', 'Higher', 'Sell orders',
                      '30.0M ISK/day paid out', '210.0M ISK/week', '≈ 45 min / week', '9.4 m³ / week', '1 of 4'])
    assert.ok(html.includes(text), text);
  assert.ok(!html.includes('<script>') && html.includes('Wide &lt;script&gt;'));
  assert.equal((html.match(/aria-current="true"/g) || []).length, 1);
  for (const label of ['Income', 'Your time', 'Colonies', 'Characters', 'Systems', 'Restarts', 'Haul', 'Uncertainty'])
    assert.equal(html.split(`data-label="${label}"`).length - 1, 2, label);
  assert.match(html, /<caption>Area: what each answer means<\/caption>/);
  assert.match(html, /class="scroll compare-scroll"/);
  assert.equal(AC.compareTableHTML({caption: 'x', rows: []}), '');
});

test('missing facts from an old saved plan render as dashes instead of failing', () => {
  const AC = load();
  const html = AC.compareTableHTML({caption: 'Saved', rows: [{label: 'Old plan', totals: {}, facts: {}}]});
  assert.ok(html.includes('Old plan'));
  assert.ok(!html.includes('undefined') && !html.includes('NaN'));
});

const STEPS = [{id: 'goal', options: []}, {id: 'cycle', options: []}, {id: 'area', options: []},
               {id: 'sell', options: []}, {id: 'plan'}];

test('completed steps stay reachable and the first unanswered one is the limit', () => {
  const AC = load();
  assert.equal(AC.tourReach(STEPS, []), 0);
  assert.equal(AC.tourReach(STEPS, ['goal', 'cycle']), 2);
  assert.equal(AC.tourReach(STEPS, new Set(['goal', 'cycle', 'area', 'sell'])), 4);
  assert.equal(AC.tourReach(STEPS, ['goal', 'area', 'sell']), 1);          // a gap stops the jump
});

test('leaving a question keeps compared answers and falls back for unconfirmed ones', () => {
  const AC = load();
  assert.equal(AC.tourLeave({forward: true, valid: true, wasAnswered: true, changed: true}), 'save');
  assert.equal(AC.tourLeave({forward: true, valid: false, wasAnswered: true, changed: true}), 'revert');
  assert.equal(AC.tourLeave({forward: false, valid: true, wasAnswered: true, changed: true}), 'save');
  assert.equal(AC.tourLeave({forward: false, valid: true, wasAnswered: true, changed: false}), 'keep');
  assert.equal(AC.tourLeave({forward: false, valid: true, wasAnswered: false, changed: true}), 'revert');
});
