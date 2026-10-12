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

const LABELS = [['poor', 0.6], ['average', 1], ['good', 1.25], ['rich', 1.5]];

test('each plan row offers what an in-game scan showed, and says where its richness comes from now', () => {
  const {richnessHTML} = load();
  const estimate = richnessHTML({planet_id: 4001, planet: 'Gas <I>', richness: 1.2}, LABELS);
  assert.match(estimate, /data-richness-planet="4001"/);
  assert.match(estimate, /aria-label="Richness of Gas &lt;I> as scanned in game"/);
  assert.match(estimate, /<option value="" selected>Not scanned: 1.2×<\/option><optgroup label="Scanned in game">/);
  assert.match(estimate, /<option value="1.5">Scanned: rich \(1.5×\)<\/option>/);
  assert.equal((estimate.match(/ selected/g) || []).length, 1);

  const measured = richnessHTML({planet_id: 1, planet: 'X', richness: 0.9, richness_source: 'extractors'}, LABELS);
  assert.match(measured, /<option value="" selected>Your extractors: 0.9×/);

  const scanned = richnessHTML({planet_id: 1, planet: 'X', richness: 1.25, richness_source: 'scan'}, LABELS);
  assert.match(scanned, /<option value="1.25" selected>Scanned: good/);
  assert.match(scanned, /<option value="">Not scanned \(estimate\)/);

  const typed = richnessHTML({planet_id: 1, planet: 'X', richness: 1.3, richness_source: 'scan'}, LABELS);
  assert.match(typed, /<option value="1.3" selected>Scanned: 1.3×<\/option><\/optgroup>/);   // an older custom value stays

  assert.equal(richnessHTML({planet: 'old plan without ids', richness: 1}, LABELS), '');
  assert.equal(richnessHTML({planet_id: 1, planet: 'X', richness: 1}, []), '');
});

test('"Never produce" lists the products of the plan and the ones already left out', () => {
  const {neverProduceHTML} = load();
  const html = neverProduceHTML({never_produce: ['Oxygen'], colonies: [
    {product: 'Coolant', tier: 2}, {product: 'Water', tier: 1}, {product: 'Water', tier: 1}, {product: 'Bacteria', tier: 1}]});
  const boxes = [...html.matchAll(/data-never="([^"]+)"( checked)?/g)].map(m => m[1] + (m[2] ? '*' : ''));
  assert.deepEqual(boxes, ['Bacteria', 'Water', 'Coolant', 'Oxygen*']);
  assert.match(html, /untick one to allow it again/);
  assert.doesNotMatch(neverProduceHTML({colonies: [{product: 'Water', tier: 1}]}), /untick/);
  assert.equal(neverProduceHTML({colonies: []}), '');
});

test('ticking and unticking keeps the stored list of names', () => {
  const {toggledNever} = load();
  assert.deepEqual([...toggledNever(['Water'], 'Coolant', true)], ['Water', 'Coolant']);
  assert.deepEqual([...toggledNever(['water', 'Coolant'], 'Water', false)], ['Coolant']);   // typed lists match too
  assert.deepEqual([...toggledNever(['Water'], 'Water', true)], ['Water']);
  assert.deepEqual([...toggledNever(undefined, 'Water', true)], ['Water']);
});
