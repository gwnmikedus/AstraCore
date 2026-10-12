const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const path = require('node:path');
const vm = require('node:vm');

// A tiny DOM: a card (clickable, like a guided-setup answer) holding a "?" button and its answer.
function page() {
  const listeners = {};
  const doc = {
    nodes: {},
    addEventListener(type, fn, capture) { (listeners[type] = listeners[type] || []).push({fn, capture}); },
    getElementById(id) { return doc.nodes[id] || null; },
    querySelector(selector) {
      const m = selector.match(/aria-controls="([^"]+)"/);
      return m ? Object.values(doc.nodes).find(n => n.attrs['aria-controls'] === m[1]) || null : null;
    },
  };
  const node = (cls, attrs = {}, parent = null) => {
    const n = {cls, id: attrs.id || "", attrs: {...attrs}, parent, hidden: false, ownerDocument: doc, focused: false,
      getAttribute: k => (k in n.attrs ? n.attrs[k] : null), setAttribute: (k, v) => { n.attrs[k] = String(v); },
      focus() { n.focused = true; },
      closest(selector) {
        for (let x = n; x; x = x.parent) if (selector.split(',').some(s => s.trim() === '.' + x.cls)) return x;
        return null;
      }};
    if (attrs.id) doc.nodes[attrs.id] = n;
    return n;
  };
  const card = node('opt');
  const button = node('help-btn', {'aria-expanded': 'false', 'aria-controls': 'help-1', id: 'btn'}, card);
  const answer = node('help-answer', {id: 'help-1'}, card);
  answer.hidden = true;
  const link = node('more', {}, answer);
  // Dispatch like a browser: document capture listeners first; if they stop it, the card never hears it.
  let picked = 0;
  const dispatch = (type, target, extra = {}) => {
    const e = {type, target, stopped: false, prevented: false, ...extra,
      stopPropagation() { this.stopped = true; }, preventDefault() { this.prevented = true; }};
    for (const l of listeners[type] || []) if (l.capture) l.fn(e);
    if (!e.stopped && target.closest('.opt')) picked++;
    return e;
  };
  const context = {Intl, document: doc};
  context.window = context;
  for (const file of ['fmt.js', 'help.js', 'plan-help.js'])
    vm.runInNewContext(readFileSync(path.join(__dirname, '../src/astracore/static/js', file), 'utf8'), context);
  return {AC: context.AC, button, answer, link, card, dispatch, picked: () => picked};
}

test('the "?" markup is an accessible button that controls a hidden answer', () => {
  const {AC} = page();
  const html = AC.helpHTML({text: 'Less ISK <b>can</b> save time.', label: 'Why "less"?', more: '/pi/glossary#isk-vs-time', id: 'h1'});
  assert.match(html, /<button type="button" class="help-btn" aria-expanded="false" aria-controls="h1" aria-label="Why &quot;less&quot;\?" title="Why &quot;less&quot;\?">/);
  assert.match(html, /<span class="help-mark" aria-hidden="true">\?<\/span><\/button>/);
  assert.match(html, /<span class="help-answer" id="h1" hidden>Less ISK &lt;b&gt;can&lt;\/b&gt; save time\. <a href="\/pi\/glossary#isk-vs-time">More<\/a><\/span>/);
});

test('a labelled "?" shows its question and every toggle gets its own id', () => {
  const {AC} = page();
  const html = AC.helpHTML({text: 'x', label: 'Why no P3 factories?', showLabel: true});
  assert.match(html, /class="help-btn labelled"/);
  assert.match(html, /<span class="help-q">Why no P3 factories\?<\/span>/);
  assert.doesNotMatch(html, /aria-label=/);
  const ids = [AC.helpHTML({text: 'a'}), AC.helpHTML({text: 'b'})].map(h => h.match(/aria-controls="([^"]+)"/)[1]);
  assert.notEqual(ids[0], ids[1]);
  assert.doesNotMatch(html, /<a /);   // no "More" without a link
});

test('helpFor builds a toggle from a server answer with its glossary link', () => {
  const {AC} = page();
  const html = AC.helpFor({label: 'How is your time estimated?', text: 'A rough yardstick.', more: 'time-estimate'}, {glossary: '/pi/glossary'});
  assert.match(html, /aria-label="How is your time estimated\?"/);
  assert.match(html, /href="\/pi\/glossary#time-estimate"/);
  assert.equal(AC.helpFor(undefined), '');
});

