const VERSION = '1.12.1-ui-v11';
const STATIC_CACHE = `cuotago-static-${VERSION}`;
const RUNTIME_CACHE = `cuotago-runtime-${VERSION}`;
const CORE = [
  '/offline',
  '/static/css/app.css',
  '/static/js/app.js',
  '/static/manifest.webmanifest',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/apple-touch-icon.png',
  '/static/icons/icon-maskable-512.png',
  '/static/icons/favicon-64.png',
  '/static/icons/favicon-32.png',
  '/static/sounds/alert.wav'
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(STATIC_CACHE).then((cache) => cache.addAll(CORE)));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => key.startsWith('cuotago-') && ![STATIC_CACHE, RUNTIME_CACHE].includes(key)).map((key) => caches.delete(key))
    ))
  );
  self.clients.claim();
});

self.addEventListener('push', (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch (_) {
    payload = { body: event.data ? event.data.text() : '' };
  }

  const title = payload.title || 'CuotaGo';
  const basicOptions = {
    body: payload.body || 'Tienes una alerta de cobro.',
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/favicon-64.png',
    tag: payload.tag || `cuotago-${Date.now()}`,
    silent: false,
    data: {
      url: payload.url || '/notifications',
      type: payload.type || 'general',
      contractId: payload.contractId || null,
    },
  };

  // Keep the first notification payload deliberately conservative. Safari/iOS
  // ignores several Chromium-only fields and older versions can reject a
  // notification when unsupported options are mixed together.
  const showSystemNotification = self.registration.showNotification(title, basicOptions)
    .catch(() => self.registration.showNotification(title, {
      body: basicOptions.body,
      icon: basicOptions.icon,
      data: basicOptions.data,
    }));

  const tellOpenWindows = self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
    clients.forEach((client) => client.postMessage({ type: 'CUOTAGO_PUSH', payload }));
  });

  event.waitUntil(Promise.allSettled([showSystemNotification, tellOpenWindows]));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = event.notification.data?.url || '/notifications';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if ('focus' in client) {
          client.navigate?.(target);
          return client.focus();
        }
      }
      return self.clients.openWindow ? self.clients.openWindow(target) : undefined;
    })
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => caches.match('/offline')));
    return;
  }

  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((response) => {
          if (!response || response.status !== 200 || response.type !== 'basic') return response;
          const copy = response.clone();
          caches.open(RUNTIME_CACHE).then((cache) => cache.put(request, copy));
          return response;
        });
      })
    );
  }
});
