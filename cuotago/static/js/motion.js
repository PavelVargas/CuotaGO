/* CuotaGo motion: progressive MPA transitions, not a client-side router.
 * Runs in <head> so pagereveal is registered before the first paint.
 * No prevented clicks, delayed navigation, fetch of private pages, or timers
 * holding a screen open. Only opacity and transform are animated.
 */
(() => {
  'use strict';
  const root = document.documentElement;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const storageKey = 'cuotago-motion-navigation';
  const activeAnimations = new Map();
  const isApp = () => root.dataset.authScreen !== '1';
  const path = (url) => new URL(url, location.href).pathname.replace(/\/$/, '') || '/';
  let hasViewTransition = false;
  let appeared = false;

  const directionBetween = (from, to) => {
    const a = path(from); const b = path(to);
    if (a === b) return 'fade';
    if (b === '/' || a.startsWith(`${b}/`)) return 'back';
    return 'forward';
  };
  const setDirection = (direction) => {
    root.dataset.motionDirection = ['back', 'forward', 'fade'].includes(direction) ? direction : 'forward';
  };
  try {
    const stored = JSON.parse(sessionStorage.getItem(storageKey) || 'null');
    sessionStorage.removeItem(storageKey);
    if (stored && stored.to === path(location.href) && Date.now() - stored.at < 15000) setDirection(stored.direction);
  } catch (_) { /* Storage is optional (private browsing / disabled storage). */ }
  if (!root.dataset.motionDirection) {
    const kind = performance.getEntriesByType?.('navigation')?.[0]?.type;
    setDirection(kind === 'back_forward' ? 'back' : (document.referrer ? directionBetween(document.referrer, location.href) : 'forward'));
  }

  const cancelAnimations = () => {
    for (const animation of activeAnimations.values()) animation.cancel();
    activeAnimations.clear();
  };
  const reveal = (element, direction = 'forward', duration = 220) => {
    if (!element || element.hidden || reduced.matches || !element.animate) return;
    activeAnimations.get(element)?.cancel();
    const sign = direction === 'back' ? -1 : 1;
    const distance = direction === 'fade' ? 0 : 12 * sign;
    const animation = element.animate([
      { opacity: .5, transform: `translate3d(${distance}px, 0, 0)` },
      { opacity: 1, transform: 'translate3d(0, 0, 0)' },
    ], { duration, easing: 'cubic-bezier(.2,.75,.25,1)', fill: 'none' });
    activeAnimations.set(element, animation);
    const clear = () => { if (activeAnimations.get(element) === animation) activeAnimations.delete(element); };
    animation.finished.then(clear, clear);
  };
  // Shared by agreement steps. It never changes visibility, focus or data.
  window.CuotaGoMotion = Object.freeze({ reveal, cancel: cancelAnimations });

  const fallbackEntrance = () => {
    if (appeared || hasViewTransition || !isApp() || reduced.matches || root.classList.contains('show-boot')) return;
    appeared = true;
    // Home geometry includes anchored indicators; only fade its content.
    const target = document.querySelector('.page-shell > .content-page, .page-shell > .launcher-wrap');
    reveal(target, document.body.classList.contains('dashboard-home') ? 'fade' : root.dataset.motionDirection, 230);
  };
  document.addEventListener('DOMContentLoaded', () => {
    // pagereveal precedes rendering; rAF prevents a double entrance in supporting browsers.
    requestAnimationFrame(fallbackEntrance);
  }, { once: true });
  window.addEventListener('pagereveal', (event) => {
    const transition = event.viewTransition;
    if (!transition) { requestAnimationFrame(fallbackEntrance); return; }
    hasViewTransition = true;
    appeared = true;
    cancelAnimations();
    const activation = window.navigation?.activation;
    if (activation?.from?.url) {
      setDirection(activation.navigationType === 'traverse' && activation.entry?.index < activation.from.index
        ? 'back' : directionBetween(activation.from.url, location.href));
    }
    if (reduced.matches || !isApp() || root.classList.contains('show-boot')) transition.skipTransition();
    // Catch rejected promises on interrupted/unsupported snapshots.
    transition.ready?.catch(() => {});
    transition.finished?.catch(() => {});
  });
  window.addEventListener('pageswap', (event) => {
    if (event.viewTransition && (reduced.matches || !isApp())) event.viewTransition.skipTransition();
  });
  window.addEventListener('pagehide', cancelAnimations);
  window.addEventListener('pageshow', (event) => {
    if (event.persisted) {
      cancelAnimations();
      // Do not replay a stale entrance, steal focus or change restored scroll position.
      appeared = true;
    }
  });
  reduced.addEventListener?.('change', () => {
    if (reduced.matches) {
      cancelAnimations();
      document.activeViewTransition?.skipTransition();
    }
  });

  document.addEventListener('click', (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest?.('a[href]');
    if (!link || link.hasAttribute('download') || (link.target && link.target !== '_self') || link.hasAttribute('data-no-motion')) return;
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin || !/^https?:$/.test(url.protocol) || url.hash) return;
    if (/\.(pdf|csv|xlsx|zip)$|\/(logout|login|register|receipt|print|export)(\/|$)/i.test(url.pathname)) return;
    if (path(url) === path(location.href)) return;
    const backLabel = /volver|atr\u00e1s|inicio/i.test(link.getAttribute('aria-label') || '');
    const direction = backLabel || link.hasAttribute('data-motion-back') ? 'back' : directionBetween(location.href, url);
    setDirection(direction);
    try {
      sessionStorage.setItem(storageKey, JSON.stringify({ to: path(url), direction, at: Date.now() }));
    } catch (_) {}
  });
})();
