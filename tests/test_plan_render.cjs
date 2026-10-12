const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const render = readFileSync(path.join(__dirname, '../src/astracore/modules/pi/templates/pi/_plan_render.html'), 'utf8');
const helpers = render.slice(render.indexOf('function colonyValueHTML'), render.indexOf('// opts.steps'));

function load() {
  const context = {AC: {eveImg: () => ''}, esc: s => String(s).replace(/</g, '&lt;'), isk: v => `${v} ISK`, num: String};
  vm.createContext(context);
  vm.runInContext(helpers, context);
  return context;
}

test('a feeder says which factory it supplies and never shows a bare 0', () => {
  const {colonyValueHTML} = load();
  const html = colonyValueHTML({value_per_day: 0, value_at_factory: true,
    feeds: [{character: 'Pilot B', product: 'Polyaramids', item: 'Industrial Fibers', units: 120}]});
  assert.match(html, /value counted at the factory/);
  assert.match(html, /→ feeds Pilot B’s Polyaramids factory/);
  assert.doesNotMatch(html, /0 ISK/);
});

test('a priced feeder keeps its value; old saved plans without feeds still render', () => {
  const {colonyValueHTML} = load();
  assert.match(colonyValueHTML({value_per_day: 5000, value_at_factory: false,
    feeds: [{character: 'A', product: 'Coolant', item: 'Water', units: 10}]}), /^5000 ISK<br>.*feeds A’s Coolant factory/);
  assert.equal(colonyValueHTML({value_per_day: 0}), '0 ISK');
  assert.equal(colonyValueHTML({value_per_day: 0, value_at_factory: true, feeds: []}), '0 ISK');
});

test('transfers are grouped per receiving character', () => {
  const {transfersHTML} = load();
  const html = transfersHTML([
    {from: 'A', to: 'C', item: 'Water', units_per_day: 10},
    {from: 'B', to: 'C', item: 'Biofuels', units_per_day: 20},
    {from: 'C', to: 'A', item: 'Coolant', units_per_day: 5}]);
  assert.equal((html.match(/<li>/g) || []).length, 2);
  assert.match(html, /<b>C<\/b> receives .*10 Water\/day from A.*20 Biofuels\/day from B/);
  assert.equal(transfersHTML([]), '');
  assert.equal(transfersHTML(undefined), '');
});
