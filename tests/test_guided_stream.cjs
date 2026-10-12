// The guided setup draws each answer card as soon as it is planned, shows the queue honestly and warms
// the next question in the background (#85).
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const plain = value => JSON.parse(JSON.stringify(value));   // objects from the page's own realm

function client(fetch, now = Date.now) {
  const context = {
    document: {querySelector: () => ({content: 'test-csrf'}), addEventListener() {}},
    fetch, Date: {now}, location: {}, TextDecoder, Uint8Array,
    setTimeout: callback => callback(),
  };
  context.window = context;
  vm.runInNewContext(readFileSync(path.join(__dirname, '../src/astracore/static/js/astracore.js'), 'utf8'), context);
  return context;
}

// A streamed response whose body arrives in the given text chunks (split anywhere, even inside a line).
function streamed(chunks, onRead = () => {}) {
  const encoder = new TextEncoder();
  const queue = [...chunks];
  return {status: 200, ok: true, headers: {get: () => 'application/x-ndjson'},
    body: {getReader: () => ({
      read: async () => { onRead(); return queue.length ? {value: encoder.encode(queue.shift()), done: false} : {done: true}; },
      cancel: async () => {},
    })}};
}

test('streamed events reach the page one by one, even split across chunks', async () => {
  const seen = [];
  let request;
  const {AC} = client(async (url, options) => {
    request = options;
    return streamed(['{"queue": {"ahead": 2, "eta": 6}}\n{"card": {"id"', ': 1}}\n', '{"card": {"id": 2}}\n{"done": true}\n']);
  });
  const end = await AC.postStream('/pi/api/whatif', {options: []}, {onEvent: e => seen.push(e)});
  assert.deepEqual(plain(end), {done: true});
  assert.deepEqual(plain(seen), [{queue: {ahead: 2, eta: 6}}, {card: {id: 1}}, {card: {id: 2}}]);
  assert.equal(JSON.parse(request.body).stream, true);
  assert.equal(request.headers['X-CSRF-Token'], 'test-csrf');
});

test('the first card is shown before the rest of the stream has arrived', async () => {
  const seen = [];
  let reads = 0;
  const {AC} = client(async () => streamed(['{"card": {"id": 1}}\n', '{"card": {"id": 2}}\n{"done": true}\n'], () => {
    reads++;
    if (reads === 2) assert.deepEqual(plain(seen), [{card: {id: 1}}]);   // drawn before the second chunk is read
  }));
  await AC.postStream('/pi/api/whatif', {}, {onEvent: e => seen.push(e)});
  assert.equal(seen.length, 2);
});

test('a busy stream waits and asks again; cards already planned come back from the cache', async () => {
  let calls = 0, busy = 0;
  const seen = [];
  const {AC} = client(async () => ++calls === 1
    ? streamed(['{"card": {"id": 1}}\n{"busy": true, "retry_after": 1}\n'])
    : streamed(['{"card": {"id": 1}}\n{"card": {"id": 2}}\n{"done": true}\n']));
  const end = await AC.postStream('/pi/api/whatif', {}, {onEvent: e => seen.push(e), onBusy: () => busy++});
  assert.deepEqual(plain(end), {done: true});
  assert.equal(calls, 2);
  assert.equal(busy, 1);
});

test('replies that are not streams are handled like AC.post', async () => {
  const conflict = client(async () => ({status: 409, ok: false, headers: {get: () => 'application/json'},
    clone() { return this; }, json: async () => ({superseded: true})}));
  assert.deepEqual(plain(await conflict.AC.postStream('/pi/api/whatif', {})), {superseded: true});

  let calls = 0;
  const queued = client(async () => ++calls === 1
    ? {status: 503, ok: false, headers: {get: () => 'application/json'}, clone() { return this; }, json: async () => ({busy: true})}
    : streamed(['{"done": true}\n']));
  assert.deepEqual(plain(await queued.AC.postStream('/pi/api/whatif', {})), {done: true});

  const aborted = client(async () => { const e = new Error('aborted'); e.name = 'AbortError'; throw e; });
  assert.deepEqual(plain(await aborted.AC.postStream('/pi/api/whatif', {})), {superseded: true});

  const cut = client(async () => streamed(['{"card": {"id": 1}}\n']));
  assert.match((await cut.AC.postStream('/pi/api/whatif', {})).error, /stopped early/);
});

