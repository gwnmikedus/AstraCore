const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const vm = require('node:vm');
const path = require('node:path');
const guide = readFileSync(path.join(__dirname, '../src/astracore/modules/pi/templates/pi/guide.html'), 'utf8');

function fixture(settings = {}) {
  const calls = [], visits = [];
  const context = {S: {guide_step: 0, answered: [], effort: 50, per_planet: 2, cross_character: true,
    ship_every_days: 21, hour_isk: -1, ...settings}, SELLER: {}, API: '/pi/api',
    Promise, window: {}, document: {querySelectorAll: () => []},
    go(index) { visits.push(index); }, setHint() {},
  };
  context.window = context;
  vm.createContext(context);
  for (const file of ['fmt.js', 'plan-compare.js'])
    vm.runInContext(readFileSync(path.join(__dirname, '../src/astracore/static/js', file), 'utf8'), context);
  context.AC.post = async (url, body) => { calls.push({url, body: JSON.parse(JSON.stringify(body))}); return context.reply || {ok: true}; };
  context.esc = context.AC.esc;
  vm.runInContext(guide.slice(guide.indexOf('const SELL ='), guide.indexOf('// ---- state')), context);
  vm.runInContext(guide.slice(guide.indexOf('const st ='), guide.indexOf('const STEP_CONTEXT')), context);
  vm.runInContext(guide.match(/^const optOf = .*$/m)[0] + guide.match(/^const labelOf = .*$/m)[0], context);
  vm.runInContext(guide.slice(guide.indexOf('// ---- question route'), guide.indexOf('// ---- tracker')), context);
  vm.runInContext(guide.slice(guide.indexOf('async function navigate('), guide.indexOf('// ---- a question')), context);
  vm.runInContext(guide.slice(guide.indexOf('async function save('), guide.indexOf('// ---- the result')), context);
  const run = code => vm.runInContext(code, context);
  const state = () => JSON.parse(run('JSON.stringify({st, saved, answered:[...answered], cur, MAIN, optionalReturn})'));
  return {context, calls, visits, run, state};
}

const MAIN_IDS = ['goal', 'cycle', 'area', 'tier', 'sell'];

test('five main questions retain the original indices and skip the optional stops', () => {
  const {run} = fixture();
  assert.equal(run('QUESTIONS'), 5);
  assert.deepEqual(JSON.parse(run('JSON.stringify(MAIN)')), [0, 1, 2, 3, 6, 8]);
  assert.equal(run('nextIndex(3)'), 6);
  assert.equal(run('cur = 6; backIndex()'), 3);
  assert.equal(run('nextIndex(6)'), 8);
  assert.equal(run('cur = 8; backIndex()'), 6);
});

test('More options shows saved non-default settings without treating them as answered', () => {
  const {run, state} = fixture();
  const before = state();
  const html = run('additionalChoicesHTML()');
  assert.match(html, /Planets:<\/b> Up to 2/);
  assert.match(html, /Teamwork:<\/b> Yes, they can trade/);
  assert.match(html, /Batches:<\/b> Every 21 days/);
  assert.match(html, /<summary>More options<\/summary>/);
  assert.match(html, /data-optional-i="4"/);
  assert.match(html, /data-optional-i="5"/);
  assert.match(html, /data-optional-i="7"/);
  assert.deepEqual(state(), before);
});

test('only the explicit Selling confirmation adds the displayed optional choices to metadata', async () => {
  const {calls, run, state} = fixture({answered: ['goal', 'cycle', 'area', 'tier']});
  await run("save(STEPS[6], 8)");
  assert.deepEqual(calls[0].body.answered, MAIN_IDS);
  assert.equal(calls[0].body.per_planet, undefined);
  await run("save(STEPS[6], 8, true)");
  assert.deepEqual(calls[1].body.answered, [...MAIN_IDS, 'share', 'chain', 'batch']);
  assert.equal(calls[1].body.guide_step, 8);
  assert.deepEqual([calls[1].body.per_planet, calls[1].body.cross_character, calls[1].body.ship_every_days], [2, true, 21]);
  assert.deepEqual(state().answered, [...MAIN_IDS, 'share', 'chain', 'batch']);
});

test('failed explicit confirmation does not mark defaults as confirmed or overwrite saved values', async () => {
  const {context, run, state} = fixture({answered: MAIN_IDS});
  context.reply = {error: 'Not saved'};
  const before = state();
  await run('save(STEPS[6], 8, true)');
  assert.deepEqual(state(), before);
});

test('reload at an original optional index returns to the first unfinished main question', () => {
  const {run, state} = fixture({guide_step: 4, answered: ['goal', 'cycle', 'area', 'tier']});
  assert.equal(state().cur, 4);
  assert.equal(state().optionalReturn, 6);
  assert.equal(run('nextIndex()'), 6);
  assert.equal(run('backIndex()'), 6);
  const result = fixture({guide_step: 7, answered: [...MAIN_IDS, 'share', 'chain', 'batch']});
  assert.equal(result.state().cur, 7);
  assert.equal(result.run('nextIndex()'), 8);
});

test('Back from an unconfirmed optional preview restores the saved choice', async () => {
  const {run, state, visits} = fixture({guide_step: 4, answered: MAIN_IDS});
  run("picks.share = 3; st.per_planet = 3; results.share = {3: {totals:{}}};");
  await run('navigate(8)');
  assert.equal(state().st.per_planet, 2);
  assert.equal(state().answered.includes('share'), false);
  assert.deepEqual(visits, [6]);    // a visible Selling confirmation is still required
});

test('an explicitly adjusted optional answer is saved under its original ID and position', async () => {
  const {run, state, calls} = fixture({guide_step: 4, answered: ['goal', 'cycle', 'area', 'tier']});
  run('picks.share = 3; st.per_planet = 3;');
  await run('save(STEPS[4], 6)');
  assert.equal(calls[0].body.per_planet, 3);
  assert.equal(calls[0].body.guide_step, 6);
  assert.deepEqual(state().answered, ['goal', 'cycle', 'area', 'tier', 'share']);
  assert.equal(calls[0].body.ship_every_days, undefined);
  assert.equal(calls[0].body.cross_character, undefined);
});
