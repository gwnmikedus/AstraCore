const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const guide = readFileSync(path.join(__dirname, '../src/astracore/modules/pi/templates/pi/guide.html'), 'utf8');
const resultCode = guide.slice(guide.indexOf('async function showPlan()'), guide.indexOf('\ngo(cur, false);'));

function fixture(active = false) {
  const nodes = new Map();
  const $ = id => {
    if (!nodes.has(id)) nodes.set(id, {innerHTML: '', textContent: '', value: '', dataset: {},
      querySelector: () => null, querySelectorAll: () => [], insertAdjacentHTML() {}});
    return nodes.get(id);
  };
  const calls = [];
  const context = {seq: 0, PLANS: active ? [{id: 5, active: true, label: 'Original', totals: {isk_per_day: 100}}] : [],
    OPTIONAL_IDS: new Set(['share','chain','batch']), additionalChoicesHTML: () => '', wireAdditionalChoices() {}, backIndex: () => 6,
    $, API: '/pi/api', EXPORT: '/pi/export', EXPORT_Q: '', STEPS: [], cur: 8,
    AC: {icon: () => '', compareTableHTML: () => '', post: (url, body) => new Promise(resolve => calls.push({url, body, resolve}))},
    document: {querySelectorAll: () => []}, esc: String, isk: String, encodeURIComponent,
    planHTML: () => 'Displayed build list', fillYieldBand() {}, navigate() { context.seq += 1; }};
  vm.createContext(context);
  vm.runInContext(resultCode, context);
  return {context, $, calls};
}

function saved(id = 11) {
  return {ok: true, id, label: 'Plan 1', active: true, plans: [{id, label: 'Plan 1', active: true, totals: {}}]};
}

test('first-plan handoff has no link until the save resolves successfully', async () => {
  const {context, $, calls} = fixture();
  const work = context.showPlan();
  assert.match($('operate-handoff').innerHTML, /disabled/);
  calls[0].resolve({result_id: 'server-result', facts: {}, totals: {}});
  await work;
  assert.equal(calls[1].body.result_id, 'server-result');
  assert.match($('operate-handoff').innerHTML, /disabled>Saving your plan/);
  assert.equal($('planbar').textContent, 'Saving your plan…');
  assert.doesNotMatch($('operate-instruction').innerHTML, /href=/);
  calls[1].resolve(saved());
  await new Promise(resolve => setImmediate(resolve));
  assert.match($('operate-handoff').innerHTML, /href=.*Go to Operate/);
  assert.equal(context.EXPORT_Q, '?plan=11');
  assert.match(guide, /id="planbar" role="status" aria-live="polite"/);
});

test('failure keeps the first-plan handoff disabled and retries the same snapshot', async () => {
  const {context, $, calls} = fixture();
  const first = context.planBar('same-result');
  calls[0].resolve({error: 'Connection lost'});
  await first;
  assert.match($('planbar').innerHTML, /Connection lost.*Retry save/);
  assert.doesNotMatch($('operate-handoff').innerHTML, /href=/);
  const retry = $('retry-save-plan').onclick();
  assert.equal(calls[1].body.result_id, 'same-result');
  calls[1].resolve(saved());
  await retry;
  assert.match($('operate-handoff').innerHTML, /Go to Operate/);
});

test('stale save offers recalculation rather than retrying the expired snapshot', async () => {
  const {context, $, calls} = fixture();
  let recalculated = false;
  context.showPlan = () => { recalculated = true; };
  const work = context.planBar('stale-result');
  calls[0].resolve({error: 'Your answers changed', stale: true});
  await work;
  assert.match($('planbar').innerHTML, /Recalculate plan/);
  $('retry-save-plan').onclick();
  assert.equal(recalculated, true);
});

test('a completed save after navigation never rewrites the new question', async () => {
  const {context, $, calls} = fixture();
  const work = context.planBar('leaving-result');
  context.seq += 1;
  $('planbar').innerHTML = 'New question';
  calls[0].resolve(saved());
  await work;
  assert.equal($('planbar').innerHTML, 'New question');
  assert.equal(context.PLANS.length, 0);
});

test('existing active plan needs an explicit save or replacement choice', async () => {
  const {context, $, calls} = fixture(true);
  await context.planBar('candidate-result');
  assert.equal(calls.length, 0);
  const work = $('plan-save').onclick();
  assert.equal(calls[0].body.active, false);
  assert.equal(calls[0].body.result_id, 'candidate-result');
  calls[0].resolve({error: 'Connection lost'});
  await work;
  assert.equal($('plan-save').disabled, false);
  const replace = $('plan-active').onclick();
  assert.equal(calls[1].body.active, true);
  calls[1].resolve(saved());
  await replace;
});

test('a new displayed candidate resets downloads after saving an earlier plan', async () => {
  const {context, $, calls} = fixture(true);
  context.setSaved(saved(11));
  assert.equal(context.EXPORT_Q, '?plan=11');
  let queryAtRender;
  context.planHTML = () => { queryAtRender = context.EXPORT_Q; return 'New candidate'; };
  const work = context.showPlan();
  calls[0].resolve({result_id: 'new/result', facts: {}, totals: {}});
  await work;
  assert.equal(queryAtRender, '?result=new%2Fresult');
  assert.equal(context.EXPORT_Q, '?result=new%2Fresult');
  assert.equal($('tpl-link').href, '/pi/export/templates.zip?result=new%2Fresult');
});

test('shared API keeps a stale 409 response readable for the save retry UI', async () => {
  const context = {window: {}, document: {querySelector: () => ({content: 'synthetic'}), addEventListener() {}},
    Date, fetch: async () => new Response(JSON.stringify({error: 'Recalculate', stale: true}), {status: 409})};
  vm.createContext(context);
  context.window.AC = {};
  context.AC = context.window.AC;
  vm.runInContext(readFileSync(path.join(__dirname, '../src/astracore/static/js/astracore.js'), 'utf8'), context);
  const response = await context.AC.post('/pi/api/plans', {result_id: 'stale'});
  assert.equal(response.stale, true);
  assert.equal(response.error, 'Recalculate');
});
