const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const vm = require('node:vm');
const path = require('node:path');

function client(fetch, now = Date.now) {
  const context = {
    document: {querySelector: () => ({content: 'test-csrf'}), addEventListener() {}},
    fetch, Date: {now}, location: {},
    setTimeout: callback => callback(),
  };
  context.window = context;
  vm.runInNewContext(readFileSync(path.join(__dirname, '../src/astracore/static/js/astracore.js'), 'utf8'), context);
  return context;
}

test('a lost connection returns a recoverable error instead of rejecting the UI handler', async () => {
  const {AC} = client(async () => { throw new TypeError('Failed to fetch'); });
  const result = await AC.post('/pi/api/save', {cycle_days: 3});
  assert.match(result.error, /Connection lost/);
});

test('cancelled comparisons are superseded instead of shown as failures', async () => {
  const {AC} = client(async () => { const error = new Error('aborted'); error.name = 'AbortError'; throw error; });
  assert.equal((await AC.post('/pi/api/whatif', {})).superseded, true);
});

test('queued work retries with CSRF and returns the eventual result', async () => {
  let calls = 0;
  let queued = 0;
  const {AC} = client(async (url, options) => {
    assert.equal(options.headers['X-CSRF-Token'], 'test-csrf');
    assert.equal(options.credentials, 'same-origin');
    calls++;
    return calls === 1 ? {status: 503, ok: false, json: async () => ({busy: true, retry_after: 1})}
      : {status: 200, ok: true, json: async () => ({ok: true})};
  });
  assert.equal((await AC.post('/pi/api/save', {}, {onBusy: () => queued++})).ok, true);
  assert.equal(calls, 2);
  assert.equal(queued, 1);
});

test('queue cancellation stops before a second request', async () => {
  let calls = 0;
  const signal = {aborted: false};
  const {AC} = client(async () => {
    calls++;
    return {status: 503, ok: false, json: async () => ({busy: true})};
  });
  const result = await AC.post('/pi/api/whatif', {}, {signal, onBusy: () => signal.aborted = true});
  assert.equal(result.superseded, true);
  assert.equal(calls, 1);
});

test('a saturated planner offers a retry instead of waiting forever', async () => {
  let time = 0;
  const {AC} = client(async () => ({status: 503, ok: false, json: async () => ({busy: true})}), () => time += 60001);
  assert.match((await AC.post('/pi/api/whatif', {})).error, /still busy/);
});

test('an expired session returns to the sign-in entry', async () => {
  const context = client(async () => ({status: 401, ok: false}));
  assert.equal((await context.AC.post('/pi/api/save', {})).error, 'Signed out');
  assert.equal(context.location.href, '/');
});

function flightTips(output = {textContent: 'First tip'}, button = {}) {
  let ready;
  let click;
  const context = {document: {
    addEventListener: (event, callback) => ready = callback,
    querySelector: selector => selector === '[data-next-tip]' ? button : output,
  }};
  if (button) button.addEventListener = (event, callback) => click = callback;
  vm.runInNewContext(readFileSync(path.join(__dirname, '../src/astracore/static/js/flight-tips.js'), 'utf8'), context);
  ready();
  return {output, button, click};
}

test('capsuleer tips change only on request, stay plain text, and wrap to the original', () => {
  const {output, button, click} = flightTips();
  assert.equal(button.hidden, false);
  assert.equal(output.textContent, 'First tip');
  const seen = new Set([output.textContent]);
  for (let i = 0; i < 5; i++) {
    click();
    assert.equal(seen.has(output.textContent), false);
    assert.equal(output.textContent.includes('<'), false);
    seen.add(output.textContent);
  }
  click();
  assert.equal(output.textContent, 'First tip');
});

test('pages without the capsuleer tip controls still initialize', () => {
  assert.doesNotThrow(() => flightTips(null, null));
});