test('a cramped "?" can put its answer elsewhere, still wired by id', () => {
  const {AC} = page();
  const {button, answer} = AC.helpPartsFor({label: 'Why this ISK figure?', text: 'Time counts.', more: 'isk-vs-time'}, {id: 'card-isk'});
  assert.match(button, /^<button type="button" class="help-btn" aria-expanded="false" aria-controls="card-isk"/);
  assert.match(answer, /^<span class="help-answer" id="card-isk" hidden>Time counts\. <a href="\/pi\/glossary#isk-vs-time">More<\/a><\/span>$/);
  const none = AC.helpPartsFor(null);
  assert.equal(none.button + none.answer, '');
});

test('click or tap toggles the answer and never picks the card around it', () => {
  const p = page();
  const e = p.dispatch('click', p.button);
  assert.equal(p.button.getAttribute('aria-expanded'), 'true');
  assert.equal(p.answer.hidden, false);
  assert.equal(e.prevented, true);
  assert.equal(p.picked(), 0);
  p.dispatch('click', p.button);
  assert.equal(p.button.getAttribute('aria-expanded'), 'false');
  assert.equal(p.answer.hidden, true);
  p.dispatch('click', p.link);          // the "More" link opens normally, the card stays unpicked
  assert.equal(p.picked(), 0);
  p.dispatch('click', p.card);          // the card itself still works
  assert.equal(p.picked(), 1);
});

test('keys on the "?" stay with it, and Escape closes the answer and returns focus', () => {
  const p = page();
  const enter = p.dispatch('keydown', p.button, {key: 'Enter'});
  assert.equal(enter.prevented, false);  // the browser still turns Enter/Space into a click
  assert.equal(p.picked(), 0);
  p.dispatch('keydown', p.button, {key: 'ArrowRight'});
  assert.equal(p.picked(), 0);
  p.dispatch('click', p.button);
  p.dispatch('keydown', p.link, {key: 'Escape'});
  assert.equal(p.button.getAttribute('aria-expanded'), 'false');
  assert.equal(p.answer.hidden, true);
  assert.equal(p.button.focused, true);
  p.dispatch('keydown', p.card, {key: 'Enter'});
  assert.equal(p.picked(), 1);
});

test('about the same: under 1% or 0.5M ISK a day', () => {
  const {AC} = page();
  assert.equal(AC.aboutSame(30e6, 30.4e6), true);     // 0.4M
  assert.equal(AC.aboutSame(100e6, 100.9e6), true);   // 0.9%
  assert.equal(AC.aboutSame(100e6, 101.5e6), false);
  assert.equal(AC.aboutSame(10e6, 10.6e6), false);
  assert.equal(AC.aboutSame(null, 1), false);
});

test('a plan below its allowed tier says how many miners a factory needs', () => {
  const {AC} = page();
  const need = {allowed: 4, used: 2, miners: 9, factory_miners: {2: 3, 3: 14, 4: 40}};
  const t = AC.tierHelp(need, {same: true, sameLabel: 'Up to P2'});
  assert.equal(t.short, 'Same plan as Up to P2');
  assert.equal(t.question, 'Why no P3 factories?');
  assert.match(t.text, /^At full speed, a typical P3 factory uses about 14 miners’ output; this plan has 9\. /);
  assert.match(t.text, /not a minimum colony count/);
  assert.match(t.text, /factories can run partially/);
  assert.match(t.text, /buying inputs is not modelled/);
  assert.equal(AC.tierHelp(need).short, 'Builds up to P2 only');
  const p1 = AC.tierHelp({allowed: 2, used: 1, miners: 4, factory_miners: {2: 1}}, {same: false});
  assert.equal(p1.short, 'Uses no factories');
  assert.match(p1.text, /about 1 miner’s output/);
});

test('no tier note when the plan uses every tier it may, or without numbers', () => {
  const {AC} = page();
  assert.equal(AC.tierHelp({allowed: 3, used: 3, miners: 5, factory_miners: {}}), null);
  assert.equal(AC.tierHelp({allowed: 3, used: 0, miners: 0, factory_miners: {}}), null);
  assert.equal(AC.tierHelp(undefined), null);
  const t = AC.tierHelp({allowed: 3, used: 2, miners: 5, factory_miners: {}});
  assert.match(t.text, /^Higher-tier factories need their complete input chain and suitable planets\./);
});
