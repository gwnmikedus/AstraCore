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

// The first random pick chooses the starting tip, the second the rare-tip chance.
const sequence = (...values) => { let i = 0; return () => values[i++ % values.length]; };

function flightTips({output = {textContent: 'First tip'}, button = {}, random = sequence(0, 0.99), reduced = false} = {}) {
  const context = {window: {}};
  vm.runInNewContext(readFileSync(path.join(__dirname, '../src/astracore/static/js/flight-tips.js'), 'utf8'), context);
  const api = context.window.AstraTips;
  let click;
  if (button) button.addEventListener = (event, callback) => { if (event === 'click') click = callback; };
  if (output) output.setAttribute = function (name, value) { this[name] = value; };
  const on = {};
  if (output) output.addEventListener = (event, callback) => { on[event] = callback; };
  const timers = [];
  let seen;
  const tips = api.setup({
    document: {querySelector: selector => selector === '[data-next-tip]' ? button : output, hidden: false},
    random, reducedMotion: () => reduced,
    schedule: (fn, ms) => { timers.push({fn, ms}); return timers.length; }, cancel: () => {},
    observe: (el, fn) => { seen = fn; },
  });
  return {api, tips, output, button, click, timers, on, setVisible: v => seen(v)};
}

test('capsuleer tips change on request, stay plain text, and wrap to the original', () => {
  const {output, button, click, api} = flightTips();
  assert.equal(button.hidden, false);
  assert.equal(output.textContent, 'First tip');
  const seen = new Set([output.textContent]);
  for (let i = 0; i < api.TIPS.length; i++) {
    click();
    assert.equal(seen.has(output.textContent), false);
    assert.equal(output.textContent.includes('<'), false);
    assert.equal(output['aria-live'], 'polite', 'a pressed tip is announced');
    seen.add(output.textContent);
  }
  click();
  assert.equal(output.textContent, 'First tip');
});

test('a page starts on a random tip, sometimes the rare one', () => {
  const {output, api} = flightTips({random: sequence(0.5, 0.99)});
  assert.notEqual(output.textContent, 'First tip');
  assert.ok(api.TIPS.includes(output.textContent));
  const rare = flightTips({random: sequence(0, 0.001)});
  assert.equal(rare.output.textContent, rare.api.RARE);
});

test('tips rotate silently only while the footer is in view and nobody is reading it', () => {
  const {output, timers, setVisible, api} = flightTips();
  assert.equal(timers.length, 1);
  assert.equal(timers[0].ms, api.ROTATE_MS);
  timers.shift().fn();
  assert.equal(output.textContent, 'First tip', 'off screen: no change');
  setVisible(true);
  timers.shift().fn();
  assert.notEqual(output.textContent, 'First tip');
  assert.equal(output['aria-live'], 'off', 'automatic changes are not announced');
});

test('hovering or focusing the tip holds it still', () => {
  const {output, timers, setVisible, on} = flightTips();
  setVisible(true);
  on.pointerenter();
  timers.shift().fn();
  assert.equal(output.textContent, 'First tip');
  on.pointerleave();
  timers.shift().fn();
  assert.notEqual(output.textContent, 'First tip');
});

test('tips never rotate on their own under reduced motion, but the button still works', () => {
  const {output, timers, click} = flightTips({reduced: true});
  assert.equal(timers.length, 0);
  click();
  assert.notEqual(output.textContent, 'First tip');
  assert.equal(timers.length, 0);
});

test('every capsuleer tip is short enough to keep the footer still', () => {
  const {api} = flightTips();
  for (const tip of api.TIPS.concat(api.RARE)) assert.ok(tip.length <= 80, tip);
});

test('pages without the capsuleer tip controls still initialize', () => {
  assert.doesNotThrow(() => flightTips({output: null, button: null}));
});

function externalLinks() {
  const context = {URL};
  context.window = context;
  for (const file of ['fmt.js', 'icons.js', 'links.js']) {
    vm.runInNewContext(readFileSync(path.join(__dirname, '../src/astracore/static/js', file), 'utf8'), context);
  }
  return context.AC;
}

test('browser-rendered external links identify GitHub, escape content, and label new tabs', () => {
  const AC = externalLinks();
  const html = AC.externalLink('https://github.com/example/templates', 'Template <P1>', {cls: 'kind-miner'});
  assert.match(html, /link-symbol icon-github/);
  assert.equal((html.match(/external-indicator/g) || []).length, 1);
  assert.match(html, /Template &lt;P1&gt;/);
  assert.match(html, /rel="noopener noreferrer"/);
  assert.match(html, /external site, opens in a new tab/);
  const withoutLeadingIcon = AC.externalLink('https://github.com/example', 'Pilot', {symbol: ''});
  assert.doesNotMatch(withoutLeadingIcon, /link-symbol icon-github/);
  assert.match(withoutLeadingIcon, /external-indicator/);
  const sameTab = AC.externalLink('https://vochauling.com', 'VOC', {newTab: false});
  assert.doesNotMatch(sameTab, /icon-github|target=|opens in a new tab/);
  assert.match(sameTab, /external site/);
});

test('external link helpers do not turn invalid destinations into executable links', () => {
  const AC = externalLinks();
  for (const href of ['javascript:alert(1)', 'data:text/html,example', 'not a URL']) {
    assert.equal(AC.externalLink(href, '<unsafe>'), '&lt;unsafe&gt;');
  }
  assert.doesNotMatch(AC.externalLink('https://github.com.evil.example/', 'Example'), /icon-github/);
});

test('relative times match the server-side ago filter', () => {
  const context = {Intl};
  context.window = context;
  vm.runInNewContext(readFileSync(path.join(__dirname, '../src/astracore/static/js/fmt.js'), 'utf8'), context);
  const {ago} = context.AC;
  const now = 1_000_000;
  assert.equal(ago(null, now), 'never');
  assert.equal(ago(now - 30, now), 'just now');
  assert.equal(ago(now - 600, now), '10 min ago');
  assert.equal(ago(now - 3 * 3600, now), '3 h ago');
  assert.equal(ago(now - 5 * 86400, now), '5 days ago');
});
