// Motion rules that live only in CSS (#245): checked as text, since no test here renders the page.
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');

const read = file => readFileSync(path.join(__dirname, '..', file), 'utf8');
const css = read('src/astracore/static/css/astracore.css');
const orbital = read('src/astracore/static/css/orbital-command.css');
const community = read('src/astracore/static/css/community.css');
const planner = read('src/astracore/modules/pi/templates/pi/planner.html');

// Split a stylesheet into what sits inside media blocks whose query contains `query`, and everything else.
function split(sheet, query) {
  let inside = '', outside = '', i = 0;
  for (;;) {
    const start = sheet.indexOf('@media', i);
    if (start < 0) { outside += sheet.slice(i); break; }
    const open = sheet.indexOf('{', start);
    let depth = 1, end = open + 1;
    while (depth) { if (sheet[end] === '{') depth++; else if (sheet[end] === '}') depth--; end++; }
    outside += sheet.slice(i, start);
    if (sheet.slice(start, open).includes(query)) inside += sheet.slice(open + 1, end - 1);
    else outside += sheet.slice(start, end);
    i = end;
  }
  return {inside, outside};
}

const rule = (sheet, selector) => {
  const at = sheet.indexOf(`${selector} {`);
  assert.ok(at >= 0, `${selector} has a rule`);
  return sheet.slice(at, sheet.indexOf('}', at) + 1);
};

test('hover nudges only apply where a pointer can hover, so they never stick after a tap', () => {
  const sheets = [split(css, '(hover: hover)'), split(orbital, '(hover: hover)')];
  const guarded = [
    '.text-action:hover .ic', '.site-menu > .menu-toggle:hover', '.header-action:hover', '.menu-group a:hover .menu-arrow',
    '.theme-toggle:hover', '.contributor:hover', '.text-action:hover .action-arrow', '.external-link:hover .external-indicator',
    '.contribution-card:hover', 'a:hover .icon-bug', 'a:hover .icon-lightbulb', '.platform-copy .text-action:hover',
    '.assurance-row a:hover', '.hero-replay:hover',
  ];
  for (const selector of guarded) {
    assert.ok(sheets.some(s => s.inside.includes(selector)), `${selector} is inside @media (hover: hover)`);
    assert.ok(sheets.every(s => !s.outside.includes(selector)), `${selector} is not outside it`);
  }
  // Keyboard focus keeps the same cue everywhere.
  assert.match(css, /\.text-action:focus-visible \.action-arrow \{ transform: translateX\(4px\); \}/);
  assert.match(css, /a:focus-visible \.icon-bug, \.contribution-card:focus-within \.contribution-symbol \.icon-bug \{ animation/);
});

test('the menu backdrop blurs at once and only fades its tint', () => {
  const backdrop = rule(css, '.menu-backdrop');
  assert.match(backdrop, /backdrop-filter: blur\(8px\)/);
  assert.doesNotMatch(backdrop, /animation|opacity|transition/);
  assert.match(rule(css, '.menu-backdrop::before'), /animation: menu-backdrop-in/);
  assert.match(css, /\.site-menu\[data-closing\] \.menu-backdrop::before \{ animation: menu-backdrop-out/);
  assert.doesNotMatch(css, /\.site-menu\[data-closing\] \.menu-backdrop \{/);
});

test('the planner result fades back as it fades out, and the busy badge shows as the flex row it is styled as', () => {
  assert.match(rule(css, 'div.result'), /transition: opacity \.2s/);
  assert.doesNotMatch(rule(css, 'div.result.loading'), /transition/);
  assert.match(rule(css, '#busy'), /display: flex/);
  assert.match(planner, /<div id="busy" role="status" hidden>/);
  assert.doesNotMatch(planner, /\$\('busy'\)\.style\.display/);
});

test('guide card bars carry no transition that could never run', () => {
  assert.doesNotMatch(rule(css, '.page-guide .bar i'), /transition/);
});

test('the dead horizon pulse is gone', () => {
  assert.doesNotMatch(community, /horizon-pulse|horizon-now/);
});

test('the wizard progress row steps aside for the floating menu button below the menu rail', () => {
  assert.match(css, /@media \(min-width: 761px\) and \(max-width: 1079px\) \{ html\[data-header-away\] \{ --menu-clear: [^}]+\} \}/);
  assert.match(css, /\.guide-progress \{ padding-left: var\(--menu-clear, 0px\); \}/);
});

test('on phones the save status keeps two lines, so its text changing after a save never moves Continue', () => {
  assert.match(css, /\.page-guide #save-status \{ min-width: 0; min-height: 36px;/);
});
