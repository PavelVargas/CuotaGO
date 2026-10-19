/* node tests/test_notification_audio_v79.cjs -- isolated Web Audio contract */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../cuotago/static/js/notification-audio.js'), 'utf8');
function harness({saved=null, blocked=false, supported=true, user='17'}={}) {
  const key = `cuotago-alert-audio-v1:${user}`;
  const store = new Map(saved===null ? [] : [[key,saved]]);
  const oscillators=[]; const gains=[]; const contexts=[];
  const listeners={};
  const param=()=>({value:0,setValueAtTime(v){this.value=v;},linearRampToValueAtTime(v){this.peak=v;},exponentialRampToValueAtTime(){}});
  const node=()=>({connect(){},disconnect(){this.disconnected=true;}});
  class Audio {
    constructor(){this.state='suspended';this.currentTime=0;this.sampleRate=44100;this.destination=node();contexts.push(this);}
    createGain(){const n={...node(),gain:param()};gains.push(n);return n;}
    createDynamicsCompressor(){return {...node(),threshold:param(),knee:param(),ratio:param(),attack:param(),release:param()};}
    createBufferSource(){return {...node(),start(){this.onended?.();}};}
    createBuffer(){return {};}
    createOscillator(){const n={...node(),frequency:param(),start(t){this.started=t;},stop(t){this.stopped=t;}};oscillators.push(n);return n;}
    async resume(){this.state='running';}
  }
  const document={body:{dataset:{notificationScope:user}},readyState:'loading',visibilityState:'visible',querySelectorAll:()=>[],addEventListener:(name,fn)=>{listeners[name]=fn;}};
  const window={setTimeout,clearTimeout,AudioContext:supported ? Audio : undefined,addEventListener:(name,fn)=>{listeners[name]=fn;}};
  const localStorage={getItem(k){if(blocked)throw Error('blocked');return store.get(k)||null;},setItem(k,v){if(blocked)throw Error('blocked');store.set(k,v);}};
  vm.runInNewContext(source,{window,document,localStorage,Date,console});
  return {api:window.CuotaGoNotificationAudio,oscillators,gains,contexts,document,listeners,store,key};
}
(async()=>{
  let count=0;
  const check=(condition)=>{assert.ok(condition);count++;};
  const h=harness();
  check(h.contexts.length===0); // No autoplay or context construction on page load.
  check(h.api.getPreferences().volume===75);
  check(h.api.play()===false);
  check(await h.api.unlock());
  check(h.contexts.length===1);
  for(const tone of ['classic','crystal','soft','pulse']) {
    h.api.setPreferences({tone,volume:100,intensity:'normal'});
    const before=h.oscillators.length;
    check(h.api.play({preview:true}));
    check(h.oscillators.length-before===(tone==='soft'?2:3));
    check(h.oscillators.slice(before).every(n=>Number.isFinite(n.frequency.value)&&n.frequency.value>0));
  }
  h.api.setPreferences({tone:'classic',intensity:'strong'});
  const before=h.oscillators.length;
  check(h.api.play({preview:true}));check(h.oscillators.length-before===6);
  check(h.gains[0].gain.value===1);
  check(h.oscillators.slice(before).every(n=>n.stopped>n.started));
  h.api.setPreferences({volume:0});const muted=h.oscillators.length;
  check(h.api.play({preview:true}));check(h.oscillators.length===muted);
  h.api.setPreferences({volume:200,tone:'__proto__',intensity:'bad'});
  check(h.api.getPreferences().volume===100);check(h.api.getPreferences().tone==='classic');check(h.api.getPreferences().intensity==='normal');
  h.api.setPreferences({volume:-20});check(h.api.getPreferences().volume===0);
  h.api.setPreferences({volume:37});check(h.api.getPreferences().volume===37);
  check(JSON.parse(h.store.get(h.key)).volume===37);
  const reload=harness({saved:h.store.get(h.key)});check(reload.api.getPreferences().volume===37);
  const corrupt=harness({saved:'{bad json'});check(corrupt.api.getPreferences().volume===75);
  const invalid=harness({saved:'{"volume":null,"tone":"constructor","intensity":[] }'});check(invalid.api.getPreferences().volume===75);check(invalid.api.getPreferences().tone==='classic');
  const noStorage=harness({blocked:true});noStorage.api.setPreferences({volume:90,tone:'pulse'});check(noStorage.api.getPreferences().volume===90);
  const silent=harness({supported:false});check(!silent.api.supported());check(!await silent.api.unlock());check(!silent.api.play());
  h.document.visibilityState='hidden';check(h.api.play());check(h.oscillators.length===muted);
  h.document.visibilityState='visible';h.contexts[0].state='suspended';check(!h.api.play());check(await h.api.unlock());
  h.api.play();const rate=h.oscillators.length;check(h.api.play());check(h.oscillators.length===rate);
  check(harness({user:'18'}).api.getPreferences().volume===75);
  h.listeners.pagehide();check(h.oscillators.every(n=>n.disconnected));
  console.log(`PASS: ${count} notification-audio assertions`);
})().catch(e=>{console.error(e);process.exitCode=1;});
