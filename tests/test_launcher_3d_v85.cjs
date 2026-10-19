'use strict';
const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../cuotago/static/js/launcher-3d-v85.js'), 'utf8');
function harness({ ready='loading', complete=false, naturalWidth=0, hasFrame=true }={}) {
  const listeners={}, windowListeners={}, events={};
  const classes = new Set();
  const frame = {classList:{add:c=>classes.add(c),toggle:(c,on)=>on?classes.add(c):classes.delete(c)}};
  const image = {complete,naturalWidth,dataset:{},closest:()=>hasFrame?frame:null,
    addEventListener:(k,f)=>{(listeners[k] ||= []).push(f);}};
  const document = {readyState:ready,querySelectorAll:()=>[image],addEventListener:(k,f)=>{events[k]=f;}};
  const window = {addEventListener:(k,f)=>{windowListeners[k]=f;}};
  vm.runInNewContext(source,{document,window});
  return {image,classes,listeners,dom:()=>events.DOMContentLoaded?.(),show:()=>windowListeners.pageshow?.(),
    fire:(k)=>listeners[k]?.forEach(f=>f())};
}
test('deferred startup binds only after DOM',()=>{
  const h=harness();assert.equal(h.image.dataset.artBound,undefined);h.dom();assert.equal(h.image.dataset.artBound,'1');
});
test('successful cached image keeps artwork',()=>{
  const h=harness({ready:'complete',complete:true,naturalWidth:256});assert.equal(h.classes.size,0);
});
test('already failed cached image shows original glyph',()=>{
  const h=harness({ready:'complete',complete:true});assert.ok(h.classes.has('cg-art-fallback-v85'));
});
test('loading image is not mistaken for failure',()=>{
  const h=harness({ready:'complete'});assert.equal(h.classes.size,0);
});
test('failure shows fallback and a later successful load recovers',()=>{
  const h=harness({ready:'complete'});h.fire('error');assert.ok(h.classes.has('cg-art-fallback-v85'));
  h.image.complete=true;h.image.naturalWidth=256;h.fire('load');assert.equal(h.classes.size,0);
});
test('bfcache restoration never multiplies listeners',()=>{
  const h=harness({ready:'complete'});for(let i=0;i<30;i++)h.show();
  assert.equal(h.listeners.load.length,1);assert.equal(h.listeners.error.length,1);
});
test('missing wrapper cannot crash navigation',()=>{
  const h=harness({ready:'complete',hasFrame:false});assert.equal(h.classes.size,0);assert.equal(Object.keys(h.listeners).length,0);
});
test('image handling does not fetch, reload, mutate storage or attach click handlers',()=>{
  for(const s of ['fetch(', 'setInterval(', 'location.reload', 'localStorage', 'sessionStorage', "addEventListener('click'"])
    assert.ok(!source.includes(s),s);
});
