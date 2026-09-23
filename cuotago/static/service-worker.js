const VERSION = '1.17.4-ui-v43';
const STATIC_CACHE = `cuotago-static-${VERSION}`;
const CORE = [
  '/offline',
  '/static/css/app.css',
  '/static/js/app.js',
  '/static/manifest.webmanifest',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/apple-touch-icon.png',
  '/static/icons/icon-maskable-512.png',
  '/static/icons/logo-full-light.png',
  '/static/icons/logo-full-dark.png',
  '/static/icons/logo-symbol-light.png',
  '/static/icons/logo-symbol-dark.png',
  '/static/icons/logo-word-light.png',
  '/static/icons/logo-word-dark.png',
  '/static/icons/favicon-64.png',
  '/static/icons/favicon-32.png',
  '/static/sounds/alert.wav'
];

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(STATIC_CACHE);
    await Promise.all(CORE.map(async (path) => {
      const response = await fetch(path, { cache: 'reload' });
      if (response.ok) await cache.put(path, response.clone());
    }));
  })());
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((key) => key.startsWith('cuotago-') && key !== STATIC_CACHE).map((key) => caches.delete(key)));
    if (self.registration.navigationPreload) {
      try { await self.registration.navigationPreload.enable(); } catch (_) {}
    }
    await self.clients.claim();
  })());
});

self.addEventListener('push', (event) => {
  let payload = {};
  try { payload = event.data ? event.data.json() : {}; }
  catch (_) { payload = { body: event.data ? event.data.text() : '' }; }

  const title = payload.title || 'CuotaGo';
  const options = {
    body: payload.body || 'Tienes una alerta de cobro.',
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/favicon-64.png',
    tag: payload.tag || `cuotago-${Date.now()}`,
    silent: false,
    data: {
      url: payload.url || '/notifications',
      type: payload.type || 'general',
      contractId: payload.contractId || null,
      installmentId: payload.installmentId || null,
      replaceKey: payload.replaceKey || null,
    },
  };

  const showSystemNotification = (async () => {
    if (options.data.replaceKey) {
      try {
        const previous = await self.registration.getNotifications();
        previous.forEach((notification) => {
          if (notification.data?.replaceKey === options.data.replaceKey) notification.close();
        });
      } catch (_) {}
    }
    try { return await self.registration.showNotification(title, options); }
    catch (_) { return self.registration.showNotification(title, { body: options.body, icon: options.icon, data: options.data }); }
  })();

  const tellOpenWindows = self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
    clients.forEach((client) => client.postMessage({ type: 'CUOTAGO_PUSH', payload }));
  });
  event.waitUntil(Promise.allSettled([showSystemNotification, tellOpenWindows]));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = event.notification.data?.url || '/notifications';
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
    for (const client of clientList) {
      if ('focus' in client) {
        client.navigate?.(target);
        return client.focus();
      }
    }
    return self.clients.openWindow ? self.clients.openWindow(target) : undefined;
  }));
});

const fetchWithTimeout = async (request, timeoutMs = 10000, preloadResponse = null) => {
  const preloaded = preloadResponse ? await preloadResponse.catch(() => null) : null;
  if (preloaded) return preloaded;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try { return await fetch(request, { signal: controller.signal }); }
  finally { clearTimeout(timer); }
};

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Financial/tenant HTML is never persisted in a runtime cache. Navigation
  // preload only removes service-worker startup latency and still comes from
  // the live server. Offline falls back to a neutral shell instead of stale money.
  if (request.mode === 'navigate') {
    event.respondWith(fetchWithTimeout(request, 10000, event.preloadResponse).catch(() => caches.match('/offline')));
    return;
  }

  if (url.pathname.startsWith('/static/')) {
    event.respondWith((async () => {
      const cached = await caches.match(request, { ignoreSearch: true });
      const network = fetch(request, { cache: 'no-cache' }).then((response) => {
        if (response && response.ok && response.type === 'basic') {
          caches.open(STATIC_CACHE).then((cache) => cache.put(request, response.clone()));
        }
        return response;
      }).catch(() => null);
      if (cached) {
        event.waitUntil(network);
        return cached;
      }
      return (await network) || Response.error();
    })());
  }
});
