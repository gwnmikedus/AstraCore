// The plan pages keep their scripts in static files and pass server data as one JSON block (#299).
const assert = require('node:assert/strict');
const {readFileSync, existsSync} = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const root = path.join(__dirname, '..', 'src', 'astracore');
const read = rel => readFileSync(path.join(root, rel), 'utf8');
const PAGES = {guide: 'modules/pi/templates/pi/guide.html', planner: 'modules/pi/templates/pi/planner.html'};

test('the plan pages have no inline executable script, only a JSON data block', () => {
  for (const [name, file] of Object.entries(PAGES)) {
    const html = read(file);
    const scripts = [...html.matchAll(/<script\b([^>]*)>/g)].map(m => m[1]);
    const inline = scripts.filter(attrs => !/\bsrc=/.test(attrs) && !/type="application\/json"/.test(attrs));
    assert.deepEqual(inline, [], `${name}: inline script`);
    assert.equal(scripts.filter(attrs => /id="plan-data"/.test(attrs)).length, 1, `${name}: one plan-data block`);
    assert.match(html, /id="plan-data">\{\{ \{[\s\S]*?\}\|tojson \}\}<\/script>/, `${name}: data goes through tojson`);
    // The shared renderer first: the page script uses PLAN_DATA, planHTML and friends from it.
    const shared = html.indexOf("asset('js/plan-render.js')"), own = html.indexOf(`asset('js/${name}.js')`);
    assert.ok(shared > 0 && own > shared, `${name}: plan-render.js loads before ${name}.js`);
    assert.ok(html.indexOf('id="plan-data"') < shared, `${name}: data block before the scripts`);
  }
  assert.equal(existsSync(path.join(root, 'modules/pi/templates/pi/_plan_render.html')), false);
});

test('the static scripts carry no template syntax', () => {
  for (const file of ['guide.js', 'planner.js', 'plan-render.js']) {
    const js = read(`static/js/${file}`);
    assert.doesNotMatch(js, /\{\{|\{%/, file);
  }
});

test('every key the scripts read from PLAN_DATA is in the page data block', () => {
  for (const [name, file] of Object.entries(PAGES)) {
    const block = read(file).match(/id="plan-data">\{\{ \{([\s\S]*?)\}\|tojson/)[1];
    const given = new Set([...block.matchAll(/'(\w+)':/g)].map(m => m[1]));
    const used = new Set();
    for (const js of [read('static/js/plan-render.js'), read(`static/js/${name}.js`)])
      for (const m of js.matchAll(/PLAN_DATA\.(\w+)/g)) used.add(m[1]);
    for (const key of used) assert.ok(given.has(key), `${name}: PLAN_DATA.${key} is passed`);
  }
});

test('plan-render reads its configuration from the data block, with safe fallbacks', () => {
  const src = read('static/js/plan-render.js');
  const header = src.slice(0, src.indexOf('let NEVER'));
  const run = data => {
    const context = {JSON, document: {getElementById: id => (id === 'plan-data' ? {textContent: JSON.stringify(data)} : null)}};
    vm.createContext(context);
    vm.runInContext(header + ';this.out = {HELP, GLOSSARY, RICHNESS, TEMPLATE_REPO};', context);
    return context.out;
  };
  const full = run({help_answers: {isk: {label: 'Why?'}}, glossary_url: '/g', richness_labels: [['Poor', 0.5]], template_repo: 'https://example.invalid/t'});
  assert.equal(full.HELP.isk.label, 'Why?');
  assert.equal(full.GLOSSARY, '/g');
  assert.deepEqual(full.RICHNESS, [['Poor', 0.5]]);
  assert.equal(full.TEMPLATE_REPO, 'https://example.invalid/t');
  const empty = run({});
  assert.deepEqual(JSON.parse(JSON.stringify(empty)), {HELP: {}, GLOSSARY: '/pi/glossary', RICHNESS: [], TEMPLATE_REPO: ''});
});
