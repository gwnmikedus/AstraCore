const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/astracore/modules/pi/templates/pi/planner.html', 'utf8');
function setup() {
  const nodes = Object.fromEntries(['apply-preview', 'preview-status', 'busy', 'result', 'h-effort'].map(k => [k, {disabled: false, textContent: '', style: {}, classList: {add(){}, remove(){}}, innerHTML: ''}]));
  const requests = [], draws = [], links = [{href: '/pi/export/plan.md?current=1', removeAttribute(k){ delete this[k]; }, setAttribute(k,v){this[k]=v;}}];
  const c = {API:"/pi/api", AbortController, setTimeout, clearTimeout, JSON, String, document: {querySelectorAll:()=>links},
    $: id=>nodes[id], state: ()=>({effort:100}), showLabels(){}, esc:String,
    AC:{post(url, body){return new Promise(resolve=>requests.push({url, body, resolve}));}},
    render(res,st){draws.push(res);}, updateSellingCoverage(){}, markAlt(){}, loadAlts(){}};
  vm.createContext(c);
  const code = source.slice(source.indexOf('let timer ='), source.indexOf('let altSeq ='));
  vm.runInContext('let altSeq = 0;'+code, c);
  return {c,nodes,requests,draws,links};
}
test('advanced requests are previews until explicit apply and carry server baseline', async()=>{
  const {c,requests,draws,nodes}=setup();
  let p=vm.runInContext('update()', c);
  assert.equal(requests[0].url,'/pi/api/preview');
  assert.equal(requests[0].body.settings.effort,100);
  requests[0].resolve({preview:true,baseline:{effort:50}}); await p;
  assert.equal(nodes['apply-preview'].disabled,false);
  p=vm.runInContext('update(true)',c);
  assert.equal(requests[1].url,'/pi/api/apply');
  assert.equal(requests[1].body.baseline.effort,50);
  requests[1].resolve({preview:false,baseline:{effort:100}});await p;
  assert.equal(draws.length,2);
  assert.match(nodes['preview-status'].textContent,/Settings applied/);
});
test('older responses cannot draw or reenable Apply after a newer preview', async()=>{
  const {c,requests,draws,nodes}=setup();
  const older=vm.runInContext('update()',c), latest=vm.runInContext('update()',c);
  requests[1].resolve({preview:true,baseline:{effort:100}});await latest;
  requests[0].resolve({error:'obsolete'});await older;
  assert.equal(draws.length,1);
  assert.equal(nodes['apply-preview'].disabled,false);
});
test('editing invalidates Apply and exports immediately before debounce', ()=>{
  const {c,nodes,links}=setup();
  vm.runInContext('invalidatePreview()',c);
  assert.equal(nodes['apply-preview'].disabled,true);
  assert.equal(links[0].href,undefined);
  assert.equal(links[0]['aria-disabled'],'true');
});
test('only an explicitly applied snapshot supplies downloadable result URLs', ()=>{
  const {c,links}=setup();
  c.planHTML=()=>'';c.fillYieldBand=()=>{};c.num=String;c.isk=String;
  vm.runInContext("let EXPORT_Q = '';"+source.slice(source.indexOf('function render(res, st)'),source.indexOf('// ---- wire up')),c);
  vm.runInContext('render({preview:true}, {})',c);
  assert.equal(vm.runInContext('EXPORT_Q',c),'');
  vm.runInContext('render({result_id:"applied/handle"}, {})',c);
  assert.equal(vm.runInContext('EXPORT_Q',c),'?result=applied%2Fhandle');
});
