const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const vm = require('node:vm');
const path = require('node:path');
const guide = readFileSync(path.join(__dirname, '../src/astracore/modules/pi/templates/pi/guide.html'), 'utf8');

function fixture(settings = {}) {
  const calls = [], visits = [], nodes = new Map();
  const $ = id => {
    if (!nodes.has(id)) nodes.set(id, {style: {setProperty(key, value) { this[key] = value; }}});
    return nodes.get(id);
  };
  const context = {S: {guide_step: 0, answered: [], effort: 50, per_planet: 2, cross_character: true,
    ship_every_days: 21, hour_isk: -1, ...settings}, SELLER: {}, API: '/pi/api', PLANNABLE: 1,
    Promise, window: {}, document: {querySelectorAll: () => []}, $,
    go(index) { visits.push(index); }, setHint() {},
  };
  context.window = context;
  vm.createContext(context);
  for (const file of ['fmt.js', 'plan-compare.js'])
    vm.runInContext(readFileSync(path.join(__dirname, '../src/astracore/static/js', file), 'utf8'), context);
  context.AC.post = async (url, body) => { calls.push({url, body: JSON.parse(JSON.stringify(body))}); return context.reply || {ok: true}; };
  context.esc = context.AC.esc;
  context.AC.icon = () => '';
  vm.runInContext(guide.slice(guide.indexOf('const SELL ='), guide.indexOf('// ---- state')), context);
  vm.runInContext(guide.slice(guide.indexOf('const st ='), guide.indexOf('const STEP_CONTEXT')), context);
  vm.runInContext(guide.match(/^const optOf = .*$/m)[0] + guide.match(/^const labelOf = .*$/m)[0], context);
  vm.runInContext(guide.slice(guide.indexOf('// ---- question route'), guide.indexOf('// ---- tracker')), context);
  vm.runInContext(guide.slice(guide.indexOf('function drawTrack()'), guide.indexOf('// Leave the current question')), context);
  vm.runInContext(guide.slice(guide.indexOf('async function navigate('), guide.indexOf('// ---- a question')), context);
  vm.runInContext(guide.slice(guide.indexOf('async function save('), guide.indexOf('// ---- the result')), context);
  const run = code => vm.runInContext(code, context);
  const state = () => JSON.parse(run('JSON.stringify({st, saved, answered:[...answered], cur, MAIN, optionalReturn})'));
  return {context, calls, visits, run, state, $};
}

const MAIN_IDS = ['goal', 'cycle', 'area', 'tier', 'buy', 'sell'];
const BEFORE_SELL = ['goal', 'cycle', 'area', 'tier', 'buy'];

test('six main questions retain the original indices and skip the optional stops', () => {
  const {run} = fixture();
  assert.equal(run('QUESTIONS'), 6);
  assert.deepEqual(JSON.parse(run('JSON.stringify(MAIN)')), [0, 1, 2, 3, 4, 7, 9]);
  assert.equal(run('nextIndex(3)'), 4);
  assert.equal(run('nextIndex(4)'), 7);
  assert.equal(run('cur = 7; backIndex()'), 4);
  assert.equal(run('nextIndex(7)'), 9);
  assert.equal(run('cur = 9; backIndex()'), 7);
});

test('optional questions preserve their originating main progress without changing saved answers', async () => {
  for (const [origin, optional, expected] of [[3, 5, 46], [7, 6, 76.667], [9, 8, 92]]) {
    const {context, run, state, $} = fixture({guide_step: origin, answered: [...MAIN_IDS, 'share', 'chain', 'batch']});
    context.go = index => run(`cur = ${index}`);
    const before = state();
    run('drawTrack()');
    const progress = $('track').style['--progress'];
    await run(`navigate(${optional})`);
    run('drawTrack()');
    assert.equal($('track').style['--progress'], progress);
    assert.ok(Math.abs(parseFloat(progress) - expected) < 0.001);
    assert.deepEqual(state().st, before.st);
    assert.deepEqual(state().saved, before.saved);
    assert.deepEqual(state().answered, before.answered);
  }
});

test('reloading a saved optional question keeps progress at its main return position', () => {
  for (const index of [5, 6, 8]) {
    const {run, $, state} = fixture({guide_step: index, answered: BEFORE_SELL});
    const before = state();
    run('drawTrack()');
    assert.ok(Math.abs(parseFloat($('track').style['--progress']) - 76.667) < 0.001);
    assert.deepEqual(state(), before);
  }
});