test('without a readable body the whole stream is read at once', async () => {
  const seen = [];
  const {AC} = client(async () => ({status: 200, ok: true, headers: {get: () => 'application/x-ndjson'},
    text: async () => '{"card": {"id": 1}}\n{"error": "Could not compare these setups."}\n'}));
  const end = await AC.postStream('/pi/api/whatif', {}, {onEvent: e => seen.push(e)});
  assert.deepEqual(plain(seen), [{card: {id: 1}}]);
  assert.equal(end.error, 'Could not compare these setups.');
});

// ---- guide.html -------------------------------------------------------------------------------
const guide = readFileSync(path.join(__dirname, '../src/astracore/modules/pi/templates/pi/guide.html'), 'utf8');
const code = guide.slice(guide.indexOf('function stepOptions(step)'), guide.indexOf('// The same answers as a table'));

function wizard(events) {
  const posts = [], painted = [], chosen = [], hints = [];
  const steps = [
    {id: 'cycle', options: [{id: 1, patch: {cycle_days: 1}}, {id: 3, patch: {cycle_days: 3}}], match: st => +st.cycle_days},
    {id: 'tier', options: [{id: 1, patch: {max_tier: 1}}, {id: 2, patch: {max_tier: 2}}], match: st => +st.max_tier},
    {id: 'plan', title: 'Your plan'},
  ];
  let release;
  const timers = [];
  const context = {
    STEPS: steps, cur: 0, st: {cycle_days: 3, max_tier: 2}, seq: 0, comparisonRequest: null, saving: false,
    results: {}, complete: {}, picks: {}, SELL_COVERAGE: {}, API: '/pi/api', AbortController, JSON, Object,
    setTimeout: callback => timers.push(callback), clearTimeout: id => { if (id) timers[id - 1] = null; },
    $: () => ({innerHTML: '', textContent: '', set onclick(f) {}}),
    needsOwnTrip: () => false, setHint: text => hints.push(text),
    recommend: () => 3,
    paint: step => painted.push(JSON.stringify(Object.keys(context.results[step.id] || {})) + (context.complete[step.id] ? ' done' : '')),
    choose(step, id) { chosen.push(id); context.picks[step.id] = id; Object.assign(context.st, step.options.find(o => o.id === id).patch); context.prefetchNext(step); },
    AC: {
      post: async (url, body) => { posts.push({url, body}); return {queued: 2}; },
      postStream: (url, body, opts) => new Promise(resolve => { release = () => {
        for (const e of events) opts.onEvent(e);
        resolve({done: true});
      }; posts.push({url, body}); }),
    },
  };
  vm.createContext(context);
  vm.runInContext(code, context);
  const flush = () => { const due = timers.splice(0); due.forEach(f => f && f()); };
  return {context, steps, posts, painted, chosen, hints, flush, release: () => release()};
}

test('cards are drawn as they arrive; the suggestion waits for every card', async () => {
  const {context, steps, painted, chosen, hints, release} = wizard([
    {queue: {ahead: 2, solves: 3, eta: 6}},
    {card: {id: 3, totals: {}}},
    {queue: {ahead: 0, solves: 0, eta: 0}},
    {card: {id: 1, totals: {}}},
  ]);
  const loading = context.load(steps[0]);
  assert.deepEqual(chosen, []);
  release();
  await loading;
  assert.deepEqual(painted, ['[]', '["3"]', '["1","3"]']);   // each card as it arrives, then all
  assert.deepEqual(chosen, [3]);
  assert.equal(context.complete.cycle, true);
  assert.match(hints[0], /2 pilots ahead of you, about 6 s/);
  assert.equal(hints[1], 'Comparing setups with your characters…');
});

