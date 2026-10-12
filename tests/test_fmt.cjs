const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const context = {Intl};
context.window = context;
vm.runInNewContext(readFileSync(path.join(__dirname, '../src/astracore/static/js/fmt.js'), 'utf8'), context);
const {pct} = context.AC;

test('whole percentages retain significant zeros and distinguish small positive shares', () => {
  for (const [value, expected] of [[0, '0%'], [0.1, '<1%'], [0.9, '<1%'], [1, '1%'],
    [10, '10%'], [20, '20%'], [100, '100%'], [1000, '1000%'], [-10, '-10%'], [-0.1, '0%']]) {
    assert.equal(pct(value, 0), expected, String(value));
  }
});

test('decimal percentages trim only fractional zeros and missing values remain absent', () => {
  assert.equal(pct(10), '10%');
  assert.equal(pct(0.1), '0.1%');
  assert.equal(pct(10.25, 2), '10.25%');
  assert.equal(pct(10.2, 2), '10.2%');
  for (const value of [null, undefined, '', NaN]) assert.equal(pct(value, 0), '–');
});
