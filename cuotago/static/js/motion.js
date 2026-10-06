/* CuotaGo motion: progressive MPA transitions, not a client-side router.
 * Deferred: never blocks HTML parsing. No full-page snapshot transitions.
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
  const reveal = (element, direction = 'forward', duration = 160) => {
    if (!element || element.hidden || reduced.matches || !element.animate || document.visibilityState === 'hidden') return;
    // Never promote an entire long inventory/CRM page to an animated texture.
    // Animate a small heading instead, leaving forms and fixed controls usable.
    const heading = element.querySelector('.pwa-home-heading,.page-head,.sls-header,.dlr-head,.wizard-progress,h2');
    const target = heading || element;
    const box = target.getBoundingClientRect();
    if (!box.width || !box.height || box.height > Math.min(320, innerHeight * .5)) return;
    activeAnimations.get(target)?.cancel();
    const distance = direction === 'fade' ? 0 : (direction === 'back' ? -5 : 5);
    const animation = target.animate([
      { opacity: .72, transform: `translate3d(${distance}px, 0, 0)` },
      { opacity: 1, transform: 'translate3d(0, 0, 0)' },
    ], { duration: Math.min(duration, 170), easing: 'cubic-bezier(.2,.75,.25,1)', fill: 'none' });
    activeAnimations.set(target, animation);
    const clear = () => { if (activeAnimations.get(target) === animation) activeAnimations.delete(target); };
    animation.finished.then(clear, clear);
  };
  // Shared by agreement steps. It never changes visibility, focus or data.
  window.CuotaGoMotion = Object.freeze({ reveal, cancel: cancelAnimations });

  const fallbackEntrance = () => {
    if (appeared || !isApp() || reduced.matches || root.classList.contains('show-boot')) return;
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
    // Compatibility guard if an old cached page opted in to a snapshot.
    event.viewTransition?.skipTransition();
    event.viewTransition?.ready?.catch(() => {});
    event.viewTransition?.finished?.catch(() => {});
    requestAnimationFrame(fallbackEntrance);
  });
  window.addEventListener('pageswap', (event) => event.viewTransition?.skipTransition());
  document.addEventListener('pointerdown', cancelAnimations, { passive: true });
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
