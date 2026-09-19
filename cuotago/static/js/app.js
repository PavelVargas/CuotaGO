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
  };

  const applyTheme = (choice, persist = true) => {
    const safeChoice = ['light', 'dark', 'system'].includes(choice) ? choice : 'system';
    const resolved = resolvedTheme(safeChoice);
    root.dataset.themeChoice = safeChoice;
    root.dataset.theme = resolved;
    const booting = root.classList.contains('show-boot');
    document.getElementById('themeColorMeta')?.setAttribute('content', booting ? '#fffaf6' : (resolved === 'dark' ? '#0b0f14' : '#f4f7fb'));
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

  const APP_VERSION = '1.12.1';
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

  const updateLocalAlertStatus = () => {
    const supported = Boolean(window.AudioContext || window.webkitAudioContext);
    document.querySelectorAll('[data-local-alert-status]').forEach((el) => {
      if (!supported) {
        el.textContent = 'Sin audio';
        el.dataset.active = '0';
        return;
      }
      el.textContent = alertAudioUnlocked ? 'Sonido listo' : 'Se activa al tocar';
      el.dataset.active = alertAudioUnlocked ? '1' : '0';
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
  const showInAppPaymentAlert = (item = {}, { forceSound = true } = {}) => {
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
      if (!showToast) return;
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
    if (!document.body.classList.contains('app-authenticated')) return;
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
      return;
    }

    if (isIOS() && !isStandalone()) {
      controls.forEach((el) => el.dataset.state = 'install-first');
      setPushMessage('Para recibir alertas en iPhone, añade CuotaGo a la pantalla de inicio y ábrela desde su icono.', 'info');
      document.querySelectorAll('[data-push-status]').forEach((el) => {
        el.textContent = 'Instala la PWA';
        el.dataset.active = '0';
      });
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
    }
  };

  const enablePush = async (button) => {
    if (button) button.disabled = true;
    try {
      if (!window.isSecureContext) throw new Error('Las alertas necesitan HTTPS.');
      if (isIOS() && !isStandalone()) throw new Error('Instala CuotaGo en la pantalla de inicio y ábrela desde su icono para activar alertas en iPhone/iPad.');
      if (!pushSupported()) throw new Error('Este navegador no admite Web Push.');

      const publicKey = document.querySelector('meta[name="cuotago-vapid-key"]')?.content || '';
      const pushEnabled = document.querySelector('meta[name="cuotago-push-enabled"]')?.content === '1';
      if (!pushEnabled || !publicKey) throw new Error('El servidor todavía no tiene Web Push habilitado.');

      // Safari/iOS exige que el permiso nazca directamente del toque del usuario.
      // Por eso requestPermission ocurre antes de cualquier fetch o espera de red.
      const permission = Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission();
      if (permission !== 'granted') throw new Error('No se concedió permiso para notificaciones.');

      setPushMessage('Conectando este dispositivo...', 'info');
      const subscription = await createPushSubscription(publicKey, () => {
        setPushMessage('Reparando la conexión Push y reintentando...', 'info');
      });
      await saveSubscriptionOnServer(subscription);

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
    const originalLabel = button?.textContent || 'Simular fuera de la app';
    try {
      if (!window.isSecureContext) throw new Error('Esta prueba necesita HTTPS.');
      if (isIOS() && !isStandalone()) throw new Error('En iPhone, instala CuotaGo en la pantalla de inicio y abre la PWA desde su icono.');
      const registration = await registerServiceWorker();
      const subscription = await registration.pushManager.getSubscription();
      if (!subscription || Notification.permission !== 'granted') {
        throw new Error('Primero activa las notificaciones en este teléfono.');
      }
      const data = await apiJson('/api/push/test-delayed', {
        method: 'POST',
        body: JSON.stringify({ endpoint: subscription.endpoint, delay: 10 }),
      });
      let remaining = Number(data.delay || 10);
      setPushMessage('Prueba programada. Sal de CuotaGo AHORA y espera la notificación del sistema.', 'success');
      if (button) button.textContent = `Cierra la app · ${remaining}s`;
      const timer = window.setInterval(() => {
        remaining -= 1;
        if (button && remaining > 0) button.textContent = `Cierra la app · ${remaining}s`;
        if (remaining <= 0) {
          window.clearInterval(timer);
          if (button) {
            button.textContent = originalLabel;
            button.disabled = false;
          }
        }
      }, 1000);
      return;
    } catch (error) {
      setPushMessage(await friendlyPushError(error), 'error');
    }
    if (button) {
      button.textContent = originalLabel;
      button.disabled = false;
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
    if (!document.body.classList.contains('app-authenticated') || !isStandalone()) return;
    const params = new URLSearchParams(window.location.search);
    if (params.get('entered') === '1') {
      try { sessionStorage.setItem('cuotago-launch-unlocked', '1'); } catch (_) {}
      params.delete('entered');
      params.delete('source');
      const cleanQuery = params.toString();
      history.replaceState({}, '', `${location.pathname}${cleanQuery ? `?${cleanQuery}` : ''}${location.hash}`);
      return;
    }
    let unlocked = false;
    try { unlocked = sessionStorage.getItem('cuotago-launch-unlocked') === '1'; } catch (_) {}
    if (!unlocked) {
      const next = `${location.pathname}${location.search}${location.hash}`;
      location.replace(`/resume?next=${encodeURIComponent(next)}`);
    }
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

  document.addEventListener('DOMContentLoaded', () => {
    setupRememberedLaunchGate();
    setupProfileMenu();
    setupPullToRefresh();
    applyTheme(document.body.classList.contains('auth-shell') ? 'light' : readTheme(), false);

    document.querySelectorAll('[data-theme-choice]').forEach((button) => {
      button.addEventListener('click', () => applyTheme(button.dataset.themeChoice));
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
    document.querySelectorAll('[data-inapp-alert-test],[data-local-alert-test]').forEach((button) => button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        await unlockAlertAudio();
        showInAppPaymentAlert({
          type: 'overdue',
          title: 'Pago atrasado',
          client: 'Cliente de prueba',
          amount: 'RD$2,500.00',
          detail: 'Toca para ir al cobro',
          url: '/notifications',
        }, { forceSound: true });
        document.querySelectorAll('[data-local-alert-copy]').forEach((el) => {
          el.textContent = alertAudioUnlocked
            ? 'Prueba enviada: debes ver la alerta y escuchar tres tonos.'
            : 'La alerta visual funciona. Toca de nuevo para habilitar el sonido en este iPhone.';
        });
      } finally {
        window.setTimeout(() => { button.disabled = false; }, 650);
      }
    }));
    updateLocalAlertStatus();
    startPaymentAlertWatcher();
    updatePushUI();
  });

})();
