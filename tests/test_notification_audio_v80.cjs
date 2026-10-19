/* node tests/test_notification_audio_v80.cjs
   Deterministic regression: rapid taps, cancellation, timeout, and single context. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../cuotago/static/js/notification-audio.js'), 'utf8');
let checks = 0;
function check(value, message) { assert.ok(value, message); checks++; }
async function flush() { for (let i = 0; i < 20; i++) await Promise.resolve(); }
function harness({resume = 'immediate', supported = true} = {}) {
  let time = 0, seq = 0;
  const timers = new Map(), listeners = {}, contexts = [], oscillators = [], store = new Map();
  const label = {textContent: ''}, status = {textContent: ''};
  const button = {disabled:false, attrs:{}, setAttribute(k,v){this.attrs[k]=v;}, querySelector(){return label;},addEventListener(){}};
  const node = () => ({connect(){},disconnect(){this.disconnected=true;}});
  const param = () => ({value:0,setValueAtTime(v){this.value=v;},linearRampToValueAtTime(){},exponentialRampToValueAtTime(){}});
  class Audio {
    constructor(){this.state='suspended';this.currentTime=0;this.sampleRate=44100;this.destination=node();this.mode=resume;contexts.push(this);}
    createGain(){return {...node(),gain:param()};}
    createDynamicsCompressor(){return {...node(),threshold:param(),knee:param(),ratio:param(),attack:param(),release:param()};}
    createBuffer(){return {};}
    createBufferSource(){return {...node(),start(){this.onended?.();}};}
    createOscillator(){const n={...node(),frequency:param(),start(){},stop(){}};oscillators.push(n);return n;}
    resume(){if(this.mode==='immediate'){this.state='running';return Promise.resolve();}if(this.mode==='reject')return Promise.reject(Error('blocked'));return new Promise(resolve=>{this.resolve=()=>{this.state='running';resolve();};});}
  }
  const document = {body:{dataset:{notificationScope:'qa'}},readyState:'loading',visibilityState:'visible',addEventListener:(n,f)=>{listeners[n]=f;},querySelectorAll:s=>s==='[data-alert-sound-preview]'?[button]:s==='[data-alert-audio-status]'?[status]:[]};
  const window = {AudioContext:supported?Audio:undefined,addEventListener:(n,f)=>{listeners[n]=f;},setTimeout(f,ms){const id=++seq;timers.set(id,{at:time+ms,f});return id;},clearTimeout:id=>timers.delete(id)};
  vm.runInNewContext(source,{window,document,Date:{now:()=>time},console,localStorage:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v)}});
  const tick = async ms => {time+=ms; for(const [id,t] of [...timers]) if(t.at<=time){timers.delete(id);t.f();} await flush();};
  return {api:window.CuotaGoNotificationAudio,button,label,status,contexts,oscillators,document,listeners,tick,timers};
}
(async()=>{
  const h=harness();h.api.setPreferences({tone:'crystal',intensity:'strong'});
  check(h.contexts.length===0,'No context before interaction');
  const attempts=Array.from({length:80},()=>h.api.preview());
  check(h.button.disabled,'Lock synchronously before await');
  const outcomes=await Promise.all(attempts);
  check(outcomes.filter(Boolean).length===1,'Only one preview accepted for 80 rapid calls');
  check(h.contexts.length===1,'One AudioContext');check(h.oscillators.length===6,'One double crystal sequence');
  check(h.label.textContent==='Reproduciendo...','Accessible busy label');
  const before=h.oscillators.length;check(h.api.play(),'Real alert remains handled during preview');
  check(h.oscillators.length===before,'No duplicate/interrupted tone');
  await h.tick(900);check(h.button.disabled,'Double tone remains locked longer than 900ms');
  await h.tick(1000);check(!h.button.disabled,'Button recovers after full sound');
  check(h.oscillators.every(n=>n.disconnected),'No connected nodes left');
  check(await h.api.preview(),'Can play again');check(h.contexts.length===1,'Reuses context');
  h.api.setPreferences({volume:20});check(!h.button.disabled,'Changing preferences cancels sound');
  check(h.oscillators.every(n=>n.disconnected),'Preference change cleans nodes');
  await h.api.preview();h.document.visibilityState='hidden';h.listeners.visibilitychange();
  check(!h.button.disabled,'Background cancels busy state');check(h.oscillators.every(n=>n.disconnected),'Background cleans audio');
  h.document.visibilityState='visible';await h.api.preview();h.listeners.pagehide();
  check(!h.button.disabled,'Navigation cancels lock');check(h.oscillators.every(n=>n.disconnected),'Navigation cleans nodes');
  h.api.setPreferences({volume:0});const muted=h.oscillators.length;
  check(await h.api.preview(),'Muted preview completes');check(!h.button.disabled,'Muted state is not stuck');check(h.oscillators.length===muted,'Muted has no oscillators');
  const deferred=harness({resume:'wait'});const old=deferred.api.preview();
  deferred.api.stop();deferred.contexts[0].resolve();check(!await old,'Cancelled pending resume never plays');
  check(deferred.oscillators.length===0,'No delayed ghost tone');check(await deferred.api.preview(),'Recovers after cancelled resume');
  deferred.api.stop();
  const blocked=harness({resume:'wait'});const waiting=blocked.api.preview();await blocked.tick(2600);
  check(!await waiting,'Hung resume times out');check(!blocked.button.disabled,'Timeout releases button');
  blocked.contexts[0].mode='immediate';check(await blocked.api.preview(),'Retry after timeout works');blocked.api.stop();
  const rejected=harness({resume:'reject'});check(!await rejected.api.preview(),'Rejected autoplay handled');check(!rejected.button.disabled,'Rejected playback unlocks UI');
  const unsupported=harness({supported:false});check(!await unsupported.api.preview(),'Unsupported audio reported');check(unsupported.button.disabled,'Unsupported preview stays disabled');
  console.log(`PASS: ${checks} UI80 audio stress assertions`);
})().catch(e=>{console.error(e);process.exitCode=1;});
