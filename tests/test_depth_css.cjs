// Depth layer (grounds, grid, bevels, bands, orbit ornament): checked as text, since no test here renders the page.
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');

const read = file => readFileSync(path.join(__dirname, '..', file), 'utf8');
const css = read('src/astracore/static/css/astracore.css');
const orbital = read('src/astracore/static/css/orbital-command.css');
const print = read('src/astracore/static/css/print.css');
const TOKENS = ['--void-deep', '--band', '--grid-minor', '--grid-major', '--bevel', '--sheen', '--core-glow', '--ornament'];

const block = selector => {
  const at = css.indexOf(`${selector} {`);
  assert.ok(at >= 0, `${selector} has a token block`);
  return css.slice(at, css.indexOf('\n}', at));
};

test('every depth token has a Hull and a Chart value, and print neutralises it', () => {
  const hull = block(':root[data-theme="dark"]');
  const chart = block(':root[data-theme="light"]');
  for (const token of TOKENS) {
    assert.match(hull, new RegExp(`${token}:`), `${token} in Hull`);
    assert.match(chart, new RegExp(`${token}:`), `${token} in Chart`);
    assert.match(print, new RegExp(`${token}:`), `${token} reset for print`);
  }
});

test('the depth layer uses tokens only: no colour literals, no motion', () => {
  const at = orbital.indexOf('depth (#');
  assert.ok(at >= 0, 'depth block present');
  const depth = orbital.slice(orbital.lastIndexOf('/*', at));
  assert.doesNotMatch(depth.replace(/\/\*[\s\S]*?\*\//g, ''), /#[0-9a-f]{3,8}\b|rgba?\((?!0, 0, 0)/i, 'colours come from tokens (mask alpha excepted)');
  assert.doesNotMatch(depth, /animation|transition|@keyframes/, 'nothing in the depth layer moves');
  assert.match(depth, /body::before \{[^}]*pointer-events: none/, 'the grid never takes pointer events');
  assert.match(depth, /\.site-footer::after \{[^}]*pointer-events: none/, 'the ornament never takes pointer events');
  assert.match(depth, /body \{ overflow-x: clip; \}/, 'full-width bands never cause horizontal scroll');
});
