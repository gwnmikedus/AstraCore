const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const path = require('node:path');
const vm = require('node:vm');

function load() {
  const context = {Intl};
  context.window = context;
  for (const file of ['fmt.js', 'print-checklist.js', 'plan-compare.js'])
    vm.runInNewContext(readFileSync(path.join(__dirname, '../src/astracore/static/js', file), 'utf8'), context);
  return context.AC;
}

// A fake plan: one pilot with two colonies, one without, and a transfer.
const PLAN = {
  hub: 'HUB <b>', totals: {isk_per_day: 6.9e6, colonies: 2},
  characters: [
    {character_id: 1, name: 'Miner <i>', route: {order: ['HUB', 'FAR']}},
    {character_id: 2, name: 'Idle'},
  ],
  colonies: [
    {character_id: 1, planet: '39P-1J I', planet_type: 'Lava', security: -0.56, template: 'Miner - 00 - Silicon',
     kind: 'miner', tier: 1, p0: ['Felsic Magma'], out_per_day: {Silicon: 1238}, upkeep: {visit_every_days: 7}, action: 'new'},
    {character_id: 1, planet: '39P-1J II', planet_type: 'Barren', security: -0.56, template: 'Factory - P2',
     kind: 'factory', tier: 2, p0: [], out_per_day: {Coolant: 40}, upkeep: {visit_every_days: 3.5}, action: 'keep'},
  ],
  transfers: [{from: 'Miner', to: 'Idle', item: 'Water', units_per_day: 100}],
};

test('one table per character with tick boxes, planet, template and upkeep', () => {
  const html = load().checklistHTML(PLAN, {date: new Date('2026-10-12T10:00:00Z')});
  assert.match(html, /<h1>Build checklist<\/h1>/);
  assert.match(html, /2026-10-12/);
  assert.match(html, /drop-off HUB &lt;b&gt;/);                   // escaped
  assert.equal((html.match(/<table>/g) || []).length, 1);         // the pilot without colonies is left out
  assert.doesNotMatch(html, /Idle<\/h2>|>Idle /);
  assert.match(html, /Miner &lt;i&gt;/);
  assert.match(html, /Route HUB → FAR/);
  assert.equal((html.match(/class="tickbox"/g) || []).length, 3);  // two colonies and one transfer
  assert.match(html, /<td class="planet">39P-1J I<small>Lava · sec -0.56<\/small>/);
  assert.match(html, /Visit every 7 d/);
  assert.match(html, /Restock every 3.5 d/);
  assert.match(html, /extract Felsic Magma/);
  assert.match(html, /Transfers between characters/);
});

test('no checklist for a failed or missing plan', () => {
  const AC = load();
  assert.equal(AC.checklistHTML(null), '');
  assert.equal(AC.checklistHTML({error: 'No plan'}), '');
});

test('a new question is scrolled to only when it starts off the first screen', () => {
  const AC = load();
  assert.equal(AC.tourScroll({top: 460, viewport: 812}), false);   // folded hero on a phone: already in view
  assert.equal(AC.tourScroll({top: 680, viewport: 812}), true);    // under the full hero
  assert.equal(AC.tourScroll({top: -300, viewport: 812}), true);   // scrolled past it
});
