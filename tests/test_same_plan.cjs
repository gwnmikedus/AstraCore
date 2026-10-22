// #232: a wider answer showing the plan of an answer it contains ("Same plan as Up to P3") saves that answer.
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const guide = readFileSync(path.join(__dirname, '../src/astracore/modules/pi/templates/pi/guide.html'), 'utf8');
const line = start => guide.slice(guide.indexOf(start), guide.indexOf('\n', guide.indexOf(start)));
const between = (start, end) => guide.slice(guide.indexOf(start), guide.indexOf(end, guide.indexOf(start)));
const code = [
  line('const optOf = '), line('const answerOf = '), line('const labelOf = '),
  between('function choose(step, id)', 'function paint(step)'),
  between('function sameAsHTML(step, r)', '// Products step: a card whose'),
  between('async function save(step, target', '// ---- the result'),
].join('\n').replace(/^const /gm, 'var ');   // top-level consts become context properties

const tier = {id: 'tier', match: st => +st.max_tier, options: [1, 2, 3, 4].map(t => ({id: t, label: `Up to P${t}`, patch: {max_tier: t}}))};

function fixture() {
  const posts = [];
  const context = {
    st: {max_tier: 2}, saved: {max_tier: 2}, picks: {}, answered: new Set(), OPTIONAL_IDS: new Set(),
    hourSave: Promise.resolve(), API: '/pi/api', esc: String,
    results: {tier: {3: {totals: {isk_per_day: 95}}, 4: {totals: {isk_per_day: 95}, same_as: 3}}},
    paint() {}, prefetchNext() {},
    AC: {post: (url, body) => { posts.push(body); return Promise.resolve({ok: true}); }},
  };
  vm.createContext(context);
  vm.runInContext(code, context);
  return {context, posts};
}

test('picking a "same plan" card plans on with the contained answer and saves it', async () => {
  const {context, posts} = fixture();
  context.choose(tier, 4);
  assert.equal(context.picks.tier, 4);              // the card the pilot clicked stays selected
  assert.equal(context.st.max_tier, 3);             // later questions plan with the answer whose plan is shown
  assert.equal(context.labelOf(tier), 'Up to P3');
  await context.save(tier, 4);
  assert.equal(posts[0].max_tier, 3);
  assert.equal(context.saved.max_tier, 3);
});

test('an ordinary card saves its own answer', async () => {
  const {context, posts} = fixture();
  context.choose(tier, 3);
  assert.equal(context.st.max_tier, 3);
  await context.save(tier, 4);
  assert.equal(posts[0].max_tier, 3);
  delete context.results.tier;                     // no comparison (yet): the pick's own answer
  context.picks.tier = 4;
  assert.equal(context.answerOf(tier, 4).patch.max_tier, 4);
});

test('the card says which answer it keeps', () => {
  const {context} = fixture();
  const html = context.sameAsHTML(tier, context.results.tier[4]);
  assert.match(html, /Same plan as Up to P3, which earns more here\. Choosing this keeps Up to P3\./);
  assert.equal(context.sameAsHTML(tier, {same_as: 9}), '');
});

test('the card shows the note instead of the tier explanation once the correction arrives', () => {
  assert.match(guide, /r\.same_as != null \? sameAsHTML\(step, r\) : step\.id === 'tier' \? samePlanHTML\(step, o, r, res\)/);
});
