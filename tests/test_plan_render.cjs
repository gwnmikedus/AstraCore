const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const render = readFileSync(path.join(__dirname, '../src/astracore/modules/pi/templates/pi/_plan_render.html'), 'utf8');
const helpers = render.slice(render.indexOf('function colonyValueHTML'), render.indexOf('// opts.steps'));

function load() {
  const context = {AC: {eveImg: () => '', icon: () => ''}, esc: s => String(s).replace(/</g, '&lt;'), isk: v => `${v} ISK`, num: String};
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

test('colony notes combine upkeep and planning notes in one closed disclosure with escaped text', () => {
  const {colonyNotesHTML} = load();
  const html = colonyNotesHTML({upkeep: {issues: ['Storage fills before the next visit.']},
    notes: ['Shared hotspot: counted at 70% yield.', '<img src=x onerror=alert(1)>']});
  assert.match(html, /^<details><summary class="warn">.*Colony notes \(3\)<\/summary>/);
  assert.doesNotMatch(html, /<details[^>]*\bopen\b|<img/);
  assert.match(html, /<li class="warn">Storage fills before the next visit\.<\/li>/);
  assert.match(html, /<li class="warn">Shared hotspot: counted at 70% yield\.<\/li>/);
  assert.match(html, /&lt;img src=x/);
  assert.equal((html.match(/<li /g) || []).length, 3);
});

test('old plans and colonies without notes have no empty disclosure', () => {
  const {colonyNotesHTML} = load();
  assert.equal(colonyNotesHTML({}), '');
  assert.equal(colonyNotesHTML({notes: [], upkeep: {issues: []}}), '');
  assert.match(colonyNotesHTML({notes: ['Keep this note.']}), /Colony notes \(1\)/);
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

function demandRow(fields = {}) {
  const context = {window: {}};
  vm.createContext(context);
  vm.runInContext(readFileSync(path.join(__dirname, '../src/astracore/static/js/fmt.js'), 'utf8'), context);
  context.AC = context.window.AC;
  context.AC.eveImg = () => '';
  context.esc = context.AC.esc;
  context.num = context.AC.num;
  vm.runInContext(render.slice(render.indexOf('const DEMAND_STATUS')), context);
  return context.renderDemand({capture: [0.1, 0.3], books_at: 0, rows: [{
    item: 'Fictional PI product', tier: 2, market_label: 'Jita sell orders', side: 'sell',
    status: 'unknown', per_day: 10, qty: 70, history: {days: 7, window: 7, avg_volume: 100},
    horizon_days: [1, 2], ...fields,
  }]});
}

test('legacy demand rows omit unavailable optional percentages but keep trade and selling information', () => {
  for (const value of [undefined, null, NaN, Infinity, -Infinity, '0', '']) {
    const html = demandRow({volume_share: value, price_uncertainty_pct: value});
    assert.doesNotMatch(html, /plan =|price moved/);
    assert.match(html, /7\/7 days with trades/);
    assert.match(html, /est\. 1\.0–2\.0 days/);
  }
});

test('demand percentages retain numeric zero and normal measured values', () => {
  const zero = demandRow({volume_share: 0, price_uncertainty_pct: 0});
  assert.match(zero, /plan = 0%/);
  assert.match(zero, /price moved ±0%/);
  const measured = demandRow({volume_share: 0.25, price_uncertainty_pct: 12.5});
  assert.match(measured, /plan = 25%/);
  assert.match(measured, /price moved ±12\.5%/);
});

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

test('a sell-order batch states its price, fees, instant alternative and slower turnaround', () => {
  const {sellOrdersHTML} = load();
  const so = {market: 'Jita 4-4', sales_tax_pct: 3.6, broker_fee_pct: 1.5, days: [2.5, 7.4],
              items: [{item: 'Robotics', list_price: 80000, net: 75920, instant: 70000},
                      {item: '<b>x</b>', list_price: 10, net: 9, instant: null}]};
  const html = sellOrdersHTML({channel: 'jita_sell', sell_orders: so, contract: {type: 'Courier'}});
  assert.match(html, /<b>Sell-order price<\/b> in Jita 4-4/);
  assert.match(html, /3\.6% sales tax and 1\.5% broker fee/);
  assert.match(html, /Robotics: list at 80000 → 75920 net <span class="muted">\(instant sale 70000\)<\/span>/);
  assert.match(html, /once the courier arrives \(about 3 days\), the orders take est\. 2\.5–7\.4 days to sell/);
  assert.match(html, /&lt;b>x/);
  assert.doesNotMatch(html, /instant sale null/);
  // listed at the hub itself: no courier wait, and no estimate without trade history
  const here = sellOrdersHTML({channel: 'jita_sell', sell_orders: {...so, days: null}});
  assert.doesNotMatch(here, /courier/);
  assert.match(here, /the orders take an unknown time to sell/);
  assert.equal(sellOrdersHTML({channel: 'jita_buy'}), '');
});

test('the result reconciles what the batches pay out with the plan figure (#246)', () => {
  const {incomeCheckHTML} = load();
  assert.equal(incomeCheckHTML({}), '');
  const html = incomeCheckHTML({income_check: {paid: 94e6, plan: 80e6, customs: 5e6, inputs: 10e6, held: 5e6, other: -4e6}});
  assert.match(html, /^<p class="muted text-small income-check">Paid out ≈ 94000000 ISK ISK\/day from the batches below, against the 80000000 ISK ISK\/day above: /);
  assert.match(html, /after customs \(5000000 ISK\) and bought inputs \(10000000 ISK\), which you pay apart from the batches/);
  assert.match(html, /5000000 ISK ISK\/day sits in held-back batches/);
  assert.match(html, /courier minimum fees, batch routing and rounding −4000000 ISK\.<\/p>$/);
  const same = incomeCheckHTML({income_check: {paid: 80.1e6, plan: 80e6, customs: 0, inputs: 0, held: 0, other: 0.1e6}});
  assert.match(same, /about the same as the 80000000 ISK ISK\/day above\.<\/p>$/);
});
