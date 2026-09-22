(() => {
  const THEME_KEY = 'cuotago-theme';
  const root = document.documentElement;
  const systemTheme = window.matchMedia('(prefers-color-scheme: dark)');
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';

  /* Native-feeling PWA: explicitly disable pinch, gesture and double-tap zoom.
     Inputs are also 16px+ in CSS so iOS never zooms on focus. */
  const stopGesture = (event) => event.preventDefault();
  document.addEventListener('gesturestart', stopGesture, { passive: false });
  document.addEventListener('gesturechange', stopGesture, { passive: false });
  document.addEventListener('gestureend', stopGesture, { passive: false });
  document.addEventListener('touchmove', (event) => {
    if (event.touches && event.touches.length > 1) event.preventDefault();
  }, { passive: false });
  let lastTouchEnd = 0;
  let lastTouchTarget = null;
  document.addEventListener('touchend', (event) => {
    const now = Date.now();
    if (now - lastTouchEnd <= 320 && event.target === lastTouchTarget) event.preventDefault();
    lastTouchEnd = now;
    lastTouchTarget = event.target;
  }, { passive: false });

  const readTheme = () => {
    try {
      const saved = localStorage.getItem(THEME_KEY);
      return ['light', 'dark', 'system'].includes(saved) ? saved : 'system';
    } catch (_) {
      return 'system';
    }
  };

  const resolvedTheme = (choice) => (
    choice === 'dark' || (choice === 'system' && systemTheme.matches) ? 'dark' : 'light'
  );

  const syncThemeControls = (choice) => {
    document.querySelectorAll('[data-theme-choice]').forEach((button) => {
      const active = button.dataset.themeChoice === choice;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    const isDark = resolvedTheme(choice) === 'dark';
    document.querySelectorAll('[data-theme-toggle-switch]').forEach((control) => {
      if ('checked' in control) control.checked = isDark;
      control.setAttribute('aria-checked', isDark ? 'true' : 'false');
      control.classList.toggle('is-checked', isDark);
    });
  };

  const applyTheme = (choice, persist = true) => {
    const safeChoice = ['light', 'dark', 'system'].includes(choice) ? choice : 'system';
    const resolved = resolvedTheme(safeChoice);
    root.dataset.themeChoice = safeChoice;
    root.dataset.theme = resolved;
    const booting = root.classList.contains('show-boot');
    document.getElementById('themeColorMeta')?.setAttribute('content', booting ? '#fffaf6' : (resolved === 'dark' ? '#101216' : '#f4f7fb'));
    document.getElementById('appleStatusMeta')?.setAttribute('content', booting ? 'default' : (resolved === 'dark' ? 'black-translucent' : 'default'));
    syncThemeControls(safeChoice);
    if (persist) {
      try { localStorage.setItem(THEME_KEY, safeChoice); } catch (_) {}
    }
  };

  systemTheme.addEventListener?.('change', () => {
    if (readTheme() === 'system') applyTheme('system', false);
  });

  /* Splash HTML only once per installed-PWA session. Internal navigation never replays it. */
  const splash = document.getElementById('bootSplash');
  if (!root.classList.contains('show-boot')) {
    splash?.remove();
  } else {
    const splashStartedAt = performance.now();
    let splashFinished = false;
    const hideSplash = () => {
      if (splashFinished || !splash) return;
      splashFinished = true;
      const remaining = Math.max(0, 460 - (performance.now() - splashStartedAt));
      window.setTimeout(() => {
        splash.classList.add('is-hidden');
        window.setTimeout(() => {
          splash.remove();
          root.classList.remove('show-boot');
          applyTheme(document.body?.classList.contains('auth-shell') ? 'light' : readTheme(), false);
        }, 210);
      }, remaining);
    };
    document.addEventListener('DOMContentLoaded', hideSplash, { once: true });
    window.setTimeout(hideSplash, 1400);
  }

  const networkBanner = document.getElementById('networkBanner');
  const syncNetworkState = () => {
    if (!networkBanner) return;
    const offline = !navigator.onLine;
    networkBanner.hidden = !offline;
    document.body.classList.toggle('is-offline', offline);
  };
  window.addEventListener('online', syncNetworkState);
  window.addEventListener('offline', syncNetworkState);
  syncNetworkState();

  let installPrompt = null;
  const installBtn = document.getElementById('installAppBtn');
  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    installPrompt = event;
    if (installBtn) installBtn.hidden = false;
  });
  installBtn?.addEventListener('click', async () => {
    if (!installPrompt) return;
    await installPrompt.prompt();
    installPrompt = null;
    installBtn.hidden = true;
  });
  window.addEventListener('appinstalled', () => {
    installPrompt = null;
    if (installBtn) installBtn.hidden = true;
  });

  const APP_VERSION = '1.17.1-ui-v38';
  const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));

  const registerServiceWorker = async ({ forceFresh = false } = {}) => {
    if (!window.isSecureContext) {
      throw new Error('Las notificaciones necesitan HTTPS. En local usa http://localhost o http://127.0.0.1.');
    }
    if (!('serviceWorker' in navigator)) throw new Error('Service Worker no disponible');

    if (forceFresh) {
      const current = await navigator.serviceWorker.getRegistration('/');
      if (current) {
        try {
          const oldSubscription = await current.pushManager?.getSubscription();
          if (oldSubscription) await oldSubscription.unsubscribe();
        } catch (_) {}
        try { await current.unregister(); } catch (_) {}
      }
      try {
        const keys = await caches.keys();
        await Promise.all(keys.filter((key) => key.startsWith('cuotago-')).map((key) => caches.delete(key)));
      } catch (_) {}
      await sleep(250);
    }

    let registration = await navigator.serviceWorker.getRegistration('/');
    const expectedScript = `/service-worker.js?v=${APP_VERSION}`;
    const currentScript = registration?.active?.scriptURL || registration?.waiting?.scriptURL || registration?.installing?.scriptURL || '';
    if (!registration || forceFresh || !currentScript.includes(`v=${APP_VERSION}`)) {
      registration = await navigator.serviceWorker.register(expectedScript, {
        scope: '/',
        updateViaCache: 'none',
      });
    }

    try { await registration.update(); } catch (_) {}

    if (!registration.active) {
      const worker = registration.installing || registration.waiting;
      if (worker) {
        await Promise.race([
          new Promise((resolve) => {
            const done = () => {
              if (worker.state === 'activated' || worker.state === 'redundant') {
                worker.removeEventListener('statechange', done);
                resolve();
              }
            };
            worker.addEventListener('statechange', done);
            done();
          }),
          sleep(6000),
        ]);
      }
    }
    return registration;
  };

  const urlBase64ToUint8Array = (base64String) => {
    const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const rawData = window.atob(base64);
    return Uint8Array.from([...rawData].map((char) => char.charCodeAt(0)));
  };

  const apiJson = async (url, options = {}) => {
    const headers = { Accept: 'application/json', ...(options.headers || {}) };
    if ((options.method || 'GET').toUpperCase() !== 'GET') {
      headers['Content-Type'] = 'application/json';
      headers['X-CSRFToken'] = csrfToken;
    }
    const response = await fetch(url, { credentials: 'same-origin', ...options, headers });
    let data = {};
    try { data = await response.json(); } catch (_) {}
    if (!response.ok) throw new Error(data.message || `Error ${response.status}`);
    return data;
  };

  const LOCAL_ALERT_SOUND_KEY = 'cuotago-local-alert-sound-v2';
  const LOCAL_ALERTS_ENABLED_KEY = 'cuotago-local-alerts-enabled-v1';
  let alertAudioContext = null;
  let alertAudioUnlocked = false;
  let pendingAlertSound = false;

  const getAlertAudioContext = () => {
    if (alertAudioContext) return alertAudioContext;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return null;
    try {
      alertAudioContext = new AudioContextClass();
      return alertAudioContext;
    } catch (_) {
      return null;
    }
  };

  const localAlertsEnabled = () => {
    try { return localStorage.getItem(LOCAL_ALERTS_ENABLED_KEY) !== '0'; } catch (_) { return true; }
  };

  const setLocalAlertsEnabled = (enabled) => {
    try { localStorage.setItem(LOCAL_ALERTS_ENABLED_KEY, enabled ? '1' : '0'); } catch (_) {}
  };

  const updateLocalAlertStatus = () => {
    const enabled = localAlertsEnabled();
    const supported = Boolean(window.AudioContext || window.webkitAudioContext);
    document.querySelectorAll('[data-local-alert-switch]').forEach((input) => { input.checked = enabled; });
    document.querySelectorAll('[data-local-alert-status]').forEach((el) => {
      if (!enabled) {
        el.textContent = 'Desactivadas';
        el.dataset.active = '0';
        return;
      }
      if (!supported) {
        el.textContent = 'Activadas · sin sonido';
        el.dataset.active = '1';
        return;
      }
      el.textContent = alertAudioUnlocked ? 'Activadas · sonido listo' : 'Activadas';
      el.dataset.active = '1';
    });
  };

  const unlockAlertAudio = async () => {
    const ctx = getAlertAudioContext();
    if (!ctx) {
      updateLocalAlertStatus();
      return false;
    }
    try {
      if (ctx.state === 'suspended') await ctx.resume();
      if (ctx.state === 'running') {
        // Prime the context silently from a real user gesture. This is much
        // more reliable on iPhone than repeatedly calling HTMLAudio.play().
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        gain.gain.setValueAtTime(0.00001, ctx.currentTime);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(ctx.currentTime);
        osc.stop(ctx.currentTime + 0.025);
        alertAudioUnlocked = true;
        try { localStorage.setItem(LOCAL_ALERT_SOUND_KEY, '1'); } catch (_) {}
        updateLocalAlertStatus();
        if (pendingAlertSound) {
          pendingAlertSound = false;
          window.setTimeout(() => playAlertSound(), 60);
        }
        return true;
      }
    } catch (_) {}
    updateLocalAlertStatus();
    return false;
  };

  const playSynthAlert = () => {
    const ctx = getAlertAudioContext();
    if (!ctx || ctx.state !== 'running' || !alertAudioUnlocked) {
      pendingAlertSound = true;
      return false;
    }
    try {
      const now = ctx.currentTime + 0.015;
      const tones = [659.25, 783.99, 987.77];
      tones.forEach((frequency, index) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.setValueAtTime(frequency, now + index * 0.14);
        gain.gain.setValueAtTime(0.0001, now + index * 0.14);
        gain.gain.exponentialRampToValueAtTime(0.19, now + index * 0.14 + 0.015);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + index * 0.14 + 0.12);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(now + index * 0.14);
        osc.stop(now + index * 0.14 + 0.13);
      });
      return true;
    } catch (_) {
      pendingAlertSound = true;
      return false;
    }
  };

  const playAlertSound = () => {
    if (!localAlertsEnabled()) return false;
    const played = playSynthAlert();
    try { navigator.vibrate?.([180, 90, 180, 90, 320]); } catch (_) {}
    return played;
  };

  const primeAlertAudioFromGesture = () => { unlockAlertAudio(); };
  document.addEventListener('pointerdown', primeAlertAudioFromGesture, { once: true, capture: true });
  document.addEventListener('touchstart', primeAlertAudioFromGesture, { once: true, capture: true, passive: true });
  const isStandalone = () => window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const pushSupported = () => window.isSecureContext && 'Notification' in window && 'PushManager' in window && 'serviceWorker' in navigator;
  const isPushServiceError = (error) => {
    const message = String(error?.message || error || '').toLowerCase();
    return error?.name === 'AbortError' || message.includes('push service error') || message.includes('push server');
  };

  const browserInfo = async () => {
    const ua = navigator.userAgent || '';
    let brave = false;
    try { brave = Boolean(await navigator.brave?.isBrave?.()); } catch (_) {}
    return {
      brave,
      opera: /OPR\//i.test(ua) || /Opera/i.test(ua),
      edge: /Edg\//i.test(ua),
      chrome: /Chrome\//i.test(ua) && !/Edg\//i.test(ua) && !/OPR\//i.test(ua),
      safari: /Safari\//i.test(ua) && !/Chrome\//i.test(ua) && !/Chromium/i.test(ua),
      firefox: /Firefox\//i.test(ua),
    };
  };

  const friendlyPushError = async (error) => {
    const raw = String(error?.message || error || 'No se pudieron activar las notificaciones.');
    if (!window.isSecureContext) return 'Modo demostración local: CuotaGo funciona normal. Las alertas con la app cerrada estarán disponibles cuando publiques la app con HTTPS.';
    if (isIOS() && !isStandalone()) return 'En iPhone o iPad, instala CuotaGo en la pantalla de inicio y ábrela desde su icono antes de activar las alertas.';
    if ('Notification' in window && Notification.permission === 'denied') return 'Las notificaciones están bloqueadas. Actívalas para CuotaGo desde los ajustes de notificaciones del teléfono o navegador.';
    if (!isPushServiceError(error)) return raw;

    const browser = await browserInfo();
    if (browser.brave) return 'Brave bloqueó su servicio Push. Activa “Usar servicios de Google para mensajería push” en la privacidad de Brave, reinicia el navegador y toca Reintentar.';
    if (browser.opera) return 'Opera no pudo registrarse con su servicio Push. CuotaGo ya reparó el Service Worker y reintentó; si sigue igual, usa Chrome, Edge o Safari para activar las alertas.';
    if (browser.safari) return isIOS()
      ? 'Safari/iOS no pudo conectar con Apple Push. Abre la PWA desde su icono, confirma que CuotaGo tenga notificaciones permitidas en Ajustes y toca Reintentar.'
      : 'Safari no pudo conectar con Apple Push. Revisa que Safari tenga notificaciones permitidas en macOS y toca Reintentar.';
    if (browser.chrome || browser.edge) return 'El navegador no pudo conectar con su servicio Push. CuotaGo reparó el Service Worker y reintentó. Cierra modo incógnito, desactiva VPN/bloqueadores que filtren servicios de Google y toca Reintentar.';
    return 'El servicio Push del navegador no respondió. CuotaGo reparó el Service Worker y reintentó. Revisa la conexión y los permisos de notificaciones y vuelve a intentarlo.';
  };

  const setPushMessage = (message, tone = '') => {
    document.querySelectorAll('[data-push-message]').forEach((el) => {
      el.textContent = message;
      el.dataset.tone = tone;
    });
  };

  const setEnableButtonLabel = (label) => {
    document.querySelectorAll('[data-push-enable]').forEach((el) => {
      el.textContent = label;
    });
  };

  const syncPushSwitch = ({ checked = false, disabled = false } = {}) => {
    document.querySelectorAll('[data-push-switch]').forEach((input) => {
      input.checked = checked;
      input.disabled = disabled;
    });
  };

  const ALERT_MEMORY_KEY = 'cuotago-inapp-alert-memory-v1';
  const ALERT_REPEAT_MS = 30 * 60 * 1000;

  const updateNotificationBadge = (count = 0) => {
    const safeCount = Math.max(0, Number(count) || 0);
    document.querySelectorAll('[data-notification-badge]').forEach((badge) => {
      badge.hidden = safeCount === 0;
      badge.textContent = safeCount > 99 ? '99+' : String(safeCount);
    });
    try {
      if ('setAppBadge' in navigator) {
        if (safeCount) navigator.setAppBadge(safeCount).catch?.(() => {});
        else navigator.clearAppBadge?.().catch?.(() => {});
      }
    } catch (_) {}
  };

  const readAlertMemory = () => {
    try {
      const parsed = JSON.parse(localStorage.getItem(ALERT_MEMORY_KEY) || '{}');
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch (_) {
      return {};
    }
  };

  const rememberAlert = (id) => {
    if (!id) return;
    const now = Date.now();
    const memory = readAlertMemory();
    memory[id] = now;
    Object.keys(memory).forEach((key) => {
      if (!Number(memory[key]) || now - Number(memory[key]) > 7 * 24 * 60 * 60 * 1000) delete memory[key];
    });
    try { localStorage.setItem(ALERT_MEMORY_KEY, JSON.stringify(memory)); } catch (_) {}
  };

  const canRepeatAlert = (id) => {
    if (!id) return true;
    const last = Number(readAlertMemory()[id] || 0);
    return !last || Date.now() - last >= ALERT_REPEAT_MS;
  };

  let inAppAlertTimer = null;
  const showInAppPaymentAlert = (item = {}, { forceSound = true, ignorePreference = false } = {}) => {
    if (!ignorePreference && !localAlertsEnabled()) return;
    let host = document.querySelector('.inapp-alert-host');
    if (!host) {
      host = document.createElement('div');
      host.className = 'inapp-alert-host';
      host.setAttribute('aria-live', 'assertive');
      document.body.appendChild(host);
    }
    host.textContent = '';

    const card = document.createElement('div');
    card.className = `inapp-payment-alert is-${item.type || 'overdue'}`;

    const icon = document.createElement('span');
    icon.className = 'inapp-alert-icon';
    icon.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M6 17h12l-1.5-2.5V10a4.5 4.5 0 1 0-9 0v4.5z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M10 19a2 2 0 0 0 4 0" stroke="currentColor" stroke-width="1.8"/></svg>';

    const link = document.createElement('a');
    link.className = 'inapp-alert-link';
    link.href = item.url || '/notifications';
    const title = document.createElement('strong');
    title.textContent = item.title || 'Alerta de cobro';
    const body = document.createElement('span');
    const pieces = [item.client, item.amount, item.detail].filter(Boolean);
    if (item.body && !item.client && !item.amount) {
      body.textContent = item.detail ? `${item.body} · ${item.detail}` : item.body;
    } else {
      body.textContent = pieces.join(' · ') || item.body || 'Tienes un pago que necesita atención.';
    }
    link.append(title, body);

    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'inapp-alert-close';
    close.setAttribute('aria-label', 'Cerrar alerta');
    close.textContent = '×';
    close.addEventListener('click', () => {
      window.clearTimeout(inAppAlertTimer);
      host.remove();
    });

    card.append(icon, link, close);
    host.appendChild(card);

    if (forceSound) {
      playAlertSound();
      try { navigator.vibrate?.([180, 80, 180]); } catch (_) {}
    }

    window.clearTimeout(inAppAlertTimer);
    inAppAlertTimer = window.setTimeout(() => host.remove(), 9000);
  };

  const fetchPaymentNotifications = async () => {
    const data = await apiJson('/api/notifications');
    updateNotificationBadge(data.urgentCount || 0);
    return data;
  };

  const pollPaymentAlerts = async ({ showToast = true } = {}) => {
    if (!document.body.classList.contains('app-authenticated')) return;
    try {
      const data = await fetchPaymentNotifications();
      if (!showToast || !localAlertsEnabled()) return;
      const candidate = (data.items || []).find((item) => item.urgent && canRepeatAlert(item.id));
      if (!candidate) return;
      rememberAlert(candidate.id);
      showInAppPaymentAlert(candidate, { forceSound: true });
    } catch (_) {
      // El centro de notificaciones no debe romper la navegación si la red falla.
    }
  };

  let paymentAlertInterval = null;
  const startPaymentAlertWatcher = () => {
    if (!document.body.classList.contains('app-authenticated') || document.body.dataset.canCollect !== '1') return;
    const shouldToast = () => !document.querySelector('[data-notifications-page]');
    pollPaymentAlerts({ showToast: shouldToast() });
    if (paymentAlertInterval) window.clearInterval(paymentAlertInterval);
    paymentAlertInterval = window.setInterval(() => pollPaymentAlerts({ showToast: shouldToast() }), 20000);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') pollPaymentAlerts({ showToast: shouldToast() });
    });
  };

  const buildNotificationOptions = (payload = {}) => ({
    body: payload.body || 'Tienes una alerta de cobro.',
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/favicon-64.png',
    tag: payload.tag || `cuotago-local-${Date.now()}`,
    renotify: true,
    requireInteraction: payload.type === 'overdue',
    silent: false,
    vibrate: [220, 100, 220, 100, 420],
    timestamp: Date.now(),
    data: { url: payload.url || '/collections', type: payload.type || 'general', contractId: payload.contractId || null },
  });

  const saveSubscriptionOnServer = async (subscription) => apiJson('/api/push/subscribe', {
    method: 'POST',
    body: JSON.stringify(subscription.toJSON()),
  });

  const createPushSubscription = async (publicKey, onRepair = () => {}) => {
    let registration = await registerServiceWorker();
    let subscription = await registration.pushManager.getSubscription();
    if (subscription) return subscription;

    const options = {
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicKey),
    };

    try {
      return await registration.pushManager.subscribe(options);
    } catch (firstError) {
      if (!isPushServiceError(firstError)) throw firstError;
      onRepair();
      registration = await registerServiceWorker({ forceFresh: true });
      await sleep(650);
      subscription = await registration.pushManager.getSubscription();
      if (subscription) return subscription;
      try {
        return await registration.pushManager.subscribe(options);
      } catch (secondError) {
        secondError.cuotagoFirstError = firstError;
        throw secondError;
      }
    }
  };

  const showLocalFallbackNotification = async (payload) => {
    if (Notification.permission !== 'granted') return false;
    const registration = await registerServiceWorker();
    await registration.showNotification(payload.title || 'CuotaGo', buildNotificationOptions(payload));
    playAlertSound();
    return true;
  };

  const updatePushUI = async () => {
    const controls = document.querySelectorAll('[data-push-controls]');
    if (!controls.length) return;

    setEnableButtonLabel('Activar notificaciones');

    if (!window.isSecureContext) {
      controls.forEach((el) => el.dataset.state = 'local-demo');
      setPushMessage('Modo demostración local: la app funciona normal. Las alertas con la app cerrada se habilitan cuando publiques CuotaGo con HTTPS.', 'info');
      document.querySelectorAll('[data-push-status]').forEach((el) => {
        el.textContent = 'Pendiente de HTTPS';
        el.dataset.active = '0';
      });
      document.querySelectorAll('[data-push-enable],[data-push-disable],[data-push-test],[data-push-test-background]').forEach((el) => { el.hidden = true; });
      syncPushSwitch({ checked: false, disabled: true });
      document.querySelectorAll('[data-push-footnote]').forEach((el) => {
        el.textContent = 'Puedes enseñar y usar CuotaGo en tu red local sin Push. Cuando tengas un dominio HTTPS, esta misma sección habilitará las alertas remotas.';
      });
      return;
    }

    if (!pushSupported()) {
      controls.forEach((el) => el.dataset.state = 'unsupported');
      setPushMessage('Este navegador no admite Web Push. El resto de CuotaGo funciona normalmente.', 'info');
      document.querySelectorAll('[data-push-status]').forEach((el) => {
        el.textContent = 'No disponible';
        el.dataset.active = '0';
      });
      document.querySelectorAll('[data-push-enable],[data-push-disable],[data-push-test],[data-push-test-background]').forEach((el) => { el.hidden = true; });
      syncPushSwitch({ checked: false, disabled: true });
      return;
    }

    if (isIOS() && !isStandalone()) {
      controls.forEach((el) => el.dataset.state = 'install-first');
      setPushMessage('Para recibir alertas en iPhone, añade CuotaGo a la pantalla de inicio y ábrela desde su icono.', 'info');
      document.querySelectorAll('[data-push-status]').forEach((el) => {
        el.textContent = 'Instala la PWA';
        el.dataset.active = '0';
      });
      syncPushSwitch({ checked: false, disabled: true });
      return;
    }

    try {
      const [config, registration] = await Promise.all([apiJson('/api/push/config'), registerServiceWorker()]);
      const subscription = await registration.pushManager.getSubscription();
      const active = Boolean(subscription && config.enabled && Notification.permission === 'granted');
      if (active && config.subscriptionCount === 0) {
        try { await saveSubscriptionOnServer(subscription); } catch (_) {}
      }
      controls.forEach((el) => el.dataset.state = active ? 'active' : 'inactive');
      syncPushSwitch({ checked: active, disabled: Notification.permission === 'denied' || !config.enabled });
      document.querySelectorAll('[data-push-status]').forEach((el) => {
        el.textContent = active ? 'Activadas' : (Notification.permission === 'denied' ? 'Bloqueadas' : 'Desactivadas');
        el.dataset.active = active ? '1' : '0';
      });
      document.querySelectorAll('[data-push-enable]').forEach((el) => { el.hidden = active; });
      document.querySelectorAll('[data-push-disable],[data-push-test],[data-push-test-background]').forEach((el) => { el.hidden = !active; });
      if (active) {
        setPushMessage('Alertas listas. CuotaGo podrá avisarte aunque la PWA esté cerrada.', 'success');
      } else {
        setPushMessage(Notification.permission === 'denied'
          ? 'Las notificaciones están bloqueadas en este dispositivo.'
          : 'Actívalas una vez para recibir alertas de pagos atrasados.', Notification.permission === 'denied' ? 'error' : 'info');
      }
    } catch (error) {
      setPushMessage(await friendlyPushError(error), 'error');
      setEnableButtonLabel('Reintentar');
      syncPushSwitch({ checked: false, disabled: false });
    }
  };

  const subscribePushFromUserGesture = async () => {
    if (!window.isSecureContext) throw new Error('Las alertas con la app cerrada necesitan HTTPS.');
    if (isIOS() && !isStandalone()) throw new Error('En iPhone/iPad, instala CuotaGo en la pantalla de inicio y ábrela desde su icono para recibir alertas con la app cerrada.');
    if (!pushSupported()) throw new Error('Este navegador no admite Web Push.');

    const publicKey = document.querySelector('meta[name="cuotago-vapid-key"]')?.content || '';
    const pushEnabled = document.querySelector('meta[name="cuotago-push-enabled"]')?.content === '1';
    if (!pushEnabled || !publicKey) throw new Error('El servidor todavía no tiene Web Push habilitado.');

    // iOS/Safari exige solicitar permiso directamente desde el toque del usuario.
    // Esta llamada sucede antes de cualquier espera de red.
    const permission = Notification.permission === 'granted'
      ? 'granted'
      : await Notification.requestPermission();
    if (permission !== 'granted') throw new Error('No se concedió permiso para notificaciones.');

    const registration = await registerServiceWorker();
    const subscription = await createPushSubscription(publicKey, () => {
      setPushMessage('Reparando la conexión Push y reintentando...', 'info');
    });
    await saveSubscriptionOnServer(subscription);
    return subscription;
  };

  const enablePush = async (button) => {
    if (button) button.disabled = true;
    try {
      setPushMessage('Conectando este dispositivo...', 'info');
      const subscription = await subscribePushFromUserGesture();

      playAlertSound();
      setPushMessage('Alertas activadas. Enviando una prueba...', 'success');
      const test = await apiJson('/api/push/test', { method: 'POST', body: JSON.stringify({ endpoint: subscription.endpoint }) });
      setPushMessage(test.message || 'Notificación de prueba enviada.', 'success');
      await unlockAlertAudio();
      showInAppPaymentAlert({
        type: 'today',
        title: 'Alertas activadas',
        body: 'CuotaGo ya puede avisarte. Esta alerta confirma el sonido mientras la app está abierta.',
        detail: 'Configuración lista',
        url: '/notifications',
      }, { forceSound: true });
      await updatePushUI();
    } catch (error) {
      const message = await friendlyPushError(error);
      setPushMessage(message, 'error');
      setEnableButtonLabel('Reintentar');
      syncPushSwitch({ checked: false, disabled: false });
    } finally {
      if (button) button.disabled = false;
    }
  };

  const disablePush = async (button) => {
    if (button) button.disabled = true;
    try {
      const registration = await registerServiceWorker();
      const subscription = await registration.pushManager.getSubscription();
      if (subscription) {
        await apiJson('/api/push/unsubscribe', {
          method: 'POST',
          body: JSON.stringify({ endpoint: subscription.endpoint }),
        });
        await subscription.unsubscribe();
      }
      await updatePushUI();
      setPushMessage('Alertas desactivadas en este teléfono.', 'info');
    } catch (error) {
      setPushMessage(await friendlyPushError(error), 'error');
    } finally {
      if (button) button.disabled = false;
    }
  };

  const testPush = async (button) => {
    if (button) button.disabled = true;
    try {
      const registration = await registerServiceWorker();
      const subscription = await registration.pushManager.getSubscription();
      if (!subscription) throw new Error('Este teléfono no tiene una suscripción Push activa. Activa las notificaciones primero.');
      const data = await apiJson('/api/push/test', {
        method: 'POST',
        body: JSON.stringify({ endpoint: subscription.endpoint }),
      });
      setPushMessage(data.message || 'Notificación enviada.', 'success');
      await unlockAlertAudio();
      showInAppPaymentAlert({
        type: 'today',
        title: 'Prueba de notificación',
        body: 'El servidor envió la prueba Push. Esta alerta confirma el aviso dentro de CuotaGo.',
        detail: 'Prueba completada',
        url: '/notifications',
      }, { forceSound: true });
    } catch (error) {
      if (Notification.permission === 'granted') {
        try {
          await showLocalFallbackNotification({
            type: 'test-local',
            title: 'Prueba local de CuotaGo',
            body: 'El teléfono puede mostrar notificaciones. La conexión Push remota necesita ser reparada.',
            url: '/settings',
            tag: `cuotago-local-test-${Date.now()}`,
          });
          setPushMessage(`${await friendlyPushError(error)} Se mostró una prueba local.`, 'error');
          return;
        } catch (_) {}
      }
      setPushMessage(await friendlyPushError(error), 'error');
    } finally {
      if (button) button.disabled = false;
    }
  };

  const testPushOutside = async (button) => {
    if (button) button.disabled = true;
    const originalLabel = button?.textContent || 'Probar notificación';
    try {
      if (!window.isSecureContext) throw new Error('Esta prueba necesita HTTPS.');
      if (isIOS() && !isStandalone()) throw new Error('En iPhone, instala CuotaGo en la pantalla de inicio y abre la PWA desde su icono.');
      const registration = await registerServiceWorker();
      const subscription = await registration.pushManager.getSubscription();
      if (!subscription || Notification.permission !== 'granted') {
        throw new Error('Primero activa las notificaciones en este teléfono.');
      }
      const data = await apiJson('/api/push/test', {
        method: 'POST',
        body: JSON.stringify({ endpoint: subscription.endpoint }),
      });
      setPushMessage(data.message || 'Notificación Push enviada ahora.', 'success');
      if (button) button.textContent = 'Enviada ✓';
    } catch (error) {
      setPushMessage(await friendlyPushError(error), 'error');
    } finally {
      window.setTimeout(() => {
        if (!button) return;
        button.textContent = originalLabel;
        button.disabled = false;
      }, 900);
    }
  };

  navigator.serviceWorker?.addEventListener('message', (event) => {
    if (event.data?.type === 'CUOTAGO_PUSH') {
      const payload = event.data.payload || {};
      showInAppPaymentAlert({
        type: payload.type || 'overdue',
        title: payload.title || 'Alerta de cobro',
        body: payload.body || 'Tienes un pago que necesita atención.',
        detail: 'Toca para abrir',
        url: payload.url || '/notifications',
      }, { forceSound: true });
      if ('setAppBadge' in navigator) navigator.setAppBadge().catch?.(() => {});
    }
  });

  const setupRememberedLaunchGate = () => {
    // Flask-Login already decides whether the user is authenticated. The PWA must
    // never replace an internal module navigation with /resume or /login.
    if (!document.body.classList.contains('app-authenticated')) return;
    const params = new URLSearchParams(window.location.search);
    if (params.get('entered') !== '1' && params.get('source') !== 'pwa') return;
    try { sessionStorage.setItem('cuotago-launch-unlocked', '1'); } catch (_) {}
    params.delete('entered');
    params.delete('source');
    const cleanQuery = params.toString();
    history.replaceState({}, '', `${location.pathname}${cleanQuery ? `?${cleanQuery}` : ''}${location.hash}`);
  };

  const setupProfileMenu = () => {
    const trigger = document.getElementById('profileMenuTrigger');
    const dialog = document.getElementById('profileMenuDialog');
    const closeButton = document.getElementById('profileMenuClose');
    if (!trigger || !dialog) return;

    const setExpanded = (expanded) => trigger.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    const openMenu = () => {
      if (dialog.open) return;
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else dialog.setAttribute('open', '');
      setExpanded(true);
    };
    const closeMenu = () => {
      if (!dialog.open && !dialog.hasAttribute('open')) return;
      if (typeof dialog.close === 'function') dialog.close();
      else dialog.removeAttribute('open');
      setExpanded(false);
    };

    trigger.addEventListener('click', openMenu);
    closeButton?.addEventListener('click', closeMenu);
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog) closeMenu();
    });
    dialog.addEventListener('close', () => setExpanded(false));
    dialog.addEventListener('cancel', () => setExpanded(false));
  };

  const setupPaymentDialog = () => {
    const dialog = document.getElementById('paymentDialog');
    if (!dialog) return;

    const amountInput = dialog.querySelector('input[name="amount"]');
    const kindInput = dialog.querySelector('[data-payment-kind-input]');
    const eyebrow = dialog.querySelector('[data-payment-dialog-eyebrow]');
    const submitButton = dialog.querySelector('[data-payment-submit]');
    const defaultAmount = dialog.dataset.defaultAmount || amountInput?.value || '';
    const openers = document.querySelectorAll('[data-open-payment]');
    const closeButtons = dialog.querySelectorAll('[data-payment-close]');

    const isOpen = () => dialog.open || dialog.hasAttribute('open');
    const openDialog = (amount = defaultAmount, kind = 'payment') => {
      const isAdvance = kind === 'advance';
      if (kindInput) kindInput.value = isAdvance ? 'advance' : 'payment';
      if (eyebrow) eyebrow.textContent = isAdvance ? 'REGISTRAR ABONO' : 'REGISTRAR PAGO';
      if (submitButton) submitButton.textContent = isAdvance ? 'Guardar abono' : 'Registrar pago';
      if (amountInput) amountInput.value = isAdvance ? (amount || '') : (amount || defaultAmount);
      if (!isOpen()) {
        if (typeof dialog.showModal === 'function') dialog.showModal();
        else dialog.setAttribute('open', '');
      }
      document.body.classList.add('payment-dialog-open');
      window.setTimeout(() => amountInput?.focus({ preventScroll: true }), 60);
    };
    const closeDialog = () => {
      if (!isOpen()) return;
      if (typeof dialog.close === 'function') dialog.close();
      else dialog.removeAttribute('open');
      document.body.classList.remove('payment-dialog-open');
    };

    openers.forEach((button) => {
      button.addEventListener('click', () => openDialog(
        button.dataset.paymentAmount ?? defaultAmount,
        button.dataset.paymentKind || 'payment',
      ));
    });
    closeButtons.forEach((button) => button.addEventListener('click', closeDialog));
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog) closeDialog();
    });
    dialog.addEventListener('cancel', (event) => {
      event.preventDefault();
      closeDialog();
    });
    dialog.addEventListener('close', () => document.body.classList.remove('payment-dialog-open'));

    if (window.location.hash === '#pay') {
      window.setTimeout(() => openDialog(defaultAmount, 'payment'), 80);
    }
  };

  const setupPullToRefresh = () => {
    const indicator = document.getElementById('pullRefreshIndicator');
    if (!indicator || !document.body.classList.contains('app-authenticated')) return;
    let startY = null;
    let distance = 0;
    let active = false;
    const threshold = 72;
    const reset = () => {
      startY = null;
      distance = 0;
      active = false;
      indicator.classList.remove('is-ready', 'is-pulling');
      indicator.style.setProperty('--pull', '0px');
      indicator.querySelector('span').textContent = 'Desliza para actualizar';
    };
    document.addEventListener('touchstart', (event) => {
      if (event.touches?.length !== 1 || window.scrollY > 0) return;
      if (event.target.closest('input,textarea,select,[contenteditable="true"],.profile-trigger,.profile-dialog')) return;
      startY = event.touches[0].clientY;
      distance = 0;
    }, { passive: true });
    document.addEventListener('touchmove', (event) => {
      if (startY === null || event.touches?.length !== 1 || window.scrollY > 0) return;
      const delta = event.touches[0].clientY - startY;
      if (delta <= 8) return;
      active = true;
      event.preventDefault();
      distance = Math.min(110, (delta - 8) * 0.58);
      indicator.classList.add('is-pulling');
      indicator.style.setProperty('--pull', `${distance}px`);
      const ready = distance >= threshold;
      indicator.classList.toggle('is-ready', ready);
      indicator.querySelector('span').textContent = ready ? 'Suelta para actualizar' : 'Desliza para actualizar';
    }, { passive: false });
    document.addEventListener('touchend', () => {
      if (!active) return reset();
      if (distance >= threshold) {
        indicator.classList.add('is-refreshing');
        indicator.querySelector('span').textContent = 'Actualizando…';
        window.setTimeout(() => window.location.reload(), 120);
        return;
      }
      reset();
    }, { passive: true });
    document.addEventListener('touchcancel', reset, { passive: true });
  };

  const setupAssetPhotoPreview = () => {
    document.querySelectorAll('[data-asset-photo-input]').forEach((input) => {
      input.addEventListener('change', () => {
        const file = input.files?.[0];
        if (!file) return;
        const editor = input.closest('.asset-photo-editor');
        const preview = editor?.querySelector('[data-asset-photo-preview]');
        const placeholder = editor?.querySelector('[data-asset-photo-placeholder]');
        const label = editor?.querySelector('[data-asset-photo-name]');
        if (!preview) return;
        const objectUrl = URL.createObjectURL(file);
        preview.src = objectUrl;
        preview.hidden = false;
        if (placeholder) placeholder.hidden = true;
        if (label) label.textContent = file.name;
        preview.addEventListener('load', () => URL.revokeObjectURL(objectUrl), { once: true });
      });
    });
  };

  const setupPaymentCalendar = () => {
    const host = document.querySelector('[data-payment-calendar]');
    if (!host) return;
    const endpoint = host.dataset.calendarApi;
    const searchInput = host.querySelector('[data-calendar-search]');
    const clearButton = host.querySelector('[data-calendar-clear]');
    const grid = host.querySelector('[data-calendar-grid]');
    const monthLabel = host.querySelector('[data-calendar-month-label]');
    const monthSummary = host.querySelector('[data-calendar-month-summary]');
    const dayTitle = host.querySelector('[data-calendar-day-title]');
    const dayCount = host.querySelector('[data-calendar-day-count]');
    const dayItems = host.querySelector('[data-calendar-day-items]');
    const filterLabel = host.querySelector('[data-calendar-filter-label]');
    const visibleCount = host.querySelector('[data-calendar-visible-count]');
    const calendarSurface = host.querySelector('.real-calendar');
    if (!endpoint || !grid || !monthLabel || !dayItems) return;

    const pad = (value) => String(value).padStart(2, '0');
    const isoFromDate = (value) => `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`;
    const dateFromIso = (value) => {
      const [year, month, day] = String(value || '').split('-').map(Number);
      return new Date(year || 2000, (month || 1) - 1, day || 1);
    };
    const titleCase = (value) => value ? value.charAt(0).toUpperCase() + value.slice(1) : value;
    const monthFormatter = new Intl.DateTimeFormat('es-DO', { month: 'long', year: 'numeric' });
    const dayFormatter = new Intl.DateTimeFormat('es-DO', { weekday: 'long', day: 'numeric', month: 'long' });
    const todayIso = host.dataset.today || isoFromDate(new Date());
    const todayDate = dateFromIso(todayIso);
    let viewYear = todayDate.getFullYear();
    let viewMonth = todayDate.getMonth();
    let selectedIso = todayIso;
    let events = [];
    let requestId = 0;
    const cache = new Map();

    const monthKey = () => `${viewYear}-${pad(viewMonth + 1)}`;
    const makeEmptyState = (title, copy) => {
      const empty = document.createElement('div');
      empty.className = 'calendar-day-empty';
      const mark = document.createElement('span');
      mark.className = 'calendar-day-empty-mark'; mark.textContent = '•';
      const heading = document.createElement('strong'); heading.textContent = title;
      const text = document.createElement('span'); text.textContent = copy;
      empty.append(mark, heading, text); return empty;
    };

    const loadMonth = async ({ force = false } = {}) => {
      const q = searchInput?.value.trim() || '';
      const key = `${monthKey()}|${q.toLowerCase()}`;
      if (!force && cache.has(key)) { events = cache.get(key); return; }
      const thisRequest = ++requestId;
      grid.classList.add('is-loading');
      host.setAttribute('aria-busy', 'true');
      try {
        const url = new URL(endpoint, location.origin);
        url.searchParams.set('month', monthKey());
        if (q) url.searchParams.set('q', q);
        const response = await fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
        if (!response.ok) throw new Error(`Error ${response.status}`);
        const data = await response.json();
        if (thisRequest !== requestId) return;
        events = Array.isArray(data.events) ? data.events : [];
        cache.set(key, events);
      } catch (_) {
        if (thisRequest !== requestId) return;
        events = [];
        dayItems.replaceChildren(makeEmptyState('No pude cargar este mes', navigator.onLine ? 'Intenta nuevamente.' : 'Revisa tu conexión y vuelve a intentar.'));
      } finally {
        if (thisRequest === requestId) {
          grid.classList.remove('is-loading');
          host.removeAttribute('aria-busy');
        }
      }
    };

    const choosePreferredDay = (preserve = false) => {
      const prefix = `${monthKey()}-`;
      if (preserve && selectedIso.startsWith(prefix)) return;
      selectedIso = events[0]?.date || `${monthKey()}-01`;
    };

    const renderDayPanel = (byDate) => {
      const selectedEvents = byDate.get(selectedIso) || [];
      const selectedDate = dateFromIso(selectedIso);
      if (dayTitle) dayTitle.textContent = titleCase(dayFormatter.format(selectedDate));
      if (dayCount) dayCount.textContent = `${selectedEvents.length} pago${selectedEvents.length === 1 ? '' : 's'}`;
      dayItems.replaceChildren();
      if (!selectedEvents.length) {
        dayItems.append(makeEmptyState(events.length ? 'Sin pagos este día' : 'Sin pagos este mes', events.length ? 'Los días de pago aparecen marcados en naranja.' : 'No hay cuotas pendientes para este filtro.'));
        return;
      }
      selectedEvents.forEach((item) => {
        const link = document.createElement('a'); link.className = 'calendar-payment-item'; link.href = item.contract_url;
        const dot = document.createElement('span'); dot.className = 'calendar-payment-dot';
        const copy = document.createElement('div'); copy.className = 'calendar-payment-copy';
        const name = document.createElement('strong'); name.textContent = item.client_name;
        const meta = document.createElement('span'); meta.textContent = `${item.asset_name}${Number(item.quantity) > 1 ? ` · ${item.quantity} uds.` : ''} · cuota ${item.sequence}`;
        copy.append(name, meta);
        if (item.late_fee) { const fee=document.createElement('small'); fee.className='calendar-payment-late'; fee.textContent=`Incluye ${item.late_fee} de mora`; copy.append(fee); }
        const money = document.createElement('div'); money.className='calendar-payment-money';
        const amount=document.createElement('strong'); amount.textContent=item.amount;
        const code=document.createElement('small'); code.textContent=item.contract_code; money.append(amount,code);
        const arrow=document.createElement('span'); arrow.className='calendar-payment-chevron'; arrow.textContent='›'; arrow.setAttribute('aria-hidden','true');
        link.append(dot,copy,money,arrow); dayItems.append(link);
      });
    };

    const render = () => {
      const byDate = new Map();
      events.forEach((item) => { if (!byDate.has(item.date)) byDate.set(item.date, []); byDate.get(item.date).push(item); });
      const monthStart = new Date(viewYear, viewMonth, 1);
      const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
      const mondayOffset = (monthStart.getDay() + 6) % 7;
      const totalCells = Math.ceil((mondayOffset + daysInMonth) / 7) * 7;
      const gridStart = new Date(viewYear, viewMonth, 1 - mondayOffset);
      monthLabel.textContent = titleCase(monthFormatter.format(monthStart));
      if (monthSummary) {
        const uniqueClients = new Set(events.map((item) => item.client_id)).size;
        monthSummary.textContent = events.length ? `${events.length} pago${events.length===1?'':'s'} · ${uniqueClients} cliente${uniqueClients===1?'':'s'}` : 'Sin pagos en este mes';
      }
      if (visibleCount) visibleCount.textContent = String(events.length);
      if (filterLabel) filterLabel.textContent = searchInput?.value.trim() ? `Filtrando: ${searchInput.value.trim()}` : 'Todos los clientes';
      grid.replaceChildren();
      for (let index=0; index<totalCells; index+=1) {
        const cellDate=new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate()+index);
        const cellIso=isoFromDate(cellDate); const cellEvents=byDate.get(cellIso)||[]; const outside=cellDate.getMonth()!==viewMonth;
        const button=document.createElement('button'); button.type='button'; button.className='real-calendar-day';
        button.classList.toggle('is-outside',outside); button.classList.toggle('is-today',cellIso===todayIso); button.classList.toggle('is-selected',cellIso===selectedIso); button.classList.toggle('has-payment',cellEvents.length>0);
        button.setAttribute('aria-label',`${titleCase(dayFormatter.format(cellDate))}${cellEvents.length?`, ${cellEvents.length} pago${cellEvents.length===1?'':'s'}`:''}`);
        const number=document.createElement('span'); number.className='real-calendar-day-number'; number.textContent=String(cellDate.getDate()); button.append(number);
        if (cellEvents.length) { const due=document.createElement('span'); due.className='real-calendar-due'; const dot=document.createElement('i'); const label=document.createElement('span'); label.textContent=cellEvents.length===1?'Pago':`${cellEvents.length} pagos`; due.append(dot,label); button.append(due); }
        button.addEventListener('click', async () => { selectedIso=cellIso; if (outside) { viewYear=cellDate.getFullYear(); viewMonth=cellDate.getMonth(); await loadMonth(); choosePreferredDay(true); } render(); });
        grid.append(button);
      }
      renderDayPanel(byDate);
    };

    const animate = (delta) => { const c=delta>0?'calendar-swipe-from-right':'calendar-swipe-from-left'; grid.classList.remove('calendar-swipe-from-right','calendar-swipe-from-left'); void grid.offsetWidth; grid.classList.add(c); grid.addEventListener('animationend',()=>grid.classList.remove(c),{once:true}); };
    const shiftMonth = async (delta, doAnimate=false) => { const target=new Date(viewYear,viewMonth+delta,1); viewYear=target.getFullYear(); viewMonth=target.getMonth(); await loadMonth(); choosePreferredDay(); render(); if(doAnimate) animate(delta); };
    host.querySelector('[data-calendar-prev]')?.addEventListener('click',()=>shiftMonth(-1));
    host.querySelector('[data-calendar-next]')?.addEventListener('click',()=>shiftMonth(1));
    host.querySelector('[data-calendar-today]')?.addEventListener('click',async()=>{viewYear=todayDate.getFullYear();viewMonth=todayDate.getMonth();selectedIso=todayIso;await loadMonth();render();});

    let searchTimer=0;
    searchInput?.addEventListener('input',()=>{ if(clearButton) clearButton.hidden=!searchInput.value; clearTimeout(searchTimer); searchTimer=window.setTimeout(async()=>{await loadMonth({force:true});choosePreferredDay();render();},220); });
    clearButton?.addEventListener('click',async()=>{if(searchInput)searchInput.value='';clearButton.hidden=true;await loadMonth();choosePreferredDay(true);searchInput?.focus();render();});

    if (calendarSurface) {
      let sx=0, sy=0, tracking=false;
      calendarSurface.addEventListener('touchstart',(event)=>{if(window.innerWidth>719||event.touches?.length!==1)return; sx=event.touches[0].clientX;sy=event.touches[0].clientY;tracking=true;},{passive:true});
      calendarSurface.addEventListener('touchend',(event)=>{if(!tracking||window.innerWidth>719||event.changedTouches?.length!==1)return;tracking=false;const dx=event.changedTouches[0].clientX-sx;const dy=event.changedTouches[0].clientY-sy;if(Math.abs(dx)<46||Math.abs(dx)<=Math.abs(dy)*1.15)return;shiftMonth(dx<0?1:-1,true);},{passive:true});
      calendarSurface.addEventListener('touchcancel',()=>{tracking=false;},{passive:true});
    }

    loadMonth().then(()=>{choosePreferredDay(true);render();});
  };

  const runNotificationDemo = async (button) => {
    if (button?.dataset.demoBusy === '1') return;
    if (button) {
      button.dataset.demoBusy = '1';
      button.disabled = true;
    }
    const originalLabel = button?.textContent.trim() || 'Probar';

    // Request system notification permission immediately from this user gesture.
    // Do not put an await before this subscription flow; iOS requires the gesture.
    let subscription = null;
    let remoteError = null;
    let remotePushPromise = null;
    try {
      setPushMessage('Activando notificaciones del sistema...', 'info');
      subscription = await subscribePushFromUserGesture();
      // Fire the real Web Push request immediately after the subscription exists.
      // Local sound/UI work continues while the provider delivers the notification.
      remotePushPromise = apiJson('/api/push/test', {
        method: 'POST',
        body: JSON.stringify({ endpoint: subscription.endpoint }),
      });
    } catch (error) {
      remoteError = error;
    }

    try {
      setLocalAlertsEnabled(true);
      updateLocalAlertStatus();
      const audioUnlockPromise = unlockAlertAudio();

      showInAppPaymentAlert({
        type: 'overdue',
        title: 'Pago atrasado',
        body: 'Pago de Cliente de ejemplo atrasado · RD$2,500.00',
        url: '/notifications',
      }, { forceSound: true });

      if (subscription) {
        const data = await remotePushPromise;
        await audioUnlockPromise.catch(() => {});
        setPushMessage(data.message || 'Notificación enviada ahora.', 'success');
        document.querySelectorAll('[data-local-alert-copy]').forEach((el) => {
          el.textContent = 'Listo. La prueba Push se envió inmediatamente al sistema.';
        });
        if (button) button.textContent = 'Enviada ✓';
        await updatePushUI();
      } else {
        const message = await friendlyPushError(remoteError || new Error('No se pudo activar Web Push.'));
        setPushMessage(message, 'error');
        document.querySelectorAll('[data-local-alert-copy]').forEach((el) => {
          el.textContent = 'La alerta dentro de CuotaGo funciona, pero falta habilitar el aviso con la app cerrada.';
        });
        if (button) button.textContent = 'Revisar';
      }
    } catch (error) {
      setPushMessage(await friendlyPushError(error), 'error');
      if (button) button.textContent = 'Reintentar';
    } finally {
      window.setTimeout(() => {
        if (!button) return;
        button.disabled = false;
        button.dataset.demoBusy = '0';
        button.textContent = originalLabel;
      }, subscription ? 1800 : 1300);
    }
  };

  const normalizeAdminConfirmation = (value) => String(value || '').trim().replace(/\s+/g, ' ').toLocaleLowerCase();

  const setupSuperadminControlCenter = () => {
    document.querySelectorAll('[data-admin-panel-group]').forEach((group) => {
      const buttons = Array.from(group.querySelectorAll('[data-admin-panel-target]'));
      const panels = Array.from(group.querySelectorAll('[data-admin-panel]'));
      if (!buttons.length || !panels.length) return;

      const activate = (name, updateHash = true) => {
        const target = panels.find((panel) => panel.dataset.adminPanel === name) || panels[0];
        const activeName = target.dataset.adminPanel;
        buttons.forEach((button) => {
          const active = button.dataset.adminPanelTarget === activeName;
          button.classList.toggle('is-active', active);
          button.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        panels.forEach((panel) => {
          const active = panel === target;
          panel.classList.toggle('is-active', active);
          panel.hidden = !active;
        });
        if (updateHash && activeName) {
          const next = `#${activeName}`;
          if (window.location.hash !== next) history.replaceState(null, '', next);
        }
      };

      buttons.forEach((button) => {
        button.addEventListener('click', () => activate(button.dataset.adminPanelTarget));
      });

      const hashName = window.location.hash.replace(/^#/, '');
      const initial = panels.some((panel) => panel.dataset.adminPanel === hashName)
        ? hashName
        : group.dataset.defaultPanel;
      activate(initial, false);

      window.addEventListener('hashchange', () => {
        const next = window.location.hash.replace(/^#/, '');
        if (panels.some((panel) => panel.dataset.adminPanel === next)) activate(next, false);
      });
    });

    document.querySelectorAll('[data-admin-danger-group]').forEach((group) => {
      const buttons = Array.from(group.querySelectorAll('[data-admin-danger-target]'));
      const host = group.parentElement;
      const panels = host ? Array.from(host.querySelectorAll('[data-admin-danger-panel]')) : [];
      if (!buttons.length || !panels.length) return;
      const activate = (name) => {
        const target = panels.find((panel) => panel.dataset.adminDangerPanel === name) || panels[0];
        const activeName = target.dataset.adminDangerPanel;
        buttons.forEach((button) => button.classList.toggle('is-active', button.dataset.adminDangerTarget === activeName));
        panels.forEach((panel) => {
          const active = panel === target;
          panel.classList.toggle('is-active', active);
          panel.hidden = !active;
        });
        target.querySelector('[data-admin-confirm-input]')?.focus({ preventScroll: true });
      };
      buttons.forEach((button) => button.addEventListener('click', () => activate(button.dataset.adminDangerTarget)));
      activate(group.dataset.defaultDanger || panels[0].dataset.adminDangerPanel);
    });

    document.querySelectorAll('[data-admin-confirm-form]').forEach((form) => {
      const input = form.querySelector('[data-admin-confirm-input]');
      const submit = form.querySelector('[data-admin-confirm-submit]');
      const checkbox = form.querySelector('[data-admin-confirm-check]');
      if (!input || !submit) return;
      const expected = normalizeAdminConfirmation(form.dataset.expectedConfirmation);
      const update = () => {
        const phraseMatches = normalizeAdminConfirmation(input.value) === expected;
        const checkMatches = !checkbox || checkbox.checked;
        submit.disabled = !(phraseMatches && checkMatches);
        form.classList.toggle('is-confirmed', phraseMatches && checkMatches);
      };
      input.addEventListener('input', update);
      checkbox?.addEventListener('change', update);
      form.addEventListener('submit', (event) => {
        update();
        if (submit.disabled) {
          event.preventDefault();
          input.focus();
        }
      });
      update();
    });
  };

  const setupPdfSharing = () => {
    document.querySelectorAll('[data-share-pdf]').forEach((button) => {
      button.addEventListener('click', async () => {
        const url = button.dataset.shareUrl;
        if (!url) return;
        const original = button.innerHTML;
        button.disabled = true;
        try {
          const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
          if (!response.ok) throw new Error('pdf');
          const blob = await response.blob();
          const name = button.dataset.shareName || 'documento.pdf';
          const file = new File([blob], name, { type: 'application/pdf' });
          if (navigator.share && (!navigator.canShare || navigator.canShare({ files: [file] }))) {
            await navigator.share({
              title: button.dataset.shareTitle || 'Documento CuotaGo',
              files: [file],
            });
          } else {
            window.open(url, '_blank', 'noopener');
          }
        } catch (error) {
          if (error?.name !== 'AbortError') window.open(url, '_blank', 'noopener');
        } finally {
          button.disabled = false;
          button.innerHTML = original;
        }
      });
    });
  };



  const setupGlobalQuickSearch = () => {
    const dialog = document.getElementById('globalSearchDialog');
    const input = document.getElementById('globalSearchInput');
    const results = document.getElementById('globalSearchResults');
    const hint = document.getElementById('globalSearchHint');
    const close = document.getElementById('globalSearchClose');
    const full = document.getElementById('globalSearchFull');
    const triggers = Array.from(document.querySelectorAll('[data-global-search-open]'));
    if (!dialog || !input || !results || !triggers.length) return;
    let timer = 0;
    let controller = null;

    const render = (items = []) => {
      results.replaceChildren();
      if (!items.length) {
        hint.hidden = false;
        hint.textContent = input.value.trim().length >= 2 ? 'No encontré coincidencias.' : 'Escribe al menos 2 caracteres.';
        return;
      }
      hint.hidden = true;
      items.slice(0, 14).forEach((item) => {
        const link = document.createElement('a');
        link.className = 'quick-search-result-v17';
        link.href = item.url;
        const kind = document.createElement('span'); kind.textContent = item.kind || 'Resultado';
        const copy = document.createElement('div');
        const title = document.createElement('strong'); title.textContent = item.title || '';
        const meta = document.createElement('small'); meta.textContent = item.meta || '';
        const chevron = document.createElement('b'); chevron.textContent = '›'; chevron.setAttribute('aria-hidden','true');
        copy.append(title, meta); link.append(kind, copy, chevron); results.append(link);
      });
    };

    const search = async () => {
      const q = input.value.trim();
      if (full) full.href = `/search${q ? `?q=${encodeURIComponent(q)}` : ''}`;
      if (q.length < 2) { controller?.abort(); render([]); return; }
      controller?.abort(); controller = new AbortController();
      hint.hidden = false; hint.textContent = 'Buscando…';
      try {
        const response = await fetch(`/api/search?q=${encodeURIComponent(q)}`, {credentials:'same-origin', cache:'no-store', signal:controller.signal});
        if (!response.ok) throw new Error('search');
        const data = await response.json(); render(data.items || []);
      } catch (error) {
        if (error?.name !== 'AbortError') { hint.hidden = false; hint.textContent = 'No pude buscar ahora. Intenta de nuevo.'; }
      }
    };

    const open = (event) => {
      event?.preventDefault();
      if (!dialog.open) dialog.showModal();
      requestAnimationFrame(() => input.focus({preventScroll:true}));
    };
    triggers.forEach((trigger) => trigger.addEventListener('click', open));
    close?.addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
    dialog.addEventListener('close', () => { controller?.abort(); });
    input.addEventListener('input', () => { clearTimeout(timer); timer = window.setTimeout(search, 150); });
    document.addEventListener('keydown', (event) => {
      if ((event.key === '/' || ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k')) && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || '')) {
        open(event);
      }
      if (event.key === 'Escape' && dialog.open) dialog.close();
    });
  };

  const setupCalmFormGuard = () => {
    document.querySelectorAll('form[method="post"], form[method="POST"]').forEach((form) => {
      form.addEventListener('submit', (event) => {
        if (form.dataset.submittingV17 === '1') { event.preventDefault(); return; }
        if (event.defaultPrevented) return;
        form.dataset.submittingV17 = '1';
        form.classList.add('is-submitting-v17');
        const submitter = event.submitter;
        if (submitter) {
          submitter.setAttribute('aria-busy', 'true');
          const label = submitter.textContent?.trim();
          if (label && label.length < 34) submitter.dataset.originalTextV17 = label;
        }
        // If browser validation/another handler cancels the navigation, unlock.
        window.setTimeout(() => {
          if (document.visibilityState === 'visible') {
            form.dataset.submittingV17 = '0'; form.classList.remove('is-submitting-v17');
            submitter?.removeAttribute('aria-busy');
          }
        }, 6000);
      });
    });
    window.addEventListener('pageshow', () => {
      document.querySelectorAll('form.is-submitting-v17').forEach((form) => {
        form.dataset.submittingV17 = '0'; form.classList.remove('is-submitting-v17');
        form.querySelectorAll('[aria-busy="true"]').forEach((node) => node.removeAttribute('aria-busy'));
      });
    });
  };



  const setupNativeNavigationMemory = () => {
    if ('scrollRestoration' in history) history.scrollRestoration = 'auto';
    const key = `cuotago-scroll:${location.pathname}${location.search}`;
    window.addEventListener('pagehide', () => {
      try { sessionStorage.setItem(key, String(Math.round(window.scrollY || 0))); } catch (_) {}
    });
    window.addEventListener('pageshow', () => {
      const nav = performance.getEntriesByType?.('navigation')?.[0];
      if (nav?.type !== 'back_forward') return;
      try {
        const saved = Number(sessionStorage.getItem(key));
        if (Number.isFinite(saved) && saved > 0) requestAnimationFrame(() => window.scrollTo({top:saved,left:0,behavior:'auto'}));
      } catch (_) {}
    });
    document.addEventListener('click', (event) => {
      const link = event.target.closest?.('a[href]');
      if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      if (link.target && link.target !== '_self') return;
      if (link.hasAttribute('download')) return;
      let url;
      try { url = new URL(link.href, location.href); } catch (_) { return; }
      if (url.origin !== location.origin || (url.pathname === location.pathname && url.search === location.search && url.hash)) return;
      document.body.classList.add('is-navigating-v17');
    }, {capture:true});
    window.addEventListener('pageshow', () => document.body.classList.remove('is-navigating-v17'));
  };

  document.addEventListener('DOMContentLoaded', () => {
    setupRememberedLaunchGate();
    setupProfileMenu();
    setupPaymentDialog();
    setupAssetPhotoPreview();
    setupPullToRefresh();
    setupPaymentCalendar();
    setupSuperadminControlCenter();
    setupPdfSharing();
    setupGlobalQuickSearch();
    setupCalmFormGuard();
    setupNativeNavigationMemory();
    applyTheme(document.body.classList.contains('auth-shell') ? 'light' : readTheme(), false);

    document.querySelectorAll('[data-theme-choice]').forEach((button) => {
      button.addEventListener('click', () => applyTheme(button.dataset.themeChoice));
    });
    document.querySelectorAll('[data-theme-toggle-switch]').forEach((control) => {
      if (control.matches('input[type="checkbox"]')) {
        control.addEventListener('change', () => applyTheme(control.checked ? 'dark' : 'light', true));
        return;
      }
      control.addEventListener('click', () => {
        const nextTheme = root.dataset.theme === 'dark' ? 'light' : 'dark';
        applyTheme(nextTheme, true);
      });
    });
    document.querySelectorAll('[data-local-alert-switch]').forEach((input) => {
      input.addEventListener('change', async () => {
        setLocalAlertsEnabled(input.checked);
        if (input.checked) await unlockAlertAudio();
        updateLocalAlertStatus();
        if (input.checked) pollPaymentAlerts({ showToast: true });
      });
    });
    document.querySelectorAll('[data-push-switch]').forEach((input) => {
      input.addEventListener('change', async () => {
        if (input.checked) await enablePush(input);
        else await disablePush(input);
        await updatePushUI();
      });
    });

    const authThemeToggle = document.getElementById('authThemeToggle');
    authThemeToggle?.addEventListener('click', () => {
      const current = root.dataset.theme === 'dark' ? 'dark' : 'light';
      applyTheme(current === 'dark' ? 'light' : 'dark');
    });

    document.querySelectorAll('form[data-confirm]').forEach((form) => {
      form.addEventListener('submit', (event) => {
        if (!window.confirm(form.dataset.confirm || '¿Continuar?')) event.preventDefault();
      });
    });

    document.querySelectorAll('[data-flash]').forEach((el) => {
      setTimeout(() => {
        el.style.opacity = '0';
        el.style.transform = 'translateY(-5px)';
        el.style.transition = 'opacity .2s ease, transform .2s ease';
        setTimeout(() => el.remove(), 220);
      }, 4200);
    });

    document.querySelectorAll('[data-push-enable]').forEach((button) => button.addEventListener('click', () => enablePush(button)));
    document.querySelectorAll('[data-push-disable]').forEach((button) => button.addEventListener('click', () => disablePush(button)));
    document.querySelectorAll('[data-push-test]').forEach((button) => button.addEventListener('click', () => testPush(button)));
    document.querySelectorAll('[data-push-test-background]').forEach((button) => button.addEventListener('click', () => testPushOutside(button)));
    document.querySelectorAll('[data-notification-demo]').forEach((button) => {
      button.addEventListener('click', () => runNotificationDemo(button));
    });
    document.querySelectorAll('[data-inapp-alert-test],[data-local-alert-test]').forEach((button) => button.addEventListener('click', async () => {
      setLocalAlertsEnabled(true);
      updateLocalAlertStatus();
      await unlockAlertAudio();
      showInAppPaymentAlert({
        type: 'overdue',
        title: 'Pago atrasado',
        body: 'Pago de Cliente de ejemplo atrasado · RD$2,500.00',
        url: '/notifications',
      }, { forceSound: true });
    }));
    updateLocalAlertStatus();
    startPaymentAlertWatcher();
    updatePushUI();
  });

})();