test('a picked answer warms the next question with that answer, at low priority', async () => {
  const {context, steps, posts, flush, release} = wizard([{card: {id: 1, totals: {}}}, {card: {id: 3, totals: {}}}]);
  const loading = context.load(steps[0]);
  release();
  await loading;
  assert.equal(posts.filter(p => p.body.prefetch).length, 0);   // a short pause first: quick re-picks send one
  flush();
  const warm = posts.filter(p => p.body.prefetch);
  assert.equal(warm.length, 1);
  assert.equal(warm[0].url, '/pi/api/whatif');
  assert.equal(warm[0].body.base.cycle_days, 3);
  assert.deepEqual(warm[0].body.options.map(o => o.id), [1, 2]);
});

test('nothing is warmed after the last question or once the pilot has moved on', () => {
  const {context, steps, posts, flush} = wizard([]);
  context.prefetchNext(steps[1]);                       // next is the plan result: no cards to warm
  context.cur = 1;
  context.prefetchNext(steps[0]);                       // the pilot already left this question
  flush();
  assert.deepEqual(posts, []);
});

test('queue text is honest and short', () => {
  const {context} = wizard([]);
  assert.equal(context.queueText(null), 'Comparing setups with your characters…');
  assert.equal(context.queueText({ahead: 0, eta: 3}), 'Comparing setups with your characters…');
  assert.match(context.queueText({ahead: 1, eta: 0}), /1 pilot ahead of you, about 1 s/);
  assert.match(context.queueText({ahead: 12, eta: 150}), /12 pilots ahead of you, about 3 min/);
});

// ---- extra solves only on request -------------------------------------------------------------
function lazyPage(source, start, end, extra = {}) {
  const nodes = new Map();
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, {id, innerHTML: '', textContent: '', isConnected: true});
    return nodes.get(id);
  };
  const posts = [];
  const context = {API: '/pi/api', isk: String, esc: String, $: node, document: {getElementById: node},
    AC: {post: async (url, body) => { posts.push({url, body}); return extra.reply; }}, ...extra};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf(start), source.indexOf(end)), context);
  return {context, node, posts};
}

test('the yield range is worked out only when the pilot asks for it', async () => {
  const render = readFileSync(path.join(__dirname, '../src/astracore/modules/pi/templates/pi/_plan_render.html'), 'utf8');
  const {context, node, posts} = lazyPage(render, 'function fillYieldBand', "document.addEventListener('click'",
    {reply: {rows: [{factor: 0.5, isk_per_day: 10}, {factor: 2, isk_per_day: 40}]}});
  context.fillYieldBand({effort: 100});
  assert.match(node('yieldband').innerHTML, /Show the range/);
  assert.equal(posts.length, 0);
  await node('yieldband-show').onclick();
  assert.equal(posts[0].url, '/pi/api/sensitivity');
  assert.equal(posts[0].body.base.effort, 100);
  assert.equal(node('yieldband').textContent, 'At 0.5× the yield this plan makes 10/day, at 2× the yield this plan makes 40/day.');
});

test('the advanced view compares the three goals only once asked, then keeps them current', async () => {
  const planner = readFileSync(path.join(__dirname, '../src/astracore/modules/pi/templates/pi/planner.html'), 'utf8');
  const {context, node, posts} = lazyPage(planner, 'let altSeq = 0;', 'function markAlt()',
    {reply: [], markAlt() {}});
  context.document.querySelectorAll = () => [];
  await context.loadAlts({effort: 50});
  assert.match(node('alts-note').innerHTML, /Compare the three goals/);
  assert.equal(posts.length, 0);
  await node('alts-show').onclick();
  assert.equal(posts.length, 1);
  await context.loadAlts({effort: 100});              // a later settings change: compared straight away
  assert.equal(posts.length, 2);
  assert.equal(posts[1].body.base.effort, 100);
});