test('More options shows saved non-default settings without treating them as answered', () => {
  const {run, state} = fixture();
  const before = state();
  const html = run('additionalChoicesHTML()');
  assert.match(html, /Planets:<\/b> Up to 2/);
  assert.match(html, /Teamwork:<\/b> Yes, they can trade/);
  assert.match(html, /Batches:<\/b> Every 21 days/);
  assert.match(html, /<summary>More options<\/summary>/);
  assert.match(html, /data-optional-i="5"/);
  assert.match(html, /data-optional-i="6"/);
  assert.match(html, /data-optional-i="8"/);
  assert.deepEqual(state(), before);
});

test('only the explicit Selling confirmation adds the displayed optional choices to metadata', async () => {
  const {calls, run, state} = fixture({answered: BEFORE_SELL});
  await run("save(STEPS[7], 9)");
  assert.deepEqual(calls[0].body.answered, MAIN_IDS);
  assert.equal(calls[0].body.per_planet, undefined);
  await run("save(STEPS[7], 9, true)");
  assert.deepEqual(calls[1].body.answered, [...MAIN_IDS, 'share', 'chain', 'batch']);
  assert.equal(calls[1].body.guide_step, 9);
  assert.deepEqual([calls[1].body.per_planet, calls[1].body.cross_character, calls[1].body.ship_every_days], [2, true, 21]);
  assert.deepEqual(state().answered, [...MAIN_IDS, 'share', 'chain', 'batch']);
});

test('failed explicit confirmation does not mark defaults as confirmed or overwrite saved values', async () => {
  const {context, run, state} = fixture({answered: MAIN_IDS});
  context.reply = {error: 'Not saved'};
  const before = state();
  await run('save(STEPS[7], 9, true)');
  assert.deepEqual(state(), before);
});

test('reload at an original optional index returns to the first unfinished main question', () => {
  const {run, state} = fixture({guide_step: 5, answered: BEFORE_SELL});
  assert.equal(state().cur, 5);
  assert.equal(state().optionalReturn, 7);
  assert.equal(run('nextIndex()'), 7);
  assert.equal(run('backIndex()'), 7);
  const result = fixture({guide_step: 8, answered: [...MAIN_IDS, 'share', 'chain', 'batch']});
  assert.equal(result.state().cur, 8);
  assert.equal(result.run('nextIndex()'), 9);
});

test('a pilot who answered everything before the Buying question is asked it next', () => {
  const {state} = fixture({guide_step: 5, answered: ['goal', 'cycle', 'area', 'tier', 'sell', 'share', 'chain', 'batch']});
  assert.equal(state().optionalReturn, 4);
});

test('Back from an unconfirmed optional preview restores the saved choice', async () => {
  const {run, state, visits} = fixture({guide_step: 5, answered: MAIN_IDS});
  run("picks.share = 3; st.per_planet = 3; results.share = {3: {totals:{}}};");
  await run('navigate(9)');
  assert.equal(state().st.per_planet, 2);
  assert.equal(state().answered.includes('share'), false);
  assert.deepEqual(visits, [7]);    // a visible Selling confirmation is still required
});

test('an explicitly adjusted optional answer is saved under its original ID and position', async () => {
  const {run, state, calls} = fixture({guide_step: 5, answered: BEFORE_SELL});
  run('picks.share = 3; st.per_planet = 3;');
  await run('save(STEPS[5], 7)');
  assert.equal(calls[0].body.per_planet, 3);
  assert.equal(calls[0].body.guide_step, 7);
  assert.deepEqual(state().answered, [...BEFORE_SELL, 'share']);
  assert.equal(calls[0].body.ship_every_days, undefined);
  assert.equal(calls[0].body.cross_character, undefined);
});

test('Teamwork follows Up to P3/P4 until the pilot chooses it, with a visible note', () => {
  const {run} = fixture({cross_character: false, max_tier: 4});
  run('PLANNABLE = 3');
  assert.equal(run("STEPS.find(s => s.id === 'chain').match(st)"), true);
  assert.match(run('additionalChoicesHTML()'), /Teamwork:<\/b> Yes, they can trade \(on for P3\/P4\)/);
  run('st.cross_character_set = true');
  assert.equal(run("STEPS.find(s => s.id === 'chain').match(st)"), false);
  run('st.cross_character_set = false; st.max_tier = 2');
  assert.equal(run("STEPS.find(s => s.id === 'chain').match(st)"), false);
  const answers = JSON.parse(run("JSON.stringify(STEPS.find(s => s.id === 'chain').options.map(o => o.patch))"));
  assert.ok(answers.every(p => p.cross_character_set === true));   // picking on Teamwork is the pilot's own choice
});
