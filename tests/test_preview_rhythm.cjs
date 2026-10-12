const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const vm = require('node:vm');
const path = require('node:path');
const source = readFileSync(path.join(__dirname, '../src/astracore/static/js/astracore.js'), 'utf8');
const start = source.indexOf('    const preview = ');
const code = source.slice(start, source.indexOf('\n  });\n  AC.enterPanel', start));

function fixture(target = '/auth/login?rhythm=passive') {
  const link = {href: 'https://synthetic.example' + target};
  const fields = {};
  const buttons = ['passive', 'balanced', 'max', 'invalid'].map(key => ({
    dataset: {approach: key, product: 'synthetic-' + key}, attributes: {},
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(name, callback) { this[name] = callback; },
  }));
  const preview = {
    querySelectorAll: () => buttons,
    querySelector(selector) {
      if (selector === '[data-preview-start]') return link;
      return fields[selector] ||= {};
    },
  };
  vm.runInNewContext(code, {document: {querySelector: () => preview}, URL, AC: {enterPanel() {}}});
  return {link, fields, buttons};
}

test('choosing another rhythm updates the login target and the selected preview', () => {
  const {link, buttons, fields} = fixture('/auth/login?next=/feedback&rhythm=passive');
  buttons[1].click();
  const url = new URL(link.href);
  assert.equal(url.pathname, '/auth/login');
  assert.equal(url.searchParams.get('rhythm'), 'balanced');
  assert.equal(url.searchParams.get('next'), '/feedback');
  assert.equal(buttons[1].attributes['aria-pressed'], 'true');
  assert.equal(buttons[0].attributes['aria-pressed'], 'false');
  assert.match(fields['[data-preview-title]'].textContent, /industry/);
  buttons[2].click();
  assert.equal(new URL(link.href).searchParams.get('rhythm'), 'max');
});

test('signed-in previews keep the PI destination and unknown choices cannot change it', () => {
  const {link, buttons} = fixture('/pi?rhythm=passive');
  buttons[2].click();
  assert.equal(new URL(link.href).pathname, '/pi');
  assert.equal(new URL(link.href).searchParams.get('rhythm'), 'max');
  const before = link.href;
  buttons[3].click();
  assert.equal(link.href, before);
});

test('pages without the preview remain unaffected', () => {
  vm.runInNewContext(code, {document: {querySelector: () => null}});
});
