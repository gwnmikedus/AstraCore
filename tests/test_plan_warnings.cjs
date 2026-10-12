const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const path = require('node:path');
const vm = require('node:vm');

function load() {
  const context = {Intl};
  context.window = context;
  for (const file of ['fmt.js', 'plan-warnings.js'])
    vm.runInNewContext(readFileSync(path.join(__dirname, '../src/astracore/static/js', file), 'utf8'), context);
  return context.AC;
}

const UNUSED = {code: 'unused_slots', level: 'warn', steps: ['area', 'share', 'goal'],
  text: '2 slots are unused: the selected area or limits (max systems 3, max jumps 3, colonies per planet 1) …',
  guided: '2 slots are unused: nothing else in your area pays enough for the time it takes.'};
const STEPS = {goal: 'Goal', area: 'Area', share: 'Planets'};

test('no warnings, no box', () => {
  assert.equal(load().planWarningsHTML([]), '');
  assert.equal(load().planWarningsHTML(undefined), '');
});

test('the guided setup shows its own wording with a link per step', () => {
  const html = load().planWarningsHTML([UNUSED], {steps: STEPS});
  assert.match(html, /Before you build \(1\)/);
  assert.match(html, /nothing else in your area pays enough/);
  assert.doesNotMatch(html, /max jumps/);
  assert.match(html, /<a href="#" data-step="area">Change Area<\/a> · <a href="#" data-step="share">Change Planets<\/a> · <a href="#" data-step="goal">Change Goal<\/a>/);
});

test('the advanced planner keeps its own wording and no step links', () => {
  const html = load().planWarningsHTML([UNUSED]);
  assert.match(html, /max jumps 3/);
  assert.doesNotMatch(html, /data-step/);
});

test('at most three show; the rest wait in a closed section, info last', () => {
  const AC = load();
  const list = [
    {code: 'replan', level: 'info', text: 'Info first in the list', steps: []},
    'Legacy <b>string</b> warning', 'Legacy <b>string</b> warning',
    {code: 'a', text: 'A', steps: []}, {code: 'b', text: 'B', steps: []}, {code: 'c', text: 'C', steps: []},
  ];
  assert.deepEqual([...AC.planNotes(list).map(n => n.text)], ['Legacy <b>string</b> warning', 'A', 'B', 'C', 'Info first in the list']);
  const html = AC.planWarningsHTML(list, {steps: STEPS});
  assert.match(html, /Before you build \(5\)/);
  assert.match(html, /Legacy &lt;b&gt;string&lt;\/b&gt; warning/);
  const [shown, more] = html.split('<details>');
  assert.match(shown, /<li>B<\/li>/);
  assert.doesNotMatch(shown, /<li>C<\/li>/);
  assert.match(more, /2 more notes/);
  assert.match(more, /<li class="info">Info first in the list<\/li>/);
  assert.doesNotMatch(html, /<details open/);
});
