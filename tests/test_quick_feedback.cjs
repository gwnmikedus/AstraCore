// In-context quick feedback (#301): the helpers that decide what goes with a note.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('src/astracore/static/js/quick-feedback.js', 'utf8');

function load() {
  const context = vm.createContext({window: {}});
  vm.runInContext(source, context);
  return context.window.AstraQuickFeedback;
}

// A tiny element tree: tag, id, classes, text, attributes; parent/children links and closest().
function el(tag, {id = '', classes = [], text = '', attrs = {}} = {}, children = []) {
  const node = {nodeType: 1, tagName: tag.toUpperCase(), id, classList: classes, attrs, children, parentElement: null,
    get textContent() { return text + children.map(c => c.textContent).join(' '); },
    getAttribute(name) { return name in attrs ? attrs[name] : null; },
    matches(selector) {
      return selector.split(',').map(s => s.trim()).some(s =>
        s === tag || (s.startsWith('[') && s.slice(1, -1) in attrs));
    },
    closest(selector) { for (let n = this; n; n = n.parentElement) if (n.matches(selector)) return n; return null; },
    querySelector(selector) {
      for (const child of children) {
        if (child.matches(selector)) return child;
        const deeper = child.querySelector(selector);
        if (deeper) return deeper;
      }
      return null;
    }};
  children.forEach(child => { child.parentElement = node; });
  return node;
}

test('selector paths stay short, structural and free of digit ids', () => {
  const qf = load();
  const target = el('button', {classes: ['option', 'char-90000001']});
  const sibling = el('button', {classes: ['option']});
  const list = el('div', {classes: ['options', 'qf-open']}, [sibling, target]);
  const section = el('section', {id: 'q'}, [list]);
  el('main', {id: 'main-content'}, [section]);
  assert.equal(qf.selectorFor(target), 'section#q > div.options > button.option:nth-of-type(2)');
  const deep = el('span');
  let node = deep;
  for (let i = 0; i < 6; i++) node = el('div', {id: `plan-${i}`}, [node]);
  assert.equal(qf.selectorFor(deep).split(' > ').length, 4);
  assert.ok(!/plan-\d/.test(qf.selectorFor(deep)));
});

test('labels name the control or section, with digits masked', () => {
  const qf = load();
  const icon = el('svg');
  const button = el('button', {text: 'Sell for 1,250,000 ISK'}, [icon]);
  assert.equal(qf.labelFor(icon), 'Sell for #,###,### ISK');
  const cell = el('span', {text: 'Some value'});
  const heading = el('h2', {text: 'Your planets'});
  el('section', {}, [heading, el('div', {}, [cell])]);
  assert.equal(qf.labelFor(cell), 'Your planets');
  const named = el('div', {attrs: {'aria-label': 'Colony card 3'}}, [el('i')]);
  assert.equal(qf.labelFor(named.children[0]), 'Colony card #');
  assert.ok(button);
});

test('the guide step is read from its tracker title', () => {
  const qf = load();
  const current = el('button', {attrs: {'aria-current': 'step', 'aria-label': 'Area: Jita, Perimeter'}},
    [el('span', {classes: ['lbl'], text: 'Area'}), el('span', {classes: ['ans'], text: 'Jita, Perimeter'})]);
  const doc = {querySelector: s => (s === '[aria-current="step"]' ? current : null)};
  current.querySelector = s => (s === '.lbl' ? current.children[0] : null);
  assert.equal(qf.stepName(doc), 'Area');
  assert.equal(qf.stepName({querySelector: () => null}), '');
});

test('the panel lists exactly what goes with the note', () => {
  const qf = load();
  const doc = {documentElement: {dataset: {theme: 'light'}}, querySelector: () => null};
  const win = {location: {pathname: '/pi/operate'}, innerWidth: 390.4, innerHeight: 844};
  const context = qf.collect(doc, win, {selector: 'section#build', label: 'Build'});
  const plain = value => JSON.parse(JSON.stringify(value));   // objects from the vm realm
  assert.deepEqual(plain(context),
    {path: '/pi/operate', viewport: '390x844', theme: 'light', target: {selector: 'section#build', label: 'Build'}});
  assert.deepEqual(plain(qf.describe(context, '0.9.1')), [
    ['Page', '/pi/operate'], ['Pointed at', '“Build”'], ['Screen', '390 × 844'], ['Theme', 'Light'], ['Version', '0.9.1']]);
  assert.ok(!('step' in context));
});
