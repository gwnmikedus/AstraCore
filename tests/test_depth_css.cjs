// Quiet grounds and the space doodles (#287): checked as text, since no test here renders the page.
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');

const read = file => readFileSync(path.join(__dirname, '..', file), 'utf8');
const css = read('src/astracore/static/css/astracore.css');
const orbital = read('src/astracore/static/css/orbital-command.css');
const print = read('src/astracore/static/css/print.css');
const doodles = read('src/astracore/templates/_doodles.html');
const home = read('src/astracore/templates/home.html');
const TOKENS = ['--void-deep', '--band', '--sheen', '--core-glow', '--doodle-ink', '--doodle-fill', '--doodle-soft'];

const block = selector => {
  const at = css.indexOf(`${selector} {`);
  assert.ok(at >= 0, `${selector} has a token block`);
  return css.slice(at, css.indexOf('\n}', at));
};

test('every depth and doodle token has a Hull and a Chart value, and print neutralises it', () => {
  const hull = block(':root[data-theme="dark"]');
  const chart = block(':root[data-theme="light"]');
  for (const token of TOKENS) {
    assert.match(hull, new RegExp(`${token}:`), `${token} in Hull`);
    assert.match(chart, new RegExp(`${token}:`), `${token} in Chart`);
    assert.match(print, new RegExp(`${token}:`), `${token} reset for print`);
  }
  assert.match(print, /\.doodle \{ display: none !important; \}/, 'doodles never print');
});

test('the doodle layer uses tokens only, never moves and never widens the page', () => {
  const at = orbital.indexOf('space doodles and quiet grounds (#');
  assert.ok(at >= 0, 'doodle block present');
  const layer = orbital.slice(orbital.lastIndexOf('/*', at)).replace(/\/\*[\s\S]*?\*\//g, '');
  assert.doesNotMatch(layer, /#[0-9a-f]{3,8}\b|rgba?\(/i, 'colours come from tokens');
  assert.doesNotMatch(layer, /animation|transition|@keyframes/, 'nothing drifts');
  assert.doesNotMatch(layer, /inset: 0 -100vmax/, 'bands never add scrollable overflow');
  assert.match(layer, /\.doodle \{[^}]*pointer-events: none/, 'doodles never take pointer events');
});

test('doodles are decorative inline SVG: hidden from assistive tech, no scripts, no colour literals', () => {
  const svgs = doodles.match(/<svg [^>]*>/g) || [];
  assert.ok(svgs.length >= 6, 'a set of doodles exists');
  for (const svg of svgs) {
    assert.match(svg, /aria-hidden="true"/);
    assert.match(svg, /focusable="false"/);
  }
  assert.doesNotMatch(doodles, /<script|on[a-z]+=|href=|fill='#|stroke='#|style=/i);
  assert.match(home, /class="doodle-divider[^"]*" aria-hidden="true"/, 'landing dividers are hidden from assistive tech');
});
