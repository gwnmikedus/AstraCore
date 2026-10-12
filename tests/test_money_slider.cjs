const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const path = require('node:path');
const vm = require('node:vm');

function slider(value = 90e6, defaultValue = 90e6, isDefault = true) {
  const context = {Intl};
  context.window = context;
  vm.runInNewContext(readFileSync(path.join(__dirname, '../src/astracore/static/js/fmt.js'), 'utf8'), context);
  vm.runInNewContext(readFileSync(path.join(__dirname, '../src/astracore/static/js/money-slider.js'), 'utf8'), context);
  const elements = {};
  for (const name of ['range', 'exact', 'output', 'reset', 'error', 'max', 'help']) {
    elements[name] = {
      value: String(value), max: Math.max(500e6, value), listeners: {}, attributes: {},
      addEventListener(event, callback) { this.listeners[event] = callback; },
      setAttribute(name, content) { this.attributes[name] = content; },
      setCustomValidity(message) { this.validationMessage = message; },
      get validity() { return {valid: !this.validationMessage}; },
      closest() { return null; },
      reportValidity() { return !this.validationMessage; },
    };
  }
  const properties = {};
  const root = {
    querySelector: selector => elements[selector.match(/data-money-(\w+)/)[1]],
    style: {setProperty: (key, next) => properties[key] = next},
  };
  const commits = [];
  const control = context.AC.wireMoneySlider(root, {value, defaultValue, isDefault,
    onCommit: (next, options) => commits.push({next, useDefault: options.useDefault})});
  return {context, root, control, elements, commits, properties};
}

test('dragging updates the readout and exact entry without committing on each input', () => {
  const {elements, commits, properties} = slider();
  for (const value of [100e6, 125e6, 150e6]) {
    elements.range.value = String(value);
    elements.range.listeners.input();
  }
  assert.equal(commits.length, 0);
  assert.equal(Number(elements.exact.value), 150e6);
  assert.equal(elements.output.textContent, '150.0M ISK/hour');
  assert.equal(properties['--money-progress'], '30%');
  elements.range.listeners.change();
  elements.range.listeners.change();
  assert.deepEqual(commits, [{next: 150e6, useDefault: false}]);
});

test('custom saved amounts survive initialization, preview and unrelated repaint exactly', () => {
  const saved = 12345678.125;
  const {control, elements, commits} = slider(saved, 90e6, false);
  assert.equal(Number(elements.range.value), saved);
  assert.equal(Number(elements.exact.value), saved);
  assert.equal(elements.range.attributes['aria-valuetext'], '12,345,678.125 ISK/hour');
  elements.exact.value = '12345679,875';
  elements.exact.listeners.input();
  control.setValue(saved, 90e6, false);
  assert.equal(elements.exact.value, '12345679,875');
  assert.equal(commits.length, 0);
  elements.exact.listeners.change();
  assert.deepEqual(commits, [{next: 12345679.875, useDefault: false}]);
});

test('the range accommodates large saved amounts and stays stable throughout a drag', () => {
  const {elements, commits} = slider(2e9, 90e6, false);
  assert.equal(Number(elements.range.value), 2e9);
  assert.equal(Number(elements.range.max), 2e9);
  for (const value of [1.8e9, 1.2e9, 300e6]) {
    elements.range.value = String(value);
    elements.range.listeners.input();
    assert.equal(Number(elements.range.max), 2e9);
  }
  assert.equal(commits.length, 0);
});

test('blank, negative, nonnumeric and infinite entries cannot save a preference', () => {
  const {control, elements, commits} = slider();
  for (const value of ['', '-1', 'bad', 'Infinity', '1e309']) {
    elements.exact.value = value;
    elements.exact.listeners.input();
    elements.exact.listeners.change();
    assert.equal(control.reportValidity(), false);
    assert.equal(elements.exact.attributes['aria-invalid'], 'true');
    assert.equal(elements.error.hidden, false);
  }
  assert.equal(commits.length, 0);
  elements.exact.value = '0';
  elements.exact.listeners.change();
  assert.equal(control.reportValidity(), true);
  assert.deepEqual(commits, [{next: 0, useDefault: false}]);
});

test('invalid input reveals a closed containing disclosure before the browser reports validity', () => {
  const {control, elements, commits} = slider();
  const details = {open: false};
  elements.exact.closest = selector => selector === 'details:not([open])' && !details.open ? details : null;
  elements.exact.reportValidity = () => {
    assert.equal(details.open, true);
    return elements.exact.validity.valid;
  };
  elements.exact.value = '';
  assert.equal(control.reportValidity(), false);
  assert.equal(elements.error.hidden, false);
  assert.deepEqual(commits, []);
});

