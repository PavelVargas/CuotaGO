/* Real badge watcher source with a deterministic clock, storage and events.
 * No live network or production records. Run: node --test tests/test_badge_lifecycle.cjs
 */
'use strict';
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const test = require('node:test'), assert = require('node:assert/strict');
const app = fs.readFileSync(path.join(__dirname, '../cuotago/static/js/app.js'), 'utf8');
const watcher = app.slice(app.indexOf('  const startPaymentAlertWatcher ='), app.indexOf('  const buildNotificationOptions'));
function fixture({cache = new Map(), scope='user1', hidden=false, fetchImpl=null}={}) {
  let now = 1000000, next=0;
  const timers = new Map(), calls=[], badges=[];
  const bus = () => {
    const handlers={};
    return {addEventListener:(n,f)=>(handlers[n]??=[]).push(f), emit:(n,e={})=>(handlers[n]||[]).forEach(f=>f(e))};
  };
  const clock = Object.assign(bus(), {setTimeout: (fn,delay) => {timers.set(++next,{fn,due:now+delay});return next;}});
  const doc = Object.assign(bus(), {visibilityState:hidden?'hidden':'visible',body:{classList:{contains:()=>true},dataset:{canCollect:'1',notificationScope:scope}}});
  const sw = bus(), nav={onLine:true,serviceWorker:sw};
  const ctx = vm.createContext({window:clock,document:doc,navigator:nav,IS_STANDALONE:true,
    Date: {now:()=>now}, AbortController, console,
    clearTimeout:id=>timers.delete(id),
    sessionStorage:{getItem:k=>cache.get(k)??null,setItem:(k,v)=>cache.set(k,String(v)),removeItem:k=>cache.delete(k)},
    updateNotificationBadge:n=>badges.push(n),
    fetchPaymentNotifications: async (opts)=>{calls.push(opts);return fetchImpl?fetchImpl(opts):{badgeCount:7};},
  });
  vm.runInContext(watcher+';startPaymentAlertWatcher();',ctx);
  const advance = async (ms) => {
    const until=now+ms;
    for(let i=0;i<100;i++) {
      const pair=[...timers].filter(([,t])=>t.due<=until).sort((a,b)=>a[1].due-b[1].due)[0];
      if(!pair)break;
      const [id,t]=pair;now=t.due;timers.delete(id);t.fn();
      for(let j=0;j<5;j++)await Promise.resolve();
    }
    now=until;
    for(let j=0;j<5;j++)await Promise.resolve();
  };
  return {advance, calls, badges, cache, doc, clock, nav, sw, timers};
}

test('badge warmup is deferred and only requests lightweight summary', async()=>{
 const f=fixture();assert.equal(f.calls.length,0);await f.advance(600);
 assert.equal(f.calls.length,1);assert.equal(f.calls[0].summary,true);
 assert.deepEqual(JSON.parse(f.cache.get('cuotago-badge-v71:user1')),{at:1000600,count:7});
});
test('recent numeric badge is reused on the next page, not full private data',async()=>{
 const f=fixture({cache:new Map([['cuotago-badge-v71:user1',JSON.stringify({at:999900,count:3})]])});
 assert.deepEqual(f.badges,[3]);await f.advance(1000);assert.equal(f.calls.length,0);
 await f.advance(90000);assert.equal(f.calls.length,1);
});
test('badge scope prevents one user from reusing another user cache',async()=>{
 const f=fixture({scope:'user2',cache:new Map([['cuotago-badge-v71:user1',JSON.stringify({at:999900,count:999})]])});
 assert.deepEqual(f.badges,[]);await f.advance(600);assert.equal(f.calls.length,1);
 assert.equal(JSON.parse(f.cache.get('cuotago-badge-v71:user2')).count,7);
});
test('hidden pages neither poll nor accumulate periodic requests',async()=>{
 const f=fixture({hidden:true});await f.advance(900000);assert.equal(f.calls.length,0);
 f.doc.visibilityState='visible';f.doc.emit('visibilitychange');await f.advance(600);assert.equal(f.calls.length,1);
 f.doc.visibilityState='hidden';f.doc.emit('visibilitychange');await f.advance(900000);assert.equal(f.calls.length,1);
});
test('hiding aborts in-flight request without replacing cached badge',async()=>{
 let deliver;
 const f=fixture({fetchImpl:()=>new Promise(r=>deliver=r)});await f.advance(600);
 f.doc.visibilityState='hidden';f.doc.emit('visibilitychange');assert.equal(f.calls[0].signal.aborted,true);
 deliver({badgeCount:555});await f.advance(1);assert.equal(f.cache.size,0);
});
test('submit/push invalidation cannot be undone by an older response',async()=>{
 let deliver;
 const f=fixture({fetchImpl:()=>new Promise(r=>deliver=r)});await f.advance(600);
 f.doc.emit('submit',{target:{method:'post'}});assert.equal(f.calls[0].signal.aborted,true);
 deliver({badgeCount:555});await f.advance(1);assert.equal(f.cache.size,0);
 await f.advance(600);assert.equal(f.calls.length,2);
 f.sw.emit('message',{data:{type:'CUOTAGO_PUSH'}});assert.equal(f.calls[1].signal.aborted,true);
});
test('corrupt storage and unavailable network do not break startup',async()=>{
 const f=fixture({cache:new Map([['cuotago-badge-v71:user1','broken-json']])});
 f.nav.onLine=false;await f.advance(600);assert.equal(f.calls.length,0);
 f.nav.onLine=true;f.clock.emit('online');await f.advance(600);assert.equal(f.calls.length,1);
});
test('restoring a page resumes polling once, not duplicate intervals',async()=>{
 const f=fixture();await f.advance(600);f.clock.emit('pagehide');await f.advance(100000);
 assert.equal(f.calls.length,1);f.clock.emit('pageshow');f.clock.emit('pageshow');await f.advance(600);
 assert.equal(f.calls.length,2);
});
