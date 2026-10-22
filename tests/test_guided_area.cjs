const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const guide = fs.readFileSync('src/astracore/modules/pi/templates/pi/guide.html', 'utf8');
const code = guide.slice(guide.indexOf('async function wireArea(step)'), guide.indexOf('// Save the answer on screen'));
const covered = {local: true, courier: true, trade_hub: false};
const unsupported = {local: false, courier: false, trade_hub: false};

function fixture() {
  const nodes = {}, calls = [], posts = [], loads = [], renders = [];
  let gate = false;
  const get = id => {
    if (id === 'enable-own-trip') return gate ? {} : null;
    return nodes[id] ||= {
      dataset: {}, isConnected: true, hidden: false, value: '',
      querySelectorAll() { return []; },
    };
  };
  const ctx = {
    st: {selected_constellations: [], hub_system: ''}, $: get, API: '/pi/api',
    URLSearchParams, esc: String, seq: 0, comparisonRequest: null,
    clearTimeout, prefetchTimer: null,
    SELL_COVERAGE: unsupported, results: {},
    fetch(url) { return new Promise(resolve => calls.push({url, resolve})); },
    setHint() {}, paint() {}, load(step) { loads.push(step.id); },
    needsOwnTrip() {
      return ctx.st.selected_constellations.length > 0 && !ctx.st.use_self_haul &&
        !Object.values(ctx.SELL_COVERAGE).some(Boolean);
    },
    showQuestion(step) { gate = ctx.needsOwnTrip(); renders.push(step.id); },
    AC: {post(...args) { posts.push(args); }},
  };
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  ctx.wireArea({id: 'area'});
  return {ctx, get, calls, posts, loads, renders};
}

const response = (id, coverage = covered) => ({
  ok: true,
  json: async () => ({selected: [id], constellations: [], systems: [], selling_coverage: coverage}),
});
async function tick() { await new Promise(resolve => setImmediate(resolve)); }

test('suggested area loads without saving; search races retain the newest result', async () => {
  const {ctx, get, calls, posts} = fixture();
  calls[0].resolve(response(1));
  await tick();
  assert.deepEqual(Array.from(ctx.st.selected_constellations), [1]);
  assert.equal(posts.length, 0);
  get('area-search').value = 'The Forge';
  get('find-area').onclick();
  get('area-search').value = 'Delve';
  get('find-area').onclick();
  calls[2].resolve(response(3));
  await tick();
  calls[1].resolve(response(2));
  await tick();
  assert.deepEqual(Array.from(ctx.st.selected_constellations), [3]);
  assert.equal(ctx.st.extra_area, 'Delve');
  assert.equal(posts.length, 0);
});

test('Continue saves the chosen area together with its travel answer once', async () => {
  const calls = [];
  const ctx = {
    hourSave: Promise.resolve(), picks: {area: 'near'},
    answerOf: () => ({patch: {max_systems: 3, max_jumps: 3}}),
    answered: new Set(['goal', 'cycle']),
    st: {selected_constellations: [1, 2], extra_area: 'The Forge', hub_system: 'HUB'},
    saved: {}, API: '/pi/api',
    AC: {post: async (url, body) => { calls.push({url, body}); return {ok: true}; }},
  };
  vm.createContext(ctx);
  const start = guide.indexOf('async function save(');
  vm.runInContext(guide.slice(start, guide.indexOf('\n}', start) + 2), ctx);
  await ctx.save({id: 'area', isArea: true}, 3);
  assert.equal(calls.length, 1);
  assert.deepEqual(Array.from(calls[0].body.selected_constellations), [1, 2]);
  assert.equal(calls[0].body.extra_area, 'The Forge');
  assert.equal(calls[0].body.max_systems, 3);
  assert.deepEqual(Array.from(calls[0].body.answered), ['goal', 'cycle', 'area']);
});

test('a searched area remains available after the own-trip prerequisite rerenders the question', async () => {
  const {ctx, calls} = fixture();
  calls[0].resolve(response(1));
  await tick();
  ctx.st.extra_area = 'Fictional region';
  ctx.st.selected_constellations = [7];
  ctx.wireArea({id: 'area'});
  assert.match(calls[1].url, /extra_area=Fictional\+region/);
  assert.match(calls[1].url, /selected_constellations=7/);
  calls[1].resolve(response(2));
  await tick();
  assert.deepEqual(Array.from(ctx.st.selected_constellations), [7]);
});

test('empty to covered area compares without requiring an own trip', async () => {
  const {ctx, calls, loads, renders} = fixture();
  calls[0].resolve(response(1, covered));
  await tick();
  assert.equal(ctx.needsOwnTrip(), false);
  assert.deepEqual(loads, ['area']);
  assert.deepEqual(renders, []);
});

test('covered to unsupported search gates comparisons before whatif runs', async () => {
  const {ctx, get, calls, loads, renders} = fixture();
  calls[0].resolve(response(1, covered));
  await tick();
  get('area-search').value = 'Fictional remote region';
  get('find-area').onclick();
  calls[1].resolve(response(2, unsupported));
  await tick();
  assert.equal(ctx.needsOwnTrip(), true);
  assert.deepEqual(loads, ['area']);
  assert.deepEqual(renders, ['area']);
});

test('drop-off changes refresh coverage before comparing and do not save the preview', async () => {
  const {get, calls, loads, renders, posts} = fixture();
  const checkbox = {value: '1'};
  get('area-adv').querySelectorAll = selector => selector.includes(':checked') ? [checkbox] : [];
  calls[0].resolve(response(1, covered));
  await tick();
  get('area-hub').value = 'Fictional remote hub';
  get('area-hub').onchange();
  assert.match(calls[1].url, /hub_system=Fictional\+remote\+hub/);
  calls[1].resolve(response(1, unsupported));
  await tick();
  assert.deepEqual(loads, ['area']);
  assert.deepEqual(renders, ['area']);
  assert.equal(posts.length, 0);
});

test('removing the last constellation preserves an empty preview instead of choosing defaults', async () => {
  const {ctx, get, calls, posts} = fixture();
  calls[0].resolve(response(1));
  await tick();
  get('area-hub').onchange();
  await tick();
  assert.deepEqual(Array.from(ctx.st.selected_constellations), []);
  assert.equal(get('next').disabled, true);
  assert.equal(calls.length, 1);
  assert.equal(posts.length, 0);
});

test('area edits cancel pending comparison work while coverage is refreshed', async () => {
  const {ctx, get, calls} = fixture();
  calls[0].resolve(response(1));
  await tick();
  let aborted = false;
  let prefetched = false;
  ctx.comparisonRequest = {abort() { aborted = true; }};
  ctx.prefetchTimer = setTimeout(() => { prefetched = true; }, 10);
  const sequence = ctx.seq;
  get('area-hub').onchange();
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(aborted, true);
  assert.equal(prefetched, false);
  assert.equal(ctx.seq, sequence + 1);
});

test('clearing the last constellation discards a pending coverage response', async () => {
  const {ctx, get, calls, renders} = fixture();
  let checked = [{value: '1'}];
  get('area-adv').querySelectorAll = selector => selector.includes(':checked') ? checked : [];
  calls[0].resolve(response(1));
  await tick();
  get('area-hub').onchange();
  checked = [];
  get('area-hub').onchange();
  calls[1].resolve(response(1, unsupported));
  await tick();
  assert.deepEqual(Array.from(ctx.st.selected_constellations), []);
  assert.equal(ctx.SELL_COVERAGE, covered);
  assert.equal(get('next').disabled, true);
  assert.deepEqual(renders, []);
});
