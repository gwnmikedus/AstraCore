const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const path = require('node:path');
const vm = require('node:vm');

const source = readFileSync(path.join(__dirname, '../src/astracore/modules/pi/templates/pi/guide.html'), 'utf8');

function guide(step, rows) {
  const context = {Intl, results: {[step.id]: rows}, compareOpen: false, TIME_NOTE: 'Synthetic time assumptions'};
  context.window = context;
  for (const file of ['fmt.js', 'plan-compare.js'])
    vm.runInNewContext(readFileSync(path.join(__dirname, '../src/astracore/static/js', file), 'utf8'), context);
  Object.assign(context, context.AC, {
    AC: {...context.AC, icon: () => ''},
    value: (s, r) => r.totals.isk_per_day,
    minutesPerWeek: (o, r) => r.facts.minutes_per_week,
    iskPerHour: () => 90e6,
    optOf: (s, id) => s.options.find(o => o.id === id),
    byEffort: (s, res) => [...s.options].sort((a, b) => res[a.id].facts.minutes_per_week - res[b.id].facts.minutes_per_week),
  });
  for (const [start, end] of [
    ['function diffs(', '// ---- tracker'],
    ['function samePlanNote(', 'function paint('],
    ['function compareHTML(', 'function choose('],
    ['function advice(', '// ---- Area step'],
  ]) vm.runInNewContext(source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start))), context);
  return context;
}

const step = {id: 'share', title: 'Planets', options: [{id: 1, label: 'One'}, {id: 2, label: 'Up to 2'}]};
const row = (income, minutes, systems) => ({
  totals: {isk_per_day: income, m3_per_week: 60000, systems, factories: 1},
  facts: {minutes_per_week: minutes},
});

test('advice does not say an estimate-tied option would earn more just because upkeep differs', () => {
  const context = guide(step, {1: row(33e6, 60, 1), 2: row(33.2e6, 90, 2)});
  const html = context.advice(step, 1, 1);
  assert.match(html, /earns about the same/);
  assert.match(html, /30 min more of your time a week/);
  assert.doesNotMatch(html, /would earn more/);
});

test('advice still identifies a meaningful income gain and its extra effort', () => {
  const context = guide(step, {1: row(33e6, 60, 1), 2: row(34e6, 90, 2)});
  const html = context.advice(step, 1, 1);
  assert.match(html, /would earn more/);
  assert.match(html, /\+1.0M\/day/);
});

test('same-plan notes retain boolean option IDs and are escaped in the comparison table', () => {
  const teamwork = {id: 'chain', title: 'Teamwork', options: [{id: false, label: 'No <trade>'}, {id: true, label: 'Yes'}]};
  const context = guide(teamwork, {false: row(33e6, 60, 1), true: {...row(33e6, 60, 1), same_as: false}});
  assert.equal(context.samePlanNote(teamwork, {same_as: false}), 'Same plan as No <trade>');
  assert.equal(context.samePlanNote(teamwork, {}), '');
  const html = context.compareHTML(teamwork, false, false);
  assert.match(html, /Same plan as No &lt;trade&gt;/);
  assert.doesNotMatch(html, /<trade>/);
});
