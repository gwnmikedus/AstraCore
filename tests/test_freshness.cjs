const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

function load() {
  const context = {};
  context.window = context;
  vm.runInNewContext(readFileSync(path.join(__dirname, '../src/astracore/static/js/freshness.js'), 'utf8'), context);
  return context.AC;
}

function line(url = '/refresh/auto') {
  const busy = {textContent: 'refreshing…'};
  const classes = new Set();
  return {busy, classes, dataset: url ? {autoRefresh: url} : {}, querySelector: () => busy,
    classList: {add: c => classes.add(c)}};
}

test('a fresh page does nothing', async () => {
  let posted = false;
  const r = await load().autoRefresh(line(null), {post: async () => { posted = true; }, reload: () => {}});
  assert.equal(r, 'skipped');
  assert.equal(posted, false);
});

test('a stale page asks for a refresh and reloads when it is done', async () => {
  const el = line();
  const calls = [];
  let reloaded = 0;
  const r = await load().autoRefresh(el, {post: async (url, body) => { calls.push([url, body]); return {refreshed: true, problems: {}}; },
    reload: () => { reloaded += 1; }});
  assert.equal(r, 'reloaded');
  assert.equal(JSON.stringify(calls), JSON.stringify([['/refresh/auto', {}]]));
  assert.equal(reloaded, 1);
  assert.equal(el.busy.textContent, 'updated, reloading…');
});

test('problems are shown before the reload', async () => {
  const el = line();
  let waited = 0, reloaded = 0;
  await load().autoRefresh(el, {post: async () => ({refreshed: true, problems: {Alt: 'needs a new EVE login'}}),
    reload: () => { reloaded += 1; }, wait: async ms => { waited = ms; }});
  assert.equal(el.busy.textContent, 'updated, except Alt (needs a new EVE login)');
  assert.ok(waited > 0);
  assert.equal(reloaded, 1);
});

test('no refresh (too soon, or an error) keeps the page and never loops', async () => {
  for (const answer of [{refreshed: false, wait: 200}, {error: 'Connection lost.'}]) {
    const el = line();
    let reloaded = 0;
    const r = await load().autoRefresh(el, {post: async () => answer, reload: () => { reloaded += 1; }});
    assert.equal(r, 'kept');
    assert.equal(reloaded, 0);
    assert.ok(el.classes.has('is-stale'));
    assert.notEqual(el.busy.textContent, 'refreshing…');
  }
});

test('many problems make one short line', async () => {
  const el = line();
  await load().autoRefresh(el, {post: async () => ({refreshed: true, problems: {A: 'All connection attempts failed', B: 'x', C: 'y'}}),
    reload: () => {}, wait: async () => {}});
  assert.equal(el.busy.textContent, '3 characters couldn’t be read (All connection attempts failed)');
});
