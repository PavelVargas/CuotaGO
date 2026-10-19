/* Local, user-scoped notification sound preferences. No audio downloads, push
   permissions, server writes, system-volume overrides or third-party requests. */
(() => {
  'use strict';
  const DEFAULTS = Object.freeze({ tone: 'classic', volume: 75, intensity: 'normal' });
  const TONES = Object.freeze({
    classic: { notes: [659.25, 783.99, 987.77], step: .15, duration: .14, type: 'sine' },
    crystal: { notes: [1046.5, 1318.51, 1567.98], step: .18, duration: .26, type: 'sine' },
    soft: { notes: [440, 554.37], step: .24, duration: .30, type: 'sine' },
    pulse: { notes: [740, 740, 880], step: .19, duration: .16, type: 'triangle' },
  });
  const LEVELS = Object.freeze({ soft: .5, normal: .8, strong: 1.0 });
  const userScope = document.body?.dataset.notificationScope || 'device';
  const STORAGE_KEY = `cuotago-alert-audio-v1:${userScope}`;
  let context = null;
  let master = null;
  let compressor = null;
  let unlocked = false;
  let resumePromise = null;
  let preference = null;
  let lastAlertAt = -Infinity;
  const playing = new Set();

  const own = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);
  const normalize = (input) => {
    const data = input && typeof input === 'object' && !Array.isArray(input) ? input : {};
    const volume = typeof data.volume === 'number' || typeof data.volume === 'string' && data.volume.trim() !== ''
      ? Number(data.volume) : NaN;
    return {
      tone: own(TONES, data.tone) ? data.tone : DEFAULTS.tone,
      volume: Number.isFinite(volume) ? Math.min(100, Math.max(0, Math.round(volume))) : DEFAULTS.volume,
      intensity: own(LEVELS, data.intensity) ? data.intensity : DEFAULTS.intensity,
    };
  };
  const read = () => {
    try { return normalize(JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')); }
    catch (_) { return { ...DEFAULTS }; }
  };
  preference = read();
  const supported = () => Boolean(window.AudioContext || window.webkitAudioContext);
  const getContext = () => {
    if (context && context.state !== 'closed') return context;
    if (!supported()) return null;
    try {
      const Audio = window.AudioContext || window.webkitAudioContext;
      context = new Audio();
      unlocked = false;
      master = context.createGain();
      compressor = context.createDynamicsCompressor();
      compressor.threshold.value = -6;
      compressor.knee.value = 8;
      compressor.ratio.value = 8;
      compressor.attack.value = .003;
      compressor.release.value = .12;
      master.connect(compressor);
      compressor.connect(context.destination);
      return context;
    } catch (_) { context = null; return null; }
  };
  const unlock = async () => {
    const ctx = getContext();
    if (!ctx) return false;
    if (ctx.state === 'running' && unlocked) return true;
    if (resumePromise) return resumePromise;
    resumePromise = (async () => {
      try {
        // Called directly from a click/key gesture. iOS can also use an
        // 'interrupted' state after a phone call or a background transition.
        if (ctx.state !== 'running') await ctx.resume();
        if (ctx.state !== 'running') return false;
        if (!unlocked) {
          const source = ctx.createBufferSource();
          source.buffer = ctx.createBuffer(1, 1, ctx.sampleRate);
          source.connect(ctx.destination);
          source.onended = () => source.disconnect();
          source.start();
        }
        unlocked = true;
        return true;
      } catch (_) { return false; }
    })();
    try { return await resumePromise; } finally { resumePromise = null; }
  };
  const stop = () => {
    for (const item of playing) {
      try { item.oscillator.stop(); } catch (_) {}
      try { item.oscillator.disconnect(); item.gain.disconnect(); } catch (_) {}
    }
    playing.clear();
  };
  const play = ({ preview = false } = {}) => {
    // Muting is successful and must not queue a tone for the next gesture.
    if (preference.volume === 0) { stop(); return true; }
    const ctx = context;
    if (!ctx || ctx.state !== 'running' || !unlocked) return false;
    if (!preview && document.visibilityState === 'hidden') return true;
    const nowMs = Date.now();
    if (!preview && nowMs - lastAlertAt < 900) return true;
    stop();
    try {
      const tone = TONES[preference.tone];
      const repeats = preference.intensity === 'strong' ? 2 : 1;
      const start = ctx.currentTime + .012;
      const sequence = (tone.notes.length - 1) * tone.step + tone.duration + .22;
      // No gain above unity; two layers are bounded below full scale, and the
      // compressor prevents sharp peaks when the Crystal notes overlap.
      master.gain.setValueAtTime((preference.volume / 100) ** 1.4 * LEVELS[preference.intensity], ctx.currentTime);
      for (let repeat = 0; repeat < repeats; repeat += 1) {
        tone.notes.forEach((frequency, index) => {
          const at = start + repeat * sequence + index * tone.step;
          const oscillator = ctx.createOscillator();
          const gain = ctx.createGain();
          oscillator.type = tone.type;
          oscillator.frequency.setValueAtTime(frequency, at);
          gain.gain.setValueAtTime(0, at);
          gain.gain.linearRampToValueAtTime(.48, at + .014);
          gain.gain.exponentialRampToValueAtTime(.0001, at + tone.duration);
          oscillator.connect(gain);
          gain.connect(master);
          const item = { oscillator, gain };
          playing.add(item);
          oscillator.onended = () => {
            playing.delete(item);
            oscillator.disconnect();
            gain.disconnect();
          };
          oscillator.start(at);
          oscillator.stop(at + tone.duration + .015);
        });
      }
      if (!preview) lastAlertAt = nowMs;
      return true;
    } catch (_) { stop(); return false; }
  };

  const status = (message) => {
    document.querySelectorAll('[data-alert-audio-status]').forEach((node) => { node.textContent = message; });
  };
  const sync = () => {
    document.querySelectorAll('[data-alert-tone]').forEach((node) => { node.value = preference.tone; });
    document.querySelectorAll('[data-alert-intensity]').forEach((node) => { node.value = preference.intensity; });
    document.querySelectorAll('[data-alert-volume]').forEach((node) => {
      node.value = String(preference.volume);
      node.setAttribute('aria-valuetext', preference.volume ? `${preference.volume}%` : 'Silenciado');
    });
    document.querySelectorAll('[data-alert-volume-output]').forEach((node) => {
      node.textContent = preference.volume ? `${preference.volume}%` : '0% \u00b7 silenciado';
    });
  };
  const save = (patch) => {
    stop();
    preference = normalize({ ...preference, ...patch });
    let persisted = false;
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(preference)); persisted = true; } catch (_) {}
    sync();
    status(persisted ? 'Preferencias guardadas en este dispositivo.' : 'Aplicado por ahora. El navegador no permite guardar preferencias.');
    return { ...preference };
  };
  const setup = () => {
    sync();
    if (!supported()) {
      document.querySelectorAll('[data-alert-sound-preview]').forEach((button) => { button.disabled = true; });
      status('Este navegador no permite reproducir estos tonos. Los avisos visuales siguen disponibles.');
    }
    document.querySelectorAll('[data-alert-tone]').forEach((node) => node.addEventListener('change', () => save({ tone: node.value })));
    document.querySelectorAll('[data-alert-intensity]').forEach((node) => node.addEventListener('change', () => save({ intensity: node.value })));
    document.querySelectorAll('[data-alert-volume]').forEach((node) => {
      node.addEventListener('input', () => save({ volume: node.value }));
    });
    document.querySelectorAll('[data-alert-sound-preview]').forEach((button) => button.addEventListener('click', async () => {
      if (preference.volume === 0) { stop(); status('Volumen en 0%: el sonido est\u00e1 silenciado.'); return; }
      button.disabled = true;
      try {
        const ready = await unlock();
        const played = ready && play({ preview: true });
        status(played ? 'Prueba enviada al audio. Revisa tambi\u00e9n el volumen de tu dispositivo.' : 'No se pudo activar el audio. Revisa los permisos de reproducci\u00f3n del navegador.');
      } catch (_) { status('No se pudo reproducir el sonido. Vuelve a tocar Probar sonido.'); }
      finally { button.disabled = false; }
    }));
  };
  window.addEventListener('storage', (event) => {
    if (event.key === STORAGE_KEY || event.key === null) { stop(); preference = read(); sync(); }
  });
  window.addEventListener('pagehide', stop);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') stop(); });
  // Shared by the existing notification callbacks and by the Settings preview.
  window.CuotaGoNotificationAudio = Object.freeze({
    unlock, play, stop, supported, getPreferences: () => ({ ...preference }), setPreferences: save,
  });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', setup, { once: true });
  else setup();
})();
