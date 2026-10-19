/* Deterministic tests for the actual inline bootstrap; no server or account. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../cuotago/templates/_launcher_preferences.html'), 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
const KEY = 'cuotago-launcher-appearance-v1';
const OLD = 'cuotago-pwa-launcher-size';
function fixture(initial = {}, options = {}) {
  const saved = new Map(Object.entries(initial));
  const writes = [];
  const hooks = new Map();
  const element = () => ({ value: '', textContent: '', dataset: {}, attrs: {}, handlers: {},
    setAttribute(k,v) { this.attrs[k]=v; },
    addEventListener(k,cb) { (this.handlers[k] ||= []).push(cb); },
    fire(k) { (this.handlers[k] || []).forEach(f=>f()); }
  });
  const nodes = {};
  for (const name of ['size-range','radius-range','size-output','radius-output','preview','status','reset']) nodes[name]=element();
  const query = (s) => {
    const name = s.match(/^\[data-launcher-(.+)\]$/)?.[1];
    if (name === 'settings') return [panel];
    return nodes[name] ? [nodes[name]] : [];
  };
  const panel = element();panel.querySelectorAll=query;
  const properties = {};
  const root = {dataset:{},style:{setProperty:(k,v)=>{properties[k]=v;}}};
  const context = { document:{documentElement:root,readyState:'complete',querySelectorAll:query,addEventListener(){}},
    localStorage: {getItem(k) { if(options.blockRead) throw Error('denied'); return saved.has(k)?saved.get(k):null; },
      setItem(k,v) { if(options.blockWrite) throw Error('denied');saved.set(k,v);writes.push([k,v]);}},
    addEventListener(k,fn) { (hooks.get(k) || hooks.set(k,[]).get(k)).push(fn); }
  };
  context.window=context;
  vm.createContext(context);vm.runInContext(source,context);
  const plain = x=>JSON.parse(JSON.stringify(x));
  return {state:()=>plain(context.CuotaGoLauncherAppearance.get()),api:context.CuotaGoLauncherAppearance,
    saved,writes,nodes,properties,context,
    event:(name,data)=>{(hooks.get(name)||[]).forEach(f=>f(data));}};
}
test('larger default and rounded square are applied before interaction',()=>{
 const x=fixture();assert.deepEqual(x.state(),{size:96,radius:30});assert.equal(x.properties['--cg-launcher-size'],'96%');assert.equal(x.properties['--cg-launcher-cap'],'107.52px');assert.equal(x.properties['--cg-launcher-radius'],'30%');assert.equal(x.writes.length,0);
});
test('one slider never changes the other preference',()=>{
 const x=fixture();x.api.update({size:100});assert.deepEqual(x.state(),{size:100,radius:30});x.api.update({radius:36});assert.deepEqual(x.state(),{size:100,radius:36});
});
test('minimum and maximum enforce readable, non-circular geometry',()=>{
 const x=fixture();x.api.update({size:-90,radius:-30});assert.deepEqual(x.state(),{size:76,radius:16});x.api.update({size:999,radius:50});assert.deepEqual(x.state(),{size:100,radius:36});
});
for (const raw of ['bad json','null','false','[]','{"size":null,"radius":false}','{"size":"NaN","radius":"Infinity"}','{"size":{},"radius":[]}']) {
 test('corrupt stored values fall back safely: '+raw,()=>assert.deepEqual(fixture({[KEY]:raw}).state(),{size:96,radius:30}));
}
test('numeric strings are rounded and clamped',()=>assert.deepEqual(fixture({[KEY]:'{"size":"92.6","radius":"32.3"}'}).state(),{size:93,radius:32}));
test('the old default migrates to the enlarged default',()=>assert.deepEqual(fixture({[OLD]:'72'}).state(),{size:96,radius:30}));
test('deliberate legacy size is respected without mutating the old key',()=>{
 const x=fixture({[OLD]:'68'});assert.deepEqual(x.state(),{size:88,radius:30});x.api.update({radius:32});assert.equal(x.saved.get(OLD),'68');
});
test('a new-format setting takes precedence over the legacy preference',()=>assert.deepEqual(fixture({[OLD]:'60',[KEY]:'{"size":100,"radius":34}'}).state(),{size:100,radius:34}));
test('live drag previews instantly but only commits once on change',()=>{
 const x=fixture();for(let v=76;v<=100;v++){x.nodes['size-range'].value=String(v);x.nodes['size-range'].fire('input');}
 assert.equal(x.state().size,100);assert.equal(x.nodes['size-output'].textContent,'100%');assert.equal(x.writes.length,0);
 x.nodes['size-range'].fire('change');assert.equal(x.writes.length,1);
 assert.deepEqual(fixture(Object.fromEntries(x.saved)).state(),{size:100,radius:30});
});
test('radius input, output and accessible preview stay synchronized',()=>{
 const x=fixture();x.nodes['radius-range'].value='36';x.nodes['radius-range'].fire('input');x.nodes['radius-range'].fire('change');
 assert.equal(x.nodes['radius-output'].textContent,'36%');assert.equal(x.nodes['radius-range'].attrs['aria-valuetext'],'36 por ciento de redondez');assert.match(x.nodes.preview.attrs['aria-label'],/36%/);
});
test('reset affects only these two preferences',()=>{
 const x=fixture({'cuotago-theme':'dark','cuotago-alert-audio-v1:1':'saved',[KEY]:'{"size":100,"radius":36}'});
 x.nodes.reset.fire('click');assert.deepEqual(x.state(),{size:96,radius:30});assert.equal(x.saved.get('cuotago-theme'),'dark');assert.equal(x.saved.get('cuotago-alert-audio-v1:1'),'saved');assert.match(x.nodes.status.textContent,/restablecidos/);
});
test('back/forward cache re-reads appearance and does not duplicate handlers',()=>{
 const x=fixture();x.saved.set(KEY,'{"size":99,"radius":35}');for(let n=0;n<10;n++)x.event('pageshow',{persisted:true});
 assert.deepEqual(x.state(),{size:99,radius:35});x.nodes['size-range'].value='98';x.nodes['size-range'].fire('change');assert.equal(x.writes.length,1);
});
test('other-tab changes and reset synchronize without writing again',()=>{
 const x=fixture();x.saved.set(KEY,'{"size":100,"radius":16}');x.event('storage',{key:KEY});assert.deepEqual(x.state(),{size:100,radius:16});x.saved.delete(KEY);x.event('storage',{key:null});assert.deepEqual(x.state(),{size:96,radius:30});assert.equal(x.writes.length,0);
});
test('a blocked storage read does not break rendering',()=>assert.deepEqual(fixture({}, {blockRead:true}).state(),{size:96,radius:30}));
test('a blocked storage write shows a truthful message',()=>{
 const x=fixture({}, {blockWrite:true});x.api.update({size:100});assert.equal(x.state().size,100);assert.match(x.nodes.status.textContent,/no permite guardar/);
});
test('returned state is a copy and repeated bootstrap is idempotent',()=>{
 const x=fixture();const state=x.api.get();state.size=1;assert.equal(x.state().size,96);vm.runInContext(source,x.context);x.nodes.reset.fire('click');assert.equal(x.writes.length,1);
});
