// Advanced saves its applied plan through the guided save: same endpoint, same server-held result.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/astracore/modules/pi/templates/pi/planner.html', 'utf8');
const code = source.slice(source.indexOf('// ---- saving the applied plan'), source.indexOf('// ---- wire up'));

function setup(active = true) {
  const nodes = new Map();
  const $ = id => {
    if (!nodes.has(id)) nodes.set(id, {id, innerHTML: '', value: '', disabled: false,
      querySelectorAll: () => ['plan-save', 'plan-active'].filter(k => nodes.has(k)).map(k => nodes.get(k)),
      querySelector: () => null, insertAdjacentHTML(_, html) { this.innerHTML += html; }});
    return nodes.get(id);
  };
  const calls = [], links = [{dataset: {export: 'plan.md'}, href: ''}];
  const c = {$, API: '/pi/api', EXPORT: '/pi/export', EXPORT_Q: '?result=r1', updateSeq: 0, esc: String, isk: String,
    PLANS: active ? [{id: 5, active: true, label: 'Original', totals: {isk_per_day: 100}}] : [],
    schedule() { c.updateSeq += 1; c.scheduled = true; $('planbar').innerHTML = ''; },
    document: {querySelectorAll: () => links},
    AC: {post: (url, body) => new Promise(resolve => calls.push({url, body, resolve}))}};
  vm.createContext(c);
  vm.runInContext(code.replace(/\{\{ operate_url \}\}/g, '/pi/operate'), c);
  return {c, $, calls, links};
}
const flush = () => new Promise(resolve => setImmediate(resolve));

test('the applied result is saved and set active through the guided save endpoint', async () => {
  const {c, $, calls, links} = setup();
  c.planBar('applied-result');
  assert.match($('planbar').innerHTML, /Your active plan is <b>Original<\/b>.*Save as new plan.*Save and set as active plan/s);
  $('plan-label').value = 'Advanced';
  $('plan-active').onclick();
  assert.equal(calls[0].url, '/pi/api/plans');
  assert.equal(JSON.stringify(calls[0].body), JSON.stringify({result_id: 'applied-result', label: 'Advanced', active: true}));
  calls[0].resolve({ok: true, id: 9, label: 'Advanced', active: true, plans: [{id: 9, active: true}, {id: 5, active: false}]});
  await flush();
  assert.match($('planbar').innerHTML, /Saved as <b>Advanced<\/b> and set as your active plan.*href="\/pi\/operate"/);
  assert.equal(c.PLANS[0].id, 9);
  assert.equal(c.EXPORT_Q, '?plan=9');
  assert.equal(links[0].href, '/pi/export/plan.md?plan=9');
});

test('without an active plan only the activating save is offered', () => {
  const {c, $} = setup(false);
  c.planBar('applied-result');
  assert.match($('planbar').innerHTML, /No active plan yet/);
  assert.doesNotMatch($('planbar').innerHTML, /Save as new plan/);
});

test('a stale result asks for a fresh preview instead of saving something else', async () => {
  const {c, $, calls} = setup();
  c.planBar('applied-result');
  $('plan-save').onclick();
  assert.equal(calls[0].body.active, false);
  calls[0].resolve({error: 'Your planning data or answers changed.', stale: true});
  await flush();
  assert.ok(c.scheduled);
  assert.match($('planbar').innerHTML, /changed\. Apply these settings again/);
  assert.equal(c.EXPORT_Q, '?result=r1');
});

test('an edit while saving drops the answer; other errors re-enable the buttons', async () => {
  let {c, $, calls} = setup();
  c.planBar('applied-result');
  $('plan-active').onclick();
  c.updateSeq += 1;
  calls[0].resolve({ok: true, id: 9, label: 'Late', active: true});
  await flush();
  assert.doesNotMatch($('planbar').innerHTML, /Late/);
  ({c, $, calls} = setup());
  c.planBar('applied-result');
  $('plan-active').onclick();
  assert.equal($('plan-active').disabled, true);
  calls[0].resolve({error: 'Connection lost'});
  await flush();
  assert.equal($('plan-active').disabled, false);
  assert.match($('planbar').innerHTML, /Connection lost/);
});

test('copy no longer promises Operate follows an applied preview', () => {
  assert.doesNotMatch(source, /when built:/);
  assert.doesNotMatch(source, /Downloads now match this plan;/);
  assert.match(source, /Operate keeps tracking your active plan until you save this one/);
  assert.match(source, /if \(apply && !res\.error && res\.result_id\) planBar\(res\.result_id\)/);
});
