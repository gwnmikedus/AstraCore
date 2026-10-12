const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const guide = fs.readFileSync('src/astracore/modules/pi/templates/pi/guide.html','utf8');
const code = guide.slice(guide.indexOf('async function wireArea(step)'),guide.indexOf('// Save the answer on screen'));
function fixture() {
  const nodes = {}, calls = [], posts=[];
  const get = id => nodes[id] ||= {dataset:{},isConnected:true,hidden:false,value:'',querySelectorAll(){return[];}};
  const ctx={st:{selected_constellations:[],hub_system:''},$:get,API:'/pi/api',URLSearchParams,esc:String,
    fetch(url){return new Promise(resolve=>calls.push({url,resolve}));},setHint(){},paint(){},load(){},needsOwnTrip:()=>false,results:{},AC:{post(...args){posts.push(args);}}};
  vm.createContext(ctx);vm.runInContext(code,ctx);
  ctx.wireArea({id:'area'});
  return {ctx,nodes,get,calls,posts};
}
const response = id => ({ok:true,json:async()=>({selected:[id],constellations:[],systems:[]})});
async function tick(){await new Promise(resolve=>setImmediate(resolve));}
test('suggested area loads without saving; search races retain the newest result',async()=>{
  const {ctx,get,calls,posts}=fixture();
  calls[0].resolve(response(1));await tick();
  assert.deepEqual(Array.from(ctx.st.selected_constellations),[1]);assert.equal(posts.length,0);
  get('area-search').value='The Forge';get('find-area').onclick();
  get('area-search').value='Delve';get('find-area').onclick();
  calls[2].resolve(response(3));await tick();calls[1].resolve(response(2));await tick();
  assert.deepEqual(Array.from(ctx.st.selected_constellations),[3]);
  assert.equal(ctx.st.extra_area,'Delve');assert.equal(posts.length,0);
});
test('Continue saves the chosen area together with its travel answer once',async()=>{
 const calls=[];
 const ctx={hourSave:Promise.resolve(),picks:{area:'near'},optOf:()=>({patch:{max_systems:3,max_jumps:3}}),
  answered:new Set(['goal','cycle']),st:{selected_constellations:[1,2],extra_area:'The Forge',hub_system:'HUB'},saved:{},API:'/pi/api',
  AC:{post:async(url,body)=>{calls.push({url,body});return{ok:true};}}};
 vm.createContext(ctx);
 vm.runInContext(guide.slice(guide.indexOf('async function save(step, target)'),guide.indexOf('\n}',guide.indexOf('async function save(step, target)'))+2),ctx);
 await ctx.save({id:'area',isArea:true},3);
 assert.equal(calls.length,1);assert.deepEqual(Array.from(calls[0].body.selected_constellations),[1,2]);
 assert.equal(calls[0].body.extra_area,'The Forge');assert.equal(calls[0].body.max_systems,3);
 assert.deepEqual(Array.from(calls[0].body.answered),['goal','cycle','area']);
});

test('a searched area remains available after the own-trip prerequisite rerenders the question', async () => {
  const {ctx, get, calls} = fixture();
  calls[0].resolve(response(1));
  await tick();
  ctx.st.extra_area = 'Fictional region';
  ctx.st.selected_constellations = [7];
  ctx.wireArea({id: 'area'});
  assert.match(calls[1].url, /extra_area=Fictional\+region/);
  calls[1].resolve(response(2));
  await tick();
  assert.deepEqual(Array.from(ctx.st.selected_constellations), [7]);
});