test('reset uses the current goal default and controls lock during answer saving', () => {
  const {control, elements, commits} = slider(125e6, 90e6, false);
  control.setValue(125e6, 300e6, false);
  elements.reset.listeners.click();
  assert.deepEqual(commits, [{next: 300e6, useDefault: true}]);
  control.setValue(300e6, 300e6, true);
  assert.equal(elements.reset.disabled, true);
  control.setValue(125e6, 300e6, false);
  control.setDisabled(false);
  assert.equal(elements.reset.disabled, false);
  control.setDisabled(true);
  for (const name of ['range', 'exact', 'reset']) assert.equal(elements[name].disabled, true);
});

test('reset recovers invalid exact editing even when starting from a goal default', () => {
  const {control, elements, commits} = slider();
  assert.equal(elements.reset.disabled, true);
  elements.exact.value = 'invalid';
  elements.exact.listeners.input();
  control.setValue(90e6, 90e6, true);
  control.setDisabled(false);
  assert.equal(elements.reset.disabled, false);
  elements.reset.listeners.click();
  assert.equal(control.reportValidity(), true);
  assert.deepEqual(commits, [{next: 90e6, useDefault: true}]);
});

function guidedSlider(value = -1) {
  const setup = slider();
  const {context, root, elements} = setup;
  const requests = [];
  let repaint = 0;
  let reload = 0;
  context.st = {hour_isk: value};
  context.HOUR_DEFAULT = {balanced: 90e6};
  context.goalId = () => 'balanced';
  context.iskPerHour = () => context.st.hour_isk >= 0 ? context.st.hour_isk : 90e6;
  context.saving = false;
  context.hourSave = Promise.resolve();
  context.hourSaveRevision = 0;
  context.API = '/pi/api';
  context.$ = id => id === 'hour' ? root : elements.output;
  context.paint = () => {
    repaint++;
    context.hourControl.setValue(context.iskPerHour(), 90e6, context.st.hour_isk < 0);
  };
  context.load = () => { reload++; };   // the value of your time changes the plans: compare again
  context.AC.post = (url, body) => new Promise(resolve => requests.push({url, body, resolve}));
  const guide = readFileSync(path.join(__dirname, '../src/astracore/modules/pi/templates/pi/guide.html'), 'utf8');
  vm.runInNewContext(guide.slice(guide.indexOf('function hourPicker()'), guide.indexOf('const net =')), context);
  context.wireHour({});
  return {...setup, requests, repaints: () => repaint, reloads: () => reload};
}

test('guide serializes preference saves and skips stale queued values without recalculating on input', async () => {
  const {context, elements, requests, repaints, reloads} = guidedSlider(12345678.125);
  assert.equal(requests.length, 0);
  assert.equal(Number(elements.exact.value), 12345678.125);
  elements.range.value = '125000000';
  elements.range.listeners.input();
  assert.equal(requests.length, 0);
  assert.equal(repaints(), 0);
  assert.equal(reloads(), 0);
  elements.range.listeners.change();
  assert.equal(reloads(), 1);
  await Promise.resolve();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].body.hour_isk, 125e6);
  for (const next of [150e6, 200e6]) {
    elements.range.value = String(next);
    elements.range.listeners.input();
    elements.range.listeners.change();
  }
  assert.equal(context.st.hour_isk, 200e6);
  assert.equal(requests.length, 1);
  requests[0].resolve({ok: true});
  for (let i = 0; i < 8; i++) await Promise.resolve();
  assert.equal(requests.length, 2);
  assert.equal(requests[1].body.hour_isk, 200e6);
  requests[1].resolve({ok: true});
  await context.hourSave;
  assert.equal(elements.output.textContent, 'Time preference saved');
});

test('guide reset persists the goal sentinel and exact zero stays numeric for balanced', async () => {
  const {context, elements, requests} = guidedSlider(125e6);
  elements.reset.listeners.click();
  assert.equal(context.st.hour_isk, -1);
  await Promise.resolve();
  assert.equal(requests[0].body.hour_isk, -1);
  requests[0].resolve({ok: true});
  await context.hourSave;
  elements.exact.value = '0';
  elements.exact.listeners.change();
  assert.equal(context.st.hour_isk, 0);
  await Promise.resolve();
  assert.equal(requests[1].body.hour_isk, 0);
  requests[1].resolve({ok: true});
  await context.hourSave;
});

test('native range semantics and labels expose keyboard controls and precise entry', () => {
  const {context} = slider();
  const html = context.AC.moneySliderHTML('time', 90e6);
  assert.match(html, /type="range" id="time-range" min="0" max="500000000" step="any" value="90000000"/);
  assert.match(html, /<label for="time-range">/);
  assert.match(html, /<label for="time-exact">Exact ISK\/hour/);
  assert.match(html, /aria-describedby="time-error"/);
});
