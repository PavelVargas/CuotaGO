/* Isolate the real app demo handler; fake network/OS promises, never send a push. */
const assert = require('node:assert/strict'), fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const app=fs.readFileSync(path.join(__dirname,'../cuotago/static/js/app.js'),'utf8');
const source=app.slice(app.indexOf('  let demoBusy = false;'),app.indexOf('  const normalizeAdminConfirmation'))+'\nglobalThis.runDemo = runNotificationDemo;';
let checks=0;const check=(v,m)=>{assert.ok(v,m);checks++;};
const flush=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};
function harness({subscription='ok',network='ok'}={}){
 let now=1000,id=0;const timers=new Map(),listeners={},counts={audio:0,subscribe:0,push:0,visual:0};
 const button={disabled:false,dataset:{},setAttribute(){},textContent:''};
 const h={counts,button};
 const window={CuotaGoNotificationAudio:{preview:async()=>{counts.audio++;return true;}},setTimeout(f,ms){const n=++id;timers.set(n,{at:now+ms,f});return n;},clearTimeout:n=>timers.delete(n),addEventListener:(n,f)=>{listeners[n]=f;}};
 const ctx={window,Date:{now:()=>now},AbortController,console,document:{querySelectorAll:()=>[button],querySelector:()=>null},pendingAlertSound:false,inAppAlertTimer:null,setLocalAlertsEnabled(){},updateLocalAlertStatus(){},setPushMessage(message){h.message=message;},friendlyPushError:async e=>e.message,showInAppPaymentAlert:(item,options)=>{counts.visual++;check(options.forceSound===false,'Demo visual must not play second sound');},subscribePushFromUserGesture(){counts.subscribe++;if(subscription==='reject')return Promise.reject(Error('blocked'));if(subscription==='wait')return new Promise(resolve=>{h.resolve=resolve;});return Promise.resolve({endpoint:'https://example.invalid/qa'});},apiJson(){counts.push++;if(network==='wait')return new Promise(()=>{});return Promise.resolve({message:'sent'});}};
 vm.createContext(ctx);vm.runInContext(source,ctx);h.run=ctx.runDemo;h.listeners=listeners;
 h.tick=async ms=>{now+=ms;for(const[n,t]of[...timers])if(t.at<=now){timers.delete(n);t.f();}await flush();};return h;
}
(async()=>{
 const h=harness();const results=Array.from({length:80},()=>h.run());await Promise.all(results);
 check(h.counts.subscribe===1,'Single subscription request');check(h.counts.push===1,'Single push test');check(h.counts.audio===1,'Single audio preview');check(h.counts.visual===1,'Single visual preview');
 check(h.button.disabled,'Cooldown active');await h.run();check(h.counts.subscribe===1,'No requests during cooldown');
 await h.tick(3001);check(!h.button.disabled,'Cooldown re-enables');await h.run();check(h.counts.push===2,'Explicit retry accepted');
 const fail=harness({subscription:'reject'});await fail.run();await fail.tick(3001);check(!fail.button.disabled,'Permission rejection does not trap button');check(fail.counts.push===0,'Never posts when denied');
 const wait=harness({subscription:'wait'});const pending=wait.run();await wait.tick(12001);await pending;
 check(wait.counts.push===0,'Subscription timeout never posts');await wait.tick(3001);check(!wait.button.disabled,'Timeout recovers UI');wait.resolve({endpoint:'https://example.invalid/late'});await flush();check(wait.counts.push===0,'Late permission does not trigger ghost push');
 const nav=harness({subscription:'wait'});const navigating=nav.run();nav.listeners.pagehide();nav.resolve({endpoint:'https://example.invalid/late'});await navigating;check(nav.counts.push===0,'No push after leaving page');check(!nav.button.disabled,'Navigation resets UI');
 const net=harness({network:'wait'});const req=net.run();await flush();await net.tick(10001);await req;await net.tick(3001);check(!net.button.disabled,'Network timeout recovers UI');
 console.log(`PASS: ${checks} UI80 notification-demo assertions`);
})().catch(e=>{console.error(e);process.exitCode=1;});
